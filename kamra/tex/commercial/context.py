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
from frappe import _
from frappe.utils import get_datetime, now_datetime

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
	Unsellable,
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
                 exclude_booking: str | None = None, at: datetime | None = None) -> dict[str, tuple[int, int]]:
	"""(uses, uses by this guest) per limited promotion. Repricing a booking does not count
	the booking's own redemptions against it (G-09). ``at``: the uses held at that moment
	instead of now (a historical simulation, G-51)."""
	limited = [p.promo_id for p in promos if p.usage_limit or p.per_guest_limit]
	if at is not None:
		return {pid: _usage_at(pid, gkey, exclude_booking, get_datetime(at)) for pid in limited}
	out = {}
	for pid in limited:
		live = {"promotion": pid, "status": ("in", ["Reserved", "Committed"])}
		if exclude_booking:
			live["booking"] = ("!=", exclude_booking)
		total = frappe.db.count("TEX Promotion Redemption", live)
		mine = frappe.db.count("TEX Promotion Redemption", {**live, "guest_key": gkey}) if gkey else 0
		out[pid] = (total, mine)
	return out


def _usage_at(pid: str, gkey: str | None, exclude_booking: str | None, at: datetime) -> tuple[int, int]:
	"""The uses of ``pid`` held at ``at``: redemptions made by then and not released by then
	(``released_at``; a row released before G-51 was last written when it was released, so its
	``modified`` stands in). Later uses do not count; a use released since still does (G-51)."""
	cond = ("promotion=%(p)s AND creation <= %(at)s AND (status IN ('Reserved', 'Committed') OR "
	        "(status = 'Released' AND COALESCE(released_at, modified) > %(at)s))")
	vals = {"p": pid, "at": at, "ex": exclude_booking, "g": gkey}
	if exclude_booking:
		cond += " AND IFNULL(booking, '') != %(ex)s"
	sql = f"SELECT COUNT(*) FROM `tabTEX Promotion Redemption` WHERE {cond}"
	total = frappe.db.sql(sql, vals)[0][0]  # nosemgrep -- static conditions, values bound
	mine = frappe.db.sql(sql + " AND guest_key=%(g)s", vals)[0][0] if gkey else 0  # nosemgrep -- as above
	return int(total), int(mine)


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


def _rule(d: dict, source: str | None = None, currency: str | None = None) -> TaxRule:
	return TaxRule(code=d["code"], name=d.get("name") or d["code"], kind=TaxKind(d.get("kind") or "PERCENT"),
	               rate=D(d.get("rate")), amount=D(d.get("amount")),
	               applies_to=frozenset(d.get("applies_to") or ["ACCOMMODATION"]),
	               compound=bool(d.get("compound")), order=int(d.get("order") or 0),
	               slabs=tuple((D_or_none(t), D(r)) for t, r in (d.get("slabs") or ())), source=source,
	               currency=currency)


def _table_rules(rows, source: str, currency: str | None) -> tuple[TaxRule, ...]:
	"""TEX Tax Rule rows (a tax policy's, or a hotel's legacy custom table)."""
	return tuple(TaxRule(code=r.code, name=r.tax_name or r.code, kind=TaxKind(r.kind or "PERCENT"),
	                     rate=D(r.rate), amount=D(r.amount), compound=bool(r.compound), order=int(r.sort_order or 0),
	                     applies_to=frozenset(x.strip() for x in (r.applies_to or "ACCOMMODATION").split(",")
	                                          if x.strip()), source=source, currency=currency or None)
	             for r in rows or [])


def policy_started(property: str, at: datetime | None = None) -> bool:
	"""Has the hotel's tax policy begun by ``at`` (a revision that was really live, not a
	cancelled schedule)? From then on its taxes are only ever a policy."""
	return bool(frappe.db.sql("""SELECT 1 FROM `tabTEX Tax Policy` WHERE property=%s
	                             AND tex_status IN ('Active','Superseded','Archived') AND active_from <= %s
	                             AND (active_to IS NULL OR active_to > active_from) LIMIT 1""",
	                          (property, at or now_datetime())))


