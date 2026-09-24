"""Transaction helpers for write endpoints."""

from __future__ import annotations

import functools
import random
import time

import frappe
from frappe import _

DEADLOCK_ATTEMPTS = 3
# errors after which the request's transaction is gone (InnoDB rolled a deadlock victim back whole) or
# must not go on (a lock wait timed out): a best-effort step (tracking, mailing) re-raises them, so the
# request is retried or fails instead of reporting what was rolled back (ADR-056 second review)
TRANSACTION_LOST = (frappe.QueryDeadlockError, frappe.QueryTimeoutError)


def retry_on_deadlock(fn):
	"""Run a whole write request again when the database chose it as a deadlock victim.

	InnoDB rolls the victim's transaction back entirely, and its documented remedy is to
	run the transaction again. The locks TEX takes (inventory days, then promotions, in a
	fixed order) keep deadlocks rare, but a locking range read can still meet another
	booking's insert, and MariaDB ≥ 11.6 reports a changed-row conflict the same way.
	Only for endpoints whose every write belongs to that one request transaction: the
	retry starts from a clean rollback and repeats all of it, so nothing is written
	twice (the booking and payment idempotency keys guard the rest)."""

	@functools.wraps(fn)
	def wrapper(*args, **kwargs):
		for attempt in range(1, DEADLOCK_ATTEMPTS + 1):
			try:
				return fn(*args, **kwargs)
			except frappe.QueryDeadlockError:
				frappe.db.rollback()
				if attempt == DEADLOCK_ATTEMPTS:
					frappe.throw(_("The hotel is very busy right now. Please try again in a moment."),
					             title=_("Please try again"))
				time.sleep(random.uniform(0.02, 0.1) * attempt)
		return None

	return wrapper
