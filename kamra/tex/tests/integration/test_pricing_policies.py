"""Occupancy precedence v2 (G-30, G-31, ADR-042) through publish and pricing.

G-30: every live pricing policy that applies to a contract (global, hotel, market,
hotel + market) cascades into it, rule by rule, frozen at publish; a contract rule
beats every policy rule, a market policy beats a hotel one; one live policy per scope.
G-31: an infant is priced by a rule naming its band before any band-less rule, and
ambiguous occupancy rules block publishing.

Policies used (fx.PROPERTY, market DE; STD in LOW = 100 per person):
  global        bands INF 0–2.99 (infant), CHD 3–11.99 · INF ×0, CHD 50 %, adult 3 ×0.70
  hotel         no bands · adult 3 ×0.80, CHB 30 %
  DE            bands INF 0–2.99, CHA 3–6.99, CHB 7–11.99 · CHA 25 %, CHB 40 %
  hotel + DE    no bands · CHB inherit, combination 1+0 ×0.90
"""

import json

import frappe
from frappe.utils import add_to_date, now_datetime

from kamra.tex.commercial import contracts, revisions
from kamra.tex.money import D
from kamra.tex.pricing.model import ChildSpec, StayRequest
from kamra.tex.services import booking, modification, quoting
from kamra.tex.tests.integration import fixtures as fx
from kamra.tex.tests.integration.test_critical_journey import TexTestCase, pick, search_std

POLICY = "TEX Pricing Policy"
INF = {"band_code": "INF", "label": "Infant", "from_age": 0, "to_age": 2.99, "is_infant": 1}
DE_BANDS = [INF, {"band_code": "CHA", "label": "Child A", "from_age": 3, "to_age": 6.99},
            {"band_code": "CHB", "label": "Child B", "from_age": 7, "to_age": 11.99}]


def child(band, op, value=None, **kw):
	return {"target": "CHILD", "age_band": band, "op": op, "value": value, **kw}


def policy(name, *, property=None, market=None, bands=(), rules=(), live=True) -> str:
	payload = {"policy_name": name, "property": property, "market": market, "age_bands": list(bands),
	           "occupancy_rules": list(rules)}
	if live:
		return fx.ensure_live(POLICY, {"policy_name": name}, payload)
	return fx.ensure(POLICY, {"policy_name": name}, payload)


class PolicyCase(TexTestCase):
	def setUp(self):
		super().setUp()
		# only this test's policies are on sale (archived inside the test transaction, rolled back)
		for name in frappe.get_all(POLICY, filters={"tex_status": ("in", ["Active", "Superseded"])}, pluck="name"):
			revisions.archive(POLICY, name)
		self.std = frappe.db.get_value("Room Type", {"property": fx.PROPERTY, "room_type_code": "STD"})
		self.flex = frappe.db.get_value("Rate Plan", {"property": fx.PROPERTY, "code": "FLEX"})

	def four_policies(self) -> dict:
		return {
			"global": policy("PP Global", bands=[INF, {"band_code": "CHD", "label": "Child", "from_age": 3,
			                                           "to_age": 11.99}],
			                 rules=[child("INF", "MULTIPLY", 0), child("CHD", "PERCENT_OF", 50),
			                        {"target": "ADULT", "position": 3, "op": "MULTIPLY", "value": 0.7}]),
			"hotel": policy("PP Hotel", property=fx.PROPERTY,
			                rules=[{"target": "ADULT", "position": 3, "op": "MULTIPLY", "value": 0.8},
			                       child("CHB", "PERCENT_OF", 30)]),
			"market": policy("PP DE", market="DE", bands=DE_BANDS,
			                 rules=[child("CHA", "PERCENT_OF", 25), child("CHB", "PERCENT_OF", 40)]),
			"hotel_market": policy("PP Hotel DE", property=fx.PROPERTY, market="DE",
			                       rules=[child("CHB", "INHERIT"),
			                              {"target": "COMBINATION", "combination": "1+0", "op": "MULTIPLY",
			                               "value": 0.9}]),
		}

	def occupancy(self, version: str, adults: int, *ages) -> D:
		"""Occupancy amount of one LOW night in STD."""
		req = StayRequest(property=fx.PROPERTY, room_type=self.std, board="AI", check_in=fx.d(6, 10),
		                  check_out=fx.d(6, 11), adults=adults, children=tuple(ChildSpec(age=a) for a in ages),
		                  sale_at=now_datetime(), market="DE", channel="DIRECT_WEB", sell_currency="EUR",
		                  rate_plan=self.flex)
		q, _terms = quoting.price_request(version, req, check_capacity=False)
		self.assertTrue(q.sellable, q.reasons)
		return q.nights[0].occupancy

	def payload(self, version: str) -> dict:
		return json.loads(frappe.db.get_value("TEX Contract Version", version, "payload"))


