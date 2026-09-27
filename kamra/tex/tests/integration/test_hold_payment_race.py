"""K-2 (R-17, R-40, R-41, R-46): a payment hold, a late payment and the inventory never race.

A booking waiting for its payment holds its rooms until its hold deadline. A payment attempt
started before it keeps them until the attempt's own, finite deadline; a stale Pending charge
keeps nothing. The booking and all its rooms expire together, in one transaction (K-2a).

Money for a booking whose rooms are still held for it confirms it at its locked price, however late
it comes (B3 a). Money arriving once its rooms were given back never takes them back unless the
gateway captured it in time (B4, D4): it is recorded, kept off the booking and put in
reconciliation (``Action Required`` for staff, or ``Refund Queued`` when late money's rooms are gone
and the gateway refunds by itself), audited, and no confirmation reaches the guest or the PMS.

Time passes in these tests by moving every stored deadline of a booking into the past
(``passes``): the hold of its rooms, and the start and deadline of its payment attempts."""

import threading
from contextlib import contextmanager
from unittest import mock

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import add_days, add_to_date, now_datetime, nowdate

from kamra.reservation_state import expire_holds
from kamra.tex.api import public
from kamra.tex.money import D
from kamra.tex.payments import service as pay
from kamra.tex.services import booking, quoting
from kamra.tex.tests.integration import fixtures as fx
from kamra.tex.tests.integration.test_commercial_flows import GUEST, SLUG, setup_site_and_payments
from kamra.tex.tests.integration.test_concurrency import _cleanup, _cleanup_payments
from kamra.tex.tests.integration.test_critical_journey import TexTestCase, pick


