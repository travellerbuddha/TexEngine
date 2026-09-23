"""Boundaries between TEX and the legacy Kamra PMS paths (ADR-014, ADR-028).

A hotel inside the TEX tenancy hierarchy (enterprise / hotel group), or one with TEX
contracts, is sold only through TEX: contract pricing, TEX inventory locks and TEX
payments. The legacy selling paths (the ``/kamra/book`` engine, the legacy staff booking
dialog) price from ``Room Type.base_price`` and must never sell such a hotel.
"""

from __future__ import annotations

import frappe
from frappe import _


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
