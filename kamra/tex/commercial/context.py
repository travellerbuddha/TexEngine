"""Builds the pure-engine PricingContext from Frappe data, as of a sale time.

Selling policies (markups, promotions, FX policies) are loaded AS OF the sale time
via their effective-dated revisions (ADR-005), so the same function serves live
quotes, historical simulations and modification proposals.
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timedelta
from decimal import Decimal

import frappe
from frappe.utils import get_datetime

from kamra.tex.commercial.revisions import as_of
from kamra.tex.money import D, D_or_none
from kamra.tex.pricing import fx as fx_math
from kamra.tex.pricing.enums import (
	ExtraPricingMode,
	FxMode,
	MarkupCombine,
	Op,
	PromoAppliesTo,
	PromoStage,
	PromoValueType,
	StayMatch,
	TaxKind,
)
from kamra.tex.pricing.model import (
	ContractTerms,
	ExtraDef,
	ExtraPriceRule,
	FxSnapshot,
	MarkupRule,
	PricingContext,
	Promotion,
	StayRequest,
	TaxRule,
)


def _date(v):
	return get_datetime(v).date() if v else None


def _csv(text) -> frozenset[str] | None:
	if not text:
		return None
	items = [x.strip() for x in str(text).replace("\n", ",").split(",") if x.strip()]
	return frozenset(items) or None


def guest_key(email: str | None = None, phone: str | None = None) -> str | None:
	"""Stable, non-reversible key for per-guest coupon limits (no raw PII stored)."""
	basis = (email or "").strip().lower() or "".join(ch for ch in (phone or "") if ch.isdigit())
	if not basis:
		return None
	return hashlib.sha256(("tex-guest:" + basis).encode()).hexdigest()[:32]


# ─── markups ─────────────────────────────────────────────────────────────


def markups(property: str, at: datetime) -> tuple[MarkupRule, ...]:
	fields = ("name", "revision_no", "revision_of", "property", "market", "contract", "room_type", "sales_channel",
	          "stay_from", "stay_to", "op", "value", "currency", "combine", "priority", "label")
	rows = [r for r in as_of("TEX Markup Rule", at, fields=fields) if not r.property or r.property == property]
	return tuple(
		MarkupRule(rule_id=r.name, op=Op(r.op), value=D(r.value), property=r.property or None,
		           market=r.market or None, contract=r.contract or None, room_type=r.room_type or None,
		           channel=r.sales_channel or None, stay_from=_date(r.stay_from), stay_to=_date(r.stay_to),
		           currency=r.currency or None, combine=MarkupCombine(r.combine or "REPLACE"),
		           priority=int(r.priority or 0), label=r.label or "",
		           revision=f"{r.revision_of or r.name}/r{r.revision_no or 1}")
		for r in rows)


# ─── promotions ──────────────────────────────────────────────────────────


PROMO_FIELDS = ("name", "revision_no", "revision_of", "promotion_name", "property", "hotel_group", "kind", "trigger",
                "code", "value_type", "value", "currency", "stage", "applies_to", "value_added", "sale_from",
                "sale_to", "min_lead_days", "max_lead_days", "stay_from", "stay_to", "stay_match", "min_nights",
                "max_nights", "markets", "channels", "room_types", "boards", "rate_plans", "contracts",
                "requires_extras", "member_only", "min_basket", "stackable", "exclusive", "priority", "promo_group",
                "free_nights_stay", "free_nights_pay", "usage_limit", "per_guest_limit")


def promotion_from_row(r) -> Promotion:
	root = r.revision_of or r.name
	return Promotion(
		promo_id=root, name=r.promotion_name, kind=r.kind or "PROMOTION",
		value_type=PromoValueType(r.value_type or "PERCENT"), value=D(r.value),
		stage=PromoStage(r.stage or "SELL"), applies_to=PromoAppliesTo(r.applies_to or "ACCOMMODATION"),
		currency=r.currency or None, code=((r.code or "").upper() or None) if r.trigger == "Code" else None,
		sale_from=_date(r.sale_from), sale_to=_date(r.sale_to), stay_from=_date(r.stay_from),
		stay_to=_date(r.stay_to), stay_match=StayMatch(r.stay_match or "ANY_NIGHT"),
		min_nights=r.min_nights or None, max_nights=r.max_nights or None,
		min_lead_days=r.min_lead_days or None, max_lead_days=r.max_lead_days or None,
		markets=_csv(r.markets), channels=_csv(r.channels), room_types=_csv(r.room_types), boards=_csv(r.boards),
		rate_plans=_csv(r.rate_plans), contracts=_csv(r.contracts), requires_extras=_csv(r.requires_extras),
		member_only=bool(r.member_only), min_basket=D_or_none(r.min_basket) if r.min_basket else None,
		stackable=bool(r.stackable), exclusive=bool(r.exclusive), priority=int(r.priority or 0),
		group=r.promo_group or None, free_nights_stay=r.free_nights_stay or None,
		free_nights_pay=r.free_nights_pay if r.value_type == "FREE_NIGHTS" else None,
		value_added=r.value_added or "", source=f"promotion:{root}/r{r.revision_no or 1}",
		usage_limit=r.usage_limit or None, per_guest_limit=r.per_guest_limit or None)


def promotions(property: str, at: datetime) -> tuple[Promotion, ...]:
	group = frappe.db.get_value("Property", property, "tex_hotel_group")
	rows = []
	for r in as_of("TEX Promotion", at, fields=PROMO_FIELDS):
		if r.property and r.property != property:
			continue
		if not r.property and r.hotel_group and r.hotel_group != group:
			continue
		rows.append(r)
	return tuple(promotion_from_row(r) for r in rows)


def coupon_usage(promos: tuple[Promotion, ...], gkey: str | None,
                 exclude_booking: str | None = None) -> dict[str, tuple[int, int]]:
	"""(uses, uses by this guest) per limited promotion. Repricing a booking does not count
	the booking's own redemptions against it (G-09)."""
	limited = [p.promo_id for p in promos if p.usage_limit or p.per_guest_limit]
	out = {}
	for pid in limited:
		live = {"promotion": pid, "status": ("in", ["Reserved", "Committed"])}
		if exclude_booking:
			live["booking"] = ("!=", exclude_booking)
		total = frappe.db.count("TEX Promotion Redemption", live)
		mine = frappe.db.count("TEX Promotion Redemption", {**live, "guest_key": gkey}) if gkey else 0
		out[pid] = (total, mine)
	return out


