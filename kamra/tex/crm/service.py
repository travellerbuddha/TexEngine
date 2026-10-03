"""TEX CRM service (R-35–R-39).

Tenancy: a guest is visible to a user when the guest has a reservation at one of
the user's hotels, or belongs to the enterprise of one of the user's hotels. Stays,
bookings and communications shown are always filtered to the user's permitted
hotels. Marketing data leaves the system only for guests with the
matching consent (KVKK / GDPR); every consent change and export is audited.
"""

from __future__ import annotations

import hashlib
import json
from datetime import timedelta

import frappe
from frappe import _
from frappe.utils import add_days, add_to_date, get_fullname, getdate, now_datetime, nowdate

from kamra.tex.crm import loyalty
from kamra.tex.crm import segments as seg
from kamra.tex.money import ZERO, D, from_db, quantize, to_str
from kamra.tex.security import scope
from kamra.tex.security.audit import audit

EDITABLE = ("first_name", "last_name", "phone", "email", "nationality", "date_of_birth", "gender", "vip",
            "guest_notes", "address_line", "city", "tex_language", "tex_country", "tex_market", "tex_tags",
            "tex_preferences", "blacklisted", "blacklist_reason")
CONSENT = ("tex_consent_email", "tex_consent_sms", "tex_consent_whatsapp")
LIST_FIELDS = ["name", "full_name", "first_name", "last_name", "email", "phone", "vip", "blacklisted", "nationality",
               "tex_country", "tex_market", "tex_language", "tex_tags", "tex_stays", "tex_lifetime_value",
               "tex_lifetime_currency", "tex_last_stay", "tex_loyalty_points", "tex_consent_email", "tex_consent_sms",
               "tex_consent_whatsapp", "tex_enterprise"]
ABANDON_AFTER_MINUTES = 45
# how long an open case left at payment is watched for its booking's payment (a payment link's life)
RECOVERY_DAYS = 60


# who sent or logged a message, as staff read it: no one for the visitor of an online booking
# ("Guest") or the system (Administrator: the scheduler, a migration); the screens show those as
# TEX itself. One rule for the Communications list and the guest profile (G-64 review L4).
SYSTEM_ACTORS = frozenset({"Guest", "Administrator"})


def actor_name(user: str | None) -> str | None:
	if not user or user in SYSTEM_ACTORS:
		return None
	return get_fullname(user)


# ─── tenancy ─────────────────────────────────────────────────────────────


def _enterprises(props: set[str]) -> set[str]:
	if not props:
		return set()
	return {e for e in frappe.get_all("Property", filters={"name": ("in", list(props))}, pluck="tex_enterprise") if e}


def _visible_guest_sql(props: set[str]) -> tuple[str, dict]:
	if not props:
		return "1=0", {}
	ents = _enterprises(props)
	cond = "(g.name IN (SELECT r.guest FROM `tabReservation` r WHERE r.property IN %(props)s)"
	if ents:
		cond += " OR g.tex_enterprise IN %(ents)s"
	cond += ")"
	return cond, {"props": tuple(props), "ents": tuple(ents) or ("",)}


def openable_guests(guests, cap: str = "crm.view") -> set[str]:
	"""Which of ``guests`` the user may open (``require_guest`` would let through): a booking at
	one of the hotels where the user holds ``cap``, or a profile of one of their enterprises."""
	guests = {g for g in guests if g}
	if not guests:
		return set()
	props = {p for p in scope.permitted_properties() if scope.has_capability(cap, p)}
	if not props:
		return set()
	seen = set(frappe.get_all("Reservation", filters={"guest": ("in", list(guests)), "property": ("in", list(props))},
	                          pluck="guest", distinct=True))
	ents = _enterprises(props)
	if ents and guests - seen:
		seen |= set(frappe.get_all("Guest", filters={"name": ("in", list(guests - seen)),
		                                            "tex_enterprise": ("in", list(ents))}, pluck="name"))
	return seen


def require_guest(guest: str, cap: str = "crm.view") -> set[str]:
	"""→ the hotels (within scope) through which the user may see this guest."""
	if not frappe.db.exists("Guest", guest):
		frappe.throw(_("Guest not found."), frappe.DoesNotExistError)
	props = {p for p in scope.permitted_properties() if scope.has_capability(cap, p)}
	via = set(frappe.get_all("Reservation", filters={"guest": guest, "property": ("in", list(props) or [""])},
	                         pluck="property", distinct=True))
	ent = frappe.db.get_value("Guest", guest, "tex_enterprise")
	if ent and ent in _enterprises(props):
		via |= {p for p in props if frappe.db.get_value("Property", p, "tex_enterprise") == ent}
	if not via:
		frappe.throw(_("You don't have access to this guest."), frappe.PermissionError)
	return via


# ─── guests ──────────────────────────────────────────────────────────────


# a stable order: the most recently changed first, the name breaks ties (so a page never repeats
# or skips a guest while the list is paged)
LIST_ORDER = "g.`modified` DESC, g.`name` DESC"
SEGMENT_BATCH = 500


def _like(q: str) -> str:
	"""``q`` as a literal LIKE pattern (``%`` and ``_`` typed by the user match themselves)."""
	q = q.strip()[:80].replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
	return f"%{q}%"


def _guest_where(props: set[str], *, q: str | None, vip: bool | None, consent: str | None) -> tuple[str, dict]:
	"""The list's WHERE clause (on ``tabGuest g``): the viewer's tenancy first, then the filters."""
	cond, params = _visible_guest_sql(props)
	where = [cond]
	if q and q.strip():
		where.append("(g.full_name LIKE %(q)s OR g.email LIKE %(q)s OR g.phone LIKE %(q)s OR g.name LIKE %(q)s)")
		params["q"] = _like(q)
	if vip is not None:
		where.append("g.vip = %(vip)s")
		params["vip"] = 1 if vip else 0
	if consent in CONSENT:
		where.append(f"g.`{consent}` = 1")
	return " AND ".join(where), params


def _guest_rows(where: str, params: dict, *, start: int, limit: int) -> list:
	cols = ", ".join(f"g.`{f}`" for f in LIST_FIELDS)
	return frappe.db.sql(  # nosemgrep -- static columns and conditions, values bound
		f"SELECT {cols} FROM `tabGuest` g WHERE {where} ORDER BY {LIST_ORDER} LIMIT %(_limit)s OFFSET %(_start)s",
		{**params, "_limit": int(limit), "_start": int(start)}, as_dict=True)


def list_guests(*, q: str | None = None, segment: str | None = None, vip: bool | None = None,
                consent: str | None = None, property: str | None = None, start: int = 0,
                limit: int = 50) -> dict:
	"""One page of the viewer's guests and the total, both from SQL inside the viewer's tenancy
	(G-65). A segment's rules are evaluated on facts from the viewer's hotels, over the matching
	guests read in batches, so only one batch and the page are ever held."""
	props = {p for p in scope.permitted_properties() if scope.has_capability("crm.view", p)}
	if property:
		scope.require("crm.view", property)
		props = {property}
	where, params = _guest_where(props, q=q, vip=vip, consent=consent)
	start, limit = max(int(start or 0), 0), max(int(limit or 0), 0)
	today = getdate(nowdate())
	if segment:
		rules = _segment_rules(_segment(segment, "crm.view", props))
		total, page, offset = 0, [], 0
		while True:
			batch = _guest_rows(where, params, start=offset, limit=SEGMENT_BATCH)
			facts = facts_for(batch, props, today)
			for r in batch:
				if not seg.matches(facts[r.name], rules, today):
					continue
				if start <= total < start + limit:
					page.append(r)
				total += 1
			if len(batch) < SEGMENT_BATCH:
				break
			offset += SEGMENT_BATCH
	else:
		total = frappe.db.sql(f"SELECT COUNT(*) FROM `tabGuest` g WHERE {where}", params)[0][0]  # nosemgrep
		page = _guest_rows(where, params, start=start, limit=limit) if limit else []
	facts = facts_for(page, props, today)
	for r in page:
		_stats(r, facts[r.name], today)
	return {"total": int(total), "rows": page}


def _stats(row: dict, f: dict, today) -> None:
	"""The guest's stays and value at the viewer's hotels, and points in the viewer's loyalty
	programs, only (never another tenant's; the stored totals count every tenant)."""
	ccy = f["lifetime_currency"]
	row["tex_stays"] = f["stays"]
	row["tex_loyalty_points"] = f["loyalty_points"]
	row["tex_lifetime_currency"] = ccy
	row["tex_lifetime_value"] = to_str(from_db(f["lifetime_value"].get(ccy, ZERO), ccy)) if ccy else "0"
	row["tex_last_stay"] = str(today - timedelta(days=f["last_stay_days_ago"])) \
		if f["last_stay_days_ago"] is not None else None


