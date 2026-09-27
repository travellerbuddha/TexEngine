# Copyright (c) 2026, TEX Engine contributors (derived from Kamra PMS, HeyKoala and contributors)
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document

from kamra.tex.commercial.revisions import block_delete, guard_revisioned
from kamra.tex.money import D

# what a discount on the total or the extras can be (``promotions.BASKET_VALUES``)
BASKET_VALUE_TYPES = ("PERCENT", "FIXED_STAY")


class TEXPromotion(Document):
	def validate(self):
		guard_revisioned(self)
		if self._new_terms():
			self._check_usable()
		if self.trigger == "Code":
			self.code = (self.code or "").strip().upper()
			if not self.code:
				frappe.throw("A code promotion needs a code.")
		else:
			self.code = None
		value = D(self.value or 0)
		if self.value_type == "PERCENT" and not (0 < value <= 100):
			frappe.throw("A percentage must be between 0 and 100.")
		# a promotion only ever lowers the price (G-18)
		if self.value_type == "MULTIPLIER" and not (0 < value <= 1):
			frappe.throw("A multiplier must be above 0 and at most 1 (0.9 = 10 % off).")
		if self.value_type in ("FIXED_STAY", "FIXED_NIGHT") and value <= 0:
			frappe.throw("A fixed discount must be a positive amount.")
		if self.value_type == "FREE_NIGHTS" and not (
				int(self.free_nights_stay or 0) > int(self.free_nights_pay or 0) >= 0 and self.free_nights_stay):
			frappe.throw("Stay X pay Y needs X greater than Y.")
		if self.value_type in ("FIXED_STAY", "FIXED_NIGHT") and not self.currency:
			frappe.throw("A fixed discount needs a currency.")
		if self.code and self.tex_status in ("Draft", "Active"):
			clash = frappe.db.sql("""SELECT name FROM `tabTEX Promotion` WHERE code=%s AND name!=%s
			   AND tex_status IN ('Draft','Active') AND IFNULL(property,'')=%s
			   AND IFNULL(revision_of,name) != %s""",
			                      (self.code, self.name or "", self.property or "", self.revision_of or self.name or ""))
			if clash:
				frappe.throw(f"Code {self.code} is already used by promotion {clash[0][0]}.")

	def _new_terms(self) -> bool:
		"""A draft being saved or activated, not ``revise``'s copy of a live revision (it is fixed as a
		draft): the checks a record already live was saved without, so it stays archivable (ADR-068)."""
		before = self.get_doc_before_save()
		copied = self.is_new() and self.flags.tex_revision_transition
		return self.tex_status in ("Draft", "Active") and (not before or before.tex_status == "Draft") and not copied

	def _check_usable(self):
		"""O-1: what no room could use as saved (the engine refuses it on every quote)."""
		scope = self.applies_to or "ACCOMMODATION"
		if scope == "ACCOMMODATION":
			return
		if self.stage == "COST":
			frappe.throw(_("A cost-stage offer lowers the contract cost of the accommodation: it applies to the "
			               "accommodation only."))
		if self.value_type not in BASKET_VALUE_TYPES:
			frappe.throw(_("A discount on {0} is a percentage or a fixed amount for the stay.").format(
				_("the whole booking") if scope == "TOTAL" else _("the extras")))

	def on_trash(self):
		block_delete(self, lambda d: d.tex_status != "Draft")
