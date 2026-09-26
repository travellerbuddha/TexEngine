"""Booking service: quote(s) → TEX Booking + one Reservation per room (ADR-009).

The whole booking is one database transaction. Inventory nights of every room are
row-locked in a global order before availability is re-checked, so two guests
can never both get the last room (R-17). Each reservation stores the accepted
pricing snapshot and is price-locked (R-46); revision 1 records the original sale.
"""

from __future__ import annotations

import hashlib
import json
import secrets
from collections import defaultdict
from datetime import datetime

import frappe
from frappe import _
from frappe.utils import add_days, add_to_date, get_datetime, getdate, now_datetime

from kamra.tex.availability import extras_repository as xinv
from kamra.tex.availability import repository as avail
from kamra.tex.commercial import context as ctxmod
from kamra.tex.commercial import contracts
from kamra.tex.money import ZERO, D, db_dec, from_db, quantize, to_str
from kamra.tex.pricing import basket as basket_math
from kamra.tex.pricing import engine
from kamra.tex.pricing.enums import LineKind
from kamra.tex.pricing.explain import Explanation
from kamra.tex.pricing.model import RuleRef
from kamra.tex.security import scope
from kamra.tex.security.audit import audit, log_exception
from kamra.tex.security.capabilities import WEB_CHANNELS
from kamra.tex.services import holds, quoting

SOURCE_BY_CHANNEL = {"DIRECT_WEB": "Website", "CALL_CENTER": "Phone", "OTA": "OTA", "META": "Website"}
CREATED_VIA = {"DIRECT_WEB": "Booking Engine", "META": "Booking Engine", "CALL_CENTER": "Call Center",
               "API": "API", "B2B": "API"}


# ─── helpers ─────────────────────────────────────────────────────────────


def scoped_idempotency_key(raw: str | None, *, staff: bool, booking_site: str | None,
                           session_id: str | None) -> str | None:
	"""Idempotency keys are namespaced by who retries: a staff user, or a guest's
	booking-site session. A replay can therefore only ever return the caller's own
	booking — never a stranger's that happens to share the key."""
	raw = (raw or "").strip()[:140]
	if not raw:
		return None
	if staff:
		ns = f"user:{frappe.session.user}"
	else:
		ns = f"site:{booking_site or ''}:{hashlib.sha256((session_id or 'anon').encode()).hexdigest()[:24]}"
	return hashlib.sha256(f"{ns}|{raw}".encode()).hexdigest()


def token_hash(token: str) -> str:
	return hashlib.sha256(("tex-manage:" + token).encode()).hexdigest()


def new_manage_token() -> tuple[str, str]:
	token = secrets.token_urlsafe(32)
	return token, token_hash(token)


def _clean_guest(g: dict) -> dict:
	g = {k: (v.strip() if isinstance(v, str) else v) for k, v in (g or {}).items()}
	if not g.get("first_name"):
		frappe.throw(_("Guest first name is required."))
	if not g.get("last_name"):
		frappe.throw(_("Guest last name is required."))
	if not (g.get("email") or g.get("phone")):
		frappe.throw(_("An email or phone number is required."))
	if g.get("email"):
		g["email"] = g["email"].lower()
		if "@" not in g["email"] or len(g["email"]) > 140:
			frappe.throw(_("Invalid email address."))
	for f in ("first_name", "last_name"):
		if len(g[f]) > 80:
			frappe.throw(_("Name is too long."))
	return g


CONSENT_FIELDS = ("tex_consent_email", "tex_consent_sms", "tex_consent_whatsapp")


def find_or_create_guest(g: dict, *, property: str, market: str | None, language: str | None) -> str:
	"""The guest profile for a booking made on the guest's behalf (channels): no consent."""
	return resolve_guest({k: v for k, v in g.items() if not k.startswith("consent_")}, property=property,
	                     market=market, language=language, staff=False)[0]


def consent_given(value) -> bool:
	"""Whether a consent flag a caller sent says yes: only ``True``, ``1``, ``"1"`` or ``"true"`` (any
	case). ``"0"``, ``"false"``, ``"no"`` or anything else is no consent (ADR-056 review)."""
	if isinstance(value, bool):
		return value
	if isinstance(value, int):
		return value == 1
	return isinstance(value, str) and value.strip().lower() in ("1", "true")


def _find_profile(g: dict, enterprise: str | None, staff: bool, *, lock: bool = False) -> str | None:
	"""The profile a booking joins (``resolve_guest``): the e-mail's, when one is given; the phone's only
	for staff, for a booking without an e-mail or a profile without one, and only when exactly one
	profile of the enterprise (or of none) has it. The e-mail is the identity when given: another e-mail
	on a shared phone (a family, a colleague, a travel agent's number) is another person, never their
	stays or history (ADR-056 review). ``lock``: a locking read (the profile found is locked)."""
	tail = " FOR UPDATE" if lock else ""
	tenant = "(IFNULL(g.tex_enterprise, '') = '' OR g.tex_enterprise = %(ent)s)"
	if g.get("email"):
		found = frappe.db.sql(  # nosemgrep -- constant clauses, values bound
			f"""SELECT g.name FROM `tabGuest` g WHERE g.email = %(email)s AND {tenant}
			ORDER BY g.creation ASC, g.name ASC LIMIT 1{tail}""", {"email": g["email"], "ent": enterprise or ""}, pluck=True)
		if found:
			return found[0]
	if g.get("phone") and staff:
		no_email = "AND IFNULL(g.email, '') = ''" if g.get("email") else ""
		found = frappe.db.sql(  # nosemgrep -- constant clauses, values bound
			f"""SELECT g.name FROM `tabGuest` g WHERE g.phone = %(phone)s AND {tenant} {no_email}
			ORDER BY g.creation ASC, g.name ASC LIMIT 2{tail}""", {"phone": g["phone"], "ent": enterprise or ""},
			pluck=True)
		return found[0] if len(found) == 1 else None
	return None


def resolve_guest(g: dict, *, property: str, market: str | None, language: str | None,
                  staff: bool) -> tuple[str, list[str], list[str]]:
	"""→ (guest profile, consent granted now, consent asked for but not applied).

	Marketing consent is only ever granted explicitly, never implied (ADR-046). It is
	recorded on a profile this booking creates, and by staff who may edit guest profiles at
	the hotel (``crm.edit``): they took the guest's word and are accountable for it. Anyone
	else who types the e-mail or phone of an EXISTING profile (an anonymous booker, or staff
	who may only sell) does not change that profile's consent: the request is returned for the
	caller to keep on record, and the hotel confirms it on a verified channel (CRM). Nothing
	here ever withdraws consent.

	Which profile: the e-mail's, when one is given; the phone's only for a booking without an
	e-mail or a profile without one (ADR-056 review), only for staff (an anonymous booker's phone is
	not verified) and only when exactly one profile has it (a shared phone is nobody's identity:
	ADR-056 second review). Otherwise a new profile is made, which the CRM shows with its possible
	duplicates for staff to merge."""
	enterprise = frappe.db.get_value("Property", property, "tex_enterprise")
	from kamra.tex.crm.service import lock_guest

	existing = _find_profile(g, enterprise, staff)
	if existing and not lock_guest(existing):
		# merged into another profile (or removed) since this request began: this request's snapshot still
		# shows it, so look again with a lock, which reads what is committed now (third review of ADR-056)
		existing = _find_profile(g, enterprise, staff, lock=True)
	asked = [k for k in CONSENT_FIELDS if consent_given(g.get(k.replace("tex_", "")))]
	if existing:
		doc = frappe.get_doc("Guest", existing, for_update=True)      # as committed now (it is locked)
		changed = False
		for f, v in (("tex_enterprise", enterprise), ("tex_language", language), ("tex_market", market),
		             ("tex_country", g.get("country"))):
			if v and not doc.get(f):
				doc.set(f, v)
				changed = True
		new = [k for k in asked if not doc.get(k)]
		trusted = staff and scope.has_capability("crm.edit", property)
		if new and trusted:
			for k in new:
				doc.set(k, 1)
			doc.tex_consent_updated_at = now_datetime()
			doc.tex_consent_source = "booking (staff)"
			changed = True
		if changed:
			doc.flags.tex_consent_recorded = True        # with the booking (``_record_consent``)
			doc.save(ignore_permissions=True)
		return (doc.name, new, []) if trusted else (doc.name, [], new)
	doc = frappe.get_doc({
		"doctype": "Guest", "first_name": g["first_name"], "last_name": g["last_name"], "email": g.get("email"),
		"phone": g.get("phone"), "nationality": g.get("nationality"),
		"date_of_birth": g.get("date_of_birth") or None, "tex_enterprise": enterprise,
		"tex_language": language, "tex_market": market,
		"tex_country": g.get("country") if g.get("country") and frappe.db.exists("Country", g.get("country")) else None,
		**dict.fromkeys(asked, 1),
		**({"tex_consent_updated_at": now_datetime(),
		    "tex_consent_source": "booking (staff)" if staff else "booking"} if asked else {}),
	})
	doc.flags.tex_consent_recorded = True                # with the booking (``_record_consent``)
	doc.insert(ignore_permissions=True)
	return doc.name, asked, []


