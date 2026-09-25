"""Publish-time validation of contract terms.

A version can only be published with zero ERRORs. WARNINGs (e.g. an occupancy
combination with no child rule, which will simply be unsellable) are shown to the
contract manager before publishing.

Occupancy rules (ADR-043): two rules that tie for a slot - same precedence, different
values - are an ERROR (``OCC_AMBIGUOUS``; the offer would be unsellable) wherever the
tie decides a price: a slot that a higher-ranked rule prices is no tie. A rule the
contract's own version names wrongly (unknown band, room or period, an adult rule with
a band) is an ERROR; a rule inherited from a pricing policy that this contract cannot
use simply never applies and is a WARNING (``OCC_INHERITED_*_UNUSED``). A pricing
policy is checked on its own before it goes live (``policy_issues``).

Board rules (ADR-061, GAP-5) are checked like room rules: a rule naming a room or period the
contract does not have, and two rules of one board for the same room and period (the engine
would settle them by row name), are ERRORs.

Each issue may carry a ``ref`` (ADR-061 D9, GAP-4): what it is about - the rule(s), room,
period, age band(s), party and board - so the workspace can mark the cell or row and show band
labels for the codes in the message. Codes and messages do not depend on it.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import date

from kamra.tex.money import ZERO, D
from kamra.tex.pricing import ages, occupancy, rooms
from kamra.tex.pricing.ages import ChildSlot, Party
from kamra.tex.pricing.enums import Level, OccTarget, Op, PricingBasis, PromoValueType
from kamra.tex.pricing.model import (
	AgeBand,
	ContractTerms,
	OccupancyRule,
	Period,
	PricingError,
	RoomSpec,
	Unsellable,
)


@dataclass(frozen=True, slots=True)
class Issue:
	level: str   # ERROR / WARNING
	code: str
	message: str
	# what the issue is about (ADR-061 D9): rule_id, rule_ids (every rule an issue about several
	# names, rule_id the first), room_type, period, other_period, age_band, age_bands (every band
	# code of the contract, for AGE_BANDS), adults, children (the party), board. Only the parts the
	# issue has; None when it is about the contract as a whole. Not part of the issue's identity.
	ref: dict | None = field(default=None, compare=False)

	def to_dict(self) -> dict:
		out = {"level": self.level, "code": self.code, "message": self.message}
		if self.ref:
			out["ref"] = dict(self.ref)
		return out


def _ref(**parts) -> dict | None:
	"""The parts that are known (0 adults or children is known), or None."""
	return {k: v for k, v in parts.items() if v is not None} or None


def _err(code, msg, **ref):
	return Issue("ERROR", code, msg, _ref(**ref))


def _warn(code, msg, **ref):
	return Issue("WARNING", code, msg, _ref(**ref))


def _rule_ref(r: OccupancyRule) -> dict:
	"""An occupancy rule's own scope."""
	return dict(rule_id=r.rule_id, room_type=r.room_type, period=r.period, age_band=r.age_band, adults=r.adults,
	            children=r.children)


def _cell_rule(t: ContractTerms, room_type: str, period: Period) -> str | None:
	"""The rule that prices ``room_type`` in ``period``: the one ``rooms.room_unit`` takes."""
	return next((r.rule_id for r in rooms._candidates(t, room_type, period) if r.op != Op.INHERIT), None)


