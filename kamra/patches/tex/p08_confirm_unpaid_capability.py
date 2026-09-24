"""Add ``reservation.confirm_unpaid`` to the seeded permission profiles that should
carry it (confirming a booking before its deposit is paid used to be open to every
user who could create bookings; it is now a separate capability)."""

import frappe

from kamra.tex.security.capabilities import DEFAULT_PROFILES
from kamra.tex.setup import ran_before

CAP = "reservation.confirm_unpaid"


def execute():
	if ran_before(__name__):
		return          # once, at the upgrade: a capability removed since is not given back (G-76)
	for name, caps in DEFAULT_PROFILES.items():
		if CAP not in caps or not frappe.db.exists("TEX Permission Profile", name):
			continue
		if frappe.db.exists("TEX Profile Capability", {"parent": name, "parenttype": "TEX Permission Profile",
		                                               "capability": CAP}):
			continue
		doc = frappe.get_doc("TEX Permission Profile", name)
		doc.append("capabilities", {"capability": CAP})
		doc.save(ignore_permissions=True)
