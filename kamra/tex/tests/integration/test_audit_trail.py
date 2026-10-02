"""G-74 (R-54, ADR-053): the audit trail says what changed, for which hotels, and how it arrived.

The 2026-09-23 audit found: draft contract edits were not audited and a publish recorded only
the payload hash; ARI bulk edits recorded no old values; payment rules were audited only on
some API paths; group and enterprise grant events carried no hotel, so only platform
administrators saw them; every payment outcome was recorded as coming from a "Webhook".
Each class below reproduces one of these first.
"""

import json
from types import SimpleNamespace
from unittest import mock

import frappe
from frappe.utils import add_days, now_datetime, nowdate

from kamra.tex.api import admin, public
from kamra.tex.api import contracts as contracts_api
from kamra.tex.api import payments as pay_api
from kamra.tex.api import policies as policies_api
from kamra.tex.commercial import contracts, grid
from kamra.tex.payments import service as pay
from kamra.tex.security import grants, scope
from kamra.tex.tests.integration import fixtures as fx
from kamra.tex.tests.integration.test_commercial_flows import guest_books, setup_site_and_payments
from kamra.tex.tests.integration.test_critical_journey import TexTestCase
from kamra.tex.tests.integration.test_security_regressions import FakeIyzico, _return_url

OTHER_HOTEL = "TEX Audit Other Hotel"
OTHER_GROUP = "TEST Audit Other Group"
OTHER_ENTERPRISE = "TEST Audit Other Enterprise"
# never stored anywhere readable: the audit may say a secret was set or changed, never what it is
SECRETS = ("ak-G74-never-logged", "sk-G74-never-logged", "sk-G74-rotated-never-logged")


def as_user(user: str) -> None:
	frappe.set_user(user)  # nosemgrep: frappe-setuser -- the test acts as each user in turn
	scope.clear_cache()


def events(action: str, reference_name: str | None = None, property: str | None = None) -> list[dict]:
	filters: dict = {"action": action}
	if reference_name:
		filters["reference_name"] = reference_name
	if property:
		filters["property"] = property
	rows = frappe.get_all("TEX Audit Event", filters=filters,
	                      fields=["name", "action", "source", "property", "reference_name", "reason", "old_value",
	                              "new_value"], order_by="creation asc, name asc")
	for r in rows:
		r["old"] = json.loads(r.pop("old_value") or "null")
		r["new"] = json.loads(r.pop("new_value") or "null")
	return rows


def last_event(action: str, reference_name: str | None = None, property: str | None = None) -> dict:
	rows = events(action, reference_name, property)
	if not rows:
		raise AssertionError(f"no {action} event for {reference_name or property}")
	return rows[-1]


def scope_hotels(event: str) -> set[str]:
	return set(frappe.get_all("TEX Audit Scope", filters={"event": event}, pluck="property"))


class AuditCase(TexTestCase):
	def setUp(self):
		super().setUp()
		frappe.flags.tex_source = None           # a flag another test module left behind


# ─── group / enterprise grant scope ──────────────────────────────────────