# ─── FX ──────────────────────────────────────────────────────────────────


def fx_policy(frm: str, to: str, property: str, at: datetime) -> fx_math.FxPolicy | None:
	fields = ("name", "property", "from_currency", "to_currency", "mode", "provider", "rate_type", "manual_rate",
	          "adjustment", "max_age_days")
	rows = [r for r in as_of("TEX FX Policy", at, fields=fields)
	        if r.from_currency == frm and r.to_currency == to and (not r.property or r.property == property)]
	if not rows:
		return None
	r = sorted(rows, key=lambda r: (0 if r.property else 1, r.name))[0]
	return fx_math.FxPolicy(policy_id=r.name, from_currency=frm, to_currency=to, mode=FxMode(r.mode),
	                        manual_rate=D_or_none(r.manual_rate) if r.manual_rate else None,
	                        provider=r.provider, rate_type=r.rate_type or "FOREX_SELLING",
	                        adjustment=D_or_none(r.adjustment), max_age_days=int(r.max_age_days or 4))


def provider_rates(provider: str, at: datetime, days: int = 10) -> tuple[fx_math.ProviderRate, ...]:
	on = get_datetime(at)
	rows = frappe.get_all("TEX FX Rate",
	                      filters={"provider": provider, "rate_date": ("between", [(on - timedelta(days=days)).date(),
	                                                                             on.date()]),
	                               "fetched_at": ("<=", on)},
	                      fields=["name", "provider", "base_currency", "quote_currency", "rate", "rate_date",
	                              "rate_type"])
	return tuple(fx_math.ProviderRate(r.name, r.provider, r.base_currency, r.quote_currency, D(r.rate),
	                                  get_datetime(r.rate_date).date(), r.rate_type) for r in rows)


def fx_snapshot(frm: str, to: str, property: str, at: datetime) -> FxSnapshot:
	"""Raises Unsellable when no policy/rate exists — conversion is never guessed."""
	frm, to = frm.upper(), to.upper()
	if frm == to:
		return fx_math.identity(frm, get_datetime(at))
	policy = fx_policy(frm, to, property, at)
	rates = provider_rates(policy.provider, at, max(policy.max_age_days, 1) + 3) \
		if policy and policy.mode != FxMode.MANUAL else ()
	return fx_math.resolve_fx(frm, to, policy, rates, get_datetime(at))


# ─── taxes ───────────────────────────────────────────────────────────────


def _rule(d: dict) -> TaxRule:
	return TaxRule(code=d["code"], name=d.get("name") or d["code"], kind=TaxKind(d.get("kind") or "PERCENT"),
	               rate=D(d.get("rate")), amount=D(d.get("amount")),
	               applies_to=frozenset(d.get("applies_to") or ["ACCOMMODATION"]),
	               compound=bool(d.get("compound")), order=int(d.get("order") or 0),
	               slabs=tuple((D_or_none(t), D(r)) for t, r in (d.get("slabs") or ())))


