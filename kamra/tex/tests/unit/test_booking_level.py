"""Booking-level money (G-05, G-06, G-08): terms that belong to the whole booking are
charged or granted once per booking, and thresholds compare amounts in one currency."""

import unittest
from decimal import Decimal

from kamra.tex.pricing import engine
from kamra.tex.pricing.enums import ExtraPricingMode, FxMode, PromoAppliesTo, PromoValueType
from kamra.tex.pricing.model import ExtraDef, ExtraRequest, FxSnapshot, Promotion
from kamra.tex.tests.unit import fixtures as fx

D = Decimal


def price(**kw):
	ctx_kw = kw.pop("ctx", {})
	q = engine.price_stay(fx.ctx(**ctx_kw), fx.req(**kw))
	assert q.sellable, q.reasons
	return q


def applied(q, promo_id):
	return next((p for p in q.promotions if p.promo_id == promo_id and p.applied), None)


class TestMinBasketCurrency(unittest.TestCase):
	"""G-08: the minimum basket is compared in the sell currency."""

	def promo(self, currency="EUR", minimum="1000"):
		return Promotion("MB", "10 % over the minimum", PromoValueType.PERCENT, D("10"), min_basket=D(minimum),
		                 currency=currency)

	def test_threshold_is_converted_into_the_sell_currency(self):
		try_fx = FxSnapshot("EUR", "TRY", FxMode.MANUAL, D("50"))
		promo_fx = {"EUR": FxSnapshot("EUR", "TRY", FxMode.MANUAL, D("50"))}
		# 200 EUR = 10 000 TRY is below 1 000 EUR = 50 000 TRY, in any currency
		eur = price(ctx={"promotions": (self.promo(),)})
		tr = price(sell_currency="TRY", ctx={"promotions": (self.promo(),), "fx": try_fx, "promo_fx": promo_fx})
		self.assertIsNone(applied(eur, "MB"))
		self.assertIsNone(applied(tr, "MB"))
		self.assertIn("below minimum", next(p.reason for p in tr.promotions if p.promo_id == "MB"))
		# 150 EUR minimum = 7 500 TRY: the 10 000 TRY stay qualifies
		tr2 = price(sell_currency="TRY", ctx={"promotions": (self.promo(minimum="150"),), "fx": try_fx,
		                                      "promo_fx": promo_fx})
		self.assertEqual(applied(tr2, "MB").discount, D("1000.00"))

	def test_no_rate_for_the_threshold_currency_rejects_the_promotion(self):
		try_fx = FxSnapshot("EUR", "TRY", FxMode.MANUAL, D("50"))
		q = price(sell_currency="TRY", ctx={"promotions": (self.promo(minimum="10"),), "fx": try_fx})
		self.assertIsNone(applied(q, "MB"))
		self.assertIn("no FX", next(p.reason for p in q.promotions if p.promo_id == "MB"))

	def test_threshold_without_currency_is_in_the_sell_currency(self):
		self.assertIsNotNone(applied(price(ctx={"promotions": (self.promo(currency=None, minimum="150"),)}), "MB"))


if __name__ == "__main__":
	unittest.main()
