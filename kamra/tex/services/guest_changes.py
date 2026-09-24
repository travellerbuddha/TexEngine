"""A guest's own change to a booking and its money (G-45, ADR-044 and its review follow-up).

The manage page proposes a change (``modification.propose``); ``preview`` says how it would be
settled (``payments.settlement``); ``submit`` records the guest's acceptance as a TEX Guest
Change Request and then:

- a higher price that the booking's payment terms need paid now: the request waits for that
  payment ("Awaiting Payment") and the reservation is untouched. When the gateway confirms the
  charge, the payment callback only records it and queues ``apply_paid``, a job that applies
  the change server-side, re-priced as of the proposal's sale time. A change that can no
  longer apply is "Failed" and its payment refunded;
- a higher price with nothing due now (pay at hotel, a deposit already covering it, a credit),
  an unchanged price, or a lower price under the "Refund automatically" / "Keep as credit"
  policies: applied now; a refund of the overpayment runs in a job queued after the commit;
- a lower price under "Staff approval", on a non-refundable rate or while cancelling would
  cost a penalty, or money due now without a card method: "Requested", for staff
  (``resolve``).

A request is keyed by its proposal: submitting the same proposal twice is one request. Refunds
are keyed per request and charge, on record before the gateway is asked (with the request's
``refund_in_flight``), and made by a job queued with the commit that decided them, one run per
request at a time (``settle_claim``), so neither a retry, a second run, a gateway timeout nor a
worker dying mid-refund ever refunds twice: a refund of the request still Pending stops its
runs until it is answered, and staff verify it at the gateway once it is old. Money TEX cannot
give back automatically (or whose refund the gateway never confirmed) waits for staff
(``staff_open``); once staff record what the gateway did, TEX refunds what the change still
owes. Nothing here raises into the payment callback.

Locks: the booking first, then the request, the reservation and the inventory days. A guest's
submit, the ``apply_paid`` and refund jobs, staff decisions, staff modifications and
cancellations, and the channel's modifications and cancellations all take them in that order;
the payment callback holds the payment row, then the booking, and no more.
"""

from __future__ import annotations

import base64
import hashlib
import json
import random
import time

import frappe
from frappe import _
from frappe.utils import add_to_date, get_datetime, getdate, now_datetime

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
# a charge the gateway confirmed this long ago whose change is still waiting: the apply job did
# not run (or could not finish), the scheduler applies it
APPLY_RETRY_MINUTES = 2
APPLY_ATTEMPTS = 3
# a refund run holds the request's refunds this long (renewed with each refund): a second run
# meanwhile does nothing, and a run that died is taken over once it lapsed (G-45 re-review F1)
SETTLE_LEASE_MINUTES = 10
# how far back the scheduler looks for a payment of a change no job looked at (re-review F7)
SWEEP_DAYS = 30
REFUND_BY_STAFF = "Refund by staff"
VERIFY_REFUND = "Verify refund at gateway"
# what staff did with money left to them, said when they close it (G-93)
REFUNDED_OUTSIDE = "Refunded outside TEX"
KEPT_ON_BOOKING = "Kept on the booking"
STAFF_MONEY = (REFUNDED_OUTSIDE, KEPT_ON_BOOKING)
# MariaDB / client errors that say "try again", never "this change cannot be made": a lock wait
# timeout, a deadlock, a statement timeout, a connection refused, gone away or lost (re-review F6)
TRANSIENT_CODES = (1205, 1213, 1969, 2003, 2006, 2013)


class PaymentPending(frappe.ValidationError):
	"""The booking's own payment is not complete: it cannot be changed yet."""


class RefundPending(frappe.ValidationError):
	"""A refund of an earlier change of the booking is still being made: no new change until it
	is (review of ADR-044: it must not be counted as money the booking still holds)."""


class ChangeApplying(frappe.ValidationError):
	"""A change of the booking was paid and is being applied: no new change until it is (the
	payment is not money the booking may use for another change, re-review F4)."""


class ChangeRefused(frappe.ValidationError):
	"""The room can no longer be changed by the guest (arrived, or not confirmed)."""


class CurrencyChanged(frappe.ValidationError):
	"""The change would be priced in another currency than the booking's."""


def _commit() -> None:
	"""A job's step is its own unit of work in production; tests keep one transaction."""
	if not frappe.flags.in_test:
		frappe.db.commit()  # nosemgrep: frappe-manual-commit -- background worker unit-of-work boundary


def _undo(savepoint: str) -> None:
	"""Undo a failed step: to its savepoint in tests (one transaction), else the whole
	uncommitted work, which in a job is only that step (the steps before it are committed, and a
	refund is committed as Pending before its gateway call, so it is never lost)."""
	if frappe.flags.in_test:
		frappe.db.rollback(save_point=savepoint)
	else:
		frappe.db.rollback()


def _transient(e: BaseException) -> bool:
	"""A deadlock, a lock wait or statement timeout, a lost connection: the work is tried again
	later, never judged as the change failing (G-45 re-review F6)."""
	if isinstance(e, frappe.QueryDeadlockError | frappe.QueryTimeoutError):
		return True
	import pymysql

	if isinstance(e, pymysql.err.InterfaceError):
		return True
	return isinstance(e, pymysql.err.OperationalError) and bool(e.args) and e.args[0] in TRANSIENT_CODES


def _release_locks() -> None:
	"""The new request (and the ones it replaced) are on record, and the booking, reservation
	and request rows released, before the gateway is asked for a checkout, which can take many
	seconds (review of ADR-044). A retry of the request finds the request and continues it."""
	if not frappe.flags.in_test:
		frappe.db.commit()  # nosemgrep: frappe-manual-commit -- no row lock is held through a gateway call


def _lock(name: str, booking: str | None = None):
	"""The request's booking, then the request, read as they are now (locking reads). Given its
	booking, nothing is read before the booking's lock, so the rest of the transaction reads as
	of after it (a REPEATABLE READ snapshot starts at the first plain read): what a run holding
	the booking before committed is seen."""
	booking = booking or frappe.db.get_value(DT, name, "booking")
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
		_undo("tex_gcr_step")
		log_exception(title)
		return None
	_commit()
	return out


def _digest(token: str) -> str:
	"""The proposal a token carries, decoded: its signed body and signature. Base64 decoding is
	lenient (characters outside the alphabet are skipped), so the raw string is not the key: the
	same proposal with junk appended is the same request (review of ADR-044)."""
	body_b64, _sep, mac_b64 = (token or "").partition(".")
	pad = lambda v: v + "=" * (-len(v) % 4)  # noqa: E731
	body = base64.urlsafe_b64decode(pad(body_b64))
	mac = base64.urlsafe_b64decode(pad(mac_b64))
	return hashlib.sha256(b"tex-guest-change:" + body + b"." + mac).hexdigest()


def _legacy_hash(token: str) -> str:
	"""The key of requests made before the review (the raw token): still found on a replay."""
	return hashlib.sha256(("tex-guest-change:" + token).encode()).hexdigest()


def _keys(token: str) -> list[str]:
	return [_digest(token), _legacy_hash(token)]


def _money(v, ccy: str) -> str:
	return to_str(quantize(D(v), ccy))


# ─── guards ──────────────────────────────────────────────────────────────


def guard(b) -> None:
	"""A booking waiting for its own payment (or held) is paid first, then changed; a booking
	whose refund of an earlier change is still being made waits for it, and so does one whose
	paid change is still being applied."""
	if b.status in ("Pending Payment", "Held"):
		frappe.throw(_("Please complete the payment of your booking before changing it."), PaymentPending,
		             title=_("Payment pending"))
	if refund_pending(b.name):
		frappe.throw(_("A refund of your earlier change is being processed. Please try again in a few minutes."),
		             RefundPending, title=_("Refund in progress"))
	if change_applying(b.name):
		frappe.throw(_("Your payment for an earlier change is being applied. Please try again in a few minutes."),
		             ChangeApplying, title=_("Change in progress"))


def refund_pending(booking: str) -> bool:
	return bool(frappe.db.exists(DT, {"booking": booking, "settle_pending": 1}))


def change_applying(booking: str) -> bool:
	"""A change of this booking is paid (the gateway confirmed it) and not applied yet: the
	``apply_paid`` job, or the scheduler after it, applies it (re-review F4)."""
	return any(any(True for _t in _charges_of(r)) for r in frappe.get_all(
		DT, filters={"booking": booking, "status": "Awaiting Payment", "attempt": (">", 0)},
		fields=["name", "property", "attempt"]))


def room_changeable(res) -> bool:
	"""Guests change a room only before they arrive: confirmed, arriving today or later."""
	return res.status == "Confirmed" and getdate(res.check_in_date) >= getdate(now_datetime())


def guard_room(res) -> None:
	if not room_changeable(res):
		frappe.throw(_("This room can no longer be changed online. Please contact the hotel."), ChangeRefused)


