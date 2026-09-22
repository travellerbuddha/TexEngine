# Copyright (c) 2026, TEX Engine contributors (derived from Kamra PMS, HeyKoala and contributors)
# For license information, please see license.txt

import frappe
from frappe.model.document import Document

from kamra.tex.commercial.revisions import block_delete, guard_revisioned


class TEXFXPolicy(Document):
	def validate(self):
		guard_revisioned(self)
		if self.from_currency == self.to_currency:
			frappe.throw("An FX policy converts between two different currencies.")
		if self.mode == "MANUAL" and not float(self.manual_rate or 0) > 0:
			frappe.throw("A manual FX policy needs a positive rate.")

	def on_trash(self):
		block_delete(self, lambda d: d.tex_status != "Draft")
