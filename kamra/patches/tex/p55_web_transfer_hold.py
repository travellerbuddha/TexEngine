"""C2 (audit 1c, user decision): a bank transfer booked on the web keeps its rooms 24 hours
(``TEX Settings.hold_minutes_transfer_web``; a hotel may override it with
``Property.tex_hold_minutes_transfer_web``), and the web takes at most two rooms by transfer; the call
centre and staff keep ``hold_minutes_transfer`` (48 hours).

Syncs the two DocTypes and gives the new setting its default when it has none; a value an
administrator set is kept, so a second run changes nothing. No hotel gets an override."""

import frappe


def execute():
	frappe.reload_doc("tex_platform", "doctype", "tex_settings")
	frappe.reload_doc("kamra", "doctype", "property")
	if not frappe.db.get_single_value("TEX Settings", "hold_minutes_transfer_web"):
		frappe.db.set_single_value("TEX Settings", "hold_minutes_transfer_web", 1440)
