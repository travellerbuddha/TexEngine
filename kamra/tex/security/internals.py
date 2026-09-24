"""Fields withheld from Desk / REST (G-95, G-65, G-81, ADR-056 and its review follow-up).

- Pricing internals (G-95). A price-locked snapshot carries what only ``price.view_cost`` may see
  in the TEX API: the rule explanation, cost and margin, the FX record (provider rate and row, FX
  margin, policy).
- A guest's stored totals (G-65): stays, lifetime value, last stay and loyalty points counted over
  every tenant's hotels and programs. The TEX CRM shows each viewer the totals of their own hotels.
- Who a booking-engine visitor is (G-81 review): an abandoned case's profile, e-mail and phone,
  a funnel event's profile and e-mail hash. The TEX CRM shows them with ``crm.view``, and only
  while the profile's own e-mail consent holds.

These fields are at Frappe permlevel 1 (DocType JSON), which only System Manager (the platform
administrators) may read. Frappe then leaves them out of every generic read path for everyone
else, and refuses a filter, sort or aggregate on them. A permlevel is role-based and cannot follow
a per-hotel capability, so a business user never reads them in Desk / REST, with or without
``price.view_cost``; the TEX API serves them by capability, at the viewer's hotels.

Frappe reads a DocType's Custom DocPerm rows instead of its JSON rows as soon as one exists (Kamra's
permission scripts write them): ``ensure_custom_perms`` then adds System Manager's permlevel-1 row,
so platform administrators keep reading these fields (p40, ``kamra.scripts.fix_perms_fields``).

Two Frappe paths ignore field-level read permissions and are closed here:

- the change history (``Version``), which the Desk form shows to whoever may read the record:
  the values of these fields are masked when the row is written (``mask_version``; p37 masked
  rows written before), and kept for platform administrators in a platform-level audit event
  (``version.withheld``, no hotel: only platform administrators read it);
- the document a generic write sends back (``frappe.client.set_value / save / insert / submit /
  cancel``, REST ``POST`` / ``PUT /api/resource``, ``POST /api/v2/document``): when such a request
  saves or inserts the document for a user who may not read these fields, the document is marked
  (``hide_after_write``, on ``on_update``) and its ``as_dict`` leaves them out
  (``HideInternalsAfterWrite``, ``hooks.extend_doctype_class``). Nothing else is marked: a
  ``db_set``, code's own saves and TEX services (``ignore_permissions``) keep their document whole.
"""

from __future__ import annotations

import json

import frappe

# DocType → withheld fields (permlevel ``PERMLEVEL`` in the DocType JSON)
INTERNAL_FIELDS: dict[str, tuple[str, ...]] = {
	"Reservation": ("tex_pricing_snapshot", "tex_cost_amount", "tex_margin_amount", "tex_fx_rate"),
	"TEX Quote": ("result_json",),
	"TEX Reservation Revision": ("snapshot_before", "snapshot_after"),
	"Guest": ("tex_stays", "tex_lifetime_value", "tex_lifetime_currency", "tex_last_stay", "tex_loyalty_points"),
	"TEX Abandoned Booking": ("guest", "email", "phone"),
	"TEX Funnel Event": ("guest", "email_hash"),
}
PERMLEVEL = 1
MASK = "*****"
PLATFORM_ROLE = "System Manager"
# a masked change history keeps its values here, for platform administrators only
KEPT_ACTION = "version.withheld"
# a business role that holds permlevel 1 of a DocType with withheld fields (reported by p40)
EXPOSED_ACTION = "permission.withheld_fields_exposed"
# audit events only platform administrators read, even through a record's own trail
PLATFORM_ONLY_ACTIONS = frozenset({KEPT_ACTION, EXPOSED_ACTION})
# the generic write endpoints whose response is the document just written
GENERIC_WRITE_METHODS = frozenset({"frappe.client.set_value", "frappe.client.save", "frappe.client.insert",
                                   "frappe.client.submit", "frappe.client.cancel"})


def may_read(doctype: str, user: str | None = None) -> bool:
	"""Whether Frappe lets ``user`` read the DocType's withheld fields (its permlevel)."""
	user = user or frappe.session.user
	if user == "Administrator":
		return True
	return PERMLEVEL in frappe.get_meta(doctype).get_permlevel_access("read", user=user)


# ─── the change history ──────────────────────────────────────────────────


def mask_diff(doctype: str, data: dict) -> list[list]:
	"""Mask the withheld fields' values in a Version diff (in place). → their rows as they were
	(empty: nothing to mask)."""
	fields = INTERNAL_FIELDS.get(doctype) or ()
	kept = []
	for row in data.get("changed") or []:
		if isinstance(row, list | tuple) and len(row) >= 3 and row[0] in fields:
			original = list(row)
			for i in (1, 2):
				if row[i] not in (None, "", MASK):
					row[i] = MASK
			if list(row) != original:
				kept.append(original)
	return kept


