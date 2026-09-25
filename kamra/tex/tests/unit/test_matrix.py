"""Pricing Workspace read models (ADR-061, GAP-2, GAP-2b): where a room's unit comes from, and
the occupancy total of a sample party, both from the engine's own resolvers; and (GAP-7) an entered
price adjusted once, as the ARI grid's rate change adjusts it."""

import unittest
from dataclasses import replace
from datetime import date
from decimal import Decimal

from kamra.tex.money import quantize, to_str
from kamra.tex.pricing import engine, matrix, ops
from kamra.tex.pricing.enums import ChildOrdering, OccTarget, Op, PricingBasis
from kamra.tex.pricing.model import ChildSpec, OccupancyRule, PricingError, RoomRule, Unsellable
from kamra.tex.tests.unit import fixtures as fx

D = Decimal


def period(t, code):
	return next(p for p in t.periods if p.code == code)


def engine_occupancy(t, room, check_in, adults, *kid_ages):
	"""The occupancy total ``engine.price_stay`` computes for one night."""
	q = engine.price_stay(fx.ctx(t), fx.req(room_type=room, check_in=check_in,
	                                         check_out=date.fromordinal(check_in.toordinal() + 1), adults=adults,
	                                         children=tuple(ChildSpec(age=a) for a in kid_ages)))
	assert q.sellable, q.reasons
	return q.nights[0].occupancy


class TestUnitSource(unittest.TestCase):
	def setUp(self):
		self.t = fx.terms()

	def test_a_generic_formula_is_the_source_for_every_period(self):
		src = matrix.unit_source(self.t, "SUP", period(self.t, "P2"))
		self.assertEqual(src, {"rule_id": "R-SUP", "scope": "ALL", "op": "MULTIPLY", "value": "1.15",
		                       "base_room_type": "STD", "chain": ["SUP", "STD"], "overridden": []})

	def test_a_period_price_overrides_the_generic_formula(self):
		src = matrix.unit_source(self.t, "SUITE", period(self.t, "P3A"))
		self.assertEqual(src["rule_id"], "R-SUITE-P3A")
		self.assertEqual(src["scope"], "PERIOD")
		self.assertEqual((src["op"], src["value"]), ("ABSOLUTE", "245"))
		self.assertIsNone(src["base_room_type"])
		self.assertEqual(src["chain"], ["SUITE"])
		self.assertEqual(src["overridden"], ["R-SUITE"])
		# elsewhere the generic formula still prices the suite
		self.assertEqual(matrix.unit_source(self.t, "SUITE", period(self.t, "P3"))["rule_id"], "R-SUITE")

	def test_the_base_rooms_own_price(self):
		src = matrix.unit_source(self.t, "STD", period(self.t, "P1"))
		self.assertEqual(src, {"rule_id": "R-STD-P1", "scope": "PERIOD", "op": "ABSOLUTE", "value": "100",
		                       "base_room_type": None, "chain": ["STD"], "overridden": []})

	def test_an_inherit_period_row_is_overridden_and_the_generic_rule_wins(self):
		t = replace(self.t, room_rules=(*self.t.room_rules, RoomRule("R-SUP-P1", "SUP", "P1", Op.INHERIT, None)))
		src = matrix.unit_source(t, "SUP", period(t, "P1"))
		self.assertEqual((src["rule_id"], src["scope"]), ("R-SUP", "ALL"))
		self.assertEqual(src["overridden"], ["R-SUP-P1"])

	def test_a_chained_derivation_names_every_room(self):
		t = replace(self.t, room_rules=tuple(
			RoomRule("R-DLX", "DLX", None, Op.MULTIPLY, D("1.10"), "SUP") if r.rule_id == "R-DLX" else r
			for r in self.t.room_rules))
		src = matrix.unit_source(t, "DLX", period(t, "P1"))
		self.assertEqual(src["chain"], ["DLX", "SUP", "STD"])
		self.assertEqual((src["base_room_type"], src["value"]), ("SUP", "1.1"))

	def test_rows_sharing_an_id_are_told_apart_as_room_unit_picks_them(self):
		# two unsaved rows posted with one client key (a client bug) share their rule id
		t = replace(self.t, room_rules=(*(r for r in self.t.room_rules if r.room_type != "SUP"),
		                                RoomRule("~dup", "SUP", None, Op.MULTIPLY, D("1.2"), "STD"),
		                                RoomRule("~dup", "SUP", "P1", Op.ABSOLUTE, D("200"))))
		p1, p2 = matrix.unit_source(t, "SUP", period(t, "P1")), matrix.unit_source(t, "SUP", period(t, "P2"))
		self.assertEqual((p1["scope"], p1["op"], p1["value"]), ("PERIOD", "ABSOLUTE", "200"))
		self.assertEqual((p2["scope"], p2["op"], p2["value"]), ("ALL", "MULTIPLY", "1.2"))

	def test_a_derivation_cycle_is_unsellable(self):
		t = replace(self.t, room_rules=tuple(
			RoomRule("R-STD-P1", "STD", "P1", Op.MULTIPLY, D("0.9"), "SUP") if r.rule_id == "R-STD-P1" else r
			for r in self.t.room_rules))
		with self.assertRaises(Unsellable) as cm:
			matrix.unit_source(t, "SUP", period(t, "P1"))
		self.assertEqual(cm.exception.code, "ROOM_DERIVATION_CYCLE")

	def test_no_price_is_unsellable(self):
		t = replace(self.t, room_rules=tuple(r for r in self.t.room_rules if r.rule_id != "R-STD-P2"))
		with self.assertRaises(Unsellable) as cm:
			matrix.unit_source(t, "STD", period(t, "P2"))
		self.assertEqual(cm.exception.code, "NO_ROOM_PRICE")


