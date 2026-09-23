"""Occupancy formula engine, precedence and derived room pricing (R-07, R-09, R-10, R-11)."""

import unittest
from dataclasses import replace
from datetime import date
from decimal import Decimal

from kamra.tex.pricing import ages, occupancy, rooms
from kamra.tex.pricing.enums import Level, OccTarget, Op, PricingBasis, RoomBasisExtraUnit
from kamra.tex.pricing.explain import Explanation
from kamra.tex.pricing.model import ChildSpec, OccupancyRule, Period, RoomRule, RoomSpec, Unsellable
from kamra.tex.tests.unit import fixtures as fx

D = Decimal


def party(t, adults, *kid_ages, arrival=date(2027, 6, 2)):
	return ages.classify_party(t, adults, tuple(ChildSpec(age=a) for a in kid_ages), arrival, date(2027, 1, 1))


def occ(t, room, period_code, adults, *kid_ages, explain=None):
	period = next(p for p in t.periods if p.code == period_code)
	unit = rooms.room_unit(t, room, period)
	return occupancy.price_occupancy(t, t.rooms[room], period, unit, party(t, adults, *kid_ages),
	                                 explain=explain)


class TestPersonBasis(unittest.TestCase):
	def setUp(self):
		self.t = fx.terms()

	def test_adults(self):
		self.assertEqual(occ(self.t, "STD", "P1", 1).total, D("100"))
		self.assertEqual(occ(self.t, "STD", "P1", 2).total, D("200"))
		self.assertEqual(occ(self.t, "STD", "P1", 3).total, D("270"))   # 100 + 100 + 70

	def test_child_bands(self):
		self.assertEqual(occ(self.t, "STD", "P1", 2, 1).total, D("200"))     # infant ×0
		self.assertEqual(occ(self.t, "STD", "P1", 2, 4).total, D("225"))     # CHA 25 %
		self.assertEqual(occ(self.t, "STD", "P1", 2, 8).total, D("250"))     # CHB 50 %
		self.assertEqual(occ(self.t, "STD", "P1", 2, 13).total, D("270"))    # TEEN 70 %

	def test_combination_dependent_child_rule(self):
		# 2A + 1C(8) → child 50 %; 1A + 1C(8) → child 100 %
		self.assertEqual(occ(self.t, "STD", "P1", 2, 8).total, D("250"))
		self.assertEqual(occ(self.t, "STD", "P1", 1, 8).total, D("200"))

	def test_second_child_in_2a2c(self):
		# child 1 = 8y (CHB 50 %), child 2 = 5y → 2A+2C position-2 rule 25 % (beats CHA band rule)
		r = occ(self.t, "STD", "P1", 2, 5, 8)
		self.assertEqual([s.amount for s in r.slots], [D(0) + 100, D(100), D("50"), D("25")])
		self.assertEqual(r.total, D("275"))
		self.assertEqual(r.slots[3].rule.rule_id, "O-2A2C-C2")
		self.assertEqual(r.slots[3].rule.level, Level.COMBINATION)

	def test_derived_rooms_scale_every_slot(self):
		self.assertEqual(occ(self.t, "SUP", "P1", 2).total, D("230.00"))   # 115 × 2
		self.assertEqual(occ(self.t, "DLX", "P1", 3).total, D("364.500"))  # 135 + 135 + 94.5

	def test_no_rule_for_child_band_is_unsellable(self):
		t = replace(self.t, occupancy_rules=tuple(r for r in self.t.occupancy_rules if r.rule_id != "O-TEEN"))
		with self.assertRaises(Unsellable) as cm:
			occ(t, "STD", "P1", 2, 13)
		self.assertEqual(cm.exception.code, "NO_CHILD_RULE")

	def test_period_rule_beats_version_rule(self):
		rules = (*self.t.occupancy_rules,
		         OccupancyRule("O-CHB-P2", OccTarget.CHILD, Op.PERCENT_OF, D("40"), age_band="CHB", period="P2"))
		t = replace(self.t, occupancy_rules=rules)
		self.assertEqual(occ(t, "STD", "P1", 2, 8).total, D("250"))    # P1: version 50 %
		self.assertEqual(occ(t, "STD", "P2", 2, 8).total, D("264"))    # P2: 110×2 + 40 % of 110

	def test_room_rule_beats_version_rule_and_period_beats_room(self):
		rules = (*self.t.occupancy_rules,
		         OccupancyRule("O-A3-DLX", OccTarget.ADULT, Op.MULTIPLY, D("0.80"), position=3, room_type="DLX"),
		         OccupancyRule("O-A3-DLX-P2", OccTarget.ADULT, Op.MULTIPLY, D("0.90"), position=3,
		                       room_type="DLX", period="P2"))
		t = replace(self.t, occupancy_rules=rules)
		self.assertEqual(occ(t, "STD", "P1", 3).total, D("270"))
		self.assertEqual(occ(t, "DLX", "P1", 3).total, D("135") * 2 + D("108"))
		self.assertEqual(occ(t, "DLX", "P2", 3).total, D("148.5") * 2 + D("133.65"))

	def test_override_beats_combination(self):
		rules = (*self.t.occupancy_rules,
		         OccupancyRule("O-OVR", OccTarget.CHILD, Op.FIXED, D("10"), position=1, adults=1, children=1,
		                       room_type="STD", period="P1", is_override=True))
		t = replace(self.t, occupancy_rules=rules)
		ex = Explanation()
		r = occ(t, "STD", "P1", 1, 8, explain=ex)
		self.assertEqual(r.total, D("110"))
		self.assertEqual(r.slots[1].rule.level, Level.OVERRIDE)
		child_step = next(s for s in ex.steps if s.code == "CHILD_SLOT")
		self.assertIn("O-1A1C", [o.rule_id for o in child_step.overridden])

	def test_inherit_defers_to_less_specific(self):
		rules = (*self.t.occupancy_rules,
		         OccupancyRule("O-CHB-P1-INH", OccTarget.CHILD, Op.INHERIT, None, age_band="CHB", period="P1"))
		t = replace(self.t, occupancy_rules=rules)
		self.assertEqual(occ(t, "STD", "P1", 2, 8).total, D("250"))

	def test_ambiguous_rules_are_refused(self):
		rules = (*self.t.occupancy_rules,
		         OccupancyRule("O-CHB-DUP", OccTarget.CHILD, Op.PERCENT_OF, D("60"), age_band="CHB"))
		t = replace(self.t, occupancy_rules=rules)
		with self.assertRaises(Unsellable) as cm:
			occ(t, "STD", "P1", 2, 8)
		self.assertEqual(cm.exception.code, "AMBIGUOUS_OCCUPANCY_RULES")

	def test_policy_rules_rank_below_version(self):
		rules = (*self.t.occupancy_rules,
		         OccupancyRule("POL-CHB", OccTarget.CHILD, Op.PERCENT_OF, D("30"), age_band="CHB",
		                       base_level=Level.HOTEL, source="policy:hotel"))
		t = replace(self.t, occupancy_rules=rules)
		self.assertEqual(occ(t, "STD", "P1", 2, 8).total, D("250"))
		only_policy = replace(self.t, occupancy_rules=tuple(
			r for r in rules if r.rule_id != "O-CHB"))
		self.assertEqual(occ(only_policy, "STD", "P1", 2, 8).total, D("230"))

	def test_combination_absolute(self):
		rules = (*self.t.occupancy_rules,
		         OccupancyRule("O-2A1C-ABS", OccTarget.COMBINATION, Op.ABSOLUTE, D("233"), adults=2, children=1))
		t = replace(self.t, occupancy_rules=rules)
		self.assertEqual(occ(t, "STD", "P1", 2, 8).total, D("233"))
		self.assertEqual(occ(t, "STD", "P1", 2).total, D("200"))

	def test_capacity(self):
		spec = self.t.rooms["STD"]
		with self.assertRaises(Unsellable):
			occupancy.check_capacity(spec, party(self.t, 4), True)
		with self.assertRaises(Unsellable):
			occupancy.check_capacity(spec, party(self.t, 2, 5, 8, 9), True)
		with self.assertRaises(Unsellable):
			occupancy.check_capacity(spec, party(self.t, 3, 5, 8), True)   # 5 > 4 occupants
		occupancy.check_capacity(spec, party(self.t, 3, 1), True)
		occupancy.check_capacity(spec, party(self.t, 3, 1, 1), False)      # infants not counted


