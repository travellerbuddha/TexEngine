"""C-04 (owner, 2026-10-03; ADR-077): who a member is, read on every member-priced search and by a merge.

``TEX Loyalty Member`` (new) holds a guest's membership of a loyalty program; a search asks whether the guest
has one, and a merge reads and moves a profile's memberships with locking reads, so every Link to Guest has an
index that starts with it (third review of ADR-056). Creates the composite index ``tex_member_guest_program``
(guest, program) from ``setup.TEX_INDEXES`` (the p46 pattern), after the model sync made the table. Composite,
so Frappe's schema sync leaves it alone (p39). Idempotent: an index that exists is not created again, so a forced
re-run runs no DDL. No row changes.
"""


def execute():
	from kamra.tex import setup

	missing = [name for _dt, _fields, name in setup.missing_indexes()]
	setup.ensure_indexes()
	print(f"p77: {len(missing)} TEX index(es) created: {', '.join(missing) or '-'}")
