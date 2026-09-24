# Copyright (c) 2026, TEX Engine contributors (derived from Kamra PMS, HeyKoala and contributors)
# For license information, please see license.txt

import hashlib

import frappe
from frappe.model.document import Document
from frappe.utils import getdate

from kamra.tex.availability import restrictions as rs

SCOPE = ("property", "room_type", "contract", "market", "rate_plan", "sales_channel", "restriction_date")
VALUES = ("stop_sell", "stop_sell_mode", "min_los", "max_los", "cta", "ctd", "release_days", "min_advance",
          "max_advance", "book_from", "book_to")
CHANNEL_SCOPES = tuple(rs.CHANNEL_SCOPES)


# fields a site holds only once its schema is migrated to G-48: a value in one of them is refused
# while the table has no column for it, never dropped on the way to the database
G48_FIELDS = ("channel_scope", "book_from", "book_to")


def scope_key(values) -> str:
	"""One cell per scope and date, from the values themselves (a dict or a document; never
	through the DocType meta, so the key a lookup computes is the key a save stores). A channel
	scope (G-48) is appended only when set, so every cell stored before it keeps its key."""
	get = values.get
	day = get("restriction_date")
	raw = "|".join((str(getdate(day)) if day else "") if k == "restriction_date" else str(get(k) or "")
	               for k in SCOPE)
	if get("channel_scope"):
		raw += f"|scope:{get('channel_scope')}"
	return hashlib.sha1(raw.encode()).hexdigest()


def missing_columns(doc) -> list[str]:
	"""The G-48 fields ``doc`` sets that this site's table cannot hold (schema not migrated)."""
	return [f for f in G48_FIELDS if doc.get(f) and not doc.meta.has_field(f)]


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
		missing = missing_columns(self)
		if missing:
			# a value the table cannot hold would be dropped silently (the cell stored without its channel
			# scope, under another cell's key): refused, the site must be migrated first (G-48)
			frappe.throw("This site's restriction table has no {0} yet: run bench migrate before setting {1}.".format(
				", ".join(missing), " or ".join(missing)))
		self.scope_key = scope_key(self)
