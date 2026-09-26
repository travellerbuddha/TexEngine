"""The Pricing Workspace's single-use form switch, priced with the engine (ADR-061, final follow-up).

The ladder's "1 Adult (single use)" row is either the whole 1+0 combination or, with "Also when
children travel", Adult 1 of 1+*. The popover switches a row's rules from one form to the other
(frontend occupancy.ts applyOccRuleAs). A switch of form must not change what one adult without
children pays: the frontend refuses it (singleWriteRefusal) when another rule would decide that
price in the other form - an "Always wins" Adult 1 rule, a special combination's rule, a pricing
policy's rule the old form outranked, a relative rule carried into another amount.

The frontend cannot run the engine, so frontend/tests/unit/single-use-switch.test.ts writes each
scenario's occupancy rows to ``parity_data/single_use_switch.json`` (and fails if the switch no
longer writes them): the rows before, with the rule written without the switch (``stay``), after
the switch as the popover applies it (``after``) and, for a refused switch, as it would have been
written without the refusal (``unchecked``). Here every row set is priced by ``price_occupancy``
for one adult and no child in every room and period:

* a switch the frontend allows prices one adult as ``stay`` does (and as ``before`` does, for a
  switch of form only), everywhere;
* a switch it refuses writes nothing, and the unchecked switch would have changed a price (or made
  the party unsellable) somewhere - the refusal is not spurious.
"""

from __future__ import annotations

import json
import unittest
from datetime import date
from decimal import Decimal
from pathlib import Path

from kamra.tex.pricing import ages, inherit, occupancy, rooms
from kamra.tex.pricing.enums import Level, OccTarget, Op
from kamra.tex.pricing.model import AgeBand, OccupancyRule, Period, RoomRule, RoomSpec, Unsellable
from kamra.tex.tests.unit import fixtures as fx

FIXTURE = Path(__file__).parent / "parity_data" / "single_use_switch.json"
D = Decimal
_SCOPES = {"global": 0, "hotel": 1, "market": 2, "hotel+market": 3}


def _count(part: str) -> int | None:
	return None if part in ("*", "") else int(part)


def _combination(text: str) -> tuple[int | None, int | None]:
	"""'1+0' → (1, 0), '1+*' → (1, None), '' → (None, None), as contracts.parse_combination reads
	the canonical forms the workspace writes."""
	if not text:
		return None, None
	a, c = text.split("+", 1)
	return _count(a), _count(c)


def version_rules(rows: list[dict], label: str) -> tuple[OccupancyRule, ...]:
	"""TEX Occupancy Rule rows of a draft as contracts.occupancy_rules_of reads them."""
	out = []
	for i, r in enumerate(rows):
		adults, children = _combination(r["combination"])
		out.append(OccupancyRule(
			rule_id=f"{label}-{i}", target=OccTarget(r["target"]), op=Op(r["op"]),
			value=None if r["op"] == "INHERIT" else D(str(r["value"])),
			position=int(r["position"]) or None, age_band=(r["age_band"] or "").upper() or None,
			room_type=r["room_type"] or None, period=r["period_code"] or None,
			adults=adults, children=children, is_override=bool(r["is_override"]),
			base_level=Level.VERSION, source="version"))
	return tuple(out)


def policy_rules(served: list[dict]) -> tuple[OccupancyRule, ...]:
	"""Inherited rules as price_matrix serves them (policy:<id>/r<rev>/<scope>), with their real op
	and value (the frontend may have been served them hidden)."""
	out = []
	for r in served:
		weight = _SCOPES[r["source"].rsplit("/", 1)[1]]
		out.append(OccupancyRule(
			rule_id=r["rule_id"], target=OccTarget(r["target"]), op=Op(r["op"]),
			value=None if r["op"] == "INHERIT" else D(r["value"]), position=r["position"] or None,
			age_band=r["age_band"] or None, room_type=r["room_type"] or None, period=r["period"] or None,
			adults=r["adults"], children=r["children"], is_override=bool(r["is_override"]),
			base_level=inherit.level_for(weight), source=r["source"], scope_weight=weight))
	return tuple(out)