class TestRoomBasis(unittest.TestCase):
	def setUp(self):
		base = fx.terms()
		rules = (
			RoomRule("R-STD-P1", "STD", "P1", Op.ABSOLUTE, D("200")),
			RoomRule("R-SUP", "SUP", None, Op.MULTIPLY, D("1.15"), "STD"),
		)
		occ_rules = (
			OccupancyRule("O-A3", OccTarget.ADULT, Op.MULTIPLY, D("0.70"), position=3),
			OccupancyRule("O-CHB", OccTarget.CHILD, Op.PERCENT_OF, D("50"), age_band="CHB"),
			OccupancyRule("O-INF", OccTarget.CHILD, Op.MULTIPLY, D("0"), age_band="INF"),
			OccupancyRule("O-1A", OccTarget.COMBINATION, Op.PERCENT_OF, D("80"), adults=1, children=0),
		)
		self.t = replace(base, basis=PricingBasis.ROOM, room_rules=rules, occupancy_rules=occ_rules,
		                 periods=(Period("P1", "P1", date(2027, 6, 1), date(2027, 6, 30)),),
		                 rooms={"STD": RoomSpec("STD", "Standard", 3, 2, 4, included_adults=2),
		                        "SUP": RoomSpec("SUP", "Superior", 3, 2, 4, included_adults=2)})

	def test_room_price_covers_included_adults(self):
		self.assertEqual(occ(self.t, "STD", "P1", 2).total, D("200"))

	def test_extra_adult_priced_on_per_person_share(self):
		self.assertEqual(occ(self.t, "STD", "P1", 3).total, D("270"))   # 200 + 0.7 × 100

	def test_extra_unit_room_price_setting(self):
		t = replace(self.t, room_basis_extra_unit=RoomBasisExtraUnit.ROOM_PRICE)
		self.assertEqual(occ(t, "STD", "P1", 3).total, D("340"))        # 200 + 0.7 × 200

	def test_single_use_combination(self):
		self.assertEqual(occ(self.t, "STD", "P1", 1).total, D("160"))   # 80 % of room

	def test_children_extra_or_filling_included_places(self):
		self.assertEqual(occ(self.t, "STD", "P1", 2, 8).total, D("250"))
		self.assertEqual(occ(self.t, "STD", "P1", 1, 8).total, D("250"))
		filling = replace(self.t, room_basis_children_fill_included=True)
		self.assertEqual(occ(filling, "STD", "P1", 1, 8).total, D("200"))


