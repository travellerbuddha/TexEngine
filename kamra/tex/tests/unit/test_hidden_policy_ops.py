"""A viewer without ``price.view_cost`` learns nothing of a hidden pricing-policy rule's op (ADR-061,
S16 re-review 4).

A pricing policy's formulas are cost (G-11). An editor who may not read them is told which inherited
rule applies where, never its op or value, and nothing whose presence or wording depends on them:
not whether a rule defers (INHERIT), not whether it prices, not what it prices. What such a viewer is
told of a draft or a published version:

* the live check (``validate.validate_terms(hidden=…)``, the workspace's ``validate_version``);
* the sample parties of the price matrix (``matrix.party_hidden``, then ``matrix.party_total``, as
  ``api.contracts._party_cells`` answers them);
* the report stored at publish (``validate.visible_issues``, get_version's and publish's).

Each test prices the same terms once per op of the hidden rules and asserts that the viewer is told
exactly the same thing every time. ``TestTheReportedLeaks`` holds the two reproductions of the
re-review's medium finding (a missing rule for a later child, a tie of the version's rules under a
hidden infant rule) and a stored report's party that moved to a later period;
``TestGeneratedRuleSets`` checks the same on rule sets generated from a fixed seed.
"""

import itertools
import random
import unittest
from dataclasses import replace
from datetime import date
from decimal import Decimal
from unittest import mock

from kamra.tex.pricing import inherit, matrix, validate
from kamra.tex.pricing.enums import OccTarget, Op, PricingBasis
from kamra.tex.pricing.model import AgeBand, Period, PricingError, RoomRule, RoomSpec, Unsellable
from kamra.tex.tests.unit.test_policy_cascade import cascaded, rule

D = Decimal
CHILD, ADULT, COMBINATION = OccTarget.CHILD, OccTarget.ADULT, OccTarget.COMBINATION
BANDS = (AgeBand("INF", "Infant", 0, 36, is_infant=True), AgeBand("CHD", "Child", 36, 144))
OWN_ADULTS = (rule("V-A1", ADULT, Op.MULTIPLY, "1", position=1), rule("V-A2", ADULT, Op.MULTIPLY, "1", position=2))


def hidden_of(t) -> frozenset[str]:
	"""What ``contracts.policy_rules`` hides from a viewer without cost: every inherited rule."""
	return frozenset(r.rule_id for r in t.occupancy_rules if r.source != "version")


def sample_parties(t):
	codes = [b.code for b in t.age_bands]
	kids = [(), *((c,) for c in codes), *itertools.product(codes, repeat=2)]
	return [(adults, tuple(k)) for adults in (1, 2, 3) for k in kids]


def party_cells(t, hidden) -> dict:
	"""The sample parties as ``price_matrix`` answers them to the viewer (``_party_cells``)."""
	cells = {}
	for rt in sorted(t.rooms):
		for p in t.periods:
			for adults, kids in sample_parties(t):
				where = (rt, p.code, adults, kids)
				if matrix.party_hidden(t, rt, p, adults, kids, hidden):
					cells[where] = "hidden"
					continue
				try:
					total, slots = matrix.party_total(t, rt, p, adults, kids)
				except (Unsellable, PricingError) as e:
					cells[where] = ("error", getattr(e, "message", None) or str(e))
				else:
					cells[where] = ("total", total, slots)
	return cells


def viewer_sees(t, hidden) -> dict:
	"""Everything a viewer who may not read ``hidden`` is told of ``t``. ``stored``: the report a
	publish stores, as that viewer reads it (None: the terms cannot be published)."""
	live = [(i.level, i.code, i.message, i.ref) for i in validate.validate_terms(t, hidden=hidden)]
	full = validate.validate_terms(t)
	stored = None if any(i.level == "ERROR" for i in full) else \
		validate.visible_issues(t, [i.to_dict(ref=True) for i in full], hidden)
	return {"live": live, "matrix": party_cells(t, hidden), "stored": stored}