class TestGrantScope(AuditCase):
	"""A group or enterprise grant gives access to hotels: its events name them, so each hotel's
	administrators see who was given access to their hotel, and only that."""

	def setUp(self):
		super().setUp()
		ent2 = fx.ensure("TEX Enterprise", {"enterprise_name": OTHER_ENTERPRISE}, {"enterprise_name": OTHER_ENTERPRISE})
		self.group2 = fx.ensure("TEX Hotel Group", {"group_name": OTHER_GROUP},
		                        {"group_name": OTHER_GROUP, "enterprise": ent2})
		if not frappe.db.exists("Property", OTHER_HOTEL):
			frappe.get_doc({"doctype": "Property", "property_name": OTHER_HOTEL, "city": "Fethiye", "country": "Turkey",
			                "currency": "EUR", "tex_hotel_group": self.group2}).insert(ignore_permissions=True)
		self.gm = fx.ensure_user("g74-gm@example.com", ["Hotel Admin"])
		fx.ensure("TEX Access Grant", {"user": self.gm, "property": fx.PROPERTY},
		          {"user": self.gm, "scope_level": "Hotel", "property": fx.PROPERTY,
		           "permission_profile": "Hotel Admin"})
		self.mine = fx.ensure_user("g74-group-agent@example.com", ["Call Center Agent"])
		self.theirs = fx.ensure_user("g74-other-agent@example.com", ["Call Center Agent"])
		self.wide = fx.ensure_user("g74-enterprise-agent@example.com", ["Call Center Agent"])
		scope.clear_cache()

	def grant(self, user: str, level: str, **where) -> str:
		as_user("Administrator")
		return frappe.get_doc({"doctype": "TEX Access Grant", "user": user, "scope_level": level,
		                       "permission_profile": "Reservations Agent", **where}).insert(ignore_permissions=True).name

	def test_group_and_enterprise_grant_events_name_their_hotels(self):
		mine = self.grant(self.mine, "Hotel Group", hotel_group=self.f["group"])
		theirs = self.grant(self.theirs, "Hotel Group", hotel_group=self.group2)
		wide = self.grant(self.wide, "Enterprise", enterprise=self.f["enterprise"])

		e = last_event("grant.update", mine)
		self.assertIsNone(e["property"])                                 # not one hotel's event...
		self.assertEqual(frappe.db.get_value("TEX Audit Event", e["name"], "hotel_group"), self.f["group"])
		self.assertIn(fx.PROPERTY, scope_hotels(e["name"]))               # ...but it reaches this hotel
		self.assertNotIn(OTHER_HOTEL, scope_hotels(e["name"]))
		self.assertEqual(scope_hotels(last_event("grant.update", theirs)["name"]), {OTHER_HOTEL})
		e = last_event("grant.update", wide)
		self.assertEqual(frappe.db.get_value("TEX Audit Event", e["name"], "enterprise"), self.f["enterprise"])
		self.assertIn(fx.PROPERTY, scope_hotels(e["name"]))

		# moved to another group: the hotels it left and the hotels it reaches are both told
		doc = frappe.get_doc("TEX Access Grant", mine)
		doc.hotel_group = self.group2
		doc.save(ignore_permissions=True)
		self.assertLessEqual({fx.PROPERTY, OTHER_HOTEL}, scope_hotels(last_event("grant.update", mine)["name"]))
		frappe.delete_doc("TEX Access Grant", theirs, ignore_permissions=True)
		self.assertEqual(scope_hotels(last_event("grant.delete", theirs)["name"]), {OTHER_HOTEL})

	def test_a_hotel_admin_sees_group_grant_events_of_their_hotel_only(self):
		mine = self.grant(self.mine, "Hotel Group", hotel_group=self.f["group"])
		theirs = self.grant(self.theirs, "Hotel Group", hotel_group=self.group2)
		wide = self.grant(self.wide, "Enterprise", enterprise=self.f["enterprise"])
		ev_mine, ev_theirs = last_event("grant.update", mine)["name"], last_event("grant.update", theirs)["name"]

		as_user(self.gm)
		rows = admin.audit_log(property=fx.PROPERTY, reference_doctype="TEX Access Grant")
		seen = {r["reference_name"] for r in rows}
		self.assertLessEqual({mine, wide}, seen)
		self.assertNotIn(theirs, seen)
		row = next(r for r in rows if r["reference_name"] == mine)
		self.assertEqual(row["hotels"], [fx.PROPERTY])                   # other hotels only as a count
		self.assertEqual(row["hotel_group"], self.f["group"])

		# Desk / REST follow the same scope
		listed = set(frappe.get_list("TEX Audit Event", filters={"reference_doctype": "TEX Access Grant"},
		                             pluck="reference_name"))
		self.assertIn(mine, listed)
		self.assertNotIn(theirs, listed)
		self.assertTrue(frappe.has_permission("TEX Audit Event", "read", doc=ev_mine, user=self.gm))
		self.assertFalse(frappe.has_permission("TEX Audit Event", "read", doc=ev_theirs, user=self.gm))
		self.assertEqual(set(frappe.get_list("TEX Audit Scope", filters={"event": ev_mine}, pluck="property")),
		                 {fx.PROPERTY})
		self.assertFalse(frappe.get_list("TEX Audit Scope", filters={"event": ev_theirs}, pluck="property"))

	def test_an_ended_group_grant_is_audited_with_its_hotels(self):
		g = self.grant(self.mine, "Hotel Group", hotel_group=self.f["group"], valid_until=nowdate())
		frappe.db.set_value("TEX Access Grant", g, "valid_until", add_days(nowdate(), -1))
		grants.remove_expired_grants()
		e = last_event("grant.expired", g)
		self.assertEqual(e["source"], "Scheduler")
		self.assertEqual(frappe.db.get_value("TEX Audit Event", e["name"], "hotel_group"), self.f["group"])
		self.assertIn(fx.PROPERTY, scope_hotels(e["name"]))


# ─── contract drafts and publishing ──────────────────────────────────────


