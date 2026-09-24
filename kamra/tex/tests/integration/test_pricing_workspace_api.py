"""Pricing Workspace backend (ADR-061, slice S2).

* GAP-1: ``price_matrix``, ``validate_version`` and ``preview_price`` take the editor's unsaved
  ``data`` and apply it to the draft in memory (the read-only overlay). Nothing is saved or
  audited; each row's client key becomes its rule id (``~<_key>``).
* GAP-8: a blank rule value is refused by ``save_version`` and by the overlay (Frappe stored it
  as 0), naming the row.
* GAP-10: ``get_version`` says what the viewer may do (``can_preview``, ``can_publish``,
  ``can_edit_contract``), whether the pricing basis is locked and the contract currency's
  minor units.

Slice S3:

* GAP-2: ``price_matrix`` says which rule priced each cell (``rooms[].sources``): its scope, the
  derivation chain and the rules it overrode.
* GAP-2b: with ``parties`` and ``party_room`` it prices sample parties per period (``party_cells``).
* GAP-3: it shows what the version inherits and what the engine assumes: the effective capacity
  (``rooms[].capacity``), the age bands with their origin, the inherited occupancy rules and the
  engine's adult default (``occupancy_defaults``).

Slice S4:

* GAP-4: ``validate_version`` issues carry a ``ref`` naming the rule(s), room, period, band(s),
  party or board they are about (row names of the saved draft, ``~<_key>`` of unsaved rows);
  messages are unchanged.
* GAP-5: a board rule naming an unknown room or period, and two rules of one board for the same
  room and period, are publish errors.

Slice S5:

* GAP-6: ``preview_price`` takes a child as whole years (as before), ``{age_months}`` or ``{dob}``
  and refuses anything else (``7.5``, ``"7.5"``, adult ages, more than 12 children).
* GAP-7: ``apply_op_values`` changes entered prices of a draft once by an op, as the ARI grid does
  (the base room's relative entry, O4, and the bulk Adjust…); read-only, ``contract.edit``.
* GAP-12: each night of a quote reports ``subtotal_adults``, ``subtotal_children`` and
  ``subtotal_board``; the guest view never carries them.
"""

import json
from unittest import mock

import frappe

from kamra.tex.api import contracts as api
from kamra.tex.commercial import contracts, revisions
from kamra.tex.money import D
from kamra.tex.pricing import rooms as room_math
from kamra.tex.pricing.model import Unsellable
from kamra.tex.security import scope
from kamra.tex.tests.integration import fixtures as fx
from kamra.tex.tests.integration.test_critical_journey import TexTestCase
from kamra.tex.tests.integration.test_pricing_policies import INF, POLICY, child, policy
from kamra.tex_commercial.doctype.tex_contract.tex_contract import header_values

OTHER_HOTEL = "PW Other Hotel"
RM = "pw-revenue@example.com"          # Revenue Manager at the test hotel
EDITOR = "pw-editor@example.com"       # contract.edit without price.view_cost
FINANCE = "pw-finance@example.com"     # price.view_cost without contract.edit
AGENT = "pw-agent@example.com"         # sells only: the catalogue
FOREIGN = "pw-foreign@example.com"     # a Revenue Manager of another hotel
ROW_MESSAGE = "a value is required; clear the cell to remove the price."


def keyed(table: str, rows: list[dict]) -> list[dict]:
	"""Rows as the workspace posts them: each with its client key (and the server's bookkeeping,
	which the server drops)."""
	return [{**r, "_key": f"{table}-k{i + 1}"} for i, r in enumerate(rows)]


def as_json(data: dict) -> str:
	"""What the browser posts (dates as ISO text)."""
	return json.dumps(data, default=str)


def find(rows: list[dict], **match) -> dict:
	return next(r for r in rows if all(r.get(k) == v for k, v in match.items()))


class WorkspaceCase(TexTestCase):
	def setUp(self):
		super().setUp()
		self.std, self.dlx = self.f["room_types"]["STD"], self.f["room_types"]["DLX"]
		self.c = fx.create_contract(self.f, code="PW-S2", publish=False)
		self.v = self.c["version"]
		fx.ensure("TEX Permission Profile", {"profile_name": "PW Contract Editor"},
		          {"profile_name": "PW Contract Editor",
		           "capabilities": [{"capability": "price.view"}, {"capability": "contract.edit"}]})
		if not frappe.db.exists("Property", OTHER_HOTEL):
			frappe.get_doc({"doctype": "Property", "property_name": OTHER_HOTEL, "city": "Side", "country": "Turkey",
			                "currency": "EUR", "tex_hotel_group": self.f["group"]}).insert(ignore_permissions=True)
		for user, prop, profile in ((RM, fx.PROPERTY, "Revenue Manager"), (EDITOR, fx.PROPERTY, "PW Contract Editor"),
		                            (FINANCE, fx.PROPERTY, "Finance"), (AGENT, fx.PROPERTY, "Reservations Agent"),
		                            (FOREIGN, OTHER_HOTEL, "Revenue Manager")):
			fx.ensure_user(user, ["Revenue Manager"])
			fx.ensure("TEX Access Grant", {"user": user, "property": prop},
			          {"user": user, "scope_level": "Hotel", "property": prop, "permission_profile": profile})
		scope.clear_cache()

	def as_user(self, user: str) -> None:
		frappe.set_user(user)  # nosemgrep: frappe-setuser -- test context switch
		scope.clear_cache()

	def payload(self) -> dict:
		"""The draft's saved state as the workspace posts it (every table, keyed rows)."""
		doc = api.get_version(self.v)
		return {t: keyed(t, doc[t]) for t in api.VERSION_TABLES}

	def std_low(self, data: dict) -> dict:
		return find(data["period_rates"], room_type=self.std, period_code="LOW")

	def preview(self, version: str | None = None, **kw):
		args = {"room_type": self.std, "board": "AI", "check_in": str(fx.d(6, 10)), "check_out": str(fx.d(6, 11)),
		        "adults": 2, "market": "DE", "rate_plan": self.f["rate_plans"]["FLEX"], **kw}
		return api.preview_price(version or self.v, **args)

	def untouched(self) -> tuple:
		"""What a write would change: the draft's modified time, its audit events and its rows."""
		rows = {t: frappe.get_all(frappe.get_meta("TEX Contract Version").get_field(t).options,
		                          filters={"parent": self.v, "parenttype": "TEX Contract Version"},
		                          fields=["name", "modified"], order_by="idx asc")
		        for t in api.VERSION_TABLES}
		return (frappe.db.get_value("TEX Contract Version", self.v, "modified"),
		        frappe.db.count("TEX Audit Event", {"reference_name": self.v}),
		        {t: [(r.name, str(r.modified)) for r in rs] for t, rs in rows.items()})


