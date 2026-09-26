"""K-1 (R-15, R-18): a published contract's fixed offer is in the contract's currency.

A EUR contract with a -50 EUR fixed stay offer sold in TRY at 51 takes 2,550 TRY off, not 50 TRY;
a TRY contract with a -2,000 TRY offer sold in EUR takes 39.22 EUR off a 600 EUR stay, not the
whole stay. The frozen payload records the offer's currency (a percentage offer keeps none); the
context converts the amount with the promotion FX snapshot (``promo_fx``), recorded like every
other rate (G-56)."""

import json

import frappe
from frappe.utils import now_datetime

from kamra.tex.commercial import context, contracts, revisions
from kamra.tex.money import D
from kamra.tex.pricing import engine
from kamra.tex.pricing.model import StayRequest
from kamra.tex.services import quoting
from kamra.tex.tests.integration import fixtures as fx
from kamra.tex.tests.integration.test_critical_journey import TexTestCase, pick

FIXED = {"offer_code": "K1FIX", "offer_name": "Fixed early booking", "kind": "EARLY_BOOKING",
         "value_type": "FIXED_STAY", "stage": "SELL", "stackable": 1}
PERCENT = {"offer_code": "K1PCT", "offer_name": "Percent early booking", "kind": "EARLY_BOOKING",
           "value_type": "PERCENT", "value": 10, "stage": "SELL", "stackable": 1}


def _policy(frm: str, to: str, rate) -> str:
	frappe.db.delete("TEX FX Policy", {"property": fx.PROPERTY, "from_currency": frm, "to_currency": to})
	doc = frappe.get_doc({"doctype": "TEX FX Policy", "property": fx.PROPERTY, "from_currency": frm,
	                      "to_currency": to, "mode": "MANUAL", "manual_rate": rate}).insert(ignore_permissions=True)
	revisions.activate("TEX FX Policy", doc.name, at="2020-01-01 00:00:00", backdate=True)
	return doc.name


class TestContractFixedOfferCurrency(TexTestCase):
	def _contract(self, currency: str, base, offers: list[dict]) -> dict:
		c = fx.create_contract(self.f, code=f"K1-{currency}", base=base, publish=False, offers=offers)
		frappe.db.set_value("TEX Contract", c["contract"], "contract_currency", currency)
		c.update(contracts.publish(c["version"]))
		return c

	def _price(self, c: dict, currency: str) -> dict:
		"""The stay priced from the frozen payload, as a booking prices it (internal view)."""
		terms = contracts.load_terms(c["version"])
		req = StayRequest(property=fx.PROPERTY, room_type=self.f["room_types"]["STD"], board="AI",
		                  rate_plan=self.f["rate_plans"]["FLEX"], check_in=fx.d(6, 10), check_out=fx.d(6, 13),
		                  adults=2, sale_at=now_datetime().replace(microsecond=0), market="DE",
		                  channel="DIRECT_WEB", sell_currency=currency)
		q = engine.price_stay(context.build_context(terms, req), req)
		self.assertTrue(q.sellable, q.reasons)
		return q.to_dict(internal=True)

	def _payload_offers(self, c: dict) -> dict:
		payload = json.loads(frappe.db.get_value("TEX Contract Version", c["version"], "payload"))
		return {o["id"]: o for o in payload["offers"]}

	def test_eur_contract_sold_in_try(self):
		c = self._contract("EUR", 100, [{**FIXED, "value": 50}, PERCENT])
		_policy("EUR", "TRY", 51)
		offers = self._payload_offers(c)
		self.assertEqual(offers["K1FIX"]["currency"], "EUR")
		self.assertIsNone(offers["K1PCT"]["currency"])
		q = self._price(c, "TRY")
		fixed = next(p for p in q["promotions"] if p["promo_id"] == "K1FIX")
		self.assertTrue(fixed["applied"], q["promotions"])
		self.assertEqual(D(fixed["discount"]), D("2550"))                        # 50 EUR × 51, not 50 TRY
		self.assertEqual(D(q["totals"]["accommodation_gross"]), D("30600.00"))   # 2 × 3 × 100 EUR × 51
		eur = next(r for r in q["fx_rates"] if (r["from"], r["to"]) == ("EUR", "TRY"))
		self.assertIn("promotion:K1FIX", eur["used_for"])

	def test_try_contract_sold_in_eur(self):
		c = self._contract("TRY", 5100, [{**FIXED, "value": 2000}])
		_policy("TRY", "EUR", "0.019607843")
		self.assertEqual(self._payload_offers(c)["K1FIX"]["currency"], "TRY")
		q = self._price(c, "EUR")
		self.assertEqual(D(q["totals"]["accommodation_gross"]), D("600.00"))
		self.assertEqual(D(q["totals"]["accommodation_discount"]), D("39.22"))   # 2,000 TRY / 51, not the stay
		self.assertEqual(D(q["totals"]["accommodation"]), D("560.78"))
		# the guest's search shows the same price
		res = quoting.search(properties=[fx.PROPERTY], check_in=fx.d(6, 10), check_out=fx.d(6, 13),
		                     rooms=[{"adults": 2}], market="DE", channel="DIRECT_WEB", currency="EUR")
		quote = pick(res["properties"][0])["rooms"][0]["quote"]
		self.assertEqual(D(quote["totals"]["accommodation"]), D("560.78"))
