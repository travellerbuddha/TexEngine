"""Guest stats count completed stays only and keep the lifetime-value currency
(``tex_lifetime_currency``); recompute them for every guest with reservations."""

import frappe


def execute():
	from kamra.tex.crm.service import refresh_guest_stats

	for guest in frappe.get_all("Reservation", filters={"guest": ("is", "set")}, pluck="guest", distinct=True):
		refresh_guest_stats(guest)
