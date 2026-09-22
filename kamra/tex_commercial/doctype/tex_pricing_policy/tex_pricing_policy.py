# Copyright (c) 2026, TEX Engine contributors (derived from Kamra PMS, HeyKoala and contributors)
# For license information, please see license.txt

import frappe
from frappe.model.document import Document

from kamra.tex.commercial.revisions import block_delete, guard_revisioned


class TEXPricingPolicy(Document):
	def validate(self):
		guard_revisioned(self)

	def on_trash(self):
		block_delete(self, lambda d: d.tex_status != "Draft")