class TestOverlayReads(WorkspaceCase):
	def test_unsaved_data_is_priced_validated_and_quoted_without_a_write(self):
		before = self.untouched()
		data = self.payload()
		self.std_low(data).update(op="ABSOLUTE", value="123.45")

		m = api.price_matrix(self.v, data=as_json(data))
		std = find(m["rooms"], room_type=self.std)
		dlx = find(m["rooms"], room_type=self.dlx)
		self.assertEqual(D(std["cells"]["LOW"]), D("123.45"))
		self.assertEqual(D(dlx["cells"]["LOW"]), D("123.45") * D("1.35"))     # the derived room follows
		self.assertEqual(D(std["cells"]["HIGH"]), D("120"))
		self.assertTrue(api.validate_version(self.v, data=data)["ok"])
		q = self.preview(data=data)
		self.assertTrue(q["sellable"], q.get("reasons"))
		self.assertEqual(D(q["nights"][0]["unit"]), D("123.45"))

		# the draft as saved: unchanged, unaudited, the same rows
		self.assertEqual(self.untouched(), before)
		self.assertEqual(self.std_low(api.get_version(self.v))["value"], "100")
		self.assertEqual(D(find(api.price_matrix(self.v)["rooms"], room_type=self.std)["cells"]["LOW"]), D("100"))
		self.assertEqual(D(self.preview()["nights"][0]["unit"]), D("100"))

	def test_validation_of_unsaved_data_reports_its_issues(self):
		data = self.payload()
		data["period_rates"].append({**self.std_low(data), "_key": "dup", "value": "90"})
		report = api.validate_version(self.v, data=as_json(data))
		self.assertFalse(report["ok"])
		self.assertIn("ROOM_RULE_DUPLICATE", [i["code"] for i in report["issues"]])
		self.assertTrue(api.validate_version(self.v)["ok"])                        # the saved draft
		self.assertEqual(contracts.validate_version(self.v), api.validate_version(self.v))

	def test_rule_ids_are_the_rows_client_keys(self):
		data = self.payload()
		key = self.std_low(data)["_key"]
		q = self.preview(data=data)
		ids = {s["rule"]["rule_id"] for s in q["explanation"] if s.get("rule") and s["rule"]["kind"] == "room_rule"}
		self.assertEqual(ids, {f"~{key}"})
		# a row without a key is named by its table and position
		for r in data["period_rates"]:
			r.pop("_key")
		q = self.preview(data=data)
		pos = data["period_rates"].index(self.std_low(data)) + 1
		ids = {s["rule"]["rule_id"] for s in q["explanation"] if s.get("rule") and s["rule"]["kind"] == "room_rule"}
		self.assertEqual(ids, {f"~period_rates-{pos}"})
		# the saved draft keeps its row names
		saved = self.std_low(api.get_version(self.v))["name"]
		q = self.preview()
		ids = {s["rule"]["rule_id"] for s in q["explanation"] if s.get("rule") and s["rule"]["kind"] == "room_rule"}
		self.assertEqual(ids, {saved})

	def test_the_overlay_prices_what_a_save_would_store(self):
		data = self.payload()
		self.std_low(data).update(value="123.45")
		dlx_high = {"room_type": self.dlx, "period_code": "HIGH", "op": "INHERIT", "value": None, "base_room_type": None,
		            "_key": "inherit"}
		data["period_rates"].append(dlx_high)                                    # INHERIT: a blank value is fine
		# a new supplement board with no child percent: the DocType default (50) applies, as on save
		data["boards"].append({"board": "UAI", "op": "ADD", "adult_amount": "30", "child_percent": None,
		                       "infant_free": 1, "room_type": self.dlx, "period_code": "LOW", "_key": "uai-dlx"})
		# a check typed as text is stored as 0: a child above the top band is not an adult
		data["children_over_max_as_adults"] = "0"
		parties = [dict(room_type=self.dlx, board="UAI", children=json.dumps([8])),
		           dict(room_type=self.std, board="AI", check_in=str(fx.d(7, 10)), check_out=str(fx.d(7, 12)), adults=3),
		           dict(room_type=self.dlx, board="AI", children=json.dumps([13]))]

		overlay_matrix = api.price_matrix(self.v, data=data)
		overlay_quotes = [self.preview(data=data, **p) for p in parties]
		self.assertTrue(overlay_quotes[0]["sellable"] and overlay_quotes[1]["sellable"],
		                [q.get("reasons") for q in overlay_quotes])
		api.save_version(self.v, as_json(data))
		saved_matrix = api.price_matrix(self.v)
		saved_quotes = [self.preview(**p) for p in parties]

		def cells(m):
			return {(r["room_type"], p): D(c) for r in m["rooms"] for p, c in r["cells"].items()}

		def money(q):
			if not q["sellable"]:
				return False, q["reasons"]
			return True, {k: D(v) for k, v in q["totals"].items()}, [
				{k: D(v) for k, v in n.items() if k not in ("date", "period")} for n in q["nights"]]

		self.assertEqual(cells(overlay_matrix), cells(saved_matrix))
		self.assertEqual([money(q) for q in overlay_quotes], [money(q) for q in saved_quotes])
		self.assertEqual(find(api.get_version(self.v)["boards"], board="UAI", room_type=self.dlx)["child_percent"], "50")


