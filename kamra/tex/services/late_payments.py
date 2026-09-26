"""Late payments (K-2b, audit 1b B2/B3; R-40, R-41, R-46): money a booking cannot take as it is.

A gateway (or a bank transfer, a payment link, staff) may bring money for a booking:

a) waiting for its payment with its rooms still held for it, even past its hold deadline (the
   expiry job has not run): nothing is taken again, so the money confirms it at its locked price;
b) whose rooms were given back (it expired, or a room was released) and are still free: nothing is
   revived by itself — ``Action Required`` for staff;
c) whose rooms were given back and sold to someone else: ``Refund Queued`` when the charge's
   gateway refunds through TEX (``refund_queued`` makes it, once), else ``Action Required``;
d) cancelled, beyond what it still owes (its cancellation charges): as b) or c).

In b)–d) the money stays on record on its charge, off the booking (never a negative balance); the
note says what is free now and what the stay costs now against its locked price;
``payment.reconciliation_required`` is audited. Nothing is confirmed or sent to the PMS. A booking
that expires with money already on it hands that money over the same way (B2).

Late is by the gateway's clock when it states it (B4): money captured while its checkout was open,
whose news came after the expiry (a delayed notification, staff verifying after an outage), takes
the booking back with its rooms while they are free (``revive``) and confirms it; when they are
not, it goes to staff (``Action Required``), never refunded by itself. The caller holds the
charge's lock (then the booking's): the order a payment callback takes."""

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
ROOMS_RELEASED = "ROOMS_RELEASED"
BOOKING_CANCELLED = "BOOKING_CANCELLED"
NOT_PAYABLE = "NOT_PAYABLE"
EXPIRED_UNPAID = "EXPIRED_UNPAID"
TAKES_MONEY = ("Confirmed", "Partially Cancelled")
CONFIRMED = ("Confirmed", "Checked In", "Checked Out", "No Show")
# what a payment made in time may undo: an expiry its news came after (B4)
REVIVABLE = (ROOMS_RELEASED, BOOKING_CANCELLED)
REVIVE_SAVEPOINT = "tex_revive_booking"
CAUSES = {ROOMS_RELEASED: "its rooms had been given back",
          BOOKING_CANCELLED: "it had been cancelled",
          NOT_PAYABLE: "it could not take payments",
          EXPIRED_UNPAID: "its hold ended before it was paid in full"}
REFUND_REASON = "the booking could not be confirmed: the payment arrived after its rooms were given back"


def problem(b, amount=None, *, in_flight: bool = False) -> str | None:
	"""Why booking ``b`` (locked by the caller) may not take ``amount`` of money, or None when it
	may. A confirmed (or partly cancelled) booking takes it. A cancelled one takes at most what it
	still owes (its cancellation charges) from staff, else ``BOOKING_CANCELLED``; money that was on
	its way (``in_flight``: a gateway, a link, a transfer) is never kept as its fee (C6). A booking
	waiting for its payment takes it while its rooms are held for it, however late (B3 a), else
	``ROOMS_RELEASED``. Any other status: ``NOT_PAYABLE``."""
	if b.status == "Partially Cancelled" and not confirmed_rooms(b.name):
		# D2: never confirmed, left "Partially Cancelled" before B1 (its other rooms released by the old
		# PMS job): it takes no money as a confirmed booking does, and owes no fee
		states = frappe.get_all("Reservation", filters={"tex_booking": b.name}, pluck="status")
		return BOOKING_CANCELLED if all(s == "Cancelled" for s in states) else NOT_PAYABLE
	if b.status in TAKES_MONEY:
		return None
	if b.status == "Cancelled":
		if in_flight:
			# money on its way when the booking was cancelled is never kept as its fee (C6, user decision)
			return BOOKING_CANCELLED
		owed = from_db(b.total_amount, b.currency) - from_db(b.paid_amount, b.currency)
		return None if amount is not None and ZERO < amount <= owed else BOOKING_CANCELLED
	if b.status not in holds.HOLDING:
		return NOT_PAYABLE
	from kamra.tex.services import booking as booking_svc

	# its rooms still held for it: nothing is taken again, so its money confirms it as quoted,
	# however late it comes (B3 a); rooms given back are never taken again by themselves (B3 b, c)
	return ROOMS_RELEASED if booking_svc.rooms_not_held(b) else None


