"""Validation issues say what they are about (ADR-061 D9, GAP-4), and board rules are checked like
room rules (GAP-5), for the Pricing Workspace: both are its opt-in (ADR-061, "Existing semantics
kept, the workspace's additions opt-in"), so every other caller gets main's issues.

* An ``Issue`` carries an optional ``ref``: the rule(s), room, period, age band(s), party and board
  it names, so the Pricing Workspace can mark the cell or row and replace band codes by labels.
  ``to_dict(ref=True)`` adds ``"ref"`` only when there is one; ``to_dict()`` is main's three keys.
  Codes and messages are unchanged.
* With ``board_checks``, new ERRORs: a board rule naming a room or period the contract does not
  have (``BOARD_UNKNOWN_ROOM`` / ``BOARD_UNKNOWN_PERIOD``), and two or more rules of one board for
  the same room and period (``BOARD_DUPLICATE``), which the engine would otherwise settle by row
  name. Without it they are not reported, as on main.
"""

import unittest
from dataclasses import replace
from datetime import date
from decimal import Decimal

from kamra.tex.pricing import inherit, validate
from kamra.tex.pricing.enums import Level, OccTarget, Op, PricingBasis
from kamra.tex.pricing.model import AgeBand, BoardRule, OccupancyRule, Period, RoomRule
from kamra.tex.tests.unit import fixtures as fx

D = Decimal
CHILD, ADULT, COMBINATION = OccTarget.CHILD, OccTarget.ADULT, OccTarget.COMBINATION
BAND_CODES = ["INF", "CHA", "CHB", "TEEN"]      # the fixture's bands, in the contract's order
INHERITED = dict(base_level=Level.HOTEL, scope_weight=1, source="policy:POL-H/r1/hotel")


def found(t, code, **kw):
	return [i for i in validate.validate_terms(t, **kw) if i.code == code]


def refs(t, code, **kw):
	return [i.ref for i in found(t, code, **kw)]


def with_rooms(t, **changes):
	return replace(t, rooms={k: replace(v, **changes.get(k, {})) for k, v in t.rooms.items()})


def with_rule(t, rule_id, **changes):
	return replace(t, room_rules=tuple(replace(r, **changes) if r.rule_id == rule_id else r for r in t.room_rules))


def with_occ(*extra, drop=()):
	return fx.terms(occupancy_rules=(*(r for r in fx.occ_rules() if r.rule_id not in drop), *extra))


def with_boards(*extra):
	return fx.terms(boards=(*fx.board_rules(), *extra))


def uai(rule_id, **kw):
	return BoardRule(rule_id, "UAI", op=Op.ADD, adult_amount=D("25"), **kw)


class TestIssueShape(unittest.TestCase):
	def test_ref_is_an_optional_last_field(self):
		plain = validate.Issue("ERROR", "X", "m")
		self.assertIsNone(plain.ref)
		self.assertEqual(validate.Issue("ERROR", "X", "m", {"room_type": "STD"}).ref, {"room_type": "STD"})

	def test_to_dict_adds_ref_only_when_there_is_one(self):
		self.assertEqual(validate.Issue("ERROR", "X", "m").to_dict(ref=True),
		                 {"level": "ERROR", "code": "X", "message": "m"})
		self.assertEqual(validate.Issue("ERROR", "X", "m", {}).to_dict(ref=True),
		                 {"level": "ERROR", "code": "X", "message": "m"})
		self.assertEqual(validate.Issue("WARNING", "X", "m", {"period": "P1"}).to_dict(ref=True),
		                 {"level": "WARNING", "code": "X", "message": "m", "ref": {"period": "P1"}})

	def test_to_dict_is_mains_unless_the_ref_is_asked_for(self):
		self.assertEqual(validate.Issue("WARNING", "X", "m", {"period": "P1"}).to_dict(),
		                 {"level": "WARNING", "code": "X", "message": "m"})

	def test_an_issue_is_still_hashable(self):
		self.assertEqual(len({validate.Issue("ERROR", "X", "m", {"rule_ids": ["a", "b"]})}), 1)

	def test_header_issues_have_no_ref(self):
		t = replace(fx.terms(), currency="EURO", sale_from=date(2028, 1, 1), stay_from=date(2028, 1, 1))
		issues = validate.validate_terms(t)
		self.assertEqual([i.code for i in issues], ["CURRENCY", "SALE_WINDOW", "STAY_WINDOW"])
		self.assertTrue(all(i.ref is None and "ref" not in i.to_dict(ref=True) for i in issues))
		self.assertIsNone(found(replace(fx.terms(), boards=fx.board_rules()[1:]), "NO_BASE_BOARD")[0].ref)

	def test_missing_parts_are_left_out_zero_is_kept(self):
		# a rule for every period has no period; a party without children has children 0
		t = replace(fx.terms(), room_rules=(*fx.room_rules(), RoomRule("dup", "SUP", None, Op.MULTIPLY, D(1), "STD")))
		self.assertEqual(refs(t, "ROOM_RULE_DUPLICATE"),
		                 [{"rule_id": "R-SUP", "rule_ids": ["R-SUP", "dup"], "room_type": "SUP"}])
		t = with_occ(OccupancyRule("O-A3-DUP", ADULT, Op.MULTIPLY, D("0.8"), position=3))
		amb = next(i for i in validate._sweep(t, 50) if i.code == "AMBIGUOUS_OCCUPANCY_RULES")
		self.assertEqual(amb.ref, {"room_type": "DLX", "period": "P1", "adults": 3, "children": 0,
		                           "rule_id": "O-A3", "rule_ids": ["O-A3", "O-A3-DUP"]})


