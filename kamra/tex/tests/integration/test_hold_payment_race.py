"""K-2 (R-17, R-40, R-41, R-46): a payment hold, a late payment and the inventory never race.

A booking waiting for its payment holds its rooms until its hold deadline. A payment attempt
started before it keeps them until the attempt's own, finite deadline; a stale Pending charge
keeps nothing. The booking and all its rooms expire together, in one transaction (K-2a).

Money arriving once the hold truly ended never confirms the booking at its old price, and never
takes rooms back: it is recorded, kept off the booking and put in reconciliation (``Action
Required`` for staff, or ``Refund Queued`` when the rooms are gone and the gateway refunds by
itself), audited, and no confirmation reaches the guest or the PMS (K-2b).

Time passes in these tests by moving every stored deadline of a booking into the past
(``passes``): the hold of its rooms, and the start and deadline of its payment attempts."""

from unittest import mock

import frappe
from frappe.utils import add_to_date, now_datetime

from kamra.reservation_state import expire_holds
from kamra.tex.api import public
from kamra.tex.money import D
from kamra.tex.payments import service as pay
from kamra.tex.services import booking, quoting
from kamra.tex.tests.integration import fixtures as fx
from kamra.tex.tests.integration.test_commercial_flows import GUEST, setup_site_and_payments
from kamra.tex.tests.integration.test_critical_journey import TexTestCase, pick


def passes(booking_name: str, minutes: int) -> None:
	"""``minutes`` go by for a booking: every deadline and start time it stored moves back."""
	frappe.db.sql("""UPDATE `tabReservation` SET hold_expires_on = hold_expires_on - INTERVAL %(m)s MINUTE
	                 WHERE tex_booking=%(b)s AND hold_expires_on IS NOT NULL""", {"m": minutes, "b": booking_name})
	frappe.db.sql("""UPDATE `tabTEX Payment Transaction` SET creation = creation - INTERVAL %(m)s MINUTE
	                 WHERE booking=%(b)s""", {"m": minutes, "b": booking_name})
	if frappe.db.has_column("TEX Payment Transaction", "expires_at"):
		frappe.db.sql("""UPDATE `tabTEX Payment Transaction` SET expires_at = expires_at - INTERVAL %(m)s MINUTE
		                 WHERE booking=%(b)s AND expires_at IS NOT NULL""", {"m": minutes, "b": booking_name})
	if frappe.db.has_column("TEX Booking", "payment_attempt_until"):
		frappe.db.sql("""UPDATE `tabTEX Booking` SET payment_attempt_until = payment_attempt_until
		                 - INTERVAL %(m)s MINUTE WHERE name=%(b)s AND payment_attempt_until IS NOT NULL""",
		              {"m": minutes, "b": booking_name})


def run_expiry_jobs() -> None:
	"""The scheduled jobs, as they run: the PMS hold expiry, then the TEX booking expiry."""
	expire_holds()
	booking.expire_pending_bookings()


class HoldCase(TexTestCase):
	def setUp(self):
		super().setUp()
		self.account = setup_site_and_payments(self.f)["account"]

	def book(self, rooms: int = 1, method: str = "Card", room: str = "STD", status: str = "Pending Payment") -> dict:
		res = quoting.search(properties=[fx.PROPERTY], check_in=fx.d(6, 10), check_out=fx.d(6, 13),
		                     rooms=[{"adults": 2}] * rooms, market="DE", channel="DIRECT_WEB", currency="EUR")
		offer = pick(res["properties"][0], room_code=room)
		quotes = quoting.create_quotes([{"offer_key": r["offer_key"]} for r in offer["rooms"]])
		b = booking.create_booking(quote_ids=[r["quote_id"] for r in quotes["rooms"]], guest=GUEST,
		                           payment_method=method)
		self.assertEqual(b["status"], status)
		return b

	def start_payment(self, b: dict) -> dict:
		"""The guest pays from the confirmation page (the booking's manage token)."""
		return public.pay_booking(token=b["manage_token"], payment_method="Card")

	def pays(self, payment: dict) -> dict:
		return public.mock_pay(transaction=payment["transaction"], outcome="success",
		                       sig=payment["fields"]["success_sig"])

	def rooms(self, b: dict) -> list[str]:
		return [r["reservation"] for r in b["rooms"]]

	def statuses(self, b: dict) -> tuple[str, list[str]]:
		return (frappe.db.get_value("TEX Booking", b["booking"], "status"),
		        [frappe.db.get_value("Reservation", r, "status") for r in self.rooms(b)])


