"""OccupancyResolver — the adult/child formula engine (R-07, R-09, ADR-006, ADR-007, ADR-043).

"Occupancy" here means the PEOPLE in the room, not hotel occupancy %.

Slot model
----------
* PERSON basis: every occupant is a priced slot against the unit (base person rate):
  Adult 1 ×1.00, Adult 2 ×1.00, Adult 3 ×0.70, Child(8) 50 % …
* ROOM basis: the unit is the room price covering ``included_adults``; further adults
  and children are extra slots priced against ``unit / included_adults`` (or the full
  room price, per contract setting). Under-occupancy (e.g. single use = 80 %) is a
  COMBINATION rule.

Rule precedence (occupancy precedence v2, ``CASCADE``; most specific wins, INHERIT defers)
------------------------------------------------------------------------------------------
For one slot (an adult, a child, or the whole combination), rules are ranked by:

1. infant slots only: a rule naming the infant's age band beats every band-less rule,
   whatever its origin or qualifiers (G-31) — band-less rules still price an infant when
   no rule names its band;
2. origin: contract version > hotel + market policy > market policy > hotel policy >
   global policy (G-30, ``inherit``);
3. level: OVERRIDE > COMBINATION > PERIOD > ROOM > none;
4. qualifiers: period > room > exact combination (adults and children);
5. slot: position + band > position > band > neither (a position rule is an exception
   to a band default for a child who is not an infant).

Two matching rules with the same rank and a different value are a configuration error:
the offer is unsellable rather than one being picked silently (publish refuses them).

Payloads frozen before v2 (``LEGACY``) keep the ranking they were sold with:
level > period > room > exact combination > position > band, with the policy level
(GLOBAL/HOTEL/MARKET) standing in for the level of a rule without qualifiers.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
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


LEGACY, CASCADE = 1, 2   # ContractTerms.occupancy_precedence; a payload without the key → LEGACY


def specificity(rule: OccupancyRule, *, precedence: int = CASCADE, infant_slot: bool = False) -> tuple:
	"""Rank of a matching rule for one slot (higher wins); see the module docstring."""
	qual = (int(rule_level(rule)), rule.period is not None, rule.room_type is not None,
	        rule.adults is not None and rule.children is not None)
	slot = (rule.position is not None, rule.age_band is not None)
	if precedence == LEGACY:
		return (*qual, *slot)                                  # exactly the pre-v2 ranking
	return (infant_slot and rule.age_band is not None,         # G-31: the infant's band first
	        int(rule.base_level), rule.scope_weight,           # G-30: VERSION > H+M > M > H > GLOBAL
	        *qual, *slot)


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


def qualifiers_match(rule: OccupancyRule, room_type: str, period: str | None, adults: int, children: int) -> bool:
	"""The rule's room, period and combination qualifiers hold for this room, period (code;
	None: a period no period-specific rule names) and party size."""
	if rule.room_type is not None and rule.room_type != room_type:
		return False
	if rule.period is not None and rule.period != period:
		return False
	if rule.adults is not None and rule.adults != adults:
		return False
	if rule.children is not None and rule.children != children:
		return False
	return True


def slot_matches(rule: OccupancyRule, target: OccTarget, position: int | None, band: str | None) -> bool:
	"""The rule prices this slot: adult ``position``, child ``position`` in age band ``band``,
	or the whole combination (``position`` and ``band`` None). Qualifiers aside."""
	if rule.target != target:
		return False
	if target == OccTarget.COMBINATION:
		return True
	if rule.position is not None and rule.position != position:
		return False
	if target == OccTarget.ADULT:
		return rule.age_band is None
	return rule.age_band is None or rule.age_band == band


def _pick(candidates: list[OccupancyRule], what: str, key) -> tuple[OccupancyRule | None, tuple[RuleRef, ...]]:
	"""Most specific non-INHERIT rule by ``key``; INHERIT rules are recorded as skipped."""
	ordered = sorted(candidates, key=key, reverse=True)
	winner = None
	for i, r in enumerate(ordered):
		if r.op == Op.INHERIT:
			continue
		# ambiguity guard: another non-INHERIT rule with identical rank
		for other in ordered[i + 1:]:
			if key(other) != key(r):
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
	# running totals of the computation, reported for the Explain ladder (ADR-061 GAP-12), never
	# priced from: the base (ROOM basis: the room price) + the adult slots, then + the child slots
	# (before a whole-combination rule; ``total`` is after it)
	after_adults: Decimal = ZERO
	after_children: Decimal = ZERO


def check_capacity(spec: RoomSpec, party: Party, infants_count: bool) -> None:
	occupants = party.adults + party.child_count - (0 if infants_count else party.infants)
	if party.adults < max(1, spec.min_adults):
		raise Unsellable("MIN_ADULTS", f"{spec.name} needs at least {max(1, spec.min_adults)} adult(s)")
	if party.adults > spec.max_adults:
		# children above the oldest child band count as adults: say so, or "at most 2
		# adults" reads wrong to a family of 2 adults and 2 teenagers
		older = len(party.children_as_adults)
		note = f" (children above the child age bands count as adults: {older})" if older else ""
		raise Unsellable("MAX_ADULTS", f"{spec.name} sleeps at most {spec.max_adults} adults{note}",
		                 max_adults=spec.max_adults, children_as_adults=older)
	if party.child_count > spec.max_children:
		raise Unsellable("MAX_CHILDREN", f"{spec.name} sleeps at most {spec.max_children} children",
		                 max_children=spec.max_children)
	if occupants > spec.max_occupants:
		raise Unsellable("MAX_OCCUPANTS", f"{spec.name} sleeps at most {spec.max_occupants} guests",
		                 max_occupants=spec.max_occupants)


def price_occupancy(terms: ContractTerms, spec: RoomSpec, period: Period, unit: Decimal, party: Party,
                    *, night=None, explain: Explanation | None = None) -> OccupancyResult:
	room_type = spec.room_type
	rules = [r for r in terms.occupancy_rules
	         if qualifiers_match(r, room_type, period.code, party.adults, party.child_count)]
	slots: list[SlotPrice] = []
	precedence = terms.occupancy_precedence

	def rank(r: OccupancyRule) -> tuple:
		return specificity(r, precedence=precedence)

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
		cands = [r for r in rules if slot_matches(r, OccTarget.ADULT, pos, None)]
		winner, overridden = _pick(cands, f"adult {pos}", rank)
		if winner is None:
			winner, overridden = GLOBAL_ADULT_DEFAULT, overridden
		amount = apply_op(winner.op, winner.value, reference=slot_unit)
		ref = rule_ref(winner)
		slots.append(SlotPrice(SlotKind.ADULT, pos, f"Adult {pos}", amount, rule=ref))
		if explain is not None:
			explain.add("occupancy", "ADULT_SLOT", "Adult {pos} {op} {unit} = {amount}",
			            night=night, after=amount, rule=ref, overridden=overridden,
			            pos=pos, op=describe_op(winner.op, winner.value), unit=slot_unit, amount=amount)

	after_adults = base_total + sum((s.amount for s in slots), ZERO)     # reported only (GAP-12)

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
		cands = [r for r in rules if slot_matches(r, OccTarget.CHILD, child.position, child.band.code)]
		infant = child.band.is_infant
		winner, overridden = _pick(cands, f"child {child.position} band {child.band.code}",
		                           lambda r, infant=infant: specificity(r, precedence=precedence, infant_slot=infant))
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
	after_children = total                                               # reported only (GAP-12)

	# ── whole-combination rules ──
	combo_cands = [r for r in rules if slot_matches(r, OccTarget.COMBINATION, None, None)]
	combo, overridden = _pick(combo_cands, f"combination {party.adults}A+{party.child_count}C", rank)
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
	                       combination_rule=combo_ref, after_adults=after_adults, after_children=after_children)


def rules_taking_part(terms: ContractTerms, spec: RoomSpec, period: Period, unit: Decimal, party: Party) -> frozenset[str]:
	"""The ids of the occupancy rules that take part in pricing ``party`` in one night of ``period``:
	each slot's winner and the whole-combination rule, as ``price_occupancy`` resolves them. Also
	when the party cannot be priced: the rules resolved before the failure (which is all of them
	for a negative total) and the rules an ambiguity names. Whether a viewer who may not read some
	rules is told about the party is ``depends_on``'s answer (ADR-061, S16 re-review)."""
	ex = Explanation()
	named: tuple = ()
	try:
		price_occupancy(terms, spec, period, unit, party, explain=ex)
	except Unsellable as u:
		named = tuple(u.params.get("rules") or ())
	return frozenset({s.rule.rule_id for s in ex.steps if s.rule is not None} | set(named))


