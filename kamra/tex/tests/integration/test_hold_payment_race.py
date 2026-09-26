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

import threading
from unittest import mock

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import add_to_date, now_datetime

from kamra.reservation_state import expire_holds
from kamra.tex.api import public
from kamra.tex.money import D
from kamra.tex.payments import service as pay
from kamra.tex.services import booking, quoting
from kamra.tex.tests.integration import fixtures as fx
from kamra.tex.tests.integration.test_commercial_flows import GUEST, setup_site_and_payments
from kamra.tex.tests.integration.test_concurrency import _cleanup, _cleanup_payments
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

	def book(self, rooms: int = 1, method: str = "Card", room: str = "STD", status: str = "Pending Payment",
	         rate_plan: str = "FLEX", **kw) -> dict:
		res = quoting.search(properties=[fx.PROPERTY], check_in=fx.d(6, 10), check_out=fx.d(6, 13),
		                     rooms=[{"adults": 2}] * rooms, market="DE", channel="DIRECT_WEB", currency="EUR")
		offer = pick(res["properties"][0], room_code=room, rate_plan_code=rate_plan)
		quotes = quoting.create_quotes([{"offer_key": r["offer_key"]} for r in offer["rooms"]])
		b = booking.create_booking(quote_ids=[r["quote_id"] for r in quotes["rooms"]], guest=GUEST,
		                           payment_method=method, **kw)
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


def paid(b: dict) -> D:
	return D(frappe.db.get_value("TEX Booking", b["booking"], "paid_amount"))


class TestMoneyForBookingsThatCannotTakeIt(HoldCase):
	"""K-2c: every way money reaches a booking — a gateway callback, a bank transfer, a manual
	payment, staff allocating — keeps to the booking's lifecycle: money a cancelled or expired
	booking cannot take is never written on it (no negative balance) and never lost."""

	def setUp(self):
		super().setUp()
		bank = fx.ensure("TEX Payment Provider Account", {"property": fx.PROPERTY, "provider": "Bank Transfer"},
		                 {"label": "Bank transfer", "property": fx.PROPERTY, "provider": "Bank Transfer",
		                  "environment": "Sandbox", "enabled": 1, "currencies": "EUR"})
		fx.ensure("TEX Payment Method Rule", {"property": fx.PROPERTY, "method": "Bank Transfer"},
		          {"property": fx.PROPERTY, "method": "Bank Transfer", "provider_account": bank, "priority": 5})

	def test_a_payment_for_a_cancelled_booking_is_kept_off_it(self):
		b = self.book()
		payment = self.start_payment(b)
		booking.cancel_reservation(self.rooms(b)[0], reason="the guest called to cancel")
		self.assertEqual(self.statuses(b), ("Cancelled", ["Cancelled"]))
		with mock.patch("kamra.tex.services.notify.booking_confirmed") as mailed:
			self.assertEqual(self.pays(payment)["status"], "Succeeded")
		mailed.assert_not_called()
		self.assertEqual(self.statuses(b), ("Cancelled", ["Cancelled"]))
		self.assertEqual(paid(b), D(0))                                      # never a negative balance
		self.assertEqual(pay.allocated_of(payment["transaction"]), D(0))
		self.assertEqual(txn_state(payment["transaction"]).reconciliation, "Action Required")

	def test_a_late_bank_transfer_is_kept_off_its_expired_booking(self):
		b = self.book(method="Bank Transfer")
		transfer = public.pay_booking(token=b["manage_token"], payment_method="Bank Transfer")
		passes(b["booking"], 2 * 24 * 60 + 5)                      # a transfer's 48-hour hold is over
		run_expiry_jobs()
		self.assertEqual(self.statuses(b), ("Cancelled", ["Cancelled"]))
		out = pay.mark_transfer_received(transfer["transaction"], reference="EFT-2027-001")
		self.assertEqual(out["status"], "Succeeded")                           # the money is on record
		self.assertEqual(out["reconciliation"], "Action Required")             # staff see it at once
		self.assertEqual(self.statuses(b), ("Cancelled", ["Cancelled"]))
		self.assertEqual(paid(b), D(0))
		self.assertEqual(confirmations(b), 0)
		# marking it again is refused: the transfer is recorded once
		with self.assertRaises(frappe.ValidationError):
			pay.mark_transfer_received(transfer["transaction"], reference="EFT-2027-001")

	def test_a_manual_payment_for_an_expired_booking_is_kept_off_it(self):
		b = self.book()
		passes(b["booking"], 25)
		run_expiry_jobs()
		out = pay.record_manual(booking=b["booking"], amount=b["due_now"], method="Cash", reference="till 3",
		                        idempotency_key=f"k2c-cash-{b['booking']}")
		self.assertEqual(out["reconciliation"], "Action Required")
		self.assertEqual(self.statuses(b), ("Cancelled", ["Cancelled"]))
		self.assertEqual(paid(b), D(0))

	def test_staff_cannot_allocate_money_to_a_cancelled_booking(self):
		source = self.book(method="Pay at Hotel", status="Confirmed")
		txn = pay.record_manual(booking=source["booking"], amount="100", method="Cash", reference="till 4",
		                        idempotency_key=f"k2c-src-{source['booking']}")["transaction"]
		pay.release(txn, booking=source["booking"], amount="100", reason="to move it")
		b = self.book()
		passes(b["booking"], 25)
		run_expiry_jobs()
		with self.assertRaises(frappe.ValidationError):
			pay.allocate(txn, booking=b["booking"], amount="100", reason="wrong booking")
		self.assertEqual(paid(b), D(0))
		self.assertEqual(pay.allocated_of(txn), D(0))

	def test_a_cancellation_fee_is_still_paid_on_a_cancelled_booking(self):
		b = self.book(rate_plan="NRF", method="Card", status="Confirmed", confirm_without_payment=True)
		booking.cancel_reservation(self.rooms(b)[0], reason="the guest cancelled")
		fee = D(frappe.db.get_value("TEX Booking", b["booking"], "total_amount"))
		self.assertGreater(fee, D(0))                                          # non-refundable: the stay is owed
		out = pay.record_manual(booking=b["booking"], amount=str(fee), method="Cash", reference="fee",
		                        idempotency_key=f"k2c-fee-{b['booking']}")
		self.assertFalse(out.get("reconciliation"))
		self.assertEqual(paid(b), fee)


