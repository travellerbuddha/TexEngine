"""Late payments (K-2b; R-40, R-41, R-46): money for a booking whose rooms are not held for it.

A gateway (or a bank transfer, a payment link, staff) may bring money for a booking that cannot
take it: a cancelled booking (beyond what it still owes), or one waiting for its payment after its
hold truly ended — the hold deadline passed and no payment attempt started
within it is still open (``holds``) — or after its rooms were released. That money never confirms
the booking at the price it was quoted and never takes rooms back:

- the booking expires at once with all its rooms (``booking.expire_booking``), if it had not yet;
- the money stays on record on its charge, off the booking (never a negative balance), in
  reconciliation: ``Refund Queued`` when the rooms are gone and the charge's gateway refunds
  through TEX (``refund_queued`` makes it, once), else ``Action Required``: staff book the stay
  again at today's price once the guest accepts it (then allocate the payment to it) or refund it;
- the note says what is free now and what the stay costs now against its locked price;
- ``payment.reconciliation_required`` is audited and the status page reports every open one.

Nothing is confirmed or sent to the guest or the PMS. The caller holds the charge's lock (then the
booking's): the order a payment callback takes."""

from __future__ import annotations

from collections import Counter
from datetime import datetime

import frappe
from frappe import _
from frappe.utils import get_datetime, getdate, now_datetime

from kamra.tex.money import ZERO, from_db, quantize, to_str
from kamra.tex.security.audit import audit, log_exception
from kamra.tex.services import holds

TXN = "TEX Payment Transaction"
OPEN = ("Action Required", "Refund Queued")
HOLD_EXPIRED = "HOLD_EXPIRED"
ROOMS_RELEASED = "ROOMS_RELEASED"
BOOKING_CANCELLED = "BOOKING_CANCELLED"
NOT_PAYABLE = "NOT_PAYABLE"
EXPIRED_UNPAID = "EXPIRED_UNPAID"
TAKES_MONEY = ("Confirmed", "Partially Cancelled")
CAUSES = {ROOMS_RELEASED: "its rooms had been given back",
          HOLD_EXPIRED: "its hold and payment window had ended",
          BOOKING_CANCELLED: "it had been cancelled",
          NOT_PAYABLE: "it could not take payments",
          EXPIRED_UNPAID: "its hold ended before it was paid in full"}
REFUND_REASON = "the booking could not be confirmed: the payment arrived after its rooms were given back"


def problem(b, now: datetime | None = None, amount=None) -> str | None:
	"""Why booking ``b`` (locked by the caller) may not take ``amount`` of money, or None when it
	may (K-2b, K-2c). A confirmed (or partly cancelled) booking takes it. A cancelled one takes
	at most what it still owes (its cancellation charges), else ``BOOKING_CANCELLED``. A booking
	waiting for its payment takes it only while its rooms are held for it: ``ROOMS_RELEASED`` (a
	room holds nothing any more), ``HOLD_EXPIRED`` (its hold deadline passed and no payment
	attempt started within it is open). Any other status: ``NOT_PAYABLE``."""
	if b.status in TAKES_MONEY:
		return None
	if b.status == "Cancelled":
		owed = from_db(b.total_amount, b.currency) - from_db(b.paid_amount, b.currency)
		return None if amount is not None and ZERO < amount <= owed else BOOKING_CANCELLED
	if b.status not in holds.HOLDING:
		return NOT_PAYABLE
	from kamra.tex.services import booking as booking_svc

	if booking_svc.rooms_not_held(b):
		return ROOMS_RELEASED
	now = get_datetime(now or now_datetime())
	if holds.in_flight(b, now):
		return None
	deadline = holds.hold_deadline(b.name, lock=True)
	return HOLD_EXPIRED if deadline and deadline <= now else None


