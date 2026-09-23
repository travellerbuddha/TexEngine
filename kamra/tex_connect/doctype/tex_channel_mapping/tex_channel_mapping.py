# Copyright (c) 2026, TEX Engine contributors (derived from Kamra PMS, HeyKoala and contributors)
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document


class TEXChannelMapping(Document):
	"""One channel room/rate code ↔ a TEX room type sold with a board, market, channel and
	currency (G-69). The hotel is the connection's; a code pair is mapped once."""

	def validate(self):
		conn = frappe.db.get_value("TEX Integration Connection", self.connection, ["property", "category"], as_dict=True)
		if not conn or conn.category != "Channel Manager":
			frappe.throw(_("Choose a channel connection."))
		self.property = conn.property
		if frappe.db.get_value("Room Type", self.room_type, "property") != self.property:
			frappe.throw(_("The room type belongs to another hotel."))
		if self.rate_plan and frappe.db.get_value("Rate Plan", self.rate_plan, "property") != self.property:
			frappe.throw(_("The rate plan belongs to another hotel."))
		if self.contract and frappe.db.get_value("TEX Contract", self.contract, "property") != self.property:
			frappe.throw(_("The contract belongs to another hotel."))
		self.external_room_code = (self.external_room_code or "").strip()
		self.external_rate_code = (self.external_rate_code or "").strip()
		if not self.external_room_code or not self.external_rate_code:
			frappe.throw(_("The channel's room and rate codes are required."))
		if frappe.db.exists("TEX Channel Mapping", {"connection": self.connection,
		                                            "external_room_code": self.external_room_code,
		                                            "external_rate_code": self.external_rate_code,
		                                            "name": ("!=", self.name or "")}):
			frappe.throw(_("{0} / {1} is already mapped on this connection.").format(self.external_room_code,
			                                                                          self.external_rate_code))
		adults = [x.strip() for x in str(self.occupancies or "2").split(",") if x.strip()]
		if not adults or any(not a.isdigit() or not 0 < int(a) < 10 for a in adults):
			frappe.throw(_("Adults priced: whole numbers from 1 to 9, separated by commas."))
		self.occupancies = ",".join(str(int(a)) for a in sorted({int(a) for a in adults}))
		if not 1 <= int(self.horizon_days or 0) <= 365:
			frappe.throw(_("Days ahead: 1 to 365."))
