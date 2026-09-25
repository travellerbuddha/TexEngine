"""Pricing-policy cascade (G-30, ADR-043).

Every live pricing policy that applies to a contract contributes its occupancy rules;
a rule keeps its origin (global < hotel < market < hotel + market < contract version)
and the origin ranks before the rule's qualifiers. Age bands are replaced, not merged:
the version's bands, else those of the most specific policy that defines bands.

Layers used here (STD P1 = 100, PERSON basis):
  GLOBAL        bands INF 0–36 m (infant), CHD 36–144 m · G-INF ×0, G-CHD 50 %, G-A3 ×0.70
  HOTEL-A       no bands · H-A3 ×0.80, H-CHB 30 %
  DE            bands INF 0–36, CHA 36–84, CHB 84–144 · M-CHA 25 %, M-CHB 40 %
  HOTEL-A + DE  no bands · HM-CHB inherit, HM-1A0C combination 1+0 ×0.90
"""

import unittest
from dataclasses import replace
from datetime import date
from decimal import Decimal

from kamra.tex.pricing import ages, inherit, occupancy, rooms, validate
from kamra.tex.pricing.enums import Level, OccTarget, Op
from kamra.tex.pricing.explain import Explanation
from kamra.tex.pricing.model import AgeBand, ChildSpec, OccupancyRule, PricingError
from kamra.tex.tests.unit import fixtures as fx

D = Decimal
CHILD, ADULT, COMBINATION = OccTarget.CHILD, OccTarget.ADULT, OccTarget.COMBINATION


def rule(rule_id, target, op, value=None, **kw):
	return OccupancyRule(rule_id, target, op, D(value) if value is not None else None, **kw)


GLOBAL = inherit.PolicyLayer(
	"POL-G", 1, None, None,
	bands=(AgeBand("INF", "Infant", 0, 36, is_infant=True), AgeBand("CHD", "Child", 36, 144)),
	rules=(rule("G-INF", CHILD, Op.MULTIPLY, "0", age_band="INF"),
	       rule("G-CHD", CHILD, Op.PERCENT_OF, "50", age_band="CHD"),
	       rule("G-A3", ADULT, Op.MULTIPLY, "0.70", position=3)))
HOTEL = inherit.PolicyLayer(
	"POL-H", 1, "HOTEL-A", None, bands=(),
	rules=(rule("H-A3", ADULT, Op.MULTIPLY, "0.80", position=3),
	       rule("H-CHB", CHILD, Op.PERCENT_OF, "30", age_band="CHB")))
MARKET = inherit.PolicyLayer(
	"POL-M", 1, None, "DE",
	bands=(AgeBand("INF", "Infant", 0, 36, is_infant=True), AgeBand("CHA", "Child A", 36, 84),
	       AgeBand("CHB", "Child B", 84, 144)),
	rules=(rule("M-CHA", CHILD, Op.PERCENT_OF, "25", age_band="CHA"),
	       rule("M-CHB", CHILD, Op.PERCENT_OF, "40", age_band="CHB")))
HOTEL_MARKET = inherit.PolicyLayer(
	"POL-HM", 2, "HOTEL-A", "DE", bands=(),
	rules=(rule("HM-CHB", CHILD, Op.INHERIT, age_band="CHB"),
	       rule("HM-1A0C", COMBINATION, Op.MULTIPLY, "0.90", adults=1, children=0)))
LAYERS = (GLOBAL, HOTEL, MARKET, HOTEL_MARKET)


def cascaded(version_bands=(), version_rules=(), layers=LAYERS):
	bands, rules = inherit.cascade(version_bands, version_rules, layers)
	return fx.terms(age_bands=bands, occupancy_rules=rules)


def occ(t, adults, *kid_ages, room="STD", explain=None):
	period = next(p for p in t.periods if p.code == "P1")
	party = ages.classify_party(t, adults, tuple(ChildSpec(age=a) for a in kid_ages), date(2027, 6, 2),
	                            date(2027, 1, 1))
	return occupancy.price_occupancy(t, t.rooms[room], period, rooms.room_unit(t, room, period), party,
	                                 explain=explain)


