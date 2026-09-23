"""A guest's own change to a booking and its money (G-45, ADR-044).

The manage page proposes a change (``modification.propose``); ``preview`` says how it would be
settled (``payments.settlement``); ``submit`` records the guest's acceptance as a TEX Guest
Change Request and then:

- a higher price that the booking's payment terms need paid now: the request waits for that
  payment ("Awaiting Payment") and the reservation is untouched. When the gateway confirms the
  charge, ``on_charge_succeeded`` (called by the payments service after the money is
  allocated) applies the change server-side, re-priced as of the proposal's sale time. A
  change that can no longer apply is "Failed" and its payment refunded;
- a higher price with nothing due now (pay at hotel, a deposit already covering it, a credit),
  an unchanged price, or a lower price under the "Refund automatically" / "Keep as credit"
  policies: applied now; a refund of the overpayment runs in a job queued after the commit;
- a lower price under "Staff approval", or money due now without a card method: "Requested",
  for staff (``resolve``).

A request is keyed by its proposal: submitting the same proposal twice is one request. Refunds
are keyed per request and charge, and made by a job queued after commit, so a request retried
after a deadlock never refunds twice. Nothing here raises into the payment callback.

Locks: the booking first, then the request (and the reservation): a guest's submit, a payment
callback (it holds the booking once the money is allocated), the refund job and staff all
take them in that order.
"""

from __future__ import annotations

import hashlib
import json

import frappe
from frappe import _
from frappe.utils import add_to_date, get_datetime, now_datetime

from kamra.tex.money import ZERO, D, from_db, quantize, to_str
from kamra.tex.payments import settlement as st
from kamra.tex.pricing.extras import guest_reason
from kamra.tex.security import scope
from kamra.tex.security.audit import audit, log_exception
from kamra.tex.services import booking as booking_svc
from kamra.tex.services import modification, quoting

DT = "TEX Guest Change Request"
TXN = "TEX Payment Transaction"
OPEN = ("Awaiting Payment", "Requested")
DONE = ("Applied", "Approved")
# the request's settlement field ↔ the settlement kind the guest API speaks
LABEL = {st.PAY_NOW: "Online payment", st.PAY_AT_HOTEL: "Pay at hotel", st.BALANCE: "Balance", st.REFUND: "Refund",
         st.CREDIT: "Credit on booking", st.NONE: "None", st.STAFF: "Staff"}
KIND = {v: k for k, v in LABEL.items()}
GUEST_STATUS = {"Awaiting Payment": "awaiting_payment", "Requested": "requested"}
SETTLE_RETRY_MINUTES = 10


class PaymentPending(frappe.ValidationError):
	"""The booking's own payment is not complete: it cannot be changed yet."""


class CurrencyChanged(frappe.ValidationError):
	"""The change would be priced in another currency than the booking's."""


def _commit() -> None:
	"""A job's step is its own unit of work in production; tests keep one transaction."""
	if not frappe.flags.in_test:
		frappe.db.commit()  # nosemgrep: frappe-manual-commit -- background worker unit-of-work boundary


def _lock(name: str):
	"""The request's booking, then the request, read as they are now (locking reads)."""
	booking = frappe.db.get_value(DT, name, "booking")
	if booking:
		frappe.db.get_value("TEX Booking", booking, "name", for_update=True)
	return frappe.get_doc(DT, name, for_update=True)


def _step(fn, title: str):
	"""One unit of scheduled work, committed on its own outside tests. A failure undoes only
	that unit (refunds it made before failing were committed one by one, on record)."""
	frappe.db.savepoint("tex_gcr_step")
	try:
		out = fn()
	except Exception:
		if frappe.flags.in_test:
			frappe.db.rollback(save_point="tex_gcr_step")
		else:
			frappe.db.rollback()
		log_exception(title)
		return None
	_commit()
	return out


def _hash(token: str) -> str:
	return hashlib.sha256(("tex-guest-change:" + token).encode()).hexdigest()


def _money(v, ccy: str) -> str:
	return to_str(quantize(D(v), ccy))


# ─── preview ─────────────────────────────────────────────────────────────


def guard(b) -> None:
	"""A booking waiting for its own payment (or held) is paid first, then changed."""
	if b.status in ("Pending Payment", "Held"):
		frappe.throw(_("Please complete the payment of your booking before changing it."), PaymentPending,
		             title=_("Payment pending"))


def lower_policy(property: str) -> str:
	return frappe.db.get_value("Property", property, "tex_lower_price_refund") or st.LOWER_STAFF


def card_account(b) -> str | None:
	"""The card gateway account the booking's hotel offers for its market, currency, channel."""
	from kamra.tex.payments import service as pay

	for m in pay.payment_methods(b.property, market=b.market, currency=b.currency, channel=b.sales_channel):
		if m["method"] == "Card" and m["provider_account"]:
			return m["provider_account"]
	return None


def preview(b, res, prop: dict) -> st.Settlement | None:
	"""How ``prop`` (a ``modification.propose`` result for ``res``) would be settled for
	booking ``b``; None when it cannot be (not priced, or priced in another currency)."""
	ccy = b.currency
	new_room = (prop.get("proposed") or {}).get("totals", {}).get("total")
	if prop.get("currency_changed") or prop.get("difference") is None or not new_room \
			or prop["proposed"].get("currency") != ccy or (res.tex_currency or ccy) != ccy:
		return None
	old_total = from_db(b.total_amount, ccy)
	new_total = old_total - D(prop["old"]["total"]) + D(new_room)
	required = booking_svc.required_now(b, {res.name: prop["proposed"]})
	return st.settle(old_total, new_total, from_db(b.paid_amount, ccy), required,
	                 pay_at_hotel=b.payment_method == "Pay at Hotel", lower_policy=lower_policy(b.property),
	                 card_available=bool(card_account(b)))


