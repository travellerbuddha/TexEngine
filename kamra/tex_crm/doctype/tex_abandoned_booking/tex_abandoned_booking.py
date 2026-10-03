# Copyright (c) 2026, TEX Engine contributors (derived from Kamra PMS, HeyKoala and contributors)
# For license information, please see license.txt

import frappe
from frappe.model.document import Document


class TEXAbandonedBooking(Document):
	def validate(self):
		"""A case keeps contact data (and what leads to the person: its quote) only while the profile's
		own marketing consent holds, each contact with its channel's (C-03): the e-mail with e-mail consent,
		the phone with SMS or WhatsApp consent; read with a lock as the case is written (ADR-056 second
		review): a withdrawal that committed after the scheduler looked is seen here, and one still
		running waits for this case and then clears it (``crm.service.forget_contact``)."""
		if not (self.guest or self.email or self.phone or self.consent_marketing or self.quote):
			return
		agreed = frappe.db.sql("""SELECT tex_consent_email, tex_consent_sms, tex_consent_whatsapp FROM `tabGuest`
			WHERE name = %s FOR UPDATE""", self.guest) if self.guest else None
		email_ok, sms_ok, whatsapp_ok = agreed[0] if agreed else (0, 0, 0)
		if not (email_ok or sms_ok or whatsapp_ok):
			self.guest = self.email = self.phone = self.quote = None
			self.consent_marketing = 0
			return
		if not email_ok:
			self.email = None
		if not (sms_ok or whatsapp_ok):
			self.phone = None
