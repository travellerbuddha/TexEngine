"""Y-11 and O-22 (audit Part 2H-1, ADR-071): close the lots that expired before points were used first-to-expire.

The old expiry job took ``min(lot, balance)`` from a lot the day it ran and, when the balance was zero, wrote
nothing and marked nothing, so the same lot was looked at every day. It is a lot model now (``kamra.tex.crm.lots``):
a lot past its expiry takes what is left of it and closes (status Expired). For every Available earning past its
``expires_on``:

(a) the old job marked it (an Expire row "expiry of <lot>"): it is closed, status Expired;
(b) its points are spent in full by first-to-expire order: closed, status Expired, no row;
(c) points are left of it: the daily job takes them. A patch never takes points.

Raw UPDATEs by name, BATCH at a time, without touching ``modified``. Prints how many lots of each kind (numbers
only); a second run closes none. It does not give back points the old job took (they are listed in the notes of
the release)."""

import frappe
from frappe.utils import getdate, nowdate

from kamra.tex.crm import lots

BATCH = 500

DUE = """SELECT DISTINCT guest, program FROM `tabTEX Loyalty Ledger`
	WHERE entry_type = 'Earn' AND status = 'Available' AND expires_on IS NOT NULL AND expires_on < %s
	ORDER BY guest, program"""
ROWS = """SELECT name, entry_type, points, status, available_on, expires_on, creation, reason
	FROM `tabTEX Loyalty Ledger` WHERE guest = %s AND program = %s AND status IN ('Available', 'Used', 'Expired')
	ORDER BY creation ASC, name ASC"""


def close(names: list[str]) -> None:
	for i in range(0, len(names), BATCH):
		frappe.db.sql("UPDATE `tabTEX Loyalty Ledger` SET status = 'Expired' WHERE name IN %s AND status = 'Available'",
		              (tuple(names[i:i + BATCH]),))


def execute():
	today = getdate(nowdate())
	marked_lots: list[str] = []
	spent_lots: list[str] = []
	left = 0
	for guest, program in frappe.db.sql(DUE, today):                    # NULL: a lot without an expiry never expires
		rows = frappe.db.sql(ROWS, (guest, program), as_dict=True)
		named = lots.marked(rows)
		for r in rows:
			if r.entry_type == "Earn" and r.status == "Available" and r.name in named and r.expires_on and \
					getdate(r.expires_on) < today:
				marked_lots.append(r.name)
				r.status = "Expired"
		plan = lots.plan(rows, today)
		unspent = {lot for lot, _points in plan["expire"]}
		for lot in plan["close"]:
			if lot in unspent:
				left += 1
			else:
				spent_lots.append(lot)
	close(marked_lots)
	close(spent_lots)
	print(f"p61: {len(marked_lots)} lot(s) closed by the old expiry marked, {len(spent_lots)} lot(s) that expired "
	      f"with nothing left closed; {left} past-due lot(s) left to the daily expiry")
