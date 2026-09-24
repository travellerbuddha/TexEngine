"""TEX T9: confirmed legacy reservations are price-locked so later edits never
silently re-price them (ADR-010).

Once, at the upgrade (G-76): what the legacy engine sold before TEX. A stay a hotel still outside
TEX sells at its Desk after the upgrade stays the Desk's: a forced re-run finds the patch logged
and locks nothing."""

import frappe

from kamra.tex.setup import ran_before


def execute():
	if not frappe.db.has_column("Reservation", "tex_price_locked") or ran_before(__name__):
		return
	frappe.db.sql(
		"""UPDATE `tabReservation`
		   SET tex_price_locked = 1, tex_pricing_source = 'Legacy'
		   WHERE status IN ('Confirmed', 'Checked In', 'Checked Out', 'No Show')
		     AND IFNULL(tex_pricing_source, '') = ''""")