def _record_consent(guest: str, booking: str, property: str, granted: list[str], requested: list[str],
                    staff: bool) -> None:
	"""Consent given with a booking is on the guest's consent record (ADR-046); a request that
	was not applied is on it too, for the hotel to confirm on a verified channel."""
	if granted:
		audit("guest.consent", reference_doctype="Guest", reference_name=guest, property=property,
		      new={**dict.fromkeys(granted, True), "booking": booking}, reason="staff" if staff else "booking")
	if requested:
		audit("guest.consent_requested", reference_doctype="Guest", reference_name=guest, property=property,
		      new={**dict.fromkeys(requested, True), "booking": booking}, reason="booking")


def amount_due_now(result: dict, method: str | None) -> tuple[D, str]:
	"""Deposit due at booking from the frozen payment policy of the rate plan."""
	total = D(result["totals"]["total"])
	ccy = result["currency"]
	policy = (result.get("rate_plan") or {}).get("payment_policy") or {"deposit_type": "FULL"}
	if method == "Pay at Hotel":
		if not policy.get("allow_pay_at_hotel") and policy.get("deposit_type") not in ("NONE",):
			frappe.throw(_("This rate cannot be paid at the hotel."))
		return ZERO, "Pay at Hotel"
	kind = policy.get("deposit_type") or "FULL"
	v = D(policy.get("deposit_value"))
	if kind == "NONE":
		return ZERO, kind
	if kind == "PERCENT":
		return quantize(total * v / 100, ccy), kind
	if kind == "FIXED":
		return min(quantize(v, ccy), total), kind
	if kind == "NIGHTS":
		# N nights' share of the stay total (extras and taxes included proportionally)
		count = max(1, len(result.get("nights") or []))
		return min(quantize(total / count * int(v or 1), ccy), total), kind
	return total, "FULL"


def pay_at_hotel_allowed(result: dict) -> bool:
	# mirrors amount_due_now: the frozen payment policy decides
	policy = (result.get("rate_plan") or {}).get("payment_policy") or {"deposit_type": "FULL"}
	return bool(policy.get("allow_pay_at_hotel")) or policy.get("deposit_type") == "NONE"


def required_now(booking, override: dict | None = None) -> D:
	"""What the booking's payment terms require to be paid by now: each live room's
	``amount_due_now`` (its frozen payment policy, the booking's payment method), with
	``override`` ({reservation: priced result}) standing in for a room being changed, plus the
	cancellation fee of each cancelled room. A room whose rate cannot be paid at the hotel
	counts as paid by card (G-45)."""
	b = frappe.get_doc("TEX Booking", booking) if isinstance(booking, str) else booking
	ccy = b.currency or "EUR"
	method = b.payment_method
	total = ZERO
	for row in b.rooms:
		r = frappe.db.get_value("Reservation", row.reservation, ["status", "tex_pricing_snapshot", "cancellation_fee",
		                                                         "tex_total_amount"], as_dict=True)
		if not r:
			continue
		if r.status in ("Cancelled", "No Show"):
			total += from_db(r.cancellation_fee, ccy)
			continue
		result = (override or {}).get(row.reservation) or json.loads(r.tex_pricing_snapshot or "{}")
		if not (result.get("totals") or {}).get("total"):
			total += from_db(r.tex_total_amount, ccy)       # not priced by TEX: all of it
			continue
		m = method if method != "Pay at Hotel" or pay_at_hotel_allowed(result) else "Card"
		due, _kind = amount_due_now(result, m)
		total += due
	return quantize(total, ccy)


def quotes_summary(loaded: list[tuple], method: str | None) -> dict:
	"""Grand total and amount due now for ``method`` of the room quotes of one booking,
	with the same deposit rules ``create_booking`` applies. ``loaded`` is a list of
	``quoting.load_quote`` results (callers check access first)."""
	props = {row.property for row, _req, _res in loaded}
	if len(props) != 1:
		frappe.throw(_("All rooms of a booking must be at the same hotel."))
	keys = {(result["currency"], req.get("market"), req.get("channel")) for _row, req, result in loaded}
	if len(keys) != 1:
		frappe.throw(_("All rooms must share currency, market and channel."))
	ccy, market, channel = keys.pop()
	rooms = []
	total = ZERO
	due = ZERO
	due_known = True
	pay_at_hotel = True
	for row, req, result in loaded:
		room_total = D(result["totals"]["total"])
		total += room_total
		allowed = pay_at_hotel_allowed(result)
		pay_at_hotel = pay_at_hotel and allowed
		policy = (result.get("rate_plan") or {}).get("payment_policy") or {}
		if method == "Pay at Hotel":
			room_due, kind = (ZERO, "Pay at Hotel") if allowed else (None, policy.get("deposit_type") or "FULL")
		else:
			room_due, kind = amount_due_now(result, method)
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
		"property": row.property, "currency": ccy, "market": market, "channel": channel,
		"payment_method": method, "total": to_str(total),
		"due_now": to_str(due) if due_known else None,
		"balance_after": to_str(total - due) if due_known else None,
		"payment_required": bool(due_known and due > 0), "pay_at_hotel_allowed": pay_at_hotel,
		"usable": all(r["problem"] is None for r in rooms),
		"expires_at": min(r["expires_at"] for r in rooms), "rooms": rooms,
	}


def _record_revision(reservation: str, booking: str | None, *, change_type: str, old_amount, new_amount, currency,
                     basis: str, basis_sale_at=None, reason=None, changes=None, before=None, after=None,
                     source="Desk", approval="Not Required", override=None) -> str:
	no = (frappe.db.sql("SELECT MAX(revision_no) FROM `tabTEX Reservation Revision` WHERE reservation=%s",
	                    reservation)[0][0] or 0) + 1
	doc = frappe.get_doc({
		"doctype": "TEX Reservation Revision", "reservation": reservation, "booking": booking, "revision_no": no,
		"change_type": change_type, "source": source, "actor": frappe.session.user,
		"actor_roles": ", ".join(sorted(r for r in frappe.get_roles() if r not in ("All", "Guest"))),
		"approval_status": approval, "currency": currency, "old_amount": old_amount, "new_amount": new_amount,
		"difference": (D(new_amount) - D(old_amount)) if old_amount is not None and new_amount is not None else None,
		"pricing_basis": basis, "basis_sale_at": basis_sale_at, "reason": reason, "override_amount": override,
		"changes_json": json.dumps(changes or {}, default=str, sort_keys=True),
		"snapshot_before": json.dumps(before, default=str, sort_keys=True) if before else None,
		"snapshot_after": json.dumps(after, default=str, sort_keys=True) if after else None,
	})
	doc.insert(ignore_permissions=True)
	frappe.db.set_value("Reservation", reservation, "tex_revision_no", no, update_modified=False)
	return doc.name


def room_basket(result: dict) -> D:
	"""A priced room's basket (G-84): recorded with its price. A price recorded before G-84 has
	its accommodation before promotions and its extras — less the extras added after booking,
	which its totals include and a basket never counts (review L4)."""
	if result.get("basket") not in (None, ""):
		return D(result["basket"])
	t = result.get("totals") or {}
	added = sum((D(((a.get("quote") or {}).get("totals") or {}).get("extras")) for a in result.get("addons") or []
	             if isinstance(a, dict)), ZERO)
	return D(t.get("accommodation_gross")) + D(t.get("extras")) - added


