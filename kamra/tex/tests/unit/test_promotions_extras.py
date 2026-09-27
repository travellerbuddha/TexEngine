"""Promotion engine (R-18), coupons (R-20) and extras (R-19)."""

import unittest
from datetime import date, timedelta
from decimal import Decimal

from kamra.tex.pricing import engine, extras, promotions
from kamra.tex.pricing.enums import (
	ExtraPricingMode,
	FxMode,
	PromoAppliesTo,
	PromoValueType,
	StackingMode,
	StayMatch,
)
from kamra.tex.pricing.model import ExtraDef, ExtraPriceRule, ExtraRequest, FxSnapshot, Promotion
from kamra.tex.tests.unit import fixtures

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


class TestUnusableNeverWins(unittest.TestCase):
	"""O-1: a promotion the room cannot use is refused before the combination step, so it never
	excludes or closes out one it can. 2 adults, STD, 3 nights: 600.00 EUR; EB10 alone 540.00."""

	EB10 = P("EB10", priority=1)

	def price(self, other, *, codes=("X",), extras_=(), ctx_kw=None, **req):
		ctx = fixtures.ctx(**{"promotions": (self.EB10, other), **(ctx_kw or {})})
		return engine.price_stay(ctx, fixtures.req(check_out=date(2027, 6, 5), promo_codes=codes, extras=extras_,
		                                           **req))

	def assertEb10Wins(self, q, reason, code, *, total="540.00", other="X"):
		self.assertTrue(q.sellable, q.reasons)
		self.assertEqual(q.totals["accommodation"], D(total))
		out = {o.promo_id: o for o in q.promotions}
		self.assertTrue(out["EB10"].applied, out["EB10"].reason)
		self.assertFalse(out[other].applied)
		self.assertEqual(out[other].reason, reason)
		steps = [s for s in q.explanation.to_list() if (s["rule"] or {}).get("rule_id") == other]
		self.assertEqual([s["code"] for s in steps], [code], q.explanation.summary_lines())

	def test_an_exclusive_fixed_amount_without_a_rate(self):
		q = self.price(P("X", PromoValueType.FIXED_STAY, "100", currency="USD", exclusive=True))
		self.assertEb10Wins(q, "no FX to convert USD", "PROMO_NO_FX")

	def test_a_non_combinable_fixed_night_amount_without_a_rate(self):
		q = self.price(P("X", PromoValueType.FIXED_NIGHT, "10", currency="USD", stackable=False, priority=9))
		self.assertEb10Wins(q, "no FX to convert USD", "PROMO_NO_FX")

	def test_a_contract_offer_in_eur_sold_in_try_without_a_promotion_rate(self):
		"""K-1: 30,600 TRY (600 EUR at 51); EB10 is 10 % of it."""
		k1 = Promotion("X", "Early booking", PromoValueType.FIXED_STAY, D("50"), currency="EUR", exclusive=True,
		               source="contract")
		eur_try = FxSnapshot("EUR", "TRY", FxMode.MANUAL, D("51"))
		q = self.price(k1, codes=(), sell_currency="TRY", ctx_kw={"fx": eur_try})
		self.assertEqual(q.totals["accommodation_gross"], D("30600.00"))
		self.assertEb10Wins(q, "no FX to convert EUR", "PROMO_NO_FX",
		                    total=str(q.totals["accommodation_gross"] * D("0.9")))

	def test_a_multiplier_on_the_total(self):
		q = self.price(P("X", PromoValueType.MULTIPLIER, "0.5", code="X", exclusive=True,
		                 applies_to=PromoAppliesTo.TOTAL))
		self.assertEb10Wins(q, "MULTIPLIER is not supported on TOTAL", "COUPON_REJECTED")

	def test_a_fixed_night_amount_on_the_total(self):
		q = self.price(P("X", PromoValueType.FIXED_NIGHT, "10", code="X", exclusive=True,
		                 applies_to=PromoAppliesTo.TOTAL))
		self.assertEb10Wins(q, "FIXED_NIGHT is not supported on TOTAL", "COUPON_REJECTED")

	def test_free_nights_on_the_extras(self):
		q = self.price(P("X", PromoValueType.FREE_NIGHTS, "0", code="X", exclusive=True, free_nights_stay=3,
		                 free_nights_pay=2, applies_to=PromoAppliesTo.EXTRAS))
		self.assertEb10Wins(q, "FREE_NIGHTS is not supported on EXTRAS", "COUPON_REJECTED")

	def test_an_extras_code_without_extras(self):
		q = self.price(P("X", code="X", exclusive=True, applies_to=PromoAppliesTo.EXTRAS))
		self.assertEb10Wins(q, "nothing to discount", "COUPON_REJECTED")

	def test_a_non_combinable_fixed_total_code_on_the_second_room(self):
		q = self.price(P("X", PromoValueType.FIXED_STAY, "50", code="X", currency="EUR", stackable=False,
		                 priority=9, applies_to=PromoAppliesTo.TOTAL), room_index=1)
		self.assertEb10Wins(q, "fixed booking discount granted once per booking, on room 1", "COUPON_REJECTED")

	def test_usable_ones_are_unchanged(self):
		"""On room 1, with the rate and extras there: the other promotion wins as before."""
		first = self.price(P("X", PromoValueType.FIXED_STAY, "50", code="X", currency="EUR", stackable=False,
		                     priority=9, applies_to=PromoAppliesTo.TOTAL))
		self.assertEqual({o.promo_id: o.applied for o in first.promotions}, {"X": True, "EB10": False})
		self.assertEqual(first.totals["subtotal"], D("550.00"))
		usd = FxSnapshot("USD", "EUR", FxMode.MANUAL, D("0.9"))
		fixed = self.price(P("X", PromoValueType.FIXED_STAY, "100", currency="USD", exclusive=True),
		                   ctx_kw={"promo_fx": {"USD": usd}})
		self.assertEqual(fixed.totals["accommodation"], D("510.00"))
		cot = ExtraDef("COT", "Baby cot", ExtraPricingMode.ROOM, "EUR", D("15"))
		extra = self.price(P("X", value="20", code="X", exclusive=True, applies_to=PromoAppliesTo.EXTRAS),
		                   extras_=(ExtraRequest("COT"),), ctx_kw={"extras": {"COT": cot}})
		self.assertEqual((extra.totals["accommodation"], extra.totals["discounts"]), (D("600.00"), D("3.00")))



