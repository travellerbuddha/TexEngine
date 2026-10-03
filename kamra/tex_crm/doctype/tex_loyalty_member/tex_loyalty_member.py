# Copyright (c) 2026, TEX Engine contributors (derived from Kamra PMS, HeyKoala and contributors)
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document

from kamra.tex.commercial.revisions import block_delete


class TEXLoyaltyMember(Document):
	def validate(self):
		if self.is_new():
			# the profile is locked before its membership is written, as a ledger entry is: a merge (which locks
			# both profiles) and this never pass each other, and a profile merged away meanwhile is refused; one
			# membership per guest and program, checked under that lock (C-04, ADR-077)
			from kamra.tex.crm.service import require_live_guest

			require_live_guest(self.guest)
			if frappe.db.exists("TEX Loyalty Member", {"guest": self.guest, "program": self.program}):
				frappe.throw(_("This guest already has a membership of this program."))

	def on_trash(self):
		block_delete(self)
