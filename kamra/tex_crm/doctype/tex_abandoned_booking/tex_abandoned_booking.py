# Copyright (c) 2026, TEX Engine contributors (derived from Kamra PMS, HeyKoala and contributors)
# For license information, please see license.txt

import frappe
from frappe.model.document import Document


class TEXAbandonedBooking(Document):
	def validate(self):
		"""A case keeps contact data (and what leads to the person: its quote) only while the profile's
		own marketing e-mail consent holds, read with a lock as the case is written (ADR-056 second
		review): a withdrawal that committed after the scheduler looked is seen here, and one still
		running waits for this case and then clears it (``crm.service.forget_contact``)."""
		if not (self.guest or self.email or self.phone or self.consent_marketing or self.quote):
			return
		agreed = frappe.db.sql("SELECT tex_consent_email FROM `tabGuest` WHERE name = %s FOR UPDATE",
		                       self.guest) if self.guest else None
		if not (agreed and agreed[0][0]):
			self.guest = self.email = self.phone = self.quote = None
			self.consent_marketing = 0