class TestMessagesUnchanged(unittest.TestCase):
	"""Byte for byte the texts before GAP-4 (the scenarios of test_contracts_restrictions)."""

	def test_room_rule_duplicate(self):
		t = replace(fx.terms(), room_rules=(*fx.room_rules(), RoomRule("dup", "STD", "P1", Op.ABSOLUTE, D(1))))
		self.assertEqual([i.message for i in found(t, "ROOM_RULE_DUPLICATE")], ["room STD has two rules for period P1"])

	def test_occupancy_duplicate(self):
		t = with_occ(OccupancyRule("dup", CHILD, Op.PERCENT_OF, D(5), age_band="CHB"))
		self.assertEqual([i.message for i in found(t, "OCC_DUPLICATE")],
		                 ["rules O-CHB, dup share the same scope (target, position, band, room, period, combination, "
		                  "override); keep one"])

	def test_period_overlap(self):
		t = replace(fx.terms(), periods=(*fx.periods(), Period("PX", "x", date(2027, 6, 10), date(2027, 6, 20))))
		self.assertEqual([i.message for i in found(t, "PERIOD_OVERLAP")],
		                 ["periods P1 and PX overlap with equal priority", "periods P2 and PX overlap with equal priority"])

	def test_the_reference_contract_is_still_clean(self):
		self.assertEqual(validate.validate_terms(fx.terms()), [])