def confirmed_rooms(booking: str) -> bool:
	"""Whether a room of the booking was ever confirmed (confirmed, in house, departed, no-show)."""
	return bool(frappe.db.exists("Reservation", {"tex_booking": booking, "status": ("in", CONFIRMED)}))


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
	in_time = holds.paid_in_time(txn)
	# paid in time, its news late: never refunded by itself — the hotel decides (B4, D4)
	state = "Refund Queued" if not free and not in_time and pay.auto_refundable(txn) else "Action Required"
	again = booking_svc.live_duplicate(booking) if in_time else None
	ccy = txn.currency
	cause = CAUSES.get(why, why)
	note = (f"{to_str(from_db(txn.amount, ccy))} {ccy} arrived at {now:%Y-%m-%d %H:%M} for booking {booking} after "
	        f"{cause}. "
	        + (f"It was paid in time (captured at {get_datetime(txn.captured_at):%Y-%m-%d %H:%M}, its checkout open "
	           f"until {holds.attempt_deadline(txn):%Y-%m-%d %H:%M}), but the booking could not take its rooms back"
	           + (f": the guest has booking {again} for the same stay. " if again else ". ")
	           if in_time else "")
	        + f"Not confirmed: {detail}. "
	        + ("The rooms are gone: the payment is refunded." if state == "Refund Queued" else
	           "Book the stay again once the guest accepts it and allocate this payment to it, or refund it."))
	_flag(txn, booking, why, state, note, from_db(txn.amount, ccy), rooms_free_now=free)


def lock_expiry_money(booking: str, *, but: str) -> list[str]:
	"""D4: the charges whose money ``booking`` held when it expired (B2) — which a revival takes back —
	locked in name order before the booking is (every payment path locks a charge, then its booking;
	a staff refund of one of them does). ``but``: the charge already locked. → their names."""
	from kamra.tex.payments import service as pay

	prop = frappe.db.get_value("TEX Booking", booking, "property")
	rows = frappe.db.sql("""SELECT `transaction`, idempotency_key FROM `tabTEX Payment Allocation`
	                        WHERE booking=%s AND allocation_type='Release'""", booking, as_dict=True)
	names = sorted({r.transaction for r in rows if r.transaction != but
	                and r.idempotency_key == pay.ns_key(prop, f"expired:{booking}:{r.transaction}", "release")})
	for name in names:
		frappe.db.get_value(TXN, name, "name", for_update=True)
	return names


def revive(txn, booking: str, amount, locked=()) -> bool:
	"""B4: money the gateway captured while its checkout was open, whose news came after the
	booking expired, takes the booking back with the rooms its expiry gave back
	(``booking.revive_expired``) — when they are still free, and when this money with what the
	booking held when it expired (B2, still unused on its charges) pays what it had to pay now, so
	it is confirmed at once. That money comes back to it and its charges leave reconciliation.
	Never when the guest has another live booking for the same stay (D4 c: staff decide). ``locked``:
	the charges of that money, locked before the booking (``lock_expiry_money``); no other is taken.
	Anything else changes nothing: → False (the caller reconciles). → whether it was taken back."""
	from kamra.tex.payments import service as pay
	from kamra.tex.services import booking as booking_svc
	from kamra.tex.services.txn import undo_step

	if not holds.paid_in_time(txn):
		return False
	b = frappe.get_doc("TEX Booking", booking, for_update=True)
	if booking_svc.live_duplicate(booking):
		return False
	back = _held_when_expired(b, set(locked))
	if from_db(b.paid_amount, b.currency) + sum(back.values(), ZERO) + amount < from_db(b.amount_due_now, b.currency):
		return False
	frappe.db.savepoint(REVIVE_SAVEPOINT)
	messages = frappe.local.message_log
	mark = len(messages)
	try:
		if not booking_svc.revive_expired(booking, reason=f"payment {txn.name} captured in time"):
			return False
		for name, held in sorted(back.items()):
			pay.allocate(name, booking=booking, amount=held, reason="the booking was taken back (paid in time)",
			             _system=True, idempotency_key=f"revived:{booking}:{name}")
			settled(name)
	except frappe.ValidationError as e:
		undo_step(e, REVIVE_SAVEPOINT)
		del messages[mark:]       # a refusal here is a note for staff, never a message to the guest
		return False
	return True


def _held_when_expired(b, locked: set) -> dict:
	"""The money booking ``b`` held when it expired (taken off it, B2), still unused on each charge
	(not refunded, not allocated elsewhere, no refund in flight), of the charges ``locked`` before the
	booking: charge → amount."""
	from kamra.tex.payments import service as pay

	out = {}
	# a locking read: the releases as they are now, an expiry committed after this request began included
	for r in frappe.db.sql("""SELECT `transaction`, amount, currency, idempotency_key FROM `tabTEX Payment Allocation`
	                          WHERE booking=%s AND allocation_type='Release' LOCK IN SHARE MODE""", b.name, as_dict=True):
		if r.transaction not in locked or r.idempotency_key != pay.ns_key(b.property, f"expired:{b.name}:{r.transaction}",
		                                                                   "release"):
			continue
		txn = frappe.db.get_value(TXN, r.transaction, ["amount", "currency"], as_dict=True, for_update=True)
		free = (from_db(txn.amount, txn.currency) - pay.allocated_of(r.transaction, lock=True)
		        - pay.refunded_of(r.transaction, lock=True) - pay.in_flight_of(r.transaction, lock=True))
		held = min(from_db(r.amount, r.currency), free)
		if held > ZERO:
			out[r.transaction] = held
	return out


