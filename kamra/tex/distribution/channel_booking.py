"""Bookings received from a channel manager (G-69, ADR-039).

A channel booking is the channel's sale: its price is the channel's (``tex_pricing_source
= "Channel"``, price-locked, revision basis ``EXTERNAL``), not TEX's. TEX takes the nights
under the same locks as its own sales and accepts the booking even when its own count
says no room is left — the channel already sold it — recording an overbooking warning
and an audit event rather than refusing a guest who holds a confirmation.

Messages carry the full state of the booking: ``new`` and ``modified`` both make TEX's
rooms equal to the message (by the channel's room line id), ``cancelled`` cancels every
room. The same message is applied once (the inbound idempotency key); a modification
for a booking TEX has not seen is applied as new.
"""

from __future__ import annotations

import json

import frappe
from frappe import _
from frappe.utils import getdate, now_datetime

from kamra.tex.distribution.adapters import AdapterError
from kamra.tex.money import D, quantize, to_str
from kamra.tex.security.audit import audit
from kamra.tex.services import booking as booking_svc

LIVE = ("Confirmed", "Checked In", "Pending Payment", "Held")


def _mapping(connection: str, room_code: str, rate_code: str):
	name = frappe.db.get_value("TEX Channel Mapping", {"connection": connection, "external_room_code": room_code,
	                                                   "external_rate_code": rate_code, "enabled": 1})
	if not name:
		# retried: once someone maps this room/rate, the booking goes in
		raise AdapterError(f"room {room_code} / rate {rate_code} is not mapped for this connection")
	return frappe.get_cached_doc("TEX Channel Mapping", name)


def _guest(g: dict | None, *, property: str, market: str, ref: str) -> str:
	g = g or {}
	first = (g.get("first_name") or "").strip() or _("Channel guest")
	last = (g.get("last_name") or "").strip() or ref
	email = (g.get("email") or "").strip().lower() or None
	if email and ("@" not in email or len(email) > 140):
		email = None
	return booking_svc.find_or_create_guest({"first_name": first[:80], "last_name": last[:80], "email": email,
	                                         "phone": (g.get("phone") or None), "country": g.get("country")},
	                                        property=property, market=market, language=None)


def _snapshot(room: dict, m, conn: str, ref: str, ccy: str) -> dict:
	total = quantize(D(room["total"]), ccy)
	return {"source": "channel", "connection": conn, "provider_ref": ref, "line_ref": room["line_ref"],
	        "currency": ccy, "request": {"room_type": m.room_type, "board": m.board, "check_in": room["check_in"],
	                                     "check_out": room["check_out"], "adults": room["adults"],
	                                     "children": [{"age": a} for a in room.get("children_ages") or []],
	                                     "market": m.market, "channel": m.sales_channel},
	        "channel_codes": {"room": room["room_code"], "rate": room["rate_code"]},
	        "totals": {"total": to_str(total), "tax": "0", "subtotal": to_str(total)},
	        "lines": [{"kind": "ACCOMMODATION", "label": f"{room['room_code']} / {room['rate_code']}",
	                   "amount": to_str(total)}],
	        "explanation": [{"step": "channel", "detail": f"priced by the channel ({ref})"}]}


def _lock_and_check(property: str, room_type: str, ci, co, exclude: list[str]) -> str | None:
	"""Take the nights under TEX's locks; → a warning when TEX shows no room left."""
	from kamra.tex.availability import repository as avail

	avail.lock_nights(property, [(room_type, ci, co)])
	count, _days = avail.stay_availability(property, room_type, None, ci, co, getdate(), exclude=exclude,
	                                       locking=True)
	return None if count >= 1 else f"{room_type} {ci}→{co}: accepted from the channel although TEX shows no room left"