def settlement_dict(s: st.Settlement | None, ccy: str) -> dict | None:
	"""The guest API's view of a settlement (amounts as strings, never floats)."""
	if s is None:
		return None
	return {"kind": s.kind, "amount": _money(s.amount, ccy), "collect": _money(s.collect, ccy),
	        "refund": _money(s.refund, ccy), "credit": _money(s.credit, ccy),
	        "balance_after": _money(s.balance_after, ccy), "currency": ccy}


# ─── submit ──────────────────────────────────────────────────────────────


def submit(b, proposal_token: str, *, note: str | None = None, return_url: str | None = None) -> dict:
	"""The guest accepts a proposal (the caller checked the manage token, the reservation and
	self-service). Idempotent by proposal: a second submit answers what the first one did."""
	p = quoting.verify(proposal_token, kind="proposal", allow_expired=True)
	existing = frappe.db.get_value(DT, {"proposal_hash": _hash(proposal_token)}, "name")
	if existing:
		return _replay(existing, p, return_url)
	quoting.require_fresh(p)
	# one change of a booking at a time, read as it is now: the booking, then the reservation
	# (the order a payment callback takes them: apply_payment locks the booking first)
	b = frappe.get_doc("TEX Booking", b.name, for_update=True)
	guard(b)
	res = frappe.get_doc("Reservation", p["reservation"], for_update=True)
	if res.tex_booking != b.name:
		frappe.throw(_("Invalid reservation."), frappe.PermissionError)
	# the reservation's requests as they are now (a locking read of existing rows: another tab
	# may have submitted this proposal while this one waited for the booking)
	rows = frappe.db.sql(f"SELECT name, proposal_hash, status FROM `tab{DT}` WHERE reservation=%s FOR UPDATE",
	                     (res.name,), as_dict=True)  # nosemgrep -- constant doctype
	mine = next((r.name for r in rows if r.proposal_hash == _hash(proposal_token)), None)
	if mine:
		return _replay(mine, p, return_url, concurrent=True)
	if p.get("currency") != (res.tex_currency or b.currency) or (res.tex_currency or b.currency) != b.currency:
		frappe.throw(_("This change cannot be priced in the currency of your booking. Please contact the hotel."),
		             CurrencyChanged)
	prop = _derive(res, p)
	s = preview(b, res, prop)
	if s is None:
		frappe.throw(_("This change cannot be priced in the currency of your booking. Please contact the hotel."),
		             CurrencyChanged)
	req = _insert(b, res, p, _hash(proposal_token), s, note)
	if req is None:
		# the same proposal is being submitted right now (another tab): its answer is on the way
		return {"status": "processing", "request": None,
		        "message": _("Your change is being processed. Please reload the page in a moment.")}
	_supersede([r.name for r in rows if r.status in OPEN], req.name)
	if s.kind == st.PAY_NOW:
		audit("guest_change.request", reference_doctype=DT, reference_name=req.name, property=b.property,
		      new=_audit_row(req, s))
		return _start_payment(req, b, return_url, new_attempt=True)
	if s.kind in (st.STAFF_APPROVAL, st.STAFF):
		ccy = b.currency
		why = (_("lower price, the hotel approves it") if s.kind == st.STAFF_APPROVAL
		       else _("{0} {1} is due now and no card payment is set up").format(_money(s.collect, ccy), ccy))
		_flag(res.name, b.name, f"Guest requests a change ({_money(s.difference, ccy)} {ccy}; {why}); "
		                        f"request {req.name} {json.dumps(p['changes'], default=str)} {note or ''}")
		audit("guest_change.request", reference_doctype=DT, reference_name=req.name, property=b.property,
		      new=_audit_row(req, s))
		return _requested(req, s)
	return _apply_now(req, proposal_token, s, note)


def _derive(res, p: dict) -> dict:
	"""The proposal priced again now, before anything is charged or applied: still sellable, on
	an unchanged reservation, at the price the guest accepted (the checks ``apply`` repeats)."""
	if str(res.modified) != p["modified"]:
		frappe.throw(_("The reservation changed since this proposal was made — review it again."))
	prop = modification.propose(res.name, p["changes"], basis=p["basis"], basis_sale_at=p.get("basis_sale_at"),
	                            _check_permission=False, internal=True)
	if not prop["sellable"]:
		why = "; ".join(w["message"] for w in prop["warnings"]) or prop["proposed"].get("reasons")
		frappe.throw(_("The modified stay cannot be sold: {0}").format(guest_reason(str(why))))
	if prop["proposed"]["totals"]["total"] != p["new_total"]:
		frappe.throw(_("The price moved since this proposal was made — review it again."))
	return prop


