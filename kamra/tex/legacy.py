"""Boundaries between TEX and the legacy Kamra PMS paths (ADR-014, ADR-028, ADR-052).

A hotel inside the TEX tenancy hierarchy (enterprise / hotel group), or one with TEX
contracts, is sold only through TEX: contract pricing, TEX inventory locks and TEX
payments. The legacy selling paths (the ``/kamra/book`` engine, the legacy staff booking
dialog) price from ``Room Type.base_price`` and must never sell such a hotel; neither may
the generic Desk / REST / data-import insert of a Reservation (G-92).
"""

from __future__ import annotations

from contextlib import contextmanager

import frappe
from frappe import _
from frappe.utils import get_datetime, now_datetime


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


# ─── go-live (G-92 review M3, ADR-052) ──────────────────────────────────


def tex_live(property: str | None) -> bool:
	"""Sold through TEX: the hotel is in TEX (``is_tex_hotel``) and an administrator set it live
	(``Property.tex_live_from``, ``set_live``). A hotel that joins TEX is *onboarding* until then:
	its Desk still sells it at the legacy price while contracts are set up. Everything else that
	protects a TEX hotel (ADR-028 legacy selling paths, TEX inventory, imports recorded as
	Imported, the price lock of what TEX sold) follows ``is_tex_hotel`` from the first moment."""
	if not is_tex_hotel(property):
		return False
	at = frappe.db.get_value("Property", property, "tex_live_from")
	return bool(at) and get_datetime(at) <= now_datetime()


def tex_mode(property: str | None) -> str | None:
	"""``live``, ``onboarding`` (in TEX, not live yet) or None (outside TEX): what the shells show."""
	if not is_tex_hotel(property):
		return None
	return "live" if tex_live(property) else "onboarding"


def set_live(property: str, live: bool, reason: str) -> dict:
	"""Set a TEX hotel live (the Desk stops selling it; ADR-052) or back to onboarding (a
	rollback). Needs ``settings.admin`` at the hotel and a reason; audited. The field is written
	only here: the Property controller refuses it from the Desk form, REST or data import."""
	from kamra.tex.security import scope
	from kamra.tex.security.audit import audit

	scope.require("settings.admin", property)
	if not (reason or "").strip():
		frappe.throw(_("A reason is required to change whether a hotel is live in TEX."))
	if not is_tex_hotel(property):
		frappe.throw(_("{0} is not in TEX: add it to a hotel group (or give it a contract) first.").format(property))
	before = frappe.db.get_value("Property", property, "tex_live_from")
	doc = frappe.get_doc("Property", property)
	doc.tex_live_from = now_datetime() if live else None
	doc.flags.tex_go_live = True
	doc.save(ignore_permissions=True)
	audit("hotel.go_live" if live else "hotel.go_live_undo", reference_doctype="Property", reference_name=property,
	      property=property, old={"tex_live_from": str(before) if before else None},
	      new={"tex_live_from": str(doc.tex_live_from) if doc.tex_live_from else None}, reason=reason.strip()[:500])
	return {"property": property, "tex_mode": tex_mode(property),
	        "tex_live_from": str(doc.tex_live_from) if doc.tex_live_from else None}


def guard_live_switch(doc) -> None:
	"""``Property.validate``: ``tex_live_from`` changes only through ``set_live`` (in-process flag,
	popped here); a Desk, REST or data-import write of it is refused."""
	flagged = doc.flags.pop("tex_go_live", None)
	if not doc.meta.has_field("tex_live_from"):
		return
	before = None if doc.is_new() else doc.get_doc_before_save()
	old = before.get("tex_live_from") if before else None
	if str(old or "") != str(doc.get("tex_live_from") or "") and not flagged:
		frappe.throw(_("A hotel goes live in TEX only through TEX (Settings: go live), by an administrator, "
		               "with a reason."), frappe.ValidationError, title=_("Go live in TEX"))


# ─── reservations written outside TEX (G-92, ADR-052) ─────────────────────

