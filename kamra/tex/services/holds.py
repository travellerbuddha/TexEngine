"""Payment holds (K-2; R-17, R-40, R-41): how long a booking's rooms wait for its payment.

A booking waiting for its payment (Pending Payment / Held) holds its rooms until its hold
deadline, the ``hold_expires_on`` of its rooms. A payment attempt started before that deadline
keeps them until the attempt's own deadline (``TEX Payment Transaction.expires_at``), recorded on
the booking as ``payment_attempt_until``: a gateway checkout is open for ``CHECKOUT_MINUTES``; a
bank transfer is open until the hold deadline and never extends it. Nothing else keeps the rooms:
a Pending charge past its deadline is stale and holds no inventory. Its money is late by the
gateway's clock when the gateway states it (``paid_in_time``, B4), never by when its news arrived.

Locks: the booking row is the one place a hold is decided. ``open_attempt`` and
``booking.expire_booking`` lock the booking (then its rooms), so an attempt is either recorded
before an expiry reads the booking, or refused because the booking expired."""

from __future__ import annotations

import json
from datetime import datetime, time

import frappe
from frappe import _
from frappe.utils import add_to_date, get_datetime, getdate, now_datetime

from kamra.tex.security.audit import audit, log_exception
from kamra.tex.services.refusals import with_code

HOLDING = ("Pending Payment", "Held")
# K-2d: the hold of each payment method — (TEX Settings field, hotel override on Property, default)
CARD, LINK = "Card", "Payment Link"
HOLD_SETTINGS = {CARD: ("hold_minutes", "tex_hold_minutes_card", 20),
                 LINK: ("hold_minutes_link", "tex_hold_minutes_link", 1440),
                 "Bank Transfer": ("hold_minutes_transfer", "tex_hold_minutes_transfer", 2880)}
# C2 (user decision): a transfer booked on the web — by anyone — holds shorter and takes few rooms
WEB_TRANSFER = ("hold_minutes_transfer_web", "tex_hold_minutes_transfer_web", 1440)
WEB_TRANSFER_MAX_ROOMS = 2
MIN_HOLD_MINUTES = 5
# how long a gateway checkout started within the hold keeps the rooms (a hosted payment page's
# life); finite, so a charge left Pending never holds inventory
CHECKOUT_MINUTES = 30
# how far a gateway attempt may run past the booking's hold: the guest may be inside 3-D Secure (C1)
THREEDS_MARGIN_MINUTES = 5
# how far a gateway's clock and TEX's may differ
CLOCK_SKEW_MINUTES = 5
TRANSFER = "Bank Transfer"


def hold_for_link(booking: str | None, wanted: datetime, now: datetime | None = None) -> tuple[datetime, datetime | None]:
	"""B6: a payment link sent for a booking waiting for its payment (an agent booked by card, then sends
	the guest a link) holds the booking's rooms for the link hold (``resolve_hold_minutes`` for a payment
	link: the hotel's, else TEX Settings, 24 hours by default), never beyond ``wanted`` nor the end of
	the arrival day (D7, E3), and never shortens a longer hold; the link lives as long as the hold. Under the booking's lock and its rooms'
	(the order of every hold decision); refused (``HoldExpired``) once the hold is over, and for a
	booking neither waiting nor confirmed (D5). → (the link's expiry, until when the rooms are held); a
	link of a confirmed booking, or of none, keeps ``wanted`` and holds nothing."""
	wanted = get_datetime(wanted)
	if not booking:
		return wanted, None
	b = frappe.get_doc("TEX Booking", booking, for_update=True)          # as it is now
	if b.status not in HOLDING:
		from kamra.tex.services import late_payments

		# a confirmed booking's balance may be asked by a link; a cancelled or expired booking gets
		# none — never a link for rooms it no longer holds (D5)
		if b.status not in late_payments.TAKES_MONEY or not late_payments.confirmed_rooms(booking):
			frappe.throw(_("Booking {0} is {1}: it cannot be paid by a link. Book the stay again.").format(
				booking, _(b.status)))
		return wanted, None
	now = get_datetime(now or now_datetime())
	deadline = hold_deadline(booking, lock=True)
	if not deadline or (deadline <= now and not in_flight(b, now)):
		# the rooms are let go at once (P1-9); a card attempt still open (3-D Secure) keeps them for its
		# recovery link, which extends them below
		_expire_and_refuse(booking, deadline, now)
	# never past the end of the arrival day (D7, E3): a link sent that day is paid by its night
	arrival = datetime.combine(min(getdate(r.check_in) for r in b.rooms if r.status in HOLDING), time(23, 59, 59))
	until = min(wanted, add_to_date(now, minutes=resolve_hold_minutes(b.property, LINK)), arrival)
	if until > deadline:
		for name in sorted(r.reservation for r in b.rooms):
			status, held = frappe.db.get_value("Reservation", name, ["status", "hold_expires_on"], for_update=True)
			if status in HOLDING and held:          # a room held without a deadline keeps none (never guessed)
				frappe.db.set_value("Reservation", name, "hold_expires_on", until, update_modified=False)
		audit("booking.hold_extended", reference_doctype="TEX Booking", reference_name=booking, property=b.property,
		      old={"hold_until": str(deadline)}, new={"hold_until": str(until)}, reason="payment link sent")
		deadline = until
	return min(wanted, deadline), deadline


