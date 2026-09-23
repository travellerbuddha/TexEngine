"""System status, alerts and e-mail delivery status (ADR-047).

- ``system.monitor`` is added to the seeded permission profiles that carry every capability
  (Hotel Admin, Group Admin, Enterprise Admin); other profiles get it only when an
  administrator adds it.
- TEX Communication gains ``email_queue`` and ``delivery_error`` (and indexes for the status
  sync).
- E-mail communications written before this patch are linked to their Email Queue row where
  exactly one row fits, and their delivery status is synced once. The others stay Queued;
  the status check never judges a communication without a queue row.
"""

import frappe

from kamra.tex.security.capabilities import DEFAULT_PROFILES

CAP = "system.monitor"


def execute():
	frappe.reload_doc("tex_crm", "doctype", "tex_communication")
	for name, caps in DEFAULT_PROFILES.items():
		if CAP not in caps or not frappe.db.exists("TEX Permission Profile", name):
			continue
		if frappe.db.exists("TEX Profile Capability", {"parent": name, "parenttype": "TEX Permission Profile",
		                                               "capability": CAP}):
			continue
		doc = frappe.get_doc("TEX Permission Profile", name)
		doc.append("capabilities", {"capability": CAP})
		doc.save(ignore_permissions=True)
	from kamra.tex.services import mail_status
	from kamra.tex.setup import ensure_indexes

	ensure_indexes()
	linked = mail_status.backfill()
	synced = mail_status.sync_all()
	print(f"p23: {linked['matched']} queued e-mail(s) linked to their queue entry, {linked['unmatched']} left as "
	      f"they were; {synced} delivery status(es) synced")
