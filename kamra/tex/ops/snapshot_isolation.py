"""MariaDB snapshot isolation stays OFF for TEX (ADR-063).

From MariaDB 11.6.2 ``innodb_snapshot_isolation`` is ON by default: a locking read, UPDATE or
upsert of a row changed after the transaction's read view fails with 1020 ("Record has changed
since last read") and the transaction is rolled back. TEX's double-selling guard is its explicit
locks and the locked recount after them (ADR-032): a booking that waited for the lock must see
what was committed meanwhile and be told "sold out", not fail with 1020.

- ``turn_off``: the ``before_request`` and ``before_job`` hook. It sets the variable OFF for the
  request's or job's connection, so TEX runs with it off on a managed host whose server setting
  cannot be changed. MariaDB reads it at every statement, so it holds even when authentication
  already opened the transaction. A server without the variable (MariaDB before 10.6.18: error
  1193) has nothing to turn off.
- ``values``: the global and session values, for the status page (``kamra.tex.ops.status``).
"""

from __future__ import annotations

import frappe

UNKNOWN_SYSTEM_VARIABLE = 1193          # ER_UNKNOWN_SYSTEM_VARIABLE


def _unknown_variable(e: BaseException) -> bool:
	return bool(getattr(e, "args", None)) and e.args[0] == UNKNOWN_SYSTEM_VARIABLE


def _mariadb() -> bool:
	db = getattr(frappe.local, "db", None)
	return bool(db) and db.db_type == "mariadb"


def turn_off() -> None:
	"""SET SESSION innodb_snapshot_isolation = 0 on this connection (hooks: before_request, before_job)."""
	if not _mariadb():
		return
	try:
		frappe.db.sql("SET SESSION innodb_snapshot_isolation = 0")
	except Exception as e:
		if not _unknown_variable(e):
			raise


def values() -> dict[str, int] | None:
	"""{"global": 0|1, "session": 0|1} of this connection; None when the server has no such variable."""
	if not _mariadb():
		return None
	try:
		row = frappe.db.sql("SELECT @@GLOBAL.innodb_snapshot_isolation, @@SESSION.innodb_snapshot_isolation")[0]
	except Exception as e:
		if _unknown_variable(e):
			return None
		raise
	return {"global": int(row[0]), "session": int(row[1])}