def validate_terms(t: ContractTerms, *, sweep_combinations: bool = True, max_warnings: int = 200,
                   hidden: frozenset[str] = frozenset()) -> list[Issue]:
	"""The issues of ``t``. ``hidden``: ids of occupancy rules the viewer may not read (a pricing
	policy's formulas, which are cost: ADR-061, S16 review). No issue whose presence depends on one
	of their ops or values is reported then: OCC_POLICY_OVERRIDE_OUTRANKED for a hidden override,
	and the sweep's negative total of a party one of them takes part in or missing child rule where
	one of them defers (``occupancy.depends_on``). A child band without any rule and an ambiguity
	are reported, whoever priced the adults (S16 re-review). ``visible_issues`` does the same to a
	stored report."""
	issues: list[Issue] = []
	if len(t.currency) != 3:
		issues.append(_err("CURRENCY", f"currency {t.currency!r} is not an ISO code"))
	if not t.rooms:
		issues.append(_err("NO_ROOMS", "the contract sells no rooms"))
	if not t.periods:
		issues.append(_err("NO_PERIODS", "the contract has no stay periods"))
	if t.sale_from and t.sale_to and t.sale_from > t.sale_to:
		issues.append(_err("SALE_WINDOW", "sale window ends before it starts"))
	if t.stay_from and t.stay_to and t.stay_from > t.stay_to:
		issues.append(_err("STAY_WINDOW", "stay window ends before it starts"))

	for r in t.rooms.values():
		if r.max_adults < 1 or r.max_occupants < 1:
			issues.append(_err("ROOM_CAPACITY", f"{r.room_type}: capacity must allow at least one adult",
			                   room_type=r.room_type))
		if r.max_occupants < r.max_adults:
			issues.append(_err("ROOM_CAPACITY", f"{r.room_type}: max occupants below max adults", room_type=r.room_type))
		if t.basis == PricingBasis.ROOM and not (1 <= r.included_adults <= r.max_adults):
			issues.append(_err("INCLUDED_ADULTS", f"{r.room_type}: included adults must be 1..max adults",
			                   room_type=r.room_type))

	# periods
	codes = [p.code for p in t.periods]
	for c in sorted({c for c in codes if codes.count(c) > 1}):
		issues.append(_err("PERIOD_DUPLICATE", f"period code {c} is used twice", period=c))
	for p in t.periods:
		if p.start > p.end:
			issues.append(_err("PERIOD_RANGE", f"period {p.code} ends before it starts", period=p.code))
	for i, a in enumerate(t.periods):
		for b in t.periods[i + 1:]:
			if a.start <= b.end and b.start <= a.end:
				same_kind = (a.weekdays is None) == (b.weekdays is None)
				days_overlap = a.weekdays is None or b.weekdays is None or bool(a.weekdays & b.weekdays)
				if same_kind and days_overlap and a.priority == b.priority:
					issues.append(_err("PERIOD_OVERLAP",
					                   f"periods {a.code} and {b.code} overlap with equal priority",
					                   period=a.code, other_period=b.code))

	# room rules
	keys = [(r.room_type, r.period) for r in t.room_rules]
	for k in sorted({k for k in keys if keys.count(k) > 1}, key=str):
		ids = [r.rule_id for r in t.room_rules if (r.room_type, r.period) == k]
		issues.append(_err("ROOM_RULE_DUPLICATE", f"room {k[0]} has two rules for period {k[1] or 'all'}",
		                   rule_id=ids[0], rule_ids=ids, room_type=k[0], period=k[1]))
	for r in t.room_rules:
		where = dict(rule_id=r.rule_id, room_type=r.room_type, period=r.period)
		if r.room_type not in t.rooms:
			issues.append(_err("ROOM_RULE_UNKNOWN_ROOM", f"rule {r.rule_id} prices unknown room {r.room_type}", **where))
		if r.period and r.period not in codes:
			issues.append(_err("ROOM_RULE_UNKNOWN_PERIOD", f"rule {r.rule_id} names unknown period {r.period}",
			                   **where))
		if r.op not in (Op.ABSOLUTE, Op.FIXED, Op.INHERIT) and not r.base_room_type:
			issues.append(_err("ROOM_RULE_NO_BASE", f"rule {r.rule_id} derives a price but names no base room",
			                   **where))
	for p in t.periods:
		for rt in sorted(t.rooms):
			try:
				unit = rooms.room_unit(t, rt, p)
				if unit < ZERO:
					issues.append(_err("ROOM_NEGATIVE", f"{rt} prices below zero in {p.code}",
					                   room_type=rt, period=p.code, rule_id=_cell_rule(t, rt, p)))
			except Unsellable as u:
				issues.append(_err(u.code, f"{rt} / {p.code}: {u.message}",
				                   room_type=rt, period=p.code, rule_id=_cell_rule(t, rt, p)))

	# age bands, on the month scale pricing uses: a gap leaves a child unsellable (G-52)
	for problem, involved in ages.band_findings(t.age_bands):
		# every code: the message names bands by code, and the workspace shows their labels
		issues.append(_err("AGE_BANDS", problem, age_bands=[b.code for b in t.age_bands],
		                   age_band=involved[0] if len(involved) == 1 else None))
	young = ages.youngest_uncovered(t.age_bands)
	if young and any(r.max_children > 0 for r in t.rooms.values()):
		issues.append(_warn("AGE_BANDS_MIN_AGE", f"no age band covers {ages.months_span(*young)}: children that "
		                    "young cannot be booked under this contract"))
	band_codes = {b.code for b in t.age_bands}
	if not t.age_bands and any(r.max_children > 0 for r in t.rooms.values()):
		issues.append(_warn("NO_AGE_BANDS", "no child age bands (neither the version nor a pricing policy defines "
		                    "any): " + ("every child is priced as an adult" if t.children_over_max_as_adults
		                                else "children cannot be booked")))

	# occupancy rules
	for r in t.occupancy_rules:
		for unknown, code, what in ((r.age_band and r.age_band not in band_codes, "BAND", f"age band {r.age_band}"),
		                            (r.room_type and r.room_type not in t.rooms, "ROOM", f"room {r.room_type}"),
		                            (r.period and r.period not in codes, "PERIOD", f"period {r.period}")):
			if not unknown:
				continue
			if r.base_level >= Level.CONTRACT:
				issues.append(_err(f"OCC_UNKNOWN_{code}", f"rule {r.rule_id} names unknown {what}", **_rule_ref(r)))
			else:   # inherited from a pricing policy: it simply never applies to this contract
				issues.append(_warn(f"OCC_INHERITED_{code}_UNUSED",
				                    f"pricing-policy rule {r.rule_id} ({r.source}) names {what}, which this "
				                    "contract does not have; it never applies here", **_rule_ref(r)))
		if r.target == OccTarget.COMBINATION and r.adults is None and r.children is None:
			# inherited too: it would reprice every combination of the contract
			issues.append(_err("OCC_COMBINATION_QUALIFIER", f"combination rule {r.rule_id} needs adults/children",
			                   **_rule_ref(r)))
		if r.target == OccTarget.ADULT and r.age_band:
			if r.base_level >= Level.CONTRACT:
				issues.append(_err("OCC_ADULT_BAND", f"adult rule {r.rule_id} cannot name an age band", **_rule_ref(r)))
			else:   # the runtime never applies it
				issues.append(_warn("OCC_INHERITED_ADULT_BAND_UNUSED",
				                    f"pricing-policy adult rule {r.rule_id} ({r.source}) names age band "
				                    f"{r.age_band}; an adult rule has no band, so it never applies", **_rule_ref(r)))
		if r.op != Op.INHERIT and r.value is None:
			issues.append(_err("OCC_NO_VALUE", f"rule {r.rule_id} has no value", **_rule_ref(r)))
	# twin rules of the version are an error; twins of one pricing policy only where they decide a price
	twins = _duplicates([r for r in t.occupancy_rules if r.base_level >= Level.CONTRACT])
	issues.extend(_twin_issue(sig, ids) for sig, ids in twins.items())
	for a, b, where, slot in _ambiguous_pairs(t, reported=twins):
		issues.append(_err("OCC_AMBIGUOUS", f"rules {a.rule_id} and {b.rule_id} both price {where} at the same "
		                   "precedence with different values; make one more specific or remove one",
		                   rule_id=a.rule_id, rule_ids=[a.rule_id, b.rule_id], **slot))
	for r, top, where, slot in _outranked_overrides(t):
		if r.rule_id in hidden:
			continue
		issues.append(_warn("OCC_POLICY_OVERRIDE_OUTRANKED",
		                    f"pricing-policy override {r.rule_id} ({r.source}) no longer prices {where}: "
		                    f"{top.rule_id} ({top.source}) does - a contract's own rule, a more specific "
		                    "policy's rule and a rule naming an infant's band rank before any policy override",
		                    rule_id=r.rule_id, rule_ids=[r.rule_id, top.rule_id], **slot))
	generic = sorted(r.rule_id for r in t.occupancy_rules
	                 if r.target == OccTarget.CHILD and r.age_band is None and r.op != Op.INHERIT)
	for band in t.age_bands:
		if generic and band.is_infant and not any(
				r.target == OccTarget.CHILD and r.age_band == band.code and r.op != Op.INHERIT
				for r in t.occupancy_rules):
			issues.append(_warn("OCC_INFANT_GENERIC",
			                    f"no rule names infant band {band.code}: infants are priced by the band-less child "
			                    f"rules ({', '.join(generic)}) — add a {band.code} rule if infants stay free",
			                    age_band=band.code, rule_id=generic[0], rule_ids=list(generic)))

	# boards
	if not any(b.is_base for b in t.boards):
		issues.append(_err("NO_BASE_BOARD", "no base board is included in the room price"))
	for b in t.boards:
		where = dict(rule_id=b.rule_id, board=b.board, room_type=b.room_type, period=b.period)
		if b.room_type and b.room_type not in t.rooms:
			issues.append(_err("BOARD_UNKNOWN_ROOM", f"board rule {b.rule_id} ({b.board}) names unknown room "
			                   f"{b.room_type}", **where))
		if b.period and b.period not in codes:
			issues.append(_err("BOARD_UNKNOWN_PERIOD", f"board rule {b.rule_id} ({b.board}) names unknown period "
			                   f"{b.period}", **where))
	# one rule per board, room and period: the engine would take the one with the greatest row name
	same_scope: dict[tuple, list[str]] = {}
	for b in t.boards:
		same_scope.setdefault((b.board, b.room_type, b.period), []).append(b.rule_id)
	for (board, rt, period), ids in sorted(same_scope.items(), key=lambda kv: str(kv[0])):
		if len(ids) > 1:
			issues.append(_err("BOARD_DUPLICATE", f"board {board} has {len(ids)} rules for the same room and period",
			                   rule_id=ids[0], rule_ids=ids, board=board, room_type=rt, period=period))
	board_codes = {b.board for b in t.boards}
	for rp in t.rate_plans.values():
		for bd in sorted(rp.boards or ()):
			if bd not in board_codes:
				issues.append(_err("RATE_PLAN_BOARD", f"rate plan {rp.code} sells unknown board {bd}"))

	for o in t.offers:
		if o.value_type == PromoValueType.PERCENT and not (ZERO < D(o.value) <= D(100)):
			issues.append(_err("OFFER_VALUE", f"offer {o.promo_id}: percent must be in (0, 100]"))
		if o.value_type == PromoValueType.FREE_NIGHTS and (
				not o.free_nights_stay or o.free_nights_pay is None or o.free_nights_pay >= o.free_nights_stay):
			issues.append(_err("OFFER_FREE_NIGHTS", f"offer {o.promo_id}: stay X pay Y needs X > Y"))

	if sweep_combinations and not any(i.level == "ERROR" for i in issues):
		issues.extend(_sweep(t, max_warnings, hidden))
	return issues


