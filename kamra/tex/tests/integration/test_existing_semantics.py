"""The contract endpoints answer existing callers exactly as on main (ADR-061, "Existing semantics
kept, the workspace's additions opt-in").

The owner's rule for the Pricing Workspace: it changes the UX only, and no existing pricing
semantics change without the owner's sign-off. An existing caller is one that sends what main
(``6b0102c``) takes: no ``workspace`` flag, no ``data``, no ``parties``. Each test here makes the same
calls with the same data as such a caller and checks main's answer:

* ``preview_price`` of a saved draft and of a published version is main's own computation (its body,
  below), each child still read with ``int()`` (``7.5`` is 7, ``"8"`` is 8, 18 is priced as main
  prices it, 13 children reach the engine), and each night has main's keys only;
* ``price_matrix``, ``get_version`` and ``save_version``'s answer are main's keys with main's values
  (main's bodies, below);
* a blank rule value is still saved as 0 and priced as 0 by ``save_version``;
* board rows naming an unknown room or period, and two rows of one board for the same scope, are
  not reported and still publish; an issue (``validate_version``, ``publish``'s warnings and the
  report it stores) has main's three keys;
* ``validate_version`` of a saved draft is not rate limited;
* a TEX Quote and a reservation's pricing snapshot store main's night keys.

``TestSecurityChanges`` holds the deliberate, reported exceptions (ADR-061): security and tenancy
fixes that apply to every caller and are never opt-in. They fail against main by design:

* a draft's rate plan row of another hotel, or its cancellation or payment policy of another hotel,
  is refused wherever the draft's terms are built (validate, preview, matrix, publish);
* an editor without ``price.view_cost`` is not told what an inherited pricing-policy rule's formula
  (cost) decides, by the live check nor in the report stored at publish.

``TestPolicyMoneyChanges`` holds those of the audit's Part 2C-1 (ADR-067), money-safety fixes for
every caller, never opt-in, that fail against main by design too:

* a refundable rate plan row whose cancellation policy is non-refundable is refused
  (``RATE_PLAN_REFUNDABLE``): main published it and sold it as free cancellation (Y-4).
* a payment or cancellation policy whose fixed amounts are in another currency than the contract's
  is refused (``POLICY_CURRENCY``): main published it and read the amount in the sale's currency
  (Y-3 A).
* a brand-new contract's first draft does not count infants as children for its combination rules
  and ``max_children`` (``infants_count_as_children`` 0, O-2): main's did. Every other draft (from a
  version, a duplicate, a version inserted directly) keeps counting them.

``TestSaleRuleChanges`` holds those of the audit's Part 2C-2 (ADR-068): a promotion no room could use as
saved is refused when a draft of it is saved or activated, never when a live one is archived. They fail
against main by design:

* a discount on the whole booking or its extras other than a percentage or a fixed amount for the
  stay, or a cost-stage offer on them (O-1): main saved it and the engine refused it on every quote.
* a minimum basket without its currency (O-7, D-18): main saved it and compared the minimum in the
  sale's currency, whatever it was sold in.
* a members-only promotion (G-57): main saved it, but no search or quote says the guest is a member,
  so it never applied.
* a second live REPLACE markup of the same scope and priority whose stay dates meet the first's
  (G-53): main activated it and priced with the newer one, silently. Its activation is now refused.

Every other test passes against main's code and against this branch's (both were run; the report of
the change has the output). What the workspace adds is opt-in (``workspace=1``, ``data``,
``parties``) and tested in ``test_pricing_workspace_api``.
"""

import json
from types import SimpleNamespace
from unittest import mock

import frappe
from frappe.utils import get_datetime, getdate, now_datetime

from kamra.tex.api import contracts as api
from kamra.tex.api._util import as_int, doc_dict, parse
from kamra.tex.commercial import context as ctxmod
from kamra.tex.commercial import contracts, revisions
from kamra.tex.pricing import engine
from kamra.tex.pricing import rooms as room_math
from kamra.tex.pricing.model import ChildSpec, PricingError, StayRequest, Unsellable
from kamra.tex.security import scope
from kamra.tex.services import booking, quoting
from kamra.tex.tests.integration import fixtures as fx
from kamra.tex.tests.integration.test_critical_journey import TexTestCase, pick
from kamra.tex.tests.integration.test_pricing_policies import POLICY, child, policy