def facts_for(rows: list[dict], props: set[str], today) -> dict[str, dict]:
	"""Segment facts of each guest, from reservations and abandoned bookings at ``props`` and
	the points in the loyalty programs of ``props`` (G-65)."""
	names = [r["name"] for r in rows]
	stays: dict[str, list] = {n: [] for n in names}
	gave_up: dict[str, list] = {n: [] for n in names}
	points: dict[str, int] = {n: 0 for n in names}
	programs = loyalty.visible_programs(props) if names and props else set()
	if names and props:
		for chunk in (names[i:i + 500] for i in range(0, len(names), 500)):
			if programs:
				for g, pts in frappe.db.sql(
					"""SELECT guest, SUM(points) FROM `tabTEX Loyalty Ledger`
					   WHERE guest IN %(g)s AND program IN %(p)s AND status IN %(s)s GROUP BY guest""",
						{"g": tuple(chunk), "p": tuple(programs), "s": loyalty.FINAL}):
					points[g] = int(pts or 0)
			for r in frappe.db.sql(
				"""SELECT name, tex_booking, guest, status, check_in_date, check_out_date, children, tex_sale_at,
				          creation, cancelled_on, tex_total_amount, amount_after_tax, tex_currency
				   FROM `tabReservation` WHERE guest IN %(g)s AND property IN %(p)s
				     AND tex_hold_expired = 0""",     # a hold that ran out of time is no stay of the guest (O-24)
					{"g": tuple(chunk), "p": tuple(props)}, as_dict=True):
				if not (r.check_in_date and r.check_out_date):
					continue
				ccy = r.tex_currency or None
				stays[r.guest].append(seg.StayFact(
					r.status, getdate(r.check_in_date), getdate(r.check_out_date), int(r.children or 0),
					getdate(r.tex_sale_at or r.creation), getdate(r.cancelled_on) if r.cancelled_on else None,
					from_db(r.tex_total_amount or r.amount_after_tax or 0, ccy or "EUR"), ccy,
					r.tex_booking or r.name))                       # the rooms of one booking are one visit (O-23)
			for a in frappe.get_all("TEX Abandoned Booking", filters={"guest": ("in", chunk),
			                                                          "property": ("in", list(props))},
			                        fields=["guest", "last_event_at"]):
				gave_up[a.guest].append(a.last_event_at)
	# the birthday fact needs the date of birth, which the guest list itself does not send
	need = [r["name"] for r in rows if "date_of_birth" not in r]
	dobs = dict(frappe.db.sql("SELECT name, date_of_birth FROM `tabGuest` WHERE name IN %(g)s",
	                          {"g": tuple(need)})) if need else {}
	return {r["name"]: seg.derive_facts({**r, "date_of_birth": r.get("date_of_birth", dobs.get(r["name"])),
	                                     "tex_loyalty_points": points[r["name"]]},
	                                    stays[r["name"]], gave_up[r["name"]], today) for r in rows}


def profile(guest: str) -> dict:
	via = require_guest(guest)
	g = frappe.get_doc("Guest", guest)
	d = {f: g.get(f) for f in ("name", "full_name", *EDITABLE, *CONSENT, "tex_consent_updated_at",
	                          "tex_consent_source", "tex_consent_text_version", "tex_stays", "tex_lifetime_value",
	                          "tex_lifetime_currency", "tex_last_stay", "tex_loyalty_points", "tex_enterprise")}
	for k in ("date_of_birth", "tex_last_stay", "tex_consent_updated_at"):
		d[k] = str(d[k]) if d.get(k) else None
	today = getdate(nowdate())
	facts = facts_for([g.as_dict()], via, today)[guest]
	_stats(d, facts, today)                                    # this tenant's stays only (G-26)
	if not any(scope.has_capability("guest.export", p) for p in via):
		d.pop("id_number", None)
	stays = frappe.get_all("Reservation", filters={"guest": guest, "property": ("in", list(via))},
	                       fields=["name", "property", "status", "check_in_date", "check_out_date", "room_type",
	                               "tex_board", "adults", "children", "tex_total_amount", "tex_currency",
	                               "tex_booking", "tex_sales_channel", "tex_market", "cancellation_fee",
	                               "tex_hold_expired"],
	                       order_by="check_in_date desc", limit=200)
	for s in stays:
		s["check_in_date"], s["check_out_date"] = str(s["check_in_date"]), str(s["check_out_date"])
		# a hold that ran out of time is no cancellation and was never a sale (O-24, LO-24)
		s["hold_expired"] = bool(s.pop("tex_hold_expired"))
		s["tex_total_amount"] = to_str(from_db(s["tex_total_amount"], s["tex_currency"] or "EUR"))
		# the fee charged for a cancellation or no-show; none on a stay that is not closed
		fee = from_db(s.pop("cancellation_fee") or 0, s["tex_currency"] or "EUR")
		s["cancellation_fee"] = to_str(fee) if fee and s["status"] in seg.NOT_STAYED else None
	comms = frappe.get_all("TEX Communication", filters={"guest": guest, "property": ("in", [*via, ""])},
	                       fields=["name", "channel", "direction", "status", "consent_basis", "subject", "body",
	                               "sent_at", "actor", "booking", "reservation", "creation", "delivery_error"],
	                       order_by="creation desc", limit=100)
	for c in comms:
		c["sent_at"] = str(c["sent_at"]) if c["sent_at"] else None
		c["creation"] = str(c["creation"])
		c["actor_name"] = actor_name(c["actor"])
	member_of = [{"name": s.name, "segment_name": s.segment_name, "system_key": s.system_key}
	             for s in visible_segments(via) if s.rules_json and _safe_match(facts, s.rules_json, today)]
	# changes, and requests from online bookings that were not applied (ADR-046) for the hotel to confirm
	# a profile is shared inside an enterprise (ADR-040), its bookings and staff are not: entries
	# made at another hotel (a booking there, its staff) stay with that hotel; profile-level
	# changes (CRM, no hotel) are the consent record everyone sharing the profile relies on
	consent_log = [c for c in frappe.get_all(
		"TEX Audit Event", filters={"reference_doctype": "Guest", "reference_name": ("in", [guest, *merged_into(guest)]),
		                            "action": ("in", ["guest.consent", "guest.consent_requested"])},
		fields=["event_time", "action", "actor", "new_value", "reason", "source", "property"],
		order_by="event_time desc", limit=200) if not c.property or c.property in via][:50]
	for c in consent_log:
		c["event_time"] = str(c["event_time"])
		change = json.loads(c["new_value"] or "{}")
		c["booking"] = change.pop("booking", None) if isinstance(change, dict) else None
		c["new_value"] = json.dumps(change)
	extras, extras_summary = _extras_bought(guest, via)
	return {"guest": d, "stays": stays, "communications": comms, "segments": member_of,
	        "loyalty": loyalty.summary(guest, loyalty.visible_programs(via), hotels=via),
	        "extras": extras, "extras_summary": extras_summary, "cancellations": _cancellations(guest, via),
	        "consent_history": consent_log, "hotels": sorted(via),
	        "possible_duplicates": possible_duplicates(guest, {p for p in scope.permitted_properties()
	                                                           if scope.has_capability("crm.view", p)})}


def _quantity(q) -> str:
	return format(D(q or 0).normalize(), "f")


def _extras_bought(guest: str, via: set[str]) -> tuple[list[dict], list[dict]]:
	"""The extras on the guest's stays at the viewer's hotels (R-37), from each stay's price-locked
	snapshot (the extras sold with it and those added later), and per extra and currency their
	quantity, value and number of stays. A cancelled stay or a no-show bought nothing. Only what
	the guest pays is read: never cost, margin or the rules that priced it."""
	lines: list[dict] = []
	for r in frappe.get_all("Reservation", filters={"guest": guest, "property": ("in", list(via)),
	                                                 "status": ("not in", list(seg.NOT_STAYED | seg.NOT_SOLD))},
	                        fields=["name", "property", "check_in_date", "tex_currency", "tex_pricing_snapshot"],
	                        order_by="check_in_date desc, name desc", limit=200):
		try:
			snap = json.loads(r.tex_pricing_snapshot or "{}")
		except ValueError:
			continue
		ccy = snap.get("currency") or r.tex_currency or "EUR"
		for e in snap.get("extras") or []:
			if not isinstance(e, dict) or not e.get("ok") or not e.get("code"):
				continue
			lines.append({"reservation": r.name, "property": r.property, "check_in": str(r.check_in_date),
			              "code": e["code"], "name": e.get("name") or e["code"], "quantity": _quantity(e.get("quantity")),
			              "amount": to_str(quantize(D(e.get("amount") or 0), ccy)), "currency": ccy,
			              "service_dates": list(e.get("service_dates") or []), "added_later": bool(e.get("addon"))})
	summary: dict[tuple[str, str], dict] = {}
	for ln in lines:
		row = summary.setdefault((ln["code"], ln["currency"]), {"code": ln["code"], "name": ln["name"],
		                                                        "currency": ln["currency"], "quantity": ZERO,
		                                                        "amount": ZERO, "stays": set()})
		row["quantity"] += D(ln["quantity"])
		row["amount"] += D(ln["amount"])
		row["stays"].add(ln["reservation"])
	return lines, [{**r, "quantity": _quantity(r["quantity"]), "amount": to_str(quantize(r["amount"], r["currency"])),
	                "stays": len(r["stays"])} for _k, r in sorted(summary.items())]


