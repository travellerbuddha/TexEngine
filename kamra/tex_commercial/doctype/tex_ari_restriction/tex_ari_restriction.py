# Copyright (c) 2026, TEX Engine contributors (derived from Kamra PMS, HeyKoala and contributors)
# For license information, please see license.txt

import hashlib

import frappe
from frappe.model.document import Document

SCOPE = ("property", "room_type", "contract", "market", "rate_plan", "sales_channel", "restriction_date")
VALUES = ("stop_sell", "stop_sell_mode", "min_los", "max_los", "cta", "ctd", "release_days", "min_advance",
          "max_advance")


def scope_key(values: dict) -> str:
	raw = "|".join(str(values.get(k) or "") for k in SCOPE)
	return hashlib.sha1(raw.encode()).hexdigest()


class TEXARIRestriction(Document):
	def validate(self):
		for f in ("min_los", "max_los", "release_days", "min_advance", "max_advance"):
			if int(self.get(f) or 0) < 0:
				frappe.throw(f"{self.meta.get_label(f)} cannot be negative.")
		if self.min_los and self.max_los and int(self.min_los) > int(self.max_los):
			frappe.throw("Min LOS is greater than max LOS.")
		self.scope_key = scope_key(self.as_dict())