def _signature(r: OccupancyRule) -> tuple:
	return (r.target, r.position, r.age_band, r.room_type, r.period, r.adults, r.children, r.is_override,
	        r.base_level, r.scope_weight)


def _duplicates(rules) -> dict[tuple, list[str]]:
	"""Signatures shared by more than one non-INHERIT rule → the ids of those rules."""
	by_sig: dict[tuple, list[str]] = {}
	for r in rules:
		if r.op != Op.INHERIT:
			by_sig.setdefault(_signature(r), []).append(r.rule_id)
	return {s: ids for s, ids in sorted(by_sig.items(), key=lambda kv: str(kv[0])) if len(ids) > 1}


def _twin_issue(sig: tuple, ids: list[str]) -> Issue:
	_target, _position, band, room_type, period, adults, children = sig[:7]
	return _err("OCC_DUPLICATE", f"rules {', '.join(ids)} share the same scope (target, position, band, room, "
	            "period, combination, override); keep one", rule_id=ids[0], rule_ids=list(ids), room_type=room_type,
	            period=period, age_band=band, adults=adults, children=children)


# ─── occupancy slots ─────────────────────────────────────────────────────
# A slot is what one occupancy rule prices: adult n, child n in an age band, or the whole
# combination, of one party size in one room and period. The checks below walk the slots a
# rule can price and ask, as ``occupancy.price_occupancy`` would, which rules match there.