def _insert(b, res, p: dict, digest: str, s: st.Settlement, note: str | None):
	ccy = b.currency
	status = {st.PAY_NOW: "Awaiting Payment", st.STAFF_APPROVAL: "Requested", st.STAFF: "Requested"}.get(s.kind,
	                                                                                                   "Applied")
	old_total = from_db(b.total_amount, ccy)
	doc = frappe.get_doc({
		"doctype": DT, "property": b.property, "booking": b.name, "reservation": res.name, "status": status,
		"proposal_hash": digest, "proposal": json.dumps(p, sort_keys=True, default=str), "note": note,
		"expires_at": modification.payment_deadline(p) if s.kind == st.PAY_NOW else None,
		"currency": ccy, "old_total": old_total, "new_total": old_total + s.difference, "difference": s.difference,
		"collect_amount": s.collect if s.kind in (st.PAY_NOW, st.STAFF) else ZERO, "attempt": 0,
		"settlement": LABEL.get(s.kind, "") if status == "Applied" else "",
		"settlement_amount": quantize(s.amount, ccy) if status == "Applied" else ZERO,
	})
	frappe.db.savepoint("tex_gcr_insert")
	try:
		doc.insert(ignore_permissions=True)
	except (frappe.UniqueValidationError, frappe.DuplicateEntryError):
		frappe.db.rollback(save_point="tex_gcr_insert")
		frappe.clear_last_message()
		return None
	return doc


def _supersede(names: list[str], by: str) -> None:
	"""One open request per reservation: the guest's newer change replaces an older one (read
	and locked by the caller). A payment of the older one arriving later is refunded."""
	for name in names:
		r = frappe.get_doc(DT, name)
		r.status = "Superseded"
		r.error = f"replaced by {by}"
		r.save(ignore_permissions=True)
		audit("guest_change.superseded", reference_doctype=DT, reference_name=name, property=r.property,
		      new={"by": by})


def close_open(reservation: str, why: str) -> None:
	"""The reservation was cancelled: a change still waiting for it is void (a payment of it
	arriving later is refunded). Called by ``booking.cancel_reservation``."""
	names = frappe.db.sql(f"SELECT name FROM `tab{DT}` WHERE reservation=%s AND status IN %s FOR UPDATE",
	                      (reservation, OPEN), pluck=True)  # nosemgrep -- constant doctype
	for name in names:
		r = frappe.get_doc(DT, name)
		r.status = "Superseded"
		r.error = why[:500]
		r.save(ignore_permissions=True)
		audit("guest_change.superseded", reference_doctype=DT, reference_name=name, property=r.property,
		      new={"why": why})


def _apply_now(req, proposal_token: str, s: st.Settlement, note: str | None) -> dict:
	out = modification.apply(proposal_token, reason=note or "Guest self-service change", source="Guest",
	                         _guest_authorized=True)
	req.revision = out["revision"]
	_after_apply(req, s)
	if s.kind == st.REFUND:
		req.settle_pending = 1
	req.save(ignore_permissions=True)
	audit("guest_change.applied", reference_doctype=DT, reference_name=req.name, property=req.property,
	      new=_audit_row(req, s))
	if s.kind == st.CREDIT:
		audit("guest_change.credit", reference_doctype="TEX Booking", reference_name=req.booking,
		      property=req.property, new={"request": req.name, "credit": to_str(quantize(s.credit, req.currency)),
		                                  "currency": req.currency})
	if s.kind == st.REFUND:
		queue_settle(req.name)
	req.reload()                          # as settled so far (tests run the refund job inline)
	return _applied(req, replay=False)


def _after_apply(req, s: st.Settlement | None) -> None:
	"""Staff hear of every guest change; the deposit due follows the new price."""
	ccy = req.currency
	what = {st.CREDIT: f"{_money(s.credit, ccy)} {ccy} kept as credit on the booking",
	        st.REFUND: f"{_money(s.refund, ccy)} {ccy} being refunded",
	        st.PAY_NOW: f"{_money(s.collect, ccy)} {ccy} paid online",
	        st.PAY_AT_HOTEL: f"{_money(s.amount, ccy)} {ccy} more to pay at the hotel"}.get(s.kind, "") if s else ""
	_flag(req.reservation, req.booking, f"Guest changed online ({req.name}{'; ' + what if what else ''})")
	frappe.db.set_value("TEX Booking", req.booking, "amount_due_now", booking_svc.required_now(req.booking),
	                    update_modified=False)


def _flag(reservation: str, booking: str, note: str) -> None:
	# never bumps the reservation's modified: a proposal made before stays valid for staff
	frappe.db.set_value("Reservation", reservation, {"tex_guest_change_pending": 1,
	                                                  "tex_guest_change_note": note[:1000]}, update_modified=False)
	frappe.db.set_value("TEX Booking", booking, "guest_change_pending", 1, update_modified=False)


def _audit_row(req, s: st.Settlement | None = None) -> dict:
	out = {"booking": req.booking, "reservation": req.reservation, "status": req.status, "currency": req.currency,
	       "difference": to_str(from_db(req.difference, req.currency)),
	       "collect": to_str(from_db(req.collect_amount, req.currency)), "settlement": req.settlement,
	       "settlement_amount": to_str(from_db(req.settlement_amount, req.currency)),
	       "payment": req.payment_transaction, "revision": req.revision}
	if s:
		out["kind"] = s.kind
	return out


# ─── answers ─────────────────────────────────────────────────────────────


