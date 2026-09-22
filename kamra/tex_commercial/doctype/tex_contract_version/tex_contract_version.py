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

	def on_trash(self):
		if self.status != "Draft":
			frappe.throw(_("Published contract versions cannot be deleted."))