class TestGroupRule(unittest.TestCase):
	"""O-4 (D-3): promotions of one group never combine. The highest priority is applied; on equal
	priority the lowest id, the older promotion (not the better one). ``group_ties`` names the
	promotions a new one would tie with."""

	def price(self, *promos):
		q = engine.price_stay(fixtures.ctx(promotions=promos), fixtures.req(check_out=date(2027, 6, 5)))
		return q.totals["accommodation"], {o.promo_id: o.applied for o in q.promotions}

	def test_on_equal_priority_the_older_one_is_applied(self):
		eb10, eb25 = P("PRM-00001", value="10", group="EB"), P("PRM-00002", value="25", group="EB")
		self.assertEqual(self.price(eb25, eb10), (D("540.00"), {"PRM-00001": True, "PRM-00002": False}))

	def test_of_two_contract_offers_the_code_first_alphabetically_is_applied(self):
		"""2D-1 0a: a contract offer's id is its code, so on equal priority the code that sorts first
		wins, whichever was entered first: LS7 entered before EB15, EB15 applies."""
		ls7 = P("LS7", value="7", group="SAVE", source="contract")
		eb15 = P("EB15", value="15", group="SAVE", source="contract")
		t = fixtures.terms(offers=(ls7, eb15))
		q = engine.price_stay(fixtures.ctx(t), fixtures.req(check_out=date(2027, 6, 5)))
		self.assertEqual({o.promo_id: o.applied for o in q.promotions}, {"EB15": True, "LS7": False})
		self.assertEqual(q.totals["accommodation"], D("510.00"))

	def test_a_top_member_refused_by_stacking_leaves_the_group_open(self):
		"""The group closes only on a member that applies: its top member refused as not stackable (another
		promotion already applies) lets the next member of the group apply."""
		other = P("A-OTHER", value="10", priority=9)
		top = P("G-TOP", value="20", group="EB", priority=5, stackable=False)
		low = P("G-LOW", value="5", group="EB", priority=3)
		chosen, rejected = promotions.select((other, top, low), pctx())
		self.assertEqual([p.promo_id for p in chosen], ["A-OTHER", "G-LOW"])
		self.assertIn("not stackable", {r.promo_id: r.reason for r in rejected}["G-TOP"])

	def test_a_higher_priority_is_applied_first(self):
		eb10, eb25 = P("PRM-00001", value="10", group="EB"), P("PRM-00002", value="25", group="EB", priority=1)
		self.assertEqual(self.price(eb10, eb25), (D("450.00"), {"PRM-00001": False, "PRM-00002": True}))

	def test_ties_are_the_same_group_and_priority_with_overlapping_windows(self):
		new = P("NEW", group="EB", sale_from=date(2027, 1, 1), sale_to=date(2027, 3, 31))
		others = (P("A", group="EB"), P("B", group="EB", priority=1), P("C", group="LS"), P("D"),
		          P("E", group="EB", sale_from=date(2027, 4, 1)), P("F", group="EB", sale_to=date(2026, 12, 31)),
		          P("G", group="EB", stay_from=date(2027, 7, 1), stay_to=date(2027, 7, 31)), P("NEW", group="EB"))
		self.assertEqual([p.promo_id for p in promotions.group_ties(new, others)], ["A", "G"])
		self.assertEqual(promotions.group_ties(P("X"), others), [])            # no group: no tie

	def test_an_empty_date_is_an_open_end(self):
		"""A window's empty start is "since always", its empty end "for ever": a promotion without
		dates meets every other in its group."""
		stay = P("S", group="EB", stay_from=date(2027, 6, 1), stay_to=date(2027, 6, 30))
		self.assertEqual([p.promo_id for p in promotions.group_ties(P("N", group="EB"), (stay,))], ["S"])
		later = P("L", group="EB", stay_from=date(2027, 7, 1))
		self.assertEqual(promotions.group_ties(P("N", group="EB", stay_to=date(2027, 6, 30)), (later,)), [])
		self.assertEqual(len(promotions.group_ties(P("N", group="EB", stay_to=date(2027, 7, 1)), (later,))), 1)



