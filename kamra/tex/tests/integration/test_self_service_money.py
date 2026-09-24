"""Guest changes settle their money (G-45, ADR-044).

The fixture booking: FLEX, 3 nights (6/10–6/13), 842.50 with a 30 % deposit (252.75). One more
LOW night makes it 1110.00 (deposit 333.00), one night less 575.00.

A higher price is paid before the change applies (the gateway's confirmation applies it); pay
at hotel and bookings already covered apply at once and say what is due later. A lower price
follows the hotel's policy: staff approval, an automatic refund of the true overpayment from
the charges holding it, or a credit kept on the booking."""

from unittest import mock

import frappe
from frappe.utils import add_to_date, get_datetime, now_datetime

from kamra.tex.api import crs as crs_api
from kamra.tex.api import payments as pay_api
from kamra.tex.api import policies as policy_api
from kamra.tex.api import public
from kamra.tex.money import D
from kamra.tex.payments import service as pay
from kamra.tex.security import scope
from kamra.tex.services import modification
from kamra.tex.tests.integration import fixtures as fx
from kamra.tex.tests.integration.test_commercial_flows import (
	GUEST,
	SLUG,
	guest_books,
	setup_site_and_payments,
	two_rooms_quoted_together,
)
from kamra.tex.tests.integration.test_critical_journey import TexTestCase
from kamra.tex.tests.integration.test_security_regressions import OTHER, other_hotel_with_mock

DT = "TEX Guest Change Request"
TXN = "TEX Payment Transaction"


def paid(start: dict) -> dict:
	"""The guest completes a checkout on the sandbox gateway."""
	frappe.set_user("Guest")  # nosemgrep: frappe-setuser -- the gateway's page, as the guest
	return public.mock_pay(transaction=start["transaction"], outcome="success", sig=start["fields"]["success_sig"])


def declined(start: dict) -> dict:
	frappe.set_user("Guest")  # nosemgrep: frappe-setuser -- the gateway's page, as the guest
	return public.mock_pay(transaction=start["transaction"], outcome="fail", sig=start["fields"]["fail_sig"])


def money(booking: str) -> tuple[D, D, D]:
	b = frappe.db.get_value("TEX Booking", booking, ["total_amount", "paid_amount", "balance_amount"], as_dict=True)
	return D(b.total_amount), D(b.paid_amount), D(b.balance_amount)


def stay(reservation: str) -> tuple[str, D]:
	r = frappe.db.get_value("Reservation", reservation, ["check_out_date", "tex_total_amount"], as_dict=True)
	return str(r.check_out_date), D(r.tex_total_amount)


def refunds(booking: str) -> list[tuple[str, D, str]]:
	rows = frappe.get_all(TXN, filters={"txn_type": "Refund", "parent_transaction": ("in", charges(booking) or [""])},
	                      fields=["parent_transaction", "amount", "status"], order_by="creation asc")
	return [(r.parent_transaction, D(r.amount), r.status) for r in rows]


def charges(booking: str) -> list[str]:
	return frappe.get_all(TXN, filters={"booking": booking, "txn_type": "Charge"}, pluck="name",
	                      order_by="creation asc")


def lower_price_policy(value: str) -> None:
	frappe.db.set_value("Property", fx.PROPERTY, "tex_lower_price_refund", value)


class GuestMoneyCase(TexTestCase):
	def setUp(self):
		super().setUp()
		self.p = setup_site_and_payments(self.f)

	def deposit_paid(self, session: str) -> dict:
		b = guest_books(session=session)
		paid(b["payment"])
		self.assertEqual(money(b["booking"])[1], D("252.75"))
		return b

	def fully_paid(self, session: str) -> dict:
		b = self.deposit_paid(session)
		rest = public.pay_booking(token=b["manage_token"])
		paid(rest)
		self.assertEqual(money(b["booking"])[1], D("842.50"))
		return b

	def propose(self, b: dict, check_out: tuple[int, int], **more) -> dict:
		frappe.set_user("Guest")  # nosemgrep: frappe-setuser -- the guest on the manage page
		return public.manage_propose(token=b["manage_token"], reservation=b["rooms"][0]["reservation"],
		                             changes={"check_out": str(fx.d(*check_out)), **more})

	def accept(self, b: dict, proposal: dict) -> dict:
		frappe.set_user("Guest")  # nosemgrep: frappe-setuser -- the guest accepts
		return public.manage_apply(token=b["manage_token"], proposal_token=proposal["proposal_token"])


class TestHigherPrice(GuestMoneyCase):
	def test_a_higher_price_is_paid_before_the_change_applies(self):
		b = self.deposit_paid("gcm-up")
		res = b["rooms"][0]["reservation"]
		up = self.propose(b, (6, 14))
		self.assertEqual(up["difference"], "267.50")
		self.assertEqual((up["settlement"]["kind"], up["settlement"]["amount"]), ("pay_now", "80.25"))
		out = self.accept(b, up)
		self.assertEqual((out["status"], out["amount"], out["currency"]), ("payment_required", "80.25", "EUR"))
		self.assertEqual(out["payment"]["kind"], "redirect")
		# nothing changed yet: the reservation waits for the payment
		self.assertEqual(stay(res), (str(fx.d(6, 13)), D("842.50")))
		self.assertEqual(frappe.db.get_value(DT, out["request"], "status"), "Awaiting Payment")
		view = public.booking_status(token=b["manage_token"])["rooms"][0]["pending_change"]
		self.assertEqual((view["status"], view["amount"], view["changes"]), ("awaiting_payment", "80.25",
		                                                                     {"check_out": str(fx.d(6, 14))}))

		paid(out["payment"])                              # the gateway's confirmation applies it
		self.assertEqual(stay(res), (str(fx.d(6, 14)), D("1110.00")))
		self.assertEqual(money(b["booking"]), (D("1110.00"), D("333.00"), D("777.00")))
		self.assertEqual(frappe.db.count("TEX Reservation Revision", {"reservation": res,
		                                                              "change_type": ("!=", "Original")}), 1)
		req = frappe.get_doc(DT, out["request"])
		self.assertEqual((req.status, req.settlement, D(req.settlement_amount), req.payment_transaction),
		                 ("Applied", "Online payment", D("80.25"), out["payment"]["transaction"]))
		self.assertEqual(D(frappe.db.get_value("TEX Booking", b["booking"], "amount_due_now")), D("333.00"))
		self.assertEqual(frappe.db.get_value("Reservation", res, "tex_guest_change_pending"), 1)
		status = public.booking_status(token=b["manage_token"])
		self.assertEqual(status["rooms"][0]["last_change"], {"request": out["request"], "status": "applied",
		                                                     "settlement": "pay_now", "amount": "80.25",
		                                                     "paid": "80.25", "refunded": "0.00",
		                                                     "hotel_refund": "0.00", "money_back": None,
		                                                     "currency": "EUR"})
		self.assertTrue(status["can_pay_online"])
		again = self.accept(b, up)                        # the manage page asks again: the same answer
		self.assertEqual((again["status"], again["replay"], again["settlement"]["kind"]), ("applied", True,
		                                                                                    "pay_now"))
		self.assertIsNone(public.booking_status(token=b["manage_token"])["rooms"][0]["pending_change"].get("request"))

	def test_a_failed_change_payment_changes_nothing(self):
		b = self.deposit_paid("gcm-fail")
		res = b["rooms"][0]["reservation"]
		up = self.propose(b, (6, 14))
		first = self.accept(b, up)
		self.assertEqual(first["status"], "payment_required")
		self.assertEqual(declined(first["payment"])["status"], "Failed")
		self.assertEqual(stay(res), (str(fx.d(6, 13)), D("842.50")))
		self.assertEqual(money(b["booking"])[1], D("252.75"))
		self.assertEqual(frappe.db.get_value(DT, first["request"], "status"), "Awaiting Payment")
		retry = self.accept(b, up)                        # "try again": a new charge, attempt 2
		self.assertEqual((retry["status"], retry["request"]), ("payment_required", first["request"]))
		self.assertNotEqual(retry["payment"]["transaction"], first["payment"]["transaction"])
		self.assertEqual(frappe.db.get_value(DT, first["request"], "attempt"), 2)
		paid(retry["payment"])
		self.assertEqual(stay(res), (str(fx.d(6, 14)), D("1110.00")))
		self.assertEqual(money(b["booking"])[1], D("333.00"))

	def test_a_paid_change_that_can_no_longer_apply_is_refunded(self):
		b = self.deposit_paid("gcm-stale")
		res = b["rooms"][0]["reservation"]
		out = self.accept(b, self.propose(b, (6, 14)))
		self.assertEqual(out["status"], "payment_required")
		frappe.set_user("Administrator")  # nosemgrep: frappe-setuser -- the guest calls; an agent shortens the stay
		staff = modification.propose(res, {"check_out": str(fx.d(6, 12))})
		modification.apply(staff["proposal_token"], reason="guest phoned")
		# the manage page no longer offers to pay for a change that cannot apply
		self.assertIsNone(public.booking_status(token=b["manage_token"])["rooms"][0]["pending_change"])
		paid(out["payment"])                              # the guest pays for the old proposal meanwhile
		req = frappe.get_doc(DT, out["request"])
		self.assertEqual(req.status, "Failed")
		self.assertIn("changed", req.error)
		self.assertEqual(refunds(b["booking"]), [(out["payment"]["transaction"], D("80.25"), "Succeeded")])
		self.assertEqual(stay(res)[0], str(fx.d(6, 12)))                   # the agent's change stands
		self.assertEqual(money(b["booking"])[1], D("252.75"))
		self.assertEqual((D(req.refunded_amount), req.settle_pending), (D("80.25"), 0))
		# back from the gateway, the guest is told the change was not made and the payment refunded
		last = public.booking_status(token=b["manage_token"])["rooms"][0]["last_change"]
		self.assertEqual((last["status"], last["amount"], last["refunded"]), ("failed", "80.25", "80.25"))

	def test_a_waiting_change_is_paid_again_from_the_manage_page(self):
		b = self.deposit_paid("gcm-again")
		res = b["rooms"][0]["reservation"]
		out = self.accept(b, self.propose(b, (6, 14)))
		declined(out["payment"])                          # the guest comes back from a declined card
		view = public.booking_status(token=b["manage_token"])["rooms"][0]["pending_change"]
		self.assertEqual((view["request"], view["status"], view["kind"], view["amount"]),
		                 (out["request"], "awaiting_payment", "pay_now", "80.25"))
		again = public.manage_change_pay(token=b["manage_token"], request=view["request"])
		self.assertEqual((again["status"], again["request"], again["amount"]), ("payment_required", out["request"],
		                                                                        "80.25"))
		self.assertNotEqual(again["payment"]["transaction"], out["payment"]["transaction"])
		other = self.deposit_paid("gcm-again-other")
		with self.assertRaises(frappe.PermissionError):          # another booking's link cannot pay it
			public.manage_change_pay(token=other["manage_token"], request=view["request"])
		paid(again["payment"])
		self.assertEqual(stay(res), (str(fx.d(6, 14)), D("1110.00")))
		self.assertEqual(money(b["booking"])[1], D("333.00"))
		done = public.manage_change_pay(token=b["manage_token"], request=view["request"])
		self.assertEqual((done["status"], done["replay"]), ("applied", True))

	def test_a_replayed_callback_applies_once(self):
		b = self.deposit_paid("gcm-replay")
		res = b["rooms"][0]["reservation"]
		out = self.accept(b, self.propose(b, (6, 14)))
		self.assertEqual(out["status"], "payment_required")
		paid(out["payment"])
		self.assertTrue(paid(out["payment"]).get("replay"))
		from kamra.tex.services import guest_changes

		guest_changes.on_charge_succeeded(frappe.get_doc(TXN, out["payment"]["transaction"]))
		self.assertEqual(frappe.db.count("TEX Reservation Revision", {"reservation": res,
		                                                              "change_type": ("!=", "Original")}), 1)
		self.assertEqual(money(b["booking"]), (D("1110.00"), D("333.00"), D("777.00")))
		self.assertEqual(refunds(b["booking"]), [])

	def test_pay_at_hotel_increase_is_announced(self):
		b = guest_books(session="gcm-hotel", method="Pay at Hotel")
		up = self.propose(b, (6, 14))
		self.assertEqual((up["settlement"]["kind"], up["settlement"]["amount"]), ("pay_at_hotel", "267.50"))
		out = self.accept(b, up)
		self.assertEqual((out["status"], out["settlement"]["kind"], out["settlement"]["amount"], out["balance"]),
		                 ("applied", "pay_at_hotel", "267.50", "1110.00"))
		self.assertEqual(charges(b["booking"]), [])
		self.assertEqual(frappe.db.get_value(DT, out["request"], "settlement"), "Pay at hotel")

	def test_without_a_card_method_the_hotel_collects_it(self):
		b = self.deposit_paid("gcm-nocard")
		frappe.set_user("Administrator")  # nosemgrep: frappe-setuser -- the hotel switches card payments off
		frappe.db.set_value("TEX Payment Method Rule", {"property": fx.PROPERTY, "method": "Card"}, "disabled", 1)
		up = self.propose(b, (6, 14))
		self.assertEqual((up["settlement"]["kind"], up["settlement"]["amount"]), ("staff", "80.25"))
		self.assertFalse(public.booking_status(token=b["manage_token"])["can_pay_online"])
		out = self.accept(b, up)
		self.assertEqual((out["status"], out["settlement"]["kind"]), ("requested", "staff"))
		self.assertEqual(stay(b["rooms"][0]["reservation"])[0], str(fx.d(6, 13)))
		frappe.set_user("Administrator")  # nosemgrep: frappe-setuser -- reservations approve it
		done = crs_api.resolve_guest_change(request=out["request"], action="approve", reason="collect at check-in")
		self.assertEqual((done["status"], done["settlement"]), ("Approved", "Balance"))
		self.assertEqual(stay(b["rooms"][0]["reservation"]), (str(fx.d(6, 14)), D("1110.00")))
		self.assertEqual(money(b["booking"]), (D("1110.00"), D("252.75"), D("857.25")))


