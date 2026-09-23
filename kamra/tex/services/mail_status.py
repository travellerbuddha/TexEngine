"""E-mail delivery status (ADR-047): a TEX Communication follows its Frappe Email Queue row.

Frappe changes an Email Queue row's status with ``frappe.db.set_value`` (no document hooks
run), so an ``on_update`` hook would never see a mail being sent. ``sync`` runs every 5
minutes instead: one indexed join picks the Queued communications whose queue row reached a
final state (Sent, Error, or Expired on older Frappe versions), in batches, and each is
updated once. Queued rows are the only ones read, so a run with nothing new costs one query
and a second run changes nothing.

Sent means the mail server accepted the message; TEX never claims "Delivered". A failure
keeps only a short reason (``SMTPRecipientsRefused (550)``), never the traceback or the
address. ``sent_at`` becomes the time the queue sent it.
"""

from __future__ import annotations

from datetime import timedelta

import frappe
from frappe.utils import get_datetime

from kamra.tex.ops import checks as C

BATCH = 500
# backfill: a Queued communication and its queue row were written in the same request (the
# mail is queued first), so the row is at most this old when the communication is written
BACKFILL_BEFORE_SECONDS = 60
BACKFILL_AFTER_SECONDS = 5


def sync(limit: int = BATCH) -> dict:
	rows = frappe.db.sql(
		"""SELECT c.name, q.status, q.error, q.modified
		   FROM `tabTEX Communication` c
		   JOIN `tabEmail Queue` q ON q.name = c.email_queue
		   WHERE c.status = 'Queued' AND IFNULL(c.email_queue, '') != '' AND q.status IN %(final)s
		   ORDER BY c.creation LIMIT %(limit)s""",
		{"final": tuple(C.QUEUE_TO_COMMUNICATION), "limit": int(limit)}, as_dict=True)
	for r in rows:
		status = C.communication_status(r.status)
		values = {"status": status}
		if status == "Sent":
			values["sent_at"] = r.modified
		else:
			values["delivery_error"] = (C.delivery_error(r.error) or r.status)[:140]
		frappe.db.set_value("TEX Communication", r.name, values, update_modified=False)
	return {"updated": len(rows)}


def sync_all() -> int:
	"""Every pending update, batch after batch (migrations)."""
	total = 0
	while True:
		n = sync()["updated"]
		total += n
		if n < BATCH:
			return total


def backfill() -> dict:
	"""Link Queued e-mail communications written before ``email_queue`` existed to their queue
	row, only where exactly one row fits: the same booking (or a payment link of it), queued
	just before the communication, and not claimed by another communication. The rest stay
	Queued; the status check never judges a communication without a queue row."""
	rows = frappe.db.sql(
		"""SELECT name, booking, template, creation FROM `tabTEX Communication`
		   WHERE channel = 'Email' AND direction = 'Outbound' AND status = 'Queued'
		     AND IFNULL(email_queue, '') = '' AND IFNULL(booking, '') != '' ORDER BY creation""", as_dict=True)
	taken = set(frappe.get_all("TEX Communication", filters={"email_queue": ("is", "set")}, pluck="email_queue"))
	matched = 0
	for r in rows:
		if r.template == "payment_link":
			doctype = "TEX Payment Link"
			refs = frappe.get_all("TEX Payment Link", filters={"booking": r.booking}, pluck="name")
		else:
			doctype, refs = "TEX Booking", [r.booking]
		if not refs:
			continue
		at = get_datetime(r.creation)
		found = frappe.db.sql(
			"""SELECT name FROM `tabEmail Queue` WHERE reference_doctype = %(dt)s AND reference_name IN %(refs)s
			   AND creation BETWEEN %(a)s AND %(b)s""",
			{"dt": doctype, "refs": tuple(refs), "a": at - timedelta(seconds=BACKFILL_BEFORE_SECONDS),
			 "b": at + timedelta(seconds=BACKFILL_AFTER_SECONDS)}, pluck=True)
		free = [q for q in found if q not in taken]
		if len(found) == 1 and len(free) == 1:
			frappe.db.set_value("TEX Communication", r.name, "email_queue", free[0], update_modified=False)
			taken.add(free[0])
			matched += 1
	return {"matched": matched, "unmatched": len(rows) - matched}
