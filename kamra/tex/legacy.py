"""Boundaries between TEX and the legacy Kamra PMS paths (ADR-014, ADR-028, ADR-052).

A hotel inside the TEX tenancy hierarchy (enterprise / hotel group), or one with TEX
contracts, is sold only through TEX: contract pricing, TEX inventory locks and TEX
payments. The legacy selling paths (the ``/kamra/book`` engine, the legacy staff booking
dialog) price from ``Room Type.base_price`` and must never sell such a hotel; neither may
the generic Desk / REST / data-import insert of a Reservation (G-92).
"""

from __future__ import annotations

import frappe
from frappe import _
from frappe.utils import now_datetime


def is_tex_hotel(property: str | None) -> bool:
	if not property:
		return False
	row = frappe.db.get_value("Property", property, ["tex_enterprise", "tex_hotel_group"], as_dict=True)
	if not row:
		return False
	return bool(row.tex_enterprise or row.tex_hotel_group or frappe.db.exists("TEX Contract", {"property": property}))


# a reservation sold by TEX carries these (ADR-010); legacy jobs read them to leave it alone
TEX_SOLD_FIELDS = ("tex_booking", "tex_price_locked", "tex_pricing_source")


def is_tex_reservation(row) -> bool:
	"""Sold and priced by TEX: only the TEX services change it (price lock, ADR-010)."""
	return bool(row.get("tex_booking") or row.get("tex_price_locked") or row.get("tex_pricing_source") == "TEX")


def tex_booking_path(property: str | None = None) -> str:
	"""The hotel's TEX booking site (its own, else its hotel group's), or the TEX engine root."""
	site = None
	if property:
		site = frappe.db.get_value("TEX Booking Site", {"property": property, "enabled": 1}, "site_slug")
		group = frappe.db.get_value("Property", property, "tex_hotel_group")
		if not site and group:
			site = frappe.db.get_value("TEX Booking Site", {"hotel_group": group, "enabled": 1}, "site_slug")
	return f"/book/{site}" if site else "/book"


def refuse_legacy_sale(property: str | None) -> None:
	"""Legacy selling paths call this first: a TEX hotel is never priced or booked there."""
	if is_tex_hotel(property):
		frappe.throw(
			_("Online booking for this hotel is on its booking site: {0}").format(tex_booking_path(property)),
			title=_("Not available here"),
		)


# ─── reservations written outside TEX (G-92, ADR-052) ─────────────────────

IMPORTED = "Imported"
# a history row of a migration is a record: it may come without an amount
HISTORY = ("Checked Out", "Cancelled", "No Show")
CRS_PATH = "/kamra/tex/crs"


def sold_through_tex(property: str | None) -> str:
	return _("{0} is sold through TEX: create this reservation in TEX (Reservations → CRS or Call Center, {1}), "
	         "which prices it from the hotel's contracts.").format(property, CRS_PATH)


def flag_import(doc, status: str | None = None) -> None:
	"""A migration importer (``kamra.api.import_bookings``, ``kamra.migrate.run_import``) marks
	the row it is about to insert: at a TEX hotel it is recorded as imported at the amount the
	file carries (``guard_new_reservation``). ``status`` is the row's final status when the
	importer stamps it after the insert. A document flag lives only in this process: a REST
	payload cannot set it (Frappe drops ``flags``)."""
	doc.flags.tex_import = {"status": status or doc.status}


def guard_new_reservation(doc) -> None:
	"""``Reservation.before_insert``: a TEX hotel's reservation is created by TEX only (ADR-052).

	Allowed: the TEX booking service (``flags.tex_sale``, one insert), a channel's sale
	(``flags.tex_channel_accept``) and a migration import (``flag_import``, one insert). Every
	other insert — the Desk form, REST, Frappe's data import, legacy code — is refused, whatever
	its status: a quote or waitlist entry would become a sale later, a history record counts in
	reports and guest stats. The flags are popped here, so they cover the one insert they were
	set for. Runs for every insert, ``ignore_validate`` ones included, before the inventory lock
	is taken and before the reservation takes its name. Hotels outside TEX are unaffected."""
	sale = doc.flags.pop("tex_sale", None)
	imported = doc.flags.pop("tex_import", None)
	if not is_tex_hotel(doc.property):
		return
	if sale or doc.flags.get("tex_channel_accept"):
		return
	if imported:
		_record_import(doc, imported.get("status") or doc.status)
		return
	frappe.throw(sold_through_tex(doc.property), title=_("Book it in TEX"))


def _record_import(doc, status: str) -> None:
	"""A migrated stay keeps the amount it was sold at: never priced by the legacy engine,
	recorded as ``Imported``, price-locked (only TEX changes it afterwards) and audited after
	the insert. Setting a stay's price at a TEX hotel needs ``price.override`` there."""
	from kamra.tex.money import ZERO, D, quantize
	from kamra.tex.security import scope

	scope.require("price.override", doc.property)
	ccy = frappe.db.get_value("Property", doc.property, "currency") or "EUR"
	amount = quantize(D(doc.get("amount_after_tax")), ccy)
	if amount < ZERO or (amount == ZERO and status not in HISTORY):
		frappe.throw(_("An imported booking at {0} needs the amount it was sold at (above zero for a live stay, never "
		               "negative): a TEX hotel's price is never computed by the legacy engine.").format(doc.property),
		             title=_("Amount missing"))
	doc.auto_price = 0
	doc.amount_after_tax = amount
	doc.tex_total_amount = amount
	doc.tex_currency = ccy
	doc.tex_pricing_source = IMPORTED
	doc.tex_price_locked = 1
	doc.tex_locked_at = now_datetime()
	doc.flags.tex_imported = {"status": status, "amount": amount, "currency": ccy}


def record_import(doc) -> None:
	"""``Reservation.after_insert``: the audit event of an imported stay (ADR-052)."""
	info = doc.flags.pop("tex_imported", None)
	if not info:
		return
	from kamra.tex.money import to_str
	from kamra.tex.security.audit import audit

	audit("reservation.import", reference_doctype="Reservation", reference_name=doc.name, property=doc.property,
	      new={"status": info["status"], "amount": to_str(info["amount"]), "currency": info["currency"],
	           "room_type": doc.room_type, "check_in": str(doc.check_in_date),
	           "check_out": str(doc.check_out_date), "pricing_source": IMPORTED})
