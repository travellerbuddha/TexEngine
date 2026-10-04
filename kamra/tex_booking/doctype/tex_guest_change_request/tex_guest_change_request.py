# Copyright (c) 2026, TEX Engine contributors (derived from Kamra PMS, HeyKoala and contributors)
# For license information, please see license.txt

from frappe.model.document import Document

from kamra.tex.commercial.revisions import block_delete, guard_immutable

# what happens to a request after the guest made it; what the guest asked for, the totals and
# the amount to pay first are never edited (G-45, ADR-044)
OUTCOME = ("status", "payment_transaction", "attempt", "settlement", "settlement_amount", "refunded_amount",
           "settle_pending", "staff_open", "staff_amount", "staff_reason", "unknown_refund", "refund_in_flight", "refund_rows", "staff_settled",
           "returned_charges", "settle_claim", "settle_claimed_until", "revision", "error", "resolved_by",
           "resolved_at", "resolution", "staff_kept_excess", "staff_kept_at", "credit_at")


class TEXGuestChangeRequest(Document):
	def validate(self):
		guard_immutable(self, allowed=OUTCOME)

	def on_trash(self):
		block_delete(self)
