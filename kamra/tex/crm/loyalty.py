"""TEX Loyalty (R-39): earn rules, pending → available maturation, tiers, blackout
dates, redemption as a payment against a booking, expiry and reversal on cancel.

Ledger entries carry signed points. The available balance counts entries whose
status is Available / Used / Expired (i.e. final); Pending earnings are shown
separately and Reversed ones are ignored. Everything is integer points; money
values use Decimal and the program currency.
"""

from __future__ import annotations

import hashlib
import json
from datetime import date, timedelta
from decimal import ROUND_FLOOR

import frappe
from frappe import _
from frappe.utils import add_days, add_months, getdate, now_datetime, nowdate

from kamra.tex.money import D, from_db, quantize, to_str
from kamra.tex.security import scope
from kamra.tex.security.audit import audit

FINAL = ("Available", "Used", "Expired")


def program_for(property: str) -> str | None:
	"""The hotel's enabled program, else its group's (at most one each: the controller)."""
	name = frappe.db.get_value("TEX Loyalty Program", {"property": property, "enabled": 1}, order_by="creation asc")
	if name:
		return name
	group = frappe.db.get_value("Property", property, "tex_hotel_group")
	if group:
		return frappe.db.get_value("TEX Loyalty Program", {"hotel_group": group, "enabled": 1,
		                                                   "property": ("is", "not set")}, order_by="creation asc")
	return None


def program_properties(prog) -> list[str]:
	"""The (enabled) hotels a program reaches."""
	if prog.get("property"):
		return [prog.property]
	if not prog.get("hotel_group"):
		return []
	return frappe.get_all("Property", filters={"tex_hotel_group": prog.hotel_group, "disabled": 0}, pluck="name",
	                      order_by="name asc")


def visible_programs(props: set[str]) -> set[str]:
	"""Programs the viewer's hotels belong to (their own, or their group's)."""
	if not props:
		return set()
	groups = {g for g in frappe.get_all("Property", filters={"name": ("in", list(props))}, pluck="tex_hotel_group")
	          if g}
	return set(frappe.get_all("TEX Loyalty Program", or_filters={"property": ("in", list(props)),
	                                                            "hotel_group": ("in", list(groups) or [""])},
	                          pluck="name"))


def balances(guest: str, program: str) -> dict:
	rows = frappe.db.sql("""SELECT status, SUM(points) pts FROM `tabTEX Loyalty Ledger`
		WHERE guest=%s AND program=%s GROUP BY status""", (guest, program), as_dict=True)
	by = {r.status: int(r.pts or 0) for r in rows}
	earned = frappe.db.sql("""SELECT COALESCE(SUM(points),0) FROM `tabTEX Loyalty Ledger`
		WHERE guest=%s AND program=%s AND entry_type='Earn' AND status IN ('Available','Used','Expired')""",
	                       (guest, program))[0][0]
	return {"available": sum(by.get(s, 0) for s in FINAL), "pending": by.get("Pending", 0),
	        "lifetime_earned": int(earned or 0)}


def tier_of(program_doc, lifetime_points: int):
	tiers = sorted(program_doc.tiers or [], key=lambda t: int(t.min_points or 0))
	current = None
	for t in tiers:
		if lifetime_points >= int(t.min_points or 0):
			current = t
	return current


def _in_blackout(program_doc, day: date, purpose: str) -> bool:
	"""``purpose``: "Earning" or "Redemption"; a row without a purpose (before G-24) is both."""
	return any(getdate(b.date_from) <= day <= getdate(b.date_to) for b in program_doc.blackouts or []
	           if b.date_from and b.date_to and (b.get("applies_to") or "Both") in (purpose, "Both"))


def stay_fingerprint(res) -> str:
	"""What an earning depends on in the stay itself: dates, room, value and extras. A
	change of the program's rules never changes it, so it never rewrites past earnings."""
	snap = json.loads(res.tex_pricing_snapshot or "{}")
	extras = sorted((e.get("code"), str(e.get("quantity"))) for e in snap.get("extras") or [] if e.get("ok"))
	basis = [str(res.check_in_date), str(res.check_out_date), res.room_type, res.tex_currency,
	         str(res.tex_total_amount or res.amount_after_tax or 0), extras]
	return hashlib.sha256(json.dumps(basis, default=str).encode()).hexdigest()[:32]


