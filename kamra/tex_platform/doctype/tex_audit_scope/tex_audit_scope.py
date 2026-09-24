# Copyright (c) 2026, TEX Engine contributors (derived from Kamra PMS, HeyKoala and contributors)
# For license information, please see license.txt

import frappe
from frappe.model.document import Document


class TEXAuditScope(Document):
	"""A hotel an audit event of a hotel group or an enterprise reached (ADR-053). Written with
	its event (``kamra.tex.security.audit.audit``) and as immutable as it."""

	def validate(self):
		if not self.is_new():
			frappe.throw("Audit events are immutable.")

	def on_trash(self):
		frappe.throw("Audit events cannot be deleted.")