def basket_terms(result: dict) -> list[dict]:
	"""The promotions with a minimum basket a priced room is eligible for (``engine.BasketTerm``).
	A price recorded before the G-84 review has none: a promotion it was granted, or refused for
	its basket, stands for one (with no forfeit recorded, so nothing is ever charged for it)."""
	if isinstance(result.get("minimum_baskets"), list):
		return result["minimum_baskets"]
	return [{"promo_id": p["promo_id"], "name": p.get("name"), "minimum": p.get("minimum") or "0",
	         "applied": bool(p.get("applied"))} for p in result.get("promotions") or []
	        if p.get("applied") or p.get("rule") == "MIN_BASKET"]


BASKET_NOT_TOGETHER = "The rooms of this booking were not priced together, and a promotion's minimum basket is " \
                      "judged on the whole booking. Please quote the rooms of this booking together again."


def check_booking_basket(rooms: list[tuple[dict, dict]]) -> None:
	"""G-84 (ADR-057): a minimum basket is the booking's, so a booking is sold only at the price
	its rooms have together. ``rooms``: (request, priced result) of each room.

	A room priced in a booking of several rooms (``quoting.create_quotes``) records that
	booking's basket and size: it is booked with rooms whose baskets add up to it, never with
	fewer or others. A room priced alone records none; in a booking of several rooms it is
	refused when a promotion its own basket missed (``rule`` MIN_BASKET) would qualify on the
	baskets of the booking's rooms that promotion covers (review M2): its rooms must be quoted
	together."""
	actual = sum((room_basket(result) for _req, result in rooms), ZERO)
	for req, _result in rooms:
		recorded = req.get("booking_basket")
		if recorded not in (None, "") and (D(recorded) != actual or int(req.get("booking_rooms") or 0) != len(rooms)):
			frappe.throw(_(BASKET_NOT_TOGETHER))
	if len(rooms) < 2:
		return
	covered = engine.eligible_baskets((room_basket(r), [t["promo_id"] for t in basket_terms(r)]) for _q, r in rooms)
	for req, result in rooms:
		if req.get("booking_basket") not in (None, ""):
			continue
		for p in result.get("promotions") or []:
			if not p.get("applied") and p.get("rule") == "MIN_BASKET" and p.get("minimum") not in (None, "") \
					and D(p["minimum"]) <= covered.get(p["promo_id"], (actual, 0))[0]:
				frappe.throw(_(BASKET_NOT_TOGETHER))


NOT_LIVE = ("Cancelled", "No Show")


def live_rooms(res, currency: str, *, live: bool = True) -> list[tuple[str, dict]]:
	"""The other live rooms of ``res``'s booking TEX priced in ``currency``, with their locked
	snapshots: what a change of ``res`` is judged with (G-84, ADR-057). A room a channel priced,
	or TEX did not price, counts for nothing. ``live=False``: the other rooms that are no longer
	live (cancelled, no-show) instead."""
	if not res.get("tex_booking"):
		return []
	rows = frappe.get_all("Reservation", filters={"tex_booking": res.tex_booking, "name": ("!=", res.name),
	                                              "status": ("not in" if live else "in", list(NOT_LIVE))},
	                      fields=["name", "tex_pricing_snapshot"], order_by="name asc")
	out = []
	for r in rows:
		snap = json.loads(r.tex_pricing_snapshot or "{}")
		if snap.get("contract") and snap.get("source") != "channel" and snap.get("currency") == currency:
			out.append((r.name, snap))
	return out


def booked_room(name: str, snap: dict) -> basket_math.BookedRoom:
	"""A priced room as the booking's basket sees it: its basket, its promotions with a minimum
	and what it carries for the other rooms (its ``basket_clawback``, review H1)."""
	carried = {e["promo_id"]: basket_math.Carried(D(e["amount"]), D(e.get("net") or e["amount"]), D(e.get("tax")))
	           for e in (snap.get("basket_clawback") or {}).get("promotions") or []}
	return basket_math.BookedRoom(name, room_basket(snap), tuple(basket_math.Term.from_dict(t)
	                                                            for t in basket_terms(snap)), carried)


def booking_others(res, currency: str) -> engine.BookingOthers:
	"""The other live rooms of ``res``'s booking as they are priced now (their locked snapshots):
	their baskets, and per promotion the baskets of those it covers (G-84 and its review M2)."""
	rooms = [booked_room(n, s) for n, s in live_rooms(res, currency)]
	return engine.BookingOthers(sum((r.basket for r in rooms), ZERO), len(rooms),
	                            engine.eligible_baskets((r.basket, [t.promo_id for t in r.terms]) for r in rooms))


def basket_clawback(res, new: dict | None, currency: str) -> basket_math.Clawback:
	"""What ``res`` carries for the other live rooms of its booking once it is priced as ``new``
	(a change), or cancelled (``new`` None): the discounts those rooms were granted only on the
	booking's basket and no longer earn, less what another room carries already (G-84 review H1,
	``basket.clawback``). The other rooms keep their locked price."""
	others = [booked_room(n, s) for n, s in live_rooms(res, currency)]
	# a cancelled room's charge carried its share for the others: it counts, its basket does not
	settled = [booked_room(n, s) for n, s in live_rooms(res, currency, live=False) if s.get("basket_clawback")]
	old = json.loads(res.tex_pricing_snapshot or "{}")
	before = booked_room(res.name, old) if old.get("contract") else None
	changed = booked_room(res.name, {k: v for k, v in new.items() if k != "basket_clawback"}) \
		if new is not None else None
	return basket_math.clawback(others, changed, currency, before=before, settled=settled)


CLAWBACK_CODE = "BASKET_CLAWBACK"


def carried(snap: dict) -> D:
	"""What a room's price carries for the other rooms of its booking (review H1)."""
	return D((snap.get("basket_clawback") or {}).get("amount"))


def with_clawback(q: dict, claw: basket_math.Clawback) -> dict:
	"""``q`` (a priced room, dict) carrying ``claw``: an explicit line before the taxes, its
	totals, an explanation step per promotion and the record (``basket_clawback``) the next change
	of any room of the booking reads. Unchanged when there is nothing to carry."""
	if not claw.promotions:
		return q
	q = dict(q)
	ccy = claw.currency
	lines = list(q.get("lines") or [])
	at = next((i for i, ln in enumerate(lines) if ln.get("kind") == "TAX"), len(lines))
	names = ", ".join(p["name"] for p in claw.promotions)
	text = (f"Minimum basket no longer reached ({names}): discount of the other rooms" if claw.amount > 0
	        else f"Minimum basket ({names}): charged on another room, credited")
	lines.insert(at, {"kind": LineKind.BASKET.value, "code": CLAWBACK_CODE, "description": text, "amount": to_str(claw.amount),
	                  "quantity": "1", "category": "ACCOMMODATION", "included": False, "ref": None})
	q["lines"] = lines
	t = dict(q.get("totals") or {})
	t["total"] = to_str(D(t.get("total")) + claw.amount)
	t["subtotal"] = to_str(D(t.get("subtotal")) + claw.net)
	t["tax_added"] = to_str(D(t.get("tax_added")) + claw.amount - claw.net)
	t["tax"] = to_str(D(t.get("tax")) + claw.tax)
	t["basket_clawback"] = to_str(claw.amount)
	if "margin" in t:                       # revenue of this room, before tax: the hotel's, like the discount was
		t["margin"] = to_str(D(t["margin"]) + claw.net)
	q["totals"] = t
	if isinstance(q.get("explanation"), list):
		ex = Explanation()
		for p in claw.promotions:
			ex.add("booking", CLAWBACK_CODE, "{text}", after=D(p["amount"]), currency=ccy, text=p["text"],
			       rule=RuleRef("promotion", p["promo_id"], None, "", p["name"]))
		q["explanation"] = [*q["explanation"], *ex.to_list()]
	q["basket_clawback"] = claw.to_dict()
	return q


