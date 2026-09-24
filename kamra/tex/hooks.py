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


# At a TEX hotel no stay changes these outside the TEX services, whoever priced it (G-92): its
# stay, party and price, the commercial record, and the hotel itself (a stay moved into a TEX
# hotel would be a sale outside TEX; one moved out of it would be re-priced by the legacy engine).
TEX_HOTEL_FIELDS = (*PRICING_INPUTS, *COMMERCIAL_RECORD, "property")


def guard_commercial_change(doc, *, final: bool = False) -> None:
	"""A stay changes commercially only through the TEX services (modification, cancellation,
	confirmation, add-ons, channel updates: ``flags.tex_modification`` on the document, for one
	save), whatever the caller — the Desk form, REST (``PUT``, ``frappe.client.set_value``), legacy
	PMS actions (``amend_stay``, ``move_reservation``) — and whatever the status change in the same
	save:

	- a price-locked stay (ADR-010, G-01): its pricing inputs and commercial record;
	- any stay that is at a hotel live in TEX, or was until this save (ADR-052, G-92; ``tex_live``),
	  also one the legacy engine sold before the hotel joined TEX: its dates, room type, party,
	  board, rate plan, price, commercial record and hotel. TEX re-prices only a stay it sold and
	  the legacy engine never prices a live TEX hotel, so such a stay keeps its terms; a new stay
	  (or, for a guest in house, the extra nights) is booked in TEX. While a hotel is onboarding
	  its legacy stays still change as before.

	``Reservation.validate`` calls this first, so nothing is locked or priced for a save that is
	refused; the ``validate`` doc event checks the values the save will write again (``final``)
	and uses up the service's flag, so it never covers a later save of the same document."""
	service = doc.flags.pop("tex_modification", None) if final else doc.flags.get("tex_modification")
	if doc.is_new() or service:
		return
	before = doc.get_doc_before_save()
	if not before:
		return
	changed = locked_changes(doc)
	meta = doc.meta
	at_hotel = [f for f in TEX_HOTEL_FIELDS if meta.has_field(f) and _differs(meta, before, doc, f)]
	if not changed and not at_hotel:
		return
	from kamra.tex.legacy import is_tex_hotel, tex_live

	hotels = list(dict.fromkeys((before.property, doc.property)))
	live = next((p for p in hotels if tex_live(p)), None)
	if live:
		changed = list(dict.fromkeys((*changed, *at_hotel)))
	if not changed:
		return
	tex_hotel = live or next((p for p in hotels if is_tex_hotel(p)), None)
	if tex_hotel and not before.get("tex_pricing_snapshot"):
		if before.status == "Checked In":
			frappe.throw(
				_("Reservation {0} is in house and was not priced by TEX, and {1} is sold through TEX: its {2} cannot "
				  "be changed here. To extend the stay, book the extra nights as a new TEX reservation (Reservations → "
				  "CRS or Call Center).").format(doc.name, tex_hotel, ", ".join(changed)),
				title=_("Book it in TEX"))
		frappe.throw(
			_("Reservation {0} was not priced by TEX, and {1} is sold through TEX: its {2} cannot be changed here. "
			  "Keep the stay as it is, or cancel it and book the new stay in TEX (Reservations → CRS or Call "
			  "Center).").format(doc.name, tex_hotel, ", ".join(changed)),
			title=_("Book it in TEX"))
	frappe.throw(
		_("Reservation {0} is price-locked. Use Modify reservation to change {1}; the price difference is "
		  "proposed and recorded as a revision.").format(doc.name, ", ".join(changed)),
		title=_("Price locked"))


def reservation_validate(doc, method=None):
	"""``validate`` doc event: the commercial guard on the values the save will write
	(ADR-010, ADR-052). ``Reservation.validate`` already ran it before its own checks."""
	guard_commercial_change(doc, final=True)


def reservation_before_insert(doc, method=None):
	"""A TEX hotel's reservation written outside TEX locks its nights before it takes its name,
	in a TEX booking's lock order (ADR-048)."""
	from kamra.tex.legacy import is_tex_hotel

	if is_tex_hotel(doc.property):
		from kamra.tex.availability.repository import lock_before_naming

		lock_before_naming(doc)


def reservation_on_update(doc, method=None):
	if doc.guest:
		from kamra.tex.crm import service as crm

		crm.refresh_guest_stats(doc.guest)
	_channels_see(doc)
	if not doc.get("tex_booking"):
		return
	from kamra.tex.connect import outbox
	from kamra.tex.crm import loyalty

	outbox.on_reservation_change(doc)
	loyalty.on_reservation_change(doc)
	_release_extras(doc)


def _channels_see(doc) -> None:
	"""Any stay at a TEX hotel changes what its channels may sell (G-69): queue an ARI sync
	for the old and the new nights and room types."""
	from kamra.tex.legacy import is_tex_hotel

	if not is_tex_hotel(doc.property):
		return
	# on insert, Frappe (v16) still hands on_update a "before" copy: a new stay is always news
	before = None if doc.flags.get("in_insert") else doc.get_doc_before_save()
	watched = ("status", "room_type", "check_in_date", "check_out_date", "property")
	if before and all(str(before.get(f) or "") == str(doc.get(f) or "") for f in watched):
		return
	from kamra.tex.distribution import repository as dist

	for d in ([before] if before else []) + [doc]:
		dist.mark_dirty(d.property, [d.room_type], d.check_in_date, d.check_out_date, reason="reservation")


