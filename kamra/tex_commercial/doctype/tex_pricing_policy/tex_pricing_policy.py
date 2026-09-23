# Copyright (c) 2026, TEX Engine contributors (derived from Kamra PMS, HeyKoala and contributors)
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document

from kamra.tex.commercial.revisions import block_delete, guard_revisioned, live_or_scheduled_roots
from kamra.tex.pricing import ages, inherit, validate
from kamra.tex.pricing.model import PricingError


class TEXPricingPolicy(Document):
	"""Default age bands and occupancy rules that contracts inherit (G-30, ADR-042).

	Every live policy that applies to a contract (global, hotel, market, hotel + market)
	cascades into it when the contract is published; a contract rule beats every policy
	rule. One live policy per scope (hotel, market): a change is a new revision of it.
	Because a policy reaches every contract of its scope, it is checked on its own: rows
	no contract could publish are refused on save, rules that tie when it goes live."""

	def validate(self):
		guard_revisioned(self)
		before = self.get_doc_before_save()
		copied = self.is_new() and self.flags.tex_revision_transition   # ``revise``: a copy, fixed as a draft
		if (not before or before.tex_status == "Draft") and not copied:
			# a draft, or a draft being activated (live revisions are immutable)
			self._check_bands()
			self._check_rules()
		if self.tex_status == "Active" and self.flags.tex_revision_transition and \
				(not before or before.tex_status == "Draft"):
			self._check_rule_set()
			self._check_one_live_per_scope()

	def on_trash(self):
		block_delete(self, lambda d: d.tex_status != "Draft")

	def _check_bands(self):
		from kamra.tex.commercial.contracts import age_bands_of

		codes = set()
		for b in self.age_bands:
			b.band_code = (b.band_code or "").strip().upper()
			if not b.band_code:
				frappe.throw(_("Every age band needs a code."))
			if b.band_code in codes:
				frappe.throw(_("Age band {0} appears twice.").format(b.band_code))
			codes.add(b.band_code)
		try:
			ages.validate_bands(age_bands_of(self.age_bands))
		except PricingError as e:
			frappe.throw(_("Age bands: {0}.").format(e))

	def _check_rules(self):
		from kamra.tex.commercial.contracts import parse_combination

		for r in self.occupancy_rules:
			# rules cascade by band code: a hotel policy may name a band its market policy defines
			r.age_band = (r.age_band or "").strip().upper() or None
			if (r.period_code or "").strip():
				frappe.throw(_("Row {0}: a pricing-policy rule cannot name a stay period; periods belong to "
				               "contracts.").format(r.idx))
			if r.room_type:
				if not self.property:
					frappe.throw(_("Row {0}: room type {1} belongs to one hotel; choose that hotel for this "
					               "policy, or leave the room empty.").format(r.idx, r.room_type))
				if frappe.db.get_value("Room Type", r.room_type, "property") != self.property:
					frappe.throw(_("Row {0}: room type {1} belongs to another hotel.").format(r.idx, r.room_type))
			adults, children = parse_combination(r.combination)
			# every contract in scope would refuse these rows (OCC_ADULT_BAND, OCC_COMBINATION_QUALIFIER)
			if r.target == "ADULT" and r.age_band:
				frappe.throw(_("Row {0}: an adult rule cannot name an age band.").format(r.idx))
			if r.target == "COMBINATION" and adults is None and children is None:
				frappe.throw(_("Row {0}: a combination rule needs a combination, e.g. 2+1 or 1+*.").format(r.idx))

	def _check_rule_set(self):
		"""On activation: twin rules, and rules that tie in some party (``validate.policy_issues``)."""
		from dataclasses import replace

		from kamra.tex.commercial.contracts import age_bands_of, occupancy_rules_of

		weight = inherit.weight_of(self.property, self.market)
		rules = tuple(replace(rule, rule_id=f"#{row.idx}") for row, rule in zip(
			self.occupancy_rules, occupancy_rules_of(self.occupancy_rules, base_level=inherit.level_for(weight),
			                                         source="policy", scope_weight=weight), strict=True))
		errors = [i.message for i in validate.policy_issues(age_bands_of(self.age_bands), rules)
		          if i.level == "ERROR"]
		if errors:
			frappe.throw(_("The occupancy rules of this policy conflict (# is the row): {0}.").format("; ".join(errors)),
			             title=_("Occupancy rules conflict"))

	def _check_one_live_per_scope(self):
		# a locking read, so it sees what another activation committed meanwhile. It cannot deadlock
		# with one: ``revisions.activate`` serialises pricing-policy activations before this record's
		# own row is locked (the second waits, then this read sees the first's policy)
		other = live_or_scheduled_roots("TEX Pricing Policy",
		                                {"property": self.property or None, "market": self.market or None},
		                                exclude_root=self.revision_of or self.name, for_update=True)
		if other:
			if self.property and self.market:
				scope = _("{0} in market {1}").format(self.property, self.market)
			elif self.property:
				scope = self.property
			elif self.market:
				scope = _("Market {0}").format(self.market)
			else:
				scope = _("The global scope (every hotel and market)")
			frappe.throw(_("{0} already has a live pricing policy ({1}); revise it instead.").format(scope, other[0]),
			             title=_("One pricing policy per scope"))