IMPORTED = "Imported"
# a history row of a migration is a record: it may come without an amount
HISTORY = ("Checked Out", "Cancelled", "No Show")
CRS_PATH = "/kamra/tex/crs"


def sold_through_tex(property: str | None) -> str:
	return _("{0} is sold through TEX: create this reservation in TEX (Reservations → CRS or Call Center, {1}), "
	         "which prices it from the hotel's contracts.").format(property, CRS_PATH)


def flag_import(doc, status: str | None = None, currency: str | None = None) -> None:
	"""A migration importer (``kamra.api.import_bookings``, ``kamra.migrate.run_import``) marks
	the row it is about to insert: at a TEX hotel it is recorded as imported at the amount the
	file carries, in ``currency`` (``guard_new_reservation``; ``read_import_amount`` reads both).
	``status`` is the row's final status when the importer stamps it after the insert. A document
	flag lives only in this process: a REST payload cannot set it (Frappe drops ``flags``)."""
	doc.flags.tex_import = {"status": status or doc.status, "currency": currency}


def guard_new_reservation(doc) -> None:
	"""``Reservation.before_insert``: a TEX hotel's reservation is created by TEX only (ADR-052).

	Allowed: the TEX booking service (``flags.tex_sale``, one insert), a channel's sale
	(``flags.tex_channel_accept``) and a migration import (``flag_import``, one insert). Once the
	hotel is live in TEX (``tex_live``) every other insert — the Desk form, REST, Frappe's data
	import, legacy code — is refused, whatever its status: a quote or waitlist entry would become a
	sale later, a history record counts in reports and guest stats. While the hotel is onboarding
	the Desk still sells it (legacy-priced; TEX inventory applies). The flags are popped here, so
	they cover the one insert they were set for. Runs for every insert, ``ignore_validate`` ones
	included, before the inventory lock is taken and before the reservation takes its name."""
	sale = doc.flags.pop("tex_sale", None)
	imported = doc.flags.pop("tex_import", None)
	if not is_tex_hotel(doc.property):
		return
	if sale or doc.flags.get("tex_channel_accept"):
		return
	if imported:
		_record_import(doc, imported.get("status") or doc.status, imported.get("currency"))
		return
	if tex_live(doc.property):
		frappe.throw(sold_through_tex(doc.property), title=_("Book it in TEX"))


def known_currency(text: str | None) -> str:
	"""The ISO code of a Currency of the site named by ``text``, else a ValidationError naming it."""
	from kamra.tex.importing import currency_code

	code = currency_code(text)
	if not code or not frappe.db.exists("Currency", code):
		frappe.throw(_("Unknown currency '{0}'.").format((text or "").strip()), title=_("Currency"))
	return code


def read_import_amount(raw, *, property: str, decimal: str | None = None, currency: str | None = None,
                       row_currency: str | None = None):
	"""(amount, currency) of one import row, read strictly (``kamra.tex.importing``; ADR-052
	review H1, L3). At a TEX hotel the row says its currency: a currency column, else the
	currency chosen for the whole import, a Currency of the site; a hotel outside TEX keeps its
	amounts in the hotel's currency, as the legacy PMS does. The amount must fit that currency
	(named in the cell, decimals). Raises with the reason for the row list."""
	from kamra.tex.importing import check_currency, currency_code, parse_amount

	amount, named = parse_amount(raw, decimal=decimal)
	given = (row_currency or "").strip() or (currency or "").strip()
	if is_tex_hotel(property):
		if not given:
			frappe.throw(_("Say which currency the amounts are in: a Currency column or the import's currency."),
			             title=_("Currency"))
		ccy = known_currency(given)
	else:
		ccy = frappe.db.get_value("Property", property, "currency")
		if given and ccy and currency_code(given) != ccy:
			frappe.throw(_("{0} keeps its amounts in {1}, not {2}.").format(property, ccy, given.strip()),
			             title=_("Currency"))
	if amount is not None and ccy:
		amount = check_currency(amount, named, ccy)
	return amount, ccy


