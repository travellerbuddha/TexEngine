"""K-2a: a payment attempt has a deadline (``TEX Payment Transaction.expires_at``) and a booking
records until when an attempt started within its hold keeps its rooms
(``TEX Booking.payment_attempt_until``).

Only the two DocTypes are synced. Existing rows stay empty: a booking without
``payment_attempt_until`` has no attempt keeping its rooms (``holds.in_flight`` reads only that),
and a charge without ``expires_at`` has no deadline, so it keeps no rooms and its money is never
judged paid in time (``holds.paid_in_time``); nothing is backfilled, so a second run changes
nothing."""

import frappe


def execute():
	frappe.reload_doc("tex_payments", "doctype", "tex_payment_transaction")
	frappe.reload_doc("tex_booking", "doctype", "tex_booking")
