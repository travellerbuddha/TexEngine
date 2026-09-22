"""TEX commercial reports (R-45, R-46).

All figures are computed from reservations with Decimal; money is grouped per
currency (never summed across currencies). Stay-date reports prorate each
reservation's value by the nights that fall inside the window; booking-date
reports count the whole reservation on its sale date. Cost and margin are included
only for users holding ``price.view_cost`` at the hotel.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date, timedelta

import frappe
from frappe import _
from frappe.utils import add_days, getdate, nowdate

from kamra.tex.money import ZERO, D, from_db, quantize, to_str
from kamra.tex.security import scope

DIMENSIONS = {
	"channel": "tex_sales_channel", "market": "tex_market", "room_type": "room_type", "board": "tex_board",
	"contract": "tex_contract", "rate_plan": "rate_plan", "agency": "travel_agent", "status": "status",
	"month": None, "day": None, "country": None,
}
MAX_DAYS = 800
LIVE = ("Confirmed", "Checked In", "Checked Out", "Pending Payment", "Held")


def _window(date_from, date_to) -> tuple[date, date]:
	a, b = getdate(date_from), getdate(date_to)
	if b < a:
		frappe.throw(_("The end date is before the start date."))
	if (b - a).days > MAX_DAYS:
		frappe.throw(_("Please choose a range of at most {0} days.").format(MAX_DAYS))
	return a, b


def _rows(property: str, a: date, b: date, basis: str, statuses=None) -> list[dict]:
	fields = ["name", "status", "check_in_date", "check_out_date", "creation", "tex_sale_at", "room_type",
	          "rate_plan", "tex_board", "tex_market", "tex_sales_channel", "tex_contract", "travel_agent", "guest",
	          "adults", "children", "tex_total_amount", "amount_after_tax", "tax_amount", "tex_currency",
	          "tex_cost_amount", "tex_margin_amount", "tex_extras_amount", "cancellation_fee", "tex_booking"]
	filters: dict = {"property": property}
	if statuses:
		filters["status"] = ("in", list(statuses))
	if basis == "stay":
		filters["check_in_date"] = ("<=", b)
		filters["check_out_date"] = (">", a)
	else:
		filters["creation"] = ("between", [str(a), f"{b} 23:59:59"])
	return frappe.get_all("Reservation", filters=filters, fields=fields, limit_page_length=0)


def _nights_in(r, a: date, b: date) -> tuple[int, int]:
	ci, co = getdate(r.check_in_date), getdate(r.check_out_date)
	total = max(1, (co - ci).days)
	lo, hi = max(ci, a), min(co, b + timedelta(days=1))
	return max(0, (hi - lo).days), total


def _ccy(r, default: str) -> str:
	return r.tex_currency or default


def _value(r, ccy: str):
	return from_db(r.tex_total_amount or r.amount_after_tax or 0, ccy)


def _dim_value(r, dim: str, basis: str) -> str:
	if dim == "month":
		d = getdate(r.check_in_date) if basis == "stay" else getdate(r.tex_sale_at or r.creation)
		return d.strftime("%Y-%m")
	if dim == "day":
		return str(getdate(r.check_in_date) if basis == "stay" else getdate(r.tex_sale_at or r.creation))
	if dim == "country":
		return (frappe.db.get_value("Guest", r.guest, "tex_country") or "—") if r.guest else "—"
	return r.get(DIMENSIONS[dim]) or "—"


def production(property: str, date_from, date_to, *, group_by: str = "channel", basis: str = "stay",
               include_cancelled: bool = False) -> dict:
	scope.require("report.view", property)
	if group_by not in DIMENSIONS:
		frappe.throw(_("Unknown grouping."))
	if basis not in ("stay", "booking"):
		frappe.throw(_("Unknown date basis."))
	a, b = _window(date_from, date_to)
	cost_ok = scope.has_capability("price.view_cost", property)
	default_ccy = frappe.db.get_value("Property", property, "currency") or "EUR"
	statuses = None if include_cancelled else LIVE
	agg: dict = defaultdict(lambda: {"bookings": 0, "room_nights": 0, "revenue": ZERO, "cost": ZERO,
	                                 "margin": ZERO, "guests": 0, "los_sum": 0, "lead_sum": 0})
	for r in _rows(property, a, b, basis, statuses):
		ccy = _ccy(r, default_ccy)
		key = (_dim_value(r, group_by, basis), ccy)
		inside, total = _nights_in(r, a, b)
		share = D(inside) / D(total) if basis == "stay" else D(1)
		nights = inside if basis == "stay" else total
		if nights == 0 and basis == "stay":
			continue
		row = agg[key]
		row["bookings"] += 1
		row["room_nights"] += nights
		row["revenue"] += _value(r, ccy) * share
		row["cost"] += from_db(r.tex_cost_amount or 0, ccy) * share
		row["margin"] += from_db(r.tex_margin_amount or 0, ccy) * share
		row["guests"] += int(r.adults or 0) + int(r.children or 0)
		row["los_sum"] += total
		sold = getdate(r.tex_sale_at or r.creation)
		row["lead_sum"] += max(0, (getdate(r.check_in_date) - sold).days)
	out = []
	for (label, ccy), v in sorted(agg.items(), key=lambda kv: (-kv[1]["revenue"], kv[0])):
		revenue = quantize(v["revenue"], ccy)
		item = {"key": label, "currency": ccy, "bookings": v["bookings"], "room_nights": v["room_nights"],
		        "revenue": to_str(revenue), "guests": v["guests"],
		        "adr": to_str(quantize(revenue / v["room_nights"], ccy)) if v["room_nights"] else None,
		        "avg_los": to_str(quantize(D(v["los_sum"]) / v["bookings"], "EUR")) if v["bookings"] else None,
		        "avg_lead_days": to_str(quantize(D(v["lead_sum"]) / v["bookings"], "EUR")) if v["bookings"] else None}
		if cost_ok:
			item["cost"] = to_str(quantize(v["cost"], ccy))
			item["margin"] = to_str(quantize(v["margin"], ccy))
			item["margin_pct"] = to_str(quantize(v["margin"] / v["revenue"] * 100, "EUR")) if v["revenue"] else None
		out.append(item)
	totals: dict = {}
	for item in out:
		t = totals.setdefault(item["currency"], {"bookings": 0, "room_nights": 0, "revenue": ZERO})
		t["bookings"] += item["bookings"]
		t["room_nights"] += item["room_nights"]
		t["revenue"] += D(item["revenue"])
	return {"property": property, "from": str(a), "to": str(b), "basis": basis, "group_by": group_by,
	        "cost_visible": cost_ok, "rows": out,
	        "totals": {c: {**t, "revenue": to_str(t["revenue"]),
	                       "adr": to_str(quantize(t["revenue"] / t["room_nights"], c)) if t["room_nights"] else None}
	                   for c, t in totals.items()}}


def dashboard(property: str, date_from=None, date_to=None) -> dict:
	scope.require("report.view", property)
	today = getdate(nowdate())
	a, b = _window(date_from or today.replace(day=1), date_to or add_days(today.replace(day=1), 40).replace(day=1)
	               - timedelta(days=1))
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
	abandoned = frappe.db.count("TEX Abandoned Booking", {"property": property, "status": "Open",
	                                                      "last_event_at": (">=", str(a))})
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


def pace(property: str, stay_from, stay_to, *, as_of_days: tuple[int, ...] = (0, 7, 14, 30, 60, 90)) -> dict:
	"""On-the-books room nights for a stay window as they stood N days ago (pick-up)."""
	scope.require("report.view", property)
	a, b = _window(stay_from, stay_to)
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