class TestLastRoomRace(IntegrationTestCase):
	"""K-2 acceptance, under real concurrency (each side its own connection, fixtures committed).

	One Deluxe room is left. Booking A holds it and starts its card payment; its hold and its
	checkout end and the expiry job gives the room back. Then, at the same instant, A's late
	payment arrives and guest B books the last room. B gets it and keeps it; A never gets it
	back, is never confirmed and nothing is sent to A; the room is never sold twice; A's money
	is on record, off its booking, in reconciliation."""

	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		frappe.set_user("Administrator")  # nosemgrep: frappe-setuser -- test setup
		_cleanup()
		_cleanup_payments()
		cls.f = fx.base_setup()
		fx.create_contract(cls.f, code="CONC")
		acc = fx.ensure("TEX Payment Provider Account", {"property": fx.PROPERTY, "provider": "Mock"},
		                {"label": "Sandbox gateway", "property": fx.PROPERTY, "provider": "Mock",
		                 "environment": "Sandbox", "enabled": 1, "currencies": "EUR"})
		fx.ensure("TEX Payment Method Rule", {"property": fx.PROPERTY, "method": "Card"},
		          {"property": fx.PROPERTY, "method": "Card", "provider_account": acc, "priority": 10})
		frappe.set_user("Guest")  # nosemgrep: frappe-setuser -- guest booking path
		prop = quoting.search(properties=[fx.PROPERTY], check_in=fx.d(8, 20), check_out=fx.d(8, 22),
		                      rooms=[{"adults": 2}], market="DE", channel="DIRECT_WEB",
		                      currency="EUR")["properties"][0]
		offer = pick(prop, room_code="DLX")
		quotes = [quoting.create_quote(offer["rooms"][0]["offer_key"])["quote_id"] for _ in range(3)]
		guest = {"first_name": "Pre", "last_name": "Booked", "email": "pre.k2@example.com"}
		booking.create_booking(quote_ids=[quotes[0]], guest=guest, payment_method="Pay at Hotel")
		cls.a = booking.create_booking(quote_ids=[quotes[1]], guest=dict(guest, first_name="Anna"),
		                               payment_method="Card")
		cls.payment = public.pay_booking(token=cls.a["manage_token"], payment_method="Card")
		cls.b_quote = quotes[2]
		frappe.set_user("Administrator")  # nosemgrep: frappe-setuser -- test setup
		passes(cls.a["booking"], 60)                      # A's hold and checkout are over
		frappe.db.commit()  # nosemgrep: frappe-manual-commit -- threads need committed fixtures

	@classmethod
	def tearDownClass(cls):
		_cleanup_payments()
		_cleanup()
		super().tearDownClass()

	def _race(self, *sides) -> dict[str, str]:
		site, sites_path = frappe.local.site, frappe.local.sites_path
		barrier = threading.Barrier(len(sides))
		results: dict[str, str] = {}

		def run(who, fn):
			frappe.init(site=site, sites_path=sites_path)
			frappe.connect()
			try:
				frappe.set_user("Guest")  # nosemgrep: frappe-setuser -- a gateway callback, a guest booking
				barrier.wait(timeout=10)
				results[who] = fn()
				frappe.db.commit()  # nosemgrep: frappe-manual-commit -- each side is its own request
			except Exception as e:
				frappe.db.rollback()
				results[who] = f"refused: {type(e).__name__}: {e}"
			finally:
				frappe.destroy()

		threads = [threading.Thread(target=run, args=side) for side in sides]
		for t in threads:
			t.start()
		for t in threads:
			t.join(timeout=60)
		frappe.db.rollback()                              # read what the sides committed
		return results

	def test_a_late_payment_never_takes_the_last_room_back(self):
		booking.expire_pending_bookings()                 # the scheduler gives A's room back
		frappe.db.commit()  # nosemgrep: frappe-manual-commit -- the job's own transaction
		self.assertEqual(frappe.db.get_value("TEX Booking", self.a["booking"], "status"), "Cancelled")

		def late_payment():
			return public.mock_pay(transaction=self.payment["transaction"], outcome="success",
			                       sig=self.payment["fields"]["success_sig"])["status"]

		def b_books():
			return booking.create_booking(quote_ids=[self.b_quote], payment_method="Pay at Hotel", guest={
				"first_name": "Ben", "last_name": "Second", "email": "ben.k2@example.com"})["status"]

		with mock.patch("kamra.tex.services.notify.booking_confirmed") as mailed:
			results = self._race(("a_pays", late_payment), ("b_books", b_books))
		self.assertEqual(results, {"a_pays": "Succeeded", "b_books": "Confirmed"})
		mailed.assert_not_called()
		dlx = self.f["room_types"]["DLX"]
		live = frappe.get_all("Reservation", filters={"room_type": dlx, "status": ("in", ["Confirmed", "Pending Payment",
		                                                                               "Held", "Checked In"])},
		                      pluck="tex_booking")
		self.assertEqual(len(live), 2, live)                                       # never sold twice
		self.assertNotIn(self.a["booking"], live)                                  # A never takes it back
		self.assertEqual(frappe.db.get_value("TEX Booking", self.a["booking"], ["status", "paid_amount"]),
		                 ("Cancelled", 0))
		self.assertFalse(frappe.db.exists("TEX Audit Event", {"action": "booking.confirm",
		                                                      "reference_name": self.a["booking"]}))
		t = txn_state(self.payment["transaction"])
		self.assertEqual(t.status, "Succeeded")                                    # the money is not lost
		self.assertIn(t.reconciliation, ("Action Required", "Refund Queued"))
		self.assertEqual(pay.allocated_of(self.payment["transaction"]), D(0))
		# the gateway calling again changes nothing
		again = self._race(("a_pays_again", late_payment))
		self.assertEqual(again, {"a_pays_again": "Succeeded"})
		self.assertEqual(frappe.db.count("TEX Audit Event", {"action": "payment.reconciliation_required",
		                                                     "reference_name": self.payment["transaction"]}), 1)


