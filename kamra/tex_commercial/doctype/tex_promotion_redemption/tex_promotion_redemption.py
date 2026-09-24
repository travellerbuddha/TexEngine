# Copyright (c) 2026, TEX Engine contributors (derived from Kamra PMS, HeyKoala and contributors)
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import now_datetime

from kamra.tex.commercial.revisions import block_delete, guard_immutable


class TEXPromotionRedemption(Document):
	def validate(self):
		guard_immutable(self, allowed=("status", "booking", "reservation", "released_at"))
		# coupon usage as of a past moment counts a use from its creation until its release
		# (G-51, ADR-054): the release time is written once, when the use is given back, and a
		# use given back stays given back (using the code again is a new redemption)
		before = None if self.is_new() else self.get_doc_before_save()
		if before and before.status == "Released" and self.status != "Released":
			frappe.throw(_("A released coupon use cannot be taken again."))
		if self.status != "Released":
			self.released_at = None
		elif before and before.status == "Released":
			self.released_at = before.released_at          # written once, when it was released
		elif before or not self.released_at:
			self.released_at = now_datetime()

	def on_trash(self):
		block_delete(self)
