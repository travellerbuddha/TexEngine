"""Manual FX rates per hotel (O-12, ADR-069).

- TEX FX Rate gets its ``property`` field (a manual rate is entered for one hotel; blank = every
  hotel, as every row was until now).
- ``fx.manual_rate`` (enter a dated manual rate that bridges a provider gap) is added to the seeded
  profiles that carry it (Revenue Manager, Finance and the admin profiles); custom profiles are left to
  their owners. Once, at the upgrade (G-76): a forced re-run does not give back a capability removed
  since.

Nothing else changes: the rows already in TEX FX Rate stay global, and no price, snapshot or payload moves."""

import frappe

from kamra.tex.security.capabilities import DEFAULT_PROFILES
from kamra.tex.setup import ran_before

CAP = "fx.manual_rate"


def execute():
	frappe.reload_doc("tex_commercial", "doctype", "tex_fx_rate")
	if ran_before(__name__):
		return
	for name, caps in DEFAULT_PROFILES.items():
		if CAP not in caps or not frappe.db.exists("TEX Permission Profile", name):
			continue
		if frappe.db.exists("TEX Profile Capability", {"parent": name, "parenttype": "TEX Permission Profile",
		                                               "capability": CAP}):
			continue
		doc = frappe.get_doc("TEX Permission Profile", name)
		doc.append("capabilities", {"capability": CAP})
		doc.save(ignore_permissions=True)
