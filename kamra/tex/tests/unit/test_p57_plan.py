"""O-38 (audit 2B, ADR-065): p57 keeps each payment link idempotency key on its oldest link. The
unique index makes duplicates impossible to seed in a database, so its plan is tested here, pure."""

import ast
import pathlib
import unittest
from datetime import datetime

from kamra.patches.tex import p57_payment_link_unique_key as p57

T = datetime(2026, 9, 1, 10, 0)


class TestP57Plan(unittest.TestCase):
	def test_the_oldest_link_keeps_its_key_and_every_later_one_is_renamed(self):
		rows = [("PL-3", "k1", T), ("PL-1", "k1", T), ("PL-2", "k1", datetime(2026, 9, 1, 9, 0)),
		        ("PL-4", "k2", T), ("PL-5", None, T), ("PL-6", "", T), ("PL-7", "  ", T)]
		renames, blanks = p57.plan(rows)
		# by creation, then name: PL-2 is the oldest; PL-1 and PL-3 (same time) follow in name order
		self.assertEqual(renames, [("PL-1", "k1:dup:PL-1", "PL-2"), ("PL-3", "k1:dup:PL-3", "PL-2")])
		self.assertEqual(blanks, ["PL-6", "PL-7"])                     # empty keys become NULL

	def test_a_second_run_finds_nothing(self):
		rows = [("PL-2", "k1", T), ("PL-1", "k1:dup:PL-1", T), ("PL-3", "k1:dup:PL-3", T), ("PL-5", None, T)]
		self.assertEqual(p57.plan(rows), ([], []))

	def test_a_long_key_still_fits_its_column(self):
		key = "x" * p57.KEY_LENGTH
		(name, new, kept), = p57.plan([("PL-1", key, T), ("PL-00002", key, datetime(2026, 9, 2))])[0]
		self.assertEqual((name, kept, len(new)), ("PL-00002", "PL-1", p57.KEY_LENGTH))
		self.assertTrue(new.endswith(":dup:PL-00002"))

	def test_frappe_is_imported_only_when_the_patch_runs(self):
		tree = ast.parse(pathlib.Path(p57.__file__).read_text())
		top = [n for n in tree.body if isinstance(n, ast.Import | ast.ImportFrom)]
		self.assertEqual(top, [])


if __name__ == "__main__":
	unittest.main()
