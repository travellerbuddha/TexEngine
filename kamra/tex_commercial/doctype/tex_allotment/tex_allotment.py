# Copyright (c) 2026, TEX Engine contributors (derived from Kamra PMS, HeyKoala and contributors)
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document

# days before each night; a year is the longest booking window TEX sells (ADR-048)
MAX_DAYS = 365


class TEXAllotment(Document):
	def validate(self):
		if str(self.date_from) > str(self.date_to):
			frappe.throw("Allotment ends before it starts.")
		if int(self.rooms or 0) < 0:
			frappe.throw("Rooms cannot be negative.")
		# release: unsold rooms go back to general sale; cutoff: the contract's booking
		# deadline. Two separate deadlines, in days before each night (G-49)
		for field, label in (("release_days", _("Release days")), ("cutoff_days", _("Cutoff days"))):
			days = int(self.get(field) or 0)
			if days < 0 or days > MAX_DAYS:
				frappe.throw(_("{0} must be between 0 and {1}.").format(label, MAX_DAYS))
		contract_prop = frappe.db.get_value("TEX Contract", self.contract, "property")
		if contract_prop and contract_prop != self.property:
			frappe.throw("The contract belongs to another hotel.")