class TestHoldPolicy(HoldCase):
	"""K-2d: one resolver decides how long a booking's rooms wait for its payment, by payment
	method (card 20 minutes, payment link 24 hours, bank transfer 48 hours by default), each
	overridable per hotel; a payment link of a held booking never outlives its hold."""

	def hold_minutes(self, b: dict) -> int:
		sale_at = frappe.db.get_value("TEX Booking", b["booking"], "sale_at")
		until = frappe.get_all("Reservation", filters={"tex_booking": b["booking"]}, pluck="hold_expires_on")[0]
		return round((until - sale_at).total_seconds() / 60)

	def test_each_payment_method_has_its_own_hold(self):
		self.assertEqual(self.hold_minutes(self.book(method="Card")), 20)
		self.assertEqual(self.hold_minutes(self.book(method="Payment Link")), 1440)
		self.assertEqual(self.hold_minutes(self.book(method="Bank Transfer")), 2880)

	def test_the_global_holds_are_tex_settings(self):
		frappe.db.set_single_value("TEX Settings", {"hold_minutes": 15, "hold_minutes_link": 720,
		                                           "hold_minutes_transfer": 1440})
		self.assertEqual(self.hold_minutes(self.book(method="Card")), 15)
		self.assertEqual(self.hold_minutes(self.book(method="Payment Link")), 720)
		self.assertEqual(self.hold_minutes(self.book(method="Bank Transfer")), 1440)

	def test_a_hotel_overrides_each_hold_and_a_blank_one_falls_back(self):
		frappe.db.set_value("Property", fx.PROPERTY, {"tex_hold_minutes_card": 45, "tex_hold_minutes_link": 600,
		                                              "tex_hold_minutes_transfer": 4320})
		self.assertEqual(self.hold_minutes(self.book(method="Card")), 45)
		self.assertEqual(self.hold_minutes(self.book(method="Payment Link")), 600)
		self.assertEqual(self.hold_minutes(self.book(method="Bank Transfer")), 4320)
		frappe.db.set_value("Property", fx.PROPERTY, "tex_hold_minutes_link", 0)          # left blank
		self.assertEqual(self.hold_minutes(self.book(method="Payment Link")), 1440)

	def test_a_payment_link_never_outlives_its_bookings_hold(self):
		b = self.book(method="Payment Link")
		out = pay.create_link(property=fx.PROPERTY, amount=b["due_now"], currency="EUR", description="Deposit",
		                      expires_hours=72, booking=b["booking"])
		hold = frappe.get_all("Reservation", filters={"tex_booking": b["booking"]}, pluck="hold_expires_on")[0]
		self.assertEqual(frappe.db.get_value("TEX Payment Link", out["link"], "expires_at"), hold)
		passes(b["booking"], 1500)                                   # its 24-hour hold is over
		with self.assertRaises(frappe.ValidationError):
			pay.create_link(property=fx.PROPERTY, amount=b["due_now"], currency="EUR", description="Deposit",
			                booking=b["booking"])

	def test_a_standalone_payment_link_keeps_its_own_validity(self):
		out = pay.create_link(property=fx.PROPERTY, amount="50", currency="EUR", description="Minibar",
		                      expires_hours=72)
		expires = frappe.db.get_value("TEX Payment Link", out["link"], "expires_at")
		self.assertAlmostEqual((expires - now_datetime()).total_seconds() / 3600, 72, delta=0.1)


