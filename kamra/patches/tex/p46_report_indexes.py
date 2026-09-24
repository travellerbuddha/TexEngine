"""G-46 review (ADR-059 review follow-up): reports read a hotel's stays by arrival and a hotel's or
hotel-group site's booking-engine funnel by time, instead of scanning every tenant's rows.

Creates the missing composite indexes ``tex_res_prop_ci`` (Reservation: property, check_in_date),
``tex_funnel_prop_time`` (TEX Funnel Event: property, occurred_at) and ``tex_funnel_site_time``
(TEX Funnel Event: site, occurred_at) from ``setup.TEX_INDEXES``. Composite, so Frappe's schema
sync leaves them alone (p39). Idempotent: an index that exists is not created again, so a forced
re-run runs no DDL.
"""


def execute():
	from kamra.tex import setup

	missing = [name for _dt, _fields, name in setup.missing_indexes()]
	setup.ensure_indexes()
	print(f"p46: {len(missing)} TEX index(es) created: {', '.join(missing) or '-'}")
