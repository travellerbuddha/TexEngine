"""TEX commercial reports (R-14, R-45–R-48; ADR-038, ADR-059 and its review follow-up).

A report is one *view* over one *selection*.

Selection
- Hotels: one hotel, or a scope (enterprise, hotel group, all), always narrowed to the hotels
  where the viewer holds ``report.view`` (``portfolio.hotels_in``); a scope never widens it.
- A stay window (nights inside it), a sale window (the day each stay was sold: its TEX sale
  time, else its creation), or both at once; at most ``MAX_DAYS`` each.
- Filters: market, channel, room type, rate plan, currency (up to ``MAX_VALUES`` values each),
  whether cancelled stays count, and the date basis. A filter a view cannot apply is refused,
  never ignored.

Views
- ``production`` and ``margin`` ("contract vs selling"): room nights and money of the nights
  inside the stay window. Each stay's amounts are split over its nights in whole cents, as the
  folio bills them (``money.split_evenly``: equal shares, the remainder on the last night), so
  every grouping and every fold of a report adds up to the same totals. By stay date a row holds
  the nights of that day or month; a stay counts once, in the row of its first night in the window.
- ``promotion``, ``extras``, ``cancellation``: each selected stay counts whole.
- ``payment``: the bookings of the selected stays: value, paid, balance, and their payments per
  currency and method. Needs ``payment.view`` at every hotel.
- ``conversion``: booking-engine sessions that started in the sale window, from the funnel.

Money (ADR-059)
- Decimal and whole minor units end to end: the database splits and sums integers of the
  currency's minor unit; the API returns strings. Nothing is added across currencies.
- Contract vs selling, per stay TEX priced from a contract: revenue (what the guest pays) =
  accommodation + extras + taxes added on top; taxes are the reservation's own (a manual price
  scales them as it did the reservation's), extras the price-locked snapshot's, the accommodation
  selling price the rest; margin = accommodation − contract cost (in the selling currency at the
  rate the sale recorded); margin % = margin ÷ accommodation. Stays without a contract cost are
  revenue beside it; a cancelled stay brings only the fee it kept.
- Cost, margin and that split need ``price.view_cost`` at every hotel of the report; without it
  they are not selected at all.

Performance: every view is a fixed number of parameterised SQL aggregates, whatever the number
of stays (indexes ``tex_res_prop_ci``, ``tex_funnel_prop_time``, ``tex_funnel_site_time``, p46);
a result longer than ``MAX_ROWS`` folds its tail into one row per currency; each user may run
``RATE_LIMIT`` reports a minute.
"""

from __future__ import annotations

import json
import re
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal

import frappe
from frappe import _
from frappe.utils import add_days, getdate, nowdate

from kamra.tex.crm.service import FUNNEL_RETENTION_DAYS
from kamra.tex.money import (
	HUNDRED,
	MINOR_UNITS,
	ZERO,
	D,
	calc,
	db_dec,
	from_db,
	minor_units,
	quantize,
	to_str,
)
from kamra.tex.security import scope

VIEWS = ("production", "margin", "promotion", "extras", "cancellation", "payment", "conversion")
MAX_DAYS = 800          # below MariaDB's default max_recursive_iterations (1000): the night calendar
MAX_ROWS = 1000
MAX_VALUES = 50
MAX_OPTIONS = 2000      # room types / rate plans a filter lists (``truncated`` says when cut)
RATE_LIMIT = (60, 60)   # reports per user per window of seconds (over HTTP)
SESSION_DAYS = 2        # a booking-engine session's events are read this far around the window
OTHER = "__other__"     # the row the tail of a long result is folded into
NOT_SET = "—"
LIVE = ("Confirmed", "Checked In", "Checked Out", "Pending Payment", "Held")
CLOSED = ("Cancelled", "No Show")
BOOKED = LIVE + CLOSED
CONFIRMED = ("Confirmed", "Partially Cancelled")
TWO = Decimal("0.01")

# ─── SQL fragments: constants only; user input only ever travels as a parameter ──────────────

_CCY = "COALESCE(NULLIF(r.tex_currency, ''), NULLIF(p.currency, ''), 'EUR')"
# the currency's minor unit (10^places) and places, from ``money.MINOR_UNITS`` (code constants)
_ODD = sorted((c, m) for c, m in MINOR_UNITS.items() if m != 2)
_PLACES = "CASE {ccy} " + " ".join(f"WHEN '{c}' THEN {m}" for c, m in _ODD) + " ELSE 2 END"
_UNIT = "CASE {ccy} " + " ".join(f"WHEN '{c}' THEN {10 ** m}" for c, m in _ODD) + " ELSE 100 END"
_VALUE = "COALESCE(NULLIF(r.tex_total_amount, 0), r.amount_after_tax, 0)"
_SALE = "IFNULL(r.tex_sale_at, r.creation)"
_NIGHTS = "GREATEST(DATEDIFF(r.check_out_date, r.check_in_date), 1)"
_INSIDE = ("GREATEST(0, DATEDIFF(LEAST(r.check_out_date, CAST(%(stay_end)s AS DATE)), "
           "GREATEST(r.check_in_date, CAST(%(stay_from)s AS DATE))))")
_PRICED = "r.tex_pricing_source = 'TEX'"
_CLOSED = "r.status IN %(closed)s"
_SNAP = "IF(JSON_VALID(r.tex_pricing_snapshot), r.tex_pricing_snapshot, '{}')"


def _snap(path: str) -> str:
	return f"CAST(JSON_VALUE(r.tex_pricing_snapshot, '$.totals.{path}') AS DECIMAL(30, 9))"


# extras after booking-level coupons, add-ons included: the snapshot's subtotal − accommodation
_EXTRAS = f"IFNULL({_snap('subtotal')} - {_snap('accommodation')}, 0)"
# taxes added on top, as the reservation holds them: a manual price scaled the reservation's tax
# (``tax_amount``), of which the snapshot says which part was added on top of the price
_TAXES = (f"CASE WHEN IFNULL({_snap('tax')}, 0) = 0 THEN 0 WHEN {_snap('tax_added')} = {_snap('tax')} "
          f"THEN IFNULL(r.tax_amount, 0) ELSE ROUND(IFNULL(r.tax_amount, 0) * IFNULL({_snap('tax_added')}, 0) "
          f"/ {_snap('tax')}, {_PLACES.format(ccy=_CCY)}) END")
_GUESTS = "IFNULL(r.adults, 0) + IFNULL(r.children, 0)"
_LEAD = f"GREATEST(DATEDIFF(r.check_in_date, {_SALE}), 0)"
_MONTH, _DAY = "'%%Y-%%m'", "'%%Y-%%m-%%d'"
# one outcome of ``$.promotions[*]`` (jp) is cost-stage: its stage says so, or (a snapshot priced
# before outcomes named it) its explanation step does
_COST_STAGE = ("(IFNULL(jp.stage, '') = 'COST' OR (jp.stage IS NULL AND EXISTS (SELECT 1 FROM JSON_TABLE("
               f"{_SNAP}, '$.explanation[*]' COLUMNS (st VARCHAR(32) PATH '$.stage', rid VARCHAR(140) PATH "
               "'$.rule.rule_id', rsrc VARCHAR(255) PATH '$.rule.source')) je WHERE je.st = 'cost_offer' "
               "AND je.rid = jp.promo_id AND IFNULL(je.rsrc, '') = IFNULL(jp.source, ''))))")

