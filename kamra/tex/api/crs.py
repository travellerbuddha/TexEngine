"""TEX CRS, Call Center and Reservations API (R-24, R-25, R-21–R-23, R-46)."""

from __future__ import annotations

import json

import frappe
from frappe import _
from frappe.utils import getdate

from kamra.tex.api._util import as_int, parse, text
from kamra.tex.commercial import grid as grid_svc
from kamra.tex.money import from_db, to_str
from kamra.tex.security import scope
from kamra.tex.services import booking as booking_svc
from kamra.tex.services import modification, quoting
from kamra.tex.services.txn import retry_on_deadlock

INTERNAL_CHANNELS = ("CALL_CENTER", "B2B", "API", "DIRECT_WEB", "META", "OTA")


# ─── search / quote / book ───────────────────────────────────────────────


@frappe.whitelist(methods=["POST"])   # a party may carry a child's date of birth
def search(check_in: str, check_out: str, rooms, market: str, channel: str = "CALL_CENTER",
           properties=None, hotel_group: str | None = None, destination: str | None = None,
           currency: str | None = None, promo_codes=None):
	"""Group search across every hotel the agent may sell (R-24), on a channel the agent may
	price on at each of them (ADR-050): hotels where they may not are left out, and a channel
	they may price nowhere among the chosen hotels is refused."""
	if channel not in INTERNAL_CHANNELS:
		frappe.throw(_("Unknown channel."))
	allowed = scope.permitted_properties()
	props = parse(properties, None) or sorted(allowed)
	props = [p for p in props if p in allowed and scope.has_capability("price.view", p)]
	if hotel_group:
		props = [p for p in props if frappe.db.get_value("Property", p, "tex_hotel_group") == hotel_group]
	if destination:
		dest = destination.strip().lower()
		props = [p for p in props if dest in (frappe.db.get_value("Property", p, "city") or "").lower()
		         or dest in p.lower()]
	if not props:
		frappe.throw(_("No hotel matches your access and filters."), frappe.PermissionError)
	selling = [p for p in props if scope.may_price_on(channel, p)]
	if not selling:
		frappe.throw(_("You may not sell on the {0} channel at the chosen hotels.").format(channel),
		             frappe.PermissionError)
	props = selling
	res = quoting.search(properties=props, check_in=check_in, check_out=check_out, rooms=rooms, market=market,
	                     channel=channel, currency=currency, promo_codes=parse(promo_codes, []) or (),
	                     internal=True)
	for p in res["properties"]:
		if not scope.has_capability("price.view_cost", p["property"]):
			for group in ("offers", "unavailable"):
				for o in p[group]:
					for r in o["rooms"]:
						quoting.strip_internal(r["quote"], staff=True)
	return res


@frappe.whitelist(methods=["POST"])
def quote(offer_key: str, extras=None, promo_codes=None):
	offer = quoting.verify(offer_key)
	scope.require("reservation.create", offer["property"])
	# the signed offer names its channel: a Booking Engine or OTA offer is not the agent's to sell
	scope.require_channel(offer.get("channel"), offer["property"])
	return quoting.create_quote(offer_key, extras=parse(extras, []), promo_codes=parse(promo_codes, None))


@frappe.whitelist(methods=["POST"])
@retry_on_deadlock
def book(quote_ids, guest, payment_method: str | None = None, confirm_without_payment: int = 0,
         notes: str | None = None, idempotency_key: str | None = None, language: str | None = None):
	ids = parse(quote_ids, [])
	if not ids:
		frappe.throw(_("Select at least one room."))
	require_quotes_sellable(ids)
	out = booking_svc.create_booking(quote_ids=ids, guest=parse(guest, {}), payment_method=payment_method,
	                                 confirm_without_payment=bool(int(confirm_without_payment or 0)),
	                                 notes=text(notes, 2000), idempotency_key=text(idempotency_key, 140),
	                                 language=text(language, 10))
	# the guest's self-service link goes to the guest (email), never to the agent's screen
	out.pop("manage_token", None)
	return out


