"""Draft overlay performance of the Pricing Workspace (ADR-061, "Draft overlay performance").

The workspace prices, validates and quotes the editor's unsaved draft on the server (the read-only
overlay, GAP-1) while a revenue manager types. This module times each call it makes then, as it
makes it, on a realistically large contract, and pins what must not grow:

* the draft (``PerfContract``; built and saved inside the test transaction, rolled back): 15 room
  types (the base room priced per period, the other 14 derived from it by a formula for every
  period, with their own prices in some periods), 26 periods (22 seasons covering the stay window
  and 4 Fri/Sat periods over the peak months), PERSON basis, adult positions 1–4 with 3rd-adult
  overrides per period and per room and period, 4 child age bands with band, position and period
  rules and the second child per room and period, 11 special combinations (and period and room
  overrides of 2A+2C), 6 boards with rules per room, per period and per room and period, 3 rate
  plans and 4 offers: 1,320 rows (129 room rules, 902 occupancy rules, 237 board rules), 390 cells.
  It validates without an error, so its check runs the whole publish sweep;
* the calls (``WorkspaceApi``, ``workspace=1``, the unsaved state posted as the JSON text the
  browser sends, the one-cell edit a user just typed applied to it): ``price_matrix`` with the
  whole matrix (alone; with the occupancy ladder's one sample party; with the 12 parties the
  endpoint takes at most), ``validate_version``, ``preview_price`` (the Price test's 3-night
  2-adult prefill; a 14-night stay of 2 adults and 2 children) and ``apply_op_values`` (a row of
  26 prices; 500, its cap). The same calls on the saved draft by name are the baseline;
* each call is timed from a fresh request's caches (the capability and value caches Frappe keeps
  per request are cleared before it, the site's redis caches stay warm as on a running server),
  after warm-up, ``RUNS`` times (at least 20): p50, p95 (nearest rank) and max wall time, the
  response's size as Frappe sends it, and its ``frappe.db.sql`` calls. HTTP, session and auth are
  not included; the request's JSON is (the calls parse the posted text).

Asserted: the query count of every call is the same for 26 periods as for 13 (half the cells and
half the period rules) and grows by at most one query per room (the room type's capacity read by
``build_terms``), whatever the cells; a 14-night quote asks the same as a 3-night one;
``apply_op_values`` asks the same for 500 prices as for 26; and
the time budgets on the development bench (p95 of the whole-matrix overlay 0.8 s, of a draft quote
0.5 s), with a factor ``CI_FACTOR`` (3, or ``TEX_PERF_FACTOR``) so a slower or busy machine does not
fail it. Every figure is printed (``PERF`` lines); ``TEX_PERF_PROFILE=1`` also prints a cProfile
of each budgeted call.
"""

from __future__ import annotations

import cProfile
import io
import json
import math
import os
import pstats
import time
from collections import defaultdict
from contextlib import contextmanager
from datetime import date, timedelta
from unittest.mock import patch

import frappe
from frappe.utils import cint
from frappe.utils.data import orjson_dumps
from frappe.utils.response import json_handler

from kamra.tex.api import contracts as api
from kamra.tex.money import D
from kamra.tex.security import scope
from kamra.tex.tests.integration import fixtures as fx
from kamra.tex.tests.integration.test_pricing_workspace_api import RM, WorkspaceCase, as_json, find, wapi

RUNS = max(20, cint(os.environ.get("TEX_PERF_RUNS")))
WARMUP = 3
SLOW = 1.0            # seconds: a call this slow is warm after one call (the check, about 2.7 s)
CI_FACTOR = float(os.environ.get("TEX_PERF_FACTOR") or 3)
PROFILE = bool(os.environ.get("TEX_PERF_PROFILE"))
# p95 on the development bench, seconds (ADR-061, "Draft overlay performance")
BUDGET = {"matrix": 0.8, "quote": 0.5}