# stay dimensions: reservation (r), its hotel (p), its guest (g)
STAY_KEYS = {
	"channel": "r.tex_sales_channel", "market": "r.tex_market", "room_type": "r.room_type", "board": "r.tex_board",
	"rate_plan": "r.rate_plan", "contract": "r.tex_contract", "agency": "r.travel_agent", "country": "g.tex_country",
	"status": "r.status", "hotel": "r.property", "group": "p.tex_hotel_group",
}
TIME_KEYS = ("month", "day")
DIMENSIONS = (*STAY_KEYS, *TIME_KEYS)
# booking dimensions: booking (b), its hotel (bp)
BOOKING_KEYS = {
	"payment_status": "b.payment_status", "payment_method": "b.payment_method", "status": "b.status",
	"channel": "b.sales_channel", "market": "b.market", "hotel": "b.property", "group": "bp.tex_hotel_group",
}
# booking-engine session dimensions: session (s), its site (bs), its booking (b), its hotel (sp)
SESSION_KEYS = {"site": "s.x_site", "market": "s.x_market", "hotel": "COALESCE(s.x_property, b.property)",
                "group": "COALESCE(sp.tex_hotel_group, bs.hotel_group)"}
VIEW_DIMENSIONS = {
	"production": DIMENSIONS, "margin": DIMENSIONS, "cancellation": DIMENSIONS, "promotion": (), "extras": (),
	"payment": (*BOOKING_KEYS, *TIME_KEYS), "conversion": (*TIME_KEYS, *SESSION_KEYS),
}
DEFAULT_GROUP = {"production": "channel", "margin": "channel", "cancellation": "channel", "payment": "payment_status",
                 "conversion": "day"}
# the views a filter applies to (any other view refuses it)
BASIS_VIEWS = ("production", "margin", "cancellation")          # stay or sale day / month rows
CANCELLED_VIEWS = ("production", "margin", "promotion", "extras")
STAY_FILTERS = {"market": "r.tex_market", "channel": "r.tex_sales_channel", "room_type": "r.room_type",
                "rate_plan": "r.rate_plan"}
FILTERS = (*STAY_FILTERS, "currency")
CONVERSION_FILTERS = ("market",)
# display names of dimension keys: (DocType, field)
LABELS = {"hotel": ("Property", "property_name"), "group": ("TEX Hotel Group", "group_name"),
          "room_type": ("Room Type", "room_type_name"), "rate_plan": ("Rate Plan", "rate_plan_name"),
          "contract": ("TEX Contract", "contract_name"), "agency": ("Travel Agent", "agent_name"),
          "site": ("TEX Booking Site", "site_name")}
# the parts of revenue (contract vs selling); accommodation is revenue less the others
MONEY_PARTS = ("accommodation", "extras", "taxes", "not_from_contract", "cancellation_fees")


# ─── throttle ────────────────────────────────────────────────────────────────────────────────


def throttle() -> None:
	"""At most ``RATE_LIMIT`` reports per user in a window (over HTTP; a report is a set of full
	aggregates): the next one is refused until the window ends."""
	if not getattr(frappe.local, "request", None):
		return
	limit, seconds = RATE_LIMIT
	key = frappe.cache.make_key(f"tex_report_rate:{frappe.session.user}")
	n = frappe.cache.incrby(key, 1)
	if n == 1:
		frappe.cache.expire(key, seconds)
	if n > limit:
		frappe.throw(_("Too many reports in a short time. Please wait a minute."), frappe.RateLimitExceededError)


# ─── selection ───────────────────────────────────────────────────────────────────────────────


@dataclass
class Selection:
	view: str
	hotels: list[str]
	scope: dict
	stay: tuple[date, date] | None
	sale: tuple[date, date] | None
	basis: str
	group_by: str | None
	filters: dict[str, tuple[str, ...]]
	include_cancelled: bool
	cost_visible: bool

	@property
	def params(self) -> dict:
		p: dict = {"hotels": tuple(self.hotels), "closed": CLOSED, "confirmed": CONFIRMED}
		if self.stay:
			p.update(stay_from=str(self.stay[0]), stay_to=str(self.stay[1]), stay_end=str(self.stay[1] + timedelta(1)))
		if self.sale:
			p.update(sale_from=str(self.sale[0]), sale_end=str(self.sale[1] + timedelta(1)))
		p.update({k: v for k, v in self.filters.items() if v})
		return p

	def statuses(self) -> tuple[str, ...]:
		return BOOKED if self.include_cancelled else LIVE


def _window(date_from, date_to, what: str) -> tuple[date, date] | None:
	if not date_from and not date_to:
		return None
	if not date_from or not date_to:
		frappe.throw(_("Choose both dates of the {0} period.").format(what))
	try:
		a, b = getdate(date_from), getdate(date_to)
	except Exception:
		frappe.throw(_("Choose valid dates for the {0} period.").format(what))
	if b < a:
		frappe.throw(_("The end date is before the start date."))
	if (b - a).days > MAX_DAYS:
		frappe.throw(_("Please choose a range of at most {0} days.").format(MAX_DAYS))
	return a, b


def _values(value, name: str) -> tuple[str, ...]:
	"""A filter's values: one value, or a JSON list of them (never split on commas)."""
	if value is None or value == "" or value == [] or value == ():
		return ()
	if isinstance(value, str):
		text = value.strip()
		if text.startswith("["):
			try:
				value = json.loads(text)
			except ValueError:
				frappe.throw(_("Invalid {0} filter.").format(name))
		else:
			value = [text]
	if not isinstance(value, list | tuple):
		frappe.throw(_("Invalid {0} filter.").format(name))
	out: list[str] = []
	for v in value:
		if not isinstance(v, str) or not v.strip() or len(v) > 140:
			frappe.throw(_("Invalid {0} filter.").format(name))
		out.append(v.strip())
	if len(out) > MAX_VALUES:
		frappe.throw(_("Choose at most {0} values for the {1} filter.").format(MAX_VALUES, name))
	if name == "currency":
		out = [v.upper() for v in out]
		if any(not re.fullmatch(r"[A-Z]{3}", v) for v in out):
			frappe.throw(_("Invalid {0} filter.").format(name))
	return tuple(dict.fromkeys(out))


def report_hotels(property: str | None, level: str | None, name: str | None) -> tuple[list[str], dict]:
	"""The hotels of a report: the one asked for, or those of a scope where the viewer holds
	``report.view`` (a scope with none of them is refused without confirming that it exists)."""
	from kamra.tex.reports import portfolio as pf

	if property:
		if level not in (None, "", "Hotel") or (name and name != property):
			frappe.throw(_("Choose either a hotel or a scope."))
		scope.require("report.view", property)
		return [property], {"level": "Hotel", "name": property}
	level = level or "All"
	return pf.hotels_in(level, name), {"level": level, "name": name or None}


