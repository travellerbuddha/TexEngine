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

The Pricing Workspace's additions are opt-in (ADR-061, "Existing semantics kept, the
workspace's additions opt-in"); without them every caller gets main's issues, in main's shape:

* ``board_checks`` (GAP-5): board rules are checked like room rules - a rule naming a room or
  period the contract does not have, and two rules of one board for the same room and period
  (the engine would settle them by row name), are ERRORs;
* ``Issue.to_dict(ref=True)`` (D9, GAP-4): what an issue is about - the rule(s), room, period,
  age band(s), party and board - so the workspace can mark the cell or row and show band labels
  for the codes in the message. Codes and messages do not depend on it.

``hidden`` is not an addition but a guard: a viewer without cost is never told what a pricing
policy's formula decides (S16 review), whoever asks.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import date

from kamra.tex.money import ZERO, D
from kamra.tex.pricing import ages, occupancy, policy_money, rooms
from kamra.tex.pricing.ages import ChildSlot, Party
from kamra.tex.pricing.enums import Level, OccTarget, Op, PricingBasis, PromoValueType
from kamra.tex.pricing.model import (
	AgeBand,
	ContractTerms,
	OccupancyRule,
	Period,
	PricingError,
	RatePlanTerms,
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
	# code of the contract, for AGE_BANDS), adults, children (the party), board, rate_plan (the
	# rate plan row of RATE_PLAN_REFUNDABLE and POLICY_CURRENCY, ADR-067). Only the parts the
	# issue has; None when it is about the contract as a whole. Not part of the issue's identity.
	ref: dict | None = field(default=None, compare=False)

	def to_dict(self, *, ref: bool = False) -> dict:
		"""Main's three keys; with ``ref`` (the workspace's, D9) also ``"ref"`` when there is one."""
		out = {"level": self.level, "code": self.code, "message": self.message}
		if ref and self.ref:
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
                   hidden: frozenset[str] = frozenset(), board_checks: bool = False) -> list[Issue]:
	"""The issues of ``t``. ``board_checks``: the workspace's board rule checks (GAP-5, opt-in:
	without them the issues are main's). ``hidden``: ids of occupancy rules the viewer may not read (a pricing
	policy's formulas, which are cost: ADR-061, S16 review). Then no issue's presence or wording
	depends on one of their ops or values, not even on whether one defers (INHERIT) (S16 re-review
	4): the issues are the same whatever their ops. Left out or told without what would say it:
	OCC_POLICY_OVERRIDE_OUTRANKED for a hidden override; OCC_NO_VALUE of a hidden rule; a tie between
	hidden rules; a tie of the viewer's rules at a slot a hidden rule may decide is named at a slot
	no hidden rule decides, else without its slot (``_ambiguous_pairs``); the sweep's failures of a
	party whose answer can depend on a hidden op (``occupancy.depends_on``). A child band without any
	rule and a tie of the viewer's rules no hidden rule decides are reported, whoever priced the
	adults (S16 re-review). OCC_INFANT_GENERIC names no hidden rule and is not said for an infant
	band a hidden rule names (``_infant_generic``, S16 re-review 3). ``visible_issues`` gives a stored
	report the same way."""
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
		if r.op != Op.INHERIT and r.value is None and r.rule_id not in hidden:
			# a hidden rule's would say that it does not defer (a policy cannot go live so: policy_issues)
			issues.append(_err("OCC_NO_VALUE", f"rule {r.rule_id} has no value", **_rule_ref(r)))
	# twin rules of the version are an error; twins of one pricing policy only where they decide a price
	twins = _duplicates([r for r in t.occupancy_rules if r.base_level >= Level.CONTRACT])
	issues.extend(_twin_issue(sig, ids) for sig, ids in twins.items())
	for a, b, where, slot in _ambiguous_pairs(t, reported=twins, hidden=hidden):
		if where is None:   # every slot of the tie is one a hidden rule may decide (``_ambiguous_pairs``)
			where, slot = _pair_scope(a, b)
			message = (f"rules {a.rule_id} and {b.rule_id} both price {where} at the same precedence with "
			           "different values wherever the pricing policy's rules leave it to them; make one more "
			           "specific or remove one")
		else:
			message = (f"rules {a.rule_id} and {b.rule_id} both price {where} at the same precedence with "
			           "different values; make one more specific or remove one")
		issues.append(_err("OCC_AMBIGUOUS", message, rule_id=a.rule_id, rule_ids=[a.rule_id, b.rule_id], **slot))
	for r, top, where, slot in _outranked_overrides(t):
		if r.rule_id in hidden:
			continue
		issues.append(_warn("OCC_POLICY_OVERRIDE_OUTRANKED",
		                    f"pricing-policy override {r.rule_id} ({r.source}) no longer prices {where}: "
		                    f"{top.rule_id} ({top.source}) does - a contract's own rule, a more specific "
		                    "policy's rule and a rule naming an infant's band rank before any policy override",
		                    rule_id=r.rule_id, rule_ids=[r.rule_id, top.rule_id], **slot))
	issues.extend(_infant_generic(t, hidden))

	# boards
	if not any(b.is_base for b in t.boards):
		issues.append(_err("NO_BASE_BOARD", "no base board is included in the room price"))
	if board_checks:
		issues.extend(_board_issues(t, codes))
	board_codes = {b.board for b in t.boards}
	for rp in t.rate_plans.values():
		for bd in sorted(rp.boards or ()):
			if bd not in board_codes:
				issues.append(_err("RATE_PLAN_BOARD", f"rate plan {rp.code} sells unknown board {bd}"))
		issues.extend(_refundable_issues(rp))
		issues.extend(_policy_currency_issues(rp, t.currency))

	for o in t.offers:
		if o.value_type == PromoValueType.PERCENT and not (ZERO < D(o.value) <= D(100)):
			issues.append(_err("OFFER_VALUE", f"offer {o.promo_id}: percent must be in (0, 100]"))
		if o.value_type == PromoValueType.FREE_NIGHTS and (
				not o.free_nights_stay or o.free_nights_pay is None or o.free_nights_pay >= o.free_nights_stay):
			issues.append(_err("OFFER_FREE_NIGHTS", f"offer {o.promo_id}: stay X pay Y needs X > Y"))

	if sweep_combinations and not any(i.level == "ERROR" for i in issues):
		issues.extend(_sweep(t, max_warnings, hidden))
	return issues


