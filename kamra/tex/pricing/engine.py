"""QuoteBuilder — the TEX pricing pipeline (TARGET_ARCHITECTURE §3).

``price_stay(ctx, request)`` prices ONE room for ONE stay. It is a pure,
deterministic function: the same context and request always produce the same
quote, including a byte-identical explanation. It never touches a database and
never guesses: anything it cannot price makes the quote unsellable with reasons.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal

from kamra.tex.money import HUNDRED, ONE, ZERO, D, calc, quantize, to_str, to_str6
from kamra.tex.pricing import ages, boards, extras, markup, occupancy, promotions, rooms, tax
from kamra.tex.pricing.enums import ExtraPricingMode, LineKind, Op, PromoAppliesTo, PromoStage, PromoValueType
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

	def to_dict(self) -> dict:
		q = to_str6
		return {"date": self.night.isoformat(), "period": self.period, "unit": q(self.unit),
		        "occupancy": q(self.occupancy), "board": q(self.board), "cost": q(self.cost),
		        "cost_net": q(self.cost_net), "sell_contract": q(self.sell_contract), "sell": q(self.sell),
		        "final": q(self.final)}


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
	totals: dict[str, Decimal] = field(default_factory=dict)
	rate_plan: dict | None = None
	explanation: Explanation = field(default_factory=Explanation)
	engine_version: str = ENGINE_VERSION

	@property
	def total(self) -> Decimal:
		return self.totals.get("total", ZERO)

	def to_dict(self, *, internal: bool = True) -> dict:
		"""JSON-safe dict. ``internal=False`` strips cost/margin and the rule-level
		explanation (guest-facing)."""
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
			"promotions": [p.to_dict() for p in self.promotions if internal or p.applied],
			"extras": [e.to_dict() for e in self.extras],
			"taxes": [t.to_dict() for t in self.taxes],
			"totals": totals,
		}
		if internal:
			out["fx"] = self.fx
			out["nights"] = [n.to_dict() for n in self.nights]
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


def price_stay(ctx: PricingContext, req: StayRequest) -> RoomQuote:
	with calc():
		return _price_stay(ctx, req)


def _price_stay(ctx: PricingContext, req: StayRequest) -> RoomQuote:
	t = ctx.terms
	sell_ccy = req.sell_currency.upper()
	q = RoomQuote(request=req, sellable=True, currency=sell_ccy)
	ex = q.explanation
	q.contract = {"contract": t.contract_id, "code": t.contract_code, "name": t.contract_name,
	              "version": t.version_id, "version_no": t.version_no, "payload_hash": t.payload_hash,
	              "market": t.market, "currency": t.currency, "basis": t.basis.value}

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
			q.rate_plan = {"code": rp.code, "name": rp.name, "refundable": rp.refundable,
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
			partial[n] = (period.code, unit, occ.total, brd)

		promo_ctx_base = dict(sale_date=sale_date, check_in=req.check_in, check_out=req.check_out, nights=nights,
		                      market=req.market, channel=req.channel, room_type=req.room_type, board=req.board,
		                      rate_plan=req.rate_plan, contract=t.contract_id, member=req.member,
		                      codes=frozenset(c.strip().upper() for c in req.promo_codes if c and c.strip()),
		                      extras=frozenset(e.code for e in req.extras))

		# ── 8: COST-stage contract offers ──
		cost_promos = tuple(p for p in (*t.offers, *ctx.promotions) if p.stage == PromoStage.COST)
		cost_ctx = promotions.PromoContext(basket=sum(costs.values(), ZERO), sell_currency=t.currency,
		                                   **promo_ctx_base)
		chosen, rejected = promotions.select(cost_promos, cost_ctx, ctx.coupon_usage)
		promotions.explain_rejections(rejected, ex, "cost_offer")
		cost_net, cost_outcomes = promotions.apply_promotions(chosen, costs, cost_ctx, t.stacking, t.currency,
		                                                      explain=ex, stage="cost_offer")
		q.promotions.extend(cost_outcomes)
		q.promotions.extend(rejected)

		# ── 9-10: markup and FX ──
		scope = markup.MarkupScope(t.property, req.market, t.contract_id, req.room_type, req.channel, t.currency)
		sells_cc: dict[date, Decimal] = {}
		sells: dict[date, Decimal] = {}
		for n in nights:
			sells_cc[n] = markup.apply_markup(ctx.markups, scope, n, cost_net[n], explain=ex)
			sells[n] = sells_cc[n] * ctx.fx.sell_rate
		q.fx = ctx.fx.to_dict()
		if ctx.fx.from_currency != ctx.fx.to_currency:
			ex.add("fx", "FX", "{frm}→{to} at {rate} ({mode})", frm=ctx.fx.from_currency, to=ctx.fx.to_currency,
			       rate=ctx.fx.sell_rate, mode=ctx.fx.mode.value)

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
			q.extras.append(outcome)
			if outcome.ok:
				ex.add("extra", "EXTRA", "{name}: {detail} = {amount}", after=outcome.amount, currency=sell_ccy,
				       name=d.name, detail=outcome.detail, amount=outcome.amount)
			else:
				ex.add("extra", "EXTRA_REJECTED", "{name} not added: {reason}", name=d.name, reason=outcome.reason)
			if not outcome.ok and d.mandatory:
				raise Unsellable("MANDATORY_EXTRA", f"mandatory extra {d.name} cannot be priced: {outcome.reason}")
		extras_total = sum((e.amount for e in q.extras if e.ok), ZERO)

		# ── 11/13: SELL promotions and coupons (one combination decision) ──
		sell_promos = tuple(p for p in (*t.offers, *ctx.promotions) if p.stage == PromoStage.SELL)
		gross_accom = sum(sells.values(), ZERO)
		sell_ctx = promotions.PromoContext(basket=gross_accom + extras_total, sell_currency=sell_ccy,
		                                   fx=ctx.promo_fx, **promo_ctx_base)
		chosen, rejected = promotions.select(sell_promos, sell_ctx, ctx.coupon_usage)
		accom_chosen = [p for p in chosen if p.applies_to == PromoAppliesTo.ACCOMMODATION]
		basket_chosen = [p for p in chosen if p.applies_to != PromoAppliesTo.ACCOMMODATION]
		promotions.explain_rejections(rejected, ex, "promotion")
		finals, accom_outcomes = promotions.apply_promotions(accom_chosen, sells, sell_ctx, t.stacking, sell_ccy,
		                                                     fx=ctx.promo_fx, explain=ex, stage="promotion")
		q.promotions.extend(accom_outcomes)
		q.promotions.extend(rejected)

		for n in nights:
			per, unit, occ_total, brd = partial[n]
			q.nights.append(NightPrice(n, per, unit, occ_total, brd, costs[n], cost_net[n], sells_cc[n], sells[n],
			                           finals[n]))

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
		for p in basket_chosen:
			if not lead_room and p.value_type != PromoValueType.PERCENT:
				# a fixed discount on the complete booking (or its extras) is granted once,
				# on room 1; a percentage is the same share of every room (G-06, ADR-029)
				reason = "fixed booking discount granted once per booking, on room 1"
				ex.add("coupon", "COUPON_REJECTED", "{name}: {reason}", rule=promotions.promo_ref(p), name=p.name,
				       reason=reason)
				q.promotions.append(promotions.PromoOutcome(p.promo_id, p.name, p.kind, False, reason,
				                                            source=p.source, code=p.code))
				continue
			outcome = _apply_basket_promo(p, categories, sell_ccy, ctx, lines, ex)
			q.promotions.append(outcome)

		persons = party.adults + party.child_count
		tax_lines, _nets = tax.compute_taxes(ctx.tax_rules, categories, inclusive=t.prices_include_tax,
		                                    currency=sell_ccy, persons=persons, nights=len(nights))
		q.taxes = tax_lines
		for tl in tax_lines:
			lines.append(QuoteLine(LineKind.TAX, tl.code, tl.name, tl.amount, category=tl.category,
			                       included=tl.included))
			ex.add("tax", "TAX", "{name} {rate} on {category}: {amount}{inc}", after=tl.amount, currency=sell_ccy,
			       name=tl.name, rate=(f"{tl.rate}%" if tl.rate is not None else "fixed"), category=tl.category,
			       amount=tl.amount, inc=" (included)" if tl.included else "")
		q.lines = lines

		subtotal = sum((ln.amount for ln in lines if ln.kind != LineKind.TAX), ZERO)
		tax_added = sum((ln.amount for ln in lines if ln.kind == LineKind.TAX and not ln.included), ZERO)
		tax_total = sum((ln.amount for ln in lines if ln.kind == LineKind.TAX), ZERO)
		total = subtotal + tax_added
		cost_sell = quantize(sum(cost_net.values(), ZERO) * ctx.fx.sell_rate, sell_ccy)
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
		q.sellable = False
		q.reasons.append({"code": u.code, "message": u.message, **{k: v for k, v in u.params.items()
		                                                            if isinstance(v, str | int | list)}})
		ex.add("unsellable", u.code, "not sellable: {reason}", reason=u.message)
		q.totals = {}
	return q


def _apply_basket_promo(p: Promotion, categories: dict[str, Decimal], currency: str, ctx: PricingContext,
                        lines: list[QuoteLine], ex: Explanation) -> promotions.PromoOutcome:
	if p.applies_to == PromoAppliesTo.EXTRAS:
		scope = {k: v for k, v in categories.items() if k.startswith("EXTRA:")}
	else:
		scope = dict(categories)
	base = sum(scope.values(), ZERO)
	if p.value_type == PromoValueType.PERCENT:
		discount = base * D(p.value) / HUNDRED
	elif p.value_type == PromoValueType.FIXED_STAY:
		amt = promotions._fixed_in(p, currency, ctx.promo_fx)
		if amt is None:
			return promotions.PromoOutcome(p.promo_id, p.name, p.kind, False, f"no FX to convert {p.currency}",
			                               source=p.source, code=p.code)
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
