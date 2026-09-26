"""Payment holds (K-2; R-17, R-40, R-41): how long a booking's rooms wait for its payment.

A booking waiting for its payment (Pending Payment / Held) holds its rooms until its hold
deadline, the ``hold_expires_on`` of its rooms. A payment attempt started before that deadline
keeps them until the attempt's own deadline (``TEX Payment Transaction.expires_at``), recorded on
the booking as ``payment_attempt_until``: a gateway checkout is open for ``CHECKOUT_MINUTES``; a
bank transfer is open until the hold deadline and never extends it. Nothing else keeps the rooms:
a Pending charge past its deadline is stale and holds no inventory.

Locks: the booking row is the one place a hold is decided. ``open_attempt`` and
``booking.expire_booking`` lock the booking (then its rooms), so an attempt is either recorded
before an expiry reads the booking, or refused because the booking expired."""

from __future__ import annotations

from datetime import datetime

import frappe
from frappe import _
from frappe.utils import add_to_date, get_datetime, now_datetime

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
TRANSFER = "Bank Transfer"


def link_expiry(booking: str | None, wanted: datetime, now: datetime | None = None) -> datetime:
	"""A payment link of a booking waiting for its payment never outlives the booking's hold (its
	money would arrive once the rooms are gone): → the earlier of ``wanted`` and the hold deadline,
	refused (``HoldExpired``) once the hold is over. A link of no held booking keeps ``wanted``."""
	if not booking or frappe.db.get_value("TEX Booking", booking, "status") not in HOLDING:
		return wanted
	now = get_datetime(now or now_datetime())
	deadline = hold_deadline(booking)
	if not deadline or deadline <= now:
		raise HoldExpired(_("The time to pay for booking {0} is over; its rooms are no longer held. "
		                    "Please book again.").format(booking))
	return min(get_datetime(wanted), deadline)


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


def attempt_deadline(txn) -> datetime:
	"""When a charge stops counting as a payment in flight: its ``expires_at``; a charge recorded
	before attempts had one, ``CHECKOUT_MINUTES`` after it was created."""
	if txn.get("expires_at"):
		return get_datetime(txn.expires_at)
	return add_to_date(get_datetime(txn.creation), minutes=CHECKOUT_MINUTES)


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
