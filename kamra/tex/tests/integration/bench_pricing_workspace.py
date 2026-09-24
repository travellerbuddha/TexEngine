"""Performance of the Pricing Workspace's server side on a large contract (ADR-061).

Opt-in: the file name does not start with ``test_``, so the regression run (every ``test_*``
module) leaves it out. Run it on its own::

    bench --site test.localhost run-tests --module kamra.tex.tests.integration.bench_pricing_workspace

It saves a large draft inside the test transaction (rolled back afterwards) and times, best of
three, the calls the workspace makes while a revenue manager types: the read-only overlay alone,
``price_matrix`` (saved draft and unsaved data, with and without sample parties),
``validate_version``, ``preview_price`` and (S5) ``apply_op_values`` at its 500-value cap; and
``save_version`` once; and (S8 review follow-up) a draft above the overlay's row cap, which the
workspace prices and validates by name (the overlay refuses it). Each run prints one
``PERF <case> {...}`` line (seconds). The workspace's answers for the unsaved data must equal
those for the same data saved (cells, sources, party totals, issues, the quote and its nights'
subtotals), so the figures
are of calls that did their whole job.

The ceilings are loose on purpose (several times the measured figures, ADR-061): they catch a
change of order (work per cell growing with the contract), not a slower machine.
"""

import json
import time

from frappe.utils import add_days

from kamra.tex.api import contracts as api
from kamra.tex.money import D
from kamra.tex.tests.integration import fixtures as fx
from kamra.tex.tests.integration.test_pricing_workspace_api import (
	WorkspaceCase,
	as_json,
	find,
	keyed,
	pre_s3_matrix,
)

OCC_KINDS = (("ADULT", 3, None, "MULTIPLY", "0.7"), ("CHILD", None, "CHA", "PERCENT_OF", "25"),
             ("CHILD", None, "CHB", "PERCENT_OF", "50"), ("CHILD", None, "INF", "MULTIPLY", "0"),
             ("ADULT", 4, None, "MULTIPLY", "0.6"), ("CHILD", 2, "CHB", "PERCENT_OF", "40"))
BOARD_KINDS = ("UAI", "FB", "HB")
# twelve sample parties, the most the matrix takes: what the occupancy ladder's resolved line offers
PARTIES = [{"adults": a, "children": kids} for a in (1, 2, 3)
           for kids in ([], ["CHB"], ["CHA", "CHB"], ["INF"])]


def best_of(fn, n: int = 3):
	best, out = None, None
	for _ in range(n):
		t0 = time.perf_counter()
		out = fn()
		dt = time.perf_counter() - t0
		best = dt if best is None else min(best, dt)
	return round(best, 3), out


def canonical_cells(m: dict) -> dict:
	return {r["room_type"]: {p: (D(c) if c is not None else None) for p, c in r["cells"].items()} for r in m["rooms"]}


