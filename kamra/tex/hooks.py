"""Frappe doc_event handlers for TEX (wired in kamra/hooks.py)."""

from __future__ import annotations

import frappe
from frappe import _

# Changing any of these on a price-locked reservation changes what was sold.
PRICING_INPUTS = ("check_in_date", "check_out_date", "room_type", "adults", "children", "meal_plan", "rate_plan",
                  "voucher", "tex_board", "tex_market", "tex_child_ages", "amount_before_tax", "tax_amount",
                  "amount_after_tax", "discount_amount", "tex_total_amount", "tex_contract_version")


def is_price_locked(doc) -> bool:
	return bool(doc.get("tex_price_locked")) or doc.get("tex_pricing_source") == "TEX"


def reservation_validate(doc, method=None):
	"""ADR-010: a price-locked reservation only changes commercially through the TEX
	modification flow (proposal → revision → audit), never by editing fields."""
	if doc.is_new() or doc.flags.tex_modification or frappe.flags.tex_modification:
		return
	if not is_price_locked(doc):
		return
	before = doc.get_doc_before_save()
	if not before:
		return
	changed = [f for f in PRICING_INPUTS
	           if doc.meta.has_field(f) and str(before.get(f) or "") != str(doc.get(f) or "")]
	if changed and doc.status not in ("Cancelled", "No Show"):
		frappe.throw(
			_("Reservation {0} is price-locked. Use Modify reservation to change {1}; the price difference is "
			  "proposed and recorded as a revision.").format(doc.name, ", ".join(changed)),
			title=_("Price locked"))


def reservation_on_update(doc, method=None):
	if doc.guest:
		from kamra.tex.crm import service as crm

		crm.refresh_guest_stats(doc.guest)
	if not doc.get("tex_booking"):
		return
	from kamra.tex.connect import outbox
	from kamra.tex.crm import loyalty

	outbox.on_reservation_change(doc)
	loyalty.on_reservation_change(doc)


def property_validate(doc, method=None):
	if doc.get("tex_hotel_group"):
		doc.tex_enterprise = frappe.db.get_value("TEX Hotel Group", doc.tex_hotel_group, "enterprise")


def property_on_update(doc, method=None):
	before = doc.get_doc_before_save()
	if before and before.get("tex_hotel_group") != doc.get("tex_hotel_group"):
		from kamra.tex.security import grants

		grants.resync_for_properties([doc.name])
