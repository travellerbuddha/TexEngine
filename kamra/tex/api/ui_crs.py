"""UI support endpoints for the TEX CRS, Call Center and Reservations screens.

Workstream B (docs/tex-engine/UI_WORKSTREAMS.md). Each endpoint fills one gap the
core CRS API (``kamra.tex.api.crs``) leaves for these screens and re-uses its
services and capability checks:

* ``search``         — ``crs.search`` plus the average nightly price of each offer,
                       so agents without ``price.view_cost`` (whose nightly lines are
                       stripped) still see a per-night figure.
* ``quote_summary``  — grand total and amount due now for a set of room quotes
                       before booking (the screens never add money up themselves).
* ``book``           — ``crs.book`` plus a booker who differs from the staying guest.
* ``reservation``    — ``crs.reservation`` plus the guest-facing nightly prices of
                       the locked pricing snapshot.

Money stays ``Decimal`` on the server and leaves as strings (ADR-003). Nothing here
prices a stay: per-night figures are the server's own totals divided by the nights
and rounded once, half-up, to the currency's minor unit.
"""

from __future__ import annotations

import json

import frappe
from frappe import _

from kamra.tex.api import crs
from kamra.tex.api._util import parse, text
from kamra.tex.money import ZERO, D, quantize, to_str
from kamra.tex.security import scope
from kamra.tex.services import booking as booking_svc
from kamra.tex.services import quoting


def _per_night(total, nights: int, currency: str) -> str | None:
	if total in (None, "") or nights < 1:
		return None
	return to_str(quantize(D(total) / nights, currency))


@frappe.whitelist()
def search(check_in: str, check_out: str, rooms, market: str, channel: str = "CALL_CENTER",
           properties=None, hotel_group: str | None = None, destination: str | None = None,
           currency: str | None = None, promo_codes=None):
	"""``crs.search`` (same arguments, same checks) with ``per_night`` on every offer
	and every room of an offer."""
	scope.require("price.view", None)
	res = crs.search(check_in=check_in, check_out=check_out, rooms=rooms, market=market, channel=channel,
	                 properties=properties, hotel_group=hotel_group, destination=destination, currency=currency,
	                 promo_codes=promo_codes)
	nights = int(res.get("nights") or 0)
	for p in res["properties"]:
		for group in ("offers", "unavailable"):
			for o in p[group]:
				o["per_night"] = _per_night(o.get("total"), nights, o["currency"])
				for r in o["rooms"]:
					q = r.get("quote") or {}
					r["per_night"] = _per_night((q.get("totals") or {}).get("total"), nights,
					                            q.get("currency") or o["currency"])
	return res


def _pay_at_hotel_allowed(result: dict) -> bool:
	# mirrors booking_svc.amount_due_now: the frozen payment policy decides
	policy = (result.get("rate_plan") or {}).get("payment_policy") or {"deposit_type": "FULL"}
	return bool(policy.get("allow_pay_at_hotel")) or policy.get("deposit_type") == "NONE"