def lower_policy(property: str) -> str:
	return frappe.db.get_value("Property", property, "tex_lower_price_refund") or st.LOWER_STAFF


def card_account(b) -> str | None:
	"""The card gateway account the booking's hotel offers for its market, currency, channel."""
	from kamra.tex.payments import service as pay

	for m in pay.payment_methods(b.property, market=b.market, currency=b.currency, channel=b.sales_channel):
		if m["method"] == "Card" and m["provider_account"]:
			return m["provider_account"]
	return None


def penalty_applies(res) -> bool:
	"""The rate is non-refundable, or cancelling the room now would cost a fee: a lower price
	of it is never refunded or credited without the hotel (review of ADR-044, H1), and its
	arrival is never moved later without the hotel either: moved out of the window, the stay
	could then be shortened or cancelled without the fee (re-review F5)."""
	penalty, _basis = booking_svc.cancellation_penalty(res)
	return penalty > 0


def _arrival_moved_later(res, prop: dict) -> bool:
	new = ((prop.get("proposed") or {}).get("request") or {}).get("check_in")
	return bool(new) and getdate(new) > getdate(res.check_in_date)


# ─── money set aside ─────────────────────────────────────────────────────


def _returned(req) -> set[str]:
	"""Payments of this request already given back, or left to staff to give back."""
	return {t for t in (req.returned_charges or "").split() if t}


def _mark_returned(req, txn: str) -> None:
	req.returned_charges = "\n".join(sorted(_returned(req) | {txn}))


def _unreturned(req) -> list[str]:
	"""The succeeded payments of this request that did not pay for its change and were not
	given back (or left to staff) yet."""
	done = _returned(req)
	return [t for t in _charges_of(req)
	        if t not in done and not (req.status in DONE and t == req.payment_transaction)]


def _in_flight(r):
	"""The refund this request asked the gateway for and has no answer to (Pending): its money
	may be back on the card already. → the refund row, or None."""
	for name in dict.fromkeys(n for n in (r.refund_in_flight, r.unknown_refund) if n):
		row = frappe.db.get_value(TXN, name, ["name", "txn_type", "status", "amount", "currency", "error_code",
		                                      "creation"], as_dict=True)
		if row and row.txn_type == "Refund" and row.status == "Pending":
			return row
	return None


def _to_verify(r) -> D:
	"""Of the money left to staff, the refund they verify at the gateway (not one to make)."""
	row = _in_flight(r)
	return from_db(row.amount, row.currency) if row and row.name == r.unknown_refund else ZERO


def _staff_due(r) -> D:
	"""Money left to staff that they have not settled yet, less a refund they verify."""
	ccy = r.currency
	return max(ZERO, from_db(r.staff_amount, ccy) - from_db(r.staff_settled, ccy) - _to_verify(r))


def _reserved(booking: str, except_request: str | None = None) -> dict[str, D]:
	"""Payments of this booking's changes that are not the booking's to use: a payment for a
	change still to be applied (the change uses it, re-review F4), a payment to give back (a
	change that did not apply, a second payment of one that did): {charge: what the booking
	holds of it, less refunds of it in flight}. No refund plan takes them and no change uses
	them (review of ADR-044, H3)."""
	from kamra.tex.payments import service as pay

	out: dict[str, D] = {}
	for r in frappe.get_all(DT, filters={"booking": booking, "attempt": (">", 0), "name": ("!=", except_request or "")},
	                        fields=["name", "property", "attempt", "status", "payment_transaction", "returned_charges"]):
		for txn in _unreturned(r):
			held = pay.booking_nets(txn).get(booking, ZERO) - pay.in_flight_of(txn)
			if held > 0:
				out[txn] = held
	return out


def earmarked(booking: str, except_request: str | None = None) -> D:
	"""Money the booking holds that is set aside: refunds the gateway was asked for and has not
	answered (the money may be back on the card), refunds still to be made, money waiting for
	staff, payments to give back and payments of a change still to be applied. It is not the
	guest's credit and pays for no change (review of ADR-044, H3; re-review F1, F4)."""
	from kamra.tex.payments import service as pay

	total = sum(_reserved(booking, except_request).values(), ZERO)
	counted: set[str] = set()
	for r in frappe.get_all(DT, filters={"booking": booking, "name": ("!=", except_request or "")},
	                        or_filters={"settle_pending": 1, "staff_open": 1},
	                        fields=["name", "status", "currency", "settlement", "settle_pending", "settlement_amount",
	                                "refunded_amount", "staff_open", "staff_amount", "staff_settled", "unknown_refund",
	                                "refund_in_flight"]):
		ccy = r.currency
		row = _in_flight(r)
		gone = from_db(row.amount, row.currency) if row else ZERO
		verify = gone if row and row.name == r.unknown_refund else ZERO
		if row:
			counted.add(row.name)
			total += gone
		if r.staff_open:
			total += max(ZERO, from_db(r.staff_amount, ccy) - from_db(r.staff_settled, ccy) - verify)
		if r.settle_pending and r.status in DONE and r.settlement == "Refund":
			total += max(ZERO, from_db(r.settlement_amount, ccy) - from_db(r.refunded_amount, ccy)
			             - from_db(r.staff_amount, ccy) - (gone - verify))
	# refunds staff started from the payment screen, not answered yet (F1)
	for row in pay.pending_refunds(booking):
		if row.name not in counted:
			total += from_db(row.amount, row.currency)
	return total


def usable_paid(b, except_request: str | None = None) -> D:
	"""What the booking holds and may use for a change: paid, less money set aside for refunds."""
	return from_db(b.paid_amount, b.currency) - earmarked(b.name, except_request)


def guest_credit(booking: str) -> tuple[D, D]:
	"""→ (credit the guest may use, money set aside for a refund) of a booking."""
	b = frappe.db.get_value("TEX Booking", booking, ["name", "paid_amount", "total_amount", "currency"], as_dict=True)
	ccy = b.currency
	over = max(ZERO, from_db(b.paid_amount, ccy) - from_db(b.total_amount, ccy))
	held = min(earmarked(booking), over)
	return quantize(over - held, ccy), quantize(held, ccy)


def refundable_now(booking: str, amount, *, except_request: str | None = None,
                   failed: set[str] | frozenset = frozenset()) -> tuple[list[tuple[str, D]], D]:
	"""How ``amount`` would be refunded now: from the charges holding the booking's money that
	TEX may refund, newest first, leaving out charges other requests must give back → (plan,
	what no charge can refund)."""
	from kamra.tex.payments import service as pay

	reserved = _reserved(booking, except_request)
	charges = [st.Charge(c["transaction"], c["available"], c["supported"] and c["transaction"] not in failed,
	                     c["at"]) for c in pay.booking_charges(booking) if c["transaction"] not in reserved]
	return st.plan_refunds(max(ZERO, D(amount)), charges)


# ─── preview ─────────────────────────────────────────────────────────────


def preview(b, res, prop: dict) -> st.Settlement | None:
	"""How ``prop`` (a ``modification.propose`` result for ``res``) would be settled for
	booking ``b``; None when it cannot be (not priced, or priced in another currency)."""
	return _preview(b, res, prop)[0]


def _preview(b, res, prop: dict) -> tuple[st.Settlement | None, bool]:
	"""→ (settlement, whether the rate's cancellation terms send it to the hotel)."""
	ccy = b.currency
	new_room = (prop.get("proposed") or {}).get("totals", {}).get("total")
	if prop.get("currency_changed") or prop.get("difference") is None or not new_room \
			or prop["proposed"].get("currency") != ccy or (res.tex_currency or ccy) != ccy:
		return None, False
	old_total = from_db(b.total_amount, ccy)
	new_total = old_total - D(prop["old"]["total"]) + D(new_room)
	required = booking_svc.required_now(b, {res.name: prop["proposed"]})
	paid = usable_paid(b)
	policy = lower_policy(b.property)
	lower, later = new_total < old_total, _arrival_moved_later(res, prop)
	# the rate's terms are judged on a lower price (H1) and on an arrival moved later (F5): a stay
	# moved out of its penalty window could then be shortened or cancelled without the fee
	fee = (lower or later) and penalty_applies(res)
	auto = None
	over = max(ZERO, paid - new_total)
	if lower and policy == st.LOWER_REFUND and over > 0 and not fee:
		# only what a card can take back is promised as a card refund; the rest the hotel refunds
		_plan, rest = refundable_now(b.name, over)
		auto = over - rest
	s = st.settle(old_total, new_total, paid, required, pay_at_hotel=b.payment_method == "Pay at Hotel",
	              lower_policy=policy, card_available=bool(card_account(b)), penalty_applies=lower and fee,
	              auto_refundable=auto, terms_review=later and fee)
	return s, fee