def require_quotes_sellable(quote_ids) -> None:
	"""The caller may book every one of these quotes: ``reservation.create`` at each quote's
	hotel and the quote's own channel among their channels there (ADR-050). A quote made on the
	Booking Engine or on another channel is never the agent's to book."""
	for qid in quote_ids:
		row = frappe.db.get_value("TEX Quote", str(qid), ["property", "sales_channel"], as_dict=True)
		if not row:
			frappe.throw(_("Quote {0} not found.").format(qid), frappe.DoesNotExistError)
		scope.require("reservation.create", row.property)
		scope.require_channel(row.sales_channel, row.property)


@frappe.whitelist()
def payment_methods(property: str, market: str | None = None, currency: str | None = None,
                    channel: str = "CALL_CENTER"):
	scope.require("price.view", property)
	scope.require_channel(channel, property, to="price")
	from kamra.tex.payments import service as pay

	return pay.payment_methods(property, market=market, currency=currency, channel=channel)


@frappe.whitelist()
def extras_for(property: str):
	scope.require("price.view", property)
	from kamra.tex.commercial.context import listed_extras

	cols = ("extra_code", "extra_name", "category", "pricing_mode", "currency", "amount", "is_mandatory",
	        "description", "max_quantity")
	rows = listed_extras(property, fields=cols)   # the revision on sale now (G-20)
	return [{k: r.get(k) for k in cols} for r in sorted(rows, key=lambda r: (r.category or "", r.extra_name or ""))]


# ─── reservations & bookings ─────────────────────────────────────────────


@frappe.whitelist()
def reservations(property: str | None = None, q: str | None = None, status: str | None = None,
                 arrival_from: str | None = None, arrival_to: str | None = None, pending_only: int = 0,
                 limit: int = 50, start: int = 0):
	props = [property] if property else sorted(scope.permitted_properties())
	props = [p for p in props if scope.has_capability("reservation.view", p)]
	if not props:
		return []
	cond = ["r.property IN %(props)s"]
	vals = {"props": tuple(props), "limit": as_int(limit, 50, lo=1, hi=200), "start": as_int(start, 0, lo=0)}
	if status:
		cond.append("r.status = %(status)s")
		vals["status"] = status
	if arrival_from:
		cond.append("r.check_in_date >= %(af)s")
		vals["af"] = getdate(arrival_from)
	if arrival_to:
		cond.append("r.check_in_date <= %(at)s")
		vals["at"] = getdate(arrival_to)
	if int(pending_only or 0):
		cond.append("r.tex_guest_change_pending = 1")
	if q:
		cond.append("(r.name LIKE %(q)s OR r.guest_name LIKE %(q)s OR r.tex_booking LIKE %(q)s "
		            "OR g.email LIKE %(q)s OR g.phone LIKE %(q)s)")
		vals["q"] = f"%{q.strip()[:60]}%"
	rows = frappe.db.sql(f"""
		SELECT r.name, r.property, r.status, r.guest, r.guest_name, r.room_type, rt.room_type_name, r.room,
		       r.check_in_date, r.check_out_date, r.nights, r.adults, r.children, r.tex_booking, r.tex_market,
		       r.tex_sales_channel, r.tex_board, r.tex_currency, r.tex_total_amount, r.amount_after_tax,
		       r.tex_guest_change_pending, r.tex_revision_no, r.creation
		FROM `tabReservation` r
		LEFT JOIN `tabGuest` g ON g.name = r.guest
		LEFT JOIN `tabRoom Type` rt ON rt.name = r.room_type
		WHERE {' AND '.join(cond)}
		ORDER BY r.creation DESC LIMIT %(start)s, %(limit)s""", vals, as_dict=True)  # nosemgrep -- static conditions, values bound
	for r in rows:
		ccy = r.tex_currency or "EUR"
		r["total"] = to_str(from_db(r.tex_total_amount or r.amount_after_tax, ccy))
		r.pop("tex_total_amount")
		r.pop("amount_after_tax")
	return rows


