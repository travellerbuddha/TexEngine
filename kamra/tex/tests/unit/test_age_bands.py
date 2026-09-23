"""G-52 (R-08): child age band hygiene, on the integer-month scale the runtime uses.

A band's ages are entered in years and priced in whole months ("2.99" and "3" both end
at 36 months; "2.95" ends at 35). Bands that leave a month uncovered between them make a
child of that age unsellable, so publishing refuses them and names the months; bands that
overlap are refused too. Bands starting above 0 months (a minimum child age) only warn.

Which band set applies (ADR-043): the version's bands, else the band set of the most
specific pricing policy that defines one - hotel + market > market > hotel > global."""

from __future__ import annotations

import unittest
from datetime import date

from kamra.tex.pricing import ages, inherit, validate
from kamra.tex.pricing.model import AgeBand, ChildSpec, PricingError, Unsellable
from kamra.tex.tests.unit import fixtures as fx


def band(code, from_years, to_years, infant=False) -> AgeBand:
	"""A band as a TEX Child Age Band row turns into one (``contracts.age_bands_of``)."""
	return AgeBand(code, code, ages.years_to_months(from_years), ages.years_to_months(to_years), is_infant=infant)


INF_295 = band("INF", 0, "2.95", infant=True)          # ends at 35 months
CHA = band("CHA", 3, "6.99")                           # 36–84
CHB = band("CHB", 7, "11.99")                          # 84–144


def terms(bands):
	"""The reference contract with these bands (and no occupancy rules naming others)."""
	return fx.terms(age_bands=tuple(bands), occupancy_rules=())


def errors(t):
	return [i for i in validate.validate_terms(t, sweep_combinations=False) if i.level == "ERROR"]


class TestBandGapsAndOverlaps(unittest.TestCase):
	def test_a_band_ending_at_2_95_leaves_35_months_unsellable(self):
		self.assertEqual((INF_295.to_months, CHA.from_months), (35, 36))
		# what the runtime does with that child: no band, not sellable
		with self.assertRaises(Unsellable) as cm:
			ages.classify_party(fx.terms(age_bands=(INF_295, CHA, CHB)), 2, (ChildSpec(age_months=35),),
			                    date(2027, 6, 2), date(2027, 1, 15))
		self.assertEqual(cm.exception.code, "NO_AGE_BAND")
		# … so the band set is refused, naming the month
		with self.assertRaises(PricingError) as e:
			ages.validate_bands((INF_295, CHA, CHB))
		msg = str(e.exception)
		self.assertIn("INF and CHA", msg)
		self.assertIn("gap at 35 months (2y11m)", msg)

	def test_publishing_refuses_the_gap_and_names_the_months(self):
		errs = errors(terms((INF_295, CHA, CHB)))
		self.assertEqual([i.code for i in errs], ["AGE_BANDS"])
		self.assertIn("35 months (2y11m)", errs[0].message)

	def test_a_wider_gap_names_every_month_of_it(self):
		msg = ages.band_problems((band("INF", 0, "1.99", infant=True), CHA))[0]
		self.assertIn("gap at 24–35 months (2y–2y11m)", msg)

	def test_every_gap_and_overlap_is_reported(self):
		problems = ages.band_problems((band("INF", 0, "2.5", infant=True), band("CHA", 3, "7.5"), CHB,
		                               band("TEEN", 12, 16)))
		self.assertEqual(len(problems), 2, problems)
		self.assertIn("gap at 30–35 months", problems[0])
		self.assertIn("overlap at 84–89 months (7y–7y5m)", problems[1])
		self.assertEqual(len(errors(terms((band("INF", 0, "2.5", infant=True), band("CHA", 3, "7.5"), CHB)))), 2)

	def test_an_overlap_names_the_months_in_both(self):
		with self.assertRaisesRegex(PricingError, r"overlap at 36–39 months \(3y–3y3m\)"):
			ages.validate_bands((AgeBand("A", "A", 0, 40), AgeBand("B", "B", 36, 84)))

	def test_bands_that_meet_pass_whatever_way_the_end_is_written(self):
		for inf_end in ("2.99", "3", 3):
			ages.validate_bands((band("INF", 0, inf_end, infant=True), CHA, CHB))
		ages.validate_bands(fx.bands())
		self.assertEqual(errors(fx.terms()), [])

	def test_a_minimum_child_age_warns_but_publishes(self):
		# no band below 3 years: younger children cannot be booked (e.g. a hotel that takes children from 3)
		t = terms((CHA, CHB))
		ages.validate_bands(t.age_bands)
		issues = validate.validate_terms(t, sweep_combinations=False)
		self.assertEqual([i.code for i in issues if i.level == "ERROR"], [])
		warn = next(i for i in issues if i.code == "AGE_BANDS_MIN_AGE")
		self.assertIn("0–35 months (0y–2y11m)", warn.message)


