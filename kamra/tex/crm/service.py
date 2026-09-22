"""TEX CRM service (R-35–R-39).

Tenancy: a guest is visible to a user when the guest has a reservation at one of
the user's hotels, or belongs to the enterprise of one of the user's hotels. Stays,
bookings and communications shown are always filtered to the user's permitted
hotels. Marketing data leaves the system only for guests with the
matching consent (KVKK / GDPR); every consent change and export is audited.
"""

from __future__ import annotations

import json
from datetime import timedelta

import frappe
from frappe import _
from frappe.utils import add_to_date, getdate, now_datetime, nowdate

from kamra.tex.crm import segments as seg
from kamra.tex.money import ZERO, D, from_db, to_str
from kamra.tex.security import scope
from kamra.tex.security.audit import audit

EDITABLE = ("first_name", "last_name", "phone", "email", "nationality", "date_of_birth", "gender", "vip",
            "guest_notes", "address_line", "city", "tex_language", "tex_country", "tex_market", "tex_tags",
            "tex_preferences", "blacklisted", "blacklist_reason")
CONSENT = ("tex_consent_email", "tex_consent_sms", "tex_consent_whatsapp")
LIST_FIELDS = ["name", "full_name", "first_name", "last_name", "email", "phone", "vip", "blacklisted", "nationality",
               "tex_country", "tex_market", "tex_language", "tex_tags", "tex_stays", "tex_lifetime_value",
               "tex_last_stay", "tex_loyalty_points", "tex_consent_email", "tex_consent_sms",
               "tex_consent_whatsapp", "tex_enterprise"]
ABANDON_AFTER_MINUTES = 45


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


def list_guests(*, q: str | None = None, segment: str | None = None, vip: bool | None = None,
                consent: str | None = None, property: str | None = None, start: int = 0,
                limit: int = 50) -> dict:
	props = {p for p in scope.permitted_properties() if scope.has_capability("crm.view", p)}
	if property:
		scope.require("crm.view", property)
		props = {property}
	cond, params = _visible_guest_sql(props)
	where = [cond]
	if q:
		where.append("(g.full_name LIKE %(q)s OR g.email LIKE %(q)s OR g.phone LIKE %(q)s OR g.name LIKE %(q)s)")
		params["q"] = f"%{q.strip()[:80]}%"
	if vip is not None:
		where.append("g.vip = %(vip)s")
		params["vip"] = 1 if vip else 0
	if consent in CONSENT:
		where.append(f"g.`{consent}` = 1")
	cols = ", ".join(f"g.`{f}`" for f in LIST_FIELDS)
	sql = f"SELECT {cols} FROM `tabGuest` g WHERE {' AND '.join(where)} ORDER BY g.modified DESC"  # nosemgrep
	rows = frappe.db.sql(sql, params, as_dict=True)
	if segment:
		rules = _segment_rules(segment)
		today = getdate(nowdate())
		upcoming = _upcoming_guests([r.name for r in rows], props)
		rows = [r for r in rows if seg.matches(seg.guest_facts(r, today, r.name in upcoming), rules, today)]
	total = len(rows)
	page = rows[start:start + limit]
	for r in page:
		r["tex_lifetime_value"] = to_str(D(r.get("tex_lifetime_value") or 0))
		r["tex_last_stay"] = str(r["tex_last_stay"]) if r.get("tex_last_stay") else None
	return {"total": total, "rows": page}


def _upcoming_guests(guests: list[str], props: set[str]) -> set[str]:
	if not guests or not props:
		return set()
	return set(frappe.get_all("Reservation", filters={"guest": ("in", guests), "property": ("in", list(props)),
	                                                  "check_in_date": (">=", nowdate()),
	                                                  "status": ("not in", ["Cancelled", "No Show"])},
	                          pluck="guest", distinct=True))