def depends_on(terms: ContractTerms, spec: RoomSpec, period: Period, unit: Decimal, party: Party,
               rules: frozenset[str]) -> bool:
	"""Whether what ``price_occupancy`` answers for ``party`` in ``period`` depends on the op or value
	of one of ``rules`` (rules a viewer may not read: a pricing policy's formulas, ADR-061): a total,
	or a negative total (NEGATIVE_OCCUPANCY_PRICE), one of them takes part in (``rules_taking_part``)
	or would take part in did it not defer (INHERIT: ``_defers_where_it_would_win``, S16 re-review
	3); a child no rule prices (NO_CHILD_RULE) where one of them defers for that child. Any other
	failure is decided by which rules exist and where, not by a hidden op or value: a child band
	without a rule, also when a hidden rule priced an adult before it, and an ambiguity (under
	``CASCADE`` a contract's own rule never ties with a policy's)."""
	if not rules:
		return False
	try:
		price_occupancy(terms, spec, period, unit, party)
	except Unsellable as u:
		if u.code == "NO_CHILD_RULE":
			position, band = u.params.get("position"), u.params.get("band")
			return any(r.rule_id in rules and r.op == Op.INHERIT
			           and qualifiers_match(r, spec.room_type, period.code, party.adults, party.child_count)
			           and slot_matches(r, OccTarget.CHILD, position, band) for r in terms.occupancy_rules)
		if u.code != "NEGATIVE_OCCUPANCY_PRICE":
			return False
	if rules_taking_part(terms, spec, period, unit, party) & rules:
		return True
	return _defers_where_it_would_win(terms, spec, period, unit, party, rules)


def _defers_where_it_would_win(terms: ContractTerms, spec: RoomSpec, period: Period, unit: Decimal, party: Party,
                               rules: frozenset[str]) -> bool:
	"""One of ``rules`` defers (INHERIT) for a slot of ``party`` where, did it not defer, it would
	take part (it outranks the slot's winner: e.g. a rule naming an infant band over a band-less
	rule, G-31): whether it defers decides which rule prices the slot, so the answer depends on
	its op (S16 re-review 3). Each such rule is tried with a pricing op in its place."""
	for r in terms.occupancy_rules:
		if r.rule_id not in rules or r.op != Op.INHERIT \
				or not qualifiers_match(r, spec.room_type, period.code, party.adults, party.child_count):
			continue
		probe = replace(terms, occupancy_rules=tuple(
			replace(x, op=Op.MULTIPLY, value=Decimal(1)) if x is r else x for x in terms.occupancy_rules))
		if r.rule_id in rules_taking_part(probe, spec, period, unit, party):
			return True
	return False
