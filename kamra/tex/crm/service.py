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
from frappe.utils import add_days, add_to_date, getdate, now_datetime, nowdate

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
				"""SELECT guest, status, check_in_date, check_out_date, children, tex_sale_at, creation, cancelled_on,
				          tex_total_amount, amount_after_tax, tex_currency
				   FROM `tabReservation` WHERE guest IN %(g)s AND property IN %(p)s""",
					{"g": tuple(chunk), "p": tuple(props)}, as_dict=True):
				if not (r.check_in_date and r.check_out_date):
					continue
				ccy = r.tex_currency or None
				stays[r.guest].append(seg.StayFact(
					r.status, getdate(r.check_in_date), getdate(r.check_out_date), int(r.children or 0),
					getdate(r.tex_sale_at or r.creation), getdate(r.cancelled_on) if r.cancelled_on else None,
					from_db(r.tex_total_amount or r.amount_after_tax or 0, ccy or "EUR"), ccy))
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
	                               "tex_booking", "tex_sales_channel", "tex_market", "cancellation_fee"],
	                       order_by="check_in_date desc", limit=200)
	for s in stays:
		s["check_in_date"], s["check_out_date"] = str(s["check_in_date"]), str(s["check_out_date"])
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
	member_of = [{"name": s.name, "segment_name": s.segment_name, "system_key": s.system_key}
	             for s in visible_segments(via) if s.rules_json and _safe_match(facts, s.rules_json, today)]
	# changes, and requests from online bookings that were not applied (ADR-046) for the hotel to confirm
	# a profile is shared inside an enterprise (ADR-040), its bookings and staff are not: entries
	# made at another hotel (a booking there, its staff) stay with that hotel; profile-level
	# changes (CRM, no hotel) are the consent record everyone sharing the profile relies on
	consent_log = [c for c in frappe.get_all(
		"TEX Audit Event", filters={"reference_doctype": "Guest", "reference_name": guest,
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
	        "consent_history": consent_log, "hotels": sorted(via)}


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
	                                                 "status": ("in", list(counts))},
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
	                                  fields=["property", "check_out_date", "tex_total_amount", "amount_after_tax",
	                                          "tex_currency"])
	        if r.check_out_date and getdate(r.check_out_date) <= today]
	hotel_ccy: dict[str, str | None] = {}
	by_ccy: dict[str, list] = {}
	for r in rows:
		if not r.tex_currency and r.property not in hotel_ccy:
			hotel_ccy[r.property] = frappe.db.get_value("Property", r.property, "currency")
		by_ccy.setdefault(r.tex_currency or hotel_ccy.get(r.property) or "EUR", []).append(r)
	main = min(by_ccy, key=lambda c: (-len(by_ccy[c]), c)) if by_ccy else None
	value = sum((from_db(r.tex_total_amount or r.amount_after_tax or 0, main) for r in by_ccy.get(main, [])), ZERO)
	frappe.db.set_value("Guest", guest, {"tex_stays": len(rows), "tex_lifetime_value": value,
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
				email, phone, agreed = frappe.db.get_value("Guest", guest, ["email", "phone", "tex_consent_email"])
				if not agreed:
					# the profile's own consent decides: a tick in an anonymous booking that matched
					# an existing profile is only a request (ADR-046)
					consent, guest, email, phone = False, None, None, None
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
	for a in frappe.get_all("TEX Abandoned Booking", filters={
			"status": ("in", ["Open", "Contacted"]), "stage_reached": "payment_started",
			"last_event_at": (">=", add_to_date(now, days=-RECOVERY_DAYS))}, fields=["name", "session_id"]):
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
	e-mail consent holds (withdrawn later: the case stays, anonymous; ADR-046, ADR-056)."""
	scope.require("crm.view", property)
	filters = {"property": property, "last_event_at": (">=", add_to_date(now_datetime(), days=-days))}
	if status:
		filters["status"] = status
	rows = frappe.get_all("TEX Abandoned Booking", filters=filters,
	                      fields=["name", "site", "stage_reached", "status", "guest", "email", "phone",
	                              "consent_marketing", "value", "currency", "check_in", "check_out",
	                              "last_event_at", "recovered_booking"], order_by="last_event_at desc", limit=500)
	guests = {r.guest for r in rows if r.guest}
	agreed = set(frappe.get_all("Guest", filters={"name": ("in", list(guests)), "tex_consent_email": 1},
	                            pluck="name")) if guests else set()
	for r in rows:
		if not (r.consent_marketing and r.guest in agreed):
			# anonymous, the profile link and the booking that recovered it included: each leads to the
			# person (ADR-056 and its second review)
			r["email"] = r["phone"] = r["guest"] = r["recovered_booking"] = None
			r["consent_marketing"] = 0
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
BATCH = 500


def _chunks(values) -> list[tuple]:
	values = sorted(v for v in values if v)
	return [tuple(values[i:i + BATCH]) for i in range(0, len(values), BATCH)]


def forget_contact(guest: str, emails=()) -> None:
	"""The guest withdrew marketing e-mail consent (or cleared their e-mail or phone, or was erased):
	their abandoned cases become anonymous (no profile, e-mail, phone or quote; no consent) and their
	funnel events lose the e-mail hash, those of the cases' sessions and those of the guest's addresses
	(ADR-056 review). The profile itself, its stays and its consent history stay."""
	cases = frappe.db.sql(CASES_OF_GUEST, {"guest": guest}, as_dict=True)
	events = set()
	hashes = {h for h in (email_hash(e) for e in emails) if h}
	for chunk in _chunks(hashes):
		events |= set(frappe.db.sql(FUNNEL_BY_HASH, {"hashes": chunk}, pluck=True))
	for chunk in _chunks({c.session_id for c in cases}):
		events |= {name for name, h in frappe.db.sql(FUNNEL_BY_SESSION, {"sessions": chunk}) if h}
	for chunk in _chunks({c.name for c in cases}):
		frappe.db.sql(FORGET_CASES, {"names": chunk})
	for chunk in _chunks(events):
		frappe.db.sql(FORGET_EVENTS, {"names": chunk})


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
	the CRM is audited; a withdrawal of marketing e-mail consent, or an e-mail or phone cleared, makes
	the guest's abandoned cases and funnel data anonymous (ADR-056 and its second review)."""
	pending = doc.flags.pop("tex_consent_audit", None)
	if pending:
		audit("guest.consent", reference_doctype="Guest", reference_name=doc.name, new=pending[0], reason=pending[1])
	before = doc.get_doc_before_save()
	if not before:
		return
	withdrawn = before.get("tex_consent_email") and not doc.get("tex_consent_email")
	cleared = any(before.get(f) and not doc.get(f) for f in ("email", "phone"))
	if withdrawn or cleared:
		forget_contact(doc.name, emails={before.get("email"), doc.get("email")})


def erase_traces(guest: str, alias: str, *, emails=()) -> dict:
	"""Right to erasure (``kamra.api.anonymize_guest``), after the profile itself was blanked and its
	consent withdrawn: its cases and funnel data are forgotten; its bookings and their payment links keep
	the alias instead of the booker's name, e-mail and phone; the profile's change history goes, and that
	of its bookings, links and stays keeps which field changed, never the value (ADR-056 second review)."""
	from kamra.tex.security.internals import mask_history

	forget_contact(guest, emails=emails)
	bookings = frappe.get_all("TEX Booking", filters={"booker_guest": guest}, pluck="name")
	links = frappe.get_all("TEX Payment Link", filters={"booking": ("in", bookings)}, pluck="name") if bookings else []
	for chunk in _chunks(bookings):
		frappe.db.sql("""UPDATE `tabTEX Booking` SET booker_name = %(a)s, booker_email = NULL, booker_phone = NULL
			WHERE name IN %(n)s""", {"a": alias, "n": chunk})
	for chunk in _chunks(links):
		frappe.db.sql("UPDATE `tabTEX Payment Link` SET guest_name = %(a)s, guest_email = NULL WHERE name IN %(n)s",
		              {"a": alias, "n": chunk})
	frappe.db.delete("Version", {"ref_doctype": "Guest", "docname": guest})
	masked = (mask_history("TEX Booking", bookings, ("booker_name", "booker_email", "booker_phone"))
	          + mask_history("TEX Payment Link", links, ("guest_name", "guest_email"))
	          + mask_history("Reservation", frappe.get_all("Reservation", filters={"guest": guest}, pluck="name"),
	                         ("guest_name", "booked_by_phone")))
	for f in frappe.get_all("File", filters={"attached_to_doctype": "Guest", "attached_to_name": guest}, pluck="name"):
		frappe.delete_doc("File", f, ignore_permissions=True)            # identity documents
	out = {"bookings": len(bookings), "payment_links": len(links), "history_rows_masked": masked}
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


def purge_funnel(days: int = 180) -> int:
	"""Data minimisation: funnel events older than ``days`` are deleted."""
	cutoff = now_datetime() - timedelta(days=days)
	n = frappe.db.count("TEX Funnel Event", {"occurred_at": ("<", cutoff)})
	frappe.db.delete("TEX Funnel Event", {"occurred_at": ("<", cutoff)})
	return n