def profile(guest: str) -> dict:
	via = require_guest(guest)
	g = frappe.get_doc("Guest", guest)
	d = {f: g.get(f) for f in ("name", "full_name", *EDITABLE, *CONSENT, "tex_consent_updated_at",
	                          "tex_consent_source", "tex_consent_text_version", "tex_stays", "tex_lifetime_value",
	                          "tex_last_stay", "tex_loyalty_points", "tex_enterprise")}
	for k in ("date_of_birth", "tex_last_stay", "tex_consent_updated_at"):
		d[k] = str(d[k]) if d.get(k) else None
	d["tex_lifetime_value"] = to_str(D(d.get("tex_lifetime_value") or 0))
	if not any(scope.has_capability("guest.export", p) for p in via):
		d.pop("id_number", None)
	stays = frappe.get_all("Reservation", filters={"guest": guest, "property": ("in", list(via))},
	                       fields=["name", "property", "status", "check_in_date", "check_out_date", "room_type",
	                               "tex_board", "adults", "children", "tex_total_amount", "tex_currency",
	                               "tex_booking", "tex_sales_channel", "tex_market"],
	                       order_by="check_in_date desc", limit=200)
	for s in stays:
		s["check_in_date"], s["check_out_date"] = str(s["check_in_date"]), str(s["check_out_date"])
		s["tex_total_amount"] = to_str(from_db(s["tex_total_amount"], s["tex_currency"] or "EUR"))
	comms = frappe.get_all("TEX Communication", filters={"guest": guest, "property": ("in", [*via, ""])},
	                       fields=["name", "channel", "direction", "status", "consent_basis", "subject", "body",
	                               "sent_at", "actor", "booking", "reservation", "creation"],
	                       order_by="creation desc", limit=100)
	for c in comms:
		c["sent_at"] = str(c["sent_at"]) if c["sent_at"] else None
		c["creation"] = str(c["creation"])
	from kamra.tex.crm import loyalty

	today = getdate(nowdate())
	facts = seg.guest_facts(g.as_dict(), today, bool(_upcoming_guests([guest], via)))
	member_of = [s.segment_name for s in frappe.get_all("TEX Guest Segment", fields=["name", "segment_name",
	                                                                                  "rules_json"])
	             if s.rules_json and _safe_match(facts, s.rules_json, today)]
	consent_log = frappe.get_all("TEX Audit Event", filters={"reference_doctype": "Guest", "reference_name": guest,
	                                                         "action": "guest.consent"},
	                             fields=["event_time", "actor", "new_value", "reason", "source"],
	                             order_by="event_time desc", limit=50)
	for c in consent_log:
		c["event_time"] = str(c["event_time"])
	return {"guest": d, "stays": stays, "communications": comms, "segments": member_of,
	        "loyalty": loyalty.summary(guest), "consent_history": consent_log, "hotels": sorted(via)}


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
	consent_changed = {}
	for f in CONSENT:
		if f in data and bool(data[f]) != bool(g.get(f)):
			g.set(f, 1 if data[f] else 0)
			consent_changed[f] = [bool(before[f]), bool(data[f])]
	if consent_changed:
		g.tex_consent_updated_at = now_datetime()
		g.tex_consent_source = consent_source[:140]
		if consent_text_version:
			g.tex_consent_text_version = consent_text_version[:140]
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