def settlement_dict(s: st.Settlement | None, ccy: str) -> dict | None:
	"""The guest API's view of a settlement (amounts as strings, never floats)."""
	if s is None:
		return None
	return {"kind": s.kind, "amount": _money(s.amount, ccy), "collect": _money(s.collect, ccy),
	        "refund": _money(s.refund, ccy), "hotel_refund": _money(s.hotel_refund, ccy),
	        "credit": _money(s.credit, ccy), "balance_after": _money(s.balance_after, ccy), "currency": ccy}


# ─── submit ──────────────────────────────────────────────────────────────


def submit(b, proposal_token: str, *, note: str | None = None, return_url: str | None = None) -> dict:
	"""The guest accepts a proposal (the caller checked the manage token, the reservation and
	self-service). Idempotent by proposal: a second submit answers what the first one did."""
	p = quoting.verify(proposal_token, kind="proposal", allow_expired=True)
	keys = _keys(proposal_token)
	existing = frappe.db.get_value(DT, {"proposal_hash": ("in", keys)}, "name")
	if existing:
		return _replay(existing, p, return_url)
	# only a proposal made on the manage page: never a staff proposal (another basis, another
	# user's entitlement) brought to the guest path (G-51)
	modification.require_proposer(p, guest=True)
	quoting.require_fresh(p)
	# one change of a booking at a time, read as it is now: the booking, then the reservation
	b = frappe.get_doc("TEX Booking", b.name, for_update=True)
	guard(b)
	res = frappe.get_doc("Reservation", p["reservation"], for_update=True)
	if res.tex_booking != b.name:
		frappe.throw(_("Invalid reservation."), frappe.PermissionError)
	guard_room(res)
	# the reservation's requests as they are now (a locking read of existing rows: another tab
	# may have submitted this proposal while this one waited for the booking)
	rows = frappe.db.sql(f"SELECT name, proposal_hash, status FROM `tab{DT}` WHERE reservation=%s FOR UPDATE",
	                     (res.name,), as_dict=True)  # nosemgrep -- constant doctype
	mine = next((r.name for r in rows if r.proposal_hash in keys), None)
	if mine:
		return _replay(mine, p, return_url, concurrent=True)
	if p.get("currency") != (res.tex_currency or b.currency) or (res.tex_currency or b.currency) != b.currency:
		frappe.throw(_("This change cannot be priced in the currency of your booking. Please contact the hotel."),
		             CurrencyChanged)
	prop = _derive(res, p)
	s, fee = _preview(b, res, prop)
	if s is None:
		frappe.throw(_("This change cannot be priced in the currency of your booking. Please contact the hotel."),
		             CurrencyChanged)
	req = _insert(b, res, p, keys[0], s, note, terms=fee and s.kind == st.STAFF_APPROVAL)
	if req is None:
		# the same proposal is being submitted right now (another tab): its answer is on the way
		return {"status": "processing", "request": None,
		        "message": _("Your change is being processed. Please reload the page in a moment.")}
	_supersede([r.name for r in rows if r.status in OPEN], req.name)
	if s.kind == st.PAY_NOW:
		audit("guest_change.request", reference_doctype=DT, reference_name=req.name, property=b.property,
		      new=_audit_row(req, s))
		_release_locks()
		return _start_payment(req, b, return_url, new_attempt=True)
	if s.kind in (st.STAFF_APPROVAL, st.STAFF):
		ccy = b.currency
		why = (_("inside the rate's cancellation terms, the hotel approves it") if req.penalty_terms
		       else _("lower price, the hotel approves it") if s.kind == st.STAFF_APPROVAL
		       else _("{0} {1} is due now and no card payment is set up").format(_money(s.collect, ccy), ccy))
		_flag(res.name, b.name, f"Guest requests a change ({_money(s.difference, ccy)} {ccy}; {why}); "
		                        f"request {req.name} {json.dumps(_note_changes(res, p['changes']), default=str)} "
		                        f"{note or ''}")
		audit("guest_change.request", reference_doctype=DT, reference_name=req.name, property=b.property,
		      new=_audit_row(req, s))
		return _requested(req, s)
	return _apply_now(req, proposal_token, s, note)


def _derive(res, p: dict) -> dict:
	"""The proposal priced again now, before anything is charged or applied: still sellable, on
	an unchanged reservation, at the price the guest accepted (the checks ``apply`` repeats)."""
	guard_room(res)
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


def _insert(b, res, p: dict, digest: str, s: st.Settlement, note: str | None, *, terms: bool = False):
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
		"penalty_terms": 1 if terms else 0,
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
		ccy = req.currency
		if s.refund > 0:
			req.settle_pending = 1
		if s.hotel_refund > 0:
			# paid in a way TEX does not refund (cash, transfer, a gateway without refunds): staff
			_give_to_staff(req, s.hotel_refund, REFUND_BY_STAFF,
			               f"{_money(s.hotel_refund, ccy)} {ccy} was not paid by a card TEX can refund")
	req.save(ignore_permissions=True)
	audit("guest_change.applied", reference_doctype=DT, reference_name=req.name, property=req.property,
	      new=_audit_row(req, s))
	if s.kind == st.CREDIT:
		audit("guest_change.credit", reference_doctype="TEX Booking", reference_name=req.booking,
		      property=req.property, new={"request": req.name, "credit": to_str(quantize(s.credit, req.currency)),
		                                  "currency": req.currency})
	if req.settle_pending:
		queue_settle(req.name)
	req.reload()                          # as settled so far (tests run the refund job inline)
	return _applied(req, replay=False)


def _after_apply(req, s: st.Settlement | None) -> None:
	"""Staff hear of every guest change; the deposit due follows the new price."""
	ccy = req.currency
	what = {st.CREDIT: f"{_money(s.credit, ccy)} {ccy} kept as credit on the booking",
	        st.REFUND: f"{_money(s.refund, ccy)} {ccy} being refunded to the card"
	                   + (f", {_money(s.hotel_refund, ccy)} {ccy} for the hotel to refund" if s.hotel_refund else ""),
	        st.PAY_NOW: f"{_money(s.collect, ccy)} {ccy} paid online",
	        st.PAY_AT_HOTEL: f"{_money(s.amount, ccy)} {ccy} more to pay at the hotel"}.get(s.kind, "") if s else ""
	_flag(req.reservation, req.booking, f"Guest changed online ({req.name}{'; ' + what if what else ''})")
	frappe.db.set_value("TEX Booking", req.booking, "amount_due_now", booking_svc.required_now(req.booking),
	                    update_modified=False)


def _note_changes(res, changes: dict) -> dict:
	"""The requested changes for a staff note: children as ages on arrival, never a date of
	birth (the reservation keeps it where the price needs it; G-52 review)."""
	out = dict(changes or {})
	if out.get("children"):
		arrival = getdate(out.get("check_in") or res.check_in_date)
		try:
			out["children"] = quoting.Party.parse({"adults": 1, "children": list(out["children"])},
			                                      arrival=arrival).summary()["children"]
		except Exception:
			out["children"] = len(out["children"])
	return out


def _flag(reservation: str, booking: str, note: str) -> None:
	# never bumps the reservation's modified: a proposal made before stays valid for staff
	frappe.db.set_value("Reservation", reservation, {"tex_guest_change_pending": 1,
	                                                  "tex_guest_change_note": note[:1000]}, update_modified=False)
	frappe.db.set_value("TEX Booking", booking, "guest_change_pending", 1, update_modified=False)


def _give_to_staff(req, amount, reason: str, why: str, *, unknown_refund: str | None = None) -> None:
	"""Money of this request waits for staff (``staff_open``): shown in the staff queue until
	they close it. Saved by the caller."""
	ccy = req.currency
	amount = quantize(D(amount), ccy)
	req.staff_open = 1
	req.staff_amount = from_db(req.staff_amount, ccy) + amount
	# a refund to verify outranks one to make: staff check the gateway first
	req.staff_reason = VERIFY_REFUND if VERIFY_REFUND in (reason, req.staff_reason) else reason
	if unknown_refund:
		req.unknown_refund = unknown_refund
	req.error = (f"{to_str(amount)} {ccy}: {why}. {req.error or ''}")[:500]
	_flag(req.reservation, req.booking, f"Guest change {req.name}: {to_str(amount)} {ccy} for staff ({reason})")
	audit("guest_change.refund_unknown" if reason == VERIFY_REFUND else "guest_change.refund_by_staff",
	      reference_doctype=DT, reference_name=req.name, property=req.property,
	      new={"amount": to_str(amount), "currency": ccy, "why": why, "refund": unknown_refund})


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


