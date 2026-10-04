import unittest
from datetime import date
from decimal import Decimal

from kamra.tex.money import D, Money, from_db, minor_units, quantize, to_str
from kamra.tex.pricing import ages
from kamra.tex.pricing.enums import AgeBasis, ChildOrdering
from kamra.tex.pricing.model import AgeBand, ChildSpec, PricingError, Unsellable
from kamra.tex.tests.unit import fixtures as fx


class TestMoney(unittest.TestCase):
	def test_float_input_goes_through_repr_not_binary(self):
		self.assertEqual(D(0.1), Decimal("0.1"))
		self.assertEqual(D(0.1) + D(0.2), Decimal("0.3"))

	def test_half_up_rounding(self):
		self.assertEqual(quantize(D("2.345"), "EUR"), Decimal("2.35"))
		self.assertEqual(quantize(D("2.344999"), "EUR"), Decimal("2.34"))
		self.assertEqual(quantize(D("-2.345"), "EUR"), Decimal("-2.35"))

	def test_minor_units(self):
		self.assertEqual(minor_units("JPY"), 0)
		self.assertEqual(minor_units("KWD"), 3)
		self.assertEqual(minor_units("try"), 2)
		self.assertEqual(quantize(D("1234.5"), "JPY"), Decimal("1235"))

	def test_clp_and_isk_are_whole_units(self):
		"""The owner's answer (2026-10-04, option a): ISO 4217 gives the Chilean peso and the Icelandic króna no minor
		unit; the server kept them in two decimals (HANDOFF §2 item 7, §6K6 "Not done")."""
		from kamra.tex.money import split_evenly

		for ccy in ("CLP", "isk"):
			with self.subTest(ccy=ccy):
				self.assertEqual(minor_units(ccy), 0)
				self.assertEqual(to_str(quantize(D("15000.5"), ccy)), "15001")
				self.assertEqual(split_evenly(D("100"), 3, ccy), [D("33"), D("33"), D("34")])

	def test_to_str_and_db(self):
		self.assertEqual(to_str(D("-0.00")), "0.00")
		self.assertEqual(from_db(1080.0000000001, "EUR"), Decimal("1080.00"))
		self.assertIsNone(to_str(None))

	def test_money_currency_guard(self):
		with self.assertRaises(ValueError):
			Money(D(1), "EUR") + Money(D(1), "TRY")
		self.assertEqual((Money(D("10"), "eur") * 3).amount, D(30))

	def test_bool_rejected(self):
		with self.assertRaises(TypeError):
			D(True)


