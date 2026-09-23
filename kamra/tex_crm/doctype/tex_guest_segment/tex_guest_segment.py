# Copyright (c) 2026, TEX Engine contributors (derived from Kamra PMS, HeyKoala and contributors)
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document


class TEXGuestSegment(Document):
	def validate(self):
		# a segment belongs to one enterprise (presets to none); its name is unique there (G-23)
		self.segment_name = (self.segment_name or "").strip()
		if self.system_key and self.enterprise:
			frappe.throw(_("A preset belongs to no enterprise."))
		taken = frappe.db.get_value("TEX Guest Segment", {
			"segment_name": self.segment_name, "enterprise": self.enterprise or ("is", "not set"),
			"name": ("!=", self.name or "")})
		if taken:
			frappe.throw(_("A segment called {0} already exists.").format(self.segment_name))
