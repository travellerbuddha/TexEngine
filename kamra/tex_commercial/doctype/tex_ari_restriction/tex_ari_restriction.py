# Copyright (c) 2026, TEX Engine contributors (derived from Kamra PMS, HeyKoala and contributors)
# For license information, please see license.txt

import hashlib

import frappe
from frappe.model.document import Document
from frappe.utils import getdate

SCOPE = ("property", "room_type", "contract", "market", "rate_plan", "sales_channel", "restriction_date")
VALUES = ("stop_sell", "stop_sell_mode", "min_los", "max_los", "cta", "ctd", "release_days", "min_advance",
          "max_advance", "book_from", "book_to")
CHANNEL_SCOPES = ("Booking Engine", "Call Center", "Booking Engine + Call Center")


def scope_key(values: dict) -> str:
	"""One cell per scope and date. A channel scope (G-48) is appended only when set, so every
	cell stored before it keeps its key."""
	raw = "|".join(str(values.get(k) or "") for k in SCOPE)
	if values.get("channel_scope"):
		raw += f"|scope:{values['channel_scope']}"
	return hashlib.sha1(raw.encode()).hexdigest()


class TEXARIRestriction(Document):
	def validate(self):
		for f in ("min_los", "max_los", "release_days", "min_advance", "max_advance"):
			if int(self.get(f) or 0) < 0:
				frappe.throw(f"{self.meta.get_label(f)} cannot be negative.")
		if self.min_los and self.max_los and int(self.min_los) > int(self.max_los):
			frappe.throw("Min LOS is greater than max LOS.")
		if self.get("channel_scope"):
			if self.channel_scope not in CHANNEL_SCOPES:
				frappe.throw("Choose the Booking Engine, the Call Center or both.")
			if self.sales_channel:
				frappe.throw("A restriction is scoped to one sales channel or to a channel scope, not both.")
		if self.get("book_from") and self.get("book_to") and getdate(self.book_from) > getdate(self.book_to):
			frappe.throw("The booking window ends before it starts.")
		self.scope_key = scope_key(self.as_dict())