class TestOverlayRefusals(WorkspaceCase):
	def calls(self, data):
		return (("price_matrix", lambda: api.price_matrix(self.v, data=data)),
		        ("validate_version", lambda: api.validate_version(self.v, data=data)),
		        ("preview_price", lambda: self.preview(data=data)))

	def test_a_published_version_is_never_overlaid(self):
		data = self.payload()
		contracts.publish(self.v)
		for name, call in self.calls(data):
			with self.subTest(endpoint=name), self.assertRaises(frappe.ValidationError) as cm:
				call()
			self.assertIn("Only draft versions can be previewed with unsaved changes", str(cm.exception))
		self.assertTrue(api.price_matrix(self.v)["rooms"])                          # its frozen terms still read

	def test_the_overlay_needs_contract_edit_at_the_versions_hotel(self):
		data = self.payload()
		for user in (FINANCE, FOREIGN):
			self.as_user(user)
			for name, call in self.calls(data):
				with self.subTest(user=user, endpoint=name), self.assertRaises(frappe.PermissionError):
					call()
		self.as_user(RM)
		self.assertTrue(api.price_matrix(self.v, data=data)["rooms"])
		self.assertTrue(api.validate_version(self.v, data=data)["ok"])
		self.assertIn("sellable", self.preview(data=data))

	def test_a_blank_value_is_refused_on_save_and_in_the_overlay(self):
		before = self.untouched()
		cases = (
			("period_rates", dict(room_type=self.std, period_code="LOW"), "value", "", "Room prices"),
			("occupancy_rules", dict(target="CHILD", age_band="CHA"), "value", None, "Occupancy rules"),
			("boards", dict(board="UAI"), "adult_amount", "  ", "Boards"),
		)
		for table, match, field, blank, label in cases:
			data = self.payload()
			row = find(data[table], **match)
			row[field] = blank
			message = f"{label}, row {data[table].index(row) + 1}: {ROW_MESSAGE}"
			with self.subTest(table=table, path="save"), self.assertRaises(frappe.ValidationError) as cm:
				api.save_version(self.v, as_json(data))
			self.assertIn(message, str(cm.exception))
			for name, call in self.calls(data):
				with self.subTest(table=table, path=name), self.assertRaises(frappe.ValidationError) as cm:
					call()
				self.assertIn(message, str(cm.exception))
		self.assertEqual(self.untouched(), before)

	def test_inherit_and_the_included_board_need_no_value(self):
		data = self.payload()
		data["period_rates"].append({"room_type": self.dlx, "period_code": "HIGH", "op": "INHERIT", "value": "",
		                             "_key": "inh"})
		find(data["boards"], board="AI")["adult_amount"] = None                     # the included (base) board
		self.assertTrue(api.price_matrix(self.v, data=data)["rooms"])
		out = api.save_version(self.v, as_json(data))
		self.assertEqual(find(out["period_rates"], room_type=self.dlx, period_code="HIGH")["value"], "0")

	def test_more_than_nine_places_are_refused_as_save_refuses_them(self):
		data = self.payload()
		find(data["occupancy_rules"], target="ADULT", position=3)["value"] = "0.3333333333"
		with self.assertRaises(frappe.ValidationError) as saved:
			api.save_version(self.v, as_json(data))
		with self.assertRaises(frappe.ValidationError) as overlaid:
			api.price_matrix(self.v, data=data)
		self.assertIn("9 decimal places", str(overlaid.exception))
		self.assertEqual(str(overlaid.exception), str(saved.exception))

	def test_more_than_5000_rows_are_refused(self):
		data = self.payload()
		rate = {"room_type": self.std, "period_code": "LOW", "op": "ABSOLUTE", "value": "100"}
		data["period_rates"] = [{**rate, "_key": f"r{i}"} for i in range(5001)]
		with self.assertRaises(frappe.ValidationError) as cm:
			api.price_matrix(self.v, data=data)
		self.assertIn("5000", str(cm.exception))

	def test_above_the_row_cap_the_saved_draft_still_answers_by_name(self):
		"""The overlay refuses a draft above its row cap with a typed error the workspace can tell
		from any other refusal (``OverlayTooLarge``: still a ValidationError, same message);
		``save_version`` has no cap, and the saved draft is priced, validated and quoted by name as
		before, which is where the workspace goes above the cap (ADR-061, S8 review follow-up)."""
		data = self.payload()
		rows = sum(len(data[t]) for t in api.VERSION_TABLES)
		self.std_low(data).update(op="ABSOLUTE", value="123.45")
		with mock.patch.object(api, "OVERLAY_MAX_ROWS", rows - 1):
			self.assertEqual(api.get_version(self.v)["overlay_max_rows"], rows - 1)
			for call in (lambda: api.price_matrix(self.v, data=as_json(data)),
			             lambda: api.validate_version(self.v, data=as_json(data)),
			             lambda: self.preview(data=as_json(data))):
				with self.assertRaises(api.OverlayTooLarge) as cm:
					call()
				self.assertIsInstance(cm.exception, frappe.ValidationError)
				self.assertEqual(str(cm.exception), f"A draft previewed with unsaved changes has at most {rows - 1} "
				                                    f"rows; this one has {rows}.")
			api.save_version(self.v, as_json(data))            # a save has no cap
			m = api.price_matrix(self.v)
			self.assertEqual(D(find(m["rooms"], room_type=self.std)["cells"]["LOW"]), D("123.45"))
			self.assertTrue(api.validate_version(self.v)["ok"])
			q = self.preview()
			self.assertTrue(q["sellable"], q.get("reasons"))
		# any other refusal keeps its own type (a blank value while a row is typed)
		blank = self.payload()
		self.std_low(blank)["value"] = ""
		with self.assertRaises(frappe.ValidationError) as cm:
			api.validate_version(self.v, data=as_json(blank))
		self.assertNotIsInstance(cm.exception, api.OverlayTooLarge)

	def test_a_row_name_used_twice_in_a_table_is_refused(self):
		# issue refs and matrix sources name a row by its key: each must name one row (ADR-061, S4)
		twice = self.payload()
		twice["period_rates"][1]["_key"] = twice["period_rates"][0]["_key"]
		shadow = self.payload()                          # a key equal to a keyless row's name
		shadow["occupancy_rules"][0].pop("_key")
		shadow["occupancy_rules"][1]["_key"] = "occupancy_rules-1"
		for data, message in ((twice, f"Room prices: two rows have the key {twice['period_rates'][0]['_key']}"),
		                      (shadow, "Occupancy rules: two rows have the key occupancy_rules-1")):
			for name, call in self.calls(data):
				with self.subTest(message=message, endpoint=name), self.assertRaises(frappe.ValidationError) as cm:
					call()
				self.assertIn(f"{message}; each row needs its own key.", str(cm.exception))
		# one key in two tables names two rows of different kinds; keyless rows are named by position
		data = self.payload()
		data["boards"][0]["_key"] = data["period_rates"][0]["_key"]
		for t in ("rooms", "periods"):
			for r in data[t]:
				r.pop("_key")
		self.assertTrue(api.validate_version(self.v, data=data)["ok"])
		api.save_version(self.v, as_json(twice))           # a save drops the keys

	def test_a_build_error_is_answered_not_raised(self):
		data = self.payload()
		data["rooms"].append({"room_type": "PW no such room", "_key": "bad"})
		m = api.price_matrix(self.v, data=data)
		self.assertEqual((m["rooms"], m["periods"]), ([], []))
		self.assertTrue(m["build_error"])
		report = api.validate_version(self.v, data=data)
		self.assertEqual([i["code"] for i in report["issues"]], ["BUILD"])


