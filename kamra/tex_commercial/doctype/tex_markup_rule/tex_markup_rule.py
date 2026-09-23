# Copyright (c) 2026, TEX Engine contributors (derived from Kamra PMS, HeyKoala and contributors)
# For license information, please see license.txt

import frappe
from frappe.model.document import Document

from kamra.tex.commercial.revisions import block_delete, guard_revisioned
from kamra.tex.money import D


class TEXMarkupRule(Document):
	def validate(self):
		guard_revisioned(self)
		if self.op == "ADD" and not self.currency:
			frappe.throw("A fixed markup needs a currency.")
		# a markup never sells for nothing (G-18)
		if self.op == "ADJUST_PERCENT" and D(self.value or 0) <= -100:
			frappe.throw("A markup cannot take off 100 % or more.")
		if self.op == "MULTIPLY" and D(self.value or 0) <= 0:
			frappe.throw("A markup multiplier must be above 0.")
		if self.stay_from and self.stay_to and self.stay_from > self.stay_to:
			frappe.throw("Stay window ends before it starts.")

	def on_trash(self):
		block_delete(self, lambda d: d.tex_status != "Draft")