class TestContractAudit(AuditCase):
	"""Every saved draft edit is on record as old → new (rows by their natural key); a publish
	says what it froze and how it differs from the version that sold before."""

	TABLES = ("rooms", "periods", "period_rates", "age_bands", "occupancy_rules", "boards", "rate_plans", "offers")

	def setUp(self):
		super().setUp()
		self.c = fx.create_contract(self.f, code="AUD")
		self.v2 = contracts.new_draft(self.c["contract"])
		self.std, self.dlx = self.f["room_types"]["STD"], self.f["room_types"]["DLX"]

	def draft(self) -> dict:
		v = contracts_api.get_version(self.v2)
		return {t: v[t] for t in self.TABLES}

	def uplift(self) -> dict:
		data = self.draft()
		for r in data["period_rates"]:
			if r["room_type"] == self.std and r["period_code"] == "LOW":
				r["value"] = 110
		data["boards"].append({"board": "HB", "op": "ADD", "adult_amount": 15, "child_percent": 50})
		data["prices_include_tax"] = 1
		data["change_note"] = "summer uplift"
		return data

	def test_a_draft_save_records_what_changed(self):
		data = self.uplift()
		contracts_api.save_version(self.v2, data)
		e = last_event("contract.version.save", self.v2)
		self.assertEqual(e["property"], fx.PROPERTY)
		self.assertEqual((e["old"]["prices_include_tax"], e["new"]["prices_include_tax"]), (False, True))
		self.assertEqual((e["old"]["change_note"], e["new"]["change_note"]), (None, "summer uplift"))
		rates = e["new"]["collections"]["period_rates"]
		self.assertEqual(rates["changed"], {f"{self.std} · LOW": {"value": ["100", "110"]}})
		self.assertEqual(rates["totals"], {"added": 0, "removed": 0, "changed": 1})
		self.assertEqual(rates["count"], [3, 3])
		self.assertEqual(e["new"]["collections"]["boards"]["added"], ["HB"])
		self.assertNotIn("rooms", e["new"]["collections"])               # untouched tables are not repeated
		n = len(events("contract.version.save", self.v2))
		again = {**self.draft(), "prices_include_tax": 1, "change_note": "summer uplift"}
		contracts_api.save_version(self.v2, again)                      # the same draft again: nothing changed
		self.assertEqual(len(events("contract.version.save", self.v2)), n)

	def test_a_large_edit_is_summarised(self):
		data = self.draft()
		data["periods"] += [{"period_code": f"X{i:02d}", "period_name": f"Extra {i}", "start_date": str(fx.d(5, 1)),
		                     "end_date": str(fx.d(5, 2))} for i in range(60)]
		contracts_api.save_version(self.v2, data)
		p = last_event("contract.version.save", self.v2)["new"]["collections"]["periods"]
		self.assertEqual(p["count"], [2, 62])
		self.assertEqual(p["totals"]["added"], 60)
		self.assertEqual(len(p["added"]), 50)                            # keys listed up to a bound
		self.assertEqual(p["added"][0], "X00")

	def test_publish_records_the_commercial_difference(self):
		first = last_event("contract.publish", self.c["version"])
		self.assertIsNone(first["new"]["previous"])
		self.assertEqual(first["new"]["collections"]["rooms"]["totals"]["added"], 2)
		contracts_api.save_version(self.v2, self.uplift())
		out = contracts.publish(self.v2, change_note="summer uplift")
		e = last_event("contract.publish", self.v2)
		self.assertEqual(e["new"]["payload_hash"], out["payload_hash"])
		self.assertEqual(e["new"]["effective_from"], out["effective_from"])
		self.assertEqual(e["new"]["previous"], {"version": self.c["version"], "payload_hash": self.c["payload_hash"]})
		cols = e["new"]["collections"]
		self.assertEqual(cols["room_rules"]["changed"], {f"{self.std} · LOW": {"value": ["100", "110"]}})
		self.assertEqual(cols["boards"]["added"], ["HB"])
		self.assertEqual(cols["settings"]["fields"], {"prices_include_tax": [False, True]})
		for untouched in ("rooms", "periods", "age_bands", "occupancy_rules", "rate_plans", "offers"):
			self.assertNotIn(untouched, cols)


# ─── ARI grid bulk edits ─────────────────────────────────────────────────


