"""TEX T9: confirmed legacy reservations are price-locked so later edits never
silently re-price them (ADR-010)."""

import frappe


def execute():
	if not frappe.db.has_column("Reservation", "tex_price_locked"):
		return
	frappe.db.sql(
		"""UPDATE `tabReservation`
		   SET tex_price_locked = 1, tex_pricing_source = 'Legacy'
		   WHERE status IN ('Confirmed', 'Checked In', 'Checked Out', 'No Show')
		     AND IFNULL(tex_pricing_source, '') = ''""")