def reservation_amounts(result: dict) -> dict:
	t = result["totals"]
	total = D(t["total"])
	tax = D(t["tax"])
	return {"amount_after_tax": total, "tax_amount": tax, "amount_before_tax": total - tax,
	        "discount_amount": D(t.get("discounts") or 0), "tex_total_amount": total,
	        "tex_extras_amount": D(t.get("extras") or 0), "tex_cost_amount": D(t.get("cost") or 0),
	        "tex_margin_amount": D(t.get("margin") or 0)}


# ─── create ──────────────────────────────────────────────────────────────


def create_booking(*, quote_ids: list[str], guest: dict, booker: dict | None = None, payment_method: str | None = None,
                   idempotency_key: str | None = None, notes: str | None = None, language: str | None = None,
                   booking_site: str | None = None, confirm_without_payment: bool = False,
                   session_id: str | None = None, source_tag: str | None = None) -> dict:
	staff = frappe.session.user != "Guest"
	key = scoped_idempotency_key(idempotency_key, staff=staff, booking_site=booking_site, session_id=session_id)
	if key:
		done = frappe.db.get_value("TEX Booking", {"idempotency_key": key}, ["name", "property"], as_dict=True)
		if done:
			if staff:
				scope.require("reservation.view", done.property)
			return booking_summary(done.name, replay=True)
	if not quote_ids:
		frappe.throw(_("Select at least one room."))
	if len(quote_ids) > quoting.MAX_ROOMS:
		frappe.throw(_("Too many rooms."))
	guest = _clean_guest(guest)
	now = now_datetime()

	rows = []
	for qid in quote_ids:
		row, req, result = quoting.load_quote(qid, for_update=True)
		problem = quoting.quote_is_usable(row)
		if problem:
			frappe.throw(problem)
		rows.append((row, req, result))
	props = {r[0].property for r in rows}
	if len(props) != 1:
		frappe.throw(_("All rooms of a booking must be at the same hotel."))
	# room 1 of the search carries the booking-level terms (per-booking extras, fixed
	# booking discounts), so it is booked exactly once, with rooms of the same search (ADR-029)
	indexes = [int(r[1].get("room_index") or 0) for r in rows]
	if indexes.count(0) != 1 or len(set(indexes)) != len(indexes):
		frappe.throw(_("The rooms of one booking must come from one search, including its first room. "
		               "Please search again."))
	rows.sort(key=lambda r: int(r[1].get("room_index") or 0))
	property = props.pop()
	currencies = {r[2]["currency"] for r in rows}
	markets = {r[1]["market"] for r in rows}
	channels = {r[1]["channel"] for r in rows}
	if len(currencies) != 1 or len(markets) != 1 or len(channels) != 1:
		frappe.throw(_("All rooms must share currency, market and channel."))
	currency, market, channel = currencies.pop(), markets.pop(), channels.pop()

	if booking_site or not staff:
		# a booking site sells on a web channel only, whoever books on it: a guest, or a signed-in
		# staff member at the price any guest gets there (ADR-050, review)
		if channel not in WEB_CHANNELS:
			frappe.throw(_("Not permitted."), frappe.PermissionError)
	if staff:
		scope.require("reservation.create", property)
		if not booking_site:
			# staff book on the channels their profiles may book on (ADR-050)
			scope.require_channel(channel, property, to="book")
	# a quote of a contract suspended since it was made no longer books (ADR-045); the shared
	# row lock makes a suspend wait for bookings in flight, and every booking after it see it
	for contract in sorted({r[2]["contract"]["contract"] for r in rows}):
		stopped = contracts.not_on_sale(contract, lock=True)
		if stopped:
			frappe.throw(str(stopped), stopped)

	# ── concurrency: lock every night of every room, then re-check under the lock ──
	avail.lock_nights(property, [(r[1]["room_type"], getdate(r[1]["check_in"]), getdate(r[1]["check_out"]))
	                             for r in rows])
	# demand per (inventory pool, night) across ALL rooms of this booking, so rooms with
	# different but overlapping dates are counted against each other
	need: dict[tuple, int] = defaultdict(int)
	for _row, req, _result in rows:
		pool = avail.pool_of(req["room_type"])[0]
		for night in avail.nights(getdate(req["check_in"]), getdate(req["check_out"])):
			need[(pool, night)] += 1
	for _row, req, result in rows:
		pool = avail.pool_of(req["room_type"])[0]
		_count, per_day = avail.stay_availability(property, req["room_type"], result["contract"]["contract"],
		                                          getdate(req["check_in"]), getdate(req["check_out"]), now.date(),
		                                          locking=True)
		for d in per_day:
			if d.available < need[(pool, d.day)]:
				frappe.throw(_("Sorry — {0} has just sold out for {1}.").format(
					frappe.db.get_value("Room Type", req["room_type"], "room_type_name") or req["room_type"],
					d.day.isoformat()), title=_("Sold out"))
	cells = avail.restriction_cells(property, min(getdate(r[1]["check_in"]) for r in rows),
	                                max(getdate(r[1]["check_out"]) for r in rows))
	for _row, req, result in rows:
		sc = avail.scope_for(req["room_type"], result["contract"]["contract"], market, req.get("rate_plan"), channel)
		v = avail.check_restrictions(property, sc, getdate(req["check_in"]), getdate(req["check_out"]), now.date(),
		                             cells)
		if v:
			frappe.throw(_("This stay is no longer bookable: {0}").format(v[0].message))
	check_booking_basket([(req, result) for _row, req, result in rows])

	# ── limited extras: every room's units together, re-checked under the day locks (G-19) ──
	extras_tracked = xinv.tracked(property)
	extras_need = xinv.demand([r[2] for r in rows], codes=set(extras_tracked))
	if extras_need:
		xinv.lock_days(property, extras_need)
		xinv.check(property, extras_need, trk=extras_tracked)

	# ── money ──
	total = sum((D(r[2]["totals"]["total"]) for r in rows), ZERO)
	due_now = ZERO
	for _row, _req, result in rows:
		d, _kind = amount_due_now(result, payment_method)
		due_now += d
	if staff and confirm_without_payment and due_now > 0:
		# confirming before the deposit arrives is a credit decision, not an agent default
		scope.require("reservation.confirm_unpaid", property)
	confirm = due_now == 0 or (staff and confirm_without_payment)
	status = "Confirmed" if confirm else "Pending Payment"
	# how long the rooms wait for the payment: by payment method and hotel (K-2d)
	hold_until = None if confirm else add_to_date(now, minutes=holds.resolve_hold_minutes(property, payment_method))
	guest_name, consent_granted, consent_requested = resolve_guest(guest, property=property, market=market,
	                                                               language=language, staff=staff)
	booker = booker or {}
	token, token_digest = new_manage_token()
	manage_days = int(frappe.db.get_single_value("TEX Settings", "manage_link_days") or 365)

	booking = frappe.get_doc({
		"doctype": "TEX Booking", "property": property, "status": status, "sales_channel": channel,
		# staff hands are "Desk" on the web channel, including on a booking site (reportable, audited below)
		"market": market, "created_via": "Desk" if staff and (booking_site or channel == "DIRECT_WEB")
		else CREATED_VIA.get(channel, "Desk"), "sale_at": now, "booker_guest": guest_name,
		"booker_name": booker.get("name") or f"{guest['first_name']} {guest['last_name']}",
		"booker_email": booker.get("email") or guest.get("email"),
		"booker_phone": booker.get("phone") or guest.get("phone"), "language": language, "currency": currency,
		"total_amount": total, "paid_amount": 0, "balance_amount": total, "amount_due_now": due_now,
		"payment_status": "Pay at Hotel" if payment_method == "Pay at Hotel" else "Unpaid",
		"payment_method": payment_method, "notes": (notes or "")[:2000], "source": (source_tag or "")[:140],
		"idempotency_key": key, "manage_token_hash": token_digest,
		"manage_token_expires": add_days(getdate(max(getdate(r[1]["check_out"]) for r in rows)), manage_days),
		"booking_site": booking_site,
	})
	booking.insert(ignore_permissions=True)
	if staff and booking_site:
		# a signed-in staff member booked on a public booking site, at the web price any guest gets
		# there: allowed, and reportable (created via Desk, owner, this event) (ADR-050 review)
		audit("booking.staff_on_site", reference_doctype="TEX Booking", reference_name=booking.name,
		      property=property, new={"booking_site": booking_site, "channel": channel, "total": to_str(total),
		                              "currency": currency})
	_record_consent(guest_name, booking.name, property, consent_granted, consent_requested, staff)

	reservations = []
	sold: list[tuple[dict, str]] = []
	for idx, (row, req, result) in enumerate(rows):
		amounts = reservation_amounts(result)
		kids = req.get("children") or []
		# the price-locked snapshot: the quote's result, when it was priced (the quote's sale time,
		# G-73) and when it was accepted; its contract terms stay a reference to the version's frozen
		# payload by version and hash (ADR-058)
		priced = get_datetime(result["request"]["sale_at"])
		snapshot = {**result, "accepted_at": str(now), "priced_at": str(priced), "quote_id": row.name}
		res = frappe.get_doc({
			"doctype": "Reservation", "property": property, "guest": guest_name, "room_type": req["room_type"],
			"check_in_date": req["check_in"], "check_out_date": req["check_out"], "adults": int(req["adults"]),
			"children": len(kids), "status": status, "source": SOURCE_BY_CHANNEL.get(channel, "Manual"),
			"channel": channel, "auto_price": 0, "rate_plan": req.get("rate_plan"),
			"special_requests": (guest.get("special_requests") or "")[:1000] if idx == 0 else None,
			"hold_expires_on": hold_until, "idempotency_key": f"{key}:{idx}" if key else None,
			"is_pay_at_hotel": 1 if payment_method == "Pay at Hotel" else 0,
			"tex_booking": booking.name, "tex_room_index": idx + 1,
			"tex_contract": result["contract"]["contract"], "tex_contract_version": result["contract"]["version"],
			"tex_payload_hash": result["contract"]["payload_hash"], "tex_market": market,
			"tex_sales_channel": channel, "tex_board": req["board"], "tex_child_ages": json.dumps(kids),
			"tex_pricing_source": "TEX", "tex_price_locked": 1, "tex_locked_at": now, "tex_sale_at": now,
			"tex_accepted_at": now, "tex_quote": row.name, "tex_currency": currency,
			# informational, at the column's 9 places; the snapshot holds the exact rate (G-72)
			"tex_fx_rate": db_dec((result.get("fx") or {}).get("sell_rate") or 1),
			# the promotions of the selling price: a cost-stage offer is a cost figure (ADR-059 review)
			"tex_promotions": ", ".join(p["promo_id"] for p in quoting.sold_promotions(result)),
			"tex_pricing_snapshot": json.dumps(snapshot, sort_keys=True, ensure_ascii=False),
			**amounts,
		})
		res.flags.ignore_permissions = True
		# its nights were locked and recounted for its contract above (ADR-048)
		res.flags.tex_inventory_checked = True
		# a TEX sale: the only way a TEX hotel's reservation is created, besides a channel's sale
		# and a migration import (ADR-052); the controller pops it on this insert
		res.flags.tex_sale = True
		res.insert(ignore_permissions=True)
		reservations.append(res.name)
		booking.append("rooms", {"reservation": res.name, "room_type": req["room_type"], "check_in": req["check_in"],
		                         "check_out": req["check_out"], "adults": int(req["adults"]), "children": len(kids),
		                         "amount": amounts["amount_after_tax"], "status": status, "quote": row.name})
		sold.append((result, res.name))
		if extras_need:
			xinv.allocate(property, booking.name, res.name, result, "Confirmed" if confirm else "Held",
			              trk=extras_tracked)
		q = frappe.get_doc("TEX Quote", row.name)
		q.status = "Used"
		q.booking = booking.name
		q.save(ignore_permissions=True)
		# the Original revision keeps the same record; its basis priced it at the quote's sale time
		_record_revision(res.name, booking.name, change_type="Original", old_amount=None,
		                 new_amount=amounts["amount_after_tax"], currency=currency, basis="CURRENT",
		                 basis_sale_at=priced, after=snapshot, source="Guest" if not staff else "Desk")
	_record_redemptions(sold, booking.name, property, guest.get("email") or guest.get("phone"), committed=confirm)
	booking.save(ignore_permissions=True)
	audit("booking.create", reference_doctype="TEX Booking", reference_name=booking.name, property=property,
	      new={"reservations": reservations, "total": to_str(total), "currency": currency, "status": status,
	           "channel": channel})
	out = booking_summary(booking.name)
	out["manage_token"] = token
	from kamra.tex.services import notify

	notify.booking_created(booking.name, token)
	return out