OTHER_HOTEL = "PW Other Hotel"
EDITOR = "pw-editor@example.com"       # contract.edit without price.view_cost
RM = "pw-revenue@example.com"          # Revenue Manager: contract.edit and price.view_cost
AGENT = "pw-agent@example.com"         # sells only: the catalogue
# a night of an internal quote on main: no running subtotals (those are the price test's, opt-in)
MAIN_NIGHT_KEYS = {"date", "period", "unit", "occupancy", "board", "cost", "cost_net", "sell_contract", "sell", "final"}
MAIN_ISSUE_KEYS = {"level", "code", "message"}
BOARD_CHECKS = {"BOARD_UNKNOWN_ROOM", "BOARD_UNKNOWN_PERIOD", "BOARD_DUPLICATE"}
# the codes whose presence can depend on a policy rule's op or value (validate.HIDEABLE_CODES)
HIDEABLE = {"OCC_POLICY_OVERRIDE_OUTRANKED", "OCC_INFANT_GENERIC", "NEGATIVE_OCCUPANCY_PRICE", "NO_CHILD_RULE"}
BOOKKEEPING = ("name", "parent", "parenttype", "parentfield", "doctype", "idx", "creation", "modified", "owner",
               "modified_by", "docstatus")


def mains_preview(version: str, room_type: str, board: str, check_in: str, check_out: str, adults: int = 2,
                  children=None, rate_plan: str | None = None, market: str | None = None, channel: str = "DIRECT_WEB",
                  currency: str | None = None, sale_at: str | None = None, promo_codes=None):
	"""``preview_price``'s body on main (6b0102c), line for line, without its gate."""
	v = frappe.get_doc("TEX Contract Version", version)
	prop = scope.property_of("TEX Contract Version", version)
	at = get_datetime(sale_at) if sale_at else now_datetime()
	try:
		terms = contracts.load_terms(version) if v.status != "Draft" else contracts.build_terms(v, at=at)
	except frappe.ValidationError as e:
		return {"sellable": False, "reasons": [{"code": "BUILD", "message": str(e)}]}
	kids = tuple(ChildSpec(age=int(a)) for a in (parse(children, []) or []))
	req = StayRequest(property=prop, room_type=room_type, board=board, rate_plan=rate_plan or None,
	                  check_in=getdate(check_in), check_out=getdate(check_out), adults=as_int(adults, 2, lo=1, hi=12),
	                  children=kids, sale_at=at, market=(market or terms.market).upper(), channel=channel,
	                  sell_currency=(currency or terms.currency).upper(),
	                  promo_codes=tuple(parse(promo_codes, []) or ()))
	try:
		ctx = ctxmod.build_context(terms, req)
		q = engine.price_stay(ctx, req)
	except (Unsellable, PricingError) as e:
		return {"sellable": False, "reasons": [{"code": getattr(e, "code", "PRICING_ERROR"), "message": str(e)}]}
	return q.to_dict(internal=True)


def mains_matrix(version: str) -> dict:
	"""``price_matrix``'s body on main (6b0102c), without its gate."""
	v = frappe.get_doc("TEX Contract Version", version)
	terms = contracts.load_terms(version) if v.status != "Draft" else contracts.build_terms(v)
	out = []
	for rt in sorted(terms.rooms):
		row = {"room_type": rt, "name": terms.rooms[rt].name, "cells": {}}
		for p in terms.periods:
			try:
				row["cells"][p.code] = str(room_math.room_unit(terms, rt, p))
			except Unsellable as u:
				row["cells"][p.code] = None
				row.setdefault("errors", {})[p.code] = u.message
		out.append(row)
	return {"periods": [{"code": p.code, "name": p.name, "start": str(p.start), "end": str(p.end)}
	                    for p in terms.periods], "rooms": out, "basis": terms.basis.value, "currency": terms.currency}


