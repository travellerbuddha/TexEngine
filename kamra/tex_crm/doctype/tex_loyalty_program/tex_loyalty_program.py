# Copyright (c) 2026, TEX Engine contributors (derived from Kamra PMS, HeyKoala and contributors)
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import getdate

from kamra.tex.money import D


class TEXLoyaltyProgram(Document):
	"""A hotel's or a hotel group's loyalty program (R-39, G-24). Every rule is checked here,
	whoever saves it (the TEX loyalty screen, Desk or a script)."""

	def validate(self):
		self.program_name = (self.program_name or "").strip()
		if bool(self.property) == bool(self.hotel_group):
			frappe.throw(_("A program belongs to one hotel or to one hotel group."))
		self._scope_is_fixed()
		scope = {"property": self.property} if self.property else {"hotel_group": self.hotel_group,
		                                                            "property": ("is", "not set")}
		if frappe.db.exists("TEX Loyalty Program", {**scope, "program_name": self.program_name,
		                                           "name": ("!=", self.name or "")}):
			frappe.throw(_("A program called {0} already exists here.").format(self.program_name))
		if self.enabled and frappe.db.exists("TEX Loyalty Program", {**scope, "enabled": 1,
		                                                            "name": ("!=", self.name or "")}):
			frappe.throw(_("Only one program can be enabled for a hotel or hotel group."))
		self._numbers()
		self._rules()

	def _scope_is_fixed(self):
		before = self.get_doc_before_save()
		if not before or (before.property, before.hotel_group) == (self.property, self.hotel_group):
			return
		if frappe.db.exists("TEX Loyalty Ledger", {"program": self.name}):
			# its ledger would move to another tenant's view
			frappe.throw(_("Guests have points in this program: it cannot move to another hotel or group."))
		if frappe.db.exists("TEX Loyalty Member", {"program": self.name}):
			# its members would be members, with member prices, at another hotel (C-04)
			frappe.throw(_("Guests are members of this program: it cannot move to another hotel or group."))

	def _numbers(self):
		if D(str(self.point_value or 0)) < 0:
			frappe.throw(_("The value of a point cannot be negative."))
		for f, label in (("min_redeem_points", _("Min points to redeem")), ("pending_days", _("Pending days")),
		                 ("expiry_months", _("Expiry (months)"))):
			if int(self.get(f) or 0) < 0:
				frappe.throw(_("{0} cannot be negative.").format(label))
		if not 0 <= D(str(self.max_redeem_percent or 0)) <= 100:
			frappe.throw(_("The share of a stay payable with points is between 0 and 100 %."))
		money = D(str(self.point_value or 0)) > 0 or any(r.basis == "MONEY" for r in self.earn_rules or [])
		if money and not self.currency:
			frappe.throw(_("Choose the program currency: points are earned on or worth money."))

	def _rules(self):
		hotels = set(self._hotels())
		for r in self.earn_rules or []:
			if D(str(r.rate or 0)) <= 0:
				frappe.throw(_("Row {0}: points per unit must be above zero.").format(r.idx))
			if r.date_from and r.date_to and getdate(r.date_from) > getdate(r.date_to):
				frappe.throw(_("Row {0}: the stay window ends before it starts.").format(r.idx))
			if r.basis == "ROOM":
				if not r.room_type or frappe.db.get_value("Room Type", r.room_type, "property") not in hotels:
					frappe.throw(_("Row {0}: choose a room type of this program's hotels.").format(r.idx))
			elif r.room_type:
				r.room_type = None
			if r.basis == "EXTRA":
				if not r.extra or frappe.db.get_value("TEX Extra", r.extra, "property") not in hotels:
					frappe.throw(_("Row {0}: choose an extra of this program's hotels.").format(r.idx))
			elif r.extra:
				r.extra = None
		names, floors = set(), set()
		for t in self.tiers or []:
			name = (t.tier_name or "").strip().lower()
			if name in names:
				frappe.throw(_("Tier {0} is listed twice.").format(t.tier_name))
			names.add(name)
			if int(t.min_points or 0) < 0 or int(t.min_points or 0) in floors:
				frappe.throw(_("Tier {0}: each tier starts at its own, non-negative number of points.").format(
					t.tier_name))
			floors.add(int(t.min_points or 0))
			if D(str(t.earn_multiplier if t.earn_multiplier is not None else 1)) <= 0:
				frappe.throw(_("Tier {0}: the earn multiplier must be above zero.").format(t.tier_name))
		for b in self.blackouts or []:
			if getdate(b.date_from) > getdate(b.date_to):
				frappe.throw(_("A blackout ends before it starts ({0}).").format(b.date_from))
			b.applies_to = b.applies_to or "Redemption"

	def _hotels(self) -> list[str]:
		if self.property:
			return [self.property]
		return frappe.get_all("Property", filters={"tex_hotel_group": self.hotel_group}, pluck="name")

	def on_trash(self):
		if frappe.db.exists("TEX Loyalty Ledger", {"program": self.name}):
			frappe.throw(_("Guests have points in this program: disable it instead."))