def selection(view: str, *, property=None, level=None, name=None, group_by=None, basis=None, stay_from=None,
              stay_to=None, sale_from=None, sale_to=None, market=None, channel=None, room_type=None, rate_plan=None,
              currency=None, include_cancelled=False) -> Selection:
	if view not in VIEWS:
		frappe.throw(_("Unknown report."))
	if basis not in (None, "", "stay", "booking"):
		frappe.throw(_("Unknown date basis."))
	stay, sale = _window(stay_from, stay_to, _("stay")), _window(sale_from, sale_to, _("sale"))
	filters = {"market": _values(market, "market"), "channel": _values(channel, "channel"),
	           "room_type": _values(room_type, "room_type"), "rate_plan": _values(rate_plan, "rate_plan"),
	           "currency": _values(currency, "currency")}
	# a filter the view cannot apply is refused, never ignored
	refused = [k for k, v in filters.items() if v and view == "conversion" and k not in CONVERSION_FILTERS]
	refused += ["stay"] if stay and view == "conversion" else []
	refused += ["basis"] if basis and view not in BASIS_VIEWS else []
	refused += ["include_cancelled"] if include_cancelled and view not in CANCELLED_VIEWS else []
	refused += ["group_by"] if group_by and not VIEW_DIMENSIONS[view] else []
	if refused:
		frappe.throw(_("These filters do not apply to this report: {0}.").format(", ".join(refused)))
	if view == "conversion":
		if not sale:
			frappe.throw(_("Conversion counts booking-engine sessions on the days they happened: choose a sale period."))
		if sale[0] < getdate(nowdate()) - timedelta(days=FUNNEL_RETENTION_DAYS):
			frappe.throw(_("Booking-engine sessions are kept for {0} days: choose a later sale period.").format(
				FUNNEL_RETENTION_DAYS))
	elif not stay and not sale:
		frappe.throw(_("Choose a stay period, a sale period or both."))
	basis = basis or "stay"
	dims = VIEW_DIMENSIONS[view]
	if dims:
		group_by = group_by or DEFAULT_GROUP[view]
		if group_by not in dims:
			frappe.throw(_("Unknown grouping."))
	if group_by in TIME_KEYS and basis == "stay" and view in ("production", "margin") and not stay:
		frappe.throw(_("Grouping by stay day or month needs a stay period."))
	hotels, sc = report_hotels(property, level, name)
	cost_visible = all(scope.has_capability("price.view_cost", h) for h in hotels)
	if view == "margin" and not cost_visible:
		frappe.throw(_("Not permitted: {0}.").format("price.view_cost"), frappe.PermissionError)
	if view == "payment" and not all(scope.has_capability("payment.view", h) for h in hotels):
		frappe.throw(_("Not permitted: {0}.").format("payment.view"), frappe.PermissionError)
	return Selection(view=view, hotels=hotels, scope={**sc, "hotels": sorted(hotels)}, stay=stay, sale=sale,
	                 basis=basis, group_by=group_by or None, filters=filters,
	                 include_cancelled=bool(include_cancelled), cost_visible=cost_visible)


def _stay_where(sel: Selection, *, statuses: tuple[str, ...] | None, currency: bool = True) -> str:
	w = ["r.property IN %(hotels)s"]
	if statuses:
		w.append("r.status IN %(statuses)s")
	if sel.stay:
		w += ["r.check_in_date <= %(stay_to)s", "r.check_out_date > %(stay_from)s", f"{_INSIDE} > 0"]
	if sel.sale:
		w.append(f"{_SALE} >= %(sale_from)s AND {_SALE} < %(sale_end)s")
	for f, col in STAY_FILTERS.items():
		if sel.filters[f]:
			w.append(f"{col} IN %({f})s")
	if currency and sel.filters["currency"]:
		w.append(f"{_CCY} IN %(currency)s")
	return " AND ".join(w)


def _stay_key(sel: Selection) -> tuple[str, str]:
	"""(key expression, extra joins) of the selection's grouping of whole stays."""
	g = sel.group_by
	if g in STAY_KEYS:
		return STAY_KEYS[g], "LEFT JOIN `tabGuest` g ON g.name = r.guest" if g == "country" else ""
	fmt = _MONTH if g == "month" else _DAY
	# a whole stay: its arrival (stay date) or its sale day (booking date)
	return f"DATE_FORMAT({'r.check_in_date' if sel.basis == 'stay' else _SALE}, {fmt})", ""


# ─── helpers ─────────────────────────────────────────────────────────────────────────────────


def _dec(v) -> Decimal:
	return db_dec(v) if v is not None else ZERO


def _money(minor: int, ccy: str) -> Decimal:
	"""Whole minor units of ``ccy`` as its amount."""
	return Decimal(int(minor or 0)).scaleb(-minor_units(ccy))


def _pct(part, whole) -> str | None:
	if not whole:
		return None
	with calc():
		return to_str((D(part) / D(whole) * HUNDRED).quantize(TWO))


def _avg(total, n) -> str | None:
	if not n:
		return None
	with calc():
		return to_str((D(total) / D(n)).quantize(TWO))


def _qty(v: Decimal) -> str:
	return format(v.normalize(), "f") if v else "0"


def _fold(buckets: dict, order) -> tuple[dict, int]:
	"""At most ``MAX_ROWS`` rows: the tail (by ``order``) is added up into one ``OTHER`` row per
	currency, so the rows still add up to the totals."""
	if len(buckets) <= MAX_ROWS:
		return buckets, 0
	ccys = sorted({c for _k, c in buckets})
	keep = max(MAX_ROWS - len(ccys), 0)
	ordered = sorted(buckets, key=order)
	out = {k: buckets[k] for k in ordered[:keep]}
	for k in ordered[keep:]:
		into = out.get((OTHER, k[1]))
		if into is None:
			out[(OTHER, k[1])] = dict(buckets[k])
			continue
		for f, v in buckets[k].items():
			if isinstance(v, int | Decimal):
				into[f] += v
	return out, len(ordered) - keep


def _labels(dim: str | None, keys) -> dict[str, str]:
	spec = LABELS.get(dim or "")
	keys = sorted(k for k in keys if k not in (NOT_SET, OTHER))
	if not spec or not keys:
		return {}
	doctype, field = spec
	return {r.name: r.get(field) or r.name
	        for r in frappe.get_all(doctype, filters={"name": ("in", keys)}, fields=["name", field])}


def _envelope(sel: Selection, rows: list, totals: dict, truncated: int = 0, **extra) -> dict:
	window = sel.stay if sel.basis == "stay" and sel.stay else sel.sale or sel.stay
	return {
		"view": sel.view, "scope": sel.scope, "basis": sel.basis, "group_by": sel.group_by,
		"stay": {"from": str(sel.stay[0]), "to": str(sel.stay[1])} if sel.stay else None,
		"sale": {"from": str(sel.sale[0]), "to": str(sel.sale[1])} if sel.sale else None,
		"filters": {k: list(v) for k, v in sel.filters.items() if v}, "include_cancelled": sel.include_cancelled,
		"cost_visible": sel.cost_visible, "rows": rows, "totals": totals, "truncated": truncated,
		"labels": _labels(sel.group_by, {r["key"] for r in rows}),
		# the one-hotel report's former keys (dashboard, older clients)
		"property": sel.hotels[0] if sel.scope.get("level") == "Hotel" else None,
		"from": str(window[0]) if window else None, "to": str(window[1]) if window else None,
		**extra,
	}


def _ordered(buckets: dict, time: bool, size: str):
	"""Rows in display order: by day / month, else largest first; the folded tail last."""
	return sorted(buckets.items(), key=lambda kv: (kv[0][0] == OTHER, kv[0][0] if time else "", -kv[1][size], kv[0]))


def _fold_order(buckets: dict, time: bool, size: str):
	return lambda k: (k[0] if time else "", -buckets[k][size], k)


# ─── production and contract vs selling ──────────────────────────────────────────────────────