def ari_source_changed(doc, method=None):
	"""Inventory, a restriction, an allotment or a mapping changed (G-69)."""
	from kamra.tex.distribution import repository as dist

	prop = doc.get("property") or frappe.db.get_value("TEX Integration Connection", doc.get("connection"), "property")
	if not prop:
		return
	a = doc.get("inventory_date") or doc.get("restriction_date") or doc.get("date_from")
	b = doc.get("inventory_date") or doc.get("restriction_date") or doc.get("date_to")
	dist.mark_dirty(prop, [doc.get("room_type")] if doc.get("room_type") else None, a, b,
	                reason=doc.doctype.removeprefix("TEX ").lower())


def mapping_changed(doc, method=None):
	"""A channel mapping was saved: its own horizon is compared again — a disabled one sends
	its close-out, so the channel stops selling what TEX no longer updates (G-69)."""
	from kamra.tex.distribution import repository as dist

	dist.queue_mapping(doc)


def contract_version_changed(doc, method=None):
	"""A version was published, withdrawn or went live: prices may have changed (G-69)."""
	before = None if doc.flags.get("in_insert") else doc.get_doc_before_save()
	if before and before.get("status") == doc.get("status"):
		return
	prop = frappe.db.get_value("TEX Contract", doc.contract, "property")
	if prop:
		from kamra.tex.distribution import repository as dist

		dist.mark_dirty(prop, reason="contract")


def _release_extras(doc) -> None:
	"""A cancelled or no-show stay gives its limited extras' units back (G-19), whichever path
	cancelled it: TEX cancel, the guest's manage page or the legacy hold expiry."""
	if doc.status not in ("Cancelled", "No Show"):
		return
	before = doc.get_doc_before_save()
	if before and before.status in ("Cancelled", "No Show"):
		return
	from kamra.tex.availability import extras_repository as xinv

	xinv.release_reservation(doc.name, f"reservation {doc.status.lower()}")


def property_validate(doc, method=None):
	from kamra.tex.legacy import guard_live_switch

	guard_live_switch(doc)      # a hotel goes live in TEX only through TEX (ADR-052 review)
	if doc.get("tex_hotel_group"):
		doc.tex_enterprise = frappe.db.get_value("TEX Hotel Group", doc.tex_hotel_group, "enterprise")
	_guard_superseded_tax_rules(doc)


def room_type_validate(doc, method=None):
	"""Some localization packs take a room type's tax % (G-20): once the hotel's tax policy
	has begun, TEX prices ignore it, so a change is announced rather than silently diverging
	from the legacy folio."""
	if not doc.get("property") or not doc.meta.has_field("tax_percent"):
		return
	from kamra.tex.commercial.context import policy_started
	from kamra.tex.money import D

	before = doc.get_doc_before_save()
	changed = D(before.get("tax_percent") or 0) != D(doc.get("tax_percent") or 0) if before \
		else bool(doc.get("tax_percent"))
	if changed and policy_started(doc.property):
		frappe.msgprint(_("TEX prices at {0} use its tax policy (Rates → Taxes); this room type's tax % does not "
		                  "affect them.").format(doc.property), title=_("Taxes are effective-dated"), indicator="orange")


# what a localization pack computes taxes from (kamra/localization/*)
PACK_TAX_FIELDS = ("country", "gst_mode", "gst_rate_low", "gst_rate_high", "gst_slab_threshold")


def _guard_superseded_tax_rules(doc) -> None:
	"""Once a hotel has a TEX Tax Policy, its taxes change only through revisions of it
	(G-20): the old per-hotel table is no longer read, so an edit there would silently do
	nothing."""
	before = doc.get_doc_before_save()
	if not before:
		return
	# a TEX hotel still without a policy gets one from what it sells with now (this save's
	# old values), so an edit in this save becomes a revision, never rewritten history
	seed_tax_policy(doc.name)
	from kamra.tex.commercial.context import policy_started

	if not policy_started(doc.name):
		return          # a draft or scheduled policy: the hotel still sells with these settings
	if any(str(before.get(f) or "") != str(doc.get(f) or "") for f in PACK_TAX_FIELDS):
		frappe.msgprint(_("TEX prices at {0} use its tax policy (Rates → Taxes); this change does not "
		                  "affect them.").format(doc.name), title=_("Taxes are effective-dated"), indicator="orange")
	from kamra.tex.money import D

	strip = lambda rows: [(r.code, r.tax_name, r.kind, D(r.rate or 0), D(r.amount or 0), r.applies_to,  # noqa: E731
	                       int(r.compound or 0), int(r.sort_order or 0)) for r in rows or []]
	if (before.get("tex_tax_profile") != doc.get("tex_tax_profile")
			or strip(before.get("tex_tax_rules")) != strip(doc.get("tex_tax_rules"))):
		frappe.throw(_("{0}'s taxes are managed as a TEX tax policy; change them there (Rates → Taxes).")
		             .format(doc.name), title=_("Taxes are effective-dated"))


def property_on_update(doc, method=None):
	before = doc.get_doc_before_save()
	if before and before.get("tex_hotel_group") != doc.get("tex_hotel_group"):
		from kamra.tex.security import grants

		grants.resync_for_properties([doc.name])
	_seed_tax_policy(doc)


def _seed_tax_policy(doc) -> None:
	"""A TEX hotel's taxes are effective-dated from the start (G-20): the save that makes it a
	TEX hotel gives it a tax policy holding its current taxes."""
	seed_tax_policy(doc.name)


def seed_tax_policy(property: str) -> None:
	"""Called when a hotel may have just become a TEX hotel (its Property saved, its first
	TEX contract created)."""
	from kamra.tex.legacy import is_tex_hotel

	if frappe.flags.in_install or frappe.flags.in_migrate or not property or not is_tex_hotel(property):
		return
	from kamra.tex.commercial import tax_policies

	tax_policies.ensure(property)