class TestViewerFlags(WorkspaceCase):
	def test_each_viewer_is_told_what_it_may_do(self):
		expect = {  # user: (editable, can_preview, can_publish, can_edit_contract)
			RM: (True, True, True, True),
			EDITOR: (True, False, False, True),
			FINANCE: (False, True, False, False),
		}
		for user, flags in expect.items():
			self.as_user(user)
			doc = api.get_version(self.v)
			with self.subTest(user=user):
				self.assertEqual((doc["editable"], doc["can_preview"], doc["can_publish"], doc["can_edit_contract"]),
				                 flags)
		self.as_user(AGENT)
		doc = api.get_version(self.v)
		self.assertTrue(doc["cost_hidden"])
		self.assertEqual((doc["can_preview"], doc["can_publish"], doc["can_edit_contract"]), (False, False, False))

	def test_an_editor_is_told_the_overlay_row_cap(self):
		# what the workspace previews with unsaved changes; above it, it asks for the saved draft
		for user, cap in ((RM, api.OVERLAY_MAX_ROWS), (EDITOR, api.OVERLAY_MAX_ROWS), (FINANCE, None), (AGENT, None)):
			self.as_user(user)
			with self.subTest(user=user):
				self.assertEqual(api.get_version(self.v).get("overlay_max_rows"), cap)
		self.assertEqual(api.OVERLAY_MAX_ROWS, 5000)

	def test_finance_reads_the_saved_matrix_but_never_validates(self):
		self.as_user(FINANCE)
		self.assertTrue(api.price_matrix(self.v)["rooms"])
		with self.assertRaises(frappe.PermissionError):
			api.validate_version(self.v)

	def test_the_basis_is_locked_once_a_version_was_published(self):
		self.assertFalse(api.get_version(self.v)["basis_locked"])
		contracts.publish(self.v)
		self.assertTrue(api.get_version(self.v)["basis_locked"])
		draft = contracts.new_draft(self.c["contract"])
		doc = api.get_version(draft)
		self.assertTrue(doc["basis_locked"])
		self.assertTrue(doc["can_edit_contract"])                                   # whatever the lock says

	def test_minor_units_of_the_contract_currency(self):
		self.assertEqual(api.get_version(self.v)["contract_doc"]["minor_units"], 2)
		fx.ensure_currency("KWD", "KD")
		kwd = frappe.get_doc({"doctype": "TEX Contract", "property": fx.PROPERTY, "contract_code": "PW-KWD",
		                      "contract_name": "PW KWD", "market": "DE", "contract_currency": "KWD",
		                      "pricing_basis": "PERSON", "status": "Draft"}).insert(ignore_permissions=True)
		draft = contracts.new_draft(kwd.name)
		self.assertEqual(api.get_version(draft)["contract_doc"]["minor_units"], 3)


class TestPricingBasis(WorkspaceCase):
	def test_the_basis_alone_changes_before_the_first_publish(self):
		header = header_values(frappe.get_doc("TEX Contract", self.c["contract"]))
		before = self.untouched()
		api.save_contract(data={"name": self.c["contract"], "pricing_basis": "ROOM"})
		after = header_values(frappe.get_doc("TEX Contract", self.c["contract"]))
		self.assertEqual({k: v for k, v in after.items() if header[k] != v}, {"pricing_basis": "ROOM"})
		self.assertEqual(self.untouched(), before)                                 # the draft is untouched
		self.assertEqual(api.get_version(self.v)["contract_doc"]["pricing_basis"], "ROOM")

	def test_the_basis_is_refused_after_publish(self):
		contracts.publish(self.v)
		with self.assertRaises(frappe.ValidationError) as cm:
			api.save_contract(data={"name": self.c["contract"], "pricing_basis": "ROOM"})
		self.assertIn("cannot change", str(cm.exception))
		self.assertEqual(frappe.db.get_value("TEX Contract", self.c["contract"], "pricing_basis"), "PERSON")


# ─── slice S3: provenance, what is inherited, sample parties ───────────────


def pre_s3_matrix(version: str) -> dict:
	"""``price_matrix`` as it answered before S3 (its keys, computed its way): the baseline the
	additive keys must leave alone."""
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


def old_keys(m: dict) -> dict:
	return {"periods": m["periods"], "basis": m["basis"], "currency": m["currency"],
	        "rooms": [{k: r[k] for k in ("room_type", "name", "cells", "errors") if k in r} for r in m["rooms"]]}


class TestMatrixProvenance(WorkspaceCase):
	def rate_name(self, room_type: str, period_code: str | None) -> str:
		return find(api.get_version(self.v)["period_rates"], room_type=room_type, period_code=period_code)["name"]

	def test_each_cell_names_the_rule_that_priced_it(self):
		m = api.price_matrix(self.v)
		std, dlx = find(m["rooms"], room_type=self.std), find(m["rooms"], room_type=self.dlx)
		self.assertEqual(std["sources"]["LOW"], {
			"rule_id": self.rate_name(self.std, "LOW"), "scope": "PERIOD", "op": "ABSOLUTE", "value": "100",
			"base_room_type": None, "chain": [self.std], "overridden": []})
		self.assertEqual(dlx["sources"]["HIGH"], {
			"rule_id": self.rate_name(self.dlx, None), "scope": "ALL", "op": "MULTIPLY", "value": "1.35",
			"base_room_type": self.std, "chain": [self.dlx, self.std], "overridden": []})

	def test_unsaved_rows_are_named_by_their_keys_and_errored_cells_have_no_source(self):
		data = self.payload()
		high = find(data["period_rates"], room_type=self.std, period_code="HIGH")
		data["period_rates"].remove(high)
		dlx_high = {"room_type": self.dlx, "period_code": "LOW", "op": "ABSOLUTE", "value": "150", "_key": "fix"}
		data["period_rates"].append(dlx_high)
		m = api.price_matrix(self.v, data=data)
		std, dlx = find(m["rooms"], room_type=self.std), find(m["rooms"], room_type=self.dlx)
		self.assertEqual(std["sources"]["LOW"]["rule_id"], f"~{self.std_low(data)['_key']}")
		generic = find(data["period_rates"], room_type=self.dlx, period_code=None)["_key"]
		self.assertEqual((dlx["sources"]["LOW"]["rule_id"], dlx["sources"]["LOW"]["scope"]), ("~fix", "PERIOD"))
		self.assertEqual(dlx["sources"]["LOW"]["overridden"], [f"~{generic}"])
		self.assertIsNone(std["cells"]["HIGH"])                    # no price: an error, and no source
		self.assertIsNone(dlx["cells"]["HIGH"])
		self.assertNotIn("HIGH", std["sources"])
		self.assertNotIn("HIGH", dlx["sources"])
		self.assertIn("HIGH", std["errors"])

	def test_capacity_is_the_effective_one(self):
		m = api.price_matrix(self.v)
		# the contract rooms set nothing: the room types' capacity (fixtures: STD 3+2, DLX 3+3, 2 included)
		self.assertEqual(find(m["rooms"], room_type=self.std)["capacity"], {
			"max_adults": 3, "max_children": 2, "max_occupants": 5, "min_adults": 1, "included_adults": 2})
		self.assertEqual(find(m["rooms"], room_type=self.dlx)["capacity"], {
			"max_adults": 3, "max_children": 3, "max_occupants": 6, "min_adults": 1, "included_adults": 2})
		data = self.payload()
		find(data["rooms"], room_type=self.dlx).update(max_adults=2, max_occupants=4, min_adults=2, included_adults=1)
		m = api.price_matrix(self.v, data=data)
		self.assertEqual(find(m["rooms"], room_type=self.dlx)["capacity"], {
			"max_adults": 2, "max_children": 3, "max_occupants": 4, "min_adults": 2, "included_adults": 1})

	def test_the_versions_own_bands_and_the_engine_default(self):
		m = api.price_matrix(self.v)
		self.assertEqual(m["age_bands"], [
			{"code": "INF", "label": "Infant", "from_months": 0, "to_months": 36, "is_infant": True,
			 "source": "version"},
			{"code": "CHA", "label": "Child A", "from_months": 36, "to_months": 84, "is_infant": False,
			 "source": "version"},
			{"code": "CHB", "label": "Child B", "from_months": 84, "to_months": 144, "is_infant": False,
			 "source": "version"}])
		self.assertEqual(m["occupancy_defaults"], {
			"adult": {"rule_id": "GLOBAL:ADULT", "target": "ADULT", "op": "MULTIPLY", "value": "1",
			          "source": "global-default", "note": "every adult pays the full unit"},
			"child": None})
		self.assertTrue(all(r["source"] != "version" for r in m["inherited_rules"]))

	def test_a_band_without_a_label_reports_its_code(self):
		data = self.payload()
		find(data["age_bands"], band_code="CHA")["label"] = ""
		m = api.price_matrix(self.v, data=data)
		self.assertEqual(find(m["age_bands"], code="CHA")["label"], "CHA")
		api.save_version(self.v, as_json(data))
		self.assertEqual(find(api.price_matrix(self.v)["age_bands"], code="CHA")["label"], "CHA")

	def test_the_existing_keys_are_unchanged(self):
		baseline = pre_s3_matrix(self.v)
		for kw in ({}, {"adults": 3}, {"parties": [{"adults": 2, "children": ["CHB"]}], "party_room": self.std}):
			with self.subTest(**{k: str(v) for k, v in kw.items()}):
				self.assertEqual(old_keys(api.price_matrix(self.v, **kw)), baseline)
		contracts.publish(self.v)
		self.assertEqual(old_keys(api.price_matrix(self.v)), pre_s3_matrix(self.v))