class TestAtomicExpiry(HoldCase):
	"""K-2a: the booking and its rooms expire together; a payment in flight keeps them only while
	its attempt is open."""

	def test_the_booking_and_all_its_rooms_expire_together(self):
		b = self.book(rooms=2)
		passes(b["booking"], 25)                                   # the 20-minute hold is over
		expire_holds()                   # the PMS job never cancels a TEX booking's room on its own
		self.assertEqual(self.statuses(b), ("Pending Payment", ["Pending Payment", "Pending Payment"]))
		booking.expire_pending_bookings()
		self.assertEqual(self.statuses(b), ("Cancelled", ["Cancelled", "Cancelled"]))
		self.assertTrue(frappe.db.exists("TEX Audit Event", {"action": "booking.expire",
		                                                     "reference_name": b["booking"]}))
		# the job again: nothing more happens
		booking.expire_pending_bookings()
		self.assertEqual(frappe.db.count("TEX Audit Event", {"action": "booking.expire",
		                                                     "reference_name": b["booking"]}), 1)

	def test_a_booking_on_hold_keeps_its_rooms(self):
		b = self.book(rooms=2)
		passes(b["booking"], 10)
		run_expiry_jobs()
		self.assertEqual(self.statuses(b), ("Pending Payment", ["Pending Payment", "Pending Payment"]))

	def test_a_payment_in_flight_keeps_the_rooms_until_it_is_paid(self):
		b = self.book()
		payment = self.start_payment(b)                            # started within the hold
		passes(b["booking"], 25)                                   # hold over, the checkout still open
		run_expiry_jobs()
		self.assertEqual(self.statuses(b), ("Pending Payment", ["Pending Payment"]))
		self.assertEqual(self.pays(payment)["status"], "Succeeded")
		self.assertEqual(self.statuses(b), ("Confirmed", ["Confirmed"]))

	def test_a_stale_pending_payment_keeps_nothing(self):
		b = self.book()
		payment = self.start_payment(b)
		passes(b["booking"], 60)                                   # hold and checkout both over
		run_expiry_jobs()
		self.assertEqual(self.statuses(b), ("Cancelled", ["Cancelled"]))
		# the charge itself is not assumed failed: the gateway may still report it
		self.assertEqual(frappe.db.get_value("TEX Payment Transaction", payment["transaction"], "status"), "Pending")

	def test_no_new_payment_attempt_once_the_hold_is_over(self):
		b = self.book()
		passes(b["booking"], 25)
		with self.assertRaises(frappe.ValidationError):
			self.start_payment(b)
		self.assertFalse(frappe.db.exists("TEX Payment Transaction", {"booking": b["booking"]}))

	def test_a_payment_attempt_has_a_deadline(self):
		b = self.book()
		payment = self.start_payment(b)
		until = frappe.db.get_value("TEX Payment Transaction", payment["transaction"], "expires_at")
		self.assertIsNotNone(until)
		self.assertLessEqual(until, add_to_date(now_datetime(), minutes=31))
		self.assertEqual(frappe.db.get_value("TEX Booking", b["booking"], "payment_attempt_until"), until)


def txn_state(name: str) -> dict:
	return frappe.db.get_value("TEX Payment Transaction", name, ["status", "reconciliation", "reconciliation_note"],
	                           as_dict=True)


def confirmations(b: dict) -> int:
	return frappe.db.count("TEX Audit Event", {"action": "booking.confirm", "reference_name": b["booking"]})