def log_communication(guest: str, *, channel: str, direction: str, subject: str | None, body: str | None,
                      consent_basis: str = "Transactional", booking: str | None = None,
                      reservation: str | None = None, property: str | None = None) -> str:
	via = require_guest(guest, "crm.edit")
	if property and property not in via:
		frappe.throw(_("You don't have access to {0}.").format(property), frappe.PermissionError)
	if channel not in ("Email", "SMS", "WhatsApp", "Phone", "Note"):
		frappe.throw(_("Unknown channel."))
	if consent_basis == "Marketing" and direction == "Outbound" and channel in ("Email", "SMS", "WhatsApp"):
		field = {"Email": "tex_consent_email", "SMS": "tex_consent_sms", "WhatsApp": "tex_consent_whatsapp"}[channel]
		if not frappe.db.get_value("Guest", guest, field):
			frappe.throw(_("The guest has not consented to marketing by {0}.").format(channel))
	doc = frappe.get_doc({"doctype": "TEX Communication", "guest": guest, "property": property or sorted(via)[0],
	                      "booking": booking, "reservation": reservation, "channel": channel,
	                      "direction": direction, "status": "Logged", "consent_basis": consent_basis,
	                      "subject": (subject or "")[:140], "body": (body or "")[:5000], "sent_at": now_datetime(),
	                      "actor": frappe.session.user})
	doc.insert(ignore_permissions=True)
	return doc.name


def refresh_guest_stats(guest: str) -> None:
	"""Stays / lifetime value / last stay from non-cancelled reservations. Money is
	never summed across currencies: lifetime value is the total in the guest's most
	used booking currency (ties → alphabetical)."""
	rows = frappe.get_all("Reservation", filters={"guest": guest, "status": ("not in", ["Cancelled", "No Show"])},
	                      fields=["check_out_date", "tex_total_amount", "amount_after_tax", "tex_currency"])
	stays = len(rows)
	by_ccy: dict[str, list] = {}
	for r in rows:
		by_ccy.setdefault(r.tex_currency or "EUR", []).append(r)
	main = min(by_ccy, key=lambda c: (-len(by_ccy[c]), c)) if by_ccy else None
	value = sum((from_db(r.tex_total_amount or r.amount_after_tax or 0, main) for r in by_ccy.get(main, [])), ZERO)
	past = [r.check_out_date for r in rows if r.check_out_date and getdate(r.check_out_date) <= getdate(nowdate())]
	frappe.db.set_value("Guest", guest, {"tex_stays": stays, "tex_lifetime_value": value,
	                                     "tex_last_stay": max(past) if past else None}, update_modified=False)


# ─── segments ────────────────────────────────────────────────────────────


def _segment_rules(segment: str) -> dict:
	raw = frappe.db.get_value("TEX Guest Segment", segment, "rules_json")
	if raw is None:
		frappe.throw(_("Segment not found."), frappe.DoesNotExistError)
	try:
		return seg.validate(json.loads(raw or "{}"))
	except (seg.SegmentError, ValueError) as e:
		frappe.throw(_("Segment rules are invalid: {0}").format(e))


def save_segment(data: dict) -> str:
	if not any(scope.has_capability("crm.edit", p) for p in scope.permitted_properties()):
		frappe.throw(_("Not permitted: {0}.").format("crm.edit"), frappe.PermissionError)
	try:
		rules = seg.validate(data.get("rules") or {})
	except seg.SegmentError as e:
		frappe.throw(str(e))
	doc = frappe.get_doc("TEX Guest Segment", data["name"]) if data.get("name") else frappe.new_doc(
		"TEX Guest Segment")
	if doc.get("system_key") and data.get("name"):
		frappe.throw(_("System segments cannot be edited."))
	doc.segment_name = (data.get("segment_name") or "").strip()[:140] or frappe.throw(_("Name is required."))
	doc.description = (data.get("description") or "")[:500]
	doc.rules_json = json.dumps(rules, sort_keys=True)
	doc.is_dynamic = 1
	doc.save(ignore_permissions=True)
	return doc.name


def evaluate_segment(segment: str, *, property: str | None = None) -> dict:
	res = list_guests(segment=segment, property=property, limit=0)
	frappe.db.set_value("TEX Guest Segment", segment, {"member_count": res["total"],
	                                                  "last_evaluated": now_datetime()}, update_modified=False)
	return {"segment": segment, "members": res["total"]}