class TestInheritedTerms(WorkspaceCase):
	def setUp(self):
		super().setUp()
		# only this test's policies are on sale (archived inside the test transaction, rolled back)
		for name in frappe.get_all(POLICY, filters={"tex_status": ("in", ["Active", "Superseded"])}, pluck="name"):
			revisions.archive(POLICY, name)
		self.policy = policy("PW Global", bands=[INF, {"band_code": "CHD", "label": "", "from_age": 3,
		                                                "to_age": 11.99}],
		                     rules=[child("INF", "MULTIPLY", 0), child("CHD", "PERCENT_OF", 50),
		                            {"target": "ADULT", "position": 3, "op": "MULTIPLY", "value": 0.8}])
		rev = frappe.db.get_value(POLICY, self.policy, "revision_no") or 1
		self.source = f"policy:{self.policy}/r{rev}/global"
		self.inh = fx.create_contract(self.f, code="PW-S3-INH", age_bands=[], occupancy_rules=[], publish=False)

	def test_bands_and_rules_inherited_from_a_policy(self):
		m = api.price_matrix(self.inh["version"])
		self.assertEqual(m["age_bands"], [
			{"code": "INF", "label": "Infant", "from_months": 0, "to_months": 36, "is_infant": True,
			 "source": self.source},
			{"code": "CHD", "label": "CHD", "from_months": 36, "to_months": 144, "is_infant": False,
			 "source": self.source}])
		rules = m["inherited_rules"]
		self.assertEqual(len(rules), 3)
		self.assertEqual({r["source"] for r in rules}, {self.source})
		adult = find(rules, target="ADULT")
		self.assertEqual({k: adult[k] for k in ("position", "age_band", "adults", "children", "room_type", "period",
		                                        "op", "value", "is_override")},
		                 {"position": 3, "age_band": None, "adults": None, "children": None, "room_type": None,
		                  "period": None, "op": "MULTIPLY", "value": "0.8", "is_override": False})
		self.assertEqual(find(rules, age_band="CHD")["value"], "50")
		# a published version keeps saying where its frozen bands came from
		contracts.publish(self.inh["version"])
		self.assertEqual({b["source"] for b in api.price_matrix(self.inh["version"])["age_bands"]}, {self.source})

	def test_the_versions_own_rules_are_not_inherited(self):
		m = api.price_matrix(self.v)
		self.assertEqual({b["source"] for b in m["age_bands"]}, {"version"})
		# the fixture draft names adult 3, INF, CHA and CHB itself; the policy's rules still cascade
		self.assertEqual(len(m["inherited_rules"]), 3)
		self.assertEqual({r["source"] for r in m["inherited_rules"]}, {self.source})


# 2 adults; 2 adults + a CHB child (a code in any case); an unknown band; more children than STD holds
PARTIES = ({"adults": 2, "children": []}, {"adults": 2, "children": ["chb"]}, {"adults": 1, "children": ["XX"]},
           {"adults": 2, "children": ["CHA", "CHA", "CHB"]})


