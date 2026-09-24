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
from typing import TYPE_CHECKING

from kamra.tex.money import HUNDRED, ONE, ZERO, D, quantize
from kamra.tex.pricing.enums import PromoValueType, StackingMode, StayMatch
from kamra.tex.pricing.explain import Explanation
from kamra.tex.pricing.model import FxSnapshot, Promotion, RuleRef

if TYPE_CHECKING:
	from kamra.tex.pricing.fx import FxLog


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
	basket: Decimal                 # this room's accommodation (+extras) value used for min_basket
	sell_currency: str
	fx: dict[str, FxSnapshot] | None = None   # promotion currency → sell_currency (thresholds)
	# the whole booking's basket and its number of rooms, when the room is priced in a booking
	# of several rooms: the minimum basket is compared with it (G-84, ADR-057)
	booking_basket: Decimal | None = None
	booking_rooms: int = 1
	# records the rates a threshold was converted with (G-56); not part of the context's identity
	fx_log: FxLog | None = field(default=None, compare=False, hash=False)


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
	# why it was refused, when a later step must know it: MIN_BASKET (the basket it was compared
	# with was below ``minimum``, the threshold in the sell currency; G-84)
	rule: str = ""
	minimum: Decimal | None = None

	def to_dict(self) -> dict:
		from kamra.tex.money import to_str6

		out = {"promo_id": self.promo_id, "name": self.name, "kind": self.kind, "applied": self.applied,
		       "reason": self.reason, "discount": to_str6(self.discount), "nights": list(self.nights),
		       "value_added": self.value_added, "source": self.source, "code": self.code}
		if self.rule:
			out.update(rule=self.rule, minimum=to_str6(self.minimum))
		return out


MIN_BASKET = "MIN_BASKET"


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


def invalid_value(p: Promotion) -> str | None:
	"""A promotion only ever lowers the price (G-18): a multiplier above 1 or a negative
	fixed amount would be a surcharge shown as a discount."""
	v = D(p.value)
	if p.value_type == PromoValueType.PERCENT and not (ZERO < v <= HUNDRED):
		return "invalid value: a percentage must be above 0 and at most 100"
	if p.value_type == PromoValueType.MULTIPLIER and not (ZERO < v <= ONE):
		return "invalid value: a multiplier must be above 0 and at most 1"
	if p.value_type in (PromoValueType.FIXED_STAY, PromoValueType.FIXED_NIGHT) and v <= ZERO:
		return "invalid value: a fixed discount must be positive"
	return None


def check_eligibility(p: Promotion, ctx: PromoContext, usage: tuple[int, int] | None = None) -> str | None:
	"""None when eligible, else the rejection reason."""
	return _eligibility(p, ctx, usage)[0]


def _eligibility(p: Promotion, ctx: PromoContext, usage: tuple[int, int] | None = None
                 ) -> tuple[str | None, Decimal | None]:
	"""→ (rejection reason or None, the minimum basket in the sell currency when the basket was
	what refused it)."""
	bad = invalid_value(p)
	if bad:
		return bad, None
	return _conditions(p, ctx, usage)


