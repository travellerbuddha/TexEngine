"""System status, alerts and e-mail delivery status (ADR-047).

- TEX Communication gains ``email_queue`` and ``delivery_error`` (and indexes for the status
  sync).
- E-mail communications written before this patch are linked to their Email Queue row where
  exactly one row fits, and their delivery status is synced once. The others stay Queued;
  the status check never judges a communication without a queue row.
"""

import frappe


def execute():
	frappe.reload_doc("tex_crm", "doctype", "tex_communication")
	from kamra.tex.services import mail_status
	from kamra.tex.setup import ensure_indexes

	ensure_indexes()
	linked = mail_status.backfill()
	synced = mail_status.sync_all()
	print(f"p23: {linked['matched']} queued e-mail(s) linked to their queue entry, {linked['unmatched']} left as "
	      f"they were; {synced} delivery status(es) synced")