class TestGridAudit(AuditCase):
	"""A bulk edit keeps each cell's old value next to the new one, bounded."""

	def setUp(self):
		super().setUp()
		self.c = fx.create_contract(self.f, code="GRID")
		self.std, self.dlx = self.f["room_types"]["STD"], self.f["room_types"]["DLX"]

	def latest(self) -> dict:
		return last_event("grid.bulk_update", property=fx.PROPERTY)

	def test_restriction_edits_keep_each_cells_old_value(self):
		d1, d2, d3 = fx.d(7, 1), fx.d(7, 2), fx.d(7, 3)
		grid.bulk_update(fx.PROPERTY, d1, d1, room_types=[self.std], restrictions={"min_los": 2})
		grid.bulk_update(fx.PROPERTY, d1, d3, room_types=[self.std, self.dlx],
		                 restrictions={"min_los": 3, "cta": "Yes"})
		e = self.latest()
		self.assertEqual(e["new"]["restrictions"], {"min_los": 3, "cta": "Yes"})   # what was set, as before
		r = e["new"]["collections"]["restrictions"]
		self.assertEqual(r["changed"][f"{self.std} · {d1}"], {"min_los": [2, 3], "cta": [None, "Yes"]})
		self.assertEqual(r["changed"][f"{self.dlx} · {d2}"], {"min_los": [0, 3], "cta": [None, "Yes"]})
		self.assertEqual(r["totals"]["changed"], 6)
		self.assertEqual(r["old_values"]["min_los"], {"0": 5, "2": 1})
		grid.bulk_update(fx.PROPERTY, d1, d3, room_types=[self.std, self.dlx],
		                 restrictions={"min_los": 3, "cta": "Yes"})
		r = self.latest()["new"]["collections"]["restrictions"]
		self.assertEqual((r["totals"]["changed"], r["unchanged"]), (0, 6))

	def test_a_wide_edit_is_bounded(self):
		grid.bulk_update(fx.PROPERTY, fx.d(8, 1), fx.d(9, 9), room_types=[self.std, self.dlx],
		                 restrictions={"stop_sell": "STOP"})
		r = self.latest()["new"]["collections"]["restrictions"]
		self.assertEqual(r["totals"]["changed"], 80)
		self.assertEqual(len(r["changed"]), 50)                          # cells detailed up to a bound
		self.assertEqual(r["old_values"], {"stop_sell": {"": 80}})       # every old value still counted

	def test_inventory_and_rate_edits_keep_old_values(self):
		day = fx.d(7, 1)
		grid.bulk_update(fx.PROPERTY, day, day, room_types=[self.std], inventory={"manual_adjustment": -1})
		grid.bulk_update(fx.PROPERTY, day, day, room_types=[self.std], inventory={"manual_adjustment": 1})
		inv = self.latest()["new"]["collections"]["inventory"]
		self.assertEqual(inv["changed"], {f"{self.std} · {day}": {"manual_adjustment": [-1, 1]}})

		out = grid.bulk_update(fx.PROPERTY, fx.d(7, 1), fx.d(7, 5), room_types=[self.std],
		                       contract=self.c["contract"], rate={"op": "ABSOLUTE", "value": "150"})
		rates = self.latest()["new"]["collections"]["rates"]
		self.assertEqual(rates["changed"], {f"{self.std} · {fx.d(7, 1)}/{fx.d(7, 5)}": {"unit": ["120.00", "150.00"]}})
		self.assertEqual(set(out["rate"]), {"draft", "periods", "note"})  # the response is unchanged


	def test_limited_extras_edits_keep_old_values(self):
		from kamra.tex.api import crs as crs_api
		from kamra.tex.tests.integration.test_extras_inventory import limited

		limited("SPA", capacity=2)
		d1, d2 = fx.d(6, 10), fx.d(6, 11)
		crs_api.extras_bulk_update(fx.PROPERTY, ["SPA"], str(d1), str(d1), capacity=3)
		out = crs_api.extras_bulk_update(fx.PROPERTY, ["SPA"], str(d1), str(d2), capacity=5, closed=1)
		self.assertEqual(set(out), {"updated", "over_capacity"})           # the response is unchanged
		x = last_event("extra_inventory.update", property=fx.PROPERTY)["new"]["collections"]["extra_inventory"]
		self.assertEqual(x["changed"], {f"SPA · {d1}": {"capacity": [3, 5], "closed": [0, 1]},
		                                f"SPA · {d2}": {"capacity": [0, 5], "closed": [0, 1]}})


# ─── payment rules ───────────────────────────────────────────────────────