def _contract_warning(m, now) -> str | None:
	"""A stay the channel sold on a contract TEX no longer sells (suspended, archived, or closed for
	this market and channel before the closed ARI reached the channel) is accepted like an
	overbooking: the guest holds the channel's confirmation (ADR-045)."""
	from kamra.tex.commercial import contracts

	if m.contract:
		if contracts.not_on_sale(m.contract):
			status = frappe.db.get_value("TEX Contract", m.contract, "status")
			return (f"{m.room_type}: accepted from the channel although its contract {m.contract} is "
			        f"{(status or 'not active').lower()} in TEX")
		return None
	if not contracts.candidate_contracts(m.property, m.market, m.sales_channel, now):
		return f"{m.room_type}: accepted from the channel although no TEX contract sells {m.market} on {m.sales_channel}"
	return None


def _reservation_values(room: dict, m, conn: str, ref: str, ccy: str) -> dict:
	total = quantize(D(room["total"]), ccy)
	kids = list(room.get("children_ages") or [])
	return {
		"room_type": m.room_type, "check_in_date": room["check_in"], "check_out_date": room["check_out"],
		"adults": int(room["adults"]), "children": len(kids), "tex_child_ages": json.dumps(kids),
		"tex_board": m.board, "rate_plan": m.rate_plan, "tex_market": m.market, "tex_sales_channel": m.sales_channel,
		"tex_currency": ccy, "tex_total_amount": total, "amount_after_tax": total, "amount_before_tax": total,
		"tax_amount": 0, "tex_pricing_source": "Channel", "tex_price_locked": 1,
		"tex_pricing_snapshot": json.dumps(_snapshot(room, m, conn, ref, ccy), sort_keys=True),
		"ota_ref": f"{ref}-{room['line_ref']}"[:140],
	}


def apply(inbound) -> dict:
	"""Apply one stored channel message (a TEX Channel Inbound row)."""
	data = json.loads(inbound.payload or "{}")
	conn, ref, status = inbound.connection, data["provider_ref"], data["status"]
	existing = frappe.db.get_value("TEX Booking", {"channel_connection": conn, "external_ref": ref}, "name")
	if status == "cancelled":
		if not existing:
			return {"status": "Ignored", "warning": "cancellation of a booking TEX never received"}
		return _cancel_all(existing, ref, inbound.name)
	rooms = data.get("rooms") or []
	currencies = {r["currency"] for r in rooms}
	if len(currencies) != 1 or not next(iter(currencies)):
		raise AdapterError("a booking must be in one currency", retryable=False)
	ccy = currencies.pop()
	mapped = [(r, _mapping(conn, r["room_code"], r["rate_code"])) for r in rooms]
	prop = frappe.db.get_value("TEX Integration Connection", conn, "property")
	if any(m.property != prop for _r, m in mapped):
		raise AdapterError("a mapping points at another hotel", retryable=False)
	if existing:
		return _update(existing, mapped, data, conn, ref, ccy, inbound.name)
	return _create(prop, mapped, data, conn, ref, ccy, inbound.name)


def _lock_all(prop: str, mapped: list) -> None:
	"""Every room's nights, before the guest, the booking or any room takes a name: the lock
	order of a TEX booking and of a desk write, so none of them waits on another in a cycle
	(G-49 review). Each room is then recounted under these locks."""
	from kamra.tex.availability import repository as avail

	avail.lock_nights(prop, [(m.room_type, getdate(r["check_in"]), getdate(r["check_out"])) for r, m in mapped])