def _applied(req, *, replay: bool) -> dict:
	summary = booking_svc.booking_summary(req.booking)
	rev = frappe.db.get_value("TEX Reservation Revision", req.revision, ["old_amount", "new_amount", "difference",
	                                                                     "currency"], as_dict=True) or {}
	ccy = rev.get("currency") or req.currency
	kind = KIND.get(req.settlement or "", st.BALANCE)
	return {"status": "applied", "request": req.name, "reservation": req.reservation, "revision": req.revision,
	        "old_total": to_str(from_db(rev.get("old_amount"), ccy)),
	        "new_total": to_str(from_db(rev.get("new_amount"), ccy)),
	        "difference": to_str(from_db(rev.get("difference"), ccy)), "currency": ccy,
	        "balance": summary["balance"], "paid": summary["paid"], "credit": summary["credit"],
	        "settlement": {"kind": kind, "amount": to_str(from_db(req.settlement_amount, req.currency)),
	                       "currency": req.currency},
	        "replay": replay}


def _requested(req, s: st.Settlement | None = None) -> dict:
	ccy = req.currency
	kind = s.kind if s else (st.STAFF_APPROVAL if D(req.difference) < 0 else st.STAFF)
	amount = s.amount if s else (abs(from_db(req.difference, ccy)) if kind == st.STAFF_APPROVAL
	                             else from_db(req.collect_amount, ccy))
	return {"status": "requested", "request": req.name,
	        "settlement": {"kind": kind, "amount": _money(amount, ccy), "currency": ccy},
	        "message": _("Your request was sent to the hotel for approval.")}


def _processing(req) -> dict:
	return {"status": "processing", "request": req.name,
	        "message": _("Your change is being processed. Please reload the page in a moment.")}


def _not_made(req) -> None:
	why = {"Failed": _("it could not be applied and any payment for it is refunded"),
	       "Expired": _("its payment did not arrive in time"),
	       "Superseded": _("you made another change after it, or the room was cancelled"),
	       "Rejected": _("the hotel declined it")}.get(req.status, req.status)
	frappe.throw(_("This change was not made: {0}. Please look at your booking and try again.").format(why))


def _replay(name: str, p: dict, return_url: str | None, *, concurrent: bool = False) -> dict:
	"""What the first submit of this proposal did. ``concurrent``: found under the booking lock,
	submitted by another tab while this one waited (read with a lock: this request's snapshot
	predates it)."""
	req = frappe.get_doc(DT, name, for_update=concurrent)
	if req.status in DONE:
		return _applied(req, replay=True)
	if req.status == "Requested":
		return _requested(req)
	if req.status == "Awaiting Payment":
		if concurrent or any(True for _t in _charges_of(req)):
			return _processing(req)
		quoting.require_fresh(p)          # a new attempt needs a live proposal
		return _start_payment(req, frappe.get_doc("TEX Booking", req.booking), return_url)
	_not_made(req)


def pay_again(b, name: str, return_url: str | None = None) -> dict:
	"""The guest pays for their change waiting for a payment again (the manage page, after a
	failed or abandoned checkout): the open charge, or a new one once the proposal was priced
	again at the accepted price. The proposal must still be fresh; after that the guest makes
	the change again."""
	req = frappe.get_doc(DT, name) if frappe.db.exists(DT, name) else None
	if not req or req.booking != b.name:
		frappe.throw(_("Invalid link."), frappe.PermissionError)
	if req.status in DONE:
		return _applied(req, replay=True)
	if req.status != "Awaiting Payment":
		_not_made(req)
	if any(True for _t in _charges_of(req)):
		return _processing(req)
	quoting.require_fresh(json.loads(req.proposal))
	return _start_payment(req, b, return_url)


# ─── paying for a change ─────────────────────────────────────────────────


def _start_payment(req, b, return_url: str | None, *, new_attempt: bool = False) -> dict:
	"""Start the change's charge, or reuse the one still open (another tab, a double click).
	After a failed or cancelled attempt a new charge is started, once the proposal was priced
	again (it must still be sellable at the accepted price).

	A retry takes its locks in the payment callback's order: the charge (``start_payment``
	re-reads a reused one with a lock), then the request; the first start holds only rows it
	has just inserted."""
	from kamra.tex.payments import service as pay
	from kamra.tex.services import sites

	account = card_account(b)
	if not account:
		frappe.throw(_("This payment method is not available."))
	attempt = int(req.attempt or 0)
	current = frappe.db.get_value(TXN, req.payment_transaction, "status") if req.payment_transaction else None
	if new_attempt or current != "Pending":
		if not new_attempt:
			_derive(frappe.get_doc("Reservation", req.reservation), json.loads(req.proposal))
		attempt += 1
	site = frappe.get_cached_doc("TEX Booking Site", b.booking_site) if b.booking_site else None
	back = return_url or (sites.guest_url(site, "manage") if site else sites.platform_url("/book"))
	ccy = b.currency
	amount = from_db(req.collect_amount, ccy)
	out = None
	for _try in (1, 2):
		try:
			out = pay.start_payment(
				property=b.property, amount=amount, currency=ccy, provider_account=account, booking=b.name,
				reservation=req.reservation, description=_("Change to booking {0}").format(b.name),
				locale=b.language or "en", return_url=back, method="Card",
				customer={"name": b.booker_name, "email": b.booker_email, "phone": b.booker_phone,
				          "ip": getattr(frappe.local, "request_ip", None)},
				idempotency_key=f"change:{req.name}:{attempt}")
			break
		except pay.ChargeSuperseded:
			# the open charge could not take another checkout and was cancelled (G-68): a new one
			if _try == 2:
				raise
			attempt += 1
	if not new_attempt:
		req = frappe.get_doc(DT, req.name, for_update=True)          # as it is now
		if req.status != "Awaiting Payment":
			_not_made(req)
	req.attempt = max(int(req.attempt or 0), attempt)
	req.payment_transaction = out["transaction"]
	req.save(ignore_permissions=True)
	return {"status": "payment_required", "request": req.name, "amount": to_str(amount), "currency": ccy,
	        "expires_at": str(req.expires_at),
	        "settlement": {"kind": st.PAY_NOW, "amount": to_str(amount), "currency": ccy}, "payment": out}