class TestPaymentRuleAudit(AuditCase):
	"""Payment policies, provider accounts and method rules are audited whichever path saves
	them (TEX API, Desk, REST): non-secret fields old → new, secrets only as set / changed."""

	def setUp(self):
		super().setUp()
		self.p = setup_site_and_payments(self.f)

	def assert_no_secret(self, reference_name: str) -> None:
		rows = frappe.get_all("TEX Audit Event", filters={"reference_name": reference_name},
		                      fields=["old_value", "new_value", "reason"])
		text = json.dumps(rows, default=str)
		for s in SECRETS:
			self.assertNotIn(s, text)

	def test_method_rules_are_audited_on_every_path(self):
		name = pay_api.save_rule(property=fx.PROPERTY, data={"method": "Bank Transfer", "priority": 1})["name"]
		c = last_event("payment_rule.create", name)
		self.assertEqual((c["property"], c["new"]["method"], c["new"]["priority"]), (fx.PROPERTY, "Bank Transfer", 1))
		pay_api.save_rule(property=fx.PROPERTY, data={"name": name, "priority": 5})
		u = last_event("payment_rule.update", name)
		self.assertEqual((u["old"], u["new"]), ({"priority": 1}, {"priority": 5}))
		doc = frappe.get_doc("TEX Payment Method Rule", name)          # Desk / REST
		doc.disabled = 1
		doc.save()
		u = last_event("payment_rule.update", name)
		self.assertEqual((u["old"], u["new"]), ({"disabled": False}, {"disabled": True}))
		n = len(events("payment_rule.update", name))
		doc.save()                                                      # nothing changed: nothing recorded
		self.assertEqual(len(events("payment_rule.update", name)), n)
		frappe.delete_doc("TEX Payment Method Rule", name)
		self.assertEqual(last_event("payment_rule.delete", name)["old"]["method"], "Bank Transfer")

	def test_provider_accounts_record_secret_changes_never_secrets(self):
		ak, sk, rotated = SECRETS
		name = pay_api.save_account(property=fx.PROPERTY, data={"label": "G74 iyzico", "provider": "iyzico",
		                                          "environment": "Sandbox", "enabled": 1, "currencies": "EUR",
		                                          "api_key": ak, "secret_key": sk})["name"]
		c = last_event("payment_account.create", name)
		self.assertEqual((c["property"], c["new"]["label"], c["new"]["provider"]), (fx.PROPERTY, "G74 iyzico", "iyzico"))
		self.assertEqual((c["new"]["api_key_set"], c["new"]["secret_key_set"], c["new"]["store_key_set"]),
		                 (True, True, False))
		self.assertEqual(len(events("payment_account.create", name)), 1)    # one record per save
		pay_api.save_account(property=fx.PROPERTY, data={"name": name, "secret_key": rotated})
		u = last_event("payment_account.update", name)
		self.assertEqual((u["old"], u["new"]), ({"secret_key_set": True},
		                                        {"secret_key_set": True, "secret_key_changed": True}))
		n = len(events("payment_account.update", name))
		pay_api.save_account(property=fx.PROPERTY, data={"name": name, "secret_key": rotated, "label": "G74 iyzico"})
		self.assertEqual(len(events("payment_account.update", name)), n)    # the same secret again: no change
		doc = frappe.get_doc("TEX Payment Provider Account", name)         # Desk / REST
		doc.enabled = 0
		doc.save()
		u = last_event("payment_account.update", name)
		self.assertEqual((u["old"], u["new"]), ({"enabled": True}, {"enabled": False}))
		self.assertFalse(frappe.get_all("TEX Audit Event", filters={"reference_name": name,
		                                                            "action": "payment_account.save"}))
		self.assert_no_secret(name)

	def test_payment_policies_are_audited_once_per_change(self):
		name = policies_api.save_record("TEX Payment Policy", {"property": fx.PROPERTY, "policy_name": "G74 deposit",
		                                                       "deposit_type": "PERCENT", "deposit_value": 30})["name"]
		self.assertEqual(last_event("payment_policy.create", name)["new"]["deposit_value"], "30")
		policies_api.save_record("TEX Payment Policy", {"name": name, "deposit_value": 50})
		u = last_event("payment_policy.update", name)
		self.assertEqual((u["old"], u["new"]), ({"deposit_value": "30"}, {"deposit_value": "50"}))
		doc = frappe.get_doc("TEX Payment Policy", name)                 # Desk / REST
		doc.allow_pay_at_hotel = 1
		doc.save()
		u = last_event("payment_policy.update", name)
		self.assertEqual((u["old"], u["new"]), ({"allow_pay_at_hotel": False}, {"allow_pay_at_hotel": True}))
		policies_api.delete_record("TEX Payment Policy", name)
		self.assertEqual(last_event("payment_policy.delete", name)["old"]["policy_name"], "G74 deposit")
		self.assertEqual(frappe.db.count("TEX Audit Event", {"reference_name": name}), 4)   # no duplicates


# ─── payment event sources ───────────────────────────────────────────────


