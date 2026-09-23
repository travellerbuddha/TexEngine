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
		"""A version created outside ``new_draft`` (Desk, REST) for a published contract, with no
		selling terms of its own, starts from the last published version's frozen ones instead of
		selling everywhere, always (G-50, ADR-045)."""
		from kamra.tex.commercial import contracts as svc

		if self.based_on or not svc.is_published(self.contract):
			return
		if any(self.get(f) for f in svc.SELLING_FIELDS) or self.get("channels"):
			return
		last = frappe.db.get_value("TEX Contract Version", {"contract": self.contract, "status": ("!=", "Draft")},
		                           "name", order_by="version_no desc")
		header = frappe.db.get_value("TEX Contract", self.contract, ["priority", "sell_currency"], as_dict=True)
		svc.set_selling(self, svc.frozen_selling(svc.load_terms(last), header))

	def on_trash(self):
		if self.status != "Draft":
			frappe.throw(_("Published contract versions cannot be deleted."))