LAYOUT = ("Section Break", "Column Break", "Tab Break")
# room capacity classes: (adults, children, occupants)
CLASSES = {"DBL": (2, 1, 3), "TRP": (3, 2, 5), "FAM": (4, 2, 6), "SUI": (4, 3, 7)}
# the 13 room types created besides the fixture's STD (the base room) and DLX
NEW_ROOMS = ("DBL", "TRP", "FAM", "DBL", "TRP", "FAM", "SUI", "DBL", "TRP", "FAM", "SUI", "TRP", "DBL")
BOARDS = (("RO", None), ("BB", "12"), ("HB", "25"), ("FB", "38"), ("AI", "55"), ("UAI", "75"))
BANDS = (("INF", "Infant", "0", "1.99", 1), ("CH1", "Small child", "2", "6.99", 0),
         ("CH2", "Child", "7", "11.99", 0), ("CH3", "Teen", "12", "15.99", 0))
# the special combinations (adults+children) and their rows: (target, position, band, op, value)
COMBINATIONS = {
	"1+0": [("ADULT", 1, None, "MULTIPLY", "1.5")],
	"1+1": [("ADULT", 1, None, "MULTIPLY", "1.3"), ("CHILD", 1, None, "PERCENT_OF", "50")],
	"1+2": [("ADULT", 1, None, "MULTIPLY", "1.2"), ("CHILD", 1, None, "PERCENT_OF", "50"),
	        ("CHILD", 2, None, "PERCENT_OF", "30")],
	"2+1": [("CHILD", 1, "CH2", "PERCENT_OF", "0"), ("CHILD", 1, "CH3", "PERCENT_OF", "50")],
	"2+2": [("CHILD", 1, "CH2", "PERCENT_OF", "0"), ("CHILD", 2, "CH2", "PERCENT_OF", "50"),
	        ("CHILD", 2, "CH1", "PERCENT_OF", "30"), ("CHILD", 2, "CH3", "PERCENT_OF", "60")],
	"2+3": [("CHILD", 3, None, "PERCENT_OF", "70")],
	"3+0": [("ADULT", 3, None, "MULTIPLY", "0.8")],
	"3+1": [("CHILD", 1, None, "PERCENT_OF", "50")],
	"3+2": [("CHILD", 1, None, "PERCENT_OF", "50"), ("CHILD", 2, None, "PERCENT_OF", "70")],
	"4+1": [("CHILD", 1, None, "PERCENT_OF", "70")],
	"4+2": [("CHILD", 1, None, "PERCENT_OF", "70"), ("CHILD", 2, None, "PERCENT_OF", "70")],
}
# twelve sample parties, the most price_matrix takes (the ladder sends one)
PARTIES = [{"adults": a, "children": kids} for a in (1, 2, 3)
           for kids in ([], ["CH2"], ["CH1", "CH2"], ["INF"])]


# ─── measuring ─────────────────────────────────────────────────────────────────────────────────


@contextmanager
def queries():
	"""Counts ``frappe.db.sql`` calls (every Frappe read and write goes through it)."""
	real = frappe.db.sql
	seen = []

	def spy(*args, **kwargs):
		seen.append(args[0] if args else kwargs.get("query"))
		return real(*args, **kwargs)

	with patch.object(frappe.db, "sql", side_effect=spy):
		yield seen


def fresh_request(user: str) -> None:
	"""The caches a new request starts without: the user's (roles, permissions), Frappe's per-request
	and value caches and TEX's capability cache. Redis (meta, documents) stays warm, as on a server
	that has been running."""
	frappe.set_user(user)  # nosemgrep: frappe-setuser -- a request of the revenue manager
	frappe.local.request_cache = defaultdict(dict)
	frappe.db.value_cache.clear()
	scope.clear_cache()


def nearest_rank(sorted_values: list[float], p: float) -> float:
	return sorted_values[max(0, math.ceil(p * len(sorted_values)) - 1)]