def points_for(program_doc, res, multiplier) -> tuple[int, list[dict]]:
	"""Deterministic earn calculation for one reservation → (points, explanation)."""
	ci, co = getdate(res.check_in_date), getdate(res.check_out_date)
	nights = max(0, (co - ci).days)
	ccy = res.tex_currency or program_doc.currency or "EUR"
	amount = from_db(res.tex_total_amount or res.amount_after_tax or 0, ccy)
	if _in_blackout(program_doc, ci, "Earning"):
		return 0, [{"rule": "BLACKOUT", "points": 0}]
	total = D(0)
	lines = []
	for r in program_doc.earn_rules or []:
		if r.date_from and ci < getdate(r.date_from):
			continue
		if r.date_to and ci > getdate(r.date_to):
			continue
		rate = D(str(r.rate or 0))
		if r.basis == "MONEY":
			if program_doc.currency and ccy != program_doc.currency:
				lines.append({"rule": "MONEY", "points": 0, "note": f"currency {ccy} ≠ program {program_doc.currency}"})
				continue
			pts = amount * rate
		elif r.basis == "NIGHTS":
			pts = rate * nights
		elif r.basis == "STAY":
			pts = rate
		elif r.basis == "ROOM":
			if r.room_type != res.room_type:
				continue
			pts = rate * nights
		else:  # EXTRA: points per booked unit of a specific extra (from the price snapshot)
			snap = json.loads(res.tex_pricing_snapshot or "{}")
			code = frappe.db.get_value("TEX Extra", r.extra, "extra_code") if r.extra else None
			qty = sum(int(e.get("quantity") or 1) for e in snap.get("extras") or [] if e.get("ok")
			          and e.get("code") == code)
			pts = rate * qty
		total += pts
		lines.append({"rule": r.basis, "rate": str(rate), "points": str(pts)})
	total = total * D(str(multiplier or 1))
	return int(total.to_integral_value(rounding=ROUND_FLOOR)), lines


def on_reservation_change(doc) -> None:
	"""doc_event (Reservation.on_update): earn when confirmed, reverse when cancelled, and
	earn again only when the stay itself changed (its fingerprint). Editing the program's
	rules, tiers or points never rewrites earnings already made (G-24)."""
	if not doc.get("tex_booking") or not doc.guest:
		return
	program = program_for(doc.property)
	if not program:
		return
	existing = frappe.get_all("TEX Loyalty Ledger", filters={"reservation": doc.name, "entry_type": "Earn",
	                                                         "status": ("!=", "Reversed")},
	                          fields=["name", "points", "status", "stay_fingerprint"])
	if doc.status in ("Cancelled", "No Show"):
		for e in existing:
			_reverse(e, reason=f"reservation {doc.status.lower()}")
		_sync_guest(doc.guest)
		return
	if doc.status not in ("Confirmed", "Checked In", "Checked Out"):
		return
	fingerprint = stay_fingerprint(doc)
	if existing and all(e.stay_fingerprint in (fingerprint, None, "") for e in existing):
		return                  # the stay is unchanged (an earning made before G-24 is kept as it was)
	prog = frappe.get_cached_doc("TEX Loyalty Program", program)
	tier = tier_of(prog, balances(doc.guest, program)["lifetime_earned"])
	points, lines = points_for(prog, doc, tier.earn_multiplier if tier else 1)
	for e in existing:
		_reverse(e, reason="reservation modified")
	if points <= 0:
		_sync_guest(doc.guest)
		return
	avail_on = add_days(getdate(doc.check_out_date), int(prog.pending_days or 0))
	frappe.get_doc({
		"doctype": "TEX Loyalty Ledger", "program": program, "guest": doc.guest, "entry_type": "Earn",
		"points": points, "status": "Pending", "available_on": avail_on,
		"expires_on": add_months(avail_on, int(prog.expiry_months)) if prog.expiry_months else None,
		"booking": doc.tex_booking, "reservation": doc.name,
		"reason": f"stay {doc.check_in_date}→{doc.check_out_date}" + (f" · tier {tier.tier_name}" if tier else ""),
		"stay_fingerprint": fingerprint,
		"explanation": json.dumps({"lines": lines, "tier": tier.tier_name if tier else None,
		                           "multiplier": str(tier.earn_multiplier) if tier else "1"}, default=str),
		"actor": frappe.session.user}).insert(ignore_permissions=True)
	_sync_guest(doc.guest)


