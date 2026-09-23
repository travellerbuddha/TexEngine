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
from kamra.tex.availability.restrictions import RestrictionScope
from kamra.tex.commercial import context as ctxmod
from kamra.tex.money import ZERO, D, from_db, quantize, to_str
from kamra.tex.security import scope
from kamra.tex.security.audit import audit
from kamra.tex.services import quoting

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


def find_or_create_guest(g: dict, *, property: str, market: str | None, language: str | None) -> str:
	enterprise = frappe.db.get_value("Property", property, "tex_enterprise")
	existing = None
	if g.get("email"):
		existing = frappe.db.get_value("Guest", {"email": g["email"], "tex_enterprise": ("in", [enterprise, "", None])})
	if not existing and g.get("phone"):
		existing = frappe.db.get_value("Guest", {"phone": g["phone"], "tex_enterprise": ("in", [enterprise, "", None])})
	consent = {k: 1 for k in ("tex_consent_email", "tex_consent_sms", "tex_consent_whatsapp")
	           if g.get(k.replace("tex_", ""))}
	if existing:
		doc = frappe.get_doc("Guest", existing)
		changed = False
		for f, v in (("tex_enterprise", enterprise), ("tex_language", language), ("tex_market", market),
		             ("tex_country", g.get("country"))):
			if v and not doc.get(f):
				doc.set(f, v)
				changed = True
		if consent:   # consent only ever granted explicitly here, never implied
			for k in consent:
				doc.set(k, 1)
			doc.tex_consent_updated_at = now_datetime()
			doc.tex_consent_source = "booking"
			changed = True
		if changed:
			doc.save(ignore_permissions=True)
		return doc.name
	doc = frappe.get_doc({
		"doctype": "Guest", "first_name": g["first_name"], "last_name": g["last_name"], "email": g.get("email"),
		"phone": g.get("phone"), "nationality": g.get("nationality"),
		"date_of_birth": g.get("date_of_birth") or None, "tex_enterprise": enterprise,
		"tex_language": language, "tex_market": market,
		"tex_country": g.get("country") if g.get("country") and frappe.db.exists("Country", g.get("country")) else None,
		**consent, **({"tex_consent_updated_at": now_datetime(), "tex_consent_source": "booking"} if consent else {}),
	})
	doc.insert(ignore_permissions=True)
	return doc.name


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

	if staff:
		scope.require("reservation.create", property)
	elif channel not in ("DIRECT_WEB", "META"):
		frappe.throw(_("Not permitted."), frappe.PermissionError)

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
		sc = RestrictionScope(room_type=req["room_type"], contract=result["contract"]["contract"], market=market,
		                      rate_plan=req.get("rate_plan"), channel=channel)
		v = avail.check_restrictions(property, sc, getdate(req["check_in"]), getdate(req["check_out"]), now.date(),
		                             cells)
		if v:
			frappe.throw(_("This stay is no longer bookable: {0}").format(v[0].message))

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
	hold_until = None if confirm else add_to_date(now, minutes=int(
		frappe.db.get_single_value("TEX Settings", "hold_minutes") or 20))
	guest_name = find_or_create_guest(guest, property=property, market=market, language=language)
	booker = booker or {}
	token, token_digest = new_manage_token()
	manage_days = int(frappe.db.get_single_value("TEX Settings", "manage_link_days") or 365)

	booking = frappe.get_doc({
		"doctype": "TEX Booking", "property": property, "status": status, "sales_channel": channel,
		"market": market, "created_via": CREATED_VIA.get(channel, "Desk") if not staff or channel != "DIRECT_WEB"
		else "Desk", "sale_at": now, "booker_guest": guest_name,
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

	reservations = []
	priced: list[tuple[dict, str]] = []
	for idx, (row, req, result) in enumerate(rows):
		amounts = reservation_amounts(result)
		kids = req.get("children") or []
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
			"tex_fx_rate": D((result.get("fx") or {}).get("sell_rate") or 1),
			"tex_promotions": ", ".join(p["promo_id"] for p in result.get("promotions") or [] if p["applied"]),
			"tex_pricing_snapshot": json.dumps({**result, "accepted_at": str(now), "quote_id": row.name},
			                                   sort_keys=True, ensure_ascii=False),
			**amounts,
		})
		res.flags.ignore_permissions = True
		res.insert(ignore_permissions=True)
		reservations.append(res.name)
		booking.append("rooms", {"reservation": res.name, "room_type": req["room_type"], "check_in": req["check_in"],
		                         "check_out": req["check_out"], "adults": int(req["adults"]), "children": len(kids),
		                         "amount": amounts["amount_after_tax"], "status": status, "quote": row.name})
		priced.append((result, res.name))
		if extras_need:
			xinv.allocate(property, booking.name, res.name, result, "Confirmed" if confirm else "Held",
			              trk=extras_tracked)
		q = frappe.get_doc("TEX Quote", row.name)
		q.status = "Used"
		q.booking = booking.name
		q.save(ignore_permissions=True)
		_record_revision(res.name, booking.name, change_type="Original", old_amount=None,
		                 new_amount=amounts["amount_after_tax"], currency=currency, basis="CURRENT",
		                 basis_sale_at=now, after=result, source="Guest" if not staff else "Desk")
	_record_redemptions(priced, booking.name, property, guest.get("email") or guest.get("phone"), committed=confirm)
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


