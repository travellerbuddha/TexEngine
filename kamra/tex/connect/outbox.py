"""TEX Connect transactional outbox (ADR-015, R-44).

Reservation changes write ``TEX Integration Outbox`` rows in the same database
transaction as the change; ``deliver_pending`` (scheduler) sends them through the
adapter registered for each enabled connection, with exponential back-off and a
dead-letter state. Core reservation code never talks to a vendor directly.
"""

from __future__ import annotations

import hashlib
import json

import frappe
from frappe.utils import add_to_date, now_datetime

from kamra.tex.connect import adapters

MAX_ATTEMPTS = 8


def _event_for(doc) -> str | None:
	before = doc.get_doc_before_save()
	if before is None:
		return "reservation.created"
	if before.status != doc.status and doc.status == "Cancelled":
		return "reservation.cancelled"
	watched = ("check_in_date", "check_out_date", "room_type", "adults", "children", "status", "tex_total_amount",
	           "tex_board", "room")
	if any(str(before.get(f) or "") != str(doc.get(f) or "") for f in watched):
		return "reservation.modified"
	return None


def reservation_payload(doc) -> dict:
	return {
		"reservation": doc.name, "booking": doc.get("tex_booking"), "property": doc.property,
		"status": doc.status, "guest": doc.guest, "guest_name": doc.guest_name,
		"room_type": doc.room_type, "room": doc.room, "check_in": str(doc.check_in_date),
		"check_out": str(doc.check_out_date), "adults": doc.adults, "children": doc.children,
		"child_ages": json.loads(doc.get("tex_child_ages") or "[]"), "board": doc.get("tex_board"),
		"rate_plan": doc.rate_plan, "market": doc.get("tex_market"), "channel": doc.get("tex_sales_channel"),
		"currency": doc.get("tex_currency"), "total": str(doc.get("tex_total_amount") or doc.amount_after_tax or 0),
		"revision": doc.get("tex_revision_no"),
	}


def on_reservation_change(doc) -> None:
	event = _event_for(doc)
	if not event:
		return
	conns = frappe.get_all("TEX Integration Connection",
	                       filters={"property": doc.property, "enabled": 1, "category": ("in", ["PMS",
	                                                                                             "Channel Manager"])},
	                       pluck="name")
	payload = reservation_payload(doc)
	for c in conns:
		key = hashlib.sha256(f"{c}|{event}|{doc.name}|{doc.modified}".encode()).hexdigest()[:40]
		if frappe.db.exists("TEX Integration Outbox", {"idempotency_key": key}):
			continue
		frappe.get_doc({"doctype": "TEX Integration Outbox", "connection": c, "property": doc.property,
		                "event": event, "status": "Pending", "attempts": 0, "next_attempt_at": now_datetime(),
		                "reference_doctype": "Reservation", "reference_name": doc.name, "idempotency_key": key,
		                "payload": json.dumps(payload, default=str, sort_keys=True)}).insert(ignore_permissions=True)


def deliver_pending(limit: int = 50) -> dict:
	rows = frappe.get_all("TEX Integration Outbox",
	                      filters={"status": ("in", ["Pending", "Failed"]), "next_attempt_at": ("<=", now_datetime())},
	                      pluck="name", order_by="creation asc", limit=limit)
	sent = failed = 0
	for name in rows:
		item = frappe.get_doc("TEX Integration Outbox", name)
		conn = frappe.get_doc("TEX Integration Connection", item.connection)
		try:
			adapter = adapters.get(conn)
			adapter.deliver(item.event, json.loads(item.payload or "{}"), idempotency_key=item.idempotency_key)
			item.status = "Sent"
			item.sent_at = now_datetime()
			item.last_error = None
			sent += 1
		except Exception as e:
			item.attempts = int(item.attempts or 0) + 1
			item.last_error = str(e)[:500]
			item.status = "Dead" if item.attempts >= MAX_ATTEMPTS else "Failed"
			item.next_attempt_at = add_to_date(now_datetime(), minutes=min(2 ** item.attempts, 720))
			failed += 1
		item.save(ignore_permissions=True)
		conn.db_set({"last_sync_at": now_datetime(), "last_status": item.status,
		             "last_error": item.last_error}, update_modified=False)
	return {"sent": sent, "failed": failed}