class TestPaymentSource(AuditCase):
	"""A payment outcome records how it arrived: the guest's browser coming back from the
	gateway, the gateway's own notification, staff, the scheduler or the guest."""

	def setUp(self):
		super().setUp()
		self.p = setup_site_and_payments(self.f)

	def iyzico(self) -> str:
		return frappe.get_doc({"doctype": "TEX Payment Provider Account", "label": "G74 iyzico gateway",
		                       "property": fx.PROPERTY, "provider": "iyzico", "environment": "Sandbox", "enabled": 1,
		                       "currencies": "EUR", "api_key": "ak-test", "secret_key": "sk-test"}).insert(
			ignore_permissions=True).name

	def charge(self, account: str, key: str) -> str:
		return pay.start_payment(property=fx.PROPERTY, amount="100", currency="EUR", provider_account=account,
		                         description="test", customer={}, return_url=_return_url(),
		                         idempotency_key=key)["transaction"]

	def callback(self, txn: str, via: str, cb: str | None = None, **params) -> None:
		form = {"txn": txn, "via": via, "cb": cb or pay.callback_signature(txn, via), **params}
		as_user("Guest")                                                # (switching user clears form_dict)
		frappe.form_dict.update(form)
		try:
			with mock.patch.object(frappe.db, "commit"):                # the endpoint commits its outcome
				pay_api.callback(txn=txn)
		finally:
			for k in form:
				frappe.form_dict.pop(k, None)
			as_user("Administrator")

	def status(self, txn: str) -> str:
		return frappe.db.get_value("TEX Payment Transaction", txn, "status")

	def test_a_gateway_return_and_a_notification_are_told_apart(self):
		from kamra.tex.payments.providers import turkey

		gw, acc = FakeIyzico(), self.iyzico()
		with gw.patch():
			t1 = self.charge(acc, "g74-return")
			init = next(p for path, p in gw.calls if path == turkey.IyzicoProvider.INIT)
			self.assertIn("via=return", init["callbackUrl"])             # the guest's browser comes back here
			gw.answers["tok-1"] = lambda t: gw.paid(t, "P1")
			self.callback(t1, "return", token="tok-1")
			self.assertEqual(self.status(t1), "Succeeded")
			self.assertEqual(last_event("payment.succeeded", t1)["source"], "Gateway Return")

			t2 = self.charge(acc, "g74-notify")
			gw.answers["tok-2"] = lambda t: gw.paid(t, "P2")
			self.callback(t2, "notify", token="tok-2")
			self.assertEqual(last_event("payment.succeeded", t2)["source"], "Webhook")

			# the channel is signed: a return address never passes for a notification
			t3 = self.charge(acc, "g74-forged")
			gw.answers["tok-3"] = lambda t: gw.paid(t, "P3")
			with self.assertRaises(frappe.DoesNotExistError):
				self.callback(t3, "notify", cb=pay.callback_signature(t3, "return"), token="tok-3")
			self.assertEqual(self.status(t3), "Pending")

	def test_staff_guest_and_scheduler_sources(self):
		gw, acc = FakeIyzico(), self.iyzico()
		with gw.patch():
			t = self.charge(acc, "g74-staff")
			gw.answers["tok-1"] = lambda x: gw.paid(x, "P9")
			# finance re-verifies it from the back office (a signed-in request)
			with mock.patch.object(frappe.local, "request", SimpleNamespace(headers={}), create=True):
				pay_api.reverify(transaction=t)
		self.assertEqual(last_event("payment.succeeded", t)["source"], "Desk")

		b = guest_books(session="g74-guest")                            # the sandbox payment page
		txn = b["payment"]["transaction"]
		public.mock_pay(transaction=txn, outcome="success", sig=b["payment"]["fields"]["success_sig"])
		as_user("Administrator")
		self.assertEqual(last_event("payment.succeeded", txn)["source"], "Gateway Return")

		link = pay.create_link(property=fx.PROPERTY, amount="50", currency="EUR", description="deposit",
		                       provider_account=self.p["account"], guest_name="G74 Guest")["link"]
		frappe.db.set_value("TEX Payment Link", link, "expires_at", add_days(now_datetime(), -1))
		from kamra.tex import scheduler

		with mock.patch.object(frappe.db, "commit"):
			scheduler._run("kamra.tex.payments.service.expire_links")
		self.assertEqual(frappe.db.get_value("TEX Payment Link", link, "status"), "Expired")
		e = last_event("payment_link.expire", link)
		self.assertEqual((e["source"], e["property"]), ("Scheduler", fx.PROPERTY))


# ─── reading a record's trail (Y-1) ──────────────────────────────────────


