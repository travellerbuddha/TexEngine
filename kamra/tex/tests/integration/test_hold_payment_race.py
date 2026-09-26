"""K-2 (R-17, R-40, R-41, R-46): a payment hold, a late payment and the inventory never race.

A booking waiting for its payment holds its rooms until its hold deadline. A payment attempt
started before it keeps them until the attempt's own, finite deadline; a stale Pending charge
keeps nothing. The booking and all its rooms expire together, in one transaction (K-2a).

Time passes in these tests by moving every stored deadline of a booking into the past
(``passes``): the hold of its rooms, and the start and deadline of its payment attempts."""

import frappe
from frappe.utils import add_to_date, now_datetime

from kamra.reservation_state import expire_holds
from kamra.tex.api import public
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

	def book(self, rooms: int = 1, method: str = "Card", room: str = "STD") -> dict:
		res = quoting.search(properties=[fx.PROPERTY], check_in=fx.d(6, 10), check_out=fx.d(6, 13),
		                     rooms=[{"adults": 2}] * rooms, market="DE", channel="DIRECT_WEB", currency="EUR")
		offer = pick(res["properties"][0], room_code=room)
		quotes = quoting.create_quotes([{"offer_key": r["offer_key"]} for r in offer["rooms"]])
		b = booking.create_booking(quote_ids=[r["quote_id"] for r in quotes["rooms"]], guest=GUEST,
		                           payment_method=method)
		self.assertEqual(b["status"], "Pending Payment")
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