class TestPartialCancellation(HoldCase):
	"""B1 (audit 1b): a room of a booking still waiting for its payment is cancelled (by staff, or by
	the guest on the manage page). The booking was never confirmed: it keeps waiting for its payment
	with the rooms it has left, which expire with its hold, are confirmed by its payment, and whose
	late payment is judged as any other late payment."""

	def cancel_first(self, b: dict) -> None:
		booking.cancel_reservation(self.rooms(b)[0], reason="one room less")

	def test_the_booking_keeps_waiting_for_its_payment(self):
		b = self.book(rooms=2)
		self.cancel_first(b)
		self.assertEqual(self.statuses(b), ("Pending Payment", ["Cancelled", "Pending Payment"]))
		row = frappe.db.get_value("TEX Booking", b["booking"], ["total_amount", "amount_due_now"], as_dict=True)
		self.assertLessEqual(row.amount_due_now, row.total_amount)          # never asks more than it costs

	def test_the_rooms_left_expire_with_its_hold(self):
		b = self.book(rooms=2)
		self.cancel_first(b)
		passes(b["booking"], 25)
		run_expiry_jobs()
		self.assertEqual(self.statuses(b), ("Cancelled", ["Cancelled", "Cancelled"]))

	def test_its_payment_confirms_the_rooms_left(self):
		b = self.book(rooms=2)
		payment = self.start_payment(b)
		self.cancel_first(b)
		self.assertEqual(self.pays(payment)["status"], "Succeeded")
		self.assertEqual(self.statuses(b), ("Partially Cancelled", ["Cancelled", "Confirmed"]))
		self.assertEqual(confirmations(b), 1)

	def test_its_late_payment_is_judged_as_a_late_payment(self):
		b = self.book(rooms=2)
		payment = self.start_payment(b)
		self.cancel_first(b)
		passes(b["booking"], 60)
		self.assertEqual(self.pays(payment)["status"], "Succeeded")
		self.assertEqual(self.statuses(b), ("Cancelled", ["Cancelled", "Cancelled"]))
		self.assertEqual(txn_state(payment["transaction"]).reconciliation, "Action Required")
		self.assertEqual(paid(b), D(0))

	def test_p52_puts_stuck_bookings_back_to_waiting_for_their_payment(self):
		from kamra.tex.tests.integration.test_patches import migrate, never_ran

		stuck, waiting, confirmed = self.book(rooms=2), self.book(rooms=2), self.book(rooms=2)
		self.pays(self.start_payment(confirmed))
		for b in (stuck, waiting, confirmed):
			self.cancel_first(b)
			# as the release before B1 left it
			frappe.db.set_value("TEX Booking", b["booking"], "status", "Partially Cancelled")
		passes(stuck["booking"], 25)                                    # its hold is over
		never_ran("p52_partly_cancelled_awaiting_payment")
		migrate("p52_partly_cancelled_awaiting_payment")
		self.assertEqual(self.statuses(stuck), ("Cancelled", ["Cancelled", "Cancelled"]))
		self.assertEqual(self.statuses(waiting), ("Pending Payment", ["Cancelled", "Pending Payment"]))
		self.assertEqual(self.statuses(confirmed), ("Partially Cancelled", ["Cancelled", "Confirmed"]))
		migrate("p52_partly_cancelled_awaiting_payment")                # a second run changes nothing
		self.assertEqual(self.statuses(waiting), ("Pending Payment", ["Cancelled", "Pending Payment"]))


