"""Portfolio dashboard (R-47, G-25): the sales picture of every hotel a user may report
on, for an enterprise, a hotel group, one hotel or all of them.

Figures come from SQL aggregates read as text (``CAST … AS CHAR``) and summed with
Decimal; money is grouped per currency and never summed across currencies. Booking
figures count a reservation on its sale day (TEX sale time, else creation); cancellations
count on the day they were cancelled. Only hotels where the user holds ``report.view``
are included, whatever scope is asked for.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date, timedelta

import frappe
from frappe import _
from frappe.utils import add_days, getdate, nowdate

from kamra.tex.money import ZERO, D, quantize, to_str
from kamra.tex.security import scope

LIVE = ("Confirmed", "Checked In", "Checked Out", "Pending Payment", "Held")
LEVELS = ("All", "Enterprise", "Group", "Hotel")
ALERT_DAYS = 14
ABANDONED_DAYS = 30
MAX_HOTELS = 300
MAX_ALERTS = 60
LOW_SHARE = D("0.1")        # a day with 10 % or less left is "few left"


def _reporting_hotels() -> set[str]:
	return {p for p in scope.permitted_properties() if scope.has_capability("report.view", p)}


def scopes() -> dict:
	"""The enterprises, groups and hotels the user can look at (report.view)."""
	hotels = _reporting_hotels()
	if not hotels:
		frappe.throw(_("Not permitted: {0}.").format("report.view"), frappe.PermissionError)
	rows = frappe.get_all("Property", filters={"name": ("in", list(hotels))},
	                      fields=["name", "property_name", "tex_hotel_group", "tex_enterprise", "currency"],
	                      order_by="property_name asc")
	groups = sorted({r.tex_hotel_group for r in rows if r.tex_hotel_group})
	ents = sorted({r.tex_enterprise for r in rows if r.tex_enterprise})
	# one query per kind, never one per group or enterprise
	group_names = dict(frappe.get_all("TEX Hotel Group", filters={"name": ("in", groups or [""])},
	                                  fields=["name", "group_name"], as_list=True))
	ent_names = dict(frappe.get_all("TEX Enterprise", filters={"name": ("in", ents or [""])},
	                                fields=["name", "enterprise_name"], as_list=True))
	return {
		"hotels": [{"name": r.name, "label": r.property_name or r.name, "group": r.tex_hotel_group,
		            "enterprise": r.tex_enterprise} for r in rows],
		"groups": [{"name": g, "label": group_names.get(g) or g} for g in groups],
		"enterprises": [{"name": e, "label": ent_names.get(e) or e} for e in ents],
	}


def hotels_in(level: str, name: str | None) -> list[str]:
	"""The hotels of a scope that the user may report on; refuses a scope they cannot see."""
	if level not in LEVELS:
		frappe.throw(_("Unknown scope {0}.").format(level))
	mine = _reporting_hotels()
	if level == "All":
		chosen = mine
	elif not name:
		frappe.throw(_("Choose the {0}.").format(_(level).lower()))
	elif level == "Hotel":
		chosen = {name} & mine
	else:
		field = "tex_enterprise" if level == "Enterprise" else "tex_hotel_group"
		chosen = set(frappe.get_all("Property", filters={field: name, "disabled": 0}, pluck="name")) & mine
	if not chosen:
		# a scope with none of the user's hotels: not even its existence is confirmed
		frappe.throw(_("Not permitted: {0}.").format("report.view"), frappe.PermissionError)
	if len(chosen) > MAX_HOTELS:
		frappe.throw(_("Choose a smaller scope (at most {0} hotels).").format(MAX_HOTELS))
	return sorted(chosen)


def _money(bucket: dict) -> dict[str, str]:
	return {c: to_str(quantize(v, c)) for c, v in sorted(bucket.items()) if c}


def _add(bucket: dict, ccy, value) -> None:
	ccy = ccy or ""
	bucket[ccy] = bucket.get(ccy, ZERO) + D(value or 0)


def portfolio(level: str = "All", name: str | None = None, date_from=None, date_to=None, today=None) -> dict:
	hotels = hotels_in(level, name)
	today = getdate(today or nowdate())
	a = getdate(date_from) if date_from else today.replace(day=1)
	b = getdate(date_to) if date_to else add_days((a.replace(day=28) + timedelta(days=4)).replace(day=1), -1)
	if b < a or (b - a).days > 400:
		frappe.throw(_("Choose a range of at most 400 days, ending after it starts."))
	names = {r.name: r.property_name or r.name
	         for r in frappe.get_all("Property", filters={"name": ("in", hotels)}, fields=["name", "property_name"])}
	groups = {r.channel_code: r.channel_group for r in frappe.get_all(
		"TEX Sales Channel", fields=["channel_code", "channel_group"])}
	per = {h: {"hotel": h, "hotel_name": names.get(h, h), "sold": 0, "sold_today": 0, "booking_value": {},
	           "direct_value": {}, "call_centre_value": {}, "cancellations": 0, "cancelled_value": {},
	           "pending_payment": 0, "pending_payment_value": {}, "open_balances": 0, "open_balance_value": {},
	           "abandoned": 0, "abandoned_value": {}, "inventory_alerts": 0, "restriction_alerts": 0}
	       for h in hotels}
	total = {"booking_value": {}, "direct_value": {}, "call_centre_value": {}, "cancelled_value": {},
	         "pending_payment_value": {}, "open_balance_value": {}, "abandoned_value": {}, "today_value": {}}
	markets: dict = defaultdict(lambda: {"count": 0, "value": {}})
	rooms: dict = defaultdict(lambda: {"count": 0, "nights": 0, "value": {}})

	# sales in the window, on their sale day
	for r in frappe.db.sql(
		# aliases never shadow a column: GROUP BY resolves a name to a column first (Reservation
		# has a legacy ``channel``), which would merge channels
		"""SELECT property, tex_currency ccy, IFNULL(tex_sales_channel, '') x_channel, IFNULL(tex_market, '') x_market,
		          room_type, DATE(IFNULL(tex_sale_at, creation)) = %(today)s x_today, COUNT(*) n,
		          SUM(GREATEST(DATEDIFF(check_out_date, check_in_date), 1)) nights,
		          CAST(SUM(IFNULL(tex_total_amount, amount_after_tax)) AS CHAR) v
		   FROM `tabReservation`
		   WHERE property IN %(h)s AND status IN %(live)s AND DATE(IFNULL(tex_sale_at, creation)) BETWEEN %(a)s AND %(b)s
		   GROUP BY property, tex_currency, x_channel, x_market, room_type, x_today""",
			{"h": tuple(hotels), "live": LIVE, "a": a, "b": b, "today": today}, as_dict=True):
		h, v, n = per[r.property], D(r.v or 0), int(r.n)
		h["sold"] += n
		_add(h["booking_value"], r.ccy, v)
		_add(total["booking_value"], r.ccy, v)
		if r.x_today:
			h["sold_today"] += n
			_add(total["today_value"], r.ccy, v)
		kind = {"Booking Engine": "direct_value", "Call Center": "call_centre_value"}.get(groups.get(r.x_channel))
		if kind:
			_add(h[kind], r.ccy, v)
			_add(total[kind], r.ccy, v)
		m = markets[r.x_market or "—"]
		m["count"] += n
		_add(m["value"], r.ccy, v)
		rt = rooms[r.room_type]
		rt["count"] += n
		rt["nights"] += int(r.nights or 0)
		_add(rt["value"], r.ccy, v)

	for r in frappe.db.sql(
		"""SELECT property, tex_currency ccy, COUNT(*) n, CAST(SUM(IFNULL(tex_total_amount, amount_after_tax)) AS CHAR) v
		   FROM `tabReservation` WHERE property IN %(h)s AND status = 'Cancelled'
		     AND DATE(cancelled_on) BETWEEN %(a)s AND %(b)s GROUP BY property, tex_currency""",
			{"h": tuple(hotels), "a": a, "b": b}, as_dict=True):
		per[r.property]["cancellations"] += int(r.n)
		_add(per[r.property]["cancelled_value"], r.ccy, r.v)
		_add(total["cancelled_value"], r.ccy, r.v)

	# money still to come in: bookings waiting for payment, and open balances
	for r in frappe.db.sql(
		"""SELECT property, currency ccy, status = 'Pending Payment' x_waiting, COUNT(*) n,
		          CAST(SUM(balance_amount) AS CHAR) v
		   FROM `tabTEX Booking` WHERE property IN %(h)s AND status NOT IN ('Cancelled', 'Draft')
		     AND (status = 'Pending Payment' OR payment_status IN ('Unpaid', 'Partially Paid'))
		     AND balance_amount > 0
		   GROUP BY property, currency, x_waiting""", {"h": tuple(hotels)}, as_dict=True):
		key = "pending_payment" if r.x_waiting else "open_balance"
		per[r.property]["pending_payment" if r.x_waiting else "open_balances"] += int(r.n)
		_add(per[r.property][f"{key}_value"], r.ccy, r.v)
		_add(total[f"{key}_value"], r.ccy, r.v)

	for r in frappe.db.sql(
		"""SELECT property, currency ccy, COUNT(*) n, CAST(SUM(IFNULL(value, 0)) AS CHAR) v
		   FROM `tabTEX Abandoned Booking` WHERE property IN %(h)s AND status = 'Open'
		     AND last_event_at >= %(since)s GROUP BY property, currency""",
			{"h": tuple(hotels), "since": add_days(today, -ABANDONED_DAYS)}, as_dict=True):
		per[r.property]["abandoned"] += int(r.n)
		_add(per[r.property]["abandoned_value"], r.ccy, r.v)
		_add(total["abandoned_value"], r.ccy, r.v)

	alerts = _inventory_alerts(hotels, today) + _restriction_alerts(hotels, today)
	for x in alerts:
		per[x["hotel"]]["inventory_alerts" if x["kind"] in INVENTORY_KINDS else "restriction_alerts"] += 1
	rt_names = {r.name: r.room_type_name for r in frappe.get_all(
		"Room Type", filters={"name": ("in", list(rooms) or [""])}, fields=["name", "room_type_name", "property"])}
	rt_hotel = dict(frappe.get_all("Room Type", filters={"name": ("in", list(rooms) or [""])},
	                               fields=["name", "property"], as_list=True))
	out_hotels = []
	for h in hotels:
		row = per[h]
		for k in [k for k in row if k.endswith("_value")]:
			row[k] = _money(row[k])
		out_hotels.append(row)
	alerts.sort(key=lambda x: (x["date"], x["hotel_name"], x["kind"]))
	return {
		"scope": {"level": level, "name": name, "hotels": len(hotels)}, "from": str(a), "to": str(b),
		"today": str(today),
		"totals": {"sold": sum(r["sold"] for r in out_hotels), "sold_today": sum(r["sold_today"] for r in out_hotels),
		           "cancellations": sum(r["cancellations"] for r in out_hotels),
		           "pending_payment": sum(r["pending_payment"] for r in out_hotels),
		           "open_balances": sum(r["open_balances"] for r in out_hotels),
		           "abandoned": sum(r["abandoned"] for r in out_hotels),
		           **{k: _money(v) for k, v in total.items()}},
		"hotels": out_hotels,
		"markets": sorted(({"market": k, "count": v["count"], "value": _money(v["value"])} for k, v in markets.items()),
		                  key=lambda x: -x["count"])[:20],
		"rooms": sorted(({"room_type": k, "room_type_name": rt_names.get(k) or k, "hotel": rt_hotel.get(k),
		                  "hotel_name": names.get(rt_hotel.get(k), rt_hotel.get(k)), "count": v["count"],
		                  "nights": v["nights"], "value": _money(v["value"])} for k, v in rooms.items()),
		                 key=lambda x: -x["nights"])[:20],
		"alerts": alerts[:MAX_ALERTS], "alerts_total": len(alerts),
	}


INVENTORY_KINDS = ("sold_out", "few_left", "closed", "oversold")


def _inventory_alerts(hotels: list[str], today: date) -> list[dict]:
	"""Room pools in the next two weeks that are sold out, nearly full, closed or oversold."""
	from kamra.tex.availability import inventory_math as inv
	from kamra.tex.availability import repository as avail

	days = [today + timedelta(days=i) for i in range(ALERT_DAYS)]
	names = dict(frappe.get_all("Property", filters={"name": ("in", hotels)}, fields=["name", "property_name"],
	                            as_list=True))
	out = []
	for h in hotels:
		seen = set()
		for rt in frappe.get_all("Room Type", filters={"property": h, "disabled": 0}, fields=["name", "room_type_name"],
		                         order_by="name asc"):
			key, _members = avail.pool_of(rt.name)
			if key in seen:
				continue
			seen.add(key)
			pdays, _allot = avail.pool_days(h, rt.name, days)
			for p in pdays:
				cap = inv.capacity(p)
				free = cap - p.sold
				kind = ("closed" if p.closed else "oversold" if free < 0 else "sold_out" if free == 0 and cap
				        else "few_left" if cap and D(free) <= max(D(1), D(cap) * LOW_SHARE) else None)
				if kind:
					out.append({"hotel": h, "hotel_name": names.get(h) or h, "date": str(p.day), "kind": kind,
					            "room_type": rt.name, "room_type_name": rt.room_type_name, "free": free,
					            "capacity": cap})
	return out


def _restriction_alerts(hotels: list[str], today: date) -> list[dict]:
	names = dict(frappe.get_all("Property", filters={"name": ("in", hotels)}, fields=["name", "property_name"],
	                            as_list=True))
	rows = frappe.get_all("TEX ARI Restriction", filters={
		"property": ("in", hotels), "restriction_date": ("between", [today, add_days(today, ALERT_DAYS - 1)])},
		or_filters={"stop_sell": "STOP", "cta": "Yes", "ctd": "Yes"},
		fields=["property", "restriction_date", "room_type", "stop_sell", "cta", "ctd", "market", "sales_channel",
		        "channel_scope"],
		order_by="restriction_date asc", limit=500)
	room_names = dict(frappe.get_all("Room Type", filters={"name": ("in", list({r.room_type for r in rows
	                                                                             if r.room_type}) or [""])},
	                                 fields=["name", "room_type_name"], as_list=True))
	out = []
	for r in rows:
		kind = "stop_sell" if r.stop_sell == "STOP" else "closed_to_arrival" if r.cta == "Yes" else "closed_to_departure"
		out.append({"hotel": r.property, "hotel_name": names.get(r.property) or r.property,
		            "date": str(r.restriction_date), "kind": kind, "room_type": r.room_type,
		            "room_type_name": room_names.get(r.room_type) if r.room_type else None, "market": r.market,
		            "channel": r.sales_channel,
		            # the Booking Engine, the Call Center or both (G-48): not every channel
		            "channel_scope": r.channel_scope or None})
	return out