@frappe.whitelist()
def reservation(name: str):
	res = frappe.get_doc("Reservation", name)
	scope.require("reservation.view", res.property)
	internal = scope.has_capability("price.view_cost", res.property)
	snap = json.loads(res.tex_pricing_snapshot or "{}")
	if not internal:
		quoting.strip_internal(snap, staff=True)
	guest = frappe.db.get_value("Guest", res.guest, ["name", "full_name", "email", "phone", "tex_language",
	                                                "tex_country", "vip", "tex_tags"], as_dict=True) \
		if scope.has_capability("crm.view", res.property) else None
	ccy = res.tex_currency or "EUR"
	return {
		"name": res.name, "status": res.status, "property": res.property, "booking": res.tex_booking,
		"room_type": res.room_type, "room_type_name": frappe.db.get_value("Room Type", res.room_type, "room_type_name"),
		"room": res.room, "check_in": str(res.check_in_date), "check_out": str(res.check_out_date),
		"nights": res.nights, "adults": res.adults, "children": res.children,
		"child_ages": json.loads(res.tex_child_ages or "[]"), "board": res.tex_board, "rate_plan": res.rate_plan,
		"market": res.tex_market, "channel": res.tex_sales_channel, "currency": ccy,
		"total": to_str(from_db(res.tex_total_amount or res.amount_after_tax, ccy)),
		"cancellation_fee": to_str(from_db(res.cancellation_fee, ccy)) if res.cancellation_fee else None,
		"price_locked": bool(res.tex_price_locked), "pricing_source": res.tex_pricing_source,
		"contract": res.tex_contract, "contract_version": res.tex_contract_version, "sale_at": str(res.tex_sale_at),
		"revision_no": res.tex_revision_no, "guest_change_pending": bool(res.tex_guest_change_pending),
		"guest_change_note": res.tex_guest_change_note, "special_requests": res.special_requests,
		"guest": guest, "pricing": snap,
		"revisions": modification.revisions(res.name),
		"capabilities": sorted(scope.capabilities(res.property)),
	}


@frappe.whitelist()
def booking(name: str):
	b = frappe.get_doc("TEX Booking", name)
	scope.require("reservation.view", b.property)
	out = booking_svc.booking_summary(name)
	if scope.has_capability("payment.view", b.property):
		out["transactions"] = frappe.get_all(
			"TEX Payment Transaction", filters={"booking": name},
			fields=["name", "txn_type", "status", "method", "amount", "currency", "provider", "card_brand",
			        "card_last4", "completed_at", "creation"], order_by="creation asc")
		for t in out["transactions"]:
			t["amount"] = to_str(from_db(t["amount"], t["currency"] or "EUR"))
		out["payment_links"] = frappe.get_all("TEX Payment Link", filters={"booking": name},
		                                      fields=["name", "status", "amount", "paid_amount", "currency",
		                                              "expires_at", "creation"], order_by="creation asc")
		for link in out["payment_links"]:
			ccy = link["currency"] or b.currency or "EUR"
			link["amount"] = to_str(from_db(link["amount"], ccy))
			link["paid_amount"] = to_str(from_db(link["paid_amount"], ccy))
	return out


@frappe.whitelist(methods=["POST"])
def resend_confirmation(booking: str):
	"""Send the guest the booking e-mail again (with a fresh manage link)."""
	b = frappe.db.get_value("TEX Booking", text(booking, 140), "property")
	if not b:
		frappe.throw(_("Booking not found."), frappe.DoesNotExistError)
	scope.require("reservation.modify", b)
	return booking_svc.resend_confirmation(text(booking, 140))


# ─── modification / simulation / cancel ──────────────────────────────────


@frappe.whitelist(methods=["POST"])
def propose_modification(reservation: str, changes, basis: str = "CURRENT", basis_sale_at: str | None = None):
	return modification.propose(reservation, parse(changes, {}), basis=basis, basis_sale_at=basis_sale_at)


@frappe.whitelist(methods=["POST"])
@retry_on_deadlock
def apply_modification(proposal_token: str, reason: str, override_amount: str | None = None):
	return modification.apply(proposal_token, reason=text(reason, 500), override_amount=override_amount or None)


@frappe.whitelist()
def simulate(reservation: str, sale_at: str):
	return modification.simulate(reservation, sale_at)


@frappe.whitelist()
def cancellation_preview(reservation: str):
	res = frappe.get_doc("Reservation", reservation)
	scope.require("reservation.cancel", res.property)
	penalty, basis = booking_svc.cancellation_penalty(res)
	return {"penalty": to_str(penalty), "currency": res.tex_currency, "basis": basis}


@frappe.whitelist(methods=["POST"])
def cancel(reservation: str, reason: str, waive_penalty: int = 0):
	return booking_svc.cancel_reservation(reservation, reason=text(reason, 500),
	                                      waive_penalty=bool(int(waive_penalty or 0)))


