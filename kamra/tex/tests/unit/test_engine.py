"""End-to-end pricing pipeline (QuoteBuilder) tests."""

import json
import unittest
from dataclasses import replace
from datetime import date, datetime
from decimal import Decimal

from kamra.tex.pricing import ages, engine, occupancy
from kamra.tex.pricing.enums import (
	ExtraPricingMode,
	FxMode,
	MarkupCombine,
	OccTarget,
	Op,
	PricingBasis,
	PromoAppliesTo,
	PromoStage,
	PromoValueType,
)
from kamra.tex.pricing.model import (
	ChildSpec,
	ExtraDef,
	ExtraRequest,
	FxSnapshot,
	MarkupRule,
	OccupancyRule,
	Period,
	PricingError,
	Promotion,
	RoomRule,
	RoomSpec,
	TaxRule,
)
from kamra.tex.tests.unit import fixtures as fx

D = Decimal

EB = Promotion("EB15", "Early Booking −15%", PromoValueType.PERCENT, D("15"), kind="EARLY_BOOKING",
               sale_from=date(2026, 10, 1), sale_to=date(2027, 3, 31), source="contract")
DE_MARKUP = MarkupRule("MK-DE", Op.ADJUST_PERCENT, D("7"), property="HOTEL-A", market="DE",
                       label="Germany markup")
TR_TAX = (TaxRule("KV", "Konaklama Vergisi", rate=D("2"), order=1),
          TaxRule("KDV", "KDV", rate=D("10"), order=2),
          TaxRule("KDV20", "KDV 20", rate=D("20"), applies_to=frozenset({"EXTRA:*"}), order=3))


def spec_terms(**kw):
	"""Spec R-45 example: base person 100, room ×1.20, stay period +10 %."""
	t = fx.terms()
	rooms = {**t.rooms, "FAM": RoomSpec("FAM", "Family Room", 3, 2, 5)}
	periods = tuple(replace(p, adjustment_op=Op.ADJUST_PERCENT, adjustment_value=D("10")) if p.code == "P1" else p
	                for p in t.periods)
	return replace(t, rooms=rooms, periods=periods,
	               room_rules=(*t.room_rules, RoomRule("R-FAM", "FAM", None, Op.MULTIPLY, D("1.20"), "STD")),
	               offers=(EB,), **kw)


def spec_request(**kw):
	base = dict(room_type="FAM", children=(8,), sale_at=datetime(2027, 1, 15, 9, 30))
	base.update(kw)
	return fx.req(**base)


class TestSpecExplanationExample(unittest.TestCase):
	"""Base person €100 · A1 ×1 · A2 ×1 · child(8) ×0.5 · room ×1.20 · period +10 % ·
	Germany markup +7 % · Early Booking −15 %."""

	def setUp(self):
		self.q = engine.price_stay(fx.ctx(spec_terms(), markups=(DE_MARKUP,)), spec_request())

	def test_nightly_pipeline(self):
		n = self.q.nights[0]
		self.assertTrue(self.q.sellable, self.q.reasons)
		self.assertEqual(n.unit, D("120.00"))
		self.assertEqual(n.occupancy, D("300.00"))
		self.assertEqual(n.cost, D("330.00"))
		self.assertEqual(n.sell, D("353.1"))
		self.assertEqual(n.final, D("300.135"))

	def test_lines_and_totals(self):
		t = self.q.totals
		self.assertEqual(t["accommodation_gross"], D("353.10"))
		self.assertEqual(t["accommodation_discount"], D("52.97"))
		self.assertEqual(t["total"], D("300.13"))
		self.assertEqual(t["cost"], D("330.00"))
		self.assertEqual(t["margin"], D("-29.87"))
		self.assertEqual([ln.kind.value for ln in self.q.lines], ["ACCOMMODATION", "DISCOUNT"])
		self.assertEqual(sum(ln.amount for ln in self.q.lines), t["total"])

	def test_explanation_names_every_step(self):
		codes = [s.code for s in self.q.explanation.steps]
		for c in ("CONTRACT", "PERIOD", "ROOM_ABSOLUTE", "ROOM_DERIVED", "ADULT_SLOT", "CHILD_SLOT",
		          "BOARD_BASE", "PERIOD_ADJUSTMENT", "NIGHT_COST", "MARKUP", "PROMO_APPLIED", "TOTAL"):
			self.assertIn(c, codes)
		text = "\n".join(self.q.explanation.summary_lines())
		self.assertIn("FAM = STD × 1.20 → 120.00", text)
		self.assertIn("Child 1 (8y, Child B) 50% of 120.00 = 60.00", text)
		self.assertIn("Germany markup +7%: 330.00 → 353.10", text)
		markup_step = next(s for s in self.q.explanation.steps if s.code == "MARKUP")
		self.assertEqual(markup_step.rule.rule_id, "MK-DE")
		self.assertEqual(markup_step.rule.level.name, "MARKET")

	def test_deterministic_and_json_safe(self):
		again = engine.price_stay(fx.ctx(spec_terms(), markups=(DE_MARKUP,)), spec_request())
		a = json.dumps(self.q.to_dict(), sort_keys=True)
		b = json.dumps(again.to_dict(), sort_keys=True)
		self.assertEqual(a, b)
		self.assertNotIn("e+", a.lower().replace("true", ""))

	def test_guest_view_hides_cost_and_margin(self):
		guest = self.q.to_dict(internal=False)
		self.assertNotIn("margin", guest["totals"])
		self.assertNotIn("cost", guest["totals"])
		self.assertNotIn("explanation", guest)
		self.assertEqual(guest["nights"], [{"date": "2027-06-02", "amount": "300.14"}])


