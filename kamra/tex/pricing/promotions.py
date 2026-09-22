"""PromotionResolver (R-18, R-20).

Eligibility is evaluated for every candidate and each one is reported as
``applied`` or ``rejected`` with a reason. Combination is deterministic:

1. candidates sorted by (priority desc, promo_id);
2. if any eligible promotion is ``exclusive``, the highest-priority exclusive one is the
   only promotion applied; all others are rejected "excluded by <id>";
3. otherwise, in order: a promotion in an ``incompatible group`` already used is rejected;
   a non-stackable promotion is rejected once anything applied; after a non-stackable
   promotion is applied, nothing else applies;
4. values apply per night on the running price (SEQUENTIAL) or all percentages on the
   pre-promotion price (ADDITIVE), per contract setting.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from kamra.tex.money import HUNDRED, ONE, ZERO, D
from kamra.tex.pricing.enums import PromoValueType, StackingMode, StayMatch
from kamra.tex.pricing.explain import Explanation
from kamra.tex.pricing.model import FxSnapshot, Promotion, RuleRef


@dataclass(frozen=True, slots=True)
class PromoContext:
	sale_date: date
	check_in: date
	check_out: date
	nights: tuple[date, ...]
	market: str
	channel: str
	room_type: str
	board: str
	rate_plan: str | None
	contract: str
	member: bool
	codes: frozenset[str]
	extras: frozenset[str]
	basket: Decimal                 # accommodation (+extras) value used for min_basket
	sell_currency: str


@dataclass(frozen=True, slots=True)
class PromoOutcome:
	promo_id: str
	name: str
	kind: str
	applied: bool
	reason: str
	discount: Decimal = ZERO
	nights: tuple[str, ...] = ()
	value_added: str = ""
	source: str = ""
	code: str | None = None

	def to_dict(self) -> dict:
		from kamra.tex.money import to_str6

		return {"promo_id": self.promo_id, "name": self.name, "kind": self.kind, "applied": self.applied,
		        "reason": self.reason, "discount": to_str6(self.discount), "nights": list(self.nights),
		        "value_added": self.value_added, "source": self.source, "code": self.code}


def promo_ref(p: Promotion) -> RuleRef:
	return RuleRef("promotion", p.promo_id, None, p.source, p.name)


def eligible_nights(p: Promotion, ctx: PromoContext) -> tuple[date, ...]:
	if not p.stay_from and not p.stay_to:
		return ctx.nights
	lo = p.stay_from or date.min
	hi = p.stay_to or date.max
	if p.stay_match == StayMatch.ANY_NIGHT:
		return tuple(n for n in ctx.nights if lo <= n <= hi)
	if p.stay_match == StayMatch.ALL_NIGHTS:
		return ctx.nights if all(lo <= n <= hi for n in ctx.nights) else ()
	if p.stay_match == StayMatch.ARRIVAL:
		return ctx.nights if lo <= ctx.check_in <= hi else ()
	if p.stay_match == StayMatch.DEPARTURE:
		return ctx.nights if lo <= ctx.check_out <= hi else ()
	return ()


def check_eligibility(p: Promotion, ctx: PromoContext, usage: tuple[int, int] | None = None) -> str | None:
	"""None when eligible, else the rejection reason."""
	if p.code and p.code.upper() not in ctx.codes:
		return "code not entered"
	if p.sale_from and ctx.sale_date < p.sale_from:
		return f"sale date {ctx.sale_date} before {p.sale_from}"
	if p.sale_to and ctx.sale_date > p.sale_to:
		return f"sale date {ctx.sale_date} after {p.sale_to}"
	n = len(ctx.nights)
	if p.min_nights and n < p.min_nights:
		return f"stay of {n} nights is shorter than {p.min_nights}"
	if p.max_nights and n > p.max_nights:
		return f"stay of {n} nights is longer than {p.max_nights}"
	lead = (ctx.check_in - ctx.sale_date).days
	if p.min_lead_days is not None and lead < p.min_lead_days:
		return f"booked {lead} days before arrival; needs at least {p.min_lead_days}"
	if p.max_lead_days is not None and lead > p.max_lead_days:
		return f"booked {lead} days before arrival; allowed at most {p.max_lead_days}"
	if p.markets is not None and ctx.market not in p.markets:
		return f"market {ctx.market} not eligible"
	if p.channels is not None and ctx.channel not in p.channels:
		return f"channel {ctx.channel} not eligible"
	if p.room_types is not None and ctx.room_type not in p.room_types:
		return f"room {ctx.room_type} not eligible"
	if p.boards is not None and ctx.board not in p.boards:
		return f"board {ctx.board} not eligible"
	if p.rate_plans is not None and (ctx.rate_plan or "") not in p.rate_plans:
		return f"rate plan {ctx.rate_plan} not eligible"
	if p.contracts is not None and ctx.contract not in p.contracts:
		return "contract not eligible"
	if p.requires_extras is not None and not p.requires_extras <= ctx.extras:
		return "required package extras not selected"
	if p.member_only and not ctx.member:
		return "members only"
	if p.min_basket is not None and ctx.basket < D(p.min_basket):
		return f"basket {ctx.basket} below minimum {p.min_basket}"
	if usage is not None:
		total, guest = usage
		if p.usage_limit is not None and total >= p.usage_limit:
			return "usage limit reached"
		if p.per_guest_limit is not None and guest >= p.per_guest_limit:
			return "per-guest limit reached"
	if not eligible_nights(p, ctx):
		return "stay dates outside the promotion window"
	if p.value_type == PromoValueType.FREE_NIGHTS:
		if not p.free_nights_stay or p.free_nights_pay is None or p.free_nights_pay >= p.free_nights_stay:
			return "free-nights promotion misconfigured"
		if len(eligible_nights(p, ctx)) < p.free_nights_stay:
			return f"needs {p.free_nights_stay} eligible nights"
	return None


def select(promos: tuple[Promotion, ...], ctx: PromoContext,
           usage: dict[str, tuple[int, int]] | None = None) -> tuple[list[Promotion], list[PromoOutcome]]:
	"""Choose the promotions to apply. → (to_apply in order, rejected outcomes)."""
	usage = usage or {}
	ordered = sorted(promos, key=lambda p: (-p.priority, p.promo_id))
	eligible: list[Promotion] = []
	rejected: list[PromoOutcome] = []
	for p in ordered:
		reason = check_eligibility(p, ctx, usage.get(p.promo_id))
		if reason:
			rejected.append(PromoOutcome(p.promo_id, p.name, p.kind, False, reason, source=p.source, code=p.code))
		else:
			eligible.append(p)

	exclusive = [p for p in eligible if p.exclusive]
	if exclusive:
		chosen = exclusive[0]
		for p in eligible:
			if p is not chosen:
				rejected.append(PromoOutcome(p.promo_id, p.name, p.kind, False,
				                             f"excluded by exclusive promotion {chosen.promo_id}",
				                             source=p.source, code=p.code))
		return [chosen], rejected

	apply: list[Promotion] = []
	groups: dict[str, str] = {}
	closed_by: str | None = None
	for p in eligible:
		if closed_by:
			rejected.append(PromoOutcome(p.promo_id, p.name, p.kind, False,
			                             f"not combinable with {closed_by}", source=p.source, code=p.code))
			continue
		if p.group and p.group in groups:
			rejected.append(PromoOutcome(p.promo_id, p.name, p.kind, False,
			                             f"incompatible group '{p.group}' already used by {groups[p.group]}",
			                             source=p.source, code=p.code))
			continue
		if not p.stackable and apply:
			rejected.append(PromoOutcome(p.promo_id, p.name, p.kind, False,
			                             f"not stackable; {apply[0].promo_id} already applied",
			                             source=p.source, code=p.code))
			continue
		apply.append(p)
		if p.group:
			groups[p.group] = p.promo_id
		if not p.stackable:
			closed_by = p.promo_id
	return apply, rejected


def _fixed_in(p: Promotion, currency: str, fx: dict[str, FxSnapshot] | None) -> Decimal | None:
	"""Fixed promotion amount in ``currency`` (converted through an explicit snapshot)."""
	if not p.currency or p.currency == currency:
		return D(p.value)
	snap = (fx or {}).get(p.currency)
	if snap is None:
		return None
	return D(p.value) * snap.sell_rate


def apply_promotions(promos: list[Promotion], amounts: dict[date, Decimal], ctx: PromoContext,
                     stacking: StackingMode, currency: str, *, fx: dict[str, FxSnapshot] | None = None,
                     explain: Explanation | None = None, stage: str = "promotion"
                     ) -> tuple[dict[date, Decimal], list[PromoOutcome]]:
	"""Apply chosen promotions to per-night amounts. → (new amounts, outcomes)."""
	running = dict(amounts)
	base = dict(amounts)
	outcomes: list[PromoOutcome] = []
	for p in promos:
		nights = [n for n in eligible_nights(p, ctx) if n in running]
		before_total = sum(running.values(), ZERO)
		ref = promo_ref(p)
		if p.value_type == PromoValueType.VALUE_ADDED:
			outcomes.append(PromoOutcome(p.promo_id, p.name, p.kind, True, "applied", ZERO,
			                             tuple(n.isoformat() for n in nights), p.value_added, p.source, p.code))
			if explain is not None:
				explain.add(stage, "PROMO_VALUE_ADDED", "{name}: includes {what}", rule=ref,
				            name=p.name, what=p.value_added or "an inclusion")
			continue
		if p.value_type == PromoValueType.PERCENT:
			for n in nights:
				ref_amt = running[n] if stacking == StackingMode.SEQUENTIAL else base[n]
				running[n] = max(ZERO, running[n] - ref_amt * D(p.value) / HUNDRED)
		elif p.value_type == PromoValueType.MULTIPLIER:
			for n in nights:
				ref_amt = running[n] if stacking == StackingMode.SEQUENTIAL else base[n]
				running[n] = max(ZERO, running[n] - ref_amt * (ONE - D(p.value)))
		elif p.value_type == PromoValueType.FIXED_NIGHT:
			amt = _fixed_in(p, currency, fx)
			if amt is None:
				outcomes.append(PromoOutcome(p.promo_id, p.name, p.kind, False,
				                             f"no FX to convert {p.currency}", source=p.source, code=p.code))
				continue
			for n in nights:
				running[n] = max(ZERO, running[n] - amt)
		elif p.value_type == PromoValueType.FIXED_STAY:
			amt = _fixed_in(p, currency, fx)
			if amt is None:
				outcomes.append(PromoOutcome(p.promo_id, p.name, p.kind, False,
				                             f"no FX to convert {p.currency}", source=p.source, code=p.code))
				continue
			# spread over eligible nights, latest night first, never below zero
			left = amt
			for n in sorted(nights, reverse=True):
				take = min(left, running[n])
				running[n] -= take
				left -= take
				if left <= ZERO:
					break
		elif p.value_type == PromoValueType.FREE_NIGHTS:
			blocks = len(nights) // p.free_nights_stay
			free = blocks * (p.free_nights_stay - p.free_nights_pay)
			# the cheapest eligible nights are free; ties broken by the later date
			for n in sorted(nights, key=lambda d: (running[d], -d.toordinal()))[:free]:
				running[n] = ZERO
		after_total = sum(running.values(), ZERO)
		discount = before_total - after_total
		outcomes.append(PromoOutcome(p.promo_id, p.name, p.kind, True, "applied", discount,
		                             tuple(n.isoformat() for n in nights), "", p.source, p.code))
		if explain is not None:
			explain.add(stage, "PROMO_APPLIED", "{name}: −{discount} on {count} night(s)",
			            before=before_total, after=after_total, currency=currency, rule=ref,
			            name=p.name, discount=discount, count=len(nights))
	return running, outcomes


def explain_rejections(rejected: list[PromoOutcome], explain: Explanation | None, stage: str) -> None:
	if explain is None:
		return
	for r in rejected:
		explain.add(stage, "PROMO_REJECTED", "{name} not applied: {reason}",
		            rule=RuleRef("promotion", r.promo_id, None, r.source, r.name), name=r.name, reason=r.reason)


@dataclass
class PromoResult:
	amounts: dict[date, Decimal]
	outcomes: list[PromoOutcome] = field(default_factory=list)