@frappe.whitelist(methods=["POST"])
def correct_imported_amount(reservation: str, amount: str, reason: str, currency: str | None = None):
	"""Correct the amount (and currency) an imported stay was locked at: ``price.override`` at
	its hotel, a reason, a revision and an audit event (ADR-052 review H1)."""
	from kamra.tex.services import imported

	return imported.correct_amount(reservation, amount, reason, currency)


@frappe.whitelist(methods=["POST"])
def acknowledge_guest_change(reservation: str, note: str | None = None):
	res = frappe.get_doc("Reservation", reservation)
	scope.require("reservation.modify", res.property)
	# only the flag and its note: the reservation's modified stays, so a guest's change waiting
	# for its payment or for approval still applies (G-45)
	frappe.db.set_value("Reservation", reservation, {
		"tex_guest_change_pending": 0,
		"tex_guest_change_note": ((res.tex_guest_change_note or "") + f"\n[ack {frappe.session.user}] {note or ''}")[
			-1000:]}, update_modified=False)
	if res.tex_booking and not frappe.db.exists("Reservation", {"tex_booking": res.tex_booking,
	                                                             "tex_guest_change_pending": 1}):
		frappe.db.set_value("TEX Booking", res.tex_booking, "guest_change_pending", 0)
	from kamra.tex.security.audit import audit

	audit("reservation.guest_change_ack", reference_doctype="Reservation", reference_name=reservation,
	      property=res.property, reason=note)
	return {"ok": True}


# ─── guest change requests (G-45) ────────────────────────────────────────


@frappe.whitelist()
def guest_change_requests(property: str | None = None, status: str | None = None, reservation: str | None = None,
                          booking: str | None = None, needs_staff: int = 0, limit: int = 50, start: int = 0):
	"""Guest changes of the hotels the user may view reservations of: what the guest asked, its
	money and how it was settled. ``needs_staff``: a request to decide, or money left to staff."""
	from kamra.tex.services import guest_changes

	props = [property] if property else sorted(scope.permitted_properties())
	props = [p for p in props if scope.has_capability("reservation.view", p)]
	if property and not props:
		frappe.throw(_("Not permitted: {0}.").format("reservation.view"), frappe.PermissionError)
	return guest_changes.staff_list(props, status=text(status, 40), reservation=text(reservation, 140),
	                                booking=text(booking, 140), needs_staff=bool(as_int(needs_staff, 0)),
	                                limit=as_int(limit, 50, lo=1, hi=200), start=as_int(start, 0, lo=0))


@frappe.whitelist(methods=["POST"])
@retry_on_deadlock
def resolve_guest_change(request: str, action: str, reason: str, settlement: str | None = None,
                         refund_outcome: str | None = None, staff_money: str | None = None):
	"""Approve or reject a guest's request (reservation.modify; a refund also needs
	payment.refund), or close money left to staff (payment.refund). Closing a refund the gateway
	never confirmed records what the gateway did: ``refund_outcome`` Succeeded or Failed. Closing
	other money says what became of it: ``staff_money`` "Refunded outside TEX" (recorded on the
	booking) or "Kept on the booking" (G-93)."""
	from kamra.tex.services import guest_changes

	if staff_money not in (None, "", *guest_changes.STAFF_MONEY):
		frappe.throw(_("Choose Refunded outside TEX or Kept on the booking."))
	if settlement not in (None, "", "Refund", "Credit on booking"):
		frappe.throw(_("Choose Refund or Credit on booking."))
	if refund_outcome not in (None, "", "Succeeded", "Failed"):
		frappe.throw(_("Choose whether the gateway refunded it."))
	return guest_changes.resolve(text(request, 140), text(action, 20), settlement=settlement or None,
	                             reason=text(reason, 500), refund_outcome=refund_outcome or None,
	                             staff_money=staff_money or None)


# ─── grid ────────────────────────────────────────────────────────────────


@frappe.whitelist()
def ari_grid(property: str, start: str, days: int = 14, contract: str | None = None, market: str | None = None,
             channel: str | None = None, rate_plan: str | None = None):
	return grid_svc.grid(property, start, days, contract or None, market or None, channel or None, rate_plan or None)