class TestPolicyCascade(PolicyCase):
	def test_policies_cascade_into_a_contract_without_rules(self):
		p = self.four_policies()
		c = fx.create_contract(self.f, code="CASCADE", age_bands=[], occupancy_rules=[])
		v = c["version"]
		self.assertEqual(self.occupancy(v, 2, 8), D("240.00"))     # CHB: hotel+DE inherits → DE 40 %
		self.assertEqual(self.occupancy(v, 3), D("280.00"))        # adult 3: hotel ×0.80 beats global ×0.70
		self.assertEqual(self.occupancy(v, 2, 1), D("200.00"))     # INF: global ×0
		self.assertEqual(self.occupancy(v, 2, 4), D("225.00"))     # CHA: DE 25 %
		self.assertEqual(self.occupancy(v, 1), D("90.00"))         # 1+0: hotel+DE ×0.90
		payload = self.payload(v)
		self.assertEqual(payload["settings"]["occupancy_precedence"], 2)
		self.assertEqual([b["code"] for b in payload["age_bands"]], ["INF", "CHA", "CHB"])   # DE's, replaced
		self.assertEqual(sorted((r["base_level"], r["scope_weight"]) for r in payload["occupancy_rules"]),
		                 sorted([("GLOBAL", 0)] * 3 + [("HOTEL", 1)] * 2 + [("MARKET", 2)] * 2 + [("MARKET", 3)] * 2))
		sources = {r["source"] for r in payload["occupancy_rules"]}
		self.assertEqual(sources, {f"policy:{p['global']}/r1/global", f"policy:{p['hotel']}/r1/hotel",
		                           f"policy:{p['market']}/r1/market", f"policy:{p['hotel_market']}/r1/hotel+market"})
		unused = [i for i in c["warnings"] if i["code"] == "OCC_INHERITED_BAND_UNUSED"]
		self.assertEqual(len(unused), 1)                           # the global CHD rule: DE has no CHD band

	def test_market_policy_beats_hotel_policy(self):
		policy("PP Hotel own bands", property=fx.PROPERTY,
		       bands=[INF, {"band_code": "CHB", "label": "Child", "from_age": 3, "to_age": 11.99}],
		       rules=[child("INF", "MULTIPLY", 0), child("CHB", "PERCENT_OF", 30)])
		policy("PP DE", market="DE", bands=DE_BANDS, rules=[child("CHA", "PERCENT_OF", 25),
		                                                   child("CHB", "PERCENT_OF", 40)])
		c = fx.create_contract(self.f, code="MKT", age_bands=[], occupancy_rules=[])
		self.assertEqual(self.occupancy(c["version"], 2, 8), D("240.00"))   # DE's bands and its 40 %

	def test_a_contract_rule_beats_every_policy_rule(self):
		self.four_policies()
		c = fx.create_contract(self.f, code="OWN")                  # the version's own bands and rules
		self.assertEqual(self.occupancy(c["version"], 2, 8), D("250.00"))   # version CHB 50 %
		self.assertEqual(self.occupancy(c["version"], 3), D("270.00"))      # version adult 3 ×0.70

	def test_two_live_policies_of_one_scope_are_refused(self):
		de = policy("PP DE", market="DE", bands=DE_BANDS, rules=[child("CHB", "PERCENT_OF", 40)])
		twin = policy("PP DE twin", market="DE", rules=[child("CHB", "PERCENT_OF", 45)], live=False)
		with self.assertRaisesRegex(frappe.ValidationError, "already has a live pricing policy"):
			revisions.activate(POLICY, twin)
		self.assertEqual(frappe.db.get_value(POLICY, twin, "tex_status"), "Draft")
		# a new revision of the live policy is the way to change it
		rev = revisions.revise(POLICY, de)
		revisions.activate(POLICY, rev)
		self.assertEqual(frappe.db.get_value(POLICY, rev, "tex_status"), "Active")
		# the global scope (no hotel, no market) is a scope too
		first = policy("PP Global", bands=[INF], rules=[child("INF", "MULTIPLY", 0)])
		second = policy("PP Global twin", rules=[child("INF", "MULTIPLY", 0)], live=False)
		with self.assertRaisesRegex(frappe.ValidationError, "already has a live pricing policy"):
			revisions.activate(POLICY, second)
		# two live ones anyway (rows written around the guard): nothing is guessed, publish refuses
		frappe.db.set_value(POLICY, second, {"tex_status": "Active", "active_from": "2020-01-01 00:00:00"})
		c = fx.create_contract(self.f, code="AMB", publish=False)
		with self.assertRaises(frappe.ValidationError) as cm:
			contracts.publish(c["version"])
		self.assertIn(first, str(cm.exception))
		self.assertIn(second, str(cm.exception))
		report = contracts.validate_version(c["version"])
		self.assertFalse(report["ok"])
		self.assertEqual([i["code"] for i in report["issues"]], ["BUILD"])

	def test_policy_rows_are_validated(self):
		with self.assertRaisesRegex(frappe.ValidationError, "overlap"):
			policy("PP bad bands", market="DE", live=False, bands=[
				INF, {"band_code": "CHA", "from_age": 2, "to_age": 6.99}])
		lower = frappe.get_doc(POLICY, policy("PP lower", market="DE", live=False, bands=[
			{"band_code": " chb ", "from_age": 7, "to_age": 11.99}], rules=[child("chb", "PERCENT_OF", 40)]))
		self.assertEqual((lower.age_bands[0].band_code, lower.occupancy_rules[0].age_band), ("CHB", "CHB"))
		with self.assertRaisesRegex(frappe.ValidationError, "period"):
			policy("PP period", market="DE", live=False, rules=[child("CHB", "PERCENT_OF", 40, period_code="LOW")])
		other = "TEX Other Hotel"
		if not frappe.db.exists("Property", other):
			frappe.get_doc({"doctype": "Property", "property_name": other, "city": "Kemer", "country": "Turkey",
			                "currency": "EUR"}).insert(ignore_permissions=True)
		other_room = fx.ensure("Room Type", {"property": other, "room_type_code": "OSTD"},
		                       {"property": other, "room_type_code": "OSTD", "room_type_name": "Other standard",
		                        "base_price": 90, "adults_capacity": 2, "children_capacity": 1,
		                        "max_total_occupants": 3, "base_occupancy": 2})
		with self.assertRaisesRegex(frappe.ValidationError, "belongs to another hotel"):
			policy("PP room", property=fx.PROPERTY, live=False,
			       rules=[child("CHB", "PERCENT_OF", 40, room_type=other_room)])
		with self.assertRaisesRegex(frappe.ValidationError, "one hotel"):
			policy("PP global room", live=False, rules=[child("CHB", "PERCENT_OF", 40, room_type=self.std)])

	def test_policy_change_reaches_contract_only_on_republish(self):
		p = self.four_policies()
		c = fx.create_contract(self.f, code="REPUB", age_bands=[], occupancy_rules=[])
		v1 = c["version"]
		# a family books while v1 is on sale
		prop = search_std(fx.d(6, 10), fx.d(6, 11), [{"adults": 2, "children": [8]}])
		q = quoting.create_quote(pick(prop)["rooms"][0]["offer_key"])
		self.assertTrue(q["ok"], q)
		b = booking.create_booking(quote_ids=[q["quote_id"]], guest={
			"first_name": "Mia", "last_name": "Wolf", "email": "mia@example.com", "country": "Germany"},
			payment_method="Card", idempotency_key="g30-republish")
		res = b["rooms"][0]["reservation"]
		sold_at = json.loads(frappe.db.get_value("Reservation", res, "tex_pricing_snapshot"))["request"]["sale_at"]
		# the market policy changes: Child B pays 45 %
		draft = frappe.get_doc(POLICY, revisions.revise(POLICY, p["market"]))
		for r in draft.occupancy_rules:
			if r.age_band == "CHB":
				r.value = 45
		draft.save(ignore_permissions=True)
		revisions.activate(POLICY, draft.name)
		self.assertEqual(self.occupancy(v1, 2, 8), D("240.00"))     # the published version keeps its terms
		# republished (effective tomorrow), the new version inherits the change
		v2 = contracts.new_draft(c["contract"])
		eff = add_to_date(now_datetime(), days=1)
		contracts.publish(v2, effective_from=str(eff))
		self.assertEqual(self.occupancy(v2, 2, 8), D("245.00"))
		self.assertIn(f"policy:{draft.name}/r2/market", {r["source"] for r in self.payload(v2)["occupancy_rules"]})
		# the simulator prices a sale time with the version on sale then
		then = modification.simulate(res, sale_at=sold_at)
		later = modification.simulate(res, sale_at=str(add_to_date(eff, hours=1)))
		self.assertEqual((then["contract_version"], D(then["simulated"]["nights"][0]["occupancy"])), (v1, D("240")))
		self.assertEqual((later["contract_version"], D(later["simulated"]["nights"][0]["occupancy"])), (v2, D("245")))


