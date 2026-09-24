"""TEX T1-T3: custom fields, permission profiles, markets/channels, enterprise backfill.

The data steps run once, at the upgrade (review of G-76, M2). Once the site runs TEX, its
administrators decide these things, and a forced re-run leaves them alone:
- the seeded profiles, markets and channels they deleted;
- the TEX Settings they changed (brand name, default channel, the legacy PMS shown or hidden);
- the hotels they keep outside TEX. Putting such a hotel in the tenant's group would give that
  group's and enterprise's grants access to it.
Only the ``User Permission.tex_managed`` custom field is ensured on every run."""

import frappe


def execute():
	from kamra.tex import setup

	setup.ensure_custom_fields()
	if not setup.ran_before(__name__):
		setup.ensure_profiles()
		setup.ensure_masters()
		setup.ensure_enterprise()
		setup.default_legacy_pms_visibility()
	frappe.clear_cache()
