"""An ARI grid rate edit as a plan of period edits (O-9, G-47, ADR-069). Pure: no frappe.

The edited nights are the range's nights on the chosen weekdays (every night without any). They
fall into *parts*: the longest runs of consecutive edited nights one period prices
(``rooms.period_for``); a night no period prices is refused (``NO_PERIOD``). Then per part:

* in place: when its period prices edited nights only, the selected rooms' own rules there are
  replaced by the new ABSOLUTE unit (a second edit of a weekend clone edits that clone; the draft
  does not gain a period);
* otherwise ONE clone over the part's first..last night, on the chosen weekdays the period has,
  with a priority above its period's (+100, as the grid always did) and above every period of its
  kind whose dates and days it overlaps, so it never ties one (validate's ``PERIOD_OVERLAP``). The
  clone copies the period's rules as the grid always did (the unselected rooms' own rules, the
  occupancy rules and the boards) and gives the selected rooms their new ABSOLUTE unit.

A clone covers the part's nights and no other: a night between its first and last that is on its
weekdays is an edited night of the same run, so its period priced it. A derived room that is not
selected follows its base; a room with a rule of its own keeps it. The new unit is the current one
changed once by the op (``matrix.adjust_amount``: rounded to the contract currency, never below 0).

``apply`` writes a plan into terms (the unit tests'); the grid writes the same into the draft
(``commercial.grid``). ``added_errors`` says which ERRORs an edit adds: the grid refuses those.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import date, timedelta
from decimal import Decimal

from kamra.tex.money import D, quantize
from kamra.tex.pricing import matrix, rooms
from kamra.tex.pricing.enums import Op
from kamra.tex.pricing.model import ContractTerms, Period, PricingError, RoomRule
from kamra.tex.pricing.validate import Issue

CLONE_STEP = 100          # a clone's priority over its period's, at least (as the grid always did)
RULE_IDS = ("rule_id", "rule_ids")   # which rows an issue names: never part of whether it is new


class RateSplitError(PricingError):
	"""The edit cannot be planned. ``code``: ``NO_PERIOD`` (``night`` has no period), ``NO_NIGHTS``
	(no night of the range is on the chosen weekdays) or ``NEGATIVE`` (``room_type``'s new unit is
	below zero)."""

	def __init__(self, code: str, **ref):
		super().__init__(code)
		self.code = code
		self.ref = ref


@dataclass(frozen=True, slots=True)
class Unit:
	room_type: str
	current: Decimal      # the unit before, rounded to the contract currency (the audit's)
	new: Decimal          # the unit after, rounded to the contract currency


@dataclass(frozen=True, slots=True)
class Step:
	source: Period                          # the period that priced the part's nights
	clone: bool                             # False: ``source`` itself is edited
	start: date                             # the clone's first night (in place: the source's start)
	end: date
	weekdays: frozenset[int] | None
	priority: int
	units: tuple[Unit, ...]                 # the selected rooms, in the order asked
	parts: tuple[tuple[date, date], ...]    # first and last edited night of each part it edits


def edited_nights(start: date, end: date, weekdays) -> list[date]:
	mask = frozenset(weekdays) if weekdays else None
	out, d = [], start
	while d <= end:
		if mask is None or d.weekday() in mask:
			out.append(d)
		d += timedelta(days=1)
	return out


def plan(terms: ContractTerms, start: date, end: date, weekdays, room_types, op: Op | str, value) -> tuple[Step, ...]:
	mask = frozenset(weekdays) if weekdays else None
	nights = edited_nights(start, end, mask)
	if not nights:
		raise RateSplitError("NO_NIGHTS")
	parts: list[tuple[Period, list[date]]] = []
	for n in nights:
		p = rooms.period_for(terms, n)
		if p is None:
			raise RateSplitError("NO_PERIOD", night=n)
		if parts and parts[-1][0].code == p.code:
			parts[-1][1].append(n)
		else:
			parts.append((p, [n]))
	edited = frozenset(nights)
	selected = tuple(dict.fromkeys(rt for rt in room_types if rt in terms.rooms))
	steps: list[Step] = []
	in_place: dict[str, int] = {}          # period code → its step (edited once, whatever its parts)
	for p, run in parts:
		part = (run[0], run[-1])
		if p.code in in_place:
			i = in_place[p.code]
			steps[i] = replace(steps[i], parts=(*steps[i].parts, part))
			continue
		units = _units(terms, p, selected, Op(op), value)
		if _prices_only(terms, p, edited):
			in_place[p.code] = len(steps)
			steps.append(Step(p, False, p.start, p.end, p.weekdays, p.priority, units, (part,)))
			continue
		days = (mask & p.weekdays) if (mask and p.weekdays) else (mask or p.weekdays)
		steps.append(Step(p, True, run[0], run[-1], days, _clone_priority(terms, p, run[0], run[-1], days), units,
		                  (part,)))
	return tuple(steps)


def _prices_only(terms: ContractTerms, p: Period, edited: frozenset[date]) -> bool:
	"""Whether ``p`` prices no night but an edited one."""
	d = p.start
	while d <= p.end:
		if d not in edited and p.covers(d) and rooms.period_for(terms, d).code == p.code:
			return False
		d += timedelta(days=1)
	return True


def _clone_priority(terms: ContractTerms, p: Period, first: date, last: date, days: frozenset[int] | None) -> int:
	"""Above ``p`` and above every period of the clone's kind (weekday-limited or not) whose dates
	and days it overlaps: the pairs validate would report as PERIOD_OVERLAP at an equal priority."""
	out = p.priority + CLONE_STEP
	for q in terms.periods:
		if (q.weekdays is None) != (days is None) or not (q.start <= last and first <= q.end):
			continue
		if days is not None and not (days & q.weekdays):
			continue
		out = max(out, q.priority + 1)
	return out


def _units(terms: ContractTerms, p: Period, selected: tuple[str, ...], op: Op, value) -> tuple[Unit, ...]:
	out = []
	for rt in selected:
		current = rooms.room_unit(terms, rt, p)
		try:
			new = matrix.adjust_amount(current, op, D(value), terms.currency)
		except PricingError as e:
			if str(e) != "NEGATIVE":
				raise
			raise RateSplitError("NEGATIVE", room_type=rt) from e
		out.append(Unit(rt, quantize(current, terms.currency), new))
	return tuple(out)


def clone_code(step: Step, idx: int, taken) -> str:
	"""The clone's period code, as the grid always named them (then ``_2``… while taken)."""
	base = f"G{step.start:%y%m%d}{step.end:%m%d}{'W' if step.weekdays else ''}{idx}"
	code, n = base, 2
	while code in taken:
		code, n = f"{base}_{n}", n + 1
	return code