class TestSampleParties(WorkspaceCase):
	def test_sample_parties_are_priced_per_period(self):
		m = api.price_matrix(self.v, parties=json.dumps(PARTIES), party_room=self.std)
		two, family, unknown, crowded = m["party_cells"]
		self.assertEqual({p: D(c) for p, c in two["cells"].items()}, {"LOW": D("200"), "HIGH": D("240")})
		self.assertEqual(two["errors"], {})
		self.assertEqual({p: D(c) for p, c in family["cells"].items()}, {"LOW": D("250"), "HIGH": D("300")})
		kid = find(family["slots"]["LOW"], target="CHILD")
		self.assertEqual((kid["position"], kid["age_band"], D(kid["amount"]), kid["included"]), (1, "CHB", D("50"), False))
		chb = [r["name"] for r in api.get_version(self.v)["occupancy_rules"]
		       if r["target"] == "CHILD" and r["age_band"] == "CHB" and not r["combination"]]
		self.assertEqual([kid["rule_id"]], chb)
		adults = [s for s in family["slots"]["LOW"] if s["target"] == "ADULT"]
		self.assertEqual([(s["position"], s["rule_id"]) for s in adults], [(1, "GLOBAL:ADULT"), (2, "GLOBAL:ADULT")])
		# the same total a quote of that party has
		q = self.preview(children=json.dumps([8]))
		self.assertEqual(D(q["nights"][0]["occupancy"]), D(family["cells"]["LOW"]))
		# an unknown band and a party the room cannot host are errors of their cells
		self.assertEqual(unknown["cells"], {"LOW": None, "HIGH": None})
		self.assertEqual(set(unknown["errors"]), {"LOW", "HIGH"})
		self.assertEqual(crowded["cells"], {"LOW": None, "HIGH": None})
		self.assertIn("at most 2 children", crowded["errors"]["LOW"])

	def test_a_period_without_a_price_is_an_error_of_its_cell(self):
		data = self.payload()
		data["period_rates"].remove(find(data["period_rates"], room_type=self.std, period_code="HIGH"))
		m = api.price_matrix(self.v, data=data, parties=[{"adults": 2, "children": []}], party_room=self.dlx)
		cell = m["party_cells"][0]
		self.assertEqual(D(cell["cells"]["LOW"]), D("270"))            # 2 × 135
		self.assertIsNone(cell["cells"]["HIGH"])
		self.assertIn("no price", cell["errors"]["HIGH"])
		self.assertNotIn("HIGH", cell["slots"])

	def test_without_parties_there_are_no_party_cells(self):
		self.assertNotIn("party_cells", api.price_matrix(self.v))
		self.assertEqual(api.price_matrix(self.v, parties="[]", party_room=self.std)["party_cells"], [])

	def test_the_party_room_must_be_in_the_contract(self):
		parties = [{"adults": 2, "children": []}]
		for room in ("PW no such room", None, ""):
			with self.subTest(room=room), self.assertRaises(frappe.ValidationError) as cm:
				api.price_matrix(self.v, parties=parties, party_room=room)
			self.assertIn("is not a room of this contract", str(cm.exception))
		# a room of the hotel the unsaved draft no longer contracts
		data = self.payload()
		data["rooms"].remove(find(data["rooms"], room_type=self.dlx))
		data["period_rates"].remove(find(data["period_rates"], room_type=self.dlx))
		with self.assertRaises(frappe.ValidationError) as cm:
			api.price_matrix(self.v, data=data, parties=parties, party_room=self.dlx)
		self.assertIn("is not a room of this contract", str(cm.exception))
		self.assertEqual(len(api.price_matrix(self.v, parties=parties, party_room=self.dlx)["party_cells"]), 1)

	def test_malformed_parties_are_refused(self):
		for parties in ({"adults": 2}, [{"adults": 2}] * 13, [{"adults": 0, "children": []}],
		                [{"adults": 13, "children": []}], [{"adults": "two", "children": []}],
		                [{"adults": True, "children": []}], [{"adults": 2, "children": ["CHA"] * 9}],
		                [{"adults": 2, "children": "CHA"}], [{"adults": 2, "children": [7]}], ["2A"], "not json"):
			with self.subTest(parties=parties), self.assertRaises(frappe.ValidationError):
				api.price_matrix(self.v, parties=parties if isinstance(parties, str) else json.dumps(parties),
				                 party_room=self.std)

	def test_the_gate_is_the_matrixs_own(self):
		self.as_user(FINANCE)                                          # sees cost, does not edit contracts
		m = api.price_matrix(self.v, parties=[{"adults": 2, "children": ["CHB"]}], party_room=self.std)
		self.assertEqual(D(m["party_cells"][0]["cells"]["LOW"]), D("250"))
		self.as_user(AGENT)
		with self.assertRaises(frappe.PermissionError):
			api.price_matrix(self.v, parties=[{"adults": 2, "children": []}], party_room=self.std)


class TestAnchoredIssues(WorkspaceCase):
	def test_a_duplicated_room_rule_is_anchored_in_the_validation_json(self):
		data = self.payload()
		key = self.std_low(data)["_key"]
		data["period_rates"].append({**self.std_low(data), "_key": "dup", "value": "90"})
		report = json.loads(frappe.as_json(api.validate_version(self.v, data=as_json(data))))   # as the browser gets it
		dup = find(report["issues"], code="ROOM_RULE_DUPLICATE")
		self.assertEqual(dup["message"], f"room {self.std} has two rules for period LOW")
		self.assertEqual(dup["ref"], {"rule_id": f"~{key}", "rule_ids": [f"~{key}", "~dup"], "room_type": self.std,
		                              "period": "LOW"})
		# the saved draft's issue names the saved rows
		api.save_version(self.v, as_json(data))
		names = [r["name"] for r in api.get_version(self.v)["period_rates"]
		         if r["room_type"] == self.std and r["period_code"] == "LOW"]
		self.assertEqual(len(names), 2)
		dup = find(api.validate_version(self.v)["issues"], code="ROOM_RULE_DUPLICATE")
		self.assertEqual(dup["ref"], {"rule_id": names[0], "rule_ids": names, "room_type": self.std, "period": "LOW"})

	def test_an_issue_about_nothing_in_particular_has_no_ref(self):
		data = self.payload()
		data["boards"] = [b for b in data["boards"] if not b["is_base"]]
		issue = find(api.validate_version(self.v, data=data)["issues"], code="NO_BASE_BOARD")
		self.assertEqual(set(issue), {"level", "code", "message"})

	def test_board_rules_for_an_unknown_room_or_period_or_twice_the_same(self):
		data = self.payload()
		data["rooms"].remove(find(data["rooms"], room_type=self.dlx))            # the draft no longer sells DLX
		data["period_rates"].remove(find(data["period_rates"], room_type=self.dlx))
		supplement = {"board": "UAI", "op": "ADD", "adult_amount": "15", "child_percent": "50"}
		data["boards"] += [{**supplement, "room_type": self.dlx, "_key": "dlx-only"},
		                   {**supplement, "period_code": "NOPE", "_key": "orphan"},
		                   {**supplement, "adult_amount": "25", "_key": "twin"}]
		report = api.validate_version(self.v, data=data)
		self.assertFalse(report["ok"])
		room = find(report["issues"], code="BOARD_UNKNOWN_ROOM")
		self.assertEqual(room["message"], f"board rule ~dlx-only (UAI) names unknown room {self.dlx}")
		self.assertEqual(room["ref"], {"rule_id": "~dlx-only", "board": "UAI", "room_type": self.dlx})
		orphan = find(report["issues"], code="BOARD_UNKNOWN_PERIOD")
		self.assertEqual(orphan["message"], "board rule ~orphan (UAI) names unknown period NOPE")
		self.assertEqual(orphan["ref"], {"rule_id": "~orphan", "board": "UAI", "period": "NOPE"})
		twin = find(report["issues"], code="BOARD_DUPLICATE")
		uai = find(data["boards"], board="UAI", period_code=None, room_type=None)["_key"]
		self.assertEqual(twin["message"], "board UAI has 2 rules for the same room and period")
		self.assertEqual(twin["ref"], {"rule_id": f"~{uai}", "rule_ids": [f"~{uai}", "~twin"], "board": "UAI"})

	def test_publish_is_refused_for_an_orphan_board_period(self):
		data = self.payload()
		data["boards"].append({"board": "UAI", "op": "ADD", "adult_amount": "15", "child_percent": "50",
		                       "period_code": "NOPE", "_key": "orphan"})
		api.save_version(self.v, as_json(data))
		row = find(api.get_version(self.v)["boards"], period_code="NOPE")["name"]
		with self.assertRaises(frappe.ValidationError) as cm:
			contracts.publish(self.v)
		self.assertIn(f"board rule {row} (UAI) names unknown period NOPE", str(cm.exception))
		self.assertEqual(frappe.db.get_value("TEX Contract Version", self.v, "status"), "Draft")
		issue = find(api.validate_version(self.v)["issues"], code="BOARD_UNKNOWN_PERIOD")
		self.assertEqual(issue["ref"], {"rule_id": row, "board": "UAI", "period": "NOPE"})

	def test_the_fixture_contract_still_publishes(self):
		out = fx.create_contract(self.f, code="PW-S4")                 # publishes, as every suite's fixture does
		self.assertEqual(frappe.db.get_value("TEX Contract Version", out["version"], "status"), "Published")
		self.assertTrue(all(set(w) <= {"level", "code", "message", "ref"} and w["level"] == "WARNING"
		                    for w in out["warnings"]), out["warnings"])
		self.assertEqual(api.get_version(out["version"])["validation_report"], out["warnings"])
		published = contracts.publish(self.v)                          # this test case's draft too
		self.assertEqual(frappe.db.get_value("TEX Contract Version", published["version"], "status"), "Published")