def hold_for_review(booking: str, txn, now: datetime | None = None) -> tuple[datetime | None, datetime] | None:
	"""O-18, D-8: the gateway holds a payment of ``booking`` in its fraud review. A booking waiting for its
	payment keeps its rooms for it — the payment's attempt, and so the booking's, runs until the link hold
	from now, never past the end of the arrival day (``hold_for_link``'s bounds) — once: never shortened,
	never extended again (the caller records the review once). Under the booking's lock, after the
	payment's (link → payment → booking, ADR-066). → (the booking's attempt deadline before, the new one);
	None for a booking not waiting for its payment (a balance, a change): nothing is held."""
	b = frappe.get_doc("TEX Booking", booking, for_update=True)          # as it is now
	if b.status not in HOLDING:
		return None
	now = get_datetime(now or now_datetime())
	rooms = [r for r in b.rooms if r.status in HOLDING] or list(b.rooms)
	arrival = datetime.combine(min(getdate(r.check_in) for r in rooms), time(23, 59, 59))
	until = min(add_to_date(now, minutes=resolve_hold_minutes(b.property, LINK)), arrival)
	before = get_datetime(b.payment_attempt_until) if b.payment_attempt_until else None
	if before and before > until:
		until = before                                                    # never shortened
	frappe.db.set_value("TEX Booking", booking, "payment_attempt_until", until, update_modified=False)
	frappe.db.set_value("TEX Payment Transaction", txn.name, "expires_at", until, update_modified=False)
	return before, until


def after_review_rejected(booking: str, txn: str, before: datetime | None) -> datetime | None:
	"""O-18, D-8: the gateway rejected a payment it held in review; its hold is over. The booking's attempt
	deadline goes back to the later of ``before`` (what it was when the review began) and the latest
	deadline of its other Pending charges (its own and its links'); None when neither exists. Under the
	booking's lock. → the deadline now (None: nothing keeps its rooms beyond its own hold)."""
	b = frappe.get_doc("TEX Booking", booking, for_update=True)
	if b.status not in HOLDING:
		return None
	# a charge without expires_at holds no rooms: not counted
	others = frappe.db.sql("""SELECT MAX(expires_at) FROM `tabTEX Payment Transaction`
	                          WHERE txn_type = 'Charge' AND status = 'Pending' AND name != %(t)s
	                            AND expires_at IS NOT NULL
	                            AND (booking = %(b)s OR payment_link IN
	                                 (SELECT name FROM `tabTEX Payment Link` WHERE booking = %(b)s))""",
	                       {"t": txn, "b": booking})[0][0]
	back = max((get_datetime(v) for v in (before, others) if v), default=None)
	frappe.db.set_value("TEX Booking", booking, "payment_attempt_until", back, update_modified=False)
	return back