def mains_get_version(name: str) -> dict:
	"""``get_version``'s body on main (6b0102c), without its gate; its catalogue for an agent."""
	v = frappe.get_doc("TEX Contract Version", name)
	prop = scope.property_of("TEX Contract Version", name)
	if not api._sees_cost(prop):
		c = frappe.db.get_value("TEX Contract", v.contract, ["name", "property", "contract_code", "contract_name",
		                                                     "market", "contract_currency", "status"], as_dict=True)
		return {
			"name": v.name, "contract": v.contract, "version_no": v.version_no, "status": v.status,
			"rooms": [{"room_type": r.room_type} for r in v.rooms],
			"boards": [{"board": b.board} for b in v.boards],
			"rate_plans": [{"rate_plan": r.rate_plan, "refundable": r.refundable} for r in v.rate_plans],
			"room_types": frappe.get_all("Room Type", filters={"property": prop, "disabled": 0},
			                             fields=["name", "room_type_name", "adults_capacity", "children_capacity"],
			                             order_by="room_type_name"),
			"rate_plan_options": frappe.get_all("Rate Plan", filters={"property": prop, "disabled": 0},
			                                    fields=["name", "rate_plan_name", "code", "tex_refundable"]),
			"contract_doc": dict(c or {}), "editable": False, "cost_hidden": True,
		}
	out = doc_dict(v, exclude=("payload",))
	out["validation_report"] = json.loads(v.validation_report) if v.validation_report else None
	out["editable"] = v.status == "Draft" and scope.has_capability("contract.edit", prop)
	c = frappe.get_doc("TEX Contract", v.contract)
	out["contract_doc"] = {f: c.get(f) for f in ("name", "property", "contract_code", "contract_name", "market",
	                                             "pricing_basis", "contract_currency", "status")}
	out.update(api._selling(v, c))
	out["room_types"] = frappe.get_all("Room Type", filters={"property": c.property, "disabled": 0},
	                                   fields=["name", "room_type_name", "adults_capacity", "children_capacity",
	                                           "max_total_occupants", "base_occupancy"], order_by="room_type_name")
	out["rate_plan_options"] = frappe.get_all("Rate Plan", filters={"property": c.property, "disabled": 0},
	                                          fields=["name", "rate_plan_name", "code", "tex_refundable"])
	return out


def tables(version: str) -> dict:
	"""The draft's tables as a caller posts them back to ``save_version``."""
	doc = api.get_version(version)
	return {t: [{k: v for k, v in r.items() if k not in BOOKKEEPING} for r in doc[t]] for t in api.VERSION_TABLES}


def find(rows: list[dict], **match) -> dict:
	return next(r for r in rows if all(r.get(k) == v for k, v in match.items()))


def as_json(data) -> str:
	return json.dumps(data, default=str)


def plain(data):
	"""What the caller receives (JSON)."""
	return json.loads(as_json(data))


def without_row_names(q):
	"""A quote with each rule's row name (``rule_id``) blanked: a save replaces a table's rows, so
	the same rule has a new row name after every save."""
	if isinstance(q, dict):
		return {k: (None if k == "rule_id" else without_row_names(v)) for k, v in q.items()}
	if isinstance(q, list):
		return [without_row_names(v) for v in q]
	return q


class ExistingCallerCase(TexTestCase):
	def setUp(self):
		super().setUp()
		self.std, self.dlx = self.f["room_types"]["STD"], self.f["room_types"]["DLX"]
		self.flex, self.nrf = self.f["rate_plans"]["FLEX"], self.f["rate_plans"]["NRF"]
		self.v = fx.create_contract(self.f, code="MAIN-PARITY", publish=False)["version"]
		self.sale_at = str(now_datetime().replace(microsecond=0))

	def args(self, **kw) -> dict:
		return {"room_type": self.std, "board": "AI", "check_in": str(fx.d(6, 10)), "check_out": str(fx.d(7, 2)),
		        "adults": 2, "rate_plan": self.flex, "market": "DE", "sale_at": self.sale_at, **kw}

	def assert_mains(self, version: str, **kw) -> dict:
		"""``preview_price`` answers what main's body answers, with main's night keys."""
		got = api.preview_price(version, **self.args(**kw))
		self.assertEqual(plain(got), plain(mains_preview(version, **self.args(**kw))))
		for night in got.get("nights") or []:
			self.assertEqual(set(night), MAIN_NIGHT_KEYS)
		return got

	def as_user(self, user: str) -> None:
		frappe.set_user(user)  # nosemgrep: frappe-setuser -- test context switch
		scope.clear_cache()

	def users(self) -> None:
		"""An editor without cost, a Revenue Manager and an agent at the test hotel."""
		fx.ensure("TEX Permission Profile", {"profile_name": "PW Contract Editor"},
		          {"profile_name": "PW Contract Editor",
		           "capabilities": [{"capability": "price.view"}, {"capability": "contract.edit"}]})
		for user, profile in ((EDITOR, "PW Contract Editor"), (RM, "Revenue Manager"), (AGENT, "Reservations Agent")):
			fx.ensure_user(user, ["Revenue Manager"])
			fx.ensure("TEX Access Grant", {"user": user, "property": fx.PROPERTY},
			          {"user": user, "scope_level": "Hotel", "property": fx.PROPERTY, "permission_profile": profile})
		scope.clear_cache()


