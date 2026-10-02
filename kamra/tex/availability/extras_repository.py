"""Capacity of limited extras (G-19, ADR-033).

An extra with *Limited daily inventory* (on the revision live now) and a daily capacity
sells at most that many units per service day. The counter is a `TEX Extra Inventory Day`
row per (hotel, extra code, day); the `TEX Extra Allocation` ledger says who holds the
units. Keyed by code, so a capacity spans the extra's revisions (G-20).

Concurrency (ADR-032): the booking service creates-and-locks each day row by primary key
(`lock_days`, sorted), re-reads it under the lock (`check`), then writes. Global lock
order: quotes → room inventory days → extra days → promotions → booking.
"""

from __future__ import annotations

import json
from collections import defaultdict
from datetime import date, timedelta

import frappe
from frappe import _
from frappe.utils import getdate, now_datetime

from kamra.tex.money import whole_number
from kamra.tex.pricing.enums import ExtraPricingMode as M
from kamra.tex.pricing.model import ExtraDayAvailability
from kamra.tex.security.changes import SEP
from kamra.tex.services.refusals import with_code

Key = tuple[str, date]            # (extra code, service day)
# a stay that happened keeps its units (the service was delivered); cancelled or no-show frees them
HOLDING = ("Confirmed", "Checked In", "Held", "Pending Payment", "Checked Out")


class ExtraSoldOut(frappe.ValidationError):
	"""A limited extra has no units left on a day the booking needs."""
	code = "EXTRA_SOLD_OUT"                      # the guest's refusal code (G-70a)


def _day_name(property: str, code: str, day) -> str:
	from kamra.tex_commercial.doctype.tex_extra_inventory_day.tex_extra_inventory_day import extra_day_name

	return extra_day_name(property, code, getdate(day))


def tracked(property: str) -> dict[str, dict]:
	"""The hotel's extras limited now: code → {capacity, name, mode}. Capacity comes from the
	revision on sale now (an operational setting), never from an older revision."""
	from kamra.tex.commercial.context import listed_extras

	rows = listed_extras(property, fields=("extra_name", "pricing_mode", "inventory_tracked", "daily_capacity"))
	return {r.extra_code: {"capacity": int(r.daily_capacity or 0), "name": r.extra_name, "mode": r.pricing_mode}
	        for r in rows if r.inventory_tracked and int(r.daily_capacity or 0) > 0}


def _days(start: date, end: date) -> list[date]:
	return [start + timedelta(days=i) for i in range((end - start).days + 1)]


def _own_units(reservation: str | None) -> dict[Key, int]:
	if not reservation:
		return {}
	out: dict[Key, int] = defaultdict(int)
	for a in frappe.get_all("TEX Extra Allocation", filters={"reservation": reservation, "status": ("!=", "Released")},
	                        fields=["extra_code", "service_date", "units"]):
		out[(a.extra_code, getdate(a.service_date))] += int(a.units)
	return out


def availability(property: str, codes, start: date, end: date, *,
                 exclude_reservation: str | None = None) -> dict[str, dict[date, ExtraDayAvailability]]:
	"""What can still be sold of the tracked ``codes`` per day from ``start`` to ``end``
	(inclusive). Advisory (no lock): the booking re-checks under lock. Units the reservation
	being modified already holds are counted as available to it."""
	trk = tracked(property)
	codes = sorted({c for c in codes if c in trk})
	if not codes:
		return {}
	rows = {(r.extra_code, getdate(r.service_date)): r for r in frappe.get_all(
		"TEX Extra Inventory Day", filters={"property": property, "extra_code": ("in", codes),
		                                    "service_date": ("between", [start, end])},
		fields=["extra_code", "service_date", "capacity", "closed", "sold"])}
	own = _own_units(exclude_reservation)
	out: dict[str, dict[date, ExtraDayAvailability]] = {}
	for code in codes:
		out[code] = {}
		for d in _days(start, end):
			r = rows.get((code, d))
			cap = int(r.capacity or 0) if r and r.capacity else trk[code]["capacity"]
			sold = int(r.sold or 0) if r else 0
			out[code][d] = ExtraDayAvailability(max(cap - sold + own.get((code, d), 0), 0),
			                                     bool(r.closed) if r else False)
	return out