class TestCodeKey(unittest.TestCase):
	"""O-31: a promotion code is compared by its key: Turkish dotted and dotless i are I, other
	letters (Ş, Ğ, Ü, Ö, Ç) are kept upper-cased."""

	def test_cases(self):
		for typed, key in (("winter", "WINTER"), ("wİnter", "WINTER"), ("WİNTER", "WINTER"), ("wınter", "WINTER"),
		                   ("wi\u0307nter", "WINTER"), ("WI\u0307NTER", "WINTER"), ("  yaz-24 ", "YAZ-24"),
		                   ("şeker", "ŞEKER"), ("ŞEKER", "ŞEKER"), ("dağ", "DAĞ"), ("üçgöz", "ÜÇGÖZ"),
		                   ("s\u0327eker", "ŞEKER")):
			with self.subTest(typed=typed):
				self.assertEqual(promotions.code_key(typed), key)
				self.assertEqual(promotions.code_key(key), promotions.code_key(typed))      # idempotent
		for blank in (None, "", "   "):
			self.assertIsNone(promotions.code_key(blank))

	def price(self, typed: str, stored: str):
		promo = P("WIN", code=stored)
		q = engine.price_stay(fixtures.ctx(promotions=(promo,)),
		                      fixtures.req(check_out=date(2027, 6, 5), promo_codes=(typed,)))
		return q.totals["accommodation"]

	def test_a_code_typed_with_a_turkish_i_matches(self):
		self.assertEqual(self.price("wİnter", "WINTER"), D("540.00"))
		self.assertEqual(self.price("WİNTER", "WINTER"), D("540.00"))

	def test_a_code_stored_with_a_turkish_i_matches(self):
		self.assertEqual(self.price("winter", "WİNTER"), D("540.00"))
		self.assertEqual(self.price("şeker", "ŞEKER"), D("540.00"))
		self.assertEqual(self.price("seker", "ŞEKER"), D("600.00"))            # Ş is not S


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
