# Copyright (c) 2026, TEX Engine contributors (derived from Kamra PMS, HeyKoala and contributors)
# For license information, please see license.txt

import frappe
from frappe.model.document import Document


class TEXAllotment(Document):
	def validate(self):
		if str(self.date_from) > str(self.date_to):
			frappe.throw("Allotment ends before it starts.")
		if int(self.rooms or 0) < 0:
			frappe.throw("Rooms cannot be negative.")
		contract_prop = frappe.db.get_value("TEX Contract", self.contract, "property")
		if contract_prop and contract_prop != self.property:
			frappe.throw("The contract belongs to another hotel.")
