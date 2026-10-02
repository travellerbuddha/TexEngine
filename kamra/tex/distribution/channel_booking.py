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

A modification or cancellation locks the booking, then its reservations (by name), then the
nights: the order every change to a TEX booking takes (ADR-044) and the order of a desk save of
a room, and a guest change still waiting for a room the channel changed or cancelled is void
(G-45 re-review F8, third review).
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


def _restriction_warning(property: str, m, ci, co, now, before=None, product_changed: bool = False) -> str | None:
	"""A stay the channel sold although a TEX restriction of its scope refuses it (a stop sell,
	CTA/CTD, a length of stay, the booking window …) is accepted like an overbooking: the guest
	holds the channel's confirmation (ADR-039, G-48). ``before``: the stay a modification
	replaces (``product_changed``: now another room type, rate plan or market): only what it
	newly takes is checked (ADR-057)."""
	from kamra.tex.availability import repository as avail
	from kamra.tex.distribution.repository import _contract_version

	contract = m.contract or _contract_version(m, now)[0]
	sc = avail.scope_for(m.room_type, contract, m.market, m.rate_plan, m.sales_channel)
	found = avail.check_restrictions(property, sc, ci, co, now.date(), before=before,
	                                 product_changed=product_changed)
	if not found:
		return None
	return (f"{m.room_type} {ci}→{co}: accepted from the channel although TEX restrictions refuse it: "
	        + "; ".join(v.message for v in found))


def _room_type_warning(m) -> str | None:
	"""A stay the channel sold in a room type TEX no longer sells (before its closed ARI reached the channel, or while
	its connection is off) is accepted like an overbooking: the guest holds the channel's confirmation (LO-03)."""
	if frappe.db.get_value("Room Type", m.room_type, "disabled"):
		return f"{m.room_type}: accepted from the channel although its room type is no longer sold in TEX"
	return None


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
		w = _room_type_warning(m)
		if w:
			warnings.append(w)
		w = _contract_warning(m, now)
		if w:
			warnings.append(w)
		w = _restriction_warning(prop, m, ci, co, now)
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
	from kamra.tex.services import guest_changes

	b = frappe.get_doc("TEX Booking", booking, for_update=True)          # the booking first
	prop = b.property
	# then its rooms, by name, then every night: a desk or PMS save of a room locks the room, then
	# its nights, so the two never wait on each other in a cycle; a new room still takes no name
	# before all the nights are held (G-49). Third review of ADR-044.
	for name in sorted(row.reservation for row in b.rooms):
		frappe.db.get_value("Reservation", name, "name", for_update=True)
	_lock_all(prop, mapped)
	lines = {}
	for row in b.rooms:
		snap = json.loads(frappe.db.get_value("Reservation", row.reservation, "tex_pricing_snapshot") or "{}")
		lines[snap.get("line_ref")] = row.reservation
	warnings, seen, reactivated = [], set(), []
	now = now_datetime()
	for room, m in mapped:
		name = lines.get(room["line_ref"])
		seen.add(room["line_ref"])
		ci, co = getdate(room["check_in"]), getdate(room["check_out"])
		values = _reservation_values(room, m, conn, ref, ccy)
		if name is None:
			w = _lock_and_check(prop, m.room_type, ci, co, [])
			disabled = _room_type_warning(m)
			if disabled:
				warnings.append(disabled)
			stopped = _contract_warning(m, now)
			if stopped:
				warnings.append(stopped)
			restricted = _restriction_warning(prop, m, ci, co, now)
			if restricted:
				warnings.append(restricted)
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
			res = frappe.get_doc("Reservation", name, for_update=True)      # locked above: read as it is now
			before = {f: str(res.get(f) or "") for f in values if f != "tex_pricing_snapshot"}
			if all(before[f] == str(values[f] or "") for f in before) and res.status in LIVE:
				continue
			w = _lock_and_check(prop, m.room_type, ci, co, [res.name])
			# the nights, arrival and departure the line already had are its own (ADR-057)
			same = (res.room_type, res.rate_plan or None, res.tex_market) == (m.room_type, m.rate_plan or None, m.market)
			# moved into a room type no longer sold, or brought back into one (a new sale, as for the restrictions); a
			# stay already in it is the hotel's to keep (ADR-048)
			disabled = _room_type_warning(m) if res.room_type != m.room_type or res.status not in LIVE else None
			if disabled:
				warnings.append(disabled)
			restricted = _restriction_warning(prop, m, ci, co, now, before=(
				getdate(res.check_in_date), getdate(res.check_out_date)) if res.status in LIVE else None,
				product_changed=not same)
			if restricted:
				warnings.append(restricted)
			old = D(str(res.tex_total_amount or 0))
			was = res.status
			res.update(values)
			changes = {k: [before.get(k), str(values[k])] for k in before if before[k] != str(values[k] or "")}
			res.flags.tex_modification = True
			res.flags.tex_channel_accept = True
			res.flags.allow_past_check_in = True
			if was == "Cancelled":
				# the channel brings back a room it had taken off (D-11, Y-8): a live stay again, as the nights above
				# were counted for it (accepted as sold, an overbooking warned). The one status move out of Cancelled
				# is allowed here, as a revival's (``revive_expired``); its cancellation is cleared
				res.status = "Confirmed"
				res.cancellation_reason = res.cancellation_note = res.cancelled_on = None
				res.cancellation_fee = 0
				res.tex_hold_expired = 0
				changes["status"] = ["Cancelled", "Confirmed"]
				reactivated.append(res.name)
				frappe.flags.kamra_status_transition = True
				try:
					res.save(ignore_permissions=True)
				finally:
					frappe.flags.kamra_status_transition = False
			else:
				if was not in LIVE:
					# a no-show or a stay already checked out keeps its status: the channel does not undo it
					warnings.append(_("Room {0} of {1} is {2}: the channel's change was applied, its status kept.").format(
						room["line_ref"], ref, was))
				res.save(ignore_permissions=True)
			booking_svc._record_revision(res.name, b.name, change_type="Multiple", old_amount=old,
			                             new_amount=res.tex_total_amount, currency=ccy, basis="EXTERNAL",
			                             reason=f"modified by the channel ({ref})", source="Channel", changes=changes)
			guest_changes.close_open(res.name, f"the channel changed the room ({ref})")
		if w:
			warnings.append(w)
	removed = []
	for line, name in lines.items():
		if line not in seen and frappe.db.get_value("Reservation", name, "status") in LIVE:
			removed.append(_cancel_one(name, b.name, f"room removed by the channel ({ref})"))
	if reactivated and b.status in ("Cancelled", "Partially Cancelled"):
		b.status = "Confirmed"          # a room is live again; the refresh below says "Partially Cancelled" if one is not
	b.save(ignore_permissions=True)
	booking_svc._refresh_booking_after_change(b.name)
	_points_back(b.name, removed, f"room removed by the channel ({ref})")
	_warn(prop, b.name, ref, warnings)
	audit("channel.booking_modified", reference_doctype="TEX Booking", reference_name=b.name, property=prop,
	      new={"ref": ref, "rooms": len(mapped), "inbound": inbound, "reactivated": reactivated}, source="Webhook")
	return {"status": "Applied", "booking": b.name, "warning": "; ".join(warnings) or None}