def _charge_keys(req) -> dict[str, int]:
	from kamra.tex.payments import service as pay

	return {pay.ns_key(req.property, f"change:{req.name}:{n}", "charge"): n
	        for n in range(1, int(req.attempt or 0) + 1)}


def _charges_of(req):
	"""The succeeded charges of this request's payment attempts."""
	for key in _charge_keys(req):
		row = frappe.db.get_value(TXN, {"idempotency_key": key}, ["name", "status"], as_dict=True)
		if row and row.status == "Succeeded":
			yield row.name


def request_of_charge(txn) -> str | None:
	"""The guest change a charge was started for (its idempotency key names it), or None."""
	if txn.txn_type != "Charge" or not txn.booking or not txn.idempotency_key:
		return None
	for r in frappe.get_all(DT, filters={"booking": txn.booking, "attempt": (">", 0)}, fields=["name", "attempt",
	                                                                                             "property"]):
		if txn.idempotency_key in _charge_keys(r):
			return r.name
	return None


def on_charge_succeeded(txn) -> None:
	"""Payments hook (after the charge was allocated to its booking, which is locked): a change
	waiting for this payment is applied now, server-side, never from the guest's browser
	return. A change that can no longer apply fails and its payment is refunded; a payment for
	a request that is no longer waiting (superseded, expired, already paid) is refunded. Never
	raises into the payment: only a deadlock, which rolled the whole transaction back, is
	passed on."""
	try:
		name = request_of_charge(txn)
	except Exception:
		log_exception(f"TEX guest change lookup for {txn.name}")
		return
	if not name:
		return
	frappe.db.savepoint("tex_gcr_paid")
	try:
		queue = _paid(name, txn)
	except frappe.QueryDeadlockError:
		raise
	except Exception as e:
		frappe.db.rollback(save_point="tex_gcr_paid")
		frappe.clear_last_message()
		log_exception(f"TEX guest change {name} after payment {txn.name}")
		queue = _fail_safely(name, txn, str(e))
	if queue:
		queue_settle(name)


def _paid(name: str, txn) -> bool:
	"""→ whether money of this request is to be refunded."""
	req = frappe.get_doc(DT, name, for_update=True)
	if req.status in DONE and req.payment_transaction == txn.name:
		return False                                      # this payment already applied it
	if req.status != "Awaiting Payment":
		req.settle_pending = 1
		req.save(ignore_permissions=True)
		audit("guest_change.late_payment", reference_doctype=DT, reference_name=name, property=req.property,
		      new={"transaction": txn.name, "status": req.status, "amount": to_str(from_db(txn.amount, txn.currency))})
		return True
	frappe.db.savepoint("tex_gcr_apply")
	try:
		out = modification.apply(None, reason=req.note or "Guest self-service change (paid online)", source="Guest",
		                         _guest_authorized=True, _proposal=json.loads(req.proposal), _from_payment=True)
	except frappe.QueryDeadlockError:
		raise
	except frappe.ValidationError as e:
		frappe.db.rollback(save_point="tex_gcr_apply")
		frappe.clear_last_message()
		_fail(req, txn, str(e))
		return True
	req.status = "Applied"
	req.payment_transaction = txn.name
	req.revision = out["revision"]
	req.settlement = LABEL[st.PAY_NOW]
	req.settlement_amount = from_db(txn.amount, txn.currency)
	_after_apply(req, st.Settlement(st.PAY_NOW, collect=from_db(txn.amount, txn.currency)))
	req.save(ignore_permissions=True)
	audit("guest_change.applied", reference_doctype=DT, reference_name=name, property=req.property,
	      new=_audit_row(req))
	return False


def _fail(req, txn, error: str) -> None:
	req.status = "Failed"
	req.payment_transaction = txn.name
	req.error = error[:500]
	req.settle_pending = 1
	req.save(ignore_permissions=True)
	audit("guest_change.failed", reference_doctype=DT, reference_name=req.name, property=req.property,
	      new={**_audit_row(req), "error": req.error})


def _fail_safely(name: str, txn, error: str) -> bool:
	try:
		req = frappe.get_doc(DT, name, for_update=True)
		if req.status == "Awaiting Payment":
			_fail(req, txn, error)
		else:
			req.settle_pending = 1
			req.save(ignore_permissions=True)
		return True
	except frappe.QueryDeadlockError:
		raise
	except Exception:
		log_exception(f"TEX guest change {name} could not be marked failed")
		return False


# ─── refunds ─────────────────────────────────────────────────────────────


