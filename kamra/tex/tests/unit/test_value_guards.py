"""G-18: a promotion never raises the price and a markup never sells for nothing."""

import unittest
from decimal import Decimal

from kamra.tex.pricing import engine
from kamra.tex.pricing.enums import Op, PromoValueType
from kamra.tex.pricing.model import MarkupRule, Promotion
from kamra.tex.tests.unit import fixtures as fx

D = Decimal


def quote(**ctx):
	return engine.price_stay(fx.ctx(**ctx), fx.req())


class TestPromotionValues(unittest.TestCase):
	def outcome(self, promo):
		q = quote(promotions=(promo,))
		self.assertTrue(q.sellable, q.reasons)
		return q, next(p for p in q.promotions if p.promo_id == promo.promo_id)

	def test_a_multiplier_above_one_is_refused_not_applied(self):
		q, o = self.outcome(Promotion("M", "Bad multiplier", PromoValueType.MULTIPLIER, D("1.2")))
		self.assertFalse(o.applied)
		self.assertIn("invalid", o.reason)
		self.assertEqual(q.totals["total"], D("200.00"))

	def test_a_negative_fixed_discount_is_refused_not_a_surcharge(self):
		q, o = self.outcome(Promotion("F", "Negative", PromoValueType.FIXED_STAY, D("-30"), currency="EUR"))
		self.assertFalse(o.applied)
		self.assertEqual(q.totals["total"], D("200.00"))

	def test_valid_values_still_apply(self):
		q, o = self.outcome(Promotion("M", "10 % off", PromoValueType.MULTIPLIER, D("0.9")))
		self.assertTrue(o.applied)
		self.assertEqual(q.totals["total"], D("180.00"))


class TestMarkupValues(unittest.TestCase):
	def test_a_markup_that_leaves_no_price_makes_the_stay_unsellable(self):
		q = quote(markups=(MarkupRule("MK", Op.ADJUST_PERCENT, D("-100"), property="HOTEL-A"),))
		self.assertFalse(q.sellable)
		self.assertEqual(q.reasons[0]["code"], "MARKUP_NO_PRICE")

	def test_a_discounting_markup_still_sells(self):
		q = quote(markups=(MarkupRule("MK", Op.ADJUST_PERCENT, D("-10"), property="HOTEL-A"),))
		self.assertTrue(q.sellable)
		self.assertEqual(q.totals["total"], D("180.00"))


if __name__ == "__main__":
	unittest.main()
