"""G-56 (R-15): every FX conversion a quote makes is recorded — the room rate, extras,
fixed promotions (and their minimum-basket thresholds), coupons and fixed levies — with
the pair, the exact rate, where it came from and the policy that chose it, so a sold price
can be re-explained from the snapshot alone, and repriced with the same rates."""

from __future__ import annotations

import json
import unittest
from dataclasses import replace
from datetime import date, datetime
from decimal import Decimal

from kamra.tex.pricing import addons, engine, fx
from kamra.tex.pricing.enums import ExtraPricingMode, FxMode, PromoAppliesTo, PromoValueType, TaxKind
from kamra.tex.pricing.model import ExtraDef, ExtraRequest, FxSnapshot, Promotion, TaxRule
from kamra.tex.tests.unit import fixtures

D = Decimal
AT = datetime(2027, 1, 15, 10, 0)
EUR_TRY = FxSnapshot("EUR", "TRY", FxMode.PROVIDER_PERCENT, D("51"), provider="TCMB", provider_rate=D("50"),
                     provider_rate_id="FXR-EURTRY-0114", rate_date=date(2027, 1, 14), adjustment=D("2"),
                     policy_id="FXP-EUR", as_of=AT)
USD_TRY = FxSnapshot("USD", "TRY", FxMode.MANUAL, D("40"), policy_id="FXP-USD", as_of=AT)

SPA = ExtraDef("SPA", "Spa ritual", ExtraPricingMode.RESERVATION, "USD", D("30"), revision="EXT-00011")
EUR20 = Promotion("P-EUR20", "20 EUR off the stay", PromoValueType.FIXED_STAY, D("20"), currency="EUR")
MIN_USD = Promotion("P-MIN", "5 % above 100 USD", PromoValueType.PERCENT, D("5"), currency="USD",
                    min_basket=D("100"))
VOUCHER = Promotion("C-USD10", "10 USD voucher", PromoValueType.FIXED_STAY, D("10"), currency="USD",
                    code="USD10", kind="PROMO_CODE", applies_to=PromoAppliesTo.TOTAL)
CITY = TaxRule("CITY", "City tax", kind=TaxKind.PER_PERSON_NIGHT, amount=D("2"), currency="EUR",
               source="tax_policy:TXP-00003")


def ctx(**kw):
	base = dict(fx=EUR_TRY, extras={"SPA": SPA}, extra_fx={"USD": USD_TRY},
	            promotions=(EUR20, MIN_USD, VOUCHER), promo_fx={"EUR": EUR_TRY, "USD": USD_TRY},
	            tax_rules=(CITY,), tax_fx={"EUR": EUR_TRY})
	base.update(kw)
	return fixtures.ctx(**base)


def req(**kw):
	return fixtures.req(**{"sell_currency": "TRY", "extras": (ExtraRequest("SPA"),), "promo_codes": ("USD10",),
	                       **kw})


def fx_steps(q) -> list[dict]:
	return [s for s in q.explanation.to_list() if s["code"] == "FX"]


