"""O-24 (audit Part 2H-2, ADR-059): flag the holds that ran out of time before ``Reservation.tex_hold_expired`` existed.

A hold the system cancelled because its time ran out is no cancellation and no sale (reports, dashboard, CRM leave
it out). Only two writers ever gave a reservation the note ``EXPIRY_NOTE`` ("Hold / payment window expired"): TEX's
``expire_booking`` and the PMS job ``expire_holds``, since G-86 (23 September); no hold expired before it. A
cancelled reservation with that note which nobody cancelled (a hold cancelled on purpose has its Cancellation
revision, whatever note staff typed) is therefore a hold that expired: ``tex_hold_expired`` = 1.

The key is the status and the note, minus the Cancellation revisions (one SELECT DISTINCT: ``reservation`` has no
index on its revisions). A reservation without a note (NULL) is never an expiry: ``NULL = 'text'`` is not true.
Raw UPDATEs by name, BATCH at a time, without touching ``modified``. Prints how many were flagged and how many of
them belong to a TEX booking (numbers only); a second run flags none (``tex_hold_expired = 0`` is part of the key).
"""

import frappe

from kamra.reservation_state import EXPIRY_NOTE

BATCH = 500

# NULL note or NULL booking: ``=`` never matches NULL, so neither a reservation without a note nor one cancelled
# with another is returned; ``tex_booking`` is only read (a TEX booking's hold, for the count)
EXPIRED = """SELECT name, tex_booking FROM `tabReservation`
	WHERE status = 'Cancelled' AND cancellation_note = %s AND tex_hold_expired = 0"""
ON_PURPOSE = "SELECT DISTINCT reservation FROM `tabTEX Reservation Revision` WHERE change_type = 'Cancellation'"


def execute():
	on_purpose = {r for (r,) in frappe.db.sql(ON_PURPOSE) if r}
	flagged = [(name, booking) for name, booking in frappe.db.sql(EXPIRED, EXPIRY_NOTE) if name not in on_purpose]
	names = [name for name, _booking in flagged]
	for i in range(0, len(names), BATCH):
		frappe.db.sql("UPDATE `tabReservation` SET tex_hold_expired = 1 WHERE name IN %s AND tex_hold_expired = 0",
		              (tuple(names[i:i + BATCH]),))
	print(f"p62: {len(flagged)} expired hold(s) flagged ({sum(1 for _n, b in flagged if b)} of TEX bookings)")