def _usage_of(e: dict, request: dict) -> list[tuple[date, int]]:
	"""The (day, units) an ok extra line takes. Quotes since G-19 carry ``usage``; older
	snapshots are read from the priced units the same way ``pricing.extras.usage`` counts."""
	if "usage" in e:
		return [(getdate(u["date"]), int(u["units"])) for u in e["usage"]]
	units = whole_number(e.get("quantity"))
	if units is None:
		# a count of units is never part of one: refused by name, never cut to a whole number (LO-48)
		raise ValueError(f"extra {e.get('code')}: quantity {e.get('quantity')!r} of a price snapshot is not a whole "
		                 "number of units")
	ci, co = getdate(request["check_in"]), getdate(request["check_out"])
	nights = [ci + timedelta(days=i) for i in range(max((co - ci).days, 1))]
	dates = [getdate(d) for d in e.get("service_dates") or []]
	one_day = dates[0] if dates else ci
	heads = int(request.get("adults") or 0) + len(request.get("children") or [])
	mode = e.get("pricing_mode")
	if mode == M.SERVICE_DATE.value:
		return [(d, units // max(len(dates), 1)) for d in dates]
	if mode == M.NIGHT.value:
		return [(n, units // len(nights)) for n in nights]
	if mode == M.PERSON_NIGHT.value:
		return [(n, units // len(nights) * heads) for n in nights]
	if mode == M.PERSON.value:
		return [(one_day, units * heads)]
	return [(one_day, units)]


def demand(results: list[dict], codes=None) -> dict[Key, int]:
	"""Units per (code, day) the priced rooms need, over all rooms of a booking (a family
	booking two rooms with the spa needs both rooms' units on the same day)."""
	need: dict[Key, int] = defaultdict(int)
	for result in results:
		for e in result.get("extras") or []:
			if e.get("ok") and (codes is None or e["code"] in codes):
				for d, u in _usage_of(e, result.get("request") or {}):
					if u > 0:
						need[(e["code"], d)] += u
	return dict(need)


def lock_days(property: str, keys) -> None:
	"""Create-and-lock the day rows, in (code, day) order (primary key: no gap locks)."""
	for code, d in sorted(set(keys)):
		frappe.db.sql(
			"""INSERT INTO `tabTEX Extra Inventory Day`
			   (name, creation, modified, owner, modified_by, docstatus, property, extra_code, service_date,
			    capacity, closed, sold)
			   VALUES (%(n)s, NOW(), NOW(), 'Administrator', 'Administrator', 0, %(p)s, %(c)s, %(d)s, 0, 0, 0)
			   ON DUPLICATE KEY UPDATE `modified` = `modified`""",
			{"n": _day_name(property, code, d), "p": property, "c": code, "d": d})


def check(property: str, need: dict[Key, int], *, credit: dict[Key, int] | None = None,
          trk: dict | None = None) -> None:
	"""Under the day locks: refuse when a tracked extra is closed or has fewer units left than
	needed on a day (``credit``: units the same reservation gives back)."""
	trk = tracked(property) if trk is None else trk
	credit = credit or {}
	for (code, d), units in sorted(need.items()):
		if code not in trk:
			continue
		row = frappe.db.sql("""SELECT capacity, closed, sold FROM `tabTEX Extra Inventory Day` WHERE name=%s
		                       FOR UPDATE""", _day_name(property, code, d), as_dict=True)
		cap = (int(row[0].capacity or 0) if row else 0) or trk[code]["capacity"]
		left = cap - (int(row[0].sold or 0) if row else 0) + credit.get((code, d), 0)
		name = trk[code]["name"] or code
		# the extra's name and the day (ISO: the booking app writes it in the guest's language, G-70b)
		if row and row[0].closed:
			raise with_code(ExtraSoldOut(_("{0} is not available on {1}.").format(name, frappe.format(d, "Date"))),
			                extra=name, date=d.isoformat(), closed=True)
		if units > left:
			# never how many are left: this can reach a guest (ADR-033); staff see counts in the grid
			raise with_code(ExtraSoldOut(_("Sorry — {0} has just sold out for {1}.").format(name, frappe.format(d, "Date"))
			                             if left <= 0 else _("Sorry — there is not enough {0} left for {1}.").format(
				                             name, frappe.format(d, "Date"))), extra=name, date=d.isoformat())


def _add_sold(property: str, code: str, d: date, units: int) -> None:
	frappe.db.sql("""UPDATE `tabTEX Extra Inventory Day` SET sold = GREATEST(sold + %s, 0), modified = modified
	                 WHERE name=%s""", (units, _day_name(property, code, d)))


def allocate(property: str, booking: str | None, reservation: str, result: dict, status: str,
             trk: dict | None = None) -> None:
	"""Record the units a priced room takes (the days must be locked and checked)."""
	trk = tracked(property) if trk is None else trk
	revisions = {e["code"]: e.get("revision") for e in result.get("extras") or []}
	for (code, d), units in sorted(demand([result], codes=set(trk)).items()):
		frappe.get_doc({"doctype": "TEX Extra Allocation", "property": property, "extra_code": code,
		                "extra": revisions.get(code), "service_date": d, "units": units, "status": status,
		                "booking": booking, "reservation": reservation}).insert(ignore_permissions=True)
		_add_sold(property, code, d, units)


def _live(reservation: str) -> list[dict]:
	return frappe.get_all("TEX Extra Allocation", filters={"reservation": reservation, "status": ("!=", "Released")},
	                      fields=["name", "property", "extra_code", "service_date", "units"])


def _release_rows(rows: list[dict], reason: str) -> None:
	now = now_datetime()
	for a in rows:
		frappe.db.set_value("TEX Extra Allocation", a.name, {"status": "Released", "released_at": now,
		                                                     "release_reason": (reason or "")[:140]},
		                    update_modified=False)
		_add_sold(a.property, a.extra_code, getdate(a.service_date), -int(a.units))


def release_reservation(reservation: str, reason: str) -> None:
	"""A cancelled or no-show stay gives its units back."""
	rows = _live(reservation)
	if rows:
		lock_days(rows[0].property, [(a.extra_code, getdate(a.service_date)) for a in rows])
		_release_rows(rows, reason)


def confirm(booking: str) -> None:
	"""Held units become confirmed with the booking (the counter already counts both)."""
	frappe.db.sql("""UPDATE `tabTEX Extra Allocation` SET status='Confirmed'
	                 WHERE booking=%s AND status='Held'""", booking)


def replace_for_reservation(property: str, booking: str | None, reservation: str, new_result: dict,
                            status: str) -> None:
	"""A modification: the reservation gives back its units and takes the new ones, all under
	the day locks; what it already held counts as available to it."""
	trk = tracked(property)
	old = _live(reservation)
	held: dict[Key, int] = defaultdict(int)
	for a in old:
		held[(a.extra_code, getdate(a.service_date))] += int(a.units)
	need = demand([new_result], codes=set(trk))
	lock_days(property, [*held, *need])
	check(property, need, credit=held, trk=trk)
	_release_rows(old, "modified")
	allocate(property, booking, reservation, new_result, status, trk=trk)


def reconcile(property: str, extra_code: str | None = None) -> list[dict]:
	"""Rebuild the counters from the ledger: units of stays that are no longer live are given
	back, and each day's sold becomes the sum of the units still held. Returns the drift."""
	filters = {"property": property, **({"extra_code": extra_code} if extra_code else {})}
	days = {(r.extra_code, getdate(r.service_date)) for r in frappe.get_all(
		"TEX Extra Inventory Day", filters=filters, fields=["extra_code", "service_date"])}
	allocs = frappe.get_all("TEX Extra Allocation", filters={**filters, "status": ("!=", "Released")},
	                        fields=["name", "property", "extra_code", "service_date", "units", "reservation"])
	days |= {(a.extra_code, getdate(a.service_date)) for a in allocs}
	lock_days(property, days)
	statuses = {r.name: r.status for r in frappe.get_all(
		"Reservation", filters={"name": ("in", list({a.reservation for a in allocs}) or ["-"])},
		fields=["name", "status"])}
	dead = [a for a in allocs if statuses.get(a.reservation) not in HOLDING]
	dead_names = {a.name for a in dead}
	now = now_datetime()
	for a in dead:
		frappe.db.set_value("TEX Extra Allocation", a.name, {"status": "Released", "released_at": now,
		                                                     "release_reason": "reconciled"}, update_modified=False)
	held: dict[Key, int] = defaultdict(int)
	for a in allocs:
		if a.name not in dead_names:
			held[(a.extra_code, getdate(a.service_date))] += int(a.units)
	drift = []
	for code, d in sorted(days):
		name = _day_name(property, code, d)
		sold = int(frappe.db.get_value("TEX Extra Inventory Day", name, "sold") or 0)
		if sold != held.get((code, d), 0):
			drift.append({"extra_code": code, "date": str(d), "was": sold, "now": held.get((code, d), 0)})
			frappe.db.sql("UPDATE `tabTEX Extra Inventory Day` SET sold=%s WHERE name=%s",
			              (held.get((code, d), 0), name))
	return drift


def backfill(property: str, codes=None) -> int:
	"""Stays already sold hold their units once an extra is limited (at migration, when a
	limited revision goes live, and daily for scheduled ones). Idempotent: a reservation that
	already holds units of a code is left alone. Returns how many reservations were filled."""
	trk = tracked(property)
	codes = (set(codes) if codes else set(trk)) & set(trk)
	if not codes:
		return 0
	today = getdate(now_datetime())
	filled = 0
	for r in frappe.get_all("Reservation", filters={"property": property, "tex_booking": ("is", "set"),
	                                                "status": ("in", ["Confirmed", "Checked In", "Held",
	                                                                  "Pending Payment"]),
	                                                "check_out_date": (">=", today)},
	                        fields=["name", "status", "tex_booking", "tex_pricing_snapshot"]):
		have = set(frappe.get_all("TEX Extra Allocation", filters={"reservation": r.name}, pluck="extra_code"))
		todo = codes - have
		snap = json.loads(r.tex_pricing_snapshot or "{}")
		try:
			need = {k: u for k, u in demand([snap], codes=todo).items() if k[1] >= today} if todo else {}
		except ValueError:
			# a quantity that is not a whole number of units (LO-48): this stay is left to staff, never cut to a
			# whole number; the others still hold their units (the limit is saved, the daily job goes on)
			from kamra.tex.security.audit import log_exception

			log_exception(f"TEX job extras backfill {r.name}")
			continue
		if not need:
			continue
		lock_days(property, need)
		revisions = {e["code"]: e.get("revision") for e in snap.get("extras") or []}
		for (code, d), units in sorted(need.items()):
			frappe.get_doc({"doctype": "TEX Extra Allocation", "property": property, "extra_code": code,
			                "extra": revisions.get(code), "service_date": d, "units": units,
			                "status": "Held" if r.status in ("Held", "Pending Payment") else "Confirmed",
			                "booking": r.tex_booking, "reservation": r.name}).insert(ignore_permissions=True)
			_add_sold(property, code, d, units)
		filled += 1
	return filled


def reconcile_all() -> None:
	"""Daily safety net: stays sold before an extra became limited hold their units, and
	every hotel's counters are rebuilt from its ledger (a status changed outside the booking
	service, a row deleted by hand), auditing any drift."""
	from kamra.tex.security.audit import audit

	props = set(frappe.get_all("TEX Extra Inventory Day", distinct=True, pluck="property"))
	props |= {r.property for r in frappe.get_all("TEX Extra", filters={"inventory_tracked": 1,
	                                                                   "tex_status": "Active"}, fields=["property"])}
	for prop in sorted(props):
		backfill(prop)
		drift = reconcile(prop)
		if drift:
			audit("extra_inventory.reconcile", property=prop, new={"drift": drift}, source="Scheduler")


# ── administration ──────────────────────────────────────────────────────────


MAX_GRID_DAYS = 62
MAX_UPDATE_DAYS = 400


def grid(property: str, start, days: int = 14) -> dict:
	"""Limited extras × days: capacity (and override), closed, sold (held/confirmed), left."""
	start = getdate(start)
	days = max(1, min(int(days or 14), MAX_GRID_DAYS))
	dates = [start + timedelta(days=i) for i in range(days)]
	trk = tracked(property)
	rows = {(r.extra_code, getdate(r.service_date)): r for r in frappe.get_all(
		"TEX Extra Inventory Day", filters={"property": property, "extra_code": ("in", list(trk) or ["-"]),
		                                    "service_date": ("between", [dates[0], dates[-1]])},
		fields=["extra_code", "service_date", "capacity", "closed", "sold", "note"])}
	by_status: dict[tuple, int] = defaultdict(int)
	for a in frappe.get_all("TEX Extra Allocation",
	                        filters={"property": property, "extra_code": ("in", list(trk) or ["-"]),
	                                 "service_date": ("between", [dates[0], dates[-1]]),
	                                 "status": ("in", ["Held", "Confirmed"])},
	                        fields=["extra_code", "service_date", "status", "units"]):
		by_status[(a.extra_code, getdate(a.service_date), a.status)] += int(a.units)
	extras = []
	for code, info in sorted(trk.items(), key=lambda kv: (kv[1]["name"] or kv[0])):
		cells = []
		for d in dates:
			r = rows.get((code, d))
			override = int(r.capacity or 0) if r else 0
			cap = override or info["capacity"]
			sold = int(r.sold or 0) if r else 0
			cells.append({"date": str(d), "capacity": cap, "override": override or None,
			              "closed": bool(r.closed) if r else False, "sold": sold,
			              "held": by_status[(code, d, "Held")], "confirmed": by_status[(code, d, "Confirmed")],
			              "remaining": max(cap - sold, 0), "over": sold > cap, "note": (r.note if r else None)})
		extras.append({"code": code, "name": info["name"], "pricing_mode": info["mode"],
		               "daily_capacity": info["capacity"], "cells": cells})
	return {"property": property, "start": str(start), "days": days, "dates": [str(d) for d in dates],
	        "extras": extras}


def bulk_update(property: str, codes, start, end, *, weekdays=None, capacity=None, closed=None,
                note=None) -> dict:
	"""Set a capacity override (0 = the extra's default) and/or open/close days. The sold
	counter is never written here."""
	trk = tracked(property)
	codes = sorted({str(c).strip().upper() for c in codes or []})
	unknown = [c for c in codes if c not in trk]
	if not codes or unknown:
		frappe.throw(_("Only this hotel's extras with a limited daily capacity can be edited here ({0}).")
		             .format(", ".join(unknown) or "—"))
	start, end = getdate(start), getdate(end)
	if end < start or (end - start).days >= MAX_UPDATE_DAYS:
		frappe.throw(_("Choose a period of at most {0} days.").format(MAX_UPDATE_DAYS))
	if capacity not in (None, "") and int(capacity) < 0:
		frappe.throw(_("Capacity cannot be negative."))
	wd = {int(w) for w in weekdays} if weekdays else None
	dates = [d for d in _days(start, end) if wd is None or d.weekday() in wd]
	keys = [(c, d) for c in codes for d in dates]
	lock_days(property, keys)
	sets, params = [], {}
	if capacity not in (None, ""):
		sets.append("capacity=%(cap)s")
		params["cap"] = int(capacity)
	if closed not in (None, ""):
		sets.append("closed=%(closed)s")
		params["closed"] = 1 if int(closed) else 0
	if note is not None:
		sets.append("note=%(note)s")
		params["note"] = (note or "")[:140]
	if not sets:
		frappe.throw(_("Nothing to change."))
	# what each day held before, for the audit (G-74): the edited fields only
	edited = {"cap": "capacity", "closed": "closed", "note": "note"}
	new = {edited[k]: v for k, v in params.items()}
	over, cells = [], []
	for code, d in sorted(keys):
		name = _day_name(property, code, d)
		before = frappe.db.get_value("TEX Extra Inventory Day", name, list(new), as_dict=True) or {}
		frappe.db.sql(f"UPDATE `tabTEX Extra Inventory Day` SET {', '.join(sets)}, modified=NOW() "
		              "WHERE name=%(name)s", {**params, "name": name})
		row = frappe.db.get_value("TEX Extra Inventory Day", name, ["capacity", "sold"], as_dict=True)
		cap = int(row.capacity or 0) or trk[code]["capacity"]
		if int(row.sold or 0) > cap:
			over.append({"extra_code": code, "date": str(d), "sold": int(row.sold), "capacity": cap})
		cells.append((f"{code}{SEP}{d}", {f: before.get(f) if f == "note" else int(before.get(f) or 0) for f in new},
		              new))
	# ``_cells`` is for the caller's audit only, never part of the response
	return {"updated": len(keys), "over_capacity": over, "_cells": cells}


def allocations(property: str, extra_code: str, day) -> list[dict]:
	"""Who holds a limited extra on one day."""
	rows = frappe.get_all("TEX Extra Allocation",
	                      filters={"property": property, "extra_code": extra_code, "service_date": getdate(day),
	                               "status": ("!=", "Released")},
	                      fields=["booking", "reservation", "units", "status"], order_by="creation asc")
	bookers = {b.name: b.booker_name for b in frappe.get_all(
		"TEX Booking", filters={"name": ("in", [r.booking for r in rows if r.booking] or ["-"])},
		fields=["name", "booker_name"])}
	return [{**r, "booker_name": bookers.get(r.booking)} for r in rows]