def _record_redemptions(rooms: list[tuple[dict, str]], booking: str, property: str, guest_ident: str | None,
                        *, committed: bool) -> None:
	"""One redemption per promotion per booking (G-06): a code used on a 3-room booking is
	one use of the code; the amount is the discount over all rooms."""
	gkey = ctxmod.guest_key(guest_ident if guest_ident and "@" in guest_ident else None,
	                        guest_ident if guest_ident and "@" not in guest_ident else None)
	currency = rooms[0][0]["currency"] if rooms else None
	used = _promotions_used(rooms)
	for root in sorted(used):
		if not frappe.db.exists("TEX Promotion", root):
			continue
		_check_redemption_limits(root, used[root]["promo"]["name"], gkey)
		_insert_redemption(root, used[root], booking=booking, property=property, gkey=gkey, currency=currency,
		                   committed=committed)


def _promotions_used(rooms: list[tuple[dict, str]]) -> dict[str, dict]:
	"""promotion → {promo, reservation (first room it applied to), discount over all rooms}:
	the limited promotions (codes and managed promotions) a booking's rooms carry."""
	used: dict[str, dict] = {}
	for result, reservation in rooms:
		for p in result.get("promotions") or []:
			if not p["applied"] or not (p.get("code") or p["source"].startswith("promotion:")):
				continue
			entry = used.setdefault(p["promo_id"], {"promo": p, "reservation": reservation, "discount": ZERO})
			entry["discount"] += D(p.get("discount") or 0)
	return used


def _insert_redemption(root: str, entry: dict, *, booking: str, property: str, gkey: str | None, currency,
                       committed: bool) -> None:
	frappe.get_doc({"doctype": "TEX Promotion Redemption", "promotion": root, "code": entry["promo"].get("code"),
	                "property": property, "status": "Committed" if committed else "Reserved",
	                "booking": booking, "reservation": entry["reservation"], "guest_key": gkey,
	                "amount": entry["discount"], "currency": currency}).insert(ignore_permissions=True)
	frappe.db.sql("UPDATE `tabTEX Promotion` SET times_redeemed = IFNULL(times_redeemed, 0) + 1 WHERE name=%s", root)


def booking_guest_key(booking: str | None, guest: str | None = None) -> str | None:
	"""The per-guest coupon key of a booking: the one its redemptions carry, else its guest's."""
	if booking:
		key = frappe.db.get_value("TEX Promotion Redemption", {"booking": booking, "guest_key": ("is", "set")},
		                          "guest_key")
		if key:
			return key
	if not guest:
		return None
	email, phone = frappe.db.get_value("Guest", guest, ["email", "phone"]) or (None, None)
	return ctxmod.guest_key(email or None, None if email else phone)


def sync_redemptions(booking: str) -> None:
	"""After a modification (G-09): the booking's redemptions follow the promotions its live
	rooms now carry — a promotion added is recorded under its limits, one dropped is released."""
	b = frappe.get_doc("TEX Booking", booking)
	rooms = []
	for row in b.rooms:
		r = frappe.db.get_value("Reservation", row.reservation, ["status", "tex_pricing_snapshot"], as_dict=True)
		if r and r.status not in ("Cancelled", "No Show") and r.tex_pricing_snapshot:
			rooms.append((json.loads(r.tex_pricing_snapshot), row.reservation))
	used = _promotions_used(rooms)
	existing = {r.promotion: r for r in frappe.get_all(
		"TEX Promotion Redemption", filters={"booking": booking, "status": ("in", ["Reserved", "Committed"])},
		fields=["name", "promotion"])}
	gkey = booking_guest_key(booking, b.booker_guest)
	for root in sorted(used):
		if root in existing:
			frappe.db.set_value("TEX Promotion Redemption", existing[root].name, "amount", used[root]["discount"])
			continue
		if not frappe.db.exists("TEX Promotion", root):
			continue
		_check_redemption_limits(root, used[root]["promo"]["name"], gkey, exclude_booking=booking)
		_insert_redemption(root, used[root], booking=booking, property=b.property, gkey=gkey, currency=b.currency,
		                   committed=b.status not in ("Pending Payment", "Held"))
	for root, red in existing.items():
		if root not in used:
			doc = frappe.get_doc("TEX Promotion Redemption", red.name)
			doc.status = "Released"
			doc.save(ignore_permissions=True)


