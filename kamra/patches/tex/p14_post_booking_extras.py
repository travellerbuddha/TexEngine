"""Extras added after booking (G-22): an order cut-off per extra, and the ADD_ON pricing
basis on reservation revisions. Existing extras can be added until the day they are used."""

import frappe


def execute():
	frappe.reload_doc("tex_commercial", "doctype", "tex_extra")
	frappe.reload_doc("tex_booking", "doctype", "tex_reservation_revision")
	frappe.db.sql("UPDATE `tabTEX Extra` SET order_cutoff_hours=0 WHERE order_cutoff_hours IS NULL")