ANY = "*"   # the room / period / band of a pricing policy checked on its own (``policy_issues``)


def _key(t: ContractTerms, r: OccupancyRule, infant: bool) -> tuple:
	return occupancy.specificity(r, precedence=t.occupancy_precedence, infant_slot=infant)


def _fill(t: ContractTerms, spec: RoomSpec, adults: int) -> int:
	"""ROOM basis: the first children fill the included places adults leave empty, free."""
	if t.basis == PricingBasis.ROOM and t.room_basis_children_fill_included:
		return max(0, max(1, spec.included_adults) - adults)
	return 0


def _positions(t: ContractTerms, spec: RoomSpec, r: OccupancyRule, adults: int, children: int) -> list:
	"""Positions of the priced slots of ``r``'s target in this party (None: the combination)."""
	if r.target == OccTarget.COMBINATION:
		return [None]
	if r.target == OccTarget.CHILD:
		first, last = _fill(t, spec, adults) + 1, children
	else:   # included adults are not priced by a rule
		first = (max(1, spec.included_adults) if t.basis == PricingBasis.ROOM else 0) + 1
		last = adults
	if r.position is not None:
		return [r.position] if first <= r.position <= last else []
	return list(range(first, last + 1))


def _fits(t: ContractTerms, spec: RoomSpec, adults: int, children: int, band: AgeBand | None) -> bool:
	if adults + children <= spec.max_occupants:
		return True
	if t.infants_count_as_occupants or not any(b.is_infant for b in t.age_bands):
		return False
	# infants do not count: the other children may be infants; the priced child is one only in an infant band
	return adults + (1 if band is not None and not band.is_infant else 0) <= spec.max_occupants


