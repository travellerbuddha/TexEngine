"""G-97 (audit Part 2I): contract versions, markup rules and pricing policies are cost, read in Desk / REST by
platform administrators only; the TEX API serves them by price.view_cost.

Their JSON gives System Manager alone access now. Once a DocType has one Custom DocPerm row, Frappe ignores
the permissions in its JSON; so where these DocTypes have Custom DocPerm rows, every role's row but System
Manager's loses every flag, read included. Where they have none, nothing is done: a new row would switch the
JSON's permissions off. Prints how many rows changed; a second run changes none."""

import frappe

DOCTYPES = ("TEX Contract Version", "TEX Markup Rule", "TEX Pricing Policy")
FLAGS = ("select", "read", "write", "create", "delete", "submit", "cancel", "amend", "report", "export", "import",
         "share", "print", "email")


def execute():
	flags = [f for f in FLAGS if frappe.db.has_column("Custom DocPerm", f)]
	changed = 0
	for doctype in DOCTYPES:
		touched = False
		for row in frappe.get_all("Custom DocPerm", filters={"parent": doctype, "role": ("!=", "System Manager")},
		                          fields=["name", *flags], order_by="name asc"):
			if any(int(row.get(f) or 0) for f in flags):
				frappe.db.set_value("Custom DocPerm", row.name, dict.fromkeys(flags, 0), update_modified=False)
				changed += 1
				touched = True
		if touched:
			frappe.clear_cache(doctype=doctype)
	print(f"p66: {changed} Custom DocPerm row(s) of the cost DocTypes closed to every role but System Manager")
