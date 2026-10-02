"""LO-06 (audit Part 2K-2, ADR-071 §4 addendum): a points return finds a Loyalty charge's burn row by the charge.

``loyalty.give_back`` reads who spent the points of a booking's Loyalty charges by the bookings they were
redeemed for (``BURNERS_OF``), so a charge staff moved to another booking, or a burner no longer on the booking,
still gets its points back. ``TEX Loyalty Ledger`` has no index on ``booking``: without one that read scans the
ledger. Creates the composite index ``tex_ledger_booking_type`` (booking, entry_type) from
``setup.TEX_INDEXES`` (the p46 pattern). Composite, so Frappe's schema sync leaves it alone (p39). Idempotent:
an index that exists is not created again, so a forced re-run runs no DDL. No row changes.
"""


def execute():
	from kamra.tex import setup

	missing = [name for _dt, _fields, name in setup.missing_indexes()]
	setup.ensure_indexes()
	print(f"p73: {len(missing)} TEX index(es) created: {', '.join(missing) or '-'}")
