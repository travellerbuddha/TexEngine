"""Payment-link URLs embed the bearer token; only its hash is kept (ADR-017)."""

import frappe


def execute():
	if frappe.db.table_exists("TEX Payment Link"):
		frappe.db.sql("UPDATE `tabTEX Payment Link` SET public_url = NULL WHERE public_url IS NOT NULL")