def _slots(t: ContractTerms, r: OccupancyRule, adults: int | None, children: int | None, periods: list):
	"""(room, period code, adults, children, position, band) of every slot ``r`` prices in a
	party of ``adults`` + ``children`` (None: any number). ``periods``: the codes to try when
	the rule names none ([None] when no rule that matters names one)."""
	if r.room_type:
		specs = [t.rooms[r.room_type]] if r.room_type in t.rooms else []
	else:
		specs = [t.rooms[k] for k in sorted(t.rooms)]
	if r.target == OccTarget.CHILD:
		ordered = sorted(t.age_bands, key=lambda b: (b.from_months, b.code))
		bands = [b for b in ordered if b.code == r.age_band] if r.age_band else ordered
	else:
		bands = [None]
	if r.period:
		periods = [r.period] if r.period in {p.code for p in t.periods} else []
	for spec in specs:
		for n_a in range(max(1, spec.min_adults), spec.max_adults + 1):
			if adults is not None and n_a != adults:
				continue
			for n_c in range(0, spec.max_children + 1):
				if children is not None and n_c != children:
					continue
				for band in bands:
					if not _fits(t, spec, n_a, n_c, band):
						continue
					for pos in _positions(t, spec, r, n_a, n_c):
						for period in periods:
							yield spec, period, n_a, n_c, pos, band


def _matching(rules, target: OccTarget, spec: RoomSpec, period, adults: int, children: int, pos, band):
	code = band.code if band is not None else None
	return [x for x in rules if occupancy.qualifiers_match(x, spec.room_type, period, adults, children)
	        and occupancy.slot_matches(x, target, pos, code)]


def _reached(t: ContractTerms, spec: RoomSpec, period, adults: int, children: int, target: OccTarget,
             pos) -> bool:
	"""The runtime gets as far as this slot for some mix of the other children's bands: every
	child priced before it (all of them, for the combination) has a rule for some band - one
	without is NO_CHILD_RULE, and the party is unsellable whatever the later slots say.
	Adults are always priced (the global default); children come after adults."""
	if target == OccTarget.ADULT:
		return True
	last = children if target == OccTarget.COMBINATION else pos - 1
	rules = [x for x in t.occupancy_rules if x.op != Op.INHERIT and x.target == OccTarget.CHILD
	         and occupancy.qualifiers_match(x, spec.room_type, period, adults, children)]
	return all(any(occupancy.slot_matches(x, OccTarget.CHILD, q, b.code) for x in rules for b in t.age_bands)
	           for q in range(_fill(t, spec, adults) + 1, last + 1))


def _period_codes(t: ContractTerms, rules) -> list:
	return [p.code for p in t.periods] if any(x.period for x in rules) else [None]