class TestPreviewAsOnMain(ExistingCallerCase):
	def test_children_are_read_as_main_reads_them(self):
		pub = fx.create_contract(self.f, code="MAIN-PARITY-PUB")["version"]
		for version in (self.v, pub):
			for kids in ([], [8], ["8"], [8.0], json.dumps([8, 1]), [7.5], [11.9], [4, 10], [1, 11, 5], [18], [17],
			             [5] * 13, None):
				with self.subTest(version=version, children=kids):
					q = self.assert_mains(version, children=kids)
					if kids in ([8], ["8"], [8.0]):
						self.assertTrue(q["sellable"], q.get("reasons"))
			with self.subTest(version=version, children="7.5 is 7"):
				self.assertEqual(api.preview_price(version, **self.args(children=[7.5])),
				                 api.preview_price(version, **self.args(children=[7])))
			for bad in (["seven"], [None]):                  # main's int() refuses them
				with self.subTest(version=version, children=bad), self.assertRaises((ValueError, TypeError)):
					api.preview_price(version, **self.args(children=bad))

	def test_every_room_board_and_plan_of_a_draft_and_a_published_version(self):
		pub = fx.create_contract(self.f, code="MAIN-PARITY-PUB2")["version"]
		for version in (self.v, pub):
			for room in (self.std, self.dlx):
				for board in ("AI", "UAI"):
					for plan in (self.flex, self.nrf):
						with self.subTest(version=version, room=room, board=board, plan=plan):
							self.assert_mains(version, room_type=room, board=board, rate_plan=plan, children=[8])


class TestReadsAsOnMain(ExistingCallerCase):
	def test_the_matrix_is_mains(self):
		pub = fx.create_contract(self.f, code="MAIN-PARITY-MX")["version"]
		for version in (self.v, pub):
			for kw in ({}, {"adults": 3}):
				with self.subTest(version=version, **kw):
					self.assertEqual(plain(api.price_matrix(version, **kw)), plain(mains_matrix(version)))

	def test_a_version_reads_as_on_main(self):
		self.users()
		pub = fx.create_contract(self.f, code="MAIN-PARITY-GV")["version"]
		for user in ("Administrator", RM, AGENT):
			self.as_user(user)
			for version in (self.v, pub):
				with self.subTest(user=user, version=version):
					self.assertEqual(plain(api.get_version(version)), plain(mains_get_version(version)))

	def test_a_save_answers_as_on_main(self):
		got = api.save_version(self.v, as_json(tables(self.v)))
		self.assertEqual(plain(got), plain(mains_get_version(self.v)))