def tax_policy(property: str, at: datetime | None = None):
	"""The hotel's tax policy revision live at ``at`` (G-20), or None. Two live at once is
	refused on activation; should it ever happen, pricing stops rather than guess."""
	at = get_datetime(at) if at else now_datetime()
	rows = as_of("TEX Tax Policy", at, filters={"property": property}, fields=("name",))
	# the stay is unsellable (never priced with a guess), and only at this hotel: a search
	# over several hotels goes on (Unsellable, not a request-wide error)
	if len(rows) > 1:
		raise Unsellable("TAX_POLICY", _("{0} has more than one tax policy in force ({1}).").format(
			property, ", ".join(r.name for r in rows)), property=property)
	if not rows and policy_started(property, at):
		# once a hotel's taxes are a policy they never silently fall back to older settings
		raise Unsellable("TAX_POLICY", _("{0} has no tax policy in force at {1}.").format(property, at),
		                 property=property)
	return frappe.get_cached_doc("TEX Tax Policy", rows[0].name) if rows else None


def tax_rules(property: str, room_type: str | None = None, at: datetime | None = None) -> tuple[TaxRule, ...]:
	"""Tax rules in force at sale time ``at``: the hotel's TEX Tax Policy revision live then.
	Without one (a hotel set up after G-20 that has no policy yet), the hotel's custom
	table or its localization pack, which are not effective-dated; the rules' ``source``
	says which, and every tax step of the explanation carries it."""
	policy = tax_policy(property, at)
	if policy:
		return _table_rules(policy.rules, f"tax_policy:{policy.name}", policy.currency)
	prop = frappe.get_cached_doc("Property", property)
	if prop.get("tex_tax_profile") == "Custom":
		# not a policy yet: a fixed amount keeps its old meaning (the sell currency)
		return _table_rules(prop.get("tex_tax_rules"), f"property:{property}", None)
	from kamra.localization import pack_for

	pack = pack_for(property)
	source = f"pack:{pack.__name__.rsplit('.', 1)[-1]}"
	rt = frappe.get_cached_doc("Room Type", room_type) if room_type else None
	fn = getattr(pack, "tex_tax_rules", None)
	if fn:
		return tuple(_rule(d, source) for d in fn(prop, rt))
	if pack.__name__.endswith(".india") and (prop.get("gst_mode") or "Slab") != "Fixed":
		threshold = D(prop.get("gst_slab_threshold") or 7500)
		slab = ((threshold, D(prop.get("gst_rate_low") or 5)), (None, D(prop.get("gst_rate_high") or 18)))
		room = TaxRule("GST", "GST", rate=slab[0][1], slabs=slab, source=source)
	else:
		room = TaxRule("TAX", "Tax", rate=D(pack.calculate_room_tax(property, rt, Decimal(0))), source=source)
	fnb = D(str(pack.fnb_tax_rate(property)))
	return (room, TaxRule("TAX-EXTRA", "Tax", rate=fnb, applies_to=frozenset({"EXTRA:*"}), order=1, source=source))


# ─── extras ──────────────────────────────────────────────────────────────


EXTRA_LIST_FIELDS = ("name", "extra_code", "extra_name", "category", "description", "image", "pricing_mode",
                     "currency", "amount", "is_mandatory", "max_quantity", "service_from", "service_to",
                     "bookable_online", "bookable_after_booking", "inventory_tracked", "daily_capacity",
                     "revision_of")


def live_extras(property: str, *, at: datetime | None = None, online_only: bool = False,
                after_booking: bool = False, fields=("name", "extra_code")) -> list[dict]:
	"""The hotel's extras as sold at ``at`` (default now): one live revision per extra,
	not disabled (G-20). ``fields`` are TEX Extra columns."""
	cols = tuple(dict.fromkeys(("name", "extra_code", "disabled", "bookable_online", "bookable_after_booking",
	                            *fields)))
	live = as_of("TEX Extra", at or now_datetime(), filters={"property": property}, fields=cols)
	codes = [r.extra_code for r in live]
	clash = sorted({c for c in codes if codes.count(c) > 1})
	if clash:
		# refused on save; should it ever happen, this hotel stops selling rather than pick a price
		frappe.log_error(title=f"TEX: ambiguous extras at {property}", message=", ".join(clash))
		raise Unsellable("EXTRA_AMBIGUOUS", _("{0} has more than one live revision of extra {1}.").format(
			property, ", ".join(clash)), property=property)
	rows = [r for r in live if not r.disabled and (r.bookable_online or not online_only)
	        and (r.bookable_after_booking or not after_booking)]
	return sorted(rows, key=lambda r: r.extra_code)