class TestRoomsAndPeriods(unittest.TestCase):
	def setUp(self):
		self.t = fx.terms()

	def unit(self, room, period, t=None):
		t = t or self.t
		return rooms.room_unit(t, room, next(p for p in t.periods if p.code == period))

	def test_derived_rooms(self):
		self.assertEqual(self.unit("SUP", "P1"), D("115.00"))
		self.assertEqual(self.unit("DLX", "P1"), D("135.00"))
		self.assertEqual(self.unit("SUITE", "P1"), D("180.00"))

	def test_base_change_propagates(self):
		rules = tuple(replace(r, value=D("150")) if r.rule_id == "R-STD-P1" else r for r in self.t.room_rules)
		t = replace(self.t, room_rules=rules)
		self.assertEqual(self.unit("SUITE", "P1", t), D("270.00"))

	def test_absolute_override_wins_in_its_period(self):
		self.assertEqual(self.unit("SUITE", "P3"), D("216.00"))    # 120 × 1.80
		self.assertEqual(self.unit("SUITE", "P3A"), D("245"))       # explicit override

	def test_period_selection(self):
		self.assertEqual(rooms.period_for(self.t, date(2027, 8, 10)).code, "P3A")
		self.assertEqual(rooms.period_for(self.t, date(2027, 8, 20)).code, "P3")
		self.assertEqual(rooms.period_for(self.t, date(2027, 6, 15)).code, "P1")
		self.assertEqual(rooms.period_for(self.t, date(2027, 6, 16)).code, "P2")
		self.assertIsNone(rooms.period_for(self.t, date(2027, 9, 1)))

	def test_weekday_period_beats_everyday(self):
		weekend = Period("WE", "Weekend", date(2027, 6, 1), date(2027, 6, 30), weekdays=frozenset({4, 5}))
		t = replace(self.t, periods=(*self.t.periods, weekend),
		            room_rules=(*self.t.room_rules, RoomRule("R-STD-WE", "STD", "WE", Op.ABSOLUTE, D("140"))))
		self.assertEqual(rooms.period_for(t, date(2027, 6, 4)).code, "WE")    # Friday
		self.assertEqual(rooms.period_for(t, date(2027, 6, 3)).code, "P1")    # Thursday

	def test_inherit_room_rule_falls_back(self):
		rules = (*self.t.room_rules, RoomRule("R-SUP-P1-INH", "SUP", "P1", Op.INHERIT, None))
		t = replace(self.t, room_rules=rules)
		self.assertEqual(self.unit("SUP", "P1", t), D("115.00"))

	def test_adjustments(self):
		rules = (*self.t.room_rules,
		         RoomRule("R-SUP-P2", "SUP", "P2", Op.ADJUST_PERCENT, D("20"), "STD"),
		         RoomRule("R-DLX-P2", "DLX", "P2", Op.ADD, D("25"), "STD"))
		t = replace(self.t, room_rules=rules)
		self.assertEqual(self.unit("SUP", "P2", t), D("132.00"))
		self.assertEqual(self.unit("DLX", "P2", t), D("135"))

	def test_cycle_and_missing_price(self):
		rules = (RoomRule("A", "STD", None, Op.MULTIPLY, D("1"), "SUP"),
		         RoomRule("B", "SUP", None, Op.MULTIPLY, D("1"), "STD"))
		with self.assertRaises(Unsellable) as cm:
			self.unit("STD", "P1", replace(self.t, room_rules=rules))
		self.assertEqual(cm.exception.code, "ROOM_DERIVATION_CYCLE")
		with self.assertRaises(Unsellable) as cm:
			self.unit("STD", "P1", replace(self.t, room_rules=()))
		self.assertEqual(cm.exception.code, "NO_ROOM_PRICE")


