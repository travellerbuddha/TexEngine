"""Y-12 (audit Part 2A, review round 1): business roles only read the Agent Action Log, also where
Custom DocPerm rows decide its permissions.

Once a DocType has one Custom DocPerm row, Frappe ignores the permissions in its JSON. The seed scripts
wrote such rows for the log: Hotel Admin read/write/create/delete (``seed_rbac_v2.ensure_hotel_admin``),
Kamra Agent create (``ensure_agent_user``; write too where ``sync_standard_perms`` mirrored the old JSON),
Front Desk create (``seed_users``). The JSON change of Y-12 does not reach them.

Where the log has Custom DocPerm rows, every role's row but System Manager's loses create, write, delete,
share, import, amend, submit and cancel; read, report, export, print and email stay. Where it has none,
nothing is done: a new row would switch the JSON's permissions off. Prints how many rows changed (no
personal data); a second run changes none."""

import frappe

DOCTYPE = "Agent Action Log"
WRITES = ("create", "write", "delete", "share", "import", "amend", "submit", "cancel")


def execute():
	flags = [f for f in WRITES if frappe.db.has_column("Custom DocPerm", f)]
	changed = 0
	for row in frappe.get_all("Custom DocPerm", filters={"parent": DOCTYPE, "role": ("!=", "System Manager")},
	                          fields=["name", *flags], order_by="name asc"):
		if any(int(row.get(f) or 0) for f in flags):
			frappe.db.set_value("Custom DocPerm", row.name, dict.fromkeys(flags, 0), update_modified=False)
			changed += 1
	if changed:
		frappe.clear_cache(doctype=DOCTYPE)
	print(f"p64: {changed} Custom DocPerm row(s) of the {DOCTYPE} made read-only")