def _describe(target: OccTarget, pos, band: AgeBand | None, spec: RoomSpec, adults: int, children: int,
              period) -> str:
	if target == OccTarget.COMBINATION:
		slot = "the combination"
	else:
		slot = f"{target.value.lower()} {pos}"
		if band is not None:
			slot += f" ({band.label if band.code.startswith(ANY) else band.code})"
	room = "" if spec.room_type == ANY else f" {spec.room_type}"
	where = f"{slot} of{room} {adults}A+{children}C"
	return where + (f" in {period}" if period not in (None, ANY) else "")


def _slot_ref(band: AgeBand | None, spec: RoomSpec, adults: int, children: int, period) -> dict:
	"""The ``ref`` parts of the slot ``_describe`` names; a pricing policy's placeholders are left out."""
	return dict(room_type=None if spec.room_type == ANY else spec.room_type,
	            period=None if period in (None, ANY) else period,
	            age_band=None if band is None or band.code.startswith(ANY) else band.code,
	            adults=adults, children=children)


def _deciding_slot(t: ContractTerms, a: OccupancyRule, b: OccupancyRule, *,
                   whole: bool) -> tuple[str, dict] | None:
	"""A slot both rules price where no higher-ranked rule does, so the tie decides the price
	(the runtime refuses to guess: AMBIGUOUS_OCCUPANCY_RULES), as (description, ref parts), or
	None. The rules have the same target, rank, room, period, position and band; their
	combinations may be partial ('2+*' and '*+2' meet at 2A+2C). ``whole``: ``t`` has every rule
	of the contract, so a slot the runtime never gets to (a child before it has no rule) is no tie."""
	adults = a.adults if a.adults is not None else b.adults
	children = a.children if a.children is not None else b.children
	same = [x for x in t.occupancy_rules if x.op != Op.INHERIT and x.target == a.target]
	higher = {inf: [x for x in same if _key(t, x, inf) > _key(t, a, inf)] for inf in (False, True)}
	for spec, period, n_a, n_c, pos, band in _slots(t, a, adults, children,
	                                                _period_codes(t, t.occupancy_rules if whole else
	                                                              higher[False] + higher[True])):
		infant = band is not None and band.is_infant
		if _matching(higher[infant], a.target, spec, period, n_a, n_c, pos, band):
			continue   # a higher-ranked rule prices this slot
		if whole and not _reached(t, spec, period, n_a, n_c, a.target, pos):
			continue
		return _describe(a.target, pos, band, spec, n_a, n_c, period), _slot_ref(band, spec, n_a, n_c, period)
	return None


def _ambiguous_pairs(t: ContractTerms, *, reported=(), whole: bool = True) -> list[tuple[OccupancyRule,
                                                                                            OccupancyRule, str, dict]]:
	"""Pairs of non-INHERIT rules with the same rank that decide some slot with different
	values, with that slot (description, ref parts). Twins whose signature is in ``reported``
	are left to OCC_DUPLICATE."""
	rules = [r for r in t.occupancy_rules if r.op != Op.INHERIT]
	rank = {id(r): occupancy.specificity(r, precedence=t.occupancy_precedence) for r in rules}
	out = []
	for i, a in enumerate(rules):
		for b in rules[i + 1:]:
			if a.target != b.target or (a.op, a.value) == (b.op, b.value) or rank[id(a)] != rank[id(b)]:
				continue
			if _signature(a) == _signature(b) and _signature(a) in reported:
				continue
			if (a.room_type, a.period, a.position, a.age_band) != (b.room_type, b.period, b.position, b.age_band):
				continue
			if (a.adults is not None and b.adults is not None and a.adults != b.adults) or \
					(a.children is not None and b.children is not None and a.children != b.children):
				continue
			slot = _deciding_slot(t, a, b, whole=whole)
			if slot:
				out.append((a, b, *slot))
	return out


