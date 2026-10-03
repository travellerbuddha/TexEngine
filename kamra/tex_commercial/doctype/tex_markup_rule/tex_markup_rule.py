# Copyright (c) 2026, TEX Engine contributors (derived from Kamra PMS, HeyKoala and contributors)
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document

from kamra.tex.commercial.revisions import block_delete, guard_revisioned
from kamra.tex.money import D


def tie_candidates(prop: str | None, root: str, start, end=None) -> tuple[str, dict]:
	"""The locking read of the REPLACE markups of ``prop``'s hotel (none: of no hotel) that another record's
	window from ``start`` (to ``end``; none: open-ended) could tie with: live or scheduled within it (active_to
	NULL: open-ended). The hotel is matched as is, never through IFNULL, and the rows are read in no order
	(``same_scope_ties`` orders them by id), so the read goes through the (property, tex_status) index and locks
	that hotel's rows only, not every markup row (LO-42 b2)."""
	from kamra.tex.commercial.context import MARKUP_FIELDS

	cols = ", ".join(f"`{f}`" for f in MARKUP_FIELDS)
	hotel = "property = %(prop)s" if prop else "(property IS NULL OR property = '')"
	until = "AND (active_from IS NULL OR active_from < %(to)s)" if end else ""
	return (f"""SELECT {cols}, `active_from` FROM `tabTEX Markup Rule`
	           WHERE {hotel} AND tex_status IN ('Active','Superseded') AND IFNULL(combine,'REPLACE')='REPLACE'
	             AND IFNULL(revision_of,name)!=%(root)s
	             AND (active_to IS NULL OR active_to > %(from)s) {until}
	           FOR UPDATE""", {"prop": prop or "", "root": root, "from": start, "to": end})


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
		if self.flags.tex_revision_transition:
			if self.tex_status == "Active" and (not before or before.tex_status == "Draft"):
				self._check_ties(self.active_from, self.active_to)
			elif self._reopened(before):
				# only the window it gets back, from its old end to its new one, is new on sale (2K-6 review S1)
				self._check_ties(before.active_to, self.active_to)

	def _reopened(self, before) -> bool:
		"""Put back on sale for longer than it was (an archived schedule hands its window back, LO-42 b1):
		a tie with a markup activated meanwhile in that window is refused as an activation's is."""
		if not before or self.tex_status not in ("Active", "Superseded") or not before.active_to:
			return False
		return not self.active_to or frappe.utils.get_datetime(self.active_to) > frappe.utils.get_datetime(
			before.active_to)

	def _check_ties(self, start, end=None):
		"""G-53: a REPLACE markup that ties with a live or scheduled one of another record in its window from
		``start`` to ``end`` (the same scope and priority, stay dates that meet: ``markup.same_scope_ties``) is
		not activated; the engine would take the newer silently. Activations run one at a time
		(``SERIAL_ACTIVATION``) and this is a locking read, so two at once see each other."""
		from kamra.tex.commercial.context import markup_from_row
		from kamra.tex.pricing import markup

		if (self.combine or "REPLACE") != "REPLACE":
			return
		sql, args = tie_candidates(self.property, self.revision_of or self.name, start, end)
		others = frappe.db.sql(sql, args, as_dict=True)
		me = markup_from_row(self)
		starts = {r.name: r.active_from for r in others}
		now = frappe.utils.now_datetime()
		for a, b in markup.same_scope_ties([me, *(markup_from_row(r) for r in others)]):
			if a is me or b is me:
				other = b if a is me else a
				# a tie is not revised away at the same priority: change a priority or archive one (2D-1)
				scheduled = starts.get(other.rule_id) and frappe.utils.get_datetime(starts[other.rule_id]) > now
				if self.flags.tex_restored_by:
					frappe.throw(_("Archiving {0} would put markup {1} back on sale, and it has the same scope and "
					               "priority as live or scheduled markup {2}, and their stay dates meet: only one "
					               "would apply. Change the priority of one, or archive one of them first.").format(
						self.flags.tex_restored_by, self.name, other.rule_id), title=_("Markup tie"))
				msg = (_("Markup {0} has the same scope and priority as live or scheduled markup {1}, and their stay "
				         "dates meet: only one would apply. Change the priority of one, or archive one of them.")
				       if scheduled else
				       _("Markup {0} has the same scope and priority as live markup {1}, and their stay dates meet: "
				         "only one would apply. Change the priority of one, or archive one of them."))
				frappe.throw(msg.format(self.name, other.rule_id), title=_("Markup tie"))

	def on_trash(self):
		block_delete(self, lambda d: d.tex_status != "Draft")