def policy(*rules, hotel_rules=()):
	layers = [inherit.PolicyLayer("POL-G", 1, None, None, bands=BANDS, rules=tuple(rules))]
	if hotel_rules:
		layers.append(inherit.PolicyLayer("POL-H", 1, "HOTEL-A", None, bands=(), rules=tuple(hotel_rules)))
	return tuple(layers)


class TestTheReportedLeaks(unittest.TestCase):
	"""The re-review's reproductions, each run once with the hidden rule deferring (INHERIT) and once
	with it pricing: the viewer is told the same both times."""

	def assert_same_whatever_the_op(self, build, ops) -> dict:
		"""The live check and the matrix are the same for every op; so is the stored report for every
		op the terms can be published with (whether they can is the publish's own, full check)."""
		seen = {}
		for op, value in ops:
			t = build(op, value)
			seen[op] = viewer_sees(t, hidden_of(t))
		first, *others = seen.values()
		for op, other in zip(list(seen)[1:], others, strict=True):
			with self.subTest(op=op):
				for part in ("live", "matrix"):
					self.assertEqual(other[part], first[part], part)
		stored = [view["stored"] for view in seen.values() if view["stored"] is not None]
		for report in stored[1:]:
			self.assertEqual(report, stored[0], "stored")
		return first

	def test_a_hidden_rule_that_priced_an_earlier_child_says_nothing_of_a_later_one(self):
		"""(a) G-C1 prices child 1 in band CHD; no rule prices child 2. With G-C1 pricing, the party of
		two CHD children failed on child 2 (NO_CHILD_RULE, said); with G-C1 deferring it failed on
		child 1 (hidden): whether it defers was told. Both parties are hidden now, INHERIT or not, in the
		matrix, the live check and the stored report; who sees cost is told of child 2."""
		def build(op, value):
			return cascaded((), (*OWN_ADULTS, rule("V-INF", CHILD, Op.MULTIPLY, "0", age_band="INF")),
			                layers=policy(rule("G-C1", CHILD, op, value, position=1, age_band="CHD")))

		seen = self.assert_same_whatever_the_op(build, ((Op.INHERIT, None), (Op.MULTIPLY, "0.5")))
		for kids in (("CHD",), ("CHD", "CHD"), ("INF", "CHD"), ("CHD", "INF")):
			self.assertEqual(seen["matrix"][("STD", "P1", 2, kids)], "hidden", kids)
		self.assertEqual(seen["matrix"][("STD", "P1", 2, ("INF", "INF"))][0], "total")
		self.assertNotIn("NO_CHILD_RULE", {i[1] for i in seen["live"]})
		self.assertNotIn("NO_CHILD_RULE", {i["code"] for i in seen["stored"]})
		full = validate.validate_terms(build(Op.MULTIPLY, "0.5"))
		self.assertIn("STD 2A+2C [CHD]: no occupancy rule for child 2 in band CHD (2A+2C)",
		              [i.message for i in full if i.code == "NO_CHILD_RULE"])

	def test_a_hidden_infant_rule_over_a_tie_of_the_versions_rules_says_nothing(self):
		"""(b) G-INF names the infant band, so it outranks the version's band-less child rules V-X and
		V-Y (G-31), which tie with different values. With G-INF deferring the tie priced the infant
		(the matrix said 'rules V-X and V-Y both define child 1 band INF', OCC_AMBIGUOUS named the INF
		slot); with G-INF pricing the party was hidden and OCC_AMBIGUOUS named the CHD slot. Now the
		infant's party is hidden either way and the tie is named where no hidden rule decides it."""
		for variant, tied in (("partial combinations", (rule("V-X", CHILD, Op.MULTIPLY, "0", adults=2),
		                                                  rule("V-Y", CHILD, Op.MULTIPLY, "0.1", children=1))),
		                      ("twins", (rule("V-X", CHILD, Op.MULTIPLY, "0"), rule("V-Y", CHILD, Op.MULTIPLY, "0.1")))):
			with self.subTest(variant):
				def build(op, value, tied=tied):
					own = (*OWN_ADULTS, rule("V-CHD", CHILD, Op.PERCENT_OF, "50", age_band="CHD"), *tied)
					return cascaded((), own, layers=policy(rule("G-INF", CHILD, op, value, age_band="INF")))

				seen = self.assert_same_whatever_the_op(build, ((Op.INHERIT, None), (Op.MULTIPLY, "0")))
				self.assertEqual(seen["matrix"][("STD", "P1", 2, ("INF",))], "hidden")
				ambiguous = [i for i in seen["live"] if i[1] == "OCC_AMBIGUOUS"]
				if variant == "twins":
					self.assertEqual(ambiguous, [])
					self.assertIn("OCC_DUPLICATE", {i[1] for i in seen["live"]})
					continue
				self.assertEqual(len(ambiguous), 1)
				self.assertIn("child 1 (CHD) of DLX 2A+1C", ambiguous[0][2])
				self.assertEqual(ambiguous[0][3]["age_band"], "CHD")
				# a party the tie prices, no hidden rule taking part: said
				self.assertEqual(seen["matrix"][("STD", "P1", 2, ("CHD",))],
				                 ("error", "rules V-X and V-Y both define child 1 band CHD at the same precedence"))

	def test_a_tie_only_a_hidden_rule_may_decide_is_named_without_its_slot(self):
		"""Where every slot of a tie is one a hidden rule may price first (here the infant's, under
		G-INF), whether the tie decides a price depends on that rule's op: the viewer is told of the
		tie, the same way whatever the op, without the slot; who sees cost is told of it only when
		G-INF defers."""
		def build(op, value):
			own = (*OWN_ADULTS, rule("V-CHD", CHILD, Op.PERCENT_OF, "50", age_band="CHD", adults=2, children=1),
			       rule("V-X", CHILD, Op.MULTIPLY, "0", adults=2), rule("V-Y", CHILD, Op.MULTIPLY, "0.1", children=1))
			return cascaded((), own, layers=policy(rule("G-INF", CHILD, op, value, age_band="INF")))

		seen = self.assert_same_whatever_the_op(build, ((Op.INHERIT, None), (Op.MULTIPLY, "0")))
		ambiguous = [i for i in seen["live"] if i[1] == "OCC_AMBIGUOUS"]
		self.assertEqual([(i[0], i[3]) for i in ambiguous],
		                 [("ERROR", {"rule_id": "V-X", "rule_ids": ["V-X", "V-Y"], "adults": 2, "children": 1})])
		self.assertNotIn("INF", ambiguous[0][2])
		full = {op: [i for i in validate.validate_terms(build(op, v)) if i.code == "OCC_AMBIGUOUS"]
		        for op, v in ((Op.INHERIT, None), (Op.MULTIPLY, "0"))}
		self.assertEqual([i.ref["age_band"] for i in full[Op.INHERIT]], ["INF"])
		self.assertEqual(full[Op.MULTIPLY], [])

	def test_a_stored_party_is_shown_where_the_live_check_shows_it(self):
		"""The sweep stores a party once, in the first period it fails. When a hidden rule decided that
		period (G-C1 turned the party's P1 total negative) the stored report had no row for P2, where
		the version's own rule alone makes it negative; with G-C1 pricing within bounds it had. A viewer
		without cost is now given the stored report's sweep as the live check gives it: the P2 row,
		whatever G-C1's op."""
		def build(op, value):
			own = (*OWN_ADULTS, rule("V-INF", CHILD, Op.MULTIPLY, "0", age_band="INF"),
			       rule("V-C1-P2", CHILD, Op.SUBTRACT, "1000", position=1, age_band="CHD", period="P2"))
			return cascaded((), own, layers=policy(rule("G-C1", CHILD, op, value, position=1, age_band="CHD")))

		seen = self.assert_same_whatever_the_op(
			build, ((Op.SUBTRACT, "1000"), (Op.MULTIPLY, "0.5"), (Op.INHERIT, None)))
		negative = {(i["ref"]["room_type"], i["ref"]["period"], i["ref"]["adults"], i["ref"]["children"])
		            for i in seen["stored"] if i["code"] == "NEGATIVE_OCCUPANCY_PRICE"}
		self.assertIn(("STD", "P2", 2, 1), negative)
		t = build(Op.SUBTRACT, "1000")
		self.assertEqual(seen["stored"], [i.to_dict(ref=True) for i in validate.validate_terms(t, hidden=hidden_of(t))])
		stored = [i.to_dict(ref=True) for i in validate.validate_terms(t)]
		self.assertNotIn(("STD", "P2", 2, 1), {(i["ref"]["room_type"], i["ref"]["period"], i["ref"]["adults"],
		                                        i["ref"]["children"]) for i in stored
		                                       if i["code"] == "NEGATIVE_OCCUPANCY_PRICE"})

	def test_a_stored_sweep_at_its_limit_is_given_as_the_live_one(self):
		"""The sweep stops at its limit (200 issues). Parties a hidden rule decides fill it in one op and
		not in another, which changes the later parties that were stored: a stored sweep at its limit is
		given as the live check's sweep, run again (the limit is 3 here)."""
		teen = AgeBand("TEEN", "Teen", 144, 192)

		def build(op, value):
			own = (*OWN_ADULTS, rule("V-INF", CHILD, Op.MULTIPLY, "0", age_band="INF"))
			return cascaded((*BANDS, teen), own,
			                layers=policy(rule("G-C1", CHILD, op, value, position=1, age_band="CHD")))

		shown = {}
		with mock.patch.object(validate, "SWEEP_LIMIT", 3):
			for op, value in ((Op.INHERIT, None), (Op.MULTIPLY, "0.5")):
				t = build(op, value)
				stored = [i.to_dict(ref=True) for i in validate.validate_terms(t, max_warnings=3)]
				self.assertEqual(sum(i["code"] == "NO_CHILD_RULE" for i in stored), 3)
				self.assertIn("CHD", {i["ref"]["age_band"] for i in stored})     # a party G-C1 decides was stored
				# what get_version bounds (S16 re-review 5): a stored sweep at its limit only
				self.assertTrue(validate.reruns_sweep(stored))
				self.assertFalse(validate.reruns_sweep(stored[:2]))
				shown[op] = validate.visible_issues(t, stored, hidden_of(t))
				self.assertEqual(shown[op], [i.to_dict(ref=True) for i in
				                             validate.validate_terms(t, hidden=hidden_of(t), max_warnings=3)])
		self.assertEqual(shown[Op.INHERIT], shown[Op.MULTIPLY])
		self.assertEqual([(i["ref"]["adults"], i["ref"]["children"], i["ref"]["age_band"]) for i in shown[Op.INHERIT]],
		                 [(1, 1, "TEEN"), (1, 2, "TEEN"), (1, 3, "TEEN")])

	def test_a_hidden_rule_without_a_value_is_not_named(self):
		"""OCC_NO_VALUE of a hidden rule says it does not defer (an INHERIT rule needs no value). A policy
		cannot go live so (``policy_issues``); were one inherited, the viewer is not told of it."""
		def build(op, value):
			layers = policy(rule("G-CHD", CHILD, op, value, age_band="CHD"))
			return cascaded((), (*OWN_ADULTS, rule("V-INF", CHILD, Op.MULTIPLY, "0", age_band="INF")), layers=layers)

		self.assertIn("OCC_NO_VALUE", {i.code for i in validate.validate_terms(build(Op.MULTIPLY, None))})
		live = {op: validate.validate_terms(build(op, None), hidden=frozenset({"G-CHD"}))
		        for op in (Op.INHERIT, Op.MULTIPLY)}
		self.assertEqual(live[Op.INHERIT], live[Op.MULTIPLY])
		self.assertNotIn("OCC_NO_VALUE", {i.code for i in live[Op.MULTIPLY]})