class TestLowerPrice(GuestMoneyCase):
	def test_refund_automatically_refunds_the_overpayment(self):
		lower_price_policy("Refund automatically")
		b = self.fully_paid("gcm-refund")
		deposit, balance = charges(b["booking"])
		down = self.propose(b, (6, 12))
		self.assertEqual((down["settlement"]["kind"], down["settlement"]["amount"]), ("refund", "267.50"))
		out = self.accept(b, down)
		self.assertEqual((out["status"], out["settlement"]["kind"], out["settlement"]["amount"]),
		                 ("applied", "refund", "267.50"))
		self.assertEqual(refunds(b["booking"]), [(balance, D("267.50"), "Succeeded")])   # the newest charge
		self.assertEqual(money(b["booking"]), (D("575.00"), D("575.00"), D("0.00")))
		self.assertEqual((out["balance"], out["credit"]), ("0.00", "0.00"))
		req = frappe.get_doc(DT, out["request"])
		self.assertEqual((req.settlement, D(req.refunded_amount), req.settle_pending), ("Refund", D("267.50"), 0))
		from kamra.tex.services import guest_changes

		guest_changes.settle(req.name)                    # the job running again refunds nothing more
		self.assertEqual(len(refunds(b["booking"])), 1)
		self.assertNotEqual(deposit, balance)

	def test_a_refund_job_that_did_not_run_is_retried(self):
		lower_price_policy("Refund automatically")
		b = self.fully_paid("gcm-retry")
		from kamra.tex.services import guest_changes

		with mock.patch.object(guest_changes, "queue_settle"):            # the worker never ran the job
			out = self.accept(b, self.propose(b, (6, 12)))
		# held until refunded, and never offered to the guest as credit meanwhile (H3)
		self.assertEqual((out["status"], out["credit"], out["refund_due"]), ("applied", "0.00", "267.50"))
		self.assertEqual(frappe.db.get_value(DT, out["request"], "settle_pending"), 1)
		self.assertEqual(refunds(b["booking"]), [])
		later = add_to_date(now_datetime(), minutes=guest_changes.SETTLE_RETRY_MINUTES + 1)
		with mock.patch("kamra.tex.services.guest_changes.now_datetime", return_value=later):
			self.assertEqual(guest_changes.expire_awaiting(), {"expired": 0, "settled": 1, "applied": 0,
			                                                   "returned": 0})
		self.assertEqual([(r[1], r[2]) for r in refunds(b["booking"])], [(D("267.50"), "Succeeded")])
		self.assertEqual(money(b["booking"]), (D("575.00"), D("575.00"), D("0.00")))
		self.assertEqual(frappe.db.get_value(DT, out["request"], "settle_pending"), 0)

	def test_refund_automatically_with_only_a_deposit_lowers_the_balance(self):
		lower_price_policy("Refund automatically")
		b = self.deposit_paid("gcm-deposit")
		down = self.propose(b, (6, 12))
		self.assertEqual((down["settlement"]["kind"], down["settlement"]["amount"]), ("balance", "267.50"))
		out = self.accept(b, down)
		self.assertEqual((out["status"], out["balance"]), ("applied", "322.25"))
		self.assertEqual(refunds(b["booking"]), [])
		self.assertEqual(money(b["booking"]), (D("575.00"), D("252.75"), D("322.25")))

	def test_keep_as_credit_records_a_credit(self):
		lower_price_policy("Keep as credit")
		b = self.fully_paid("gcm-credit")
		down = self.propose(b, (6, 12))
		self.assertEqual((down["settlement"]["kind"], down["settlement"]["amount"]), ("credit", "267.50"))
		out = self.accept(b, down)
		self.assertEqual((out["status"], out["credit"], out["settlement"]["kind"]), ("applied", "267.50", "credit"))
		self.assertEqual(public.booking_status(token=b["manage_token"])["credit"], "267.50")
		req = frappe.get_doc(DT, out["request"])
		self.assertEqual((req.settlement, D(req.settlement_amount)), ("Credit on booking", D("267.50")))
		self.assertTrue(frappe.db.get_value("TEX Booking", b["booking"], "guest_change_pending"))
		self.assertTrue(frappe.db.exists("TEX Audit Event", {"action": "guest_change.credit",
		                                                     "reference_name": b["booking"]}))
		self.assertEqual(refunds(b["booking"]), [])
		# the credit pays for a later change: back to three nights, nothing to pay
		up = self.propose(b, (6, 13))
		self.assertEqual((up["settlement"]["kind"], up["settlement"]["collect"]), ("balance", "0.00"))
		back = self.accept(b, up)
		self.assertEqual((back["status"], back["credit"], back["balance"]), ("applied", "0.00", "0.00"))
		self.assertEqual(charges(b["booking"]).__len__(), 2)                 # no new charge

	def test_refund_the_provider_cannot_make_goes_to_staff(self):
		lower_price_policy("Refund automatically")
		b = guest_books(session="gcm-manual")
		frappe.set_user("Administrator")  # nosemgrep: frappe-setuser -- the guest paid at the desk
		pay.record_manual(booking=b["booking"], amount="842.50", method="Cash", reference="desk receipt 1",
		                  idempotency_key="gcm-manual-1")
		down = self.propose(b, (6, 12))
		# a cash payment is not refunded to a card: the guest is told the hotel refunds it (L1)
		self.assertEqual((down["settlement"]["kind"], down["settlement"]["amount"], down["settlement"]["refund"],
		                  down["settlement"]["hotel_refund"]), ("refund", "267.50", "0.00", "267.50"))
		out = self.accept(b, down)
		self.assertEqual((out["status"], out["settlement"]["kind"], out["settlement"]["hotel_refund"], out["credit"]),
		                 ("applied", "refund", "267.50", "0.00"))
		req = frappe.get_doc(DT, out["request"])
		self.assertEqual((req.settlement, D(req.refunded_amount), req.settle_pending), ("Refund", D("0"), 0))
		self.assertEqual((req.staff_open, D(req.staff_amount), req.staff_reason), (1, D("267.50"), "Refund by staff"))
		self.assertEqual(refunds(b["booking"]), [])
		self.assertTrue(frappe.db.exists("TEX Audit Event", {"action": "guest_change.refund_by_staff",
		                                                     "reference_name": req.name}))
		self.assertEqual(frappe.db.get_value("Reservation", b["rooms"][0]["reservation"],
		                                     "tex_guest_change_pending"), 1)
		frappe.set_user("Administrator")  # nosemgrep: frappe-setuser -- finance refunds it at the desk
		listed = crs_api.guest_change_requests(property=fx.PROPERTY, needs_staff=1)
		self.assertEqual([r["name"] for r in listed], [req.name])
		closed = crs_api.resolve_guest_change(request=req.name, action="close", reason="refunded in cash",
		                                      staff_money="Refunded outside TEX")
		self.assertEqual((closed["resolved_by"], closed["needs_staff"], closed["staff_open"]),
		                 ("Administrator", False, False))
		self.assertEqual(crs_api.guest_change_requests(property=fx.PROPERTY, needs_staff=1), [])


class TestGuards(GuestMoneyCase):
	def test_no_guest_change_while_payment_is_pending(self):
		b = guest_books(session="gcm-pending")                  # the deposit is not paid yet
		self.assertEqual(frappe.db.get_value("TEX Booking", b["booking"], "status"), "Pending Payment")
		with self.assertRaisesRegex(frappe.ValidationError, "complete the payment"):
			self.propose(b, (6, 14))
		frappe.set_user("Administrator")  # nosemgrep: frappe-setuser -- a proposal made elsewhere
		staff = modification.propose(b["rooms"][0]["reservation"], {"check_out": str(fx.d(6, 14))})
		with self.assertRaisesRegex(frappe.ValidationError, "complete the payment"):
			self.accept(b, staff)
		self.assertEqual(stay(b["rooms"][0]["reservation"])[0], str(fx.d(6, 13)))
		self.assertEqual(public.booking_status(token=b["manage_token"])["changes_blocked"], "PAYMENT_PENDING")

	def test_the_same_proposal_twice_opens_one_request(self):
		b = self.deposit_paid("gcm-twice")
		up = self.propose(b, (6, 14))
		first, second = self.accept(b, up), self.accept(b, up)
		self.assertEqual((second["status"], second["request"]), ("payment_required", first["request"]))
		self.assertEqual(second["payment"]["transaction"], first["payment"]["transaction"])   # one charge
		self.assertEqual(frappe.db.count(DT, {"booking": b["booking"]}), 1)
		at_hotel = guest_books(session="gcm-twice-hotel", method="Pay at Hotel")
		up = self.propose(at_hotel, (6, 14))
		one, two = self.accept(at_hotel, up), self.accept(at_hotel, up)
		self.assertEqual((one["status"], two["status"], two["replay"], two["revision"]),
		                 ("applied", "applied", True, one["revision"]))
		self.assertEqual(frappe.db.count("TEX Reservation Revision", {"reservation": at_hotel["rooms"][0]["reservation"],
		                                                              "change_type": ("!=", "Original")}), 1)

	def test_a_late_payment_on_a_superseded_request_is_refunded(self):
		b = self.deposit_paid("gcm-late")
		res = b["rooms"][0]["reservation"]
		first = self.accept(b, self.propose(b, (6, 14)))
		second = self.accept(b, self.propose(b, (6, 15)))          # the guest changes their mind
		self.assertEqual((first["status"], second["status"]), ("payment_required", "payment_required"))
		self.assertEqual(frappe.db.get_value(DT, first["request"], "status"), "Superseded")
		paid(first["payment"])                                    # the older tab is paid after all
		self.assertEqual(refunds(b["booking"]), [(first["payment"]["transaction"], D("80.25"), "Succeeded")])
		self.assertEqual(stay(res)[0], str(fx.d(6, 13)))
		paid(second["payment"])
		self.assertEqual(stay(res)[0], str(fx.d(6, 15)))
		self.assertEqual(money(b["booking"])[1], D("413.25"))                # 30 % of 1377.50

	def test_an_unpaid_change_expires_and_its_late_payment_is_refunded(self):
		b = self.deposit_paid("gcm-expire")
		up = self.propose(b, (6, 14))
		out = self.accept(b, up)
		self.assertEqual(out["status"], "payment_required")
		from kamra.tex.services import guest_changes

		later = add_to_date(now_datetime(), hours=2)             # past the proposal's payment deadline
		with mock.patch("kamra.tex.services.guest_changes.now_datetime", return_value=later):
			self.assertEqual(guest_changes.expire_awaiting()["expired"], 1)
		self.assertEqual(frappe.db.get_value(DT, out["request"], "status"), "Expired")
		self.assertIsNone(public.booking_status(token=b["manage_token"])["rooms"][0]["pending_change"])
		with self.assertRaisesRegex(frappe.ValidationError, "not made"):
			self.accept(b, up)
		paid(out["payment"])                                      # the old checkout is paid after all
		self.assertEqual(refunds(b["booking"]), [(out["payment"]["transaction"], D("80.25"), "Succeeded")])
		self.assertEqual(stay(b["rooms"][0]["reservation"])[0], str(fx.d(6, 13)))
		self.assertEqual(money(b["booking"])[1], D("252.75"))


	def test_staff_acknowledging_or_cancelling_a_waiting_change(self):
		b = self.deposit_paid("gcm-ack")
		res = b["rooms"][0]["reservation"]
		out = self.accept(b, self.propose(b, (6, 14)))
		frappe.set_user("Administrator")  # nosemgrep: frappe-setuser -- reservations see the flag
		crs_api.acknowledge_guest_change(reservation=res, note="seen")      # the flag only: it still applies
		paid(out["payment"])
		self.assertEqual(stay(res), (str(fx.d(6, 14)), D("1110.00")))
		later = self.accept(b, self.propose(b, (6, 15)))
		self.assertEqual((later["status"], later["amount"]), ("payment_required", "80.25"))
		frappe.set_user("Administrator")  # nosemgrep: frappe-setuser -- the guest phones to cancel
		crs_api.cancel(reservation=res, reason="guest phoned to cancel")
		self.assertEqual(frappe.db.get_value(DT, later["request"], "status"), "Superseded")
		paid(later["payment"])                                    # the open checkout is paid after all
		self.assertEqual(refunds(b["booking"])[-1], (later["payment"]["transaction"], D("80.25"), "Succeeded"))
		self.assertEqual(frappe.db.get_value("Reservation", res, "status"), "Cancelled")