class TestRoomAndPeriodRefs(unittest.TestCase):
	def test_room_capacity_and_included_adults_name_the_room(self):
		t = with_rooms(fx.terms(), STD={"max_adults": 0}, SUP={"max_occupants": 2})
		self.assertEqual(refs(t, "ROOM_CAPACITY"), [{"room_type": "STD"}, {"room_type": "SUP"}])
		t = with_rooms(replace(fx.terms(), basis=PricingBasis.ROOM), DLX={"included_adults": 5})
		self.assertEqual(refs(t, "INCLUDED_ADULTS"), [{"room_type": "DLX"}])

	def test_periods(self):
		t = replace(fx.terms(), periods=(*fx.periods(), Period("P1", "again", date(2027, 9, 1), date(2027, 9, 5))))
		self.assertEqual(refs(t, "PERIOD_DUPLICATE"), [{"period": "P1"}])
		t = replace(fx.terms(), periods=(*fx.periods(), Period("PR", "back", date(2027, 9, 5), date(2027, 9, 1))))
		self.assertEqual(refs(t, "PERIOD_RANGE"), [{"period": "PR"}])
		t = replace(fx.terms(), periods=(*fx.periods(), Period("PX", "x", date(2027, 6, 10), date(2027, 6, 20))))
		self.assertEqual(refs(t, "PERIOD_OVERLAP"),
		                 [{"period": "P1", "other_period": "PX"}, {"period": "P2", "other_period": "PX"}])

	def test_room_rule_duplicate_names_every_twin(self):
		t = replace(fx.terms(), room_rules=(*fx.room_rules(), RoomRule("dup", "STD", "P1", Op.ABSOLUTE, D(1))))
		self.assertEqual(refs(t, "ROOM_RULE_DUPLICATE"),
		                 [{"rule_id": "R-STD-P1", "rule_ids": ["R-STD-P1", "dup"], "room_type": "STD", "period": "P1"}])

	def test_room_rules_naming_what_the_contract_lacks(self):
		t = replace(fx.terms(), room_rules=(*fx.room_rules(), RoomRule("x", "ZZZ", "P1", Op.ABSOLUTE, D(1)),
		                                     RoomRule("y", "STD", "PZ", Op.ABSOLUTE, D(1))))
		self.assertEqual(refs(t, "ROOM_RULE_UNKNOWN_ROOM"), [{"rule_id": "x", "room_type": "ZZZ", "period": "P1"}])
		self.assertEqual(refs(t, "ROOM_RULE_UNKNOWN_PERIOD"), [{"rule_id": "y", "room_type": "STD", "period": "PZ"}])

	def test_a_formula_without_a_base_room(self):
		t = with_rule(fx.terms(), "R-SUP", base_room_type=None)
		self.assertEqual(refs(t, "ROOM_RULE_NO_BASE"), [{"rule_id": "R-SUP", "room_type": "SUP"}])
		# … and each period's cell it leaves without a price (a room_unit error)
		self.assertEqual(refs(t, "ROOM_DERIVATION_NO_BASE"),
		                 [{"rule_id": "R-SUP", "room_type": "SUP", "period": p} for p in ("P1", "P2", "P3", "P3A")])

	def test_a_negative_cell_names_the_rule_that_priced_it(self):
		t = with_rule(fx.terms(), "R-STD-P1", value=D(-5))
		self.assertEqual(refs(t, "ROOM_NEGATIVE"), [
			{"room_type": "DLX", "period": "P1", "rule_id": "R-DLX"},
			{"room_type": "STD", "period": "P1", "rule_id": "R-STD-P1"},
			{"room_type": "SUITE", "period": "P1", "rule_id": "R-SUITE"},
			{"room_type": "SUP", "period": "P1", "rule_id": "R-SUP"}])

	def test_a_cell_without_a_price(self):
		t = replace(fx.terms(), room_rules=fx.room_rules()[1:])          # no STD price in P1
		by_room = {i.ref["room_type"]: i.ref for i in found(t, "NO_ROOM_PRICE")}
		self.assertEqual(by_room["STD"], {"room_type": "STD", "period": "P1"})       # no rule of its own
		self.assertEqual(by_room["SUP"], {"room_type": "SUP", "period": "P1", "rule_id": "R-SUP"})

	def test_an_inherit_row_is_not_the_cells_rule(self):
		t = replace(fx.terms(), room_rules=(RoomRule("R-STD-P1-I", "STD", "P1", Op.INHERIT, None),
		                                     *fx.room_rules()[1:]))
		std = next(i.ref for i in found(t, "NO_ROOM_PRICE") if i.ref["room_type"] == "STD")
		self.assertEqual(std, {"room_type": "STD", "period": "P1"})

	def test_a_derivation_cycle(self):
		t = replace(fx.terms(), room_rules=(*(r for r in fx.room_rules() if not r.rule_id.startswith("R-STD")),
		                                     RoomRule("R-STD", "STD", None, Op.MULTIPLY, D(1), "SUP")))
		cyc = found(t, "ROOM_DERIVATION_CYCLE")
		self.assertIn({"room_type": "STD", "period": "P1", "rule_id": "R-STD"}, [i.ref for i in cyc])
		self.assertTrue(all(set(i.ref) == {"room_type", "period", "rule_id"} for i in cyc))


class TestAgeBandRefs(unittest.TestCase):
	def test_a_gap_carries_every_band_code(self):
		t = fx.terms(age_bands=(AgeBand("INF", "Infant", 0, 35, is_infant=True), *fx.bands()[1:]))
		self.assertEqual(refs(t, "AGE_BANDS"), [{"age_bands": BAND_CODES}])     # two bands: no single one

	def test_an_overlap_carries_every_band_code(self):
		t = fx.terms(age_bands=(AgeBand("INF", "Infant", 0, 40, is_infant=True), *fx.bands()[1:]))
		self.assertEqual(refs(t, "AGE_BANDS"), [{"age_bands": BAND_CODES}])

	def test_an_invalid_band_is_named(self):
		t = fx.terms(age_bands=(*fx.bands(), AgeBand("OLD", "Old", 200, 190)))
		self.assertEqual(refs(t, "AGE_BANDS"), [{"age_bands": [*BAND_CODES, "OLD"], "age_band": "OLD"}])


