"""OccupancyResolver — the adult/child formula engine (R-07, ADR-006, ADR-007).

"Occupancy" here means the PEOPLE in the room, not hotel occupancy %.

Slot model
----------
* PERSON basis: every occupant is a priced slot against the unit (base person rate):
  Adult 1 ×1.00, Adult 2 ×1.00, Adult 3 ×0.70, Child(8) 50 % …
* ROOM basis: the unit is the room price covering ``included_adults``; further adults
  and children are extra slots priced against ``unit / included_adults`` (or the full
  room price, per contract setting). Under-occupancy (e.g. single use = 80 %) is a
  COMBINATION rule.

Rule precedence (most specific wins; INHERIT defers):
    OVERRIDE > COMBINATION > PERIOD > ROOM > VERSION > MARKET > HOTEL > GLOBAL
with, inside one level: period-qualified > room-qualified > explicit position >
explicit age band. A rule that is still tied with another matching rule is a
configuration error and makes the offer unsellable rather than picking one silently.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from kamra.tex.money import ZERO
from kamra.tex.pricing.ages import Party, format_months
from kamra.tex.pricing.enums import Level, OccTarget, Op, PricingBasis, RoomBasisExtraUnit, SlotKind
from kamra.tex.pricing.explain import Explanation
from kamra.tex.pricing.model import ContractTerms, OccupancyRule, Period, RoomSpec, RuleRef, Unsellable
from kamra.tex.pricing.ops import apply_op, describe_op

GLOBAL_ADULT_DEFAULT = OccupancyRule(
	rule_id="GLOBAL:ADULT", target=OccTarget.ADULT, op=Op.MULTIPLY, value=Decimal(1),
	base_level=Level.GLOBAL, source="global-default", note="every adult pays the full unit")

_REPLACING_COMBINATION_OPS = (Op.ABSOLUTE, Op.FIXED, Op.MULTIPLY, Op.PERCENT_OF)


def rule_level(rule: OccupancyRule) -> Level:
	if rule.is_override:
		return Level.OVERRIDE
	if rule.adults is not None or rule.children is not None:
		return Level.COMBINATION
	if rule.period:
		return Level.PERIOD
	if rule.room_type:
		return Level.ROOM
	return rule.base_level


def specificity(rule: OccupancyRule) -> tuple:
	return (
		int(rule_level(rule)),
		rule.period is not None,
		rule.room_type is not None,
		rule.adults is not None and rule.children is not None,
		rule.position is not None,
		rule.age_band is not None,
	)


def rule_ref(rule: OccupancyRule) -> RuleRef:
	parts = [rule.target.value.title()]
	if rule.position:
		parts.append(str(rule.position))
	if rule.age_band:
		parts.append(f"[{rule.age_band}]")
	if rule.adults is not None or rule.children is not None:
		parts.append(f"@{rule.adults if rule.adults is not None else '*'}A+"
		             f"{rule.children if rule.children is not None else '*'}C")
	if rule.room_type:
		parts.append(f"room={rule.room_type}")
	if rule.period:
		parts.append(f"period={rule.period}")
	parts.append(describe_op(rule.op, rule.value))
	return RuleRef("occupancy_rule", rule.rule_id, rule_level(rule), rule.source, " ".join(parts))


def _qualifiers_match(rule: OccupancyRule, room_type: str, period: Period, party: Party) -> bool:
	if rule.room_type is not None and rule.room_type != room_type:
		return False
	if rule.period is not None and rule.period != period.code:
		return False
	if rule.adults is not None and rule.adults != party.adults:
		return False
	if rule.children is not None and rule.children != party.child_count:
		return False
	return True


def _pick(candidates: list[OccupancyRule], what: str) -> tuple[OccupancyRule | None, tuple[RuleRef, ...]]:
	"""Most specific non-INHERIT rule; INHERIT rules are recorded as skipped."""
	ordered = sorted(candidates, key=specificity, reverse=True)
	winner = None
	for i, r in enumerate(ordered):
		if r.op == Op.INHERIT:
			continue
		# ambiguity guard: another non-INHERIT rule with identical specificity
		for other in ordered[i + 1:]:
			if specificity(other) != specificity(r):
				break
			if other.op != Op.INHERIT and (other.op, other.value) != (r.op, r.value):
				raise Unsellable("AMBIGUOUS_OCCUPANCY_RULES",
				                 f"rules {r.rule_id} and {other.rule_id} both define {what} "
				                 "at the same precedence", rules=[r.rule_id, other.rule_id])
		winner = r
		break
	overridden = tuple(rule_ref(r) for r in ordered if r is not winner)
	return winner, overridden


@dataclass(frozen=True, slots=True)
class SlotPrice:
	kind: SlotKind
	position: int
	label: str
	amount: Decimal
	band: str | None = None
	included: bool = False
	rule: RuleRef | None = None


@dataclass(frozen=True, slots=True)
class OccupancyResult:
	total: Decimal
	unit: Decimal
	slot_unit: Decimal
	slots: tuple[SlotPrice, ...]
	combination_rule: RuleRef | None = None


def check_capacity(spec: RoomSpec, party: Party, infants_count: bool) -> None:
	occupants = party.adults + party.child_count - (0 if infants_count else party.infants)
	if party.adults < max(1, spec.min_adults):
		raise Unsellable("MIN_ADULTS", f"{spec.name} needs at least {max(1, spec.min_adults)} adult(s)")
	if party.adults > spec.max_adults:
		raise Unsellable("MAX_ADULTS", f"{spec.name} sleeps at most {spec.max_adults} adults",
		                 max_adults=spec.max_adults)
	if party.child_count > spec.max_children:
		raise Unsellable("MAX_CHILDREN", f"{spec.name} sleeps at most {spec.max_children} children",
		                 max_children=spec.max_children)
	if occupants > spec.max_occupants:
		raise Unsellable("MAX_OCCUPANTS", f"{spec.name} sleeps at most {spec.max_occupants} guests",
		                 max_occupants=spec.max_occupants)


def price_occupancy(terms: ContractTerms, spec: RoomSpec, period: Period, unit: Decimal, party: Party,
                    *, night=None, explain: Explanation | None = None) -> OccupancyResult:
	room_type = spec.room_type
	rules = [r for r in terms.occupancy_rules if _qualifiers_match(r, room_type, period, party)]
	slots: list[SlotPrice] = []

	if terms.basis == PricingBasis.PERSON:
		slot_unit = unit
		included_adults = 0
		base_total = ZERO
	else:
		included_adults = max(1, spec.included_adults)
		slot_unit = unit if terms.room_basis_extra_unit == RoomBasisExtraUnit.ROOM_PRICE \
			else unit / Decimal(included_adults)
		base_total = unit
		if explain is not None:
			explain.add("occupancy", "ROOM_BASIS", "room price {unit} covers {included} adult(s)",
			            night=night, after=unit, unit=unit, included=included_adults)

	# ── adults ──
	for pos in range(1, party.adults + 1):
		if pos <= included_adults:
			slots.append(SlotPrice(SlotKind.ADULT, pos, f"Adult {pos}", ZERO, included=True))
			continue
		cands = [r for r in rules if r.target == OccTarget.ADULT and r.age_band is None
		         and (r.position is None or r.position == pos)]
		winner, overridden = _pick(cands, f"adult {pos}")
		if winner is None:
			winner, overridden = GLOBAL_ADULT_DEFAULT, overridden
		amount = apply_op(winner.op, winner.value, reference=slot_unit)
		ref = rule_ref(winner)
		slots.append(SlotPrice(SlotKind.ADULT, pos, f"Adult {pos}", amount, rule=ref))
		if explain is not None:
			explain.add("occupancy", "ADULT_SLOT", "Adult {pos} {op} {unit} = {amount}",
			            night=night, after=amount, rule=ref, overridden=overridden,
			            pos=pos, op=describe_op(winner.op, winner.value), unit=slot_unit, amount=amount)

	# ── children ──
	fill = max(0, included_adults - party.adults) if terms.basis == PricingBasis.ROOM \
		and terms.room_basis_children_fill_included else 0
	for child in party.children:
		label = f"Child {child.position} ({format_months(child.months)}, {child.band.label or child.band.code})"
		if fill > 0:
			fill -= 1
			slots.append(SlotPrice(SlotKind.CHILD, child.position, label, ZERO, band=child.band.code,
			                       included=True))
			if explain is not None:
				explain.add("occupancy", "CHILD_INCLUDED", "{label} fills an included room place",
				            night=night, label=label)
			continue
		cands = [r for r in rules if r.target == OccTarget.CHILD
		         and (r.position is None or r.position == child.position)
		         and (r.age_band is None or r.age_band == child.band.code)]
		winner, overridden = _pick(cands, f"child {child.position} band {child.band.code}")
		if winner is None:
			raise Unsellable("NO_CHILD_RULE",
			                 f"no occupancy rule for child {child.position} in band {child.band.code} "
			                 f"({party.adults}A+{party.child_count}C)",
			                 band=child.band.code, position=child.position)
		amount = apply_op(winner.op, winner.value, reference=slot_unit)
		ref = rule_ref(winner)
		slots.append(SlotPrice(SlotKind.CHILD, child.position, label, amount, band=child.band.code, rule=ref))
		if explain is not None:
			explain.add("occupancy", "CHILD_SLOT", "{label} {op} {unit} = {amount}",
			            night=night, after=amount, rule=ref, overridden=overridden,
			            label=label, op=describe_op(winner.op, winner.value), unit=slot_unit, amount=amount)

	total = base_total + sum((s.amount for s in slots), ZERO)

	# ── whole-combination rules ──
	combo_cands = [r for r in rules if r.target == OccTarget.COMBINATION]
	combo, overridden = _pick(combo_cands, f"combination {party.adults}A+{party.child_count}C")
	combo_ref = None
	if combo is not None:
		combo_ref = rule_ref(combo)
		before = total
		if combo.op in _REPLACING_COMBINATION_OPS:
			total = apply_op(combo.op, combo.value, reference=unit)
		else:
			total = apply_op(combo.op, combo.value, reference=before, current=before)
		if explain is not None:
			explain.add("occupancy", "COMBINATION_RULE",
			            "combination {adults}A+{children}C {op} → {total}",
			            night=night, before=before, after=total, rule=combo_ref, overridden=overridden,
			            adults=party.adults, children=party.child_count,
			            op=describe_op(combo.op, combo.value), total=total)
	elif explain is not None:
		explain.add("occupancy", "OCCUPANCY_TOTAL", "occupancy {adults}A+{children}C = {total}",
		            night=night, after=total, adults=party.adults, children=party.child_count, total=total)

	if total < ZERO:
		raise Unsellable("NEGATIVE_OCCUPANCY_PRICE", "occupancy rules produce a negative price")
	return OccupancyResult(total=total, unit=unit, slot_unit=slot_unit, slots=tuple(slots),
	                       combination_rule=combo_ref)
