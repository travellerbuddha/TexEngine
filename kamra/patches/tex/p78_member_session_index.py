"""C-04 on the web (owner, 2026-10-03; ADR-078): a guest's web sessions, read and moved by a merge.

``TEX Member Session`` (new) holds a guest's session on a booking site, opened by a one-time e-mail link. A merge
reads and moves a profile's records with locking reads, so every Link to Guest has an index that starts with it
(third review of ADR-056); an erasure deletes them by the guest too. Creates the composite index
``tex_member_session_guest`` (guest, site) from ``setup.TEX_INDEXES`` (the p46 pattern), after the model sync made the
table. Composite, so Frappe's schema sync leaves it alone (p39). Idempotent: an index that exists is not created again,
so a forced re-run runs no DDL. No row changes.
"""


def execute():
	from kamra.tex import setup

	missing = [name for _dt, _fields, name in setup.missing_indexes()]
	setup.ensure_indexes()
	print(f"p78: {len(missing)} TEX index(es) created: {', '.join(missing) or '-'}")