class TestPipelineStages(unittest.TestCase):
	def test_cost_stage_offer_before_markup(self):
		eb_cost = replace(EB, stage=PromoStage.COST)
		q = engine.price_stay(fx.ctx(replace(spec_terms(), offers=(eb_cost,)), markups=(DE_MARKUP,)),
		                      spec_request())
		n = q.nights[0]
		self.assertEqual(n.cost_net, D("280.5000"))
		self.assertEqual(q.totals["total"], D("300.14"))
		self.assertEqual(q.totals["cost"], D("280.50"))
		self.assertEqual(q.totals["margin"], D("19.64"))

	def test_sale_date_outside_eb_window(self):
		q = engine.price_stay(fx.ctx(spec_terms(), markups=(DE_MARKUP,)),
		                      spec_request(sale_at=datetime(2027, 4, 2, 9)))
		self.assertEqual(q.totals["total"], D("353.10"))
		rejected = [p for p in q.promotions if not p.applied]
		self.assertIn("after", rejected[0].reason)

	def test_multi_night_across_periods(self):
		q = engine.price_stay(fx.ctx(), fx.req(check_in=date(2027, 6, 14), check_out=date(2027, 6, 18)))
		self.assertEqual([n.period for n in q.nights], ["P1", "P1", "P2", "P2"])
		self.assertEqual(q.totals["total"], D("840.00"))   # 2×200 + 2×220

	def test_rate_plan_and_board(self):
		t = fx.with_rate_plans(fx.terms())
		with self.assertRaises(PricingError):
			engine.price_stay(fx.ctx(t), fx.req())
		flex = engine.price_stay(fx.ctx(t), fx.req(rate_plan="FLEX", board="UAI", children=(8,)))
		nrf = engine.price_stay(fx.ctx(t), fx.req(rate_plan="NRF", board="UAI", children=(8,)))
		self.assertEqual(flex.totals["total"], D("300.00"))   # 250 + UAI 20+20+10
		self.assertEqual(nrf.totals["total"], D("270.00"))
		self.assertFalse(nrf.rate_plan["refundable"])

	def test_fx_tax_extras_and_coupon(self):
		t = replace(spec_terms(), prices_include_tax=True)
		fx_eur_try = FxSnapshot("EUR", "TRY", FxMode.PROVIDER_PERCENT, D("51"), provider="TCMB",
		                        provider_rate=D("50"), adjustment=D("2"))
		transfer = ExtraDef("TRF", "Airport transfer", ExtraPricingMode.RESERVATION, "EUR", D("40"))
		coupon = Promotion("WELCOME", "Welcome 5%", PromoValueType.PERCENT, D("5"), code="WELCOME",
		                   applies_to=PromoAppliesTo.TOTAL)
		ctx = fx.ctx(t, fx=fx_eur_try, markups=(DE_MARKUP,), tax_rules=TR_TAX, extras={"TRF": transfer},
		             extra_fx={"EUR": fx_eur_try}, promotions=(coupon,))
		q = engine.price_stay(ctx, spec_request(sell_currency="TRY", extras=(ExtraRequest("TRF"),),
		                                        promo_codes=("welcome",)))
		self.assertTrue(q.sellable, q.reasons)
		tot = q.totals
		self.assertEqual(tot["accommodation_gross"], D("18008.10"))
		self.assertEqual(tot["accommodation_discount"], D("2701.22"))
		self.assertEqual(tot["extras"], D("2040.00"))
		coupon_line = next(ln for ln in q.lines if ln.kind.value == "COUPON")
		self.assertEqual(coupon_line.amount, D("-867.34"))
		self.assertEqual(tot["total"], D("16479.54"))
		self.assertEqual(tot["tax_added"], D("0"))
		inc = sum(ln.amount for ln in q.lines if ln.kind.value == "TAX")
		self.assertEqual(inc, tot["tax"])
		self.assertEqual(q.fx["sell_rate"], "51.000000")
		non_tax = sum(ln.amount for ln in q.lines if ln.kind.value != "TAX")
		self.assertEqual(non_tax, tot["total"])

	def test_exclusive_taxes_are_added(self):
		q = engine.price_stay(fx.ctx(tax_rules=(TaxRule("VAT", "VAT", rate=D("10")),)), fx.req())
		self.assertEqual(q.totals["subtotal"], D("200.00"))
		self.assertEqual(q.totals["total"], D("220.00"))

	def test_mandatory_extra_added_automatically(self):
		gala = ExtraDef("GALA", "Gala dinner", ExtraPricingMode.PERSON, "EUR", D("50"), child_amount=D("25"),
		                mandatory=True)
		q = engine.price_stay(fx.ctx(extras={"GALA": gala}), fx.req(children=(8,)))
		self.assertEqual(q.totals["extras"], D("125"))
		seasonal = replace(gala, service_from=date(2027, 12, 31), service_to=date(2027, 12, 31))
		q2 = engine.price_stay(fx.ctx(extras={"GALA": seasonal}), fx.req())
		self.assertEqual(q2.extras, [])
		self.assertTrue(q2.sellable)

	def test_markup_stack_and_channel(self):
		cc = MarkupRule("MK-CC", Op.ADD, D("5"), property="HOTEL-A", channel="CALL_CENTER",
		                combine=MarkupCombine.STACK)
		web = engine.price_stay(fx.ctx(markups=(DE_MARKUP, cc)), fx.req())
		call = engine.price_stay(fx.ctx(markups=(DE_MARKUP, cc)), fx.req(channel="CALL_CENTER"))
		self.assertEqual(web.totals["total"], D("214.00"))
		self.assertEqual(call.totals["total"], D("219.00"))