def queue_settle(name: str) -> None:
	"""Refunds run after the commit that decided them: a request retried after a deadlock (or
	rolled back) never refunds at the gateway. Tests run the job inline."""
	frappe.enqueue("kamra.tex.services.guest_changes.settle", queue="short", request=name,
	               enqueue_after_commit=True, now=bool(frappe.flags.in_test))


def settle(request: str) -> dict:
	"""The refunds a request owes (a queued job, retried by the scheduler). Idempotent:

	- an applied change under the refund policy: the overpayment, from the charges holding the
	  booking's money (``settlement.plan_refunds``); what no charge can refund stays as credit
	  and goes to staff (settlement "Staff");
	- a paid change that did not apply, or a payment arriving for a request that no longer
	  waited: that payment, back to the card (what the booking still holds of it).

	Each refund is keyed by the request, the charge and the step, and committed before the next
	one is made (outside tests)."""
	from kamra.tex.payments import service as pay

	req = _lock(request)
	if not req.settle_pending:
		return {"request": request, "refunded": "0.00", "not_refunded": "0.00", "pending": False}
	ccy = req.currency
	refunded = ZERO
	short = ZERO
	if req.status in DONE and req.settlement == "Refund":
		failed: set[str] = set()
		while True:
			left = from_db(req.settlement_amount, ccy) - from_db(req.refunded_amount, ccy)
			charges = [st.Charge(c["transaction"], c["available"], c["supported"] and c["transaction"] not in failed,
			                     c["at"]) for c in pay.booking_charges(req.booking)]
			plan, rest = st.plan_refunds(max(ZERO, left), charges)
			if not plan:
				short = rest
				break
			txn, amount = plan[0]
			# keyed by the request, the charge and how much was refunded before: the same step
			# replays, a later step (after a commit) is a new refund
			key = f"change:{req.name}:refund:{txn}:{to_str(from_db(req.refunded_amount, ccy))}"
			got = _refund(req, txn, amount, key, "the guest's change lowered the price")
			if got <= 0:
				failed.add(txn)
				continue
			refunded += got
			req = _progress(req, got)
			if not req.settle_pending:
				return {"request": request, "refunded": to_str(quantize(refunded, ccy)), "not_refunded": "0.00",
				        "pending": False}                       # another run finished it meanwhile
	elif req.status != "Awaiting Payment":
		for txn in list(_charges_of(req)):
			if req.status in DONE and txn == req.payment_transaction:
				continue                                      # the payment the change was made with
			row = frappe.db.get_value(TXN, txn, ["name", "txn_type", "status", "provider_account", "amount",
			                                      "currency"], as_dict=True)
			held = min(pay.booking_nets(txn).get(req.booking, ZERO),
			           from_db(row.amount, row.currency) - pay.refunded_of(txn))
			if held <= 0:
				continue                                      # already given back
			got = _refund(req, txn, held, f"change:{req.name}:return:{txn}",
			              "payment for a guest change that was not applied") if pay.auto_refundable(row) else ZERO
			refunded += got
			short += held - got
			if got > 0:
				req = _progress(req, got)
	req.settle_pending = 0
	if short > 0:
		if req.settlement in ("", None, "Refund"):
			req.settlement = "Staff"
		req.error = (f"{to_str(quantize(short, ccy))} {ccy} could not be refunded automatically: it stays as credit "
		             f"on the booking for staff to refund. {req.error or ''}")[:500]
		_flag(req.reservation, req.booking, f"Guest change {req.name}: {to_str(quantize(short, ccy))} {ccy} to "
		                                    "refund by staff (credit on the booking)")
		audit("guest_change.refund_incomplete", reference_doctype=DT, reference_name=req.name,
		      property=req.property, new={"not_refunded": to_str(quantize(short, ccy)), "currency": ccy,
		                                  "refunded": to_str(quantize(refunded, ccy))})
	req.save(ignore_permissions=True)
	_commit()
	return {"request": request, "refunded": to_str(quantize(refunded, ccy)),
	        "not_refunded": to_str(quantize(short, ccy)), "pending": False}


def _refund(req, txn: str, amount, key: str, why: str) -> D:
	"""One refund (never raises but for a deadlock): → the amount refunded."""
	from kamra.tex.payments import service as pay

	frappe.db.savepoint("tex_gcr_refund")
	try:
		out = pay.refund(txn, amount=amount, reason=f"Guest change {req.name}: {why}", idempotency_key=key,
		                 booking=req.booking, _system=True)
	except frappe.QueryDeadlockError:
		raise
	except Exception:
		frappe.db.rollback(save_point="tex_gcr_refund")
		frappe.clear_last_message()
		log_exception(f"TEX guest change {req.name} refund of {txn}")
		return ZERO
	r = frappe.db.get_value(TXN, out["refund"], ["status", "amount", "currency"], as_dict=True)
	if not r or r.status != "Succeeded":
		return ZERO
	return from_db(r.amount, r.currency)


def _progress(req, got):
	"""Each refund is on record, and committed outside tests, before the next one is made; the
	booking and the request are then locked and read again as they are now."""
	req.refunded_amount = from_db(req.refunded_amount, req.currency) + got
	req.save(ignore_permissions=True)
	_commit()
	return _lock(req.name)


# ─── scheduler ───────────────────────────────────────────────────────────