def after_link_closed(booking: str | None, now: datetime | None = None) -> datetime | None:
	"""D7, E3: a cancelled link no longer holds its booking's rooms. The hold goes back to the latest of
	what the booking's own payment method gave it (before any link extended it), the expiry of its
	other links — open, or paid in full or in part (they held the rooms while their money came) — and
	now plus its payment method's hold (the guest may still pay, at the desk or by card); never longer
	than it is. Under the booking's lock (after the link's). → until when its rooms are held (None:
	they are not held for it)."""
	if not booking:
		return None
	b = frappe.get_doc("TEX Booking", booking, for_update=True)
	if b.status not in HOLDING:
		return None
	first = frappe.get_all("TEX Audit Event", filters={"action": "booking.hold_extended", "reference_name": booking},
	                       fields=["old_value"], order_by="event_time asc, creation asc", limit=1)
	current = hold_deadline(booking, lock=True)
	if not first or not current:
		return current
	links = frappe.get_all("TEX Payment Link", filters={"booking": booking,
	                                                    "status": ("in", ["Active", "Partially Paid", "Paid"])},
	                       pluck="expires_at")
	floor = add_to_date(get_datetime(now or now_datetime()),
	                    minutes=resolve_hold_minutes(b.property, b.payment_method, web=b.created_via == "Booking Engine"))
	back = max([get_datetime(json.loads(first[0].old_value)["hold_until"]), floor,
	            *(get_datetime(x) for x in links if x)])
	if back >= current:
		return current
	for name in sorted(r.reservation for r in b.rooms):
		status, held = frappe.db.get_value("Reservation", name, ["status", "hold_expires_on"], for_update=True)
		if status in HOLDING and held:
			frappe.db.set_value("Reservation", name, "hold_expires_on", back, update_modified=False)
	audit("booking.hold_restored", reference_doctype="TEX Booking", reference_name=booking, property=b.property,
	      old={"hold_until": str(current)}, new={"hold_until": str(back)}, reason="payment link cancelled")
	return back


def resolve_hold_minutes(property: str, payment_method: str | None, *, web: bool = False) -> int:
	"""How long a booking of ``property`` paid by ``payment_method`` keeps its rooms waiting for
	its payment (K-2d), the one place every booking and payment path asks: the hotel's override
	for the method, else TEX Settings, else the default (card 20 minutes, payment link 24 hours,
	bank transfer 48 hours; ``web``: a transfer booked on the public web, 24 hours, C2). A method with no
	hold of its own (a gateway card checkout, anything unknown) holds as a card does. Never below
	``MIN_HOLD_MINUTES``."""
	setting, override, default = WEB_TRANSFER if web and payment_method == TRANSFER else HOLD_SETTINGS.get(
		payment_method or CARD, HOLD_SETTINGS[CARD])
	minutes = frappe.db.get_value("Property", property, override) if property else None
	if not minutes:
		minutes = frappe.db.get_single_value("TEX Settings", setting) or default
	return max(MIN_HOLD_MINUTES, int(minutes))


class HoldExpired(frappe.ValidationError):
	"""The booking's hold is over: no new payment attempt may keep its rooms."""
	code = "HOLD_EXPIRED"                        # the guest's refusal code (G-70a)


EXPIRE_SAVEPOINT = "tex_hold_over"


def _expire_and_refuse(booking: str, deadline: datetime | None, now: datetime):
	"""P1-9: an attempt or a link refused because the booking's hold is over, with no attempt open, lets its
	rooms go now rather than at the next 5-minute run: the booking expires (the caller holds its lock: the
	order booking → rooms) and that is committed before the refusal, which Frappe rolls back. The commit
	also puts what the request did before on record (a link it just found expired). Raises ``HoldExpired``."""
	if deadline:
		from kamra.tex.payments.service import _commit_step  # payments.service imports this module
		from kamra.tex.services import booking as booking_svc
		from kamra.tex.services.txn import undo_step

		frappe.db.savepoint(EXPIRE_SAVEPOINT)
		try:
			booking_svc.expire_booking(booking, now=now)
		except Exception as e:
			undo_step(e, EXPIRE_SAVEPOINT)
			log_exception(f"TEX booking expiry failed for {booking}")
		_commit_step()
	raise HoldExpired(_("The time to pay for booking {0} is over; its rooms are no longer held. "
	                    "Please book again.").format(booking))