def _create(prop: str, mapped: list, data: dict, conn: str, ref: str, ccy: str, inbound: str) -> dict:
	first = mapped[0][1]
	_lock_all(prop, mapped)
	guest = _guest(data.get("guest"), property=prop, market=first.market, ref=ref)
	now = now_datetime()
	total = sum((quantize(D(r["total"]), ccy) for r, _m in mapped), D(0))
	g = data.get("guest") or {}
	booking = frappe.get_doc({
		"doctype": "TEX Booking", "property": prop, "status": "Confirmed", "sales_channel": first.sales_channel,
		"market": first.market, "created_via": "Channel", "sale_at": now, "channel_connection": conn,
		"external_ref": ref, "booker_guest": guest,
		"booker_name": " ".join(x for x in (g.get("first_name"), g.get("last_name")) if x) or ref,
		"booker_email": (g.get("email") or None), "booker_phone": (g.get("phone") or None), "currency": ccy,
		"total_amount": total, "paid_amount": 0, "balance_amount": total, "amount_due_now": 0,
		"payment_status": "Pay at Hotel", "payment_method": "Channel",
		"notes": f"{data.get('channel_name') or ''} {data.get('notes') or ''}".strip()[:2000],
		"source": f"channel:{conn}"[:140],
	})
	booking.insert(ignore_permissions=True)
	warnings = []
	for idx, (room, m) in enumerate(mapped):
		ci, co = getdate(room["check_in"]), getdate(room["check_out"])
		w = _lock_and_check(prop, m.room_type, ci, co, [])
		if w:
			warnings.append(w)
		w = _contract_warning(m, now)
		if w:
			warnings.append(w)
		res = frappe.get_doc({"doctype": "Reservation", "property": prop, "guest": guest, "status": "Confirmed",
		                      "source": "OTA", "channel": m.sales_channel, "auto_price": 0, "tex_booking": booking.name,
		                      "tex_room_index": idx + 1, "tex_sale_at": now, "tex_locked_at": now, "tex_accepted_at": now,
		                      "is_pay_at_hotel": 1, **_reservation_values(room, m, conn, ref, ccy)})
		res.flags.tex_channel_accept = True
		res.flags.allow_past_check_in = True
		res.insert(ignore_permissions=True)
		booking.append("rooms", {"reservation": res.name, "room_type": m.room_type, "check_in": ci, "check_out": co,
		                         "adults": int(room["adults"]), "children": len(room.get("children_ages") or []),
		                         "amount": res.tex_total_amount, "status": "Confirmed"})
		booking_svc._record_revision(res.name, booking.name, change_type="Original", old_amount=None,
		                             new_amount=res.tex_total_amount, currency=ccy, basis="EXTERNAL",
		                             reason=f"received from the channel ({ref})", source="Channel",
		                             after=json.loads(res.tex_pricing_snapshot))
	booking.save(ignore_permissions=True)
	_warn(prop, booking.name, ref, warnings)
	audit("channel.booking", reference_doctype="TEX Booking", reference_name=booking.name, property=prop,
	      new={"ref": ref, "rooms": len(mapped), "total": to_str(total), "currency": ccy, "inbound": inbound},
	      source="Webhook")
	return {"status": "Applied", "booking": booking.name, "warning": "; ".join(warnings) or None}