def keep(doctype: str, docname: str, version: str | None, rows: list[list]) -> None:
	"""The values a Version no longer shows, kept for platform administrators: a platform-level
	audit event (no hotel, group or enterprise: only platform administrators read it)."""
	if not rows:
		return
	from kamra.tex.security.audit import audit

	audit(KEPT_ACTION, reference_doctype=doctype, reference_name=docname,
	      new={"version": version, "changed": rows})


def mask_version(doc, method=None) -> None:
	"""``Version.before_insert``: a change of a withheld field is recorded without its values (kept
	for platform administrators by ``keep_withheld_values``)."""
	if doc.ref_doctype not in INTERNAL_FIELDS or not doc.data:
		return
	try:
		data = json.loads(doc.data)
	except ValueError:
		return
	if not isinstance(data, dict):
		return
	kept = mask_diff(doc.ref_doctype, data)
	if kept:
		doc.data = frappe.as_json(data, indent=None, separators=(",", ":"))
		doc.flags.tex_withheld = kept


def keep_withheld_values(doc, method=None) -> None:
	"""``Version.after_insert``: the masked values, under the Version's name."""
	kept = doc.flags.pop("tex_withheld", None)
	if kept:
		keep(doc.ref_doctype, doc.docname, doc.name, kept)


# ─── a generic write's response ──────────────────────────────────────────


def generic_write_request() -> bool:
	"""Whether this request is a generic write that answers with the document it wrote."""
	req = getattr(frappe.local, "request", None)
	if req is None:
		return False
	path = (getattr(req, "path", None) or "").rstrip("/")
	method = (getattr(req, "method", None) or "").upper()
	if method in ("POST", "PUT", "PATCH") and path.startswith(("/api/resource/", "/api/v2/document/")):
		return True
	for prefix in ("/api/method/", "/api/v2/method/"):
		if path.startswith(prefix):
			return path[len(prefix):] in GENERIC_WRITE_METHODS
	return (frappe.form_dict or {}).get("cmd") in GENERIC_WRITE_METHODS


def hide_after_write(doc, method=None) -> None:
	"""``on_update`` (a save or an insert; never a ``db_set``): a generic write request answers with
	this document, so leave the withheld fields out when the user may not read them."""
	if doc.flags.ignore_permissions or not generic_write_request() or may_read(doc.doctype):
		return
	doc.flags.tex_hide_internals = True


class HideInternalsAfterWrite:
	"""Mixed into the DocTypes business roles write in Desk / REST (``hooks.extend_doctype_class``)."""

	def as_dict(self, *args, **kwargs):
		d = super().as_dict(*args, **kwargs)
		if self.flags.get("tex_hide_internals"):
			for f in INTERNAL_FIELDS.get(self.doctype, ()):
				d.pop(f, None)
		return d


# ─── customised role permissions ─────────────────────────────────────────


def ensure_custom_perms(doctypes=None) -> list[str]:
	"""Where a DocType with withheld fields has Custom DocPerm rows (Frappe then ignores its JSON
	rows), add System Manager's permlevel-1 row as its JSON has it. → the DocTypes given one."""
	if not frappe.db.table_exists("Custom DocPerm"):
		return []
	added = []
	for dt in doctypes or INTERNAL_FIELDS:
		if dt not in INTERNAL_FIELDS or not frappe.db.exists("Custom DocPerm", {"parent": dt}):
			continue
		if frappe.db.exists("Custom DocPerm", {"parent": dt, "role": PLATFORM_ROLE, "permlevel": PERMLEVEL}):
			continue
		std = frappe.db.get_value("DocPerm", {"parent": dt, "role": PLATFORM_ROLE, "permlevel": PERMLEVEL},
		                          ["read", "write"], as_dict=True) or frappe._dict(read=1, write=0)
		frappe.get_doc({"doctype": "Custom DocPerm", "parent": dt, "parenttype": "DocType",
		                "parentfield": "permissions", "role": PLATFORM_ROLE, "permlevel": PERMLEVEL,
		                "read": 1, "write": 1 if std.write else 0}).insert(ignore_permissions=True)
		frappe.clear_cache(doctype=dt)
		added.append(dt)
	return added


def exposed_roles() -> list[dict]:
	"""Roles other than System Manager that may read a DocType's withheld fields (permlevel >= 1),
	from the rows Frappe uses: the Custom DocPerm rows where a DocType has any, its JSON rows
	otherwise."""
	out = []
	for dt in INTERNAL_FIELDS:
		custom = frappe.db.table_exists("Custom DocPerm") and frappe.db.exists("Custom DocPerm", {"parent": dt})
		source = "Custom DocPerm" if custom else "DocPerm"
		for r in frappe.get_all(source, filters={"parent": dt, "permlevel": (">=", PERMLEVEL), "read": 1,
		                                         "role": ("!=", PLATFORM_ROLE)}, fields=["role", "permlevel"]):
			out.append({"doctype": dt, "role": r.role, "permlevel": int(r.permlevel), "source": source})
	return sorted(out, key=lambda r: (r["doctype"], r["role"], r["permlevel"]))
