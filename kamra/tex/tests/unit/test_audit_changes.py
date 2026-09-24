"""Audit change records (G-74, ADR-053): canonical values and bounded collection diffs."""

import unittest
from datetime import date, datetime
from decimal import Decimal

from kamra.tex.commercial import diffs
from kamra.tex.security import changes


class TestCanonicalValues(unittest.TestCase):
	def test_numbers_never_become_floats(self):
		self.assertEqual(changes.canon(100.0), "100")
		self.assertEqual(changes.canon(Decimal("0.70")), "0.7")
		self.assertEqual(changes.canon(Decimal("-0.00")), "0")
		self.assertEqual(changes.canon(0.1), "0.1")
		self.assertEqual(changes.canon(1e-7), "0.0000001")                # never "1E-7"
		self.assertEqual(changes.canon(3), 3)
		self.assertIs(changes.canon(True), True)

	def test_blanks_dates_and_sequences(self):
		self.assertIsNone(changes.canon(""))
		self.assertEqual(changes.canon(date(2027, 7, 1)), "2027-07-01")
		self.assertEqual(changes.canon(datetime(2027, 7, 1, 9, 30, 5, 123)), "2027-07-01 09:30:05")
		self.assertEqual(changes.canon(frozenset({"b", "a"})), ["a", "b"])
		self.assertEqual(changes.canon({"x": (1, 2.5)}), {"x": [1, "2.5"]})
		self.assertTrue(changes.canon("x" * 1000).endswith("…"))

	def test_field_changes_compare_canonical_values(self):
		old, new = changes.field_changes({"value": 100.0, "note": "", "op": "ADD"},
		                                 {"value": "100", "note": None, "op": "SUBTRACT"})
		self.assertEqual((old, new), ({"op": "ADD"}, {"op": "SUBTRACT"}))


class TestCollectionDiff(unittest.TestCase):
	def test_rows_are_matched_by_natural_key(self):
		before = [{"id": "r1", "room_type": "STD", "period": "LOW", "value": "100"},
		          {"id": "r2", "room_type": "DLX", "period": None, "value": "1.35"}]
		after = [{"id": "x9", "room_type": "STD", "period": "LOW", "value": "110"},
		         {"id": "x8", "room_type": "DLX", "period": None, "value": "1.35"},
		         {"id": "x7", "room_type": "STE", "period": "HIGH", "value": "300"}]
		d = changes.collection_diff(before, after, ("room_type", "period"), ignore=("id",))
		self.assertEqual(d["count"], [2, 3])
		self.assertEqual(d["totals"], {"added": 1, "removed": 0, "changed": 1})
		self.assertEqual(d["added"], ["STE · HIGH"])
		self.assertEqual(d["changed"], {"STD · LOW": {"value": ["100", "110"]}})
		self.assertIsNone(changes.collection_diff(before, before, ("room_type", "period"), ignore=("id",)))

	def test_trailing_blank_keys_are_dropped_and_duplicates_told_apart(self):
		self.assertEqual(changes.key_of({"board": "HB", "room_type": None, "period": ""}, ("board", "room_type", "period")),
		                 "HB")
		self.assertEqual(changes.key_of({"board": "HB", "room_type": None, "period": "LOW"},
		                                ("board", "room_type", "period")), "HB · * · LOW")
		d = changes.collection_diff([], [{"code": "A"}, {"code": "A"}], ("code",))
		self.assertEqual(d["added"], ["A", "A #2"])

	def test_a_large_diff_is_bounded(self):
		before = [{"code": f"P{i:03d}", "value": 1} for i in range(200)]
		after = [{"code": f"P{i:03d}", "value": 2} for i in range(150)] + [{"code": f"N{i:03d}"} for i in range(80)]
		d = changes.collection_diff(before, after, ("code",))
		self.assertEqual(d["totals"], {"added": 80, "removed": 50, "changed": 150})
		self.assertEqual(len(d["added"]), changes.LIST_LIMIT)
		self.assertEqual(len(d["removed"]), 50)
		self.assertEqual(len(d["changed"]), changes.DETAIL_LIMIT)
		self.assertEqual(len(d["changed_keys"]), changes.LIST_LIMIT)
		self.assertEqual(d["changed_keys"][0], f"P{changes.DETAIL_LIMIT:03d}")

	def test_cells_keep_old_values_and_count_them_beyond_the_bound(self):
		cells = [(f"STD · 2027-07-{i:02d}", {"min_los": 2 if i == 1 else 0}, {"min_los": 3}) for i in range(1, 61)]
		cells.append(("DLX · 2027-07-01", {"min_los": 3}, {"min_los": 3}))
		d = changes.cells_diff(cells)
		self.assertEqual(d["totals"]["changed"], 60)
		self.assertEqual(d["unchanged"], 1)
		self.assertEqual(len(d["changed"]), changes.CELL_LIMIT)
		self.assertEqual(d["changed"]["STD · 2027-07-01"], {"min_los": [2, 3]})
		self.assertEqual(d["old_values"], {"min_los": {"0": 59, "2": 1}})
		self.assertEqual(changes.cells_diff([("a", {"x": 1}, {"x": 1})])["totals"]["changed"], 0)

	def test_old_value_counts_are_bounded(self):
		cells = [(str(i), {"v": i}, {"v": -1}) for i in range(30)]
		hist = changes.cells_diff(cells)["old_values"]["v"]
		self.assertEqual(len(hist), changes.HISTOGRAM_LIMIT + 1)
		self.assertEqual(hist["…"], 30 - changes.HISTOGRAM_LIMIT)


