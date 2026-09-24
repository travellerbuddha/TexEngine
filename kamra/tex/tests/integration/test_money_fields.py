"""G-72 (R-02, R-03, ADR-055): TEX commercial decimal fields keep exactly what was typed.

Rates, occupancy values, board amounts, promotion and markup values, FX rates and policies,
cancellation/payment/tax values and loyalty values saved through the TEX API with up to 9
decimals are stored as typed (DECIMAL(21,9)), returned as exact decimal strings and read by
the engine's loaders as the exact Decimal; more decimals than a field keeps are refused, never
rounded silently. A published version's frozen payload keeps its hash through the migration
(p35), and a reservation sold before FX rates kept 10 significant digits reprices on its sold
terms to its sold total, while new quotes convert TRY → EUR at 0.02941176471, not 0.029412."""

import json
from unittest import mock

import frappe
from frappe.utils import add_days, add_to_date, get_datetime, getdate, now_datetime

from kamra.tex import money
from kamra.tex.api import contracts as contracts_api
from kamra.tex.api import loyalty as loyalty_api
from kamra.tex.api import policies as policies_api
from kamra.tex.commercial import context, contracts, revisions
from kamra.tex.crm import loyalty
from kamra.tex.money import D
from kamra.tex.pricing import serialize
from kamra.tex.services import booking, modification, quoting
from kamra.tex.tests.integration import fixtures as fx
from kamra.tex.tests.integration.test_critical_journey import TexTestCase, pick

# every field G-72 moved to 9 decimal places (ADR-055), with its fieldtype
G72 = {
	("TEX Price Period", "adjustment_value"): "Float", ("TEX Period Rate", "value"): "Float",
	("TEX Occupancy Rule", "value"): "Float", ("TEX Board Rule", "adult_amount"): "Float",
	("TEX Board Rule", "child_percent"): "Percent", ("TEX Contract Rate Plan", "value"): "Float",
	("TEX Contract Offer", "value"): "Float", ("TEX Markup Rule", "value"): "Float",
	("TEX Promotion", "value"): "Float", ("TEX FX Rate", "rate"): "Float", ("TEX FX Policy", "manual_rate"): "Float",
	("TEX FX Policy", "adjustment"): "Float", ("TEX Cancellation Rule", "penalty_value"): "Float",
	("TEX Cancellation Policy", "no_show_value"): "Float", ("TEX Payment Policy", "deposit_value"): "Float",
	("TEX Tax Rule", "rate"): "Percent", ("TEX Loyalty Tier", "earn_multiplier"): "Float",
	("TEX Loyalty Earn Rule", "rate"): "Float", ("TEX Loyalty Program", "point_value"): "Currency",
	("TEX Loyalty Program", "max_redeem_percent"): "Percent",
}


def stored(doctype: str, field: str, name: str) -> str:
	"""The column's own text, read without a float on the way."""
	return frappe.db.sql(f"SELECT CAST(`{field}` AS CHAR) FROM `tab{doctype}` WHERE name=%s", name)[0][0]


def by(rows, **match):
	return next(r for r in rows if all(r.get(k) == v for k, v in match.items()))


def _p35():
	from kamra.patches.tex import p35_money_field_types

	p35_money_field_types.execute()


class TestSchema(TexTestCase):
	def test_every_g72_field_keeps_nine_places(self):
		cols = {(t[3:], c): (typ, scale) for t, c, typ, scale in frappe.db.sql(
			"""SELECT table_name, column_name, data_type, numeric_scale FROM information_schema.columns
			   WHERE table_schema = DATABASE() AND table_name LIKE 'tabTEX %%'""")}
		for (doctype, field), fieldtype in G72.items():
			self.assertEqual(cols[(doctype, field)], ("decimal", 9), f"{doctype}.{field}: run the migration")
			df = frappe.get_meta(doctype).get_field(field)
			self.assertEqual((df.fieldtype, df.precision), (fieldtype, "9"), f"{doctype}.{field}")
		point = frappe.get_meta("TEX Loyalty Program").get_field("point_value")
		self.assertEqual(point.options, "currency")          # money, in the program's currency