class TestStaffDecide(GuestMoneyCase):
	def setUp(self):
		super().setUp()
		self.agent = fx.ensure_user("gcm-agent@example.com", ["Call Center Agent"])
		fx.ensure("TEX Access Grant", {"user": self.agent, "property": fx.PROPERTY},
		          {"user": self.agent, "scope_level": "Hotel", "property": fx.PROPERTY,
		           "permission_profile": "Reservations Agent"})
		other_hotel_with_mock()
		self.outsider = fx.ensure_user("gcm-outsider@example.com", ["Hotel Admin"])
		fx.ensure("TEX Access Grant", {"user": self.outsider, "property": OTHER},
		          {"user": self.outsider, "scope_level": "Hotel", "property": OTHER,
		           "permission_profile": "Hotel Admin"})
		scope.clear_cache()

	def test_the_hotel_approves_a_lower_price_and_settles_it(self):
		b = self.fully_paid("gcm-staff")
		res = b["rooms"][0]["reservation"]
		down = self.propose(b, (6, 12))
		self.assertEqual((down["settlement"]["kind"], down["settlement"]["amount"]), ("staff_approval", "267.50"))
		out = self.accept(b, down)
		self.assertEqual((out["status"], out["settlement"]["kind"]), ("requested", "staff_approval"))
		self.assertEqual(stay(res), (str(fx.d(6, 13)), D("842.50")))
		self.assertEqual(public.booking_status(token=b["manage_token"])["rooms"][0]["pending_change"]["status"],
		                 "requested")
		frappe.set_user(self.outsider)  # nosemgrep: frappe-setuser -- the admin of another hotel
		self.assertEqual(crs_api.guest_change_requests(), [])
		with self.assertRaises(frappe.PermissionError):
			crs_api.resolve_guest_change(request=out["request"], action="reject", reason="no")
		frappe.set_user(self.agent)  # nosemgrep: frappe-setuser -- a reservations agent of the hotel
		listed = crs_api.guest_change_requests(property=fx.PROPERTY, needs_staff=1)
		self.assertEqual([(r["name"], r["status"], r["difference"], r["overpaid_after"]) for r in listed],
		                 [(out["request"], "Requested", "-267.50", "267.50")])
		with self.assertRaises(frappe.PermissionError):           # a refund is finance's call
			crs_api.resolve_guest_change(request=out["request"], action="approve", reason="ok", settlement="Refund")
		with self.assertRaisesRegex(frappe.ValidationError, "refund it or keep it as credit"):
			crs_api.resolve_guest_change(request=out["request"], action="approve", reason="ok")
		frappe.set_user("Administrator")  # nosemgrep: frappe-setuser -- finance approves with a refund
		done = crs_api.resolve_guest_change(request=out["request"], action="approve", reason="ok",
		                                    settlement="Refund")
		self.assertEqual((done["status"], done["settlement"], done["refunded_amount"]), ("Approved", "Refund",
		                                                                                 "267.50"))
		self.assertEqual(stay(res), (str(fx.d(6, 12)), D("575.00")))
		self.assertEqual(money(b["booking"]), (D("575.00"), D("575.00"), D("0.00")))
		self.assertEqual(frappe.db.get_value("Reservation", res, "tex_guest_change_pending"), 0)
		self.assertTrue(frappe.db.exists("TEX Audit Event", {"action": "guest_change.resolve",
		                                                     "reference_name": out["request"]}))

	def test_the_hotel_rejects_a_request(self):
		b = self.deposit_paid("gcm-reject")
		out = self.accept(b, self.propose(b, (6, 12)))
		self.assertEqual(out["status"], "requested")
		frappe.set_user(self.agent)  # nosemgrep: frappe-setuser -- a reservations agent of the hotel
		listed = crs_api.guest_change_requests(reservation=b["rooms"][0]["reservation"])
		self.assertEqual([(r["status"], r["overpaid_after"]) for r in listed], [("Requested", "0.00")])
		with self.assertRaisesRegex(frappe.ValidationError, "reason"):
			crs_api.resolve_guest_change(request=out["request"], action="reject", reason=" ")
		done = crs_api.resolve_guest_change(request=out["request"], action="reject", reason="minimum stay 3 nights")
		self.assertEqual(done["status"], "Rejected")
		self.assertEqual(stay(b["rooms"][0]["reservation"]), (str(fx.d(6, 13)), D("842.50")))
		with self.assertRaisesRegex(frappe.ValidationError, "waiting for the hotel"):
			crs_api.resolve_guest_change(request=out["request"], action="approve", reason="changed my mind")


# ─── review follow-up (G-45 adversarial review) ─────────────────────────


def nrf_books(session: str) -> dict:
	"""The fixture stay on the Non-refundable rate (paid in full by card)."""
	frappe.set_user("Guest")  # nosemgrep: frappe-setuser -- anonymous booking-engine visitor
	found = public.search(site=SLUG, check_in=str(fx.d(6, 10)), check_out=str(fx.d(6, 13)),
	                      rooms=[{"adults": 2, "children": [8]}], market="DE", session_id=session)
	rt = frappe.db.get_value("Room Type", {"property": fx.PROPERTY, "room_type_code": "STD"})
	rp = frappe.db.get_value("Rate Plan", {"property": fx.PROPERTY, "code": "NRF"})
	offer = next(o for o in found["properties"][0]["offers"]
	             if o["room_type"] == rt and o["board"] == "AI" and o["rate_plan"] == rp)
	q = public.quote(site=SLUG, offer_key=offer["rooms"][0]["offer_key"], session_id=session)
	return public.book(site=SLUG, quote_ids=[q["quote_id"]], guest=GUEST, payment_method="Card",
	                   session_id=session, idempotency_key=f"idem-{session}")


def gateway_calls(outcomes: dict | None = None, *, timeout: bool = False):
	"""A sandbox gateway double for refunds: records each refund it is asked for; answers
	Failed for the charges named in ``outcomes`` ({charge: "Failed"}), or refunds and then times
	out (the answer never arrives) when ``timeout`` or for the charges named "Timeout"."""
	import requests

	from kamra.tex.payments.providers.base import Outcome
	from kamra.tex.payments.providers.simple import MockProvider

	calls: list[tuple[str, D]] = []

	def refund(self, provider_ref, amount, currency, **_kw):
		calls.append((provider_ref, D(amount)))
		said = (outcomes or {}).get(provider_ref.removeprefix("MOCK-"))
		if timeout or said == "Timeout":
			raise requests.exceptions.ReadTimeout("the gateway did not answer in time")
		if said == "Failed":
			return Outcome(status="Failed", error_code="DECLINED", error_message="refund declined")
		return Outcome(status="Succeeded", provider_ref=f"{provider_ref}-R", amount=amount, currency=currency,
		               raw_status="REFUNDED")

	return calls, mock.patch.object(MockProvider, "refund", refund)


def requests_of(booking: str) -> list[dict]:
	return frappe.get_all(DT, filters={"booking": booking}, fields=["*"], order_by="creation asc")


class TestReviewRefundGuards(GuestMoneyCase):
	"""H1: a lower price never refunds what the rate or its cancellation terms would keep."""

	def test_a_non_refundable_stay_shortened_goes_to_the_hotel(self):
		lower_price_policy("Refund automatically")
		b = nrf_books("gcm-nrf")
		paid(b["payment"])
		total, held, _bal = money(b["booking"])
		self.assertEqual(held, total)                                  # paid in full
		down = self.propose(b, (6, 11))                               # three nights → one
		self.assertLess(D(down["difference"]), 0)
		self.assertEqual(down["settlement"]["kind"], "staff_approval")
		out = self.accept(b, down)
		self.assertEqual(out["status"], "requested")
		self.assertEqual(refunds(b["booking"]), [])
		self.assertEqual(money(b["booking"])[:2], (total, held))
		lower_price_policy("Keep as credit")                           # a credit would be the same bypass
		self.assertEqual(self.propose(b, (6, 12))["settlement"]["kind"], "staff_approval")

	def test_a_shortening_inside_the_cancellation_penalty_window_goes_to_the_hotel(self):
		lower_price_policy("Refund automatically")
		b = self.fully_paid("gcm-window")
		three_days_before = get_datetime(f"{fx.YEAR}-06-07 12:00:00")
		with mock.patch("kamra.tex.services.booking.now_datetime", return_value=three_days_before):
			down = self.propose(b, (6, 12))
			self.assertEqual(down["settlement"]["kind"], "staff_approval")   # the first night is charged now
			out = self.accept(b, down)
		self.assertEqual(out["status"], "requested")
		self.assertEqual(refunds(b["booking"]), [])
		# outside the window the same shortening is refunded
		self.assertEqual(self.propose(b, (6, 11))["settlement"]["kind"], "refund")

	def test_no_guest_change_once_the_guest_arrived(self):
		lower_price_policy("Refund automatically")
		b = self.fully_paid("gcm-arrived")
		res = b["rooms"][0]["reservation"]
		down = self.propose(b, (6, 12))
		frappe.db.set_value("Reservation", res, "status", "Checked In", update_modified=False)
		for call in (lambda: self.propose(b, (6, 11)), lambda: self.accept(b, down),
		             lambda: public.manage_cancel(token=b["manage_token"], reservation=res)):
			with self.assertRaisesRegex(frappe.ValidationError, "no longer be changed online"):
				call()
		self.assertEqual(refunds(b["booking"]), [])
		self.assertEqual(frappe.db.count(DT, {"booking": b["booking"]}), 0)


class TestReviewRefundDurability(GuestMoneyCase):
	"""H2: a refund the gateway did not answer is never made again, nor moved to another charge."""

	def test_a_refund_the_gateway_did_not_answer_stops_and_waits_for_staff(self):
		lower_price_policy("Refund automatically")
		b = self.fully_paid("gcm-timeout")
		deposit, balance = charges(b["booking"])
		from kamra.tex.services import guest_changes

		calls, gateway = gateway_calls(timeout=True)
		with gateway:
			out = self.accept(b, self.propose(b, (6, 12)))
			guest_changes.settle(out["request"])                     # a retry of the job asks nothing again
		self.assertEqual(calls, [(f"MOCK-{balance}", D("267.50"))])  # one question, never a second charge
		self.assertEqual(refunds(b["booking"]), [(balance, D("267.50"), "Pending")])
		self.assertEqual(money(b["booking"])[1], D("842.50"))          # not taken off until it is known
		req = frappe.get_doc(DT, out["request"])
		# the refund waits for staff, and the request with it (re-review F3: nothing of it is dropped)
		self.assertEqual((req.staff_open, req.staff_reason, D(req.staff_amount), req.settle_pending),
		                 (1, "Verify refund at gateway", D("267.50"), 1))
		self.assertTrue(req.unknown_refund)
		frappe.set_user("Administrator")  # nosemgrep: frappe-setuser -- finance checks the gateway
		from kamra.tex.ops import status as system_status

		check = next(c for c in system_status.collect(properties=[fx.PROPERTY]) if c["key"] == "payments.callbacks")
		self.assertIn(("refund_unknown", {"count": 1}), [(i["reason"], i["params"]) for i in check["issues"]])
		self.assertIn(req.name, [r["name"] for r in crs_api.guest_change_requests(property=fx.PROPERTY,
		                                                                          needs_staff=1)])
		done = crs_api.resolve_guest_change(request=req.name, action="close", reason="refund seen at the gateway",
		                                    refund_outcome="Succeeded")
		self.assertEqual((done["staff_open"], done["refunded_amount"]), (False, "267.50"))
		self.assertEqual(refunds(b["booking"]), [(balance, D("267.50"), "Succeeded")])
		self.assertEqual(money(b["booking"]), (D("575.00"), D("575.00"), D("0.00")))
		self.assertNotEqual(deposit, balance)

	def test_staff_record_a_refund_the_gateway_did_not_make(self):
		lower_price_policy("Refund automatically")
		b = self.fully_paid("gcm-timeout-no")
		deposit, balance = charges(b["booking"])
		_calls, gateway = gateway_calls(timeout=True)
		with gateway:
			out = self.accept(b, self.propose(b, (6, 12)))
		frappe.set_user("Administrator")  # nosemgrep: frappe-setuser -- finance checks the gateway
		with self.assertRaisesRegex(frappe.ValidationError, "Say whether the gateway made refund"):
			crs_api.resolve_guest_change(request=out["request"], action="close", reason="checked")
		done = crs_api.resolve_guest_change(request=out["request"], action="close", reason="not at the gateway",
		                                    refund_outcome="Failed")
		# not made: TEX refunds it again from the other card payment, the rest waits for staff
		# (re-review F3; before, a "Failed" close left all of it on the booking)
		self.assertEqual(refunds(b["booking"]), [(balance, D("267.50"), "Failed"),
		                                         (deposit, D("252.75"), "Succeeded")])
		self.assertEqual((done["staff_open"], done["refunded_amount"], done["staff_amount"], done["staff_reason"]),
		                 (True, "252.75", "14.75", "Refund by staff"))
		self.assertEqual(money(b["booking"])[1], D("589.75"))

	def test_a_declined_refund_moves_on_to_the_older_charges(self):
		lower_price_policy("Refund automatically")
		b = self.deposit_paid("gcm-spill")
		up = self.accept(b, self.propose(b, (6, 14)))
		paid(up["payment"])                                            # the change's own 80.25
		paid(public.pay_booking(token=b["manage_token"]))               # the rest: 777.00
		deposit, change, rest = charges(b["booking"])
		self.assertEqual(money(b["booking"]), (D("1110.00"), D("1110.00"), D("0.00")))
		calls, gateway = gateway_calls({rest: "Failed"})
		with gateway:
			out = self.accept(b, self.propose(b, (6, 11)))            # 1110.00 → 307.50: 802.50 over
		self.assertEqual([c[0] for c in calls], [f"MOCK-{rest}", f"MOCK-{change}", f"MOCK-{deposit}"])
		self.assertEqual(refunds(b["booking"]), [(rest, D("777.00"), "Failed"), (change, D("80.25"), "Succeeded"),
		                                         (deposit, D("252.75"), "Succeeded")])
		req = frappe.get_doc(DT, out["request"])
		self.assertEqual((D(req.refunded_amount), req.staff_open, D(req.staff_amount), req.staff_reason),
		                 (D("333.00"), 1, D("469.50"), "Refund by staff"))
		self.assertEqual(money(b["booking"])[1], D("777.00"))

	def test_refunds_spread_over_charges_newest_first(self):
		lower_price_policy("Refund automatically")
		b = self.deposit_paid("gcm-spill-ok")
		up = self.accept(b, self.propose(b, (6, 14)))
		paid(up["payment"])
		paid(public.pay_booking(token=b["manage_token"]))
		_deposit, change, rest = charges(b["booking"])
		out = self.accept(b, self.propose(b, (6, 11)))
		self.assertEqual((out["settlement"]["kind"], out["settlement"]["refund"], out["settlement"]["hotel_refund"],
		                  out["settlement"]["refund_done"]), ("refund", "802.50", "0.00", True))
		self.assertEqual(refunds(b["booking"]), [(rest, D("777.00"), "Succeeded"), (change, D("25.50"), "Succeeded")])
		self.assertEqual(money(b["booking"]), (D("307.50"), D("307.50"), D("0.00")))

	def test_a_staff_refund_is_on_record_before_the_gateway_is_asked(self):
		b = self.fully_paid("gcm-staff-timeout")
		_deposit, balance = charges(b["booking"])
		order: list = []

		def durable():
			order.append(("commit", frappe.db.get_value(TXN, {"parent_transaction": balance, "txn_type": "Refund"},
			                                            "status")))

		calls, gateway = gateway_calls(timeout=True)
		frappe.set_user("Administrator")  # nosemgrep: frappe-setuser -- finance refunds a goodwill amount
		with gateway, mock.patch.object(pay, "_durable_commit", durable):
			with self.assertRaises(pay.RefundUnknown):
				pay_api.refund(transaction=balance, amount="10.00", reason="goodwill", idempotency_key="gcm-g1",
				               booking=b["booking"])
			again = pay_api.refund(transaction=balance, amount="10.00", reason="goodwill", idempotency_key="gcm-g1",
			                       booking=b["booking"])
		self.assertEqual(order[0], ("commit", "Pending"))              # the attempt is durable first …
		self.assertEqual(len(calls), 1)                                # … then asked once, never again
		self.assertEqual((again["replay"], again["status"]), (True, "Pending"))
		row = frappe.db.get_value(TXN, again["refund"], ["status", "error_code"], as_dict=True)
		self.assertEqual((row.status, row.error_code), ("Pending", "UNKNOWN"))


