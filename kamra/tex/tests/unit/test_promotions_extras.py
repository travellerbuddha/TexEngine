"""Promotion engine (R-18), coupons (R-20) and extras (R-19)."""

import unittest
from datetime import date, timedelta
from decimal import Decimal

from kamra.tex.pricing import extras, promotions
from kamra.tex.pricing.enums import ExtraPricingMode, FxMode, PromoValueType, StackingMode, StayMatch
from kamra.tex.pricing.model import ExtraDef, ExtraPriceRule, ExtraRequest, FxSnapshot, Promotion

D = Decimal
CI, CO = date(2027, 7, 10), date(2027, 7, 17)
NIGHTS = tuple(CI + timedelta(days=i) for i in range(7))


def pctx(**kw):
	base = dict(sale_date=date(2027, 1, 15), check_in=CI, check_out=CO, nights=NIGHTS, market="DE",
	            channel="DIRECT_WEB", room_type="STD", board="AI", rate_plan=None, contract="C1", member=False,
	            codes=frozenset(), extras=frozenset(), basket=D("1400"), sell_currency="EUR")
	base.update(kw)
	return promotions.PromoContext(**base)


def P(pid, vt=PromoValueType.PERCENT, value="10", **kw):
	return Promotion(pid, kw.pop("name", pid), vt, D(value), **kw)


def amounts(v="200"):
	return {n: D(v) for n in NIGHTS}


class TestEligibility(unittest.TestCase):
	def reason(self, p, **kw):
		return promotions.check_eligibility(p, pctx(**kw))

	def test_early_booking_sale_window(self):
		eb = P("EB", sale_from=date(2027, 1, 1), sale_to=date(2027, 3, 31), kind="EARLY_BOOKING")
		self.assertIsNone(self.reason(eb))
		self.assertIn("after", self.reason(eb, sale_date=date(2027, 4, 1)))

	def test_last_minute_lead_time(self):
		lm = P("LM", max_lead_days=14)
		self.assertIn("at most 14", self.reason(lm))
		self.assertIsNone(self.reason(lm, sale_date=date(2027, 7, 1)))
		self.assertIsNotNone(self.reason(P("EB", min_lead_days=200)))

	def test_long_stay_and_markets_channels(self):
		self.assertIsNone(self.reason(P("LOS", min_nights=7)))
		self.assertIn("shorter", self.reason(P("LOS", min_nights=8)))
		self.assertIn("market", self.reason(P("UK", markets=frozenset({"UK"}))))
		self.assertIn("channel", self.reason(P("CC", channels=frozenset({"CALL_CENTER"}))))
		self.assertIn("room", self.reason(P("R", room_types=frozenset({"DLX"}))))
		self.assertIn("members", self.reason(P("M", member_only=True)))
		self.assertIsNone(self.reason(P("M", member_only=True), member=True))

	def test_codes_and_limits(self):
		code = P("C", code="SUMMER")
		self.assertEqual(self.reason(code), "code not entered")
		self.assertIsNone(self.reason(code, codes=frozenset({"SUMMER"})))
		limited = P("C", code="SUMMER", usage_limit=10, per_guest_limit=1)
		ctx = pctx(codes=frozenset({"SUMMER"}))
		self.assertEqual(promotions.check_eligibility(limited, ctx, (10, 0)), "usage limit reached")
		self.assertEqual(promotions.check_eligibility(limited, ctx, (3, 1)), "per-guest limit reached")
		self.assertIsNone(promotions.check_eligibility(limited, ctx, (3, 0)))
		self.assertIn("minimum", self.reason(P("B", min_basket=D("2000"))))

	def test_stay_windows(self):
		any_ = P("A", stay_from=date(2027, 7, 15), stay_to=date(2027, 7, 31))
		self.assertEqual(promotions.eligible_nights(any_, pctx()), NIGHTS[5:])
		all_ = P("B", stay_from=date(2027, 7, 15), stay_to=date(2027, 7, 31), stay_match=StayMatch.ALL_NIGHTS)
		self.assertIn("outside", self.reason(all_))
		arr = P("C", stay_from=date(2027, 7, 1), stay_to=date(2027, 7, 10), stay_match=StayMatch.ARRIVAL)
		self.assertEqual(promotions.eligible_nights(arr, pctx()), NIGHTS)
		dep = P("D", stay_from=date(2027, 7, 1), stay_to=date(2027, 7, 10), stay_match=StayMatch.DEPARTURE)
		self.assertIn("outside", self.reason(dep))

	def test_package_requires_extras(self):
		pk = P("PK", requires_extras=frozenset({"SPA"}))
		self.assertIn("package", self.reason(pk))
		self.assertIsNone(self.reason(pk, extras=frozenset({"SPA", "TRF"})))