def response_bytes(result) -> int:
	"""The body Frappe sends for a whitelisted call's answer (``frappe.utils.response.as_json``)."""
	return len(orjson_dumps({"message": result}, default=json_handler, decode=False))


def measure(user: str, fn, runs: int = RUNS) -> tuple[dict, object]:
	"""``fn`` timed ``runs`` times after ``WARMUP`` calls, each from a fresh request; then once more
	under the query counter. → the figures, and the last answer."""
	out = None
	for _ in range(WARMUP):
		fresh_request(user)
		t0 = time.perf_counter()
		out = fn()
		if time.perf_counter() - t0 > SLOW:
			break
	times = []
	for _ in range(runs):
		fresh_request(user)
		t0 = time.perf_counter()
		out = fn()
		times.append(time.perf_counter() - t0)
	fresh_request(user)
	with queries() as seen:
		fn()
	times.sort()
	return {"runs": runs, "p50_ms": round(nearest_rank(times, 0.50) * 1000, 1),
	        "p95_ms": round(nearest_rank(times, 0.95) * 1000, 1), "max_ms": round(times[-1] * 1000, 1),
	        "payload_kb": round(response_bytes(out) / 1024, 2), "payload_bytes": response_bytes(out),
	        "queries": len(seen)}, out


def count_queries(user: str, fn) -> int:
	fresh_request(user)
	fn()                                             # the same warm redis as the measured calls
	fresh_request(user)
	with queries() as seen:
		fn()
	return len(seen)


def profile(user: str, fn, top: int = 25) -> str:
	fresh_request(user)
	pr = cProfile.Profile()
	pr.enable()
	fn()
	pr.disable()
	s = io.StringIO()
	pstats.Stats(pr, stream=s).sort_stats("cumulative").print_stats(top)
	return s.getvalue()


# ─── the contract ──────────────────────────────────────────────────────────────────────────────


def periods_of(stay_from: date, stay_to: date, seasons: int, weekends: int, year: int) -> list[dict]:
	"""``seasons`` consecutive periods covering the stay window, and ``weekends`` Fri/Sat periods
	over the peak months from June (a weekday period ranks before the season it overlaps)."""
	days = (stay_to - stay_from).days + 1
	starts = [stay_from + timedelta(days=round(i * days / seasons)) for i in range(seasons)]
	out = []
	for i, start in enumerate(starts):
		end = starts[i + 1] - timedelta(days=1) if i + 1 < seasons else stay_to
		out.append({"period_code": f"S{i + 1:02d}", "period_name": f"Season {i + 1}", "start_date": str(start),
		            "end_date": str(end), "weekdays": None, "adjustment_op": None, "adjustment_value": None,
		            "priority": 0})
	for w in range(weekends):
		month = 6 + w
		last = date(year, month + 1, 1) - timedelta(days=1)
		out.append({"period_code": f"W{w + 1}", "period_name": f"Weekend {date(year, month, 1):%b}",
		            "start_date": str(date(year, month, 1)), "end_date": str(last), "weekdays": "Fri,Sat",
		            "adjustment_op": None, "adjustment_value": None, "priority": 1})
	return out