def _refundable_issues(rp: RatePlanTerms) -> list[Issue]:
	"""A rate plan row and its cancellation policy that disagree about refunds (Y-4, ADR-067). A
	price is refundable only when both say so, so a refundable row on a non-refundable policy would
	be sold as non-refundable: an ERROR, for every caller. A non-refundable row on a refundable
	policy with rules sells as the row says and the rules never apply: a WARNING."""
	pol = rp.cancellation_policy or {}
	name = pol.get("name") or pol.get("id")
	if rp.refundable and not policy_money.refundable(rp.refundable, pol):
		return [_err("RATE_PLAN_REFUNDABLE", f"rate plan {rp.code} is refundable but its cancellation policy "
		             f"{name} is not; mark the rate plan non-refundable or choose a refundable policy",
		             rate_plan=rp.code)]
	if not rp.refundable and pol.get("rules") and pol.get("refundable", True) is not False:
		return [_warn("RATE_PLAN_REFUNDABLE", f"rate plan {rp.code} is non-refundable, so the rules of its "
		              f"cancellation policy {name} never apply", rate_plan=rp.code)]
	return []


def _policy_currency_issues(rp: RatePlanTerms, contract_currency: str) -> list[Issue]:
	"""A payment or cancellation policy whose fixed amounts are in another currency than the
	contract's (Y-3 A, ADR-067): an ERROR, so a fixed amount always converts to the sale's currency
	at the one contract → sell rate a quote records. A policy without a currency is in the contract's."""
	out = []
	for kind, pol in (("cancellation", rp.cancellation_policy), ("payment", rp.payment_policy)):
		ccy = ((pol or {}).get("currency") or "").upper()
		if policy_money.has_fixed(pol) and ccy and ccy != contract_currency.upper():
			out.append(_err("POLICY_CURRENCY", f"rate plan {rp.code}: the fixed amounts of {kind} policy "
			                f"{pol.get('name') or pol.get('id')} are in {ccy}, the contract's currency is "
			                f"{contract_currency}; give the policy the contract's currency (or none)",
			                rate_plan=rp.code))
	return out