def _outranked_overrides(t: ContractTerms) -> list[tuple[OccupancyRule, OccupancyRule, str, dict]]:
	"""Pricing-policy "specific override" rules that a rule of a higher origin (or, for an
	infant, a rule naming its band) now beats with another value, although the legacy
	ranking let the override win: (override, winner, first such slot, its ref parts)."""
	if t.occupancy_precedence != occupancy.CASCADE:
		return []
	rules = [r for r in t.occupancy_rules if r.op != Op.INHERIT]
	out = []
	for r in rules:
		if not r.is_override or r.base_level >= Level.CONTRACT:
			continue
		same = [x for x in rules if x is not r and x.target == r.target]
		higher = {inf: [x for x in same if _key(t, x, inf) > _key(t, r, inf)] for inf in (False, True)}
		legacy = occupancy.specificity(r, precedence=occupancy.LEGACY)
		for spec, period, n_a, n_c, pos, band in _slots(t, r, r.adults, r.children,
		                                                _period_codes(t, t.occupancy_rules)):
			infant = band is not None and band.is_infant
			found = _matching(higher[infant], r.target, spec, period, n_a, n_c, pos, band)
			if not found or not _reached(t, spec, period, n_a, n_c, r.target, pos):
				continue
			top = max(found, key=lambda x, infant=infant: _key(t, x, infant))
			if (top.op, top.value) != (r.op, r.value) and \
					occupancy.specificity(top, precedence=occupancy.LEGACY) <= legacy:
				out.append((r, top, _describe(r.target, pos, band, spec, n_a, n_c, period),
				            _slot_ref(band, spec, n_a, n_c, period)))
				break
	return out


def policy_issues(bands: tuple[AgeBand, ...], rules: tuple[OccupancyRule, ...]) -> list[Issue]:
	"""One pricing policy checked on its own, before it goes live: it cascades into every
	contract of its scope, so a row no contract can publish (an adult rule with a band, a
	combination rule without adults/children), twin rules and rules that tie in some party
	are refused here. Rooms and periods are unknown: a room is taken to hold any party the
	rules name, and a band-less rule to meet bands no rule names (an infant one too)."""
	issues: list[Issue] = []
	for r in rules:
		if r.target == OccTarget.COMBINATION and r.adults is None and r.children is None:
			issues.append(_err("OCC_COMBINATION_QUALIFIER", f"combination rule {r.rule_id} needs adults/children",
			                   **_rule_ref(r)))
		if r.target == OccTarget.ADULT and r.age_band:
			issues.append(_err("OCC_ADULT_BAND", f"adult rule {r.rule_id} cannot name an age band", **_rule_ref(r)))
		if r.op != Op.INHERIT and r.value is None:
			issues.append(_err("OCC_NO_VALUE", f"rule {r.rule_id} has no value", **_rule_ref(r)))
	twins = _duplicates(rules)
	issues.extend(_twin_issue(sig, ids) for sig, ids in twins.items())
	size = max([2, *(n for r in rules for n in (r.adults, r.children, r.position) if n)])
	room = RoomSpec(ANY, "any room", max_adults=size, max_children=size, max_occupants=2 * size)
	named = sorted({r.age_band for r in rules if r.age_band} - {b.code for b in bands})
	t = ContractTerms(
		contract_id=ANY, contract_code=ANY, contract_name="pricing policy", version_id=ANY, version_no=0,
		payload_hash="", property=ANY, market=ANY, currency="XXX", basis=PricingBasis.PERSON,
		rooms={ANY: room, **{rt: replace(room, room_type=rt, name=rt)
		                     for rt in sorted({r.room_type for r in rules if r.room_type})}},
		periods=(Period(ANY, "any period", date.min, date.max),), room_rules=(), occupancy_rules=tuple(rules),
		age_bands=(*bands, *(AgeBand(c, c, 0, 1) for c in named), AgeBand(ANY, "any band", 0, 1),
		           AgeBand(ANY + "INF", "an infant", 0, 1, is_infant=True)),
		boards=(), rate_plans={})
	# the contract's own rules are unknown here: every party counts
	for a, b, where, slot in _ambiguous_pairs(t, reported=twins, whole=False):
		issues.append(_err("OCC_AMBIGUOUS", f"rules {a.rule_id} and {b.rule_id} both price {where} at the same "
		                   "precedence with different values; make one more specific or remove one",
		                   rule_id=a.rule_id, rule_ids=[a.rule_id, b.rule_id], **slot))
	return issues


def _sweep_party(t: ContractTerms, adults: int, children: int, band: AgeBand | None, p: Period) -> Party:
	"""The party the sweep prices: ``children`` children, all at the lower edge of ``band``."""
	slots = tuple(ChildSlot(i + 1, band.from_months, band, i) for i in range(children)) if band else ()
	return Party(adults=adults, declared_adults=adults, children=slots, children_as_adults=(),
	             infants=sum(1 for s in slots if s.band.is_infant), reference_date=p.start)


