"""Fields withheld from Desk / REST (G-95, G-65, ADR-056).

- Pricing internals (G-95). A price-locked snapshot carries what only ``price.view_cost`` may see
  in the TEX API: the rule explanation, cost and margin, the FX record (provider rate and row, FX
  margin, policy).
- A guest's stored totals (G-65): stays, lifetime value, last stay and loyalty points counted over
  every tenant's hotels and programs. The TEX CRM shows each viewer the totals of their own hotels.

These fields are at Frappe permlevel 1 (DocType JSON), which only System Manager (the platform
administrators) may read. Frappe then leaves them out of every generic read path for everyone
else, and refuses a filter, sort or aggregate on them. A permlevel is role-based and cannot follow
a per-hotel capability, so a business user never reads them in Desk / REST, with or without
``price.view_cost``; the TEX API serves them by capability, at the viewer's hotels.

Two Frappe paths ignore field-level read permissions and are closed here:

- the change history (``Version``), which the Desk form shows to whoever may read the record:
  the values of these fields are masked when the row is written (``mask_version``; p37 masks
  rows written before). TEX keeps the full before/after in ``TEX Reservation Revision``;
- the document a generic write sends back (``frappe.client.set_value / save / insert``, REST
  ``POST`` / ``PUT /api/resource``): a save checked against the user's permissions by a user who
  may not read these fields marks the document (``hide_after_write``) and its ``as_dict`` leaves
  them out (``HideInternalsAfterWrite``, ``hooks.extend_doctype_class``). Saves by TEX services
  (``ignore_permissions``) are never marked.
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
}
PERMLEVEL = 1
MASK = "*****"


def may_read(doctype: str, user: str | None = None) -> bool:
	"""Whether Frappe lets ``user`` read the DocType's pricing internals (its permlevel)."""
	user = user or frappe.session.user
	if user == "Administrator":
		return True
	return PERMLEVEL in frappe.get_meta(doctype).get_permlevel_access("read", user=user)


def mask_diff(doctype: str, data: dict) -> bool:
	"""Mask the internal fields' values in a Version diff (in place). → whether anything changed."""
	fields = INTERNAL_FIELDS.get(doctype) or ()
	changed = False
	for row in data.get("changed") or []:
		if isinstance(row, list | tuple) and len(row) >= 3 and row[0] in fields:
			for i in (1, 2):
				if row[i] not in (None, "", MASK):
					row[i] = MASK
					changed = True
	return changed


def mask_version(doc, method=None) -> None:
	"""``Version.before_insert``: a change of a withheld field is recorded without its values."""
	if doc.ref_doctype not in INTERNAL_FIELDS or not doc.data:
		return
	try:
		data = json.loads(doc.data)
	except ValueError:
		return
	if isinstance(data, dict) and mask_diff(doc.ref_doctype, data):
		doc.data = frappe.as_json(data, indent=None, separators=(",", ":"))


def hide_after_write(doc, method=None) -> None:
	"""``on_change`` of a DocType in ``INTERNAL_FIELDS``: a save checked against the user's own
	permissions returns the document to that user; leave the internals out when they may not
	read them."""
	if doc.flags.ignore_permissions or may_read(doc.doctype):
		return
	doc.flags.tex_hide_internals = True


class HideInternalsAfterWrite:
	"""Mixed into the DocTypes of ``INTERNAL_FIELDS`` (``hooks.extend_doctype_class``)."""

	def as_dict(self, *args, **kwargs):
		d = super().as_dict(*args, **kwargs)
		if self.flags.get("tex_hide_internals"):
			for f in INTERNAL_FIELDS.get(self.doctype, ()):
				d.pop(f, None)
		return d
