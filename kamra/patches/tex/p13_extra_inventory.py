"""Capacity-limited extras (G-19): the day counters and the allocation ledger.

Stays already sold hold the units of the extras that are limited now, from their price
snapshot, for today onwards; the counters are then rebuilt from that ledger. Idempotent.
"""

import frappe


def execute():
	frappe.reload_doc("tex_commercial", "doctype", "tex_extra_inventory_day")
	frappe.reload_doc("tex_commercial", "doctype", "tex_extra_allocation")
	from kamra.tex.availability import extras_repository as xinv
	from kamra.tex.setup import ensure_indexes

	ensure_indexes()
	props = {r.property for r in frappe.get_all("TEX Extra", filters={"inventory_tracked": 1}, fields=["property"])}
	for prop in sorted(props):
		filled = xinv.backfill(prop)
		xinv.reconcile(prop)
		if filled:
			print(f"G-19: {prop}: {filled} reservation(s) now hold their limited extras")
