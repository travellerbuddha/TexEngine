"""PromotionResolver (R-18, R-20).

Eligibility is evaluated for every candidate and each one is reported as
``applied`` or ``rejected`` with a reason. Combination is deterministic:

1. candidates sorted by (priority desc, promo_id); an eligible promotion the room cannot use
   (a fixed amount without a rate to the sell currency; on the total or the extras, a value type
   other than a percentage or a fixed amount, extras that are not there, or a fixed amount on a
   booking's later room) is refused first, so it never excludes or closes out one it can (O-1);
2. if any eligible promotion is ``exclusive``, the highest-priority exclusive one is the
   only promotion applied; all others are rejected "excluded by <id>";
3. otherwise, in order: a promotion in an ``incompatible group`` already used is rejected (of
   one group the highest priority applies, on equal priority the lowest id: the older one, not the
   better one; ``group_ties`` finds such pairs, D-3);
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
from kamra.tex.pricing.enums import PromoAppliesTo, PromoValueType, StackingMode, StayMatch
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
	# of several rooms (G-84, ADR-057)
	booking_basket: Decimal | None = None
	booking_rooms: int = 1
	# per promotion, the basket of the booking's rooms it covers — the rooms eligible for it on
	# every other check — and how many: its minimum basket is compared with it (G-84 review M2).
	# A promotion absent here is compared with ``booking_basket`` (a request recorded before), or
	# with this room's own basket when the room is priced alone
	booking_baskets: dict[str, tuple[Decimal, int]] | None = None
	# the booking's room this is (0: its first) and, at the SELL stage, the room's extras in the sell
	# currency: what a discount on the total or the extras can use (O-1). None at the COST stage,
	# which lowers the accommodation's cost only
	room_index: int = 0
	extras_total: Decimal | None = None
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
	# COST: a cost-stage offer (it lowers the contract cost: its discount, and a basket it was
	# compared with, are cost figures, shown only with price.view_cost); SELL otherwise
	stage: str = "SELL"
	# how a refusal is explained when it is not PROMO_REJECTED (O-1): PROMO_NO_FX with the pair it
	# had no rate for, or COUPON_REJECTED; neither is part of the outcome's identity or its dict
	explain_code: str = field(default="", compare=False)
	fx_pair: tuple[str, str] | None = field(default=None, compare=False)

	def to_dict(self) -> dict:
		from kamra.tex.money import to_str6

		out = {"promo_id": self.promo_id, "name": self.name, "kind": self.kind, "applied": self.applied,
		       "reason": self.reason, "discount": to_str6(self.discount), "nights": list(self.nights),
		       "value_added": self.value_added, "source": self.source, "code": self.code, "stage": self.stage}
		if self.rule:
			out.update(rule=self.rule, minimum=to_str6(self.minimum))
		return out


MIN_BASKET = "MIN_BASKET"
PROMO_NO_FX = "PROMO_NO_FX"
COUPON_REJECTED = "COUPON_REJECTED"


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


def _conditions(p: Promotion, ctx: PromoContext, usage: tuple[int, int] | None, *, basket: bool = True
                ) -> tuple[str | None, Decimal | None]:
	"""The minimum basket is the last check: a promotion refused for it is eligible on every
	other one (G-84 review M2). ``basket=False`` leaves it out."""
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
	if basket and p.min_basket is not None:
		return _min_basket(p, ctx)
	return None, None


def minimum_in_sell(p: Promotion, ctx: PromoContext) -> Decimal | None:
	"""The minimum basket in the sell currency: the threshold is in the promotion's (G-08)."""
	return in_currency(p.min_basket, p.currency, ctx.sell_currency, ctx.fx, log=ctx.fx_log,
	                   use=f"promotion:{p.promo_id}:min_basket")