class TestSaveAsOnMain(ExistingCallerCase):
	def test_a_blank_value_is_saved_as_0_and_priced_as_0(self):
		cases = (
			("period_rates", dict(room_type=self.std, period_code="LOW"), {"value": ""}),
			("occupancy_rules", dict(target="CHILD", age_band="CHA"), {"value": None}),
			("boards", dict(board="UAI"), {"adult_amount": ""}),
			("periods", dict(period_code="LOW"), {"adjustment_op": "MULTIPLY", "adjustment_value": ""}),
			("rate_plans", dict(rate_plan=self.flex), {"op": "MULTIPLY", "value": None}),
		)
		original = as_json(tables(self.v))
		for table, match, blank in cases:
			with self.subTest(table=table):
				data = json.loads(original)
				find(data[table], **match).update(blank)
				api.save_version(self.v, as_json(data))                    # accepted, as on main
				stored = tables(self.v)
				blank_quote = self.assert_mains(self.v, board="UAI", children=[4])
				zero = {k: (0 if k in ("value", "adult_amount", "adjustment_value") else v) for k, v in blank.items()}
				find(data[table], **match).update(zero)
				api.save_version(self.v, as_json(data))
				self.assertEqual(tables(self.v), stored)                   # stored as 0
				zero_quote = self.assert_mains(self.v, board="UAI", children=[4])
				self.assertEqual(without_row_names(plain(zero_quote)), without_row_names(plain(blank_quote)))

	def test_unknown_and_twin_board_rows_publish_as_on_main(self):
		data = tables(self.v)
		supplement = {"board": "UAI", "op": "ADD", "child_percent": 50}
		data["boards"] += [{**supplement, "adult_amount": 15, "period_code": "NOPE"},
		                   {**supplement, "adult_amount": 16, "room_type": self.dlx},
		                   {**supplement, "adult_amount": 25}]                   # a twin of the UAI row
		data["rooms"] = [r for r in data["rooms"] if r["room_type"] != self.dlx]
		data["period_rates"] = [r for r in data["period_rates"] if r["room_type"] != self.dlx]
		api.save_version(self.v, as_json(data))
		report = api.validate_version(self.v)
		self.assertTrue(report["ok"], report)
		self.assertEqual([i["code"] for i in report["issues"] if i["code"] in BOARD_CHECKS], [])
		self.assertEqual([set(i) for i in report["issues"]], [MAIN_ISSUE_KEYS] * len(report["issues"]))
		before = self.assert_mains(self.v, board="UAI", children=[8])
		published = contracts.publish(self.v)
		self.assertEqual(frappe.db.get_value("TEX Contract Version", published["version"], "status"), "Published")
		self.assertEqual(published["warnings"], report["issues"])
		stored = json.loads(frappe.db.get_value("TEX Contract Version", published["version"], "validation_report"))
		self.assertEqual(stored, report["issues"])
		after = self.assert_mains(self.v, board="UAI", children=[8])
		self.assertEqual(after["totals"], before["totals"])

	def test_issues_have_mains_keys(self):
		"""A draft with warnings (a child band no rule prices: the sweep's NO_CHILD_RULE, which the
		workspace anchors by a ``ref``): the live check, publish's warnings and the stored report give
		each issue as main did (level, code, message)."""
		data = tables(self.v)
		data["age_bands"].append({"band_code": "TEE", "label": "Teen", "from_age": 12, "to_age": 17.99})
		api.save_version(self.v, as_json(data))
		report = api.validate_version(self.v)
		self.assertTrue(report["ok"], report)
		self.assertIn("NO_CHILD_RULE", {i["code"] for i in report["issues"]})
		published = contracts.publish(self.v)
		stored = json.loads(frappe.db.get_value("TEX Contract Version", published["version"], "validation_report"))
		for issues in (report["issues"], published["warnings"], stored):
			self.assertEqual([set(i) for i in issues], [MAIN_ISSUE_KEYS] * len(issues))
		self.assertEqual(stored, report["issues"])

	def test_validating_a_saved_draft_is_not_rate_limited(self):
		limits = {"validate": (1, 1)} if hasattr(api, "HEAVY_LIMITS") else {}
		had, saved = hasattr(frappe.local, "request"), getattr(frappe.local, "request", None)
		try:
			frappe.local.request = SimpleNamespace(method="GET")             # as a web request
			with mock.patch.dict(getattr(api, "HEAVY_LIMITS", {}), limits):
				for _ in range(3):
					self.assertTrue(api.validate_version(self.v)["ok"])
		finally:
			if had:
				frappe.local.request = saved
			else:
				del frappe.local.request


class TestStoredQuotesAsOnMain(TexTestCase):
	def test_a_quote_and_a_reservation_snapshot_keep_mains_nights(self):
		fx.create_contract(self.f, code="MAIN-PARITY-Q")
		ci, co = fx.d(6, 10), fx.d(6, 12)
		res = quoting.search(properties=[fx.PROPERTY], check_in=ci, check_out=co, rooms=[{"adults": 2, "children": [8]}],
		                     market="DE", channel="DIRECT_WEB", currency="EUR")
		q = quoting.create_quote(pick(res["properties"][0])["rooms"][0]["offer_key"])
		stored = json.loads(frappe.db.get_value("TEX Quote", q["quote_id"], "result_json"))
		self.assertTrue(stored["nights"])
		self.assertEqual([set(n) for n in stored["nights"]], [MAIN_NIGHT_KEYS] * len(stored["nights"]))
		b = booking.create_booking(quote_ids=[q["quote_id"]], guest={"first_name": "M", "last_name": "P",
		                                                              "email": "main-parity@example.com"},
		                           payment_method="Card", confirm_without_payment=True, idempotency_key="main-parity")
		snap = json.loads(frappe.db.get_value("Reservation", b["rooms"][0]["reservation"], "tex_pricing_snapshot"))
		nights = snap.get("nights") or snap.get("quote", {}).get("nights")
		self.assertTrue(nights)
		self.assertEqual([set(n) for n in nights], [MAIN_NIGHT_KEYS] * len(nights))


