# Copyright (c) 2026, TEX Engine contributors (derived from Kamra PMS, HeyKoala and contributors)
# For license information, please see license.txt

import hashlib

import frappe
from frappe import _
from frappe.model.document import Document


def extra_day_name(property: str, extra_code: str, day) -> str:
	"""Deterministic, so the booking service can create-and-lock it in one statement (G-19)."""
	return "EXI-" + hashlib.sha1(f"{property}|{extra_code}|{day}".encode()).hexdigest()[:20]


class TEXExtraInventoryDay(Document):
	def autoname(self):
		self.name = extra_day_name(self.property, self.extra_code, self.service_date)

	def validate(self):
		self.extra_code = (self.extra_code or "").strip().upper()
		if int(self.capacity or 0) < 0:
			frappe.throw(_("Capacity cannot be negative."))
		# the sold counter belongs to the booking service: an edit here never changes it
		current = frappe.db.sql("SELECT sold FROM `tabTEX Extra Inventory Day` WHERE name=%s FOR UPDATE",
		                        self.name) if not self.is_new() else None
		self.sold = int(current[0][0] or 0) if current else 0
