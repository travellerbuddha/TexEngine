# Copyright (c) 2026, TEX Engine contributors (derived from Kamra PMS, HeyKoala and contributors)
# For license information, please see license.txt

import frappe
from frappe.model.document import Document


class TEXAuditEvent(Document):
	def validate(self):
		if not self.is_new():
			frappe.throw("Audit events are immutable.")

	def on_trash(self):
		frappe.throw("Audit events cannot be deleted.")
