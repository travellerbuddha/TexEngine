# Copyright (c) 2026, TEX Engine contributors (derived from Kamra PMS, HeyKoala and contributors)
# For license information, please see license.txt

import frappe
from frappe.model.document import Document

from kamra.tex.security.capabilities import CAPABILITIES


class TEXPermissionProfile(Document):
	def validate(self):
		seen = set()
		for row in self.capabilities:
			if row.capability not in CAPABILITIES:
				frappe.throw(f"Unknown capability {row.capability}")
			if row.capability in seen:
				frappe.throw(f"Capability {row.capability} listed twice")
			seen.add(row.capability)
		seen = set()
		for row in self.get("sales_channels") or []:
			if row.sales_channel in seen:
				frappe.throw(f"Sales channel {row.sales_channel} listed twice")
			seen.add(row.sales_channel)

	def on_update(self):
		from kamra.tex.security.audit import audit

		audit("profile.update", reference_doctype=self.doctype, reference_name=self.name,
		      new={"capabilities": sorted(r.capability for r in self.capabilities),
		           "sales_channels": sorted(r.sales_channel for r in self.get("sales_channels") or [])})