class PerfContract:
	"""The large draft, in the shape the workspace posts (every table, each row with its client key).

	``n_rooms`` room types (STD, the base; DLX; then ``NEW_ROOMS`` in order), ``seasons`` + ``weekends``
	periods. Peak periods: the middle third of the seasons and every weekend period."""

	def __init__(self, f: dict, n_rooms: int = 15, seasons: int = 22, weekends: int = 4):
		self.std, self.dlx = f["room_types"]["STD"], f["room_types"]["DLX"]
		self.rooms = {self.std: "TRP", self.dlx: "SUI"}
		for i, cls in enumerate(NEW_ROOMS[:n_rooms - 2]):
			a, c, o = CLASSES[cls]
			rt = fx.ensure("Room Type", {"property": fx.PROPERTY, "room_type_code": f"PWP{i:02d}"},
			               {"property": fx.PROPERTY, "room_type_code": f"PWP{i:02d}",
			                "room_type_name": f"Perf {cls} {i:02d}", "base_price": 100, "adults_capacity": a,
			                "children_capacity": c, "max_total_occupants": o, "base_occupancy": 2})
			self.rooms[rt] = cls
		self.periods = periods_of(fx.STAY_FROM, fx.STAY_TO, seasons, weekends, fx.YEAR)
		codes = [p["period_code"] for p in self.periods]
		self.peak = [c for i, c in enumerate(codes[:seasons]) if seasons // 3 <= i < 2 * seasons // 3] + codes[seasons:]
		self.rate_plans = self.ensure_rate_plans(f)
		self.data = self.build(codes)

	def ensure_rate_plans(self, f: dict) -> list[str]:
		nrf = frappe.db.get_value("Rate Plan", f["rate_plans"]["NRF"],
		                          ["tex_cancellation_policy", "tex_payment_policy"], as_dict=True)
		saver = fx.ensure("Rate Plan", {"property": fx.PROPERTY, "code": "PWSAVER"},
		                  {"property": fx.PROPERTY, "code": "PWSAVER", "rate_plan_name": "Saver all inclusive",
		                   "modifier_type": "Percent", "modifier_value": 0, "tex_refundable": 0,
		                   "tex_cancellation_policy": nrf.tex_cancellation_policy,
		                   "tex_payment_policy": nrf.tex_payment_policy})
		return [f["rate_plans"]["FLEX"], f["rate_plans"]["NRF"], saver]

	def of_class(self, *classes: str) -> list[str]:
		return [rt for rt, cls in self.rooms.items() if cls in classes]

	def build(self, codes: list[str]) -> dict:
		std, rooms, peak = self.std, list(self.rooms), set(self.peak)
		rates, occ, boards = [], [], []

		def rate(rt, period, op, value, base=None):
			rates.append({"room_type": rt, "period_code": period, "op": op, "value": value, "base_room_type": base})

		def rule(target, position=None, band=None, op="PERCENT_OF", value="0", room=None, period=None, combo=None):
			occ.append({"target": target, "position": position, "age_band": band, "combination": combo,
			            "room_type": room, "period_code": period, "op": op, "value": value, "is_override": 0,
			            "note": None})

		def board(code, amount, room=None, period=None, is_base=0):
			boards.append({"board": code, "is_base": is_base, "op": "ADD", "adult_amount": amount,
			               "child_percent": "50", "infant_free": 1, "room_type": room, "period_code": period,
			               "label": None})

		# rooms: the base room priced per period; every other room derived by a formula for every
		# period, with its own price in every fourth season; the suites add to the base at weekends
		for pi, p in enumerate(codes):
			rate(std, p, "ABSOLUTE", str(80 + 3 * pi + (15 if p.startswith("W") else 0)))
		for ri, rt in enumerate(rooms[1:], 1):
			rate(rt, None, "MULTIPLY", str(D(1) + D(ri) * D("0.08")), std)
			for pi, p in enumerate(codes):
				if p.startswith("S") and pi % 4 == ri % 4:
					rate(rt, p, "ABSOLUTE", str(95 + 7 * ri + 2 * pi))
				elif p.startswith("W") and self.rooms[rt] == "SUI":
					rate(rt, p, "ADD", "25", std)

		# adults: positions 1-4; the 3rd adult per period, per room and period in rooms with a 3rd
		# adult, the 4th per room and period in the four-adult rooms
		for pos, value in ((1, "1"), (2, "1"), (3, "0.7"), (4, "0.6")):
			rule("ADULT", pos, op="MULTIPLY", value=value)
		for p in codes:
			rule("ADULT", 3, op="MULTIPLY", value="0.75" if p in peak else "0.65", period=p)
			for rt in self.of_class("TRP", "FAM", "SUI"):
				rule("ADULT", 3, op="MULTIPLY", value="0.8" if p in peak else "0.7", room=rt, period=p)
			for rt in self.of_class("FAM", "SUI"):
				rule("ADULT", 4, op="MULTIPLY", value="0.6" if p in peak else "0.5", room=rt, period=p)

		# children: a rule per band, the first small child free, the first child 25 %; per period the
		# first small child, the child band and its first child, the teens; per room and period the
		# second child in the rooms for two children or more
		for code, value in (("INF", "0"), ("CH1", "30"), ("CH2", "50"), ("CH3", "70")):
			rule("CHILD", band=code, op="MULTIPLY" if code == "INF" else "PERCENT_OF", value=value)
		rule("CHILD", 1, "CH1", value="0")
		rule("CHILD", 1, "CH2", value="25")
		for p in codes:
			hi = p in peak
			rule("CHILD", 1, "CH1", value="20" if hi else "0", period=p)
			rule("CHILD", None, "CH2", value="50" if hi else "40", period=p)
			rule("CHILD", 1, "CH2", value="30" if hi else "0", period=p)
			rule("CHILD", None, "CH3", value="75" if hi else "60", period=p)
			for rt in self.of_class("TRP", "FAM", "SUI"):
				rule("CHILD", 2, "CH2", value="60" if hi else "45", room=rt, period=p)

		# special combinations: each at the contract; 2A+2C also per peak period and per family room
		for combo, rows in COMBINATIONS.items():
			for target, pos, band, op, value in rows:
				rule(target, pos, band, op, value, combo=combo)
		for p in self.peak:
			rule("CHILD", 2, "CH2", value="60", period=p, combo="2+2")
		for rt in self.of_class("FAM"):
			rule("CHILD", 2, "CH2", value="40", room=rt, combo="2+2")

		# boards: room only is the base; the others per adult, with rules per room (all-inclusive
		# in the family rooms and suites), per period and per room and period
		board("RO", None, is_base=1)
		for code, amount in BOARDS[1:]:
			board(code, amount)
		for rt in self.of_class("FAM", "SUI"):
			board("AI", "60", room=rt)
			board("UAI", "82", room=rt)
		for p in codes:
			hi = p in peak
			board("AI", "62" if hi else "52", period=p)
			board("UAI", "85" if hi else "70", period=p)
			if hi:
				board("HB", "28", period=p)
			for rt in self.of_class("SUI"):
				board("UAI", "95" if hi else "80", room=rt, period=p)
			for rt in self.of_class("FAM"):
				board("AI", "66" if hi else "56", room=rt, period=p)

		flex, nrf, saver = self.rate_plans
		plans = [{"rate_plan": flex, "op": None, "value": None, "refundable": 1, "boards": None},
		         {"rate_plan": nrf, "op": "ADJUST_PERCENT", "value": "-10", "refundable": 0, "boards": None},
		         {"rate_plan": saver, "op": "ADJUST_PERCENT", "value": "-15", "refundable": 0, "boards": "AI,UAI"}]
		sui = ",".join(self.of_class("SUI"))
		offers = [
			{"offer_code": "EB10", "offer_name": "Early booking", "kind": "EARLY_BOOKING", "value_type": "PERCENT",
			 "value": "10", "min_lead_days": 30},
			{"offer_code": "LS5", "offer_name": "Long stay", "kind": "LONG_STAY", "value_type": "PERCENT",
			 "value": "5", "min_nights": 10},
			{"offer_code": "FN76", "offer_name": "Stay 7 pay 6", "kind": "LONG_STAY", "value_type": "FREE_NIGHTS",
			 "value": "0", "free_nights_stay": 7, "free_nights_pay": 6, "stackable": 0, "priority": 1},
			{"offer_code": "SUI8", "offer_name": "Suites", "kind": "ROOM", "value_type": "PERCENT", "value": "8",
			 "room_types": sui},
		]
		return {
			"rooms": [{"room_type": rt, "is_base": 1 if rt == std else 0} for rt in rooms],
			"periods": self.periods, "period_rates": rates,
			"age_bands": [{"band_code": c, "label": lbl, "from_age": lo, "to_age": hi, "is_infant": inf}
			              for c, lbl, lo, hi, inf in BANDS],
			"occupancy_rules": occ, "boards": boards, "rate_plans": plans, "offers": offers,
		}

	def shape(self) -> dict:
		return {t: len(self.data[t]) for t in api.VERSION_TABLES} | {
			"rows": sum(len(self.data[t]) for t in api.VERSION_TABLES), "cells": len(self.rooms) * len(self.periods),
			"combinations": len(COMBINATIONS)}


def ui_payload(doc: dict) -> dict:
	"""What the workspace posts for a version it loaded (``overlayPayloadOf``): its settings and each
	table's fields as the editor holds them, each row with its client key."""
	out = {f: doc.get(f) for f in api.VERSION_SETTINGS}
	out["change_note"] = out.get("change_note") or None
	version = frappe.get_meta("TEX Contract Version")
	for t in api.VERSION_TABLES:
		meta = frappe.get_meta(version.get_field(t).options)
		rows = []
		for i, r in enumerate(doc[t]):
			row = {}
			for df in meta.fields:
				if df.fieldtype in LAYOUT:
					continue
				v = r.get(df.fieldname)
				if df.fieldtype == "Int":
					row[df.fieldname] = cint(v)
				elif df.fieldtype == "Check":
					row[df.fieldname] = 1 if cint(v) else 0
				else:
					row[df.fieldname] = None if v is None or v == "" else str(v)
			row["_key"] = f"{t}-k{i + 1}"
			rows.append(row)
		out[t] = rows
	return out


# ─── the tests ─────────────────────────────────────────────────────────────────────────────────


class PerfCase(WorkspaceCase):
	def save(self, contract: PerfContract) -> dict:
		"""Saves the draft as the workspace does; → what the workspace then posts for it."""
		wapi.save_version(self.v, as_json(contract.data))
		return ui_payload(wapi.get_version(self.v))

	def quotes(self, contract: PerfContract) -> dict:
		"""The Price test's calls: its prefill (the base room in the fifth season, the base board, the
		first rate plan, 3 nights, 2 adults) and the worst case the workspace is asked for (a family
		room, ultra all inclusive, 14 nights in July across two seasons and the July Fri/Sat period,
		2 adults and 2 children aged 4 and 9)."""
		s05 = next(p for p in contract.periods if p["period_code"] == "S05")
		common = {"rate_plan": contract.rate_plans[0], "market": "DE", "channel": "DIRECT_WEB", "currency": "EUR",
		          "sale_at": None, "promo_codes": json.dumps([])}
		fam = contract.of_class("FAM")[0]
		return {
			"typical": {**common, "room_type": contract.std, "board": "RO", "check_in": s05["start_date"],
			            "check_out": str(date.fromisoformat(s05["start_date"]) + timedelta(days=3)), "adults": 2,
			            "children": json.dumps([])},
			"worst": {**common, "room_type": fam, "board": "UAI", "check_in": str(fx.d(7, 10)),
			          "check_out": str(fx.d(7, 24)), "adults": 2, "children": json.dumps([4, 9])},
		}

	def calls(self, contract: PerfContract, body: str) -> dict:
		"""Each call the workspace makes while its user edits, with the unsaved state ``body``
		(overlay) and on the saved draft by name (saved): label → (overlay call, saved call)."""
		v, fam = self.v, contract.of_class("FAM")[0]
		one = json.dumps([{"adults": 2, "children": ["CH1", "CH2"]}])
		twelve = json.dumps(PARTIES)
		q = self.quotes(contract)
		row = json.dumps([f"{100 + i}.50" for i in range(len(contract.periods))])
		cap = json.dumps([f"{100 + i % 50}.55" for i in range(api.ADJUST_VALUES_MAX)])
		return {
			"matrix": (lambda: wapi.price_matrix(v, data=body), lambda: wapi.price_matrix(v)),
			"matrix_1_party": (lambda: wapi.price_matrix(v, data=body, parties=one, party_room=fam),
			                   lambda: wapi.price_matrix(v, parties=one, party_room=fam)),
			"matrix_12_parties": (lambda: wapi.price_matrix(v, data=body, parties=twelve, party_room=fam),
			                      lambda: wapi.price_matrix(v, parties=twelve, party_room=fam)),
			"quote_3n_2a": (lambda: wapi.preview_price(v, data=body, **q["typical"]),
			                lambda: wapi.preview_price(v, **q["typical"])),
			"quote_14n_2a2c": (lambda: wapi.preview_price(v, data=body, **q["worst"]),
			                   lambda: wapi.preview_price(v, **q["worst"])),
			"validate": (lambda: wapi.validate_version(v, data=body), lambda: wapi.validate_version(v)),
			"apply_op_values_26": (lambda: api.apply_op_values(v, values=row, op="ADJUST_PERCENT", value="7.5"), None),
			"apply_op_values_500": (lambda: api.apply_op_values(v, values=cap, op="ADJUST_PERCENT", value="7.5"),
			                        None),
		}


class TestDraftOverlayPerformance(PerfCase):
	def test_draft_overlay_within_budget(self):
		contract = PerfContract(self.f)
		shape = contract.shape()
		print(f"PERF shape {json.dumps(shape)}")
		self.assertGreaterEqual(len(contract.rooms), 15)
		self.assertEqual(len(contract.periods), 26)
		t0 = time.perf_counter()
		payload = self.save(contract)
		print(f"PERF save_version {round((time.perf_counter() - t0) * 1000)} ms")
		# the edit just typed: the base room's price in the fifth season
		edited = find(payload["period_rates"], room_type=contract.std, period_code="S05")
		old = D(edited["value"])
		edited["value"] = str(old + 1)
		body = as_json(payload)
		print(f"PERF request {json.dumps({'data_kb': round(len(body.encode()) / 1024, 1)})}")

		results, answers = {}, {}
		for label, (overlay, saved) in self.calls(contract, body).items():
			results[f"{label} overlay" if saved else label], answers[(label, "overlay")] = measure(RM, overlay)
			if saved:
				results[f"{label} saved"], answers[(label, "saved")] = measure(RM, saved)
		for label, r in results.items():
			print(f"PERF {label} {json.dumps(r)}")

		# the calls did their whole job: the unsaved price is priced, the saved one by name
		m_o, m_s = answers[("matrix", "overlay")], answers[("matrix", "saved")]
		self.assertEqual(D(find(m_o["rooms"], room_type=contract.std)["cells"]["S05"]), old + 1)
		self.assertEqual(D(find(m_s["rooms"], room_type=contract.std)["cells"]["S05"]), old)
		self.assertEqual(len(m_o["rooms"]), 15)
		self.assertTrue(all(len(r["cells"]) == 26 and all(r["cells"].values()) for r in m_o["rooms"]),
		                [r.get("errors") for r in m_o["rooms"]])
		self.assertEqual(len(answers[("matrix_12_parties", "overlay")]["party_cells"]), 12)
		for label in ("quote_3n_2a", "quote_14n_2a2c"):
			for how in ("overlay", "saved"):
				q = answers[(label, how)]
				self.assertTrue(q["sellable"], (label, how, q.get("reasons")))
		self.assertEqual(len(answers[("quote_14n_2a2c", "overlay")]["nights"]), 14)
		# the check ran the whole publish sweep (it is skipped when an error is found first)
		for how in ("overlay", "saved"):
			report = answers[("validate", how)]
			self.assertEqual([i for i in report["issues"] if i["level"] == "ERROR"], [], how)
		print(f"PERF issues {len(answers[('validate', 'overlay')]['issues'])}")
		self.assertEqual(len(answers[("apply_op_values_500", "overlay")]), api.ADJUST_VALUES_MAX)

		# the budgets (p95, development bench) with the CI factor
		budgeted = {"matrix overlay": "matrix", "matrix_1_party overlay": "matrix",
		            "quote_3n_2a overlay": "quote", "quote_14n_2a2c overlay": "quote"}
		calls = self.calls(contract, body)
		over = []
		for label, kind in budgeted.items():
			limit = BUDGET[kind] * 1000
			print(f"PERF budget {label}: p95 {results[label]['p95_ms']} ms, budget {limit:.0f} ms"
			      f" ({'within' if results[label]['p95_ms'] <= limit else 'OVER'})")
			if PROFILE or results[label]["p95_ms"] > limit:
				print(f"PERF profile {label}\n" + profile(RM, calls[label.split()[0]][0]))
			if results[label]["p95_ms"] > limit * CI_FACTOR:
				over.append(f"{label}: p95 {results[label]['p95_ms']} ms > {limit * CI_FACTOR:.0f} ms")
		self.assertEqual(over, [], f"over the budget × {CI_FACTOR}")


class TestDraftOverlayQueries(PerfCase):
	def test_query_count_does_not_scale_with_cells(self):
		"""Every call asks the same number of queries for 26 periods as for 13 (half the cells and
		half the period rules), at most one more per room for 15 rooms than for 8, a 14-night quote
		the same as a 3-night one, and ``apply_op_values`` the same for 500 prices as for 26."""
		full = PerfContract(self.f)
		payload = self.save(full)
		half = PerfContract(self.f, seasons=11, weekends=2)
		small = PerfContract(self.f, n_rooms=8)
		self.assertEqual((len(half.periods), len(small.rooms)), (13, 8))

		def keyed(data: dict) -> str:
			return as_json({**{f: payload[f] for f in api.VERSION_SETTINGS},
			                **{t: [{**r, "_key": f"{t}-k{i + 1}"} for i, r in enumerate(data[t])]
			                   for t in api.VERSION_TABLES}})

		counts: dict[str, dict[str, int]] = {}
		for name, contract in (("full", full), ("half_periods", half), ("fewer_rooms", small)):
			for label, (overlay, _saved) in self.calls(contract, keyed(contract.data)).items():
				if label.startswith("apply_op_values") and name != "full":
					continue
				counts.setdefault(f"{label} overlay", {})[name] = count_queries(RM, overlay)
		# the saved draft by name, saved at each size (the draft's own tables are read, whatever they hold)
		for name, contract in (("full", full), ("half_periods", half), ("fewer_rooms", small)):
			wapi.save_version(self.v, as_json(contract.data))
			for label, (_overlay, saved) in self.calls(contract, "").items():
				if saved:
					counts.setdefault(f"{label} saved", {})[name] = count_queries(RM, saved)
		for label, c in counts.items():
			print(f"PERF queries {label} {json.dumps(c)}")

		rooms_less = len(full.rooms) - len(small.rooms)
		for label, c in counts.items():
			if label.startswith("apply_op_values"):
				continue
			self.assertEqual(c["half_periods"], c["full"], f"{label}: queries grow with the periods")
			self.assertLessEqual(c["full"] - c["fewer_rooms"], rooms_less,
			                     f"{label}: more than one query per room")
			self.assertGreaterEqual(c["full"], c["fewer_rooms"], label)
		for how in ("overlay", "saved"):                          # no query per night
			self.assertEqual(counts[f"quote_14n_2a2c {how}"], counts[f"quote_3n_2a {how}"], how)
		self.assertEqual(counts["apply_op_values_26 overlay"]["full"], counts["apply_op_values_500 overlay"]["full"])