class TestLayers(unittest.TestCase):
	def test_scope_weight_level_and_label(self):
		self.assertEqual([x.weight for x in LAYERS], [0, 1, 2, 3])
		self.assertEqual([inherit.level_for(w) for w in range(4)],
		                 [Level.GLOBAL, Level.HOTEL, Level.MARKET, Level.MARKET])
		self.assertEqual([inherit.scope_label(w) for w in range(4)], ["global", "hotel", "market", "hotel+market"])

	def test_bands_come_from_the_most_specific_policy_defining_them(self):
		bands, _rules = inherit.cascade((), (), LAYERS)
		self.assertEqual(bands, MARKET.bands)
		bands, _rules = inherit.cascade((), (), (GLOBAL, HOTEL))
		self.assertEqual(bands, GLOBAL.bands)

	def test_version_bands_replace_every_policy_band_set(self):
		bands, _rules = inherit.cascade(fx.bands(), (), LAYERS)
		self.assertEqual(bands, fx.bands())

	def test_rules_keep_their_origin_most_specific_first(self):
		version_rule = rule("V-CHB", CHILD, Op.PERCENT_OF, "35", age_band="CHB")
		_bands, rules = inherit.cascade((), (version_rule,), (GLOBAL, MARKET, HOTEL_MARKET, HOTEL))
		self.assertEqual([r.rule_id for r in rules],
		                 ["V-CHB", "HM-CHB", "HM-1A0C", "M-CHA", "M-CHB", "H-A3", "H-CHB", "G-INF", "G-CHD", "G-A3"])
		origin = {r.rule_id: (r.base_level, r.scope_weight, r.source) for r in rules}
		self.assertEqual(origin["V-CHB"], (Level.VERSION, 0, "version"))
		self.assertEqual(origin["HM-CHB"], (Level.MARKET, 3, "policy:POL-HM/r2/hotel+market"))
		self.assertEqual(origin["M-CHB"], (Level.MARKET, 2, "policy:POL-M/r1/market"))
		self.assertEqual(origin["H-CHB"], (Level.HOTEL, 1, "policy:POL-H/r1/hotel"))
		self.assertEqual(origin["G-INF"], (Level.GLOBAL, 0, "policy:POL-G/r1/global"))

	def test_two_policies_of_one_scope_are_refused(self):
		twin = inherit.PolicyLayer("POL-M2", 1, None, "DE", bands=(), rules=())
		with self.assertRaises(PricingError) as cm:
			inherit.cascade((), (), (*LAYERS, twin))
		self.assertIn("POL-M", str(cm.exception))
		self.assertIn("POL-M2", str(cm.exception))


class TestCascadedPrices(unittest.TestCase):
	def setUp(self):
		self.t = cascaded()

	def test_prices(self):
		self.assertEqual(occ(self.t, 3).total, D("280"))           # A3: hotel ×0.80 beats global ×0.70
		self.assertEqual(occ(self.t, 2, 8).total, D("240"))        # CHB: hotel+market inherits → market 40 %
		self.assertEqual(occ(self.t, 2, 4).total, D("225"))        # CHA: market 25 %
		self.assertEqual(occ(self.t, 2, 1).total, D("200"))        # INF: global ×0
		self.assertEqual(occ(self.t, 1).total, D("90.00"))         # 1+0: hotel+market ×0.90

	def test_explanation_names_the_winning_scope_and_what_it_overrode(self):
		ex = Explanation()
		occ(self.t, 2, 8, explain=ex)
		step = next(s for s in ex.steps if s.code == "CHILD_SLOT")
		self.assertEqual(step.rule.rule_id, "M-CHB")
		self.assertEqual(step.rule.level, Level.MARKET)
		self.assertEqual(step.rule.source, "policy:POL-M/r1/market")
		self.assertTrue({"HM-CHB", "H-CHB"} <= {o.rule_id for o in step.overridden})

	def test_layer_order_does_not_matter(self):
		shuffled = cascaded(layers=(HOTEL_MARKET, GLOBAL, MARKET, HOTEL))
		for party in ((3,), (2, 8), (2, 4), (2, 1), (1,)):
			self.assertEqual(occ(shuffled, *party).total, occ(self.t, *party).total)

	def test_an_inherited_rule_for_a_band_the_contract_lacks_only_warns(self):
		issues = validate.validate_terms(self.t)
		self.assertEqual([i for i in issues if i.level == "ERROR"], [])
		unused = [i for i in issues if i.code == "OCC_INHERITED_BAND_UNUSED"]
		self.assertEqual(len(unused), 1)
		self.assertIn("G-CHD", unused[0].message)