class TestSecurityChanges(ExistingCallerCase):
	"""The deliberate differences from main for existing callers (ADR-061): security and tenancy
	fixes, enforced for every caller and never opt-in. These fail against main by design."""

	def test_another_hotels_rate_plan_or_terms_are_refused_for_every_caller(self):
		"""Main built a saved draft's terms without checking the hotel of a rate plan row or of its
		cancellation or payment policy: another hotel's plan and terms were priced, validated, shown
		in the matrix and published. They are refused wherever the terms are built; saving the row is
		accepted as before (a save builds no terms); a policy of no hotel is shared."""
		if not frappe.db.exists("Property", OTHER_HOTEL):
			frappe.get_doc({"doctype": "Property", "property_name": OTHER_HOTEL, "city": "Side", "country": "Turkey",
			                "currency": "EUR", "tex_hotel_group": self.f["group"]}).insert(ignore_permissions=True)
		plan = fx.ensure("Rate Plan", {"property": OTHER_HOTEL, "code": "PWX"},
		                 {"property": OTHER_HOTEL, "code": "PWX", "rate_plan_name": "PW other plan",
		                  "modifier_type": "Percent", "modifier_value": 0})
		cxl = fx.ensure("TEX Cancellation Policy", {"property": OTHER_HOTEL, "policy_name": "PW other cxl"},
		                {"property": OTHER_HOTEL, "policy_name": "PW other cxl", "refundable": 1})
		pay = fx.ensure("TEX Payment Policy", {"property": OTHER_HOTEL, "policy_name": "PW other pay"},
		                {"property": OTHER_HOTEL, "policy_name": "PW other pay", "deposit_type": "PERCENT",
		                 "deposit_value": 45})
		shared = fx.ensure("TEX Payment Policy", {"property": "", "policy_name": "PW shared pay"},
		                   {"policy_name": "PW shared pay", "deposit_type": "FULL"})
		original = as_json(tables(self.v))
		cases = (("rate plan", lambda d: d["rate_plans"].append({"rate_plan": plan, "refundable": 1}), plan),
		         ("cancellation policy",
		          lambda d: find(d["rate_plans"], rate_plan=self.flex).update(cancellation_policy=cxl), cxl),
		         ("payment policy",
		          lambda d: find(d["rate_plans"], rate_plan=self.flex).update(payment_policy=pay), pay))
		for what, change, name in cases:
			with self.subTest(what=what):
				data = json.loads(original)
				change(data)
				api.save_version(self.v, as_json(data))                    # saved, as on main
				report = api.validate_version(self.v)
				self.assertFalse(report["ok"])
				self.assertEqual([(i["code"], name in i["message"], "belongs to another hotel" in i["message"])
				                  for i in report["issues"]], [("BUILD", True, True)])
				q = api.preview_price(self.v, **self.args())
				self.assertEqual((q["sellable"], [r["code"] for r in q["reasons"]]), (False, ["BUILD"]))
				with self.assertRaises(frappe.ValidationError):
					api.price_matrix(self.v)
				with self.assertRaises(frappe.ValidationError) as cm:
					contracts.publish(self.v)
				self.assertIn("belongs to another hotel", str(cm.exception))
				self.assertEqual(frappe.db.get_value("TEX Contract Version", self.v, "status"), "Draft")
		data = json.loads(original)
		find(data["rate_plans"], rate_plan=self.flex)["payment_policy"] = shared
		api.save_version(self.v, as_json(data))
		self.assertTrue(api.validate_version(self.v)["ok"])
		self.assertTrue(self.assert_mains(self.v)["sellable"])

	def policy_override(self) -> None:
		"""A hotel pricing policy's infant override that the draft's own INF rule outranks (the live
		check's OCC_POLICY_OVERRIDE_OUTRANKED); only this test's policies are on sale (archived inside
		the test transaction, rolled back)."""
		for name in frappe.get_all(POLICY, filters={"tex_status": ("in", ["Active", "Superseded"])}, pluck="name"):
			revisions.archive(POLICY, name)
		policy("PW Hotel Override", property=fx.PROPERTY, rules=[child("INF", "FIXED", 15, is_override=1)])

	def test_an_editor_without_cost_is_not_told_what_a_policy_formula_decides(self):
		"""A pricing policy's formulas are cost (G-11). Main's live check told an editor without
		``price.view_cost`` whether the draft's own rule differs from a policy override's value (an
		equality oracle, and the override's scope). Now that editor's check leaves out each issue whose
		presence depends on an inherited rule's op or value; who sees cost gets main's report."""
		self.users()
		self.policy_override()
		self.as_user(RM)
		full = api.validate_version(self.v)
		self.assertIn("OCC_POLICY_OVERRIDE_OUTRANKED", {i["code"] for i in full["issues"]})
		self.as_user(EDITOR)
		mine = api.validate_version(self.v)
		self.assertEqual(mine["issues"], [i for i in full["issues"] if i["code"] != "OCC_POLICY_OVERRIDE_OUTRANKED"])
		self.assertEqual(mine["ok"], full["ok"])

	def test_the_report_stored_at_publish_is_filtered_the_same_way(self):
		"""``get_version`` gave an editor without cost the report stored at publish as stored. It is
		now given as the live check gives it; a stored row that does not say what it is about (every
		report an existing caller's publish stores has main's three keys) is left out when its code
		can depend on a policy rule. The rest of the answer is main's; who sees cost gets main's."""
		self.users()
		self.policy_override()
		contracts.publish(self.v)
		stored = json.loads(frappe.db.get_value("TEX Contract Version", self.v, "validation_report"))
		self.assertIn("OCC_POLICY_OVERRIDE_OUTRANKED", {i["code"] for i in stored})
		self.as_user(RM)
		self.assertEqual(plain(api.get_version(self.v)), plain(mains_get_version(self.v)))
		self.as_user(EDITOR)
		got, main = plain(api.get_version(self.v)), plain(mains_get_version(self.v))
		self.assertEqual(got["validation_report"], [i for i in stored if i["code"] not in HIDEABLE])
		self.assertEqual({**got, "validation_report": None}, {**main, "validation_report": None})


