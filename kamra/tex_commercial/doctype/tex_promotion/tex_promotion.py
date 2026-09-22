# Copyright (c) 2026, TEX Engine contributors (derived from Kamra PMS, HeyKoala and contributors)
# For license information, please see license.txt

import frappe
from frappe.model.document import Document

from kamra.tex.commercial.revisions import block_delete, guard_revisioned


class TEXPromotion(Document):
	def validate(self):
		guard_revisioned(self)
		if self.trigger == "Code":
			self.code = (self.code or "").strip().upper()
			if not self.code:
				frappe.throw("A code promotion needs a code.")
		else:
			self.code = None
		if self.value_type == "PERCENT" and not (0 < float(self.value or 0) <= 100):
			frappe.throw("A percentage must be between 0 and 100.")
		if self.value_type == "FREE_NIGHTS" and not (
				int(self.free_nights_stay or 0) > int(self.free_nights_pay or 0) >= 0 and self.free_nights_stay):
			frappe.throw("Stay X pay Y needs X greater than Y.")
		if self.value_type in ("FIXED_STAY", "FIXED_NIGHT") and not self.currency:
			frappe.throw("A fixed discount needs a currency.")
		if self.code and self.tex_status in ("Draft", "Active"):
			clash = frappe.db.sql("""SELECT name FROM `tabTEX Promotion` WHERE code=%s AND name!=%s
			   AND tex_status IN ('Draft','Active') AND IFNULL(property,'')=%s
			   AND IFNULL(revision_of,name) != %s""",
			                      (self.code, self.name or "", self.property or "", self.revision_of or self.name or ""))
			if clash:
				frappe.throw(f"Code {self.code} is already used by promotion {clash[0][0]}.")

	def on_trash(self):
		block_delete(self, lambda d: d.tex_status != "Draft")