class TestPrecedenceReport(unittest.TestCase):
	"""devtools.precedence_report: which frozen versions price differently under v2."""

	def test_lists_the_cells_a_legacy_payload_prices_differently(self):
		from kamra.tex.devtools import precedence_report

		legacy = replace(fx.terms(), occupancy_precedence=occupancy.LEGACY)
		diff = precedence_report.differences(legacy)
		self.assertIn({"room": "STD", "period": "P1", "party": "2A+[INF,CHB]", "sold_as": "275.00", "now": "250.00"},
		              diff)
		self.assertTrue(all("INF" in d["party"] for d in diff))    # only infants in 2A+2C change
		self.assertEqual(precedence_report.differences(fx.terms(occupancy_precedence=occupancy.CASCADE)), [])

	def test_compares_a_frozen_version_with_its_rebuild(self):
		from kamra.tex.devtools import precedence_report

		frozen = replace(fx.terms(), occupancy_precedence=occupancy.LEGACY)
		rebuilt = cascaded(fx.bands(), fx.occ_rules())               # + every policy, v2 ranking
		changed = {(d["room"], d["period"], d["party"]) for d in precedence_report.differences(frozen, rebuilt)}
		self.assertIn(("STD", "P1", "1A"), changed)                   # hotel+market 1+0 ×0.90 now applies
		self.assertIn(("STD", "P1", "2A+[INF,CHB]"), changed)

	def test_a_version_frozen_without_age_bands_shows_its_child_cells(self):
		# the G-30 cohort: no bands anywhere, so every child was sold as an adult; a republish
		# takes a policy's bands. The grid must price children of either side's bands.
		from kamra.tex.devtools import precedence_report

		frozen = replace(fx.terms(age_bands=(), occupancy_rules=tuple(r for r in fx.occ_rules() if not r.age_band)),
		                 occupancy_precedence=occupancy.LEGACY)
		diff = precedence_report.differences(frozen, fx.terms())
		self.assertIn({"room": "STD", "period": "P1", "party": "2A+[CHB]", "sold_as": "270.00", "now": "250.00"},
		              diff)                                           # sold as a third adult (×0.70)
		self.assertIn({"room": "STD", "period": "P1", "party": "2A+[INF]", "sold_as": "270.00", "now": "200.00"},
		              diff)

	def test_a_rebuild_the_publish_check_refuses_is_reported(self):
		from kamra.tex.devtools import precedence_report

		amb = inherit.PolicyLayer("POL-G", 1, None, None, rules=(
			rule("G-2A", CHILD, Op.PERCENT_OF, "60", position=1, adults=2),
			rule("G-2C", CHILD, Op.PERCENT_OF, "40", position=1, children=2)))
		rebuilt = cascaded(fx.bands(), (), layers=(amb, MARKET))
		errors = precedence_report.republish_errors(rebuilt)
		self.assertTrue(errors)
		self.assertTrue(all(e.startswith("OCC_AMBIGUOUS") for e in errors), errors)
		self.assertEqual(precedence_report.republish_errors(fx.terms()), [])


def errors(t):
	return [i for i in validate.validate_terms(t) if i.level == "ERROR"]


def warnings(t):
	return [i.code for i in validate.validate_terms(t) if i.level == "WARNING"]