# the hidden rules' ops tried on each generated rule set
HIDDEN_OPS = ((Op.INHERIT, None), (Op.MULTIPLY, "0.5"), (Op.SUBTRACT, "300"))
VERSION_OPS = ((Op.INHERIT, None), (Op.MULTIPLY, "1"), (Op.MULTIPLY, "0.5"), (Op.MULTIPLY, "0"),
               (Op.PERCENT_OF, "50"), (Op.SUBTRACT, "150"), (Op.ADD, "10"))
GENERATED = 160


def generated_rule(rng: random.Random, rule_id: str, *, inherited: bool):
	target = rng.choice((ADULT, CHILD, CHILD, COMBINATION))
	kw = {}
	if target != COMBINATION and rng.random() < 0.6:
		kw["position"] = rng.choice((1, 2))
	if target == CHILD and rng.random() < 0.6:
		kw["age_band"] = rng.choice(("INF", "CHD"))
	if target == COMBINATION or rng.random() < 0.3:
		adults, children = rng.choice((None, 1, 2)), rng.choice((None, 0, 1, 2))
		if target == COMBINATION and adults is None and children is None:
			adults = 2
		kw.update(adults=adults, children=children)
	if not inherited and rng.random() < 0.25:
		kw["period"] = rng.choice(("P1", "P2"))    # a pricing policy cannot name a period
	if rng.random() < 0.1:
		kw["is_override"] = True
	op, value = rng.choice(VERSION_OPS) if not inherited else (Op.MULTIPLY, "1")
	return rule(rule_id, target, op, value, **kw)


