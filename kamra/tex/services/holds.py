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

from datetime import datetime

import frappe
from frappe import _
from frappe.utils import add_to_date, get_datetime, now_datetime

from kamra.tex.security.audit import audit

HOLDING = ("Pending Payment", "Held")
# K-2d: the hold of each payment method — (TEX Settings field, hotel override on Property, default)
CARD, LINK = "Card", "Payment Link"
HOLD_SETTINGS = {CARD: ("hold_minutes", "tex_hold_minutes_card", 20),
                 LINK: ("hold_minutes_link", "tex_hold_minutes_link", 1440),
                 "Bank Transfer": ("hold_minutes_transfer", "tex_hold_minutes_transfer", 2880)}
MIN_HOLD_MINUTES = 5
# how long a gateway checkout started within the hold keeps the rooms (a hosted payment page's
# life); finite, so a charge left Pending never holds inventory
CHECKOUT_MINUTES = 30
# how far a gateway's clock and TEX's may differ
CLOCK_SKEW_MINUTES = 5
TRANSFER = "Bank Transfer"


def hold_for_link(booking: str | None, wanted: datetime, now: datetime | None = None) -> tuple[datetime, datetime | None]:
	"""B6: a payment link sent for a booking waiting for its payment (an agent booked by card, then sends
	the guest a link) holds the booking's rooms for the link hold (``resolve_hold_minutes`` for a payment
	link: the hotel's, else TEX Settings, 24 hours by default), never beyond ``wanted``, and never
	shortens a longer hold; the link lives as long as the hold. Under the booking's lock and its rooms'
	(the order of every hold decision); refused (``HoldExpired``) once the hold is over. → (the link's
	expiry, until when the rooms are held); a link of no booking waiting for its payment keeps ``wanted``
	and holds nothing."""
	wanted = get_datetime(wanted)
	if not booking:
		return wanted, None
	b = frappe.get_doc("TEX Booking", booking, for_update=True)          # as it is now
	if b.status not in HOLDING:
		return wanted, None
	now = get_datetime(now or now_datetime())
	deadline = hold_deadline(booking, lock=True)
	if not deadline or deadline <= now:
		raise HoldExpired(_("The time to pay for booking {0} is over; its rooms are no longer held. "
		                    "Please book again.").format(booking))
	until = min(wanted, add_to_date(now, minutes=resolve_hold_minutes(b.property, LINK)))
	if until > deadline:
		for name in sorted(r.reservation for r in b.rooms):
			status, held = frappe.db.get_value("Reservation", name, ["status", "hold_expires_on"], for_update=True)
			if status in HOLDING and held:          # a room held without a deadline keeps none (never guessed)
				frappe.db.set_value("Reservation", name, "hold_expires_on", until, update_modified=False)
		audit("booking.hold_extended", reference_doctype="TEX Booking", reference_name=booking, property=b.property,
		      old={"hold_until": str(deadline)}, new={"hold_until": str(until)}, reason="payment link sent")
		deadline = until
	return min(wanted, deadline), deadline


def resolve_hold_minutes(property: str, payment_method: str | None) -> int:
	"""How long a booking of ``property`` paid by ``payment_method`` keeps its rooms waiting for
	its payment (K-2d), the one place every booking and payment path asks: the hotel's override
	for the method, else TEX Settings, else the default (card 20 minutes, payment link 24 hours,
	bank transfer 48 hours). A method with no hold of its own (a gateway card checkout, anything
	unknown) holds as a card does. Never below ``MIN_HOLD_MINUTES``."""
	setting, override, default = HOLD_SETTINGS.get(payment_method or CARD, HOLD_SETTINGS[CARD])
	minutes = frappe.db.get_value("Property", property, override) if property else None
	if not minutes:
		minutes = frappe.db.get_single_value("TEX Settings", setting) or default
	return max(MIN_HOLD_MINUTES, int(minutes))


class HoldExpired(frappe.ValidationError):
	"""The booking's hold is over: no new payment attempt may keep its rooms."""


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
	"""A new payment attempt for a booking: under the booking lock, refused once the hold is over
	(``HoldExpired``); otherwise → the attempt's deadline, and the booking keeps its rooms until
	then. A booking not waiting for its payment (a balance, a change of a confirmed stay) holds
	nothing: → None."""
	now = get_datetime(now or now_datetime())
	b = frappe.get_doc("TEX Booking", booking, for_update=True)   # as it is now
	if b.status not in HOLDING:
		return None
	deadline = hold_deadline(booking, lock=True)
	if not deadline or deadline <= now:
		raise HoldExpired(_("The time to pay for booking {0} is over; its rooms are no longer held. "
		                    "Please book again.").format(booking))
	until = deadline if method == TRANSFER else add_to_date(now, minutes=CHECKOUT_MINUTES)
	if not b.payment_attempt_until or get_datetime(b.payment_attempt_until) < until:
		frappe.db.set_value("TEX Booking", booking, "payment_attempt_until", until, update_modified=False)
	return until