class TestPartyTotal(unittest.TestCase):
	def setUp(self):
		self.t = fx.terms()

	def test_two_adults_and_a_child_equal_the_engines_occupancy(self):
		total, slots = matrix.party_total(self.t, "STD", period(self.t, "P1"), 2, ["CHB"])
		self.assertEqual(total, D("250"))
		self.assertEqual(total, engine_occupancy(self.t, "STD", date(2027, 6, 2), 2, 7))
		self.assertEqual(slots, [
			{"target": "ADULT", "position": 1, "age_band": None, "amount": "100.00", "rule_id": "O-A1",
			 "included": False},
			{"target": "ADULT", "position": 2, "age_band": None, "amount": "100.00", "rule_id": "O-A2",
			 "included": False},
			{"target": "CHILD", "position": 1, "age_band": "CHB", "amount": "50", "rule_id": "O-CHB",
			 "included": False},
		])

	def test_children_are_ordered_as_the_contract_orders_them(self):
		p = period(self.t, "P1")
		for ordering, expected in ((ChildOrdering.OLDEST_FIRST, D("275")), (ChildOrdering.YOUNGEST_FIRST, D("250"))):
			t = replace(self.t, child_ordering=ordering)
			total, slots = matrix.party_total(t, "STD", p, 2, ["cha", "CHB"])
			self.assertEqual(total, expected, ordering)
			self.assertEqual(total, engine_occupancy(t, "STD", date(2027, 6, 2), 2, 3, 7), ordering)
			first = next(s for s in slots if s["target"] == "CHILD" and s["position"] == 1)
			self.assertEqual(first["age_band"], "CHB" if ordering == ChildOrdering.OLDEST_FIRST else "CHA")

	def test_a_derived_room_and_a_period_override(self):
		for room, code, day in (("SUP", "P2", date(2027, 6, 20)), ("SUITE", "P3A", date(2027, 8, 3))):
			total, _slots = matrix.party_total(self.t, room, period(self.t, code), 3, ["INF"])
			self.assertEqual(total, engine_occupancy(self.t, room, day, 3, 1), room)

	def test_room_basis(self):
		t = replace(self.t, basis=PricingBasis.ROOM)
		total, slots = matrix.party_total(t, "STD", period(t, "P1"), 3, [])
		self.assertEqual(total, D("135"))                      # room 100 + adult 3 ×0.70 of 50
		self.assertEqual(total, engine_occupancy(t, "STD", date(2027, 6, 2), 3))
		self.assertEqual([s["included"] for s in slots], [True, True, False])
		self.assertIsNone(slots[0]["rule_id"])

	def test_each_child_is_at_the_lower_edge_of_its_band_as_the_sweep_prices_it(self):
		p = period(self.t, "P1")
		for ordering, codes in ((ChildOrdering.OLDEST_FIRST, ["TEEN", "CHB", "INF"]),
		                        (ChildOrdering.YOUNGEST_FIRST, ["INF", "CHB", "TEEN"])):
			party = matrix.sample_party(replace(self.t, child_ordering=ordering), 2, ["chb", "INF", "TEEN"], p.start)
			self.assertEqual([(s.position, s.band.code, s.months) for s in party.children],
			                 [(i + 1, c, {"INF": 0, "CHB": 84, "TEEN": 144}[c]) for i, c in enumerate(codes)], ordering)
			self.assertEqual([s.input_index for s in party.children],
			                 [["CHB", "INF", "TEEN"].index(c) for c in codes])
			self.assertEqual((party.adults, party.declared_adults, party.infants, party.reference_date),
			                 (2, 2, 1, p.start))

	def test_an_unknown_band_raises(self):
		with self.assertRaises(PricingError):
			matrix.party_total(self.t, "STD", period(self.t, "P1"), 2, ["XX"])

	def test_a_room_that_cannot_host_the_party_is_unsellable(self):
		with self.assertRaises(Unsellable) as cm:
			matrix.party_total(self.t, "STD", period(self.t, "P1"), 2, ["CHA", "CHA", "CHB"])
		self.assertEqual(cm.exception.code, "MAX_CHILDREN")

	def test_a_child_band_without_a_rule_is_unsellable(self):
		t = replace(self.t, occupancy_rules=tuple(r for r in self.t.occupancy_rules if r.rule_id != "O-TEEN"))
		with self.assertRaises(Unsellable) as cm:
			matrix.party_total(t, "STD", period(t, "P1"), 2, ["TEEN"])
		self.assertEqual(cm.exception.code, "NO_CHILD_RULE")