class TestUnsellable(unittest.TestCase):
	def reasons(self, q):
		self.assertFalse(q.sellable)
		self.assertEqual(q.totals, {})
		return [r["code"] for r in q.reasons]

	def test_windows_market_channel(self):
		self.assertEqual(self.reasons(engine.price_stay(fx.ctx(), fx.req(sale_at=datetime(2026, 9, 1)))),
		                 ["SALE_WINDOW"])
		self.assertEqual(self.reasons(engine.price_stay(fx.ctx(), fx.req(market="UK"))), ["MARKET_MISMATCH"])
		t = fx.terms(channels=frozenset({"CALL_CENTER"}))
		self.assertEqual(self.reasons(engine.price_stay(fx.ctx(t), fx.req())), ["CHANNEL_NOT_ALLOWED"])
		self.assertEqual(self.reasons(engine.price_stay(fx.ctx(), fx.req(check_in=date(2027, 8, 31),
		                                                                 check_out=date(2027, 9, 2)))),
		                 ["STAY_WINDOW"])

	def test_global_market_contract_serves_any_market(self):
		q = engine.price_stay(fx.ctx(fx.terms(market="GLOBAL")), fx.req(market="PL"))
		self.assertTrue(q.sellable)

	def test_capacity_and_board_and_room(self):
		self.assertEqual(self.reasons(engine.price_stay(fx.ctx(), fx.req(adults=4))), ["MAX_ADULTS"])
		self.assertEqual(self.reasons(engine.price_stay(fx.ctx(), fx.req(board="HB"))), ["NO_BOARD"])
		self.assertEqual(self.reasons(engine.price_stay(fx.ctx(), fx.req(room_type="VILLA"))),
		                 ["ROOM_NOT_IN_CONTRACT"])

	def test_no_child_rule(self):
		t = fx.terms(occupancy_rules=tuple(r for r in fx.occ_rules() if r.rule_id != "O-TEEN"))
		self.assertEqual(self.reasons(engine.price_stay(fx.ctx(t), fx.req(children=(13,)))), ["NO_CHILD_RULE"])

	def test_fx_snapshot_must_match(self):
		with self.assertRaises(PricingError):
			engine.price_stay(fx.ctx(), fx.req(sell_currency="TRY"))

	def test_invalid_dates(self):
		with self.assertRaises(PricingError):
			engine.price_stay(fx.ctx(), fx.req(check_out=date(2027, 6, 2)))


