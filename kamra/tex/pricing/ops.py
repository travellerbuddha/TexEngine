"""Arithmetic of rule operations (ADR-006). Pure Decimal maths."""

from __future__ import annotations

from decimal import Decimal

from kamra.tex.money import HUNDRED, ONE, ZERO, D, display, display_pct
from kamra.tex.pricing.enums import Op
from kamra.tex.pricing.model import PricingError


def apply_op(op: Op, value: Decimal | None, *, reference: Decimal, current: Decimal | None = None) -> Decimal:
	"""Apply an operation.

	``reference`` is what shares/multipliers are taken of (e.g. the base person
	rate, the base room price). ``current`` is the running amount that
	adjustments modify; it defaults to ``reference``.
	"""
	if op == Op.INHERIT:
		raise PricingError("INHERIT has no arithmetic; resolve it to a concrete rule first")
	cur = reference if current is None else current
	v = D(value)
	if op in (Op.ABSOLUTE, Op.FIXED):
		return v
	if op == Op.MULTIPLY:
		return reference * v
	if op == Op.PERCENT_OF:
		return reference * v / HUNDRED
	if op == Op.ADJUST_PERCENT:
		return cur * (ONE + v / HUNDRED)
	if op == Op.ADD:
		return cur + v
	if op == Op.SUBTRACT:
		return cur - v
	raise PricingError(f"unknown operation {op!r}")


def describe_op(op: Op, value: Decimal | None) -> str:
	v = D(value)
	s = display(v)
	match op:
		case Op.ABSOLUTE | Op.FIXED:
			return f"= {s}"
		case Op.MULTIPLY:
			return f"× {s}"
		case Op.PERCENT_OF:
			return f"{display_pct(v)}% of"
		case Op.ADJUST_PERCENT:
			return f"{'+' if v >= ZERO else ''}{display_pct(v)}%"
		case Op.ADD:
			return f"+ {s}"
		case Op.SUBTRACT:
			return f"− {s}"
		case Op.INHERIT:
			return "inherit"
	return str(op)
