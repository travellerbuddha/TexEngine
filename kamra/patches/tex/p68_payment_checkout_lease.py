"""NEW-6 (ADR-066): a charge's checkout is asked of the gateway with no row, gap or naming-series lock
held. While it is, the charge carries a lease (``TEX Payment Transaction.checkout_started_at``): a second
start of the same charge is told a payment is being started, until the lease is cleared or has lapsed.

Only the DocType is synced: a charge recorded before this patch has no lease (nothing is starting it), so
a second run changes nothing."""

import frappe


def execute():
	frappe.reload_doc("tex_payments", "doctype", "tex_payment_transaction")