PERIODS = (
	Period("P1", "Apr", date(2027, 4, 1), date(2027, 4, 30)),
	Period("P2", "May", date(2027, 5, 1), date(2027, 5, 31)),
	Period("P3", "Jun", date(2027, 6, 1), date(2027, 6, 30)),
	Period("P4", "Jul", date(2027, 7, 1), date(2027, 7, 31)),
)
ROOMS = {code: RoomSpec(code, code, max_adults=3, max_children=2, max_occupants=4) for code in ("STD", "SUP", "DLX")}
ROOM_RULES = (
	RoomRule("R-STD-P1", "STD", "P1", Op.ABSOLUTE, D("70")),
	RoomRule("R-STD-P2", "STD", "P2", Op.ABSOLUTE, D("80")),
	RoomRule("R-STD-P3", "STD", "P3", Op.ABSOLUTE, D("100")),
	RoomRule("R-STD-P4", "STD", "P4", Op.ABSOLUTE, D("130")),
	RoomRule("R-SUP", "SUP", None, Op.MULTIPLY, D("1.15"), "STD"),
	RoomRule("R-DLX", "DLX", None, Op.MULTIPLY, D("1.35"), "STD"),
)
BANDS = (AgeBand("INF", "Infant", 0, 36, is_infant=True), AgeBand("CHD", "Child", 36, 144))


def single_use_prices(rows: list[dict], served: list[dict], label: str) -> dict[str, str]:
	"""What one adult without children pays, per room and period (or the engine's refusal)."""
	t = fx.terms(rooms=ROOMS, periods=PERIODS, room_rules=ROOM_RULES, age_bands=BANDS,
	             occupancy_rules=version_rules(rows, label) + policy_rules(served),
	             occupancy_precedence=occupancy.CASCADE)
	out = {}
	for room in ROOMS:
		for period in PERIODS:
			party = ages.classify_party(t, 1, (), period.start, date(2027, 1, 1))
			try:
				total = occupancy.price_occupancy(t, t.rooms[room], period, rooms.room_unit(t, room, period), party).total
				out[f"{room}|{period.code}"] = format(total.normalize(), "f")
			except Unsellable as e:
				out[f"{room}|{period.code}"] = f"unsellable:{e.code}"
	return out


class TestSingleUseSwitchWithTheEngine(unittest.TestCase):
	@classmethod
	def setUpClass(cls):
		cls.data = json.loads(FIXTURE.read_text())

	def test_the_fixture_covers_refused_and_allowed_switches(self):
		refusals = [s["refusal"] for s in self.data["scenarios"]]
		self.assertIn(None, refusals)
		self.assertIn("outranked", refusals)
		self.assertIn("relative", refusals)
		self.assertEqual(self.data["rooms"], list(ROOMS))
		self.assertEqual(self.data["periods"], [p.code for p in PERIODS])

	def test_an_allowed_switch_prices_one_adult_as_the_rule_written_without_it(self):
		for s in self.data["scenarios"]:
			if s["refusal"] is not None:
				continue
			with self.subTest(s["name"]):
				stay = single_use_prices(s["stay"], s["inherited"], "stay")
				after = single_use_prices(s["after"], s["inherited"], "after")
				self.assertEqual(after, stay)
				self.assertFalse(any(v.startswith("unsellable") for v in after.values()), after)
				if s["pure"]:
					self.assertEqual(after, single_use_prices(s["before"], s["inherited"], "before"))

	def test_a_refused_switch_writes_nothing_and_would_have_changed_a_price(self):
		for s in self.data["scenarios"]:
			if s["refusal"] is None:
				continue
			with self.subTest(s["name"]):
				self.assertEqual(s["after"], s["before"])
				stay = single_use_prices(s["stay"], s["inherited"], "stay")
				unchecked = single_use_prices(s["unchecked"], s["inherited"], "unchecked")
				changed = {k: (stay[k], unchecked[k]) for k in stay if stay[k] != unchecked[k]}
				self.assertTrue(changed, "the refused switch would have priced one adult the same everywhere")

	def test_the_reviewers_case_always_wins_adult_1_and_single_use_x0_8(self):
		# Adult 1 ×1 Always wins, single use ×0.8 (the whole 1+0): 1A+0C pays 0.8 of the unit; the
		# switch written anyway would make the Always-wins Adult 1 decide it (×1): refused
		s = next(x for x in self.data["scenarios"] if x["name"] == "an Always-wins Adult 1 and single use as the whole 1+0")
		self.assertEqual(s["refusal"], "outranked")
		self.assertEqual(single_use_prices(s["before"], [], "before")["STD|P1"], "56")
		self.assertEqual(single_use_prices(s["unchecked"], [], "unchecked")["STD|P1"], "70")


if __name__ == "__main__":
	unittest.main()