@frappe.whitelist()
def quote_summary(quote_ids, payment_method: str | None = None):
	"""Server totals for the room quotes of one booking: grand total, amount due now for
	``payment_method`` (deposit rules of each rate plan) and whether every quote can
	still be booked."""
	ids = [str(q) for q in (parse(quote_ids, []) or [])]
	if not ids or len(ids) > quoting.MAX_ROOMS:
		frappe.throw(_("Select between 1 and {0} rooms.").format(quoting.MAX_ROOMS))
	method = text(payment_method, 40)
	loaded = [quoting.load_quote(qid) for qid in ids]
	props = {row.property for row, _req, _res in loaded}
	if len(props) != 1:
		frappe.throw(_("All rooms of a booking must be at the same hotel."))
	prop = props.pop()
	scope.require("reservation.create", prop)
	currencies = {result["currency"] for _row, _req, result in loaded}
	if len(currencies) != 1:
		frappe.throw(_("All rooms must share currency, market and channel."))
	ccy = currencies.pop()

	rooms = []
	total = ZERO
	due = ZERO
	due_known = True
	pay_at_hotel = True
	for row, req, result in loaded:
		room_total = D(result["totals"]["total"])
		total += room_total
		allowed = _pay_at_hotel_allowed(result)
		pay_at_hotel = pay_at_hotel and allowed
		policy = (result.get("rate_plan") or {}).get("payment_policy") or {}
		if method == "Pay at Hotel":
			room_due, kind = (ZERO, "Pay at Hotel") if allowed else (None, policy.get("deposit_type") or "FULL")
		else:
			room_due, kind = booking_svc.amount_due_now(result, method)
		if room_due is None:
			due_known = False
		else:
			due += room_due
		rooms.append({
			"quote_id": row.name, "room_type": req.get("room_type"), "total": to_str(room_total),
			"due_now": to_str(room_due) if room_due is not None else None, "deposit_type": kind,
			"payment_policy": policy.get("name"), "pay_at_hotel_allowed": allowed,
			"expires_at": str(row.expires_at), "problem": quoting.quote_is_usable(row),
		})
	return {
		"property": prop, "currency": ccy, "payment_method": method, "total": to_str(total),
		"due_now": to_str(due) if due_known else None,
		"balance_after": to_str(total - due) if due_known else None,
		"payment_required": bool(due_known and due > 0), "pay_at_hotel_allowed": pay_at_hotel,
		"usable": all(r["problem"] is None for r in rooms),
		"expires_at": min(r["expires_at"] for r in rooms), "rooms": rooms,
	}


def _booker(raw) -> dict | None:
	b = parse(raw, None)
	if not isinstance(b, dict):
		return None
	out = {"name": text(b.get("name"), 140), "email": text(b.get("email"), 140), "phone": text(b.get("phone"), 40)}
	if not any(out.values()):
		return None
	if out["email"]:
		out["email"] = out["email"].lower()
		if "@" not in out["email"]:
			frappe.throw(_("Invalid booker email address."))
	return out


@frappe.whitelist(methods=["POST"])
def book(quote_ids, guest, booker=None, payment_method: str | None = None, confirm_without_payment: int = 0,
         notes: str | None = None, idempotency_key: str | None = None, language: str | None = None):
	"""``crs.book`` with an optional ``booker`` ({name, email, phone}) — the person on the
	phone when they are not the staying guest (an assistant, a travel agent)."""
	ids = parse(quote_ids, [])
	if not ids:
		frappe.throw(_("Select at least one room."))
	prop = frappe.db.get_value("TEX Quote", ids[0], "property")
	scope.require("reservation.create", prop)
	out = booking_svc.create_booking(quote_ids=ids, guest=parse(guest, {}), booker=_booker(booker),
	                                 payment_method=text(payment_method, 40),
	                                 confirm_without_payment=bool(int(confirm_without_payment or 0)),
	                                 notes=text(notes, 2000), idempotency_key=text(idempotency_key, 140),
	                                 language=text(language, 10))
	# the guest's self-service token travels only to the guest, never to a staff screen
	out.pop("manage_token", None)
	return out


@frappe.whitelist()
def reservation(name: str):
	"""``crs.reservation`` (same checks) plus ``nightly``: the guest-facing price of each
	night of the locked snapshot, rounded as the guest's quote showed it."""
	out = crs.reservation(name)
	snap = json.loads(frappe.db.get_value("Reservation", name, "tex_pricing_snapshot") or "{}")
	ccy = out.get("currency") or snap.get("currency") or "EUR"
	out["nightly"] = [
		{"date": n.get("date"), "amount": to_str(quantize(D(n["final"] if "final" in n else n.get("amount")), ccy))}
		for n in snap.get("nights") or [] if n.get("date")
	]
	return out