class TestInheritedRuleChecks(unittest.TestCase):
	"""A pricing policy reaches every contract in its scope: its rules block publishing only
	where they would decide a price; the policy itself is checked on its own at activation."""

	TIE = (rule("G-2A", CHILD, Op.PERCENT_OF, "60", position=1, adults=2),
	       rule("G-2C", CHILD, Op.PERCENT_OF, "40", position=1, children=2))

	def test_a_policy_tie_the_version_always_outranks_is_not_an_error(self):
		# child 1 of 2A+2C: the version prices every band itself, and a version rule beats any policy rule
		t = cascaded(fx.bands(), fx.occ_rules(), layers=(inherit.PolicyLayer("POL-G", 1, None, None, rules=self.TIE),))
		self.assertEqual(errors(t), [])
		self.assertEqual(occ(t, 2, 8, 5).total, D("275.00"))

	def test_a_policy_tie_that_prices_a_slot_is_an_error(self):
		# the version has no Child A rule: the policy tie decides child 1 (CHA) of 2A+2C
		t = cascaded(fx.bands(), tuple(r for r in fx.occ_rules() if r.rule_id != "O-CHA"),
		             layers=(inherit.PolicyLayer("POL-G", 1, None, None, rules=self.TIE),))
		found = errors(t)
		self.assertEqual([i.code for i in found], ["OCC_AMBIGUOUS"])
		self.assertIn("CHA", found[0].message)

	def test_policy_rows_the_contract_never_reaches_do_not_block_publishing(self):
		g = inherit.PolicyLayer("POL-G", 1, None, None, rules=(
			rule("G-A-INF", ADULT, Op.MULTIPLY, "0.5", age_band="INF"),     # an adult rule never has a band
			rule("G-X1", CHILD, Op.PERCENT_OF, "30", age_band="CHB"),
			rule("G-X2", CHILD, Op.PERCENT_OF, "35", age_band="CHB")))    # the version's own CHB rule wins
		t = cascaded(fx.bands(), fx.occ_rules(), layers=(g,))
		self.assertEqual(errors(t), [])
		self.assertIn("OCC_INHERITED_ADULT_BAND_UNUSED", warnings(t))
		# where the contract has no CHB rule of its own, the twin rules decide the price: an error
		t = cascaded(fx.bands(), tuple(r for r in fx.occ_rules() if r.rule_id != "O-CHB"), layers=(g,))
		found = errors(t)
		self.assertEqual([i.code for i in found], ["OCC_AMBIGUOUS"])
		self.assertIn("G-X1", found[0].message)
		self.assertIn("G-X2", found[0].message)

	def test_a_policy_combination_rule_without_a_combination_is_an_error(self):
		# it would reprice every combination of every contract in scope (guard)
		g = inherit.PolicyLayer("POL-G", 1, None, None, rules=(rule("G-COMBO", COMBINATION, Op.MULTIPLY, "0.9"),))
		self.assertIn("OCC_COMBINATION_QUALIFIER", [i.code for i in errors(cascaded(fx.bands(), fx.occ_rules(),
		                                                                           layers=(g,)))])

	def test_a_policy_is_checked_on_its_own(self):
		issues = validate.policy_issues((), (
			rule("A-INF", ADULT, Op.MULTIPLY, "0.5", age_band="INF"),
			rule("C-ANY", COMBINATION, Op.MULTIPLY, "0.9"),
			rule("X1", CHILD, Op.PERCENT_OF, "30", age_band="CHB"),
			rule("X2", CHILD, Op.PERCENT_OF, "35", age_band="CHB"),
			*self.TIE))
		self.assertEqual(sorted(i.code for i in issues if i.level == "ERROR"),
		                 ["OCC_ADULT_BAND", "OCC_AMBIGUOUS", "OCC_COMBINATION_QUALIFIER", "OCC_DUPLICATE"])
		tie = next(i for i in issues if i.code == "OCC_AMBIGUOUS")
		self.assertIn("child 1", tie.message)
		self.assertIn("2A+2C", tie.message)
		# an exact 2+2 rule settles the tie for every band; partial rules that never meet are fine
		settled = (*self.TIE, rule("G-2A2C", CHILD, Op.PERCENT_OF, "50", position=1, adults=2, children=2))
		self.assertEqual(validate.policy_issues((), settled), [])
		self.assertEqual(validate.policy_issues((), (rule("G-1A", CHILD, Op.PERCENT_OF, "60", position=1, adults=1),
		                                             rule("G-2A", CHILD, Op.PERCENT_OF, "40", position=1, adults=2))),
		                 [])