def _components(sel: Selection) -> dict[str, str]:
	"""Each stay's amounts to split over its nights, in whole minor units: revenue for every
	viewer; its parts and the contract cost only with cost access. A cancelled or no-show stay
	(counted only with cancelled stays included) brings the fee it kept, nothing else."""
	def minor(expr: str) -> str:
		return f"CAST(ROUND(({expr}) * {_UNIT.format(ccy=_CCY)}) AS SIGNED)"

	live_priced = f"{_PRICED} AND NOT {_CLOSED}"
	out = {"rev": minor(f"CASE WHEN {_CLOSED} THEN IFNULL(r.cancellation_fee, 0) ELSE {_VALUE} END")}
	if sel.cost_visible:
		out.update(
			fee=minor(f"CASE WHEN {_CLOSED} THEN IFNULL(r.cancellation_fee, 0) ELSE 0 END"),
			unpriced=minor(f"CASE WHEN {_PRICED} OR {_CLOSED} THEN 0 ELSE {_VALUE} END"),
			extras=minor(f"CASE WHEN {live_priced} THEN {_EXTRAS} ELSE 0 END"),
			taxes=minor(f"CASE WHEN {live_priced} THEN {_TAXES} ELSE 0 END"),
			cost=minor(f"CASE WHEN {live_priced} THEN IFNULL(r.tex_cost_amount, 0) ELSE 0 END"),
		)
	return out


def _production_rows(sel: Selection) -> list[dict]:
	"""One row per (key, currency) with whole minor units of each component, split per stay
	(``c DIV nights`` a night, the remainder on the last night)."""
	statuses = sel.statuses()
	params = {**sel.params, "statuses": statuses}
	comps = _components(sel)
	nights_in = _INSIDE if sel.stay else _NIGHTS
	last_in = "r.check_out_date <= CAST(%(stay_end)s AS DATE)" if sel.stay else "1"
	per_stay = (f"SELECT {_CCY} AS x_ccy, r.check_in_date AS x_ci, r.check_out_date AS x_co, {_NIGHTS} AS x_total, "
	            f"{nights_in} AS x_k, {last_in} AS x_last, {_GUESTS} AS x_guests, {_LEAD} AS x_lead, "
	            + ", ".join(f"{expr} AS c_{name}" for name, expr in comps.items()))
	source = (f"FROM `tabReservation` r JOIN `tabProperty` p ON p.name = r.property {{joins}} "
	          f"WHERE {_stay_where(sel, statuses=statuses)}")
	if sel.group_by in TIME_KEYS and sel.basis == "stay":
		# a row holds the nights of its day or month: the stays grouped by their dates, then each
		# group's nights inside the window (a numbers table as long as the longest of them)
		fmt = _MONTH if sel.group_by == "month" else _DAY
		night = "DATE_ADD(GREATEST(d.x_ci, CAST(%(stay_from)s AS DATE)), INTERVAL x_nums.i DAY)"
		first = "x_nums.i = 0"
		last = f"{night} = DATE_SUB(d.x_co, INTERVAL 1 DAY)"
		inside = ("DATEDIFF(LEAST(d.x_co, CAST(%(stay_end)s AS DATE)), GREATEST(d.x_ci, CAST(%(stay_from)s AS "
		          "DATE)))")
		sums = ", ".join(f"SUM(c_{n} DIV x_total) AS q_{n}, SUM(c_{n} - (c_{n} DIV x_total) * x_total) AS r_{n}"
		                 for n in comps)
		sql = (f"WITH RECURSIVE x_stay AS ({per_stay} {source.format(joins='')}), "
		       f"x_dates AS (SELECT x_ccy, x_ci, x_co, x_total, COUNT(*) AS x_n, SUM(x_guests) AS x_guests, "
		       f"SUM(x_lead) AS x_lead, {sums} FROM x_stay GROUP BY x_ccy, x_ci, x_co, x_total), "
		       f"x_len AS (SELECT MAX({inside.replace('d.', '')}) AS m FROM x_dates), "
		       f"x_nums (i) AS (SELECT 0 UNION ALL SELECT i + 1 FROM x_nums, x_len WHERE i + 1 < x_len.m) "
		       f"SELECT DATE_FORMAT({night}, {fmt}) AS x_key, d.x_ccy, "
		       f"SUM(IF({first}, d.x_n, 0)) AS x_n, SUM(d.x_n) AS x_nights, SUM(IF({first}, d.x_guests, 0)) AS x_guests, "
		       f"SUM(IF({first}, d.x_lead, 0)) AS x_lead, SUM(IF({first}, d.x_total * d.x_n, 0)) AS x_los, "
		       + ", ".join(f"SUM(d.q_{n} + IF({last}, d.r_{n}, 0)) AS x_{n}" for n in comps)
		       + f" FROM x_dates d JOIN x_nums ON x_nums.i < {inside} GROUP BY x_key, d.x_ccy")
		return frappe.db.sql(sql, params, as_dict=True)
	key, joins = _stay_key(sel)
	per_stay = per_stay.replace("SELECT ", f"SELECT {key} AS x_key, ", 1)
	sql = ("SELECT x_key, x_ccy, COUNT(*) AS x_n, SUM(x_k) AS x_nights, SUM(x_guests) AS x_guests, "
	       "SUM(x_lead) AS x_lead, SUM(x_total) AS x_los, "
	       + ", ".join(f"SUM((c_{n} DIV x_total) * x_k + IF(x_last, c_{n} - (c_{n} DIV x_total) * x_total, 0)) AS x_{n}"
	                   for n in comps)
	       + f" FROM ({per_stay} {source.format(joins=joins)}) s GROUP BY x_key, x_ccy")
	return frappe.db.sql(sql, params, as_dict=True)


def production(sel_or_property, date_from=None, date_to=None, *, group_by: str = "channel", basis: str = "stay",
               include_cancelled: bool = False, **filters) -> dict:
	"""Production, and contract vs selling (``margin``). The former one-hotel signature
	``production(property, date_from, date_to, group_by=, basis=)`` still works: the dates are
	the stay or the sale window by ``basis``."""
	if isinstance(sel_or_property, Selection):
		sel = sel_or_property
	else:
		window = {"stay_from": date_from, "stay_to": date_to} if basis == "stay" else \
			{"sale_from": date_from, "sale_to": date_to}
		sel = selection("production", property=sel_or_property, group_by=group_by, basis=basis,
		                include_cancelled=include_cancelled, **window, **filters)
	cost = sel.cost_visible
	names = list(_components(sel))
	buckets: dict = defaultdict(lambda: {"n": 0, "nights": 0, "guests": 0, "lead": 0, "los": 0,
	                                     **dict.fromkeys(names, 0)})
	for r in _production_rows(sel):
		b = buckets[(r.x_key or NOT_SET, r.x_ccy)]
		for k in ("n", "nights", "guests", "lead", "los", *names):
			b[k] += int(r[f"x_{k}"] or 0)
	time = sel.group_by in TIME_KEYS
	buckets = dict(buckets)
	buckets, truncated = _fold(buckets, _fold_order(buckets, time, "nights"))
	rows, totals = [], {}
	for (key, ccy), b in _ordered(buckets, time, "nights"):
		row = {"key": key, "currency": ccy, "bookings": b["n"], "room_nights": b["nights"], "guests": b["guests"],
		       "revenue": _money(b["rev"], ccy)}
		if cost:
			parts = {"extras": b["extras"], "taxes": b["taxes"], "not_from_contract": b["unpriced"],
			         "cancellation_fees": b["fee"]}
			row["accommodation"] = _money(b["rev"] - sum(parts.values()), ccy)
			row.update({k: _money(v, ccy) for k, v in parts.items()})
			row["cost"] = _money(b["cost"], ccy)
			row["margin"] = row["accommodation"] - row["cost"]
		money = [k for k in ("revenue", *MONEY_PARTS, "cost", "margin") if k in row]
		t = totals.setdefault(ccy, {"bookings": 0, "room_nights": 0, "guests": 0, "los": 0, "lead": 0,
		                            **dict.fromkeys(money, ZERO)})
		for k in ("bookings", "room_nights", "guests", *money):
			t[k] += row[k]
		t["los"] += b["los"]
		t["lead"] += b["lead"]
		rows.append(_finish(row, b["los"], b["lead"], ccy))
	return _envelope(sel, rows, {c: _finish(t, t.pop("los"), t.pop("lead"), c) for c, t in totals.items()}, truncated)


