"""Guest changes settle their money (G-45, ADR-044).

The fixture booking: FLEX, 3 nights (6/10–6/13), 842.50 with a 30 % deposit (252.75). One more
LOW night makes it 1110.00 (deposit 333.00), one night less 575.00.

A higher price is paid before the change applies (the gateway's confirmation applies it); pay
at hotel and bookings already covered apply at once and say what is due later. A lower price
follows the hotel's policy: staff approval, an automatic refund of the true overpayment from
the charges holding it, or a credit kept on the booking."""

from unittest import mock

import frappe
from frappe.utils import add_to_date, now_datetime

from kamra.tex.api import crs as crs_api
from kamra.tex.api import public
from kamra.tex.money import D
from kamra.tex.payments import service as pay
from kamra.tex.security import scope
from kamra.tex.services import modification
from kamra.tex.tests.integration import fixtures as fx
from kamra.tex.tests.integration.test_commercial_flows import guest_books, setup_site_and_payments
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
		self.assertEqual((out["status"], out["credit"]), ("applied", "267.50"))    # held until refunded
		self.assertEqual(frappe.db.get_value(DT, out["request"], "settle_pending"), 1)
		self.assertEqual(refunds(b["booking"]), [])
		later = add_to_date(now_datetime(), minutes=guest_changes.SETTLE_RETRY_MINUTES + 1)
		with mock.patch("kamra.tex.services.guest_changes.now_datetime", return_value=later):
			self.assertEqual(guest_changes.expire_awaiting(), {"expired": 0, "settled": 1})
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
		self.assertEqual((down["settlement"]["kind"], down["settlement"]["amount"]), ("refund", "267.50"))
		out = self.accept(b, down)
		self.assertEqual((out["status"], out["settlement"]["kind"], out["credit"]), ("applied", "staff", "267.50"))
		req = frappe.get_doc(DT, out["request"])
		self.assertEqual((req.settlement, D(req.refunded_amount), req.settle_pending), ("Staff", D("0"), 0))
		self.assertIn("267.50", req.error)
		self.assertEqual(refunds(b["booking"]), [])
		self.assertTrue(frappe.db.exists("TEX Audit Event", {"action": "guest_change.refund_incomplete",
		                                                     "reference_name": req.name}))
		self.assertEqual(frappe.db.get_value("Reservation", b["rooms"][0]["reservation"],
		                                     "tex_guest_change_pending"), 1)
		frappe.set_user("Administrator")  # nosemgrep: frappe-setuser -- finance refunds it at the desk
		listed = crs_api.guest_change_requests(property=fx.PROPERTY, needs_staff=1)
		self.assertEqual([r["name"] for r in listed], [req.name])
		closed = crs_api.resolve_guest_change(request=req.name, action="close", reason="refunded in cash")
		self.assertEqual((closed["resolved_by"], closed["needs_staff"]), ("Administrator", False))
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