class TestChildrenAtBoundaries(unittest.TestCase):
	"""DOB-based pricing on the arrival date — the 3rd birthday on arrival day pays CHA."""

	def total(self, dob):
		q = engine.price_stay(fx.ctx(), fx.req(children=(ChildSpec(dob=dob),)))
		return q.totals["total"]

	def test_birthday_boundaries(self):
		arrival = date(2027, 6, 2)
		self.assertEqual(self.total(date(2024, 6, 3)), D("200.00"))   # 2y11m → infant free
		self.assertEqual(self.total(date(2024, 6, 2)), D("225.00"))   # exactly 3 → 25 %
		self.assertEqual(self.total(date(2020, 6, 3)), D("225.00"))   # 6y11m → CHA
		self.assertEqual(self.total(date(2020, 6, 2)), D("250.00"))   # exactly 7 → CHB 50 %
		self.assertEqual(self.total(date(2015, 6, 3)), D("250.00"))   # 11y11m → CHB
		self.assertEqual(self.total(date(2015, 6, 2)), D("270.00"))   # exactly 12 → TEEN 70 %
		self.assertEqual(self.total(date(2011, 6, 2)), D("270.00"))   # 16 → priced as 3rd adult ×0.70
		self.assertEqual(arrival, fx.req().check_in)

	def test_engine_family_with_infant(self):
		# 2A + child 8 + infant: the infant's band rule (×0) beats the band-less 2A+2C child-2 rule (G-31)
		q = engine.price_stay(fx.ctx(), fx.req(children=(8, 1)))
		self.assertEqual(q.totals["total"], D("250.00"))


# ─── GAP-12 (ADR-061): the running totals of a night, reported ──────────────

# the spec example as the engine priced it before GAP-12 (captured on the S4 tip 564014a)
SPEC_SUMMARY = [
	"contract DE-S27 v1 (DE, EUR, PERSON basis)",
	"[2027-06-02] period P1 (1–15 Jun)",
	"[2027-06-02] STD in P1: price 100.00",
	"[2027-06-02] FAM = STD × 1.20 → 120.00",
	"[2027-06-02] Adult 1 × 1.00 120.00 = 120.00",
	"[2027-06-02] Adult 2 × 1.00 120.00 = 120.00",
	"[2027-06-02] Child 1 (8y, Child B) 50% of 120.00 = 60.00",
	"[2027-06-02] occupancy 2A+1C = 300.00",
	"[2027-06-02] board AI included in the price",
	"[2027-06-02] period P1 adjustment +10%",
	"[2027-06-02] contract cost 330.00 EUR",
	"[2027-06-02] Germany markup +7%: 330.00 → 353.10",
	"Early Booking −15%: −52.965 on 1 night(s)",
	"total 300.13 EUR",
]
SPEC_STEPS = [
	("CONTRACT", None, None), ("PERIOD", None, None), ("ROOM_ABSOLUTE", None, "100.000000"),
	("ROOM_DERIVED", "100.000000", "120.000000"), ("ADULT_SLOT", None, "120.000000"),
	("ADULT_SLOT", None, "120.000000"), ("CHILD_SLOT", None, "60.000000"), ("OCCUPANCY_TOTAL", None, "300.000000"),
	("BOARD_BASE", None, None), ("PERIOD_ADJUSTMENT", "300.000000", "330.000000"),
	("NIGHT_COST", None, "330.000000"), ("MARKUP", "330.000000", "353.100000"),
	("PROMO_APPLIED", "353.100000", "300.135000"), ("TOTAL", None, "300.130000"),
]
SPEC_TOTALS = {"accommodation_gross": "353.10", "accommodation_discount": "52.97", "accommodation": "300.13",
               "extras": "0", "discounts": "52.97", "subtotal": "300.13", "tax": "0", "tax_added": "0",
               "total": "300.13", "cost": "330.00", "cost_contract_currency": "330.00", "margin": "-29.87",
               "margin_percent": "-9.95"}
