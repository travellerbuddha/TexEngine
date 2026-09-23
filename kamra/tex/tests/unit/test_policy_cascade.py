"""Pricing-policy cascade (G-30, ADR-042).

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
