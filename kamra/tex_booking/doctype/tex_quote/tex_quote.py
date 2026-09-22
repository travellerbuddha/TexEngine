# Copyright (c) 2026, TEX Engine contributors (derived from Kamra PMS, HeyKoala and contributors)
# For license information, please see license.txt

from frappe.model.document import Document

from kamra.tex.commercial.revisions import block_delete, guard_immutable


class TEXQuote(Document):
	def validate(self):
		guard_immutable(self, allowed=("status", "booking"))

	def on_trash(self):
		block_delete(self)