class BenchPricingWorkspace(WorkspaceCase):
	def large_draft(self, n_rooms: int, n_periods: int, occ_per_cell: int, boards_per_cell: int):
		"""A contract shaped like an ORS one: the base room priced per period, every other room
		derived from it by a formula for all periods with its own price in every fourth period,
		``occ_per_cell`` occupancy rules and ``boards_per_cell`` board supplements per room and
		period. Saved; returns the workspace's payload of it (every table, keyed rows)."""
		rts = [self.std, self.dlx]
		for i in range(n_rooms - 2):
			rts.append(fx.ensure("Room Type", {"property": fx.PROPERTY, "room_type_code": f"PWB{i}"},
			                     {"property": fx.PROPERTY, "room_type_code": f"PWB{i}", "room_type_name": f"PWB Room {i}",
			                      "base_price": 100, "adults_capacity": 4, "children_capacity": 3,
			                      "max_total_occupants": 6, "base_occupancy": 2}))
		span = ((fx.STAY_TO - fx.STAY_FROM).days + 1) // n_periods
		periods = [{"period_code": f"P{p:02d}", "period_name": f"Period {p}",
		            "start_date": str(add_days(fx.STAY_FROM, p * span)),
		            "end_date": str(add_days(fx.STAY_FROM, (p + 1) * span - 1) if p < n_periods - 1 else fx.STAY_TO)}
		           for p in range(n_periods)]
		rates, occ, boards = [], [], [{"board": "AI", "is_base": 1}]
		for ri, rt in enumerate(rts):
			if ri:
				rates.append({"room_type": rt, "period_code": None, "op": "MULTIPLY", "value": f"1.{ri:02d}",
				              "base_room_type": self.std})
			for pi, p in enumerate(periods):
				if ri == 0 or pi % 4 == 0:
					rates.append({"room_type": rt, "period_code": p["period_code"], "op": "ABSOLUTE",
					              "value": str(100 + ri * 5 + pi)})
				for k in OCC_KINDS[:occ_per_cell]:
					occ.append({"target": k[0], "position": k[1], "age_band": k[2], "room_type": rt,
					            "period_code": p["period_code"], "op": k[3], "value": k[4]})
				for b in BOARD_KINDS[:boards_per_cell]:
					boards.append({"board": b, "op": "ADD", "adult_amount": "20", "child_percent": "50",
					               "room_type": rt, "period_code": p["period_code"]})
		data = {"rooms": [{"room_type": rt, "is_base": 1 if i == 0 else 0} for i, rt in enumerate(rts)],
		        "periods": periods, "period_rates": rates, "age_bands": fx.default_age_bands(),
		        "occupancy_rules": occ, "boards": boards}
		t0 = time.perf_counter()
		api.save_version(self.v, as_json(data))
		saved_in = round(time.perf_counter() - t0, 3)
		doc = api.get_version(self.v)
		payload = {t: keyed(t, doc[t]) for t in api.VERSION_TABLES}
		ids = {r["name"]: f"~{r['_key']}" for t in api.VERSION_TABLES for r in payload[t]}
		return payload, rts, saved_in, ids

	def run_case(self, label: str, n_rooms: int, n_periods: int, occ_per_cell: int, boards_per_cell: int,
	             ceilings: dict) -> dict:
		payload, rts, saved_in, ids = self.large_draft(n_rooms, n_periods, occ_per_cell, boards_per_cell)
		body = as_json(payload)
		rows = sum(len(payload[t]) for t in api.VERSION_TABLES)
		room = rts[3]                                        # a derived room
		quote = {"room_type": room, "board": "UAI", "check_in": str(fx.d(6, 10)), "check_out": str(fx.d(6, 17)),
		         "adults": 3, "children": json.dumps([5]), "market": "DE", "rate_plan": self.f["rate_plans"]["FLEX"]}
		parties = json.dumps(PARTIES)
		r = {"rows": rows, "cells": n_rooms * n_periods, "json_kb": round(len(body) / 1024, 1), "save_version": saved_in}
		r["overlay_only"], _ = best_of(lambda: api._overlay(self.v, body))
		r["matrix_pre_s3_keys"], _ = best_of(lambda: pre_s3_matrix(self.v))
		r["matrix_saved"], m_saved = best_of(lambda: api.price_matrix(self.v))
		r["matrix_overlay"], m_overlay = best_of(lambda: api.price_matrix(self.v, data=body))
		r["matrix_saved_12_parties"], p_saved = best_of(
			lambda: api.price_matrix(self.v, parties=parties, party_room=room))
		r["matrix_overlay_12_parties"], p_overlay = best_of(
			lambda: api.price_matrix(self.v, data=body, parties=parties, party_room=room))
		r["preview_saved"], q_saved = best_of(lambda: api.preview_price(self.v, **quote))
		r["preview_overlay"], q_overlay = best_of(lambda: api.preview_price(self.v, data=body, **quote))
		prices = json.dumps([f"{100 + i % 50}.55" for i in range(api.ADJUST_VALUES_MAX)])
		r["apply_op_values_500"], adjusted = best_of(
			lambda: api.apply_op_values(self.v, values=prices, op="ADJUST_PERCENT", value="7.5"))
		r["validate_saved"], v_saved = best_of(lambda: api.validate_version(self.v), n=1)
		r["validate_overlay"], v_overlay = best_of(lambda: api.validate_version(self.v, data=body), n=1)
		r["issues"] = len(v_saved["issues"])
		print(f"PERF {label} {json.dumps(r)}")

		# the unsaved data answers what the saved draft answers (rule ids: the row's key for its name)
		self.assertEqual(len(m_saved["rooms"]), n_rooms)
		self.assertEqual(canonical_cells(m_overlay), canonical_cells(m_saved))
		self.assertTrue(all(len(x["sources"]) == n_periods for x in m_saved["rooms"]))
		for saved, unsaved in zip(m_saved["rooms"], m_overlay["rooms"], strict=True):
			for p, src in saved["sources"].items():
				mapped = {**src, "rule_id": ids[src["rule_id"]], "overridden": [ids[i] for i in src["overridden"]]}
				self.assertEqual(unsaved["sources"][p], mapped)
		self.assertEqual(find(m_saved["rooms"], room_type=room)["sources"]["P01"]["chain"], [room, self.std])
		for a, b in zip(p_saved["party_cells"], p_overlay["party_cells"], strict=True):
			self.assertEqual({k: D(v) for k, v in a["cells"].items() if v}, {k: D(v) for k, v in b["cells"].items() if v})
			self.assertEqual(a["errors"], b["errors"])
		self.assertTrue(any(v for c in p_saved["party_cells"] for v in c["cells"].values()))
		self.assertEqual(sorted(i["code"] for i in v_overlay["issues"]), sorted(i["code"] for i in v_saved["issues"]))
		self.assertTrue(q_saved["sellable"], q_saved.get("reasons"))
		self.assertTrue(q_overlay["sellable"], q_overlay.get("reasons"))
		self.assertEqual({k: D(v) for k, v in q_overlay["totals"].items()}, {k: D(v) for k, v in q_saved["totals"].items()})
		subtotals = ("subtotal_adults", "subtotal_children", "subtotal_board")
		self.assertEqual([{k: D(n[k]) for k in subtotals} for n in q_overlay["nights"]],
		                 [{k: D(n[k]) for k in subtotals} for n in q_saved["nights"]])
		self.assertEqual(len(adjusted), api.ADJUST_VALUES_MAX)
		self.assertEqual(adjusted[0], {"value": "108.09", "error": None})           # 100.55 × 1.075 = 108.09125

		for key, ceiling in ceilings.items():
			self.assertLessEqual(r[key], ceiling, f"{label}: {key} took {r[key]} s (ceiling {ceiling} s)")
		return r

	def test_realistic_contract(self):
		"""12 rooms × 26 weekly periods, 3 occupancy rules and a board supplement per room and period."""
		self.run_case("realistic_12x26", 12, 26, 3, 1, {
			"overlay_only": 2, "matrix_overlay": 3, "matrix_overlay_12_parties": 6, "preview_overlay": 3,
			"validate_overlay": 15, "apply_op_values_500": 1})

	def test_near_the_row_cap(self):
		"""12 rooms × 40 periods, 6 occupancy rules and 3 board supplements per room and period."""
		self.run_case("near_cap_12x40", 12, 40, 6, 3, {
			"overlay_only": 4, "matrix_overlay": 6, "matrix_overlay_12_parties": 12, "preview_overlay": 6,
			"validate_overlay": 60, "apply_op_values_500": 1})

	def test_above_the_row_cap(self):
		"""12 rooms × 52 weekly periods, 6 occupancy rules and 3 board supplements per room and period:
		more rows than the overlay takes (ADR-061, S8 review follow-up). The overlay refuses it before
		any work (``OverlayTooLarge``); the workspace then asks for the saved draft by name, which has
		no cap: its matrix, sample parties, quote and validation, and the version as the editor loads it."""
		payload, rts, saved_in, _ids = self.large_draft(12, 52, 6, 3)
		body = as_json(payload)
		rows = sum(len(payload[t]) for t in api.VERSION_TABLES)
		self.assertGreater(rows, api.OVERLAY_MAX_ROWS)
		room = rts[3]
		quote = {"room_type": room, "board": "UAI", "check_in": str(fx.d(6, 10)), "check_out": str(fx.d(6, 17)),
		         "adults": 3, "children": json.dumps([5]), "market": "DE", "rate_plan": self.f["rate_plans"]["FLEX"]}

		def refused(call) -> bool:
			try:
				call()
			except api.OverlayTooLarge:
				return True
			return False

		r = {"rows": rows, "cells": 12 * 52, "json_kb": round(len(body) / 1024, 1), "save_version": saved_in}
		r["get_version"], doc = best_of(lambda: api.get_version(self.v))
		r["matrix_overlay_refused"], m_refused = best_of(lambda: refused(lambda: api.price_matrix(self.v, data=body)))
		r["validate_overlay_refused"], v_refused = best_of(
			lambda: refused(lambda: api.validate_version(self.v, data=body)))
		r["matrix_saved"], m_saved = best_of(lambda: api.price_matrix(self.v))
		r["matrix_saved_12_parties"], p_saved = best_of(
			lambda: api.price_matrix(self.v, parties=json.dumps(PARTIES), party_room=room))
		r["preview_saved"], q_saved = best_of(lambda: api.preview_price(self.v, **quote))
		r["validate_saved"], v_saved = best_of(lambda: api.validate_version(self.v), n=1)
		r["issues"] = len(v_saved["issues"])
		print(f"PERF above_cap_12x52 {json.dumps(r)}")

		self.assertEqual(doc["overlay_max_rows"], api.OVERLAY_MAX_ROWS)
		self.assertTrue(m_refused and v_refused)
		self.assertEqual(len(m_saved["rooms"]), 12)
		self.assertTrue(all(len(x["sources"]) == 52 and all(x["cells"].values()) for x in m_saved["rooms"]))
		self.assertTrue(any(v for c in p_saved["party_cells"] for v in c["cells"].values()))
		self.assertTrue(q_saved["sellable"], q_saved.get("reasons"))
		self.assertIn("ok", v_saved)
		for key, ceiling in {"matrix_overlay_refused": 2, "validate_overlay_refused": 2, "matrix_saved": 6,
		                     "matrix_saved_12_parties": 12, "preview_saved": 6, "validate_saved": 90,
		                     "get_version": 5}.items():
			self.assertLessEqual(r[key], ceiling, f"above_cap_12x52: {key} took {r[key]} s (ceiling {ceiling} s)")