@frappe.whitelist(methods=["POST"])
def ari_bulk_update(property: str, start: str, end: str, room_types, weekdays=None, contract: str | None = None,
                    market: str | None = None, channel: str | None = None, rate_plan: str | None = None,
                    restrictions=None, inventory=None, rate=None):
	scope.assert_property(property)
	return grid_svc.bulk_update(property, start, end, room_types=parse(room_types, []),
	                            weekdays=parse(weekdays, None) or None, contract=contract or None,
	                            market=market or None, channel=channel or None, rate_plan=rate_plan or None,
	                            restrictions=parse(restrictions, None), inventory=parse(inventory, None),
	                            rate=parse(rate, None))


# ─── limited extras (G-19) ───────────────────────────────────────────────


@frappe.whitelist()
def extras_availability(property: str, check_in: str, check_out: str):
	"""What is left of each limited extra per day of a stay (the agent's extras picker)."""
	scope.require("price.view", property)
	from kamra.tex.availability import extras_repository as xinv

	ci, co = getdate(check_in), getdate(check_out)
	if co < ci or (co - ci).days > 60:
		frappe.throw(_("Choose a stay of at most 60 nights."))
	avail = xinv.availability(property, xinv.tracked(property), ci, co)
	return {code: {str(d): {"remaining": a.remaining, "closed": a.closed} for d, a in days.items()}
	        for code, days in avail.items()}


@frappe.whitelist()
def extras_grid(property: str, start: str, days: int = 14):
	scope.require("price.view", property)
	from kamra.tex.availability import extras_repository as xinv

	return xinv.grid(property, start, as_int(days, 14))


@frappe.whitelist(methods=["POST"])
@retry_on_deadlock
def extras_bulk_update(property: str, extra_codes, start: str, end: str, weekdays=None, capacity=None,
                       closed=None, note: str | None = None):
	scope.require("inventory.edit", property)
	from kamra.tex.availability import extras_repository as xinv
	from kamra.tex.security.audit import audit

	out = xinv.bulk_update(property, parse(extra_codes, []), start, end, weekdays=parse(weekdays, None) or None,
	                       capacity=capacity, closed=closed, note=(text(note, 140) or "") if note is not None else None)
	audit("extra_inventory.update", property=property,
	      new={"extras": parse(extra_codes, []), "start": start, "end": end, "weekdays": parse(weekdays, None),
	           "capacity": capacity, "closed": closed, "updated": out["updated"]})
	return out


@frappe.whitelist()
def extras_allocations(property: str, extra_code: str, date: str):
	scope.require("reservation.view", property)
	from kamra.tex.availability import extras_repository as xinv

	return xinv.allocations(property, (extra_code or "").upper(), date)


@frappe.whitelist(methods=["POST"])
@retry_on_deadlock
def extras_reconcile(property: str, extra_code: str | None = None):
	scope.require("inventory.edit", property)
	from kamra.tex.availability import extras_repository as xinv
	from kamra.tex.security.audit import audit

	drift = xinv.reconcile(property, (extra_code or "").upper() or None)
	audit("extra_inventory.reconcile", property=property, new={"extra_code": extra_code, "drift": drift})
	return {"drift": drift}



# ─── extras added after booking (G-22) ───────────────────────────────────


@frappe.whitelist()
def addon_options(reservation: str):
	scope.require("reservation.modify", frappe.db.get_value("Reservation", reservation, "property"))
	from kamra.tex.services import addons as addon_svc

	return addon_svc.options(reservation, guest=False)


@frappe.whitelist(methods=["POST"])
def addon_propose(reservation: str, extras):
	prop = frappe.db.get_value("Reservation", reservation, "property")
	scope.require("reservation.modify", prop)
	from kamra.tex.services import addons as addon_svc

	p = addon_svc.propose(reservation, parse(extras, []), guest=False)
	if not scope.has_capability("price.view_cost", prop):
		p["addon"].pop("explanation", None)
		p["addon"].pop("fx_rates", None)
	return p


@frappe.whitelist(methods=["POST"])
@retry_on_deadlock
def addon_apply(proposal_token: str, reason: str | None = None):
	p = quoting.verify(proposal_token, kind="addon", allow_expired=True)       # the service checks freshness
	scope.require("reservation.modify", frappe.db.get_value("Reservation", p["reservation"], "property"))
	from kamra.tex.services import addons as addon_svc

	return addon_svc.apply(proposal_token, source="Desk", reason=text(reason, 500) or "Extras added", guest=False)