class TestReviewRefundAmounts(GuestMoneyCase):
	"""H3: a refund is what is still over when it is made, never money used or refunded since."""

	def queued(self):
		from kamra.tex.services import guest_changes

		return mock.patch.object(guest_changes, "queue_settle")

	def test_a_queued_refund_is_capped_by_what_is_still_over(self):
		lower_price_policy("Refund automatically")
		b = self.fully_paid("gcm-cap")
		res = b["rooms"][0]["reservation"]
		with self.queued():
			out = self.accept(b, self.propose(b, (6, 12)))
		self.assertEqual(frappe.db.get_value(DT, out["request"], "settle_pending"), 1)
		with self.assertRaisesRegex(frappe.ValidationError, "being processed"):
			self.propose(b, (6, 13))                                  # no new change while it is refunded
		self.assertEqual(public.booking_status(token=b["manage_token"])["changes_blocked"], "REFUND_PENDING")
		frappe.set_user("Administrator")  # nosemgrep: frappe-setuser -- the guest phones: back to three nights
		back = modification.propose(res, {"check_out": str(fx.d(6, 13))})
		modification.apply(back["proposal_token"], reason="guest phoned")
		from kamra.tex.services import guest_changes

		guest_changes.settle(out["request"])
		self.assertEqual(refunds(b["booking"]), [])                    # nothing is over any more
		self.assertEqual(money(b["booking"]), (D("842.50"), D("842.50"), D("0.00")))
		self.assertEqual(frappe.db.get_value(DT, out["request"], "settle_pending"), 0)

	def test_a_refund_staff_made_by_hand_is_not_made_again(self):
		lower_price_policy("Refund automatically")
		b = self.fully_paid("gcm-by-hand")
		_deposit, balance = charges(b["booking"])
		with self.queued():
			out = self.accept(b, self.propose(b, (6, 12)))
		frappe.set_user("Administrator")  # nosemgrep: frappe-setuser -- finance refunds the credit by hand
		pay_api.refund(transaction=balance, amount="267.50", reason="guest asked at the desk",
		               idempotency_key="gcm-hand-1", booking=b["booking"])
		from kamra.tex.services import guest_changes

		guest_changes.settle(out["request"])
		self.assertEqual(refunds(b["booking"]), [(balance, D("267.50"), "Succeeded")])     # one refund only
		self.assertEqual(money(b["booking"]), (D("575.00"), D("575.00"), D("0.00")))

	def test_a_late_payment_of_a_replaced_change_is_returned_not_used_for_another_refund(self):
		lower_price_policy("Refund automatically")
		b = self.deposit_paid("gcm-reserved")
		first = self.accept(b, self.propose(b, (6, 14)))              # waits for 80.25
		rest = public.pay_booking(token=b["manage_token"])              # the guest pays the rest instead
		paid(rest)
		balance = rest["transaction"]
		with self.queued():
			second = self.accept(b, self.propose(b, (6, 12)))          # replaces the first: 267.50 over
			self.assertEqual(frappe.db.get_value(DT, first["request"], "status"), "Superseded")
			paid(first["payment"])                                      # the old checkout is paid after all
		from kamra.tex.services import guest_changes

		guest_changes.settle(second["request"])                       # its plan runs first
		guest_changes.settle(first["request"])
		self.assertEqual(sorted(refunds(b["booking"])), sorted([(balance, D("267.50"), "Succeeded"),
		                                                        (first["payment"]["transaction"], D("80.25"),
		                                                         "Succeeded")]))
		self.assertEqual(money(b["booking"]), (D("575.00"), D("575.00"), D("0.00")))


class TestReviewPaidChanges(GuestMoneyCase):
	"""M1, M2 and the gaps: the payment callback records the charge; a job applies the change."""

	def test_the_callback_records_the_payment_and_a_job_applies_the_change(self):
		b = self.deposit_paid("gcm-job")
		res = b["rooms"][0]["reservation"]
		out = self.accept(b, self.propose(b, (6, 14)))
		from kamra.tex.services import guest_changes

		with mock.patch.object(guest_changes, "queue_apply") as queued:
			paid(out["payment"])
		queued.assert_called_once_with(out["request"], out["payment"]["transaction"])
		self.assertEqual(stay(res), (str(fx.d(6, 13)), D("842.50")))      # the callback changed no stay
		self.assertEqual(money(b["booking"])[1], D("333.00"))            # the money is recorded
		later = add_to_date(now_datetime(), minutes=5)
		with mock.patch("kamra.tex.services.guest_changes.now_datetime", return_value=later):
			self.assertEqual(guest_changes.expire_awaiting()["applied"], 1)   # the job never ran: the scheduler
		self.assertEqual(stay(res), (str(fx.d(6, 14)), D("1110.00")))
		self.assertEqual(frappe.db.get_value(DT, out["request"], "status"), "Applied")

	def test_a_payment_made_after_the_deadline_is_refunded_before_the_request_expires(self):
		b = self.deposit_paid("gcm-late-pay")
		out = self.accept(b, self.propose(b, (6, 14)))
		deadline = get_datetime(frappe.db.get_value(DT, out["request"], "expires_at"))
		with mock.patch("kamra.tex.payments.service.now_datetime", return_value=add_to_date(deadline, minutes=5)):
			paid(out["payment"])
		req = frappe.get_doc(DT, out["request"])
		self.assertEqual(req.status, "Failed")
		self.assertIn("expired", req.error)
		self.assertEqual(refunds(b["booking"]), [(out["payment"]["transaction"], D("80.25"), "Succeeded")])
		self.assertEqual(stay(b["rooms"][0]["reservation"])[0], str(fx.d(6, 13)))

	def test_a_change_that_breaks_while_applying_is_refunded(self):
		b = self.deposit_paid("gcm-break")
		out = self.accept(b, self.propose(b, (6, 14)))
		with mock.patch("kamra.tex.services.modification.apply", side_effect=KeyError("snapshot")):
			paid(out["payment"])
		self.assertEqual(frappe.db.get_value(DT, out["request"], "status"), "Failed")
		self.assertEqual(refunds(b["booking"]), [(out["payment"]["transaction"], D("80.25"), "Succeeded")])
		self.assertEqual(money(b["booking"])[1], D("252.75"))

	def test_a_second_paid_attempt_of_an_applied_change_is_refunded_or_left_to_staff(self):
		b = self.deposit_paid("gcm-dup")
		up = self.propose(b, (6, 14))
		first = self.accept(b, up)
		declined(first["payment"])
		retry = self.accept(b, up)
		paid(retry["payment"])
		self.assertEqual(frappe.db.get_value(DT, first["request"], "status"), "Applied")
		calls, gateway = gateway_calls({first["payment"]["transaction"]: "Failed"})
		with gateway:
			paid(first["payment"])                                     # the declined tab is paid after all
		req = frappe.get_doc(DT, first["request"])
		self.assertEqual((req.status, req.settlement, req.payment_transaction),
		                 ("Applied", "Online payment", retry["payment"]["transaction"]))
		self.assertEqual((req.staff_open, D(req.staff_amount), req.staff_reason), (1, D("80.25"), "Refund by staff"))
		frappe.set_user("Administrator")  # nosemgrep: frappe-setuser -- finance sees it in the queue
		row = next(r for r in crs_api.guest_change_requests(property=fx.PROPERTY, needs_staff=1)
		           if r["name"] == req.name)
		self.assertEqual((row["needs_staff"], row["staff_amount"]), (True, "80.25"))
		self.assertEqual(len(calls), 1)

	def test_a_guest_cancelling_the_room_voids_a_waiting_change(self):
		b = self.deposit_paid("gcm-void")
		res = b["rooms"][0]["reservation"]
		out = self.accept(b, self.propose(b, (6, 14)))
		frappe.set_user("Guest")  # nosemgrep: frappe-setuser -- the guest cancels on the manage page
		public.manage_cancel(token=b["manage_token"], reservation=res)
		self.assertEqual(frappe.db.get_value(DT, out["request"], "status"), "Superseded")
		paid(out["payment"])
		self.assertEqual(refunds(b["booking"])[-1], (out["payment"]["transaction"], D("80.25"), "Succeeded"))
		last = public.booking_status(token=b["manage_token"])["rooms"][0]["last_change"]
		self.assertEqual((last["status"], last["paid"], last["refunded"], last["money_back"]),
		                 ("superseded", "80.25", "80.25", "refunded"))

	def test_a_declined_checkout_is_not_announced_as_a_refund(self):
		b = self.deposit_paid("gcm-declined")
		out = self.accept(b, self.propose(b, (6, 14)))
		declined(out["payment"])                                     # the card was declined; no retry
		from kamra.tex.services import guest_changes

		later = add_to_date(now_datetime(), hours=2)
		with mock.patch("kamra.tex.services.guest_changes.now_datetime", return_value=later):
			guest_changes.expire_awaiting()
		last = public.booking_status(token=b["manage_token"])["rooms"][0]["last_change"]
		self.assertEqual((last["request"], last["status"], last["paid"], last["money_back"]),
		                 (out["request"], "expired", "0.00", "none"))  # "no payment was taken", not "refunded"

	def test_a_price_in_another_currency_is_never_offered_or_applied(self):
		b = self.deposit_paid("gcm-ccy")
		real = modification.propose

		def in_dollars(*args, **kwargs):
			out = real(*args, **kwargs)
			return {**out, "currency_changed": True, "proposed": {**out["proposed"], "currency": "USD"}}

		with mock.patch("kamra.tex.services.modification.propose", side_effect=in_dollars):
			up = self.propose(b, (6, 14))
		self.assertEqual((up["sellable"], up["proposal_token"], up["settlement"]), (False, None, None))
		self.assertIn("CURRENCY_CHANGED", [w["code"] for w in up["warnings"]])
		from kamra.tex.services import quoting

		token = self.propose(b, (6, 14))["proposal_token"]
		forged = quoting.sign({**quoting.verify(token, kind="proposal"), "currency": "USD"})
		with self.assertRaisesRegex(frappe.ValidationError, "currency of your booking"):
			public.manage_apply(token=b["manage_token"], proposal_token=forged)
		self.assertEqual(frappe.db.count(DT, {"booking": b["booking"]}), 0)

	def test_the_same_proposal_with_junk_appended_is_the_same_request(self):
		b = self.deposit_paid("gcm-junk")
		up = self.propose(b, (6, 14))
		first = self.accept(b, up)
		second = self.accept(b, {**up, "proposal_token": up["proposal_token"] + "!!!!"})
		self.assertEqual((second["status"], second["request"]), ("payment_required", first["request"]))
		self.assertEqual(frappe.db.count(DT, {"booking": b["booking"]}), 1)

	def test_the_gateway_is_asked_after_the_request_is_on_record(self):
		b = self.deposit_paid("gcm-order")
		from kamra.tex.payments.providers.simple import MockProvider
		from kamra.tex.services import guest_changes

		order: list = []
		real = MockProvider.create_checkout

		def checkout(self_, intent):
			order.append("gateway")
			return real(self_, intent)

		with mock.patch.object(guest_changes, "_release_locks", side_effect=lambda: order.append("committed")), \
				mock.patch.object(MockProvider, "create_checkout", checkout):
			out = self.accept(b, self.propose(b, (6, 14)))
		self.assertEqual(out["status"], "payment_required")
		self.assertEqual(order, ["committed", "gateway"])

	def test_every_path_locks_the_booking_first(self):
		b = self.deposit_paid("gcm-locks")
		res = b["rooms"][0]["reservation"]
		frappe.set_user("Administrator")  # nosemgrep: frappe-setuser -- reservations change and cancel the stay
		staff = modification.propose(res, {"check_out": str(fx.d(6, 12))})
		for run in (lambda: modification.apply(staff["proposal_token"], reason="guest phoned"),
		            lambda: crs_api.cancel(reservation=res, reason="guest phoned")):
			seen = locks_during(run)
			booking_at = seen.index("tabTEX Booking")
			for table in ("tabReservation", "tabTEX Inventory Day"):
				if table in seen:
					self.assertLess(booking_at, seen.index(table), f"{table} locked before the booking: {seen}")