def _cancellations(guest: str, via: set[str]) -> dict:
	"""Cancelled stays and no-shows at the viewer's hotels, with the fees charged for them per
	currency (never summed across currencies) and the last cancellation day (R-37)."""
	ccy_of = dict(frappe.get_all("Property", filters={"name": ("in", list(via))}, fields=["name", "currency"],
	                             as_list=True))
	counts = {"Cancelled": 0, "No Show": 0}
	fees: dict = {}
	last = None
	for r in frappe.get_all("Reservation", filters={"guest": guest, "property": ("in", list(via)),
	                                                 "status": ("in", list(counts)), "tex_hold_expired": 0},
	                        fields=["status", "property", "tex_currency", "cancellation_fee", "cancelled_on"]):
		counts[r.status] += 1
		if r.status == "Cancelled" and r.cancelled_on:
			last = max(last, getdate(r.cancelled_on)) if last else getdate(r.cancelled_on)
		ccy = r.tex_currency or ccy_of.get(r.property) or "EUR"
		fee = from_db(r.cancellation_fee or 0, ccy)
		if fee:
			fees[ccy] = fees.get(ccy, ZERO) + fee
	return {"count": counts["Cancelled"], "no_shows": counts["No Show"],
	        "fees": [{"currency": c, "amount": to_str(quantize(fees[c], c))} for c in sorted(fees)],
	        "last_cancelled_on": str(last) if last else None}


def _safe_match(facts: dict, rules_json: str, today) -> bool:
	try:
		return seg.matches(facts, seg.validate(json.loads(rules_json)), today)
	except (seg.SegmentError, ValueError):
		return False


def update_profile(guest: str, data: dict, *, consent_source: str = "staff",
                   consent_text_version: str | None = None) -> dict:
	require_guest(guest, "crm.edit")
	g = frappe.get_doc("Guest", guest)
	before = {f: g.get(f) for f in (*EDITABLE, *CONSENT)}
	for f in EDITABLE:
		if f in data:
			g.set(f, data[f] if data[f] not in ("",) else None)
	from kamra.tex.services.booking import consent_given

	consent_changed = {}
	for f in CONSENT:
		# a consent sent as text means what it says ("0", "false": no), as in a booking (ADR-056)
		if f in data and consent_given(data[f]) != bool(g.get(f)):
			given = consent_given(data[f])
			g.set(f, 1 if given else 0)
			consent_changed[f] = [bool(before[f]), given]
	if consent_changed:
		g.tex_consent_updated_at = now_datetime()
		g.tex_consent_source = consent_source[:140]
		if consent_text_version:
			g.tex_consent_text_version = consent_text_version[:140]
	g.flags.tex_consent_recorded = True                  # audited below, with the source the caller named
	g.save(ignore_permissions=True)
	changed = {f: [str(before[f] or ""), str(g.get(f) or "")] for f in EDITABLE
	           if str(before[f] or "") != str(g.get(f) or "")}
	if changed:
		audit("guest.update", reference_doctype="Guest", reference_name=guest,
		      old={k: v[0] for k, v in changed.items()}, new={k: v[1] for k, v in changed.items()})
	if consent_changed:
		audit("guest.consent", reference_doctype="Guest", reference_name=guest,
		      new={k: v[1] for k, v in consent_changed.items()}, reason=consent_source)
	return {"name": g.name, "changed": sorted(changed), "consent_changed": sorted(consent_changed)}


# what a logged communication may point at (G-83): only these, only this guest's, and only at
# the hotels through which the caller may edit the guest
COMMUNICATION_LINKS = {"booking": "TEX Booking", "reservation": "Reservation"}


def _communication_hotel(guest: str, via: set[str], *, booking: str | None, reservation: str | None,
                         property: str | None) -> str:
	"""The hotel a communication is logged at, after checking every record it links (G-83).
	A record that does not exist, is another guest's, or is at a hotel outside ``via`` gets
	the same answer, so the check tells nothing about other tenants."""
	hotels = set()
	if booking:
		b = frappe.db.get_value(COMMUNICATION_LINKS["booking"], booking, ["property", "booker_guest"], as_dict=True)
		if not b or b.property not in via or (b.booker_guest != guest and not frappe.db.exists(
				"Reservation", {"tex_booking": booking, "guest": guest})):
			frappe.throw(_("Booking {0} is not one of this guest's bookings at your hotels.").format(booking),
			             frappe.PermissionError)
		hotels.add(b.property)
	if reservation:
		r = frappe.db.get_value(COMMUNICATION_LINKS["reservation"], reservation, ["property", "guest", "tex_booking"],
		                        as_dict=True)
		if not r or r.property not in via or r.guest != guest:
			frappe.throw(_("Reservation {0} is not one of this guest's stays at your hotels.").format(reservation),
			             frappe.PermissionError)
		if booking and r.tex_booking != booking:
			frappe.throw(_("Reservation {0} is not part of booking {1}.").format(reservation, booking))
		hotels.add(r.property)
	if property:
		if property not in via:
			frappe.throw(_("You don't have access to {0}.").format(property), frappe.PermissionError)
		hotels.add(property)
	if len(hotels) > 1:
		frappe.throw(_("The linked records belong to different hotels."))
	return hotels.pop() if hotels else sorted(via)[0]


def log_communication(guest: str, *, channel: str, direction: str, subject: str | None, body: str | None,
                      consent_basis: str = "Transactional", booking: str | None = None,
                      reservation: str | None = None, property: str | None = None) -> str:
	via = require_guest(guest, "crm.edit")
	if channel not in ("Email", "SMS", "WhatsApp", "Phone", "Note"):
		frappe.throw(_("Unknown channel."))
	if direction not in ("Outbound", "Inbound", "Internal"):
		frappe.throw(_("Unknown direction."))
	if consent_basis not in ("Transactional", "Marketing", "Legitimate Interest"):
		frappe.throw(_("Unknown consent basis."))
	booking, reservation = booking or None, reservation or None
	property = _communication_hotel(guest, via, booking=booking, reservation=reservation, property=property or None)
	if consent_basis == "Marketing" and direction == "Outbound" and channel in ("Email", "SMS", "WhatsApp"):
		field = {"Email": "tex_consent_email", "SMS": "tex_consent_sms", "WhatsApp": "tex_consent_whatsapp"}[channel]
		if not frappe.db.get_value("Guest", guest, field):
			frappe.throw(_("The guest has not consented to marketing by {0}.").format(channel))
	doc = frappe.get_doc({"doctype": "TEX Communication", "guest": guest, "property": property,
	                      "booking": booking, "reservation": reservation, "channel": channel,
	                      "direction": direction, "status": "Logged", "consent_basis": consent_basis,
	                      "subject": (subject or "")[:140], "body": (body or "")[:5000], "sent_at": now_datetime(),
	                      "actor": frappe.session.user})
	doc.insert(ignore_permissions=True)
	return doc.name


def refresh_guest_stats(guest: str) -> None:
	"""Completed stays, their value and the last stay, from reservations that were sold (not an
	inquiry, quote or waitlist entry), not cancelled or no-shows, and whose check-out has passed
	(upcoming bookings are not stays yet): the stays the CRM facts count (``segments``). Money is
	never summed across currencies: lifetime value is the total in the guest's most used currency
	(ties → alphabetical), stored with that currency. A stay the legacy engine priced (no TEX
	currency) is in its hotel's currency, as Kamra kept it (G-76)."""
	today = getdate(nowdate())
	rows = [r for r in frappe.get_all("Reservation",
	                                  filters={"guest": guest, "status": ("not in", sorted(seg.NOT_STAYED | seg.NOT_SOLD))},
	                                  fields=["name", "tex_booking", "property", "check_out_date", "tex_total_amount",
	                                          "amount_after_tax", "tex_currency"])
	        if r.check_out_date and getdate(r.check_out_date) <= today]
	hotel_ccy: dict[str, str | None] = {}
	by_ccy: dict[str, list] = {}
	for r in rows:
		if not r.tex_currency and r.property not in hotel_ccy:
			hotel_ccy[r.property] = frappe.db.get_value("Property", r.property, "currency")
		by_ccy.setdefault(r.tex_currency or hotel_ccy.get(r.property) or "EUR", []).append(r)

	def visits(of: list) -> int:
		"""A stay is a visit: the reservations (rooms) of one booking are one (O-23)."""
		return len({r.tex_booking or r.name for r in of})

	main = min(by_ccy, key=lambda c: (-visits(by_ccy[c]), c)) if by_ccy else None
	value = sum((from_db(r.tex_total_amount or r.amount_after_tax or 0, main) for r in by_ccy.get(main, [])), ZERO)
	frappe.db.set_value("Guest", guest, {"tex_stays": visits(rows), "tex_lifetime_value": value,
	                                     "tex_lifetime_currency": main,
	                                     "tex_last_stay": max(r.check_out_date for r in rows) if rows else None},
	                    update_modified=False)


def refresh_recent_checkouts(days: int = 2) -> int:
	"""Scheduler (daily): a booking becomes a stay when its check-out passes."""
	since = add_days(nowdate(), -days)
	guests = frappe.get_all("Reservation", filters={"check_out_date": ("between", [since, nowdate()]),
	                                                "guest": ("is", "set")}, pluck="guest", distinct=True)
	for g in guests:
		refresh_guest_stats(g)
	return len(guests)


# ─── segments ────────────────────────────────────────────────────────────


