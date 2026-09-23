"""Extras added to a booked stay (G-22, ADR-034).

An add-on is priced on its own and appended to the reservation's price: the stay itself
stays price-locked (its nights, discounts and taxes are never repriced). It is priced with
the extra revision on sale now, never with promotions or coupons, and taxed on its own
(EXTRA:* categories only). Every problem refuses the whole add-on with the reason: nothing
is silently dropped. Pure: no Frappe.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from decimal import Decimal

from kamra.tex.money import ZERO, D, calc, quantize, to_str
from kamra.tex.pricing import ages, extras, tax
from kamra.tex.pricing.engine import QuoteLine
from kamra.tex.pricing.enums import ExtraPricingMode, Level, LineKind
from kamra.tex.pricing.explain import Explanation
from kamra.tex.pricing.model import (
	ContractTerms,
	ExtraDayAvailability,
	ExtraDef,
	ExtraRequest,
	FxSnapshot,
	PricingError,
	RuleRef,
	StayRequest,
	TaxRule,
	Unsellable,
)


@dataclass
class AddonQuote:
	ok: bool
	currency: str
	outcomes: list = field(default_factory=list)          # ExtraOutcome
	lines: list[QuoteLine] = field(default_factory=list)
	taxes: list = field(default_factory=list)             # TaxLine
	totals: dict[str, Decimal] = field(default_factory=dict)
	reasons: list[dict] = field(default_factory=list)
	explanation: Explanation = field(default_factory=Explanation)

	def to_dict(self, internal: bool = False) -> dict:
		out = {"ok": self.ok, "currency": self.currency, "extras": [o.to_dict() for o in self.outcomes],
		       "lines": [ln.to_dict() for ln in self.lines], "taxes": [t.to_dict() for t in self.taxes],
		       "totals": {k: to_str(v) for k, v in self.totals.items()}, "reasons": self.reasons}
		if internal:
			out["explanation"] = self.explanation.to_list()
		return out


def _refuse(currency: str, code: str, message: str, ex: Explanation) -> AddonQuote:
	ex.add("addon", code, "{message}", message=message)
	return AddonQuote(False, currency, reasons=[{"code": code, "message": message}],
	                  totals={"extras": ZERO, "tax": ZERO, "tax_added": ZERO, "subtotal": ZERO, "total": ZERO},
	                  explanation=ex)


def price_addons(*, terms: ContractTerms, request: StayRequest, requests: tuple[ExtraRequest, ...],
                 catalog: dict[str, ExtraDef], today: date, now: datetime, extra_fx: dict[str, FxSnapshot],
                 tax_rules: tuple[TaxRule, ...], tax_fx: dict[str, FxSnapshot] | None = None,
                 availability: dict[str, dict[date, ExtraDayAvailability]] | None = None,
                 booked: dict[str, int] | None = None) -> AddonQuote:
	"""Price extras a guest adds to the stay ``request`` (the booked room, as sold).

	``catalog``: the extras that may be added now (on sale online and after booking);
	``booked``: quantities of each code the reservation already has (for ``max_quantity``);
	``availability``: what is left of limited extras (G-19)."""
	with calc():
		return _price(terms=terms, request=request, requests=requests, catalog=catalog, today=today, now=now,
		              extra_fx=extra_fx, tax_rules=tax_rules, tax_fx=tax_fx or {}, availability=availability,
		              booked=booked or {})


def _price(*, terms, request, requests, catalog, today, now, extra_fx, tax_rules, tax_fx, availability, booked):
	sell = request.sell_currency.upper()
	ex = Explanation()
	if not requests:
		return _refuse(sell, "ADDON_EMPTY", "choose at least one extra", ex)
	try:
		party = ages.classify_party(terms, request.adults, request.children, request.check_in, today)
	except (PricingError, Unsellable) as e:
		return _refuse(sell, "ADDON_PARTY", str(e), ex)
	nights = (request.check_out - request.check_in).days
	ctx = extras.ExtraContext(sale_date=today, check_in=request.check_in, check_out=request.check_out,
	                          nights=nights, market=request.market, channel=request.channel,
	                          room_type=request.room_type, adults=party.adults,
	                          children=party.child_count - party.infants, infants=party.infants, sell_currency=sell)
	outcomes = []
	for req in sorted(requests, key=lambda r: r.code):
		d = catalog.get(req.code)
		if d is None:
			return _refuse(sell, "ADDON_NOT_AVAILABLE", f"{req.code}: not available to add", ex)
		if d.mandatory:
			return _refuse(sell, "ADDON_NOT_AVAILABLE", f"{d.name}: included by the hotel", ex)
		if d.pricing_mode == ExtraPricingMode.RESERVATION and request.room_index != 0:
			return _refuse(sell, "ADDON_NOT_AVAILABLE", f"{d.name}: charged once per booking, on room 1", ex)
		if d.max_quantity and booked.get(d.code, 0) + req.quantity > d.max_quantity:
			return _refuse(sell, "ADDON_QUANTITY", f"{d.name}: at most {d.max_quantity} per stay", ex)
		outcome = extras.price_extra(d, req, ctx, extra_fx)
		if not outcome.ok:
			return _refuse(sell, "ADDON_NOT_AVAILABLE", f"{d.name}: {outcome.reason}", ex)
		use = extras.usage(d, req, ctx)
		earliest = max(today, (now + timedelta(hours=d.cutoff_hours)).date())
		late = [day for day, _u in use if day < earliest]
		if late:
			return _refuse(sell, "ADDON_TOO_LATE", f"{d.name}: can no longer be added for {late[0].isoformat()}", ex)
		days = (availability or {}).get(d.code)
		refusal = extras.capacity_refusal(use, days) if days is not None else None
		if refusal:
			return _refuse(sell, "ADDON_SOLD_OUT", f"{d.name}: {refusal}", ex)
		outcome = _with_usage(outcome, use)
		outcomes.append(outcome)
		ex.add("extra", "EXTRA", "{name}: {detail} = {amount}", after=outcome.amount, currency=sell,
		       rule=RuleRef("extra", d.code, Level.HOTEL, f"extra:{d.revision}" if d.revision else "", d.name),
		       name=d.name, detail=outcome.detail, amount=outcome.amount)
	ex.add("addon", "ADDON_NO_PROMOTIONS", "added after booking: priced on its own, without promotions or coupons")

	lines: list[QuoteLine] = []
	categories: dict[str, Decimal] = {}
	for o in outcomes:
		amt = quantize(o.amount, sell)
		cat = f"EXTRA:{o.tax_category}"
		categories[cat] = categories.get(cat, ZERO) + amt
		lines.append(QuoteLine(LineKind.EXTRA, o.code, o.name, amt, o.quantity, category=cat, ref="addon"))
	# the add-on's own taxes: extras categories only (a per-night levy belongs to the stay)
	persons = party.adults + party.child_count
	try:
		tax_lines, _nets = tax.compute_taxes(tax_rules, categories, inclusive=terms.prices_include_tax,
		                                    currency=sell, persons=persons, nights=nights, fx=tax_fx)
	except Unsellable as u:
		return _refuse(sell, u.code, u.message, ex)
	for tl in tax_lines:
		lines.append(QuoteLine(LineKind.TAX, tl.code, tl.name, tl.amount, category=tl.category, included=tl.included))
		ex.add("tax", "TAX", "{name} {rate} on {category}: {amount}", after=tl.amount, currency=sell,
		       rule=RuleRef("tax", tl.code, Level.HOTEL, tl.source or "", tl.name), name=tl.name,
		       rate=(f"{tl.rate}%" if tl.rate is not None else "fixed"), category=tl.category, amount=tl.amount)
	extras_total = sum(categories.values(), ZERO)
	tax_total = sum((t.amount for t in tax_lines), ZERO)
	tax_added = sum((t.amount for t in tax_lines if not t.included), ZERO)
	lines.sort(key=lambda ln: (ln.kind != LineKind.EXTRA, ln.code))
	return AddonQuote(True, sell, outcomes, lines, list(tax_lines),
	                  {"extras": extras_total, "subtotal": extras_total, "tax": tax_total, "tax_added": tax_added,
	                   "total": extras_total + tax_added}, [], ex)


def _with_usage(outcome, use):
	from dataclasses import replace

	return replace(outcome, usage=tuple((d.isoformat(), u) for d, u in use))


SUMMED = ("extras", "subtotal", "tax", "tax_added", "total")


def merge_addons(snapshot: dict, addon: dict, *, addon_id: str, at: str) -> dict:
	"""The reservation's price with an add-on appended (a copy). The stay's own lines are
	unchanged; the add-on's extra lines come before the tax lines, its taxes after; the
	totals add up; cost and margin are the stay's (``snapshot["addons"]`` keeps each block,
	so a later repricing of the stay carries it over at the same amount)."""
	out = copy.deepcopy(snapshot)
	add = copy.deepcopy(addon)
	for e in add.get("extras") or []:
		e["addon"] = addon_id
	lines = out.get("lines") or []
	first_tax = next((i for i, ln in enumerate(lines) if ln.get("kind") == "TAX"), len(lines))
	extra_lines = [{**ln, "ref": addon_id} for ln in add.get("lines") or [] if ln.get("kind") != "TAX"]
	tax_lines = [{**ln, "ref": addon_id} for ln in add.get("lines") or [] if ln.get("kind") == "TAX"]
	out["lines"] = lines[:first_tax] + extra_lines + lines[first_tax:] + tax_lines
	out["extras"] = (out.get("extras") or []) + (add.get("extras") or [])
	out["taxes"] = (out.get("taxes") or []) + (add.get("taxes") or [])
	totals = dict(out.get("totals") or {})
	for k in SUMMED:
		totals[k] = to_str(D(totals.get(k) or 0) + D((add.get("totals") or {}).get(k) or 0))
	out["totals"] = totals
	out.setdefault("addons", []).append({"id": addon_id, "at": at, "quote": addon})
	return out
