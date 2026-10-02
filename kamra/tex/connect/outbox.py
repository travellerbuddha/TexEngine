"""TEX Connect transactional outbox (ADR-015, R-44).

Reservation changes write ``TEX Integration Outbox`` rows in the same database
transaction as the change; ``deliver_pending`` (scheduler) sends them through the
adapter registered for each enabled connection, with exponential back-off and a
dead-letter state. Core reservation code never talks to a vendor directly.

Order and isolation (NEW-7, ADR-015): the messages of one reservation to one connection go in
the order they were written — a failed one holds the later ones back until it is sent or Dead
(a Dead one never blocks) — and a run stops starting messages when its time budget is used.
"""

from __future__ import annotations

import hashlib
import json
import time
from functools import partial

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


def _deliver(name: str, token: str | None = None) -> bool | None:
	"""Send one claimed message. It is read again first (every item starts after a commit, so the read is
	current): one that is no longer Pending or Failed (sent, dead, retried meanwhile) or, when ``token`` is given,
	no longer this run's (its claim lapsed and another worker took it) is not sent. → False when skipped."""
	state = frappe.db.get_value("TEX Integration Outbox", name, ["status", "claim_token"], as_dict=True)
	if not state or state.status not in ("Pending", "Failed") or (token is not None and state.claim_token != token):
		return False
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
	if not getattr(e, "retryable", True):
		from kamra.tex.security.audit import audit

		# a refused delivery (no signing secret, uncertified in Production …) is on the audit
		# trail, with the reason only: never the payload or a secret (G-83)
		audit("connect.delivery_refused", reference_doctype="TEX Integration Outbox", reference_name=name,
		      property=frappe.db.get_value("TEX Integration Outbox", name, "property"),
		      new={"connection": item.connection, "status": status}, reason=err, source="System")


def _claim(limit: int, token: str, connection: str | None = None) -> list[str]:
	"""Claim for one run (``token``) the first undelivered message of each reservation and connection, when it is
	due and no worker holds it (NEW-7); at most ``limit``. Kind Reservation only: ARI jobs coalesce and need no
	order (``distribution.claim``). Undelivered = Pending or Failed, in the order written (``creation``, ``name``):

	* a reservation's later messages are never claimed while an earlier one is undelivered — one waiting in
	  back-off, one claimed by another worker — so a "cancelled" never overtakes a "modified". Dead and Sent
	  messages do not count: a Dead one never blocks;
	* due = ``next_attempt_at <= now``; a NULL ``next_attempt_at`` is NOT due (as in ``distribution.claim``);
	* free = ``claim_token`` NULL, or ``claimed_until`` before now (a NULL ``claimed_until`` of a claimed row is
	  not free: its worker's lease is unknown).

	The read returns only those first messages, oldest first, at most ``limit`` (LO-10): the database finds them
	(whether a message has an earlier undelivered one through ``tex_outbox_ref_order``), so a long outage that
	leaves thousands in back-off is never read whole into each round. The claim is one conditional UPDATE by
	name (the same conditions: a row another worker took or sent since the read is left alone), committed so it is
	visible at once, read back by this run's token."""
	from kamra.tex.distribution.repository import CLAIM_MINUTES, _commit

	now = now_datetime()
	take = frappe.db.sql(
		"""SELECT o.name FROM `tabTEX Integration Outbox` o
		   WHERE o.kind='Reservation' AND o.status IN ('Pending', 'Failed') AND o.next_attempt_at <= %(n)s
		     AND (o.claim_token IS NULL OR o.claimed_until < %(n)s) AND (%(c)s IS NULL OR o.connection=%(c)s)
		     AND NOT EXISTS (SELECT 1 FROM `tabTEX Integration Outbox` p
		                     WHERE p.connection <=> o.connection AND p.reference_name <=> o.reference_name
		                       AND p.kind='Reservation' AND p.status IN ('Pending', 'Failed')
		                       AND (p.creation < o.creation OR (p.creation = o.creation AND p.name < o.name)))
		   ORDER BY o.creation ASC, o.name ASC LIMIT %(limit)s""",
		{"n": now, "c": connection, "limit": int(limit)}, pluck=True)
	if not take:
		return []
	frappe.db.sql(
		"""UPDATE `tabTEX Integration Outbox` SET claim_token=%(t)s, claimed_until=%(u)s
		   WHERE name IN %(names)s AND kind='Reservation' AND status IN ('Pending', 'Failed')
		     AND next_attempt_at <= %(n)s AND (claim_token IS NULL OR claimed_until < %(n)s)""",
		{"t": token, "u": add_to_date(now, minutes=CLAIM_MINUTES), "n": now, "names": tuple(take)})
	_commit()                                          # the claim must be visible to other workers at once
	got = {r[0] for r in frappe.db.sql("SELECT name FROM `tabTEX Integration Outbox` WHERE name IN %(names)s "
	                                    "AND claim_token=%(t)s", {"names": tuple(take), "t": token})}
	return [n for n in take if n in got]


def _release(names: list[str], token: str) -> None:
	"""Give back the claims of the messages this run did not start (its budget was used): still Pending or
	Failed, no attempt counted, due again at the next run."""
	if names:
		frappe.db.sql("""UPDATE `tabTEX Integration Outbox` SET claim_token=NULL, claimed_until=NULL
		                 WHERE name IN %(names)s AND claim_token=%(t)s AND status IN ('Pending', 'Failed')""",
		              {"names": tuple(names), "t": token})


def deliver_pending(limit: int = 50, budget_seconds: int = 120) -> dict:
	"""Scheduler: claim due reservation messages (no two workers send the same row, a reservation's messages in
	order) and send each as its own unit of work; errors are stored redacted.

	One round claims at most one message per reservation and connection; rounds repeat, each with a new claim,
	while the budget (``budget_seconds``, ``time.monotonic``) and ``limit`` (messages claimed) allow, so a
	reservation's due messages go one after another, oldest first. A run never starts a message once the budget
	is used: a PMS that answers slowly (a webhook waits 15 s to connect and 15 s to read) cannot hold the job past
	its time limit; the messages not started are given back."""
	from kamra.tex.distribution import repository as dist

	deadline = time.monotonic() + budget_seconds
	sent = failed = claimed = 0
	while claimed < limit and time.monotonic() < deadline:
		token = frappe.generate_hash(length=16)
		names = _claim(limit - claimed, token)
		if not names:
			break
		ok, bad = dist._each(names, partial(_deliver, token=token), _failed, deadline=deadline,
		                     release=partial(_release, token=token))
		sent, failed, claimed = sent + ok, failed + bad, claimed + len(names)
	return {"sent": sent, "failed": failed}
