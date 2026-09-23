"""Frappe doc_event handlers for TEX (wired in kamra/hooks.py)."""

from __future__ import annotations

import frappe
from frappe import _

# Changing any of these on a price-locked reservation changes what was sold.
PRICING_INPUTS = ("check_in_date", "check_out_date", "room_type", "adults", "children", "meal_plan", "rate_plan",
                  "voucher", "tex_board", "tex_market", "tex_child_ages", "amount_before_tax", "tax_amount",
                  "amount_after_tax", "discount_amount", "tex_total_amount", "tex_contract_version")
# The accepted commercial record (ADR-010): what was sold, on which terms, at which FX rate,
# for which cost. The lock flags themselves belong here — a save must not unlock and edit at once.
COMMERCIAL_RECORD = ("tex_booking", "tex_room_index", "tex_contract", "tex_payload_hash", "tex_sales_channel",
                     "tex_pricing_source", "tex_price_locked", "tex_locked_at", "tex_sale_at", "tex_accepted_at",
                     "tex_quote", "tex_currency", "tex_fx_rate", "tex_extras_amount", "tex_cost_amount",
                     "tex_margin_amount", "tex_promotions", "tex_pricing_snapshot")
CLOSED = ("Cancelled", "No Show")
_NUMERIC = ("Currency", "Float", "Int", "Percent", "Check")


def is_price_locked(doc) -> bool:
	return bool(doc.get("tex_price_locked")) or doc.get("tex_pricing_source") == "TEX"


def _differs(meta, before, doc, field: str) -> bool:
	a, b = before.get(field), doc.get(field)
	df = meta.get_field(field)
	if df and df.fieldtype in _NUMERIC:
		from kamra.tex.money import D

		return D(a or 0) != D(b or 0)
	return str(a or "") != str(b or "")


def locked_changes(doc) -> list[str]:
	"""Commercial fields a save would change on a reservation that was price-locked BEFORE
	this save (the lock is judged on the stored values, never on the incoming ones)."""
	before = doc.get_doc_before_save()
	if not before or not is_price_locked(before):
		return []
	meta = doc.meta
	changed = [f for f in (*PRICING_INPUTS, *COMMERCIAL_RECORD)
	           if meta.has_field(f) and _differs(meta, before, doc, f)]
	if meta.has_field("cancellation_fee") and _differs(meta, before, doc, "cancellation_fee"):
		# A stay sold before TEX (legacy pricing) may take the legacy cancellation fee as it is
		# closed. TEX-sold stays are cancelled only by the TEX service, which applies the frozen
		# cancellation policy of the rate plan.
		closing = doc.status in CLOSED and before.status not in CLOSED
		if not (closing and before.get("tex_pricing_source") != "TEX"):
			changed.append("cancellation_fee")
	return changed


def reservation_validate(doc, method=None):
	"""ADR-010: a price-locked reservation only changes commercially through the TEX
	modification flow (proposal → revision → audit), never by editing fields — whatever the
	caller (Desk, REST, legacy PMS code) and whatever the status change in the same save."""
	if doc.is_new() or doc.flags.tex_modification or frappe.flags.tex_modification:
		return
	changed = locked_changes(doc)
	if changed:
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
