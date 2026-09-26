"""D2 (audit 1c): before B1, a booking waiting for its payment with a room cancelled became
"Partially Cancelled", and the old PMS job then released its other rooms. Such a leftover — every
room cancelled, "Partially Cancelled", never confirmed — was counted as confirmed and took money.

Each one is cancelled with its rooms (``booking._refresh_booking_after_change``: status, total,
coupon uses released), owing nothing — a fee its rooms were charged before C6 included (E6); the
money it held comes off it into reconciliation for staff
(``late_payments.money_off_expired``); ``booking.leftover_cancelled`` is audited. No e-mail is sent
from the migration. A booking one of whose rooms was ever confirmed is left as it is. A second run
finds none."""

import json

import frappe

from kamra.tex.money import ZERO, from_db, to_str


def ever_confirmed(name: str) -> bool:
	"""Confirmed by its payment (``booking.confirm``) or when it was made (``booking.create``)."""
	if frappe.db.exists("TEX Audit Event", {"action": "booking.confirm", "reference_name": name}):
		return True
	created = frappe.db.get_value("TEX Audit Event", {"action": "booking.create", "reference_name": name},
	                              "new_value")
	return (json.loads(created or "{}") or {}).get("status") == "Confirmed"


def execute():
	from kamra.tex.security.audit import audit
	from kamra.tex.services import booking, late_payments

	for name in frappe.get_all("TEX Booking", filters={"status": "Partially Cancelled"}, pluck="name"):
		states = frappe.get_all("Reservation", filters={"tex_booking": name}, pluck="status")
		if not states or any(s != "Cancelled" for s in states) or ever_confirmed(name):
			continue
		b = frappe.get_doc("TEX Booking", name, for_update=True)
		booking.void_fees(b, reason="p54: never confirmed, every room cancelled (C6)")
		booking._refresh_booking_after_change(name)
		paid = from_db(b.paid_amount, b.currency)
		parked = late_payments.money_off_expired(name, send_mail=False) if paid > ZERO else ZERO
		audit("booking.leftover_cancelled", reference_doctype="TEX Booking", reference_name=name, property=b.property,
		      old={"status": "Partially Cancelled"}, new={"status": frappe.db.get_value("TEX Booking", name, "status"),
		                                               "paid": to_str(paid), "parked": to_str(parked),
		                                               "currency": b.currency},
		      reason="p54: never confirmed, every room cancelled")
