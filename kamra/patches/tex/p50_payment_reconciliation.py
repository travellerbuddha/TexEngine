"""K-2b: money a gateway captured that could not safely confirm its booking is kept in
reconciliation on its charge (``TEX Payment Transaction.reconciliation`` / ``reconciliation_note``).

Only the DocType is synced: no charge recorded before this patch is put in reconciliation (a
charge allocated earlier stays as it was), so a second run changes nothing."""

import frappe


def execute():
	frappe.reload_doc("tex_payments", "doctype", "tex_payment_transaction")
