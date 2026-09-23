"""Extras added after booking (G-22): priced on their own, the stay stays price-locked."""

import unittest
from dataclasses import replace
from datetime import date, datetime
from decimal import Decimal

from kamra.tex.pricing import addons, engine
from kamra.tex.pricing.enums import ExtraPricingMode as M
from kamra.tex.pricing.enums import FxMode
from kamra.tex.pricing.model import ExtraDayAvailability, ExtraDef, ExtraRequest, FxSnapshot, TaxRule
from kamra.tex.tests.unit import fixtures

D = Decimal
SPA = ExtraDef("SPA", "Spa", M.UNIT, "EUR", D("30"), tax_category="SERVICE")
DINNER = ExtraDef("DINNER", "Dinner", M.SERVICE_DATE, "EUR", D("45"), tax_category="FOOD", max_quantity=4)
TRF = ExtraDef("TRF", "Transfer", M.RESERVATION, "EUR", D("40"), tax_category="TRANSFER")
VAT = (TaxRule("VAT-SVC", "VAT", rate=D("20"), applies_to=frozenset({"EXTRA:SERVICE", "EXTRA:TRANSFER"})),
       TaxRule("VAT-FOOD", "VAT", rate=D("10"), applies_to=frozenset({"EXTRA:FOOD"})),
       TaxRule("CITY", "City tax", rate=D("2")))                        # on the stay only: never on an add-on
STAY = fixtures.req(check_in=date(2027, 6, 2), check_out=date(2027, 6, 5), children=(8,))
TODAY, NOW = date(2027, 5, 1), datetime(2027, 5, 1, 10, 0)


def price(*reqs, terms=None, request=STAY, catalog=None, **kw):
	base = dict(terms=terms or fixtures.terms(), request=request, requests=tuple(reqs),
	            catalog=catalog or {"SPA": SPA, "DINNER": DINNER, "TRF": TRF}, today=TODAY, now=NOW,
	            extra_fx={}, tax_rules=VAT)
	base.update(kw)
	return addons.price_addons(**base)


class TestPriceAddons(unittest.TestCase):
	def test_only_the_extras_are_priced_with_their_taxes(self):
		q = price(ExtraRequest("SPA", 2), ExtraRequest("DINNER", 1, (date(2027, 6, 3),)))
		self.assertTrue(q.ok, q.reasons)
		self.assertEqual([(ln.kind.value, ln.code, ln.amount) for ln in q.lines],
		                 [("EXTRA", "DINNER", D("45.00")), ("EXTRA", "SPA", D("60.00")),
		                  ("TAX", "VAT-FOOD", D("4.50")), ("TAX", "VAT-SVC", D("12.00"))])
		self.assertEqual((q.totals["extras"], q.totals["tax"], q.totals["total"]), (D("105.00"), D("16.50"),
		                                                                           D("121.50")))
		self.assertIn("ADDON_NO_PROMOTIONS", [s.code for s in q.explanation.steps])

	def test_inclusive_prices_keep_their_total(self):
		q = price(ExtraRequest("SPA"), terms=replace(fixtures.terms(), prices_include_tax=True))
		self.assertEqual((q.totals["total"], q.totals["tax"], q.totals["tax_added"]), (D("30.00"), D("5.00"), D("0")))

	def test_a_refused_extra_refuses_the_add_on(self):
		for req, reason in ((ExtraRequest("GOLF"), "not available to add"),
		                    (ExtraRequest("TRF"), "charged once per booking, on room 1"),
		                    (ExtraRequest("DINNER", 1, ()), "choose at least one service date")):
			q = price(req, request=replace(STAY, room_index=1) if req.code == "TRF" else STAY)
			self.assertFalse(q.ok, req)
			self.assertIn(reason, q.reasons[0]["message"], req)
			self.assertEqual(q.totals["total"], D("0"))

	def test_days_already_past_or_inside_the_cutoff_are_refused(self):
		stay = fixtures.req(check_in=date(2027, 5, 1), check_out=date(2027, 5, 4))     # arriving today
		q = price(ExtraRequest("DINNER", 1, (date(2027, 5, 1),)), request=stay,
		          catalog={"DINNER": replace(DINNER, cutoff_hours=24)})
		self.assertEqual(q.reasons[0]["code"], "ADDON_TOO_LATE")
		ok = price(ExtraRequest("DINNER", 1, (date(2027, 5, 3),)), request=stay,
		           catalog={"DINNER": replace(DINNER, cutoff_hours=24)})
		self.assertTrue(ok.ok, ok.reasons)

	def test_the_quantity_limit_counts_what_is_already_booked(self):
		q = price(ExtraRequest("DINNER", 2, (date(2027, 6, 3),)), booked={"DINNER": 3})
		self.assertEqual(q.reasons[0]["code"], "ADDON_QUANTITY")
		self.assertTrue(price(ExtraRequest("DINNER", 1, (date(2027, 6, 3),)), booked={"DINNER": 3}).ok)

	def test_a_full_day_refuses_a_limited_extra(self):
		q = price(ExtraRequest("SPA"), availability={"SPA": {date(2027, 6, 2): ExtraDayAvailability(0)}})
		self.assertEqual((q.ok, q.reasons[0]["message"]), (False, "Spa: sold out on 2027-06-02"))

	def test_another_currency_is_converted(self):
		eur_try = FxSnapshot("EUR", "TRY", FxMode.PROVIDER, D("50"), provider="TCMB", provider_rate=D("50"))
		q = price(ExtraRequest("SPA"), request=replace(STAY, sell_currency="TRY"), extra_fx={"EUR": eur_try})
		self.assertEqual((q.currency, q.totals["extras"]), ("TRY", D("1500.00")))


class TestMergeAddons(unittest.TestCase):
	def test_the_stay_is_untouched_and_the_total_adds_up(self):
		stay = engine.price_stay(fixtures.ctx(extras={"TRF": TRF}, tax_rules=VAT),
		                         replace(STAY, extras=(ExtraRequest("TRF"),))).to_dict(internal=True)
		add = price(ExtraRequest("SPA", 2)).to_dict()
		merged = addons.merge_addons(stay, add, addon_id="ADD-1", at="2027-05-01 10:00:00")
		keep = [ln for ln in stay["lines"] if ln["kind"] != "TAX"]
		self.assertEqual([ln for ln in merged["lines"] if ln["kind"] == "ACCOMMODATION"],
		                 [ln for ln in keep if ln["kind"] == "ACCOMMODATION"])
		self.assertEqual(D(merged["totals"]["total"]), D(stay["totals"]["total"]) + D(add["totals"]["total"]))
		self.assertEqual(D(merged["totals"]["extras"]), D(stay["totals"]["extras"]) + D("60"))
		self.assertEqual([e["code"] for e in merged["extras"]], ["TRF", "SPA"])            # nothing dropped
		self.assertEqual(merged["extras"][1]["addon"], "ADD-1")
		self.assertEqual([a["id"] for a in merged["addons"]], ["ADD-1"])
		self.assertEqual(merged["totals"]["margin"], stay["totals"]["margin"])             # cost unchanged
		twice = addons.merge_addons(merged, price(ExtraRequest("SPA")).to_dict(), addon_id="ADD-2", at="x")
		self.assertEqual(D(twice["totals"]["total"]), D(merged["totals"]["total"]) + D("36.00"))
		self.assertEqual(D(stay["totals"]["total"]), D(engine.price_stay(
			fixtures.ctx(extras={"TRF": TRF}, tax_rules=VAT), replace(STAY, extras=(ExtraRequest("TRF"),))).total))