def visible_segments(props: set[str]) -> list:
	"""Presets and the segments of the viewer's enterprises, never another tenant's."""
	ents = sorted(_enterprises(props))
	filters = [["system_key", "is", "set"]]
	rows = frappe.get_all("TEX Guest Segment", filters=filters, fields=SEGMENT_FIELDS, order_by="segment_name asc")
	if ents:
		rows += frappe.get_all("TEX Guest Segment", filters={"enterprise": ("in", ents), "system_key": ("is", "not set")},
		                       fields=SEGMENT_FIELDS, order_by="segment_name asc")
	if scope.is_platform_admin():
		rows += frappe.get_all("TEX Guest Segment", filters={"enterprise": ("is", "not set"),
		                                                     "system_key": ("is", "not set")},
		                       fields=SEGMENT_FIELDS, order_by="segment_name asc")
	return rows


SEGMENT_FIELDS = ["name", "segment_name", "system_key", "description", "enterprise", "member_count",
                  "last_evaluated", "rules_json"]


def _cap_props(cap: str) -> set[str]:
	return {p for p in scope.permitted_properties() if scope.has_capability(cap, p)}


def _segment(segment: str, cap: str, props: set[str] | None = None):
	"""A segment the user may use with ``cap`` (a preset, or one of their enterprise's)."""
	row = frappe.db.get_value("TEX Guest Segment", segment, SEGMENT_FIELDS, as_dict=True)
	props = _cap_props(cap) if props is None else props
	if not props and not scope.is_platform_admin():
		frappe.throw(_("Not permitted: {0}.").format(cap), frappe.PermissionError)
	if not row:
		frappe.throw(_("Segment not found."), frappe.DoesNotExistError)
	if row.system_key or scope.is_platform_admin():
		return row
	if not row.enterprise or row.enterprise not in _enterprises(props):
		frappe.throw(_("Segment not found."), frappe.DoesNotExistError)       # another tenant's: not even its name
	return row


def _segment_rules(row) -> dict:
	try:
		return seg.validate(json.loads(row.rules_json or "{}"))
	except (seg.SegmentError, ValueError) as e:
		frappe.throw(_("Segment rules are invalid: {0}").format(str(e)))


def save_segment(data: dict) -> str:
	props = _cap_props("crm.edit")
	if not props:
		frappe.throw(_("Not permitted: {0}.").format("crm.edit"), frappe.PermissionError)
	try:
		rules = seg.validate(data.get("rules") or {}, strict=True)
	except seg.SegmentError as e:
		frappe.throw(str(e))
	ents = _enterprises(props)
	if data.get("name"):
		row = _segment(data["name"], "crm.edit", props)
		if row.system_key:
			frappe.throw(_("Presets cannot be edited; save a copy instead."))
		doc = frappe.get_doc("TEX Guest Segment", row.name)
		old = {"segment_name": doc.segment_name, "rules": json.loads(doc.rules_json or "{}")}
	else:
		ent = data.get("enterprise") or (next(iter(ents)) if len(ents) == 1 else None)
		# a platform administrator may keep a segment at platform level (seen by platform admins only)
		if (ent or not scope.is_platform_admin()) and ent not in ents:
			frappe.throw(_("Choose the enterprise this segment belongs to."))
		doc = frappe.new_doc("TEX Guest Segment")
		doc.enterprise = ent
		old = None
	doc.segment_name = (data.get("segment_name") or "").strip()[:140] or frappe.throw(_("Name is required."))
	doc.description = (data.get("description") or "")[:500]
	doc.rules_json = json.dumps(rules, sort_keys=True)
	doc.is_dynamic = 1
	doc.save(ignore_permissions=True)
	audit("guest_segment.save", reference_doctype="TEX Guest Segment", reference_name=doc.name, old=old,
	      new={"segment_name": doc.segment_name, "enterprise": doc.enterprise, "rules": rules})
	return doc.name


def delete_segment(segment: str) -> None:
	row = _segment(segment, "crm.edit")
	if row.system_key:
		frappe.throw(_("Presets cannot be deleted."))
	frappe.delete_doc("TEX Guest Segment", row.name, ignore_permissions=True)
	audit("guest_segment.delete", reference_doctype="TEX Guest Segment", reference_name=row.name,
	      old={"segment_name": row.segment_name, "enterprise": row.enterprise})


def evaluate_segment(segment: str, *, property: str | None = None) -> dict:
	"""How many of the viewer's guests are in it now. A preset's count depends on who
	looks, so only a tenant's own segment keeps its count."""
	row = _segment(segment, "crm.view")
	res = list_guests(segment=row.name, property=property, limit=0)
	if not row.system_key and not property:
		frappe.db.set_value("TEX Guest Segment", row.name, {"member_count": res["total"],
		                                                   "last_evaluated": now_datetime()}, update_modified=False)
	return {"segment": row.name, "members": res["total"]}


def export_segment(segment: str, *, channel: str, property: str | None = None) -> list[dict]:
	"""Marketing export: only guests with consent for ``channel`` and not blacklisted."""
	props = [property] if property else sorted(scope.permitted_properties())
	if not props or not all(scope.has_capability("guest.export", p) for p in props):
		frappe.throw(_("Not permitted: {0}.").format("guest.export"), frappe.PermissionError)
	row = _segment(segment, "guest.export", set(props))
	field = {"Email": "tex_consent_email", "SMS": "tex_consent_sms", "WhatsApp": "tex_consent_whatsapp"}.get(channel)
	if not field:
		frappe.throw(_("Unknown channel."))
	res = list_guests(segment=row.name, property=property, consent=field, limit=100000)
	rows = [{"guest": r["name"], "first_name": r["first_name"], "last_name": r["last_name"],
	         "email": r["email"] if channel == "Email" else None,
	         "phone": r["phone"] if channel != "Email" else None, "language": r["tex_language"],
	         "country": r["tex_country"]} for r in res["rows"] if not r.get("blacklisted")]
	audit("guest.export", reference_doctype="TEX Guest Segment", reference_name=row.name, property=property,
	      new={"channel": channel, "rows": len(rows)})
	return rows


def ensure_system_segments() -> None:
	"""The presets every tenant sees; kept equal to ``segments.SYSTEM_SEGMENTS``."""
	for key, (label, rules) in seg.SYSTEM_SEGMENTS.items():
		payload = json.dumps(seg.validate(rules, strict=True), sort_keys=True)
		name = frappe.db.get_value("TEX Guest Segment", {"system_key": key})
		if name:
			frappe.db.set_value("TEX Guest Segment", name, {"segment_name": label, "rules_json": payload,
			                                                "enterprise": None}, update_modified=False)
			continue
		frappe.get_doc({"doctype": "TEX Guest Segment", "segment_name": label, "system_key": key, "is_dynamic": 1,
		                "rules_json": payload}).insert(ignore_permissions=True)


# ─── abandoned bookings (R-38) ───────────────────────────────────────────

STAGES = ("search", "room_view", "quote", "guest_details", "payment_started")


def detect_abandoned(now=None) -> dict:
	"""Scheduler: sessions that reached at least a quote, went quiet for
	ABANDON_AFTER_MINUTES and never booked. Contact data is kept only with the guest's
	marketing consent; otherwise the record is anonymous (value, dates, stage). A case is
	recovered when its session books, or when the booking it left at payment is paid later."""
	now = now or now_datetime()
	cutoff = add_to_date(now, minutes=-ABANDON_AFTER_MINUTES)
	since = add_to_date(now, days=-3)
	sessions = frappe.db.sql(
		"""SELECT session_id, site, MAX(occurred_at) last_at FROM `tabTEX Funnel Event`
		WHERE occurred_at >= %s AND session_id IS NOT NULL GROUP BY session_id, site HAVING last_at <= %s""",
		(since, cutoff), as_dict=True)
	created = recovered = 0
	for s in sessions:
		events = frappe.get_all("TEX Funnel Event", filters={"session_id": s.session_id},
		                        fields=["event", "payload", "property", "consent_marketing", "occurred_at"],
		                        order_by="occurred_at asc")
		names = [e.event for e in events]
		existing = frappe.db.get_value("TEX Abandoned Booking", {"session_id": s.session_id},
		                               ["name", "status"], as_dict=True)
		# booked in the session, or the booking left at payment was paid later (a payment link, a
		# retry): nothing was abandoned; an open case is recovered by that booking (G-81)
		booked = next((json.loads(e.payload or "{}").get("booking") for e in reversed(events)
		               if e.event == "booked"), None) if "booked" in names else _paid_later(events)
		if "booked" in names or booked:
			if existing and existing.status in ("Open", "Contacted"):
				frappe.db.set_value("TEX Abandoned Booking", existing.name,
				                    {"status": "Recovered", "recovered_booking": booked})
				recovered += 1
			continue
		if existing or not ({"quote", "guest_details", "payment_started"} & set(names)):
			continue
		stage = max((n for n in names if n in STAGES), key=STAGES.index)
		quote_ev = next((e for e in reversed(events) if e.event == "quote"), None)
		qp = json.loads(quote_ev.payload or "{}") if quote_ev else {}
		search_ev = next((e for e in reversed(events) if e.event == "search"), None)
		sp = json.loads(search_ev.payload or "{}") if search_ev else {}
		consent = any(e.consent_marketing for e in events)
		booking = next((json.loads(e.payload or "{}").get("booking") for e in reversed(events)
		                if e.event == "payment_started"), None)
		guest = email = phone = None
		if booking and consent:
			guest = frappe.db.get_value("TEX Booking", booking, "booker_guest")
			if guest:
				email, phone, agreed, sms, whatsapp = frappe.db.get_value(
					"Guest", guest, ["email", "phone", "tex_consent_email", "tex_consent_sms", "tex_consent_whatsapp"])
				if not (agreed or sms or whatsapp):
					# the profile's own consent decides: a tick in an anonymous booking that matched
					# an existing profile is only a request (ADR-046)
					consent, guest, email, phone = False, None, None, None
				else:
					# each contact only with its channel's consent (C-03): a guest who agreed to SMS or
					# WhatsApp alone is kept with the phone, never the e-mail
					email = email if agreed else None
					phone = phone if (sms or whatsapp) else None   # a phone is for SMS or WhatsApp (O-26)
		prop = next((e.property for e in events if e.property), None)
		if not prop and qp.get("quote"):
			prop = frappe.db.get_value("TEX Quote", qp["quote"], "property")
		frappe.get_doc({
			"doctype": "TEX Abandoned Booking", "property": prop, "site": s.site, "session_id": s.session_id,
			"stage_reached": stage, "status": "Open", "guest": guest if consent else None,
			"email": email if consent else None, "phone": phone if consent else None,
			"consent_marketing": 1 if consent else 0,
			"value": D(qp.get("total") or 0), "currency": qp.get("currency"),
			"check_in": sp.get("check_in"), "check_out": sp.get("check_out"),
			# the quote leads to the booking and its booker: kept only with the contact data (ADR-056)
			"quote": qp.get("quote") if consent and qp.get("quote") and frappe.db.exists("TEX Quote", qp.get("quote"))
			else None,
			"last_event_at": s.last_at}).insert(ignore_permissions=True)
		created += 1
	# a case left at payment is recovered when its booking is paid, however long after its session
	# went quiet (a payment link lives up to 60 days)
	for a in frappe.get_all("TEX Abandoned Booking", filters=[
			["status", "in", ["Open", "Contacted"]], ["stage_reached", "=", "payment_started"],
			["last_event_at", "is", "set"], ["last_event_at", ">=", add_to_date(now, days=-RECOVERY_DAYS)]],
	                        fields=["name", "session_id"]):
		booked = _paid_later(frappe.get_all("TEX Funnel Event", filters={"session_id": a.session_id,
		                                                                  "event": "payment_started"},
		                                    fields=["event", "payload"], order_by="occurred_at asc"))
		if booked:
			frappe.db.set_value("TEX Abandoned Booking", a.name, {"status": "Recovered", "recovered_booking": booked})
			recovered += 1
	return {"created": created, "recovered": recovered}


