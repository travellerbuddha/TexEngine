# Copyright (c) 2026, TEX Engine contributors (derived from Kamra PMS, HeyKoala and contributors)
# For license information, please see license.txt

import frappe
from frappe.model.document import Document

from kamra.tex.commercial.revisions import block_delete, guard_immutable


class TEXPaymentTransaction(Document):
	def validate(self):
		if self.card_last4 and (len(self.card_last4) != 4 or not self.card_last4.isdigit()):
			frappe.throw("Only the last four card digits may be stored.")
		before = self.get_doc_before_save()
		if before and before.status in ("Succeeded", "Failed", "Cancelled"):
			guard_immutable(self)
		else:
			guard_immutable(self, allowed=("status", "provider_ref", "raw_status", "error_code", "error_message",
			                               "completed_at", "card_brand", "card_last4"))

	def on_trash(self):
		block_delete(self)