class TestCombination(unittest.TestCase):
	def test_exclusive_wins_alone(self):
		chosen, rejected = promotions.select(
			(P("EB", priority=5), P("VIP", exclusive=True, priority=1), P("LOS", priority=3)), pctx())
		self.assertEqual([p.promo_id for p in chosen], ["VIP"])
		self.assertTrue(all("excluded by exclusive" in r.reason for r in rejected))

	def test_incompatible_group_and_non_stackable(self):
		chosen, rejected = promotions.select(
			(P("EB10", priority=9, group="EB"), P("EB15", priority=5, group="EB"), P("LOS", priority=4),
			 P("NS", priority=3, stackable=False)), pctx())
		self.assertEqual([p.promo_id for p in chosen], ["EB10", "LOS"])
		reasons = {r.promo_id: r.reason for r in rejected}
		self.assertIn("incompatible group", reasons["EB15"])
		self.assertIn("not stackable", reasons["NS"])

	def test_non_stackable_first_closes(self):
		chosen, rejected = promotions.select((P("NS", priority=9, stackable=False), P("LOS", priority=1)), pctx())
		self.assertEqual([p.promo_id for p in chosen], ["NS"])
		self.assertIn("not combinable", rejected[0].reason)

	def test_sequential_vs_additive(self):
		promos = [P("A", value="10"), P("B", value="20")]
		seq, _ = promotions.apply_promotions(promos, amounts("100"), pctx(), StackingMode.SEQUENTIAL, "EUR")
		add, _ = promotions.apply_promotions(promos, amounts("100"), pctx(), StackingMode.ADDITIVE, "EUR")
		self.assertEqual(seq[NIGHTS[0]], D("72.0"))   # 100 × 0.9 × 0.8
		self.assertEqual(add[NIGHTS[0]], D("70"))     # 100 − 10 − 20

	def test_free_nights_cheapest(self):
		am = amounts("100")
		am[NIGHTS[3]] = D("80")
		res, out = promotions.apply_promotions([P("7=6", PromoValueType.FREE_NIGHTS, "0", free_nights_stay=7,
		                                          free_nights_pay=6)], am, pctx(), StackingMode.SEQUENTIAL, "EUR")
		self.assertEqual(res[NIGHTS[3]], D(0))
		self.assertEqual(out[0].discount, D("80"))

	def test_fixed_values_and_fx(self):
		res, out = promotions.apply_promotions([P("F", PromoValueType.FIXED_STAY, "250")], amounts("100"),
		                                       pctx(), StackingMode.SEQUENTIAL, "EUR")
		self.assertEqual(out[0].discount, D("250"))
		self.assertEqual(res[NIGHTS[-1]], D(0))
		self.assertEqual(res[NIGHTS[-3]], D(50))
		try_fx = {"TRY": FxSnapshot("TRY", "EUR", FxMode.MANUAL, D("0.02"))}
		_, out2 = promotions.apply_promotions([P("N", PromoValueType.FIXED_NIGHT, "500", currency="TRY")],
		                                      amounts("100"), pctx(), StackingMode.SEQUENTIAL, "EUR", fx=try_fx)
		self.assertEqual(out2[0].discount, D("70.00"))   # 7 × (500 TRY × 0.02)
		_, out3 = promotions.apply_promotions([P("N", PromoValueType.FIXED_NIGHT, "500", currency="GBP")],
		                                      amounts("100"), pctx(), StackingMode.SEQUENTIAL, "EUR")
		self.assertFalse(out3[0].applied)

	def test_value_added_and_multiplier(self):
		res, out = promotions.apply_promotions(
			[P("VA", PromoValueType.VALUE_ADDED, "0", value_added="Free spa"), P("M", PromoValueType.MULTIPLIER,
			                                                                    "0.85")],
			amounts("100"), pctx(), StackingMode.SEQUENTIAL, "EUR")
		self.assertEqual(out[0].value_added, "Free spa")
		self.assertEqual(res[NIGHTS[0]], D("85.00"))