class TestOccupancyRefs(unittest.TestCase):
	def test_rules_naming_what_the_contract_lacks(self):
		t = with_occ(OccupancyRule("x", CHILD, Op.PERCENT_OF, D(5), age_band="ZZ"),
		             OccupancyRule("y", CHILD, Op.PERCENT_OF, D(5), age_band="CHB", room_type="ZZZ"),
		             OccupancyRule("z", CHILD, Op.PERCENT_OF, D(5), age_band="CHB", period="PZ"))
		self.assertEqual(refs(t, "OCC_UNKNOWN_BAND"), [{"rule_id": "x", "age_band": "ZZ"}])
		self.assertEqual(refs(t, "OCC_UNKNOWN_ROOM"), [{"rule_id": "y", "age_band": "CHB", "room_type": "ZZZ"}])
		self.assertEqual(refs(t, "OCC_UNKNOWN_PERIOD"), [{"rule_id": "z", "age_band": "CHB", "period": "PZ"}])

	def test_inherited_rules_the_contract_cannot_use(self):
		t = with_occ(OccupancyRule("H-CHD", CHILD, Op.PERCENT_OF, D(50), age_band="CHD", **INHERITED),
		             OccupancyRule("H-FAM", CHILD, Op.PERCENT_OF, D(20), age_band="CHB", room_type="FAM", **INHERITED),
		             OccupancyRule("H-PER", CHILD, Op.PERCENT_OF, D(20), age_band="CHB", period="PZ", **INHERITED),
		             OccupancyRule("H-AB", ADULT, Op.MULTIPLY, D("0.5"), age_band="INF", **INHERITED))
		self.assertEqual(refs(t, "OCC_INHERITED_BAND_UNUSED"), [{"rule_id": "H-CHD", "age_band": "CHD"}])
		self.assertEqual(refs(t, "OCC_INHERITED_ROOM_UNUSED"),
		                 [{"rule_id": "H-FAM", "age_band": "CHB", "room_type": "FAM"}])
		self.assertEqual(refs(t, "OCC_INHERITED_PERIOD_UNUSED"),
		                 [{"rule_id": "H-PER", "age_band": "CHB", "period": "PZ"}])
		self.assertEqual(refs(t, "OCC_INHERITED_ADULT_BAND_UNUSED"), [{"rule_id": "H-AB", "age_band": "INF"}])

	def test_rules_that_cannot_be_applied(self):
		t = with_occ(OccupancyRule("q", COMBINATION, Op.MULTIPLY, D("0.9")),
		             OccupancyRule("ab", ADULT, Op.MULTIPLY, D("0.9"), age_band="CHB", position=3, room_type="SUITE"),
		             OccupancyRule("nv", CHILD, Op.PERCENT_OF, None, age_band="TEEN", room_type="STD", period="P2",
		                           adults=2, children=1))
		self.assertEqual(refs(t, "OCC_COMBINATION_QUALIFIER"), [{"rule_id": "q"}])
		self.assertEqual(refs(t, "OCC_ADULT_BAND"), [{"rule_id": "ab", "age_band": "CHB", "room_type": "SUITE"}])
		self.assertEqual(refs(t, "OCC_NO_VALUE"), [{"rule_id": "nv", "age_band": "TEEN", "room_type": "STD",
		                                            "period": "P2", "adults": 2, "children": 1}])

	def test_twin_rules_name_every_twin(self):
		t = with_occ(OccupancyRule("dup", CHILD, Op.PERCENT_OF, D(5), age_band="CHB"))
		self.assertEqual(refs(t, "OCC_DUPLICATE"), [{"rule_id": "O-CHB", "rule_ids": ["O-CHB", "dup"],
		                                             "age_band": "CHB"}])

	def test_a_tie_names_both_rules_and_the_slot_it_decides(self):
		t = with_occ(OccupancyRule("P-2A", CHILD, Op.PERCENT_OF, D(60), position=1, adults=2),
		             OccupancyRule("P-2C", CHILD, Op.PERCENT_OF, D(40), position=1, children=2))
		issue = found(t, "OCC_AMBIGUOUS")[0]
		self.assertIn("child 1 (CHA) of DLX 2A+2C", issue.message)
		self.assertEqual(issue.ref, {"rule_id": "P-2A", "rule_ids": ["P-2A", "P-2C"], "room_type": "DLX",
		                             "age_band": "CHA", "adults": 2, "children": 2})
		# settled in P1 only: the slot is in P2
		t = replace(t, occupancy_rules=(*t.occupancy_rules, OccupancyRule(
			"P-2A2C", CHILD, Op.PERCENT_OF, D(50), position=1, adults=2, children=2, period="P1")))
		self.assertEqual(found(t, "OCC_AMBIGUOUS")[0].ref["period"], "P2")

	def test_an_outranked_policy_override(self):
		ovr = inherit.PolicyLayer("POL-H", 1, "HOTEL-A", None, rules=(
			OccupancyRule("H-INF-OVR", CHILD, Op.FIXED, D(15), age_band="INF", is_override=True),))
		t = fx.terms(occupancy_rules=inherit.cascade(fx.bands(), fx.occ_rules(), (ovr,))[1])
		self.assertEqual(refs(t, "OCC_POLICY_OVERRIDE_OUTRANKED"), [
			{"rule_id": "H-INF-OVR", "rule_ids": ["H-INF-OVR", "O-INF"], "room_type": "DLX", "age_band": "INF",
			 "adults": 1, "children": 1}])

	def test_infants_priced_by_band_less_rules(self):
		t = with_occ(OccupancyRule("O-ANY", CHILD, Op.PERCENT_OF, D(50)), drop=("O-INF",))
		self.assertEqual(refs(t, "OCC_INFANT_GENERIC"), [
			{"age_band": "INF", "rule_id": "O-2A2C-C2", "rule_ids": ["O-2A2C-C2", "O-ANY"]}])

	def test_a_policy_checked_on_its_own_never_names_its_placeholders(self):
		def rule(rule_id, target, op, value=None, **kw):
			return OccupancyRule(rule_id, target, op, D(value) if value is not None else None, **kw)
		issues = validate.policy_issues((), (
			rule("X1", CHILD, Op.PERCENT_OF, "30", age_band="CHB"), rule("X2", CHILD, Op.PERCENT_OF, "35", age_band="CHB"),
			rule("G-2A", CHILD, Op.PERCENT_OF, "60", position=1, adults=2),
			rule("G-2C", CHILD, Op.PERCENT_OF, "40", position=1, children=2)))
		by_code = {i.code: i for i in issues}
		self.assertEqual(by_code["OCC_DUPLICATE"].ref, {"rule_id": "X1", "rule_ids": ["X1", "X2"], "age_band": "CHB"})
		self.assertIn("child 1 (any band) of 2A+2C", by_code["OCC_AMBIGUOUS"].message)
		self.assertEqual(by_code["OCC_AMBIGUOUS"].ref, {"rule_id": "G-2A", "rule_ids": ["G-2A", "G-2C"],
		                                                 "adults": 2, "children": 2})