def _cancel_one(reservation: str, booking: str, reason: str):
	"""The channel's cancellation: no TEX penalty (the channel's own terms apply). The caller
	holds the booking's lock and, once the booking is refreshed, gives its points back
	(``_points_back``). → the reservation."""
	from kamra.tex.services import guest_changes

	res = frappe.get_doc("Reservation", reservation, for_update=True)
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
		# the stay's own earning is reversed after the points spent on its booking came back (as at the desk)
		res.flags.tex_loyalty_after_money = True
		res.save(ignore_permissions=True)
	finally:
		frappe.flags.kamra_cancelling = False
		frappe.flags.kamra_status_transition = False
	booking_svc._record_revision(res.name, booking, change_type="Cancellation", old_amount=old, new_amount=0,
	                             currency=res.tex_currency, basis="EXTERNAL", reason=reason, source="Channel")
	guest_changes.close_open(res.name, f"the room was cancelled ({reason})")
	return res


def _points_back(booking: str, cancelled: list, reason: str) -> None:
	"""D-16 (LO-02): after the channel's cancellation (the booking refreshed), what the booking's Loyalty charges
	hold beyond what it now costs goes back as points, never as money; then the cancelled stays' own earnings are
	reversed, as ``booking.cancel_reservation`` does. Points were spent on it before redemptions on channel
	bookings were refused."""
	from kamra.tex.crm import loyalty

	if not cancelled:
		return
	loyalty.return_points(booking, reason=reason)
	for res in cancelled:
		res.flags.tex_loyalty_after_money = False
		loyalty.on_reservation_change(res)


def _cancel_all(booking: str, ref: str, inbound: str) -> dict:
	b = frappe.get_doc("TEX Booking", booking, for_update=True)          # the booking first
	n = 0
	cancelled = []
	for row in b.rooms:
		if frappe.db.get_value("Reservation", row.reservation, "status") in LIVE:
			cancelled.append(_cancel_one(row.reservation, b.name, f"cancelled by the channel ({ref})"))
			n += 1
	booking_svc._refresh_booking_after_change(b.name)
	_points_back(b.name, cancelled, f"cancelled by the channel ({ref})")
	audit("channel.booking_cancelled", reference_doctype="TEX Booking", reference_name=b.name, property=b.property,
	      new={"ref": ref, "rooms": n, "inbound": inbound}, source="Webhook")
	return {"status": "Applied", "booking": b.name, "warning": None if n else "already cancelled"}


def _warn(prop: str, booking: str, ref: str, warnings: list[str]) -> None:
	if warnings:
		audit("channel.overbooking", reference_doctype="TEX Booking", reference_name=booking, property=prop,
		      new={"ref": ref, "warnings": warnings}, source="Webhook")
