"""Transaction helpers for write endpoints."""

from __future__ import annotations

import functools
import random
import time

import frappe
from frappe import _

DEADLOCK_ATTEMPTS = 3
# innodb_rollback_on_timeout per site (a server setting, read once, on the first timeout)
_ROLLBACK_ON_TIMEOUT: dict[str, bool] = {}


def _rollback_on_timeout() -> bool:
	"""Whether the server rolls a whole transaction back on a lock wait timeout. Unknown: assume so."""
	site = getattr(frappe.local, "site", None) or ""
	if site not in _ROLLBACK_ON_TIMEOUT:
		try:
			_ROLLBACK_ON_TIMEOUT[site] = bool(int(frappe.db.sql("SELECT @@innodb_rollback_on_timeout")[0][0]))
		except Exception:
			return True
	return _ROLLBACK_ON_TIMEOUT[site]


def transaction_lost(e: BaseException) -> bool:
	"""Whether ``e`` ended the request's transaction (ADR-056 second and third reviews).

	A deadlock did: InnoDB rolled the victim back whole (MariaDB reports a changed-row conflict under
	snapshot isolation the same way), so nothing the request wrote is left and it must be retried or
	fail, never go on as if its writes were there. A lock wait timeout did only where the server rolls
	the transaction back on one (``innodb_rollback_on_timeout``); by default it undoes only the statement
	that waited, and the transaction goes on."""
	if isinstance(e, frappe.QueryDeadlockError):
		return True
	return isinstance(e, frappe.QueryTimeoutError) and _rollback_on_timeout()


def undo_step(e: BaseException, savepoint: str) -> None:
	"""For a best-effort step (a funnel event, a guest e-mail) that failed with ``e`` after
	``frappe.db.savepoint(savepoint)``: raise ``e`` when the transaction is gone (``transaction_lost``),
	else undo the step's own writes back to its savepoint, so the request goes on without the step."""
	if transaction_lost(e):
		raise e
	frappe.db.rollback(save_point=savepoint)


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
