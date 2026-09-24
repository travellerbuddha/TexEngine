"""Amounts read from a migration file (G-92 review H1, L2, L3; ADR-052) and a locked price
split over its nights (G-96). Pure: runs without frappe.

A cell is read strictly: the decimal mark is the last ``,`` or ``.`` when exactly one or two
digits follow it at the end; a single separator followed by exactly three digits is ambiguous
("1.500" is 1500 or 1.5) and is refused unless the import says which mark it uses; known
currency symbols and codes are stripped and reported; negatives and anything else are refused.
Nothing is guessed.
"""

import unittest
from decimal import Decimal

from kamra.tex import importing as imp
from kamra.tex.money import split_evenly


class TestAmountCells(unittest.TestCase):
	def ok(self, cell, amount, named=(), decimal=None):
		value, currencies = imp.parse_amount(cell, decimal=decimal)
		self.assertEqual(value, Decimal(amount), cell)
		self.assertIsInstance(value, Decimal)
		self.assertEqual(currencies, frozenset(named), cell)

	def refused(self, cell, reason, decimal=None):
		with self.assertRaises(imp.AmountError, msg=cell) as caught:
			imp.parse_amount(cell, decimal=decimal)
		self.assertIn(reason, str(caught.exception), cell)

	def test_the_review_cells(self):
		self.ok("150,00", "150.00")                          # was read as 15000.00
		self.ok("1.250,50", "1250.50")                       # was 1.25
		self.refused("TL 1.500", "ambiguous")                # was 1.50
		self.refused("Rs. 1,500", "ambiguous")               # was 0.15
		self.refused("-120", "negative")                     # was 120
		self.ok("10,500.50", "10500.50")                     # L2: as before, in both importers

	def test_the_decimal_mark_is_the_last_separator_with_one_or_two_digits(self):
		self.ok("1250", "1250")
		self.ok("1250.5", "1250.5")
		self.ok("1,5", "1.5")
		self.ok("1,250.50", "1250.50")
		self.ok("1.250.000,00", "1250000.00")
		self.ok("1 250,50", "1250.50")                       # space, no-break and thin spaces group
		self.ok("1 250,50", "1250.50")
		self.ok("1'250.50", "1250.50")                       # Swiss grouping
		self.ok("1,50,000.00", "150000.00")                  # Indian grouping
		self.ok("0.75", "0.75")
		self.ok("  18,500.00 ", "18500.00")

	def test_a_repeated_separator_is_grouping(self):
		self.ok("1,250,000", "1250000")
		self.ok("1.250.000", "1250000")

	def test_three_digits_after_a_single_separator_are_ambiguous(self):
		for cell in ("1.500", "1,500", "12,345", "Rs. 1,500", "TL 1.500"):
			self.refused(cell, "ambiguous")

	def test_the_import_can_say_which_mark_it_uses(self):
		self.ok("1.500", "1500", decimal=",")
		self.ok("1.500", "1.500", decimal=".")
		self.ok("TL 1.500", "1500", named={"TRY"}, decimal=",")
		self.ok("Rs. 1,500", "1500", named={"INR"}, decimal=".")
		self.ok("150,00", "150.00", decimal=",")
		self.ok("1250", "1250", decimal=",")
		# a cell that contradicts the setting is refused, not reinterpreted
		self.refused("1,250.50", "decimal mark", decimal=",")
		self.refused("1.250,50", "decimal mark", decimal=".")
		self.refused("1,2,3", "decimal mark", decimal=",")
		with self.assertRaises(ValueError):
			imp.parse_amount("1", decimal=";")

	def test_currency_symbols_and_codes_are_stripped_and_reported(self):
		self.ok("€ 99,90", "99.90", {"EUR"})
		self.ok("99.90 EUR", "99.90", {"EUR"})
		self.ok("£1,200.00", "1200.00", {"GBP"})
		self.ok("₺2.500,00", "2500.00", {"TRY"})
		self.ok("2500,00 TL", "2500.00", {"TRY"})
		self.ok("₹ 18,500.00", "18500.00", {"INR"})
		self.ok("USD 12.50", "12.50", {"USD"})
		self.ok("try 12.50", "12.50", {"TRY"})
		# an ambiguous symbol names every currency it may be; the row's currency must be one of them
		value, named = imp.parse_amount("$ 12.50")
		self.assertEqual(value, Decimal("12.50"))
		self.assertIn("USD", named)
		self.assertIn("CAD", named)
		self.refused("€ 10 USD", "two currencies")

	def test_garbage_and_negatives_are_refused(self):
		for cell in ("(120.00)", "120-", "- 5", "−120"):
			self.refused(cell, "negative")
		for cell in ("abc", "12a", "1..5", "1,,5", "1.2.3,4.5", "1e5", "12,34,5", "12 34 5,1.2", ".", ",50", "5.",
		             "EUR", "1,2345,67"):
			self.refused(cell, "not an amount")

	def test_empty_cells_have_no_amount(self):
		for cell in (None, "", "   "):
			self.assertEqual(imp.parse_amount(cell), (None, frozenset()))

	def test_numbers_from_json_are_exact(self):
		self.ok(312.4, "312.4")
		self.ok(300, "300")
		self.ok(Decimal("12.345"), "12.345")
		self.refused(-1, "negative")
		self.refused(True, "not an amount")
		self.refused(float("nan"), "not an amount")

	def test_the_row_currency_decides(self):
		amount, named = imp.parse_amount("€ 99,90")
		self.assertEqual(imp.check_currency(amount, named, "EUR"), Decimal("99.90"))
		with self.assertRaisesRegex(imp.AmountError, "EUR, not USD"):
			imp.check_currency(amount, named, "USD")
		with self.assertRaisesRegex(imp.AmountError, "decimals"):
			imp.check_currency(Decimal("1.505"), frozenset(), "EUR")   # more than the currency's minor unit
		self.assertEqual(imp.check_currency(Decimal("1.505"), frozenset(), "KWD"), Decimal("1.505"))
		self.assertEqual(imp.check_currency(Decimal("1250"), frozenset(), "JPY"), Decimal("1250"))
		self.assertEqual(imp.check_currency(Decimal("12.5"), frozenset(), "EUR"), Decimal("12.50"))

	def test_currency_codes(self):
		self.assertEqual(imp.currency_code(" eur "), "EUR")
		self.assertEqual(imp.currency_code("TL"), "TRY")
		self.assertEqual(imp.currency_code("€"), "EUR")
		self.assertIsNone(imp.currency_code("$"))          # ambiguous: never guessed
		self.assertIsNone(imp.currency_code("euro coins"))
		self.assertIsNone(imp.currency_code(""))

	def test_pure(self):
		import ast
		import pathlib

		tree = ast.parse(pathlib.Path(imp.__file__).read_text())
		names = {a.name for n in ast.walk(tree) if isinstance(n, ast.Import | ast.ImportFrom) for a in n.names}
		mods = {n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)}
		self.assertNotIn("frappe", names | mods)