SPEC_NIGHT = {"date": "2027-06-02", "period": "P1", "unit": "120.000000", "occupancy": "300.000000",
              "board": "0.000000", "cost": "330.000000", "cost_net": "330.000000", "sell_contract": "353.100000",
              "sell": "353.100000", "final": "300.135000"}
SUBTOTALS = ("subtotal_adults", "subtotal_children", "subtotal_board")
COMBO_2A2C = OccupancyRule("O-2A2C", OccTarget.COMBINATION, Op.ADJUST_PERCENT, D("-10"), adults=2, children=2)


def steps_of(q, code, night):
	return [s for s in q.explanation.steps if s.code == code and s.night == night.isoformat()]


def room_basis_terms():
	"""The ROOM basis contract of test_occupancy_and_rooms.TestRoomBasis: room 200 for 2 adults."""
	rules = (RoomRule("R-STD-P1", "STD", "P1", Op.ABSOLUTE, D("200")),)
	occ_rules = (
		OccupancyRule("O-A3", OccTarget.ADULT, Op.MULTIPLY, D("0.70"), position=3),
		OccupancyRule("O-CHB", OccTarget.CHILD, Op.PERCENT_OF, D("50"), age_band="CHB"),
		OccupancyRule("O-INF", OccTarget.CHILD, Op.MULTIPLY, D("0"), age_band="INF"),
		OccupancyRule("O-1A", OccTarget.COMBINATION, Op.PERCENT_OF, D("80"), adults=1, children=0),
	)
	return replace(fx.terms(), basis=PricingBasis.ROOM, room_rules=rules, occupancy_rules=occ_rules,
	               periods=(Period("P1", "P1", date(2027, 6, 1), date(2027, 6, 30)),),
	               rooms={"STD": RoomSpec("STD", "Standard", 3, 2, 4, included_adults=2)})