# ─── slice S5: preview ages in months or by date of birth, apply_op_values, quote subtotals ───

CHILD_MESSAGE = "Child ages are whole years (0–17), {age_months} or {dob}."
SUBTOTALS = ("subtotal_adults", "subtotal_children", "subtotal_board")
SIX_PLACES = r"^\d+\.\d{6}$"


def pre_s5_preview(version: str, room_type: str, board: str, check_in: str, check_out: str, adults: int, children,
                   rate_plan: str, market: str, sale_at: str) -> dict:
	"""``preview_price`` of a saved version as it answered before S5 (its body, each child read with
	``int()``): the baseline a whole-year age must still give."""
	from frappe.utils import get_datetime, getdate

	from kamra.tex.commercial import context as ctxmod
	from kamra.tex.pricing import engine
	from kamra.tex.pricing.model import ChildSpec, StayRequest

	v = frappe.get_doc("TEX Contract Version", version)
	prop = scope.property_of("TEX Contract Version", version)
	at = get_datetime(sale_at)
	terms = contracts.load_terms(version) if v.status != "Draft" else contracts.build_terms(v, at=at)
	kids = tuple(ChildSpec(age=int(a)) for a in children)
	req = StayRequest(property=prop, room_type=room_type, board=board, rate_plan=rate_plan, check_in=getdate(check_in),
	                  check_out=getdate(check_out), adults=adults, children=kids, sale_at=at, market=market,
	                  channel="DIRECT_WEB", sell_currency=terms.currency, promo_codes=())
	return engine.price_stay(ctxmod.build_context(terms, req), req).to_dict(internal=True)


def without_subtotals(q: dict) -> dict:
	return {**q, "nights": [{k: v for k, v in n.items() if k not in SUBTOTALS} for n in q.get("nights") or []]}


class TestPreviewChildren(WorkspaceCase):
	def test_whole_years_price_as_before(self):
		pub = fx.create_contract(self.f, code="PW-S5")                 # published, as sold
		sale_at = str(frappe.utils.now_datetime().replace(microsecond=0))
		args = {"room_type": self.std, "board": "AI", "check_in": str(fx.d(6, 10)), "check_out": str(fx.d(6, 12)),
		        "adults": 2, "rate_plan": self.f["rate_plans"]["FLEX"], "market": "DE", "sale_at": sale_at}
		before = without_subtotals(pre_s5_preview(pub["version"], children=[8], **args))
		self.assertTrue(before["sellable"], before["reasons"])
		self.assertEqual([D(n["occupancy"]) for n in before["nights"]], [D("250"), D("250")])   # 100 + 100 + 50
		for kids in ([8], json.dumps([8]), ["8"], [8.0]):
			with self.subTest(children=kids):
				q = self.preview(pub["version"], children=kids, **args)
				self.assertEqual(without_subtotals(q), before)
		# 96 months is 8 years: the same price (the request records the months it was given)
		q = self.preview(pub["version"], children=[{"age_months": 96}], **args)
		self.assertEqual(q["request"]["children"], [{"age": None, "dob": None, "age_months": 96}])
		self.assertEqual((q["totals"], without_subtotals(q)["nights"]), (before["totals"], before["nights"]))
		# a draft too, and the other ages of the fixture's bands
		for kids in ([1], [4], [8, 1], [11, 3]):
			with self.subTest(draft=kids):
				self.assertEqual(without_subtotals(self.preview(children=kids, **args)),
				                 without_subtotals(pre_s5_preview(self.v, children=kids, **args)))

	def test_an_age_in_months_lands_in_its_band(self):
		q = self.preview(children=[{"age_months": 95}])                 # 7y11m: the 7–11.99 band
		self.assertTrue(q["sellable"], q.get("reasons"))
		child = find(q["explanation"], code="CHILD_SLOT")
		self.assertIn("(7y11m, Child B)", child["text"])
		self.assertEqual(D(q["nights"][0]["occupancy"]), D("250"))
		q = self.preview(children=[{"age_months": 83}])                 # 6y11m: still 3–6.99
		self.assertIn("(6y11m, Child A)", find(q["explanation"], code="CHILD_SLOT")["text"])

	def test_a_date_of_birth_is_checked_and_priced(self):
		today = frappe.utils.getdate()
		dob = frappe.utils.add_years(today, -8)
		q = self.preview(children=[{"dob": str(dob)}])
		self.assertTrue(q["sellable"], q.get("reasons"))
		self.assertIn("Child B)", find(q["explanation"], code="CHILD_SLOT")["text"])
		self.assertNotIn(str(dob), json.dumps(q["explanation"]))       # the explanation never carries the date
		for dob, message in ((frappe.utils.add_days(today, 1), "date of birth is in the future"),
		                     (frappe.utils.add_years(fx.d(6, 10), -18), "18 or older on arrival")):
			with self.subTest(dob=str(dob)), self.assertRaises(frappe.ValidationError) as cm:
				self.preview(children=[{"dob": str(dob)}])
			self.assertIn(message, str(cm.exception))
		for bad in ("2019-02-30", "yesterday", 20190101, None):
			with self.subTest(dob=bad), self.assertRaises(frappe.ValidationError) as cm:
				self.preview(children=[{"dob": bad}])
			self.assertIn(CHILD_MESSAGE, str(cm.exception))
			self.assertNotIn(str(bad), str(cm.exception).replace(CHILD_MESSAGE, ""))

	def test_what_is_not_an_age_is_refused(self):
		self.assertTrue(self.preview(children=["7"])["sellable"])
		self.assertIn("sellable", self.preview(children=[0, 17]))                     # the edges are ages
		for kids in ([7.5], ["7.5"], [True], [False], [-1], [18], ["-1"], ["seven"], [None], [""], [[7]],
		             [{"age_months": 216}], [{"age_months": -1}], [{"age_months": "95"}], [{"age_months": 95.5}],
		             [{"age_months": True}], [{"age": 7}], [{}], [{"age_months": 95, "dob": "2019-01-01"}],
		             {"age": 7}, 7, "not json"):
			with self.subTest(children=kids), self.assertRaises(frappe.ValidationError) as cm:
				self.preview(children=kids if isinstance(kids, str) else json.dumps(kids))
			if kids != "not json":
				self.assertIn(CHILD_MESSAGE, str(cm.exception))
		with self.assertRaises(frappe.ValidationError) as cm:
			self.preview(children=[5] * 13)
		self.assertIn("12", str(cm.exception))
		self.assertIn("sellable", self.preview(children=[5] * 12))                    # answered: over capacity