def locks_during(run) -> list[str]:
	"""The tables whose rows ``run`` locks or writes, in the order it first does (a locking read,
	an UPDATE or an INSERT locks rows until the transaction ends)."""
	import re

	seen: list[str] = []
	real = frappe.db.sql

	def sql(query, *args, **kwargs):
		q = str(query)
		m = (re.search(r"FROM\s+`(tab[^`]+)`.*FOR UPDATE", q, re.S | re.I) if re.search(r"FOR UPDATE", q, re.I)
		     else re.match(r"\s*(?:UPDATE|INSERT INTO)\s+`(tab[^`]+)`", q, re.I))
		if m and m.group(1) not in seen:
			seen.append(m.group(1))
		return real(query, *args, **kwargs)

	with mock.patch.object(frappe.db, "sql", side_effect=sql):
		run()
	return seen


class TestReviewStaffCredit(GuestMoneyCase):
	def test_the_hotel_approves_a_lower_price_as_credit(self):
		b = self.fully_paid("gcm-approve-credit")
		out = self.accept(b, self.propose(b, (6, 12)))
		self.assertEqual(out["status"], "requested")
		frappe.set_user("Administrator")  # nosemgrep: frappe-setuser -- reservations approve with credit
		done = crs_api.resolve_guest_change(request=out["request"], action="approve", reason="ok",
		                                    settlement="Credit on booking")
		self.assertEqual((done["status"], done["settlement"], done["settlement_amount"]),
		                 ("Approved", "Credit on booking", "267.50"))
		self.assertEqual(refunds(b["booking"]), [])
		self.assertEqual(public.booking_status(token=b["manage_token"])["credit"], "267.50")
		self.assertTrue(frappe.db.exists("TEX Audit Event", {"action": "guest_change.credit",
		                                                     "reference_name": b["booking"]}))


# ─── second review (G-45 re-review F1–F8) ───────────────────────────────


class Crash(BaseException):
	"""The worker dies (killed, out of memory, the container lost): nothing after this point runs
	and nothing TEX catches stops it. What is left is what was on record when it died: tests keep
	one transaction, so that is what a commit before that point would have left (the durable
	refund row is committed before the gateway is asked)."""


def crashing_gateway():
	"""The gateway makes the refund, and the worker dies before TEX hears the answer."""
	from kamra.tex.payments.providers.simple import MockProvider

	calls: list[tuple[str, D]] = []

	def refund(self, provider_ref, amount, currency, **_kw):
		calls.append((provider_ref, D(amount)))
		raise Crash()

	return calls, mock.patch.object(MockProvider, "refund", refund)


def settle_queued():
	"""The refund job is queued, not run (the worker has not picked it up yet)."""
	from kamra.tex.services import guest_changes

	return mock.patch.object(guest_changes, "queue_settle")


def at(minutes: int):
	"""TEX's guest-change clock ``minutes`` from now (the scheduler running later)."""
	return mock.patch("kamra.tex.services.guest_changes.now_datetime",
	                  return_value=add_to_date(now_datetime(), minutes=minutes))


def refund_row(charge: str) -> str:
	return frappe.db.get_value(TXN, {"parent_transaction": charge, "txn_type": "Refund"}, "name",
	                           order_by="creation desc")


def audits(action: str, name: str) -> int:
	return frappe.db.count("TEX Audit Event", {"action": action, "reference_name": name})


class TestReReviewInFlight(GuestMoneyCase):
	"""F1: a refund run never plans around its own refund in flight, and never overlaps another."""

	def test_a_refund_the_worker_never_finished_is_never_made_again(self):
		lower_price_policy("Refund automatically")
		b = self.fully_paid("gcm2-crash")
		_deposit, balance = charges(b["booking"])
		from kamra.tex.services import guest_changes

		with settle_queued():
			out = self.accept(b, self.propose(b, (6, 12)))
		calls, gateway = crashing_gateway()
		with gateway, self.assertRaises(Crash):
			guest_changes.settle(out["request"])          # the gateway refunds; the worker dies before TEX hears it
		self.assertEqual(calls, [(f"MOCK-{balance}", D("267.50"))])
		row = refund_row(balance)
		self.assertEqual(refunds(b["booking"]), [(balance, D("267.50"), "Pending")])
		more, gateway = gateway_calls()
		with gateway:
			with at(1):
				guest_changes.settle(out["request"])      # a second run while the first one holds the refunds
			self.assertEqual(more, [])
			# the first run's hold ended (it died) but its refund is fresh: wait, never plan around it
			frappe.db.set_value(DT, out["request"], "settle_claimed_until", add_to_date(now_datetime(), minutes=-1))
			guest_changes.settle(out["request"])
			self.assertEqual(more, [])
			self.assertEqual(frappe.db.get_value(DT, out["request"], ["settle_pending", "staff_open"]), (1, 0))
			with at(guest_changes.SETTLE_RETRY_MINUTES + 1):
				guest_changes.expire_awaiting()           # the scheduler: the refund is old, staff verify it
		self.assertEqual(more, [])                        # no other charge refunded instead
		self.assertEqual(refunds(b["booking"]), [(balance, D("267.50"), "Pending")])
		req = frappe.get_doc(DT, out["request"])
		self.assertEqual((req.staff_open, req.staff_reason, D(req.staff_amount), req.unknown_refund),
		                 (1, "Verify refund at gateway", D("267.50"), row))
		self.assertEqual(money(b["booking"])[1], D("842.50"))
		self.assertEqual(public.booking_status(token=b["manage_token"])["credit"], "0.00")

	def test_the_apply_job_and_the_scheduler_hand_one_payment_back_once(self):
		b = self.deposit_paid("gcm2-twice")
		res = b["rooms"][0]["reservation"]
		out = self.accept(b, self.propose(b, (6, 14)))
		frappe.set_user("Administrator")  # nosemgrep: frappe-setuser -- an agent changes the stay meanwhile
		staff = modification.propose(res, {"check_out": str(fx.d(6, 12))})
		modification.apply(staff["proposal_token"], reason="guest phoned")
		txn = out["payment"]["transaction"]
		with settle_queued():
			paid(out["payment"])                          # the apply job fails the change, its refund is queued
		self.assertEqual(frappe.db.get_value(DT, out["request"], ["status", "settle_pending"]), ("Failed", 1))
		from kamra.tex.services import guest_changes

		calls, gateway = crashing_gateway()
		with gateway, self.assertRaises(Crash):
			guest_changes.settle(out["request"])          # the refund is asked for; the worker dies
		more, gateway = gateway_calls()
		with gateway:
			# the scheduler had read the request as still waiting: the same payment, once more
			self.assertEqual(guest_changes.apply_paid(out["request"], txn), "done")
			self.assertEqual(audits("guest_change.late_payment", out["request"]), 0)
			req = frappe.get_doc(DT, out["request"])
			self.assertEqual((req.status, req.settle_pending, req.staff_open), ("Failed", 1, 0))
			with at(guest_changes.SETTLE_RETRY_MINUTES + 1):
				guest_changes.expire_awaiting()
		self.assertEqual((len(calls), more), (1, []))
		req.reload()
		self.assertEqual((req.staff_open, req.staff_reason, req.unknown_refund),
		                 (1, "Verify refund at gateway", refund_row(txn)))

	def test_a_refund_staff_started_and_never_confirmed_is_not_the_guests_credit(self):
		lower_price_policy("Keep as credit")
		b = self.fully_paid("gcm2-staff-pending")
		_deposit, balance = charges(b["booking"])
		frappe.set_user("Administrator")  # nosemgrep: frappe-setuser -- finance refunds a goodwill amount
		_calls, gateway = gateway_calls(timeout=True)
		with gateway, self.assertRaises(pay.RefundUnknown):
			pay_api.refund(transaction=balance, amount="100.00", reason="goodwill", idempotency_key="gcm2-sp-1",
			               booking=b["booking"])
		down = self.propose(b, (6, 12))                   # 267.50 lower; 100.00 of it may be back on the card
		self.assertEqual((down["settlement"]["kind"], down["settlement"]["amount"]), ("credit", "167.50"))
		out = self.accept(b, down)
		self.assertEqual((out["credit"], out["refund_due"]), ("167.50", "100.00"))


class TestReReviewStaff(GuestMoneyCase):
	"""F2 and F3: a refund the gateway never confirmed is closed from the payment screen too, and
	what the change still owes is refunded after it."""

	def setUp(self):
		super().setUp()
		other_hotel_with_mock()
		self.outsider = fx.ensure_user("gcm-outsider@example.com", ["Hotel Admin"])
		fx.ensure("TEX Access Grant", {"user": self.outsider, "property": OTHER},
		          {"user": self.outsider, "scope_level": "Hotel", "property": OTHER,
		           "permission_profile": "Hotel Admin"})
		scope.clear_cache()

	def test_staff_record_a_refunds_outcome_from_the_payment_screen(self):
		b = self.fully_paid("gcm2-finish")
		_deposit, balance = charges(b["booking"])
		frappe.set_user("Administrator")  # nosemgrep: frappe-setuser -- finance refunds a goodwill amount
		_calls, gateway = gateway_calls(timeout=True)
		with gateway, self.assertRaises(pay.RefundUnknown):
			pay_api.refund(transaction=balance, amount="10.00", reason="goodwill", idempotency_key="gcm2-f1",
			               booking=b["booking"])
		row = refund_row(balance)
		self.assertEqual(pay_api.transaction(name=balance)["refundable"], "579.75")   # 10.00 may be gone
		frappe.set_user(self.outsider)  # nosemgrep: frappe-setuser -- the admin of another hotel
		with self.assertRaises(frappe.PermissionError):
			pay_api.finish_refund(refund=row, outcome="Succeeded", reason="seen")
		frappe.set_user("Administrator")  # nosemgrep: frappe-setuser -- finance checked the gateway
		with self.assertRaisesRegex(frappe.ValidationError, "reason"):
			pay_api.finish_refund(refund=row, outcome="Succeeded", reason=" ")
		done = pay_api.finish_refund(refund=row, outcome="Succeeded", reason="seen at the gateway",
		                             reference="GW-77")
		self.assertEqual((done["status"], done["amount"]), ("Succeeded", "10.00"))
		self.assertEqual(money(b["booking"])[1], D("832.50"))
		self.assertEqual(frappe.db.get_value(TXN, row, ["status", "provider_ref"]), ("Succeeded", "GW-77"))
		self.assertEqual(audits("payment.refund_verified", row), 1)
		with self.assertRaisesRegex(frappe.ValidationError, "waiting for its outcome"):
			pay_api.finish_refund(refund=row, outcome="Failed", reason="again")

	def test_a_refund_left_pending_is_flagged_after_a_few_minutes(self):
		b = self.fully_paid("gcm2-stuck")
		_deposit, balance = charges(b["booking"])
		frappe.set_user("Administrator")  # nosemgrep: frappe-setuser -- finance refunds; the worker dies
		_calls, gateway = crashing_gateway()
		with gateway, self.assertRaises(Crash):
			pay_api.refund(transaction=balance, amount="10.00", reason="goodwill", idempotency_key="gcm2-s1",
			               booking=b["booking"])
		self.assertIsNone(frappe.db.get_value(TXN, refund_row(balance), "error_code"))   # no answer, no error
		from kamra.tex.ops import status as system_status

		def reasons(minutes):
			check = next(c for c in system_status.collect(properties=[fx.PROPERTY],
			                                              now=add_to_date(now_datetime(), minutes=minutes))
			             if c["key"] == "payments.callbacks")
			return [(i["reason"], i["params"]) for i in check["issues"]]

		self.assertEqual(reasons(0), [])                                # just asked: its answer may still come
		self.assertIn(("refund_unknown", {"count": 1}), reasons(pay.REFUND_STUCK_MINUTES + 1))

	def test_a_guest_changes_refund_closed_from_the_payment_screen_settles_the_change(self):
		lower_price_policy("Refund automatically")
		b = self.fully_paid("gcm2-finish-gcr")
		_deposit, balance = charges(b["booking"])
		_calls, gateway = gateway_calls(timeout=True)
		with gateway:
			out = self.accept(b, self.propose(b, (6, 12)))
		row = refund_row(balance)
		frappe.set_user("Administrator")  # nosemgrep: frappe-setuser -- finance checked the gateway
		pay_api.finish_refund(refund=row, outcome="Succeeded", reason="seen at the gateway")
		req = frappe.get_doc(DT, out["request"])
		self.assertEqual((D(req.refunded_amount), req.staff_open, D(req.staff_amount), req.settle_pending),
		                 (D("267.50"), 0, D("0"), 0))
		self.assertEqual(money(b["booking"]), (D("575.00"), D("575.00"), D("0.00")))
		self.assertEqual(crs_api.guest_change_requests(property=fx.PROPERTY, needs_staff=1), [])

	def spread(self, session: str):
		"""1110.00 paid by three card charges (deposit 252.75, the change's 80.25, the rest 777.00)."""
		b = self.deposit_paid(session)
		paid(self.accept(b, self.propose(b, (6, 14)))["payment"])
		paid(public.pay_booking(token=b["manage_token"]))
		return b, *charges(b["booking"])

	def test_after_an_unanswered_refund_the_rest_is_still_refunded(self):
		lower_price_policy("Refund automatically")
		b, _deposit, change, rest = self.spread("gcm2-rest")
		calls, gateway = gateway_calls({rest: "Timeout"})
		down = self.propose(b, (6, 11))                   # 1110.00 → 307.50: 802.50 back
		with gateway:
			out = self.accept(b, down)
			self.assertEqual(calls, [(f"MOCK-{rest}", D("777.00"))])   # stops at the refund never answered
			req = frappe.get_doc(DT, out["request"])
			self.assertEqual((req.settle_pending, req.staff_open, req.staff_reason, D(req.staff_amount)),
			                 (1, 1, "Verify refund at gateway", D("777.00")))
			# the rest is owed, not the guest's credit, and nothing changes until it is settled
			view = public.booking_status(token=b["manage_token"])
			self.assertEqual((view["credit"], view["refund_due"], view["changes_blocked"]),
			                 ("0.00", "802.50", "REFUND_PENDING"))
			frappe.set_user("Administrator")  # nosemgrep: frappe-setuser -- finance saw the refund at the gateway
			done = crs_api.resolve_guest_change(request=req.name, action="close", reason="refund seen at the gateway",
			                                    refund_outcome="Succeeded")
		self.assertEqual(refunds(b["booking"]), [(rest, D("777.00"), "Succeeded"), (change, D("25.50"), "Succeeded")])
		self.assertEqual((done["refunded_amount"], done["staff_amount"], done["staff_open"], done["settle_pending"]),
		                 ("802.50", "0.00", False, False))
		self.assertEqual(money(b["booking"]), (D("307.50"), D("307.50"), D("0.00")))
		again = self.accept(b, down)
		self.assertEqual((again["settlement"]["refund"], again["settlement"]["hotel_refund"],
		                  again["settlement"]["refund_done"]), ("802.50", "0.00", True))

	def test_a_refund_found_not_made_is_made_from_the_other_payments(self):
		lower_price_policy("Refund automatically")
		b, deposit, change, rest = self.spread("gcm2-not-made")
		calls, gateway = gateway_calls({rest: "Timeout"})
		with gateway:
			out = self.accept(b, self.propose(b, (6, 11)))
			frappe.set_user("Administrator")  # nosemgrep: frappe-setuser -- the gateway shows no refund
			done = crs_api.resolve_guest_change(request=out["request"], action="close", reason="not at the gateway",
			                                    refund_outcome="Failed")
		self.assertEqual([c[0] for c in calls], [f"MOCK-{rest}", f"MOCK-{change}", f"MOCK-{deposit}"])
		self.assertEqual(refunds(b["booking"]), [(rest, D("777.00"), "Failed"), (change, D("80.25"), "Succeeded"),
		                                         (deposit, D("252.75"), "Succeeded")])
		self.assertEqual((done["refunded_amount"], done["staff_open"], done["staff_amount"], done["staff_reason"],
		                  done["settle_pending"]), ("333.00", True, "469.50", "Refund by staff", False))
		self.assertEqual(money(b["booking"])[1], D("777.00"))


