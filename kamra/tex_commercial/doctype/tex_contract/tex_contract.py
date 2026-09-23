# Copyright (c) 2026, TEX Engine contributors (derived from Kamra PMS, HeyKoala and contributors)
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document


class TEXContract(Document):
	def validate(self):
		self.contract_code = (self.contract_code or "").strip().upper()
		clash = frappe.db.get_value("TEX Contract", {"property": self.property, "contract_code": self.contract_code,
		                                             "name": ("!=", self.name or "")})
		if clash:
			frappe.throw(_("Contract code {0} already exists for this hotel ({1}).").format(self.contract_code, clash))
		for a, b, label in (("sale_from", "sale_to", _("Sale window")), ("stay_from", "stay_to", _("Stay window"))):
			if self.get(a) and self.get(b) and str(self.get(a)) > str(self.get(b)):
				frappe.throw(_("{0} ends before it starts.").format(label))
		before = self.get_doc_before_save()
		if before and before.contract_currency != self.contract_currency and self.active_version:
			frappe.throw(_("The contract currency cannot change after a version was published."))
		if before and before.pricing_basis != self.pricing_basis and self.active_version:
			frappe.throw(_("The pricing basis cannot change after a version was published."))

	def on_update(self):
		before = self.get_doc_before_save()
		if before and before.status != self.status:
			from kamra.tex.security.audit import audit

			audit("contract.status", reference_doctype=self.doctype, reference_name=self.name,
			      property=self.property, old={"status": before.status}, new={"status": self.status})

	def after_insert(self):
		# a hotel's first TEX contract makes it a TEX hotel: its taxes become a policy (G-20)
		from kamra.tex.hooks import seed_tax_policy

		seed_tax_policy(self.property)

	def on_trash(self):
		if frappe.db.exists("TEX Contract Version", {"contract": self.name, "status": ("!=", "Draft")}):
			frappe.throw(_("A contract with published versions cannot be deleted; archive it."))