class TestTypedValuesAreKept(TexTestCase):
	def draft(self) -> str:
		return fx.create_contract(self.f, code="G72D", publish=False)["version"]

	def test_contract_version_fields(self):
		name = self.draft()
		doc = contracts_api.get_version(name)
		dlx = self.f["room_types"]["DLX"]
		by(doc["periods"], period_code="LOW").update(adjustment_op="MULTIPLY", adjustment_value="1.123456789")
		by(doc["period_rates"], room_type=dlx)["value"] = "1.357913579"
		by(doc["occupancy_rules"], target="ADULT", position=3)["value"] = "0.333333333"
		by(doc["boards"], board="UAI").update(adult_amount="20.123456789", child_percent="33.333333333")
		by(doc["rate_plans"], rate_plan=self.f["rate_plans"]["NRF"])["value"] = "-12.345678901"
		doc["offers"] = [{"offer_code": "EB", "offer_name": "Early", "kind": "EARLY_BOOKING", "value_type": "PERCENT",
		                  "value": "7.777777777", "stage": "SELL"}]
		out = contracts_api.save_version(name, json.dumps({t: doc[t] for t in contracts_api.VERSION_TABLES}, default=str))

		expect = {("periods", "adjustment_value"): "1.123456789", ("period_rates", "value"): "1.357913579",
		          ("occupancy_rules", "value"): "0.333333333", ("boards", "adult_amount"): "20.123456789",
		          ("boards", "child_percent"): "33.333333333", ("rate_plans", "value"): "-12.345678901",
		          ("offers", "value"): "7.777777777"}
		rows = {("periods", "adjustment_value"): by(out["periods"], period_code="LOW"),
		        ("period_rates", "value"): by(out["period_rates"], room_type=dlx),
		        ("occupancy_rules", "value"): by(out["occupancy_rules"], target="ADULT", position=3),
		        ("boards", "adult_amount"): by(out["boards"], board="UAI"),
		        ("boards", "child_percent"): by(out["boards"], board="UAI"),
		        ("rate_plans", "value"): by(out["rate_plans"], rate_plan=self.f["rate_plans"]["NRF"]),
		        ("offers", "value"): out["offers"][0]}
		child = {"periods": "TEX Price Period", "period_rates": "TEX Period Rate",
		         "occupancy_rules": "TEX Occupancy Rule", "boards": "TEX Board Rule",
		         "rate_plans": "TEX Contract Rate Plan", "offers": "TEX Contract Offer"}
		for (table, field), text in expect.items():
			row = rows[(table, field)]
			self.assertEqual(stored(child[table], field, row["name"]), text, f"{table}.{field} stored")
			self.assertEqual(row[field], text, f"{table}.{field} returned")        # a string, not a float
		# the engine's loaders read the exact Decimals
		terms = contracts.build_terms(frappe.get_doc("TEX Contract Version", name))
		self.assertEqual(next(p.adjustment_value for p in terms.periods if p.code == "LOW"), D("1.123456789"))
		self.assertEqual(next(r.value for r in terms.room_rules if r.room_type == dlx), D("1.357913579"))
		self.assertIn(D("0.333333333"), {r.value for r in terms.occupancy_rules if r.position == 3})
		uai = next(b for b in terms.boards if b.board == "UAI")
		self.assertEqual((uai.adult_amount, uai.child_percent), (D("20.123456789"), D("33.333333333")))
		self.assertEqual(terms.rate_plans[self.f["rate_plans"]["NRF"]].value, D("-12.345678901"))
		self.assertEqual(terms.offers[0].value, D("7.777777777"))
		# and the payload froze them as typed
		payload = serialize.normalise_payload(serialize.terms_to_payload(terms))
		self.assertEqual(by(payload["boards"], board="UAI")["child_percent"], "33.333333333")

	def test_policies(self):
		def save(doctype, data):
			return policies_api.save_record(doctype, json.dumps(data))

		mk = save("TEX Markup Rule", {"label": "G72 markup", "property": fx.PROPERTY, "market": "DE",
		                              "op": "ADJUST_PERCENT", "value": "12.345678901"})
		promo = save("TEX Promotion", {"promotion_name": "G72 promo", "property": fx.PROPERTY, "kind": "MARKET",
		                               "trigger": "Automatic", "value_type": "PERCENT", "value": "7.777777777"})
		fxp = save("TEX FX Policy", {"property": fx.PROPERTY, "from_currency": "TRY", "to_currency": "EUR",
		                             "mode": "PROVIDER_PERCENT", "provider": "TCMB", "adjustment": "1.123456789",
		                             "manual_rate": "0.029411765"})
		cxl = save("TEX Cancellation Policy", {"policy_name": "G72 cxl", "property": fx.PROPERTY, "refundable": 1,
		                                       "no_show_type": "PERCENT", "no_show_value": "33.333333333",
		                                       "rules": [{"days_before_arrival": 3, "penalty_type": "PERCENT",
		                                                  "penalty_value": "66.666666667"}]})
		pay = save("TEX Payment Policy", {"policy_name": "G72 pay", "property": fx.PROPERTY,
		                                  "deposit_type": "PERCENT", "deposit_value": "12.345678901"})
		tax = save("TEX Tax Policy", {"policy_name": "G72 tax", "property": fx.PROPERTY, "currency": "EUR",
		                              "rules": [{"code": "VAT", "tax_name": "VAT", "kind": "PERCENT",
		                                         "rate": "7.123456789", "applies_to": "ACCOMMODATION"}]})
		for doctype, doc, field, text in (
			("TEX Markup Rule", mk, "value", "12.345678901"), ("TEX Promotion", promo, "value", "7.777777777"),
			("TEX FX Policy", fxp, "adjustment", "1.123456789"), ("TEX FX Policy", fxp, "manual_rate", "0.029411765"),
			("TEX Cancellation Policy", cxl, "no_show_value", "33.333333333"),
			("TEX Payment Policy", pay, "deposit_value", "12.345678901")):
			self.assertEqual(stored(doctype, field, doc["name"]), text, f"{doctype}.{field} stored")
			self.assertEqual(doc[field], text, f"{doctype}.{field} returned")    # as typed, a string
		self.assertEqual(stored("TEX Cancellation Rule", "penalty_value", cxl["rules"][0]["name"]), "66.666666667")
		self.assertEqual(cxl["rules"][0]["penalty_value"], "66.666666667")
		self.assertEqual(stored("TEX Tax Rule", "rate", tax["rules"][0]["name"]), "7.123456789")
		self.assertEqual(policies_api.get_record("TEX Markup Rule", mk["name"])["value"], "12.345678901")
		listed = by(policies_api.list_records("TEX Markup Rule", fx.PROPERTY), name=mk["name"])
		self.assertEqual(listed["value"], "12.345678901")

		# the loaders read what was typed
		for doctype, doc in (("TEX Markup Rule", mk), ("TEX Promotion", promo), ("TEX FX Policy", fxp)):
			revisions.activate(doctype, doc["name"], at="2020-01-01 00:00:00", backdate=True)
		now = now_datetime()
		self.assertEqual(by_id(context.markups(fx.PROPERTY, now), mk["name"]).value, D("12.345678901"))
		self.assertEqual(next(p for p in context.promotions(fx.PROPERTY, now) if p.promo_id == promo["name"]).value,
		                 D("7.777777777"))
		pol = context.fx_policy("TRY", "EUR", fx.PROPERTY, now)
		self.assertEqual((pol.adjustment, pol.manual_rate), (D("1.123456789"), D("0.029411765")))
		rules = context._table_rules(frappe.get_doc("TEX Tax Policy", tax["name"]).rules, "tax_policy:G72", "EUR")
		self.assertEqual({r.code: r.rate for r in rules}, {"VAT": D("7.123456789")})
		cp = contracts._cancellation_policy(cxl["name"])
		self.assertEqual((cp["no_show"]["value"], cp["rules"][0]["penalty_value"]), ("33.333333333", "66.666666667"))
		self.assertEqual(contracts._payment_policy(pay["name"])["deposit_value"], "12.345678901")

	def test_fx_rates(self):
		out = policies_api.add_manual_rate("EUR", "TRY", "34.123456789", str(getdate()))
		self.assertEqual(stored("TEX FX Rate", "rate", out["name"]), "34.123456789")
		rate = next(r for r in context.provider_rates("MANUAL", now_datetime()) if r.rate_id == out["name"])
		self.assertEqual(rate.rate, D("34.123456789"))
		listed = next(r for r in policies_api.fx_rates("MANUAL", days=2) if r["name"] == out["name"])
		self.assertEqual(listed["rate"], "34.123456789")

	def test_loyalty(self):
		name = loyalty_api.save_program({
			"program_name": "G72 club", "property": fx.PROPERTY, "enabled": 0, "currency": "EUR",
			"point_value": "0.004999999", "max_redeem_percent": "33.333333333", "pending_days": 0,
			"earn_rules": [{"basis": "MONEY", "rate": "0.999999999"}],
			"tiers": [{"tier_name": "Base", "min_points": 0, "earn_multiplier": "1.333333333"}]})["name"]
		prog = frappe.get_doc("TEX Loyalty Program", name)
		self.assertEqual(stored("TEX Loyalty Program", "point_value", name), "0.004999999")
		self.assertEqual(stored("TEX Loyalty Program", "max_redeem_percent", name), "33.333333333")
		self.assertEqual(stored("TEX Loyalty Earn Rule", "rate", prog.earn_rules[0].name), "0.999999999")
		self.assertEqual(stored("TEX Loyalty Tier", "earn_multiplier", prog.tiers[0].name), "1.333333333")
		read = loyalty_api.program(name)
		self.assertEqual((read["point_value"], read["max_redeem_percent"], read["earn_rules"][0]["rate"],
		                  read["tiers"][0]["earn_multiplier"]), ("0.004999999", "33.333333333", "0.999999999",
		                                                          "1.333333333"))
		# 1000 EUR at 0.999999999 point per EUR is 999 points (at 6 places the rate was 1: 1000)
		stay = frappe._dict(check_in_date=fx.d(6, 10), check_out_date=fx.d(6, 13), tex_currency="EUR",
		                    tex_total_amount=1000, room_type=None, tex_pricing_snapshot="{}")
		self.assertEqual(loyalty.points_for(prog, stay, 1)[0], 999)
		self.assertEqual(loyalty.points_for(prog, stay, prog.tiers[0].earn_multiplier)[0], 1333)

	def test_more_places_than_a_field_keeps_are_refused(self):
		name = self.draft()
		doc = contracts_api.get_version(name)
		by(doc["occupancy_rules"], target="ADULT", position=3)["value"] = "0.3333333333"
		with self.assertRaises(frappe.ValidationError) as cm:
			contracts_api.save_version(name, json.dumps({"occupancy_rules": doc["occupancy_rules"]}))
		self.assertIn("9 decimal places", str(cm.exception))
		self.assertEqual(stored("TEX Occupancy Rule", "value",
		                        by(doc["occupancy_rules"], target="ADULT", position=3)["name"]), "0.700000000")
		for doctype, data in (
			("TEX Markup Rule", {"label": "x", "property": fx.PROPERTY, "op": "ADD", "value": "1.0000000001"}),
			("TEX FX Policy", {"property": fx.PROPERTY, "from_currency": "TRY", "to_currency": "EUR",
			                   "mode": "MANUAL", "manual_rate": "0.0294117647"}),
			("TEX Promotion", {"promotion_name": "x", "property": fx.PROPERTY, "value": "1234567.123456789"}),
			("TEX Markup Rule", {"label": "x", "property": fx.PROPERTY, "op": "ADD", "value": "1e13"}),
		):
			with self.assertRaises(frappe.ValidationError, msg=str(data)):
				policies_api.save_record(doctype, json.dumps(data))
		with self.assertRaises(frappe.ValidationError):
			policies_api.add_manual_rate("EUR", "TRY", "34.1234567891", str(getdate()))
		with self.assertRaises(frappe.ValidationError):
			loyalty_api.save_program({"program_name": "x", "property": fx.PROPERTY, "enabled": 0,
			                          "currency": "EUR", "point_value": "0.0049999999"})
		# a script's binary float has no typed digits: stored as the column rounds it
		doc = frappe.get_doc({"doctype": "TEX Markup Rule", "label": "noise", "property": fx.PROPERTY, "op": "MULTIPLY",
		                      "value": 0.1 + 0.2}).insert(ignore_permissions=True)
		self.assertEqual(stored("TEX Markup Rule", "value", doc.name), "0.300000000")