class TestExpiryWithMoney(HoldCase):
	"""B2 (audit 1b): a booking waiting for its payment that was partly paid (a first of two links,
	a part paid at the desk) and then expires never keeps that money as a negative balance: the
	money comes off the cancelled booking into reconciliation, audited with its amount."""

	def test_money_paid_before_the_expiry_goes_to_reconciliation(self):
		b = self.book()
		part = (D(b["due_now"]) / 2).quantize(D("0.01"))
		txn = pay.record_manual(booking=b["booking"], amount=str(part), method="Cash", reference="first half",
		                        idempotency_key=f"b2-half-{b['booking']}")["transaction"]
		self.assertEqual(self.statuses(b), ("Pending Payment", ["Pending Payment"]))   # the rest is still due
		self.assertEqual(paid(b), part)
		passes(b["booking"], 25)
		run_expiry_jobs()
		self.assertEqual(self.statuses(b), ("Cancelled", ["Cancelled"]))
		self.assertEqual(paid(b), D(0))                                               # never a negative balance
		self.assertEqual(pay.allocated_of(txn), D(0))
		t = txn_state(txn)
		self.assertEqual((t.status, t.reconciliation), ("Succeeded", "Action Required"))
		import json

		expired = frappe.get_all("TEX Audit Event", filters={"action": "booking.expire", "reference_name": b["booking"]},
		                         pluck="new_value")
		self.assertEqual(D(json.loads(expired[0])["paid"]), part)                      # the amount is on record
		self.assertTrue(frappe.db.exists("TEX Audit Event", {"action": "payment.reconciliation_required",
		                                                     "reference_name": txn}))
