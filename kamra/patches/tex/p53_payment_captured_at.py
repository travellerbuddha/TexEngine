"""B4: a payment is late by the gateway's clock — when it captured (or authorised) the money, when
it states it (``TEX Payment Transaction.captured_at``) — never by when its news reached TEX.

Only the DocType is synced: a charge recorded before this patch has no such time and is judged as
before (when its news arrived), so a second run changes nothing."""

import frappe


def execute():
	frappe.reload_doc("tex_payments", "doctype", "tex_payment_transaction")