def expire_awaiting() -> dict:
	"""Every 15 minutes: a change whose payment did not arrive before its deadline expires (a
	payment arriving later is refunded); refunds that were queued but did not run are retried.
	Each request is its own unit of work."""
	now = now_datetime()
	expired = settled = 0
	for name in frappe.get_all(DT, filters={"status": "Awaiting Payment", "expires_at": ("<", now)}, pluck="name"):
		if _step(lambda n=name: _expire(n, now), f"TEX guest change {name} expiry"):
			expired += 1
	cutoff = add_to_date(now, minutes=-SETTLE_RETRY_MINUTES)
	for name in frappe.get_all(DT, filters={"settle_pending": 1, "modified": ("<", cutoff)}, pluck="name"):
		if _step(lambda n=name: settle(n), f"TEX guest change {name} refund retry"):
			settled += 1
	return {"expired": expired, "settled": settled}


def _expire(name: str, now) -> bool:
	req = _lock(name)
	if req.status != "Awaiting Payment" or not req.expires_at or get_datetime(req.expires_at) >= now:
		return False
	req.status = "Expired"
	req.error = "no payment arrived before the deadline"
	# a payment recorded without applying the change (its hook failed) is given back
	req.settle_pending = 1 if any(True for _t in _charges_of(req)) else 0
	req.save(ignore_permissions=True)
	audit("guest_change.expired", reference_doctype=DT, reference_name=name, property=req.property,
	      new=_audit_row(req), source="Scheduler")
	if req.settle_pending:
		settle(name)
	return True


# ─── the guest's view ────────────────────────────────────────────────────


def open_request(res):
	"""The guest's change of reservation ``res`` still waiting for a payment or for the hotel,
	if it can still be made: none once its payment deadline passed (the scheduler marks it
	expired) or the reservation changed since (it could no longer apply)."""
	name = frappe.db.get_value(DT, {"reservation": res.name, "status": ("in", OPEN)}, "name",
	                           order_by="creation desc")
	if not name:
		return None
	req = frappe.get_doc(DT, name)
	if req.status == "Awaiting Payment" and req.expires_at and get_datetime(req.expires_at) < now_datetime():
		return None
	if json.loads(req.proposal or "{}").get("modified") != str(res.modified):
		return None
	return req


def guest_view(req) -> dict:
	"""A waiting change as the guest sees it: what they asked for and what it waits for
	(``pay_now``: their payment of ``amount``; ``staff_approval`` / ``staff``: the hotel)."""
	ccy = req.currency
	p = json.loads(req.proposal or "{}")
	waiting = req.status == "Awaiting Payment"
	kind = st.PAY_NOW if waiting else (st.STAFF_APPROVAL if from_db(req.difference, ccy) < 0 else st.STAFF)
	return {"request": req.name, "status": GUEST_STATUS.get(req.status, req.status.lower()), "kind": kind,
	        "changes": p.get("changes") or {}, "difference": to_str(from_db(req.difference, ccy)),
	        "amount": to_str(from_db(req.collect_amount, ccy)) if waiting else None,
	        "currency": ccy, "expires_at": str(req.expires_at) if waiting else None}


# ─── staff ───────────────────────────────────────────────────────────────


STAFF_FIELDS = ("name", "property", "booking", "reservation", "status", "currency", "old_total", "new_total",
                "difference", "collect_amount", "payment_transaction", "attempt", "settlement", "settlement_amount",
                "refunded_amount", "settle_pending", "revision", "error", "note", "expires_at", "resolved_by",
                "resolved_at", "resolution", "creation", "modified")
MONEY_FIELDS = ("old_total", "new_total", "difference", "collect_amount", "settlement_amount", "refunded_amount")


def staff_row(row) -> dict:
	out = {f: row.get(f) for f in STAFF_FIELDS}
	for f in MONEY_FIELDS:
		out[f] = to_str(from_db(out[f], row.get("currency") or "EUR"))
	for f in ("expires_at", "resolved_at", "creation", "modified"):
		out[f] = str(out[f]) if out[f] else None
	out["settle_pending"] = bool(out["settle_pending"])
	# waiting for staff: a request to decide, or money left for staff to refund
	out["needs_staff"] = row.get("status") == "Requested" or (row.get("settlement") == "Staff"
	                                                           and not row.get("resolved_at"))
	out["changes"] = json.loads(row.get("proposal") or "{}").get("changes") or {}
	return out


def staff_list(properties: list[str], *, status: str | None = None, reservation: str | None = None,
               booking: str | None = None, needs_staff: bool = False, limit: int = 50, start: int = 0) -> list[dict]:
	if not properties:
		return []
	filters = [[DT, "property", "in", properties]]
	if status:
		filters.append([DT, "status", "=", status])
	if reservation:
		filters.append([DT, "reservation", "=", reservation])
	if booking:
		filters.append([DT, "booking", "=", booking])
	or_filters = None
	if needs_staff:
		or_filters = [[DT, "status", "=", "Requested"], [DT, "settlement", "=", "Staff"]]
		filters.append([DT, "resolved_at", "is", "not set"])
	rows = frappe.get_all(DT, filters=filters, or_filters=or_filters, fields=[*STAFF_FIELDS, "proposal"],
	                      order_by="creation desc", limit_start=start, limit=limit)
	out = []
	for r in rows:
		row = staff_row(r)
		if r.status == "Requested" and from_db(r.difference, r.currency) < 0:
			# what approving it would leave paid above the new total: staff choose to refund it or
			# keep it as credit (``resolve`` decides it again as the booking is then)
			b = frappe.db.get_value("TEX Booking", r.booking, ["paid_amount", "total_amount", "currency"],
			                        as_dict=True)
			ccy = b.currency if b else r.currency
			over = max(ZERO, from_db(b.paid_amount, ccy) - from_db(b.total_amount, ccy)
			           - from_db(r.difference, ccy)) if b else ZERO
			row["overpaid_after"] = to_str(quantize(over, ccy))
		out.append(row)
	return out