def judged_basket(promo_id: str, ctx: PromoContext) -> tuple[Decimal, int, bool]:
	"""(the basket a minimum is compared with, how many rooms make it, whether it is the
	booking's): the basket of the booking's rooms the promotion covers (G-84 review M2), the whole
	booking's (a request recorded before), or this room's own."""
	if ctx.booking_baskets and promo_id in ctx.booking_baskets:
		b, n = ctx.booking_baskets[promo_id]
		return b, n, True
	if ctx.booking_basket is not None:
		return ctx.booking_basket, ctx.booking_rooms, True
	return ctx.basket, 1, False


def _min_basket(p: Promotion, ctx: PromoContext) -> tuple[str | None, Decimal | None]:
	minimum = minimum_in_sell(p, ctx)
	if minimum is None:
		return f"no FX to compare the minimum basket in {p.currency} with {ctx.sell_currency}", None
	basket, rooms, booking = judged_basket(p.promo_id, ctx)
	if basket >= minimum:
		return None, None
	if booking:
		return (f"booking basket {quantize(basket, ctx.sell_currency)} {ctx.sell_currency} ({rooms} rooms) "
		        f"below minimum {minimum}", minimum)
	return f"basket {basket} {ctx.sell_currency} below minimum {minimum}", minimum


def basket_minimums(promos, ctx: PromoContext, usage: dict[str, tuple[int, int]] | None = None
                    ) -> dict[str, Decimal]:
	"""{promotion: its minimum basket in the sell currency} of the promotions with a minimum that
	this room is eligible for on every other check: the rooms whose baskets make that promotion's
	booking basket (G-84 review M2). A minimum without an FX rate is left out (the promotion is
	refused for it)."""
	usage = usage or {}
	out: dict[str, Decimal] = {}
	for p in promos:
		if p.min_basket is None or invalid_value(p) or _conditions(p, ctx, usage.get(p.promo_id), basket=False)[0]:
			continue
		minimum = minimum_in_sell(p, ctx)
		if minimum is not None:
			out[p.promo_id] = minimum
	return out


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
		elif refused := unusable(p, ctx):
			rejected.append(refused)
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


def _overlap(lo1: date | None, hi1: date | None, lo2: date | None, hi2: date | None) -> bool:
	"""Two inclusive date windows meet. An empty start is "since always", an empty end "for ever"
	(a promotion's sale and stay windows are nullable)."""
	return max(lo1 or date.min, lo2 or date.min) <= min(hi1 or date.max, hi2 or date.max)


def group_ties(p: Promotion, others) -> list[Promotion]:
	"""The promotions of ``others`` that ``p`` ties with in its group (O-4, D-3): the same group and
	priority, sale and stay windows that meet. Of such a pair ``select`` applies the lowest id (the
	older promotion), whichever is the better offer, so the owner is told."""
	if not p.group:
		return []
	return [o for o in others if o.promo_id != p.promo_id and o.group == p.group and o.priority == p.priority
	        and _overlap(p.sale_from, p.sale_to, o.sale_from, o.sale_to)
	        and _overlap(p.stay_from, p.stay_to, o.stay_from, o.stay_to)]


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


FIXED_VALUES = frozenset({PromoValueType.FIXED_STAY, PromoValueType.FIXED_NIGHT})


def offer_currency(value_type: PromoValueType, currency: str | None, contract_currency: str) -> str | None:
	"""The currency of a contract offer's amount (K-1): a fixed amount is in the contract's
	currency, as the contract screen shows it, also when a payload frozen before offers carried
	one has none; a percentage, multiplier or free nights keeps what it has (none)."""
	if value_type not in FIXED_VALUES:
		return currency or None
	return (currency or contract_currency).upper()


def _fixed_in(p: Promotion, currency: str, fx: dict[str, FxSnapshot] | None,
              log: FxLog | None = None) -> Decimal | None:
	"""Fixed promotion amount in ``currency`` (converted through an explicit snapshot)."""
	return in_currency(p.value, p.currency, currency, fx, log=log, use=f"promotion:{p.promo_id}")


