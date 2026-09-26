"""K-1 (R-15, R-18): a contract offer's fixed amount is in the contract's currency.

The contract screen shows a fixed offer in the contract currency; a stay sold in another
currency converts it with the explicit promotion FX snapshot (promo currency → sell currency),
never takes the raw figure as sell currency. Without that rate the offer is not applied and the
explanation names the missing pair. A payload frozen before offers carried a currency is read
with the contract's currency. Percentage, multiplier and free-night offers are unchanged."""

from __future__ import annotations

import unittest
from datetime import date
from decimal import Decimal

from kamra.tex.pricing import engine, serialize
from kamra.tex.pricing.enums import FxMode, Op, PromoStage, PromoValueType
from kamra.tex.pricing.model import FxSnapshot, Promotion, RoomRule
from kamra.tex.tests.unit import fixtures

D = Decimal
EUR_TRY = FxSnapshot("EUR", "TRY", FxMode.MANUAL, D("51"))
TRY_EUR = FxSnapshot("TRY", "EUR", FxMode.MANUAL, D("0.0196078431"))     # 1 EUR = 51 TRY


def offer(value_type: PromoValueType, value: str, **kw) -> Promotion:
	return Promotion("K1", "Early booking", value_type, D(value), kind="EARLY_BOOKING", source="contract", **kw)


def published(t, *, drop_currency: bool = False):
	"""The terms as priced after a publish: frozen to the payload and read back. ``drop_currency``:
	a payload frozen before offers carried a currency (the key is absent)."""
	payload = serialize.normalise_payload(serialize.terms_to_payload(t))
	if drop_currency:
		for o in payload["offers"]:
			o.pop("currency", None)
	return serialize.terms_from_payload(payload)


def eur_terms(*offers):
	return fixtures.terms(offers=tuple(offers))


def try_terms(*offers):
	# 5,100 TRY a person a night: 2 adults × 3 nights = 30,600 TRY = 600 EUR at 51
	return fixtures.terms(currency="TRY", offers=tuple(offers),
	                      room_rules=(RoomRule("R-STD", "STD", None, Op.ABSOLUTE, D("5100")),))


def eur_to_try(t, **kw):
	ctx = fixtures.ctx(t, fx=EUR_TRY, **({"promo_fx": {"EUR": EUR_TRY}} | kw))
	return engine.price_stay(ctx, fixtures.req(sell_currency="TRY"))


def try_to_eur(t, **kw):
	ctx = fixtures.ctx(t, fx=TRY_EUR, **({"promo_fx": {"TRY": TRY_EUR}} | kw))
	return engine.price_stay(ctx, fixtures.req(sell_currency="EUR", check_out=date(2027, 6, 5)))


def outcome(q, promo_id="K1"):
	return next(p for p in q.promotions if p.promo_id == promo_id)


class TestFixedOfferInContractCurrency(unittest.TestCase):
	def test_eur_contract_sold_in_try(self):
		"""-50 EUR at 51 is 2,550 TRY off a 10,200 TRY stay (2 adults × 100 EUR × 51)."""
		q = eur_to_try(published(eur_terms(offer(PromoValueType.FIXED_STAY, "50"))))
		self.assertTrue(q.sellable, q.reasons)
		self.assertEqual(q.totals["accommodation_gross"], D("10200.00"))
		self.assertEqual(q.totals["accommodation_discount"], D("2550.00"))
		self.assertEqual(outcome(q).discount, D("2550"))
		rates = q.to_dict()["fx_rates"]
		self.assertEqual([(r["from"], r["to"]) for r in rates], [("EUR", "TRY")])
		self.assertIn("promotion:K1", rates[0]["used_for"])

	def test_try_contract_sold_in_eur(self):
		"""-2,000 TRY at 1/51 is 39.22 EUR off a 600 EUR stay, never 2,000 EUR (the stay at 0)."""
		q = try_to_eur(published(try_terms(offer(PromoValueType.FIXED_STAY, "2000"))))
		self.assertTrue(q.sellable, q.reasons)
		self.assertEqual(q.totals["accommodation_gross"], D("600.00"))
		self.assertEqual(q.totals["accommodation_discount"], D("39.22"))
		self.assertEqual(q.totals["accommodation"], D("560.78"))

	def test_fixed_per_night(self):
		"""-10 EUR a night over 2 nights at 51 is 1,020 TRY."""
		t = published(eur_terms(offer(PromoValueType.FIXED_NIGHT, "10")))
		ctx = fixtures.ctx(t, fx=EUR_TRY, promo_fx={"EUR": EUR_TRY})
		q = engine.price_stay(ctx, fixtures.req(sell_currency="TRY", check_out=date(2027, 6, 4)))
		self.assertEqual(q.totals["accommodation_discount"], D("1020.00"))

	def test_the_frozen_payload_carries_the_contract_currency(self):
		t = published(eur_terms(offer(PromoValueType.FIXED_STAY, "50")))
		self.assertEqual(t.offers[0].currency, "EUR")
		self.assertEqual(serialize.terms_to_payload(t)["offers"][0]["currency"], "EUR")

	def test_same_currency_unchanged(self):
		t = published(eur_terms(offer(PromoValueType.FIXED_STAY, "50")))
		q = engine.price_stay(fixtures.ctx(t), fixtures.req())
		self.assertEqual(q.totals["accommodation_discount"], D("50.00"))
		self.assertEqual(q.to_dict()["fx_rates"], [])


