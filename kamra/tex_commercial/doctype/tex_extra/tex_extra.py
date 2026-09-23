# Copyright (c) 2026, TEX Engine contributors (derived from Kamra PMS, HeyKoala and contributors)
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document

from kamra.tex.commercial.revisions import block_delete, guard_revisioned, live_or_scheduled_roots
from kamra.tex.money import D


class TEXExtra(Document):
	def validate(self):
		# effective-dated (G-20): a live revision is never edited, a change is a new revision
		guard_revisioned(self)
		self.extra_code = (self.extra_code or "").strip().upper()
		if self.revision_of and frappe.db.get_value("TEX Extra", self.revision_of, "extra_code") != self.extra_code:
			# bookings, loyalty rules, translations and capacity know an extra by its code
			frappe.throw(_("A revision keeps its code ({0}).").format(
				frappe.db.get_value("TEX Extra", self.revision_of, "extra_code")))
		root = self.revision_of or self.name or ""
		# one record per code and hotel: another record's draft, or a revision of it that is
		# live now or scheduled (a superseded revision stays live until its successor starts)
		clash = frappe.db.sql("""SELECT name FROM `tabTEX Extra` WHERE property=%s AND extra_code=%s
		                         AND tex_status='Draft' AND name != %s AND IFNULL(revision_of, name) != %s""",
		                      (self.property, self.extra_code, self.name or "", root), pluck=True) \
			or live_or_scheduled_roots("TEX Extra", {"property": self.property, "extra_code": self.extra_code},
			                           exclude_root=root)
		if clash:
			frappe.throw(_("Extra code {0} already exists ({1}).").format(self.extra_code, clash[0]))
		for label, value in (("price", self.amount), ("child price", self.child_amount),
		                     ("infant price", self.infant_amount)):
			if D(value or 0) < 0:
				frappe.throw(_("The {0} cannot be negative.").format(_(label)))
		for r in self.price_rules or []:
			if any(D(v or 0) < 0 for v in (r.amount, r.child_amount, r.infant_amount)):
				frappe.throw(_("Price rule {0}: a price cannot be negative.").format(r.idx))

	def on_trash(self):
		block_delete(self, lambda d: d.tex_status != "Draft")
