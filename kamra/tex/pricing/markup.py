"""MarkupResolver: contract cost → selling price (R-14).

Markup rules vary by hotel, market, contract, room, stay period and channel.
Resolution per night:

* REPLACE rules: the most specific matching rule wins. Specificity weights are
  unique powers of two - property 1, market 2, contract 4, room 8, stay dates 16,
  channel 32 - so two different scopes can never tie; ``priority`` then rule id
  break ties between rules of the *same* scope (a configuration smell the admin UI
  flags).
* STACK rules: every matching STACK rule is applied on top of the REPLACE result, in
  ascending specificity - never hidden, always listed in the explanation.
* No matching rule → selling price = contract price (explicitly explained).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from kamra.tex.pricing.enums import Level, MarkupCombine, Op
from kamra.tex.pricing.explain import Explanation
from kamra.tex.pricing.model import MarkupRule, RuleRef, Unsellable
from kamra.tex.pricing.ops import apply_op, describe_op

_ALLOWED_OPS = (Op.ADJUST_PERCENT, Op.MULTIPLY, Op.ADD)


@dataclass(frozen=True, slots=True)
class MarkupScope:
	property: str
	market: str
	contract: str
	room_type: str
	channel: str
	currency: str   # contract currency (ADD amounts must be in it)


def weight(rule: MarkupRule) -> int:
	return ((1 if rule.property else 0) | (2 if rule.market else 0) | (4 if rule.contract else 0)
	        | (8 if rule.room_type else 0) | (16 if (rule.stay_from or rule.stay_to) else 0)
	        | (32 if rule.channel else 0))


def level(rule: MarkupRule) -> Level:
	if rule.stay_from or rule.stay_to:
		return Level.PERIOD
	if rule.room_type:
		return Level.ROOM
	if rule.contract:
		return Level.CONTRACT
	if rule.market:
		return Level.MARKET
	if rule.property:
		return Level.HOTEL
	return Level.GLOBAL


def ref(rule: MarkupRule) -> RuleRef:
	scope = [f"{k}={v}" for k, v in (("market", rule.market), ("contract", rule.contract),
	                                  ("room", rule.room_type), ("channel", rule.channel)) if v]
	if rule.stay_from or rule.stay_to:
		scope.append(f"stay {rule.stay_from or '…'}→{rule.stay_to or '…'}")
	label = rule.label or ("markup " + (" ".join(scope) or ("hotel" if rule.property else "global")))
	return RuleRef("markup", rule.rule_id, level(rule), rule.revision or "markup",
	               f"{label} {describe_op(rule.op, rule.value)}")


def matches(rule: MarkupRule, scope: MarkupScope, night: date) -> bool:
	if rule.property and rule.property != scope.property:
		return False
	if rule.market and rule.market != scope.market:
		return False
	if rule.contract and rule.contract != scope.contract:
		return False
	if rule.room_type and rule.room_type != scope.room_type:
		return False
	if rule.channel and rule.channel != scope.channel:
		return False
	if rule.stay_from and night < rule.stay_from:
		return False
	if rule.stay_to and night > rule.stay_to:
		return False
	return True


def resolve(rules: tuple[MarkupRule, ...], scope: MarkupScope, night: date
            ) -> tuple[MarkupRule | None, list[MarkupRule], list[MarkupRule]]:
	"""→ (winning REPLACE rule, STACK rules in order, overridden REPLACE rules)."""
	hits = [r for r in rules if matches(r, scope, night)]
	replace = sorted((r for r in hits if r.combine == MarkupCombine.REPLACE),
	                 key=lambda r: (weight(r), r.priority, r.rule_id), reverse=True)
	stack = sorted((r for r in hits if r.combine == MarkupCombine.STACK),
	               key=lambda r: (weight(r), r.priority, r.rule_id))
	winner = replace[0] if replace else None
	return winner, stack, replace[1:]


def _apply(rule: MarkupRule, amount: Decimal, scope: MarkupScope) -> Decimal:
	if rule.op not in _ALLOWED_OPS:
		raise Unsellable("MARKUP_OP_UNSUPPORTED", f"markup {rule.rule_id} uses unsupported {rule.op}")
	if rule.op == Op.ADD and rule.currency and rule.currency != scope.currency:
		raise Unsellable("MARKUP_CURRENCY", f"markup {rule.rule_id} is in {rule.currency}, "
		                 f"contract is in {scope.currency}")
	return apply_op(rule.op, rule.value, reference=amount, current=amount)


def apply_markup(rules: tuple[MarkupRule, ...], scope: MarkupScope, night: date, cost: Decimal,
                 *, explain: Explanation | None = None) -> Decimal:
	winner, stack, overridden = resolve(rules, scope, night)
	amount = cost
	if winner is None:
		if explain is not None:
			explain.add("markup", "NO_MARKUP", "no markup rule: selling = contract price", night=night,
			            before=cost, after=cost)
	else:
		amount = _apply(winner, cost, scope)
		if explain is not None:
			explain.add("markup", "MARKUP", "{label}: {cost} → {sell}", night=night, before=cost,
			            after=amount, rule=ref(winner), overridden=[ref(r) for r in overridden],
			            label=ref(winner).label, cost=cost, sell=amount)
	for r in stack:
		before = amount
		amount = _apply(r, amount, scope)
		if explain is not None:
			explain.add("markup", "MARKUP_STACK", "stacked {label}: {cost} → {sell}", night=night,
			            before=before, after=amount, rule=ref(r), label=ref(r).label, cost=before, sell=amount)
	if (winner is not None or stack) and amount <= 0 < cost:
		# a markup never sells a priced night for nothing (G-18)
		raise Unsellable("MARKUP_NO_PRICE", f"markup leaves no selling price on {night.isoformat()}")
	return amount