def _finish(row: dict, los: int, lead: int, ccy: str) -> dict:
	"""A production row or total: averages, percentages, money as strings."""
	out = dict(row)
	with calc():
		out["adr"] = quantize(row["revenue"] / row["room_nights"], ccy) if row["room_nights"] else None
	out["avg_los"] = _avg(los, row["bookings"])
	out["avg_lead_days"] = _avg(lead, row["bookings"])
	if "margin" in row:
		out["margin_pct"] = _pct(row["margin"], row["accommodation"])
	for k in ("revenue", "adr", *MONEY_PARTS, "cost", "margin"):
		if out.get(k) is not None:
			out[k] = to_str(out[k])
	return out


# ─── promotions and extras (whole stays) ─────────────────────────────────────────────────────


def _promotion(sel: Selection) -> dict:
	"""Per promotion applied: the stays it applied to, their nights and revenue, the discount
	it gave on the selling price (the rounded discount lines). A cost-stage offer lowers the
	contract cost: it is listed, with that reduction (at the rate the sale recorded, rounded per
	stay), only with cost access."""
	statuses = sel.statuses()
	where, params = _stay_where(sel, statuses=statuses), {**sel.params, "statuses": statuses}
	cost = sel.cost_visible
	places = _PLACES.format(ccy=_CCY)
	reduction = (f"MAX(IF({_COST_STAGE}, ROUND(jp.discount * IFNULL(CAST(JSON_VALUE(r.tex_pricing_snapshot, "
	             f"'$.fx.sell_rate') AS DECIMAL(30, 12)), 1), {places}), 0))")
	applied = frappe.db.sql(f"""
		SELECT x_key, MAX(x_name) AS x_name, MAX(x_kind) AS x_kind, x_ccy, COUNT(*) AS x_n,
		       SUM(x_nights) AS x_nights, CAST(SUM(x_value) AS CHAR) AS x_value, MAX(x_cost) AS x_cost,
		       CAST(SUM(x_reduction) AS CHAR) AS x_reduction
		FROM (SELECT r.name, jp.promo_id AS x_key, MAX(jp.promo_name) AS x_name, MAX(jp.kind) AS x_kind,
		             {_CCY} AS x_ccy, MAX({_NIGHTS}) AS x_nights, MAX({_VALUE}) AS x_value,
		             MAX({_COST_STAGE}) AS x_cost, {reduction if cost else '0'} AS x_reduction
		      FROM `tabReservation` r JOIN `tabProperty` p ON p.name = r.property
		      JOIN JSON_TABLE({_SNAP}, '$.promotions[*]' COLUMNS (
		           promo_id VARCHAR(140) PATH '$.promo_id', promo_name VARCHAR(140) PATH '$.name',
		           kind VARCHAR(64) PATH '$.kind', applied VARCHAR(8) PATH '$.applied',
		           stage VARCHAR(8) PATH '$.stage', source VARCHAR(255) PATH '$.source',
		           discount DECIMAL(30, 9) PATH '$.discount')) jp
		      WHERE {where} AND jp.applied = 'true' AND jp.promo_id IS NOT NULL{'' if cost else f' AND NOT {_COST_STAGE}'}
		      GROUP BY r.name, x_key, x_ccy) s
		GROUP BY x_key, x_ccy""", params, as_dict=True)
	discounts = frappe.db.sql(f"""
		SELECT jl.code AS x_key, {_CCY} AS x_ccy, CAST(SUM(jl.amount) AS CHAR) AS x_amount
		FROM `tabReservation` r JOIN `tabProperty` p ON p.name = r.property
		JOIN JSON_TABLE({_SNAP}, '$.lines[*]' COLUMNS (
		     kind VARCHAR(16) PATH '$.kind', code VARCHAR(140) PATH '$.code',
		     amount DECIMAL(30, 9) PATH '$.amount')) jl
		WHERE {where} AND jl.kind IN ('DISCOUNT', 'COUPON') AND jl.code IS NOT NULL
		GROUP BY x_key, x_ccy""", params, as_dict=True)
	buckets: dict = {}
	for r in applied:
		buckets[(r.x_key, r.x_ccy)] = {"name": r.x_name or r.x_key, "kind": r.x_kind, "n": int(r.x_n),
		                               "cost_stage": bool(r.x_cost), "nights": int(r.x_nights or 0),
		                               "value": _dec(r.x_value), "discount": ZERO, "reduction": _dec(r.x_reduction)}
	for r in discounts:
		b = buckets.get((r.x_key, r.x_ccy))
		if b is not None:                                 # the discount lines of a listed promotion
			b["discount"] -= _dec(r.x_amount)             # discount lines are negative
	buckets, truncated = _fold(buckets, _fold_order(buckets, False, "n"))
	rows, totals = [], {}
	for (key, ccy), b in _ordered(buckets, False, "n"):
		discount = quantize(b["discount"], ccy)
		row = {"key": key, "name": b["name"] if key != OTHER else None, "kind": b["kind"] if key != OTHER else None,
		       "stage": ("COST" if b["cost_stage"] else "SELL") if key != OTHER else None, "currency": ccy,
		       "applications": b["n"], "room_nights": b["nights"], "revenue": to_str(quantize(b["value"], ccy)),
		       "discount": to_str(discount)}
		t = totals.setdefault(ccy, {"applications": 0, "discount": ZERO, **({"cost_reduction": ZERO} if cost else {})})
		t["applications"] += b["n"]
		t["discount"] += discount
		if cost:
			reduction = quantize(b["reduction"], ccy)
			row["cost_reduction"] = to_str(reduction)
			t["cost_reduction"] += reduction
		rows.append(row)
	return _envelope(sel, rows, {c: {k: to_str(v) if isinstance(v, Decimal) else v for k, v in t.items()}
	                             for c, t in totals.items()}, truncated)


