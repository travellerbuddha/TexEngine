"""Booking-level money (G-05, G-06, G-08, G-84): terms that belong to the whole booking are
charged or granted once per booking, thresholds compare amounts in one currency, and a minimum
basket is the whole booking's."""

import unittest
from decimal import Decimal

from kamra.tex.pricing import engine, serialize
from kamra.tex.pricing.enums import ExtraPricingMode, FxMode, PromoAppliesTo, PromoStage, PromoValueType
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


class TestBookingBasket(unittest.TestCase):
	"""G-84 (ADR-057): a promotion's minimum basket is compared with the whole booking's basket
	(every room's accommodation and extras, in the sell currency), not with each room's. The
	rooms of one booking are priced together: alone first, then — when a minimum refused a
	promotion — again with the booking's basket, which each room's request records."""

	def promo(self, minimum="250", **kw):
		return Promotion("MB", "10 % from 250", PromoValueType.PERCENT, D("10"), min_basket=D(minimum), **kw)

	def rooms(self, promos=(), ctx=None, **kw):
		c = fx.ctx(promotions=tuple(promos), **(ctx or {}))
		return [(c, fx.req(**kw)), (c, fx.req(room_index=1, adults=1, **kw))]         # 200 and 100 EUR

	def test_rooms_that_qualify_together_get_the_promotion(self):
		rooms = self.rooms([self.promo()])
		alone = [engine.price_stay(c, r) for c, r in rooms]
		self.assertEqual([applied(q, "MB") for q in alone], [None, None])          # 200 and 100: each below 250
		together = engine.price_booking(rooms)
		self.assertEqual([applied(q, "MB").discount for q in together], [D("20"), D("10")])
		self.assertEqual([q.totals["total"] for q in together], [D("180.00"), D("90.00")])
		self.assertEqual([q.basket for q in together], [D("200.00"), D("100.00")])
		self.assertEqual([(q.request.booking_basket, q.request.booking_rooms) for q in together],
		                 [(D("300.00"), 2)] * 2)

	def test_the_explanation_names_the_booking_basket(self):
		q = engine.price_booking(self.rooms([self.promo()]))[1]
		step = next(s for s in q.explanation.to_list() if s["code"] == "BOOKING_BASKET")
		self.assertIn("300.00", step["text"])
		self.assertIn("2 rooms", step["text"])

	def test_a_booking_below_the_minimum_is_still_refused(self):
		together = engine.price_booking(self.rooms([self.promo(minimum="300.01")]))
		self.assertEqual([applied(q, "MB") for q in together], [None, None])
		out = next(p for p in together[0].promotions if p.promo_id == "MB")
		self.assertIn("booking basket 300.00 EUR (2 rooms) below minimum 300.01", out.reason)
		self.assertEqual((out.rule, out.minimum), ("MIN_BASKET", D("300.01")))

	def test_a_fixed_booking_coupon_is_still_granted_once(self):
		c = Promotion("C", "50 off", PromoValueType.FIXED_STAY, D("50"), code="SAVE", applies_to=PromoAppliesTo.TOTAL,
		              currency="EUR", min_basket=D("250"))
		alone = [engine.price_stay(x, r) for x, r in self.rooms([c], promo_codes=("SAVE",))]
		self.assertEqual([q.totals["discounts"] for q in alone], [D("0"), D("0")])
		together = engine.price_booking(self.rooms([c], promo_codes=("SAVE",)))
		self.assertEqual([q.totals["discounts"] for q in together], [D("50.00"), D("0")])
		self.assertIn("once per booking", next(p.reason for p in together[1].promotions if p.promo_id == "C"))

	def test_one_room_is_its_own_booking(self):
		c = fx.ctx(promotions=(self.promo(minimum="150"),))
		one = engine.price_booking([(c, fx.req())])[0]
		self.assertIsNone(one.request.booking_basket)
		self.assertEqual(one.to_dict(), engine.price_stay(c, fx.req()).to_dict())

	def test_rooms_are_priced_alone_when_no_minimum_refused_anything(self):
		together = engine.price_booking(self.rooms([self.promo(minimum="100")]))
		self.assertEqual([q.request.booking_basket for q in together], [None, None])
		self.assertTrue(all(applied(q, "MB") for q in together))

	def test_the_basket_counts_extras_and_a_per_booking_extra_once(self):
		ctx = {"extras": {"FEE": FEE}}
		self.assertEqual([q.basket for q in engine.price_booking(self.rooms([self.promo("340")], ctx=ctx))],
		                 [D("240.00"), D("100.00")])
		self.assertTrue(applied(engine.price_booking(self.rooms([self.promo("340")], ctx=ctx))[1], "MB"))
		self.assertIsNone(applied(engine.price_booking(self.rooms([self.promo("340.01")], ctx=ctx))[1], "MB"))

	def test_a_threshold_in_another_currency_is_converted_and_recorded(self):
		usd = {"USD": FxSnapshot("USD", "EUR", FxMode.MANUAL, D("0.9"))}
		together = engine.price_booking(self.rooms([self.promo("330", currency="USD")], ctx={"promo_fx": usd}))
		self.assertTrue(applied(together[0], "MB"))                                 # 330 USD = 297 EUR ≤ 300
		uses = [u for r in together[0].fx_rates for u in r["used_for"]]
		self.assertIn("promotion:MB:min_basket", uses)
		self.assertIsNone(applied(engine.price_booking(self.rooms([self.promo("334", currency="USD")],
		                                                          ctx={"promo_fx": usd}))[0], "MB"))

	def test_rooms_in_different_currencies_are_judged_alone(self):
		c = fx.ctx(promotions=(self.promo(),))
		t = fx.ctx(promotions=(self.promo(currency="EUR"),), fx=FxSnapshot("EUR", "TRY", FxMode.MANUAL, D("50")),
		           promo_fx={"EUR": FxSnapshot("EUR", "TRY", FxMode.MANUAL, D("50"))})
		mixed = engine.price_booking([(c, fx.req()), (t, fx.req(room_index=1, adults=1, sell_currency="TRY"))])
		self.assertEqual([q.request.booking_basket for q in mixed], [None, None])

	def test_a_changed_room_is_judged_with_the_other_rooms(self):
		c = fx.ctx(promotions=(self.promo(),))
		req = fx.req(room_index=1, adults=1)
		alone = engine.price_stay(c, req)
		again = engine.booking_request(req, alone, others_basket=D("200.00"), others_rooms=1)
		self.assertEqual((again.booking_basket, again.booking_rooms), (D("300.00"), 2))
		self.assertEqual(applied(engine.price_stay(c, again), "MB").discount, D("10"))
		# nothing refused for its minimum, or no other room: the room is its own booking
		self.assertIsNone(engine.booking_request(req, engine.price_stay(fx.ctx(), req), others_basket=D("200.00"),
		                                         others_rooms=1))
		self.assertIsNone(engine.booking_request(req, alone, others_basket=D("0"), others_rooms=0))

	def test_booking_pricing_is_deterministic_and_the_request_round_trips(self):
		a = engine.price_booking(self.rooms([self.promo()]))
		b = engine.price_booking(self.rooms([self.promo()]))
		self.assertEqual([q.explanation.to_list() for q in a], [q.explanation.to_list() for q in b])
		self.assertEqual(serialize.request_from_dict(serialize.request_to_dict(a[1].request)), a[1].request)
		self.assertEqual(a[1].to_dict()["basket"], "100.000000")               # recorded to 6 places

	def test_a_cost_stage_minimum_stays_the_rooms_own(self):
		# a contract offer on the supplier cost (contract currency) is never judged on the booking
		offer = Promotion("CO", "Cost offer", PromoValueType.PERCENT, D("5"), min_basket=D("250"),
		                  stage=PromoStage.COST)
		rooms = self.rooms([offer])
		alone = [engine.price_stay(c, r) for c, r in rooms]
		out = next(p for p in alone[0].promotions if p.promo_id == "CO")
		self.assertFalse(out.applied)
		self.assertEqual((out.rule, engine.basket_limited(alone[0])), ("", False))
		self.assertEqual([q.request.booking_basket for q in engine.price_booking(rooms)], [None, None])


if __name__ == "__main__":
	unittest.main()
