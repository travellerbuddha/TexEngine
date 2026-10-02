"""LO-10 (audit Part 2K-4, ADR-015 addendum): a PMS outbox claim reads only the messages it may send.

``outbox._claim`` used to read every undelivered Reservation message (all connections) each round to find each
reservation's first; a long PMS outage leaves thousands in back-off. The claim now asks the database for the first
undelivered message of each reservation and connection that is due and free, oldest first, at most the round's cap:
whether a due message has an earlier undelivered one is read through the composite index ``tex_outbox_ref_order``
(connection, reference_name, status, creation) from ``setup.TEX_INDEXES`` (the p46 pattern). Composite, so Frappe's
schema sync leaves it alone (p39). Idempotent: an index that exists is not created again, so a forced re-run runs no
DDL. No row changes.
"""


def execute():
	from kamra.tex import setup

	missing = [name for _dt, _fields, name in setup.missing_indexes()]
	setup.ensure_indexes()
	print(f"p74: {len(missing)} TEX index(es) created: {', '.join(missing) or '-'}")
