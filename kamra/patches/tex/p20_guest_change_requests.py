"""Guest changes settle their money (G-45, ADR-044).

- New: TEX Guest Change Request, one row per change a guest makes on the manage page: what they
  accepted, whether it waits for a payment or for the hotel, and how the money was settled
  (paid online, at the hotel, refunded, kept as credit, left to staff).
- Property: the "When a guest change costs less" setting says what "Keep as credit" means.
Nothing existing changes: reservations a guest already changed keep their staff flag.
"""

import frappe


def execute():
	frappe.reload_doc("tex_booking", "doctype", "tex_guest_change_request")
	frappe.reload_doc("kamra", "doctype", "property")