class TestInfantPrecedence(PolicyCase):
	def test_infant_in_a_family_room_is_free(self):
		# child 2 of 2A+2C pays 25 %, but an infant is priced by the infant band (×0), not that band-less rule
		fx.create_contract(self.f, code="FAM", occupancy_rules=[
			*fx.default_occupancy_rules(),
			{"target": "CHILD", "position": 2, "combination": "2+2", "op": "PERCENT_OF", "value": 25}])
		fx.create_markup("DE", 7)
		offer = pick(search_std(fx.d(6, 10), fx.d(6, 13), [{"adults": 2, "children": [8, 1]}]))
		self.assertEqual(offer["total"], "802.50")                  # (100 + 100 + 50 + 0) × 1.07 × 3

	def test_ambiguous_rules_block_publish(self):
		c = fx.create_contract(self.f, code="AMBIG", publish=False, occupancy_rules=[
			*fx.default_occupancy_rules(),
			{"target": "CHILD", "position": 1, "combination": "2+*", "op": "PERCENT_OF", "value": 60},
			{"target": "CHILD", "position": 1, "combination": "*+2", "op": "PERCENT_OF", "value": 40}])
		with self.assertRaisesRegex(frappe.ValidationError, "Cannot publish"):
			contracts.publish(c["version"])
		codes = [i["code"] for i in contracts.validate_version(c["version"])["issues"] if i["level"] == "ERROR"]
		self.assertEqual(codes, ["OCC_AMBIGUOUS"])