def passes(booking_name: str, minutes: int) -> None:
	"""``minutes`` go by for a booking: every deadline and start time it stored moves back."""
	frappe.db.sql("""UPDATE `tabReservation` SET hold_expires_on = hold_expires_on - INTERVAL %(m)s MINUTE
	                 WHERE tex_booking=%(b)s AND hold_expires_on IS NOT NULL""", {"m": minutes, "b": booking_name})
	# its charges: its own, and those of its payment links
	of_booking = """(booking=%(b)s OR payment_link IN (SELECT name FROM `tabTEX Payment Link` WHERE booking=%(b)s))"""
	frappe.db.sql(f"""UPDATE `tabTEX Payment Transaction` SET creation = creation - INTERVAL %(m)s MINUTE
	                  WHERE {of_booking}""", {"m": minutes, "b": booking_name})
	if frappe.db.has_column("TEX Payment Transaction", "expires_at"):
		frappe.db.sql(f"""UPDATE `tabTEX Payment Transaction` SET expires_at = expires_at - INTERVAL %(m)s MINUTE
		                  WHERE {of_booking} AND expires_at IS NOT NULL""", {"m": minutes, "b": booking_name})
	frappe.db.sql("""UPDATE `tabTEX Payment Link` SET expires_at = expires_at - INTERVAL %(m)s MINUTE
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
	         rate_plan: str = "FLEX", guest: dict | None = None, **kw) -> dict:
		res = quoting.search(properties=[fx.PROPERTY], check_in=fx.d(6, 10), check_out=fx.d(6, 13),
		                     rooms=[{"adults": 2}] * rooms, market="DE", channel="DIRECT_WEB", currency="EUR")
		offer = pick(res["properties"][0], room_code=room, rate_plan_code=rate_plan)
		quotes = quoting.create_quotes([{"offer_key": r["offer_key"]} for r in offer["rooms"]])
		b = booking.create_booking(quote_ids=[r["quote_id"] for r in quotes["rooms"]], guest=guest or GUEST,
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
		passes(b["booking"], 22)                                   # hold over, the checkout still open (3DS margin)
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

	def test_a_card_attempt_never_outlives_the_hold_by_more_than_a_3ds_margin(self):
		"""C1 (audit 1c): a web card booking opens its payment at once; its attempt keeps the rooms at
		most a short 3-D Secure margin past the booking's 20-minute hold, never a fixed 30 minutes."""
		from kamra.tex.services import holds

		b = self.book()
		payment = self.start_payment(b)
		hold = held_until(b)[0]
		until = frappe.db.get_value("TEX Payment Transaction", payment["transaction"], "expires_at")
		self.assertEqual(until, add_to_date(hold, minutes=holds.THREEDS_MARGIN_MINUTES))

	def test_a_declined_card_may_try_again_while_its_rooms_are_held(self):
		"""C1 (audit 1c): 10:00 booked, 10:21 the card is declined: the rooms are still held by that
		attempt, so the guest may try again (never "sold out" by their own booking); once nothing holds
		them any more, no new attempt starts."""
		b = self.book()
		first = self.start_payment(b)
		passes(b["booking"], 21)                                   # the hold ended, the attempt is open
		public.mock_pay(transaction=first["transaction"], outcome="fail", sig=first["fields"]["fail_sig"])
		again = self.start_payment(b)
		self.assertEqual(self.pays(again)["status"], "Succeeded")
		self.assertEqual(self.statuses(b), ("Confirmed", ["Confirmed"]))
		c = self.book()
		self.start_payment(c)
		passes(c["booking"], 30)                                   # hold and attempt both over
		with self.assertRaises(frappe.ValidationError):
			self.start_payment(c)

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


def pre_c6_fee(b: dict) -> None:
	"""As a cancellation before C6 left a booking never confirmed: the rate's penalty on its first room
	(NRF: the room's price), counted in its total (E6)."""
	room = b["rooms"][0]["reservation"]
	fee = D(frappe.db.get_value("Reservation", room, "tex_total_amount"))
	frappe.db.set_value("Reservation", room, "cancellation_fee", fee)
	live = [D(r.tex_total_amount) for r in frappe.get_all("Reservation", filters={"tex_booking": b["booking"],
	                                                                             "status": ("!=", "Cancelled")},
	                                                         fields=["tex_total_amount"])]
	total = fee + sum(live, D(0))
	frappe.db.set_value("TEX Booking", b["booking"], {"total_amount": total, "balance_amount": total - paid(b)})


def confirmations(b: dict) -> int:
	return frappe.db.count("TEX Audit Event", {"action": "booking.confirm", "reference_name": b["booking"]})


class TestLatePayment(HoldCase):
	"""K-2b, B3: late money never confirms a booking whose rooms are not held for it; money for rooms still held does."""

	def test_a_payment_within_the_hold_confirms_the_booking(self):
		b = self.book(rooms=2)
		payment = self.start_payment(b)
		passes(b["booking"], 10)
		self.assertEqual(self.pays(payment)["status"], "Succeeded")
		self.assertEqual(self.statuses(b), ("Confirmed", ["Confirmed", "Confirmed"]))
		self.assertFalse(txn_state(payment["transaction"]).reconciliation)

	def test_a_payment_while_its_rooms_are_still_held_confirms_it_at_its_price(self):
		"""B3 a): hold and checkout are over but the expiry job has not run: the rooms are still
		held for this booking, nothing is taken again, so its payment confirms it as quoted."""
		b = self.book()
		payment = self.start_payment(b)
		passes(b["booking"], 60)
		with mock.patch("kamra.tex.services.notify.booking_confirmed") as mailed:
			self.assertEqual(self.pays(payment)["status"], "Succeeded")
		mailed.assert_called_once()
		self.assertEqual(self.statuses(b), ("Confirmed", ["Confirmed"]))
		self.assertFalse(txn_state(payment["transaction"]).reconciliation)
		self.assertEqual(pay.allocated_of(payment["transaction"]), D(b["due_now"]))

	def test_a_payment_after_its_rooms_were_given_back_is_reconciled(self):
		"""B3 b): the booking expired and its rooms were given back; they are still free. Nothing is
		revived by itself: the money stays on record, off the booking, for staff."""
		b = self.book()
		payment = self.start_payment(b)
		passes(b["booking"], 60)
		run_expiry_jobs()
		with mock.patch("kamra.tex.services.notify.booking_confirmed") as mailed:
			self.assertEqual(self.pays(payment)["status"], "Succeeded")      # the money is on record
		mailed.assert_not_called()
		self.assertEqual(confirmations(b), 0)
		self.assertEqual(self.statuses(b), ("Cancelled", ["Cancelled"]))
		t = txn_state(payment["transaction"])
		self.assertEqual((t.status, t.reconciliation), ("Succeeded", "Action Required"))
		self.assertIn("free now: yes", t.reconciliation_note)     # availability and price evaluated again
		self.assertIn("price now", t.reconciliation_note)
		self.assertEqual(pay.allocated_of(payment["transaction"]), D(0))   # never written on the booking
		self.assertEqual(D(frappe.db.get_value("TEX Booking", b["booking"], "paid_amount")), D(0))
		# the gateway calling again changes nothing
		self.assertTrue(self.pays(payment).get("replay"))
		self.assertEqual(frappe.db.count("TEX Audit Event", {"action": "payment.reconciliation_required",
		                                                     "reference_name": payment["transaction"]}), 1)
		self.assertEqual(frappe.db.count("TEX Payment Allocation", {"transaction": payment["transaction"]}), 0)

	def test_while_a_rooms_are_held_b_cannot_have_them_and_a_late_payment_confirms_a(self):
		"""B3: A holds the last Deluxe room past its hold (the job has not run yet). Guest B is told
		it is sold out; A's payment then confirms A: the room is sold once, to A."""
		self.book(room="DLX", method="Pay at Hotel", status="Confirmed")
		res = quoting.search(properties=[fx.PROPERTY], check_in=fx.d(6, 10), check_out=fx.d(6, 13),
		                     rooms=[{"adults": 2}], market="DE", channel="DIRECT_WEB", currency="EUR")
		b_quote = quoting.create_quote(pick(res["properties"][0], room_code="DLX")["rooms"][0]["offer_key"])
		a = self.book(room="DLX")                                   # A takes the last room first
		payment = self.start_payment(a)
		passes(a["booking"], 60)
		with self.assertRaises(frappe.ValidationError) as refused:
			booking.create_booking(quote_ids=[b_quote["quote_id"]], payment_method="Pay at Hotel",
			                       guest={"first_name": "Ben", "last_name": "Late", "email": "ben.b3@example.com"})
		self.assertIn("sold out", str(refused.exception))
		self.assertEqual(self.pays(payment)["status"], "Succeeded")
		self.assertEqual(self.statuses(a), ("Confirmed", ["Confirmed"]))
		dlx = self.f["room_types"]["DLX"]
		self.assertEqual(frappe.db.count("Reservation", {"room_type": dlx, "status": "Confirmed"}), 2)

	def test_rooms_given_away_are_never_taken_back_by_a_late_payment(self):
		"""The rooms of a booking still waiting were released before its payment arrived (as the PMS
		job did before K-2a) and the last Deluxe room was sold to another guest meanwhile."""
		self.book(room="DLX", method="Pay at Hotel", status="Confirmed")        # one of the two is sold
		a = self.book(room="DLX")
		payment = self.start_payment(a)                                           # started within the hold
		frappe.db.sql("UPDATE `tabReservation` SET status='Cancelled' WHERE tex_booking=%s", a["booking"])
		b = self.book(room="DLX", method="Pay at Hotel", status="Confirmed")    # the last room, to B
		passes(a["booking"], 60)                                  # paid once its checkout had closed
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

	def test_a_manual_payment_for_an_expired_booking_is_refused(self):
		"""C5 (audit 1c): staff are told why, and nothing is recorded — never money parked at the desk."""
		b = self.book()
		passes(b["booking"], 25)
		run_expiry_jobs()
		with self.assertRaisesRegex(frappe.ValidationError, "is cancelled"):
			pay.record_manual(booking=b["booking"], amount=b["due_now"], method="Cash", reference="till 3",
			                  idempotency_key=f"k2c-cash-{b['booking']}")
		self.assertFalse(frappe.db.exists("TEX Payment Transaction", {"booking": b["booking"], "provider": "Manual"}))
		self.assertEqual(self.statuses(b), ("Cancelled", ["Cancelled"]))
		self.assertEqual(paid(b), D(0))

	def test_points_are_never_burned_on_a_booking_that_cannot_take_them(self):
		"""C5 (audit 1c): a loyalty redemption on an expired booking is refused before a point is burned."""
		from kamra.tex.crm import loyalty

		prog = frappe.get_doc({"doctype": "TEX Loyalty Program", "program_name": "C5 Club", "property": fx.PROPERTY,
		                       "enabled": 1, "currency": "EUR", "point_value": 0.1, "min_redeem_points": 50,
		                       "max_redeem_percent": 100, "pending_days": 0,
		                       "earn_rules": [{"basis": "MONEY", "rate": 1}]}).insert(ignore_permissions=True)
		stayed = self.book()
		self.pays(self.start_payment(stayed))
		guest = frappe.db.get_value("TEX Booking", stayed["booking"], "booker_guest")
		loyalty.mature_and_expire(today=fx.d(6, 13))
		before = loyalty.balances(guest, prog.name)["available"]
		self.assertGreaterEqual(before, 50)
		b = self.book()
		passes(b["booking"], 25)
		run_expiry_jobs()
		with self.assertRaisesRegex(frappe.ValidationError, "is cancelled"):
			loyalty.redeem(guest, b["booking"], 50, idempotency_key=f"c5-{b['booking']}")
		self.assertEqual(loyalty.balances(guest, prog.name)["available"], before)

	def test_money_on_a_booking_cancelled_before_it_was_confirmed_comes_off_it(self):
		"""P1-7 a (audit 2B, ADR-065): a booking waiting for its payment, part paid, is cancelled (by staff,
		or by the guest online): its money comes off it into reconciliation for staff — never left on a
		cancelled booking owing nothing — and the guest gets no late-payment e-mail."""
		import json

		frappe.db.set_value("Property", fx.PROPERTY, "tex_self_service", 1)
		for how in ("staff", "online"):
			with self.subTest(how=how):
				b = self.book(method="Card")
				half = (D(b["due_now"]) / 2).quantize(D("0.01"))
				link = pay.create_link(property=fx.PROPERTY, amount=str(half), currency="EUR",
				                       description="First half", booking=b["booking"])
				started = public.pay_link(token=link["token"])
				public.mock_pay(transaction=started["transaction"], outcome="success",
				                sig=started["fields"]["success_sig"])
				t = started["transaction"]
				self.assertEqual((self.statuses(b)[0], paid(b)), ("Pending Payment", half))
				with mock.patch("kamra.tex.services.notify.payment_after_expiry") as guest_mail:
					if how == "staff":
						booking.cancel_reservation(self.rooms(b)[0], reason="the guest called to cancel")
					else:
						public.manage_cancel(token=b["manage_token"], reservation=self.rooms(b)[0], reason="plans")
				guest_mail.assert_not_called()
				self.assertEqual(self.statuses(b), ("Cancelled", ["Cancelled"]))
				self.assertEqual((paid(b), pay.allocated_of(t)), (D(0), D(0)))
				self.assertEqual(txn_state(t).reconciliation, "Action Required")
				why = frappe.get_all("TEX Audit Event", filters={"action": "payment.reconciliation_required",
				                                                 "reference_name": t}, pluck="new_value")
				self.assertEqual([json.loads(v)["why"] for v in why], ["CANCELLED_UNPAID"])

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

	def test_a_booking_never_confirmed_owes_no_cancellation_fee(self):
		"""C6 (user decision): a room of a booking never confirmed (never paid) is cancelled free of
		charge, even at a non-refundable rate, and no debt is left once the rest expires."""
		b = self.book(rooms=2, rate_plan="NRF")
		out = booking.cancel_reservation(self.rooms(b)[0], reason="one room less")
		self.assertEqual(D(out["penalty"]), D(0))
		passes(b["booking"], 25)
		run_expiry_jobs()
		row = frappe.db.get_value("TEX Booking", b["booking"], ["status", "total_amount", "balance_amount"], as_dict=True)
		self.assertEqual((row.status, D(row.total_amount), D(row.balance_amount)), ("Cancelled", D(0), D(0)))

	def test_money_in_flight_is_never_kept_as_a_cancellation_fee(self):
		"""C6 (user decision): a confirmed, unpaid booking is cancelled with its fee while the guest's
		card payment is on its way: the payment is not silently taken as the fee — it goes to staff."""
		b = self.book(rate_plan="NRF", status="Confirmed", confirm_without_payment=True)
		payment = public.pay_booking(token=b["manage_token"], payment_method="Card")
		booking.cancel_reservation(self.rooms(b)[0], reason="the guest cancelled")
		self.assertGreater(D(frappe.db.get_value("TEX Booking", b["booking"], "total_amount")), D(0))   # the fee
		self.assertEqual(self.pays(payment)["status"], "Succeeded")
		self.assertEqual(paid(b), D(0))
		self.assertEqual(txn_state(payment["transaction"]).reconciliation, "Action Required")

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
	"""K-2 acceptance and audit 1b, under real concurrency: each side its own connection, the fixtures
	committed, every side released at the same instant.

	One Deluxe room is left. Booking A holds it and started its card payment; A's hold and checkout
	are over, but the expiry job has not run yet. Then the expiry job, A's late payment and guest B
	booking the last room run at once. Whatever order the database gives them: the room is sold at
	most once; A is confirmed exactly when its rooms were still held for it when its payment came
	(B3 a) — and then B is refused; otherwise A expired, never takes the room back, nothing is sent to
	A, and its money is on record, off its booking, in reconciliation. A side the database chose as a
	deadlock victim is run again, as its caller would (the scheduler's next run, the gateway's retry)."""

	@classmethod
	def tearDownClass(cls):
		_cleanup_payments()
		_cleanup()
		super().tearDownClass()

	def setUp(self):
		super().setUp()
		frappe.set_user("Administrator")  # nosemgrep: frappe-setuser -- test setup
		_cleanup()
		_cleanup_payments()
		self.f = fx.base_setup()
		fx.create_contract(self.f, code="CONC")
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
		self.a = booking.create_booking(quote_ids=[quotes[1]], guest=dict(guest, first_name="Anna"),
		                                payment_method="Card")
		self.payment = public.pay_booking(token=self.a["manage_token"], payment_method="Card")
		self.b_quote = quotes[2]
		frappe.set_user("Administrator")  # nosemgrep: frappe-setuser -- test setup
		passes(self.a["booking"], 60)                     # A's hold and checkout are over; no job ran yet
		frappe.db.commit()  # nosemgrep: frappe-manual-commit -- threads need committed fixtures

	def _race(self, *sides) -> dict[str, str]:
		"""``sides``: (name, fn, user). Deadlock victims are run again, one at a time, afterwards."""
		site, sites_path = frappe.local.site, frappe.local.sites_path
		barrier = threading.Barrier(len(sides))
		results: dict[str, str] = {}

		def run(who, fn, user, wait=True):
			frappe.init(site=site, sites_path=sites_path)
			frappe.connect()
			try:
				frappe.set_user(user)  # nosemgrep: frappe-setuser -- a job, a gateway callback, a guest booking
				if wait:
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
		for who, fn, user in sides:
			if "Deadlock" in results.get(who, "") or "InventoryBusy" in results.get(who, ""):
				t = threading.Thread(target=run, args=(who, fn, user, False))
				t.start()
				t.join(timeout=60)
		frappe.db.rollback()                              # read what the sides committed
		return results

	def expiry(self):
		booking.expire_pending_bookings()
		return "ran"

	def late_payment(self):
		return public.mock_pay(transaction=self.payment["transaction"], outcome="success",
		                       sig=self.payment["fields"]["success_sig"])["status"]

	def b_books(self):
		return booking.create_booking(quote_ids=[self.b_quote], payment_method="Pay at Hotel", guest={
			"first_name": "Ben", "last_name": "Second", "email": "ben.k2@example.com"})["status"]

	def assert_a_settled(self, confirmations: int) -> str:
		"""A ends confirmed with its money, or expired with its money in reconciliation: never between."""
		status = frappe.db.get_value("TEX Booking", self.a["booking"], "status")
		rooms = frappe.get_all("Reservation", filters={"tex_booking": self.a["booking"]}, pluck="status")
		t = txn_state(self.payment["transaction"])
		self.assertEqual(t.status, "Succeeded")                                    # the money is never lost
		audit = frappe.db.count("TEX Audit Event", {"action": "booking.confirm", "reference_name": self.a["booking"]})
		expired_by = frappe.get_all("TEX Audit Event", filters={"action": "booking.expire",
		                                                         "reference_name": self.a["booking"]}, pluck="source")
		if status == "Confirmed":
			self.assertEqual(expired_by, [])
			self.assertEqual(rooms, ["Confirmed"])
			self.assertEqual(pay.allocated_of(self.payment["transaction"]), D(self.a["due_now"]))
			self.assertFalse(t.reconciliation)
			self.assertEqual((audit, confirmations), (1, 1))
		else:
			self.assertEqual((status, rooms), ("Cancelled", ["Cancelled"]))
			# B3 a): a payment that found A's rooms still held would have confirmed A, so the expiry job
			# gave them back before the payment came — never the payment itself (D8)
			self.assertEqual(expired_by, ["System"])
			self.assertEqual(pay.allocated_of(self.payment["transaction"]), D(0))
			self.assertIn(t.reconciliation, ("Action Required", "Refund Queued"))
			self.assertEqual((audit, confirmations), (0, 0))                           # nothing sent to A
			self.assertEqual(frappe.db.count("TEX Audit Event", {"action": "payment.reconciliation_required",
			                                                     "reference_name": self.payment["transaction"]}), 1)
		return status

	def test_the_expiry_job_and_a_late_payment_race_for_the_same_booking(self):
		with mock.patch("kamra.tex.services.notify.booking_confirmed") as mailed:
			results = self._race(("expiry", self.expiry, "Administrator"), ("a_pays", self.late_payment, "Guest"))
		self.assertEqual(results, {"expiry": "ran", "a_pays": "Succeeded"})
		self.assert_a_settled(mailed.call_count)

	def test_a_late_payment_holding_the_booking_before_the_expiry_job_confirms_it(self):
		"""E7 (audit 1c-son): the same race in a forced order — the expiry job starts only once the late
		payment holds A's lock, A's rooms still held for it. Only one outcome: A is confirmed at its
		locked price (B3 a) and the job, waiting behind the payment, leaves it."""
		from kamra.tex.services import late_payments

		holds_the_lock = threading.Event()
		judge = late_payments.problem

		def payment_judges_a(b, *args, **kw):
			if b.name == self.a["booking"]:
				holds_the_lock.set()                               # ``allocate`` judges A under A's lock
			return judge(b, *args, **kw)

		def expiry_once_the_payment_holds_a():
			return self.expiry() if holds_the_lock.wait(timeout=30) else "the payment never took A's lock"

		with mock.patch("kamra.tex.services.late_payments.problem", payment_judges_a), \
		     mock.patch("kamra.tex.services.notify.booking_confirmed") as mailed:
			results = self._race(("expiry", expiry_once_the_payment_holds_a, "Administrator"),
			                     ("a_pays", self.late_payment, "Guest"))
		self.assertEqual(results, {"expiry": "ran", "a_pays": "Succeeded"})
		self.assertEqual(self.assert_a_settled(mailed.call_count), "Confirmed")

	def test_a_charge_leaves_reconciliation_by_its_state_as_it_is_now(self):
		"""E5 (audit 1c-son): ``settled`` decides by the charge's reconciliation as it is now (a locking
		read), never as this transaction's snapshot saw it before another one changed it."""
		from kamra.tex.services import late_payments

		self.expiry()
		self.late_payment()                                        # A expired; its money in reconciliation
		txn = self.payment["transaction"]
		frappe.db.set_value("TEX Payment Transaction", txn, "reconciliation", "Resolved", update_modified=False)
		frappe.db.commit()  # nosemgrep: frappe-manual-commit -- the other connection reads it
		self.assertEqual(frappe.db.get_value("TEX Payment Transaction", txn, "reconciliation"), "Resolved")
		site, sites_path = frappe.local.site, frappe.local.sites_path

		def staff_queue_the_refund():                              # another request, its own connection
			frappe.init(site=site, sites_path=sites_path)
			frappe.connect()
			try:
				frappe.db.set_value("TEX Payment Transaction", txn, "reconciliation", "Refund Queued",
				                    update_modified=False)
				frappe.db.commit()  # nosemgrep: frappe-manual-commit -- its own request
			finally:
				frappe.destroy()

		other = threading.Thread(target=staff_queue_the_refund)
		other.start()
		other.join(timeout=30)
		frappe.db.sql("SELECT name FROM `tabTEX Payment Transaction` WHERE name=%s FOR UPDATE", txn)   # its lock
		late_payments.settled(txn)
		frappe.db.commit()  # nosemgrep: frappe-manual-commit -- read what was decided
		self.assertEqual(frappe.db.get_value("TEX Payment Transaction", txn, "reconciliation"), "Refund Queued")

	def test_the_expiry_job_a_late_payment_and_a_new_guest_race_for_the_last_room(self):
		with mock.patch("kamra.tex.services.notify.booking_confirmed") as mailed:
			results = self._race(("expiry", self.expiry, "Administrator"), ("a_pays", self.late_payment, "Guest"),
			                     ("b_books", self.b_books, "Guest"))
		self.assertEqual((results["expiry"], results["a_pays"]), ("ran", "Succeeded"))
		a = self.assert_a_settled(mailed.call_count)
		dlx = self.f["room_types"]["DLX"]
		live = frappe.get_all("Reservation", filters={"room_type": dlx, "status": ("in", ["Confirmed", "Pending Payment",
		                                                                               "Held", "Checked In"])},
		                      pluck="tex_booking")
		self.assertLessEqual(len(live), 2, live)                                   # never sold twice
		if results["b_books"] == "Confirmed":
			self.assertNotEqual(a, "Confirmed")                                   # the room went to B alone
		else:
			self.assertIn("sold out", results["b_books"])                         # refused while A held it
		self.assertEqual(a == "Confirmed", self.a["booking"] in live)
		# the gateway calling again changes nothing
		again = self._race(("a_pays_again", self.late_payment, "Guest"))
		self.assertEqual(again, {"a_pays_again": "Succeeded"})
		self.assertEqual(frappe.db.get_value("TEX Booking", self.a["booking"], "status"), a)


class TestRefundOutcomeOnABookingThatExpiredMeanwhile(IntegrationTestCase):
	"""P1-3 review 2, under real concurrency: a durable refund is committed before the gateway is asked;
	the gateway's own plain read (its secret) fixes the request's read view; while it works, the expiry job
	(another connection) cancels the never-confirmed booking and commits. The refund's outcome must judge the
	booking as it is now (a locking read), never as that read view saw it. Fixtures committed, cleaned up."""

	@classmethod
	def tearDownClass(cls):
		_cleanup_payments()
		_cleanup()
		super().tearDownClass()

	def setUp(self):
		super().setUp()
		frappe.set_user("Administrator")  # nosemgrep: frappe-setuser -- test setup
		_cleanup()
		_cleanup_payments()
		self.f = fx.base_setup()
		fx.create_contract(self.f, code="CONC")
		acc = fx.ensure("TEX Payment Provider Account", {"property": fx.PROPERTY, "provider": "Mock"},
		                {"label": "Sandbox gateway", "property": fx.PROPERTY, "provider": "Mock",
		                 "environment": "Sandbox", "enabled": 1, "currencies": "EUR"})
		fx.ensure("TEX Payment Method Rule", {"property": fx.PROPERTY, "method": "Card"},
		          {"property": fx.PROPERTY, "method": "Card", "provider_account": acc, "priority": 10})
		frappe.set_user("Guest")  # nosemgrep: frappe-setuser -- guest booking path
		prop = quoting.search(properties=[fx.PROPERTY], check_in=fx.d(8, 20), check_out=fx.d(8, 22),
		                      rooms=[{"adults": 2}], market="DE", channel="DIRECT_WEB",
		                      currency="EUR")["properties"][0]
		offer = pick(prop, room_code="STD", rate_plan_code="FLEX")
		quote = quoting.create_quote(offer["rooms"][0]["offer_key"])["quote_id"]
		b = booking.create_booking(quote_ids=[quote], payment_method="Card", guest={
			"first_name": "Rita", "last_name": "Refund", "email": "rita.p13@example.com"})
		frappe.set_user("Administrator")  # nosemgrep: frappe-setuser -- the agent sends a link for most of it
		# just under the deposit: never confirmed, and at least 80 on it, so that once the expiry released all
		# but the 40 on their way, the refund comes wholly out of that released money and this request never
		# writes the booking before it judges it (a transaction always sees its own writes)
		part = D(b["due_now"]) - 1
		self.assertGreaterEqual(part - 40, D(40))
		link = pay.create_link(property=fx.PROPERTY, amount=str(part), currency="EUR", description="Most of it",
		                       booking=b["booking"])
		started = public.pay_link(token=link["token"])
		public.mock_pay(transaction=started["transaction"], outcome="success", sig=started["fields"]["success_sig"])
		self.b, self.c = b["booking"], started["transaction"]
		frappe.db.commit()  # nosemgrep: frappe-manual-commit -- the other connection needs committed fixtures

	def test_a_refunds_outcome_judges_the_booking_as_it_is_now(self):
		import traceback

		from kamra.tex.payments.providers.simple import MockProvider

		self.assertEqual(frappe.db.get_value("TEX Booking", self.b, "status"), "Pending Payment")
		site, sites_path = frappe.local.site, frappe.local.sites_path
		real = MockProvider.refund
		errors: list[str] = []

		def expiry_elsewhere():
			frappe.init(site=site, sites_path=sites_path)
			frappe.connect()
			try:
				frappe.set_user("Administrator")  # nosemgrep: frappe-setuser -- the expiry job
				booking.expire_booking(self.b, force=True, send_mail=False)
				frappe.db.commit()  # nosemgrep: frappe-manual-commit -- the job's own transaction
			except Exception:
				frappe.db.rollback()
				errors.append(traceback.format_exc())
			finally:
				frappe.destroy()

		def gateway(provider, *args, **kw):
			# the gateway reads its secret first: a plain read, which fixes this request's read view
			frappe.db.sql("SELECT status FROM `tabTEX Booking` WHERE name=%s", self.b)
			job = threading.Thread(target=expiry_elsewhere)
			job.start()
			job.join(timeout=60)
			return real(provider, *args, **kw)

		frappe.flags.in_test = False                    # the durable commit runs, as in production
		try:
			with mock.patch.object(MockProvider, "refund", gateway):
				out = pay.refund(self.c, amount="40", reason="the guest asked", idempotency_key=f"p13r2-{self.c}",
				                 durable=True)
		finally:
			frappe.flags.in_test = True
		self.assertEqual(errors, [])
		self.assertEqual(out["status"], "Succeeded")
		self.assertIsNone(frappe.db.get_value("TEX Payment Transaction", out["refund"], "booking"))  # off no booking
		now = frappe.db.get_value("TEX Booking", self.b, ["status", "paid_amount"], as_dict=True, for_update=True)
		self.assertEqual((now.status, D(now.paid_amount)), ("Cancelled", D(0)))
		self.assertEqual(frappe.db.get_value("TEX Payment Transaction", self.c, "reconciliation", for_update=True),
		                 "Action Required")


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

	def guest_books(self, **kw) -> dict:
		frappe.set_user("Guest")  # nosemgrep: frappe-setuser -- the public booking engine
		try:
			return self.book(**kw)
		finally:
			frappe.set_user("Administrator")  # nosemgrep: frappe-setuser -- back to staff

	def test_a_web_transfer_holds_24_hours_and_staff_bookings_48(self):
		"""C2 (user decision): a bank transfer booked on the web keeps its rooms 24 hours (the hotel may
		change it); one booked by the call centre or staff keeps 48."""
		self.assertEqual(self.hold_minutes(self.guest_books(method="Bank Transfer")), 1440)
		self.assertEqual(self.hold_minutes(self.book(method="Bank Transfer")), 2880)
		frappe.db.set_value("Property", fx.PROPERTY, "tex_hold_minutes_transfer_web", 600)
		self.assertEqual(self.hold_minutes(self.guest_books(method="Bank Transfer")), 600)
		self.assertEqual(frappe.db.get_single_value("TEX Settings", "hold_minutes_transfer_web"), 1440)

	def test_the_web_takes_at_most_two_rooms_by_bank_transfer(self):
		"""C2 (user decision): one visitor must not lock many rooms for a day by choosing a transfer."""
		with self.assertRaises(frappe.ValidationError):
			self.guest_books(rooms=3, method="Bank Transfer")
		self.guest_books(rooms=2, method="Bank Transfer")
		self.book(rooms=3, method="Bank Transfer")                          # staff may

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


class TestHoldSettings(HoldCase):
	def test_the_platform_settings_read_and_save_the_web_transfer_hold(self):
		"""K4 (audit 1c-son): the web transfer hold (C2) is a platform setting like the other holds."""
		import json

		from kamra.tex.api import admin

		admin.save_settings(json.dumps({"hold_minutes_transfer_web": 600}))
		self.assertEqual(frappe.db.get_single_value("TEX Settings", "hold_minutes_transfer_web"), 600)
		self.assertEqual(admin.settings()["hold_minutes_transfer_web"], 600)


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
		run_expiry_jobs()                                          # the room left was given back
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

	def test_a_room_cancelled_after_part_of_the_money_came_confirms_the_rest(self):
		"""D1 (audit 1c): two rooms, a link for each half; the guest pays the first, then cancels the
		second room free of charge. What the booking owes now is paid: it is confirmed at once, and
		nothing expires or goes to reconciliation later."""
		b = self.book(rooms=2)
		half = (D(b["due_now"]) / 2).quantize(D("0.01"))
		links = [pay.create_link(property=fx.PROPERTY, amount=str(half), currency="EUR", description=f"Half {i}",
		                         booking=b["booking"]) for i in (1, 2)]
		started = public.pay_link(token=links[0]["token"])
		public.mock_pay(transaction=started["transaction"], outcome="success", sig=started["fields"]["success_sig"])
		self.assertEqual(self.statuses(b)[0], "Pending Payment")
		with mock.patch("kamra.tex.services.notify.booking_confirmed") as mailed:
			booking.cancel_reservation(self.rooms(b)[1], reason="one room less")
		mailed.assert_called_once()
		self.assertEqual(self.statuses(b), ("Partially Cancelled", ["Confirmed", "Cancelled"]))
		self.assertEqual(paid(b), half)
		passes(b["booking"], 24 * 60 + 5)
		run_expiry_jobs()
		self.assertEqual(self.statuses(b), ("Partially Cancelled", ["Confirmed", "Cancelled"]))
		self.assertFalse(txn_state(started["transaction"]).reconciliation)

	def test_the_guest_cancelling_a_room_online_leaves_the_rest_waiting_for_what_it_needs(self):
		"""D8 (audit 1c): the manage page's cancel of a room of a booking still waiting for its payment:
		the rest keeps waiting, owing only its own deposit, and the guest's payment of it confirms it."""
		frappe.db.set_value("Property", fx.PROPERTY, "tex_self_service", 1)
		b = self.book(rooms=2)
		public.manage_cancel(token=b["manage_token"], reservation=self.rooms(b)[1], reason="one room less")
		self.assertEqual(self.statuses(b), ("Pending Payment", ["Pending Payment", "Cancelled"]))
		due = D(frappe.db.get_value("TEX Booking", b["booking"], "amount_due_now"))
		self.assertEqual(due, (D(b["due_now"]) / 2).quantize(D("0.01")))       # one room's deposit left
		self.assertEqual(self.pays(self.start_payment(b))["status"], "Succeeded")
		self.assertEqual(self.statuses(b), ("Partially Cancelled", ["Confirmed", "Cancelled"]))
		self.assertEqual(paid(b), due)

	def test_p52_drops_a_fee_from_before_c6_and_sends_no_mail(self):
		"""E6 (audit 1c-son): a room cancelled before C6 carried the rate's penalty (NRF: its price) on a
		booking never confirmed. p52 voids it: the booking owes what its room left requires; one whose
		hold is over expires owing nothing, its money in reconciliation, and no e-mail leaves the migration."""
		from kamra.tex.tests.integration.test_patches import migrate, never_ran

		waiting, over = self.book(rooms=2, rate_plan="NRF"), self.book(rooms=2, rate_plan="NRF")
		cash = pay.record_manual(booking=over["booking"], amount="50", method="Cash", reference="desk",
		                         idempotency_key=f"e6-cash-{over['booking']}")["transaction"]
		for b in (waiting, over):
			self.cancel_first(b)
			pre_c6_fee(b)
			frappe.db.set_value("TEX Booking", b["booking"], "status", "Partially Cancelled")
		passes(over["booking"], 25)                                      # its hold is over
		never_ran("p52_partly_cancelled_awaiting_payment")
		with mock.patch("kamra.tex.services.notify.reconciliation") as mailed:
			migrate("p52_partly_cancelled_awaiting_payment")
		mailed.assert_not_called()
		left = D(frappe.db.get_value("Reservation", self.rooms(waiting)[1], "tex_total_amount"))
		row = frappe.db.get_value("TEX Booking", waiting["booking"], ["status", "total_amount", "amount_due_now"],
		                          as_dict=True)
		self.assertEqual((row.status, D(row.total_amount), D(row.amount_due_now)), ("Pending Payment", left, left))
		self.assertEqual(D(frappe.db.get_value("Reservation", self.rooms(waiting)[0], "cancellation_fee")), D(0))
		self.assertEqual(self.statuses(over), ("Cancelled", ["Cancelled", "Cancelled"]))
		self.assertEqual((D(frappe.db.get_value("TEX Booking", over["booking"], "total_amount")), paid(over)),
		                 (D(0), D(0)))
		self.assertEqual(txn_state(cash).reconciliation, "Action Required")

	def test_p52_confirms_a_stuck_booking_whose_payment_was_taken(self):
		"""D1 (audit 1c): before B1 a stuck booking (Partially Cancelled, never confirmed) took its
		payment without confirming its rooms. p52 confirms it — never parks or expires it — and sends
		no e-mail from the migration."""
		from kamra.tex.tests.integration.test_patches import migrate, never_ran

		b = self.book(rooms=2)
		self.cancel_first(b)
		due = D(frappe.db.get_value("TEX Booking", b["booking"], "amount_due_now"))
		# as the release before B1 left it: Partially Cancelled, its payment taken, its room still waiting
		frappe.db.set_value("TEX Booking", b["booking"], {"status": "Partially Cancelled", "paid_amount": due,
		                                                  "payment_status": "Paid"})
		passes(b["booking"], 25)                                         # its hold is over
		never_ran("p52_partly_cancelled_awaiting_payment")
		with mock.patch("kamra.tex.services.notify.booking_confirmed") as mailed:
			migrate("p52_partly_cancelled_awaiting_payment")
		mailed.assert_not_called()
		self.assertEqual(self.statuses(b), ("Partially Cancelled", ["Cancelled", "Confirmed"]))
		self.assertEqual(paid(b), due)
		self.assertEqual(confirmations(b), 1)


class TestChangesOfABookingWaitingForItsPayment(HoldCase):
	"""E2 (audit 1c-son): any change of a booking never confirmed — its dates, extras, coupon, a price
	staff set, a room cancelled — makes it owe now what its rooms require now, up or down, never more
	than it costs; money that already covers that confirms it at once."""

	def test_shortened_after_its_first_half_was_paid_it_is_confirmed(self):
		from kamra.tex.services import modification

		b = self.book(rate_plan="NRF")                                  # 3 nights, all of it paid now
		half = (D(b["total"]) / 2).quantize(D("0.01"))
		links = [pay.create_link(property=fx.PROPERTY, amount=str(half), currency="EUR", description=f"Half {i}",
		                         booking=b["booking"]) for i in (1, 2)]
		started = public.pay_link(token=links[0]["token"])
		public.mock_pay(transaction=started["transaction"], outcome="success", sig=started["fields"]["success_sig"])
		self.assertEqual(self.statuses(b)[0], "Pending Payment")
		p = modification.propose(self.rooms(b)[0], {"check_out": str(fx.d(6, 11))})     # one night
		with mock.patch("kamra.tex.services.notify.booking_confirmed") as mailed:
			modification.apply(p["proposal_token"], reason="one night only")
		mailed.assert_called_once()
		self.assertEqual(self.statuses(b), ("Confirmed", ["Confirmed"]))
		self.assertEqual(confirmations(b), 1)
		night = D(frappe.db.get_value("TEX Booking", b["booking"], "total_amount"))
		self.assertEqual(D(frappe.db.get_value("TEX Booking", b["booking"], "amount_due_now")), night)

	def test_a_higher_price_is_not_confirmed_by_the_old_amount(self):
		from kamra.tex.services import modification

		b = self.book(rate_plan="NRF")
		payment = self.start_payment(b)                                 # the old amount, 3 nights
		p = modification.propose(self.rooms(b)[0], {"check_out": str(fx.d(6, 14))})     # a fourth night
		modification.apply(p["proposal_token"], reason="one night more")
		row = frappe.db.get_value("TEX Booking", b["booking"], ["total_amount", "amount_due_now"], as_dict=True)
		self.assertEqual(D(row.amount_due_now), D(row.total_amount))
		self.assertGreater(D(row.amount_due_now), D(b["due_now"]))
		self.assertEqual(self.pays(payment)["status"], "Succeeded")
		self.assertEqual(self.statuses(b), ("Pending Payment", ["Pending Payment"]))
		self.assertEqual(paid(b), D(b["due_now"]))

	def test_a_price_staff_raised_is_owed_in_full_and_the_old_amount_confirms_nothing(self):
		"""P1-6 (audit 2B, ADR-065): what a room owes now is read from its stored price, never from the
		engine's total its snapshot explains."""
		from kamra.tex.services import modification

		b = self.book(rate_plan="NRF")                                  # all of it paid now
		total = D(b["total"])
		payment = self.start_payment(b)                                 # the old amount
		p = modification.propose(self.rooms(b)[0], {})
		modification.apply(p["proposal_token"], reason="the price agreed by phone", override_amount=str(total + 100))
		self.assertEqual(D(frappe.db.get_value("TEX Booking", b["booking"], "amount_due_now")), total + 100)
		self.assertEqual(self.pays(payment)["status"], "Succeeded")
		self.assertEqual(self.statuses(b), ("Pending Payment", ["Pending Payment"]))
		self.assertEqual(paid(b), total)

	def test_a_price_staff_lowered_lowers_the_deposit_and_its_payment_confirms(self):
		from kamra.tex.money import quantize
		from kamra.tex.services import modification

		b = self.book()                                                 # FLEX: 30% now
		lower = D(b["total"]) - 100
		p = modification.propose(self.rooms(b)[0], {})
		modification.apply(p["proposal_token"], reason="the price agreed by phone", override_amount=str(lower))
		due = quantize(lower * D("0.3"), "EUR")
		self.assertEqual(D(frappe.db.get_value("TEX Booking", b["booking"], "amount_due_now")), due)
		payment = self.start_payment(b)
		self.assertEqual(D(frappe.db.get_value("TEX Payment Transaction", payment["transaction"], "amount")), due)
		self.assertEqual(self.pays(payment)["status"], "Succeeded")
		self.assertEqual(self.statuses(b), ("Confirmed", ["Confirmed"]))
		self.assertEqual(paid(b), due)


class TestNeverConfirmedLeftovers(HoldCase):
	"""D2 (audit 1c): before B1, a booking waiting for its payment with a room cancelled became
	"Partially Cancelled", and the old PMS job then released its other rooms: every room cancelled,
	never confirmed, yet counted as confirmed and taking money. It takes no money as a confirmed booking
	does, and p54 cancels it: its money off it into reconciliation, audited, no e-mail from migrate."""

	def leftover(self, b: dict) -> None:
		booking.cancel_reservation(self.rooms(b)[0], reason="one room less")
		frappe.db.sql("""UPDATE `tabReservation` SET status='Cancelled', cancellation_note='Hold expired'
		                 WHERE tex_booking=%s AND status IN ('Pending Payment', 'Held')""", b["booking"])
		frappe.db.set_value("TEX Booking", b["booking"], "status", "Partially Cancelled")

	def test_a_leftover_takes_no_money_as_a_confirmed_booking(self):
		b = self.book(rooms=2)
		payment = self.start_payment(b)
		self.leftover(b)
		self.assertEqual(self.pays(payment)["status"], "Succeeded")
		self.assertEqual(pay.allocated_of(payment["transaction"]), D(0))
		self.assertEqual(paid(b), D(0))
		self.assertEqual(txn_state(payment["transaction"]).reconciliation, "Action Required")

	def test_p54_cancels_leftovers_and_parks_their_money_without_mail(self):
		from kamra.tex.tests.integration.test_patches import migrate, never_ran

		b = self.book(rooms=2)
		cash = pay.record_manual(booking=b["booking"], amount="50", method="Cash", reference="desk",
		                         idempotency_key=f"d2-cash-{b['booking']}")["transaction"]   # less than a room's deposit
		self.leftover(b)
		kept = self.book(rooms=2)                                  # confirmed, then one room cancelled
		self.pays(self.start_payment(kept))
		booking.cancel_reservation(self.rooms(kept)[0], reason="one room less")
		never_ran("p54_never_confirmed_leftovers")
		with mock.patch("kamra.tex.services.notify.reconciliation") as mailed:
			migrate("p54_never_confirmed_leftovers")
		mailed.assert_not_called()
		self.assertEqual(self.statuses(b), ("Cancelled", ["Cancelled", "Cancelled"]))
		self.assertEqual((paid(b), pay.allocated_of(cash)), (D(0), D(0)))
		self.assertEqual(txn_state(cash).reconciliation, "Action Required")
		self.assertTrue(frappe.db.exists("TEX Audit Event", {"action": "booking.leftover_cancelled",
		                                                     "reference_name": b["booking"]}))
		self.assertEqual(self.statuses(kept), ("Partially Cancelled", ["Cancelled", "Confirmed"]))
		migrate("p54_never_confirmed_leftovers")                   # a second run changes nothing
		self.assertEqual(frappe.db.count("TEX Audit Event", {"action": "booking.leftover_cancelled",
		                                                     "reference_name": b["booking"]}), 1)

	def test_p54_leaves_a_leftover_owing_nothing_not_even_a_fee_from_before_c6(self):
		"""E6 (audit 1c-son): the leftover's cancelled room carried the rate's penalty from before C6 (NRF:
		its price). Cancelled by p54, it owes nothing: its total and its rooms' charges are nothing."""
		from kamra.tex.tests.integration.test_patches import migrate, never_ran

		b = self.book(rooms=2, rate_plan="NRF")
		self.leftover(b)
		pre_c6_fee(b)
		self.assertGreater(D(frappe.db.get_value("TEX Booking", b["booking"], "total_amount")), D(0))
		never_ran("p54_never_confirmed_leftovers")
		migrate("p54_never_confirmed_leftovers")
		row = frappe.db.get_value("TEX Booking", b["booking"], ["status", "total_amount", "balance_amount"], as_dict=True)
		self.assertEqual((row.status, D(row.total_amount), D(row.balance_amount)), ("Cancelled", D(0), D(0)))
		self.assertEqual([D(frappe.db.get_value("Reservation", r, "cancellation_fee") or 0) for r in self.rooms(b)],
		                 [D(0), D(0)])


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

	def test_a_part_paid_in_time_and_a_late_rest_are_each_flagged_once(self):
		"""D8 (audit 1c): T1 pays a first half within the hold; T2 (the rest) is paid after it ended. T1
		comes off the expired booking and T2 is kept off it: each flagged exactly once, however often
		the job runs or the gateway calls."""
		b = self.book(method="Card")
		half = (D(b["due_now"]) / 2).quantize(D("0.01"))
		links = [pay.create_link(property=fx.PROPERTY, amount=str(half), currency="EUR", description=f"Half {i}",
		                         booking=b["booking"]) for i in (1, 2)]
		t1 = public.pay_link(token=links[0]["token"])
		public.mock_pay(transaction=t1["transaction"], outcome="success", sig=t1["fields"]["success_sig"])
		t2 = public.pay_link(token=links[1]["token"])                      # started within the hold
		passes(b["booking"], 24 * 60 + 5)
		run_expiry_jobs()
		self.assertEqual(self.statuses(b)[0], "Cancelled")
		for _ in range(2):
			public.mock_pay(transaction=t2["transaction"], outcome="success", sig=t2["fields"]["success_sig"])
			run_expiry_jobs()
		self.assertEqual((paid(b), pay.allocated_of(t1["transaction"]), pay.allocated_of(t2["transaction"])),
		                 (D(0), D(0), D(0)))
		for t in (t1, t2):
			self.assertEqual(txn_state(t["transaction"]).reconciliation, "Action Required")
			self.assertEqual(frappe.db.count("TEX Audit Event", {"action": "payment.reconciliation_required",
			                                                     "reference_name": t["transaction"]}), 1)

	def test_a_first_link_paid_before_the_hold_ended_goes_to_reconciliation(self):
		"""The real flow: booked by card, the agent sends a link for half; the guest pays it; the rest
		never comes and the link hold ends."""
		b = self.book(method="Card")
		half = (D(b["due_now"]) / 2).quantize(D("0.01"))
		link = pay.create_link(property=fx.PROPERTY, amount=str(half), currency="EUR", description="First half",
		                       booking=b["booking"])
		started = public.pay_link(token=link["token"])
		public.mock_pay(transaction=started["transaction"], outcome="success", sig=started["fields"]["success_sig"])
		self.assertEqual((self.statuses(b), paid(b)), (("Pending Payment", ["Pending Payment"]), half))
		passes(b["booking"], 24 * 60 + 5)                          # the link hold is over
		run_expiry_jobs()
		self.assertEqual((self.statuses(b), paid(b)), (("Cancelled", ["Cancelled"]), D(0)))
		self.assertEqual(pay.allocated_of(started["transaction"]), D(0))
		self.assertEqual(txn_state(started["transaction"]).reconciliation, "Action Required")
		self.assertEqual(public.booking_status(token=b["manage_token"])["late_payment"], "contact")


def captured(at):
	"""The mock gateway states when it captured the money (B4), as a real gateway may."""
	import dataclasses

	from kamra.tex.payments.providers.simple import MockProvider

	real = MockProvider.handle_callback

	def handle(self, *args, **kw):
		return dataclasses.replace(real(self, *args, **kw), captured_at=at)

	return mock.patch.object(MockProvider, "handle_callback", handle)


class TestPaidInTime(HoldCase):
	"""B4 (audit 1b): a payment is late by the gateway's clock, when it states when it captured
	the money, never by when its news reached TEX. A delayed notification, or staff verifying after
	an outage, never leaves a booking paid in time cancelled: it gets back the rooms its expiry gave
	back while they are still free and is confirmed; rooms sold meanwhile go to staff, never an
	automatic refund."""

	def paid_in_time(self, b: dict) -> tuple[dict, object]:
		"""A pays within its checkout; the news is delayed until the expiry job has given its rooms back."""
		payment = self.start_payment(b)
		passes(b["booking"], 60)
		at = add_to_date(frappe.db.get_value("TEX Payment Transaction", payment["transaction"], "expires_at"),
		                 minutes=-5)
		run_expiry_jobs()
		self.assertEqual(self.statuses(b)[0], "Cancelled")
		return payment, at

	def test_a_delayed_notification_confirms_a_booking_paid_in_time(self):
		b = self.book(rooms=2)
		payment, at = self.paid_in_time(b)
		with captured(at), mock.patch("kamra.tex.services.notify.booking_confirmed") as mailed:
			self.assertEqual(self.pays(payment)["status"], "Succeeded")
		mailed.assert_called_once()
		self.assertEqual(self.statuses(b), ("Confirmed", ["Confirmed", "Confirmed"]))
		self.assertFalse(txn_state(payment["transaction"]).reconciliation)
		self.assertEqual(paid(b), D(b["due_now"]))
		self.assertEqual(D(frappe.db.get_value("TEX Booking", b["booking"], "total_amount")), D(b["total"]))
		self.assertEqual(frappe.db.get_value("TEX Payment Transaction", payment["transaction"], "captured_at"), at)
		self.assertTrue(frappe.db.exists("TEX Audit Event", {"action": "booking.revive",
		                                                     "reference_name": b["booking"]}))

	def test_a_payment_captured_after_its_checkout_closed_is_late(self):
		b = self.book()
		payment, at = self.paid_in_time(b)
		with captured(add_to_date(at, minutes=20)):                # 15 minutes past its deadline
			self.assertEqual(self.pays(payment)["status"], "Succeeded")
		self.assertEqual(self.statuses(b), ("Cancelled", ["Cancelled"]))
		self.assertEqual(txn_state(payment["transaction"]).reconciliation, "Action Required")

	def test_a_booking_paid_in_time_whose_room_was_sold_meanwhile_goes_to_staff(self):
		other = {"first_name": "Otto", "last_name": "Other", "email": "otto.d4@example.com"}
		self.book(room="DLX", method="Pay at Hotel", status="Confirmed", guest=other)
		a = self.book(room="DLX")
		payment, at = self.paid_in_time(a)
		b = self.book(room="DLX", method="Pay at Hotel", status="Confirmed",           # the last room, to B
		              guest=dict(other, email="ben.d4@example.com"))
		with captured(at), mock.patch("kamra.tex.services.notify.booking_confirmed") as mailed:
			self.assertEqual(self.pays(payment)["status"], "Succeeded")
		mailed.assert_not_called()
		self.assertEqual(self.statuses(a), ("Cancelled", ["Cancelled"]))
		self.assertEqual(self.statuses(b), ("Confirmed", ["Confirmed"]))
		dlx = self.f["room_types"]["DLX"]
		self.assertEqual(frappe.db.count("Reservation", {"room_type": dlx, "status": ("in", [
			"Confirmed", "Pending Payment", "Held", "Checked In"])}), 2)                # never oversold
		t = txn_state(payment["transaction"])
		self.assertEqual(t.reconciliation, "Action Required")        # paid in time: staff decide, no auto refund
		self.assertIn("in time", t.reconciliation_note)
		self.assertIn("rooms free now: no", t.reconciliation_note)   # the room was sold, not a duplicate

	def test_money_it_held_before_its_expiry_comes_back_with_it(self):
		b = self.book()
		part = (D(b["due_now"]) / 2).quantize(D("0.01"))
		cash = pay.record_manual(booking=b["booking"], amount=str(part), method="Cash", reference="first half",
		                         idempotency_key=f"b4-half-{b['booking']}")["transaction"]
		payment, at = self.paid_in_time(b)
		self.assertEqual(txn_state(cash).reconciliation, "Action Required")           # B2: off the expired booking
		with captured(at):
			self.assertEqual(self.pays(payment)["status"], "Succeeded")
		self.assertEqual(self.statuses(b), ("Confirmed", ["Confirmed"]))
		self.assertEqual(paid(b), D(b["due_now"]))
		self.assertEqual(pay.allocated_of(cash), part)
		self.assertEqual(txn_state(cash).reconciliation, "Resolved")

	def test_a_capture_within_the_clocks_tolerance_is_in_time_and_one_from_the_future_is_not(self):
		b = self.book()
		payment, at = self.paid_in_time(b)
		with captured(add_to_date(at, minutes=7)):                 # 2 minutes past its deadline
			self.assertEqual(self.pays(payment)["status"], "Succeeded")
		self.assertEqual(self.statuses(b), ("Confirmed", ["Confirmed"]))
		c = self.book()
		payment, _at = self.paid_in_time(c)
		with captured(add_to_date(now_datetime(), hours=1)):       # a time still to come is not believed
			self.assertEqual(self.pays(payment)["status"], "Succeeded")
		self.assertEqual(self.statuses(c), ("Cancelled", ["Cancelled"]))

	def transfer(self, b: dict) -> str:
		return public.pay_booking(token=b["manage_token"], payment_method="Bank Transfer")["transaction"]

	def test_a_bank_transfer_is_late_by_its_value_date(self):
		"""D3 (audit 1c): staff record the transfer's value date; money on the account before its hold
		ended takes its booking back, however late it was seen."""
		self.transfer_account()
		b = self.book(method="Bank Transfer")
		txn = self.transfer(b)
		passes(b["booking"], 3 * 24 * 60)                          # the 48-hour hold ended a day ago
		run_expiry_jobs()
		self.assertEqual(self.statuses(b)[0], "Cancelled")
		out = pay.mark_transfer_received(txn, reference="EFT-D3-1", value_date=add_days(nowdate(), -2))
		self.assertEqual(out["status"], "Succeeded")
		self.assertEqual(self.statuses(b), ("Confirmed", ["Confirmed"]))

	def test_a_transfer_valued_after_its_hold_is_late_and_a_future_one_is_refused(self):
		self.transfer_account()
		b = self.book(method="Bank Transfer")
		txn = self.transfer(b)
		passes(b["booking"], 3 * 24 * 60)
		run_expiry_jobs()
		with self.assertRaises(frappe.ValidationError):
			pay.mark_transfer_received(txn, reference="EFT-D3-2", value_date=add_days(nowdate(), 1))
		out = pay.mark_transfer_received(txn, reference="EFT-D3-2", value_date=nowdate())
		self.assertEqual(out["reconciliation"], "Action Required")
		self.assertEqual(self.statuses(b)[0], "Cancelled")

	def test_a_transfer_is_confirmed_with_the_amount_that_came(self):
		"""P1-11 + NEW-3 (audit 2B, ADR-065): the API requires the value date, as the page does; staff record
		the amount that arrived, at most the amount asked: a short transfer is allocated as it came and the
		booking waits for the rest (or expires with its hold)."""
		import json

		from kamra.tex.api import payments as payments_api
		from kamra.tex.money import from_db, to_str

		self.transfer_account()
		b = self.book(method="Bank Transfer")
		txn = self.transfer(b)
		asked = from_db(frappe.db.get_value("TEX Payment Transaction", txn, "amount"), "EUR")
		with self.assertRaisesRegex(frappe.ValidationError, "value date"):
			payments_api.mark_transfer_received(transaction=txn, reference="EFT-P111")
		with self.assertRaisesRegex(frappe.ValidationError, "at most"):
			payments_api.mark_transfer_received(transaction=txn, reference="EFT-P111", value_date=nowdate(),
			                                    amount=str(asked + 1))
		out = payments_api.mark_transfer_received(transaction=txn, reference="EFT-P111", value_date=nowdate(),
		                                          amount=str(asked - 5))            # the bank's fee came off
		self.assertEqual(out["status"], "Succeeded")
		self.assertEqual(D(frappe.db.get_value("TEX Payment Transaction", txn, "amount")), asked - 5)
		self.assertEqual(paid(b), asked - 5)
		row = frappe.db.get_value("TEX Booking", b["booking"], ["total_amount", "balance_amount", "status"], as_dict=True)
		self.assertEqual((D(row.balance_amount), row.status), (D(row.total_amount) - (asked - 5), "Pending Payment"))
		recorded = json.loads(frappe.db.get_value("TEX Audit Event", {"action": "payment.transfer_received",
		                                                              "reference_name": txn}, "new_value"))
		self.assertEqual((recorded["amount"], recorded["asked"]), (to_str(asked - 5), to_str(asked)))

	def test_a_transfer_amount_that_is_not_a_number_is_refused(self):
		"""P1-11 review: an amount that is not a finite number is told as such, never a server error."""
		from kamra.tex.api import payments as payments_api

		self.transfer_account()
		b = self.book(method="Bank Transfer")
		txn = self.transfer(b)
		for amount in ("NaN", "abc", "Infinity"):
			with self.subTest(amount=amount), self.assertRaisesRegex(frappe.ValidationError, "must be a number"):
				payments_api.mark_transfer_received(transaction=txn, reference="EFT-NAN", value_date=nowdate(),
				                                    amount=amount)
		self.assertEqual(frappe.db.get_value("TEX Payment Transaction", txn, "status"), "Pending")

	def transfer_account(self):
		bank = fx.ensure("TEX Payment Provider Account", {"property": fx.PROPERTY, "provider": "Bank Transfer"},
		                 {"label": "Bank transfer", "property": fx.PROPERTY, "provider": "Bank Transfer",
		                  "environment": "Sandbox", "enabled": 1, "currencies": "EUR"})
		fx.ensure("TEX Payment Method Rule", {"property": fx.PROPERTY, "method": "Bank Transfer"},
		          {"property": fx.PROPERTY, "method": "Bank Transfer", "provider_account": bank, "priority": 5})

	def test_a_guest_booked_again_for_the_stay_is_not_revived(self):
		"""D4 c) (user decision): the guest already has another live booking for the same stay (staff
		booked them again after the expiry): the paid-in-time booking is not revived, staff decide."""
		b = self.book()
		payment, at = self.paid_in_time(b)
		again = self.book(method="Pay at Hotel", status="Confirmed")        # the same guest, the same dates
		with captured(at):
			self.assertEqual(self.pays(payment)["status"], "Succeeded")
		self.assertEqual(self.statuses(b), ("Cancelled", ["Cancelled"]))
		t = txn_state(payment["transaction"])
		self.assertEqual(t.reconciliation, "Action Required")                # never refunded by itself
		self.assertIn(again["booking"], t.reconciliation_note)

	def test_a_revival_locks_the_charges_before_the_booking(self):
		"""D4: every payment path locks a charge, then its booking. A revival takes back the money the
		booking held when it expired (another charge): that charge is locked before the booking, never
		after (a staff refund of it, charge then booking, would deadlock with it)."""
		b = self.book()
		part = (D(b["due_now"]) / 2).quantize(D("0.01"))
		cash = pay.record_manual(booking=b["booking"], amount=str(part), method="Cash", reference="half",
		                         idempotency_key=f"d4-half-{b['booking']}")["transaction"]
		payment, at = self.paid_in_time(b)
		locks, real = [], frappe.db.sql

		def sql(query, values=(), *args, **kw):
			q = str(query).lower()
			if "for update" in q:
				locks.append((q, str(values)))
			return real(query, values, *args, **kw)

		with captured(at), mock.patch.object(frappe.db, "sql", side_effect=sql):
			self.assertEqual(self.pays(payment)["status"], "Succeeded")
		self.assertEqual(self.statuses(b), ("Confirmed", ["Confirmed"]))

		def first(table, name):
			return next(i for i, (q, v) in enumerate(locks) if table in q and name in v)

		self.assertLess(first("tabtex payment transaction", cash), first("tabtex booking", b["booking"]))

	def test_a_booking_cancelled_on_purpose_is_never_revived(self):
		b = self.book()
		payment = self.start_payment(b)
		booking.cancel_reservation(self.rooms(b)[0], reason="the guest called to cancel")
		with captured(now_datetime()):
			self.assertEqual(self.pays(payment)["status"], "Succeeded")
		self.assertEqual(self.statuses(b), ("Cancelled", ["Cancelled"]))
		self.assertEqual(txn_state(payment["transaction"]).reconciliation, "Action Required")


class TestReconciliationVisible(HoldCase):
	"""B5 (audit 1b): money kept off its booking is seen. The status page counts it with its age, the
	hotel's reservations team is e-mailed, the staff API says what happened to it, and the guest is
	told the payment came after the booking's time to pay — never "payment received"."""

	TEAM = "reservations.b5@example.com"

	def setUp(self):
		super().setUp()
		from kamra.tex.tests.integration.test_migrations_notify import ensure_test_outbox

		ensure_test_outbox()
		frappe.db.set_value("Property", fx.PROPERTY, "email", self.TEAM)

	def late(self, room: str = "STD") -> tuple[dict, dict]:
		b = self.book(room=room)
		payment = self.start_payment(b)
		passes(b["booking"], 60)
		run_expiry_jobs()
		return b, payment

	def recipients(self, doctype: str, name: str) -> list[str]:
		queues = frappe.get_all("Email Queue", filters={"reference_doctype": doctype, "reference_name": name},
		                        pluck="name")
		return frappe.get_all("Email Queue Recipient", filters={"parent": ("in", queues or [""])}, pluck="recipient")

	def reconciliation(self) -> dict:
		from kamra.tex.ops import status as system_status

		return next(c for c in system_status.collect(properties=[fx.PROPERTY]) if c["key"] == "payments.reconciliation")

	def test_the_status_page_counts_it_with_its_age(self):
		before = self.reconciliation()
		waiting = sum(i["params"]["count"] for i in before["issues"] if i["reason"] == "reconciliation_action")
		_b, payment = self.late()
		self.pays(payment)
		check = self.reconciliation()
		action = next(i for i in check["issues"] if i["reason"] == "reconciliation_action")
		self.assertEqual(action["params"]["count"], waiting + 1)
		self.assertIn(fx.PROPERTY, check["properties"])
		if not waiting:
			self.assertEqual((check["status"], action["params"]["hours"]), ("warn", 0.0))
		frappe.db.sql("""UPDATE `tabTEX Audit Event` SET event_time = event_time - INTERVAL 25 HOUR
		                 WHERE action='payment.reconciliation_required' AND reference_name=%s""", payment["transaction"])
		self.assertEqual(self.reconciliation()["status"], "fail")              # a day with no one acting on it

	def test_the_reservations_team_and_the_guest_are_told(self):
		b, payment = self.late()
		self.pays(payment)
		self.assertIn(self.TEAM, self.recipients("TEX Payment Transaction", payment["transaction"]))
		self.assertIn(GUEST["email"], self.recipients("TEX Booking", b["booking"]))
		sent = frappe.get_all("TEX Communication", filters={"booking": b["booking"]}, pluck="template")
		self.assertIn("payment_after_expiry", sent)
		self.assertNotIn("payment_received", sent)

	def test_the_staff_api_and_the_guest_page_say_what_happened(self):
		from kamra.tex.api import payments as payments_api

		b, payment = self.late()
		self.pays(payment)
		detail = payments_api.transaction(payment["transaction"])
		self.assertEqual(detail["reconciliation"], "Action Required")
		self.assertIn(b["booking"], detail["reconciliation_note"])
		listed = payments_api.transactions(property=fx.PROPERTY, booking=b["booking"])
		self.assertEqual(listed[0]["reconciliation"], "Action Required")
		guest = public.booking_status(token=b["manage_token"])
		self.assertEqual((guest["status"], guest["late_payment"]), ("Cancelled", "contact"))

	def test_money_whose_rooms_were_sold_is_announced_as_a_refund(self):
		self.book(room="DLX", method="Pay at Hotel", status="Confirmed")
		a, payment = self.late(room="DLX")
		self.book(room="DLX", method="Pay at Hotel", status="Confirmed")              # the last room, to B
		self.pays(payment)
		self.assertEqual(txn_state(payment["transaction"]).reconciliation, "Refund Queued")
		self.assertEqual(public.booking_status(token=a["manage_token"])["late_payment"], "refund")

	def test_a_booking_that_took_its_money_announces_nothing(self):
		b = self.book()
		self.pays(self.start_payment(b))
		self.assertIsNone(public.booking_status(token=b["manage_token"])["late_payment"])
		self.assertNotIn(self.TEAM, self.recipients("TEX Booking", b["booking"]))


def held_until(b: dict) -> list:
	return frappe.get_all("Reservation", filters={"tex_booking": b["booking"]}, pluck="hold_expires_on")


class TestExpiryFailureVisible(HoldCase):
	"""D9 (audit 1c): a booking whose expiry keeps failing ("TEX booking expiry failed …") keeps its
	rooms held: the status page shows it — the hotel's check of holds past their deadline fails, and
	the failures count among the TEX job errors."""

	def test_a_hold_its_expiry_cannot_end_is_on_the_status_page(self):
		from kamra.tex.ops import status as system_status

		b = self.book()
		passes(b["booking"], 45)
		with mock.patch("kamra.tex.services.booking.expire_booking", side_effect=frappe.ValidationError("broken")):
			booking.expire_pending_bookings()
		self.assertEqual(self.statuses(b)[0], "Pending Payment")                   # its rooms are still held
		checks = {c["key"]: c for c in system_status.collect(properties=[fx.PROPERTY], platform=True)}
		self.assertEqual(checks["holds.overdue"]["status"], "fail")
		self.assertIn(fx.PROPERTY, checks["holds.overdue"]["properties"])
		self.assertGreaterEqual(checks["scheduler.errors"]["count"], 1)


class TestDeadlockRetries(HoldCase):
	"""C3 (audit 1c): a payment's outcome chosen as a deadlock victim is applied again (``complete`` is
	idempotent), never left Pending unreconciled; the guest's and staff's payment endpoints run again
	too."""

	def test_a_payment_callback_that_deadlocks_is_applied_again(self):
		b = self.book()
		payment = self.start_payment(b)
		real_allocate, real_rollback, calls = pay.allocate, frappe.db.rollback, []
		frappe.db.savepoint("c3")

		def allocate(*args, **kw):
			calls.append(1)
			if len(calls) == 1:
				raise frappe.QueryDeadlockError("Deadlock found when trying to get lock")
			return real_allocate(*args, **kw)

		def rollback(*args, **kw):                    # the test's own transaction stands for the request's
			return real_rollback(*args, **kw) if kw.get("save_point") else real_rollback(save_point="c3")

		with mock.patch.object(pay, "allocate", side_effect=allocate), \
				mock.patch.object(frappe.db, "rollback", side_effect=rollback):
			self.assertEqual(self.pays(payment)["status"], "Succeeded")
		self.assertEqual(len(calls), 2)
		self.assertEqual(self.statuses(b), ("Confirmed", ["Confirmed"]))

	def test_a_payment_callback_that_times_out_waiting_for_a_lock_is_applied_again(self):
		"""P1-8: a lock wait timeout in ``complete`` (money captured) is run again like a deadlock, after a
		full rollback: the statement that timed out was the only one undone."""
		b = self.book()
		payment = self.start_payment(b)
		real_allocate, real_rollback, calls = pay.allocate, frappe.db.rollback, []
		frappe.db.savepoint("c3")

		def allocate(*args, **kw):
			calls.append(1)
			if len(calls) == 1:
				raise frappe.QueryTimeoutError("Lock wait timeout exceeded; try restarting transaction")
			return real_allocate(*args, **kw)

		def rollback(*args, **kw):                    # the test's own transaction stands for the request's
			return real_rollback(*args, **kw) if kw.get("save_point") else real_rollback(save_point="c3")

		with mock.patch.object(pay, "allocate", side_effect=allocate), \
				mock.patch.object(frappe.db, "rollback", side_effect=rollback):
			self.assertEqual(self.pays(payment)["status"], "Succeeded")
		self.assertEqual(len(calls), 2)
		self.assertEqual(self.statuses(b), ("Confirmed", ["Confirmed"]))

	def test_a_request_that_put_a_step_on_record_is_not_run_again(self):
		"""P1-8 e (NEW-6): a request that committed a step (``_commit_step``) and then meets a deadlock is not
		run again from the start: its first steps are on record. One without a committed step is."""
		from kamra.tex.services.txn import retry_on_deadlock

		real_rollback, calls = frappe.db.rollback, []
		frappe.db.savepoint("c3")

		def rollback(*args, **kw):
			return real_rollback(*args, **kw) if kw.get("save_point") else real_rollback(save_point="c3")

		@retry_on_deadlock
		def committed_then_deadlocked():
			calls.append("committed")
			pay._commit_step()
			raise frappe.QueryDeadlockError("Deadlock found when trying to get lock")

		@retry_on_deadlock
		def deadlocked():
			calls.append("plain")
			raise frappe.QueryDeadlockError("Deadlock found when trying to get lock")

		with mock.patch.object(frappe.db, "rollback", side_effect=rollback), mock.patch("time.sleep"):
			with self.assertRaises(frappe.ValidationError):
				committed_then_deadlocked()
			with self.assertRaises(frappe.ValidationError):
				deadlocked()
		self.assertEqual(calls, ["committed", "plain", "plain", "plain"])

	def test_a_reverify_keeps_no_message_of_a_token_that_failed(self):
		"""P1-8: staff re-verify an iyzico charge with two checkout tokens; the first try fails with a
		message, the next confirms it: the answer carries no message of the failed try."""
		from kamra.tex.api import payments as payments_api

		txn = pay._new_txn(property=fx.PROPERTY, txn_type="Charge", method="Card", amount=D("100"), currency="EUR",
		                   provider="iyzico", provider_ref="tok-b tok-a", idempotency_key="p18-reverify").name
		tries = []

		def complete_retrying(transaction, **kw):
			tries.append(kw["params"])
			if len(tries) == 1:
				frappe.throw("The hotel is very busy right now. Please try again in a moment.")
			return {"status": "Succeeded", "transaction": transaction}

		frappe.local.message_log = []
		with mock.patch.object(pay, "complete_retrying", side_effect=complete_retrying):
			self.assertEqual(payments_api.reverify(transaction=txn)["status"], "Succeeded")
		self.assertEqual(len(tries), 2)
		self.assertEqual(frappe.local.message_log, [])

	def test_the_payment_endpoints_run_again_on_a_deadlock(self):
		from kamra.tex.api import crm as crm_api
		from kamra.tex.api import crs
		from kamra.tex.api import payments as payments_api

		def retried(fn) -> bool:
			while fn is not None:
				if fn.__code__.co_qualname == "retry_on_deadlock.<locals>.wrapper":     # wraps copies __qualname__
					return True
				fn = getattr(fn, "__wrapped__", None)
			return False

		for fn in (public.pay_booking, public.pay_link, public.manage_cancel, public.mock_pay, crs.cancel,
		           payments_api.allocate, payments_api.transfer, payments_api.mark_transfer_received,
		           payments_api.record_manual, payments_api.create_link, payments_api.cancel_link,
		           payments_api.reverify, payments_api.reissue_link, crm_api.loyalty_redeem, crm_api.merge_guests):
			self.assertTrue(retried(fn), fn.__name__)


class TestPaymentsVerifiedByTheJob(HoldCase):
	"""NEW-2 (audit 2E-2): a card payment whose guest never came back from the gateway is asked for by the
	5-minute job, before that tick's expiry: its booking is confirmed, never expired. Only charges that
	may still be paid are asked, one at a time, each on record before the next question."""

	@contextmanager
	def askable(self):
		"""The sandbox gateway answers a status query: its page's success for each charge. → the charges asked."""
		from kamra.tex.payments.providers.simple import MockProvider, mock_signature

		asked: list[str] = []

		def status_params(provider_ref):
			txn = str(provider_ref or "").split("MOCK-", 1)[-1]
			asked.append(txn)
			return [{"outcome": "success", "sig": mock_signature(pay._mock_secret(), txn, "success")}]

		with mock.patch.object(MockProvider, "status_query", True), \
				mock.patch.object(MockProvider, "status_params", staticmethod(status_params)):
			yield asked

	def tick(self) -> None:
		"""The payment jobs of one 5-minute tick, in their order there (``_run``'s rollback would take the test's
		data with it on an error)."""
		from kamra.tex import scheduler

		for job in scheduler.EVERY_5_MINUTES:
			if job in ("kamra.tex.payments.service.reverify_pending", "kamra.tex.services.booking.expire_pending_bookings"):
				frappe.get_attr(job)()

	def test_a_payment_whose_guest_never_came_back_confirms_its_booking(self):
		b = self.book()
		payment = self.start_payment(b)
		passes(b["booking"], 26)                                   # hold and checkout over, no job ran yet
		with self.askable() as asked:
			self.tick()
		self.assertEqual(asked, [payment["transaction"]])
		self.assertEqual(txn_state(payment["transaction"]).status, "Succeeded")
		self.assertEqual(self.statuses(b), ("Confirmed", ["Confirmed"]))
		self.assertFalse(frappe.db.exists("TEX Audit Event", {"action": "booking.expire", "reference_name": b["booking"]}))

	def test_only_payments_that_may_still_be_paid_are_asked(self):
		guests = [dict(GUEST, email=f"new2-{n}@example.com") for n in range(3)]
		old, live, due = (self.book(guest=g) for g in guests)
		payments = {k: self.start_payment(b)["transaction"] for k, b in (("old", old), ("live", live), ("due", due))}
		passes(old["booking"], 26 + 180)                           # its deadline 3 hours ago
		passes(live["booking"], 26)
		passes(due["booking"], 26)
		frappe.db.set_value("TEX Payment Transaction", payments["live"], "checkout_started_at", now_datetime(),
		                    update_modified=False)                  # a start is asking the gateway right now
		with self.askable() as asked:
			pay.reverify_pending()
		self.assertEqual(asked, [payments["due"]])

	def test_a_disabled_account_is_not_asked(self):
		b = self.book()
		payment = self.start_payment(b)
		passes(b["booking"], 26)
		frappe.db.set_value("TEX Payment Provider Account", self.account, "enabled", 0)
		with self.askable() as asked:
			pay.reverify_pending()
		self.assertEqual(asked, [])
		self.assertEqual(txn_state(payment["transaction"]).status, "Pending")

	def test_a_gateway_error_is_logged_and_the_next_payment_is_still_asked(self):
		from kamra.tex.payments.providers.simple import MockProvider

		first, second = (self.book(guest=dict(GUEST, email=f"new2-err-{n}@example.com")) for n in range(2))
		broken, fine = self.start_payment(first)["transaction"], self.start_payment(second)["transaction"]
		passes(first["booking"], 27)
		passes(second["booking"], 26)
		real = MockProvider.handle_callback

		def handle_callback(provider, transaction, *args, **kw):
			if transaction == broken:
				raise RuntimeError("gateway unreachable")
			return real(provider, transaction, *args, **kw)

		with self.askable() as asked, mock.patch.object(MockProvider, "handle_callback", handle_callback):
			pay.reverify_pending()
		self.assertEqual(asked, [broken, fine])
		self.assertEqual((txn_state(broken).status, txn_state(fine).status), ("Pending", "Succeeded"))
		self.assertTrue(frappe.db.exists("Error Log", {"method": f"TEX payment re-verify {broken}"}))
		self.assertEqual(frappe.db.get_value("TEX Booking", second["booking"], "status"), "Confirmed")

	def test_money_the_job_finds_after_the_expiry_is_a_late_payment(self):
		b = self.book()
		payment = self.start_payment(b)
		passes(b["booking"], 60)
		run_expiry_jobs()
		self.assertEqual(self.statuses(b)[0], "Cancelled")
		with self.askable() as asked:
			pay.reverify_pending()
		self.assertEqual(asked, [payment["transaction"]])
		t = txn_state(payment["transaction"])
		self.assertEqual((t.status, t.reconciliation), ("Succeeded", "Action Required"))    # ADR-062 b), rooms free
		self.assertEqual(self.statuses(b)[0], "Cancelled")


class TestReconciliationStates(HoldCase):
	"""C4 (audit 1c): a charge in reconciliation leaves it only when its money is settled — refunded
	(through the gateway, or outside it and recorded), or allocated by staff. A refund still waiting
	for its answer settles nothing; a refund found not made after all opens it again."""

	def parked(self) -> tuple[dict, str]:
		b = self.book()
		payment = self.start_payment(b)
		passes(b["booking"], 60)
		run_expiry_jobs()
		self.pays(payment)
		self.assertEqual(txn_state(payment["transaction"]).reconciliation, "Action Required")
		return b, payment["transaction"]

	def refund_unanswered(self, txn: str) -> str:
		from kamra.tex.payments.providers.simple import MockProvider

		amount = frappe.db.get_value("TEX Payment Transaction", txn, "amount")
		with mock.patch.object(MockProvider, "refund", side_effect=RuntimeError("gateway timeout")):
			with self.assertRaises(pay.RefundUnknown):
				pay.refund(txn, amount=str(amount), reason="the guest asked", idempotency_key=f"c4-{txn}")
		return frappe.db.get_value("TEX Payment Transaction", {"parent_transaction": txn, "txn_type": "Refund"}, "name")

	def expired_with_a_refund_unanswered(self) -> tuple[dict, str, str]:
		"""P1-3: a FLEX booking by card, never confirmed, holds a half link's charge C; 40 of C is refunded
		off it and the gateway does not answer; the booking expires with it on its way. → (b, C, refund)."""
		from kamra.tex.payments.providers.simple import MockProvider

		b = self.book(method="Card")
		half = (D(b["due_now"]) / 2).quantize(D("0.01"))
		link = pay.create_link(property=fx.PROPERTY, amount=str(half), currency="EUR", description="First half",
		                       booking=b["booking"])
		started = public.pay_link(token=link["token"])
		public.mock_pay(transaction=started["transaction"], outcome="success", sig=started["fields"]["success_sig"])
		c = started["transaction"]
		with mock.patch.object(MockProvider, "refund", side_effect=RuntimeError("gateway timeout")):
			with self.assertRaises(pay.RefundUnknown):
				pay.refund(c, amount="40", reason="the guest asked", idempotency_key=f"p13-{c}", booking=b["booking"])
		refund = frappe.db.get_value("TEX Payment Transaction", {"parent_transaction": c, "txn_type": "Refund"}, "name")
		passes(b["booking"], 24 * 60 + 5)
		run_expiry_jobs()
		self.assertEqual(self.statuses(b)[0], "Cancelled")
		self.assertEqual(paid(b), D(40))                                  # the refund on its way stays on it
		return b, c, refund

	@staticmethod
	def releases(c: str) -> list[tuple[str, D]]:
		rows = frappe.get_all("TEX Payment Allocation", filters={"transaction": c, "allocation_type": "Release"},
		                      fields=["idempotency_key", "amount"], order_by="creation asc, name asc")
		return [(r.idempotency_key, D(r.amount)) for r in rows]

	def test_a_refund_on_its_way_when_an_unconfirmed_booking_ended_leaves_no_money_on_it(self):
		"""P1-3 (audit 2B, ADR-065): once the refund's outcome is known, a booking cancelled before it was
		ever confirmed holds none of the money: whatever the outcome, it comes off into reconciliation."""
		for outcome in ("Failed", "Succeeded"):
			with self.subTest(outcome=outcome):
				b, c, refund = self.expired_with_a_refund_unanswered()
				expired = self.releases(c)
				key = lambda raw: pay.ns_key(fx.PROPERTY, raw, "release")  # noqa: E731
				self.assertEqual([k for k, _a in expired], [key(f"expired:{b['booking']}:{c}")])
				with mock.patch("kamra.tex.services.notify.payment_after_expiry") as guest_mail:
					pay.finish_unknown_refund(refund, outcome=outcome, reference="GW-P13", reason="seen at the gateway")
				guest_mail.assert_not_called()
				self.assertEqual((paid(b), pay.allocated_of(c)), (D(0), D(0)))
				self.assertEqual(txn_state(c).reconciliation, "Action Required")
				after = self.releases(c)
				self.assertEqual(after[:1], expired)                           # the expiry's release as it was
				self.assertEqual(after[1:], [(key(f"refund:{refund}:{b['booking']}:{c}"), D(40))])

	def test_a_durable_refund_naming_no_booking_whose_booking_expires_meanwhile_leaves_no_money_on_it(self):
		"""P1-3 review: staff refund 40 of a half link's charge without naming the booking (the dialog's
		default); while the gateway works the booking expires (never confirmed), and the refund, decided again
		once answered, comes out of the money the expiry released: the 40 still on the booking comes off it."""
		from kamra.tex.payments.providers.simple import MockProvider

		b = self.book(method="Card")
		half = (D(b["due_now"]) / 2).quantize(D("0.01"))
		link = pay.create_link(property=fx.PROPERTY, amount=str(half), currency="EUR", description="First half",
		                       booking=b["booking"])
		started = public.pay_link(token=link["token"])
		public.mock_pay(transaction=started["transaction"], outcome="success", sig=started["fields"]["success_sig"])
		c = started["transaction"]
		real = MockProvider.refund

		def expires_meanwhile(provider, *args, **kw):
			booking.expire_booking(b["booking"], force=True)
			return real(provider, *args, **kw)

		with mock.patch.object(MockProvider, "refund", expires_meanwhile):
			out = pay.refund(c, amount="40", reason="the guest asked", idempotency_key=f"p13d-{c}", durable=True)
		self.assertEqual(out["status"], "Succeeded")
		self.assertEqual(self.statuses(b)[0], "Cancelled")
		self.assertEqual(paid(b), D(0))
		self.assertEqual(txn_state(c).reconciliation, "Action Required")

	def test_a_refund_of_a_confirmed_booking_locks_none_of_its_payments_after_its_outcome(self):
		"""P1-3 review: ``after_refund`` reads the booking first (a locking read: its state now) and locks none
		of its payments unless it is cancelled: locking them after the booking would invert the order a payment
		callback takes (payment, then booking)."""
		import re

		from kamra.tex.services import late_payments

		b = self.book()
		payment = self.start_payment(b)
		self.pays(payment)
		self.assertEqual(self.statuses(b)[0], "Confirmed")
		real, sql = late_payments.after_refund, frappe.db.sql
		locks: list[str] = []

		def spied(*args, **kw):
			def recording(query, *a, **k):
				# the booking's own row may be locked (review 2: its status is read as it is now); its payments never
				if re.search(r"FOR UPDATE|LOCK IN SHARE MODE", str(query), re.I) and "tabTEX Payment" in str(query):
					locks.append(" ".join(str(query).split()))
				return sql(query, *a, **k)

			with mock.patch.object(frappe.db, "sql", side_effect=recording):
				return real(*args, **kw)

		with mock.patch.object(late_payments, "after_refund", side_effect=spied) as after:
			out = pay.refund(payment["transaction"], amount="10", reason="goodwill",
			                 idempotency_key=f"p13r-{b['booking']}", booking=b["booking"])
		self.assertEqual(out["status"], "Succeeded")
		after.assert_called_once()
		self.assertEqual(locks, [])

	def test_money_given_back_outside_tex_settles_it(self):
		_b, txn = self.parked()
		amount = frappe.db.get_value("TEX Payment Transaction", txn, "amount")
		pay.refund_outside(txn, amount=str(amount), reason="refunded at the desk", reference="cash 7",
		                   idempotency_key=f"c4-out-{txn}")
		self.assertEqual(txn_state(txn).reconciliation, "Refunded")

	def test_a_refund_waiting_for_its_answer_settles_nothing_until_staff_record_it(self):
		_b, txn = self.parked()
		refund = self.refund_unanswered(txn)
		self.assertEqual(txn_state(txn).reconciliation, "Action Required")        # it may not have been made
		pay.finish_unknown_refund(refund, outcome="Succeeded", reference="GW-1", reason="seen at the gateway")
		self.assertEqual(txn_state(txn).reconciliation, "Refunded")

	def test_a_refund_found_not_made_opens_it_again(self):
		_b, txn = self.parked()
		refund = self.refund_unanswered(txn)
		pay.finish_unknown_refund(refund, outcome="Succeeded", reference="GW-2", reason="looked refunded")
		self.assertEqual(txn_state(txn).reconciliation, "Refunded")
		frappe.get_doc({"doctype": "TEX Audit Event", "action": "payment.refund_outcome_conflict", "event_time":
		                now_datetime(), "reference_doctype": "TEX Payment Transaction", "reference_name": refund,
		                "property": fx.PROPERTY, "new_value": '{"recorded": "Succeeded", "gateway": "Failed"}'}).insert(
			ignore_permissions=True)
		pay.correct_refund(refund, outcome="Failed", reason="the gateway never paid it back")
		self.assertEqual(txn_state(txn).reconciliation, "Action Required")


class TestMoneyShownRight(HoldCase):
	"""C7 (audit 1c): the payment report, a payment link and a booking's payment status show where the
	money is: a late payment refunded nets to nothing, a link whose money was parked is not "Paid", and
	a booking whose money came off it at its expiry is not "Paid"."""

	def test_a_late_payment_refunded_nets_to_nothing_in_the_payment_report(self):
		from kamra.tex.api import reports as rep_api
		from kamra.tex.services import late_payments

		self.book(room="DLX", method="Pay at Hotel", status="Confirmed")
		a = self.book(room="DLX")
		payment = self.start_payment(a)
		frappe.db.sql("UPDATE `tabReservation` SET status='Cancelled' WHERE tex_booking=%s", a["booking"])
		self.book(room="DLX", method="Pay at Hotel", status="Confirmed")           # the last room, to B
		passes(a["booking"], 60)
		self.pays(payment)
		late_payments.refund_queued()
		self.assertEqual(txn_state(payment["transaction"]).reconciliation, "Refunded")
		out = rep_api.report(view="payment", property=fx.PROPERTY, stay_from=str(fx.d(6, 1)), stay_to=str(fx.d(6, 30)))
		t = out["totals"]["EUR"]
		self.assertEqual((D(t["charged"]), D(t["refunded"])), (D(a["due_now"]), D(a["due_now"])))

	def test_a_capture_tex_refused_and_its_refund_are_both_left_out_of_the_payment_report(self):
		"""K1 (audit 1c-son): a capture TEX refused to count (G-67: the gateway stated another amount) is
		no charge of the booking, and the refund giving it back is no refund of the booking's money: both
		are left out, never one without the other."""
		import dataclasses

		from kamra.tex.api import reports as rep_api
		from kamra.tex.payments.providers.simple import MockProvider

		b = self.book(room="DLX")
		payment = self.start_payment(b)
		real = MockProvider.handle_callback

		def another_amount(provider, *args, **kw):
			return dataclasses.replace(real(provider, *args, **kw), amount="1.00")

		with mock.patch.object(MockProvider, "handle_callback", another_amount):
			self.assertEqual(self.pays(payment)["status"], "Failed")
		r = pay.refund(payment["transaction"], amount="1.00", reason="captured but refused",
		               idempotency_key=f"k1-{b['booking']}")
		self.assertEqual(r["status"], "Succeeded")
		out = rep_api.report(view="payment", property=fx.PROPERTY, stay_from=str(fx.d(6, 1)), stay_to=str(fx.d(6, 30)))
		t = out["totals"]["EUR"]
		self.assertEqual((D(t["charged"]), D(t["refunded"])), (D(0), D(0)))
		self.assertEqual([(m["charges"], m["refunds"]) for m in out["methods"]], [])

	def test_a_link_whose_money_was_parked_is_not_paid(self):
		b = self.book()
		link = pay.create_link(property=fx.PROPERTY, amount=b["due_now"], currency="EUR", description="Deposit",
		                       booking=b["booking"])
		started = public.pay_link(token=link["token"])
		passes(b["booking"], 24 * 60 + 5)
		run_expiry_jobs()
		public.mock_pay(transaction=started["transaction"], outcome="success", sig=started["fields"]["success_sig"])
		self.assertEqual(txn_state(started["transaction"]).reconciliation, "Action Required")
		self.assertNotEqual(frappe.db.get_value("TEX Payment Link", link["link"], "status"), "Paid")

	def test_a_booking_cancelled_for_free_and_refunded_in_full_reads_refunded(self):
		"""P1-10 (audit 2B, ADR-065): one payment status formula wherever it is written: a cancelled booking
		owing nothing reads "Paid" while its money is on it, and "Refunded" once all of it went back."""
		b = self.book()                                                     # FLEX by card
		payment = self.start_payment(b)
		self.pays(payment)
		self.assertEqual(self.statuses(b)[0], "Confirmed")
		booking.cancel_reservation(self.rooms(b)[0], reason="free cancellation")
		state = lambda: frappe.db.get_value("TEX Booking", b["booking"], ["status", "total_amount",  # noqa: E731
		                                                                  "payment_status"])
		self.assertEqual(state(), ("Cancelled", 0, "Paid"))                # nothing owed, the money on it
		pay.refund(payment["transaction"], amount=b["due_now"], reason="free cancellation",
		           idempotency_key=f"p110-{b['booking']}", booking=b["booking"])
		self.assertEqual(state(), ("Cancelled", 0, "Refunded"))            # apply_payment's reading
		booking._refresh_booking_after_change(b["booking"])
		self.assertEqual(state(), ("Cancelled", 0, "Refunded"))            # the refresh reads the same

	def test_a_booking_whose_money_came_off_at_its_expiry_is_not_paid(self):
		b = self.book()
		pay.record_manual(booking=b["booking"], amount="50", method="Cash", reference="desk",
		                  idempotency_key=f"c7-{b['booking']}")
		passes(b["booking"], 25)
		run_expiry_jobs()
		self.assertEqual(frappe.db.get_value("TEX Booking", b["booking"], ["status", "payment_status"]),
		                 ("Cancelled", "Unpaid"))


class TestPaymentLinkHold(HoldCase):
	"""B6 (audit 1b), the real flow: an agent books by card (a 20-minute hold), then sends the guest a
	payment link. Sending it holds the rooms for the link hold (the hotel's, else TEX Settings, 24 hours
	by default); the link expires with the hold; the response and the e-mail say until when."""

	def send_link(self, b: dict, **kw) -> dict:
		return pay.create_link(property=fx.PROPERTY, amount=b["due_now"], currency="EUR", description="Deposit",
		                       expires_hours=72, booking=b["booking"], **kw)

	def test_a_link_holds_the_rooms_for_the_link_hold_and_its_payment_confirms(self):
		b = self.book(method="Card")
		out = self.send_link(b)
		until = held_until(b)[0]
		self.assertAlmostEqual((until - now_datetime()).total_seconds() / 60, 1440, delta=2)
		self.assertEqual(frappe.db.get_value("TEX Payment Link", out["link"], "expires_at"), until)
		self.assertEqual((out["expires_at"], out["rooms_held_until"]), (str(until), str(until)))
		self.assertTrue(frappe.db.exists("TEX Audit Event", {"action": "booking.hold_extended",
		                                                     "reference_name": b["booking"]}))
		passes(b["booking"], 25)                                   # the card's 20 minutes are long over
		run_expiry_jobs()
		self.assertEqual(self.statuses(b), ("Pending Payment", ["Pending Payment"]))
		started = public.pay_link(token=out["token"])
		public.mock_pay(transaction=started["transaction"], outcome="success", sig=started["fields"]["success_sig"])
		self.assertEqual(self.statuses(b), ("Confirmed", ["Confirmed"]))

	def test_the_hotels_link_hold_decides(self):
		frappe.db.set_value("Property", fx.PROPERTY, "tex_hold_minutes_link", 120)
		b = self.book(method="Card")
		out = self.send_link(b)
		until = held_until(b)[0]
		self.assertAlmostEqual((until - now_datetime()).total_seconds() / 60, 120, delta=2)
		self.assertEqual(frappe.db.get_value("TEX Payment Link", out["link"], "expires_at"), until)

	def test_the_link_expires_with_its_hold(self):
		b = self.book(method="Card")
		out = self.send_link(b)
		passes(b["booking"], 24 * 60 + 5)
		run_expiry_jobs()
		pay.expire_links()
		self.assertEqual(self.statuses(b), ("Cancelled", ["Cancelled"]))
		self.assertEqual(frappe.db.get_value("TEX Payment Link", out["link"], "status"), "Expired")

	def test_no_link_for_a_booking_that_expired(self):
		"""D5 (audit 1c): a booking whose hold is over (cancelled) gets no link — never a silent 72-hour
		link for rooms it no longer holds; a confirmed booking still gets one for its balance."""
		b = self.book(method="Card")
		passes(b["booking"], 25)
		run_expiry_jobs()
		with self.assertRaises(frappe.ValidationError):
			self.send_link(b)
		self.assertFalse(frappe.db.exists("TEX Payment Link", {"booking": b["booking"]}))
		kept = self.book(method="Pay at Hotel", status="Confirmed")
		out = pay.create_link(property=fx.PROPERTY, amount=kept["balance"], currency="EUR", description="Balance",
		                      expires_hours=72, booking=kept["booking"])
		self.assertIsNone(out["rooms_held_until"])

	def test_a_link_for_a_reservation_pays_its_booking(self):
		"""D6 (audit 1c): a link made for a room (reservation only) belongs to that room's booking: it
		holds its rooms, and its payment reaches the booking and confirms it."""
		b = self.book(method="Card")
		out = pay.create_link(property=fx.PROPERTY, amount=b["due_now"], currency="EUR", description="Room",
		                      expires_hours=72, reservation=self.rooms(b)[0])
		self.assertEqual(frappe.db.get_value("TEX Payment Link", out["link"], "booking"), b["booking"])
		started = public.pay_link(token=out["token"])
		public.mock_pay(transaction=started["transaction"], outcome="success", sig=started["fields"]["success_sig"])
		self.assertEqual(self.statuses(b), ("Confirmed", ["Confirmed"]))
		self.assertEqual(pay.allocated_of(started["transaction"]), D(b["due_now"]))

	def test_a_link_never_holds_the_rooms_past_the_arrival_day(self):
		"""D7 (audit 1c), E3: the link hold ends at the latest at the end of the arrival day; a link sent
		on the arrival day itself stays valid until that day ends."""
		from datetime import datetime, time, timedelta

		from kamra.tex.services import holds

		b = self.book(method="Card")
		arrival = datetime.combine(fx.d(6, 10), time.min)
		now = arrival + timedelta(hours=9)                              # the morning of the arrival day
		frappe.db.sql("UPDATE `tabReservation` SET hold_expires_on=%s WHERE tex_booking=%s",
		              (now + timedelta(minutes=20), b["booking"]))
		expires, held = holds.hold_for_link(b["booking"], arrival + timedelta(days=2), now=now)[:2]
		day_end = datetime.combine(fx.d(6, 10), time(23, 59, 59))
		self.assertEqual((expires, held, held_until(b)[0]), (day_end, day_end, day_end))

	def test_cancelling_a_link_gives_its_extension_back(self):
		"""D7 (audit 1c): a cancelled link no longer holds the rooms: the hold goes back to what the
		booking's other open links, or its own payment method, give it."""
		b = self.book(method="Card")
		base = held_until(b)[0]
		first, second = self.send_link(b), self.send_link(b)
		kept = frappe.db.get_value("TEX Payment Link", second["link"], "expires_at")
		pay.cancel_link(first["link"], reason="sent twice")
		self.assertEqual(held_until(b)[0], kept)                     # the other open link keeps its hold
		back = pay.cancel_link(second["link"], reason="the guest pays at the desk")
		self.assertEqual(held_until(b)[0], back)
		self.assertAlmostEqual((back - base).total_seconds(), 0, delta=60)     # its card hold, from now
		self.assertTrue(frappe.db.exists("TEX Audit Event", {"action": "booking.hold_restored",
		                                                     "reference_name": b["booking"]}))

	def test_a_paid_link_keeps_holding_when_the_other_is_cancelled(self):
		"""E3 (audit 1c-son): two links for half each; the guest pays the first, staff cancel the second.
		The paid link held the rooms while its money came: the hold stays until it expires, and the
		booking waits for the rest."""
		b = self.book(method="Card")
		half = (D(b["due_now"]) / 2).quantize(D("0.01"))
		first, second = (pay.create_link(property=fx.PROPERTY, amount=str(half), currency="EUR", description=f"Half {i}",
		                                 booking=b["booking"]) for i in (1, 2))
		started = public.pay_link(token=first["token"])
		public.mock_pay(transaction=started["transaction"], outcome="success", sig=started["fields"]["success_sig"])
		passes(b["booking"], 25)                                        # the card's 20 minutes are long over
		pay.cancel_link(second["link"], reason="the guest pays the rest at the desk")
		self.assertEqual(held_until(b)[0], frappe.db.get_value("TEX Payment Link", first["link"], "expires_at"))
		run_expiry_jobs()
		self.assertEqual(self.statuses(b), ("Pending Payment", ["Pending Payment"]))

	def test_a_link_cancelled_later_leaves_the_payment_methods_hold_from_now(self):
		"""E3 (audit 1c-son): the one link is cancelled 20 minutes after the booking (the guest pays at the
		desk): the rooms are never given back at once, they stay held for the card's 20 minutes from now."""
		b = self.book(method="Card")
		out = self.send_link(b)
		passes(b["booking"], 20)
		back = pay.cancel_link(out["link"], reason="the guest pays at the desk")
		self.assertAlmostEqual((back - now_datetime()).total_seconds() / 60, 20, delta=1)
		run_expiry_jobs()
		self.assertEqual(self.statuses(b), ("Pending Payment", ["Pending Payment"]))

	def test_the_second_link_of_a_booking_paid_in_full_cannot_be_paid(self):
		"""E4 (audit 1c-son): the D1 confirmation leaves nothing owed (shortened after its first half was
		paid): its other link is closed, audited, and cannot be paid — never 200 paid for 100."""
		from kamra.tex.services import modification

		b = self.book(rate_plan="NRF")
		half = (D(b["total"]) / 2).quantize(D("0.01"))
		first, second = (pay.create_link(property=fx.PROPERTY, amount=str(half), currency="EUR", description=f"Half {i}",
		                                 booking=b["booking"]) for i in (1, 2))
		started = public.pay_link(token=first["token"])
		public.mock_pay(transaction=started["transaction"], outcome="success", sig=started["fields"]["success_sig"])
		p = modification.propose(self.rooms(b)[0], {"check_out": str(fx.d(6, 11))})
		modification.apply(p["proposal_token"], reason="one night only")
		self.assertEqual(self.statuses(b)[0], "Confirmed")
		self.assertEqual(frappe.db.get_value("TEX Payment Link", second["link"], "status"), "Cancelled")
		self.assertTrue(frappe.db.exists("TEX Audit Event", {"action": "payment_link.closed",
		                                                     "reference_name": second["link"]}))
		with self.assertRaisesRegex(frappe.ValidationError, "cancelled"):
			public.pay_link(token=second["token"])
		self.assertEqual(paid(b), half)

	def test_a_second_links_money_for_a_booking_already_paid_is_kept_off_it(self):
		"""P1-7 b (audit 2B, ADR-065): two links for what the booking owes, both opened; the first pays it
		(and closes the second); the second's open checkout is paid too: the booking takes at most what it
		owes, the rest stays on the charge for staff (OVERPAID), never twice on the booking."""
		import json

		b = self.book(rate_plan="NRF")
		first, second = self.send_link(b), self.send_link(b)
		t1, t2 = public.pay_link(token=first["token"]), public.pay_link(token=second["token"])
		for t in (t1, t2):
			public.mock_pay(transaction=t["transaction"], outcome="success", sig=t["fields"]["success_sig"])
		total = D(frappe.db.get_value("TEX Booking", b["booking"], "total_amount"))
		self.assertEqual((self.statuses(b)[0], paid(b)), ("Confirmed", total))
		self.assertEqual(pay.allocated_of(t2["transaction"]), D(0))
		self.assertEqual(txn_state(t2["transaction"]).reconciliation, "Action Required")
		why = frappe.get_all("TEX Audit Event", filters={"action": "payment.reconciliation_required",
		                                                 "reference_name": t2["transaction"]}, pluck="new_value")
		self.assertEqual([json.loads(v)["why"] for v in why], ["OVERPAID"])

	def test_a_link_in_another_currency_than_its_booking_is_refused(self):
		"""P1-5 (D-10, ADR-065): a booking is paid in its own currency; a link asking another one is never
		made, sent again or paid."""
		b = self.book(method="Card")
		with self.assertRaisesRegex(frappe.ValidationError, "is in EUR"):
			pay.create_link(property=fx.PROPERTY, amount="100", currency="TRY", description="Deposit",
			                booking=b["booking"])
		with self.assertRaisesRegex(frappe.ValidationError, "is in EUR"):
			pay.create_link(property=fx.PROPERTY, amount="100", currency="TRY", description="Deposit",
			                reservation=self.rooms(b)[0])
		link = self.send_link(b)
		frappe.db.set_value("TEX Payment Link", link["link"], "currency", "TRY")       # made before D-10
		with self.assertRaisesRegex(frappe.ValidationError, "cannot be paid online"):
			public.pay_link(token=link["token"])
		with self.assertRaisesRegex(frappe.ValidationError, "this link asks TRY"):
			pay.reissue_link(link["link"])

	def test_money_that_came_in_another_currency_is_recorded_and_kept_off_the_booking(self):
		"""P1-5 (D-10): a checkout opened in another currency (a link made before D-10) is paid: the charge
		is recorded, never undone, kept off the booking for staff, and the link is closed."""
		import json

		from kamra.tex.services import sites

		b = self.book(method="Card")
		link = self.send_link(b)
		frappe.db.set_value("TEX Payment Link", link["link"], "currency", "TRY")
		started = pay.start_payment(property=fx.PROPERTY, amount="3000", currency="TRY", provider_account=self.account,
		                            payment_link=link["link"], description="Deposit", customer={},
		                            return_url=sites.guest_url(sites.site_for(fx.PROPERTY), "pay/return",
		                                                       site_scoped=False),
		                            idempotency_key=f"p15-{link['link']}")
		out = public.mock_pay(transaction=started["transaction"], outcome="success", sig=started["fields"]["success_sig"])
		self.assertEqual(out["status"], "Succeeded")
		self.assertEqual(txn_state(started["transaction"]).reconciliation, "Action Required")
		why = frappe.get_all("TEX Audit Event", filters={"action": "payment.reconciliation_required",
		                                                 "reference_name": started["transaction"]}, pluck="new_value")
		self.assertEqual([json.loads(v)["why"] for v in why], ["CURRENCY_MISMATCH"])
		self.assertEqual(frappe.db.get_value("TEX Payment Link", link["link"], "status"), "Cancelled")
		self.assertEqual((paid(b), self.statuses(b)[0]), (D(0), "Pending Payment"))

	def test_a_link_asking_more_than_the_booking_owes_is_refused(self):
		"""E4: a link left open (being paid when its booking was settled) never takes more than the
		booking still owes; a balance link sent after the deposit stays open and is paid."""
		kept = self.book(method="Pay at Hotel", status="Confirmed")
		too_much = pay.create_link(property=fx.PROPERTY, amount=str(D(kept["balance"]) + 50), currency="EUR",
		                           description="Balance", booking=kept["booking"])
		with self.assertRaisesRegex(frappe.ValidationError, "more than its booking still owes"):
			public.pay_link(token=too_much["token"])
		balance = pay.create_link(property=fx.PROPERTY, amount=kept["balance"], currency="EUR", description="Balance",
		                          booking=kept["booking"])
		started = public.pay_link(token=balance["token"])
		public.mock_pay(transaction=started["transaction"], outcome="success", sig=started["fields"]["success_sig"])
		self.assertEqual(paid(kept), D(kept["balance"]))
		self.assertEqual(frappe.db.get_value("TEX Payment Link", too_much["link"], "status"), "Cancelled")  # paid in full

	def test_the_link_of_an_expired_booking_cannot_be_sent_again(self):
		"""E4: a booking that expired closes its open links; one left open (being paid at that moment) is
		never sent again: its booking cannot take the money."""
		b = self.book(method="Card")
		out = self.send_link(b)
		passes(b["booking"], 24 * 60 + 5)
		run_expiry_jobs()
		self.assertEqual(frappe.db.get_value("TEX Payment Link", out["link"], "status"), "Expired")
		self.assertTrue(frappe.db.exists("TEX Audit Event", {"action": "payment_link.closed",
		                                                     "reference_name": out["link"]}))
		with self.assertRaisesRegex(frappe.ValidationError, "Only open links"):
			pay.reissue_link(out["link"])
		frappe.db.set_value("TEX Payment Link", out["link"], {"status": "Active",
		                                                     "expires_at": add_to_date(now_datetime(), hours=1)})
		with self.assertRaisesRegex(frappe.ValidationError, "cannot take"):
			pay.reissue_link(out["link"])
		with self.assertRaisesRegex(frappe.ValidationError, "can no longer be paid"):
			public.pay_link(token=out["token"])

	def test_the_email_says_until_when(self):
		from kamra.tex.tests.integration.test_migrations_notify import ensure_test_outbox

		ensure_test_outbox()
		b = self.book(method="Card")
		out = self.send_link(b, guest_email=GUEST["email"], guest_name="Lena Kraus", send_email=True)
		self.assertTrue(out["emailed"])
		import email

		queue = frappe.get_all("Email Queue", filters={"reference_doctype": "TEX Payment Link",
		                                               "reference_name": out["link"]}, pluck="name")
		msg = email.message_from_string(frappe.get_doc("Email Queue", queue[0]).message)
		body = "".join(part.get_payload(decode=True).decode("utf-8", "replace") for part in msg.walk()
		               if part.get_content_type() == "text/html")
		self.assertIn(f"{held_until(b)[0]:%Y-%m-%d %H:%M}", body)


NEW6_EMAILS = ("anna.new6@example.com", "carl.new6@example.com", "dora.new6@example.com")


def _cleanup_new6():
	"""What the gateway race commits beyond ``_cleanup``/``_cleanup_payments``, run before them: the
	booking site's funnel events, the bookings' e-mails (queue, records, errors), the stays' deposits and
	versions, and the race's guests."""
	frappe.set_user("Administrator")  # nosemgrep: frappe-setuser -- test cleanup
	bookings = frappe.get_all("TEX Booking", filters={"property": fx.PROPERTY}, pluck="name")
	rooms = frappe.get_all("Reservation", filters={"property": fx.PROPERTY}, pluck="name")
	frappe.db.delete("TEX Funnel Event", {"site": SLUG})
	if bookings:
		frappe.db.delete("TEX Communication", {"booking": ("in", bookings)})
		queue = frappe.get_all("Email Queue", filters={"reference_doctype": "TEX Booking",
		                                               "reference_name": ("in", bookings)}, pluck="name")
		if queue:
			frappe.db.delete("Email Queue Recipient", {"parent": ("in", queue)})
			frappe.db.delete("Email Queue", {"name": ("in", queue)})
		frappe.db.delete("Error Log", {"method": ("in", [f"TEX booking e-mail {b}" for b in bookings])})
	if rooms:
		frappe.db.delete("Security Deposit", {"reservation": ("in", rooms)})
		frappe.db.delete("Version", {"ref_doctype": "Reservation", "docname": ("in", rooms)})
	frappe.db.delete("Guest", {"email": ("in", NEW6_EMAILS)})
	frappe.db.commit()  # nosemgrep: frappe-manual-commit -- test fixture cleanup across connections


class TestNoLockHeldThroughTheGateway(IntegrationTestCase):
	"""NEW-6 (ADR-066), under real concurrency: guest A books and pays by card, and the gateway takes
	its time making A's checkout. Meanwhile another connection writes an audit event, books other nights
	and starts another booking's payment: none of them may wait for A. Before, A held its booking's rows
	and the site-wide naming-series rows (AUD-, TEX-, RES-, REV-, G-, PTX-) through the gateway call,
	and each of them timed out. Fixtures committed, cleaned up."""

	@classmethod
	def tearDownClass(cls):
		_cleanup_new6()
		_cleanup_payments()
		_cleanup()
		frappe.db.delete("TEX Booking Site", SLUG)
		frappe.db.commit()  # nosemgrep: frappe-manual-commit -- test fixture cleanup across connections
		super().tearDownClass()

	def setUp(self):
		super().setUp()
		frappe.set_user("Administrator")  # nosemgrep: frappe-setuser -- test setup
		_cleanup_new6()
		_cleanup()
		_cleanup_payments()
		self.f = fx.base_setup()
		fx.create_contract(self.f, code="CONC")
		acc = fx.ensure("TEX Payment Provider Account", {"property": fx.PROPERTY, "provider": "Mock"},
		                {"label": "Sandbox gateway", "property": fx.PROPERTY, "provider": "Mock",
		                 "environment": "Sandbox", "enabled": 1, "currencies": "EUR"})
		fx.ensure("TEX Payment Method Rule", {"property": fx.PROPERTY, "method": "Card"},
		          {"property": fx.PROPERTY, "method": "Card", "provider_account": acc, "priority": 10})
		if not frappe.db.exists("TEX Booking Site", SLUG):
			frappe.get_doc({"doctype": "TEX Booking Site", "site_name": "TEX Test Resort", "site_slug": SLUG,
			                "enabled": 1, "property": fx.PROPERTY, "default_market": "DE", "default_currency": "EUR",
			                "currencies": "EUR", "self_service_enabled": 1}).insert(ignore_permissions=True)
		frappe.set_user("Guest")  # nosemgrep: frappe-setuser -- guest booking path
		res = public.search(site=SLUG, check_in=str(fx.d(8, 20)), check_out=str(fx.d(8, 22)), rooms=[{"adults": 2}],
		                    market="DE", session_id="new6-a")
		self.a_quote = public.quote(site=SLUG, offer_key=pick(res["properties"][0])["rooms"][0]["offer_key"],
		                            session_id="new6-a")["quote_id"]
		quote = lambda code, ci, co: quoting.create_quote(pick(quoting.search(  # noqa: E731
			properties=[fx.PROPERTY], check_in=ci, check_out=co, rooms=[{"adults": 2}], market="DE",
			channel="DIRECT_WEB", currency="EUR")["properties"][0], room_code=code)["rooms"][0]["offer_key"])["quote_id"]
		self.c_quote = quote("DLX", fx.d(8, 24), fx.d(8, 26))
		self.d = booking.create_booking(quote_ids=[quote("STD", fx.d(9, 1), fx.d(9, 3))], payment_method="Card",
		                                guest={"first_name": "Dora", "last_name": "Waiting",
		                                       "email": "dora.new6@example.com"})
		frappe.set_user("Administrator")  # nosemgrep: frappe-setuser -- test setup
		frappe.db.commit()  # nosemgrep: frappe-manual-commit -- the other connections need committed fixtures

	def test_other_writers_never_wait_for_a_gateway_call(self):
		from kamra.tex.payments.providers.simple import MockProvider
		from kamra.tex.security.audit import audit

		site, sites_path = frappe.local.site, frappe.local.sites_path
		in_gateway, release = threading.Event(), threading.Event()
		calls: list[str] = []
		results: dict = {}
		real = MockProvider.create_checkout

		def gateway(provider, intent):
			calls.append(intent.transaction)
			if len(calls) == 1:                         # A's checkout: the gateway takes its time
				in_gateway.set()
				release.wait(timeout=30)
			return real(provider, intent)

		def guest_a():
			frappe.init(site=site, sites_path=sites_path)
			frappe.connect()
			# a new thread copies the test mode: this request's commits run, as in production
			frappe.flags.in_test = False
			try:
				frappe.set_user("Guest")  # nosemgrep: frappe-setuser -- the guest books and pays
				results["a"] = public.book(site=SLUG, quote_ids=[self.a_quote], payment_method="Card",
				                           guest={"first_name": "Anna", "last_name": "Gateway",
				                                  "email": "anna.new6@example.com"},
				                           session_id="new6-a", idempotency_key="idem-new6-a")
				frappe.db.commit()  # nosemgrep: frappe-manual-commit -- the request's own end
			except Exception as e:
				frappe.db.rollback()
				results["a"] = f"{type(e).__name__}: {e}"
			finally:
				in_gateway.set()
				frappe.destroy()

		def others():
			frappe.init(site=site, sites_path=sites_path)
			frappe.connect()
			try:
				frappe.db.sql("SET SESSION innodb_lock_wait_timeout = 2")
				for step, user, fn in (
					("audit", "Administrator", lambda: audit("tex.test.new6", property=fx.PROPERTY, new={"n": 1})),
					("book", "Guest", lambda: booking.create_booking(
						quote_ids=[self.c_quote], payment_method="Pay at Hotel",
						guest={"first_name": "Carl", "last_name": "Other", "email": "carl.new6@example.com"})),
					("pay", "Guest", lambda: public.pay_booking(token=self.d["manage_token"], payment_method="Card")),
				):
					frappe.set_user(user)  # nosemgrep: frappe-setuser -- staff, then guests, on their own requests
					try:
						fn()
						results[step] = "ok"
					except Exception as e:
						results[step] = type(e).__name__
					finally:
						frappe.db.rollback()
			finally:
				frappe.destroy()

		frappe.db.rollback()                            # this connection holds nothing while the others run
		a, b = threading.Thread(target=guest_a), threading.Thread(target=others)
		with mock.patch.object(MockProvider, "create_checkout", gateway):
			try:
				a.start()
				self.assertTrue(in_gateway.wait(timeout=60))
				b.start()
			finally:
				# whatever failed: the other side ends, then A is let go and ends before anything is cleaned up
				if b.ident is not None:
					b.join(timeout=60)
				release.set()
				if a.ident is not None:
					a.join(timeout=60)
		self.assertEqual({k: results.get(k) for k in ("audit", "book", "pay")},
		                 {"audit": "ok", "book": "ok", "pay": "ok"})
		out = results.get("a")
		self.assertIsInstance(out, dict, out if isinstance(out, str) else None)       # never its manage token
		frappe.db.rollback()                            # read what A committed
		txn = out["payment"]["transaction"]
		self.assertTrue(out["payment"]["url"])
		row = frappe.db.get_value("TEX Payment Transaction", txn, ["status", "provider_ref", "checkout_started_at"],
		                          as_dict=True)
		self.assertEqual((row.status, row.provider_ref, row.checkout_started_at), ("Pending", f"MOCK-{txn}", None))

	def test_two_first_starts_of_one_charge_start_it_once(self):
		"""The same new charge started twice at once (a double click, two tabs of one link): the unique key
		lets one start insert it; the other, whose snapshot did not see it, undoes its own steps and is told
		a payment is being started — one charge, one checkout."""
		b = self.d["booking"]
		acc = frappe.db.get_value("TEX Payment Provider Account", {"property": fx.PROPERTY, "provider": "Mock"})
		key = pay.ns_key(fx.PROPERTY, f"book:{b}:{self.d['due_now']}:1", "charge")    # pay_booking's first key
		site, sites_path = frappe.local.site, frappe.local.sites_path
		first: dict = {}

		def other_tab():
			frappe.init(site=site, sites_path=sites_path)
			frappe.connect()
			try:
				frappe.set_user("Administrator")  # nosemgrep: frappe-setuser -- the first start's insert
				first["charge"] = pay._new_txn(property=fx.PROPERTY, txn_type="Charge", method="Card",
				                               amount=D(self.d["due_now"]), currency="EUR", provider_account=acc,
				                               provider="Mock", idempotency_key=key, booking=b).name
				frappe.db.commit()  # nosemgrep: frappe-manual-commit -- its step (a)
			except Exception as e:
				frappe.db.rollback()
				first["error"] = f"{type(e).__name__}: {e}"
			finally:
				frappe.destroy()

		frappe.db.rollback()
		# this request's snapshot is taken before the other start's charge exists: it does not see it
		frappe.db.sql("SELECT name FROM `tabTEX Payment Transaction` LIMIT 1")
		t = threading.Thread(target=other_tab)
		t.start()
		t.join(timeout=60)
		self.assertIn("charge", first, first)
		frappe.set_user("Guest")  # nosemgrep: frappe-setuser -- the guest's second tab
		with self.assertRaisesRegex(pay.PaymentBusy, "A payment is being started"):
			public.pay_booking(token=self.d["manage_token"], payment_method="Card")
		frappe.set_user("Administrator")  # nosemgrep: frappe-setuser -- read what is on record
		frappe.db.rollback()
		self.assertEqual(frappe.get_all("TEX Payment Transaction", filters={"booking": b}, pluck="name"),
		                 [first["charge"]])