def _settlement_view(req) -> dict:
	"""How the request's money was settled, as the guest is told: a refund splits into what goes
	back to the card (``refund``, including one the gateway has not confirmed yet) and what the
	hotel refunds (``hotel_refund``). Done only once nothing of it is still being refunded."""
	ccy = req.currency
	kind = KIND.get(req.settlement or "", st.BALANCE)
	staff = max(ZERO, from_db(req.staff_amount, ccy) - _to_verify(req)) if kind == st.REFUND else ZERO
	amount = from_db(req.settlement_amount, ccy)
	card = max(ZERO, amount - staff) if kind == st.REFUND else ZERO
	refunded = from_db(req.refunded_amount, ccy)
	return {"kind": kind, "amount": to_str(amount), "refund": _money(card, ccy), "hotel_refund": _money(staff, ccy),
	        "refunded": to_str(refunded), "refund_done": bool(card > 0 and refunded >= card and not req.settle_pending),
	        "currency": ccy}


def _applied(req, *, replay: bool) -> dict:
	summary = booking_svc.booking_summary(req.booking)
	credit, due = guest_credit(req.booking)
	rev = frappe.db.get_value("TEX Reservation Revision", req.revision, ["old_amount", "new_amount", "difference",
	                                                                     "currency"], as_dict=True) or {}
	ccy = rev.get("currency") or req.currency
	return {"status": "applied", "request": req.name, "reservation": req.reservation, "revision": req.revision,
	        "old_total": to_str(from_db(rev.get("old_amount"), ccy)),
	        "new_total": to_str(from_db(rev.get("new_amount"), ccy)),
	        "difference": to_str(from_db(rev.get("difference"), ccy)), "currency": ccy,
	        "balance": summary["balance"], "paid": summary["paid"], "credit": _money(credit, req.currency),
	        "refund_due": _money(due, req.currency), "settlement": _settlement_view(req), "replay": replay}


def _requested(req, s: st.Settlement | None = None) -> dict:
	ccy = req.currency
	kind = s.kind if s else (st.STAFF_APPROVAL if D(req.difference) < 0 or req.penalty_terms else st.STAFF)
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

	No booking, reservation or request lock is held through the gateway call: the first submit
	committed the request first (``_release_locks``), and a retry holds only the charge
	(``start_payment`` re-reads a reused one with a lock). The request is locked and read again
	after the gateway answered."""
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
	req = frappe.get_doc(DT, req.name, for_update=True)              # as it is now
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
	"""Payments hook (the charge is recorded and allocated to its booking): the change it paid
	for is applied by ``apply_paid``, a job queued after the payment's commit, never inside
	the payment callback and never from the guest's browser return. The callback writes
	nothing more and holds no other lock (review of ADR-044, M1). Never raises."""
	try:
		name = request_of_charge(txn)
		if name:
			queue_apply(name, txn.name)
	except frappe.QueryDeadlockError:
		raise
	except Exception:
		frappe.clear_last_message()
		log_exception(f"TEX guest change lookup for {txn.name}")      # the scheduler applies it later


def queue_apply(request: str, transaction: str) -> None:
	frappe.enqueue("kamra.tex.services.guest_changes.apply_paid", queue="short", request=request,
	               transaction=transaction, enqueue_after_commit=True, now=bool(frappe.flags.in_test))


def apply_paid(request: str, transaction: str) -> str:
	"""A job: the change paid by ``transaction`` is applied (or, if it can no longer apply,
	failed and its payment refunded; a payment for a request no longer waiting is refunded). Its
	own unit of work; a deadlock, a lock wait timeout or a lost connection is tried again a few
	times and then left to the scheduler, which applies a change left waiting (re-review F6):
	only an error of the change itself fails it. Never raises. → "done" or "retry"."""
	for attempt in range(1, APPLY_ATTEMPTS + 1):
		frappe.db.savepoint("tex_gcr_paid")
		try:
			queue = _paid(request, transaction)
		except Exception as e:
			transient = _transient(e)
			try:
				_undo("tex_gcr_paid")
			except Exception:
				if not transient:
					raise
				log_exception(f"TEX guest change {request} after payment {transaction}: connection lost")
				return "retry"                            # a new job (the scheduler) tries with a new connection
			if transient:
				if frappe.flags.in_test or attempt == APPLY_ATTEMPTS:
					log_exception(f"TEX guest change {request} after payment {transaction}: try again later")
					return "retry"
				time.sleep(random.uniform(0.05, 0.2) * attempt)
				continue
			frappe.clear_last_message()
			log_exception(f"TEX guest change {request} after payment {transaction}")
			try:
				queue = _fail_safely(request, transaction, str(e))
			except Exception:
				# only a lock wait, a deadlock or a lost connection comes out of it: the change stays
				# waiting and the scheduler tries again; its sweep goes on (third review)
				try:
					_undo("tex_gcr_paid")
				except Exception:
					pass
				log_exception(f"TEX guest change {request} could not be marked failed now: try again later")
				return "retry"
		if queue:
			# registered before this job's commit, so that commit sends it: a rollback later in the
			# same job (the scheduler's next request failing) can no longer drop it (re-review F7)
			queue_settle(request)
		_commit()
		return "done"
	return "retry"


def _paid(name: str, transaction: str) -> bool:
	"""→ whether money of this request is to be refunded."""
	req = _lock(name)
	txn = frappe.db.get_value(TXN, transaction, ["name", "status", "amount", "currency", "completed_at"],
	                          as_dict=True)
	if not txn or txn.status != "Succeeded":
		return False
	if req.status in DONE and req.payment_transaction == txn.name:
		return False                                      # this payment already applied it
	if req.status != "Awaiting Payment":
		if txn.name in _returned(req) or req.settle_pending:
			# given back already, or a refund run is on it (it gives back every payment of the
			# request not given back yet): the job and the scheduler may both bring this payment,
			# and a run that failed the change with it queued its refund (re-review F1)
			return False
		req.settle_pending = 1
		req.save(ignore_permissions=True)
		audit("guest_change.late_payment", reference_doctype=DT, reference_name=name, property=req.property,
		      new={"transaction": txn.name, "status": req.status, "amount": to_str(from_db(txn.amount, txn.currency))})
		return True
	frappe.db.savepoint("tex_gcr_apply")
	try:
		# the guest arrived (or the room was not confirmed) meanwhile: the change is not made
		guard_room(frappe.get_doc("Reservation", req.reservation))
		out = modification.apply(None, reason=req.note or "Guest self-service change (paid online)", source="Guest",
		                         _guest_authorized=True, _proposal=json.loads(req.proposal), _from_payment=True,
		                         _paid_at=txn.completed_at)
	except frappe.QueryDeadlockError:
		raise
	except frappe.ValidationError as e:
		frappe.db.rollback(save_point="tex_gcr_apply")
		frappe.clear_last_message()
		_fail(req, txn.name, str(e))
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


def _fail(req, transaction: str, error: str) -> None:
	req.status = "Failed"
	req.payment_transaction = transaction
	req.error = error[:500]
	req.settle_pending = 1
	req.save(ignore_permissions=True)
	audit("guest_change.failed", reference_doctype=DT, reference_name=req.name, property=req.property,
	      new={**_audit_row(req), "error": req.error})


def _fail_safely(name: str, transaction: str, error: str) -> bool:
	try:
		req = _lock(name)
		if req.status == "Awaiting Payment":
			_fail(req, transaction, error)
		else:
			req.settle_pending = 1
			req.save(ignore_permissions=True)
		return True
	except Exception as e:
		if _transient(e):
			raise
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

	- an applied change under the refund policy: the overpayment, as far as it is still over
	  now (``paid − total``, less money set aside: a later change or a refund staff made by hand
	  may have used it), from the charges holding the booking's money that other requests do not
	  have to give back (``settlement.plan_refunds``);
	- a paid change that did not apply, or a payment arriving for a request that no longer
	  waited: that payment, back to the card (what the booking still holds of it).

	One run per request at a time (``settle_claim``, a lease committed as soon as it is taken
	and renewed before each refund): a second run meanwhile does nothing. Each refund is keyed by
	the request, the charge and the step, committed as Pending (named in ``refund_in_flight``
	and ``refund_rows``) before the gateway is asked, and its outcome committed before the next
	one. What the request refunded is counted from the refunds it made, never from a counter a
	run increments. A refund of the request still Pending stops the run: fresh, a later run looks
	again; unanswered or old (the run asking it died), staff verify it at the gateway ("Verify
	refund at gateway") and the rest waits for them, never planned around it (re-review F1, F3).
	A gateway that says "no" moves on to the next charge. A gateway answering after an outcome
	was recorded for the refund, and saying something else, stops the refunds of the request for
	good: staff reconcile it (third review). What no charge can refund waits for staff ("Refund
	by staff")."""
	from kamra.tex.payments import service as pay

	req = _lock(request)
	ccy = req.currency
	if not req.settle_pending:
		return _settled(request, ccy)
	if _run_holds(req):
		return _settled(request, ccy, pending=True, busy=True)     # another run holds its refunds
	token = frappe.generate_hash(length=16)
	req = _hold(req, token)
	refunded = short = capped = ZERO
	waiting = False
	failed: set[str] = set()
	first = True
	while True:
		_count_refunds(req)
		row = _in_flight(req)
		if row:
			waiting = True
			if pay.stuck(row, now_datetime()) and req.unknown_refund != row.name:
				_give_to_staff(req, from_db(row.amount, row.currency), VERIFY_REFUND,
				               "the gateway did not confirm this refund: check it at the gateway before refunding "
				               "again", unknown_refund=row.name)
			break
		if req.status in DONE and req.settlement == "Refund":
			b = frappe.db.get_value("TEX Booking", req.booking, ["name", "paid_amount", "total_amount", "currency"],
			                        as_dict=True)                    # locked by _lock: as it is now
			target = max(ZERO, from_db(req.settlement_amount, ccy) - from_db(req.refunded_amount, ccy)
			             - from_db(req.staff_amount, ccy))
			still_over = max(ZERO, from_db(b.paid_amount, ccy) - from_db(b.total_amount, ccy)
			                 - earmarked(req.booking, except_request=req.name))
			left = min(target, still_over)
			if first:
				capped, first = target - left, False
			if left <= 0:
				break
			plan, rest = refundable_now(req.booking, left, except_request=req.name, failed=failed)
			if not plan:
				short = rest
				break
			txn, amount = plan[0]
			# keyed by the request, the charge and how much was refunded before: the same step
			# replays, a later step (after a commit) is a new refund
			key = f"change:{req.name}:refund:{txn}:{to_str(from_db(req.refunded_amount, ccy))}"
			result, got = _refund(req, txn, amount, key, "the guest's change lowered the price")
			if result == "conflict":
				return _settled(request, ccy, refunded)     # the request is stopped (``_conflicted``)
			req = _relock(req, token)
			if req is None:
				return _settled(request, ccy, refunded, pending=True, busy=True)
			if result == "failed":
				failed.add(txn)
			elif result == "ok":
				refunded += got
			if result != "unknown":                           # "unknown": the loop sees it in flight
				req = _step_done(req, token)
				if req is None:
					return _settled(request, ccy, refunded, pending=True, busy=True)
			continue
		if req.status == "Awaiting Payment":
			break
		todo = _unreturned(req)
		if not todo:
			break
		txn = todo[0]
		row = frappe.db.get_value(TXN, txn, ["name", "txn_type", "status", "provider_account", "amount", "currency"],
		                          as_dict=True)
		in_flight = pay.in_flight_of(txn)
		held = min(pay.booking_nets(txn).get(req.booking, ZERO),
		           from_db(row.amount, row.currency) - pay.refunded_of(txn) - in_flight)
		if held > 0 and pay.auto_refundable(row) and not in_flight:
			result, got = _refund(req, txn, held, f"change:{req.name}:return:{txn}",
			                      "payment for a guest change that was not applied")
			if result == "conflict":
				return _settled(request, ccy, refunded)     # the request is stopped (``_conflicted``)
			req = _relock(req, token)
			if req is None:
				return _settled(request, ccy, refunded, pending=True, busy=True)
			if result == "unknown":
				continue
			_mark_returned(req, txn)
			if result == "ok":
				refunded += got
				held = ZERO
		else:
			_mark_returned(req, txn)                      # given back already, or TEX cannot give it back
		if held > 0:
			short += held
			_give_to_staff(req, held, REFUND_BY_STAFF, f"no card refund TEX can make gives back {txn}: it stays "
			                                           "as credit on the booking for staff to refund")
		req = _step_done(req, token)
		if req is None:
			return _settled(request, ccy, refunded, pending=True, busy=True)
	if not waiting:
		req.settle_pending = 0
	req.settle_claim = None
	req.settle_claimed_until = None
	if capped > 0:
		audit("guest_change.refund_capped", reference_doctype=DT, reference_name=req.name, property=req.property,
		      new={"not_refunded": to_str(quantize(capped, ccy)), "currency": ccy,
		           "why": "no longer over: a later change or a refund made by staff used it"})
		req.error = (f"{to_str(quantize(capped, ccy))} {ccy} was not refunded: a later change or a refund made by "
		             f"staff used it. {req.error or ''}")[:500]
	if short > 0 and req.status in DONE and req.settlement == "Refund":
		_give_to_staff(req, short, REFUND_BY_STAFF, "no card payment TEX can refund holds it: it stays as credit "
		                                            "on the booking for staff to refund")
	req.save(ignore_permissions=True)
	_commit()
	return _settled(request, ccy, refunded, short, pending=waiting)