def _board_issues(t: ContractTerms, codes: list[str]) -> list[Issue]:
	"""The workspace's board rule checks (ADR-061 GAP-5; ``validate_terms(board_checks=True)``): a
	rule naming a room or period the contract does not have, and two or more rules of one board for
	the same room and period (the engine would take the one with the greatest row name), are ERRORs.
	Main published such rows (a rule for an unknown room or period never applies), so an existing
	caller is not told about them."""
	out: list[Issue] = []
	for b in t.boards:
		where = dict(rule_id=b.rule_id, board=b.board, room_type=b.room_type, period=b.period)
		if b.room_type and b.room_type not in t.rooms:
			out.append(_err("BOARD_UNKNOWN_ROOM", f"board rule {b.rule_id} ({b.board}) names unknown room "
			                f"{b.room_type}", **where))
		if b.period and b.period not in codes:
			out.append(_err("BOARD_UNKNOWN_PERIOD", f"board rule {b.rule_id} ({b.board}) names unknown period "
			                f"{b.period}", **where))
	same_scope: dict[tuple, list[str]] = {}
	for b in t.boards:
		same_scope.setdefault((b.board, b.room_type, b.period), []).append(b.rule_id)
	for (board, rt, period), ids in sorted(same_scope.items(), key=lambda kv: str(kv[0])):
		if len(ids) > 1:
			out.append(_err("BOARD_DUPLICATE", f"board {board} has {len(ids)} rules for the same room and period",
			                rule_id=ids[0], rule_ids=ids, board=board, room_type=rt, period=period))
	return out


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