class TestReReviewPaidChanges(GuestMoneyCase):
	"""F4–F7: a paid change waiting to apply, the penalty window, transient errors, lost jobs."""

	def test_a_paid_change_waiting_to_be_applied_is_neither_credit_nor_changed_again(self):
		b = self.deposit_paid("gcm2-waiting")
		res = b["rooms"][0]["reservation"]
		out = self.accept(b, self.propose(b, (6, 14)))
		from kamra.tex.services import guest_changes

		with mock.patch.object(guest_changes, "queue_apply"):
			paid(out["payment"])                          # recorded; the job that applies it has not run yet
		self.assertEqual(money(b["booking"])[1], D("333.00"))
		self.assertEqual(guest_changes.usable_paid(frappe.get_doc("TEX Booking", b["booking"])), D("252.75"))
		with self.assertRaisesRegex(frappe.ValidationError, "being applied"):
			self.propose(b, (6, 15))                      # a new change would use the paid one's money
		self.assertEqual(public.booking_status(token=b["manage_token"])["changes_blocked"], "CHANGE_APPLYING")
		with at(guest_changes.APPLY_RETRY_MINUTES + 3):
			self.assertEqual(guest_changes.expire_awaiting()["applied"], 1)
		self.assertEqual(stay(res), (str(fx.d(6, 14)), D("1110.00")))
		self.assertIsNone(public.booking_status(token=b["manage_token"])["changes_blocked"])

	def test_moving_the_arrival_later_inside_the_penalty_window_goes_to_the_hotel(self):
		lower_price_policy("Refund automatically")
		b = self.fully_paid("gcm2-shift")
		res = b["rooms"][0]["reservation"]
		later = {"check_in": str(fx.d(6, 11)), "check_out": str(fx.d(6, 14))}
		three_days_before = get_datetime(f"{fx.YEAR}-06-07 12:00:00")
		frappe.set_user("Guest")  # nosemgrep: frappe-setuser -- the guest on the manage page
		with mock.patch("kamra.tex.services.booking.now_datetime", return_value=three_days_before):
			shift = public.manage_propose(token=b["manage_token"], reservation=res, changes=later)
			# moved later, the stay would leave the window: then shortened, refunded without its fee
			self.assertEqual(shift["settlement"]["kind"], "staff_approval")
			out = self.accept(b, shift)
		self.assertEqual(out["status"], "requested")
		self.assertEqual(stay(res), (str(fx.d(6, 13)), D("842.50")))                    # the hotel decides
		self.assertEqual(frappe.db.get_value(DT, out["request"], "penalty_terms"), 1)
		view = public.booking_status(token=b["manage_token"])["rooms"][0]["pending_change"]
		self.assertEqual(view["kind"], "staff_approval")
		frappe.set_user("Guest")  # nosemgrep: frappe-setuser -- outside the window it is the guest's own change
		self.assertNotEqual(public.manage_propose(token=b["manage_token"], reservation=res,
		                                          changes=later)["settlement"]["kind"], "staff_approval")

	def test_a_lock_wait_or_a_lost_connection_while_applying_is_retried_not_refunded(self):
		import pymysql

		from kamra.tex.services import guest_changes

		for session, error in (("gcm2-lockwait", frappe.QueryTimeoutError("Lock wait timeout exceeded")),
		                       ("gcm2-lost", pymysql.err.OperationalError(2013, "Lost connection to server"))):
			with self.subTest(error=type(error).__name__):
				b = self.deposit_paid(session)
				res = b["rooms"][0]["reservation"]
				out = self.accept(b, self.propose(b, (6, 14)))
				with mock.patch("kamra.tex.services.modification.apply", side_effect=error):
					paid(out["payment"])
				self.assertEqual(frappe.db.get_value(DT, out["request"], "status"), "Awaiting Payment")
				self.assertEqual(refunds(b["booking"]), [])
				with at(guest_changes.APPLY_RETRY_MINUTES + 3):
					self.assertEqual(guest_changes.expire_awaiting()["applied"], 1)   # the scheduler applies it
				self.assertEqual(stay(res), (str(fx.d(6, 14)), D("1110.00")))

	def test_a_payment_whose_apply_job_was_lost_is_found_by_the_scheduler(self):
		b = self.deposit_paid("gcm2-lost-job")
		first = self.accept(b, self.propose(b, (6, 14)))
		self.accept(b, self.propose(b, (6, 15)))          # replaces the first
		from kamra.tex.services import guest_changes

		with mock.patch.object(guest_changes, "queue_apply"):
			paid(first["payment"])                        # the old tab is paid; the job that returns it is lost
		self.assertEqual(refunds(b["booking"]), [])
		with at(guest_changes.APPLY_RETRY_MINUTES + 3):
			guest_changes.expire_awaiting()
		self.assertEqual(refunds(b["booking"]), [(first["payment"]["transaction"], D("80.25"), "Succeeded")])
		self.assertEqual(audits("guest_change.late_payment", first["request"]), 1)
		with at(guest_changes.SETTLE_RETRY_MINUTES + 20):
			guest_changes.expire_awaiting()               # found once, returned once
		self.assertEqual(len(refunds(b["booking"])), 1)
		self.assertEqual(audits("guest_change.late_payment", first["request"]), 1)

	def test_a_refund_is_queued_with_the_commit_that_decided_it(self):
		b = self.deposit_paid("gcm2-order")
		res = b["rooms"][0]["reservation"]
		out = self.accept(b, self.propose(b, (6, 14)))
		frappe.set_user("Administrator")  # nosemgrep: frappe-setuser -- an agent changes the stay meanwhile
		staff = modification.propose(res, {"check_out": str(fx.d(6, 12))})
		modification.apply(staff["proposal_token"], reason="guest phoned")
		from kamra.tex.services import guest_changes

		order: list[str] = []
		with mock.patch.object(guest_changes, "queue_settle", side_effect=lambda _n: order.append("queue")), \
				mock.patch.object(guest_changes, "_commit", side_effect=lambda: order.append("commit")):
			paid(out["payment"])
		# registered before the job's commit, so that commit sends it: a later rollback in the same
		# job (the next request failing) can no longer drop it
		self.assertEqual(order[:2], ["queue", "commit"])


# ─── third review (G-45 re-review 3) ───────────────────────────────────


def gateway_during(step, outcome: str = "Succeeded"):
	"""A gateway double: while its first refund call is running, ``step()`` happens (staff
	record an outcome, another run takes over), then it answers ``outcome``."""
	from kamra.tex.payments.providers.base import Outcome
	from kamra.tex.payments.providers.simple import MockProvider

	calls: list[tuple[str, D]] = []

	def refund(self, provider_ref, amount, currency, **_kw):
		calls.append((provider_ref, D(amount)))
		if len(calls) == 1:
			step()
		if outcome == "Failed":
			return Outcome(status="Failed", error_code="DECLINED", error_message="refund declined")
		return Outcome(status="Succeeded", provider_ref=f"{provider_ref}-R", amount=amount, currency=currency,
		               raw_status="REFUNDED")

	return calls, mock.patch.object(MockProvider, "refund", refund)


def as_staff(fn):
	"""``fn`` run by finance (Administrator), then back to whoever was acting."""
	user = frappe.session.user
	frappe.set_user("Administrator")  # nosemgrep: frappe-setuser -- finance at the payment screen
	try:
		return fn()
	finally:
		frappe.set_user(user)  # nosemgrep: frappe-setuser -- back to the caller


def at_both(minutes: int):
	"""The guest-change and the payments clocks ``minutes`` from now."""
	later = add_to_date(now_datetime(), minutes=minutes)
	return mock.patch("kamra.tex.services.guest_changes.now_datetime", return_value=later), \
		mock.patch("kamra.tex.payments.service.now_datetime", return_value=later)