def _update(booking: str, mapped: list, data: dict, conn: str, ref: str, ccy: str, inbound: str) -> dict:
	"""Make TEX's rooms equal to the channel's (full state), line by line."""
	b = frappe.get_doc("TEX Booking", booking)
	prop = b.property
	_lock_all(prop, mapped)
	lines = {}
	for row in b.rooms:
		snap = json.loads(frappe.db.get_value("Reservation", row.reservation, "tex_pricing_snapshot") or "{}")
		lines[snap.get("line_ref")] = row.reservation
	warnings, seen = [], set()
	now = now_datetime()
	for room, m in mapped:
		name = lines.get(room["line_ref"])
		seen.add(room["line_ref"])
		ci, co = getdate(room["check_in"]), getdate(room["check_out"])
		values = _reservation_values(room, m, conn, ref, ccy)
		if name is None:
			w = _lock_and_check(prop, m.room_type, ci, co, [])
			stopped = _contract_warning(m, now)
			if stopped:
				warnings.append(stopped)
			res = frappe.get_doc({"doctype": "Reservation", "property": prop, "guest": b.booker_guest,
			                      "status": "Confirmed", "source": "OTA", "channel": m.sales_channel, "auto_price": 0,
			                      "tex_booking": b.name, "tex_room_index": len(b.rooms) + 1, "tex_sale_at": now,
			                      "tex_locked_at": now, "tex_accepted_at": now, "is_pay_at_hotel": 1, **values})
			res.flags.tex_channel_accept = True
			res.flags.allow_past_check_in = True
			res.insert(ignore_permissions=True)
			b.append("rooms", {"reservation": res.name, "room_type": m.room_type, "check_in": ci, "check_out": co,
			                   "adults": int(room["adults"]), "children": len(room.get("children_ages") or []),
			                   "amount": res.tex_total_amount, "status": "Confirmed"})
			booking_svc._record_revision(res.name, b.name, change_type="Original", old_amount=None,
			                             new_amount=res.tex_total_amount, currency=ccy, basis="EXTERNAL",
			                             reason=f"room added by the channel ({ref})", source="Channel")
		else:
			res = frappe.get_doc("Reservation", name)
			before = {f: str(res.get(f) or "") for f in values if f != "tex_pricing_snapshot"}
			if all(before[f] == str(values[f] or "") for f in before) and res.status in LIVE:
				continue
			w = _lock_and_check(prop, m.room_type, ci, co, [res.name])
			old = D(str(res.tex_total_amount or 0))
			res.update(values)
			if res.status not in LIVE:
				res.status = "Confirmed"
			res.flags.tex_modification = True
			res.flags.tex_channel_accept = True
			res.flags.allow_past_check_in = True
			res.save(ignore_permissions=True)
			booking_svc._record_revision(res.name, b.name, change_type="Multiple", old_amount=old,
			                             new_amount=res.tex_total_amount, currency=ccy, basis="EXTERNAL",
			                             reason=f"modified by the channel ({ref})", source="Channel",
			                             changes={k: [before.get(k), str(values[k])] for k in before
			                                      if before[k] != str(values[k] or "")})
		if w:
			warnings.append(w)
	for line, name in lines.items():
		if line not in seen and frappe.db.get_value("Reservation", name, "status") in LIVE:
			_cancel_one(name, b.name, f"room removed by the channel ({ref})")
	b.save(ignore_permissions=True)
	booking_svc._refresh_booking_after_change(b.name)
	_warn(prop, b.name, ref, warnings)
	audit("channel.booking_modified", reference_doctype="TEX Booking", reference_name=b.name, property=prop,
	      new={"ref": ref, "rooms": len(mapped), "inbound": inbound}, source="Webhook")
	return {"status": "Applied", "booking": b.name, "warning": "; ".join(warnings) or None}


def _cancel_one(reservation: str, booking: str, reason: str) -> None:
	"""The channel's cancellation: no TEX penalty (the channel's own terms apply)."""
	res = frappe.get_doc("Reservation", reservation)
	old = D(str(res.tex_total_amount or 0))
	frappe.flags.kamra_cancelling = True
	frappe.flags.kamra_status_transition = True
	try:
		res.status = "Cancelled"
		res.cancellation_reason = "Other"
		res.cancellation_note = reason[:500]
		res.cancellation_fee = 0
		res.cancelled_on = now_datetime()
		res.flags.tex_modification = True
		res.save(ignore_permissions=True)
	finally:
		frappe.flags.kamra_cancelling = False
		frappe.flags.kamra_status_transition = False
	booking_svc._record_revision(res.name, booking, change_type="Cancellation", old_amount=old, new_amount=0,
	                             currency=res.tex_currency, basis="EXTERNAL", reason=reason, source="Channel")


def _cancel_all(booking: str, ref: str, inbound: str) -> dict:
	b = frappe.get_doc("TEX Booking", booking)
	n = 0
	for row in b.rooms:
		if frappe.db.get_value("Reservation", row.reservation, "status") in LIVE:
			_cancel_one(row.reservation, b.name, f"cancelled by the channel ({ref})")
			n += 1
	booking_svc._refresh_booking_after_change(b.name)
	audit("channel.booking_cancelled", reference_doctype="TEX Booking", reference_name=b.name, property=b.property,
	      new={"ref": ref, "rooms": n, "inbound": inbound}, source="Webhook")
	return {"status": "Applied", "booking": b.name, "warning": None if n else "already cancelled"}


def _warn(prop: str, booking: str, ref: str, warnings: list[str]) -> None:
	if warnings:
		audit("channel.overbooking", reference_doctype="TEX Booking", reference_name=booking, property=prop,
		      new={"ref": ref, "warnings": warnings}, source="Webhook")