def _positions_infants_apart(t: ContractTerms, spec: RoomSpec, r: OccupancyRule, adults: int, children: int,
                             band: AgeBand | None) -> list:
	"""``_positions`` of a contract whose infants are not children (O-2, ADR-067): ``children`` counts
	the other children, numbered first, as the combination rules and max_children count them; an
	infant's slot follows them, as ``ages.order_children`` numbers it. The party fits the room as the
	runtime checks it: the adults and the other children always (a party they overfill never sells,
	whatever its infants), the infants up to the priced one when they count as occupants (else up to
	the room's size)."""
	if adults + children > spec.max_occupants:
		return []
	if band is None or not band.is_infant:
		return _positions(t, spec, r, adults, children)
	room = spec.max_occupants - adults - children if t.infants_count_as_occupants else spec.max_occupants
	first, last = max(children, _fill(t, spec, adults)) + 1, children + room
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
	the rule names none ([None] when no rule that matters names one). When infants are not
	children (O-2) ``children`` is the count the combination rules see, without the infants."""
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
					if not t.infants_count_as_children:
						positions = _positions_infants_apart(t, spec, r, n_a, n_c, band)
					elif _fits(t, spec, n_a, n_c, band):
						positions = _positions(t, spec, r, n_a, n_c)
					else:
						continue
					for pos in positions:
						for period in periods:
							yield spec, period, n_a, n_c, pos, band


def _matching(rules, target: OccTarget, spec: RoomSpec, period, adults: int, children: int, pos, band):
	code = band.code if band is not None else None
	return [x for x in rules if occupancy.qualifiers_match(x, spec.room_type, period, adults, children)
	        and occupancy.slot_matches(x, target, pos, code)]


def _reached(t: ContractTerms, spec: RoomSpec, period, adults: int, children: int, target: OccTarget,
             pos, reaching=None) -> bool:
	"""The runtime gets as far as this slot for some mix of the other children's bands: every
	child priced before it (all of them, for the combination) has a rule for some band - one
	without is NO_CHILD_RULE, and the party is unsellable whatever the later slots say.
	Adults are always priced (the global default); children come after adults. ``reaching``: the
	rules that price a child (default: every rule that does not defer)."""
	if target == OccTarget.ADULT:
		return True
	last = children if target == OccTarget.COMBINATION else pos - 1
	pool = [x for x in t.occupancy_rules if x.op != Op.INHERIT] if reaching is None else reaching
	rules = [x for x in pool if x.target == OccTarget.CHILD
	         and occupancy.qualifiers_match(x, spec.room_type, period, adults, children)]

	def bands_at(q: int):
		"""When infants are not children (O-2) the first ``children`` positions are the other
		children and the ones after them infants."""
		if t.infants_count_as_children:
			return t.age_bands
		return [b for b in t.age_bands if b.is_infant == (q > children)]

	return all(any(occupancy.slot_matches(x, OccTarget.CHILD, q, b.code) for x in rules for b in bands_at(q))
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


def _deciding_slot(t: ContractTerms, a: OccupancyRule, b: OccupancyRule, *, whole: bool,
                   pricing=None, reaching=None) -> tuple[str, dict] | None:
	"""A slot both rules price where no higher-ranked rule does, so the tie decides the price
	(the runtime refuses to guess: AMBIGUOUS_OCCUPANCY_RULES), as (description, ref parts), or
	None. The rules have the same target, rank, room, period, position and band; their
	combinations may be partial ('2+*' and '*+2' meet at 2A+2C). ``whole``: ``t`` has every rule
	of the contract, so a slot the runtime never gets to (a child before it has no rule) is no tie.
	``pricing``: the rules that price a slot where they match, before the tie (default: every rule
	that does not defer); ``reaching``: the rules that price a child before it (``_reached``)."""
	adults = a.adults if a.adults is not None else b.adults
	children = a.children if a.children is not None else b.children
	pool = [x for x in t.occupancy_rules if x.op != Op.INHERIT] if pricing is None else pricing
	same = [x for x in pool if x.target == a.target]
	higher = {inf: [x for x in same if _key(t, x, inf) > _key(t, a, inf)] for inf in (False, True)}
	for spec, period, n_a, n_c, pos, band in _slots(t, a, adults, children,
	                                                _period_codes(t, t.occupancy_rules if whole else
	                                                              higher[False] + higher[True])):
		infant = band is not None and band.is_infant
		if _matching(higher[infant], a.target, spec, period, n_a, n_c, pos, band):
			continue   # a higher-ranked rule prices this slot
		if whole and not _reached(t, spec, period, n_a, n_c, a.target, pos, reaching):
			continue
		return _describe(a.target, pos, band, spec, n_a, n_c, period), _slot_ref(band, spec, n_a, n_c, period)
	return None


def _pair_scope(a: OccupancyRule, b: OccupancyRule) -> tuple[str, dict]:
	"""What two tied rules price, from their own scope (no party, band or slot the rules do not
	name): the description and ref parts of an OCC_AMBIGUOUS without its slot."""
	adults = a.adults if a.adults is not None else b.adults
	children = a.children if a.children is not None else b.children
	if a.target == OccTarget.COMBINATION:
		slot = "the combination"
	elif a.position is not None:
		slot = f"{a.target.value.lower()} {a.position}"
	else:
		slot = f"any {a.target.value.lower()}"
	if a.age_band:
		slot += f" ({a.age_band})"
	party = f"{'*' if adults is None else adults}A+{'*' if children is None else children}C"
	where = f"{slot} of{' ' + a.room_type if a.room_type else ''} {party}" + (f" in {a.period}" if a.period else "")
	return where, dict(room_type=a.room_type, period=a.period, age_band=a.age_band, adults=adults, children=children)


def _ambiguous_pairs(t: ContractTerms, *, reported=(), whole: bool = True,
                     hidden: frozenset[str] = frozenset()) -> list[tuple[OccupancyRule, OccupancyRule,
                                                                         str | None, dict | None]]:
	"""Pairs of non-INHERIT rules with the same rank that decide some slot with different
	values, with that slot (description, ref parts). Twins whose signature is in ``reported``
	are left to OCC_DUPLICATE.

	With ``hidden`` rules (a viewer who may not read them, S16 re-review 4) the pairs and slots
	do not depend on their ops: a pair with a hidden rule is left out (it ties only if that rule
	does not defer, and with that value); the slot is one where the tie decides a price whatever
	the hidden ops (no hidden rule ranked above it matches there, and the children before it are
	priced by the viewer's rules); where there is none but some ops of the hidden rules would let
	the tie decide a price (the hidden rules above it all defer, or price the children before
	it), the pair comes with no slot (None, None)."""
	rules = [r for r in t.occupancy_rules if r.op != Op.INHERIT and r.rule_id not in hidden]
	if hidden:
		read = list(rules)
		maybe = [r for r in t.occupancy_rules if r.rule_id in hidden]
		certain = dict(pricing=read + maybe, reaching=read)     # a hidden rule may price: skip its slots
		possible = dict(pricing=read, reaching=read + maybe)    # the hidden rules all defer, or all price
	else:
		certain = possible = {}
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
			slot = _deciding_slot(t, a, b, whole=whole, **certain)
			if slot is None and hidden and _deciding_slot(t, a, b, whole=whole, **possible):
				slot = (None, None)
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


def _infant_generic(t: ContractTerms, hidden: frozenset[str] = frozenset()) -> list[Issue]:
	"""OCC_INFANT_GENERIC: an infant band no rule names is priced by the band-less child rules,
	which the warning names (INHERIT ones left out). With ``hidden`` rules (S16 re-review 3) a
	hidden one is never named, whatever its op (naming only the ones that price would say which
	defer), and an infant band a hidden rule names is not reported (whether that rule defers may be
	why no rule prices the band)."""
	generic = sorted(r.rule_id for r in t.occupancy_rules
	                 if r.target == OccTarget.CHILD and r.age_band is None and r.op != Op.INHERIT
	                 and r.rule_id not in hidden)
	out: list[Issue] = []
	for band in t.age_bands:
		if not generic or not band.is_infant:
			continue
		named = [r for r in t.occupancy_rules if r.target == OccTarget.CHILD and r.age_band == band.code]
		if any(r.op != Op.INHERIT for r in named) or any(r.rule_id in hidden for r in named):
			continue
		out.append(_warn("OCC_INFANT_GENERIC",
		                 f"no rule names infant band {band.code}: infants are priced by the band-less child "
		                 f"rules ({', '.join(generic)}) — add a {band.code} rule if infants stay free",
		                 age_band=band.code, rule_id=generic[0], rule_ids=list(generic)))
	return out


def _sweep_party(t: ContractTerms, adults: int, children: int, band: AgeBand | None, p: Period) -> Party:
	"""The party the sweep prices: ``children`` children, all at the lower edge of ``band``."""
	slots = tuple(ChildSlot(i + 1, band.from_months, band, i) for i in range(children)) if band else ()
	return Party(adults=adults, declared_adults=adults, children=slots, children_as_adults=(),
	             infants=sum(1 for s in slots if s.band.is_infant), reference_date=p.start,
	             infants_as_children=t.infants_count_as_children)


# the sweep's issues whose presence can depend on a rule's op or value (``occupancy.depends_on``: every
# failure of ``occupancy.price_occupancy``), and every code ``validate_terms(hidden=…)`` may leave out
_SWEEP_HIDEABLE = frozenset({"NEGATIVE_OCCUPANCY_PRICE", "NO_CHILD_RULE", "AMBIGUOUS_OCCUPANCY_RULES"})
HIDEABLE_CODES = _SWEEP_HIDEABLE | {"OCC_POLICY_OVERRIDE_OUTRANKED", "OCC_INFANT_GENERIC", "OCC_AMBIGUOUS",
                                    "OCC_NO_VALUE"}
SWEEP_LIMIT = 200   # validate_terms' max_warnings: the sweep stops at so many issues


def _sweep_issue(rt: str, a: int, c: int, band: AgeBand | None, p: Period, u: Unsellable) -> Issue:
	level = "ERROR" if u.code == "AMBIGUOUS_OCCUPANCY_RULES" else "WARNING"
	tied = list(u.params.get("rules") or ()) or None
	return Issue(level, u.code, f"{rt} {a}A+{c}C{' [' + band.code + ']' if band else ''}: {u.message}",
	             _ref(room_type=rt, period=p.code, adults=a, children=c, age_band=band.code if band else None,
	                  rule_id=tied[0] if tied else None, rule_ids=tied))


def _sweep(t: ContractTerms, limit: int, hidden: frozenset[str] = frozenset()) -> list[Issue]:
	"""Price every valid combination (all children in one band) once per period and
	report the ones that cannot be priced. Ambiguous rules are an ERROR (the runtime
	refuses to guess); a combination without a rule only makes that offer unsellable.
	A combination is reported once, in the first period where it fails (``ref.period``).
	A failure whose presence can depend on the op of one of the ``hidden`` rules is not reported
	(``occupancy.depends_on``), and the combination is then reported in the next period where it
	fails the same way independently of them: the report is the same whatever their ops (S16
	re-review 4). A child band without a rule is reported, whoever priced the adults before it (S16
	re-review)."""
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
							if hidden and u.code in _SWEEP_HIDEABLE and \
									occupancy.depends_on(t, spec, p, unit, party, hidden):
								continue
							seen.add(key)
							out.append(_sweep_issue(rt, a, c, band, p, u))
							if len(out) >= limit:
								return out
	return out


def visible_issues(t: ContractTerms, issues: list, hidden: frozenset[str]) -> list:
	"""A stored report of ``t`` (``Issue.to_dict`` rows: the one frozen at publish, made with
	nothing hidden) as a viewer who may not read the ``hidden`` rules may see it, as
	``validate_terms(t, hidden=hidden)`` gives its issues (S16 re-review): no
	OCC_POLICY_OVERRIDE_OUTRANKED about a hidden override; an OCC_INFANT_GENERIC row as the live check
	gives it (its stored message may name hidden rules; ``_infant_generic``); the sweep's rows as the
	live check's sweep gives them (``_visible_sweep``: a party whose answer can depend on a hidden op
	is reported in the next period where it does not, as the live check does, so the rows are the
	same whatever the hidden ops, S16 re-review 4). A row that does not say which override, party or
	band it is about is left out, and so is an ERROR row of a code the live check may leave out (a
	published version's report has none). Nothing is left out when nothing is hidden."""
	if not hidden:
		return list(issues)
	# the infant warning as the live check gives it (its stored message may name hidden rules)
	infants = {x.ref.get("age_band"): x for x in _infant_generic(t, hidden)}
	out, swept = [], []
	for i in issues:
		if not isinstance(i, dict):
			continue
		ref = i.get("ref") if isinstance(i.get("ref"), dict) else {}
		code = i.get("code")
		if code == "OCC_POLICY_OVERRIDE_OUTRANKED":
			if not ref.get("rule_id") or ref["rule_id"] in hidden:
				continue
		elif code == "OCC_INFANT_GENERIC":
			band = ref.get("age_band")
			if not isinstance(band, str) or band not in infants:
				continue
			i = infants.pop(band).to_dict(ref="ref" in i)       # the stored row's shape (main's has no ref)
		elif code in _SWEEP_HIDEABLE:
			row = _stored_party(t, ref)
			if row is not None:
				swept.append((i, row))
			continue
		elif code in HIDEABLE_CODES:
			continue
		out.append(i)
	return out + _visible_sweep(t, swept, hidden)


def refusal_errors(t: ContractTerms, errors: list[Issue], hidden: frozenset[str], *,
                   board_checks: bool = False) -> list[Issue]:
	"""The errors a refused publish names to a viewer who may not read the ``hidden`` rules; ``errors``
	are the full check's, which failed (S16 re-review 5). The errors of that viewer's own live check
	(``validate_terms(t, hidden=hidden)``): none of them depends on a hidden op, so what the refusal
	says is the same whatever those ops are (the full check's could name a slot, a party or a tie a
	hidden rule decides). Empty when every error depends on a hidden rule. Nothing hidden: ``errors``."""
	if not hidden:
		return list(errors)
	return [i for i in validate_terms(t, hidden=hidden, board_checks=board_checks) if i.level == "ERROR"]


def reruns_sweep(issues: list) -> bool:
	"""Whether ``visible_issues`` may run the sweep again for the stored report ``issues``: its sweep
	rows reached ``SWEEP_LIMIT`` (``_visible_sweep``), seconds on a large contract, which the caller
	bounds (S16 re-review 5). An upper bound: a row that does not say its party is counted too."""
	return sum(1 for i in issues if isinstance(i, dict) and i.get("code") in _SWEEP_HIDEABLE) >= SWEEP_LIMIT


def _stored_party(t: ContractTerms, ref: dict):
	"""The room, period, party and band a stored sweep row names, or None when it does not say."""
	spec = t.rooms.get(ref.get("room_type"))
	p = next((x for x in t.periods if x.code == ref.get("period")), None)
	a, c = ref.get("adults"), ref.get("children") or 0
	band = next((b for b in t.age_bands if b.code == ref.get("age_band")), None)
	if spec is None or p is None or not isinstance(a, int) or not isinstance(c, int) or (c and band is None):
		return None
	return spec, p, a, c, band if c else None


def _visible_sweep(t: ContractTerms, swept: list, hidden: frozenset[str]) -> list[dict]:
	"""The live check's sweep for a viewer who may not read ``hidden`` (``_sweep(t, SWEEP_LIMIT,
	hidden)``, as ``to_dict(ref=True)`` rows), worked out from a stored report's sweep rows ``swept``
	((row, its party)) without pricing every combination again. The stored sweep reports each
	combination in the first period it fails; the live one skips a period whose failure can depend on
	a hidden op, so a stored row is kept when its failure cannot, and otherwise moved to the next period
	where the combination fails the same way independently of the hidden rules (or left out). A stored
	sweep that reached its limit may have left combinations out: the live sweep is then run (a report
	of main's shape has no sweep row with a ``ref``: nothing to give)."""
	if len(swept) >= SWEEP_LIMIT:
		return [x.to_dict(ref=True) for x in _sweep(t, SWEEP_LIMIT, hidden)]
	order = {rt: n for n, rt in enumerate(sorted(t.rooms))}
	at = {p.code: n for n, p in enumerate(t.periods)}
	bands = {b.code: n for n, b in enumerate(t.age_bands)}
	shown = []
	for row, (spec, p, a, c, band) in swept:
		for q in t.periods[at[p.code]:]:
			try:
				unit = rooms.room_unit(t, spec.room_type, q)
			except Unsellable:
				continue
			party = _sweep_party(t, a, c, band, q)
			try:
				occupancy.price_occupancy(t, spec, q, unit, party)
			except Unsellable as u:
				if u.code != row.get("code") or occupancy.depends_on(t, spec, q, unit, party, hidden):
					continue
				moved = row if q is p else _sweep_issue(spec.room_type, a, c, band, q, u).to_dict(ref=True)
				shown.append(((order[spec.room_type], at[q.code], a, c, bands[band.code] if band else -1), moved))
				break
	return [row for _, row in sorted(shown, key=lambda x: x[0])]
