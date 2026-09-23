"""Extras added to a booked stay (G-22, ADR-034): Frappe glue around ``pricing.addons``.

The guest (manage page) or staff pick extras for a reservation; they are priced on their
own with the extra revision on sale now and appended to the reservation's price. The stay
stays price-locked. Limited extras take their units under the day locks (G-19). The
booking's balance grows by the add-on; it is paid online (the manage page's Pay now) or at
the hotel, like any balance.
"""

from __future__ import annotations

import hashlib
import json

import frappe
from frappe import _
from frappe.utils import add_to_date, getdate, now_datetime

from kamra.tex.availability import extras_repository as xinv
from kamra.tex.commercial import context, contracts
from kamra.tex.money import D, from_db, to_str
from kamra.tex.pricing import addons, extras, serialize
from kamra.tex.pricing.model import ExtraRequest
from kamra.tex.security.audit import audit
from kamra.tex.services import booking as booking_svc
from kamra.tex.services import quoting

OPEN_STATUSES = ("Confirmed", "Pending Payment", "Held")     # not yet arrived, not cancelled
PROPOSAL_TTL_MINUTES = 30


def _snapshot(res) -> dict:
	if not res.tex_pricing_snapshot:
		frappe.throw(_("Reservation {0} was not priced by TEX; extras cannot be added here.").format(res.name))
	return json.loads(res.tex_pricing_snapshot)


def _open(res) -> None:
	if res.get("tex_pricing_source") == "Channel":
		frappe.throw(_("This booking came from a channel: its price is the channel's."))
	if res.status not in OPEN_STATUSES:
		frappe.throw(_("Extras can no longer be added to a {0} reservation.").format(_(res.status).lower()))


def _booked(snap: dict) -> dict[str, int]:
	"""Quantities of each extra the stay already has (its booking and earlier add-ons)."""
	out: dict[str, int] = {}
	for e in (snap.get("request") or {}).get("extras") or []:
		out[e["code"]] = out.get(e["code"], 0) + int(e.get("quantity") or 1)
	for a in snap.get("addons") or []:
		for e in a.get("requests") or []:
			out[e["code"]] = out.get(e["code"], 0) + int(e.get("quantity") or 1)
	return out


def _requests(raw) -> tuple[ExtraRequest, ...]:
	out = []
	for e in raw or []:
		code = str((e or {}).get("code") or "").strip().upper()
		qty = int((e or {}).get("quantity") or 1)
		if not code or qty < 1 or qty > 99:
			frappe.throw(_("Choose the extras and how many."))
		out.append(ExtraRequest(code, qty, tuple(sorted(getdate(d) for d in (e.get("service_dates") or [])))))
	return tuple(out)


def _catalog(res, guest: bool, at):
	# a guest adds what the hotel sells online after booking; staff anything on sale now
	return context.extras_catalog(res.property, online_only=guest, after_booking=guest, at=at)


def _fx(currencies, sell: str, property: str, at) -> dict:
	out = {}
	for ccy in sorted({c.upper() for c in currencies if c and c.upper() != sell}):
		try:
			out[ccy] = context.fx_snapshot(ccy, sell, property, at)
		except Exception:
			continue       # the extra (or levy) is then refused with the reason
	return out


def price(res, raw_requests, *, guest: bool):
	"""→ (AddonQuote, snapshot, requests). Priced now, on the booked stay as sold."""
	snap = _snapshot(res)
	req = serialize.request_from_dict(snap["request"])
	terms = contracts.load_terms(res.tex_contract_version)
	now = now_datetime()
	requests = _requests(raw_requests)
	catalog = _catalog(res, guest, now)
	sell = req.sell_currency.upper()
	taxes = context.tax_rules(res.property, req.room_type, at=now)
	q = addons.price_addons(
		terms=terms, request=req, requests=requests, catalog=catalog, today=now.date(), now=now,
		extra_fx=_fx((d.currency for d in catalog.values()), sell, res.property, now),
		tax_rules=taxes, tax_fx=_fx((r.currency for r in taxes if r.currency), sell, res.property, now),
		availability=xinv.availability(res.property, {r.code for r in requests}, req.check_in, req.check_out,
		                               exclude_reservation=None),
		booked=_booked(snap))
	return q, snap, requests


def options(reservation: str, *, guest: bool) -> dict:
	"""What can be added to a reservation now, with what is left of limited extras."""
	res = frappe.get_doc("Reservation", reservation)
	_open(res)
	snap = _snapshot(res)
	req = snap["request"]
	ci, co = getdate(req["check_in"]), getdate(req["check_out"])
	catalog = _catalog(res, guest, now_datetime())
	fields = ("extra_name", "category", "description", "image", "pricing_mode", "currency", "amount",
	          "max_quantity", "order_cutoff_hours")
	rows = {r.extra_code: r for r in context.listed_extras(res.property, online_only=guest, after_booking=guest,
	                                                       fields=fields)}
	avail = xinv.availability(res.property, set(catalog), ci, co)
	booked = _booked(snap)
	out = []
	for code, d in sorted(catalog.items(), key=lambda kv: (kv[1].category or "", kv[1].name or "")):
		if d.mandatory or (d.pricing_mode.value == "RESERVATION" and int(req.get("room_index") or 0) != 0):
			continue
		r = rows.get(code) or {}
		days = avail.get(code)
		out.append({
			"code": code, "name": d.name, "category": d.category, "description": r.get("description"),
			"image": r.get("image"), "pricing_mode": d.pricing_mode.value, "currency": d.currency,
			"amount": to_str(from_db(r.get("amount") or 0, d.currency)), "max_quantity": d.max_quantity,
			"booked": booked.get(code, 0), "cutoff_hours": d.cutoff_hours, "limited": days is not None,
			"days": ({str(k): ({"available": a.remaining > 0 and not a.closed,
			                    "low": 0 < a.remaining <= 3 and not a.closed} if guest else
			                   {"remaining": a.remaining, "closed": a.closed}) for k, a in days.items()}
			         if days is not None else None),
		})
	return {"reservation": res.name, "check_in": str(ci), "check_out": str(co), "currency": snap.get("currency"),
	        "extras": out}


