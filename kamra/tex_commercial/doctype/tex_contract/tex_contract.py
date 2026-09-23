# Copyright (c) 2026, TEX Engine contributors (derived from Kamra PMS, HeyKoala and contributors)
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import getdate

# every header field an edit can touch (channels as a sorted list)
HEADER_FIELDS = ("property", "contract_code", "contract_name", "market", "status", "pricing_basis",
                 "contract_currency", "sell_currency", "priority", "is_bar", "sale_from", "sale_to", "stay_from",
                 "stay_to", "channels", "notes")
# moved only by the contract lifecycle (publish, withdraw, the scheduler) or a status action
LIFECYCLE_FIELDS = ("status", "active_version", "latest_version_no")


def header_values(doc) -> dict:
	"""The header as JSON-safe, comparable values (G-50: what the audit records)."""
	out = {}
	for f in HEADER_FIELDS:
		v = doc.get(f)
		if f == "channels":
			v = sorted({c.sales_channel for c in (v or [])})
		elif f in ("sale_from", "sale_to", "stay_from", "stay_to"):
			v = str(getdate(v)) if v else None
		elif f in ("priority", "is_bar"):
			v = int(v or 0)
		else:
			v = v or None
		out[f] = v
	return out


def header_changes(before, doc) -> dict:
	"""{field: [old, new]} for the header fields (and version pointers) that differ."""
	a, b = header_values(before), header_values(doc)
	a["active_version"], b["active_version"] = before.get("active_version") or None, doc.get("active_version") or None
	a["latest_version_no"], b["latest_version_no"] = int(before.get("latest_version_no") or 0), \
		int(doc.get("latest_version_no") or 0)
	return {f: [a[f], b[f]] for f in a if a[f] != b[f]}


class TEXContract(Document):
	def validate(self):
		if self.is_new():
			# a contract starts as a draft; publishing a version makes it Active (G-50)
			self.status = "Draft"
			self.active_version = None
			self.latest_version_no = 0
		self.contract_code = (self.contract_code or "").strip().upper()
		clash = frappe.db.get_value("TEX Contract", {"property": self.property, "contract_code": self.contract_code,
		                                             "name": ("!=", self.name or "")})
		if clash:
			frappe.throw(_("Contract code {0} already exists for this hotel ({1}).").format(self.contract_code, clash))
		for a, b, label in (("sale_from", "sale_to", _("Sale window")), ("stay_from", "stay_to", _("Stay window"))):
			if self.get(a) and self.get(b) and str(self.get(a)) > str(self.get(b)):
				frappe.throw(_("{0} ends before it starts.").format(label))
		before = self.get_doc_before_save()
		if before and not self.flags.tex_lifecycle:
			self._guard_header(before)

	def _guard_header(self, before):
		"""G-50 (ADR-045): once a version was published, what selection and pricing read is fixed;
		the status and the version pointers move only through the contract lifecycle."""
		from kamra.tex.commercial.contracts import FIXED_FIELDS, SELLING_FIELDS, is_published

		changed = header_changes(before, self)
		if "property" in changed:
			frappe.throw(_("A contract cannot move to another hotel."), title=_("Contract locked"))
		if {"active_version", "latest_version_no"} & set(changed):
			frappe.throw(_("The active version is set by publishing, withdrawing or scheduling versions."),
			             title=_("Contract locked"))
		if "status" in changed and not self.flags.tex_status_action:
			frappe.throw(_("A contract's status changes only through its actions: publish a version, or "
			               "suspend, resume, archive or restore the contract."), title=_("Contract locked"))
		if not is_published(self.name):
			return
		fixed = [f for f in FIXED_FIELDS if f in changed]
		if fixed:
			frappe.throw(_("{0} of a published contract cannot change: its versions were priced and sold on "
			               "them. Duplicate the contract to sell another market, currency or pricing basis.")
			             .format(", ".join(_(self.meta.get_label(f)) for f in fixed)), title=_("Contract locked"))
		selling = [f for f in (*SELLING_FIELDS, "channels") if f in changed]
		if selling:
			frappe.throw(_("{0} of a published contract belong to its versions and cannot be edited on the "
			               "contract. Change them in a new draft version (Settings → Selling terms) and publish "
			               "it.").format(", ".join(_(self.meta.get_label(f)) for f in selling)),
			             title=_("Contract locked"))

	def on_update(self):
		from kamra.tex.security.audit import audit

		before = self.get_doc_before_save()
		if not before or self.flags.in_insert:
			return                                  # a new contract is audited by after_insert
		changed = header_changes(before, self)
		if "status" in changed:
			audit("contract.status", reference_doctype=self.doctype, reference_name=self.name,
			      property=self.property, old={"status": before.status}, new={"status": self.status},
			      reason=self.flags.tex_status_reason)
		edits = {f: v for f, v in changed.items() if f not in LIFECYCLE_FIELDS}
		if edits and not self.flags.tex_lifecycle:
			# every header change, whatever the path (TEX API, Desk, REST); the lifecycle's own
			# changes (publish, withdraw, a scheduled version going live) are audited by it
			audit("contract.save", reference_doctype=self.doctype, reference_name=self.name,
			      property=self.property, old={f: v[0] for f, v in edits.items()},
			      new={f: v[1] for f, v in edits.items()})

	def after_insert(self):
		from kamra.tex.hooks import seed_tax_policy
		from kamra.tex.security.audit import audit

		audit("contract.save", reference_doctype=self.doctype, reference_name=self.name, property=self.property,
		      new=header_values(self))
		# a hotel's first TEX contract makes it a TEX hotel: its taxes become a policy (G-20)
		seed_tax_policy(self.property)

	def on_trash(self):
		if frappe.db.exists("TEX Contract Version", {"contract": self.name, "status": ("!=", "Draft")}):
			frappe.throw(_("A contract with published versions cannot be deleted; archive it."))
