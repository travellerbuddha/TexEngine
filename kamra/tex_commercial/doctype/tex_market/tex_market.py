# Copyright (c) 2026, TEX Engine contributors (derived from Kamra PMS, HeyKoala and contributors)
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document


class TEXMarket(Document):
	def validate(self):
		self.market_code = (self.market_code or "").strip().upper()
		codes = [c.strip().upper() for c in (self.countries or "").replace("\n", ",").split(",") if c.strip()]
		bad = [c for c in codes if len(c) != 2 or not c.isalpha()]
		if bad:
			frappe.throw(f"Country codes must be ISO alpha-2: {', '.join(bad)}")
		self.countries = ", ".join(sorted(set(codes)))
		if self.is_global and codes:
			frappe.throw("The global market does not list countries.")
		# a residents-only market sells on the web only to guests of its countries (O-8, ADR-070): it names them
		if self.residency_required and (self.is_global or not codes):
			frappe.throw(_("A residents-only market lists its countries; the global market cannot be one."))