def export_segment(segment: str, *, channel: str, property: str | None = None) -> list[dict]:
	"""Marketing export: only guests with consent for ``channel`` and not blacklisted."""
	props = [property] if property else sorted(scope.permitted_properties())
	if not props or not all(scope.has_capability("guest.export", p) for p in props):
		frappe.throw(_("Not permitted: {0}.").format("guest.export"), frappe.PermissionError)
	field = {"Email": "tex_consent_email", "SMS": "tex_consent_sms", "WhatsApp": "tex_consent_whatsapp"}.get(channel)
	if not field:
		frappe.throw(_("Unknown channel."))
	res = list_guests(segment=segment, property=property, consent=field, limit=100000)
	rows = [{"guest": r["name"], "first_name": r["first_name"], "last_name": r["last_name"],
	         "email": r["email"] if channel == "Email" else None,
	         "phone": r["phone"] if channel != "Email" else None, "language": r["tex_language"],
	         "country": r["tex_country"]} for r in res["rows"] if not r.get("blacklisted")]
	audit("guest.export", reference_doctype="TEX Guest Segment", reference_name=segment, property=property,
	      new={"channel": channel, "rows": len(rows)})
	return rows


def ensure_system_segments() -> None:
	for key, (label, rules) in seg.SYSTEM_SEGMENTS.items():
		if frappe.db.exists("TEX Guest Segment", {"system_key": key}):
			continue
		if frappe.db.exists("TEX Guest Segment", label):
			continue
		frappe.get_doc({"doctype": "TEX Guest Segment", "segment_name": label, "system_key": key, "is_dynamic": 1,
		                "rules_json": json.dumps(rules, sort_keys=True)}).insert(ignore_permissions=True)


# ─── abandoned bookings (R-38) ───────────────────────────────────────────

STAGES = ("search", "room_view", "quote", "guest_details", "payment_started")


def detect_abandoned(now=None) -> dict:
	"""Scheduler: sessions that reached at least a quote, went quiet for
	ABANDON_AFTER_MINUTES and never booked. Contact data is kept only with the guest's
	marketing consent; otherwise the record is anonymous (value, dates, stage)."""
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
		                        fields=["event", "payload", "property", "email_hash", "consent_marketing",
		                                "occurred_at"], order_by="occurred_at asc")
		names = [e.event for e in events]
		existing = frappe.db.get_value("TEX Abandoned Booking", {"session_id": s.session_id},
		                               ["name", "status"], as_dict=True)
		if "booked" in names:
			if existing and existing.status in ("Open", "Contacted"):
				booking = next((json.loads(e.payload or "{}").get("booking") for e in reversed(events)
				                if e.event == "booked"), None)
				frappe.db.set_value("TEX Abandoned Booking", existing.name,
				                    {"status": "Recovered", "recovered_booking": booking})
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
				email, phone = frappe.db.get_value("Guest", guest, ["email", "phone"])
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
			"quote": qp.get("quote") if qp.get("quote") and frappe.db.exists("TEX Quote", qp.get("quote")) else None,
			"last_event_at": s.last_at}).insert(ignore_permissions=True)
		created += 1
	return {"created": created, "recovered": recovered}


def abandoned(property: str, *, status: str | None = None, days: int = 30) -> list[dict]:
	scope.require("crm.view", property)
	filters = {"property": property, "last_event_at": (">=", add_to_date(now_datetime(), days=-days))}
	if status:
		filters["status"] = status
	rows = frappe.get_all("TEX Abandoned Booking", filters=filters,
	                      fields=["name", "site", "stage_reached", "status", "guest", "email", "phone",
	                              "consent_marketing", "value", "currency", "check_in", "check_out",
	                              "last_event_at", "recovered_booking"], order_by="last_event_at desc", limit=500)
	for r in rows:
		r["value"] = to_str(from_db(r["value"], r["currency"] or "EUR"))
		for k in ("check_in", "check_out", "last_event_at"):
			r[k] = str(r[k]) if r[k] else None
	return rows


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