def _conditions(p: Promotion, ctx: PromoContext, usage: tuple[int, int] | None
                ) -> tuple[str | None, Decimal | None]:
	if p.code and p.code.upper() not in ctx.codes:
		return "code not entered", None
	if p.sale_from and ctx.sale_date < p.sale_from:
		return f"sale date {ctx.sale_date} before {p.sale_from}", None
	if p.sale_to and ctx.sale_date > p.sale_to:
		return f"sale date {ctx.sale_date} after {p.sale_to}", None
	n = len(ctx.nights)
	if p.min_nights and n < p.min_nights:
		return f"stay of {n} nights is shorter than {p.min_nights}", None
	if p.max_nights and n > p.max_nights:
		return f"stay of {n} nights is longer than {p.max_nights}", None
	lead = (ctx.check_in - ctx.sale_date).days
	if p.min_lead_days is not None and lead < p.min_lead_days:
		return f"booked {lead} days before arrival; needs at least {p.min_lead_days}", None
	if p.max_lead_days is not None and lead > p.max_lead_days:
		return f"booked {lead} days before arrival; allowed at most {p.max_lead_days}", None
	if p.markets is not None and ctx.market not in p.markets:
		return f"market {ctx.market} not eligible", None
	if p.channels is not None and ctx.channel not in p.channels:
		return f"channel {ctx.channel} not eligible", None
	if p.room_types is not None and ctx.room_type not in p.room_types:
		return f"room {ctx.room_type} not eligible", None
	if p.boards is not None and ctx.board not in p.boards:
		return f"board {ctx.board} not eligible", None
	if p.rate_plans is not None and (ctx.rate_plan or "") not in p.rate_plans:
		return f"rate plan {ctx.rate_plan} not eligible", None
	if p.contracts is not None and ctx.contract not in p.contracts:
		return "contract not eligible", None
	if p.requires_extras is not None and not p.requires_extras <= ctx.extras:
		return "required package extras not selected", None
	if p.member_only and not ctx.member:
		return "members only", None
	if p.min_basket is not None:
		# the threshold is in the promotion's currency; the basket in the sell currency (G-08)
		minimum = in_currency(p.min_basket, p.currency, ctx.sell_currency, ctx.fx, log=ctx.fx_log,
		                      use=f"promotion:{p.promo_id}:min_basket")
		if minimum is None:
			return f"no FX to compare the minimum basket in {p.currency} with {ctx.sell_currency}", None
		# the whole booking's basket when the room is priced in a booking of several rooms (G-84)
		if ctx.booking_basket is not None:
			if ctx.booking_basket < minimum:
				return (f"booking basket {quantize(ctx.booking_basket, ctx.sell_currency)} {ctx.sell_currency} "
				        f"({ctx.booking_rooms} rooms) below minimum {minimum}", minimum)
		elif ctx.basket < minimum:
			return f"basket {ctx.basket} {ctx.sell_currency} below minimum {minimum}", minimum
	if usage is not None:
		total, guest = usage
		if p.usage_limit is not None and total >= p.usage_limit:
			return "usage limit reached", None
		if p.per_guest_limit is not None and guest >= p.per_guest_limit:
			return "per-guest limit reached", None
	if not eligible_nights(p, ctx):
		return "stay dates outside the promotion window", None
	if p.value_type == PromoValueType.FREE_NIGHTS:
		if not p.free_nights_stay or p.free_nights_pay is None or p.free_nights_pay >= p.free_nights_stay:
			return "free-nights promotion misconfigured", None
		if len(eligible_nights(p, ctx)) < p.free_nights_stay:
			return f"needs {p.free_nights_stay} eligible nights", None
	return None, None


def select(promos: tuple[Promotion, ...], ctx: PromoContext,
           usage: dict[str, tuple[int, int]] | None = None) -> tuple[list[Promotion], list[PromoOutcome]]:
	"""Choose the promotions to apply. → (to_apply in order, rejected outcomes)."""
	usage = usage or {}
	ordered = sorted(promos, key=lambda p: (-p.priority, p.promo_id))
	eligible: list[Promotion] = []
	rejected: list[PromoOutcome] = []
	for p in ordered:
		reason, minimum = _eligibility(p, ctx, usage.get(p.promo_id))
		if reason:
			rejected.append(PromoOutcome(p.promo_id, p.name, p.kind, False, reason, source=p.source, code=p.code,
			                             rule=MIN_BASKET if minimum is not None else "", minimum=minimum))
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


def in_currency(amount, from_ccy: str | None, to_ccy: str, fx: dict[str, FxSnapshot] | None, *,
                log: FxLog | None = None, use: str = "") -> Decimal | None:
	"""``amount`` in ``to_ccy`` through an explicit snapshot; None when there is no rate.
	An amount without a currency is already in ``to_ccy``. ``log`` records the rate used
	(G-56) as ``use``."""
	if not from_ccy or from_ccy == to_ccy:
		return D(amount)
	snap = (fx or {}).get(from_ccy)
	if snap is None or snap.to_currency != to_ccy:
		return None
	if log is not None:
		log.note(snap, use)
	return D(amount) * snap.sell_rate


def _fixed_in(p: Promotion, currency: str, fx: dict[str, FxSnapshot] | None,
              log: FxLog | None = None) -> Decimal | None:
	"""Fixed promotion amount in ``currency`` (converted through an explicit snapshot)."""
	return in_currency(p.value, p.currency, currency, fx, log=log, use=f"promotion:{p.promo_id}")


def apply_promotions(promos: list[Promotion], amounts: dict[date, Decimal], ctx: PromoContext,
                     stacking: StackingMode, currency: str, *, fx: dict[str, FxSnapshot] | None = None,
                     explain: Explanation | None = None, stage: str = "promotion", fx_log: FxLog | None = None
                     ) -> tuple[dict[date, Decimal], list[PromoOutcome]]:
	"""Apply chosen promotions to per-night amounts. → (new amounts, outcomes). ``fx_log``
	records the rate a fixed amount in another currency is converted with (G-56)."""
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
			amt = _fixed_in(p, currency, fx, fx_log)
			if amt is None:
				outcomes.append(PromoOutcome(p.promo_id, p.name, p.kind, False,
				                             f"no FX to convert {p.currency}", source=p.source, code=p.code))
				continue
			for n in nights:
				running[n] = max(ZERO, running[n] - amt)
		elif p.value_type == PromoValueType.FIXED_STAY:
			amt = _fixed_in(p, currency, fx, fx_log)
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
