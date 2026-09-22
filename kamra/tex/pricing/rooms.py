"""StayPeriodResolver and RoomPricingResolver (R-10, R-11)."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from kamra.tex.pricing.enums import Level, Op
from kamra.tex.pricing.explain import Explanation
from kamra.tex.pricing.model import ContractTerms, Period, RoomRule, RuleRef, Unsellable
from kamra.tex.pricing.ops import apply_op, describe_op

MAX_DERIVATION_DEPTH = 8


def period_for(terms: ContractTerms, night: date) -> Period | None:
	"""The stay period pricing ``night``.

	Overlaps are rejected when a version is published unless they are resolvable:
	a weekday-limited period beats an every-day period, then higher priority, then
	the shorter range, then the period code - fully deterministic.
	"""
	candidates = [p for p in terms.periods if p.covers(night)]
	if not candidates:
		return None
	return max(candidates, key=lambda p: (
		p.weekdays is not None, p.priority, -(p.end - p.start).days, p.code))


def _rule_ref(rule: RoomRule) -> RuleRef:
	level = Level.PERIOD if rule.period else Level.ROOM
	return RuleRef("room_rule", rule.rule_id, level, "version",
	               f"{rule.room_type}{' @' + rule.period if rule.period else ''} {describe_op(rule.op, rule.value)}")


def _candidates(terms: ContractTerms, room_type: str, period: Period) -> list[RoomRule]:
	"""Rules for this room, most specific first (period-specific before generic)."""
	specific = [r for r in terms.room_rules if r.room_type == room_type and r.period == period.code]
	generic = [r for r in terms.room_rules if r.room_type == room_type and r.period is None]
	return specific + generic


def room_unit(terms: ContractTerms, room_type: str, period: Period, *, night: date | None = None,
              explain: Explanation | None = None, _depth: int = 0, _chain: tuple[str, ...] = ()) -> Decimal:
	"""The priced unit of ``room_type`` in ``period``: the base person rate (PERSON
	basis) or the room price at included occupancy (ROOM basis)."""
	if room_type in _chain or _depth > MAX_DERIVATION_DEPTH:
		raise Unsellable("ROOM_DERIVATION_CYCLE",
		                 f"room price derivation loops: {' → '.join((*_chain, room_type))}")
	rules = _candidates(terms, room_type, period)
	skipped: list[RuleRef] = []
	winner: RoomRule | None = None
	for r in rules:
		if r.op == Op.INHERIT:
			skipped.append(_rule_ref(r))
			continue
		winner = r
		break
	if winner is None:
		raise Unsellable("NO_ROOM_PRICE",
		                 f"no price for {room_type} in period {period.code}",
		                 room_type=room_type, period=period.code)
	overridden = tuple(_rule_ref(r) for r in rules if r is not winner and r.op != Op.INHERIT) + tuple(skipped)

	if winner.op == Op.ABSOLUTE or winner.op == Op.FIXED:
		unit = Decimal(winner.value)
		if explain is not None:
			explain.add("room", "ROOM_ABSOLUTE", "{room} in {period}: price {unit}",
			            night=night, after=unit, rule=_rule_ref(winner), overridden=overridden,
			            room=room_type, period=period.code, unit=unit)
		return unit

	if not winner.base_room_type:
		raise Unsellable("ROOM_DERIVATION_NO_BASE",
		                 f"rule {winner.rule_id} derives {room_type} but names no base room")
	base_unit = room_unit(terms, winner.base_room_type, period, night=night, explain=explain,
	                      _depth=_depth + 1, _chain=(*_chain, room_type))
	unit = apply_op(winner.op, winner.value, reference=base_unit)
	if explain is not None:
		explain.add("room", "ROOM_DERIVED", "{room} = {base} {op} → {unit}",
		            night=night, before=base_unit, after=unit, rule=_rule_ref(winner),
		            overridden=overridden, room=room_type, base=winner.base_room_type,
		            op=describe_op(winner.op, winner.value), unit=unit)
	return unit