def _settled(request: str, ccy: str, refunded=ZERO, short=ZERO, *, pending: bool = False, busy: bool = False) -> dict:
	out = {"request": request, "refunded": to_str(quantize(refunded, ccy)),
	       "not_refunded": to_str(quantize(short, ccy)), "pending": pending}
	if busy:
		out["busy"] = True
	return out


def _run_holds(r) -> bool:
	"""A refund run holds this request's refunds now (its lease has not lapsed)."""
	return bool(r.settle_claim and r.settle_claimed_until and get_datetime(r.settle_claimed_until) > now_datetime())


def _hold(req, token: str):
	"""This run holds the request's refunds, committed at once: a refund that fails before its
	own commit (a lock wait, a refusal) rolls its work back, never the hold, so the run goes on
	to the next charge or to staff instead of stopping as if another run held them (third
	review). → the request, locked and read again."""
	until = add_to_date(now_datetime(), minutes=SETTLE_LEASE_MINUTES)
	frappe.db.set_value(DT, req.name, {"settle_claim": token, "settle_claimed_until": until}, update_modified=False)
	_commit()
	return _lock(req.name, req.booking)


def _relock(req, token: str):
	"""The booking and the request locked and read again after a commit; None when another run
	took the refunds over (this run's lease lapsed): it stops."""
	req = _lock(req.name, req.booking)
	return req if req.settle_claim == token else None


def _refunds_made(req) -> list[str]:
	return [n for n in (req.refund_rows or "").split() if n]


def _count_refunds(req) -> None:
	"""What the request refunded, counted from the refunds it made that succeeded (a refund made
	by a run that lost its hold, or recorded by staff meanwhile, is counted once and only
	once, third review). Requests without refunds on record keep their amount."""
	made = _refunds_made(req)
	if made:
		req.refunded_amount = sum((from_db(r.amount, r.currency) for r in frappe.get_all(
			TXN, filters={"name": ("in", made), "txn_type": "Refund", "status": "Succeeded"},
			fields=["amount", "currency"])), ZERO)


def _refund(req, txn: str, amount, key: str, why: str) -> tuple[str, D]:
	"""One refund → ("ok", refunded) | ("failed", 0) | ("unknown", amount) | ("conflict", amount).
	The run's lease is renewed and the request saved first (its refund is committed with it,
	before the gateway is asked, and named in ``refund_in_flight`` and ``refund_rows``). After
	the gateway answered, the booking and the request are locked again before the refund
	(``relock``: the lock order of a staff verification). Never raises but for a deadlock.
	"failed" is a definite no (the gateway refused, or it was never asked); "unknown": no answer
	yet, it may have refunded; "conflict": the gateway answered otherwise than the outcome
	recorded meanwhile: never a failure, the run stops."""
	from kamra.tex.payments import service as pay

	req.settle_claimed_until = add_to_date(now_datetime(), minutes=SETTLE_LEASE_MINUTES)
	req.save(ignore_permissions=True)

	def recorded(name):
		frappe.db.set_value(DT, req.name, {"refund_in_flight": name,
		                                   "refund_rows": "\n".join([*_refunds_made(req), name])},
		                    update_modified=False)

	frappe.db.savepoint("tex_gcr_refund")
	try:
		out = pay.refund(txn, amount=amount, reason=f"Guest change {req.name}: {why}", idempotency_key=key,
		                 booking=req.booking, _system=True, durable=True, on_record=recorded,
		                 relock=lambda: _lock(req.name, req.booking),
		                 on_conflict=lambda refund: _conflicted(req.name, refund))
	except pay.RefundConflict:
		return "conflict", D(amount)
	except pay.RefundUnknown:
		return "unknown", D(amount)
	except frappe.QueryDeadlockError:
		raise
	except Exception:
		_undo("tex_gcr_refund")
		frappe.clear_last_message()
		log_exception(f"TEX guest change {req.name} refund of {txn}")
		# after its durable commit the attempt is on record: judged by what it says
		name = frappe.db.get_value(TXN, {"idempotency_key": pay.ns_key(req.property, key, "refund")}, "name")
		if not name:
			return "failed", ZERO                          # the gateway was never asked
		out = {"refund": name}
	r = frappe.db.get_value(TXN, out["refund"], ["name", "status", "amount", "currency"], as_dict=True)
	if not r or r.status == "Failed":
		return "failed", ZERO
	if r.status != "Succeeded":
		# a replay of a refund still Pending: name it, so the run waits for it (never around it)
		frappe.db.set_value(DT, req.name, "refund_in_flight", r.name, update_modified=False)
		return "unknown", from_db(r.amount, r.currency)
	return "ok", from_db(r.amount, r.currency)


