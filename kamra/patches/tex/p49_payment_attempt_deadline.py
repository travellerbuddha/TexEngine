"""K-2a: a payment attempt has a deadline (``TEX Payment Transaction.expires_at``) and a booking
records until when an attempt started within its hold keeps its rooms
(``TEX Booking.payment_attempt_until``).

Only the two DocTypes are synced. Existing rows stay empty: a Pending charge without a deadline
counts as in flight for ``holds.CHECKOUT_MINUTES`` after it was created, and a booking without
``payment_attempt_until`` has no attempt keeping its rooms, as before (nothing is backfilled, so
a second run changes nothing)."""

import frappe


def execute():
	frappe.reload_doc("tex_payments", "doctype", "tex_payment_transaction")
	frappe.reload_doc("tex_booking", "doctype", "tex_booking")
