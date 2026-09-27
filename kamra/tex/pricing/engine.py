"""QuoteBuilder — the TEX pricing pipeline (TARGET_ARCHITECTURE §3).

``price_stay(ctx, request)`` prices ONE room for ONE stay. It is a pure,
deterministic function: the same context and request always produce the same
quote, including a byte-identical explanation. It never touches a database and
never guesses: anything it cannot price makes the quote unsellable with reasons.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field, replace
from datetime import date, timedelta
from decimal import Decimal

from kamra.tex.money import HUNDRED, ONE, ZERO, D, calc, quantize, to_str, to_str6
from kamra.tex.pricing import (
	ages,
	boards,
	extras,
	fx,
	markup,
	occupancy,
	policy_money,
	promotions,
	rooms,
	tax,
)
from kamra.tex.pricing.enums import (
	ExtraPricingMode,
	Level,
	LineKind,
	Op,
	PromoAppliesTo,
	PromoStage,
	PromoValueType,
)
from kamra.tex.pricing.explain import Explanation
from kamra.tex.pricing.model import (
	ExtraRequest,
	PricingContext,
	PricingError,
	Promotion,
	RuleRef,
	StayRequest,
	Unsellable,
)
from kamra.tex.pricing.ops import apply_op, describe_op

ENGINE_VERSION = "tex-pricing/1.0"
GLOBAL_MARKET = "GLOBAL"
MAX_NIGHTS = 90


@dataclass(frozen=True, slots=True)
class NightPrice:
	night: date
	period: str
	unit: Decimal
	occupancy: Decimal
	board: Decimal
	cost: Decimal              # contract currency, before COST offers
	cost_net: Decimal = ZERO   # after COST offers
	sell_contract: Decimal = ZERO   # after markup, contract currency
	sell: Decimal = ZERO       # sell currency, before SELL promotions
	final: Decimal = ZERO      # sell currency, after accommodation promotions
	# the night's running totals, reported for the Explain ladder (ADR-061 GAP-12): in the dict only
	# when asked for (the workspace's price test); a stored quote keeps main's keys
	subtotal_adults: Decimal = ZERO     # the unit priced for the adults (ROOM basis: room + extra adults)
	subtotal_children: Decimal = ZERO   # … + the children, before a whole-combination rule
	subtotal_board: Decimal = ZERO      # occupancy + board, before the period adjustment

	def to_dict(self, *, subtotals: bool = False) -> dict:
		q = to_str6
		out = {"date": self.night.isoformat(), "period": self.period, "unit": q(self.unit),
		       "occupancy": q(self.occupancy), "board": q(self.board), "cost": q(self.cost),
		       "cost_net": q(self.cost_net), "sell_contract": q(self.sell_contract), "sell": q(self.sell),
		       "final": q(self.final)}
		if subtotals:
			out.update(subtotal_adults=q(self.subtotal_adults), subtotal_children=q(self.subtotal_children),
			           subtotal_board=q(self.subtotal_board))
		return out


@dataclass(frozen=True, slots=True)
class QuoteLine:
	kind: LineKind
	code: str
	description: str
	amount: Decimal            # rounded, sell currency (negative for discounts)
	quantity: Decimal = ONE
	category: str = "ACCOMMODATION"
	included: bool = False     # tax included in other lines (informational)
	ref: str | None = None

	def to_dict(self) -> dict:
		return {"kind": self.kind.value, "code": self.code, "description": self.description,
		        "amount": to_str(self.amount), "quantity": to_str(self.quantity), "category": self.category,
		        "included": self.included, "ref": self.ref}


# totals only staff with cost access may see (supplier cost, margin)
INTERNAL_TOTALS = ("cost", "margin", "margin_percent", "cost_contract_currency")
COST = PromoStage.COST.value         # the stage of a promotion outcome only cost access may see


@dataclass(frozen=True, slots=True)
class BasketTerm:
	"""A SELL promotion with a minimum basket this room is eligible for on every other check
	(G-84, ADR-057 and its review): its minimum in the sell currency, the basket it was compared
	with (this room's, or the basket of the booking's rooms it covers, over ``rooms`` rooms),
	whether that basket reached the minimum and whether the promotion applied to this room.
	``forfeit``: granted only on the booking's basket (this room's own is below the minimum), what
	the room costs more without it — its total, the part before added tax (``forfeit_net``) and
	the tax in it (``forfeit_tax``); never below zero. A change that takes the booking below the
	minimum charges it to the changed room (review H1)."""

	promo_id: str
	name: str
	code: str | None
	minimum: Decimal
	basket: Decimal
	rooms: int
	qualified: bool
	applied: bool
	forfeit: Decimal = ZERO
	forfeit_net: Decimal = ZERO
	forfeit_tax: Decimal = ZERO

	def to_dict(self) -> dict:
		return {"promo_id": self.promo_id, "name": self.name, "code": self.code, "minimum": to_str6(self.minimum),
		        "basket": to_str6(self.basket), "rooms": self.rooms, "qualified": self.qualified,
		        "applied": self.applied, "forfeit": to_str(self.forfeit), "forfeit_net": to_str(self.forfeit_net),
		        "forfeit_tax": to_str(self.forfeit_tax)}


@dataclass
class RoomQuote:
	request: StayRequest
	sellable: bool
	currency: str
	reasons: list[dict] = field(default_factory=list)
	contract: dict = field(default_factory=dict)
	nights: list[NightPrice] = field(default_factory=list)
	lines: list[QuoteLine] = field(default_factory=list)
	promotions: list[promotions.PromoOutcome] = field(default_factory=list)
	extras: list[extras.ExtraOutcome] = field(default_factory=list)
	taxes: list[tax.TaxLine] = field(default_factory=list)
	fx: dict | None = None
	# every conversion the quote made: rate, source, policy and what it converted (G-56)
	fx_rates: list[dict] = field(default_factory=list)
	totals: dict[str, Decimal] = field(default_factory=dict)
	rate_plan: dict | None = None
	explanation: Explanation = field(default_factory=Explanation)
	engine_version: str = ENGINE_VERSION
	# this room's basket: its accommodation before promotions and its extras, in the sell
	# currency. A minimum basket compares with it, or with the booking's basket: the sum of every
	# room's basket as recorded (6 places, ``recorded_basket``; G-84, ADR-057)
	basket: Decimal | None = None
	# the promotions with a minimum basket this room is eligible for (``BasketTerm``)
	basket_terms: list[BasketTerm] = field(default_factory=list)

	@property
	def total(self) -> Decimal:
		return self.totals.get("total", ZERO)

	def to_dict(self, *, internal: bool = True, subtotals: bool = False) -> dict:
		"""JSON-safe dict. ``internal=False`` strips cost/margin and the rule-level
		explanation (guest-facing). ``subtotals``: each internal night also reports its running
		subtotals (the Pricing Workspace's price test, ADR-061 GAP-12; opt-in, so a TEX Quote, a
		reservation snapshot and every other caller keep main's keys)."""
		from kamra.tex.pricing.serialize import request_to_dict

		totals = {k: to_str(v) for k, v in self.totals.items()}
		if not internal:
			for k in INTERNAL_TOTALS:
				totals.pop(k, None)
		out = {
			"engine_version": self.engine_version,
			"sellable": self.sellable,
			"reasons": self.reasons,
			"currency": self.currency,
			"request": request_to_dict(self.request),
			"contract": self.contract,
			"rate_plan": self.rate_plan,
			"lines": [ln.to_dict() for ln in self.lines],
			# a cost-stage outcome is a cost figure (ADR-059 review): internal only
			"promotions": [p.to_dict() for p in self.promotions if internal or (p.applied and p.stage != COST)],
			"extras": [e.to_dict() for e in self.extras],
			"taxes": [t.to_dict() for t in self.taxes],
			"totals": totals,
		}
		if self.basket is not None:
			out["basket"] = to_str6(self.basket)
		if internal:
			out["minimum_baskets"] = [t.to_dict() for t in self.basket_terms]
		if internal:
			out["fx"] = self.fx
			out["fx_rates"] = self.fx_rates
			out["nights"] = [n.to_dict(subtotals=subtotals) for n in self.nights]
			out["explanation"] = self.explanation.to_list()
		else:
			out["nights"] = [{"date": n.night.isoformat(), "amount": to_str(quantize(n.final, self.currency))}
			                 for n in self.nights]
		return out


def _nights(check_in: date, check_out: date) -> tuple[date, ...]:
	n = (check_out - check_in).days
	return tuple(check_in + timedelta(days=i) for i in range(n))


def _allocate(total: Decimal, weights: dict[str, Decimal], currency: str) -> dict[str, Decimal]:
	"""Split a rounded amount over categories proportionally; remainder to the largest."""
	if not weights or total == ZERO:
		return {k: ZERO for k in weights}
	s = sum(weights.values(), ZERO)
	if s <= ZERO:
		return {k: ZERO for k in weights}
	alloc = {k: quantize(total * w / s, currency) for k, w in weights.items()}
	diff = total - sum(alloc.values(), ZERO)
	if diff:
		biggest = max(sorted(weights), key=lambda k: weights[k])
		alloc[biggest] += diff
	return alloc


def _check_contract(ctx: PricingContext, req: StayRequest, nights: tuple[date, ...], explain: Explanation):
	t = ctx.terms
	if req.property != t.property:
		raise PricingError(f"contract {t.contract_code} belongs to {t.property}, not {req.property}")
	if t.market not in (req.market, GLOBAL_MARKET):
		raise Unsellable("MARKET_MISMATCH", f"contract market {t.market} does not serve market {req.market}")
	if t.channels is not None and req.channel not in t.channels:
		raise Unsellable("CHANNEL_NOT_ALLOWED", f"contract is not sold on channel {req.channel}")
	sale = req.sale_at.date()
	if t.sale_from and sale < t.sale_from:
		raise Unsellable("SALE_WINDOW", f"contract sales open on {t.sale_from.isoformat()}")
	if t.sale_to and sale > t.sale_to:
		raise Unsellable("SALE_WINDOW", f"contract sales closed on {t.sale_to.isoformat()}")
	if t.stay_from and nights[0] < t.stay_from:
		raise Unsellable("STAY_WINDOW", f"contract stays start on {t.stay_from.isoformat()}")
	if t.stay_to and nights[-1] > t.stay_to:
		raise Unsellable("STAY_WINDOW", f"contract stays end on {t.stay_to.isoformat()}")
	if req.room_type not in t.rooms:
		raise Unsellable("ROOM_NOT_IN_CONTRACT", f"{req.room_type} is not sold under {t.contract_code}")
	rp = None
	if req.rate_plan:
		rp = t.rate_plans.get(req.rate_plan)
		if rp is None:
			raise Unsellable("RATE_PLAN_NOT_IN_CONTRACT", f"rate plan {req.rate_plan} is not in this contract")
		if rp.boards is not None and req.board not in rp.boards:
			raise Unsellable("BOARD_NOT_IN_RATE_PLAN", f"board {req.board} is not sold with {rp.code}")
	elif t.rate_plans:
		raise PricingError("this contract has rate plans; the request must name one")
	explain.add("contract", "CONTRACT", "contract {code} v{version} ({market}, {currency}, {basis} basis)",
	            rule=RuleRef("contract_version", t.version_id, None, "version", t.contract_name),
	            code=t.contract_code, version=t.version_no, market=t.market, currency=t.currency,
	            basis=t.basis.value)
	return rp


def _contract_info(t) -> dict:
	return {"contract": t.contract_id, "code": t.contract_code, "name": t.contract_name,
	        "version": t.version_id, "version_no": t.version_no, "payload_hash": t.payload_hash,
	        "market": t.market, "currency": t.currency, "basis": t.basis.value}


def _unsellable(q: RoomQuote, u: Unsellable) -> RoomQuote:
	q.sellable = False
	q.reasons.append({"code": u.code, "message": u.message, **{k: v for k, v in u.params.items()
	                                                            if isinstance(v, str | int | list)}})
	q.explanation.add("unsellable", u.code, "not sellable: {reason}", reason=u.message)
	q.totals = {}
	return q


def unsellable_quote(terms, req: StayRequest, u: Unsellable) -> RoomQuote:
	"""The quote of a stay whose selling context could not be built (no FX rate, an
	ambiguous or missing tax policy…): unsellable with the reason, like any other."""
	q = RoomQuote(request=req, sellable=True, currency=req.sell_currency.upper())
	q.contract = _contract_info(terms)
	return _unsellable(q, u)


def price_stay(ctx: PricingContext, req: StayRequest) -> RoomQuote:
	with calc():
		log = fx.FxLog()
		q = _price_stay(ctx, req, log)
		q.fx_rates = log.to_list()
		if q.sellable and req.booking_basket is not None:
			_forfeits(ctx, req, q)
		return q


def _without(ctx: PricingContext, promo_id: str) -> PricingContext:
	t = ctx.terms
	return replace(ctx, terms=replace(t, offers=tuple(p for p in t.offers if p.promo_id != promo_id)),
	               promotions=tuple(p for p in ctx.promotions if p.promo_id != promo_id))


def _forfeits(ctx: PricingContext, req: StayRequest, q: RoomQuote) -> None:
	"""A room priced in a booking: for each promotion granted only on the booking's basket (the
	room's own is below its minimum), what the room would cost without it — priced again without
	that promotion, everything else the same; never below zero (G-84 review H1)."""
	for i, t in enumerate(q.basket_terms):
		if not t.applied or q.basket >= t.minimum:
			continue                      # granted on the room's own basket: the booking never takes it back
		alone = _price_stay(_without(ctx, t.promo_id), req, fx.FxLog())
		if not alone.sellable or alone.currency != q.currency:
			continue
		more = alone.total - q.total
		if more <= ZERO:
			continue                      # another promotion would do at least as well
		net = min(more, max(ZERO, alone.totals["subtotal"] - q.totals["subtotal"]))
		tax_ = min(more, max(ZERO, alone.totals["tax"] - q.totals["tax"]))
		q.basket_terms[i] = replace(t, forfeit=more, forfeit_net=net, forfeit_tax=tax_)
		q.explanation.add("promotion", "BASKET_FORFEIT",
		                  "{name} is granted on the booking's basket ({basket} {currency} over {rooms} rooms, minimum "
		                  "{minimum}): without it this room costs {forfeit} more",
		                  rule=RuleRef("promotion", t.promo_id, None, "", t.name), currency=q.currency, name=t.name,
		                  basket=quantize(t.basket, q.currency), rooms=t.rooms, minimum=quantize(t.minimum, q.currency),
		                  forfeit=more)


# ─── the rooms of one booking (G-84, ADR-057) ────────────────────────────


def basket_limited(q: RoomQuote) -> bool:
	"""A SELL promotion of this room was refused because its basket was below the minimum: a
	larger basket (the booking's) may grant it."""
	return any(not p.applied and p.rule == promotions.MIN_BASKET for p in q.promotions)


def recorded_basket(q: RoomQuote) -> Decimal:
	"""A room's basket as its quote records it (6 places): what a booking's basket adds up."""
	return D(to_str6(q.basket))


def eligible_baskets(rooms) -> dict[str, tuple[Decimal, int]]:
	"""``rooms``: (basket, the promotions it is eligible for). → {promotion: (the sum of the
	baskets of the rooms eligible for it, how many)}: what each minimum is compared with (G-84
	review M2)."""
	out: dict[str, tuple[Decimal, int]] = {}
	for basket, promos in rooms:
		for pid in set(promos):
			b, n = out.get(pid, (ZERO, 0))
			out[pid] = (b + basket, n + 1)
	return out


def in_booking(req: StayRequest, total: Decimal, rooms: int, baskets: dict[str, tuple[Decimal, int]]
               ) -> StayRequest:
	"""``req`` recording the booking it is priced in: the whole booking's basket and size, and
	per promotion the basket of the rooms it covers."""
	return replace(req, booking_basket=total, booking_rooms=rooms,
	               booking_baskets=tuple(sorted((p, b, n) for p, (b, n) in baskets.items())))


def _one_booking(quotes: list[RoomQuote]) -> bool:
	return len(quotes) > 1 and all(q.sellable and q.basket is not None for q in quotes) \
		and len({q.currency for q in quotes}) == 1


def price_together(reqs: list[StayRequest], quotes: list[RoomQuote],
                   price: Callable[[int, StayRequest], RoomQuote], *, record: bool = True
                   ) -> tuple[list[RoomQuote], Decimal | None]:
	"""The rooms of one booking, priced alone as ``quotes``, as one booking (G-84, ADR-057): each
	promotion's minimum is compared with the basket of the rooms it covers (the rooms' recorded
	baskets, ``eligible_baskets``). When a minimum refused a promotion on a room and the rooms it
	covers reach it, every room ``i`` is priced again by ``price(i, request)`` with the booking
	recorded in its request; else the rooms priced alone are the answer, and — ``record`` — each
	records the booking it is in all the same (review L3): priced again when a promotion with a
	minimum could see it, so a request always prices to its quote. The booking pass can raise a
	price (an exclusive promotion granted on the booking's basket replaces a better one: review
	M1). → (quotes, the booking's basket, or None when the rooms are not one booking: fewer than
	two, one unsellable, or different sell currencies)."""
	if not _one_booking(quotes):
		return quotes, None
	total = sum((recorded_basket(q) for q in quotes), ZERO)
	baskets = eligible_baskets((recorded_basket(q), [t.promo_id for t in q.basket_terms]) for q in quotes)
	again = [in_booking(r, total, len(reqs), baskets) for r in reqs]
	grows = any(not t.qualified and baskets[t.promo_id][0] >= t.minimum for q in quotes for t in q.basket_terms)
	if grows or (record and any(q.basket_terms for q in quotes)):
		return [price(i, r) for i, r in enumerate(again)], total
	if record:
		for q, r in zip(quotes, again, strict=True):
			q.request = r                 # nothing in this room's price depends on the booking
	return quotes, total


def price_booking(rooms: list[tuple[PricingContext, StayRequest]]) -> list[RoomQuote]:
	"""Price the rooms of one booking together: alone, then ``price_together``. Deterministic."""
	reqs = [req for _ctx, req in rooms]
	return price_together(reqs, [price_stay(ctx, req) for ctx, req in rooms],
	                      lambda i, req: price_stay(rooms[i][0], req))[0]


@dataclass(frozen=True)
class BookingOthers:
	"""The other live rooms of a booking one room is priced again in (a change, the simulator):
	their baskets, how many, and per promotion the baskets of those it covers
	(``eligible_baskets``). ``promos`` None: a booking recorded before the review, whose rooms
	count for every promotion."""

	basket: Decimal
	rooms: int
	promos: dict[str, tuple[Decimal, int]] | None


def booking_request(req: StayRequest, quote: RoomQuote, others: BookingOthers) -> StayRequest | None:
	"""A room of a booking priced again on its own: ``req`` recording the booking it makes with
	``others`` — this room's new basket and theirs — or None when there are no other rooms or the
	room cannot be sold (it is its own booking)."""
	if others.rooms < 1 or not quote.sellable or quote.basket is None:
		return None
	own = recorded_basket(quote)
	if others.promos is None:
		baskets = {t.promo_id: (others.basket, others.rooms) for t in quote.basket_terms}
	else:
		baskets = dict(others.promos)
	for t in quote.basket_terms:
		b, n = baskets.get(t.promo_id, (ZERO, 0))
		baskets[t.promo_id] = (b + own, n + 1)
	return in_booking(req, own + others.basket, others.rooms + 1, baskets)


def price_in_booking(quote: RoomQuote, others: BookingOthers, price: Callable[[StayRequest], RoomQuote]
                     ) -> RoomQuote:
	"""``quote`` (a room priced alone) as a room of the booking it makes with ``others``: priced
	again by ``price`` when a promotion with a minimum basket could see the booking, else recording
	it (review L3). A room the booking cannot sell answers alone."""
	again = booking_request(quote.request, quote, others)
	if again is None:
		return quote
	if not quote.basket_terms:
		quote.request = again
		return quote
	q2 = price(again)
	return q2 if q2.sellable else quote


def _price_stay(ctx: PricingContext, req: StayRequest, log: fx.FxLog) -> RoomQuote:
	t = ctx.terms
	sell_ccy = req.sell_currency.upper()
	q = RoomQuote(request=req, sellable=True, currency=sell_ccy)
	ex = q.explanation
	q.contract = _contract_info(t)

	if req.check_out <= req.check_in:
		raise PricingError("check-out must be after check-in")
	nights = _nights(req.check_in, req.check_out)
	if len(nights) > MAX_NIGHTS:
		raise PricingError(f"stays longer than {MAX_NIGHTS} nights are priced by the reservations team")
	if ctx.fx.from_currency != t.currency or ctx.fx.to_currency != sell_ccy:
		raise PricingError(f"FX snapshot {ctx.fx.from_currency}→{ctx.fx.to_currency} does not match "
		                   f"{t.currency}→{sell_ccy}")
	sale_date = req.sale_at.date()

	try:
		rp = _check_contract(ctx, req, nights, ex)
		if rp is not None:
			# refundable only when the row and its cancellation policy both say so (Y-4, ADR-067)
			q.rate_plan = {"code": rp.code, "name": rp.name,
			               "refundable": policy_money.refundable(rp.refundable, rp.cancellation_policy),
			               "cancellation_policy": rp.cancellation_policy,
			               "payment_policy": rp.payment_policy, "inclusions": list(rp.inclusions)}
		party = ages.classify_party(t, req.adults, req.children, req.check_in, sale_date)
		for idx in party.children_as_adults:
			ex.add("occupancy", "CHILD_AS_ADULT", "child {n} is above the oldest child band: priced as adult",
			       n=idx + 1)
		spec = t.rooms[req.room_type]
		occupancy.check_capacity(spec, party, t.infants_count_as_occupants)

		# ── 1-7: nightly contract cost ──
		costs: dict[date, Decimal] = {}
		partial: dict[date, tuple] = {}
		for n in nights:
			period = rooms.period_for(t, n)
			if period is None:
				raise Unsellable("NO_PERIOD", f"no stay period covers {n.isoformat()}", night=n.isoformat())
			ex.add("period", "PERIOD", "period {period} ({name})", night=n, period=period.code, name=period.name)
			unit = rooms.room_unit(t, req.room_type, period, night=n, explain=ex)
			occ = occupancy.price_occupancy(t, spec, period, unit, party, night=n, explain=ex)
			brd = boards.price_board(t, req.board, req.room_type, period, party, occ.total, night=n, explain=ex)
			amount = occ.total + brd
			before_adjust = amount                     # reported as the night's subtotal_board (GAP-12)
			if period.adjustment_op and period.adjustment_op != Op.INHERIT:
				before = amount
				amount = apply_op(period.adjustment_op, period.adjustment_value, reference=amount, current=amount)
				ex.add("period", "PERIOD_ADJUSTMENT", "period {period} adjustment {op}", night=n, before=before,
				       after=amount, period=period.code, op=describe_op(period.adjustment_op, period.adjustment_value))
			if rp is not None and rp.op and rp.op != Op.INHERIT:
				before = amount
				amount = apply_op(rp.op, rp.value, reference=amount, current=amount)
				ex.add("rate_plan", "RATE_PLAN_ADJUSTMENT", "rate plan {code} {op}", night=n, before=before,
				       after=amount, rule=RuleRef("rate_plan", rp.code, None, "version", rp.name),
				       code=rp.code, op=describe_op(rp.op, rp.value))
			if amount < ZERO:
				raise Unsellable("NEGATIVE_PRICE", f"night {n.isoformat()} prices below zero")
			ex.add("night", "NIGHT_COST", "contract cost {amount} {currency}", night=n, after=amount,
			       currency=t.currency, amount=amount)
			costs[n] = amount
			partial[n] = (period.code, unit, occ.total, brd, occ.after_adults, occ.after_children, before_adjust)

		promo_ctx_base = dict(sale_date=sale_date, check_in=req.check_in, check_out=req.check_out, nights=nights,
		                      market=req.market, channel=req.channel, room_type=req.room_type, board=req.board,
		                      rate_plan=req.rate_plan, contract=t.contract_id, member=req.member,
		                      codes=frozenset(k for c in req.promo_codes if (k := promotions.code_key(c))),
		                      extras=frozenset(e.code for e in req.extras), room_index=req.room_index)

		# ── 8: COST-stage contract offers ──
		cost_promos = tuple(p for p in (*t.offers, *ctx.promotions) if p.stage == PromoStage.COST)
		cost_ctx = promotions.PromoContext(basket=sum(costs.values(), ZERO), sell_currency=t.currency,
		                                   **promo_ctx_base)
		chosen, rejected = promotions.select(cost_promos, cost_ctx, ctx.coupon_usage)
		# a cost-stage minimum is the room's supplier cost, in the contract's currency: never the
		# booking's basket, so it never asks for the rooms to be priced together (G-84)
		rejected = [replace(o, rule="", minimum=None, stage=COST) for o in rejected]
		promotions.explain_rejections(rejected, ex, "cost_offer")
		cost_net, cost_outcomes = promotions.apply_promotions(chosen, costs, cost_ctx, t.stacking, t.currency,
		                                                      explain=ex, stage="cost_offer")
		q.promotions.extend(replace(o, stage=COST) for o in cost_outcomes)
		q.promotions.extend(rejected)

		# ── 9-10: markup and FX ──
		scope = markup.MarkupScope(t.property, req.market, t.contract_id, req.room_type, req.channel, t.currency)
		sells_cc: dict[date, Decimal] = {}
		sells: dict[date, Decimal] = {}
		for n in nights:
			sells_cc[n] = markup.apply_markup(ctx.markups, scope, n, cost_net[n], explain=ex)
			sells[n] = sells_cc[n] * ctx.fx.sell_rate
		q.fx = ctx.fx.to_dict()
		log.note(ctx.fx, "accommodation")
		fx.explain_new(log, ex)

		# ── 12: extras (priced before promotions so min-basket can see them) ──
		ex_ctx = extras.ExtraContext(sale_date=sale_date, check_in=req.check_in, check_out=req.check_out,
		                             nights=len(nights), market=req.market, channel=req.channel,
		                             room_type=req.room_type, adults=party.adults,
		                             children=party.child_count - party.infants, infants=party.infants,
		                             sell_currency=sell_ccy)
		requested = {e.code: e for e in req.extras}
		lead_room = req.room_index == 0
		for code in sorted(ctx.extras):
			d = ctx.extras[code]
			# a per-booking extra belongs to the booking's first room only (G-05, ADR-029)
			if d.mandatory and code not in requested and (lead_room or d.pricing_mode != ExtraPricingMode.RESERVATION):
				requested[code] = ExtraRequest(code=code, quantity=1)
		for code in sorted(requested):
			d = ctx.extras.get(code)
			if d is None:
				q.extras.append(extras.ExtraOutcome(code=code, name=code, ok=False, reason="unknown extra"))
				continue
			if d.pricing_mode == ExtraPricingMode.RESERVATION and not lead_room:
				q.extras.append(extras.ExtraOutcome(code=code, name=d.name, ok=False, currency=sell_ccy,
				                                    pricing_mode=d.pricing_mode.value,
				                                    reason="charged once per booking, on room 1"))
				ex.add("extra", "EXTRA_REJECTED", "{name} not added: {reason}", name=d.name,
				       reason="charged once per booking, on room 1")
				continue
			outcome = extras.price_extra(d, requested[code], ex_ctx, ctx.extra_fx)
			if not outcome.ok and d.mandatory and (d.service_from or d.service_to) and \
				outcome.reason == "not available during this stay":
				continue   # mandatory seasonal extra outside this stay
			if outcome.ok:
				# a capacity-limited extra takes units on the days it is used (G-19)
				use = extras.usage(d, requested[code], ex_ctx)
				outcome = replace(outcome, usage=tuple((day.isoformat(), u) for day, u in use))
				days = (ctx.extra_availability or {}).get(code)
				refusal = extras.capacity_refusal(use, days) if days is not None else None
				if refusal:
					outcome = replace(outcome, ok=False, reason=refusal, amount=ZERO)
					ex.add("extra", "EXTRA_SOLD_OUT", "{name} not added: {reason}", name=d.name, reason=refusal,
					       rule=RuleRef("extra", d.code, Level.HOTEL, f"extra:{d.revision}" if d.revision else "",
					                    d.name))
					q.extras.append(outcome)
					if d.mandatory:
						raise Unsellable("MANDATORY_EXTRA", f"mandatory extra {d.name} cannot be priced: {refusal}")
					continue
			q.extras.append(outcome)
			if outcome.ok:
				ex.add("extra", "EXTRA", "{name}: {detail} = {amount}", after=outcome.amount, currency=sell_ccy,
				       rule=RuleRef("extra", d.code, Level.HOTEL, f"extra:{d.revision}" if d.revision else "",
				                    d.name),
				       name=d.name, detail=outcome.detail, amount=outcome.amount)
				if outcome.fx_rate is not None:
					log.note(ctx.extra_fx.get(d.currency), f"extra:{code}")
					fx.explain_new(log, ex)
			else:
				ex.add("extra", "EXTRA_REJECTED", "{name} not added: {reason}", name=d.name, reason=outcome.reason)
			if not outcome.ok and d.mandatory:
				raise Unsellable("MANDATORY_EXTRA", f"mandatory extra {d.name} cannot be priced: {outcome.reason}")
		extras_total = sum((e.amount for e in q.extras if e.ok), ZERO)

		# ── 11/13: SELL promotions and coupons (one combination decision) ──
		sell_promos = tuple(p for p in (*t.offers, *ctx.promotions) if p.stage == PromoStage.SELL)
		gross_accom = sum(sells.values(), ZERO)
		q.basket = gross_accom + extras_total
		sell_ctx = promotions.PromoContext(basket=q.basket, sell_currency=sell_ccy, fx=ctx.promo_fx, fx_log=log,
		                                   booking_basket=req.booking_basket, booking_rooms=req.booking_rooms,
		                                   booking_baskets={p: (b, n) for p, b, n in req.booking_baskets} or None,
		                                   extras_total=extras_total, **promo_ctx_base)
		# the promotions with a minimum basket this room is eligible for on every other check (G-84)
		minimums = promotions.basket_minimums(sell_promos, sell_ctx, ctx.coupon_usage)
		by_id = {p.promo_id: p for p in sell_promos}
		if req.booking_basket is not None and minimums:
			# priced in a booking of several rooms: a minimum basket is the booking's, counting the
			# rooms the promotion covers (G-84, ADR-057 and its review M2)
			ex.add("promotion", "BOOKING_BASKET",
			       "minimum baskets judged on the booking: {basket} {currency} over {rooms} rooms (this room {own})",
			       after=req.booking_basket, currency=sell_ccy, basket=quantize(req.booking_basket, sell_ccy),
			       rooms=req.booking_rooms, own=quantize(q.basket, sell_ccy))
			for pid in sorted(minimums):
				b, n, _booked = promotions.judged_basket(pid, sell_ctx)
				ex.add("promotion", "BOOKING_BASKET_PROMOTION",
				       "{name}: minimum {minimum} {currency} judged on the {rooms} room(s) it covers: {basket} {currency}",
				       after=b, currency=sell_ccy, rule=promotions.promo_ref(by_id[pid]), name=by_id[pid].name,
				       minimum=quantize(minimums[pid], sell_ccy), rooms=n, basket=quantize(b, sell_ccy))
		sell_from = len(q.promotions)
		chosen, rejected = promotions.select(sell_promos, sell_ctx, ctx.coupon_usage)
		fx.explain_new(log, ex)
		accom_chosen = [p for p in chosen if p.applies_to == PromoAppliesTo.ACCOMMODATION]
		basket_chosen = [p for p in chosen if p.applies_to != PromoAppliesTo.ACCOMMODATION]
		promotions.explain_rejections(rejected, ex, "promotion")
		finals, accom_outcomes = promotions.apply_promotions(accom_chosen, sells, sell_ctx, t.stacking, sell_ccy,
		                                                     fx=ctx.promo_fx, explain=ex, stage="promotion",
		                                                     fx_log=log)
		fx.explain_new(log, ex)
		q.promotions.extend(accom_outcomes)
		q.promotions.extend(rejected)

		for n in nights:
			per, unit, occ_total, brd, after_adults, after_children, before_adjust = partial[n]
			q.nights.append(NightPrice(n, per, unit, occ_total, brd, costs[n], cost_net[n], sells_cc[n], sells[n],
			                           finals[n], subtotal_adults=after_adults, subtotal_children=after_children,
			                           subtotal_board=before_adjust))

		# ── lines & rounding ──
		lines: list[QuoteLine] = []
		accom_gross = quantize(gross_accom, sell_ccy)
		lines.append(QuoteLine(LineKind.ACCOMMODATION, req.room_type,
		                       f"{t.rooms[req.room_type].name} · {req.board} · {len(nights)} night(s)",
		                       accom_gross, D(len(nights))))
		accom_discount = ZERO
		for o in accom_outcomes:
			if o.applied and o.discount:
				amt = quantize(o.discount, sell_ccy)
				accom_discount += amt
				lines.append(QuoteLine(LineKind.DISCOUNT, o.promo_id, o.name, -amt, ref=o.code))
		extra_cats: dict[str, Decimal] = {}
		for e in q.extras:
			if not e.ok:
				continue
			amt = quantize(e.amount, sell_ccy)
			cat = f"EXTRA:{e.tax_category}"
			extra_cats[cat] = extra_cats.get(cat, ZERO) + amt
			lines.append(QuoteLine(LineKind.EXTRA, e.code, e.name, amt, e.quantity, category=cat))

		categories = {"ACCOMMODATION": accom_gross - accom_discount, **extra_cats}
		# a fixed discount on the complete booking (or its extras) is granted once, on room 1; a
		# percentage is the same share of every room (G-06, ADR-029): ``promotions.select`` refused
		# the others, and any this room cannot use, before choosing (O-1)
		for p in basket_chosen:
			outcome = _apply_basket_promo(p, categories, sell_ccy, ctx, lines, ex, log)
			q.promotions.append(outcome)
		sold = q.promotions[sell_from:]
		refused = {o.promo_id for o in sold if not o.applied and o.rule == promotions.MIN_BASKET}
		granted = {o.promo_id for o in sold if o.applied}
		for pid in sorted(minimums):
			b, n, _booked = promotions.judged_basket(pid, sell_ctx)
			q.basket_terms.append(BasketTerm(pid, by_id[pid].name, by_id[pid].code, minimums[pid], b, n,
			                                 pid not in refused, pid in granted))

		persons = party.adults + party.child_count
		tax_lines, _nets = tax.compute_taxes(ctx.tax_rules, categories, inclusive=t.prices_include_tax,
		                                    currency=sell_ccy, persons=persons, nights=len(nights),
		                                    fx=ctx.tax_fx, fx_log=log)
		fx.explain_new(log, ex)
		q.taxes = tax_lines
		for tl in tax_lines:
			lines.append(QuoteLine(LineKind.TAX, tl.code, tl.name, tl.amount, category=tl.category,
			                       included=tl.included))
			ex.add("tax", "TAX", "{name} {rate} on {category}: {amount}{inc}", after=tl.amount, currency=sell_ccy,
			       rule=RuleRef("tax", tl.code, Level.HOTEL, tl.source or "", tl.name),
			       name=tl.name, rate=(f"{tl.rate}%" if tl.rate is not None else "fixed"), category=tl.category,
			       amount=tl.amount, inc=" (included)" if tl.included else "")
		q.lines = lines

		subtotal = sum((ln.amount for ln in lines if ln.kind != LineKind.TAX), ZERO)
		tax_added = sum((ln.amount for ln in lines if ln.kind == LineKind.TAX and not ln.included), ZERO)
		tax_total = sum((ln.amount for ln in lines if ln.kind == LineKind.TAX), ZERO)
		total = subtotal + tax_added
		cost_sell = quantize(sum(cost_net.values(), ZERO) * ctx.fx.sell_rate, sell_ccy)
		log.note(ctx.fx, "cost")
		fx.explain_new(log, ex)
		accom_net = categories["ACCOMMODATION"]
		margin = accom_net - cost_sell
		q.totals = {
			"accommodation_gross": accom_gross,
			"accommodation_discount": accom_discount,
			"accommodation": accom_net,
			"extras": sum(extra_cats.values(), ZERO),
			"discounts": -sum((ln.amount for ln in lines if ln.kind in (LineKind.DISCOUNT, LineKind.COUPON)), ZERO),
			"subtotal": subtotal,
			"tax": tax_total,
			"tax_added": tax_added,
			"total": total,
			"cost": cost_sell,
			"cost_contract_currency": quantize(sum(cost_net.values(), ZERO), t.currency),
			"margin": margin,
			"margin_percent": (margin / accom_net * HUNDRED).quantize(D("0.01")) if accom_net else ZERO,
		}
		ex.add("total", "TOTAL", "total {total} {currency}", after=total, currency=sell_ccy,
		       total=total)
	except Unsellable as u:
		_unsellable(q, u)
	return q


def _apply_basket_promo(p: Promotion, categories: dict[str, Decimal], currency: str, ctx: PricingContext,
                        lines: list[QuoteLine], ex: Explanation, log: fx.FxLog | None = None
                        ) -> promotions.PromoOutcome:
	if p.applies_to == PromoAppliesTo.EXTRAS:
		scope = {k: v for k, v in categories.items() if k.startswith("EXTRA:")}
	else:
		scope = dict(categories)
	base = sum(scope.values(), ZERO)
	if p.value_type == PromoValueType.PERCENT:
		discount = base * D(p.value) / HUNDRED
	elif p.value_type == PromoValueType.FIXED_STAY:
		amt = promotions._fixed_in(p, currency, ctx.promo_fx, log)
		if amt is None:
			return promotions.PromoOutcome(p.promo_id, p.name, p.kind, False, f"no FX to convert {p.currency}",
			                               source=p.source, code=p.code)
		fx.explain_new(log, ex)
		discount = min(amt, base)
	else:
		return promotions.PromoOutcome(p.promo_id, p.name, p.kind, False,
		                               f"{p.value_type.value} is not supported on {p.applies_to.value}",
		                               source=p.source, code=p.code)
	discount = quantize(min(discount, base), currency)
	if discount <= ZERO:
		return promotions.PromoOutcome(p.promo_id, p.name, p.kind, False, "nothing to discount",
		                               source=p.source, code=p.code)
	alloc = _allocate(discount, scope, currency)
	for k, v in alloc.items():
		categories[k] -= v
	lines.append(QuoteLine(LineKind.COUPON, p.promo_id, p.name, -discount,
	                       category=p.applies_to.value, ref=p.code))
	ex.add("coupon", "COUPON_APPLIED", "{name}: −{discount} on {scope}", after=discount, currency=currency,
	       rule=promotions.promo_ref(p), name=p.name, discount=discount, scope=p.applies_to.value)
	return promotions.PromoOutcome(p.promo_id, p.name, p.kind, True, "applied", discount, (), "", p.source, p.code)
