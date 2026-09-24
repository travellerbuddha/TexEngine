# Copyright (c) 2026, TEX Engine contributors (derived from Kamra PMS, HeyKoala and contributors)
# For license information, please see license.txt

from frappe.model.document import Document


class TEXCommunication(Document):
	def validate(self):
		if self.is_new() and self.guest:
			# a link to a profile is written under a lock on it: a merge that deletes the profile and this
			# record never pass each other (third review of ADR-056); shared, nothing here writes the profile
			from kamra.tex.crm.service import require_live_guest

			require_live_guest(self.guest, share=True)