class TestApplyOpValues(WorkspaceCase):
	def call(self, values, op="ADJUST_PERCENT", value="10", version=None):
		return api.apply_op_values(version or self.v, values=json.dumps(values), op=op, value=value)

	def test_results_are_exact_strings_in_the_contract_currency(self):
		before = self.untouched()
		out = self.call(["70", "80.55", None, "", "10", "99.99"])
		self.assertEqual(out, [{"value": "77.00", "error": None}, {"value": "88.61", "error": None},
		                       {"value": None, "error": "NO_VALUE"}, {"value": None, "error": "NO_VALUE"},
		                       {"value": "11.00", "error": None}, {"value": "109.99", "error": None}])
		self.assertEqual(self.call(["10", "30"], op="SUBTRACT", value="20"),
		                 [{"value": None, "error": "NEGATIVE"}, {"value": "10.00", "error": None}])
		self.assertEqual(self.call(["100"], op="MULTIPLY", value="1.155"), [{"value": "115.50", "error": None}])
		self.assertEqual(self.call(["70"], op="PERCENT_OF", value="50"), [{"value": "35.00", "error": None}])
		self.assertEqual(self.call(["70", None], op="ABSOLUTE", value="82.5"),
		                 [{"value": "82.50", "error": None}, {"value": None, "error": "NO_VALUE"}])
		self.assertEqual(self.call(["70"], op="ADD", value="5"), [{"value": "75.00", "error": None}])
		self.assertEqual(self.call([]), [])
		self.assertEqual(self.untouched(), before)                                     # nothing written
		# in a 3-decimal currency
		fx.ensure_currency("KWD", "KD")
		kwd = frappe.get_doc({"doctype": "TEX Contract", "property": fx.PROPERTY, "contract_code": "PW-S5-KWD",
		                      "contract_name": "PW S5 KWD", "market": "DE", "contract_currency": "KWD",
		                      "pricing_basis": "PERSON", "status": "Draft"}).insert(ignore_permissions=True)
		draft = contracts.new_draft(kwd.name)
		self.assertEqual(self.call(["12.345"], version=draft), [{"value": "13.580", "error": None}])

	def test_only_who_edits_the_hotels_contracts(self):
		self.as_user(EDITOR)                                                           # contract.edit only
		self.assertEqual(self.call(["70"]), [{"value": "77.00", "error": None}])
		for user in (AGENT, FINANCE, FOREIGN):
			self.as_user(user)
			with self.subTest(user=user), self.assertRaises(frappe.PermissionError):
				self.call(["70"])

	def test_only_drafts(self):
		contracts.publish(self.v)
		with self.assertRaises(frappe.ValidationError) as cm:
			self.call(["70"])
		self.assertIn("draft", str(cm.exception))

	def test_malformed_calls_are_refused(self):
		self.assertEqual(len(self.call(["70"] * 500)), 500)
		for kw in ({"values": ["70"] * 501}, {"values": ["70"], "op": "INHERIT"}, {"values": ["70"], "op": "FIXED"},
		           {"values": ["70"], "op": "bogus"}, {"values": ["70"], "op": None}, {"values": ["70"], "value": ""},
		           {"values": ["70"], "value": None}, {"values": ["70"], "value": "1.0000000001"},
		           {"values": ["70"], "value": "ten"}, {"values": ["70.0000000001"]}, {"values": ["abc"]},
		           {"values": [True]}, {"values": [["70"]]}, {"values": [{"v": "70"}]}, {"values": ["70"], "value": [10]},
		           {"values": {"a": "70"}}, {"values": "70"}):
			with self.subTest(**{k: str(v)[:40] for k, v in kw.items()}), self.assertRaises(frappe.ValidationError):
				self.call(**kw)

	def test_the_base_room_is_adjusted_once_and_stored_as_a_price(self):
		# O4 (provisional): "+10%" on the base room's entered 100 → the server's 110.00, saved as ABSOLUTE
		data = self.payload()
		low = self.std_low(data)
		[result] = self.call([low["value"]], op="ADJUST_PERCENT", value="10")
		self.assertEqual(result, {"value": "110.00", "error": None})
		low.update(op="ABSOLUTE", value=result["value"])
		m = api.price_matrix(self.v, data=data)
		self.assertEqual(D(find(m["rooms"], room_type=self.std)["cells"]["LOW"]), D("110"))
		self.assertEqual(D(find(m["rooms"], room_type=self.dlx)["cells"]["LOW"]), D("148.5"))   # the formula follows
		api.save_version(self.v, as_json(data))
		self.assertEqual((self.std_low(api.get_version(self.v))["op"], self.std_low(api.get_version(self.v))["value"]),
		                 ("ABSOLUTE", "110"))


class TestQuoteSubtotals(WorkspaceCase):
	def test_each_night_carries_the_ladders_subtotals(self):
		q = self.preview(board="UAI", children=[8])
		self.assertTrue(q["sellable"], q.get("reasons"))
		n = q["nights"][0]
		for k in SUBTOTALS:
			self.assertRegex(n[k], SIX_PLACES)
		self.assertEqual((n["unit"], n["subtotal_adults"], n["subtotal_children"], n["occupancy"], n["board"],
		                  n["subtotal_board"]),
		                 ("100.000000", "200.000000", "250.000000", "250.000000", "50.000000", "300.000000"))
		self.assertEqual(n["subtotal_children"], n["occupancy"])
		# the same from the unsaved draft
		overlay = self.preview(board="UAI", children=[8], data=self.payload())
		self.assertEqual({k: overlay["nights"][0][k] for k in SUBTOTALS}, {k: n[k] for k in SUBTOTALS})

	def test_the_guest_view_never_carries_them(self):
		from kamra.tex.services import quoting

		q = self.preview(board="UAI", children=[8])
		for staff in (False, True):
			shown = quoting.strip_internal(json.loads(json.dumps(q)), staff=staff)
			self.assertEqual([set(n) for n in shown["nights"]], [{"date", "amount"}])
