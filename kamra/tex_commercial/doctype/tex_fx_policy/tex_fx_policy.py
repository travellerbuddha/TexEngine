# Copyright (c) 2026, TEX Engine contributors (derived from Kamra PMS, HeyKoala and contributors)
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document

from kamra.tex.commercial.revisions import block_delete, guard_revisioned, live_or_scheduled_roots
from kamra.tex.money import D


class TEXFXPolicy(Document):
	def validate(self):
		guard_revisioned(self)
		if self.from_currency == self.to_currency:
			frappe.throw("An FX policy converts between two different currencies.")
		if self.mode == "MANUAL" and not D(self.manual_rate or 0) > 0:
			frappe.throw("A manual FX policy needs a positive rate.")
		before = self.get_doc_before_save()
		if self.tex_status == "Active" and self.flags.tex_revision_transition and \
				(not before or before.tex_status == "Draft"):
			# O-11: one live or scheduled policy per scope and pair; a change is a revision of it. Activations
			# run one at a time (``SERIAL_ACTIVATION``) and this is a locking read: two at once see each other.
			# A global policy (no hotel) does not clash with a hotel's own for the same pair.
			other = live_or_scheduled_roots(
				"TEX FX Policy", {"property": self.property or None, "from_currency": self.from_currency,
				                  "to_currency": self.to_currency},
				exclude_root=self.revision_of or self.name, for_update=True)
			if other:
				frappe.throw(_("{0} already has a live FX policy for {1}→{2} ({3}); revise it instead.").format(
					self.property or _("All hotels"), self.from_currency, self.to_currency, other[0]),
					title=_("FX policy already live"))

	def on_trash(self):
		block_delete(self, lambda d: d.tex_status != "Draft")
