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



FEE = ExtraDef("FEE", "Booking fee", ExtraPricingMode.RESERVATION, "EUR", D("40"), mandatory=True)
TRF = ExtraDef("TRF", "Airport transfer", ExtraPricingMode.RESERVATION, "EUR", D("60"))
COT = ExtraDef("COT", "Baby cot", ExtraPricingMode.ROOM, "EUR", D("15"))


class TestPerBookingExtras(unittest.TestCase):
	"""G-05: a per-booking (RESERVATION-mode) extra is charged once per booking — on the
	booking's first room — however many rooms are booked."""

	def test_mandatory_per_booking_extra_is_charged_on_the_first_room_only(self):
		first = price(ctx={"extras": {"FEE": FEE}})
		second = price(room_index=1, adults=1, ctx={"extras": {"FEE": FEE}})
		self.assertEqual(first.totals["extras"], D("40.00"))
		self.assertEqual(second.totals["extras"], D("0"))
		self.assertEqual(first.totals["extras"] + second.totals["extras"], D("40.00"))

	def test_per_booking_extra_requested_on_another_room_is_refused(self):
		q = price(room_index=1, extras=(ExtraRequest("TRF"),), ctx={"extras": {"TRF": TRF}})
		trf = next(e for e in q.extras if e.code == "TRF")
		self.assertFalse(trf.ok)
		self.assertIn("once per booking", trf.reason)
		self.assertEqual(q.totals["extras"], D("0"))
		self.assertEqual(price(extras=(ExtraRequest("TRF"),), ctx={"extras": {"TRF": TRF}}).totals["extras"], D("60.00"))

	def test_per_room_extras_still_apply_to_every_room(self):
		q = price(room_index=1, extras=(ExtraRequest("COT"),), ctx={"extras": {"COT": COT}})
		self.assertEqual(q.totals["extras"], D("15.00"))


class TestBookingCoupons(unittest.TestCase):
	"""G-06: a fixed discount on the complete reservation (or on its extras) is granted
	once per booking; a percentage is the same share of every room."""

	def coupon(self, value_type=PromoValueType.FIXED_STAY, value="50", applies_to=PromoAppliesTo.TOTAL):
		return Promotion("C", "Booking coupon", value_type, D(value), code="SAVE", applies_to=applies_to,
		                 currency="EUR")

	def test_fixed_total_coupon_is_granted_once(self):
		c = self.coupon()
		first = price(promo_codes=("SAVE",), ctx={"promotions": (c,)})
		second = price(room_index=1, adults=1, promo_codes=("SAVE",), ctx={"promotions": (c,)})
		self.assertEqual(first.totals["discounts"], D("50.00"))
		self.assertEqual(second.totals["discounts"], D("0"))
		self.assertIn("once per booking", next(p.reason for p in second.promotions if p.promo_id == "C"))

	def test_fixed_extras_coupon_is_granted_once(self):
		c = self.coupon(value="10", applies_to=PromoAppliesTo.EXTRAS)
		kw = {"extras": (ExtraRequest("COT"),), "promo_codes": ("SAVE",)}
		first = price(**kw, ctx={"promotions": (c,), "extras": {"COT": COT}})
		second = price(room_index=1, **kw, ctx={"promotions": (c,), "extras": {"COT": COT}})
		self.assertEqual((first.totals["discounts"], second.totals["discounts"]), (D("10.00"), D("0")))

	def test_percentage_total_coupon_is_the_same_share_of_every_room(self):
		c = self.coupon(PromoValueType.PERCENT, "10")
		first = price(promo_codes=("SAVE",), ctx={"promotions": (c,)})
		second = price(room_index=1, adults=1, promo_codes=("SAVE",), ctx={"promotions": (c,)})
		self.assertEqual(first.totals["discounts"], (first.totals["subtotal"] + first.totals["discounts"]) / 10)
		self.assertEqual(second.totals["discounts"], (second.totals["subtotal"] + second.totals["discounts"]) / 10)
		self.assertGreater(second.totals["discounts"], D("0"))


if __name__ == "__main__":
	unittest.main()