def _step_done(req, token: str):
	"""Each refund's outcome (and what it left to staff) is on record, and committed outside
	tests, before the next one is made; the run's hold is renewed, and the booking and the
	request are locked and read again."""
	_count_refunds(req)
	req.refund_in_flight = None
	req.settle_claimed_until = add_to_date(now_datetime(), minutes=SETTLE_LEASE_MINUTES)
	req.save(ignore_permissions=True)
	_commit()
	return _relock(req, token)


def _conflicted(name: str, refund: str) -> None:
	"""The gateway answered refund ``refund`` of this request otherwise than the outcome recorded
	for it meanwhile (audited, failed in the system status). Called by the payments service
	while it holds the booking, this request, the refund and its charge, whichever run got the
	answer: the request stops for good (``settle_pending`` 0; the hold taken from any run, so a
	run still going stops at its next step) and names the refund for staff, who check it at the
	gateway and record what it actually did (``resolve_conflict``). Nothing else is decided
	before (re-review 4)."""
	req = frappe.get_doc(DT, name)
	req.settle_pending = 0
	req.settle_claim = None
	req.settle_claimed_until = None
	req.refund_in_flight = None
	_give_to_staff(req, ZERO, VERIFY_REFUND, f"the gateway answered refund {refund} otherwise than the outcome recorded "
	                                         "for it: check it at the gateway and record what it actually did (payment "
	                                         "screen); TEX refunds nothing more for this change until then",
	               unknown_refund=refund)
	req.save(ignore_permissions=True)


# ─── scheduler ───────────────────────────────────────────────────────────


def expire_awaiting() -> dict:
	"""Every 15 minutes, each request its own unit of work:

	- a change whose payment the gateway confirmed but the ``apply_paid`` job did not apply is
	  applied (or failed and refunded) now;
	- a change whose payment did not arrive before its deadline expires (a payment arriving
	  later is refunded);
	- a payment of a request no longer waiting that no job looked at (its ``apply_paid`` job
	  was lost: Redis down, a rollback dropped it) is given back (re-review F7);
	- refunds that were queued but did not run are retried."""
	now = now_datetime()
	expired = settled = applied = returned = 0
	paid_before = add_to_date(now, minutes=-APPLY_RETRY_MINUTES)
	for name in frappe.get_all(DT, filters={"status": "Awaiting Payment"}, pluck="name"):
		req = frappe.get_doc(DT, name)
		paid_txns = [t for t in _charges_of(req)
		             if get_datetime(frappe.db.get_value(TXN, t, "completed_at") or now) <= paid_before]
		if paid_txns:
			if apply_paid(name, paid_txns[0]) == "done":
				applied += 1
			continue
		if req.expires_at and get_datetime(req.expires_at) < now and _step(lambda n=name: _expire(n, now),
		                                                                     f"TEX guest change {name} expiry"):
			expired += 1
	for r in frappe.get_all(DT, filters={"attempt": (">", 0), "status": ("!=", "Awaiting Payment"), "settle_pending": 0,
	                                     "creation": (">=", add_to_date(now, days=-SWEEP_DAYS))},
	                        fields=["name", "property", "booking", "attempt", "status", "payment_transaction",
	                                "returned_charges"]):
		late = [t for t in _unreturned(r) if _held(t, r.booking)
		        and get_datetime(frappe.db.get_value(TXN, t, "completed_at") or now) <= paid_before]
		if late and apply_paid(r.name, late[0]) == "done":
			returned += 1
	cutoff = add_to_date(now, minutes=-SETTLE_RETRY_MINUTES)
	for name in frappe.get_all(DT, filters={"settle_pending": 1, "modified": ("<", cutoff)}, pluck="name"):
		if _step(lambda n=name: settle(n), f"TEX guest change {name} refund retry"):
			settled += 1
	return {"expired": expired, "settled": settled, "applied": applied, "returned": returned}


def _held(txn: str, booking: str) -> bool:
	"""The booking still holds money of this payment that no refund is on its way for."""
	from kamra.tex.payments import service as pay

	return pay.booking_nets(txn).get(booking, ZERO) - pay.in_flight_of(txn) > 0


def _expire(name: str, now) -> bool:
	req = _lock(name)
	if req.status != "Awaiting Payment" or not req.expires_at or get_datetime(req.expires_at) >= now:
		return False
	if any(True for _t in _charges_of(req)):
		return False                                      # paid meanwhile: ``apply_paid`` decides
	req.status = "Expired"
	req.error = "no payment arrived before the deadline"
	req.save(ignore_permissions=True)
	audit("guest_change.expired", reference_doctype=DT, reference_name=name, property=req.property,
	      new=_audit_row(req), source="Scheduler")
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


def last_request(res):
	"""The guest's latest change of reservation ``res``, whatever came of it, or None."""
	name = frappe.db.get_value(DT, {"reservation": res.name}, "name", order_by="creation desc")
	return frappe.get_doc(DT, name) if name else None


def _paid_for(req) -> D:
	"""What the guest paid online for this change (all its succeeded attempts)."""
	total = ZERO
	for t in _charges_of(req):
		row = frappe.db.get_value(TXN, t, ["amount", "currency"], as_dict=True)
		total += from_db(row.amount, row.currency)
	return total


def guest_outcome(req) -> dict:
	"""What came of a guest's change: the manage page tells the guest, back from a payment,
	whether the change was made, whether a payment was taken (``paid``) and what came back
	(``refunded``; ``hotel_refund``: what the hotel refunds)."""
	ccy = req.currency
	paid = quantize(_paid_for(req), ccy)
	refunded = from_db(req.refunded_amount, ccy)
	hotel = _staff_due(req) if req.staff_open else ZERO
	# for a change not made: what became of the guest's payment, decided here, never in the page
	back = None if req.status in (*DONE, *OPEN) else (
		"none" if paid <= 0 else "hotel" if hotel > 0 else "refunded" if refunded >= paid else "refunding")
	return {"request": req.name, "status": req.status.lower().replace(" ", "_"),
	        "settlement": KIND.get(req.settlement or ""),
	        "amount": to_str(from_db(req.settlement_amount if req.status in DONE else req.collect_amount, ccy)),
	        "paid": to_str(paid), "refunded": to_str(refunded), "hotel_refund": _money(hotel, ccy),
	        "money_back": back, "currency": ccy}


def guest_view(req) -> dict:
	"""A waiting change as the guest sees it: what they asked for and what it waits for
	(``pay_now``: their payment of ``amount``; ``staff_approval`` / ``staff``: the hotel)."""
	ccy = req.currency
	p = json.loads(req.proposal or "{}")
	waiting = req.status == "Awaiting Payment"
	kind = st.PAY_NOW if waiting else (st.STAFF_APPROVAL if from_db(req.difference, ccy) < 0 or req.penalty_terms
	                                   else st.STAFF)
	return {"request": req.name, "status": GUEST_STATUS.get(req.status, req.status.lower()), "kind": kind,
	        "changes": p.get("changes") or {}, "difference": to_str(from_db(req.difference, ccy)),
	        "amount": to_str(from_db(req.collect_amount, ccy)) if waiting else None,
	        "currency": ccy, "expires_at": str(req.expires_at) if waiting else None}


# ─── staff ───────────────────────────────────────────────────────────────


STAFF_FIELDS = ("name", "property", "booking", "reservation", "status", "currency", "old_total", "new_total",
                "difference", "collect_amount", "payment_transaction", "attempt", "settlement", "settlement_amount",
                "refunded_amount", "settle_pending", "staff_open", "staff_amount", "staff_settled", "staff_reason",
                "unknown_refund", "refund_in_flight", "penalty_terms", "revision", "error", "note", "expires_at", "resolved_by",
                "resolved_at", "resolution", "creation", "modified")
MONEY_FIELDS = ("old_total", "new_total", "difference", "collect_amount", "settlement_amount", "refunded_amount",
                "staff_amount", "staff_settled")


