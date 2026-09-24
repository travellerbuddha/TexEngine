# Copyright (c) 2026, TEX Engine contributors (derived from Kamra PMS, HeyKoala and contributors)
# For license information, please see license.txt

import frappe
from frappe.model.document import Document

from kamra.tex.commercial.revisions import block_delete, guard_immutable


class TEXLoyaltyLedger(Document):
	def validate(self):
		guard_immutable(self, allowed=("status",))
		if self.is_new() and not self.property:
			# the hotel the entry belongs to: its booking's or stay's (ADR-056 second review); a manual
			# adjustment names the hotel it was made for (``crm.loyalty.adjust``)
			self.property = (frappe.db.get_value("TEX Booking", self.booking, "property") if self.booking else None) \
				or (frappe.db.get_value("Reservation", self.reservation, "property") if self.reservation else None) \
				or frappe.db.get_value("TEX Loyalty Program", self.program, "property")

	def on_trash(self):
		block_delete(self)