# a booking whose payment arrived: the guest came back and completed it
PAID_BOOKING = ("Confirmed", "Partially Cancelled")


def _paid_later(events) -> str | None:
	"""The booking a session left at the payment step, when it has been paid since."""
	for e in reversed(events):
		if e.event != "payment_started":
			continue
		booking = json.loads(e.payload or "{}").get("booking")
		if booking and frappe.db.get_value("TEX Booking", booking, "status") in PAID_BOOKING:
			return booking
	return None


def abandoned(property: str, *, status: str | None = None, days: int = 30) -> list[dict]:
	"""The hotel's abandoned bookings. Contact data is shown only while the guest profile's own
	marketing consent holds (withdrawn later: the case stays, anonymous; ADR-046, ADR-056), each contact
	with its channel's (C-03, ADR-076): the e-mail while the guest agrees to marketing e-mail, the phone
	while they agree to SMS or WhatsApp (``phone_channels`` says which; TEX records no consent to be
	called, so it is never offered as a call, O-26)."""
	scope.require("crm.view", property)
	filters = [["property", "=", property], ["last_event_at", "is", "set"],
	           ["last_event_at", ">=", add_to_date(now_datetime(), days=-days)]]
	if status:
		filters.append(["status", "=", status])
	rows = frappe.get_all("TEX Abandoned Booking", filters=filters,
	                      fields=["name", "site", "stage_reached", "status", "guest", "email", "phone",
	                              "consent_marketing", "value", "currency", "check_in", "check_out",
	                              "last_event_at", "recovered_booking"], order_by="last_event_at desc", limit=500)
	guests = {r.guest for r in rows if r.guest}
	agreed = {g.name: g for g in frappe.get_all(
		"Guest", filters={"name": ("in", list(guests))},
		fields=["name", "tex_consent_email", "tex_consent_sms", "tex_consent_whatsapp"])
		if g.tex_consent_email or g.tex_consent_sms or g.tex_consent_whatsapp} if guests else {}
	for r in rows:
		if not (r.consent_marketing and r.guest in agreed):
			# anonymous, the profile link and the booking that recovered it included: each leads to the
			# person (ADR-056 and its second review)
			r["email"] = r["phone"] = r["guest"] = r["recovered_booking"] = None
			r["consent_marketing"] = 0
			r["phone_channels"] = []
		else:
			g = agreed[r.guest]
			r["phone_channels"] = [c for c, on in (("SMS", g.tex_consent_sms), ("WhatsApp", g.tex_consent_whatsapp)) if on]
			if not r["phone_channels"]:
				r["phone"] = None
			if not g.tex_consent_email:
				r["email"] = None                   # the phone's consent never shows the e-mail (C-03)
		r["value"] = to_str(from_db(r["value"], r["currency"] or "EUR"))
		for k in ("check_in", "check_out", "last_event_at"):
			r[k] = str(r[k]) if r[k] else None
	return rows


def email_hash(email: str | None) -> str | None:
	"""The funnel's pseudonymous key of an e-mail address (``public._track``)."""
	email = (email or "").strip().lower()
	return hashlib.sha256(email.encode()).hexdigest() if email else None


# A withdrawal's statements (ADR-056 second review). The rows it clears are read through an index and
# written by primary key, so a withdrawal locks those rows only: never a scan of the funnel, which every
# visitor's tracking writes to inside a booking's transaction. The cases are read with a lock, so a case
# the scheduler writes while the withdrawal runs is seen (and cleared) once written.
CASES_OF_GUEST = "SELECT name, session_id FROM `tabTEX Abandoned Booking` WHERE guest = %(guest)s FOR UPDATE"
FUNNEL_BY_HASH = "SELECT name FROM `tabTEX Funnel Event` WHERE email_hash IN %(hashes)s"
FUNNEL_BY_SESSION = "SELECT name, email_hash FROM `tabTEX Funnel Event` WHERE session_id IN %(sessions)s"
FORGET_CASES = """UPDATE `tabTEX Abandoned Booking` SET guest = NULL, email = NULL, phone = NULL, quote = NULL,
	consent_marketing = 0 WHERE name IN %(names)s"""
FORGET_EVENTS = "UPDATE `tabTEX Funnel Event` SET email_hash = NULL WHERE name IN %(names)s"
FORGET_PHONE = "UPDATE `tabTEX Abandoned Booking` SET phone = NULL WHERE name IN %(names)s AND phone IS NOT NULL"
FORGET_EMAIL = "UPDATE `tabTEX Abandoned Booking` SET email = NULL WHERE name IN %(names)s AND email IS NOT NULL"
BATCH = 500


def _chunks(values) -> list[tuple]:
	values = sorted(v for v in values if v)
	return [tuple(values[i:i + BATCH]) for i in range(0, len(values), BATCH)]


def forget_contact(guest: str, emails=(), *, keep_phone: bool = False) -> int:
	"""The guest withdrew their last marketing consent (or cleared their e-mail or phone, or was erased):
	their abandoned cases become anonymous (no profile, e-mail, phone or quote; no consent) and their
	funnel events lose the e-mail hash, those of the cases' sessions and those of the guest's addresses
	(ADR-056 review). ``keep_phone``: they withdrew marketing e-mail consent while SMS or WhatsApp still
	holds (C-03): the cases lose only the e-mail, the funnel its hashes. The profile itself, its stays and
	its consent history stay. → the cases and events changed."""
	cases = frappe.db.sql(CASES_OF_GUEST, {"guest": guest}, as_dict=True)
	events = set()
	hashes = {h for h in (email_hash(e) for e in emails) if h}
	for chunk in _chunks(hashes):
		events |= set(frappe.db.sql(FUNNEL_BY_HASH, {"hashes": chunk}, pluck=True))
	for chunk in _chunks({c.session_id for c in cases}):
		events |= {name for name, h in frappe.db.sql(FUNNEL_BY_SESSION, {"sessions": chunk}) if h}
	for chunk in _chunks({c.name for c in cases}):
		frappe.db.sql(FORGET_EMAIL if keep_phone else FORGET_CASES, {"names": chunk})
	for chunk in _chunks(events):
		frappe.db.sql(FORGET_EVENTS, {"names": chunk})
	return len(cases) + len(events)


def forget_phone(guest: str) -> int:
	"""The guest no longer agrees to SMS or WhatsApp: their abandoned cases lose the phone (the e-mail and the
	rest stay while the e-mail consent holds). The cases are read with a lock, as ``forget_contact`` does, so
	one written while this runs is seen. → the cases changed."""
	cases = [c.name for c in frappe.db.sql(CASES_OF_GUEST, {"guest": guest}, as_dict=True)]
	for chunk in _chunks(cases):
		frappe.db.sql(FORGET_PHONE, {"names": chunk})
	return len(cases)