class TestMissingFx(unittest.TestCase):
	def test_no_rate_no_discount_and_the_pair_is_explained(self):
		q = eur_to_try(published(eur_terms(offer(PromoValueType.FIXED_STAY, "50"))), promo_fx={})
		self.assertTrue(q.sellable, q.reasons)
		o = outcome(q)
		self.assertFalse(o.applied)
		self.assertEqual(o.discount, D(0))
		self.assertEqual(q.totals["accommodation_discount"], D("0.00"))
		self.assertEqual(q.totals["accommodation"], D("10200.00"))
		steps = [s for s in q.explanation.to_list() if s["code"] == "PROMO_NO_FX"]
		self.assertEqual(len(steps), 1, q.explanation.summary_lines())
		self.assertEqual((steps[0]["params"]["from_currency"], steps[0]["params"]["to_currency"]), ("EUR", "TRY"))
		self.assertIn("EUR→TRY", steps[0]["text"])
		self.assertEqual(steps[0]["rule"]["rule_id"], "K1")

	def test_a_rate_to_another_currency_is_not_used(self):
		eur_gbp = FxSnapshot("EUR", "GBP", FxMode.MANUAL, D("0.85"))
		q = eur_to_try(published(eur_terms(offer(PromoValueType.FIXED_STAY, "50"))), promo_fx={"EUR": eur_gbp})
		self.assertFalse(outcome(q).applied)
		self.assertEqual(q.totals["accommodation_discount"], D("0.00"))


class TestLegacyPayload(unittest.TestCase):
	def test_an_offer_without_a_currency_is_in_the_contract_currency(self):
		t = published(eur_terms(offer(PromoValueType.FIXED_STAY, "50")), drop_currency=True)
		self.assertEqual(t.offers[0].currency, "EUR")
		q = eur_to_try(t)
		self.assertEqual(q.totals["accommodation_discount"], D("2550.00"))

	def test_a_null_currency_is_in_the_contract_currency(self):
		payload = serialize.normalise_payload(serialize.terms_to_payload(
			try_terms(offer(PromoValueType.FIXED_STAY, "2000"))))
		payload["offers"][0]["currency"] = None
		q = try_to_eur(serialize.terms_from_payload(payload))
		self.assertEqual(q.totals["accommodation_discount"], D("39.22"))


class TestOtherValuesUnchanged(unittest.TestCase):
	def test_percent(self):
		"""10 % of 10,200 TRY; the offer keeps no currency, so the payload is unchanged."""
		src = eur_terms(offer(PromoValueType.PERCENT, "10"))
		t = published(src)
		self.assertIsNone(t.offers[0].currency)
		self.assertEqual(serialize.terms_to_payload(t)["offers"], serialize.normalise_payload(
			serialize.terms_to_payload(src))["offers"])
		q = eur_to_try(t)
		self.assertEqual(q.totals["accommodation_discount"], D("1020.00"))

	def test_multiplier_and_free_nights(self):
		mult = eur_to_try(published(eur_terms(offer(PromoValueType.MULTIPLIER, "0.8"))))
		self.assertEqual(mult.totals["accommodation_discount"], D("2040.00"))
		free = published(eur_terms(offer(PromoValueType.FREE_NIGHTS, "0", free_nights_stay=3, free_nights_pay=2)))
		self.assertIsNone(free.offers[0].currency)
		ctx = fixtures.ctx(free, fx=EUR_TRY, promo_fx={"EUR": EUR_TRY})
		q = engine.price_stay(ctx, fixtures.req(sell_currency="TRY", check_out=date(2027, 6, 5)))
		self.assertEqual(q.totals["accommodation_discount"], D("10200.00"))

	def test_cost_stage_fixed_offer_stays_in_the_contract_currency(self):
		"""A cost offer lowers the contract cost (EUR) before FX: -50 EUR of cost = 2,550 TRY."""
		t = published(eur_terms(offer(PromoValueType.FIXED_STAY, "50", stage=PromoStage.COST)))
		q = eur_to_try(t, promo_fx={})
		self.assertEqual(q.totals["accommodation_gross"], D("7650.00"))


if __name__ == "__main__":
	unittest.main()
