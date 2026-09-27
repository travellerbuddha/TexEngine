# Copyright (c) 2026, TEX Engine contributors (derived from Kamra PMS, HeyKoala and contributors)
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document

from kamra.tex.commercial.revisions import block_delete, guard_revisioned
from kamra.tex.money import D


class TEXMarkupRule(Document):
	def validate(self):
		guard_revisioned(self)
		if self.op == "ADD" and not self.currency:
			frappe.throw("A fixed markup needs a currency.")
		# a markup never sells for nothing (G-18)
		if self.op == "ADJUST_PERCENT" and D(self.value or 0) <= -100:
			frappe.throw("A markup cannot take off 100 % or more.")
		if self.op == "MULTIPLY" and D(self.value or 0) <= 0:
			frappe.throw("A markup multiplier must be above 0.")
		if self.stay_from and self.stay_to and self.stay_from > self.stay_to:
			frappe.throw("Stay window ends before it starts.")
		before = self.get_doc_before_save()
		if self.tex_status == "Active" and self.flags.tex_revision_transition and \
				(not before or before.tex_status == "Draft"):
			self._check_ties()

	def _check_ties(self):
		"""G-53: a REPLACE markup that ties with a live or scheduled one of another record (the same
		scope and priority, stay dates that meet: ``markup.same_scope_ties``) is not activated; the
		engine would take the newer silently. Activations run one at a time (``SERIAL_ACTIVATION``)
		and this is a locking read, so two at once see each other."""
		from kamra.tex.commercial.context import MARKUP_FIELDS, markup_from_row
		from kamra.tex.pricing import markup

		if (self.combine or "REPLACE") != "REPLACE":
			return
		cols = ", ".join(f"`{f}`" for f in MARKUP_FIELDS)
		others = frappe.db.sql(f"""SELECT {cols} FROM `tabTEX Markup Rule`
		                           WHERE tex_status IN ('Active','Superseded') AND IFNULL(combine,'REPLACE')='REPLACE'
		                             AND IFNULL(property,'')=%(prop)s AND IFNULL(revision_of,name)!=%(root)s
		                             AND (active_to IS NULL OR active_to > %(from)s)
		                           ORDER BY name FOR UPDATE""",
		                       {"prop": self.property or "", "root": self.revision_of or self.name,
		                        "from": self.active_from}, as_dict=True)
		me = markup_from_row(self)
		for a, b in markup.same_scope_ties([me, *(markup_from_row(r) for r in others)]):
			if a is me or b is me:
				other = b if a is me else a
				frappe.throw(_("Markup {0} has the same scope and priority as live markup {1}, and their stay dates "
				               "meet: only one would apply. Give one a higher priority, or revise {1} instead.")
				             .format(self.name, other.rule_id), title=_("Markup tie"))

	def on_trash(self):
		block_delete(self, lambda d: d.tex_status != "Draft")