def _extras(sel: Selection) -> dict:
	statuses = sel.statuses()
	found = frappe.db.sql(f"""
		SELECT jl.code AS x_key, MAX(jl.descr) AS x_name, {_CCY} AS x_ccy, COUNT(DISTINCT r.name) AS x_n,
		       CAST(SUM(jl.quantity) AS CHAR) AS x_qty, CAST(SUM(jl.amount) AS CHAR) AS x_amount
		FROM `tabReservation` r JOIN `tabProperty` p ON p.name = r.property
		JOIN JSON_TABLE({_SNAP}, '$.lines[*]' COLUMNS (
		     kind VARCHAR(16) PATH '$.kind', code VARCHAR(140) PATH '$.code', descr VARCHAR(255) PATH '$.description',
		     quantity DECIMAL(30, 9) PATH '$.quantity', amount DECIMAL(30, 9) PATH '$.amount')) jl
		WHERE {_stay_where(sel, statuses=statuses)} AND jl.kind = 'EXTRA' AND jl.code IS NOT NULL
		GROUP BY x_key, x_ccy""", {**sel.params, "statuses": statuses}, as_dict=True)
	buckets = {(r.x_key, r.x_ccy): {"name": r.x_name or r.x_key, "n": int(r.x_n), "qty": _dec(r.x_qty),
	                                "amount": _dec(r.x_amount)} for r in found}
	buckets, truncated = _fold(buckets, _fold_order(buckets, False, "n"))
	rows, totals = [], {}
	for (key, ccy), b in _ordered(buckets, False, "n"):
		amount = quantize(b["amount"], ccy)
		rows.append({"key": key, "name": b["name"] if key != OTHER else None, "currency": ccy, "stays": b["n"],
		             "quantity": _qty(b["qty"]), "amount": to_str(amount)})
		totals[ccy] = totals.get(ccy, ZERO) + amount
	return _envelope(sel, rows, {c: {"amount": to_str(v)} for c, v in totals.items()}, truncated)


# ─── cancellations (whole stays) ─────────────────────────────────────────────────────────────


def _cancellation(sel: Selection) -> dict:
	key, joins = _stay_key(sel)
	found = frappe.db.sql(f"""
		SELECT {key} AS x_key, {_CCY} AS x_ccy, COUNT(*) AS x_n,
		       SUM(r.status = 'Cancelled') AS x_cancelled, SUM(r.status = 'No Show') AS x_no_shows,
		       SUM(CASE WHEN {_CLOSED} THEN {_NIGHTS} ELSE 0 END) AS x_nights,
		       CAST(SUM(CASE WHEN {_CLOSED} THEN {_VALUE} ELSE 0 END) AS CHAR) AS x_value,
		       CAST(SUM(CASE WHEN {_CLOSED} THEN IFNULL(r.cancellation_fee, 0) ELSE 0 END) AS CHAR) AS x_fees,
		       SUM(CASE WHEN r.status = 'Cancelled' AND r.cancelled_on IS NOT NULL
		                THEN GREATEST(DATEDIFF(r.check_in_date, r.cancelled_on), 0) ELSE 0 END) AS x_lead,
		       SUM(r.status = 'Cancelled' AND r.cancelled_on IS NOT NULL) AS x_lead_n
		FROM `tabReservation` r JOIN `tabProperty` p ON p.name = r.property {joins}
		WHERE {_stay_where(sel, statuses=BOOKED)}
		GROUP BY x_key, x_ccy""", {**sel.params, "statuses": BOOKED}, as_dict=True)
	counts = ("n", "cancelled", "no_shows", "nights", "lead", "lead_n")
	buckets = {(r.x_key or NOT_SET, r.x_ccy): {**{k: int(r[f"x_{k}"] or 0) for k in counts},
	                                           "value": _dec(r.x_value), "fees": _dec(r.x_fees)} for r in found}
	time = sel.group_by in TIME_KEYS
	buckets, truncated = _fold(buckets, _fold_order(buckets, time, "n"))
	rows, totals = [], {}
	for (key, ccy), b in _ordered(buckets, time, "n"):
		b = {**b, "value": quantize(b["value"], ccy), "fees": quantize(b["fees"], ccy)}
		rows.append({"key": key, "currency": ccy, **_cancel_figures(b)})
		t = totals.setdefault(ccy, {**dict.fromkeys(counts, 0), "value": ZERO, "fees": ZERO})
		for k in (*counts, "value", "fees"):
			t[k] += b[k]
	return _envelope(sel, rows, {c: _cancel_figures(t) for c, t in totals.items()}, truncated)


def _cancel_figures(b: dict) -> dict:
	"""Cancelled figures count cancellations and no-shows; fees are what they kept."""
	return {"stays": b["n"], "cancelled": b["cancelled"], "no_shows": b["no_shows"],
	        "cancelled_pct": _pct(b["cancelled"] + b["no_shows"], b["n"]), "cancelled_nights": b["nights"],
	        "cancelled_value": to_str(b["value"]), "fees": to_str(b["fees"]), "net_lost": to_str(b["value"] - b["fees"]),
	        "avg_days_before_arrival": _avg(b["lead"], b["lead_n"])}


# ─── payments (the bookings of the selected stays) ───────────────────────────────────────────


# a payment's booking: its own, else its charge's (a refund that touched no booking: a late payment's,
# C7), else its payment link's (a link's charge)
_TXN_OF_BOOKING = """`tabTEX Payment Transaction` t
		LEFT JOIN `tabTEX Payment Transaction` pt ON pt.name = t.parent_transaction
		LEFT JOIN `tabTEX Payment Link` pl ON pl.name = COALESCE(t.payment_link, pt.payment_link)
		JOIN `tabTEX Booking` b ON b.name = COALESCE(t.booking, pt.booking, pl.booking)"""