def propose(reservation: str, raw_requests, *, guest: bool) -> dict:
	res = frappe.get_doc("Reservation", reservation)
	_open(res)
	q, snap, requests = price(res, raw_requests, guest=guest)
	old_total = D(snap["totals"]["total"])
	now = now_datetime()
	token = quoting.sign({
		"kind": "addon", "reservation": res.name, "modified": str(res.modified), "guest": guest,
		"requests": [{"code": r.code, "quantity": r.quantity, "service_dates": [str(d) for d in r.service_dates]}
		             for r in requests],
		"total": to_str(q.totals["total"]), "currency": q.currency,
		"exp": add_to_date(now, minutes=PROPOSAL_TTL_MINUTES).isoformat(),
	}) if q.ok else None
	return {"reservation": res.name, "ok": q.ok, "reasons": q.reasons, "addon": q.to_dict(internal=not guest),
	        "currency": q.currency, "old_total": to_str(old_total),
	        "new_total": to_str(old_total + q.totals["total"]) if q.ok else None, "proposal_token": token}


def apply(proposal_token: str, *, source: str, reason: str | None = None, guest: bool) -> dict:
	"""Add the proposed extras: re-priced under the reservation's lock and the extras' day
	locks, the price must not have moved; applying the same proposal twice adds them once."""
	# an expired token is still recognised as the add-on it already made (a lost response,
	# retried late): the replay is answered before freshness is required
	p = quoting.verify(proposal_token, kind="addon", allow_expired=True)
	if bool(p.get("guest")) != guest:
		frappe.throw(_("Invalid proposal."))
	addon_id = "ADD-" + hashlib.sha256(proposal_token.encode()).hexdigest()[:12]
	frappe.db.sql("SELECT name FROM `tabReservation` WHERE name=%s FOR UPDATE", p["reservation"])
	res = frappe.get_doc("Reservation", p["reservation"])
	snap = _snapshot(res)
	if any(a.get("id") == addon_id for a in snap.get("addons") or []):
		return _result(res, addon_id, replay=True)                 # the first response was lost
	quoting.require_fresh(p)
	_open(res)
	if str(res.modified) != p["modified"]:
		frappe.throw(_("The reservation changed since these extras were priced — please check them again."))
	q, snap, _unused = price(res, p["requests"], guest=guest)
	if not q.ok:
		msg = "; ".join(r["message"] for r in q.reasons)
		frappe.throw(extras.guest_reason(msg) if guest else msg)
	if to_str(q.totals["total"]) != p["total"]:
		frappe.throw(_("The price moved since these extras were priced — please check them again."))
	now = now_datetime()
	# limited extras: re-checked and taken under the day locks (G-19)
	block = q.to_dict(internal=True)
	priced = {"extras": block["extras"], "request": snap["request"]}
	trk = xinv.tracked(res.property)
	need = xinv.demand([priced], codes=set(trk))
	if need:
		xinv.lock_days(res.property, need)
		xinv.check(res.property, need, trk=trk)
		xinv.allocate(res.property, res.tex_booking, res.name, priced,
		              "Held" if res.status in ("Held", "Pending Payment") else "Confirmed", trk=trk)
	merged = addons.merge_addons(snap, block, addon_id=addon_id, at=str(now))
	merged["addons"][-1]["requests"] = p["requests"]
	merged["addons"][-1]["source"] = source
	old_total, new_total = D(snap["totals"]["total"]), D(merged["totals"]["total"])
	res.flags.tex_modification = True
	res.update({"tex_pricing_snapshot": json.dumps(merged, sort_keys=True, ensure_ascii=False),
	            **booking_svc.reservation_amounts(merged)})
	if guest:
		added = ", ".join(f"{o.name} ×{o.quantity.normalize()}" for o in q.outcomes)
		res.tex_guest_change_pending = 1
		res.tex_guest_change_note = f"Guest added extras online: {added} (+{to_str(q.totals['total'])} {q.currency})"
	res.save(ignore_permissions=True)
	booking_svc._record_revision(
		res.name, res.tex_booking, change_type="Extras", old_amount=old_total, new_amount=new_total,
		currency=q.currency, basis="ADD_ON", basis_sale_at=now, reason=reason or "Extras added",
		changes={"added": p["requests"], "addon": addon_id}, before=snap, after=merged, source=source)
	if res.tex_booking:
		booking_svc._refresh_booking_after_change(res.tex_booking)
		if guest:
			frappe.db.set_value("TEX Booking", res.tex_booking, "guest_change_pending", 1)
	audit("reservation.addon", reference_doctype="Reservation", reference_name=res.name, property=res.property,
	      new={"addon": addon_id, "extras": p["requests"], "total": to_str(q.totals["total"]),
	           "currency": q.currency}, source=source)
	return _result(res, addon_id)


def _result(res, addon_id: str, replay: bool = False) -> dict:
	res.reload()
	out = {"reservation": res.name, "addon": addon_id, "total": to_str(from_db(res.tex_total_amount, res.tex_currency)),
	       "currency": res.tex_currency, "replay": replay}
	if res.tex_booking:
		summary = booking_svc.booking_summary(res.tex_booking)
		out.update({"booking": res.tex_booking, "balance": summary["balance"],
		            "payment_status": summary.get("payment_status")})
	return out