class TestTheQuoteRecordsEveryConversion(unittest.TestCase):
	def setUp(self):
		self.q = engine.price_stay(ctx(), req())
		self.assertTrue(self.q.sellable, self.q.reasons)

	def test_the_prices_use_the_rates(self):
		t = self.q.totals
		self.assertEqual(t["accommodation_gross"], D("10200.00"))     # 2 × 100 EUR × 51
		self.assertEqual(t["accommodation_discount"], D("1479.00"))   # 20 EUR × 51 = 1020, then 5 % of 9180
		self.assertEqual(t["extras"], D("1200.00"))                   # 30 USD × 40
		self.assertEqual(next(ln for ln in self.q.lines if ln.code == "C-USD10").amount, D("-400.00"))
		self.assertEqual(next(tl for tl in self.q.taxes if tl.code == "CITY").amount, D("204.00"))

	def test_each_rate_is_recorded_once_with_what_it_converted(self):
		rates = self.q.to_dict()["fx_rates"]
		self.assertEqual([(r["from"], r["to"]) for r in rates], [("EUR", "TRY"), ("USD", "TRY")])
		eur, usd = rates
		self.assertEqual(eur["used_for"], ["accommodation", "promotion:P-EUR20", "tax:CITY", "cost"])
		self.assertEqual(usd["used_for"], ["extra:SPA", "promotion:P-MIN:min_basket", "promotion:C-USD10"])
		self.assertEqual({k: eur[k] for k in ("mode", "sell_rate", "provider", "provider_rate", "provider_rate_id",
		                                     "rate_date", "adjustment", "policy_id", "as_of")},
		                 {"mode": "PROVIDER_PERCENT", "sell_rate": "51.000000", "provider": "TCMB",
		                  "provider_rate": "50.000000", "provider_rate_id": "FXR-EURTRY-0114",
		                  "rate_date": "2027-01-14", "adjustment": "2.000000", "policy_id": "FXP-EUR",
		                  "as_of": "2027-01-15T10:00:00"})
		self.assertEqual((usd["mode"], usd["sell_rate"], usd["policy_id"], usd["provider"]),
		                 ("MANUAL", "40.000000", "FXP-USD", None))

	def test_each_conversion_is_explained_with_its_source(self):
		steps = fx_steps(self.q)
		self.assertEqual([s["params"]["use"] for s in steps],
		                 ["accommodation", "extra:SPA", "promotion:P-MIN:min_basket", "promotion:P-EUR20",
		                  "promotion:C-USD10", "tax:CITY", "cost"])
		spa = next(s for s in steps if s["params"]["use"] == "extra:SPA")
		self.assertEqual((spa["params"]["from"], spa["params"]["to"], spa["params"]["rate"], spa["params"]["policy"]),
		                 ("USD", "TRY", "40.000000", "FXP-USD"))
		self.assertIn("1 USD = 40.000000 TRY", spa["text"])
		self.assertIn("manual rate", spa["text"])
		promo = next(s for s in steps if s["params"]["use"] == "promotion:P-EUR20")
		self.assertIn("1 EUR = 51.000000 TRY", promo["text"])
		self.assertIn("TCMB 50.000000 of 2027-01-14", promo["text"])
		self.assertIn("FXP-EUR", promo["text"])
		self.assertEqual((promo["params"]["provider"], promo["params"]["rate_date"], promo["params"]["as_of"]),
		                 ("TCMB", "2027-01-14", "2027-01-15T10:00:00"))

	def test_the_explanation_and_record_are_deterministic(self):
		again = engine.price_stay(ctx(), req())
		self.assertEqual(json.dumps(self.q.to_dict(), sort_keys=True), json.dumps(again.to_dict(), sort_keys=True))

	def test_guests_never_see_the_rates(self):
		self.assertNotIn("fx_rates", self.q.to_dict(internal=False))

	def test_a_same_currency_sale_records_no_conversion(self):
		q = engine.price_stay(fixtures.ctx(), fixtures.req())
		self.assertEqual(q.to_dict()["fx_rates"], [])
		self.assertEqual(fx_steps(q), [])


class TestRecordedRatesReprice(unittest.TestCase):
	def test_the_record_rebuilds_the_snapshots_it_was_made_from(self):
		q = engine.price_stay(ctx(), req())
		pins = fx.pins(q.to_dict()["fx_rates"], origin="reservation:RES-1")
		self.assertEqual(set(pins), {("EUR", "TRY"), ("USD", "TRY")})
		self.assertEqual(replace(pins[("EUR", "TRY")], origin=None), EUR_TRY)
		self.assertEqual(replace(pins[("USD", "TRY")], origin=None), USD_TRY)
		self.assertEqual(pins[("EUR", "TRY")].origin, "reservation:RES-1")

	def test_a_reprice_on_the_recorded_rates_gives_the_sold_price(self):
		sold = engine.price_stay(ctx(), req())
		pins = fx.pins(sold.to_dict()["fx_rates"], origin="reservation:RES-1")
		eur, usd = pins[("EUR", "TRY")], pins[("USD", "TRY")]
		again = engine.price_stay(ctx(fx=eur, extra_fx={"USD": usd}, promo_fx={"EUR": eur, "USD": usd},
		                              tax_fx={"EUR": eur}), req())
		self.assertEqual(again.totals, sold.totals)
		strip = lambda rates: [{k: v for k, v in r.items() if k != "origin"} for r in rates]  # noqa: E731
		self.assertEqual(strip(again.to_dict()["fx_rates"]), strip(sold.to_dict()["fx_rates"]))
		self.assertEqual({r["origin"] for r in again.to_dict()["fx_rates"]}, {"reservation:RES-1"})
		self.assertIn("recorded", next(s for s in fx_steps(again) if s["params"]["use"] == "extra:SPA")["text"])

	def test_a_legacy_snapshot_pins_its_room_rate(self):
		# a snapshot sold before G-56 records the room rate only (``fx``)
		legacy = {"fx": EUR_TRY.to_dict(), "extras": [{"code": "SPA", "fx_rate": "40.000000"}]}
		pins = fx.pins(fx.recorded(legacy), origin="reservation:RES-0")
		self.assertEqual(set(pins), {("EUR", "TRY")})
		self.assertEqual(pins[("EUR", "TRY")].sell_rate, D("51"))

	def test_identity_is_never_recorded_or_pinned(self):
		self.assertEqual(fx.recorded({"fx": fixtures.eur().to_dict()}), [])


