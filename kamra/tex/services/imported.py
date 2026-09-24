"""Correcting an imported stay's amount (ADR-052 review H1).

An imported stay is price-locked at the amount its file carried, so a wrong reading (before the
strict reader: "150,00" read as 15000.00) could not be corrected by anyone. The correction is a
price override: ``price.override`` at the hotel, a reason, a revision (``Price Override``, basis
MANUAL) and an audit event. Only an imported stay is corrected here; a stay TEX sold changes
through the modification service (``Modify reservation``).
"""

from __future__ import annotations

import frappe
from frappe import _

from kamra.tex.money import from_db, to_str
from kamra.tex.security import scope
from kamra.tex.security.audit import audit

LIVE = ("Confirmed", "Checked In", "Held", "Pending Payment")


def correct_amount(reservation: str, amount, reason: str, currency: str | None = None) -> dict:
	from kamra.tex.importing import AmountError, check_currency, parse_amount
	from kamra.tex.legacy import IMPORTED, known_currency
	from kamra.tex.services import booking as booking_svc

	res = frappe.get_doc("Reservation", reservation, for_update=True)
	scope.require("price.override", res.property)
	if res.get("tex_pricing_source") != IMPORTED:
		frappe.throw(_("Only an imported stay's amount is corrected here. A stay TEX sold changes through Modify "
		               "reservation."), title=_("Not an imported stay"))
	if not (reason or "").strip():
		frappe.throw(_("A reason is required to correct an imported amount."))
	if frappe.db.exists("Folio Charge", {"reservation": res.name, "charge_type": "Room", "amount": ("!=", 0)}):
		frappe.throw(_("Reservation {0}'s nights are already billed on its folio: correct the folio.")
		             .format(res.name))
	old_ccy = res.tex_currency or frappe.db.get_value("Property", res.property, "currency") or "EUR"
	ccy = known_currency(currency) if (currency or "").strip() else old_ccy
	try:
		value, named = parse_amount(amount)
		if value is None:
			raise AmountError(_("an amount is required"))
		new = check_currency(value, named, ccy)
	except AmountError as e:
		frappe.throw(str(e), title=_("Amount"))
	if new <= 0 and res.status in LIVE:
		frappe.throw(_("A live stay needs an amount above zero."), title=_("Amount"))
	old = from_db(res.tex_total_amount or res.amount_after_tax, old_ccy)
	if (new, ccy) == (old, old_ccy):
		frappe.throw(_("The amount is already {0} {1}.").format(to_str(new), ccy))
	res.flags.tex_modification = True        # a TEX service's save (ADR-010): this one only
	res.update({"amount_after_tax": new, "tex_total_amount": new, "tex_currency": ccy})
	res.save(ignore_permissions=True)
	changes = {"amount_after_tax": [to_str(old), to_str(new)], "currency": [old_ccy, ccy]}
	rev = booking_svc._record_revision(res.name, res.tex_booking or None, change_type="Price Override",
	                                   old_amount=old, new_amount=new, currency=ccy, basis="MANUAL",
	                                   reason=reason.strip()[:500], changes=changes, source="Desk", override=new)
	audit("reservation.import_correct", reference_doctype="Reservation", reference_name=res.name,
	      property=res.property, old={"amount": to_str(old), "currency": old_ccy},
	      new={"amount": to_str(new), "currency": ccy, "revision": rev}, reason=reason.strip()[:500])
	return {"reservation": res.name, "revision": rev, "old_amount": to_str(old), "new_amount": to_str(new),
	        "currency": ccy, "old_currency": old_ccy}