def confirm_booking(booking: str, *, reason: str | None = None) -> None:
	b = frappe.get_doc("TEX Booking", booking)
	if b.status == "Confirmed":
		return
	if b.status not in ("Pending Payment", "Held"):
		frappe.throw(_("Booking {0} cannot be confirmed from {1}.").format(booking, b.status))
	now = now_datetime()
	frappe.flags.kamra_status_transition = True
	try:
		for row in b.rooms:
			res = frappe.get_doc("Reservation", row.reservation)
			if res.status in ("Pending Payment", "Held"):
				res.status = "Confirmed"
				res.hold_expires_on = None
				res.tex_price_locked = 1
				res.tex_locked_at = now
				res.flags.tex_modification = True
				res.save(ignore_permissions=True)
			row.status = "Confirmed"
	finally:
		frappe.flags.kamra_status_transition = False
	xinv.confirm(booking)            # held extras units become confirmed (G-19)
	for r in frappe.get_all("TEX Promotion Redemption", filters={"booking": booking, "status": "Reserved"},
	                        pluck="name"):
		d = frappe.get_doc("TEX Promotion Redemption", r)
		d.status = "Committed"
		d.save(ignore_permissions=True)
	b.status = "Confirmed"
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


def cancellation_penalty(reservation, today=None) -> tuple[D, dict]:
	snap = json.loads(reservation.tex_pricing_snapshot or "{}")
	ccy = reservation.tex_currency or snap.get("currency") or "EUR"
	total = from_db(reservation.tex_total_amount or reservation.amount_after_tax, ccy)
	rp = snap.get("rate_plan") or {}
	policy = rp.get("cancellation_policy")
	today = getdate(today or now_datetime())
	days = (getdate(reservation.check_in_date) - today).days
	if rp and not rp.get("refundable", True):
		return quantize(total, ccy), {"rule": "non-refundable", "days_before": days}
	if not policy:
		return ZERO, {"rule": "no policy (free cancellation)", "days_before": days}
	applicable = [r for r in policy.get("rules") or [] if days < int(r["days_before_arrival"])]
	if not applicable:
		return ZERO, {"rule": "free cancellation window", "days_before": days}
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
	guest's manage token for this exact reservation; staff calls always check scope."""
	res = frappe.get_doc("Reservation", reservation)
	if not _guest_authorized:
		scope.require("reservation.cancel", res.property)
	elif waive_penalty:
		frappe.throw(_("Guests cannot waive cancellation fees."), frappe.PermissionError)
	if res.status in ("Cancelled", "No Show", "Checked Out"):
		frappe.throw(_("Reservation {0} is already {1}.").format(reservation, res.status))
	if not (reason or "").strip():
		frappe.throw(_("A cancellation reason is required."))
	penalty, basis = cancellation_penalty(res)
	if waive_penalty:
		scope.require("price.override", res.property)
		penalty = ZERO
	old_amount = from_db(res.tex_total_amount or res.amount_after_tax, res.tex_currency or "EUR")
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
		b.status = "Partially Cancelled"
	paid = from_db(b.paid_amount, ccy)
	b.payment_status = "Paid" if paid >= total and total > 0 else ("Partially Paid" if paid > 0 else b.payment_status)
	b.save(ignore_permissions=True)


def resend_confirmation(booking: str) -> dict:
	"""Send the booking e-mail again with a NEW manage link (only a hash of the old one
	exists, so it cannot be re-sent; the old link stops working)."""
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
	sent = notify.booking_created(b.name, token)
	audit("booking.confirmation_resent", reference_doctype="TEX Booking", reference_name=b.name,
	      property=b.property, new={"sent": bool(sent)})
	return {"booking": b.name, "sent": bool(sent), "email": b.booker_email}


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


def expire_pending_bookings() -> dict:
	"""Scheduler: bookings whose payment hold expired follow their reservations."""
	now = now_datetime()
	n = 0
	for name in frappe.get_all("TEX Booking", filters={"status": "Pending Payment"}, pluck="name"):
		rooms = frappe.get_all("TEX Booking Room", filters={"parent": name}, pluck="reservation")
		states = [frappe.db.get_value("Reservation", r, "status") for r in rooms]
		if states and all(s == "Cancelled" for s in states):
			_refresh_booking_after_change(name)
			n += 1
	return {"expired": n, "at": str(now)}


def _as_dt(v) -> datetime:
	return get_datetime(v)
