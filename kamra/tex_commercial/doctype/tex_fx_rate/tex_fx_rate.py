# Copyright (c) 2026, TEX Engine contributors (derived from Kamra PMS, HeyKoala and contributors)
# For license information, please see license.txt

import frappe
from frappe.model.document import Document

from kamra.tex.commercial.revisions import block_delete, guard_immutable
from kamra.tex.money import D


class TEXFXRate(Document):
	def validate(self):
		self.base_currency = (self.base_currency or "").upper()
		self.quote_currency = (self.quote_currency or "").upper()
		if not D(self.rate or 0) > 0:
			frappe.throw("Rate must be positive.")
		if self.property and self.provider != "MANUAL":
			frappe.throw("Provider rates are for every hotel; only a manual rate names a hotel.")
		# a provider rate is recorded once; a MANUAL one may be entered again as a correction for its date
		# (the latest entry wins, the rows stay immutable: O-12)
		if self.is_new() and self.provider != "MANUAL" and frappe.db.exists("TEX FX Rate", {
				"provider": self.provider, "base_currency": self.base_currency, "quote_currency": self.quote_currency,
				"rate_type": self.rate_type, "rate_date": self.rate_date}):
			frappe.throw("This provider rate is already recorded; provider rates are immutable.")
		guard_immutable(self)

	def on_trash(self):
		block_delete(self)