def reconcile(txn, booking: str, why: str, *, now: datetime | None = None) -> None:
	"""Keep the charge's money off ``booking`` in reconciliation (see the module). Idempotent: a
	charge already in reconciliation is left as it is."""
	from kamra.tex.payments import service as pay
	from kamra.tex.services import booking as booking_svc

	now = get_datetime(now or now_datetime())
	if frappe.db.get_value(TXN, txn.name, "reconciliation"):
		return
	booking_svc.expire_booking(booking, now=now, force=True)
	free, detail = _today(booking, now)
	state = "Refund Queued" if not free and pay.auto_refundable(txn) else "Action Required"
	ccy = txn.currency
	cause = CAUSES.get(why, why)
	note = (f"{to_str(from_db(txn.amount, ccy))} {ccy} arrived at {now:%Y-%m-%d %H:%M} for booking {booking} after "
	        f"{cause}. Not confirmed: {detail}. "
	        + ("The rooms are gone: the payment is refunded." if state == "Refund Queued" else
	           "Book the stay again once the guest accepts it and allocate this payment to it, or refund it."))
	_flag(txn, booking, why, state, note, from_db(txn.amount, ccy), rooms_free_now=free)


def money_off_expired(booking: str, *, now: datetime | None = None):
	"""B2: the money a booking held when it expired before it was paid in full (a first of two
	links, a part paid at the desk) comes off the cancelled booking — never a negative balance —
	and each charge it came from goes to reconciliation for staff. → the amount taken off."""
	from kamra.tex.payments import service as pay

	now = get_datetime(now or now_datetime())
	taken = ZERO
	for name in sorted(set(frappe.get_all("TEX Payment Allocation", filters={"booking": booking},
	                                      pluck="transaction"))):
		held = pay.booking_nets(name, lock=True).get(booking, ZERO) - pay.in_flight_from(name, booking, lock=True)
		if held <= ZERO:
			continue
		pay.release(name, booking=booking, amount=held, reason=CAUSES[EXPIRED_UNPAID],
		            idempotency_key=f"expired:{booking}:{name}", _system=True)
		txn = frappe.get_doc(TXN, name)
		note = (f"{to_str(held)} {txn.currency} of this payment was on booking {booking}, whose hold ended at "
		        f"{now:%Y-%m-%d %H:%M} before it was paid in full: the booking expired with its rooms and the money "
		        "came off it. Book the stay again once the guest accepts it and allocate this payment to it, or "
		        "refund it.")
		_flag(txn, booking, EXPIRED_UNPAID, "Action Required", note, held)
		taken += held
	return taken


def _flag(txn, booking: str, why: str, state: str, note: str, amount, **extra) -> None:
	"""Put a charge's money in reconciliation (never twice), audited."""
	if frappe.db.get_value(TXN, txn.name, "reconciliation") in OPEN:
		return
	frappe.db.set_value(TXN, txn.name, {"reconciliation": state, "reconciliation_note": note[:1000]},
	                    update_modified=False)
	audit("payment.reconciliation_required", reference_doctype=TXN, reference_name=txn.name, property=txn.property,
	      new={"booking": booking, "why": why, "state": state, "amount": to_str(amount), "currency": txn.currency,
	           **extra})


def refusal(why: str, b, amount) -> str:
	"""What staff are told when they allocate money a booking cannot take (never done silently)."""
	if why == BOOKING_CANCELLED:
		owed = from_db(b.total_amount, b.currency) - from_db(b.paid_amount, b.currency)
		return _("Booking {0} is cancelled and owes {1} {2}: {3} {2} cannot be allocated to it. Book the stay "
		         "again and allocate the payment there, or refund it.").format(
			b.name, to_str(max(owed, ZERO)), b.currency, to_str(amount))
	if why in (HOLD_EXPIRED, ROOMS_RELEASED):
		return _("Booking {0} can no longer take this payment: {1}. Book the stay again and allocate the payment "
		         "there, or refund it.").format(b.name, CAUSES[why])
	return _("Booking {0} cannot take payments ({1}).").format(b.name, b.status)


def _today(booking: str, now: datetime) -> tuple[bool, str]:
	"""The stay judged again now (INV-6): whether its rooms are free, and its price today against
	the price it was locked at. → (all rooms free, a sentence for the note)."""
	from kamra.tex.availability import repository as avail

	rooms = [frappe.get_doc("Reservation", r.reservation) for r in frappe.get_doc("TEX Booking", booking).rooms]
	wanted = Counter((r.room_type, r.tex_contract, getdate(r.check_in_date), getdate(r.check_out_date)) for r in rooms)
	free = True
	for (room_type, contract, ci, co), n in wanted.items():
		count, _days = avail.stay_availability(rooms[0].property, room_type, contract, ci, co, now.date())
		free = free and count >= n
	ccy = rooms[0].tex_currency if rooms else ""
	sold = sum((from_db(r.tex_total_amount, ccy) for r in rooms), ZERO)
	today = _price_today(rooms, now)
	price = (f"price now: {to_str(today)} {ccy} (sold at {to_str(sold)} {ccy}, difference "
	         f"{to_str(quantize(today - sold, ccy))})" if today is not None
	         else f"price now: not sellable (sold at {to_str(sold)} {ccy})")
	return free, f"rooms free now: {'yes' if free else 'no'}; {price}"