class TestSweepRefs(unittest.TestCase):
	def test_a_combination_without_a_rule_names_room_period_party_and_band(self):
		t = with_occ(drop=("O-TEEN",))
		warnings = found(t, "NO_CHILD_RULE")
		self.assertTrue(warnings)
		first = warnings[0]
		self.assertEqual(first.message, "DLX 1A+1C [TEEN]: no occupancy rule for child 1 in band TEEN (1A+1C)")
		self.assertEqual(first.ref, {"room_type": "DLX", "period": "P1", "adults": 1, "children": 1, "age_band": "TEEN"})
		for w in warnings:
			self.assertEqual(w.ref["age_band"], "TEEN")
			self.assertIn(f"{w.ref['room_type']} {w.ref['adults']}A+{w.ref['children']}C [TEEN]", w.message)
			self.assertIn(w.ref["period"], {"P1", "P2", "P3", "P3A"})

	def test_an_ambiguous_combination_names_the_tied_rules(self):
		t = with_occ(OccupancyRule("O-CHB-DUP", CHILD, Op.PERCENT_OF, D(60), age_band="CHB"))
		amb = [i for i in validate._sweep(t, 50) if i.code == "AMBIGUOUS_OCCUPANCY_RULES"]
		self.assertTrue(amb)
		self.assertEqual(amb[0].ref, {"room_type": "DLX", "period": "P1", "adults": 1, "children": 2,
		                              "age_band": "CHB", "rule_id": "O-CHB", "rule_ids": ["O-CHB", "O-CHB-DUP"]})


BOARD_CHECKS = {"board_checks": True}