class TestPolicyOverride(unittest.TestCase):
	"""A pricing-policy "specific override" no longer beats a contract's own rule (ADR-043):
	publishing says so where that changes a price."""

	OVR = inherit.PolicyLayer("POL-H", 1, "HOTEL-A", None, rules=(
		rule("H-INF-OVR", CHILD, Op.FIXED, "15", age_band="INF", is_override=True),))

	def test_an_outranked_policy_override_warns(self):
		t = cascaded(fx.bands(), fx.occ_rules(), layers=(self.OVR,))
		self.assertEqual(occ(t, 2, 1).total, D("200"))              # the version's INF ×0 wins
		self.assertEqual(occ(replace(t, occupancy_precedence=occupancy.LEGACY), 2, 1).total, D("215"))
		found = [i for i in validate.validate_terms(t) if i.code == "OCC_POLICY_OVERRIDE_OUTRANKED"]
		self.assertEqual(len(found), 1)
		self.assertEqual(found[0].level, "WARNING")
		self.assertIn("H-INF-OVR", found[0].message)
		self.assertIn("O-INF", found[0].message)

	def test_a_policy_override_that_still_applies_does_not_warn(self):
		t = cascaded(fx.bands(), tuple(r for r in fx.occ_rules() if r.rule_id != "O-INF"), layers=(self.OVR,))
		self.assertEqual(occ(t, 2, 1).total, D("215"))
		self.assertNotIn("OCC_POLICY_OVERRIDE_OUTRANKED", warnings(t))