def hold_deadline(booking: str, *, lock: bool = False) -> datetime | None:
	"""The booking's hold deadline: the earliest ``hold_expires_on`` of its rooms still holding
	inventory for it. ``lock``: a locking read (the rows as they are now, under the booking lock)."""
	rows = frappe.db.sql(
		"""SELECT hold_expires_on FROM `tabReservation`
		   WHERE tex_booking=%(b)s AND status IN %(s)s AND hold_expires_on IS NOT NULL"""
		+ (" LOCK IN SHARE MODE" if lock else ""), {"b": booking, "s": HOLDING})
	deadlines = [get_datetime(r[0]) for r in rows]
	return min(deadlines) if deadlines else None


def in_flight(b, now: datetime | None = None) -> bool:
	"""Whether a payment attempt started within the hold is still open (``b``: the booking)."""
	until = b.get("payment_attempt_until")
	return bool(until) and get_datetime(until) > get_datetime(now or now_datetime())


def attempt_deadline(txn) -> datetime | None:
	"""When a charge's payment attempt closed: its ``expires_at``; None for a charge of no booking
	waiting for its payment (it held no rooms)."""
	return get_datetime(txn.expires_at) if txn.get("expires_at") else None


def paid_in_time(txn) -> bool:
	"""B4, D3: whether the gateway captured (or authorised) the charge while its attempt was open, by
	the gateway's own clock (``captured_at``: the virtual POS's transaction time, the mock's server
	clock, a bank transfer's value date), however late its news reached TEX (a delayed notification,
	staff verifying after an outage). ``CLOCK_SKEW_MINUTES`` either side of the attempt; a time from
	before the charge existed or after its news came is not believed. A charge whose gateway states
	no time (iyzico, Sipay), or that held no rooms, is judged by when its news arrives."""
	until, at = attempt_deadline(txn), txn.get("captured_at")
	if not until or not at:
		return False
	at, created = get_datetime(at), get_datetime(txn.creation)
	if txn.get("provider") == TRANSFER:
		# a value date is a day: money on the account by the day the hold ended is in time
		return created.date() <= at.date() <= min(until.date(), get_datetime(txn.completed_at or now_datetime()).date())
	skew = CLOCK_SKEW_MINUTES
	news = get_datetime(txn.completed_at or now_datetime())
	return (add_to_date(created, minutes=-skew) <= at <= add_to_date(until, minutes=skew)
	        and at <= add_to_date(news, minutes=skew))


def open_attempt(booking: str, method: str | None, now: datetime | None = None) -> datetime | None:
	"""A new payment attempt for a booking, under the booking lock (C1: one rule). It may start while
	the booking's rooms are held for it — its hold is not over, or an earlier attempt still keeps them
	(a declined card tries again) — else ``HoldExpired``. A gateway attempt keeps the rooms for
	``CHECKOUT_MINUTES`` but never more than ``THREEDS_MARGIN_MINUTES`` past the hold (the guest may be
	inside 3-D Secure when it ends), nor past an earlier attempt's own deadline beyond that; a bank
	transfer's lasts until the hold ends. → the attempt's deadline; the booking keeps its rooms until
	then. A booking not waiting for its payment (a balance, a change of a confirmed stay) holds
	nothing: → None."""
	now = get_datetime(now or now_datetime())
	b = frappe.get_doc("TEX Booking", booking, for_update=True)   # as it is now
	if b.status not in HOLDING:
		return None
	deadline = hold_deadline(booking, lock=True)
	if not deadline or (deadline <= now and not in_flight(b, now)):
		_expire_and_refuse(booking, deadline, now)
	if method == TRANSFER:
		if deadline <= now:
			# a transfer lasts until the hold ends, never past it: a card attempt still open keeps the rooms,
			# no transfer is started beside it (P1-9)
			raise with_code(HoldExpired(_("The time to pay for booking {0} by bank transfer is over. Please pay by "
			                              "card, or book again.").format(booking)), "HOLD_EXPIRED_TRANSFER")
		until = deadline
	else:
		cap = add_to_date(deadline, minutes=THREEDS_MARGIN_MINUTES)
		if in_flight(b, now):
			cap = max(cap, get_datetime(b.payment_attempt_until))
		until = min(add_to_date(now, minutes=CHECKOUT_MINUTES), cap)
	if not b.payment_attempt_until or get_datetime(b.payment_attempt_until) < until:
		frappe.db.set_value("TEX Booking", booking, "payment_attempt_until", until, update_modified=False)
	return until