class TestPolicyMoneyChanges(ExistingCallerCase):
	"""The deliberate differences from main of the audit's Part 2C-1 (ADR-067): money-safety fixes,
	enforced for every caller and never opt-in. These fail against main by design."""

	def test_a_refundable_row_on_a_non_refundable_policy_is_refused(self):
		"""Y-4: main validated and published a refundable rate plan row whose cancellation policy is
		non-refundable, and sold it as free cancellation. Now it is an ERROR (``RATE_PLAN_REFUNDABLE``,
		an issue in main's shape) and the publish is refused; the row marked non-refundable is main's."""
		nrf_cxl = frappe.db.get_value("TEX Cancellation Policy", {"property": fx.PROPERTY,
		                                                         "policy_name": "Non-refundable"})
		data = tables(self.v)
		find(data["rate_plans"], rate_plan=self.flex)["cancellation_policy"] = nrf_cxl
		api.save_version(self.v, as_json(data))
		report = api.validate_version(self.v)
		self.assertFalse(report["ok"])
		self.assertEqual([(i["level"], i["code"]) for i in report["issues"]], [("ERROR", "RATE_PLAN_REFUNDABLE")])
		self.assertTrue(all(set(i) == MAIN_ISSUE_KEYS for i in report["issues"]))
		with self.assertRaises(frappe.ValidationError):
			contracts.publish(self.v)
		self.assertEqual(frappe.db.get_value("TEX Contract Version", self.v, "status"), "Draft")
		find(data["rate_plans"], rate_plan=self.flex)["refundable"] = 0
		api.save_version(self.v, as_json(data))
		self.assertTrue(api.validate_version(self.v)["ok"])
		self.assertEqual(contracts.publish(self.v)["version"], self.v)

	def test_a_fixed_policy_in_another_currency_is_refused(self):
		"""Y-3 A: main published a policy's fixed deposit whatever its currency and took it in the sale's
		currency. A fixed policy in another currency than the contract's is now an ERROR
		(``POLICY_CURRENCY``, in main's shape) and not published; without a currency it is the contract's
		and publishes as before."""
		pay = fx.ensure("TEX Payment Policy", {"property": fx.PROPERTY, "policy_name": "PW 100 TRY"},
		                {"property": fx.PROPERTY, "policy_name": "PW 100 TRY", "deposit_type": "FIXED",
		                 "deposit_value": 100, "currency": "TRY"})
		data = tables(self.v)
		find(data["rate_plans"], rate_plan=self.flex)["payment_policy"] = pay
		api.save_version(self.v, as_json(data))
		report = api.validate_version(self.v)
		self.assertEqual([(i["level"], i["code"]) for i in report["issues"]], [("ERROR", "POLICY_CURRENCY")])
		self.assertTrue(all(set(i) == MAIN_ISSUE_KEYS for i in report["issues"]))
		with self.assertRaises(frappe.ValidationError):
			contracts.publish(self.v)
		frappe.db.set_value("TEX Payment Policy", pay, "currency", None)
		self.assertTrue(api.validate_version(self.v)["ok"])
		self.assertEqual(contracts.publish(self.v)["version"], self.v)

	def test_a_new_contracts_first_draft_does_not_count_infants_as_children(self):
		"""O-2 (D-2): main's ``save_contract`` made a new contract's first draft in which an infant was a
		child for the combination rules (1A + 8y + infant priced as 1A+2C). That draft now says infants
		are not children, so the infant leaves the 8-year-old's price alone; switched back on, it prices as
		main did."""
		out = api.save_contract(data={"property": fx.PROPERTY, "contract_code": "PW-O2", "contract_name": "O2",
		                              "market": "DE", "contract_currency": "EUR", "pricing_basis": "PERSON"})
		draft = frappe.db.get_value("TEX Contract Version", {"contract": out["contract"]["name"]}, "name")
		self.assertEqual(frappe.db.get_value("TEX Contract Version", draft, "infants_count_as_children"), 0)
		data = tables(self.v)
		api.save_version(draft, as_json(data))                       # the fixture's rooms, rates and rules
		kids = {"children": json.dumps([8, 1]), "check_out": str(fx.d(6, 11))}
		new = api.preview_price(draft, **self.args(**kids, adults=1))
		self.assertEqual(new["totals"]["accommodation"], api.preview_price(draft, **self.args(
			children=json.dumps([8]), check_out=str(fx.d(6, 11)), adults=1))["totals"]["accommodation"])
		api.save_version(draft, as_json({"infants_count_as_children": 1}))
		self.assertEqual(plain(self.assert_mains(draft, **kids, adults=1))["totals"]["accommodation"], "150.00")