RESOLVE_ACTIONS = ("approve", "reject", "close")


def resolve(request: str, action: str, *, settlement: str | None = None, reason: str | None = None) -> dict:
	"""Staff decide a guest's request, or close one whose money they settled themselves.

	- ``approve`` (Requested; reservation.modify): the guest's change is applied at the price
	  they were shown (as of its pricing time; the reservation must not have changed since). A
	  lower price with money paid above the new total is refunded (``settlement="Refund"``,
	  also needs payment.refund) or kept as credit (``"Credit on booking"``); anything else
	  changes the balance;
	- ``reject`` (Requested; reservation.modify): nothing changes;
	- ``close`` (payment.refund): money left to staff (settlement "Staff") was settled outside
	  TEX."""
	if action not in RESOLVE_ACTIONS:
		frappe.throw(_("Unknown action {0}.").format(action))
	prop = frappe.db.get_value(DT, request, "property")
	if not prop:
		frappe.throw(_("Guest change request not found."), frappe.DoesNotExistError)
	scope.require("payment.refund" if action == "close" else "reservation.modify", prop)
	if settlement == "Refund":
		scope.require("payment.refund", prop)
	if not (reason or "").strip():
		frappe.throw(_("A reason is required."))
	req = _lock(request)
	queue = False
	if action in ("approve", "reject") and req.status != "Requested":
		frappe.throw(_("Only a request waiting for the hotel can be approved or rejected ({0}).").format(req.status))
	if action == "approve":
		queue = _approve(req, settlement, reason)
	elif action == "reject":
		if settlement:
			frappe.throw(_("A rejected request settles nothing."))
		req.status = "Rejected"
	elif req.resolved_at or req.settlement != "Staff" or req.settle_pending:
		frappe.throw(_("Only money left to staff can be closed."))
	req.resolved_by = frappe.session.user
	req.resolved_at = now_datetime()
	req.resolution = reason.strip()[:500]
	req.save(ignore_permissions=True)
	_acknowledge(req, f"{action} {req.name}: {reason.strip()[:200]}")
	audit("guest_change.resolve", reference_doctype=DT, reference_name=req.name, property=req.property,
	      new={"action": action, **_audit_row(req)}, reason=reason)
	if queue:
		queue_settle(req.name)
		req.reload()                      # as refunded so far (tests run the refund job inline)
	return staff_row(req.as_dict())


def _approve(req, settlement: str | None, reason: str) -> bool:
	b = frappe.get_doc("TEX Booking", req.booking)
	ccy = b.currency
	lower = from_db(req.difference, ccy) < 0
	# decided before anything is applied: what was paid above the new total, if anything
	over = max(ZERO, from_db(b.paid_amount, ccy) - (from_db(b.total_amount, ccy) + from_db(req.difference, ccy)))
	if lower and over > 0 and settlement not in ("Refund", "Credit on booking"):
		frappe.throw(_("{0} {1} was paid above the new total: choose to refund it or keep it as credit.").format(
			to_str(quantize(over, ccy)), ccy))
	if settlement and not (lower and over > 0):
		frappe.throw(_("Nothing was paid above the new total: there is nothing to refund or keep as credit."))
	out = modification.apply(None, reason=f"Guest request {req.name} approved: {reason.strip()[:300]}",
	                         source="Guest", _proposal=json.loads(req.proposal))
	req.status = "Approved"
	req.revision = out["revision"]
	b.reload()
	over = max(ZERO, from_db(b.paid_amount, ccy) - from_db(b.total_amount, ccy))
	frappe.db.set_value("TEX Booking", req.booking, "amount_due_now", booking_svc.required_now(req.booking),
	                    update_modified=False)
	if settlement and over > 0:
		req.settlement = settlement
		req.settlement_amount = over
		if settlement == "Refund":
			req.settle_pending = 1
			return True
		audit("guest_change.credit", reference_doctype="TEX Booking", reference_name=req.booking,
		      property=req.property, new={"request": req.name, "credit": to_str(quantize(over, ccy)), "currency": ccy})
		return False
	req.settlement = LABEL[st.BALANCE]
	req.settlement_amount = abs(from_db(req.difference, ccy))
	return False


def _acknowledge(req, note: str) -> None:
	"""Staff resolved it: the reservation (and the booking, when nothing else waits) is no
	longer flagged for a guest change, as ``crs.acknowledge_guest_change`` does."""
	current = frappe.db.get_value("Reservation", req.reservation, "tex_guest_change_note") or ""
	frappe.db.set_value("Reservation", req.reservation, {
		"tex_guest_change_pending": 0,
		"tex_guest_change_note": (current + f"\n[{frappe.session.user}] {note}")[-1000:]}, update_modified=False)
	if not frappe.db.exists("Reservation", {"tex_booking": req.booking, "tex_guest_change_pending": 1}):
		frappe.db.set_value("TEX Booking", req.booking, "guest_change_pending", 0, update_modified=False)