BASKET_VALUES = frozenset({PromoValueType.PERCENT, PromoValueType.FIXED_STAY})


def unusable(p: Promotion, ctx: PromoContext) -> PromoOutcome | None:
	"""An eligible promotion this room cannot use (O-1), refused before the combination step with
	the reason and explanation it was refused with once chosen, in the same order: on the total or the
	extras (SELL stage), a fixed amount on a booking's later room (G-06, ADR-029) or a value type other
	than a percentage or a fixed amount for the stay; a fixed amount without a rate to the sell
	currency (K-1); an extras discount on a room without extras. None when it can be used."""
	def refused(reason: str, explain_code: str, fx_pair: tuple[str, str] | None = None) -> PromoOutcome:
		return PromoOutcome(p.promo_id, p.name, p.kind, False, reason, source=p.source, code=p.code,
		                    explain_code=explain_code, fx_pair=fx_pair)

	basket = ctx.extras_total is not None and p.applies_to != PromoAppliesTo.ACCOMMODATION
	if basket and ctx.room_index >= 1 and p.value_type != PromoValueType.PERCENT:
		# a fixed discount on the complete booking (or its extras) is granted once, on room 1; a
		# percentage is the same share of every room
		return refused("fixed booking discount granted once per booking, on room 1", COUPON_REJECTED)
	if basket and p.value_type not in BASKET_VALUES:
		return refused(f"{p.value_type.value} is not supported on {p.applies_to.value}", COUPON_REJECTED)
	if p.value_type in FIXED_VALUES and _fixed_in(p, ctx.sell_currency, ctx.fx) is None:
		return refused(f"no FX to convert {p.currency}", PROMO_NO_FX, (p.currency, ctx.sell_currency))
	if basket and p.applies_to == PromoAppliesTo.EXTRAS and ctx.extras_total <= ZERO:
		return refused("nothing to discount", COUPON_REJECTED)
	return None


def _explain_no_fx(explain: Explanation, stage: str, rule: RuleRef, name: str, pair: tuple[str, str]) -> None:
	explain.add(stage, PROMO_NO_FX,
	            "{name} not applied: no FX rate {from_currency}→{to_currency} to convert its fixed amount",
	            rule=rule, name=name, from_currency=pair[0], to_currency=pair[1])


def _no_fx(p: Promotion, currency: str, explain: Explanation | None, stage: str) -> PromoOutcome:
	"""A fixed amount without a rate to the sell currency is not applied: never the raw figure,
	never zero; the explanation names the missing pair (K-1). ``select`` refuses it first (O-1)."""
	if explain is not None:
		_explain_no_fx(explain, stage, promo_ref(p), p.name, (p.currency, currency))
	return PromoOutcome(p.promo_id, p.name, p.kind, False, f"no FX to convert {p.currency}", source=p.source,
	                    code=p.code)


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
				outcomes.append(_no_fx(p, currency, explain, stage))
				continue
			for n in nights:
				running[n] = max(ZERO, running[n] - amt)
		elif p.value_type == PromoValueType.FIXED_STAY:
			amt = _fixed_in(p, currency, fx, fx_log)
			if amt is None:
				outcomes.append(_no_fx(p, currency, explain, stage))
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
		rule = RuleRef("promotion", r.promo_id, None, r.source, r.name)
		if r.explain_code == PROMO_NO_FX:
			_explain_no_fx(explain, stage, rule, r.name, r.fx_pair)
		elif r.explain_code == COUPON_REJECTED:
			explain.add("coupon", COUPON_REJECTED, "{name}: {reason}", rule=rule, name=r.name, reason=r.reason)
		else:
			explain.add(stage, "PROMO_REJECTED", "{name} not applied: {reason}", rule=rule, name=r.name,
			            reason=r.reason)


@dataclass
class PromoResult:
	amounts: dict[date, Decimal]
	outcomes: list[PromoOutcome] = field(default_factory=list)