class TestGeneratedRuleSets(unittest.TestCase):
	"""Rule sets generated from a fixed seed: a version's rules (any op, some naming a period) and one
	or two hidden policy rules (in one policy or in two), PERSON or ROOM basis. For each rule set every
	combination of the hidden rules' ops (INHERIT, a factor, a deduction that can make a total
	negative) is tried: the viewer is told the same live check and the same sample parties every time,
	and the same stored report whenever the terms can be published."""

	def test_the_viewer_is_told_the_same_whatever_the_hidden_ops(self):
		rng = random.Random(61)
		periods = (Period("P1", "June", date(2027, 6, 1), date(2027, 6, 30)),
		           Period("P2", "July", date(2027, 7, 1), date(2027, 7, 31)))
		room_rules = (RoomRule("R-STD-P1", "STD", "P1", Op.ABSOLUTE, D("100")),
		              RoomRule("R-STD-P2", "STD", "P2", Op.ABSOLUTE, D("110")))
		for n in range(GENERATED):
			own = tuple(generated_rule(rng, f"V{i}", inherited=False) for i in range(rng.randint(0, 5)))
			shape = tuple(generated_rule(rng, f"G{i}", inherited=True) for i in range(rng.randint(1, 2)))
			split = rng.random() < 0.3
			room_basis = rng.random() < 0.3
			fill = rng.random() < 0.5
			views = []
			for ops in itertools.product(HIDDEN_OPS, repeat=len(shape)):
				ruled = [replace(r, op=op, value=D(v) if v is not None else None) for r, (op, v) in zip(shape, ops, strict=True)]
				layers = policy(*ruled[:1], hotel_rules=ruled[1:]) if split else policy(*ruled)
				t = cascaded((), own, layers=layers)
				t = replace(t, rooms={"STD": RoomSpec("STD", "Standard", max_adults=3, max_children=2, max_occupants=4)},
				            periods=periods, room_rules=room_rules,
				            basis=PricingBasis.ROOM if room_basis else PricingBasis.PERSON,
				            room_basis_children_fill_included=fill)
				views.append((ops, viewer_sees(t, hidden_of(t))))
			(_, first), *others = views
			for ops, view in others:
				with self.subTest(n=n, own=own, hidden=shape, ops=ops):
					self.assertEqual(view["live"], first["live"])
					self.assertEqual(view["matrix"], first["matrix"])
			stored = [(ops, view["stored"]) for ops, view in views if view["stored"] is not None]
			for ops, report in stored[1:]:
				with self.subTest(n=n, own=own, hidden=shape, ops=ops, part="stored"):
					self.assertEqual(report, stored[0][1])