def _check_redemption_limits(root: str, name: str, gkey: str | None, *, exclude_booking: str | None = None) -> None:
	"""Under a row lock on the promotion (concurrent bookings cannot exceed a limit): the
	total usage limit and the per-guest limit (G-07). Redemptions of ``exclude_booking``
	(a booking being modified) are not counted against it."""
	limit, per_guest = frappe.db.sql("""SELECT usage_limit, per_guest_limit FROM `tabTEX Promotion`
	                                     WHERE name=%s FOR UPDATE""", root)[0]

	def used(guest_key: str | None = None) -> int:
		# a locking read: under REPEATABLE READ a plain count still sees this transaction's
		# snapshot, taken before a competing booking committed its redemption, and the limit
		# would be exceeded (two simultaneous bookings both used a code limited to one)
		return int(frappe.db.sql(
			"""SELECT COUNT(*) FROM `tabTEX Promotion Redemption`
			   WHERE promotion=%(p)s AND status IN ('Reserved', 'Committed')"""
			+ (" AND IFNULL(booking, '') != %(ex)s" if exclude_booking else "")
			+ (" AND guest_key=%(g)s" if guest_key else "") + " LOCK IN SHARE MODE",
			{"p": root, "ex": exclude_booking, "g": guest_key})[0][0])

	if limit and used() >= int(limit):
		frappe.throw(_("Promotion {0} has just been fully redeemed.").format(name))
	if per_guest:
		if not gkey:
			frappe.throw(_("Promotion {0} needs the guest's e-mail address or phone number.").format(name))
		if used(gkey) >= int(per_guest):
			frappe.throw(_("Promotion {0} has already been used by this guest.").format(name))


# ─── confirm / payments ──────────────────────────────────────────────────


class RoomsNotHeld(frappe.ValidationError):
	"""A booking whose rooms are not all held for it is never confirmed (K-2b)."""


def cancelled_on_purpose(reservation: str) -> bool:
	"""A room the guest or staff cancelled (it has its Cancellation revision): it left its booking.
	A room released without one (an expired hold) was taken from it."""
	return bool(frappe.db.exists("TEX Reservation Revision", {"reservation": reservation,
	                                                         "change_type": "Cancellation"}))


def rooms_not_held(b) -> list[str]:
	"""The rooms of booking ``b`` that hold no inventory for it any more, read under their row
	locks in name order (after the booking's lock: the order every TEX booking change takes). A
	room cancelled on purpose is no longer part of the booking, so it is not missing (B1)."""
	names = sorted(r.reservation for r in b.rooms)
	states = {n: frappe.db.get_value("Reservation", n, "status", for_update=True) for n in names}
	return [n for n, st in states.items() if st not in (*holds.HOLDING, "Confirmed")
	        and not (st == "Cancelled" and cancelled_on_purpose(n))]


def confirm_booking(booking: str, *, reason: str | None = None) -> None:
	"""Confirm a booking waiting for its payment, under its lock and its rooms' locks. A booking
	whose rooms are not all held for it (released, or sold to someone else since) is never
	confirmed and nothing is sent (``RoomsNotHeld``, K-2b)."""
	b = frappe.get_doc("TEX Booking", booking, for_update=True)
	if b.status == "Confirmed":
		return
	if b.status not in ("Pending Payment", "Held"):
		frappe.throw(_("Booking {0} cannot be confirmed from {1}.").format(booking, b.status))
	gone = rooms_not_held(b)
	if gone:
		raise RoomsNotHeld(_("Booking {0} cannot be confirmed: its rooms {1} are no longer held for it.").format(
			booking, ", ".join(gone)))
	now = now_datetime()
	frappe.flags.kamra_status_transition = True
	try:
		for row in b.rooms:
			res = frappe.get_doc("Reservation", row.reservation, for_update=True)
			if res.status in ("Pending Payment", "Held"):
				res.status = "Confirmed"
				res.hold_expires_on = None
				res.tex_price_locked = 1
				res.tex_locked_at = now
				res.flags.tex_modification = True
				res.save(ignore_permissions=True)
			row.status = res.status          # a room cancelled before the payment stays cancelled (B1)
	finally:
		frappe.flags.kamra_status_transition = False
	xinv.confirm(booking)            # held extras units become confirmed (G-19)
	for r in frappe.get_all("TEX Promotion Redemption", filters={"booking": booking, "status": "Reserved"},
	                        pluck="name"):
		d = frappe.get_doc("TEX Promotion Redemption", r)
		d.status = "Committed"
		d.save(ignore_permissions=True)
	# a booking one of whose rooms was cancelled before its payment is confirmed with the rest (B1)
	b.status = "Partially Cancelled" if any(r.status == "Cancelled" for r in b.rooms) else "Confirmed"
	b.save(ignore_permissions=True)
	audit("booking.confirm", reference_doctype="TEX Booking", reference_name=booking, property=b.property,
	      reason=reason)
	from kamra.tex.services import notify

	notify.booking_confirmed(booking)


def apply_payment(booking: str, amount, *, reference: str | None = None) -> dict:
	"""Record money received against a booking (called by the payments service).
	The booking row is locked so concurrent allocations never lose an update."""
	# a locking read: the booking as it is now, not as this request's snapshot saw it before
	# it waited for the lock (a stale copy would lose the other payment's amount)
	b = frappe.get_doc("TEX Booking", booking, for_update=True)
	amount = D(amount)
	paid = from_db(b.paid_amount, b.currency) + amount
	total = from_db(b.total_amount, b.currency)
	b.paid_amount = paid
	b.balance_amount = total - paid
	b.payment_status = "Paid" if paid >= total else ("Partially Paid" if paid > 0 else "Unpaid")
	b.save(ignore_permissions=True)
	if b.status in ("Pending Payment", "Held") and paid >= from_db(b.amount_due_now, b.currency):
		confirm_booking(booking, reason=f"payment {reference or ''}".strip())
	return booking_summary(booking)


# ─── cancel ──────────────────────────────────────────────────────────────


def cancellation_penalty(reservation, today=None, *, basket: bool = True) -> tuple[D, dict]:
	"""What cancelling the room costs now: the rate's cancellation terms on the room's own price
	and — ``basket`` — what the room carries for the other rooms of its booking once it is gone
	(``basket_clawback``: the discount they keep but no longer earn; review H1), explained in the
	basis. A room that carried such a discount for the others passes it on, or has it credited when
	it is no longer owed; the charge is then below the rate's penalty, and may be a credit."""
	pen, basis = _policy_penalty(reservation, today)
	snap = json.loads(reservation.tex_pricing_snapshot or "{}")
	if basket and snap.get("contract") and reservation.get("tex_booking") and snap.get("source") != "channel":
		ccy = reservation.tex_currency or snap.get("currency") or "EUR"
		claw = basket_clawback(reservation, None, ccy)
		if claw.promotions:
			pen = quantize(pen + claw.amount, ccy)
			basis = {**basis, "basket_clawback": claw.to_dict()}
	return pen, basis


