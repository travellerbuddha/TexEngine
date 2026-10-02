"""LO-22 (audit Part 2K-4, ADR-064 addendum): the re-verification job asks every Pending card charge in turn.

By urgency alone, a tick that has more candidates than it asks (``REVERIFY_BATCH``) asked the same most urgent
charges again and again while the others waited. The job now writes when it last asked a charge
(``TEX Payment Transaction.last_reverified_at``) and, within an urgency, asks the one asked least recently first
(one never asked before any).

Only the DocType is synced: a charge recorded before this patch was never asked by that rule, which is what a
NULL says, so a second run changes nothing."""

import frappe


def execute():
	frappe.reload_doc("tex_payments", "doctype", "tex_payment_transaction")