LAYER_BANDS = {
	"global": (band("INF", 0, "1.99", infant=True), band("CHD", 2, "11.99")),
	"hotel": (band("INF", 0, "2.99", infant=True), band("CHD", 3, "12.99")),
	"market": (band("INF", 0, "2.99", infant=True), band("CHA", 3, "6.99"), band("CHB", 7, "11.99")),
	"hotel_market": (band("BABY", 0, "1.99", infant=True), band("KID", 2, "13.99")),
}
GLOBAL = inherit.PolicyLayer("POL-G", 1, None, None, bands=LAYER_BANDS["global"])
HOTEL = inherit.PolicyLayer("POL-H", 1, "HOTEL-A", None, bands=LAYER_BANDS["hotel"])
MARKET = inherit.PolicyLayer("POL-M", 1, None, "DE", bands=LAYER_BANDS["market"])
HOTEL_MARKET = inherit.PolicyLayer("POL-HM", 1, "HOTEL-A", "DE", bands=LAYER_BANDS["hotel_market"])


def bands_for(layers, version_bands=()):
	return inherit.cascade(version_bands, (), layers)[0]


def band_of(bands, months) -> str | None:
	b = ages.band_for(months, tuple(bands))
	return b.code if b else None


class TestWhichBandSetApplies(unittest.TestCase):
	"""The caller (``contracts._policy_layers``) passes the live policies of the contract's
	hotel and market; the band set of the most specific one that defines bands wins."""

	def test_a_contract_of_the_hotel_in_its_policy_market(self):
		self.assertEqual(bands_for((GLOBAL, HOTEL, MARKET, HOTEL_MARKET)), LAYER_BANDS["hotel_market"])
		self.assertEqual(bands_for((GLOBAL, HOTEL, MARKET)), LAYER_BANDS["market"])   # market beats hotel

	def test_a_contract_of_the_hotel_in_another_market(self):
		self.assertEqual(bands_for((GLOBAL, HOTEL)), LAYER_BANDS["hotel"])

	def test_a_contract_of_another_hotel_in_the_market(self):
		self.assertEqual(bands_for((GLOBAL, MARKET)), LAYER_BANDS["market"])

	def test_any_other_contract_takes_the_global_set(self):
		self.assertEqual(bands_for((GLOBAL,)), LAYER_BANDS["global"])
		self.assertEqual(bands_for(()), ())

	def test_a_policy_without_bands_passes_to_the_next_one(self):
		bandless = inherit.PolicyLayer("POL-HM", 1, "HOTEL-A", "DE")
		self.assertEqual(bands_for((GLOBAL, HOTEL, MARKET, bandless)), LAYER_BANDS["market"])

	def test_the_version_replaces_every_policy_set(self):
		self.assertEqual(bands_for((GLOBAL, HOTEL, MARKET, HOTEL_MARKET), fx.bands()), fx.bands())

	def test_the_same_child_falls_in_the_band_of_the_set_that_applies(self):
		months = 30                               # 2y6m
		self.assertEqual(band_of(LAYER_BANDS["global"], months), "CHD")
		self.assertEqual(band_of(LAYER_BANDS["hotel"], months), "INF")
		self.assertEqual(band_of(LAYER_BANDS["market"], months), "INF")
		self.assertEqual(band_of(LAYER_BANDS["hotel_market"], months), "KID")
		self.assertEqual(band_of(LAYER_BANDS["hotel"], 155), "CHD")          # 12y11m
		self.assertIsNone(band_of(LAYER_BANDS["hotel"], 156))                # "12.99": 13 is above the set

	def test_a_gap_in_an_inherited_set_blocks_publishing(self):
		gappy = inherit.PolicyLayer("POL-M", 2, None, "DE", bands=(INF_295, CHA, CHB))
		t = terms(bands_for((GLOBAL, HOTEL, gappy)))
		self.assertIn("35 months (2y11m)", errors(t)[0].message)
		# a version with bands of its own replaces the inherited set: nothing to refuse
		t = terms(bands_for((GLOBAL, HOTEL, gappy), fx.bands()))
		self.assertEqual(errors(t), [])


class TestChildAgeFromDateOfBirth(unittest.TestCase):
	"""A date of birth is priced in completed months at the reference date (arrival)."""

	def test_months_at_arrival_decide_the_band(self):
		t = fx.terms(age_bands=LAYER_BANDS["market"])
		arrival = date(2027, 6, 2)
		two_years_eleven = ChildSpec(dob=date(2024, 6, 3))          # 35 months on arrival
		third_birthday = ChildSpec(dob=date(2024, 6, 2))             # 36 months on arrival
		p = ages.classify_party(t, 2, (two_years_eleven, third_birthday), arrival, date(2027, 1, 15))
		self.assertEqual(sorted((c.months, c.band.code) for c in p.children), [(35, "INF"), (36, "CHA")])
		# a declared age of 2 is 24 months: the same band, the child's real age is more precise
		self.assertEqual(ages.child_months(ChildSpec(age=2), arrival), 24)

	def test_the_age_limit_of_a_date_of_birth(self):
		arrival = date(2027, 6, 2)
		self.assertEqual(ages.check_child_dob(date(2009, 6, 3), arrival, today=date(2027, 1, 15)), 215)
		with self.assertRaisesRegex(PricingError, "18 or older"):
			ages.check_child_dob(date(2009, 6, 2), arrival, today=date(2027, 1, 15))
		with self.assertRaisesRegex(PricingError, "future"):
			ages.check_child_dob(date(2027, 1, 16), arrival, today=date(2027, 1, 15))
		self.assertEqual(ages.check_child_dob(date(2027, 1, 15), arrival, today=date(2027, 1, 15)), 4)


if __name__ == "__main__":
	unittest.main()