class TestThirdReview(GuestMoneyCase):
	"""Third review: an outcome is recorded only once the refund's answer cannot come any more,
	an answer after a recorded outcome is a conflict (never a failure), a run keeps its hold
	when a refund fails early, what was refunded is counted from the refunds made, and a
	transient error never stops the scheduler."""

	def shortened(self, session: str):
		lower_price_policy("Refund automatically")
		b = self.fully_paid(session)
		deposit, balance = charges(b["booking"])
		with settle_queued():
			out = self.accept(b, self.propose(b, (6, 12)))          # 267.50 back, from the balance first
		return b, out["request"], deposit, balance

	def test_staff_cannot_record_an_outcome_while_its_gateway_call_runs(self):
		b, name, _deposit, balance = self.shortened("gcm3-race")
		from kamra.tex.services import guest_changes

		seen: dict = {}

		def staff_try():
			row = refund_row(balance)
			seen["view"] = as_staff(lambda: pay_api.transaction(name=row))
			try:
				as_staff(lambda: pay_api.finish_refund(refund=row, outcome="Failed", reason="not at the gateway yet"))
			except frappe.ValidationError as e:
				seen["refused"] = str(e)

		calls, gateway = gateway_during(staff_try)
		with gateway:
			guest_changes.settle(name)
		self.assertRegex(seen.get("refused", ""), "may still come")
		self.assertEqual((seen["view"]["status"], seen["view"]["can_finish"]), ("Pending", False))
		self.assertRegex(seen["view"]["finish_blocked"], "may still come")
		self.assertEqual(calls, [(f"MOCK-{balance}", D("267.50"))])
		self.assertEqual(refunds(b["booking"]), [(balance, D("267.50"), "Succeeded")])
		req = frappe.get_doc(DT, name)
		self.assertEqual((D(req.refunded_amount), req.staff_open, req.settle_pending), (D("267.50"), 0, 0))

	def test_a_stuck_refund_is_closed_only_once_its_run_let_go(self):
		b, name, _deposit, balance = self.shortened("gcm3-lease")
		from kamra.tex.services import guest_changes

		_calls, gateway = crashing_gateway()
		with gateway, self.assertRaises(Crash):
			guest_changes.settle(name)                          # the worker dies during the call
		row = refund_row(balance)

		def finish():
			return as_staff(lambda: pay_api.finish_refund(refund=row, outcome="Succeeded", reason="seen at the gateway"))

		clock, pay_clock = at_both(pay.REFUND_STUCK_MINUTES + 1)
		with clock, pay_clock:                                  # old, but its run still holds the refunds
			self.assertFalse(as_staff(lambda: pay_api.transaction(name=row))["can_finish"])
			with self.assertRaisesRegex(frappe.ValidationError, "still waiting"):
				finish()
		clock, pay_clock = at_both(guest_changes.SETTLE_LEASE_MINUTES + 1)
		with clock, pay_clock:                                  # the run's hold lapsed: nothing can answer now
			self.assertTrue(as_staff(lambda: pay_api.transaction(name=row))["can_finish"])
			finish()
		self.assertEqual(refunds(b["booking"]), [(balance, D("267.50"), "Succeeded")])
		req = frappe.get_doc(DT, name)
		self.assertEqual((D(req.refunded_amount), req.settle_pending), (D("267.50"), 0))

	def test_a_gateway_answer_after_a_recorded_outcome_is_a_conflict_never_a_failure(self):
		_b, name, _deposit, balance = self.shortened("gcm3-conflict")
		from kamra.tex.services import guest_changes

		def recorded():
			# an outcome recorded while the call ran (another transaction committed it)
			frappe.db.set_value(TXN, refund_row(balance), {"status": "Failed", "raw_status": "VERIFIED BY STAFF"},
			                    update_modified=False)

		calls, gateway = gateway_during(recorded)
		with gateway:
			guest_changes.settle(name)
		row = refund_row(balance)
		self.assertEqual(calls, [(f"MOCK-{balance}", D("267.50"))])   # never refunded again from the deposit
		self.assertEqual(frappe.db.get_value(TXN, row, "status"), "Failed")   # the record is not overwritten
		self.assertEqual(audits("payment.refund_outcome_conflict", row), 1)
		req = frappe.get_doc(DT, name)
		# the change stops and names the refund; no money moves to staff until they record what the
		# gateway actually did (re-review 4: before, what the books said was owed went to staff)
		self.assertEqual((req.settle_pending, req.staff_open, req.staff_reason, req.unknown_refund, D(req.staff_amount)),
		                 (0, 1, "Verify refund at gateway", row, D("0")))
		from kamra.tex.ops import status as system_status

		check = next(c for c in as_staff(lambda: system_status.collect(properties=[fx.PROPERTY]))
		             if c["key"] == "payments.callbacks")
		self.assertIn(("refund_conflict", {"count": 1}), [(i["reason"], i["params"]) for i in check["issues"]])

	def test_an_outcome_recorded_during_the_call_is_counted_once(self):
		b, name, _deposit, balance = self.shortened("gcm3-twice")
		from kamra.tex.services import guest_changes

		def verified():
			# a verification that got past the checks (a clock skew): the gateway then says the same
			with mock.patch.object(guest_changes, "finish_block", return_value=None, create=True), \
					mock.patch.object(pay, "stuck", return_value=True):
				as_staff(lambda: guest_changes.verify_refund(refund_row(balance), outcome="Succeeded",
				                                             reason="seen at the gateway"))

		calls, gateway = gateway_during(verified)
		with gateway:
			guest_changes.settle(name)
		self.assertEqual(len(calls), 1)
		self.assertEqual(refunds(b["booking"]), [(balance, D("267.50"), "Succeeded")])
		self.assertEqual(money(b["booking"]), (D("575.00"), D("575.00"), D("0.00")))
		req = frappe.get_doc(DT, name)
		self.assertEqual((D(req.refunded_amount), req.staff_open, req.settle_pending), (D("267.50"), 0, 0))
		self.assertEqual(audits("payment.refund_outcome_conflict", refund_row(balance)), 0)

	def test_after_the_gateway_answers_the_booking_is_locked_first(self):
		import re

		_b, name, _deposit, balance = self.shortened("gcm3-order")
		from kamra.tex.services import guest_changes

		after: list[str] = []
		on = {"after": False}
		real = frappe.db.sql

		def sql(query, *args, **kwargs):
			q = str(query)
			if on["after"] and re.search(r"FOR UPDATE", q, re.I):
				m = re.search(r"FROM\s+`(tab[^`]+)`", q)
				after.append(f"{m.group(1) if m else '?'} {args!r} {kwargs!r}")
			return real(query, *args, **kwargs)

		_calls, gateway = gateway_during(lambda: on.update(after=True))
		with gateway, mock.patch.object(frappe.db, "sql", side_effect=sql):
			guest_changes.settle(name)
		row = refund_row(balance)
		first = [next(i for i, a in enumerate(after) if cond(a)) for cond in (
			lambda a: a.startswith("tabTEX Booking"),
			lambda a: a.startswith("tabTEX Guest Change Request"),
			lambda a: a.startswith("tabTEX Payment Transaction") and row in a,
			lambda a: a.startswith("tabTEX Payment Transaction") and balance in a)]
		self.assertEqual(first, sorted(first), after)      # the booking, the request, the refund, its charge

	def test_a_refund_that_fails_before_it_is_on_record_goes_to_staff_not_into_a_loop(self):
		b, name, _deposit, _balance = self.shortened("gcm3-early")
		from kamra.tex.services import guest_changes

		committed: dict = {}

		def commit():                       # what a commit makes durable
			committed.update(frappe.db.get_value(DT, name, ["settle_claim", "settle_claimed_until"], as_dict=True))

		real_undo = guest_changes._undo

		def undo(savepoint):                # production: all uncommitted work goes, the run's hold with it
			real_undo(savepoint)
			frappe.db.set_value(DT, name, {"settle_claim": committed.get("settle_claim"),
			                               "settle_claimed_until": committed.get("settle_claimed_until")},
			                    update_modified=False)

		with mock.patch.object(guest_changes, "_commit", side_effect=commit), \
				mock.patch.object(guest_changes, "_undo", side_effect=undo), \
				mock.patch.object(pay, "provider_for", side_effect=frappe.QueryTimeoutError("Lock wait timeout")):
			out = guest_changes.settle(name)
		self.assertFalse(out.get("busy"))
		req = frappe.get_doc(DT, name)
		self.assertEqual((req.settle_pending, req.staff_open, req.staff_reason, D(req.staff_amount)),
		                 (0, 1, "Refund by staff", D("267.50")))
		self.assertEqual(refunds(b["booking"]), [])

	def test_a_refund_made_by_a_run_that_lost_its_hold_is_still_counted(self):
		b, name, _deposit, balance = self.shortened("gcm3-lost-hold")
		from kamra.tex.services import guest_changes

		real_relock = guest_changes._relock
		state = {"answered": False, "lost": False}

		def relock(req, token):
			if state["answered"] and not state["lost"]:
				state["lost"] = True
				return None                 # its hold lapsed during the call: another run took over
			return real_relock(req, token)

		_calls, gateway = gateway_during(lambda: state.update(answered=True))
		with gateway, mock.patch.object(guest_changes, "_relock", side_effect=relock):
			self.assertTrue(guest_changes.settle(name).get("busy"))
		self.assertEqual(refunds(b["booking"]), [(balance, D("267.50"), "Succeeded")])
		# meanwhile the hotel lengthens the stay, the guest pays the difference by card (now the
		# newest charge) and the hotel shortens it back: the booking holds money over its total
		# again, and a new plan would start from that newer charge (a new refund key)
		res = b["rooms"][0]["reservation"]
		for check_out in ((6, 13), None, (6, 12)):
			if check_out is None:
				paid(public.pay_booking(token=b["manage_token"]))
				continue
			prop = as_staff(lambda co=check_out: modification.propose(res, {"check_out": str(fx.d(*co))}))
			as_staff(lambda p=prop: modification.apply(p["proposal_token"], reason="guest phoned"))
		self.assertEqual(money(b["booking"])[:2], (D("575.00"), D("842.50")))
		frappe.db.set_value(DT, name, {"settle_claim": None, "settle_claimed_until": None}, update_modified=False)
		more, gateway = gateway_calls()
		with gateway:
			guest_changes.settle(name)                      # the run that took over
		self.assertEqual(more, [])                          # the refund made is counted: nothing twice
		req = frappe.get_doc(DT, name)
		self.assertEqual((D(req.refunded_amount), req.settle_pending), (D("267.50"), 0))

	def test_a_transient_error_while_failing_a_change_does_not_stop_the_scheduler(self):
		from kamra.tex.services import guest_changes

		outs = []
		for session in ("gcm3-sweep-a", "gcm3-sweep-b"):
			b = self.deposit_paid(session)
			out = self.accept(b, self.propose(b, (6, 14)))
			with mock.patch.object(guest_changes, "queue_apply"):
				paid(out["payment"])                        # paid; the jobs that apply them are lost
			outs.append(out)
		real_apply = modification.apply
		n = {"calls": 0}

		def apply(*args, **kwargs):
			n["calls"] += 1
			if n["calls"] == 1:
				raise KeyError("snapshot")                  # the first change breaks …
			return real_apply(*args, **kwargs)

		with at(guest_changes.APPLY_RETRY_MINUTES + 3), \
				mock.patch("kamra.tex.services.modification.apply", side_effect=apply), \
				mock.patch.object(guest_changes, "_fail", side_effect=frappe.QueryTimeoutError("Lock wait timeout")):
			result = guest_changes.expire_awaiting()        # … and marking it failed waits on a lock
		self.assertEqual(result["applied"], 1)
		self.assertEqual(sorted(frappe.db.get_value(DT, o["request"], "status") for o in outs),
		                 ["Applied", "Awaiting Payment"])


class TestRefundedOutsideTex(GuestMoneyCase):
	"""G-93: money the hotel refunds outside TEX (cash, a bank transfer) is recorded on the
	booking, so it is no longer counted as paid nor offered to the guest as credit."""

	def setUp(self):
		super().setUp()
		self.agent = fx.ensure_user("gcm-agent@example.com", ["Call Center Agent"])
		fx.ensure("TEX Access Grant", {"user": self.agent, "property": fx.PROPERTY},
		          {"user": self.agent, "scope_level": "Hotel", "property": fx.PROPERTY,
		           "permission_profile": "Reservations Agent"})
		scope.clear_cache()

	def test_closing_money_refunded_at_the_desk_records_the_refund(self):
		lower_price_policy("Refund automatically")
		b = guest_books(session="gcm3-outside")
		as_staff(lambda: pay.record_manual(booking=b["booking"], amount="842.50", method="Cash",
		                                   reference="desk receipt 9", idempotency_key="gcm3-out-1"))
		out = self.accept(b, self.propose(b, (6, 12)))            # 267.50 the hotel refunds
		req = frappe.get_doc(DT, out["request"])
		self.assertEqual((req.staff_open, req.staff_reason), (1, "Refund by staff"))
		frappe.set_user("Administrator")  # nosemgrep: frappe-setuser -- finance refunded it in cash
		with self.assertRaisesRegex(frappe.ValidationError, "refunded to the guest outside TEX or kept"):
			crs_api.resolve_guest_change(request=req.name, action="close", reason="done")
		done = crs_api.resolve_guest_change(request=req.name, action="close", reason="refunded in cash at the desk",
		                                    staff_money="Refunded outside TEX")
		self.assertEqual(done["staff_open"], False)
		self.assertEqual(money(b["booking"]), (D("575.00"), D("575.00"), D("0.00")))
		rows = frappe.get_all(TXN, filters={"txn_type": "Refund", "booking": b["booking"]},
		                      fields=["status", "amount", "method", "raw_status"])
		self.assertEqual([(r.status, D(r.amount), r.method, r.raw_status) for r in rows],
		                 [("Succeeded", D("267.50"), "Manual", "REFUNDED OUTSIDE TEX")])
		view = public.booking_status(token=b["manage_token"])
		self.assertEqual((view["credit"], view["refund_due"]), ("0.00", "0.00"))

	def test_money_kept_on_the_booking_stays_its_credit(self):
		lower_price_policy("Refund automatically")
		b = guest_books(session="gcm3-kept")
		as_staff(lambda: pay.record_manual(booking=b["booking"], amount="842.50", method="Cash",
		                                   reference="desk receipt 10", idempotency_key="gcm3-kept-1"))
		out = self.accept(b, self.propose(b, (6, 12)))
		frappe.set_user("Administrator")  # nosemgrep: frappe-setuser -- the guest keeps it for their next stay
		crs_api.resolve_guest_change(request=out["request"], action="close", reason="guest keeps it as credit",
		                             staff_money="Kept on the booking")
		self.assertEqual(money(b["booking"])[1], D("842.50"))
		self.assertEqual(public.booking_status(token=b["manage_token"])["credit"], "267.50")

	def test_staff_record_a_refund_made_outside_tex_from_the_payment_screen(self):
		b = self.fully_paid("gcm3-outside-pay")
		_deposit, balance = charges(b["booking"])
		frappe.set_user(self.agent)  # nosemgrep: frappe-setuser -- a reservations agent (no payment.refund)
		with self.assertRaises(frappe.PermissionError):
			pay_api.refund_outside(transaction=balance, amount="50.00", reason="cash back", reference="desk 3",
			                       idempotency_key="gcm3-po-1", booking=b["booking"])
		frappe.set_user("Administrator")  # nosemgrep: frappe-setuser -- finance
		with self.assertRaisesRegex(frappe.ValidationError, "At most"):
			pay_api.refund_outside(transaction=balance, amount="600.00", reason="too much", reference="desk 3",
			                       idempotency_key="gcm3-po-2", booking=b["booking"])
		first = pay_api.refund_outside(transaction=balance, amount="50.00", reason="cash back", reference="desk 3",
		                               idempotency_key="gcm3-po-1", booking=b["booking"])
		again = pay_api.refund_outside(transaction=balance, amount="50.00", reason="cash back", reference="desk 3",
		                               idempotency_key="gcm3-po-1", booking=b["booking"])
		self.assertEqual((again["refund"], again["replay"]), (first["refund"], True))
		self.assertEqual(money(b["booking"])[1], D("792.50"))
		self.assertEqual(audits("payment.refund_outside", first["refund"]), 1)
		self.assertEqual(pay_api.transaction(name=balance)["refundable"], "539.75")


# ─── fourth review (G-45 re-review 4) ──────────────────────────────────


def outside_refunds(booking: str) -> list[tuple[str, D]]:
	"""Refunds recorded as made outside TEX, of the payments of ``booking``: [(payment, amount)]."""
	rows = frappe.get_all(TXN, filters={"txn_type": "Refund", "raw_status": "REFUNDED OUTSIDE TEX",
	                                    "parent_transaction": ("in", charges(booking) or [""])},
	                      fields=["parent_transaction", "amount"], order_by="creation asc")
	return [(r.parent_transaction, D(r.amount)) for r in rows]