class TestChildAges(unittest.TestCase):
	def setUp(self):
		self.bands = fx.bands()

	def band(self, months):
		b = ages.band_for(months, self.bands)
		return b.code if b else None

	def test_completed_months(self):
		self.assertEqual(ages.completed_months(date(2024, 6, 2), date(2027, 6, 2)), 36)
		self.assertEqual(ages.completed_months(date(2024, 6, 3), date(2027, 6, 2)), 35)
		self.assertEqual(ages.completed_months(date(2024, 1, 31), date(2024, 2, 29)), 0)
		self.assertEqual(ages.completed_months(date(2024, 1, 31), date(2024, 3, 31)), 2)
		# 29 Feb birthday reached on 1 Mar in a non-leap year
		self.assertEqual(ages.completed_months(date(2024, 2, 29), date(2027, 2, 28)), 35)
		self.assertEqual(ages.completed_months(date(2024, 2, 29), date(2027, 3, 1)), 36)
		with self.assertRaises(PricingError):
			ages.completed_months(date(2027, 1, 2), date(2027, 1, 1))

	def test_boundaries_in_months(self):
		# 2.99 / 3.00
		self.assertEqual(self.band(35), "INF")
		self.assertEqual(self.band(36), "CHA")
		# 6.99 / 7.00
		self.assertEqual(self.band(83), "CHA")
		self.assertEqual(self.band(84), "CHB")
		# 11.99 / 12.00
		self.assertEqual(self.band(143), "CHB")
		self.assertEqual(self.band(144), "TEEN")
		# 15.99 / 16.00 → above the top band
		self.assertEqual(self.band(191), "TEEN")
		self.assertIsNone(self.band(192))

	def test_declared_whole_years(self):
		for age, expected in ((0, "INF"), (2, "INF"), (3, "CHA"), (6, "CHA"), (7, "CHB"), (11, "CHB"),
		                      (12, "TEEN"), (15, "TEEN")):
			m = ages.child_months(ChildSpec(age=age), date(2027, 6, 1))
			self.assertEqual(self.band(m), expected, age)

	def test_dob_on_arrival_day_is_the_new_age(self):
		arrival = date(2027, 7, 10)
		third_birthday_today = ChildSpec(dob=date(2024, 7, 10))
		one_day_short = ChildSpec(dob=date(2024, 7, 11))
		self.assertEqual(self.band(ages.child_months(third_birthday_today, arrival)), "CHA")
		self.assertEqual(self.band(ages.child_months(one_day_short, arrival)), "INF")

	def test_fractional_band_boundaries(self):
		self.assertEqual(ages.years_to_months("2.99"), 36)   # 35.88 → 36 (display 2.99 ≙ exclusive 3)
		self.assertEqual(ages.years_to_months("3"), 36)
		self.assertEqual(ages.years_to_months("2.5"), 30)

	def test_bands_validation(self):
		ages.validate_bands(self.bands)
		with self.assertRaises(PricingError):
			ages.validate_bands((AgeBand("A", "A", 0, 40), AgeBand("B", "B", 36, 84)))
		with self.assertRaises(PricingError):
			ages.validate_bands((AgeBand("A", "A", 10, 10),))

	def test_classify_orders_oldest_first_and_promotes_over_age(self):
		t = fx.terms()
		p = ages.classify_party(t, 2, (ChildSpec(age=4), ChildSpec(age=9), ChildSpec(age=17)),
		                        date(2027, 6, 2), date(2027, 1, 1))
		self.assertEqual(p.adults, 3)                       # the 17-year-old counts as an adult
		self.assertEqual([c.band.code for c in p.children], ["CHB", "CHA"])
		self.assertEqual([c.position for c in p.children], [1, 2])
		self.assertEqual(p.children_as_adults, (2,))

	def test_ordering_youngest_and_as_entered(self):
		kids = (ChildSpec(age=9), ChildSpec(age=4))
		young = ages.classify_party(fx.terms(child_ordering=ChildOrdering.YOUNGEST_FIRST), 2, kids,
		                            date(2027, 6, 2), date(2027, 1, 1))
		self.assertEqual([c.band.code for c in young.children], ["CHA", "CHB"])
		entered = ages.classify_party(fx.terms(child_ordering=ChildOrdering.AS_ENTERED), 2, kids,
		                              date(2027, 6, 2), date(2027, 1, 1))
		self.assertEqual([c.band.code for c in entered.children], ["CHB", "CHA"])

	def test_age_basis_booking_date(self):
		kid = (ChildSpec(dob=date(2024, 3, 1)),)
		at_arrival = ages.classify_party(fx.terms(), 2, kid, date(2027, 6, 2), date(2027, 1, 15))
		at_booking = ages.classify_party(fx.terms(age_basis=AgeBasis.BOOKING_DATE), 2, kid,
		                                 date(2027, 6, 2), date(2027, 1, 15))
		self.assertEqual(at_arrival.children[0].band.code, "CHA")   # 3y3m at arrival
		self.assertEqual(at_booking.children[0].band.code, "INF")   # 2y10m at booking

	def test_over_age_rejected_when_not_promoted(self):
		with self.assertRaises(Unsellable):
			ages.classify_party(fx.terms(children_over_max_as_adults=False), 2, (ChildSpec(age=17),),
			                    date(2027, 6, 2), date(2027, 1, 1))

	def test_missing_age_rejected(self):
		with self.assertRaises(PricingError):
			ages.child_months(ChildSpec(), date(2027, 1, 1))
		with self.assertRaises(PricingError):
			ages.child_months(ChildSpec(age=-1), date(2027, 1, 1))
