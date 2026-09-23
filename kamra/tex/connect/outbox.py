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
	# on insert Frappe (v16) may already hold a "before" copy (a db_set in after_insert loads
	# the just-written row), so a new stay is told by the insert flag, never by that copy
	before = None if doc.flags.get("in_insert") else doc.get_doc_before_save()
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
	# channel managers get availability and prices (ARI, kamra.tex.distribution), not reservations
	conns = frappe.get_all("TEX Integration Connection",
	                       filters={"property": doc.property, "enabled": 1, "category": "PMS"}, pluck="name")
	payload = reservation_payload(doc)
	for c in conns:
		key = hashlib.sha256(f"{c}|{event}|{doc.name}|{doc.modified}".encode()).hexdigest()[:40]
		if frappe.db.exists("TEX Integration Outbox", {"idempotency_key": key}):
			continue
		frappe.get_doc({"doctype": "TEX Integration Outbox", "kind": "Reservation", "connection": c,
		                "property": doc.property,
		                "event": event, "status": "Pending", "attempts": 0, "next_attempt_at": now_datetime(),
		                "reference_doctype": "Reservation", "reference_name": doc.name, "idempotency_key": key,
		                "payload": json.dumps(payload, default=str, sort_keys=True)}).insert(ignore_permissions=True)


def _deliver(name: str) -> None:
	item = frappe.get_doc("TEX Integration Outbox", name)
	conn = frappe.get_doc("TEX Integration Connection", item.connection)
	if not conn.enabled:
		raise RuntimeError("the connection is disabled")
	adapters.get(conn).deliver(item.event, json.loads(item.payload or "{}"), idempotency_key=item.idempotency_key)
	frappe.db.set_value("TEX Integration Outbox", name, {"status": "Sent", "sent_at": now_datetime(), "last_error": None,
	                                                    "claim_token": None, "claimed_until": None},
	                    update_modified=False)
	conn.db_set({"last_sync_at": now_datetime(), "last_status": "Sent", "last_error": None}, update_modified=False)


def _failed(name: str, e: Exception) -> None:
	from kamra.tex.security.audit import redact_text

	item = frappe.db.get_value("TEX Integration Outbox", name, ["attempts", "connection"], as_dict=True)
	attempts = int(item.attempts or 0) + 1
	err = redact_text(str(e))[:500]
	# a refusal (e.g. an uncertified adapter in Production, G-90) is final: no retry can help
	status = "Dead" if (attempts >= MAX_ATTEMPTS or not getattr(e, "retryable", True)) else "Failed"
	frappe.db.set_value("TEX Integration Outbox", name, {
		"attempts": attempts, "last_error": err, "status": status, "claim_token": None, "claimed_until": None,
		"next_attempt_at": add_to_date(now_datetime(), minutes=min(2 ** attempts, 720))}, update_modified=False)
	frappe.db.set_value("TEX Integration Connection", item.connection, {
		"last_sync_at": now_datetime(), "last_status": status, "last_error": err}, update_modified=False)


def deliver_pending(limit: int = 50) -> dict:
	"""Scheduler: claim due reservation events (no two workers send the same row) and send
	each as its own unit of work; errors are stored redacted."""
	from kamra.tex.distribution import repository as dist

	sent, failed = dist._each(dist.claim("Reservation", limit), _deliver, _failed)
	return {"sent": sent, "failed": failed}
