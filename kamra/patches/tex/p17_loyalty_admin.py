"""Loyalty administration (G-24).

- ``loyalty.edit`` is added to the default profiles that hold it (Revenue Manager, the
  admin profiles); custom profiles are left to their owners.
- A max-redeem share of 0 used to mean 100 %; now 0 means "cannot redeem". Existing
  programs keep what they did: 0 becomes 100.
- Blackout rows were applied to earning while labelled as redemption blackouts. They
  keep earning's behaviour and now also block redemption (``Both``).
- Earnings made before G-24 get the fingerprint of their stay as it is now, so a later
  rule change does not rewrite them and a later change of the stay does.

The capability and the 0 → 100 conversion happen once, at the upgrade (G-76): a forced re-run
neither gives back a capability removed since nor turns a program set to "cannot redeem" (0)
since into 100 %.
"""

import frappe

from kamra.tex.security.capabilities import DEFAULT_PROFILES
from kamra.tex.setup import ran_before

CAP = "loyalty.edit"


def execute():
	for dt in ("tex_loyalty_program", "tex_loyalty_blackout", "tex_loyalty_ledger"):
		frappe.reload_doc("tex_crm", "doctype", dt)
	first = not ran_before(__name__)
	for name, caps in DEFAULT_PROFILES.items() if first else ():
		if CAP not in caps or not frappe.db.exists("TEX Permission Profile", name):
			continue
		if frappe.db.exists("TEX Profile Capability", {"parent": name, "parenttype": "TEX Permission Profile",
		                                               "capability": CAP}):
			continue
		doc = frappe.get_doc("TEX Permission Profile", name)
		doc.append("capabilities", {"capability": CAP})
		doc.save(ignore_permissions=True)
	if first:
		frappe.db.sql("UPDATE `tabTEX Loyalty Program` SET max_redeem_percent=100 "
		              "WHERE IFNULL(max_redeem_percent, 0) = 0")
	frappe.db.sql("UPDATE `tabTEX Loyalty Blackout` SET applies_to='Both' WHERE IFNULL(applies_to, '') = ''")
	from kamra.tex.crm.loyalty import stay_fingerprint

	for e in frappe.get_all("TEX Loyalty Ledger", filters={"entry_type": "Earn", "status": ("!=", "Reversed"),
	                                                       "reservation": ("is", "set"),
	                                                       "stay_fingerprint": ("is", "not set")},
	                        fields=["name", "reservation"]):
		res = frappe.db.get_value("Reservation", e.reservation, ["check_in_date", "check_out_date", "room_type",
		                                                         "tex_currency", "tex_total_amount",
		                                                         "amount_after_tax", "tex_pricing_snapshot"],
		                          as_dict=True)
		if res:
			frappe.db.set_value("TEX Loyalty Ledger", e.name, "stay_fingerprint", stay_fingerprint(res),
			                    update_modified=False)