class TestSplitEvenly(unittest.TestCase):
	def test_the_remainder_goes_to_the_last_night(self):
		self.assertEqual(split_evenly(Decimal("100.00"), 3, "EUR"),
		                 [Decimal("33.33"), Decimal("33.33"), Decimal("33.34")])
		self.assertEqual(split_evenly(Decimal("312.40"), 2, "EUR"), [Decimal("156.20"), Decimal("156.20")])
		self.assertEqual(split_evenly(Decimal("1000"), 3, "JPY"), [Decimal("333"), Decimal("333"), Decimal("334")])
		self.assertEqual(split_evenly(Decimal("0.05"), 3, "EUR"), [Decimal("0.01"), Decimal("0.01"), Decimal("0.03")])
		self.assertEqual(split_evenly(Decimal("50"), 1, "EUR"), [Decimal("50.00")])
		for total, n in ((Decimal("100.00"), 3), (Decimal("0.05"), 3), (Decimal("99999.99"), 7)):
			self.assertEqual(sum(split_evenly(total, n, "EUR")), total)

	def test_no_night_or_a_negative_total_is_refused(self):
		with self.assertRaises(ValueError):
			split_evenly(Decimal("10"), 0, "EUR")
		with self.assertRaises(ValueError):
			split_evenly(Decimal("-1"), 2, "EUR")