def _record_import(doc, status: str, currency: str | None) -> None:
	"""A migrated stay keeps the amount it was sold at: never priced by the legacy engine,
	recorded as ``Imported`` in the currency the import named, price-locked (only TEX changes it
	afterwards) and audited after the insert. Setting a stay's price at a TEX hotel needs
	``price.override`` there."""
	from kamra.tex.money import ZERO, D, quantize
	from kamra.tex.security import scope

	scope.require("price.override", doc.property)
	if not currency:
		frappe.throw(_("An imported booking at {0} needs the currency of its amount.").format(doc.property),
		             title=_("Currency"))
	ccy = known_currency(currency)
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
	"""``Reservation.after_insert``: the audit event of an imported stay (ADR-052). The importer
	runs each row in its own savepoint, so a row that fails later leaves no event behind."""
	info = doc.flags.pop("tex_imported", None)
	if not info:
		return
	from kamra.tex.money import to_str
	from kamra.tex.security.audit import audit

	audit("reservation.import", reference_doctype="Reservation", reference_name=doc.name, property=doc.property,
	      new={"status": info["status"], "amount": to_str(info["amount"]), "currency": info["currency"],
	           "room_type": doc.room_type, "check_in": str(doc.check_in_date),
	           "check_out": str(doc.check_out_date), "pricing_source": IMPORTED})


@contextmanager
def import_savepoint(name: str):
	"""One import row, all or nothing (ADR-052 review M1): the row's guest, reservation, audit
	event and inventory rows are rolled back together when it fails, and the failure is reported
	for that row. A deadlock is raised: InnoDB has undone the whole import (G-49 review)."""
	frappe.db.savepoint(name)
	try:
		yield
	except frappe.QueryDeadlockError:
		raise
	except Exception:
		frappe.db.rollback(save_point=name)
		raise
	frappe.db.release_savepoint(name)


def insert_imported(doc, final_status: str | None) -> None:
	"""Insert an import row with its final status, as a record or as a live stay:

	- a history row (Checked Out, Cancelled, No Show) is a record: inserted without live
	  validation, its status stamped; it holds no room;
	- an in-house row (Checked In) is inserted as Confirmed and checked like any live stay (TEX
	  inventory at a TEX hotel; its arrival may be past), then stamped Checked In without the
	  check-in side effects: the guest arrived in the previous system."""
	if final_status in HISTORY:
		doc.flags.ignore_validate = True
	elif final_status == "Checked In":
		doc.flags.allow_past_check_in = True
	doc.insert()
	if final_status and final_status != doc.status:
		doc.db_set("status", final_status, update_modified=False)


# ─── the legacy folio and a price TEX locked (G-96, ADR-052 review) ──────


def locked_bill(res) -> dict | None:
	"""How the legacy folio bills a stay whose price is locked (``is_tex_reservation``), or None
	for a stay the legacy engine prices (a hotel outside TEX, an unlocked legacy stay). Never the
	legacy Room Type rate:

	- ``{"tex": True, ...}``: sold through TEX (a TEX booking, also a channel's sale). Its TEX
	  booking is the bill — total, payments, balance, cancellation penalty — so the folio posts
	  none of its nights, board, discount or cleaning fee (as the night audit, ADR-028);
	- ``{"foreign": True, ...}``: locked in another currency than the hotel's. The folio is in the
	  hotel's currency and TEX never converts a locked price silently: nothing is billed here;
	- ``{"nights": {date: amount}, "gst_rate": rate, ...}``: a price-locked stay without a TEX
	  booking (imported, or a legacy stay locked at the TEX upgrade): its locked amount split
	  evenly over its nights (Decimal, the remainder on the last night). A stay that recorded its
	  tax split posts the pre-tax share with its own tax rate; an imported amount carries no split
	  and is posted tax included (rate 0)."""
	if not is_tex_reservation(res):
		return None
	from frappe.utils import add_days, getdate

	from kamra.tex.money import D, from_db, split_evenly

	hotel_ccy = frappe.db.get_value("Property", res.property, "currency")
	ccy = res.get("tex_currency") or hotel_ccy or "EUR"
	total = from_db(res.get("tex_total_amount") or res.get("amount_after_tax"), ccy)
	out = {"currency": ccy, "total": total, "booking": res.get("tex_booking")}
	if res.get("tex_booking"):
		return {**out, "tex": True}
	if hotel_ccy and ccy != hotel_ccy:
		return {**out, "foreign": True}
	start, end = getdate(res.check_in_date), getdate(res.check_out_date)
	dates = [getdate(add_days(start, i)) for i in range(max(1, (end - start).days))]
	before, tax = from_db(res.get("amount_before_tax"), ccy), from_db(res.get("tax_amount"), ccy)
	rate = D(0)
	base = total
	if before > 0 and tax >= 0 and before + tax == total:
		base, rate = before, (tax * 100 / before).quantize(D("0.000001"))
	return {**out, "nights": dict(zip(dates, split_evenly(base, len(dates), ccy), strict=True)), "gst_rate": rate}


