"""O-13 (audit Part 2D-1, ADR-069): a withdrawn version's open quotes are expired under a lock.

``contracts.withdraw`` locks the version's open quotes (``FOR UPDATE``) before the contract, in
``create_booking``'s order. ``TEX Quote`` has no index on ``contract_version``: without one that read
scans and locks the whole quote table. Creates the composite index ``tex_quote_version_open``
(contract_version, status, expires_at) from ``setup.TEX_INDEXES`` (the p46 pattern). Composite, so
Frappe's schema sync leaves it alone (p39). Idempotent: an index that exists is not created again, so
a forced re-run runs no DDL. No row changes.
"""


def execute():
	from kamra.tex import setup

	missing = [name for _dt, _fields, name in setup.missing_indexes()]
	setup.ensure_indexes()
	print(f"p69: {len(missing)} TEX index(es) created: {', '.join(missing) or '-'}")