def _policy_penalty(reservation, today=None) -> tuple[D, dict]:
	snap = json.loads(reservation.tex_pricing_snapshot or "{}")
	if not snap:
		# a stay TEX did not price (imported, legacy): the hotel's own policy on its locked
		# amount (ADR-052 review M2), never "no policy"
		from kamra.tex.legacy import hotel_policy_penalty

		return hotel_policy_penalty(reservation, today)
	ccy = reservation.tex_currency or snap.get("currency") or "EUR"
	# the room's own price: what it carries for the other rooms is settled by ``basket_clawback``
	total = from_db(reservation.tex_total_amount or reservation.amount_after_tax, ccy) - carried(snap)
	rp = snap.get("rate_plan") or {}
	policy = rp.get("cancellation_policy")
	today = getdate(today or now_datetime())
	days = (getdate(reservation.check_in_date) - today).days
	if rp and not rp.get("refundable", True):
		return quantize(total, ccy), {"rule": "non-refundable", "days_before": days}
	if not policy:
		return quantize(ZERO, ccy), {"rule": "no policy (free cancellation)", "days_before": days}
	applicable = [r for r in policy.get("rules") or [] if days < int(r["days_before_arrival"])]
	if not applicable:
		return quantize(ZERO, ccy), {"rule": "free cancellation window", "days_before": days}
	rule = min(applicable, key=lambda r: int(r["days_before_arrival"]))
	v = D(rule["penalty_value"])
	if rule["penalty_type"] == "PERCENT":
		pen = total * v / 100
	elif rule["penalty_type"] == "NIGHTS":
		pen = total / max(1, len(snap.get("nights") or [1])) * v
	else:
		pen = v
	return quantize(min(pen, total), ccy), {"rule": rule, "days_before": days}


def cancel_reservation(reservation: str, *, reason: str, waive_penalty: bool = False,
                       source: str = "Desk", _guest_authorized: bool = False) -> dict:
	"""``_guest_authorized`` is set only by the self-service API after it verified the
	guest's manage token for this exact reservation; staff calls always check scope.

	Locks the booking, then the reservation (then the guest's change requests): the order every
	change to a TEX booking takes (review of ADR-044)."""
	res = frappe.get_doc("Reservation", reservation)
	if res.tex_booking:
		frappe.db.get_value("TEX Booking", res.tex_booking, "name", for_update=True)
		res = frappe.get_doc("Reservation", reservation, for_update=True)
	if not _guest_authorized:
		scope.require("reservation.cancel", res.property)
	elif waive_penalty:
		frappe.throw(_("Guests cannot waive cancellation fees."), frappe.PermissionError)
	if res.status in ("Cancelled", "No Show", "Checked Out"):
		frappe.throw(_("Reservation {0} is already {1}.").format(reservation, res.status))
	if not (reason or "").strip():
		frappe.throw(_("A cancellation reason is required."))
	penalty, basis = cancellation_penalty(res)
	claw = basis.get("basket_clawback")
	if waive_penalty:
		# the rate's penalty is waived; what the room carries for the other rooms is the price of
		# the discount they keep, not a penalty (G-84 review H1)
		scope.require("price.override", res.property)
		penalty = D(claw["amount"]) if claw else ZERO
	old_amount = from_db(res.tex_total_amount or res.amount_after_tax, res.tex_currency or "EUR")
	snap = json.loads(res.tex_pricing_snapshot or "{}")
	if claw or snap.get("basket_clawback"):
		# what the room carries for the others is now its cancellation charge's: the next change of
		# any room of the booking reads it there (G-84 review H1)
		if claw:
			snap["basket_clawback"] = claw
		else:
			snap.pop("basket_clawback", None)
		res.tex_pricing_snapshot = json.dumps(snap, sort_keys=True, ensure_ascii=False)
	frappe.flags.kamra_cancelling = True
	frappe.flags.kamra_status_transition = True
	try:
		res.status = "Cancelled"
		res.cancellation_reason = "Other"
		res.cancellation_note = reason[:500]
		res.cancellation_fee = penalty
		res.cancelled_on = now_datetime()
		res.flags.tex_modification = True
		res.save(ignore_permissions=True)
	finally:
		frappe.flags.kamra_cancelling = False
		frappe.flags.kamra_status_transition = False
	_record_revision(res.name, res.tex_booking, change_type="Cancellation", old_amount=old_amount,
	                 new_amount=penalty, currency=res.tex_currency, basis="NONE", reason=reason,
	                 changes={"status": [res.get_doc_before_save().status if res.get_doc_before_save() else None,
	                                     "Cancelled"], "penalty": to_str(penalty), "policy": basis},
	                 source=source)
	if claw:
		audit("reservation.basket_clawback", reference_doctype="Reservation", reference_name=res.name,
		      property=res.property, new=claw, reason=reason)
	if res.tex_booking:
		_refresh_booking_after_change(res.tex_booking)
	# a guest's change still waiting for this room is void; a payment of it arriving later is
	# refunded (G-45)
	from kamra.tex.services import guest_changes

	guest_changes.close_open(res.name, f"the room was cancelled ({source})")
	audit("reservation.cancel", reference_doctype="Reservation", reference_name=res.name, property=res.property,
	      new={"penalty": to_str(penalty), "waived": bool(waive_penalty), "basis": basis}, reason=reason)
	return {"reservation": res.name, "penalty": to_str(penalty), "currency": res.tex_currency, "basis": basis}


def _refresh_booking_after_change(booking: str) -> None:
	b = frappe.get_doc("TEX Booking", booking)
	ccy = b.currency or "EUR"
	total = ZERO
	statuses = []
	for row in b.rooms:
		r = frappe.db.get_value("Reservation", row.reservation,
		                        ["status", "tex_total_amount", "cancellation_fee", "check_in_date", "check_out_date",
		                         "adults", "children", "room_type"], as_dict=True)
		statuses.append(r.status)
		amount = from_db(r.cancellation_fee if r.status == "Cancelled" else r.tex_total_amount, ccy)
		total += amount
		row.status, row.amount = r.status, amount
		row.check_in, row.check_out, row.adults, row.children, row.room_type = (
			r.check_in_date, r.check_out_date, r.adults, r.children, r.room_type)
	b.total_amount = total
	b.balance_amount = total - from_db(b.paid_amount, ccy)
	if all(s == "Cancelled" for s in statuses):
		b.status = "Cancelled"
		for red in frappe.get_all("TEX Promotion Redemption", filters={"booking": booking,
		                                                               "status": ("in", ["Reserved", "Committed"])},
		                          pluck="name"):
			d = frappe.get_doc("TEX Promotion Redemption", red)
			d.status = "Released"
			d.save(ignore_permissions=True)
	elif any(s == "Cancelled" for s in statuses):
		if b.status in holds.HOLDING and all(s in holds.HOLDING for s in statuses if s != "Cancelled"):
			# never confirmed: it keeps waiting for its payment with the rooms it has left, which
			# expire with its hold or are confirmed by its payment, never asking more than it costs (B1)
			b.amount_due_now = min(from_db(b.amount_due_now, ccy), total)
		else:
			b.status = "Partially Cancelled"
	paid = from_db(b.paid_amount, ccy)
	b.payment_status = "Paid" if paid >= total and total > 0 else ("Partially Paid" if paid > 0 else b.payment_status)
	b.save(ignore_permissions=True)


def resend_confirmation(booking: str) -> dict:
	"""Queue the booking e-mail again with a NEW manage link (only a hash of the old one
	exists, so it cannot be re-sent; the old link stops working).

	Reports what happened, never more (ADR-047): ``queued`` when the e-mail queue took the
	message (``status`` "Queued"; the guest's timeline later shows Sent or Failed), else
	``status`` "Failed" (e.g. no outgoing e-mail account)."""
	from kamra.tex.services import notify

	b = frappe.get_doc("TEX Booking", booking)
	scope.require("reservation.modify", b.property)
	if b.status == "Cancelled":
		frappe.throw(_("This booking is cancelled."))
	if not b.booker_email:
		frappe.throw(_("This booking has no e-mail address."))
	token, digest = new_manage_token()
	b.manage_token_hash = digest
	b.save(ignore_permissions=True)
	mail = notify.booking_mail(b.name, token)
	audit("booking.confirmation_resent", reference_doctype="TEX Booking", reference_name=b.name,
	      property=b.property, new={"queued": mail["queued"], "status": mail["status"],
	                                "communication": mail["communication"]})
	return {"booking": b.name, "queued": mail["queued"], "status": mail["status"], "email": b.booker_email}


# ─── read ────────────────────────────────────────────────────────────────