class TestBoardRules(unittest.TestCase):
	def test_the_fixture_boards_are_clean(self):
		# AI (base) and UAI (+20 per adult): none of the new checks fires
		self.assertEqual([i.code for i in validate.validate_terms(fx.terms(), **BOARD_CHECKS)
		                  if i.code.startswith("BOARD_")], [])

	def test_without_board_checks_the_issues_are_mains(self):
		"""An existing caller is not told about board rows main published (ADR-061)."""
		for t in (with_boards(uai("B-X", room_type="ZZZ")), with_boards(uai("B-Y", room_type="SUP", period="PZ")),
		          with_boards(uai("B-UAI2")), replace(fx.terms(), boards=(uai("B-X", room_type="ZZZ"),))):
			self.assertEqual([i.code for i in validate.validate_terms(t) if i.code.startswith("BOARD_")], [])
			# the checks add their own issues only (their errors stop the sweep, as any error does)
			plain = validate.validate_terms(t, sweep_combinations=False)
			checked = validate.validate_terms(t, sweep_combinations=False, **BOARD_CHECKS)
			self.assertEqual([i for i in checked if not i.code.startswith("BOARD_")], plain)
			self.assertTrue([i for i in checked if i.code.startswith("BOARD_")])

	def test_a_board_rule_for_an_unknown_room(self):
		issues = found(with_boards(uai("B-X", room_type="ZZZ")), "BOARD_UNKNOWN_ROOM", **BOARD_CHECKS)
		self.assertEqual([(i.level, i.message, i.ref) for i in issues], [
			("ERROR", "board rule B-X (UAI) names unknown room ZZZ",
			 {"rule_id": "B-X", "board": "UAI", "room_type": "ZZZ"})])

	def test_a_board_rule_for_an_unknown_period(self):
		issues = found(with_boards(uai("B-Y", room_type="SUP", period="PZ")), "BOARD_UNKNOWN_PERIOD", **BOARD_CHECKS)
		self.assertEqual([(i.level, i.message, i.ref) for i in issues], [
			("ERROR", "board rule B-Y (UAI) names unknown period PZ",
			 {"rule_id": "B-Y", "board": "UAI", "room_type": "SUP", "period": "PZ"})])

	def test_two_rules_of_one_board_for_the_same_room_and_period(self):
		issues = found(with_boards(uai("B-UAI2")), "BOARD_DUPLICATE", **BOARD_CHECKS)
		self.assertEqual([(i.level, i.message, i.ref) for i in issues], [
			("ERROR", "board UAI has 2 rules for the same room and period",
			 {"rule_id": "B-UAI", "rule_ids": ["B-UAI", "B-UAI2"], "board": "UAI"})])
		scoped = found(with_boards(uai("S1", room_type="SUP", period="P1"), uai("S2", room_type="SUP", period="P1"),
		                           uai("S3", room_type="SUP", period="P1")), "BOARD_DUPLICATE", **BOARD_CHECKS)
		self.assertEqual([(i.message, i.ref) for i in scoped], [
			("board UAI has 3 rules for the same room and period",
			 {"rule_id": "S1", "rule_ids": ["S1", "S2", "S3"], "board": "UAI", "room_type": "SUP", "period": "P1"})])
		# two base rows of the included board are twins too
		self.assertEqual(len(found(with_boards(BoardRule("B-AI2", "AI", is_base=True)), "BOARD_DUPLICATE",
		                           **BOARD_CHECKS)), 1)

	def test_rules_of_one_board_for_different_scopes_are_fine(self):
		t = with_boards(uai("B-SUP", room_type="SUP"), uai("B-SUP-P1", room_type="SUP", period="P1"),
		                uai("B-P1", period="P1"), BoardRule("B-HB", "HB", op=Op.ADD, adult_amount=D(10)))
		self.assertEqual(validate.validate_terms(t, **BOARD_CHECKS), [])

	def test_board_errors_block_publishing_and_come_after_the_base_board_check(self):
		t = replace(fx.terms(), boards=(uai("B-X", room_type="ZZZ"), uai("B-Y", period="PZ")))
		self.assertEqual([i.code for i in validate.validate_terms(t, **BOARD_CHECKS)],
		                 ["NO_BASE_BOARD", "BOARD_UNKNOWN_ROOM", "BOARD_UNKNOWN_PERIOD"])
		self.assertEqual([i.code for i in validate.validate_terms(t)], ["NO_BASE_BOARD"])


if __name__ == "__main__":
	unittest.main()