def _pol(rule_id, target, op, value, level, weight, **kw):
	"""A rule inherited from a pricing policy of scope ``weight`` (hotel 1 | market 2)."""
	return OccupancyRule(rule_id, target, op, D(value) if value is not None else None, base_level=level,
	                     scope_weight=weight, source=f"policy:{rule_id}", **kw)


def _without(t, *ids):
	return tuple(r for r in t.occupancy_rules if r.rule_id not in ids)


class TestPrecedenceV2(unittest.TestCase):
	"""Occupancy precedence v2 (G-30, G-31, ADR-042): the rule's origin ranks before its
	qualifiers, and an infant is priced by a rule naming its band before any band-less rule."""

	def setUp(self):
		self.t = fx.terms()

	# ── G-30: origin before qualifiers ──

	def test_version_combination_rule_beats_same_policy_rule(self):
		room = TestRoomBasis()
		room.setUp()
		t = replace(room.t, occupancy_rules=(
			*room.t.occupancy_rules,
			_pol("POL-1A", OccTarget.COMBINATION, Op.PERCENT_OF, "90", Level.HOTEL, 1, adults=1, children=0)))
		self.assertEqual(occ(t, "STD", "P1", 1).total, D("160"))       # the version's 80 % of 200

	def test_contract_rule_beats_policy_room_rule(self):
		t = replace(self.t, occupancy_rules=(
			*self.t.occupancy_rules,
			_pol("POL-A3-DLX", OccTarget.ADULT, Op.MULTIPLY, "0.90", Level.HOTEL, 1, position=3, room_type="DLX")))
		r = occ(t, "DLX", "P1", 3)
		self.assertEqual(r.total, D("364.500"))                         # 135 + 135 + 0.70 × 135
		self.assertEqual(r.slots[2].rule.rule_id, "O-A3")

	def test_hotel_market_policy_beats_market_policy(self):
		t = replace(self.t, occupancy_rules=(
			*_without(self.t, "O-CHB"),
			_pol("M-CHB", OccTarget.CHILD, Op.PERCENT_OF, "40", Level.MARKET, 2, age_band="CHB"),
			_pol("HM-CHB", OccTarget.CHILD, Op.PERCENT_OF, "45", Level.MARKET, 3, age_band="CHB")))
		self.assertEqual(occ(t, "STD", "P1", 2, 8).total, D("245"))

	def test_inherit_in_hotel_market_policy_defers_to_market_policy(self):
		t = replace(self.t, occupancy_rules=(
			*_without(self.t, "O-CHB"),
			_pol("HM-CHB", OccTarget.CHILD, Op.INHERIT, None, Level.MARKET, 3, age_band="CHB"),
			_pol("M-CHB", OccTarget.CHILD, Op.PERCENT_OF, "40", Level.MARKET, 2, age_band="CHB"),
			_pol("H-CHB", OccTarget.CHILD, Op.PERCENT_OF, "30", Level.HOTEL, 1, age_band="CHB")))
		self.assertEqual(occ(t, "STD", "P1", 2, 8).total, D("240"))

	# ── G-31: an infant is priced by its band ──

	def test_infant_is_priced_by_its_band_rule_not_a_band_less_combination_rule(self):
		ex = Explanation()
		r = occ(self.t, "STD", "P1", 2, 8, 1, explain=ex)
		self.assertEqual(r.total, D("250"))
		self.assertEqual([s.amount for s in r.slots], [D("100"), D("100"), D("50"), D("0")])
		self.assertEqual(r.slots[3].rule.rule_id, "O-INF")
		infant_step = [s for s in ex.steps if s.code == "CHILD_SLOT"][-1]
		self.assertIn("O-2A2C-C2", [o.rule_id for o in infant_step.overridden])

	def test_band_less_position_rule_never_prices_an_infant(self):
		t = replace(self.t, occupancy_rules=(
			*self.t.occupancy_rules, OccupancyRule("O-C1", OccTarget.CHILD, Op.MULTIPLY, D("0.5"), position=1)))
		self.assertEqual(occ(t, "STD", "P1", 2, 1).total, D("200"))
		self.assertEqual(occ(t, "STD", "P1", 2, 4).total, D("250"))    # a child: the position rule still wins

	def test_policy_infant_rule_beats_version_band_less_rule(self):
		t = replace(self.t, occupancy_rules=(
			*_without(self.t, "O-INF"), OccupancyRule("O-C1", OccTarget.CHILD, Op.MULTIPLY, D("0.5"), position=1),
			_pol("G-INF", OccTarget.CHILD, Op.MULTIPLY, "0", Level.GLOBAL, 0, age_band="INF")))
		self.assertEqual(occ(t, "STD", "P1", 2, 1).total, D("200"))

	def test_band_less_rule_still_prices_an_infant_without_a_band_rule(self):
		t = replace(self.t, occupancy_rules=(
			*_without(self.t, "O-INF"), OccupancyRule("O-ANY", OccTarget.CHILD, Op.PERCENT_OF, D("50"))))
		self.assertEqual(occ(t, "STD", "P1", 2, 1).total, D("250"))

	def test_an_explicit_infant_combination_rule_wins(self):
		t = replace(self.t, occupancy_rules=(
			*self.t.occupancy_rules,
			OccupancyRule("O-2A2C-INF", OccTarget.CHILD, Op.FIXED, D("10"), position=2, age_band="INF",
			              adults=2, children=2)))
		self.assertEqual(occ(t, "STD", "P1", 2, 8, 1).total, D("260"))

	def test_legacy_payload_keeps_its_sold_price(self):
		legacy = replace(self.t, occupancy_precedence=1)
		self.assertEqual(occ(legacy, "STD", "P1", 2, 8, 1).total, D("275"))   # as sold before v2