def limit_reads(run, charge: str) -> list[str]:
	"""The reads of refunds, allocations and idempotency keys ``run`` makes after it locked
	``charge``: they decide what may still be refunded or moved."""
	import re

	reads: list[str] = []
	on = {"locked": False}
	real = frappe.db.sql

	def sql(query, *args, **kwargs):
		q = " ".join(str(query).split())
		values = f"{args!r} {kwargs!r}"
		if not on["locked"] and re.search(r"FROM `tabTEX Payment Transaction`.*FOR UPDATE", q) and charge in values:
			on["locked"] = True
		elif on["locked"] and q.upper().startswith("SELECT") and (
				"parent_transaction" in q or "`tabTEX Payment Allocation`" in q or "idempotency_key" in q):
			reads.append(q)
		return real(query, *args, **kwargs)

	with mock.patch.object(frappe.db, "sql", side_effect=sql):
		run()
	return reads


class TestFourthReview(GuestMoneyCase):
	"""Fourth review: money given back outside TEX is recorded against the payments it came from,
	limits are read with locking reads, money being refunded cannot move, a conflict stops every
	run and staff record the truth, p28 names the refunds made, one lock order."""

	def close_outside(self, name: str):
		frappe.set_user("Administrator")  # nosemgrep: frappe-setuser -- finance refunded it at the desk
		return crs_api.resolve_guest_change(request=name, action="close", reason="refunded in cash at the desk",
		                                    staff_money="Refunded outside TEX")

	def test_a_change_payment_returned_at_the_desk_is_recorded_on_a_partly_paid_booking(self):
		b = self.deposit_paid("gcm4-deposit")
		res = b["rooms"][0]["reservation"]
		out = self.accept(b, self.propose(b, (6, 14)))
		txn = out["payment"]["transaction"]
		prop = as_staff(lambda: modification.propose(res, {"check_out": str(fx.d(6, 12))}))
		as_staff(lambda: modification.apply(prop["proposal_token"], reason="guest phoned"))   # it cannot apply
		_calls, gateway = gateway_calls({txn: "Failed"})
		with gateway:
			paid(out["payment"])                           # the change fails; the gateway refuses its refund
		req = frappe.get_doc(DT, out["request"])
		self.assertEqual((req.status, req.staff_open, req.staff_reason, D(req.staff_amount)),
		                 ("Failed", 1, "Refund by staff", D("80.25")))
		self.assertEqual(money(b["booking"])[:2], (D("575.00"), D("333.00")))   # still counted as paid
		self.assertFalse(self.close_outside(req.name)["staff_open"])
		self.assertEqual(outside_refunds(b["booking"]), [(txn, D("80.25"))])
		self.assertEqual(money(b["booking"])[1], D("252.75"))

	def test_a_late_change_payment_returned_at_the_desk_is_recorded(self):
		b = self.deposit_paid("gcm4-late")
		out = self.accept(b, self.propose(b, (6, 14)))
		txn = out["payment"]["transaction"]
		from kamra.tex.services import guest_changes

		with at(120):
			guest_changes.expire_awaiting()                # its payment did not come in time
		_calls, gateway = gateway_calls({txn: "Failed"})
		with gateway:
			paid(out["payment"])                           # the old checkout is paid after all
		req = frappe.get_doc(DT, out["request"])
		self.assertEqual((req.status, req.staff_open, D(req.staff_amount)), ("Expired", 1, D("80.25")))
		self.close_outside(req.name)
		self.assertEqual(outside_refunds(b["booking"]), [(txn, D("80.25"))])
		self.assertEqual(money(b["booking"])[1], D("252.75"))

	def test_a_second_payment_of_an_applied_change_returned_at_the_desk_is_recorded(self):
		b = self.deposit_paid("gcm4-second")
		up = self.propose(b, (6, 14))
		first = self.accept(b, up)
		declined(first["payment"])
		paid(self.accept(b, up)["payment"])               # the retry pays it: applied
		txn = first["payment"]["transaction"]
		_calls, gateway = gateway_calls({txn: "Failed"})
		with gateway:
			paid(first["payment"])                         # the declined tab is paid after all
		self.assertEqual(money(b["booking"])[:2], (D("1110.00"), D("413.25")))
		self.close_outside(first["request"])
		self.assertEqual(outside_refunds(b["booking"]), [(txn, D("80.25"))])
		self.assertEqual(money(b["booking"])[1], D("333.00"))

	def test_money_refunded_outside_tex_comes_off_the_booking_named(self):
		b = self.fully_paid("gcm4-unallocated")
		_deposit, balance = charges(b["booking"])
		as_staff(lambda: pay.release(balance, booking=b["booking"], amount="100.00", reason="belongs elsewhere"))
		self.assertEqual(money(b["booking"])[1], D("742.50"))
		out = as_staff(lambda: pay.refund_outside(balance, amount="50.00", reason="cash back", reference="desk 4",
		                                          idempotency_key="gcm4-u1", booking=b["booking"]))
		self.assertEqual(out["from_booking"], "50.00")    # the booking's money, not the unallocated 100
		self.assertEqual(money(b["booking"])[1], D("692.50"))
		self.assertEqual(as_staff(lambda: pay_api.transaction(name=balance))["unallocated"], "100.00")

	def test_limits_are_read_with_locking_reads_once_the_payment_is_locked(self):
		b = self.fully_paid("gcm4-reads")
		_deposit, balance = charges(b["booking"])
		runs = {"outside": lambda: pay.refund_outside(balance, amount="10.00", reason="cash", reference="desk 5",
		                                              idempotency_key="gcm4-r1", booking=b["booking"]),
		        "gateway": lambda: pay.refund(balance, amount="10.00", reason="goodwill", idempotency_key="gcm4-r2",
		                                      booking=b["booking"], durable=True),
		        "release": lambda: pay.release(balance, booking=b["booking"], amount="10.00", reason="move"),
		        "allocate": lambda: pay.allocate(balance, booking=b["booking"], amount="10.00", reason="back")}
		for what, run in runs.items():
			with self.subTest(what):
				reads = as_staff(lambda r=run: limit_reads(r, balance))
				self.assertTrue(reads, what)
				for q in reads:
					self.assertRegex(q, "LOCK IN SHARE MODE|FOR UPDATE", f"{what}: {q}")

	def test_money_being_refunded_cannot_be_moved_to_another_booking(self):
		b = self.fully_paid("gcm4-move")
		other = self.deposit_paid("gcm4-move-2")
		_deposit, balance = charges(b["booking"])
		seen: dict = {}

		def move():
			try:
				as_staff(lambda: pay.transfer(balance, from_booking=b["booking"], to_booking=other["booking"],
				                              amount="589.75", reason="wrong booking"))
			except frappe.ValidationError as e:
				seen["refused"] = str(e)

		_calls, gateway = gateway_during(move)
		with gateway:
			as_staff(lambda: pay_api.refund(transaction=balance, amount="100.00", reason="goodwill",
			                                idempotency_key="gcm4-m1", booking=b["booking"]))
		self.assertIn("489.75", seen.get("refused", ""))     # only what no refund is taking can move
		self.assertEqual(money(b["booking"])[1], D("742.50"))
		self.assertEqual(money(other["booking"])[1], D("252.75"))

	def test_a_conflict_stops_every_run_and_names_its_refund_until_staff_record_the_truth(self):
		lower_price_policy("Refund automatically")
		b = self.fully_paid("gcm4-conflict")
		_deposit, balance = charges(b["booking"])
		from kamra.tex.payments.providers.base import Outcome
		from kamra.tex.payments.providers.simple import MockProvider
		from kamra.tex.services import guest_changes

		with settle_queued():
			name = self.accept(b, self.propose(b, (6, 12)))["request"]
		calls: list[str] = []

		def refund(self_, provider_ref, amount, currency, **_kw):
			calls.append(provider_ref)
			if len(calls) == 1:
				# the run is paused far past its hold; staff find nothing at the gateway yet and record
				# "not refunded": TEX runs the refunds again (the deposit's refund is declined) …
				clock, pay_clock = at_both(guest_changes.SETTLE_LEASE_MINUTES + 1)
				with clock, pay_clock:
					as_staff(lambda: pay_api.finish_refund(refund=refund_row(balance), outcome="Failed",
					                                       reason="nothing at the gateway yet"))
				# … and then the gateway answers the first call: it did refund
				return Outcome(status="Succeeded", provider_ref=f"{provider_ref}-R", amount=amount, currency=currency,
				               raw_status="REFUNDED")
			return Outcome(status="Failed", error_code="DECLINED", error_message="refund declined")

		with mock.patch.object(MockProvider, "refund", refund):
			guest_changes.settle(name)
		row = refund_row(balance)
		self.assertEqual((frappe.db.get_value(TXN, row, "status"), audits("payment.refund_outcome_conflict", row)),
		                 ("Failed", 1))
		req = frappe.get_doc(DT, name)
		self.assertEqual((req.settle_pending, req.staff_open, req.staff_reason, req.unknown_refund),
		                 (0, 1, "Verify refund at gateway", row))
		more, gateway = gateway_calls()
		with gateway:
			guest_changes.settle(name)
		self.assertEqual(more, [])                          # no run refunds anything more
		frappe.set_user("Administrator")  # nosemgrep: frappe-setuser -- finance checked the gateway again
		pay_api.resolve_refund_conflict(refund=row, outcome="Succeeded", reason="the gateway shows it refunded")
		self.assertEqual(frappe.db.get_value(TXN, row, "status"), "Succeeded")
		self.assertEqual(money(b["booking"]), (D("575.00"), D("575.00"), D("0.00")))
		self.assertEqual(audits("payment.refund_conflict_resolved", row), 1)
		req.reload()
		self.assertEqual((D(req.refunded_amount), req.staff_open, req.settle_pending, req.unknown_refund),
		                 (D("267.50"), 0, 0, None))
		from kamra.tex.ops import status as system_status

		check = next(c for c in system_status.collect(properties=[fx.PROPERTY]) if c["key"] == "payments.callbacks")
		self.assertNotIn("refund_conflict", [i["reason"] for i in check["issues"]])

	def test_p28_names_the_refunds_each_change_made(self):
		lower_price_policy("Refund automatically")
		b = self.fully_paid("gcm4-p28")
		_deposit, balance = charges(b["booking"])
		name = self.accept(b, self.propose(b, (6, 12)))["request"]
		row = refund_row(balance)
		# money of the same change the hotel gave back at the desk is not one of its card refunds
		as_staff(lambda: pay.refund_outside(balance, amount="5.00", reason=f"Guest change {name}: cash",
		                                    reference="desk 6", idempotency_key="gcm4-p28-o", booking=b["booking"]))
		frappe.db.set_value(DT, name, "refund_rows", None, update_modified=False)   # as before the field existed
		from kamra.patches.tex import p28_guest_change_refund_rows as p28

		p28.execute()
		p28.execute()                                       # idempotent
		self.assertEqual(frappe.db.get_value(DT, name, "refund_rows"), row)

	def test_a_refund_made_outside_tex_locks_the_booking_before_the_payment(self):
		b = self.fully_paid("gcm4-order")
		_deposit, balance = charges(b["booking"])
		seen = as_staff(lambda: locks_during(lambda: pay.refund_outside(
			balance, amount="10.00", reason="cash", reference="desk 7", idempotency_key="gcm4-o1")))
		self.assertLess(seen.index("tabTEX Booking"), seen.index("tabTEX Payment Transaction"), seen)

	def test_the_staff_refund_endpoint_runs_a_deadlock_victim_again(self):
		b = self.fully_paid("gcm4-deadlock")
		_deposit, balance = charges(b["booking"])
		answers = [frappe.QueryDeadlockError("Deadlock found"), {"refund": "PTX-X", "status": "Succeeded"}]
		with mock.patch.object(pay, "refund", side_effect=answers), mock.patch.object(frappe.db, "rollback"):
			out = as_staff(lambda: pay_api.refund(transaction=balance, amount="10.00", reason="goodwill",
			                                      idempotency_key="gcm4-d1", booking=b["booking"]))
		self.assertEqual(out, {"refund": "PTX-X", "status": "Succeeded"})


class TestBasketClawbackMoney(GuestMoneyCase):
	"""G-84 review H1: a guest's change that takes a paid booking below a promotion's minimum
	basket carries the discount the other room keeps, so the refund shrinks by it."""

	def test_the_refund_of_a_shortened_room_keeps_the_other_rooms_discount(self):
		lower_price_policy("Refund automatically")
		frappe.set_user("Administrator")  # nosemgrep: frappe-setuser -- revenue manager sets up the code
		doc = policy_api.save_record("TEX Promotion", {
			"promotion_name": "Code BIG", "property": fx.PROPERTY, "trigger": "Code", "code": "BIG",
			"value_type": "PERCENT", "value": 10, "applies_to": "ACCOMMODATION", "currency": "EUR", "min_basket": 1100})
		policy_api.activate("TEX Promotion", doc["name"], at=str(add_to_date(now_datetime(), minutes=-1)))
		quotes, _offer = two_rooms_quoted_together("gcm-basket", code="BIG")        # 722.25 + 288.90
		b = public.book(site=SLUG, quote_ids=[q["quote_id"] for q in quotes], guest=GUEST, payment_method="Card",
		                session_id="gcm-basket", idempotency_key="idem-gcm-basket")
		paid(b["payment"])
		paid(public.pay_booking(token=b["manage_token"]))
		self.assertEqual(money(b["booking"])[1], D("1011.15"))
		# room 1 shortened: 535.00 + 321.00 = 856.00 is below 1 100, so room 1 pays room 2's 32.10
		down = self.propose(b, (6, 12))
		self.assertEqual((down["new_total"], down["basket_clawback"]["amount"]), ("567.10", "32.10"))
		self.assertEqual((down["settlement"]["kind"], down["settlement"]["amount"]), ("refund", "155.15"))
		out = self.accept(b, down)
		self.assertEqual((out["status"], out["settlement"]["amount"]), ("applied", "155.15"))
		self.assertEqual([r[1] for r in refunds(b["booking"])], [D("155.15")])
		self.assertEqual(money(b["booking"]), (D("856.00"), D("856.00"), D("0.00")))
