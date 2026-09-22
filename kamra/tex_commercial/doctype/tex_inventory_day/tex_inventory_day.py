# Copyright (c) 2026, TEX Engine contributors (derived from Kamra PMS, HeyKoala and contributors)
# For license information, please see license.txt

import hashlib

import frappe
from frappe.model.document import Document


def inventory_day_name(room_type: str, day) -> str:
	return "INV-" + hashlib.sha1(f"{room_type}|{day}".encode()).hexdigest()[:20]


class TEXInventoryDay(Document):
	def autoname(self):
		self.name = inventory_day_name(self.room_type, self.inventory_date)

	def validate(self):
		if int(self.oversell_limit or 0) < 0:
			frappe.throw("Oversell limit cannot be negative.")