class TestPartyRules(unittest.TestCase):
	"""The rules that take part in pricing a sample party, also when it cannot be priced: a
	viewer who may not read some rules is told nothing about a party one of them prices (S16
	review: a whole-party rule is not a slot rule, and a failure's message is an oracle too)."""

	def setUp(self):
		self.t = fx.terms()
		self.p1 = period(self.t, "P1")

	def test_each_slots_winner_and_the_whole_party_rule(self):
		self.assertEqual(matrix.party_rules(self.t, "STD", self.p1, 2, ["CHB"]), {"O-A1", "O-A2", "O-CHB"})
		combo = OccupancyRule("O-2A0C", OccTarget.COMBINATION, Op.ADJUST_PERCENT, D("-10"), adults=2, children=0)
		t = replace(self.t, occupancy_rules=(*self.t.occupancy_rules, combo))
		total, slots = matrix.party_total(t, "STD", self.p1, 2, [])
		self.assertEqual((total, {s["rule_id"] for s in slots}), (D("180"), {"O-A1", "O-A2"}))
		self.assertEqual(matrix.party_rules(t, "STD", self.p1, 2, []), {"O-A1", "O-A2", "O-2A0C"})

	def test_a_party_that_cannot_be_priced(self):
		probe = OccupancyRule("V-PROBE", OccTarget.COMBINATION, Op.SUBTRACT, D("251"), adults=2, children=1)
		t = replace(self.t, occupancy_rules=(*self.t.occupancy_rules, probe))
		with self.assertRaises(Unsellable) as cm:
			matrix.party_total(t, "STD", self.p1, 2, ["CHB"])
		self.assertEqual(cm.exception.code, "NEGATIVE_OCCUPANCY_PRICE")
		# every rule priced before the total fell below zero
		self.assertEqual(matrix.party_rules(t, "STD", self.p1, 2, ["CHB"]), {"O-A1", "O-A2", "O-CHB", "V-PROBE"})
		# the rules an ambiguity names
		twin = OccupancyRule("O-CHB-2", OccTarget.CHILD, Op.PERCENT_OF, D("40"), age_band="CHB")
		t = replace(self.t, occupancy_rules=(*self.t.occupancy_rules, twin))
		self.assertEqual(matrix.party_rules(t, "STD", self.p1, 2, ["CHB"]), {"O-A1", "O-A2", "O-CHB", "O-CHB-2"})
		# a child without a rule: the rules resolved before it
		t = replace(self.t, occupancy_rules=tuple(r for r in self.t.occupancy_rules if r.rule_id != "O-TEEN"))
		self.assertEqual(matrix.party_rules(t, "STD", self.p1, 2, ["TEEN"]), {"O-A1", "O-A2"})

	def test_no_rule_takes_part_before_the_occupancy_is_priced(self):
		for room, adults, kids in (("STD", 2, ["CHA", "CHA", "CHB"]), ("STD", 2, ["XX"]), ("NOPE", 2, [])):
			with self.subTest(room=room, kids=kids):
				self.assertEqual(matrix.party_rules(self.t, room, self.p1, adults, kids), frozenset())
		t = replace(self.t, room_rules=tuple(r for r in self.t.room_rules if r.rule_id != "R-STD-P1"))
		self.assertEqual(matrix.party_rules(t, "STD", self.p1, 2, []), frozenset())