class TestReportedSubtotals(unittest.TestCase):
	"""GAP-12: each night reports the running totals the engine already holds — after the adults,
	after the children (before a combination rule) and occupancy + board (before the period
	adjustment) — for the Explain ladder's Occupancy, Child and Board stages. No price, total,
	explanation step or engine version changes; the guest view never carries them."""

	def spec(self, **kw):
		return engine.price_stay(fx.ctx(spec_terms(), markups=(DE_MARKUP,)), spec_request(**kw))

	def test_the_spec_example_is_priced_and_explained_as_before(self):
		q = self.spec()
		d = q.to_dict()
		self.assertEqual(q.explanation.summary_lines(), SPEC_SUMMARY)
		self.assertEqual([(s["code"], s["before"], s["after"]) for s in d["explanation"]], SPEC_STEPS)
		self.assertEqual(d["totals"], SPEC_TOTALS)
		self.assertEqual({k: v for k, v in d["nights"][0].items() if k not in SUBTOTALS}, SPEC_NIGHT)
		self.assertEqual(d["engine_version"], "tex-pricing/1.0")
		self.assertEqual(q.engine_version, engine.ENGINE_VERSION)

	def test_the_spec_examples_subtotals(self):
		n = self.spec().nights[0]
		self.assertEqual((n.unit, n.subtotal_adults, n.subtotal_children, n.occupancy, n.subtotal_board),
		                 (D("120"), D("240"), D("300"), D("300"), D("300")))
		self.assertEqual({k: n.to_dict()[k] for k in SUBTOTALS},
		                 {"subtotal_adults": "240.000000", "subtotal_children": "300.000000",
		                  "subtotal_board": "300.000000"})

	def test_every_night_chains_occupancy_child_and_board(self):
		t = fx.with_rate_plans(fx.terms())
		scenarios = {
			"spec example": self.spec(),
			"supplement board, period adjustment": self.spec(board="UAI"),
			"two periods, rate plan, supplement": engine.price_stay(fx.ctx(t), fx.req(
				rate_plan="NRF", board="UAI", children=(8, 1), check_in=date(2027, 6, 14),
				check_out=date(2027, 6, 18))),
			"adults only": engine.price_stay(fx.ctx(), fx.req(adults=3, room_type="SUITE", check_in=date(2027, 8, 3),
			                                                  check_out=date(2027, 8, 5))),
		}
		for name, q in scenarios.items():
			self.assertTrue(q.sellable, (name, q.reasons))
			for n in q.nights:
				with self.subTest(scenario=name, night=n.night):
					self.assertFalse(steps_of(q, "COMBINATION_RULE", n.night))
					self.assertEqual(n.subtotal_children, n.occupancy)
					self.assertEqual(n.subtotal_board, n.occupancy + n.board)
					adj = steps_of(q, "PERIOD_ADJUSTMENT", n.night)
					if adj:
						self.assertEqual(adj[0].before, n.subtotal_board)
					else:
						first = steps_of(q, "RATE_PLAN_ADJUSTMENT", n.night)
						self.assertEqual(first[0].before if first else n.cost, n.subtotal_board)
		self.assertEqual(steps_of(scenarios["supplement board, period adjustment"], "PERIOD_ADJUSTMENT",
		                          date(2027, 6, 2))[0].before, D("350"))        # 300 + UAI 20 + 20 + 10
		adults_only = scenarios["adults only"].nights[0]
		self.assertEqual((adults_only.unit, adults_only.subtotal_adults, adults_only.subtotal_children),
		                 (D("245"), D("661.5"), D("661.5")))                   # 245 + 245 + 0.70 × 245

	def test_a_combination_rule_starts_from_the_childrens_subtotal(self):
		t = fx.terms(occupancy_rules=(*fx.occ_rules(), COMBO_2A2C))
		q = engine.price_stay(fx.ctx(t), fx.req(children=(8, 4), board="UAI"))
		self.assertTrue(q.sellable, q.reasons)
		n = q.nights[0]
		combo = steps_of(q, "COMBINATION_RULE", n.night)[0]
		self.assertEqual((n.subtotal_adults, n.subtotal_children), (D("200"), D("275")))   # 100 + 100 + 50 + 25
		self.assertEqual(combo.before, n.subtotal_children)
		self.assertEqual(combo.after, n.occupancy)
		self.assertNotEqual(n.subtotal_children, n.occupancy)                            # 247.50
		self.assertEqual(n.subtotal_board, D("307.5"))                                   # 247.50 + UAI 60

	def test_room_basis(self):
		t = room_basis_terms()
		q = engine.price_stay(fx.ctx(t), fx.req(adults=3))
		n = q.nights[0]
		self.assertEqual((n.unit, n.subtotal_adults, n.subtotal_children, n.occupancy), (D("200"), D("270"),
		                                                                              D("270"), D("270")))
		# single use: the room price covers the adult, then the combination takes 80 % of the room
		single = engine.price_stay(fx.ctx(t), fx.req(adults=1)).nights[0]
		self.assertEqual((single.subtotal_adults, single.subtotal_children, single.occupancy),
		                 (D("200"), D("200"), D("160")))

	def test_the_occupancy_result_holds_the_running_totals(self):
		t = fx.terms()
		period = next(p for p in t.periods if p.code == "P1")
		unit = D("100")
		party = ages.classify_party(t, 2, (ChildSpec(age=8),), date(2027, 6, 2), date(2027, 1, 1))
		r = occupancy.price_occupancy(t, t.rooms["STD"], period, unit, party)
		self.assertEqual((r.after_adults, r.after_children, r.total), (2 * unit, D("250"), D("250")))
		party = ages.classify_party(t, 2, (ChildSpec(age=8), ChildSpec(age=4)), date(2027, 6, 2), date(2027, 1, 1))
		combo = occupancy.price_occupancy(replace(t, occupancy_rules=(*t.occupancy_rules, COMBO_2A2C)),
		                                  t.rooms["STD"], period, unit, party)
		self.assertEqual((combo.after_adults, combo.after_children, combo.total), (D("200"), D("275"), D("247.5")))

	def test_guests_and_staff_without_cost_access_never_see_them(self):
		from kamra.tex.services import quoting

		q = self.spec(board="UAI")
		self.assertEqual(set(q.to_dict(internal=False)["nights"][0]), {"date", "amount"})
		internal = q.to_dict()
		self.assertTrue(set(SUBTOTALS) <= set(internal["nights"][0]))
		for staff in (False, True):
			shown = quoting.strip_internal(json.loads(json.dumps(internal)), staff=staff)
			self.assertEqual([set(n) for n in shown["nights"]], [{"date", "amount"}])
