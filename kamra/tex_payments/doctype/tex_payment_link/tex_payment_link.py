# Copyright (c) 2026, TEX Engine contributors (derived from Kamra PMS, HeyKoala and contributors)
# For license information, please see license.txt

from frappe.model.document import Document

from kamra.tex.commercial.revisions import guard_immutable


class TEXPaymentLink(Document):
	def validate(self):
		# what the guest is asked to pay never changes after the link exists
		guard_immutable(self, allowed=("status", "paid_amount", "allocated_amount", "token_hash", "public_url",
		                               "expires_at"))
