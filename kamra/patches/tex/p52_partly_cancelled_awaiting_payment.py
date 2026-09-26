"""B1 (audit 1b): a booking waiting for its payment one of whose rooms was cancelled became
"Partially Cancelled" — a status reports and the CRM count as confirmed — and was then never
expired: its other rooms kept their inventory, and its payment never confirmed them.

Such a booking (Partially Cancelled, no room ever confirmed, a room still waiting for the
payment) waits for its payment again: Pending Payment (Held when its rooms are held without a
payment), never asking more than it costs or its rooms left require now. A fee its cancelled room
was charged before C6 is void (a booking never confirmed owes none; what a room carried for the
others stays, E1, E6). One whose payment was taken — it holds what it owes now — is confirmed with its
rooms still held (D1, audited); any other whose hold is over expires now with the rooms it has left
(``booking.expire_booking``: atomic, audited), owing nothing. No e-mail leaves the migration. A second
run finds none."""

import frappe

WAITING = ("Pending Payment", "Held")
CONFIRMED = ("Confirmed", "Checked In", "Checked Out", "No Show")


def execute():
	from kamra.tex.services import booking

	for name in frappe.get_all("TEX Booking", filters={"status": "Partially Cancelled"}, pluck="name"):
		states = frappe.get_all("Reservation", filters={"tex_booking": name}, pluck="status")
		if any(s in CONFIRMED for s in states) or not any(s in WAITING for s in states):
			continue
		status = "Pending Payment" if "Pending Payment" in states else "Held"
		frappe.db.set_value("TEX Booking", name, "status", status, update_modified=False)
		booking.void_fees(frappe.get_doc("TEX Booking", name), keep_clawback=True,
		                  reason="p52: charged before C6 on a booking never confirmed")
		booking._refresh_booking_after_change(name)            # its total, and what it owes now (D1, E2)
		if not booking.confirm_if_paid(name, reason="p52: its payment was taken before B1", send_mail=False):
			booking.expire_booking(name, send_mail=False)