def tax_rules(property: str, room_type: str | None = None) -> tuple[TaxRule, ...]:
	prop = frappe.get_cached_doc("Property", property)
	if prop.get("tex_tax_profile") == "Custom":
		return tuple(TaxRule(code=r.code, name=r.tax_name or r.code, kind=TaxKind(r.kind or "PERCENT"),
		                     rate=D(r.rate), amount=D(r.amount), compound=bool(r.compound), order=int(r.sort_order or 0),
		                     applies_to=frozenset(x.strip() for x in (r.applies_to or "ACCOMMODATION").split(",")
		                                          if x.strip()))
		             for r in prop.get("tex_tax_rules") or [])
	from kamra.localization import pack_for

	pack = pack_for(property)
	rt = frappe.get_cached_doc("Room Type", room_type) if room_type else None
	fn = getattr(pack, "tex_tax_rules", None)
	if fn:
		return tuple(_rule(d) for d in fn(prop, rt))
	if pack.__name__.endswith(".india") and (prop.get("gst_mode") or "Slab") != "Fixed":
		threshold = D(prop.get("gst_slab_threshold") or 7500)
		slab = ((threshold, D(prop.get("gst_rate_low") or 5)), (None, D(prop.get("gst_rate_high") or 18)))
		room = TaxRule("GST", "GST", rate=slab[0][1], slabs=slab)
	else:
		room = TaxRule("TAX", "Tax", rate=D(pack.calculate_room_tax(property, rt, Decimal(0))))
	fnb = D(pack.fnb_tax_rate(property))
	return (room, TaxRule("TAX-EXTRA", "Tax", rate=fnb, applies_to=frozenset({"EXTRA:*"}), order=1))


# ─── extras ──────────────────────────────────────────────────────────────


def extras_catalog(property: str, *, online_only: bool = False, after_booking: bool = False) -> dict[str, ExtraDef]:
	filters = {"property": property, "disabled": 0}
	if online_only:
		filters["bookable_online"] = 1
	if after_booking:
		filters["bookable_after_booking"] = 1
	out = {}
	for name in frappe.get_all("TEX Extra", filters=filters, pluck="name"):
		e = frappe.get_cached_doc("TEX Extra", name)
		child = D(e.child_amount) if e.child_pricing == "CUSTOM" else None
		infant = (D(0) if e.infant_pricing == "FREE" else (D(e.infant_amount) if e.infant_pricing == "CUSTOM"
		                                                   else None))
		rules = tuple(
			ExtraPriceRule(rule_id=r.name, amount=D(r.amount),
			               child_amount=D(r.child_amount) if r.custom_child_amounts else None,
			               infant_amount=D(r.infant_amount) if r.custom_child_amounts else None,
			               market=r.market or None, room_type=r.room_type or None, channel=r.sales_channel or None,
			               stay_from=_date(r.stay_from), stay_to=_date(r.stay_to), sale_from=_date(r.sale_from),
			               sale_to=_date(r.sale_to), service_from=_date(r.service_from),
			               service_to=_date(r.service_to), priority=int(r.priority or 0))
			for r in e.price_rules)
		out[e.extra_code] = ExtraDef(
			code=e.extra_code, name=e.extra_name, pricing_mode=ExtraPricingMode(e.pricing_mode),
			currency=e.currency, amount=D(e.amount), child_amount=child, infant_amount=infant,
			category=e.category or "Service", tax_category=e.tax_category or "SERVICE",
			mandatory=bool(e.is_mandatory), sale_from=_date(e.sale_from), sale_to=_date(e.sale_to),
			service_from=_date(e.service_from), service_to=_date(e.service_to), markets=_csv(e.markets),
			channels=_csv(e.channels), room_types=_csv(e.room_types), max_quantity=e.max_quantity or None,
			price_rules=rules, inventory_tracked=bool(e.inventory_tracked))
	return out


# ─── assembly ────────────────────────────────────────────────────────────


def build_context(terms: ContractTerms, req: StayRequest, *, gkey: str | None = None,
                  extras: dict[str, ExtraDef] | None = None, exclude_booking: str | None = None) -> PricingContext:
	at = req.sale_at
	sell = req.sell_currency.upper()
	promos = promotions(req.property, at)
	catalog = extras if extras is not None else extras_catalog(req.property)
	needed = {e.currency for e in catalog.values() if e.currency != sell}
	extra_fx = {}
	for ccy in sorted(needed):
		try:
			extra_fx[ccy] = fx_snapshot(ccy, sell, req.property, at)
		except Exception:
			continue      # the extra is then reported as not convertible
	promo_fx = {}
	for ccy in sorted({p.currency for p in promos if p.currency and p.currency != sell}):
		try:
			promo_fx[ccy] = fx_snapshot(ccy, sell, req.property, at)
		except Exception:
			continue
	return PricingContext(
		terms=terms,
		fx=fx_snapshot(terms.currency, sell, req.property, at),
		markups=markups(req.property, at),
		promotions=promos,
		tax_rules=tax_rules(req.property, req.room_type),
		extras=catalog,
		extra_fx=extra_fx,
		promo_fx=promo_fx,
		coupon_usage=coupon_usage(promos, gkey, exclude_booking),
	)