def lock_guest(guest: str | None, *, share: bool = False) -> bool:
	"""Lock a guest profile's row (exclusive, or ``share``d) and say whether it exists now. A locking read
	sees what is committed now, not the request's snapshot: a profile merged into another (or removed)
	since the request began is gone here. Whoever writes a link to a profile locks it first, so a merge,
	which locks both profiles, and a link to the profile it deletes never pass each other (third review
	of ADR-056)."""
	if not guest:
		return False
	return bool(frappe.db.sql(f"SELECT name FROM `tabGuest` WHERE name = %s {'LOCK IN SHARE MODE' if share else 'FOR UPDATE'}",
	                          guest))  # nosemgrep -- a constant clause


def require_live_guest(guest: str | None, *, share: bool = False) -> None:
	"""``lock_guest``, refusing a profile that is gone (merged into another, or removed, meanwhile)."""
	if guest and not lock_guest(guest, share=share):
		frappe.throw(_("Guest {0} no longer exists: it was merged into another profile or removed. Reload and "
		               "choose the guest again.").format(guest), frappe.DoesNotExistError)


def guest_validate(doc, method=None) -> None:
	"""``Guest.validate``, whoever saves: a consent change made outside the CRM and the booking flows
	(the Desk form, REST, a merge, an erasure) is stamped as theirs are (when, and how: ADR-046) and
	audited once saved (``guest_on_update``). The CRM and the booking flows record their own."""
	if doc.flags.get("tex_consent_recorded"):
		return
	before = doc.get_doc_before_save()
	changed = {f: bool(doc.get(f)) for f in CONSENT if bool(doc.get(f)) != bool(before.get(f) if before else 0)}
	if not changed:
		return
	from kamra.tex.security.audit import source_of_request

	how = (doc.flags.get("tex_consent_source") or source_of_request())[:140]
	doc.tex_consent_updated_at = now_datetime()
	doc.tex_consent_source = how
	doc.flags.tex_consent_audit = (changed, how)


def guest_on_update(doc, method=None) -> None:
	"""``Guest.on_update``, whoever saves (the CRM, the Desk form, REST): a consent change made outside
	the CRM is audited; an e-mail or phone cleared, or the last marketing consent withdrawn, makes the
	guest's abandoned cases and funnel data anonymous (ADR-056 and its second review); marketing e-mail
	consent withdrawn while SMS or WhatsApp holds takes the e-mail off the cases and the hashes off the
	funnel (C-03); the last SMS or WhatsApp consent withdrawn while e-mail holds takes the phone off."""
	pending = doc.flags.pop("tex_consent_audit", None)
	if pending:
		audit("guest.consent", reference_doctype="Guest", reference_name=doc.name, new=pending[0], reason=pending[1])
	before = doc.get_doc_before_save()
	if not before:
		return
	phone_ok = bool(doc.get("tex_consent_sms") or doc.get("tex_consent_whatsapp"))
	withdrawn = before.get("tex_consent_email") and not doc.get("tex_consent_email")
	cleared = any(before.get(f) and not doc.get(f) for f in ("email", "phone"))
	phone_withdrawn = (before.get("tex_consent_sms") or before.get("tex_consent_whatsapp")) and not phone_ok
	if cleared or ((withdrawn or phone_withdrawn) and not (phone_ok or doc.get("tex_consent_email"))):
		forget_contact(doc.name, emails={before.get("email"), doc.get("email")})
	elif withdrawn:                                 # SMS or WhatsApp still holds: the phone stays (C-03)
		forget_contact(doc.name, emails={before.get("email"), doc.get("email")}, keep_phone=True)
	elif phone_withdrawn:
		forget_phone(doc.name)                      # no SMS or WhatsApp consent left: no phone on the cases (O-26)


def erase_traces(guest: str, alias: str, *, emails=(), audit_event: bool = True) -> dict:
	"""Right to erasure (``kamra.api.anonymize_guest``), after the profile itself was blanked and its
	consent withdrawn: its cases and funnel data are forgotten; its bookings and their payment links keep
	the alias instead of the booker's name, e-mail and phone; the profile's change history goes, and that
	of its bookings, links and stays keeps which field changed, never the value (ADR-056 second review);
	the copies of the profiles merged into it (Deleted Documents, ``MERGE_COPY_DAYS``) go too (third
	review); its loyalty memberships end (C-04). Re-runnable: → what it changed (``changed``: 0 when nothing
	was left); ``audit_event``: ``guest.erase`` is audited (p48 audits only a run that changed something)."""
	from kamra.tex.security.internals import mask_history

	forgotten = forget_contact(guest, emails=emails)
	bookings = frappe.get_all("TEX Booking", filters={"booker_guest": guest}, pluck="name")
	links = frappe.get_all("TEX Payment Link", filters={"booking": ("in", bookings)}, pluck="name") if bookings else []
	named = 0
	for chunk in _chunks(bookings):
		stale = frappe.db.sql("""SELECT name FROM `tabTEX Booking` WHERE name IN %(n)s AND (IFNULL(booker_name, '') != %(a)s
			OR IFNULL(booker_email, '') != '' OR IFNULL(booker_phone, '') != '')""", {"a": alias, "n": chunk}, pluck=True)
		if stale:
			frappe.db.sql("""UPDATE `tabTEX Booking` SET booker_name = %(a)s, booker_email = NULL, booker_phone = NULL
				WHERE name IN %(n)s""", {"a": alias, "n": tuple(stale)})
			named += len(stale)
	for chunk in _chunks(links):
		stale = frappe.db.sql("""SELECT name FROM `tabTEX Payment Link` WHERE name IN %(n)s
			AND (IFNULL(guest_name, '') != %(a)s OR IFNULL(guest_email, '') != '')""", {"a": alias, "n": chunk}, pluck=True)
		if stale:
			frappe.db.sql("UPDATE `tabTEX Payment Link` SET guest_name = %(a)s, guest_email = NULL WHERE name IN %(n)s",
			              {"a": alias, "n": tuple(stale)})
			named += len(stale)
	history = frappe.db.count("Version", {"ref_doctype": "Guest", "docname": guest})
	frappe.db.delete("Version", {"ref_doctype": "Guest", "docname": guest})
	masked = (mask_history("TEX Booking", bookings, ("booker_name", "booker_email", "booker_phone"))
	          + mask_history("TEX Payment Link", links, ("guest_name", "guest_email"))
	          + mask_history("Reservation", frappe.get_all("Reservation", filters={"guest": guest}, pluck="name"),
	                         ("guest_name", "booked_by_phone")))
	files = frappe.get_all("File", filters={"attached_to_doctype": "Guest", "attached_to_name": guest}, pluck="name")
	for f in files:
		frappe.delete_doc("File", f, ignore_permissions=True)            # identity documents
	copies = _drop_merge_copies(merged_into(guest))
	ended = loyalty.end_memberships(guest, "erased")    # no member prices for a profile nobody is (C-04)
	from kamra.tex.crm import members

	ended += members.end_sessions(guest)                # signed out on every booking site (ADR-078)
	out = {"bookings": len(bookings), "payment_links": len(links), "history_rows_masked": masked,
	       "history_rows_removed": history, "merge_copies_removed": copies, "memberships_ended": ended}
	out["changed"] = forgotten + named + history + masked + len(files) + copies + ended
	if audit_event:
		audit("guest.erase", reference_doctype="Guest", reference_name=guest, new=out)
	return out


def set_abandoned_status(name: str, status: str, note: str | None = None) -> None:
	prop = frappe.db.get_value("TEX Abandoned Booking", name, "property")
	scope.require("crm.edit", prop)
	if status not in ("Open", "Contacted", "Recovered", "Dismissed"):
		frappe.throw(_("Unknown status."))
	frappe.db.set_value("TEX Abandoned Booking", name, "status", status)
	audit("abandoned.status", reference_doctype="TEX Abandoned Booking", reference_name=name, property=prop,
	      new={"status": status}, reason=note)


def _commit() -> None:
	"""A scheduler job's batch is its own unit of work in production; tests keep one transaction."""
	if not frappe.flags.in_test:
		frappe.db.commit()  # nosemgrep: frappe-manual-commit -- scheduler job batch boundary


# The purge (third review of ADR-056, M-6): old events are read through ``tex_funnel_time_session`` without
# a lock and deleted by primary key, one statement per event, PURGE_BATCH at a time, each batch committed. A
# DELETE on ``occurred_at`` without that index locked every funnel row and gap until the job ended, and every
# booking's tracking waited behind it. One DELETE naming the whole batch (``name IN``) is no better where the
# batch is most of the funnel (a new or quiet site: 3 events of 5, 400 of 500): the optimizer reads it as a
# scan, which locks every row and gap until the batch commits. An equality on the primary key is read through
# it whatever the table holds, so the purge locks the rows it deletes and nothing else.
PURGE_BATCH = 500
PURGE_OLD = """SELECT name FROM `tabTEX Funnel Event` WHERE occurred_at < %(cutoff)s
	ORDER BY occurred_at LIMIT %(n)s"""
PURGE_EVENT = "DELETE FROM `tabTEX Funnel Event` WHERE name = %(name)s"


FUNNEL_RETENTION_DAYS = 180         # funnel events older than this are deleted (reports refuse older windows)