def _price_today(rooms: list, now: datetime):
	"""The rooms priced again as a new sale now (the contract on sale now, today's rates and
	rules); None when a room cannot be sold now."""
	from kamra.tex.services import modification, quoting

	total = ZERO
	messages = frappe.local.message_log
	for res in rooms:
		mark = len(messages)
		try:
			req, snap = modification.build_changed_request(res, {}, now)
			version, _at, _how = modification._resolve(res, snap, req, "CURRENT", None)
			quote, _terms = quoting.price_request(version, req, exclude_booking=res.tex_booking,
			                                      exclude_reservation=res.name)
		except Exception as e:
			del messages[mark:]       # a refusal here is a note for staff, never a message to the guest
			if not isinstance(e, frappe.ValidationError):
				log_exception(f"TEX late payment reprice {res.name}")
			return None
		if not quote.sellable:
			return None
		total += quote.total
	return total


def settled(transaction: str) -> None:
	"""A charge in reconciliation whose money is all refunded, or allocated to a booking by staff,
	leaves it (``Refunded`` / ``Resolved``). Called under the charge's lock."""
	from kamra.tex.payments import service as pay

	row = frappe.db.get_value(TXN, transaction, ["reconciliation", "amount", "currency", "property"], as_dict=True)
	if not row or row.reconciliation not in OPEN:
		return
	amount = from_db(row.amount, row.currency)
	refunded = pay.refunded_of(transaction, lock=True)
	left = amount - pay.allocated_of(transaction, lock=True) - refunded - pay.in_flight_of(transaction, lock=True)
	if left > ZERO:
		return
	state = "Refunded" if refunded >= amount else "Resolved"
	frappe.db.set_value(TXN, transaction, "reconciliation", state, update_modified=False)
	audit("payment.reconciliation_" + state.lower(), reference_doctype=TXN, reference_name=transaction,
	      property=row.property, new={"state": state})


def refund_queued() -> dict:
	"""Scheduler: refund the charges queued for a refund, once each (idempotency key per charge),
	each under its lock and on record before the gateway is asked (``durable``). A refund the
	gateway refuses, or does not answer, goes to staff (``Action Required``)."""
	from kamra.tex.payments import service as pay

	done = 0
	for name in frappe.get_all(TXN, filters={"reconciliation": "Refund Queued"}, pluck="name"):
		txn = frappe.get_doc(TXN, name, for_update=True)
		if txn.reconciliation != "Refund Queued":
			continue
		free = (from_db(txn.amount, txn.currency) - pay.allocated_of(name, lock=True) - pay.refunded_of(name, lock=True)
		        - pay.in_flight_of(name, lock=True))
		state, note = None, None
		if free <= ZERO:
			settled(name)
		else:
			try:
				out = pay.refund(name, amount=free, reason=REFUND_REASON, idempotency_key=f"late:{name}",
				                 _system=True, _late=True, durable=True)
			except pay.RefundUnknown:
				state, note = "Action Required", "the gateway did not answer the refund: check it at the gateway"
			except frappe.ValidationError as e:
				state, note = "Action Required", f"the automatic refund was refused: {e}"
			else:
				if out.get("status") == "Succeeded":
					settled(name)
					done += 1
				elif out.get("status") == "Failed":
					state, note = "Action Required", "the gateway refused the refund"
		if state:
			frappe.db.set_value(TXN, name, {"reconciliation": state, "reconciliation_note": (
				(txn.reconciliation_note or "") + f" Refund: {note}.")[:1000]}, update_modified=False)
		if not frappe.flags.in_test:
			frappe.db.commit()  # nosemgrep: frappe-manual-commit -- one charge's refund per transaction
	return {"refunded": done}
