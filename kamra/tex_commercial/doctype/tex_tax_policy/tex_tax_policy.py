# Copyright (c) 2026, TEX Engine contributors (derived from Kamra PMS, HeyKoala and contributors)
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import get_datetime, now_datetime

from kamra.tex.commercial.revisions import block_delete, guard_revisioned, live_or_scheduled_roots
from kamra.tex.money import D

# what a tax rule may apply to: the stay, every extra, or extras of one tax category
EXTRA_TAX_CATEGORIES = ("SERVICE", "FOOD", "TRANSFER", "ACCOMMODATION")
APPLIES_TO = frozenset({"ACCOMMODATION", "EXTRA:*", *(f"EXTRA:{c}" for c in EXTRA_TAX_CATEGORIES)})


class TEXTaxPolicy(Document):
	"""A hotel's tax rules, effective-dated like the other selling policies (G-20)."""

	def validate(self):
		guard_revisioned(self)
		if not self.currency and self.property:
			self.currency = frappe.db.get_value("Property", self.property, "currency")
		codes = set()
		for r in self.rules:
			r.code = (r.code or "").strip().upper()
			if not r.code:
				frappe.throw(_("Every tax rule needs a code."))
			if r.code in codes:
				frappe.throw(_("Tax code {0} appears twice.").format(r.code))
			codes.add(r.code)
			kind = r.kind or "PERCENT"
			if kind == "PERCENT" and not (0 <= D(r.rate or 0) <= 100):
				frappe.throw(_("Tax {0}: a rate must be between 0 and 100 %.").format(r.code))
			if kind != "PERCENT":
				if D(r.amount or 0) < 0:
					frappe.throw(_("Tax {0}: a fixed amount cannot be negative.").format(r.code))
				if r.compound:
					frappe.throw(_("Tax {0}: only a percentage can be compound.").format(r.code))
				if not self.currency:
					frappe.throw(_("Tax {0}: choose the currency of the fixed amounts.").format(r.code))
			tokens = [t.strip().upper() for t in (r.applies_to or "ACCOMMODATION").split(",") if t.strip()]
			unknown = [t for t in tokens if t not in APPLIES_TO]
			if unknown or not tokens:
				# a typo would silently charge no tax at all
				frappe.throw(_("Tax {0}: unknown 'applies to' {1}; use {2}.").format(
					r.code, ", ".join(unknown) or "—", ", ".join(sorted(APPLIES_TO))))
			if kind != "PERCENT" and "ACCOMMODATION" not in tokens:
				frappe.throw(_("Tax {0}: a fixed levy is charged on the stay (ACCOMMODATION).").format(r.code))
			r.applies_to = ",".join(dict.fromkeys(tokens))
		before = self.get_doc_before_save()
		if self.tex_status == "Active" and self.flags.tex_revision_transition and \
				(not before or before.tex_status == "Draft"):
			# two drafts activated at the same instant run one after the other
			frappe.db.sql("SELECT name FROM `tabProperty` WHERE name=%s FOR UPDATE", self.property)
			other = live_or_scheduled_roots("TEX Tax Policy", {"property": self.property},
			                                exclude_root=self.revision_of or self.name)
			if other:
				# one tax policy per hotel: a change is a new revision of it, never a second policy
				frappe.throw(_("{0} already has a live tax policy ({1}); revise it instead.").format(
					self.property, other[0]))
		if self.tex_status == "Archived" and before and before.tex_status in ("Active", "Superseded") \
				and _live_now(before):
			# a hotel's taxes are never switched off by accident (pricing would stop): a change
			# is a revision, and a revision without rules charges no tax
			frappe.throw(_("A hotel's live tax policy cannot be archived; revise it instead."))

	def on_trash(self):
		block_delete(self, lambda d: d.tex_status != "Draft")


def _live_now(doc) -> bool:
	now = now_datetime()
	return bool(doc.active_from) and get_datetime(doc.active_from) <= now and (
		not doc.active_to or get_datetime(doc.active_to) > now)