class TestSaleRuleChanges(TexTestCase):
	"""The deliberate differences from main of the audit's Part 2C-2 (ADR-068): a promotion no room
	could use as saved is refused on a draft's save and activation. These fail against main by
	design; a record already live is never refused for them and stays archivable."""

	def promotion(self, **kw) -> dict:
		from kamra.tex.api import policies

		return policies.save_record("TEX Promotion", {"promotion_name": "2C-2", "property": fx.PROPERTY,
		                                              "value_type": "PERCENT", "value": 10, **kw})

	def test_a_discount_no_room_could_use_is_refused(self):
		"""O-1: main saved a multiplier on the whole booking and a cost-stage offer on the extras; every
		quote then refused it (``MULTIPLIER is not supported on TOTAL``, or a cost discount taken off the
		accommodation). Now the save is refused; a percentage on them saves as on main."""
		for kw in ({"value_type": "MULTIPLIER", "value": "0.9", "applies_to": "TOTAL"},
		           {"stage": "COST", "applies_to": "EXTRAS"}):
			with self.subTest(**kw), self.assertRaises(frappe.ValidationError):
				self.promotion(**kw)
		self.assertEqual(self.promotion(applies_to="TOTAL")["applies_to"], "TOTAL")

	def test_a_minimum_basket_without_its_currency_is_refused(self):
		"""O-7 (D-18): main saved a 1,000 minimum without a currency and read it in each sale's currency
		(1,000 EUR or 1,000 TRY). Now the save asks for the currency; with it, it saves as on main."""
		with self.assertRaises(frappe.ValidationError):
			self.promotion(min_basket=1000)
		self.assertEqual(self.promotion(min_basket=1000, currency="EUR")["currency"], "EUR")

	def test_a_members_only_promotion_is_refused(self):
		"""G-57: main saved a members-only promotion that no sale could apply (no caller passes
		``member``). Now the save is refused; without it, it saves as on main."""
		with self.assertRaises(frappe.ValidationError):
			self.promotion(member_only=1)
		self.assertEqual(self.promotion(member_only=0)["member_only"], 0)

	def test_an_equal_markup_is_not_activated(self):
		"""G-53: main activated a second DE markup of the hotel at the same priority and priced with the
		newer. Now its activation is refused, naming the first; at another priority it activates."""
		from kamra.tex.api import policies

		def markup(**kw) -> str:
			return policies.save_record("TEX Markup Rule", {"label": "2C-2", "property": fx.PROPERTY, "market": "DE",
			                                                "op": "ADJUST_PERCENT", "value": 7, **kw})["name"]

		first = markup()
		revisions.activate("TEX Markup Rule", first)
		second = markup(value=9)
		with self.assertRaises(frappe.ValidationError):
			revisions.activate("TEX Markup Rule", second)
		revisions.activate("TEX Markup Rule", markup(value=9, priority=1))