def purge_funnel(days: int = FUNNEL_RETENTION_DAYS) -> int:
	"""Data minimisation: funnel events older than ``days`` are deleted, oldest first, in small committed
	batches (``PURGE_OLD``, ``PURGE_EVENT``). → how many."""
	cutoff = now_datetime() - timedelta(days=days)
	purged = 0
	while True:
		names = frappe.db.sql(PURGE_OLD, {"cutoff": cutoff, "n": PURGE_BATCH}, pluck=True)
		if not names:
			break
		for name in names:
			frappe.db.sql(PURGE_EVENT, {"name": name})
		_commit()
		purged += len(names)
		if len(names) < PURGE_BATCH:
			break
	return purged


# ─── duplicates and merging (ADR-056 second review) ─────────────────────

# what a merged profile takes from the duplicate where it has nothing itself
MERGE_FILL = ("first_name", "last_name", "email", "phone", "nationality", "date_of_birth", "gender", "id_type",
              "id_number", "address_line", "city", "guest_notes", "tex_language", "tex_country", "tex_market",
              "tex_preferences", "id_file", "address_proof_file")


def possible_duplicates(guest: str, props: set[str]) -> list[dict]:
	"""Other profiles the viewer may see, of the same enterprise (or none), with this profile's phone
	or e-mail: the identity rule keeps a shared phone apart (``booking.resolve_guest``), so staff
	decide, and merge (``merge_guests``)."""
	g = frappe.db.get_value("Guest", guest, ["email", "phone", "tex_enterprise"], as_dict=True)
	email, phone = (g.email or "").strip(), (g.phone or "").strip()
	if not (email or phone) or not props:
		return []
	cond, params = _visible_guest_sql(props)
	match = [c for c, v in (("g.email = %(email)s", email), ("g.phone = %(phone)s", phone)) if v]
	tenant = "AND IFNULL(g.tex_enterprise, '') IN %(tenants)s" if g.tex_enterprise else ""
	rows = frappe.db.sql(  # nosemgrep -- static conditions, values bound
		f"""SELECT g.name, g.full_name, g.email, g.phone FROM `tabGuest` g
		WHERE g.name != %(me)s AND ({" OR ".join(match)}) {tenant} AND {cond}
		ORDER BY g.creation ASC, g.name ASC LIMIT 20""",
		{**params, "me": guest, "email": email, "phone": phone, "tenants": (g.tex_enterprise or "", "")},
		as_dict=True)
	return [{"name": r.name, "full_name": r.full_name,
	         "match": [f for f, v in (("email", email), ("phone", phone)) if v and (r[f] or "").strip().lower() == v.lower()]}
	        for r in rows]


def merged_into(guest: str) -> list[str]:
	"""The profiles merged into this one (and into those, …): their consent record is this profile's."""
	names, frontier = [], [guest]
	for _depth in range(10):
		found = []
		for old in frappe.get_all("TEX Audit Event", filters={"action": "guest.merge", "reference_doctype": "Guest",
		                                                      "reference_name": ("in", frontier)}, pluck="old_value"):
			try:
				source = (json.loads(old or "{}") or {}).get("source")
			except (ValueError, AttributeError):
				source = None
			if source and source != guest and source not in names:
				found.append(source)
		if not found:
			break
		names += found
		frontier = found
	return names


def _guest_links() -> list[tuple[str, str]]:
	"""Every (DocType, field) linking to a Guest, from the meta (custom fields included)."""
	from frappe.model.rename_doc import get_link_fields

	return sorted({(f["parent"], f["fieldname"]) for f in get_link_fields("Guest")
	               if not f.get("issingle") and frappe.db.table_exists(f["parent"])})


# What Frappe links to any record by (DocType field, name field): ``delete_doc`` deletes or unlinks these
# rows when the record goes, so a merge moves them first (third review of ADR-056, M-1). The audit trail is
# immutable and keeps the duplicate's name (``merged_into`` reads through the merge event).
DYNAMIC_LINKS = (("Comment", "reference_doctype", "reference_name"),
                 ("Communication", "reference_doctype", "reference_name"),
                 ("Communication Link", "link_doctype", "link_name"),
                 ("ToDo", "reference_type", "reference_name"),
                 ("Activity Log", "reference_doctype", "reference_name"),
                 ("Activity Log", "timeline_doctype", "timeline_name"),
                 ("DocShare", "share_doctype", "share_name"),
                 ("Document Follow", "ref_doctype", "ref_docname"),
                 ("Notification Log", "document_type", "document_name"),
                 ("View Log", "reference_doctype", "reference_name"),
                 ("Email Unsubscribe", "reference_doctype", "reference_name"),
                 ("Tag Link", "document_type", "document_name"),
                 ("File", "attached_to_doctype", "attached_to_name"),
                 ("Version", "ref_doctype", "docname"))
KEEP_LINKS = frozenset({"TEX Audit Event", "TEX Audit Scope"})


def _dynamic_links() -> list[tuple[str, str, str]]:
	"""Every (DocType, DocType field, name field) that may name a Guest: Frappe's own (``DYNAMIC_LINKS``) and
	any Dynamic Link found in the meta, but the audit trail."""
	from frappe.model.dynamic_links import get_dynamic_link_map

	found = {(dt, dtf, nf) for dt, dtf, nf in DYNAMIC_LINKS
	         if frappe.db.table_exists(dt) and frappe.db.has_column(dt, dtf) and frappe.db.has_column(dt, nf)}
	for df in get_dynamic_link_map().get("Guest", []):
		if df.parent not in KEEP_LINKS and not frappe.get_meta(df.parent).issingle:
			found.add((df.parent, df.options, df.fieldname))
	return sorted(found)


def _records_hotels(guests: tuple[str, ...], links=None) -> tuple[set[str], set[str]]:
	"""(the hotels any record of these profiles belongs to, the DocTypes holding a record of them that
	names no hotel). Locking reads: what is committed now, rows committed after this request began
	included, and none of them can change until the merge ends (third review of ADR-056, H-1)."""
	hotels, unknown = set(), set()
	for parent, field in _guest_links() if links is None else links:
		if frappe.db.has_column(parent, "property"):
			hotels |= set(frappe.db.sql(  # nosemgrep -- identifiers from the meta, values bound
				f"""SELECT DISTINCT property FROM `tab{parent}` WHERE `{field}` IN %(g)s AND IFNULL(property, '') != ''
				LOCK IN SHARE MODE""", {"g": guests}, pluck=True))
		elif frappe.db.sql(f"SELECT name FROM `tab{parent}` WHERE `{field}` IN %(g)s LIMIT 1 LOCK IN SHARE MODE",  # nosemgrep
		                   {"g": guests}):
			unknown.add(parent)
	return hotels, unknown


def _repoint(source: str, target: str, links=None, dynamic=None) -> dict[str, list[str]]:
	"""Every link to ``source`` now names ``target``: its rows read with a lock (what is committed now; a
	link written meanwhile waits for the merge), then written by primary key. → the records moved, by
	DocType (the audit names them: third review, M-3)."""
	moved: dict[str, list[str]] = {}
	for parent, field in _guest_links() if links is None else links:
		names = frappe.db.sql(f"SELECT name FROM `tab{parent}` WHERE `{field}` = %(g)s FOR UPDATE",  # nosemgrep
		                      {"g": source}, pluck=True)
		for chunk in _chunks(names):
			frappe.db.sql(f"UPDATE `tab{parent}` SET `{field}` = %(t)s WHERE name IN %(n)s",  # nosemgrep
			              {"t": target, "n": chunk})
		if names:
			moved.setdefault(parent, []).extend(names)
	# comments, mail, tasks, shares, activity, attachments and the change history follow the profile
	for doctype, dt_field, name_field in _dynamic_links() if dynamic is None else dynamic:
		names = frappe.db.sql(  # nosemgrep -- identifiers from the meta or a constant list, values bound
			f"SELECT name FROM `tab{doctype}` WHERE `{dt_field}` = 'Guest' AND `{name_field}` = %(g)s FOR UPDATE",
			{"g": source}, pluck=True)
		for chunk in _chunks(names):
			frappe.db.sql(f"UPDATE `tab{doctype}` SET `{name_field}` = %(t)s WHERE name IN %(n)s",  # nosemgrep
			              {"t": target, "n": chunk})
		if names:
			moved.setdefault(doctype, []).extend(n for n in names if n not in moved.get(doctype, []))
	return moved


def _assert_unlinked(source: str, links=None, dynamic=None) -> None:
	"""Nothing points at ``source`` any more, read with a shared lock (committed rows included): a link
	written meanwhile fails the merge, which rolls back, rather than point at a deleted profile."""
	for parent, field in _guest_links() if links is None else links:
		left = frappe.db.sql(f"SELECT name FROM `tab{parent}` WHERE `{field}` = %(g)s LIMIT 1 LOCK IN SHARE MODE",  # nosemgrep
		                     {"g": source})
		if left:
			frappe.throw(_("{0} {1} still names the duplicate: nothing was merged. Please try again.").format(
				_(parent), left[0][0]))
	for doctype, dt_field, name_field in _dynamic_links() if dynamic is None else dynamic:
		left = frappe.db.sql(  # nosemgrep -- identifiers from the meta or a constant list, values bound
			f"""SELECT name FROM `tab{doctype}` WHERE `{dt_field}` = 'Guest' AND `{name_field}` = %(g)s LIMIT 1
			LOCK IN SHARE MODE""", {"g": source})
		if left:
			frappe.throw(_("{0} {1} still names the duplicate: nothing was merged. Please try again.").format(
				_(doctype), left[0][0]))