# the sweep's issues whose presence can depend on a rule's op or value (``occupancy.depends_on``),
# and every code ``validate_terms(hidden=…)`` may leave out
_SWEEP_HIDEABLE = frozenset({"NEGATIVE_OCCUPANCY_PRICE", "NO_CHILD_RULE"})
HIDEABLE_CODES = _SWEEP_HIDEABLE | {"OCC_POLICY_OVERRIDE_OUTRANKED"}


def _sweep(t: ContractTerms, limit: int, hidden: frozenset[str] = frozenset()) -> list[Issue]:
	"""Price every valid combination (all children in one band) once per period and
	report the ones that cannot be priced. Ambiguous rules are an ERROR (the runtime
	refuses to guess); a combination without a rule only makes that offer unsellable.
	A combination is reported once, in the first period where it fails (``ref.period``).
	A failure whose presence depends on the op or value of one of the ``hidden`` rules is not
	reported (``occupancy.depends_on``): a negative total one of them takes part in, a child no
	rule prices where one of them defers. A child band without a rule is, whoever priced the
	adults before it (S16 re-review)."""
	out: list[Issue] = []
	seen: set[tuple] = set()
	for rt, spec in sorted(t.rooms.items()):
		for p in t.periods:
			try:
				unit = rooms.room_unit(t, rt, p)
			except Unsellable:
				continue
			for a in range(max(1, spec.min_adults), spec.max_adults + 1):
				for c in range(0, spec.max_children + 1):
					if a + c > spec.max_occupants:
						continue
					for band in (t.age_bands if c else (None,)):
						party = _sweep_party(t, a, c, band, p)
						try:
							occupancy.price_occupancy(t, spec, p, unit, party)
						except Unsellable as u:
							key = (rt, a, c, band.code if band else None, u.code)
							if key in seen:
								continue
							level = "ERROR" if u.code == "AMBIGUOUS_OCCUPANCY_RULES" else "WARNING"
							if hidden and u.code in _SWEEP_HIDEABLE and \
									occupancy.depends_on(t, spec, p, unit, party, hidden):
								continue
							seen.add(key)
							tied = list(u.params.get("rules") or ()) or None
							out.append(Issue(level, u.code, f"{rt} {a}A+{c}C"
							                 f"{' [' + band.code + ']' if band else ''}: {u.message}",
							                 _ref(room_type=rt, period=p.code, adults=a, children=c,
							                      age_band=band.code if band else None,
							                      rule_id=tied[0] if tied else None, rule_ids=tied)))
							if len(out) >= limit:
								return out
	return out


def visible_issues(t: ContractTerms, issues: list, hidden: frozenset[str]) -> list:
	"""A stored report of ``t`` (``Issue.to_dict`` rows: the one frozen at publish, made with
	nothing hidden) as a viewer who may not read the ``hidden`` rules may see it, as
	``validate_terms(t, hidden=hidden)`` leaves issues out (S16 re-review): no
	OCC_POLICY_OVERRIDE_OUTRANKED about a hidden override, no sweep issue whose presence depends
	on a hidden rule (``occupancy.depends_on``, for the party and period the row names). A row
	that does not say which override or party it is about is left out; nothing is left out when
	nothing is hidden."""
	if not hidden:
		return list(issues)
	bands = {b.code: b for b in t.age_bands}
	periods = {p.code: p for p in t.periods}
	out = []
	for i in issues:
		if not isinstance(i, dict):
			continue
		ref = i.get("ref") if isinstance(i.get("ref"), dict) else {}
		code = i.get("code")
		if code == "OCC_POLICY_OVERRIDE_OUTRANKED":
			if not ref.get("rule_id") or ref["rule_id"] in hidden:
				continue
		elif code in _SWEEP_HIDEABLE:
			spec, p = t.rooms.get(ref.get("room_type")), periods.get(ref.get("period"))
			a, c, band = ref.get("adults"), ref.get("children") or 0, bands.get(ref.get("age_band"))
			if spec is None or p is None or not isinstance(a, int) or not isinstance(c, int) or (c and band is None):
				continue
			try:
				unit = rooms.room_unit(t, spec.room_type, p)
			except Unsellable:
				continue
			if occupancy.depends_on(t, spec, p, unit, _sweep_party(t, a, c, band, p), hidden):
				continue
		out.append(i)
	return out