def xctx(**kw):
	base = dict(sale_date=date(2027, 1, 15), check_in=CI, check_out=CO, nights=7, market="DE",
	            channel="DIRECT_WEB", room_type="STD", adults=2, children=1, infants=1, sell_currency="EUR")
	base.update(kw)
	return extras.ExtraContext(**base)


def X(code, mode, amount="10", **kw):
	return ExtraDef(code, kw.pop("name", code), mode, kw.pop("currency", "EUR"), D(amount), **kw)


class TestExtras(unittest.TestCase):
	def price(self, d, qty=1, dates=(), **kw):
		return extras.price_extra(d, ExtraRequest(d.code, qty, tuple(dates)), xctx(**kw))

	def test_modes(self):
		cases = [
			(X("R", ExtraPricingMode.RESERVATION, "50"), D("50")),
			(X("RM", ExtraPricingMode.ROOM, "30"), D("30")),
			(X("P", ExtraPricingMode.PERSON, "20", child_amount=D("10"), infant_amount=D("0")), D("50")),
			(X("A", ExtraPricingMode.ADULT, "20"), D("40")),
			(X("C", ExtraPricingMode.CHILD, "20", child_amount=D("15")), D("15")),
			(X("I", ExtraPricingMode.INFANT, "20", infant_amount=D("5")), D("5")),
			(X("N", ExtraPricingMode.NIGHT, "10"), D("70")),
			(X("PN", ExtraPricingMode.PERSON_NIGHT, "10", child_amount=D("5"), infant_amount=D("0")), D("175")),
			(X("U", ExtraPricingMode.UNIT, "12"), D("36")),
		]
		for d, expected in cases:
			qty = 3 if d.code == "U" else 1
			self.assertEqual(self.price(d, qty).amount, expected, d.code)

	def test_service_date_and_date_rules(self):
		gala = X("GALA", ExtraPricingMode.SERVICE_DATE, "100", price_rules=(
			ExtraPriceRule("peak", D("150"), service_from=date(2027, 7, 14), service_to=date(2027, 7, 14)),))
		o = self.price(gala, dates=(date(2027, 7, 12), date(2027, 7, 14)))
		self.assertEqual(o.amount, D("250"))
		self.assertFalse(self.price(gala).ok)
		self.assertFalse(self.price(gala, dates=(date(2027, 7, 20),)).ok)

	def test_market_price_rule_and_specificity(self):
		trf = X("TRF", ExtraPricingMode.RESERVATION, "40", price_rules=(
			ExtraPriceRule("de", D("45"), market="DE"),
			ExtraPriceRule("de-dlx", D("55"), market="DE", room_type="DLX")))
		self.assertEqual(self.price(trf).amount, D("45"))
		self.assertEqual(self.price(trf, room_type="DLX").amount, D("55"))
		self.assertEqual(self.price(trf, market="UK").amount, D("40"))

	def test_eligibility_and_fx(self):
		d = X("SPA", ExtraPricingMode.UNIT, "1000", currency="TRY", markets=frozenset({"TR"}))
		self.assertIn("market", self.price(d).reason)
		d2 = X("SPA", ExtraPricingMode.UNIT, "1000", currency="TRY")
		self.assertFalse(self.price(d2).ok)
		o = extras.price_extra(d2, ExtraRequest("SPA", 2), xctx(),
		                       {"TRY": FxSnapshot("TRY", "EUR", FxMode.MANUAL, D("0.02"))})
		self.assertEqual(o.amount, D("40.00"))
		self.assertIn("at most", self.price(X("L", ExtraPricingMode.UNIT, max_quantity=2), qty=3).reason)