class TestAddonsRecordTheirRates(unittest.TestCase):
	def test_an_addon_records_the_rate_of_its_extra(self):
		t = fixtures.terms()
		q = addons.price_addons(terms=t, request=fixtures.req(sell_currency="TRY"), requests=(ExtraRequest("SPA"),),
		                        catalog={"SPA": SPA}, today=date(2027, 5, 1), now=datetime(2027, 5, 1, 9, 0),
		                        extra_fx={"USD": USD_TRY}, tax_rules=())
		self.assertTrue(q.ok, q.reasons)
		out = q.to_dict(internal=True)
		self.assertEqual([(r["from"], r["sell_rate"], r["used_for"]) for r in out["fx_rates"]],
		                 [("USD", "40.000000", ["extra:SPA"])])
		self.assertEqual([s["params"]["use"] for s in out["explanation"] if s["code"] == "FX"], ["extra:SPA"])
		self.assertNotIn("fx_rates", q.to_dict(internal=False))


if __name__ == "__main__":
	unittest.main()


class TestLegacySnapshotLinePins(unittest.TestCase):
	"""Review of G-56: a snapshot sold before G-56 also recorded each converted extra's and
	levy's rate on its line (``extras[].fx_rate`` with the extra revision, ``taxes[].fx_rate``
	with the tax policy): those rates are pinned too, keyed by the currency the caller reads
	from the revision / policy."""

	def legacy(self):
		sold = engine.price_stay(ctx(), req()).to_dict()
		return {k: v for k, v in sold.items() if k != "fx_rates"}, sold

	def test_line_rates_become_pins(self):
		legacy, _sold = self.legacy()
		record = fx.recorded(legacy, extra_currency={"EXT-00011": "USD"},
		                     tax_currency={"tax_policy:TXP-00003": "EUR"})
		pins = fx.pins(record, origin="reservation:RES-0")
		self.assertEqual(set(pins), {("EUR", "TRY"), ("USD", "TRY")})
		self.assertEqual(pins[("EUR", "TRY")], replace(EUR_TRY, origin="reservation:RES-0"))   # the full room rate
		usd = pins[("USD", "TRY")]
		self.assertEqual((usd.mode, usd.sell_rate, usd.policy_id), (FxMode.RECORDED, D("40"), None))
		self.assertEqual(next(r for r in record if r["from"] == "USD")["used_for"], ["extra:SPA"])
		self.assertIn("rate recorded on the sold line", fx.describe(usd))

	def test_a_reprice_on_legacy_line_pins_gives_the_sold_price(self):
		legacy, sold = self.legacy()
		pins = fx.pins(fx.recorded(legacy, extra_currency={"EXT-00011": "USD"}), origin="reservation:RES-0")
		eur, usd = pins[("EUR", "TRY")], pins[("USD", "TRY")]
		again = engine.price_stay(ctx(fx=eur, extra_fx={"USD": usd}, promo_fx={"EUR": eur, "USD": usd},
		                              tax_fx={"EUR": eur}), req())
		self.assertEqual(again.to_dict()["totals"], sold["totals"])

	def test_without_the_line_currency_nothing_is_guessed(self):
		legacy, _sold = self.legacy()
		self.assertEqual({(r["from"], r["to"]) for r in fx.recorded(legacy)}, {("EUR", "TRY")})
		# an extra added after booking is carried at its own price, never repriced: not a pin
		legacy["extras"] = [{**e, "addon": "ADD-1"} for e in legacy["extras"]]
		self.assertEqual({(r["from"], r["to"]) for r in fx.recorded(legacy, extra_currency={"EXT-00011": "USD"})},
		                 {("EUR", "TRY")})