class TestLatePayment(HoldCase):
	"""K-2b: a late payment never confirms a booking whose rooms are not held for it."""

	def test_a_payment_within_the_hold_confirms_the_booking(self):
		b = self.book(rooms=2)
		payment = self.start_payment(b)
		passes(b["booking"], 10)
		self.assertEqual(self.pays(payment)["status"], "Succeeded")
		self.assertEqual(self.statuses(b), ("Confirmed", ["Confirmed", "Confirmed"]))
		self.assertFalse(txn_state(payment["transaction"]).reconciliation)

	def test_a_payment_after_the_hold_and_its_checkout_never_confirms_the_old_quote(self):
		b = self.book()
		payment = self.start_payment(b)
		passes(b["booking"], 60)                 # hold and checkout over; the expiry job has not run yet
		with mock.patch("kamra.tex.services.notify.booking_confirmed") as mailed:
			self.assertEqual(self.pays(payment)["status"], "Succeeded")      # the money is on record
		mailed.assert_not_called()
		self.assertEqual(confirmations(b), 0)
		# the hold truly ended: the booking and its room expire now, never confirmed at the old price
		self.assertEqual(self.statuses(b), ("Cancelled", ["Cancelled"]))
		t = txn_state(payment["transaction"])
		self.assertEqual((t.status, t.reconciliation), ("Succeeded", "Action Required"))
		self.assertIn("free now", t.reconciliation_note)          # availability and price evaluated again
		self.assertIn("price now", t.reconciliation_note)
		self.assertEqual(pay.allocated_of(payment["transaction"]), D(0))   # never written on the booking
		self.assertEqual(D(frappe.db.get_value("TEX Booking", b["booking"], "paid_amount")), D(0))
		self.assertTrue(frappe.db.exists("TEX Audit Event", {"action": "payment.reconciliation_required",
		                                                     "reference_name": payment["transaction"]}))
		# the gateway calling again changes nothing
		self.assertTrue(self.pays(payment).get("replay"))
		self.assertEqual(frappe.db.count("TEX Audit Event", {"action": "payment.reconciliation_required",
		                                                     "reference_name": payment["transaction"]}), 1)
		self.assertEqual(frappe.db.count("TEX Payment Allocation", {"transaction": payment["transaction"]}), 0)

	def test_rooms_given_away_are_never_taken_back_by_a_late_payment(self):
		"""The rooms of a booking still waiting were released before its payment arrived (as the PMS
		job did before K-2a) and the last Deluxe room was sold to another guest meanwhile."""
		self.book(room="DLX", method="Pay at Hotel", status="Confirmed")        # one of the two is sold
		a = self.book(room="DLX")
		payment = self.start_payment(a)                                           # started within the hold
		frappe.db.sql("UPDATE `tabReservation` SET status='Cancelled' WHERE tex_booking=%s", a["booking"])
		b = self.book(room="DLX", method="Pay at Hotel", status="Confirmed")    # the last room, to B
		with mock.patch("kamra.tex.services.notify.booking_confirmed") as mailed:
			self.assertEqual(self.pays(payment)["status"], "Succeeded")
		mailed.assert_not_called()
		self.assertEqual(confirmations(a), 0)
		self.assertNotEqual(frappe.db.get_value("TEX Booking", a["booking"], "status"), "Confirmed")
		self.assertEqual(self.statuses(a)[1], ["Cancelled"])
		self.assertEqual(self.statuses(b), ("Confirmed", ["Confirmed"]))                # B untouched
		dlx = self.f["room_types"]["DLX"]
		live = frappe.db.count("Reservation", {"room_type": dlx, "status": ("in", ["Confirmed", "Pending Payment",
		                                                                             "Held", "Checked In"])})
		self.assertEqual(live, 2)                                                        # never oversold
		# the rooms are gone and the gateway refunds by itself: the refund is queued, then made once
		self.assertEqual(txn_state(payment["transaction"]).reconciliation, "Refund Queued")
		from kamra.tex.services import late_payments

		late_payments.refund_queued()
		late_payments.refund_queued()
		self.assertEqual(txn_state(payment["transaction"]).reconciliation, "Refunded")
		refunds = frappe.get_all("TEX Payment Transaction", filters={"parent_transaction": payment["transaction"],
		                                                             "txn_type": "Refund"}, pluck="status")
		self.assertEqual(refunds, ["Succeeded"])
