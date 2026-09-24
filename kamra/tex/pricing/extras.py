"""ExtrasPricingResolver (R-19)."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal

from kamra.tex.money import ZERO, D
from kamra.tex.pricing.enums import ExtraPricingMode
from kamra.tex.pricing.model import ExtraDayAvailability, ExtraDef, ExtraPriceRule, ExtraRequest, FxSnapshot


@dataclass(frozen=True, slots=True)
class ExtraContext:
	sale_date: date
	check_in: date
	check_out: date
	nights: int
	market: str
	channel: str
	room_type: str
	adults: int
	children: int      # non-infant children
	infants: int
	sell_currency: str


@dataclass(frozen=True, slots=True)
class ExtraOutcome:
	code: str
	name: str
	ok: bool
	reason: str = ""
	quantity: Decimal = ZERO
	amount: Decimal = ZERO          # sell currency, full precision
	currency: str = ""
	tax_category: str = ""
	mandatory: bool = False
	pricing_mode: str = ""
	service_dates: tuple[str, ...] = ()
	rule_id: str | None = None
	detail: str = ""
	revision: str | None = None       # the extra revision that priced it (G-20)
	fx_rate: Decimal | None = None    # extra currency → sell currency, when converted
	usage: tuple[tuple[str, int], ...] = ()   # (ISO day, units) it consumes of a limited capacity (G-19)

	def to_dict(self) -> dict:
		from kamra.tex.money import to_str6, to_str_rate

		return {"code": self.code, "name": self.name, "ok": self.ok, "reason": self.reason,
		        "quantity": to_str6(self.quantity), "amount": to_str6(self.amount), "currency": self.currency,
		        "tax_category": self.tax_category, "mandatory": self.mandatory,
		        "pricing_mode": self.pricing_mode, "service_dates": list(self.service_dates),
		        "rule_id": self.rule_id, "detail": self.detail, "revision": self.revision,
		        "fx_rate": to_str_rate(self.fx_rate) if self.fx_rate is not None else None,
		        "usage": [{"date": d, "units": u} for d, u in self.usage]}


def _in(d: date, lo: date | None, hi: date | None) -> bool:
	return (lo is None or d >= lo) and (hi is None or d <= hi)


def _rule_matches(r: ExtraPriceRule, ctx: ExtraContext, service: date | None) -> bool:
	if r.market and r.market != ctx.market:
		return False
	if r.room_type and r.room_type != ctx.room_type:
		return False
	if r.channel and r.channel != ctx.channel:
		return False
	if (r.stay_from or r.stay_to) and not _in(ctx.check_in, r.stay_from, r.stay_to):
		return False
	if (r.sale_from or r.sale_to) and not _in(ctx.sale_date, r.sale_from, r.sale_to):
		return False
	if (r.service_from or r.service_to):
		if service is None or not _in(service, r.service_from, r.service_to):
			return False
	return True


def _price_rule(defn: ExtraDef, ctx: ExtraContext, service: date | None) -> ExtraPriceRule | None:
	hits = [r for r in defn.price_rules if _rule_matches(r, ctx, service)]
	if not hits:
		return None

	def spec(r: ExtraPriceRule):
		q = sum(1 for v in (r.market, r.room_type, r.channel) if v)
		q += sum(1 for pair in ((r.stay_from, r.stay_to), (r.sale_from, r.sale_to),
		                        (r.service_from, r.service_to)) if any(pair))
		return (q, r.priority, r.rule_id)

	return max(hits, key=spec)


def _amounts(defn: ExtraDef, rule: ExtraPriceRule | None) -> tuple[Decimal, Decimal, Decimal]:
	adult = D(rule.amount if rule else defn.amount)
	child_src = (rule.child_amount if rule and rule.child_amount is not None else defn.child_amount)
	child = D(child_src) if child_src is not None else adult
	inf_src = (rule.infant_amount if rule and rule.infant_amount is not None else defn.infant_amount)
	infant = D(inf_src) if inf_src is not None else child
	return adult, child, infant


def eligibility(defn: ExtraDef, req: ExtraRequest, ctx: ExtraContext) -> str | None:
	if (defn.sale_from or defn.sale_to) and not _in(ctx.sale_date, defn.sale_from, defn.sale_to):
		return "not on sale for this booking date"
	if defn.markets is not None and ctx.market not in defn.markets:
		return f"not available for market {ctx.market}"
	if defn.channels is not None and ctx.channel not in defn.channels:
		return f"not available on channel {ctx.channel}"
	if defn.room_types is not None and ctx.room_type not in defn.room_types:
		return f"not available with room {ctx.room_type}"
	if req.quantity < 1:
		return "quantity must be at least 1"
	if defn.max_quantity and req.quantity > defn.max_quantity:
		return f"at most {defn.max_quantity}"
	for sd in req.service_dates:
		if not (ctx.check_in <= sd <= ctx.check_out):
			return f"service date {sd} outside the stay"
		if not _in(sd, defn.service_from, defn.service_to):
			return f"not available on {sd}"
	if defn.pricing_mode == ExtraPricingMode.SERVICE_DATE and not req.service_dates:
		return "choose at least one service date"
	if not req.service_dates and (defn.service_from or defn.service_to):
		overlap = defn.service_to is None or defn.service_to >= ctx.check_in
		overlap = overlap and (defn.service_from is None or defn.service_from <= ctx.check_out)
		if not overlap:
			return "not available during this stay"
	return None


def usage(defn: ExtraDef, req: ExtraRequest, ctx: ExtraContext) -> tuple[tuple[date, int], ...]:
	"""The days a sold extra takes from a daily capacity and how many units on each (G-19).

	Service-date extras use each chosen date; nightly ones every night of the stay; all the
	others one day: the chosen service date, else the arrival day. Per-person modes count
	heads (adults, children and infants), so a spa slot for a family of four is four units."""
	qty = int(req.quantity)
	heads = ctx.adults + ctx.children + ctx.infants
	one_day = req.service_dates[0] if req.service_dates else ctx.check_in
	nights = [ctx.check_in + timedelta(days=i) for i in range(max((ctx.check_out - ctx.check_in).days, 1))]
	mode = defn.pricing_mode
	if mode == ExtraPricingMode.SERVICE_DATE:
		pairs = [(d, qty) for d in req.service_dates]
	elif mode == ExtraPricingMode.NIGHT:
		pairs = [(n, qty) for n in nights]
	elif mode == ExtraPricingMode.PERSON_NIGHT:
		pairs = [(n, qty * heads) for n in nights]
	elif mode == ExtraPricingMode.PERSON:
		pairs = [(one_day, qty * heads)]
	elif mode == ExtraPricingMode.ADULT:
		pairs = [(one_day, qty * ctx.adults)]
	elif mode == ExtraPricingMode.CHILD:
		pairs = [(one_day, qty * ctx.children)]
	elif mode == ExtraPricingMode.INFANT:
		pairs = [(one_day, qty * ctx.infants)]
	else:        # per booking, room, stay, unit or use
		pairs = [(one_day, qty)]
	per_day: dict[date, int] = {}
	for d, u in pairs:
		per_day[d] = per_day.get(d, 0) + u
	return tuple((d, u) for d, u in sorted(per_day.items()) if u > 0)


def capacity_refusal(use: tuple[tuple[date, int], ...], days: dict[date, ExtraDayAvailability]) -> str | None:
	"""Why a limited extra cannot be sold for these days, or None (G-19)."""
	for d, units in use:
		a = days.get(d)
		if a is None or a.remaining <= 0:
			return f"sold out on {d.isoformat()}" if not (a and a.closed) else f"closed on {d.isoformat()}"
		if a.closed:
			return f"closed on {d.isoformat()}"
		if units > a.remaining:
			return f"only {a.remaining} left on {d.isoformat()}"
	return None


_ONLY_LEFT = re.compile(r"\bonly \d+ left on\b")


def guest_reason(text):
	"""A capacity reason as a guest may read it: "not enough left on D", never how many are
	left (staff see the count; ADR-033)."""
	return _ONLY_LEFT.sub("not enough left on", text) if isinstance(text, str) else text


def guest_safe(value):
	"""``value`` (a response or part of one) with every capacity reason made guest-safe."""
	if isinstance(value, str):
		return guest_reason(value)
	if isinstance(value, dict):
		return {k: guest_safe(v) for k, v in value.items()}
	if isinstance(value, list | tuple):
		return [guest_safe(v) for v in value]
	return value


def price_extra(defn: ExtraDef, req: ExtraRequest, ctx: ExtraContext,
                fx: dict[str, FxSnapshot] | None = None) -> ExtraOutcome:
	base = dict(code=defn.code, name=defn.name, tax_category=defn.tax_category, mandatory=defn.mandatory,
	            pricing_mode=defn.pricing_mode.value, revision=defn.revision,
	            service_dates=tuple(d.isoformat() for d in req.service_dates))
	reason = eligibility(defn, req, ctx)
	if reason:
		return ExtraOutcome(ok=False, reason=reason, **base)

	qty = D(req.quantity)
	mode = defn.pricing_mode
	rule = _price_rule(defn, ctx, req.service_dates[0] if req.service_dates else None)
	adult, child, infant = _amounts(defn, rule)
	person_total = adult * ctx.adults + child * ctx.children + infant * ctx.infants

	if mode in (ExtraPricingMode.RESERVATION, ExtraPricingMode.ROOM, ExtraPricingMode.STAY,
	            ExtraPricingMode.UNIT, ExtraPricingMode.USAGE):
		units, amount, detail = qty, adult * qty, f"{qty} × {adult}"
	elif mode == ExtraPricingMode.PERSON:
		units, amount = qty, person_total * qty
		detail = f"{ctx.adults}×{adult} + {ctx.children}×{child} + {ctx.infants}×{infant}"
	elif mode == ExtraPricingMode.ADULT:
		units, amount, detail = qty * ctx.adults, adult * ctx.adults * qty, f"{ctx.adults} adult(s) × {adult}"
	elif mode == ExtraPricingMode.CHILD:
		units, amount, detail = qty * ctx.children, child * ctx.children * qty, f"{ctx.children} child(ren) × {child}"
	elif mode == ExtraPricingMode.INFANT:
		units, amount, detail = qty * ctx.infants, infant * ctx.infants * qty, f"{ctx.infants} infant(s) × {infant}"
	elif mode == ExtraPricingMode.NIGHT:
		n = max(ctx.nights, 1)
		units, amount, detail = qty * n, adult * n * qty, f"{n} night(s) × {adult}"
	elif mode == ExtraPricingMode.PERSON_NIGHT:
		n = max(ctx.nights, 1)
		units, amount, detail = qty * n, person_total * n * qty, f"{n} night(s) × persons"
	elif mode == ExtraPricingMode.SERVICE_DATE:
		amount = ZERO
		for sd in req.service_dates:
			r = _price_rule(defn, ctx, sd)
			a, _, _ = _amounts(defn, r)
			amount += a * qty
		units, detail = qty * len(req.service_dates), f"{len(req.service_dates)} date(s)"
	else:
		return ExtraOutcome(ok=False, reason=f"unsupported pricing mode {mode}", **base)

	currency = ctx.sell_currency
	fx_rate = None
	if defn.currency != ctx.sell_currency:
		snap = (fx or {}).get(defn.currency)
		if snap is None:
			return ExtraOutcome(ok=False, reason=f"no FX policy for {defn.currency}→{ctx.sell_currency}", **base)
		fx_rate = snap.sell_rate
		amount = amount * fx_rate
	return ExtraOutcome(ok=True, quantity=units, amount=amount, currency=currency,
	                    rule_id=rule.rule_id if rule else None, detail=detail, fx_rate=fx_rate, **base)
