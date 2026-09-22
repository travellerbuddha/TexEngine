# Copyright (c) 2026, TEX Engine contributors (derived from Kamra PMS, HeyKoala and contributors)
# For license information, please see license.txt

import frappe
from frappe.model.document import Document


class TEXExtra(Document):
	def validate(self):
		self.extra_code = (self.extra_code or "").strip().upper()
		clash = frappe.db.get_value("TEX Extra", {"property": self.property, "extra_code": self.extra_code,
		                                          "name": ("!=", self.name or "")})
		if clash:
			frappe.throw(f"Extra code {self.extra_code} already exists ({clash}).")
		if float(self.amount or 0) < 0:
			frappe.throw("Price cannot be negative.")