def staff_row(row) -> dict:
	out = {f: row.get(f) for f in STAFF_FIELDS}
	# money left to staff, open now (a refund to verify is shown apart)
	out["staff_due"] = _money(_staff_due(frappe._dict(row)), row.get("currency") or "EUR")
	for f in MONEY_FIELDS:
		out[f] = to_str(from_db(out[f], row.get("currency") or "EUR"))
	for f in ("expires_at", "resolved_at", "creation", "modified"):
		out[f] = str(out[f]) if out[f] else None
	out["settle_pending"] = bool(out["settle_pending"])
	out["staff_open"] = bool(out["staff_open"])
	out["penalty_terms"] = bool(out["penalty_terms"])
	# waiting for staff: a request to decide, or money left to staff (a refund to make or to verify)
	out["needs_staff"] = row.get("status") == "Requested" or out["staff_open"]
	# a refund to verify is closed at once (TEX then refunds the rest); money to refund by staff
	# once TEX is done refunding
	verify = bool(row.get("unknown_refund")) and frappe.db.get_value(TXN, row.get("unknown_refund"),
	                                                                   "status") == "Pending"
	out["verify_refund"] = row.get("unknown_refund") if verify else None
	# a refund is verified only once its answer cannot come any more (third review); a conflict
	# first needs the gateway's actual outcome (re-review 4)
	from kamra.tex.payments import service as pay

	conflict = bool(row.get("unknown_refund")) and not verify and bool(pay.conflict_open(row.get("unknown_refund")))
	blocked = (_("The gateway answered refund {0} otherwise than the outcome recorded for it: record what it "
	             "actually did on the payment screen first.").format(row.get("unknown_refund")) if conflict
	           else finish_block(row.get("unknown_refund")) if verify
	           else _("TEX is still refunding this change: close the rest once it is done.") if out["settle_pending"]
	           else None) if out["staff_open"] else None
	out["can_close"] = out["staff_open"] and not blocked
	out["close_blocked"] = blocked
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
		or_filters = [[DT, "status", "=", "Requested"], [DT, "staff_open", "=", 1]]
	rows = frappe.get_all(DT, filters=filters, or_filters=or_filters, fields=[*STAFF_FIELDS, "proposal"],
	                      order_by="creation desc", limit_start=start, limit=limit)
	out = []
	for r in rows:
		row = staff_row(r)
		if r.status == "Requested" and from_db(r.difference, r.currency) < 0:
			# what approving it would leave paid above the new total: staff choose to refund it or
			# keep it as credit (``resolve`` decides it again as the booking is then)
			b = frappe.db.get_value("TEX Booking", r.booking, ["name", "paid_amount", "total_amount", "currency"],
			                        as_dict=True)
			ccy = b.currency if b else r.currency
			over = max(ZERO, usable_paid(b, r.name) - from_db(b.total_amount, ccy)
			           - from_db(r.difference, ccy)) if b else ZERO
			row["overpaid_after"] = to_str(quantize(over, ccy))
		out.append(row)
	return out


RESOLVE_ACTIONS = ("approve", "reject", "close")


def resolve(request: str, action: str, *, settlement: str | None = None, reason: str | None = None,
            refund_outcome: str | None = None, staff_money: str | None = None) -> dict:
	"""Staff decide a guest's request, or close money of it left to them.

	- ``approve`` (Requested; reservation.modify): the guest's change is applied at the price
	  they were shown (as of its pricing time; the reservation must not have changed since). A
	  lower price with money paid above the new total is refunded (``settlement="Refund"``,
	  also needs payment.refund) or kept as credit (``"Credit on booking"``); anything else
	  changes the balance;
	- ``reject`` (Requested; reservation.modify): nothing changes;
	- ``close`` (payment.refund): money left to staff was settled outside TEX. When it is a
	  refund the gateway never confirmed, ``refund_outcome`` records what the gateway did
	  (``Succeeded``: the money comes off the booking; ``Failed``: it stays), and TEX refunds
	  what the change still owes (re-review F3), once the refund's answer cannot come any more
	  (``finish_block``). Other money left to staff is closed saying what became of it
	  (``staff_money``): "Refunded outside TEX" records that refund on the booking (a Manual
	  refund of the payments holding it: no longer paid, nor the guest's credit), "Kept on the
	  booking" leaves it as the booking's credit (G-93)."""
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
	else:
		queue = _close(req, refund_outcome, reason, staff_money)
	req.resolved_by = frappe.session.user
	req.resolved_at = now_datetime()
	note = reason.strip()[:500]
	req.resolution = (f"{req.resolution}\n{note}" if action == "close" and req.resolution else note)[-500:]
	req.save(ignore_permissions=True)
	_acknowledge(req, f"{action} {req.name}: {reason.strip()[:200]}")
	audit("guest_change.resolve", reference_doctype=DT, reference_name=req.name, property=req.property,
	      new={"action": action, "refund_outcome": refund_outcome, "staff_money": staff_money, **_audit_row(req)},
	      reason=reason)
	if queue:
		queue_settle(req.name)
		req.reload()                      # as refunded so far (tests run the refund job inline)
	return staff_row(req.as_dict())


def _close(req, refund_outcome: str | None, reason: str, staff_money: str | None = None) -> bool:
	"""→ whether TEX refunds what the change still owes now (after a refund was verified)."""
	from kamra.tex.payments import service as pay

	if not req.staff_open:
		frappe.throw(_("Only money left to staff can be closed."))
	if req.unknown_refund and pay.conflict_open(req.unknown_refund):
		frappe.throw(_("The gateway answered refund {0} otherwise than the outcome recorded for it: check it at the "
		               "gateway and record what it actually did on the payment screen first.").format(req.unknown_refund))
	row = _in_flight(req)
	if row and row.name == req.unknown_refund:
		if refund_outcome not in ("Succeeded", "Failed"):
			frappe.throw(_("Say whether the gateway made refund {0}: check it at the gateway first.").format(
				req.unknown_refund))
		why = finish_block(row.name)
		if why:
			frappe.throw(why)
		done = pay.finish_unknown_refund(row.name, outcome=refund_outcome, reference=None, reason=reason)
		return _verified(req, row.name, refund_outcome, D(done["amount"]))
	if refund_outcome:
		frappe.throw(_("There is no refund to verify on this request."))
	if req.settle_pending:
		frappe.throw(_("TEX is still refunding this change: close the rest once it is done."))
	if staff_money not in STAFF_MONEY:
		frappe.throw(_("Say whether this money was refunded to the guest outside TEX or kept on the booking."))
	ccy = req.currency
	due = _staff_due(req)
	recorded = _record_outside(req, due, reason) if staff_money == REFUNDED_OUTSIDE and due > 0 else ZERO
	req.staff_settled = from_db(req.staff_settled, ccy) + due
	req.staff_open = 0
	audit("guest_change.staff_money", reference_doctype=DT, reference_name=req.name, property=req.property,
	      new={"how": staff_money, "amount": to_str(quantize(due, ccy)), "recorded": to_str(quantize(recorded, ccy)),
	           "currency": ccy}, reason=reason)
	return False


def _left_to_staff(req) -> list[tuple[str, D, str]]:
	"""The request's own payments left to staff to give back (a change that did not apply, a
	late or second payment whose refund TEX could not make): [(payment, what the booking still
	holds of it, less refunds of it on their way, when it was taken)]."""
	from kamra.tex.payments import service as pay

	out = []
	for txn in _charges_of(req):
		if txn not in _returned(req) or (req.status in DONE and txn == req.payment_transaction):
			continue
		held = pay.booking_nets(txn).get(req.booking, ZERO) - pay.in_flight_from(txn, req.booking)
		if held > 0:
			at = frappe.db.get_value(TXN, txn, ["completed_at", "creation"], as_dict=True)
			out.append((txn, held, str(at.completed_at or at.creation)))
	return out


def _record_outside(req, amount: D, reason: str) -> D:
	"""Staff gave ``amount`` of the change's money back outside TEX: recorded as Manual refunds
	taken off the booking (never the payments' unallocated money), so it is no longer counted as
	paid (G-93). → what came off the booking.

	- A lower price refunded (settlement "Refund"): from the payments holding the booking's
	  money, newest first (payments other requests must give back left out), at most what the
	  booking holds over its total, so a refund recorded by hand before is not recorded twice.
	- The change's own payments handed back (a change that did not apply, a late or second
	  payment): from exactly those payments, at most what the booking still holds of them, on
	  any booking, paid in full or not (re-review 4)."""
	from kamra.tex.payments import service as pay

	ccy = req.currency
	if req.status in DONE and req.settlement == "Refund":
		b = frappe.db.get_value("TEX Booking", req.booking, ["paid_amount", "total_amount"], as_dict=True)
		cap = max(ZERO, from_db(b.paid_amount, ccy) - from_db(b.total_amount, ccy)
		          - earmarked(req.booking, except_request=req.name))
		reserved = _reserved(req.booking, req.name)
		sources = [st.Charge(c["transaction"], min(c["available"], pay.booking_nets(c["transaction"]).get(
			req.booking, ZERO) - pay.in_flight_from(c["transaction"], req.booking)), True, c["at"])
			for c in pay.booking_charges(req.booking) if c["transaction"] not in reserved]
	else:
		sources = [st.Charge(txn, held, True, at) for txn, held, at in _left_to_staff(req)]
		cap = sum((c.available for c in sources), ZERO)
	plan, _rest = st.plan_refunds(min(amount, cap), sources)
	step = to_str(from_db(req.staff_settled, ccy))
	done = ZERO
	for txn, part in plan:
		out = pay.refund_outside(txn, amount=part, reason=f"Guest change {req.name}: {reason.strip()}"[:500],
		                         reference=f"guest change {req.name}",
		                         idempotency_key=f"change:{req.name}:outside:{txn}:{step}", booking=req.booking,
		                         _system=True)
		done += D(out["from_booking"])                   # what came off this booking, nothing else
	if done < amount:
		req.error = (f"{to_str(quantize(amount - done, ccy))} {ccy} refunded outside TEX was not recorded: the "
		             f"booking no longer holds it. {req.error or ''}")[:500]
	return done