def refused_with(t, hidden) -> list[str] | None:
	"""What a refused publish names to the viewer (``contracts._refusal``): None when the full check
	passes (a real, audited publish)."""
	errors = [i for i in validate.validate_terms(t) if i.level == "ERROR"]
	if not errors:
		return None
	return [i.message for i in validate.refusal_errors(t, errors, hidden)[:8]]


class TestRefusals(unittest.TestCase):
	"""A refused publish named every error of the full check, before anything was written or audited
	and as often as asked: with an error no op decides every publish fails, and the other errors named
	a hidden rule's slot (S16 re-review 5, medium finding). A viewer without cost is now told what its
	own live check shows: the same whatever the hidden ops, whenever it is refused."""

	def test_the_reproduction(self):
		"""V-X and V-Y tie on the child of 2A+1C under G-INF, which names the infant band; V-BAD names an
		unknown band. The full check names the tie at the infant's slot with G-INF deferring and at the CHD
		child's with it pricing; the viewer is told the CHD slot both times."""
		def build(op, value):
			own = (*OWN_ADULTS, rule("V-X", CHILD, Op.MULTIPLY, "0", adults=2),
			       rule("V-Y", CHILD, Op.MULTIPLY, "0.1", children=1),
			       rule("V-BAD", CHILD, Op.MULTIPLY, "0", age_band="NOPE"))
			return cascaded((), own, layers=policy(rule("G-INF", CHILD, op, value, age_band="INF")))

		told = {op: refused_with(build(op, v), frozenset({"G-INF"})) for op, v in ((Op.INHERIT, None),
		                                                                        (Op.MULTIPLY, "0"))}
		self.assertEqual(told[Op.INHERIT], told[Op.MULTIPLY])
		self.assertEqual(told[Op.INHERIT][0], "rule V-BAD names unknown age band NOPE")
		self.assertIn("child 1 (CHD) of DLX 2A+1C", told[Op.INHERIT][1])
		full = {op: refused_with(build(op, v), frozenset()) for op, v in ((Op.INHERIT, None), (Op.MULTIPLY, "0"))}
		self.assertIn("child 1 (INF)", full[Op.INHERIT][1])      # who sees cost is told the full check
		self.assertIn("child 1 (CHD)", full[Op.MULTIPLY][1])

	def test_generated_rule_sets_every_one_refused(self):
		"""Rule sets generated from a fixed seed, as ``TestGeneratedRuleSets``, most with two tied version
		rules and each with a rule naming an unknown band, so that every op is refused: the viewer is told
		the same each time."""
		rng = random.Random(62)
		ties = ((dict(adults=2), dict(children=1)), (dict(adults=1), dict(children=2)), ({}, {}),
		        (dict(position=1), dict(adults=2)), (dict(age_band="CHD"), dict(age_band="CHD")))
		for n in range(GENERATED):
			own = tuple(generated_rule(rng, f"V{i}", inherited=False) for i in range(rng.randint(0, 4)))
			if rng.random() < 0.6:
				one, two = rng.choice(ties)
				own += (rule("V-X", CHILD, Op.MULTIPLY, "0", **one), rule("V-Y", CHILD, Op.MULTIPLY, "0.1", **two))
			own += (rule("V-BAD", CHILD, Op.MULTIPLY, "0", age_band="NOPE"),)
			shape = tuple(generated_rule(rng, f"G{i}", inherited=True) for i in range(rng.randint(1, 2)))
			told = []
			for ops in itertools.product(HIDDEN_OPS, repeat=len(shape)):
				ruled = [replace(r, op=op, value=D(v) if v is not None else None)
				         for r, (op, v) in zip(shape, ops, strict=True)]
				t = cascaded((), own, layers=policy(ruled[0], hotel_rules=ruled[1:]))
				told.append((ops, refused_with(t, hidden_of(t))))
			(_, first), *others = told
			for ops, message in others:
				with self.subTest(n=n, own=own, hidden=shape, ops=ops):
					self.assertIsNotNone(message)
					self.assertEqual(message, first)


if __name__ == "__main__":
	unittest.main()