def listed_extras(property: str, **kw) -> list[dict]:
	"""``live_extras`` for lists outside pricing (the booking site, CRS pickers, content): a
	hotel whose catalog is ambiguous lists no extras instead of failing the whole page."""
	try:
		return live_extras(property, **kw)
	except Unsellable:
		return []


def extras_catalog(property: str, *, online_only: bool = False, after_booking: bool = False,
                   at: datetime | None = None) -> dict[str, ExtraDef]:
	"""Extras priced as sold at ``at`` (the quote's sale time; default now)."""
	out = {}
	for row in live_extras(property, at=at, online_only=online_only, after_booking=after_booking):
		e = frappe.get_cached_doc("TEX Extra", row.name)
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
			price_rules=rules, inventory_tracked=bool(e.inventory_tracked), revision=e.name,
			cutoff_hours=int(e.get("order_cutoff_hours") or 0))
	return out


# ─── assembly ────────────────────────────────────────────────────────────


def _extra_availability(req: StayRequest, exclude_reservation: str | None):
	"""What is left of the limited extras this request asks for, over the stay (G-19)."""
	codes = {e.code for e in req.extras}
	if not codes:
		return {}
	from kamra.tex.availability import extras_repository as xinv

	return xinv.availability(req.property, codes, req.check_in, req.check_out,
	                         exclude_reservation=exclude_reservation)


def build_context(terms: ContractTerms, req: StayRequest, *, gkey: str | None = None,
                  extras: dict[str, ExtraDef] | None = None, exclude_booking: str | None = None,
                  check_capacity: bool = True, exclude_reservation: str | None = None,
                  fx_pins: dict[tuple[str, str], FxSnapshot] | None = None,
                  usage_at: datetime | None = None) -> PricingContext:
	"""``check_capacity``: whether limited extras are checked against what is left now (not in
	a historical simulation); ``exclude_reservation``: the reservation being repriced, whose
	own units count as available to it (G-19). ``fx_pins``: (from, to) → a rate recorded
	when the reservation was sold (``fx.pins``), used instead of the FX tables for that pair
	(G-56, ADR-051); any other pair is resolved as of ``req.sale_at``. ``usage_at``: coupon uses
	counted as held at that moment, not now (the historical simulator, G-51)."""
	at = req.sale_at
	sell = req.sell_currency.upper()
	pinned = fx_pins or {}

	def rate(ccy: str) -> FxSnapshot:
		ccy = ccy.upper()
		return pinned.get((ccy, sell)) or fx_snapshot(ccy, sell, req.property, at)

	promos = promotions(req.property, at)
	# extras and taxes as they were at the sale time being priced (G-20)
	catalog = extras if extras is not None else extras_catalog(req.property, at=at)
	needed = {e.currency for e in catalog.values() if e.currency != sell}
	extra_fx = {}
	for ccy in sorted(needed):
		try:
			extra_fx[ccy] = rate(ccy)
		except Exception:
			continue      # the extra is then reported as not convertible
	promo_fx = {}
	for ccy in sorted({p.currency for p in promos if p.currency and p.currency != sell}):
		try:
			promo_fx[ccy] = rate(ccy)
		except Exception:
			continue
	taxes = tax_rules(req.property, req.room_type, at=at)
	tax_fx = {}
	for ccy in sorted({r.currency.upper() for r in taxes if r.kind != TaxKind.PERCENT and r.currency
	                   and r.currency.upper() != sell}):
		try:
			tax_fx[ccy] = rate(ccy)
		except Exception:
			continue      # the stay is then unsellable (TAX_FX): a levy is never charged unconverted
	return PricingContext(
		terms=terms,
		fx=rate(terms.currency),
		markups=markups(req.property, at),
		promotions=promos,
		tax_rules=taxes,
		tax_fx=tax_fx,
		extra_availability=_extra_availability(req, exclude_reservation) if check_capacity else None,
		extras=catalog,
		extra_fx=extra_fx,
		promo_fx=promo_fx,
		coupon_usage=coupon_usage(promos, gkey, exclude_booking, at=usage_at),
	)
