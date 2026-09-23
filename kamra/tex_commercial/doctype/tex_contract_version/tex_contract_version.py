# Copyright (c) 2026, TEX Engine contributors (derived from Kamra PMS, HeyKoala and contributors)
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document

from kamra.tex.commercial.revisions import guard_immutable


class TEXContractVersion(Document):
	def autoname(self):
		last = frappe.db.sql("SELECT MAX(version_no) FROM `tabTEX Contract Version` WHERE contract=%s",
		                     self.contract)[0][0] or 0
		self.version_no = int(last) + 1
		self.name = f"{self.contract}-V{self.version_no}"

	def validate(self):
		if self.is_new():
			self._default_selling_terms()
		# a draft's selling terms (G-50): the same checks as on the contract header
		for a, b, label in (("sale_from", "sale_to", _("Sale window")), ("stay_from", "stay_to", _("Stay window"))):
			if self.get(a) and self.get(b) and str(self.get(a)) > str(self.get(b)):
				frappe.throw(_("{0} ends before it starts.").format(label))
		if self.is_new():
			self.status = "Draft"
			return
		before = self.get_doc_before_save()
		if before and before.status != "Draft":
			# published versions are immutable (ADR-004); only lifecycle fields move,
			# and only through the contract service
			if not self.flags.tex_lifecycle:
				guard_immutable(self)
		elif before and before.status == "Draft" and self.status != "Draft" and not self.flags.tex_lifecycle:
			frappe.throw(_("Use Publish to publish a version."))

	def _default_selling_terms(self):
		"""A version created with no selling terms of its own for a published contract (Desk, REST,
		a Desk "Duplicate") starts from what its source sold (``based_on``, else the last published
		version) instead of selling everywhere, always (G-50, ADR-045)."""
		from kamra.tex.commercial import contracts as svc

		if not svc.selling_empty(self) or not svc.is_published(self.contract):
			return
		src = None
		if self.based_on:
			src = frappe.db.get_value("TEX Contract Version", {"name": self.based_on, "contract": self.contract,
			                                                   "status": ("!=", "Draft")}, "name")
		src = src or frappe.db.get_value("TEX Contract Version", {"contract": self.contract,
		                                                          "status": ("!=", "Draft")},
		                                 "name", order_by="version_no desc")
		svc.set_selling(self, svc.version_selling(src).draft_values())

	def on_trash(self):
		if self.status != "Draft":
			frappe.throw(_("Published contract versions cannot be deleted."))
