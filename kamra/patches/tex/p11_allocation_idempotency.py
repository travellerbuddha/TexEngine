"""Payment allocations carry an idempotency key, so a double submit allocates once (G-14)."""

import frappe


def execute():
	frappe.reload_doc("tex_payments", "doctype", "tex_payment_allocation")