def _trim_staff(req) -> None:
	"""Money left to staff is never more than the change still owes: once a refund's outcome is
	known (verified, or put right after a conflict), money no longer owed leaves staff's hands,
	and ``staff_open`` / ``staff_reason`` follow what is left (re-review 4). Saved by the caller."""
	from kamra.tex.payments import service as pay

	ccy = req.currency
	if req.status in DONE and req.settlement == "Refund":
		owed = max(ZERO, from_db(req.settlement_amount, ccy) - from_db(req.refunded_amount, ccy)
		           - from_db(req.staff_settled, ccy))
	else:
		owed = sum((held for _t, held, _at in _left_to_staff(req)), ZERO)
	due = _staff_due(req)
	if due > owed:
		req.staff_amount = from_db(req.staff_amount, ccy) - (due - owed)
	verify = _to_verify(req) > 0 or bool(req.unknown_refund and pay.conflict_open(req.unknown_refund))
	left = _staff_due(req)
	req.staff_open = 1 if verify or left > 0 else 0
	req.staff_reason = VERIFY_REFUND if verify else REFUND_BY_STAFF if left > 0 else ""


def _verified(req, refund: str, outcome: str, amount: D) -> bool:
	"""Staff recorded what the gateway did with the request's refund it never confirmed: the
	money is refunded or not, it is no longer staff's to verify, and what the change still owes
	(the rest of its refund, its other payments to give back) is TEX's to refund again: →
	whether a refund run is queued (re-review F3). Saved by the caller."""
	ccy = req.currency
	if refund not in _refunds_made(req):
		req.refund_rows = "\n".join([*_refunds_made(req), refund])
	_count_refunds(req)                                   # counted once, from the refund as it now is
	if req.unknown_refund == refund:
		req.staff_amount = max(ZERO, from_db(req.staff_amount, ccy) - amount)   # no longer staff's to verify
		req.unknown_refund = None
	if req.refund_in_flight == refund:
		req.refund_in_flight = None
	_trim_staff(req)
	audit("guest_change.refund_verified", reference_doctype=DT, reference_name=req.name, property=req.property,
	      new={"refund": refund, "outcome": outcome, "amount": to_str(quantize(amount, ccy)), "currency": ccy})
	if req.status == "Awaiting Payment":
		return False
	req.settle_pending = 1
	return True


def request_of_refund(refund: str) -> str | None:
	"""The guest change a refund was made for, if any."""
	return (frappe.db.get_value(DT, {"refund_in_flight": refund}, "name")
	        or frappe.db.get_value(DT, {"unknown_refund": refund}, "name")
	        or frappe.db.get_value(DT, {"refund_rows": ("like", f"%{refund}%")}, "name"))


def finish_block(refund: str | None) -> str | None:
	"""Why staff cannot record the outcome of this refund now (None: they can). Only once its
	answer cannot come any more: Pending, and unanswered (UNKNOWN) or older than
	``REFUND_STUCK_MINUTES``, and no refund run holding the request it was made for (its gateway
	call may still be running, and its answer would be lost). Third review of ADR-044."""
	from kamra.tex.payments import service as pay

	row = frappe.db.get_value(TXN, refund, ["name", "txn_type", "status", "error_code", "creation"], as_dict=True) \
		if refund else None
	if not row or row.txn_type != "Refund" or row.status != "Pending":
		return _("Only a refund waiting for its outcome can be settled here ({0}).").format(row.status if row else "-")
	if not pay.stuck(row, now_datetime()):
		return _("This refund was asked for a moment ago and the gateway's answer may still come: check again in a "
		         "few minutes.")
	name = request_of_refund(refund)
	if name and _run_holds(frappe.db.get_value(DT, name, ["settle_claim", "settle_claimed_until"], as_dict=True)):
		return _("A refund run is still waiting for the gateway's answer to this refund: check again in a few "
		         "minutes.")
	return None


def resolve_conflict(refund: str, *, outcome: str, reason: str, reference: str | None = None) -> dict:
	"""Staff record what the gateway actually did with a refund whose answer contradicted the
	outcome recorded for it (the payment screen; payment.refund, audited): the refund and the
	booking are put right (``payments.service.correct_refund``), and a guest change it was made
	for goes on from the truth: what it refunded is counted again, money no longer owed leaves
	staff's hands, and its refunds resume (re-review 4). Locks the booking, the request, the
	refund, its charge."""
	from kamra.tex.payments import service as pay

	row = frappe.db.get_value(TXN, refund, ["name", "property", "txn_type", "booking", "parent_transaction", "provider"],
	                          as_dict=True)
	if not row or row.txn_type != "Refund":
		frappe.throw(_("Refund not found."), frappe.DoesNotExistError)
	scope.require("payment.refund", row.property)
	name = request_of_refund(refund)
	booking = ((frappe.db.get_value(DT, name, "booking") if name else None) or row.booking
	           or frappe.db.get_value(TXN, row.parent_transaction, "booking"))
	if booking:
		frappe.db.get_value("TEX Booking", booking, "name", for_update=True)
	req = _lock(name, booking) if name else None
	done = pay.correct_refund(refund, outcome=outcome, reason=reason, reference=reference)
	if req:
		if refund not in _refunds_made(req) and row.provider != "Manual":
			req.refund_rows = "\n".join([*_refunds_made(req), refund])
		_count_refunds(req)
		if req.unknown_refund == refund:
			req.unknown_refund = None
		_trim_staff(req)
		resume = req.status != "Awaiting Payment"
		if resume:
			req.settle_pending = 1
		audit("guest_change.refund_conflict_resolved", reference_doctype=DT, reference_name=req.name,
		      property=req.property, new={"refund": refund, "outcome": outcome}, reason=reason)
		req.save(ignore_permissions=True)
		if not req.staff_open:
			_acknowledge(req, f"refund {refund} put right: the gateway's answer was {outcome}")
		if resume:
			queue_settle(req.name)
	return done


def verify_refund(refund: str, *, outcome: str, reason: str, reference: str | None = None) -> dict:
	"""Staff checked at the gateway a refund it never confirmed (the payment screen: a refund
	they started, or one a guest change's refund run left), and record what it did (needs
	payment.refund; audited ``payment.refund_verified``). A guest change the refund was made for
	is settled with it: TEX refunds what it still owes (G-45 re-review F2, F3). Locks the
	booking, then the request, then the payment rows."""
	from kamra.tex.payments import service as pay

	row = frappe.db.get_value(TXN, refund, ["name", "property", "txn_type", "booking", "parent_transaction"],
	                          as_dict=True)
	if not row or row.txn_type != "Refund":
		frappe.throw(_("Refund not found."), frappe.DoesNotExistError)
	scope.require("payment.refund", row.property)
	if not (reason or "").strip():
		frappe.throw(_("A reason is required."))
	name = request_of_refund(refund)
	booking = ((frappe.db.get_value(DT, name, "booking") if name else None) or row.booking
	           or frappe.db.get_value(TXN, row.parent_transaction, "booking"))
	# the booking, the request, the refund, its charge: the order a refund run takes after the
	# gateway answered (third review)
	if booking:
		frappe.db.get_value("TEX Booking", booking, "name", for_update=True)
	req = _lock(name, booking) if name else None
	why = finish_block(refund)
	if why:
		frappe.throw(why)
	done = pay.finish_unknown_refund(refund, outcome=outcome, reference=reference, reason=reason.strip())
	if req:
		resume = _verified(req, refund, outcome, D(done["amount"]))
		req.save(ignore_permissions=True)
		if not req.staff_open:
			_acknowledge(req, f"refund {refund} checked at the gateway: {outcome}")
		if resume:
			queue_settle(req.name)
	return done


def _approve(req, settlement: str | None, reason: str) -> bool:
	b = frappe.get_doc("TEX Booking", req.booking)
	ccy = b.currency
	lower = from_db(req.difference, ccy) < 0
	# decided before anything is applied: what was paid above the new total, if anything (money
	# set aside for other refunds is not counted)
	over = max(ZERO, usable_paid(b, req.name) - (from_db(b.total_amount, ccy) + from_db(req.difference, ccy)))
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
	over = max(ZERO, usable_paid(b, req.name) - from_db(b.total_amount, ccy))
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
