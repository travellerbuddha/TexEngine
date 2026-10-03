"""O-37 (audit Part 2I): no secret stays in plain text in a change history (Version).

TEX Integration Connection.api_key was a tracked Data field for a day (2026-09-22 to 09-23) before it became a
Password: its Version rows kept the plain keys, which the hotel's Hotel Admins read in Desk (docinfo), and every
tenant for a connection without a hotel. p18 encrypted only the column; p24 masked only the TEX Payment Provider
Account's history.

For every DocType with a Password field (DocField or Custom Field), this masks those fields in its Version rows:
``changed`` entries, and a child table's secret fields in ``row_changed`` entries and in the rows ``added`` and
``removed`` keep whole (LO-29; no child table has a Password field today; the rule is there for one that will). A value is masked unless it is already all asterisks (p24's
rule), so Frappe's own "********" stays as it is. Batches by name, without touching ``modified``; prints only the
count, never a value; a second run masks none."""

import json

import frappe

MASK = "*****"
BATCH = 500
TABLE_TYPES = ("Table", "Table MultiSelect")


def password_fields() -> dict[str, set[str]]:
	"""{DocType: its Password fields}, standard and custom."""
	out: dict[str, set[str]] = {}
	for r in frappe.get_all("DocField", filters={"fieldtype": "Password"}, fields=["parent", "fieldname"]):
		out.setdefault(r.parent, set()).add(r.fieldname)
	for r in frappe.get_all("Custom Field", filters={"fieldtype": "Password"}, fields=["dt", "fieldname"]):
		out.setdefault(r.dt, set()).add(r.fieldname)
	return out


def _mask_value(value) -> tuple[object, bool]:
	if not value or set(str(value)) == {"*"}:
		return value, False
	return MASK, True


def _mask_cells(cells, fields: set[str]) -> bool:
	hit = False
	for cell in cells or []:
		if isinstance(cell, list) and len(cell) >= 3 and cell[0] in fields:
			for i in (1, 2):
				cell[i], masked = _mask_value(cell[i])
				hit = hit or masked
	return hit


def _mask_row(row: dict, fields: set[str]) -> bool:
	hit = False
	for field in fields:
		if field in row:
			row[field], masked = _mask_value(row[field])
			hit = hit or masked
	return hit


def mask(data: dict, fields: set[str], tables: dict[str, set[str]]) -> bool:
	"""Mask, in place, one Version's secrets: ``changed`` entries of ``fields``; for a table field named in
	``tables``, that table's secret fields in its ``row_changed`` entries and in the rows ``added`` and ``removed``
	keep whole (Frappe's ``as_dict``, LO-29). → whether anything was masked."""
	hit = _mask_cells(data.get("changed"), fields)
	for row in data.get("row_changed") or []:
		if isinstance(row, list) and len(row) >= 4 and row[0] in tables:
			hit = _mask_cells(row[3], tables[row[0]]) or hit
	for key in ("added", "removed"):
		for entry in data.get(key) or []:
			if isinstance(entry, list) and len(entry) >= 2 and entry[0] in tables and isinstance(entry[1], dict):
				hit = _mask_row(entry[1], tables[entry[0]]) or hit
	return hit


def _tables(secrets: dict[str, set[str]], children: set[str]) -> dict[str, dict[str, set[str]]]:
	"""{parent DocType: {table field: the child table's secret fields}}."""
	out: dict[str, dict[str, set[str]]] = {}
	if not children:
		return out
	for r in frappe.get_all("DocField", filters={"fieldtype": ("in", TABLE_TYPES), "options": ("in", sorted(children))},
	                        fields=["parent", "fieldname", "options"]):
		out.setdefault(r.parent, {})[r.fieldname] = secrets[r.options]
	for r in frappe.get_all("Custom Field", filters={"fieldtype": ("in", TABLE_TYPES), "options": ("in", sorted(children))},
	                        fields=["dt", "fieldname", "options"]):
		out.setdefault(r.dt, {})[r.fieldname] = secrets[r.options]
	return out


def execute():
	secrets = password_fields()
	children = {dt for dt in secrets if frappe.db.get_value("DocType", dt, "istable")}
	tables = _tables(secrets, children)
	masked = 0
	for doctype in sorted((set(secrets) - children) | set(tables)):
		fields, table_fields = secrets.get(doctype, set()), tables.get(doctype, {})
		last = ""
		while True:
			rows = frappe.get_all("Version", filters={"ref_doctype": doctype, "name": (">", last)},
			                      fields=["name", "data"], order_by="name asc", limit=BATCH)
			if not rows:
				break
			for v in rows:
				try:
					data = json.loads(v.data or "{}")
				except ValueError:
					continue
				if isinstance(data, dict) and mask(data, fields, table_fields):
					frappe.db.set_value("Version", v.name, "data",
					                    json.dumps(data, indent=1, sort_keys=True, default=str), update_modified=False)
					masked += 1
			last = rows[-1].name
	print(f"p63: {masked} change-history row(s) with a secret masked")