def _reverse(entry, *, reason: str) -> None:
	"""Take an earning back. Points already spent are not clawed back below zero: the
	balance after reversal is max(0, balance − points), topped up by an Adjust entry."""
	src = frappe.get_doc("TEX Loyalty Ledger", entry.name)
	was_final = src.status in FINAL
	before = balances(src.guest, src.program)["available"] if was_final else 0
	frappe.db.set_value("TEX Loyalty Ledger", src.name, {"status": "Reversed",
	                                                    "reason": f"{src.reason or ''} · reversed: {reason}"[:500]})
	if was_final and before - int(src.points) < 0:
		frappe.get_doc({"doctype": "TEX Loyalty Ledger", "program": src.program, "guest": src.guest,
		                "entry_type": "Adjust", "points": int(src.points) - before, "status": "Available",
		                "booking": src.booking, "reservation": src.reservation,
		                "reason": f"{reason}: reversal limited to unspent points",
		                "actor": frappe.session.user}).insert(ignore_permissions=True)


def _sync_guest(guest: str) -> None:
	total = 0
	for p in frappe.get_all("TEX Loyalty Ledger", filters={"guest": guest}, pluck="program", distinct=True):
		total += balances(guest, p)["available"]
	frappe.db.set_value("Guest", guest, "tex_loyalty_points", total, update_modified=False)


def mature_and_expire(today: date | None = None) -> dict:
	"""Scheduler (daily): Pending → Available on ``available_on``; expire earnings past
	``expires_on`` (never more than the remaining balance)."""
	today = today or getdate(nowdate())
	matured = expired = 0
	for name in frappe.get_all("TEX Loyalty Ledger", filters={"status": "Pending", "entry_type": "Earn",
	                                                          "available_on": ("<=", today)}, pluck="name"):
		frappe.db.set_value("TEX Loyalty Ledger", name, "status", "Available")
		matured += 1
	for e in frappe.get_all("TEX Loyalty Ledger", filters={"status": "Available", "entry_type": "Earn",
	                                                       "expires_on": ("<", today)},
	                        fields=["name", "guest", "program", "points", "booking"]):
		if frappe.db.exists("TEX Loyalty Ledger", {"entry_type": "Expire", "reason": f"expiry of {e.name}"}):
			continue
		bal = balances(e.guest, e.program)["available"]
		take = max(0, min(int(e.points), bal))
		if take:
			frappe.get_doc({"doctype": "TEX Loyalty Ledger", "program": e.program, "guest": e.guest,
			                "entry_type": "Expire", "points": -take, "status": "Expired", "booking": e.booking,
			                "reason": f"expiry of {e.name}"}).insert(ignore_permissions=True)
			expired += take
		_sync_guest(e.guest)
	return {"matured": matured, "expired_points": expired}


def summary(guest: str, programs: set[str] | None = None) -> list[dict]:
	"""``programs``: the ones the viewer may see (another tenant's program is never shown, G-65)."""
	out = []
	for p in frappe.get_all("TEX Loyalty Ledger", filters={"guest": guest}, pluck="program", distinct=True):
		if programs is not None and p not in programs:
			continue
		prog = frappe.get_cached_doc("TEX Loyalty Program", p)
		b = balances(guest, p)
		tier = tier_of(prog, b["lifetime_earned"])
		entries = frappe.get_all("TEX Loyalty Ledger", filters={"guest": guest, "program": p},
		                         fields=["name", "entry_type", "points", "status", "available_on", "expires_on",
		                                 "booking", "reason", "creation"], order_by="creation desc", limit=50)
		for e in entries:
			for k in ("available_on", "expires_on", "creation"):
				e[k] = str(e[k]) if e[k] else None
		out.append({"program": p, "program_name": prog.program_name, "currency": prog.currency, **b,
		            "value": to_str(quantize(D(str(prog.point_value or 0)) * b["available"], prog.currency or "EUR")),
		            "tier": tier.tier_name if tier else None, "entries": entries})
	return out


def adjust(guest: str, program: str, points: int, reason: str) -> str:
	prog = frappe.get_doc("TEX Loyalty Program", program)
	props = [prog.property] if prog.property else frappe.get_all("Property", filters={
		"tex_hotel_group": prog.hotel_group}, pluck="name")
	if not any(scope.has_capability("crm.edit", p) and p in scope.permitted_properties() for p in props):
		frappe.throw(_("Not permitted: {0}.").format("crm.edit"), frappe.PermissionError)
	if not (reason or "").strip():
		frappe.throw(_("A reason is required."))
	points = int(points)
	if points == 0:
		frappe.throw(_("Points must not be zero."))
	if points < 0 and balances(guest, program)["available"] + points < 0:
		frappe.throw(_("The balance cannot go negative."))
	doc = frappe.get_doc({"doctype": "TEX Loyalty Ledger", "program": program, "guest": guest,
	                      "entry_type": "Adjust", "points": points, "status": "Available", "reason": reason[:500],
	                      "actor": frappe.session.user}).insert(ignore_permissions=True)
	_sync_guest(guest)
	audit("loyalty.adjust", reference_doctype="TEX Loyalty Ledger", reference_name=doc.name,
	      property=prog.property, new={"guest": guest, "points": points}, reason=reason)
	return doc.name


