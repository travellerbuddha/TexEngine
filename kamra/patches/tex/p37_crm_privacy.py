"""CRM privacy and pricing internals (G-81, G-95, ADR-056).

1. G-81: a funnel event kept an e-mail hash (a pseudonymous identifier of the visitor) whether or
   not the visitor gave marketing consent. Hashes of events without consent are removed; events
   with consent keep theirs.
2. G-95: the change history (``Version``) of reservations, quotes and revisions kept the values
   of the pricing internals (snapshot, cost, margin, FX rate), which the Desk form shows to whoever
   may read the record. Those values are masked; which field changed stays on record, and the
   values are kept for platform administrators in a platform-level audit event
   (``version.withheld``, ADR-056 review). From now on
   ``kamra.tex.security.internals.mask_version`` does the same as a row is written.
3. The fields themselves are at permlevel 1 (DocType JSON, synced before this patch). A site
   whose role permissions for these DocTypes were customised (Custom DocPerm) uses its own rows
   instead of the JSON's: those DocTypes are listed so an administrator can check who reads
   permlevel 1.

Re-runnable. Prints what it did; never prints a hash or a value.
"""

import json

import frappe

from kamra.tex.security.internals import INTERNAL_FIELDS, keep, mask_diff

BATCH = 500


def _purge_hashes() -> int:
	if not frappe.db.has_column("TEX Funnel Event", "email_hash"):
		return 0
	n = frappe.db.count("TEX Funnel Event", {"email_hash": ("is", "set"), "consent_marketing": 0})
	if n:
		frappe.db.sql("""UPDATE `tabTEX Funnel Event` SET email_hash = NULL
			WHERE IFNULL(email_hash, '') != '' AND IFNULL(consent_marketing, 0) = 0""")
	return n


def _mask_history() -> int:
	masked = 0
	for doctype, fields in INTERNAL_FIELDS.items():
		like = " OR ".join(["data LIKE %s"] * len(fields))
		last = ""
		while True:
			rows = frappe.db.sql(  # nosemgrep -- static condition, values bound
				f"""SELECT name, docname, data FROM `tabVersion` WHERE ref_doctype = %s AND name > %s AND ({like})
				ORDER BY name LIMIT {BATCH}""", (doctype, last, *(f'%"{f}"%' for f in fields)), as_dict=True)
			if not rows:
				break
			for v in rows:
				try:
					data = json.loads(v.data or "{}")
				except ValueError:
					continue
				kept = mask_diff(doctype, data) if isinstance(data, dict) else []
				if kept:
					keep(doctype, v.docname, v.name, kept)             # for platform administrators
					frappe.db.set_value("Version", v.name, "data",
					                    frappe.as_json(data, indent=None, separators=(",", ":")), update_modified=False)
					masked += 1
			last = rows[-1].name
	return masked


def _customised() -> list[str]:
	if not frappe.db.table_exists("Custom DocPerm"):
		return []
	return sorted(set(frappe.get_all("Custom DocPerm", filters={"parent": ("in", list(INTERNAL_FIELDS))},
	                                 pluck="parent")))


def execute():
	purged = _purge_hashes()
	masked = _mask_history()
	custom = _customised()
	print(f"p37: {purged} funnel e-mail hash(es) kept without consent removed, {masked} change-history row(s) "
	      f"with pricing internals masked; customised role permissions (check permlevel 1): "
	      f"{', '.join(custom) or '-'}")