def _payment(sel: Selection) -> dict:
	"""Booking value and paid in the booking's currency; payments in their own currency (a payment
	in another currency than its booking is in that currency's row, as in the payments by method)."""
	g = sel.group_by
	key = f"DATE_FORMAT(IFNULL(b.sale_at, b.creation), {_MONTH if g == 'month' else _DAY})" if g in TIME_KEYS \
		else BOOKING_KEYS[g]
	# every booking with a stay in the selection, whatever that stay's status: a cancelled stay
	# keeps its fee, payments and refunds
	stays = (f"SELECT r.tex_booking FROM `tabReservation` r JOIN `tabProperty` p ON p.name = r.property "
	         f"WHERE {_stay_where(sel, statuses=None, currency=False)} AND r.tex_booking IS NOT NULL")
	bccy = "COALESCE(NULLIF(b.currency, ''), NULLIF(bp.currency, ''), 'EUR')"
	tccy = f"COALESCE(NULLIF(t.currency, ''), {bccy})"
	where = f"b.property IN %(hotels)s AND b.status != 'Draft' AND b.name IN ({stays})"
	# a capture TEX refused to count (G-67) is no charge (Failed), so its refund is no refund of the
	# booking's money: both left out, never one alone (K1)
	txn = f"t.property IN %(hotels)s AND {where} AND NOT (t.txn_type = 'Refund' AND IFNULL(pt.status, 'Succeeded') != 'Succeeded')"
	if sel.filters["currency"]:
		where += f" AND {bccy} IN %(currency)s"
		txn += f" AND {tccy} IN %(currency)s"
	params = sel.params
	found = frappe.db.sql(f"""
		SELECT {key} AS x_key, {bccy} AS x_ccy, COUNT(*) AS x_n,
		       CAST(SUM(IFNULL(b.total_amount, 0)) AS CHAR) AS x_value,
		       CAST(SUM(IFNULL(b.paid_amount, 0)) AS CHAR) AS x_paid
		FROM `tabTEX Booking` b JOIN `tabProperty` bp ON bp.name = b.property
		WHERE {where}
		GROUP BY x_key, x_ccy""", params, as_dict=True)
	moved = frappe.db.sql(f"""
		SELECT {key} AS x_key, {tccy} AS x_ccy,
		       CAST(SUM(CASE WHEN t.txn_type = 'Charge' AND t.status = 'Succeeded' THEN t.amount ELSE 0 END) AS CHAR)
		         AS x_charged,
		       CAST(SUM(CASE WHEN t.txn_type = 'Refund' AND t.status = 'Succeeded' THEN t.amount ELSE 0 END) AS CHAR)
		         AS x_refunded,
		       CAST(SUM(CASE WHEN t.txn_type = 'Charge' AND t.status = 'Pending' THEN t.amount ELSE 0 END) AS CHAR)
		         AS x_pending
		FROM {_TXN_OF_BOOKING}
		JOIN `tabProperty` bp ON bp.name = b.property
		WHERE {txn}
		GROUP BY x_key, x_ccy""", params, as_dict=True)
	by_method = frappe.db.sql(f"""
		SELECT t.method AS x_method, IFNULL(t.provider, '') AS x_provider, {tccy} AS x_ccy,
		       SUM(t.txn_type = 'Charge') AS x_charges, SUM(t.txn_type = 'Refund') AS x_refunds,
		       CAST(SUM(CASE WHEN t.txn_type = 'Charge' THEN t.amount ELSE 0 END) AS CHAR) AS x_charged,
		       CAST(SUM(CASE WHEN t.txn_type = 'Refund' THEN t.amount ELSE 0 END) AS CHAR) AS x_refunded
		FROM {_TXN_OF_BOOKING}
		JOIN `tabProperty` bp ON bp.name = b.property
		WHERE t.status = 'Succeeded' AND t.txn_type IN ('Charge', 'Refund') AND {txn}
		GROUP BY x_method, x_provider, x_ccy""", params, as_dict=True)
	money = ("value", "paid", "charged", "refunded", "pending")
	buckets: dict = defaultdict(lambda: {"n": 0, **dict.fromkeys(money, ZERO)})
	for r in found:
		b = buckets[(r.x_key or NOT_SET, r.x_ccy)]
		b["n"] += int(r.x_n)
		b["value"] += _dec(r.x_value)
		b["paid"] += _dec(r.x_paid)
	for r in moved:
		b = buckets[(r.x_key or NOT_SET, r.x_ccy)]
		for k in ("charged", "refunded", "pending"):
			b[k] += _dec(r[f"x_{k}"])
	time = g in TIME_KEYS
	buckets = dict(buckets)
	buckets, truncated = _fold(buckets, _fold_order(buckets, time, "n"))
	rows, totals = [], {}
	for (key, ccy), b in _ordered(buckets, time, "n"):
		m = {k: quantize(b[k], ccy) for k in money}
		rows.append({"key": key, "currency": ccy, "bookings": b["n"], **{k: to_str(v) for k, v in m.items()},
		             "balance": to_str(m["value"] - m["paid"])})
		t = totals.setdefault(ccy, {"bookings": 0, **dict.fromkeys(money, ZERO)})
		t["bookings"] += b["n"]
		for k in money:
			t[k] += m[k]
	methods, method_totals = [], {}
	for r in sorted(by_method, key=lambda r: (r.x_ccy, r.x_method or "", r.x_provider)):
		charged, refunded = from_db(_dec(r.x_charged), r.x_ccy), from_db(_dec(r.x_refunded), r.x_ccy)
		methods.append({"method": r.x_method, "provider": r.x_provider or None, "currency": r.x_ccy,
		                "charges": int(r.x_charges or 0), "refunds": int(r.x_refunds or 0), "charged": to_str(charged),
		                "refunded": to_str(refunded), "net": to_str(charged - refunded)})
		mt = method_totals.setdefault(r.x_ccy, {"charged": ZERO, "refunded": ZERO})
		mt["charged"] += charged
		mt["refunded"] += refunded
	return _envelope(
		sel, rows,
		{c: {"bookings": t["bookings"], **{k: to_str(t[k]) for k in money}, "balance": to_str(t["value"] - t["paid"])}
		 for c, t in totals.items()}, truncated, methods=methods,
		method_totals={c: {"charged": to_str(t["charged"]), "refunded": to_str(t["refunded"]),
		                   "net": to_str(t["charged"] - t["refunded"])} for c, t in method_totals.items()})


# ─── conversion (booking-engine sessions of the sale window) ─────────────────────────────────


CONVERSION = ("sessions", "searched", "quoted", "details", "booked", "confirmed")
# a stage counts as reached when it or a later one happened (a guest who quoted searched too)
STAGES = {"searched": ("search", "room_view", "quote", "guest_details", "payment_started", "booked"),
          "quoted": ("quote", "guest_details", "payment_started", "booked"),
          "details": ("guest_details", "payment_started", "booked"),
          "booked": ("payment_started", "booked")}


def group_sites(hotels: list[str]) -> list[str]:
	"""The hotel-group booking sites whose every hotel is in ``hotels``: their sessions record no
	hotel, so they are the report's only when it covers the whole group (never another hotel's)."""
	sites = frappe.get_all("TEX Booking Site", filters={"property": ("is", "not set"), "hotel_group": ("is", "set")},
	                       fields=["name", "hotel_group"])
	if not sites:
		return []
	members: dict = defaultdict(set)
	for r in frappe.get_all("Property", filters={"tex_hotel_group": ("in", sorted({s.hotel_group for s in sites})),
	                                             "disabled": 0}, fields=["name", "tex_hotel_group"]):
		members[r.tex_hotel_group].add(r.name)
	mine = set(hotels)
	return sorted(s.name for s in sites if members[s.hotel_group] and members[s.hotel_group] <= mine)


def _conversion(sel: Selection) -> dict:
	"""Each session counts once, in the window of its first event (its events up to
	``SESSION_DAYS`` around the window are read), and every stage it reached implies the ones
	before it: no stage exceeds the one before, and conversion never exceeds 100 %."""
	g = sel.group_by
	key = f"DATE_FORMAT(s.x_first, {_MONTH if g == 'month' else _DAY})" if g in TIME_KEYS else SESSION_KEYS[g]
	market = " AND s.x_market IN %(market)s" if sel.filters["market"] else ""
	params = {**sel.params, "group_sites": tuple(group_sites(sel.hotels)) or ("",),
	          "ev_from": str(sel.sale[0] - timedelta(days=SESSION_DAYS)),
	          "ev_end": str(sel.sale[1] + timedelta(days=1 + SESSION_DAYS))}
	stages = ", ".join(f"MAX(e.event IN ({', '.join(repr(x) for x in events)})) AS x_{name}"
	                   for name, events in STAGES.items())
	found = frappe.db.sql(f"""
		SELECT {key} AS x_key, COUNT(*) AS x_sessions, SUM(s.x_searched) AS x_searched, SUM(s.x_quoted) AS x_quoted,
		       SUM(s.x_details) AS x_details, SUM(s.x_booked) AS x_booked,
		       SUM(IFNULL(b.status IN %(confirmed)s, 0)) AS x_confirmed
		FROM (SELECT e.session_id, e.site AS x_site, MAX(e.property) AS x_property, MIN(e.occurred_at) AS x_first,
		             MAX(CASE WHEN e.event = 'search' THEN JSON_VALUE(e.payload, '$.market') END) AS x_market,
		             {stages},
		             MAX(CASE WHEN e.event IN ('payment_started', 'booked')
		                      THEN JSON_VALUE(e.payload, '$.booking') END) AS x_booking
		      FROM `tabTEX Funnel Event` e
		      WHERE (e.property IN %(hotels)s OR e.site IN %(group_sites)s)
		        AND e.occurred_at >= %(ev_from)s AND e.occurred_at < %(ev_end)s
		      GROUP BY e.session_id, e.site
		      HAVING x_first >= %(sale_from)s AND x_first < %(sale_end)s) s
		LEFT JOIN `tabTEX Booking Site` bs ON bs.name = s.x_site
		LEFT JOIN `tabTEX Booking` b ON b.name = s.x_booking AND b.property IN %(hotels)s
		LEFT JOIN `tabProperty` sp ON sp.name = COALESCE(s.x_property, b.property)
		WHERE 1 = 1{market}
		GROUP BY x_key""", params, as_dict=True)
	buckets = {(r.x_key or NOT_SET, ""): {k: int(r[f"x_{k}"] or 0) for k in CONVERSION} for r in found}
	time = g in TIME_KEYS
	buckets, truncated = _fold(buckets, _fold_order(buckets, time, "sessions"))
	total = dict.fromkeys(CONVERSION, 0)
	rows = []
	for (key, _c), b in _ordered(buckets, time, "sessions"):
		rows.append({"key": key, **b, **_rates(b)})
		for k in CONVERSION:
			total[k] += b[k]
	return _envelope(sel, rows, {**total, **_rates(total)}, truncated)