def money_off_expired(booking: str, *, now: datetime | None = None, send_mail: bool = True):
	"""B2: the money a booking held when it expired before it was paid in full (a first of two
	links, a part paid at the desk) comes off the cancelled booking — never a negative balance —
	and each charge it came from goes to reconciliation for staff (``send_mail``: False from a
	migration). → the amount taken off."""
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
		_flag(txn, booking, EXPIRED_UNPAID, "Action Required", note, held, send_mail=send_mail)
		taken += held
	return taken


def _flag(txn, booking: str, why: str, state: str, note: str, amount, *, send_mail: bool = True, **extra) -> None:
	"""Put a charge's money in reconciliation (never twice), audited; the team and the payer are told
	(``send_mail``)."""
	if frappe.db.get_value(TXN, txn.name, "reconciliation") in OPEN:
		return
	frappe.db.set_value(TXN, txn.name, {"reconciliation": state, "reconciliation_note": note[:1000]},
	                    update_modified=False)
	audit("payment.reconciliation_required", reference_doctype=TXN, reference_name=txn.name, property=txn.property,
	      new={"booking": booking, "why": why, "state": state, "amount": to_str(amount), "currency": txn.currency,
	           **extra})
	if send_mail:
		from kamra.tex.services import notify

		notify.reconciliation(txn, booking, state, note, amount)      # the team and the guest are told (B5)


def guest_notice(booking: str | None) -> str | None:
	"""What the guest's page says about money the booking could not take (B5): "refund" when it is
	refunded (or queued for it), "contact" when the hotel decides, None when there is none. Only a
	cancelled booking has any: money it could not take cancelled (or expired) it."""
	if not booking or frappe.db.get_value("TEX Booking", booking, "status") != "Cancelled":
		return None
	states = set(frappe.db.sql_list(
		"""SELECT reconciliation FROM `tabTEX Payment Transaction` WHERE txn_type='Charge'
		   AND reconciliation IN ('Action Required', 'Refund Queued', 'Refunded')
		   AND (booking=%(b)s OR payment_link IN (SELECT name FROM `tabTEX Payment Link` WHERE booking=%(b)s))""",
		{"b": booking}))
	if "Action Required" in states:
		return "contact"
	return "refund" if states else None


def refusal(why: str, b, amount) -> str:
	"""What staff are told when they allocate money a booking cannot take (never done silently)."""
	if why == BOOKING_CANCELLED:
		owed = from_db(b.total_amount, b.currency) - from_db(b.paid_amount, b.currency)
		return _("Booking {0} is cancelled and owes {1} {2}: {3} {2} cannot be allocated to it. Book the stay "
		         "again and allocate the payment there, or refund it.").format(
			b.name, to_str(max(owed, ZERO)), b.currency, to_str(amount))
	if why == ROOMS_RELEASED:
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
	leaves it (``Refunded`` / ``Resolved``); a refund still waiting for its answer settles nothing
	(it may not be made). One that left it whose money is loose again — a refund found not made after
	all — goes back to ``Action Required`` (C4). Called under the charge's lock, after every way its
	money moves (allocation, refund through the gateway or outside it, a refund's outcome recorded or
	corrected)."""
	from kamra.tex.payments import service as pay

	# a locking read: its state as it is now, never this transaction's older snapshot of it (E5)
	row = frappe.db.get_value(TXN, transaction, ["reconciliation", "amount", "currency", "property"], as_dict=True,
	                          for_update=True)
	if not row or not row.reconciliation:
		return
	amount = from_db(row.amount, row.currency)
	refunded = pay.refunded_of(transaction, lock=True)
	left = amount - pay.allocated_of(transaction, lock=True) - refunded
	if row.reconciliation in OPEN:
		if left > ZERO or pay.in_flight_of(transaction, lock=True) > ZERO:
			return
		state = "Refunded" if refunded >= amount else "Resolved"
	elif left > ZERO:
		state = "Action Required"
	else:
		return
	frappe.db.set_value(TXN, transaction, "reconciliation", state, update_modified=False)
	audit("payment.reconciliation_" + state.lower().replace(" ", "_"), reference_doctype=TXN,
	      reference_name=transaction, property=row.property, new={"state": state, "left": to_str(left)})


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
			from kamra.tex.services import notify

			notify.team_notice(txn, txn.booking, state, f"The automatic refund did not go through: {note}.", free)
		if not frappe.flags.in_test:
			frappe.db.commit()  # nosemgrep: frappe-manual-commit -- one charge's refund per transaction
	return {"refunded": done}