class TestContractDiffs(unittest.TestCase):
	def payload(self, low="100", boards=("AI",), tax=False):
		return {"schema": 1, "version": {"id": "V", "no": 1},
		        "contract": {"id": "C", "currency": "EUR", "channels": ["DIRECT_WEB"]},
		        "settings": {"prices_include_tax": tax, "stacking": "SEQUENTIAL"},
		        "rooms": [{"room_type": "STD", "max_adults": 3}],
		        "room_rules": [{"id": "a", "room_type": "STD", "period": "LOW", "op": "ABSOLUTE", "value": low}],
		        "boards": [{"id": b, "board": b, "room_type": None, "period": None} for b in boards],
		        "offers": [{"id": "EARLY", "value": "10"}]}

	def test_publish_diff_names_what_changed(self):
		d = diffs.payload_diff(self.payload(), self.payload(low="110", boards=("AI", "HB"), tax=True))
		self.assertEqual(d["room_rules"]["changed"], {"STD · LOW": {"value": ["100", "110"]}})
		self.assertEqual(d["boards"]["added"], ["HB"])
		self.assertEqual(d["settings"], {"fields": {"prices_include_tax": [False, True]}})
		self.assertEqual(set(d), {"room_rules", "boards", "settings"})

	def test_a_first_publish_lists_what_it_froze(self):
		d = diffs.payload_diff(None, self.payload())
		self.assertEqual(d["rooms"]["added"], ["STD"])
		self.assertEqual(d["offers"]["added"], ["EARLY"])
		self.assertNotIn("settings", d)

	def test_draft_diff_splits_fields_and_tables(self):
		before = {"fields": {"stacking": "SEQUENTIAL"}, "tables": {"periods": [{"period_code": "LOW", "priority": 0}]}}
		after = {"fields": {"stacking": "BEST"}, "tables": {"periods": [{"period_code": "LOW", "priority": 5}]}}
		old, new, tables = diffs.draft_diff(before, after)
		self.assertEqual((old, new), ({"stacking": "SEQUENTIAL"}, {"stacking": "BEST"}))
		self.assertEqual(tables["periods"]["changed"], {"LOW": {"priority": [0, 5]}})


if __name__ == "__main__":
	unittest.main()