def locked_fee(res, basis: str) -> tuple:
	"""A price-locked stay's policy fee from its locked amount (ADR-052 review M2): ``Full Stay``
	the whole locked price, ``First Night`` its first night's share (as the folio posts it), else
	nothing. (amount, gst_rate) as the legacy folio posts it; None when the folio does not bill
	the stay (sold through TEX, another currency)."""
	from kamra.tex.money import ZERO

	bill = locked_bill(res)
	if bill is None or bill.get("tex") or bill.get("foreign"):
		return None
	nights = list(bill["nights"].values())
	amount = sum(nights, ZERO) if basis == "Full Stay" else (nights[0] if basis == "First Night" else ZERO)
	return amount, bill["gst_rate"]


def refuse_legacy_cancel(res) -> None:
	"""The legacy cancellation (``kamra.api.cancel_reservation``) applies the hotel's legacy
	policy on the folio. A stay the folio does not bill — sold through TEX (its frozen rate-plan
	policy applies), or locked in another currency — is cancelled in TEX only."""
	bill = locked_bill(res)
	if bill and (bill.get("tex") or bill.get("foreign")):
		frappe.throw(_("Reservation {0} is billed in TEX ({1}). Cancel it in TEX (Reservations), which applies "
		               "its cancellation policy.").format(res.name, bill.get("booking") or bill["currency"]),
		             title=_("Cancel it in TEX"))


def hotel_policy_penalty(res, today=None) -> tuple:
	"""The TEX cancellation penalty of a stay TEX did not price (no TEX snapshot: imported, or a
	legacy stay): the hotel's own policy (free days before arrival, fee basis) applied to the
	stay's locked amount, after tax (ADR-052 review M2). (penalty, basis dict)."""
	from frappe.utils import getdate, nowdate

	from kamra.tex.money import ZERO, from_db, quantize, split_evenly

	policy = frappe.db.get_value("Property", res.property, ["free_cancel_days", "cancellation_fee"],
	                             as_dict=True) or frappe._dict()
	ccy = res.get("tex_currency") or frappe.db.get_value("Property", res.property, "currency") or "EUR"
	total = from_db(res.get("tex_total_amount") or res.get("amount_after_tax"), ccy)
	days = (getdate(res.check_in_date) - getdate(today or nowdate())).days
	basis = policy.cancellation_fee or "None"
	rule = {"rule": "hotel cancellation policy (stay not priced by TEX)", "fee_basis": basis,
	        "free_cancel_days": int(policy.free_cancel_days or 0), "days_before": days}
	if days >= int(policy.free_cancel_days or 0) or basis == "None" or total <= 0:
		return quantize(ZERO, ccy), rule
	if basis == "Full Stay":
		return total, rule
	nights = max(1, (getdate(res.check_out_date) - getdate(res.check_in_date)).days)
	return split_evenly(total, nights, ccy)[0], rule