class TestTrailByReference(AuditCase):
	"""Y-1 (audit Part 2A): a record's trail read by reference needs what reading the record itself
	needs. It needed ``reservation.view`` whatever the record, so an agent read a contract version's
	publish (its period rates, old → new) and a viewer a payment's amount, provider and bank
	reference, which their own APIs refuse them (G-11)."""

	def setUp(self):
		super().setUp()
		from kamra.tex.tests.integration.test_crm_segments import agent

		self.p = setup_site_and_payments(self.f)
		self.version = frappe.db.get_value("TEX Contract", {"contract_code": "PAY", "property": fx.PROPERTY},
		                                   "active_version")
		self.contract = frappe.db.get_value("TEX Contract Version", self.version, "contract")
		b = guest_books(session="y1-trail")
		self.txn = b["payment"]["transaction"]
		public.mock_pay(transaction=self.txn, outcome="success", sig=b["payment"]["fields"]["success_sig"])
		self.res = b["rooms"][0]["reservation"]
		self.agent = agent("y1-agent@example.com", fx.PROPERTY)                      # Reservations Agent
		self.revenue = agent("y1-revenue@example.com", fx.PROPERTY, "Revenue Manager")
		self.viewer = agent("y1-viewer@example.com", fx.PROPERTY, "Viewer")
		self.desk = fx.ensure_user("y1-desk@example.com", ["Front Desk"])
		fx.ensure("TEX Access Grant", {"user": self.desk, "property": fx.PROPERTY},
		          {"user": self.desk, "scope_level": "Hotel", "property": fx.PROPERTY,
		           "permission_profile": "Reservations Agent"})
		as_user("Administrator")

	def trail(self, user: str, doctype: str, name: str) -> list[dict]:
		as_user(user)
		try:
			return admin.audit_log(reference_doctype=doctype, reference_name=name, limit=500)
		finally:
			as_user("Administrator")

	def test_contract_events_need_cost_or_contract_edit(self):
		for doctype, name in (("TEX Contract Version", self.version), ("TEX Contract", self.contract)):
			with self.assertRaises(frappe.PermissionError, msg=doctype):
				self.trail(self.agent, doctype, name)
		published = [r for r in self.trail(self.revenue, "TEX Contract Version", self.version)
		             if r["action"] == "contract.publish"]
		self.assertTrue(published and published[0]["new_value"]["collections"])

	def test_markups_and_pricing_policies_need_cost_as_their_own_api(self):
		# review round 1: their own API reads them with price.view_cost only (policies.READ_CAP); a
		# contract's trail still takes price.view_cost or contract.edit (G-11, contracts._sees_cost)
		from kamra.tex.security.audit import audit
		from kamra.tex.tests.integration.test_channel_binding import grant as bind
		from kamra.tex.tests.integration.test_channel_binding import profile
		from kamra.tex.tests.integration.test_patches import put

		editor = fx.ensure_user("y1-editor@example.com", ["Call Center Agent"])
		bind(editor, fx.PROPERTY, profile("Y1 Contract editor without cost",
		                                  ["price.view", "contract.edit", "reservation.view"]))
		as_user("Administrator")
		records = {"TEX Markup Rule": put("TEX Markup Rule", property=fx.PROPERTY, tex_status="Active"),
		           "TEX Pricing Policy": put("TEX Pricing Policy", property=fx.PROPERTY, tex_status="Active")}
		for doctype, name in records.items():
			audit(f"{doctype.lower().replace(' ', '_')}.save", reference_doctype=doctype, reference_name=name,
			      property=fx.PROPERTY, new={"formula": "COST * 1.25"})
		for doctype, name in records.items():
			with self.assertRaises(frappe.PermissionError, msg=doctype):
				self.trail(editor, doctype, name)
			self.assertTrue(self.trail(self.revenue, doctype, name), doctype)
		self.assertTrue(self.trail(editor, "TEX Contract Version", self.version))

	def test_a_hotels_trail_leaves_out_the_cost_its_viewer_may_not_read(self):
		# audit Part 2I, fix round 1 (G-97): the hotel view needed settings.admin alone, so a custom profile
		# with settings.admin but neither price.view_cost nor contract.edit read there the cost events (a
		# version's rate diff, markups, pricing policies) that each record's own trail refuses it; the group
		# events that reached the hotel (TEX Audit Scope) too
		from kamra.tex.security.audit import audit
		from kamra.tex.tests.integration.test_channel_binding import grant as bind
		from kamra.tex.tests.integration.test_channel_binding import profile
		from kamra.tex.tests.integration.test_patches import put

		viewers = {}
		for key, caps in (("settings", ["settings.admin"]),
		                  ("cost", ["settings.admin", "price.view_cost"]),
		                  ("contract", ["settings.admin", "contract.edit"])):
			viewers[key] = fx.ensure_user(f"y1-{key}-admin@example.com", ["Call Center Agent"])
			bind(viewers[key], fx.PROPERTY, profile(f"2I hotel trail, {key}", caps))
		as_user("Administrator")
		markup = put("TEX Markup Rule", property=fx.PROPERTY, tex_status="Active")
		policy = put("TEX Pricing Policy", property=fx.PROPERTY, tex_status="Active")
		grant = frappe.db.get_value("TEX Access Grant", {"user": self.agent, "property": fx.PROPERTY})
		group = {"hotel_group": self.f["group"], "hotels": [fx.PROPERTY]}
		made = {"grant": audit("grant.update", reference_doctype="TEX Access Grant", reference_name=grant,
		                       property=fx.PROPERTY, new={"permission_profile": "Reservations Agent"})}
		made |= {
			"version": audit("contract.version.save", reference_doctype="TEX Contract Version",
			                 reference_name=self.version, property=fx.PROPERTY, new={"rates": {"DBL": "100.00"}}),
			"markup": audit("tex_markup_rule.save", reference_doctype="TEX Markup Rule", reference_name=markup,
			                property=fx.PROPERTY, new={"formula": "COST * 1.25"}),
			"policy": audit("tex_pricing_policy.save", reference_doctype="TEX Pricing Policy", reference_name=policy,
			                property=fx.PROPERTY, new={"formula": "COST * 1.30"}),
			"group version": audit("contract.version.save", reference_doctype="TEX Contract Version",
			                       reference_name=self.version, new={"rates": {"DBL": "90.00"}}, **group),
			"group markup": audit("tex_markup_rule.save", reference_doctype="TEX Markup Rule", reference_name=markup,
			                      new={"formula": "COST * 1.20"}, **group),
		}

		def seen(user: str, limit: int = 500) -> set[str]:
			as_user(user)
			try:
				names = {r["name"] for r in admin.audit_log(property=fx.PROPERTY, limit=limit)}
			finally:
				as_user("Administrator")
			return {k for k, name in made.items() if name in names}

		contract = {"version", "group version"}
		self.assertEqual(seen(viewers["settings"]), {"grant"})
		self.assertEqual(seen(viewers["cost"]), set(made))
		self.assertEqual(seen(viewers["contract"]), {"grant"} | contract)
		self.assertEqual(seen("Administrator"), set(made))
		# the filter is in the query: the newest page of a viewer without cost is not emptied by it
		self.assertEqual(seen(viewers["settings"], limit=1), {"grant"})

	def test_a_hotels_trail_leaves_out_payments_stays_and_policies_its_viewer_may_not_read(self):
		"""LO-28 (2K-4): the hotel view left out only cost. A custom profile with settings.admin alone read there the
		payment and stay events (amounts, provider, bank reference, a stay's changes) that each record's own trail
		refuses it (``TRAIL_CAPABILITY``), and a commercial policy's events that its own API refuses it."""
		from kamra.tex.security.audit import audit
		from kamra.tex.tests.integration.test_channel_binding import grant as bind
		from kamra.tex.tests.integration.test_channel_binding import profile
		from kamra.tex.tests.integration.test_patches import put

		viewers = {}
		for key, caps in (("settings", ["settings.admin"]),
		                  ("all", ["settings.admin", "payment.view", "reservation.view", "price.view"])):
			viewers[key] = fx.ensure_user(f"lo28-{key}-admin@example.com", ["Call Center Agent"])
			bind(viewers[key], fx.PROPERTY, profile(f"LO-28 hotel trail, {key}", caps))
		as_user("Administrator")
		booking = frappe.db.get_value("Reservation", self.res, "tex_booking")
		promotion = put("TEX Promotion", property=fx.PROPERTY, tex_status="Active")
		grant = frappe.db.get_value("TEX Access Grant", {"user": self.agent, "property": fx.PROPERTY})
		made = {"grant": audit("grant.update", reference_doctype="TEX Access Grant", reference_name=grant,
		                       property=fx.PROPERTY, new={"permission_profile": "Reservations Agent"})}
		made |= {
			"payment": audit("payment.note", reference_doctype="TEX Payment Transaction", reference_name=self.txn,
			                 property=fx.PROPERTY, new={"amount": "100.00", "provider_ref": "BANK-REF"}),
			"stay": audit("reservation.note", reference_doctype="Reservation", reference_name=self.res,
			              property=fx.PROPERTY, new={"check_out": "2026-06-14"}),
			"booking": audit("booking.note", reference_doctype="TEX Booking", reference_name=booking,
			                 property=fx.PROPERTY, new={"total": "100.00"}),
			"promotion": audit("tex_promotion.save", reference_doctype="TEX Promotion", reference_name=promotion,
			                   property=fx.PROPERTY, new={"value": "10"}),
		}

		def seen(user: str, limit: int = 500) -> set[str]:
			as_user(user)
			try:
				names = {r["name"] for r in admin.audit_log(property=fx.PROPERTY, limit=limit)}
			finally:
				as_user("Administrator")
			return {k for k, name in made.items() if name in names}

		self.assertEqual(seen(viewers["settings"]), {"grant"})
		self.assertEqual(seen(viewers["all"]), set(made))
		self.assertEqual(seen("Administrator"), set(made))
		# the filter is in the query: the newest page of a viewer without them is not emptied by it
		self.assertEqual(seen(viewers["settings"], limit=1), {"grant"})

	def test_payment_events_need_payment_view(self):
		with self.assertRaises(frappe.PermissionError):
			self.trail(self.viewer, "TEX Payment Transaction", self.txn)
		self.assertIn("payment.succeeded", {r["action"] for r in self.trail(self.agent, "TEX Payment Transaction",
		                                                                    self.txn)})

	def test_a_stays_events_are_still_read_at_the_front_desk(self):
		from kamra.tex.services import modification

		p = modification.propose(self.res, {"check_out": str(fx.d(6, 14))})
		modification.apply(p["proposal_token"], reason="one more night")
		for user in (self.desk, self.viewer):
			self.assertIn("reservation.modify", {r["action"] for r in self.trail(user, "Reservation", self.res)})

	def test_any_other_record_needs_hotel_settings(self):
		from kamra.tex.security.audit import audit

		grant = frappe.db.get_value("TEX Access Grant", {"user": self.agent, "property": fx.PROPERTY})
		audit("grant.update", reference_doctype="TEX Access Grant", reference_name=grant, property=fx.PROPERTY,
		      new={"permission_profile": "Reservations Agent"})
		with self.assertRaises(frappe.PermissionError):
			self.trail(self.revenue, "TEX Access Grant", grant)
		self.assertTrue(self.trail("Administrator", "TEX Access Grant", grant))
