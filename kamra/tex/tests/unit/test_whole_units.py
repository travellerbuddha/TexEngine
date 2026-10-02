"""LO-48 (Part 2K-4): a count stored as a decimal string is read as Decimal, never through ``float``.

Price snapshots store quantities as decimal strings ("2.000000", ``to_str6``). The extras inventory read an old
snapshot's units, and the guest's localised quote its nights, with ``int(float(...))``: a float on the way
(CLAUDE.md: never float) and a fraction cut off without a word. They are read as ``money.whole_number`` reads
them, as ``loyalty.extra_units`` does: a whole number of units, or none. The inventory refuses a quantity that is
not one, naming it; the quote keeps the line's own text.
"""

import unittest
from datetime import date
from unittest import mock

from kamra.tex.availability import extras_repository as xinv
from kamra.tex.pricing.enums import ExtraPricingMode as M
from kamra.tex.services import content

REQUEST = {"check_in": "2027-06-02", "check_out": "2027-06-05", "adults": 2, "children": [7]}


class TestWholeNumber(unittest.TestCase):
	def test_a_stored_count_is_read_as_a_whole_number_or_none(self):
		from kamra.tex.money import whole_number

		for value, units in (("2.000000", 2), ("3", 3), (4, 4), ("0", 0), (None, 0), ("", 0), ("-1.000000", -1)):
			self.assertEqual(whole_number(value), units, value)
		for value in ("2.5", "0.000001", "abc", "NaN", "Infinity", 2.5):
			self.assertIsNone(whole_number(value), value)


class TestOldSnapshotUnits(unittest.TestCase):
	"""``_usage_of``: a snapshot from before G-19 carries no ``usage``; its units come from its quantity."""

	def line(self, quantity, mode=M.NIGHT.value):
		return {"code": "SPA", "ok": True, "quantity": quantity, "pricing_mode": mode}

	def test_a_decimal_quantity_is_its_whole_units(self):
		d2, d3, d4 = date(2027, 6, 2), date(2027, 6, 3), date(2027, 6, 4)
		self.assertEqual(xinv._usage_of(self.line("3.000000"), REQUEST), [(d2, 1), (d3, 1), (d4, 1)])
		self.assertEqual(xinv._usage_of(self.line("2.000000", M.PERSON.value), REQUEST), [(d2, 6)])

	def test_a_quantity_that_is_not_whole_is_refused_by_name(self):
		with self.assertRaisesRegex(ValueError, r"SPA.*'2\.5'"):
			xinv._usage_of(self.line("2.5", M.PERSON.value), REQUEST)


class TestQuoteNights(unittest.TestCase):
	def quote(self, quantity):
		q = {"request": {"room_type": "DBL", "board": "AI"},
		     "lines": [{"kind": "ACCOMMODATION", "code": "DBL", "quantity": quantity, "description": "as sold"}]}
		loc = content.Localizer("de")
		with mock.patch.object(loc, "room_type_name", return_value="Doppelzimmer"):
			return loc.quote("HOTEL", q)["lines"][0]["description"]

	def test_the_nights_of_a_line_are_its_whole_quantity(self):
		self.assertEqual(self.quote("3.000000"), "Doppelzimmer · AI · 3 Nächte")

	def test_a_line_whose_quantity_is_not_whole_keeps_its_own_text(self):
		self.assertEqual(self.quote("2.5"), "as sold")


if __name__ == "__main__":
	unittest.main()
