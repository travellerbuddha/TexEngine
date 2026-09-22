# Copyright (c) 2026, TEX Engine contributors (derived from Kamra PMS, HeyKoala and contributors)
# For license information, please see license.txt

from frappe.model.document import Document


class TEXSalesChannel(Document):
	def validate(self):
		self.channel_code = (self.channel_code or "").strip().upper()