def _lock_pair(source: str, target: str) -> tuple[str, str]:
	"""Both profiles locked, in name order (two merges of the same profiles never deadlock), read as they
	are committed now; → their names as stored. A name typed in another case (or with spaces) is the same
	profile; a profile that is gone (merged elsewhere meanwhile) is not found (third review, H-1)."""
	rows = frappe.db.sql("""SELECT name, name = %(s)s AS s, name = %(t)s AS t FROM `tabGuest`
		WHERE name IN %(g)s ORDER BY name FOR UPDATE""", {"s": source, "t": target, "g": (source, target)}, as_dict=True)
	if any(r.s and r.t for r in rows) or source.casefold() == target.casefold():
		frappe.throw(_("Pick two different profiles to merge."))
	src = [r.name for r in rows if r.s]
	dst = [r.name for r in rows if r.t]
	if len(src) != 1 or len(dst) != 1:
		frappe.throw(_("Guest not found: it may have been merged into another profile meanwhile."),
		             frappe.DoesNotExistError)
	return src[0], dst[0]


# the duplicate is kept as a Deleted Document (platform administrators only) for this many days after a
# merge, so a merge can be reconstructed and undone by hand; then the daily job removes it, and an erasure
# of the profile it went into removes it at once (third review of ADR-056, M-3; owner decision to confirm)
MERGE_COPY_DAYS = 90


def merge_guests(source: str, target: str, *, checked: bool = False) -> dict:
	"""Merge the duplicate profile ``source`` into ``target`` (ADR-056 second and third reviews).

	Who: staff who may edit both profiles (``crm.edit``) and may edit guests at every hotel either
	profile has a record at: its stays, bookings, communications, cases and loyalty entries go with it;
	platform administrators. ``checked``: the legacy PMS endpoint decided whether the caller sees both
	profiles by its own rule (``kamra.authz``); the hotels of every record are still checked here. A
	record of a DocType that names no hotel is merged by a platform administrator only. Both profiles
	belong to one enterprise (or to none); neither is erased (``tex_erased_at``).

	Concurrency: both profiles are locked first, and everything the merge decides on or moves is read
	with a lock, so it sees what is committed now (the request's snapshot may be older): a booking of the
	duplicate committed meanwhile is moved and its hotel checked; a duplicate merged elsewhere meanwhile
	is not found. Whoever writes a link to a profile locks it first (``lock_guest``).

	What moves: every link to the duplicate (from the meta: TEX and legacy DocTypes, custom fields), its
	comments, mail, tasks, shares, activity, attachments and history; its loyalty entries, so the balance
	is one and the tier follows the merged lifetime; its memberships, one per program (where both have one,
	the one changed last stays, C-04). The profile that stays keeps its own data and takes
	the duplicate's where it has none; VIP and blacklist are kept if either has them. Consent is the
	stricter of the two: a channel stays consented only when both profiles consented to it. The duplicate
	is then deleted and kept as a Deleted Document for ``MERGE_COPY_DAYS``; the merge is audited with
	every record it moved (names, no contact data)."""
	source, target = (source or "").strip(), (target or "").strip()
	if not source or not target:
		frappe.throw(_("Pick two different profiles to merge."))
	source, target = _lock_pair(source, target)
	admin = scope.is_platform_admin()
	if not (checked or admin):
		require_guest(target, "crm.edit")
		require_guest(source, "crm.edit")
	src = frappe.get_doc("Guest", source, for_update=True)
	dst = frappe.get_doc("Guest", target, for_update=True)
	if src.get("tex_erased_at") or dst.get("tex_erased_at"):
		frappe.throw(_("An erased profile is never merged: its stays stay anonymous, and nothing is copied into it."))
	links, dynamic = _guest_links(), _dynamic_links()
	hotels, unknown = _records_hotels((source, target), links)
	if not admin:
		if unknown:
			frappe.throw(_("These profiles have records that name no hotel ({0}): a platform administrator can "
			               "merge them.").format(", ".join(_(d) for d in sorted(unknown))), frappe.PermissionError)
		allowed = {p for p in scope.permitted_properties() if scope.has_capability("crm.edit", p)}
		if not hotels <= allowed:
			frappe.throw(_("These profiles have records at hotels where you may not edit guests; someone who may "
			               "edit guests at all of them can merge them."), frappe.PermissionError)
	ents = {e for e in (src.tex_enterprise, dst.tex_enterprise) if e} | _enterprises(hotels)
	if len(ents) > 1:
		frappe.throw(_("Profiles of different enterprises cannot be merged."))
	before = {g.name: {f: bool(g.get(f)) for f in CONSENT} for g in (src, dst)}
	dropped = loyalty.merge_memberships(source, target)   # one membership per program (C-04); the rest move below
	moved = _repoint(source, target, links, dynamic)
	filled = [f for f in MERGE_FILL if not dst.get(f) and src.get(f)]
	for f in filled:
		dst.set(f, src.get(f))
	if src.vip and not dst.vip:
		dst.vip = 1
		filled.append("vip")
	if src.blacklisted and not dst.blacklisted:
		dst.blacklisted, dst.blacklist_reason = 1, dst.blacklist_reason or src.blacklist_reason
		filled.append("blacklisted")
	tags = [t for t in dict.fromkeys(x.strip() for x in f"{dst.tex_tags or ''},{src.tex_tags or ''}".split(","))
	        if t]
	if ",".join(tags) != (dst.tex_tags or ""):
		dst.tex_tags = ",".join(tags)
	if ents and not dst.tex_enterprise:
		dst.tex_enterprise = next(iter(ents))
		filled.append("tex_enterprise")
	consent = {f: before[source][f] and before[target][f] for f in CONSENT}
	for f, v in consent.items():
		dst.set(f, 1 if v else 0)
	dst.flags.tex_consent_source = "merge"             # a change is stamped and audited (``guest_validate``)
	dst.save(ignore_permissions=True)
	# the duplicate's cases came with the links: each keeps the contact the merged consent allows (C-03)
	phone_ok = consent["tex_consent_sms"] or consent["tex_consent_whatsapp"]
	if not (consent["tex_consent_email"] or phone_ok):
		forget_contact(target, emails={src.email, dst.email})          # no consent: no contact data
	else:
		if not consent["tex_consent_email"]:
			forget_contact(target, emails={src.email, dst.email}, keep_phone=True)
		if not phone_ok:
			forget_phone(target)                                        # a phone is for SMS or WhatsApp (O-26)
	for doctype in ("Reservation", "Folio"):
		if moved.get(doctype) and frappe.db.has_column(doctype, "guest_name"):
			for chunk in _chunks(moved[doctype]):
				frappe.db.sql(f"UPDATE `tab{doctype}` SET guest_name = %(n)s WHERE name IN %(r)s",  # nosemgrep
				              {"n": dst.full_name, "r": chunk})
	_assert_unlinked(source, links, dynamic)
	frappe.delete_doc("Guest", source, ignore_permissions=True)
	copy = frappe.db.get_value("Deleted Document", {"deleted_doctype": "Guest", "deleted_name": source}, "name",
	                           order_by="creation desc")
	if copy:
		# the duplicate as it is committed now (read with its lock), not as the request's snapshot saw it
		frappe.db.set_value("Deleted Document", copy, "data", src.as_json(), update_modified=False)
	loyalty._sync_guest(target)
	refresh_guest_stats(target)
	counts = {dt: len(names) for dt, names in sorted(moved.items())}
	records = {dt: sorted(names) for dt, names in sorted(moved.items())}
	audit("guest.merge", reference_doctype="Guest", reference_name=target, hotels=sorted(hotels),
	      enterprise=next(iter(ents)) if ents else None,
	      old={"source": source, "consent": before},
	      new={"moved": counts, "records": records, "filled": sorted(filled), "consent": consent, "copy": copy,
	           "copy_kept_days": MERGE_COPY_DAYS, "memberships_dropped": dropped})
	return {"target": target, "source": source, "moved": counts, "records": records, "filled": sorted(filled),
	        "consent": consent, "memberships_dropped": dropped}


def _drop_merge_copies(sources) -> int:
	"""Delete the Deleted Document copies of these merged profiles. → how many."""
	names = frappe.get_all("Deleted Document", filters={"deleted_doctype": "Guest",
	                                                    "deleted_name": ("in", list(sources) or [""])}, pluck="name")
	for chunk in _chunks(names):
		frappe.db.sql("DELETE FROM `tabDeleted Document` WHERE name IN %(n)s", {"n": chunk})
	return len(names)


def purge_merge_copies(days: int | None = None) -> int:
	"""Scheduler (daily): the copies of profiles merged more than ``MERGE_COPY_DAYS`` ago are deleted
	(the merge events keep which records moved, never the duplicate's contact data). → how many."""
	before = add_days(now_datetime(), -(days if days is not None else MERGE_COPY_DAYS))
	sources = set()
	# an event of unknown time is never old enough: a deleted copy cannot come back
	for old in frappe.get_all("TEX Audit Event", filters=[["action", "=", "guest.merge"], ["event_time", "is", "set"],
	                                                      ["event_time", "<", before]], pluck="old_value"):
		try:
			source = (json.loads(old or "{}") or {}).get("source")
		except (ValueError, AttributeError):
			source = None
		if source:
			sources.add(source)
	return _drop_merge_copies(sources) if sources else 0