def clone_name(step: Step) -> str:
	return f"{step.source.name} · edit {step.start:%d %b}–{step.end:%d %b}"


def apply(terms: ContractTerms, steps, codes=None) -> tuple[ContractTerms, dict[str, str]]:
	"""``terms`` with the plan written in, and each clone's code → its period's code. ``codes``:
	the clones' codes, in order (default ``clone_code``)."""
	periods, room_rules = list(terms.periods), list(terms.room_rules)
	occupancy, boards = list(terms.occupancy_rules), list(terms.boards)
	taken, alias, clones = {p.code for p in periods}, {}, iter(codes or ())
	for idx, s in enumerate(steps):
		src, selected = s.source.code, {u.room_type for u in s.units}
		if s.clone:
			code = next(clones, None) or clone_code(s, idx, taken)
			taken.add(code)
			alias[code] = src
			periods.append(Period(code, clone_name(s), s.start, s.end, s.weekdays, s.source.adjustment_op,
			                      s.source.adjustment_value, s.priority))
			room_rules += [replace(r, rule_id=f"{r.rule_id}@{code}", period=code) for r in terms.room_rules
			               if r.period == src and r.room_type not in selected]
			occupancy += [replace(r, rule_id=f"{r.rule_id}@{code}", period=code) for r in terms.occupancy_rules
			              if r.period == src]
			boards += [replace(b, rule_id=f"{b.rule_id}@{code}", period=code) for b in terms.boards if b.period == src]
		else:
			code = src
			room_rules = [r for r in room_rules if not (r.period == code and r.room_type in selected)]
		room_rules += [RoomRule(f"{u.room_type}@{code}", u.room_type, code, Op.ABSOLUTE, u.new) for u in s.units]
	return replace(terms, periods=tuple(periods), room_rules=tuple(room_rules), occupancy_rules=tuple(occupancy),
	               boards=tuple(boards)), alias


def _error_key(issue: Issue, alias: dict[str, str]) -> tuple:
	"""What an ERROR is about, a clone's as its period's: the same issue before and after an edit
	whatever rows or clone it names now."""
	if not issue.ref:
		return issue.code, issue.message
	ref = {k: alias.get(v, v) if k in ("period", "other_period") else v for k, v in issue.ref.items()
	       if k not in RULE_IDS}
	return issue.code, tuple(sorted((k, str(v)) for k, v in ref.items()))


def added_errors(before: list[Issue], after: list[Issue], alias: dict[str, str]) -> list[Issue]:
	"""The ERRORs of ``after`` that ``before`` did not have (``alias``: clone code → its period's)."""
	had = {_error_key(i, {}) for i in before if i.level == "ERROR"}
	return [i for i in after if i.level == "ERROR" and _error_key(i, alias) not in had]