def redeem(guest: str, booking: str, points: int, *, idempotency_key: str) -> dict:
	"""Burn points as a payment on a booking (min points, max % of the booking, currency)."""
	b = frappe.get_doc("TEX Booking", booking)
	scope.require("payment.link", b.property)
	guests = {b.booker_guest} | set(frappe.get_all("Reservation", filters={"tex_booking": booking}, pluck="guest"))
	if guest not in guests:
		frappe.throw(_("The booking belongs to another guest."))
	program = program_for(b.property)
	if not program:
		frappe.throw(_("This hotel has no loyalty program."))
	prog = frappe.get_doc("TEX Loyalty Program", program)
	if prog.currency and prog.currency != b.currency:
		frappe.throw(_("Points can only be redeemed on {0} bookings.").format(prog.currency))
	pct = D(str(prog.max_redeem_percent if prog.max_redeem_percent is not None else 100))
	if pct <= 0:
		frappe.throw(_("Points cannot be redeemed in this program."))
	for r in frappe.get_all("Reservation", filters={"tex_booking": booking, "status": ("not in", ["Cancelled",
	                                                                                               "No Show"])},
	                        fields=["check_in_date", "check_out_date"]):
		ci, co = getdate(r.check_in_date), getdate(r.check_out_date)
		blocked = next((ci + timedelta(days=i) for i in range(max((co - ci).days, 1))
		                if _in_blackout(prog, ci + timedelta(days=i), "Redemption")), None)
		if blocked:
			frappe.throw(_("Points cannot be redeemed for stays on {0}.").format(frappe.format(blocked, "Date")))
	from kamra.tex.payments.service import ns_key

	idempotency_key = ns_key(b.property, idempotency_key, "loyalty")
	if not idempotency_key:
		frappe.throw(_("Idempotency key required."))
	done = frappe.db.get_value("TEX Payment Transaction", {"idempotency_key": idempotency_key}, "name")
	if done:
		return {"transaction": done, "replay": True}
	points = int(points)
	if points < int(prog.min_redeem_points or 0) or points <= 0:
		frappe.throw(_("At least {0} points must be redeemed.").format(prog.min_redeem_points or 1))
	frappe.db.sql("SELECT name FROM `tabGuest` WHERE name=%s FOR UPDATE", guest)
	if balances(guest, program)["available"] < points:
		frappe.throw(_("Not enough points."))
	value = quantize(D(str(prog.point_value or 0)) * points, b.currency)
	cap = quantize(from_db(b.total_amount, b.currency) * pct / 100, b.currency)
	if value > cap:
		frappe.throw(_("Points can cover at most {0} {1} of this booking.").format(to_str(cap), b.currency))
	from kamra.tex.payments import service as pay

	txn = frappe.get_doc({"doctype": "TEX Payment Transaction", "property": b.property, "txn_type": "Charge",
	                      "status": "Succeeded", "method": "Manual", "provider": "Loyalty", "amount": value,
	                      "currency": b.currency, "idempotency_key": idempotency_key, "booking": booking,
	                      "provider_ref": f"{points} pts", "raw_status": "REDEEMED", "completed_at": now_datetime(),
	                      "actor": frappe.session.user, "reason": f"loyalty {program}"})
	txn.insert(ignore_permissions=True)
	pay.allocate(txn.name, booking=booking, amount=value, reason="loyalty redemption", _system=True)
	led = frappe.get_doc({"doctype": "TEX Loyalty Ledger", "program": program, "guest": guest, "entry_type": "Burn",
	                      "points": -points, "status": "Used", "booking": booking,
	                      "reason": f"redeemed as {txn.name}", "actor": frappe.session.user}).insert(
		ignore_permissions=True)
	_sync_guest(guest)
	audit("loyalty.redeem", reference_doctype="TEX Loyalty Ledger", reference_name=led.name, property=b.property,
	      new={"booking": booking, "points": points, "value": to_str(value), "transaction": txn.name})
	return {"transaction": txn.name, "ledger": led.name, "value": to_str(value), "currency": b.currency}