class TestHiddenPolicyRules(unittest.TestCase):
	"""A viewer who may not read a pricing policy's formulas (``hidden``, S16 review) gets no
	issue whose presence depends on one: the sweep's issues for a party a hidden rule takes part in
	(a probe "2A+1C SUBTRACT X" is a threshold oracle) and OCC_POLICY_OVERRIDE_OUTRANKED (it shows
	only while the version's rule differs from the override: an equality oracle)."""

	OVR = TestPolicyOverride.OVR

	def test_an_outranked_override_is_left_out(self):
		t = cascaded(fx.bands(), fx.occ_rules(), layers=(self.OVR,))
		self.assertIn("OCC_POLICY_OVERRIDE_OUTRANKED", warnings(t))
		hidden = frozenset(r.rule_id for r in t.occupancy_rules if r.source != "version")
		self.assertNotIn("OCC_POLICY_OVERRIDE_OUTRANKED",
		                 [i.code for i in validate.validate_terms(t, hidden=hidden)])

	def test_the_sweep_says_nothing_about_a_party_a_hidden_rule_prices(self):
		probe = rule("V-PROBE", COMBINATION, Op.SUBTRACT, "251", adults=2, children=1)
		t = cascaded((), (probe,), layers=(GLOBAL,))
		hidden = frozenset(r.rule_id for r in t.occupancy_rules if r.source != "version")
		negative = [i for i in validate.validate_terms(t) if i.code == "NEGATIVE_OCCUPANCY_PRICE"]
		self.assertTrue(any(i.ref["adults"] == 2 and i.ref["children"] == 1 for i in negative))
		self.assertNotIn("NEGATIVE_OCCUPANCY_PRICE", [i.code for i in validate.validate_terms(t, hidden=hidden)])
		# a party no hidden rule prices is still reported: the version's own rules only
		own = rule("V-CHD", CHILD, Op.PERCENT_OF, "50", age_band="CHD")
		t = cascaded((), (probe, own, rule("V-A1", ADULT, Op.MULTIPLY, "1", position=1),
		                  rule("V-A2", ADULT, Op.MULTIPLY, "1", position=2)), layers=(GLOBAL,))
		hidden = frozenset(r.rule_id for r in t.occupancy_rules if r.source != "version")
		kept = [i for i in validate.validate_terms(t, hidden=hidden) if i.code == "NEGATIVE_OCCUPANCY_PRICE"]
		self.assertTrue(any(i.ref["adults"] == 2 and i.ref["children"] == 1 and i.ref["age_band"] == "CHD"
		                    for i in kept))


	# the usual adult ladder of a global policy, an infant rule and no rule for the CHD band
	LADDER = inherit.PolicyLayer(
		"POL-G", 1, None, None,
		bands=(AgeBand("INF", "Infant", 0, 36, is_infant=True), AgeBand("CHD", "Child", 36, 144)),
		rules=(rule("G-A1", ADULT, Op.MULTIPLY, "1", position=1), rule("G-A2", ADULT, Op.MULTIPLY, "1", position=2),
		       rule("G-A3", ADULT, Op.MULTIPLY, "0.70", position=3),
		       rule("G-INF", CHILD, Op.MULTIPLY, "0", age_band="INF")))

	def test_a_missing_child_rule_is_said_whoever_priced_the_adults(self):
		"""NO_CHILD_RULE says that no rule prices a band: whether it shows depends on which rules
		exist, not on any value, so it is said also when a hidden rule priced an adult before the
		child (re-review of S16, finding 1). A negative total a hidden rule takes part in still goes."""
		probe = rule("V-PROBE", COMBINATION, Op.SUBTRACT, "251", adults=2, children=1)
		t = cascaded((), (probe,), layers=(self.LADDER,))
		hidden = frozenset(r.rule_id for r in t.occupancy_rules if r.source != "version")
		self.assertEqual(hidden, {"G-A1", "G-A2", "G-A3", "G-INF"})
		full = validate.validate_terms(t)
		missing = [i for i in full if i.code == "NO_CHILD_RULE"]
		self.assertTrue(missing)
		self.assertTrue(all(i.ref["age_band"] == "CHD" for i in missing))
		# 2 × 100 + 0 (INF) − 251: negative
		self.assertIn(("NEGATIVE_OCCUPANCY_PRICE", "INF"),
		              {(i.code, i.ref.get("age_band")) for i in full if i.ref})
		seen = validate.validate_terms(t, hidden=hidden)
		self.assertEqual([(i.message, i.ref) for i in seen if i.code == "NO_CHILD_RULE"],
		                 [(i.message, i.ref) for i in missing])
		self.assertNotIn("NEGATIVE_OCCUPANCY_PRICE", [i.code for i in seen])

	def test_a_missing_child_rule_where_a_hidden_rule_defers_is_left_out(self):
		"""A hidden rule that defers (INHERIT) for a band is why no rule prices it: its op is hidden
		too, so the missing rule is not said for that band."""
		defers = inherit.PolicyLayer("POL-G", 1, None, None, bands=self.LADDER.bands,
		                             rules=(*self.LADDER.rules, rule("G-CHD", CHILD, Op.INHERIT, age_band="CHD")))
		t = cascaded((), (), layers=(defers,))
		hidden = frozenset(r.rule_id for r in t.occupancy_rules if r.source != "version")
		self.assertIn("NO_CHILD_RULE", [i.code for i in validate.validate_terms(t)])
		self.assertNotIn("NO_CHILD_RULE", [i.code for i in validate.validate_terms(t, hidden=hidden)])
		# a rule of the version's own for the band prices it: nothing to hide or say
		own = cascaded((), (rule("V-CHD", CHILD, Op.PERCENT_OF, "50", age_band="CHD"),), layers=(defers,))
		self.assertNotIn("NO_CHILD_RULE", [i.code for i in validate.validate_terms(own)])

	def test_a_stored_report_is_filtered_as_the_live_check_is(self):
		"""The report frozen at publish was made with nothing hidden: ``visible_issues`` leaves out of
		it what ``validate_terms(hidden=…)`` leaves out (re-review of S16, low finding)."""
		probe = rule("V-PROBE", COMBINATION, Op.SUBTRACT, "251", adults=2, children=1)
		t = cascaded(fx.bands(), (*fx.occ_rules(), probe), layers=(TestPolicyOverride.OVR, self.LADDER))
		hidden = frozenset(r.rule_id for r in t.occupancy_rules if r.source != "version")
		stored = [i.to_dict() for i in validate.validate_terms(t)]
		self.assertIn("OCC_POLICY_OVERRIDE_OUTRANKED", {i["code"] for i in stored})
		shown = validate.visible_issues(t, stored, hidden)
		self.assertEqual(shown, [i.to_dict() for i in validate.validate_terms(t, hidden=hidden)])
		self.assertNotIn("OCC_POLICY_OVERRIDE_OUTRANKED", {i["code"] for i in shown})
		self.assertEqual(validate.visible_issues(t, stored, frozenset()), stored)
		# a party priced with the version's own rules only is still said (fx.occ_rules name adults 1-3)
		self.assertIn("NEGATIVE_OCCUPANCY_PRICE", {i["code"] for i in shown})
		# a row that no longer says which party it is about, or that is not a dict, is left out
		bare = [{"level": "WARNING", "code": "NEGATIVE_OCCUPANCY_PRICE", "message": "x"}, "junk"]
		self.assertEqual(validate.visible_issues(t, bare, hidden), [])
		self.assertEqual(validate.visible_issues(t, bare[:1], frozenset()), bare[:1])