def by_id(rules, rule_id):
	return next(r for r in rules if r.rule_id == rule_id)


class TestPublishedAndSoldTermsAreUnchanged(TexTestCase):
	def test_a_published_payload_keeps_its_hash_through_the_migration(self):
		out = fx.create_contract(self.f, code="G72P")
		before = frappe.db.get_value("TEX Contract Version", out["version"],
		                             ["payload", "payload_hash", "effective_from"], as_dict=True)
		_p35()
		after = frappe.db.get_value("TEX Contract Version", out["version"], ["payload", "payload_hash"], as_dict=True)
		self.assertEqual((after.payload, after.payload_hash), (before.payload, before.payload_hash))
		self.assertEqual(serialize.payload_hash(json.loads(after.payload)), before.payload_hash)
		contracts.clear_terms_cache()
		self.assertEqual(contracts.load_terms(out["version"]).payload_hash, before.payload_hash)
		# the version's own rows, read through the new field types, rebuild the same frozen payload
		version = frappe.get_doc("TEX Contract Version", out["version"])
		rebuilt = contracts.build_terms(version, at=get_datetime(before.effective_from))
		self.assertEqual(serialize.payload_hash(serialize.normalise_payload(serialize.terms_to_payload(rebuilt))),
		                 before.payload_hash)

	def test_a_reservation_sold_at_six_places_reprices_to_its_total(self):
		self.try_contract()
		self.try_rate()

		with mock.patch.object(money, "FX_SIGNIFICANT", 0, create=True):      # sold before G-72: 6 places
			res = self.book()
		sold = json.loads(frappe.db.get_value("Reservation", res, "tex_pricing_snapshot"))
		self.assertEqual([r["sell_rate"] for r in sold["fx_rates"]], ["0.029412"])
		self.assertEqual(sold["totals"]["total"], "4411.80")                   # 150,000 TRY × 0.029412

		_p35()
		for basis in ("ORIGINAL_VERSION", "ORIGINAL_SALE_DATE"):
			p = modification.propose(res, {}, basis=basis)
			self.assertEqual(p["proposed"]["totals"]["total"], "4411.80", basis)
			self.assertEqual(p["difference"], "0.00", basis)
			self.assertEqual([r["sell_rate"] for r in p["proposed"]["fx_rates"]], ["0.029412"], basis)
		# today's terms, and a new quote, convert at ten significant digits
		cur = modification.propose(res, {}, basis="CURRENT")["proposed"]
		self.assertEqual([r["sell_rate"] for r in cur["fx_rates"]], ["0.02941176471"])
		self.assertEqual(cur["totals"]["total"], "4411.76")                    # 150,000 / 34
		offer = pick(self.search())
		self.assertEqual(offer["total"], "4411.76")

	def test_a_reservation_sold_at_ten_significant_digits_keeps_its_rate(self):
		self.try_contract()
		self.try_rate()
		res = self.book()
		sold = json.loads(frappe.db.get_value("Reservation", res, "tex_pricing_snapshot"))
		self.assertEqual([r["sell_rate"] for r in sold["fx_rates"]], ["0.02941176471"])
		self.assertEqual(sold["totals"]["total"], "4411.76")
		# the reservation's informational rate is kept at its column's 9 places; a plain save of
		# the price-locked stay (the booking object still in memory) changes nothing commercial
		self.assertEqual(stored("Reservation", "tex_fx_rate", res), "0.029411765")
		frappe.get_doc("Reservation", res).save(ignore_permissions=True)
		for basis in ("ORIGINAL_VERSION", "ORIGINAL_SALE_DATE"):
			p = modification.propose(res, {}, basis=basis)
			self.assertEqual((p["proposed"]["totals"]["total"], p["difference"]), ("4411.76", "0.00"), basis)
			self.assertEqual([r["sell_rate"] for r in p["proposed"]["fx_rates"]], ["0.02941176471"], basis)
		p = modification.propose(res, {"check_out": add_days(fx.d(6, 13), 1)}, basis="ORIGINAL_SALE_DATE")
		modification.apply(p["proposal_token"], reason="one more night")
		after = json.loads(frappe.db.get_value("Reservation", res, "tex_pricing_snapshot"))
		self.assertEqual(after["totals"]["total"], "5882.35")                   # 200,000 / 34
		self.assertEqual(stored("Reservation", "tex_fx_rate", res), "0.029411765")

	def try_rate(self) -> None:
		now = now_datetime()
		frappe.db.delete("TEX FX Rate", {"provider": "TCMB", "base_currency": "EUR", "quote_currency": "TRY"})
		frappe.get_doc({"doctype": "TEX FX Rate", "provider": "TCMB", "base_currency": "EUR", "quote_currency": "TRY",
		                "rate_type": "FOREX_SELLING", "rate": 34, "rate_date": add_days(getdate(now), -1),
		                "fetched_at": add_to_date(now, days=-1), "source_ref": "test"}).insert(ignore_permissions=True)
		policy = frappe.get_doc({"doctype": "TEX FX Policy", "property": fx.PROPERTY, "from_currency": "TRY",
		                         "to_currency": "EUR", "mode": "PROVIDER", "provider": "TCMB",
		                         "rate_type": "FOREX_SELLING", "max_age_days": 4}).insert(ignore_permissions=True)
		revisions.activate("TEX FX Policy", policy.name, at="2020-01-01 00:00:00", backdate=True)

	def try_contract(self) -> None:
		"""A TRY contract (25,000 TRY per person and night) sold in EUR."""
		std = self.f["room_types"]["STD"]
		c = frappe.get_doc({"doctype": "TEX Contract", "property": fx.PROPERTY, "contract_code": "G72TRY",
		                    "contract_name": "TRY contract", "market": "DE", "contract_currency": "TRY",
		                    "pricing_basis": "PERSON", "status": "Draft", "sale_from": add_days(now_datetime(), -30),
		                    "sale_to": fx.STAY_TO, "stay_from": fx.STAY_FROM, "stay_to": fx.STAY_TO,
		                    }).insert(ignore_permissions=True)
		v = frappe.get_doc({
			"doctype": "TEX Contract Version", "contract": c.name, "prices_include_tax": 0,
			"rooms": [{"room_type": std, "is_base": 1}],
			"periods": [{"period_code": "ALL", "period_name": "All", "start_date": fx.STAY_FROM,
			             "end_date": fx.STAY_TO}],
			"period_rates": [{"room_type": std, "op": "ABSOLUTE", "value": 25000}],
			"age_bands": fx.default_age_bands(), "occupancy_rules": fx.default_occupancy_rules(),
			"boards": [{"board": "AI", "is_base": 1}],
			"rate_plans": [{"rate_plan": self.f["rate_plans"]["FLEX"], "refundable": 1}],
		}).insert(ignore_permissions=True)
		contracts.publish(v.name)

	def search(self) -> dict:
		res = quoting.search(properties=[fx.PROPERTY], check_in=fx.d(6, 10), check_out=fx.d(6, 13),
		                     rooms=[{"adults": 2}], market="DE", channel="DIRECT_WEB", currency="EUR")
		return res["properties"][0]

	def book(self) -> str:
		q = quoting.create_quote(pick(self.search())["rooms"][0]["offer_key"])
		self.assertTrue(q["ok"], q)
		b = booking.create_booking(quote_ids=[q["quote_id"]], guest={
			"first_name": "Ayla", "last_name": "Demir", "email": "ayla@example.com"}, payment_method="Card",
			confirm_without_payment=True, idempotency_key="g72-fx")
		return b["rooms"][0]["reservation"]