def _rates(b: dict) -> dict:
	return {"conversion_pct": _pct(b["booked"], b["searched"]), "confirmed_pct": _pct(b["confirmed"], b["searched"])}


# ─── entry points ────────────────────────────────────────────────────────────────────────────


def report(view: str, **kw) -> dict:
	sel = selection(view, **kw)
	if view in ("production", "margin"):
		return production(sel)
	return {"promotion": _promotion, "extras": _extras, "cancellation": _cancellation, "payment": _payment,
	        "conversion": _conversion}[view](sel)


def filter_options(property=None, level=None, name=None) -> dict:
	"""What the report filters offer for a scope: its hotels' room types and rate plans (at most
	``MAX_OPTIONS`` each; ``truncated`` says when a list was cut)."""
	hotels, sc = report_hotels(property, level, name)
	out = {"scope": {**sc, "hotels": sorted(hotels)},
	       "cost_visible": all(scope.has_capability("price.view_cost", h) for h in hotels), "truncated": {},
	       "limit": MAX_OPTIONS}
	for key, doctype, field in (("room_types", "Room Type", "room_type_name"),
	                            ("rate_plans", "Rate Plan", "rate_plan_name")):
		rows = frappe.get_all(doctype, filters={"property": ("in", hotels)}, fields=["name", field, "property"],
		                      order_by=f"property asc, {field} asc", limit=MAX_OPTIONS + 1)
		out["truncated"][key] = len(rows) > MAX_OPTIONS
		out[key] = [{"name": r.name, "label": r.get(field) or r.name, "hotel": r.property} for r in rows[:MAX_OPTIONS]]
	return out


def _one_window(date_from, date_to) -> tuple[date, date]:
	w = _window(date_from, date_to, _("report"))
	if not w:
		frappe.throw(_("Choose a start and an end date."))
	return w


def dashboard(property: str, date_from=None, date_to=None) -> dict:
	scope.require("report.view", property)
	today = getdate(nowdate())
	a, b = _one_window(date_from or today.replace(day=1),
	                   date_to or add_days(today.replace(day=1), 40).replace(day=1) - timedelta(days=1))
	default_ccy = frappe.db.get_value("Property", property, "currency") or "EUR"
	stay = production(property, a, b, group_by="channel", basis="stay")
	booked = production(property, a, b, group_by="day", basis="booking")
	cancelled = frappe.db.count("Reservation", {"property": property, "status": "Cancelled",
	                                            "cancelled_on": ("between", [str(a), f"{b} 23:59:59"])})
	created = frappe.db.count("Reservation", {"property": property, "creation": ("between", [str(a),
	                                                                                           f"{b} 23:59:59"])})
	arrivals = frappe.db.count("Reservation", {"property": property, "check_in_date": today,
	                                           "status": ("in", ["Confirmed", "Pending Payment"])})
	departures = frappe.db.count("Reservation", {"property": property, "check_out_date": today,
	                                             "status": ("in", ["Confirmed", "Checked In"])})
	pending_changes = frappe.db.count("Reservation", {"property": property, "tex_guest_change_pending": 1})
	unpaid = frappe.get_all("TEX Booking", filters={"property": property, "payment_status": ("in", ["Unpaid",
	                                                                                               "Partially Paid"]),
	                                                "status": ("not in", ["Cancelled"])},
	                        fields=["currency", "balance_amount"], limit_page_length=0)
	balance: dict = defaultdict(lambda: ZERO)
	for u in unpaid:
		balance[u.currency or default_ccy] += from_db(u.balance_amount, u.currency or default_ccy)
	funnel = frappe.db.sql("""SELECT event, COUNT(DISTINCT session_id) n FROM `tabTEX Funnel Event`
		WHERE property=%s AND occurred_at BETWEEN %s AND %s GROUP BY event""",
	                       (property, str(a), f"{b} 23:59:59"), as_dict=True)
	f = {r.event: r.n for r in funnel}
	searches = f.get("search", 0)
	abandoned = frappe.db.count("TEX Abandoned Booking", [["property", "=", property], ["status", "=", "Open"],
	                                                      ["last_event_at", "is", "set"],
	                                                      ["last_event_at", ">=", str(a)]])
	return {
		"property": property, "from": str(a), "to": str(b), "currency": default_ccy,
		"stay": stay["totals"], "by_channel": stay["rows"], "pickup_by_day": booked["rows"],
		"reservations_created": created, "cancellations": cancelled,
		"cancellation_rate": to_str(quantize(D(cancelled) / D(created) * 100, "EUR")) if created else None,
		"today": {"arrivals": arrivals, "departures": departures}, "guest_changes_pending": pending_changes,
		"open_balance": {c: to_str(v) for c, v in balance.items()},
		"funnel": {"search": searches, "quote": f.get("quote", 0), "guest_details": f.get("guest_details", 0),
		           "payment_started": f.get("payment_started", 0), "booked": f.get("booked", 0),
		           "conversion_pct": to_str(quantize(D(f.get("booked", 0)) / D(searches) * 100, "EUR"))
		           if searches else None},
		"abandoned_open": abandoned,
	}


def _nights_in(r, a: date, b: date) -> tuple[int, int]:
	ci, co = getdate(r.check_in_date), getdate(r.check_out_date)
	total = max(1, (co - ci).days)
	lo, hi = max(ci, a), min(co, b + timedelta(days=1))
	return max(0, (hi - lo).days), total


def pace(property: str, stay_from, stay_to, *, as_of_days: tuple[int, ...] = (0, 7, 14, 30, 60, 90)) -> dict:
	"""On-the-books room nights for a stay window as they stood N days ago (pick-up)."""
	scope.require("report.view", property)
	a, b = _one_window(stay_from, stay_to)
	today = getdate(nowdate())
	rows = frappe.get_all("Reservation", filters={"property": property, "check_in_date": ("<=", b),
	                                              "check_out_date": (">", a)},
	                      fields=["check_in_date", "check_out_date", "creation", "status", "cancelled_on"],
	                      limit_page_length=0)
	out = []
	for n in as_of_days:
		at = today - timedelta(days=n)
		nights = 0
		for r in rows:
			if getdate(r.creation) > at:
				continue
			if r.status in ("Cancelled", "No Show") and r.cancelled_on and getdate(r.cancelled_on) <= at:
				continue
			inside, _total = _nights_in(r, a, b)
			nights += inside
		out.append({"days_ago": n, "as_of": str(at), "room_nights": nights})
	return {"property": property, "from": str(a), "to": str(b), "points": out}