def booking_summary(booking: str, *, replay: bool = False) -> dict:
	b = frappe.get_doc("TEX Booking", booking)
	ccy = b.currency or "EUR"
	return {
		"booking": b.name, "status": b.status, "property": b.property, "currency": b.currency,
		"total": to_str(from_db(b.total_amount, ccy)),
		"paid": to_str(from_db(b.paid_amount, ccy)),
		"balance": to_str(from_db(b.balance_amount, ccy)),
		# money held above the total (a guest change kept as credit, or not refunded yet, G-45)
		"credit": to_str(quantize(max(ZERO, from_db(b.paid_amount, ccy) - from_db(b.total_amount, ccy)), ccy)),
		"due_now": to_str(from_db(b.amount_due_now, b.currency or "EUR")),
		"payment_status": b.payment_status, "market": b.market, "channel": b.sales_channel,
		"booker_name": b.booker_name, "guest_change_pending": bool(b.guest_change_pending),
		"rooms": [{"reservation": r.reservation, "room_type": r.room_type, "check_in": str(r.check_in),
		           "check_out": str(r.check_out), "adults": r.adults, "children": r.children,
		           "amount": to_str(from_db(r.amount, b.currency or "EUR")), "status": r.status} for r in b.rooms],
		"idempotent_replay": replay,
	}


def expire_booking(booking: str, *, now: datetime | None = None, force: bool = False) -> bool:
	"""A booking waiting for its payment whose hold is over, with no payment attempt open, gives
	back all its rooms at once (K-2a): the booking is locked, then its rooms in name order (the
	order every change of a TEX booking takes), and the rooms and the booking are cancelled in
	this one transaction; their held extras and coupon uses are released with them. A payment
	attempt started within the hold keeps the rooms until its own deadline (``holds``), never
	longer; a booking none of whose rooms is held any more follows them at once. ``force``: its
	money arrived and cannot confirm it (``late_payments``, K-2b). → whether it expired."""
	now = get_datetime(now or now_datetime())
	b = frappe.get_doc("TEX Booking", booking, for_update=True)
	if b.status not in holds.HOLDING:
		return False
	names = sorted(r.reservation for r in b.rooms)
	states = {n: frappe.db.get_value("Reservation", n, "status", for_update=True) for n in names}
	holding = [n for n in names if states[n] in holds.HOLDING]
	deadline = holds.hold_deadline(booking, lock=True)
	if holding and not force:
		if holds.in_flight(b, now) or not deadline or deadline > now:
			return False        # still on hold, or rooms held without a deadline (never guessed)
	frappe.flags.kamra_status_transition = True
	frappe.flags.kamra_cancelling = True
	try:
		for name in holding:
			res = frappe.get_doc("Reservation", name, for_update=True)
			res.cancellation_reason = "Payment failed" if res.status == "Pending Payment" else "Other"
			res.cancellation_note = "Hold / payment window expired"
			res.status = "Cancelled"
			res.cancelled_on = now
			res.hold_expires_on = None
			res.flags.tex_modification = True
			res.save(ignore_permissions=True)
	finally:
		frappe.flags.kamra_status_transition = False
		frappe.flags.kamra_cancelling = False
	_refresh_booking_after_change(booking)
	paid = from_db(b.paid_amount, b.currency)
	if paid > ZERO:
		# paid in part before its hold ended: that money comes off the cancelled booking into
		# reconciliation, never a negative balance (B2)
		from kamra.tex.services import late_payments

		late_payments.money_off_expired(booking, now=now)
	audit("booking.expire", reference_doctype="TEX Booking", reference_name=booking, property=b.property,
	      old={"status": b.status}, new={"status": frappe.db.get_value("TEX Booking", booking, "status"),
	                                     "reservations": holding, "hold_deadline": str(deadline) if deadline else None,
	                                     "payment_attempt_until": str(b.payment_attempt_until or "") or None,
	                                     "paid": to_str(paid), "currency": b.currency})
	return True


def revive_expired(booking: str, *, reason: str) -> list[str]:
	"""B4: a booking that expired while its payment was already made (the gateway captured it in
	time, its news came after the expiry) takes back the rooms its expiry gave back, at their locked
	price, when they are still free: under the booking's lock, its rooms' (name order) and their
	nights', recounted as a new sale of its contract is; its limited extras and coupon uses are
	checked and taken again. It waits for its payment again, which confirms it. Rooms cancelled on
	purpose stay cancelled. A room, extra or coupon gone meanwhile raises ``frappe.ValidationError``
	(the caller undoes the whole step). → the rooms taken back (none: nothing to take back)."""
	b = frappe.get_doc("TEX Booking", booking, for_update=True)
	if b.status != "Cancelled" and b.status not in holds.HOLDING:
		return []
	rooms = [frappe.get_doc("Reservation", n, for_update=True) for n in sorted(r.reservation for r in b.rooms)]
	back = [r for r in rooms if r.status == "Cancelled" and not cancelled_on_purpose(r.name)]
	if not back:
		return []
	now = now_datetime()
	stays = [(r, getdate(r.check_in_date), getdate(r.check_out_date)) for r in back]
	avail.lock_nights(b.property, [(r.room_type, ci, co) for r, ci, co in stays])
	need: dict[tuple, int] = defaultdict(int)
	for r, ci, co in stays:
		for night in avail.nights(ci, co):
			need[(avail.pool_of(r.room_type)[0], night)] += 1
	for r, ci, co in stays:
		pool = avail.pool_of(r.room_type)[0]
		_count, per_day = avail.stay_availability(b.property, r.room_type, r.tex_contract, ci, co, now.date(),
		                                          locking=True)
		if any(d.available < need[(pool, d.day)] for d in per_day):
			frappe.throw(_("The rooms of booking {0} are no longer free.").format(booking), title=_("Sold out"))
	snaps = {r.name: json.loads(r.tex_pricing_snapshot or "{}") for r, _ci, _co in stays}
	extras = xinv.tracked(b.property)
	extras_need = xinv.demand(list(snaps.values()), codes=set(extras))
	if extras_need:
		xinv.lock_days(b.property, extras_need)
		xinv.check(b.property, extras_need, trk=extras)
	frappe.flags.kamra_status_transition = True
	try:
		for r, _ci, _co in stays:
			r.status = "Pending Payment"
			r.hold_expires_on = now              # its payment confirms it now; nothing else keeps it
			r.cancellation_reason = r.cancellation_note = r.cancelled_on = None
			r.flags.tex_modification = True
			r.flags.tex_inventory_checked = True     # its nights were locked and recounted above
			r.save(ignore_permissions=True)
			if extras_need:
				xinv.allocate(b.property, booking, r.name, snaps[r.name], "Held", trk=extras)
	finally:
		frappe.flags.kamra_status_transition = False
	b.status = "Pending Payment"
	b.save(ignore_permissions=True)
	_refresh_booking_after_change(booking)
	sync_redemptions(booking)                  # its coupon uses, under their limits again
	names = [r.name for r, _ci, _co in stays]
	audit("booking.revive", reference_doctype="TEX Booking", reference_name=booking, property=b.property,
	      new={"reservations": names}, reason=reason)
	return names


def expire_pending_bookings() -> dict:
	"""Scheduler: bookings whose hold is over, with no payment attempt open, expire with all their
	rooms (``expire_booking``), each in its own transaction so a payment callback waits for at
	most one booking's expiry (tests keep one transaction)."""
	now = now_datetime()
	n = 0
	for name in frappe.get_all("TEX Booking", filters={"status": ("in", list(holds.HOLDING))}, pluck="name"):
		frappe.db.savepoint("tex_expire_booking")
		try:
			n += expire_booking(name, now=now)
		except Exception:
			try:
				frappe.db.rollback(save_point="tex_expire_booking")
			except Exception:
				frappe.db.rollback()     # a deadlock victim's transaction is gone with its savepoint
			log_exception(f"TEX booking expiry failed for {name}")
			continue
		if not frappe.flags.in_test:
			frappe.db.commit()  # nosemgrep: frappe-manual-commit -- one booking's expiry per transaction
	return {"expired": n, "at": str(now)}


def _as_dt(v) -> datetime:
	return get_datetime(v)