class TestBandLayer(unittest.TestCase):
	"""Where a contract without bands of its own takes them from (``price_matrix`` names it)."""

	def test_the_most_specific_policy_defining_bands(self):
		from kamra.tex.pricing import inherit
		from kamra.tex.tests.unit.test_policy_cascade import GLOBAL, HOTEL, LAYERS, MARKET

		self.assertIs(inherit.band_layer(LAYERS), MARKET)
		self.assertIs(inherit.band_layer((GLOBAL, HOTEL)), GLOBAL)
		self.assertIsNone(inherit.band_layer((HOTEL,)))
		self.assertEqual(inherit.cascade((), (), LAYERS)[0], inherit.band_layer(LAYERS).bands)
		self.assertEqual(MARKET.source, "policy:POL-M/r1/market")


class TestRuleValue(unittest.TestCase):
	def test_exact_text_without_trailing_zeros(self):
		self.assertEqual(matrix.rule_value(D("1")), "1")
		self.assertEqual(matrix.rule_value(D("1.150000000")), "1.15")
		self.assertEqual(matrix.rule_value(D("0.333333333")), "0.333333333")
		self.assertEqual(matrix.rule_value(D("1E+2")), "100")
		self.assertEqual(matrix.rule_value(D("-0.00")), "0")
		self.assertIsNone(matrix.rule_value(None))


class TestAdjustAmount(unittest.TestCase):
	"""GAP-7 (ADR-061): an entered price changed once by a relative entry on the base room (O4) or by
	the bulk Adjust…, computed as the ARI grid's rate change computes it (``grid.apply_rate_change``):
	the op on the current price, rounded HALF_UP to the currency's minor unit."""

	def text(self, current, op, value, currency="EUR"):
		out = matrix.adjust_amount(D(current), op, D(value), currency)
		self.assertIsInstance(out, Decimal)
		return to_str(out)

	def test_the_owners_examples(self):
		cases = (
			("70", Op.ADJUST_PERCENT, "10", "EUR", "77.00"),
			("80.55", Op.ADJUST_PERCENT, "10", "EUR", "88.61"),         # 88.605: HALF_UP, not HALF_EVEN
			("100", Op.MULTIPLY, "1.155", "EUR", "115.50"),
			("1000", Op.MULTIPLY, "1.155", "JPY", "1155"),
			("12.345", Op.ADJUST_PERCENT, "10", "KWD", "13.580"),       # 3 places
			("99.99", Op.ADJUST_PERCENT, "-100", "EUR", "0.00"),
			("70", Op.ADJUST_PERCENT, "0", "EUR", "70.00"),
			("70", Op.PERCENT_OF, "50", "EUR", "35.00"),
			("70", Op.ADD, "5", "EUR", "75.00"),
			("70", Op.SUBTRACT, "5", "EUR", "65.00"),
			("70", Op.ADJUST_PERCENT, "-10", "EUR", "63.00"),
			("70", Op.MULTIPLY, "1.1", "EUR", "77.00"),
		)
		for current, op, value, currency, expected in cases:
			with self.subTest(current=current, op=op, value=value, currency=currency):
				self.assertEqual(self.text(current, op, value, currency), expected)

	def test_absolute_is_the_value_whatever_the_current_price(self):
		self.assertEqual(self.text("70", Op.ABSOLUTE, "82.5"), "82.50")
		self.assertEqual(self.text("0", Op.ABSOLUTE, "82.555"), "82.56")
		self.assertEqual(self.text("70", Op.ABSOLUTE, "82.5", "JPY"), "83")

	def test_a_negative_result_is_refused(self):
		for current, op, value in (("10", Op.SUBTRACT, "20"), ("10", Op.ADD, "-10.01"), ("10", Op.ABSOLUTE, "-1"),
		                           ("10", Op.ADJUST_PERCENT, "-101"), ("10", Op.MULTIPLY, "-1")):
			with self.subTest(op=op, value=value), self.assertRaises(PricingError) as cm:
				matrix.adjust_amount(D(current), op, D(value), "EUR")
			self.assertEqual(str(cm.exception), "NEGATIVE")

	def test_the_op_is_applied_as_the_engine_applies_it(self):
		# relative ops take the current price as both reference and running amount (grid.py)
		for op, value in ((Op.MULTIPLY, "1.2345"), (Op.PERCENT_OF, "33.3"), (Op.ADJUST_PERCENT, "7.5"),
		                  (Op.ADD, "0.004"), (Op.SUBTRACT, "0.005")):
			with self.subTest(op=op):
				exact = ops.apply_op(op, D(value), reference=D("123.45"), current=D("123.45"))
				self.assertEqual(matrix.adjust_amount(D("123.45"), op, D(value), "EUR"), quantize(exact, "EUR"))


if __name__ == "__main__":
	unittest.main()
