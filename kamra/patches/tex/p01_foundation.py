"""TEX T1-T3: custom fields, permission profiles, markets/channels, enterprise backfill."""

import frappe


def execute():
	from kamra.tex import setup

	setup.ensure_custom_fields()
	setup.ensure_profiles()
	setup.ensure_masters()
	setup.ensure_enterprise()
	setup.default_legacy_pms_visibility()
	frappe.clear_cache()
