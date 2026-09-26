"""K-2d: how long a booking's rooms wait for its payment depends on the payment method — card
(``TEX Settings.hold_minutes``, as before), payment link (``hold_minutes_link``, 24 hours) and
bank transfer (``hold_minutes_transfer``, 48 hours) — and each hotel may override each one
(``Property.tex_hold_minutes_card`` / ``_link`` / ``_transfer``, blank = the setting).

Syncs the two DocTypes and gives the two new settings their defaults when they have none; a
value an administrator set is kept, so a second run changes nothing. No hotel gets an override."""

import frappe

DEFAULTS = (("hold_minutes_link", 1440), ("hold_minutes_transfer", 2880))


def execute():
	frappe.reload_doc("tex_platform", "doctype", "tex_settings")
	frappe.reload_doc("kamra", "doctype", "property")
	for field, minutes in DEFAULTS:
		if not frappe.db.get_single_value("TEX Settings", field):
			frappe.db.set_single_value("TEX Settings", field, minutes)
