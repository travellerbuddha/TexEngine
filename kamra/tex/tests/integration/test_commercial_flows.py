"""TEX flows around a booking: guest booking API with the sandbox gateway, payment
idempotency, refunds, transfers, payment links, guest self-service, CRM consent,
loyalty, abandoned-booking detection, reports and tenant isolation."""

import json
from datetime import timedelta
from unittest import mock

import frappe
from frappe.utils import add_to_date, get_datetime, now_datetime

from kamra.tex.api import crm as crm_api
from kamra.tex.api import payments as pay_api
from kamra.tex.api import policies as policy_api
from kamra.tex.api import public, ui_crs
from kamra.tex.commercial import context, contracts
from kamra.tex.crm import loyalty
from kamra.tex.crm import service as crm
from kamra.tex.money import D
from kamra.tex.payments import service as pay
from kamra.tex.payments.providers.base import ProviderError
from kamra.tex.pricing import engine, policy_money, serialize
from kamra.tex.pricing.model import ChildSpec, StayRequest, Unsellable
from kamra.tex.reports import service as reports
from kamra.tex.security import scope
from kamra.tex.services import booking, modification, quoting
from kamra.tex.tests.integration import fixtures as fx
from kamra.tex.tests.integration.test_critical_journey import TexTestCase, pick

SLUG = "tex-test-resort"
GUEST = {"first_name": "Lena", "last_name": "Kraus", "email": "lena@example.com", "country": "Germany"}


OTHER_SELLING = "TEX Search Other Hotel"


def sellable_other_hotel(f: dict) -> str:
	"""A second hotel of the test hotel's group, live in TEX, with one room type, one rate plan and a
	published DE contract: what a search over several hotels prices next to the test hotel."""
	from kamra.tex.commercial import contracts

	if not frappe.db.exists("Property", OTHER_SELLING):
		frappe.get_doc({"doctype": "Property", "property_name": OTHER_SELLING, "city": "Side", "country": "Turkey",
		                "currency": "EUR", "tex_hotel_group": f["group"], "tex_tax_profile": "Custom",
		                "minimum_nights": 1}).insert(ignore_permissions=True)
		# sold through TEX, as the test hotel (base_setup)
		frappe.db.set_value("Property", OTHER_SELLING, "tex_live_from", "2020-01-01 00:00:00")
	std = fx.ensure("Room Type", {"property": OTHER_SELLING, "room_type_code": "STD"},
	                {"property": OTHER_SELLING, "room_type_code": "STD", "room_type_name": "Standard Room",
	                 "base_price": 90, "adults_capacity": 3, "children_capacity": 2, "max_total_occupants": 5,
	                 "base_occupancy": 2})
	for i in range(4):
		fx.ensure("Room", {"property": OTHER_SELLING, "room_number": f"O-STD{i + 1}"},
		          {"property": OTHER_SELLING, "room_number": f"O-STD{i + 1}", "room_type": std})
	flex = fx.ensure("Rate Plan", {"property": OTHER_SELLING, "code": "FLEX"},
	                 {"property": OTHER_SELLING, "code": "FLEX", "rate_plan_name": "Flexible",
	                  "modifier_type": "Percent", "modifier_value": 0, "tex_refundable": 1})
	contract = frappe.get_doc({
		"doctype": "TEX Contract", "property": OTHER_SELLING, "contract_code": "OTHER-DE", "contract_name": "Other DE",
		"market": "DE", "contract_currency": "EUR", "pricing_basis": "PERSON", "status": "Draft",
		"sale_from": add_to_date(now_datetime(), days=-30), "sale_to": fx.STAY_TO, "stay_from": fx.STAY_FROM,
		"stay_to": fx.STAY_TO}).insert(ignore_permissions=True)
	version = frappe.get_doc({
		"doctype": "TEX Contract Version", "contract": contract.name, "prices_include_tax": 0,
		"rooms": [{"room_type": std, "is_base": 1}],
		"periods": [{"period_code": "ALL", "period_name": "All", "start_date": fx.STAY_FROM, "end_date": fx.STAY_TO}],
		"period_rates": [{"room_type": std, "period_code": "ALL", "op": "ABSOLUTE", "value": 90}],
		"age_bands": fx.default_age_bands(), "occupancy_rules": fx.default_occupancy_rules(),
		"boards": [{"board": "AI", "is_base": 1}], "rate_plans": [{"rate_plan": flex, "refundable": 1}],
	}).insert(ignore_permissions=True)
	contracts.publish(version.name)
	return OTHER_SELLING


def setup_site_and_payments(f: dict, **contract) -> dict:
	fx.create_contract(f, code="PAY", **contract)
	fx.create_markup("DE", 7)
	acc = fx.ensure("TEX Payment Provider Account", {"property": fx.PROPERTY, "provider": "Mock"},
	                {"label": "Sandbox gateway", "property": fx.PROPERTY, "provider": "Mock",
	                 "environment": "Sandbox", "enabled": 1, "currencies": "EUR"})
	fx.ensure("TEX Payment Method Rule", {"property": fx.PROPERTY, "method": "Card"},
	          {"property": fx.PROPERTY, "method": "Card", "provider_account": acc, "priority": 10})
	# the hotel sells pay at the hotel too (O-15: a hotel with a rule is bound by its rules; a method with no rule
	# is not offered). No account: nothing is charged
	fx.ensure("TEX Payment Method Rule", {"property": fx.PROPERTY, "method": "Pay at Hotel"},
	          {"property": fx.PROPERTY, "method": "Pay at Hotel", "priority": 5})
	if not frappe.db.exists("TEX Booking Site", SLUG):
		frappe.get_doc({"doctype": "TEX Booking Site", "site_name": "TEX Test Resort", "site_slug": SLUG,
		                "enabled": 1, "property": fx.PROPERTY, "default_market": "DE", "default_currency": "EUR",
		                "currencies": "EUR", "self_service_enabled": 1}).insert(ignore_permissions=True)
	return {"account": acc}


def guest_books(session="sess-1", method="Card", guest=None, before_book=None, extras=None) -> dict:
	"""search → quote → book through the public API, as an anonymous visitor.
	``before_book`` runs between the quote and the booking; ``extras`` default: one airport transfer."""
	frappe.set_user("Guest")  # nosemgrep: frappe-setuser -- anonymous booking-engine visitor
	res = public.search(site=SLUG, check_in=str(fx.d(6, 10)), check_out=str(fx.d(6, 13)),
	                    rooms=[{"adults": 2, "children": [8]}], market="DE", session_id=session)
	prop = res["properties"][0]
	rt = frappe.db.get_value("Room Type", {"property": fx.PROPERTY, "room_type_code": "STD"})
	rp = frappe.db.get_value("Rate Plan", {"property": fx.PROPERTY, "code": "FLEX"})
	offer = next(o for o in prop["offers"] if o["room_type"] == rt and o["board"] == "AI" and o["rate_plan"] == rp)
	assert "contract" not in offer, "guest offers must not expose contract ids"
	q = public.quote(site=SLUG, offer_key=offer["rooms"][0]["offer_key"], extras=extras or [{"code": "TRF", "quantity": 1}],
	                 session_id=session)
	assert q["ok"], q
	if before_book:
		before_book()
		frappe.set_user("Guest")  # nosemgrep: frappe-setuser -- the visitor books
	return public.book(site=SLUG, quote_ids=[q["quote_id"]], guest=guest or GUEST, payment_method=method,
	                   session_id=session, idempotency_key=f"idem-{session}")


class TestGuestPayment(TexTestCase):
	def setUp(self):
		super().setUp()
		self.p = setup_site_and_payments(self.f)

	def test_sandbox_card_payment_confirms_booking(self):
		b = guest_books()
		self.assertEqual(b["status"], "Pending Payment")
		self.assertEqual(b["due_now"], "252.75")                 # 30 % of 842.50
		pmt = b["payment"]
		self.assertEqual(pmt["kind"], "redirect")
		self.assertTrue(pmt["sandbox"])
		txn = pmt["transaction"]

		# a forged signature is rejected and changes nothing (a coded refusal since G-70b, not a server error)
		with self.assertRaises(frappe.ValidationError) as cm:
			public.mock_pay(transaction=txn, outcome="success", sig="0" * 64)
		self.assertEqual(cm.exception.code, "PAYMENT_SIGNATURE_INVALID")
		self.assertEqual(frappe.db.get_value("TEX Payment Transaction", txn, "status"), "Pending")

		out = public.mock_pay(transaction=txn, outcome="success", sig=pmt["fields"]["success_sig"])
		self.assertEqual(out["status"], "Succeeded")
		self.assertTrue(out["return_url"].endswith(f"/book/{SLUG}/confirmation/{b['booking']}"))
		bk = frappe.get_doc("TEX Booking", b["booking"])
		self.assertEqual(bk.status, "Confirmed")
		self.assertEqual(D(bk.paid_amount), D("252.75"))
		self.assertEqual(D(bk.balance_amount), D("589.75"))
		row = frappe.db.get_value("TEX Payment Transaction", txn, ["card_last4", "card_brand"], as_dict=True)
		self.assertEqual(row.card_last4, "4242")                   # at most brand + last 4 are stored

		# the gateway calling again (or the guest reloading) is a no-op
		again = public.mock_pay(transaction=txn, outcome="success", sig=pmt["fields"]["success_sig"])
		self.assertTrue(again.get("replay"))
		self.assertEqual(D(frappe.db.get_value("TEX Booking", b["booking"], "paid_amount")), D("252.75"))
		self.assertEqual(frappe.db.count("TEX Payment Allocation", {"transaction": txn}), 1)

	def test_transactions_filter_on_either_date_bound(self):
		# G-91: an open-ended range filters on the bound it has; it is never widened to every
		# transaction, so the screen need not close it with a "today" of its own
		txn = guest_books(session="sess-range")["payment"]["transaction"]
		frappe.set_user("Administrator")  # nosemgrep: frappe-setuser -- finance lists transactions
		day = get_datetime(frappe.db.get_value("TEX Payment Transaction", txn, "creation")).date()

		def listed(**kw):
			return txn in {r["name"] for r in pay_api.transactions(property=fx.PROPERTY, **kw)}

		self.assertTrue(listed(date_from=str(day)))
		self.assertFalse(listed(date_from=str(day + timedelta(days=1))))
		self.assertTrue(listed(date_to=str(day)))
		self.assertFalse(listed(date_to=str(day - timedelta(days=1))))
		self.assertTrue(listed(date_from=str(day), date_to=str(day)))
		self.assertFalse(listed(date_from=str(day + timedelta(days=1)), date_to=str(day + timedelta(days=2))))

	def test_failed_payment_can_be_retried_with_manage_token(self):
		b = guest_books(session="sess-fail")
		pmt = b["payment"]
		out = public.mock_pay(transaction=pmt["transaction"], outcome="fail", sig=pmt["fields"]["fail_sig"])
		self.assertEqual(out["status"], "Failed")
		self.assertEqual(frappe.db.get_value("TEX Booking", b["booking"], "status"), "Pending Payment")
		retry = public.pay_booking(token=b["manage_token"])
		self.assertNotEqual(retry["transaction"], pmt["transaction"])
		public.mock_pay(transaction=retry["transaction"], outcome="success", sig=retry["fields"]["success_sig"])
		self.assertEqual(frappe.db.get_value("TEX Booking", b["booking"], "status"), "Confirmed")
		with self.assertRaises(frappe.PermissionError):
			public.pay_booking(token="x" * 40)

	def test_callback_endpoint_only_serves_real_gateways(self):
		b = guest_books(session="sess-cb")
		with self.assertRaises(frappe.DoesNotExistError):
			pay_api.callback(txn=b["payment"]["transaction"])

	def test_open_redirects_are_refused(self):
		site = frappe.get_doc("TEX Booking Site", SLUG)
		self.assertIsNone(public._safe_return_url(site, "https://evil.example.com/steal"))
		own = frappe.utils.get_url("/book/x")
		if own.startswith("https://"):
			self.assertEqual(public._safe_return_url(site, own), own)

	def test_refund_transfer_and_idempotency(self):
		b1 = guest_books(session="sess-r1")
		p1 = b1["payment"]
		public.mock_pay(transaction=p1["transaction"], outcome="success", sig=p1["fields"]["success_sig"])
		frappe.set_user("Administrator")  # nosemgrep: frappe-setuser -- finance user
		r = pay.refund(p1["transaction"], amount="50", reason="goodwill", idempotency_key="rf-1")
		self.assertEqual(r["status"], "Succeeded")
		self.assertEqual(pay.refund(p1["transaction"], amount="50", reason="goodwill",
		                            idempotency_key="rf-1")["replay"], True)
		self.assertEqual(D(frappe.db.get_value("TEX Booking", b1["booking"], "paid_amount")), D("202.75"))
		with self.assertRaises(frappe.ValidationError):
			pay.refund(p1["transaction"], amount="500", reason="too much", idempotency_key="rf-2")
		with self.assertRaises(frappe.ValidationError):
			pay.refund(p1["transaction"], amount="5", reason=" ", idempotency_key="rf-3")

		b2 = guest_books(session="sess-r2", guest={**GUEST, "email": "second@example.com"})
		frappe.set_user("Administrator")  # nosemgrep: frappe-setuser -- finance user
		t = pay.transfer(p1["transaction"], from_booking=b1["booking"], to_booking=b2["booking"], amount="20",
		                 reason="guest asked to move the deposit")
		self.assertTrue(t["released"] and t["allocated"])
		self.assertEqual(D(frappe.db.get_value("TEX Booking", b1["booking"], "paid_amount")), D("182.75"))
		self.assertEqual(D(frappe.db.get_value("TEX Booking", b2["booking"], "paid_amount")), D("20"))
		detail = pay_api.transaction(name=p1["transaction"])
		self.assertEqual(detail["refundable"], "202.75")
		self.assertEqual(detail["unallocated"], "0.00")
		self.assertTrue(frappe.db.exists("TEX Audit Event", {"action": "payment.refund"}))

	def test_allocation_submits_are_idempotent(self):
		b1 = guest_books(session="sess-ai1")
		p1 = b1["payment"]
		public.mock_pay(transaction=p1["transaction"], outcome="success", sig=p1["fields"]["success_sig"])
		b2 = guest_books(session="sess-ai2", guest={**GUEST, "email": "idem.second@example.com"})
		frappe.set_user("Administrator")  # nosemgrep: frappe-setuser -- finance user submitting twice
		paid = lambda b: D(frappe.db.get_value("TEX Booking", b, "paid_amount"))  # noqa: E731
		first = pay.transfer(p1["transaction"], from_booking=b1["booking"], to_booking=b2["booking"], amount="20",
		                     reason="move the deposit", idempotency_key="tr-1")
		again = pay.transfer(p1["transaction"], from_booking=b1["booking"], to_booking=b2["booking"], amount="20",
		                     reason="move the deposit", idempotency_key="tr-1")
		self.assertEqual(first, again)                                  # G-14: one transfer, not two
		self.assertEqual((paid(b1["booking"]), paid(b2["booking"])), (D("232.75"), D("20")))
		rel = [pay.release(p1["transaction"], booking=b2["booking"], amount="20", reason="back",
		                   idempotency_key="rl-1") for _ in range(2)]
		alloc = [pay.allocate(p1["transaction"], booking=b1["booking"], amount="20", reason="back",
		                      idempotency_key="al-1") for _ in range(2)]
		self.assertEqual((len(set(rel)), len(set(alloc))), (1, 1))
		self.assertEqual((paid(b1["booking"]), paid(b2["booking"])), (D("252.75"), D("0")))

	def test_payment_link_pays_and_allocates(self):
		b = guest_books(session="sess-link", method="Pay at Hotel")
		self.assertEqual(b["payment"], None)                      # 30 % deposit rate allows pay at hotel
		frappe.set_user("Administrator")  # nosemgrep: frappe-setuser -- call-centre agent
		link = pay.create_link(property=fx.PROPERTY, amount="100", currency="EUR", description="Deposit",
		                       booking=b["booking"], provider_account=self.p["account"], idempotency_key="lk-1")
		self.assertTrue(pay.create_link(property=fx.PROPERTY, amount="100", currency="EUR", description="Deposit",
		                                booking=b["booking"], idempotency_key="lk-1")["replay"])
		frappe.set_user("Guest")  # nosemgrep: frappe-setuser -- guest opens the link
		info = public.payment_link(token=link["token"])
		self.assertEqual(info["amount"], "100.00")
		start = public.pay_link(token=link["token"])
		public.mock_pay(transaction=start["transaction"], outcome="success", sig=start["fields"]["success_sig"])
		lk = frappe.get_doc("TEX Payment Link", link["link"])
		self.assertEqual(lk.status, "Paid")
		self.assertEqual(D(frappe.db.get_value("TEX Booking", b["booking"], "paid_amount")), D("100"))
		with self.assertRaises(frappe.ValidationError):
			public.pay_link(token=link["token"])


	# ── NEW-6 (ADR-066): no row, gap or series lock is held through a gateway call ──

	def started(self, session: str, gateway) -> tuple[dict | Exception, list, str | None]:
		"""``guest_books`` with the commits of a request outside tests (recorded, never made) and the
		sandbox gateway replaced by ``gateway(real, intent)``. → (its answer or error, what happened: a
		commit with the charge's status and whether its checkout lease was on, and each gateway call;
		the charge)."""
		from kamra.tex.payments.providers.simple import MockProvider

		events: list = []
		charge: dict = {}
		real, real_new = MockProvider.create_checkout, pay._new_txn

		def new_txn(**kw):
			doc = real_new(**kw)
			charge.setdefault("name", doc.name)
			return doc

		def commit(*_a, **_kw):
			row = frappe.db.get_value("TEX Payment Transaction", charge["name"],
			                          ["status", "checkout_started_at"], as_dict=True) if charge else None
			events.append(("commit", row and (row.status, bool(row.checkout_started_at))))

		def checkout(provider, intent):
			events.append("gateway")
			return gateway(lambda: real(provider, intent), intent)

		with mock.patch.dict(frappe.flags, {"in_test": False}), \
				mock.patch.object(frappe.db, "commit", side_effect=commit), \
				mock.patch.object(pay, "_new_txn", side_effect=new_txn), \
				mock.patch.object(MockProvider, "create_checkout", checkout):
			try:
				out = guest_books(session=session)
			except Exception as e:                   # the caller asserts on it
				out = e
		return out, events, charge.get("name")

	def test_the_gateway_is_asked_between_two_commits(self):
		out, events, _charge = self.started("new6-order", lambda real, _intent: real())
		self.assertEqual(events, [("commit", ("Pending", True)), "gateway", ("commit", ("Pending", False))])
		frappe.set_user("Administrator")  # nosemgrep: frappe-setuser -- read what was recorded
		pmt = out["payment"]
		self.assertEqual(frappe.db.get_value("TEX Payment Transaction", pmt["transaction"], "provider_ref"),
		                 f"MOCK-{pmt['transaction']}")

	def test_a_failed_start_is_on_record_before_the_guest_is_told(self):
		def down(_real, _intent):
			raise ProviderError("gateway down")

		out, events, charge = self.started("new6-down", down)
		self.assertIsInstance(out, frappe.ValidationError)
		self.assertIn("could not be started", str(out))
		# the booking and its charge were committed first; the failure is committed before the error
		self.assertEqual(events, [("commit", ("Pending", True)), "gateway", ("commit", ("Failed", False))])
		frappe.set_user("Administrator")  # nosemgrep: frappe-setuser -- read what was recorded
		b = frappe.db.get_value("TEX Payment Transaction", charge, "booking")
		self.assertEqual(frappe.db.get_value("TEX Booking", b, "status"), "Pending Payment")

	def test_a_second_start_while_the_gateway_works_is_told_to_wait(self):
		from kamra.tex.payments.providers.simple import MockProvider

		frappe.set_user("Guest")  # nosemgrep: frappe-setuser -- the guest's second tab
		real_start, first, second = pay.start_payment, {}, []

		def start(**kw):
			first.setdefault("kw", kw)
			return real_start(**kw)

		def gateway(real, _intent):
			if "again" not in first:          # the same charge, started again while this checkout is made
				first["again"] = True
				try:
					second.append(("started", real_start(**first["kw"])["transaction"]))
				except pay.PaymentBusy as e:
					second.append(("busy", str(e)))
			return real()

		real_checkout = MockProvider.create_checkout
		with mock.patch.object(pay, "start_payment", side_effect=start), \
				mock.patch.object(MockProvider, "create_checkout",
				                  lambda provider, intent: gateway(lambda: real_checkout(provider, intent), intent)):
			try:
				b = guest_books(session="new6-busy")
			except Exception as e:                   # before NEW-6 the second checkout broke the first
				b = e
		self.assertEqual(second, [("busy", "A payment is being started. Please wait a moment and try again.")])
		self.assertIsInstance(b, dict, b)
		self.assertTrue(b["payment"]["url"])


	def booked_with_its_start(self, session: str) -> tuple[dict, dict]:
		"""``guest_books`` and the arguments its payment was started with (to start it again)."""
		real_start, seen = pay.start_payment, {}

		def start(**kw):
			seen.setdefault("kw", kw)
			return real_start(**kw)

		with mock.patch.object(pay, "start_payment", side_effect=start):
			b = guest_books(session=session)
		return b, seen["kw"]

	def test_a_lease_outlasts_the_slowest_gateway_then_a_dead_start_is_taken_over(self):
		"""Sipay makes two calls, each up to 20 s to connect and 20 s to read: a start 70 s into its
		gateway call is alive. Once the lease is over the start died (its checkout never reached the
		guest): the charge it left is started again, and the guest pays it."""
		b, again = self.booked_with_its_start("new6-lease")
		txn = b["payment"]["transaction"]

		def started(seconds_ago):
			frappe.db.set_value("TEX Payment Transaction", txn, "checkout_started_at",
			                    add_to_date(now_datetime(), seconds=-seconds_ago), update_modified=False)

		started(70)
		with self.assertRaises(pay.PaymentBusy):
			pay.start_payment(**again)
		started(pay.CHECKOUT_LEASE_SECONDS + 1)
		out = pay.start_payment(**again)
		self.assertEqual(out["transaction"], txn)                  # the same charge, never a second one
		self.assertIsNone(frappe.db.get_value("TEX Payment Transaction", txn, "checkout_started_at"))
		public.mock_pay(transaction=txn, outcome="success", sig=out["fields"]["success_sig"])
		self.assertEqual(frappe.db.get_value("TEX Booking", b["booking"], "status"), "Confirmed")

	def test_the_answer_of_a_gateway_never_changes_a_charge_settled_meanwhile(self):
		"""A reused charge's earlier checkout is paid while the gateway makes its new one: step (c) records
		the new reference and leaves the charge Succeeded, its booking confirmed once; the new checkout is never
		handed out (LO-04)."""
		from kamra.tex.payments.providers.simple import MockProvider
		from kamra.tex.services import refusals

		b, again = self.booked_with_its_start("new6-settled")
		first = b["payment"]
		real = MockProvider.create_checkout

		def paid_meanwhile(provider, intent):
			public.mock_pay(transaction=first["transaction"], outcome="success", sig=first["fields"]["success_sig"])
			return real(provider, intent)

		with mock.patch.object(MockProvider, "create_checkout", paid_meanwhile), \
				self.assertRaisesRegex(frappe.ValidationError, "already processed") as cm:
			pay.start_payment(**again)
		self.assertEqual(refusals.code_of(cm.exception), "PAYMENT_ALREADY_PROCESSED")
		row = frappe.db.get_value("TEX Payment Transaction", first["transaction"],
		                          ["status", "provider_ref", "checkout_started_at"], as_dict=True)
		self.assertEqual((row.status, row.checkout_started_at), ("Succeeded", None))
		self.assertIn(f"MOCK-{first['transaction']}", row.provider_ref)
		self.assertEqual(frappe.db.get_value("TEX Booking", b["booking"], "status"), "Confirmed")
		self.assertEqual(frappe.db.count("TEX Payment Allocation", {"transaction": first["transaction"]}), 1)


class TestSelfService(TexTestCase):
	def setUp(self):
		super().setUp()
		setup_site_and_payments(self.f)

	def _paid_booking(self, session):
		b = guest_books(session=session)
		p = b["payment"]
		public.mock_pay(transaction=p["transaction"], outcome="success", sig=p["fields"]["success_sig"])
		return b

	def test_guest_extends_stay_and_lower_price_waits_for_staff(self):
		b = self._paid_booking("sess-ss")
		token, res = b["manage_token"], b["rooms"][0]["reservation"]
		view = public.booking_status(token=token)
		self.assertTrue(view["self_service"])
		self.assertNotIn("margin", str(view["rooms"][0].get("lines") or ""))
		up = public.manage_propose(token=token, reservation=res, changes={"check_out": str(fx.d(6, 14))})
		self.assertTrue(up["sellable"])
		self.assertGreater(D(up["difference"]), 0)
		self.assertEqual(up["settlement"]["kind"], "pay_now")     # the deposit share of the new price (G-45)
		done = public.manage_apply(token=token, proposal_token=up["proposal_token"])
		self.assertEqual(done["status"], "payment_required")
		self.assertEqual(str(frappe.db.get_value("Reservation", res, "check_out_date")), str(fx.d(6, 13)))
		public.mock_pay(transaction=done["payment"]["transaction"], outcome="success",
		                sig=done["payment"]["fields"]["success_sig"])     # paid: the gateway's word applies it
		self.assertEqual(frappe.db.get_value("Reservation", res, "tex_guest_change_pending"), 1)
		self.assertEqual(str(frappe.db.get_value("Reservation", res, "check_out_date")), str(fx.d(6, 14)))
		total_after = D(frappe.db.get_value("Reservation", res, "tex_total_amount"))

		down = public.manage_propose(token=token, reservation=res, changes={"check_out": str(fx.d(6, 12))})
		self.assertLess(D(down["difference"]), 0)
		self.assertEqual(down["settlement"]["kind"], "staff_approval")
		req = public.manage_apply(token=token, proposal_token=down["proposal_token"])
		self.assertEqual(req["status"], "requested")             # default policy: staff approval
		self.assertEqual(D(frappe.db.get_value("Reservation", res, "tex_total_amount")), total_after)

		# a token only reaches its own booking
		other = self._paid_booking("sess-ss2")
		with self.assertRaises(frappe.PermissionError):
			public.manage_cancel(token=token, reservation=other["rooms"][0]["reservation"])

	def test_a_free_cancellation_penalty_keeps_its_decimals(self):
		# money is a quantized string on every path, "0.00" as much as "84.25" (crs.cancellation_preview)
		from kamra.tex.money import to_str

		policy = {"rules": [{"days_before_arrival": 3, "penalty_type": "PERCENT", "penalty_value": "100"}]}
		for rate_plan, rule in (({}, "no policy (free cancellation)"),
		                        ({"cancellation_policy": policy}, "free cancellation window")):
			res = frappe._dict(tex_pricing_snapshot=json.dumps({"currency": "EUR", "rate_plan": rate_plan}),
			                   tex_currency="EUR", tex_total_amount="842.50", amount_after_tax=None,
			                   check_in_date=fx.d(6, 10))
			penalty, basis = booking.cancellation_penalty(res, today=fx.d(6, 1))
			self.assertEqual((to_str(penalty), basis["rule"]), ("0.00", rule))

	def test_the_manage_view_of_a_channels_booking_offers_no_change_or_cancel(self):
		"""LO-12 (PR #16 Kalanlar, audit 2K-3): a channel's booking is changed and cancelled on the channel (D-11, Y-8):
		the guest's page offers neither (before: ``can_change`` and ``can_cancel`` were true and the server refused
		both), and says who sold it by the connection's label, never its id."""
		b = guest_books(session="lo12", method="Pay at Hotel")
		frappe.set_user("Administrator")  # nosemgrep: frappe-setuser -- the channel manager's connection
		conn = frappe.get_doc({"doctype": "TEX Integration Connection", "label": "Sandbox CM", "property": fx.PROPERTY,
		                       "category": "Channel Manager", "adapter": "sandbox_channel", "environment": "Sandbox",
		                       "enabled": 1, "secret": "lo12-secret"}).insert(ignore_permissions=True)
		frappe.db.set_value("TEX Booking", b["booking"], {"channel_connection": conn.name, "external_ref": "OTA-LO12"})
		frappe.set_user("Guest")  # nosemgrep: frappe-setuser -- the guest's booking page
		view = public.booking_status(token=b["manage_token"])
		self.assertEqual([(r["can_change"], r["can_cancel"]) for r in view["rooms"]], [(False, False)])
		self.assertEqual(view["sold_by"], {"label": "Sandbox CM"})
		self.assertNotIn(conn.name, json.dumps(view))
		# a TEX booking is the guest's to change: no channel named
		own = public.booking_status(token=guest_books(session="lo12-own", method="Pay at Hotel")["manage_token"])
		self.assertIsNone(own["sold_by"])
		self.assertEqual([(r["can_change"], r["can_cancel"]) for r in own["rooms"]], [(True, True)])

	def test_no_online_cancellation_from_the_arrival_day(self):
		# O-16 (audit Part 2A, user decision): from the arrival day the stay may have started; giving its
		# nights back would resell a room the guest is in. A change still starts on the arrival day
		# (``guest_changes.room_changeable``, unchanged): the stricter rule is the cancellation's alone
		from frappe.utils import add_days, getdate

		b = self._paid_booking("sess-o16")
		token, res = b["manage_token"], b["rooms"][0]["reservation"]
		arrival = getdate(frappe.db.get_value("Reservation", res, "check_in_date"))

		def on(day):
			return self.freeze_time(f"{day} 10:00:00.250000")

		def room():
			return public.booking_status(token=token)["rooms"][0]

		for day in (add_days(arrival, 1), arrival):                       # arrived yesterday, arriving today
			with on(day):
				self.assertFalse(room()["can_cancel"], day)
				with self.assertRaisesRegex(frappe.ValidationError, "no longer be changed online") as cm:
					public.manage_cancel(token=token, reservation=res)
				# the code of a cancellation too late, not of a change refused (same English text, G-70b)
				self.assertEqual((cm.exception.code, frappe.local.response["tex_code"]),
				                 ("CANCEL_TOO_LATE", "CANCEL_TOO_LATE"))
		self.assertEqual(frappe.db.get_value("Reservation", res, "status"), "Confirmed")
		with on(arrival):                                                  # the change flow is still open
			self.assertTrue(room()["can_change"])
			self.assertIn("sellable", public.manage_propose(token=token, reservation=res,
			                                                changes={"check_out": str(fx.d(6, 14))}))
		with on(add_days(arrival, -1)):                                    # the day before: cancelled
			self.assertTrue(room()["can_cancel"])
			public.manage_cancel(token=token, reservation=res)
		self.assertEqual(frappe.db.get_value("Reservation", res, "status"), "Cancelled")

	def test_guest_cancels_with_policy_penalty(self):
		b = self._paid_booking("sess-cx")
		out = public.manage_cancel(token=b["manage_token"], reservation=b["rooms"][0]["reservation"])
		self.assertEqual(frappe.db.get_value("Reservation", out["reservation"], "status"), "Cancelled")
		self.assertTrue(frappe.db.get_value("TEX Booking", b["booking"], "guest_change_pending"))


class TestCrmLoyaltyReports(TexTestCase):
	def setUp(self):
		super().setUp()
		setup_site_and_payments(self.f)

	def test_loyalty_earn_mature_redeem_reverse(self):
		prog = frappe.get_doc({"doctype": "TEX Loyalty Program", "program_name": "Test Club", "property": fx.PROPERTY,
		                       "enabled": 1, "currency": "EUR", "point_value": 0.1, "min_redeem_points": 50,
		                       "max_redeem_percent": 50, "pending_days": 0,
		                       "earn_rules": [{"basis": "MONEY", "rate": 1}, {"basis": "STAY", "rate": 25}]}
		                      ).insert(ignore_permissions=True)
		b = guest_books(session="sess-loy")
		p = b["payment"]
		public.mock_pay(transaction=p["transaction"], outcome="success", sig=p["fields"]["success_sig"])
		frappe.set_user("Administrator")  # nosemgrep: frappe-setuser -- staff
		guest = frappe.db.get_value("TEX Booking", b["booking"], "booker_guest")
		bal = loyalty.balances(guest, prog.name)
		self.assertEqual(bal["pending"], 867)                     # floor(842.50) + 25
		self.assertEqual(bal["available"], 0)
		loyalty.mature_and_expire(today=fx.d(6, 13))
		self.assertEqual(loyalty.balances(guest, prog.name)["available"], 867)
		r = loyalty.redeem(guest, b["booking"], 300, idempotency_key="loy-1")
		self.assertEqual(r["value"], "30.00")
		self.assertEqual(loyalty.balances(guest, prog.name)["available"], 567)
		self.assertEqual(frappe.db.get_value("Guest", guest, "tex_loyalty_points"), 567)
		booking.cancel_reservation(b["rooms"][0]["reservation"], reason="test", waive_penalty=True)
		# 867 earned, 300 spent: the reversal floors the balance at zero, never negative
		self.assertEqual(loyalty.balances(guest, prog.name)["available"], 0)

	def test_consent_is_audited_and_export_respects_it(self):
		guest_books(session="sess-crm")
		frappe.set_user("Administrator")  # nosemgrep: frappe-setuser -- staff
		guest = frappe.db.get_value("Guest", {"email": "lena@example.com"})
		self.assertFalse(frappe.db.get_value("Guest", guest, "tex_consent_email"))   # never implied
		seg = crm.save_segment({"segment_name": "DE guests", "rules": {"match": "all", "conditions": [
			{"field": "country", "op": "eq", "value": "Germany"}]}})
		exported = lambda: [r["guest"] for r in crm.export_segment(seg, channel="Email")]  # noqa: E731
		self.assertNotIn(guest, exported())                                          # no consent → not exported
		crm.update_profile(guest, {"tex_consent_email": 1}, consent_source="phone call",
		                   consent_text_version="v1")
		rows = [r for r in crm.export_segment(seg, channel="Email") if r["guest"] == guest]
		self.assertEqual([r["email"] for r in rows], ["lena@example.com"])
		prof = crm_api.guest(name=guest)
		self.assertEqual(len(prof["consent_history"]), 1)
		self.assertIn("DE guests", [s["segment_name"] for s in prof["segments"]])
		with self.assertRaises(frappe.ValidationError):
			crm.save_segment({"segment_name": "bad", "rules": {"conditions": [{"field": "password", "op": "eq"}]}})

	def test_abandoned_booking_detection(self):
		frappe.set_user("Guest")  # nosemgrep: frappe-setuser -- visitor
		public.search(site=SLUG, check_in=str(fx.d(6, 10)), check_out=str(fx.d(6, 13)), rooms=[{"adults": 2}],
		              market="DE", session_id="sess-ab")
		frappe.set_user("Administrator")  # nosemgrep: frappe-setuser -- scheduler
		frappe.get_doc({"doctype": "TEX Funnel Event", "event": "quote", "occurred_at": now_datetime(),
		                "site": SLUG, "property": fx.PROPERTY, "session_id": "sess-ab",
		                "payload": '{"total": "610.00", "currency": "EUR"}'}).insert(ignore_permissions=True)
		frappe.db.sql("UPDATE `tabTEX Funnel Event` SET occurred_at=%s WHERE session_id='sess-ab'",
		              add_to_date(now_datetime(), hours=-2))
		out = crm.detect_abandoned()
		self.assertGreaterEqual(out["created"], 1)
		row = frappe.get_doc("TEX Abandoned Booking", {"session_id": "sess-ab"})
		self.assertEqual(row.stage_reached, "quote")
		self.assertEqual(D(row.value), D("610"))
		self.assertFalse(row.email)                               # no consent → anonymous
		self.assertEqual(crm.detect_abandoned()["created"], 0)    # idempotent

	def test_production_report_prorates_stay_nights(self):
		b = guest_books(session="sess-rep")
		p = b["payment"]
		public.mock_pay(transaction=p["transaction"], outcome="success", sig=p["fields"]["success_sig"])
		frappe.set_user("Administrator")  # nosemgrep: frappe-setuser -- revenue manager
		rep = reports.production(fx.PROPERTY, fx.d(6, 11), fx.d(6, 30), group_by="channel", basis="stay")
		eur = rep["totals"]["EUR"]
		self.assertEqual(eur["room_nights"], 2)                   # nights of 11th and 12th fall inside
		self.assertEqual(eur["revenue"], "561.67")                # 842.50 × 2/3
		dash = reports.dashboard(fx.PROPERTY, fx.d(6, 1), fx.d(6, 30))
		self.assertIn("EUR", dash["stay"])


class TestTenantIsolation(TexTestCase):
	def setUp(self):
		super().setUp()
		setup_site_and_payments(self.f)
		self.other = "TEX Other Hotel"
		if not frappe.db.exists("Property", self.other):
			frappe.get_doc({"doctype": "Property", "property_name": self.other, "city": "Kemer", "country": "Turkey",
			                "currency": "EUR"}).insert(ignore_permissions=True)
		self.user = fx.ensure_user("agent-other@example.com", ["Call Center Agent"])
		fx.ensure("TEX Access Grant", {"user": self.user, "property": self.other},
		          {"user": self.user, "scope_level": "Hotel", "property": self.other,
		           "permission_profile": "Reservations Agent"})
		scope.clear_cache()

	def test_agent_of_another_hotel_sees_nothing_here(self):
		b = guest_books(session="sess-ten")
		frappe.set_user(self.user)  # nosemgrep: frappe-setuser -- foreign-hotel agent
		scope.clear_cache()
		self.assertNotIn(fx.PROPERTY, scope.permitted_properties())
		with self.assertRaises(frappe.PermissionError):
			pay_api.transactions(property=fx.PROPERTY)
		with self.assertRaises(frappe.PermissionError):
			pay_api.transaction(name=b["payment"]["transaction"])
		with self.assertRaises(frappe.PermissionError):
			pay.create_link(property=fx.PROPERTY, amount="10", currency="EUR", description="x")
		with self.assertRaises(frappe.PermissionError):
			booking.cancel_reservation(b["rooms"][0]["reservation"], reason="not mine")
		guest = frappe.db.get_value("TEX Booking", b["booking"], "booker_guest")
		self.assertNotIn(guest, [r["name"] for r in crm.list_guests()["rows"]])
		with self.assertRaises(frappe.PermissionError):
			crm.profile(guest)
		with self.assertRaises(frappe.PermissionError):
			policy_api.get_record(doctype="User", name="Administrator")
		with self.assertRaises(frappe.ValidationError):
			policy_api.history(doctype="User", name="Administrator")
		with self.assertRaises(frappe.PermissionError):
			reports.production(fx.PROPERTY, fx.d(6, 1), fx.d(6, 30))

	def test_domain_verified_flag_cannot_be_set_by_editing(self):
		site = frappe.get_doc("TEX Booking Site", SLUG)
		site.append("domains", {"domain": "book.example.com", "verified": 1})
		site.save(ignore_permissions=True)
		self.assertEqual(site.domains[0].verified, 0)
		self.assertTrue(site.domains[0].verification_token)

	def test_legacy_endpoints_and_desk_lists_respect_tenancy(self):
		frappe.db.set_single_value("TEX Settings", "show_legacy_pms", 1)  # a site that runs the PMS (G-16)
		b = guest_books(session="sess-leg")
		res = b["rooms"][0]["reservation"]
		frappe.set_user("Administrator")  # nosemgrep: frappe-setuser -- give the agent a legacy role
		frappe.get_doc("User", self.user).add_roles("Front Desk")
		frappe.set_user(self.user)  # nosemgrep: frappe-setuser -- foreign-hotel agent
		scope.clear_cache()
		from kamra import api, crs

		self.assertEqual(crs.permitted_properties(), {self.other})
		self.assertEqual([p["name"] for p in api.my_properties()], [self.other])
		with self.assertRaises(frappe.PermissionError):             # property argument
			api.front_desk_snapshot(property=fx.PROPERTY)
		snap = api.front_desk_snapshot()                             # no argument → own hotels only
		self.assertNotIn(res, [r["name"] for r in snap.get("arrivals", [])])
		# Desk / get_list: row-level filter and document-level check
		self.assertNotIn(res, frappe.get_list("Reservation", pluck="name"))
		self.assertFalse(frappe.has_permission("Reservation", "read", doc=frappe.get_doc("Reservation", res)))
		self.assertEqual(frappe.get_list("Property", pluck="name"), [self.other])

	def test_permission_hooks_cover_every_scoped_doctype(self):
		from kamra import hooks
		from kamra.tex.security import perm

		self.assertEqual(set(hooks._TEX_SCOPED), set(perm.SCOPED_DOCTYPES))



def two_rooms_book(session: str, *, extras=((), ()), code: str | None = None, method="Pay at Hotel",
                   guest=None) -> tuple[list[dict], dict]:
	"""Search two rooms (2A+child 8, 1A), quote each with its extras, book them together."""
	frappe.set_user("Guest")  # nosemgrep: frappe-setuser -- anonymous booking-engine visitor
	res = public.search(site=SLUG, check_in=str(fx.d(6, 10)), check_out=str(fx.d(6, 13)),
	                    rooms=[{"adults": 2, "children": [8]}, {"adults": 1}], market="DE", promo_code=code,
	                    session_id=session)
	rt = frappe.db.get_value("Room Type", {"property": fx.PROPERTY, "room_type_code": "STD"})
	rp = frappe.db.get_value("Rate Plan", {"property": fx.PROPERTY, "code": "FLEX"})
	offer = next(o for o in res["properties"][0]["offers"]
	             if o["room_type"] == rt and o["board"] == "AI" and o["rate_plan"] == rp)
	quotes = []
	for room, extra in zip(sorted(offer["rooms"], key=lambda r: r["room_index"]), extras, strict=True):
		q = public.quote(site=SLUG, offer_key=room["offer_key"], extras=[{"code": c, "quantity": 1} for c in extra],
		                 promo_code=code, session_id=session)
		assert q["ok"], q
		quotes.append(q)
	b = public.book(site=SLUG, quote_ids=[q["quote_id"] for q in quotes], guest=guest or GUEST,
	                payment_method=method, session_id=session, idempotency_key=f"idem-{session}")
	return quotes, b


class TestBookingLevelTerms(TexTestCase):
	"""G-05/G-06 (ADR-029): a per-booking extra is charged once per booking and a fixed
	booking coupon is granted once; a code used on a multi-room booking is one use."""

	def setUp(self):
		super().setUp()
		setup_site_and_payments(self.f)

	def _coupon(self, code: str, **kw) -> str:
		doc = policy_api.save_record("TEX Promotion", {
			"promotion_name": f"Coupon {code}", "property": fx.PROPERTY, "trigger": "Code", "code": code,
			"value_type": "FIXED_STAY", "value": 50, "currency": "EUR", "applies_to": "TOTAL", **kw})
		policy_api.activate("TEX Promotion", doc["name"], at=str(add_to_date(now_datetime(), minutes=-1)))
		return doc["name"]

	def test_per_booking_extra_is_charged_once(self):
		quotes, b = two_rooms_book("blt-trf", extras=(("TRF",), ("TRF",)))
		trf = [next(e for e in q["quote"]["extras"] if e["code"] == "TRF") for q in quotes]
		self.assertTrue(trf[0]["ok"])
		self.assertFalse(trf[1]["ok"])                                   # refused on room 2, with the reason
		self.assertIn("once per booking", trf[1]["reason"])
		self.assertEqual(D(quotes[0]["quote"]["totals"]["extras"]), D("40.00"))
		self.assertEqual(D(quotes[1]["quote"]["totals"]["extras"]), D("0"))
		self.assertEqual(D(b["total"]), sum(D(q["quote"]["totals"]["total"]) for q in quotes))

	def test_fixed_booking_coupon_is_granted_once_and_used_once(self):
		promo = self._coupon("TWOROOMS", usage_limit=1)
		quotes, b = two_rooms_book("blt-coupon", code="TWOROOMS")
		self.assertEqual([D(q["quote"]["totals"]["discounts"]) for q in quotes], [D("50.00"), D("0")])
		self.assertTrue(b["booking"])                                    # one use left was enough for 2 rooms
		frappe.set_user("Administrator")  # nosemgrep: frappe-setuser -- read the ledger
		reds = frappe.get_all("TEX Promotion Redemption", filters={"promotion": promo},
		                      fields=["booking", "amount", "reservation"])
		self.assertEqual(len(reds), 1)
		self.assertEqual((reds[0].booking, D(reds[0].amount)), (b["booking"], D("50")))

	def test_rooms_of_one_booking_come_from_one_search(self):
		rt = frappe.db.get_value("Room Type", {"property": fx.PROPERTY, "room_type_code": "STD"})
		rp = frappe.db.get_value("Rate Plan", {"property": fx.PROPERTY, "code": "FLEX"})
		frappe.set_user("Guest")  # nosemgrep: frappe-setuser -- anonymous visitor mixing two searches
		ids = []
		for _search in range(2):  # two one-room searches: both rooms claim to be room 1
			res = public.search(site=SLUG, check_in=str(fx.d(6, 10)), check_out=str(fx.d(6, 13)),
			                    rooms=[{"adults": 2}], market="DE", session_id="blt-mix")
			offer = next(o for o in res["properties"][0]["offers"]
			             if o["room_type"] == rt and o["board"] == "AI" and o["rate_plan"] == rp)
			ids.append(public.quote(site=SLUG, offer_key=offer["rooms"][0]["offer_key"], session_id="blt-mix")[
				"quote_id"])
		with self.assertRaisesRegex(frappe.ValidationError, "one search"):
			public.book(site=SLUG, quote_ids=ids, guest=GUEST, payment_method="Pay at Hotel", session_id="blt-mix",
			            idempotency_key="idem-blt-mix")


def two_rooms_quoted_together(session: str, *, code: str | None = None, rooms=None) -> tuple[list[dict], dict]:
	"""Search two rooms (2A+child 8, 1A) and quote them together, as the booking engine does."""
	frappe.set_user("Guest")  # nosemgrep: frappe-setuser -- anonymous booking-engine visitor
	res = public.search(site=SLUG, check_in=str(fx.d(6, 10)), check_out=str(fx.d(6, 13)),
	                    rooms=rooms or [{"adults": 2, "children": [8]}, {"adults": 1}], market="DE", promo_code=code,
	                    session_id=session)
	rt = frappe.db.get_value("Room Type", {"property": fx.PROPERTY, "room_type_code": "STD"})
	rp = frappe.db.get_value("Rate Plan", {"property": fx.PROPERTY, "code": "FLEX"})
	offer = next(o for o in res["properties"][0]["offers"]
	             if o["room_type"] == rt and o["board"] == "AI" and o["rate_plan"] == rp)
	out = public.quote_rooms(site=SLUG, rooms=[{"offer_key": r["offer_key"], "extras": []}
	                                            for r in sorted(offer["rooms"], key=lambda r: r["room_index"])],
	                         session_id=session)
	assert out["ok"], out
	return out["rooms"], offer


class TestBookingBasket(TexTestCase):
	"""G-84 (ADR-057): a coupon's minimum basket is the whole booking's. Two rooms of 802.50 and
	321.00 EUR are each below a 1 000 EUR minimum and qualify together (1 123.50): the booking
	engine and the CRS quote the rooms of a booking together; a room quoted alone is priced
	alone, and a booking whose rooms were priced otherwise than together is refused rather than
	sold at another price. A change is judged with the other live rooms of the booking; a room
	that is not changed keeps its locked price."""

	def setUp(self):
		super().setUp()
		setup_site_and_payments(self.f)

	def _big(self, minimum=1000, code="BIG") -> str:
		frappe.set_user("Administrator")  # nosemgrep: frappe-setuser -- revenue manager sets up the code
		doc = policy_api.save_record("TEX Promotion", {
			"promotion_name": f"Code {code}", "property": fx.PROPERTY, "trigger": "Code", "code": code,
			"value_type": "PERCENT", "value": 10, "applies_to": "ACCOMMODATION", "currency": "EUR",
			"min_basket": minimum})
		policy_api.activate("TEX Promotion", doc["name"], at=str(add_to_date(now_datetime(), minutes=-1)))
		return doc["name"]

	def _discounts(self, quotes) -> list:
		return [D(q["quote"]["totals"]["discounts"]) for q in quotes]

	def test_rooms_quoted_together_qualify_on_the_booking_basket(self):
		promo = self._big()
		quotes, _offer = two_rooms_quoted_together("g84-together", code="BIG")
		self.assertEqual(self._discounts(quotes), [D("80.25"), D("32.10")])
		b = public.book(site=SLUG, quote_ids=[q["quote_id"] for q in quotes], guest=GUEST,
		                payment_method="Pay at Hotel", session_id="g84-together", idempotency_key="idem-g84-together")
		self.assertEqual(D(b["total"]), D("1011.15"))
		frappe.set_user("Administrator")  # nosemgrep: frappe-setuser -- read what was sold
		snap = json.loads(frappe.db.get_value("Reservation", b["rooms"][1]["reservation"], "tex_pricing_snapshot"))
		self.assertEqual((snap["request"]["booking_basket"], snap["request"]["booking_rooms"], snap["basket"]),
		                 ("1123.500000", 2, "321.000000"))                # recorded to 6 places
		self.assertTrue(any(s["code"] == "BOOKING_BASKET" for s in snap["explanation"]))
		reds = frappe.get_all("TEX Promotion Redemption", filters={"promotion": promo}, fields=["amount"])
		self.assertEqual([D(r.amount) for r in reds], [D("112.35")])             # one use, both rooms' discount

	def test_a_booking_below_the_minimum_gets_nothing(self):
		self._big(minimum=1200)
		quotes, _offer = two_rooms_quoted_together("g84-below", code="BIG")
		self.assertEqual(self._discounts(quotes), [D("0"), D("0")])

	def test_the_search_prices_a_full_offer_on_the_booking_basket(self):
		self._big()
		_quotes, offer = two_rooms_quoted_together("g84-search", code="BIG")
		self.assertEqual(D(offer["total"]), D("1011.15"))

	def test_rooms_quoted_alone_are_not_booked_below_the_booking_price(self):
		self._big()
		frappe.set_user("Guest")  # nosemgrep: frappe-setuser -- an API client quotes each room on its own
		res = public.search(site=SLUG, check_in=str(fx.d(6, 10)), check_out=str(fx.d(6, 13)),
		                    rooms=[{"adults": 2, "children": [8]}, {"adults": 1}], market="DE", promo_code="BIG",
		                    session_id="g84-alone")
		rt = frappe.db.get_value("Room Type", {"property": fx.PROPERTY, "room_type_code": "STD"})
		rp = frappe.db.get_value("Rate Plan", {"property": fx.PROPERTY, "code": "FLEX"})
		offer = next(o for o in res["properties"][0]["offers"]
		             if o["room_type"] == rt and o["board"] == "AI" and o["rate_plan"] == rp)
		ids = [public.quote(site=SLUG, offer_key=r["offer_key"], session_id="g84-alone")["quote_id"]
		       for r in sorted(offer["rooms"], key=lambda r: r["room_index"])]
		with self.assertRaisesRegex(frappe.ValidationError, "together"):
			public.book(site=SLUG, quote_ids=ids, guest=GUEST, payment_method="Pay at Hotel", session_id="g84-alone",
			            idempotency_key="idem-g84-alone")

	def test_rooms_priced_together_are_booked_together(self):
		self._big()
		quotes, _offer = two_rooms_quoted_together("g84-part", code="BIG")
		with self.assertRaisesRegex(frappe.ValidationError, "together"):
			public.book(site=SLUG, quote_ids=[quotes[0]["quote_id"]], guest=GUEST, payment_method="Pay at Hotel",
			            session_id="g84-part", idempotency_key="idem-g84-part")

	def test_a_booking_locks_its_quotes_in_name_order(self):
		"""2F-1 (P1-4): two bookings made of the same quotes, named in opposite orders by their callers, would each
		hold one quote and wait for the other. The quotes are locked in name order whatever the caller's order; a
		duplicated id is still refused (a set would have hidden it)."""
		quotes, _offer = two_rooms_quoted_together("p14-quotes")
		ids = sorted((q["quote_id"] for q in quotes), reverse=True)          # the caller's order is not the lock order
		with mock.patch.object(quoting, "load_quote", wraps=quoting.load_quote) as load:
			public.book(site=SLUG, quote_ids=ids, guest=GUEST, payment_method="Pay at Hotel", session_id="p14-quotes",
			            idempotency_key="idem-p14-quotes")
		self.assertEqual([c.args[0] for c in load.call_args_list if c.kwargs.get("for_update")], sorted(ids))
		fresh, _offer = two_rooms_quoted_together("p14-dup")
		with self.assertRaisesRegex(frappe.ValidationError, "one search"):
			public.book(site=SLUG, quote_ids=[fresh[0]["quote_id"]] * 2, guest=GUEST, payment_method="Pay at Hotel",
			            session_id="p14-dup", idempotency_key="idem-p14-dup")

	def _booked(self, session: str) -> dict:
		quotes, _offer = two_rooms_quoted_together(session, code="BIG")
		return public.book(site=SLUG, quote_ids=[q["quote_id"] for q in quotes], guest=GUEST,
		                   payment_method="Pay at Hotel", session_id=session, idempotency_key=f"idem-{session}")

	def test_a_change_keeps_the_discount_while_the_booking_qualifies(self):
		self._big()
		b = self._booked("g84-keep")
		frappe.set_user("Administrator")  # nosemgrep: frappe-setuser -- the agent adds a guest to room 2
		room2 = b["rooms"][1]["reservation"]
		p = modification.propose(room2, {"adults": 2})                   # 642.00 alone: below 1 000
		code = next(x for x in p["proposed"]["promotions"] if x["code"] == "BIG")
		self.assertTrue(code["applied"], code["reason"])
		self.assertEqual(p["proposed"]["totals"]["total"], "577.80")
		self.assertEqual(p["proposed"]["request"]["booking_basket"], "1444.500000")
		modification.apply(p["proposal_token"], reason="second guest")
		frappe.set_user("Guest")  # nosemgrep: frappe-setuser -- the guest extends room 2 on the manage page
		up = public.manage_propose(token=b["manage_token"], reservation=room2, changes={"check_out": str(fx.d(6, 14))})
		self.assertTrue(up["sellable"], up["warnings"])
		self.assertEqual(up["new_total"], "770.40")                      # 856.00 alone, less 10 % with room 1

	def test_a_change_below_the_minimum_charges_the_changed_room_the_discount_the_others_keep(self):
		# review H1: room 2 shortened takes the booking below 1 100 (802.50 + 214.00 = 1 016.50); room 1
		# keeps its locked 722.25, so room 2 carries the 80.25 room 1 no longer earns
		self._big(minimum=1100)
		b = self._booked("g84-drop")
		room1, room2 = (r["reservation"] for r in b["rooms"])
		frappe.set_user("Guest")  # nosemgrep: frappe-setuser -- the guest sees it before confirming
		up = public.manage_propose(token=b["manage_token"], reservation=room2, changes={"check_out": str(fx.d(6, 12))})
		self.assertEqual((up["new_total"], up["basket_clawback"]["amount"]), ("294.25", "80.25"))
		self.assertEqual([(ln["kind"], ln["amount"]) for ln in up["lines"] if ln["kind"] == "BASKET"],
		                 [("BASKET", "80.25")])
		frappe.set_user("Administrator")  # nosemgrep: frappe-setuser -- the agent shortens room 2
		p = modification.propose(room2, {"check_out": str(fx.d(6, 12))})
		code = next(x for x in p["proposed"]["promotions"] if x["code"] == "BIG")
		self.assertFalse(code["applied"])
		self.assertIn("booking basket 1016.50 EUR (2 rooms)", code["reason"])
		self.assertEqual((p["proposed"]["totals"]["total"], p["proposed"]["totals"]["basket_clawback"]),
		                 ("294.25", "80.25"))
		(promo,) = p["basket_clawback"]["promotions"]
		self.assertEqual((promo["name"], promo["minimum"], promo["basket_before"], promo["basket_after"]),
		                 ("Code BIG", "1100.00", "1123.50", "1016.50"))
		self.assertEqual(promo["rooms"], [{"reservation": room1, "amount": "80.25"}])
		step = next(x for x in p["proposed"]["explanation"] if x["code"] == "BASKET_CLAWBACK")
		self.assertIn("80.25", step["text"])
		out = modification.apply(p["proposal_token"], reason="leaves a day early")
		self.assertEqual(D(frappe.db.get_value("Reservation", room2, "tex_total_amount")), D("294.25"))
		self.assertEqual(D(frappe.db.get_value("Reservation", room1, "tex_total_amount")), D("722.25"))  # locked
		# the booking costs what its rooms cost without the promotion they no longer earn
		self.assertEqual(D(frappe.db.get_value("TEX Booking", b["booking"], "total_amount")), D("1016.50"))
		changes = json.loads(frappe.db.get_value("TEX Reservation Revision", out["revision"], "changes_json"))
		self.assertEqual(changes["basket_clawback"]["amount"], "80.25")
		self.assertTrue(frappe.db.exists("TEX Audit Event", {"action": "reservation.basket_clawback",
		                                                     "reference_name": room2}))
		# changed again, still below: charged once, never twice
		again = modification.propose(room2, {"adults": 1, "check_out": str(fx.d(6, 12))})
		self.assertEqual(again["proposed"]["totals"]["total"], "294.25")

	def test_cancelling_a_room_charges_the_discount_the_other_rooms_keep(self):
		from kamra.tex.api import crs as crs_api

		self._big(minimum=1100)
		b = self._booked("g84-cancel")
		room1, room2 = (r["reservation"] for r in b["rooms"])
		frappe.set_user("Guest")  # nosemgrep: frappe-setuser -- the guest sees the fee before cancelling
		view = public.booking_status(token=b["manage_token"])["rooms"]
		self.assertEqual([r["cancellation_fee_now"] for r in view], ["32.10", "80.25"])   # free cancellation else
		self.assertEqual(view[1]["cancellation_basket"]["promotions"][0]["basket_after"], "802.50")
		frappe.set_user("Administrator")  # nosemgrep: frappe-setuser -- the agent cancels room 2
		pre = crs_api.cancellation_preview(room2)
		self.assertEqual((pre["penalty"], pre["basis"]["basket_clawback"]["amount"]), ("80.25", "80.25"))
		# waiving the rate's penalty does not waive the discount the other room keeps
		out = booking.cancel_reservation(room2, reason="one room is enough", waive_penalty=True)
		self.assertEqual(out["penalty"], "80.25")
		self.assertEqual(D(frappe.db.get_value("Reservation", room1, "tex_total_amount")), D("722.25"))  # locked
		self.assertEqual(D(frappe.db.get_value("TEX Booking", b["booking"], "total_amount")), D("802.50"))
		self.assertTrue(frappe.db.exists("TEX Audit Event", {"action": "reservation.basket_clawback",
		                                                     "reference_name": room2}))
		# room 1 cancelled too: no room keeps the discount, and what room 2 paid for it comes back
		self.assertEqual(booking.cancel_reservation(room1, reason="plans changed")["penalty"], "-80.25")
		self.assertEqual(D(frappe.db.get_value("TEX Booking", b["booking"], "total_amount")), D("0"))

	def _pending(self, session: str) -> dict:
		"""The two rooms booked by card, not paid yet: the booking waits for its payment."""
		quotes, _offer = two_rooms_quoted_together(session, code="BIG")
		b = public.book(site=SLUG, quote_ids=[q["quote_id"] for q in quotes], guest=GUEST, payment_method="Card",
		                session_id=session, idempotency_key=f"idem-{session}")
		self.assertEqual((b["status"], D(b["total"])), ("Pending Payment", D("1011.15")))
		return b

	def _money(self, booking_name: str) -> tuple:
		frappe.set_user("Administrator")  # nosemgrep: frappe-setuser -- read what the booking owes
		row = frappe.db.get_value("TEX Booking", booking_name, ["status", "total_amount", "balance_amount"],
		                          as_dict=True)
		fees = [D(frappe.db.get_value("Reservation", r, "cancellation_fee") or 0)
		        for r in sorted(frappe.get_all("TEX Booking Room", filters={"parent": booking_name}, pluck="reservation"))]
		return row.status, D(row.total_amount), D(row.balance_amount), fees

	def test_a_room_of_a_booking_not_paid_yet_still_carries_the_discount_the_others_keep(self):
		# E1: C6 frees the rate's penalty of a booking never confirmed, not the discount room 1 keeps
		self._big(minimum=1100)
		b = self._pending("g84-pend")
		room2 = b["rooms"][1]["reservation"]
		frappe.set_user("Guest")  # nosemgrep: frappe-setuser -- the guest cancels room 2 on the manage page
		self.assertEqual(public.manage_cancel(token=b["manage_token"], reservation=room2)["penalty"], "80.25")
		frappe.set_user("Administrator")  # nosemgrep: frappe-setuser -- read what the booking owes
		bk = frappe.get_doc("TEX Booking", b["booking"])
		self.assertEqual((bk.status, D(bk.total_amount)), ("Pending Payment", D("802.50")))     # 722.25 + 80.25
		self.assertEqual(D(bk.amount_due_now), booking.required_now(bk))                         # its deposit + 80.25
		self.assertEqual(D(bk.amount_due_now), D("216.68") + D("80.25"))
		frappe.set_user("Guest")  # nosemgrep: frappe-setuser -- the guest pays what is due now
		p = public.pay_booking(token=b["manage_token"])
		self.assertEqual(D(frappe.db.get_value("TEX Payment Transaction", p["transaction"], "amount")), D("296.93"))
		public.mock_pay(transaction=p["transaction"], outcome="success", sig=p["fields"]["success_sig"])
		self.assertEqual(self._money(b["booking"])[:3], ("Partially Cancelled", D("802.50"), D("505.57")))

	def test_a_booking_that_expires_unpaid_owes_nothing_not_even_the_discount(self):
		self._big(minimum=1100)
		b = self._pending("g84-pend-exp")
		frappe.set_user("Guest")  # nosemgrep: frappe-setuser -- the guest cancels room 2, never pays
		public.manage_cancel(token=b["manage_token"], reservation=b["rooms"][1]["reservation"])
		frappe.set_user("Administrator")  # nosemgrep: frappe-setuser -- the expiry job runs past the hold
		self.assertTrue(booking.expire_booking(b["booking"], now=add_to_date(now_datetime(), days=2)))
		self.assertEqual(self._money(b["booking"]), ("Cancelled", D("0"), D("0"), [D("0"), D("0")]))
		self.assertTrue(frappe.db.exists("TEX Audit Event", {"action": "booking.fees_void",
		                                                     "reference_name": b["booking"]}))
		# its payment was made in time after all (B4): room 1 is taken back, and room 2 carries the discount again
		booking.revive_expired(b["booking"], reason="paid in time")
		self.assertEqual(self._money(b["booking"]), ("Pending Payment", D("802.50"), D("802.50"), [D("0"), D("80.25")]))

	def test_a_booking_cancelled_before_it_was_paid_owes_nothing_not_even_the_discount(self):
		self._big(minimum=1100)
		b = self._pending("g84-pend-all")
		frappe.set_user("Guest")  # nosemgrep: frappe-setuser -- the guest cancels both rooms, never pays
		for row in reversed(b["rooms"]):
			public.manage_cancel(token=b["manage_token"], reservation=row["reservation"])
		self.assertEqual(self._money(b["booking"]), ("Cancelled", D("0"), D("0"), [D("0"), D("0")]))

	def test_removing_an_extra_the_basket_counted_charges_the_other_rooms_discount(self):
		self._big(minimum=1150)
		frappe.set_user("Guest")  # nosemgrep: frappe-setuser -- the visitor adds a transfer to room 1
		res = public.search(site=SLUG, check_in=str(fx.d(6, 10)), check_out=str(fx.d(6, 13)),
		                    rooms=[{"adults": 2, "children": [8]}, {"adults": 1}], market="DE", promo_code="BIG",
		                    session_id="g84-extra")
		rt = frappe.db.get_value("Room Type", {"property": fx.PROPERTY, "room_type_code": "STD"})
		rp = frappe.db.get_value("Rate Plan", {"property": fx.PROPERTY, "code": "FLEX"})
		offer = next(o for o in res["properties"][0]["offers"]
		             if o["room_type"] == rt and o["board"] == "AI" and o["rate_plan"] == rp)
		rooms = sorted(offer["rooms"], key=lambda r: r["room_index"])
		out = public.quote_rooms(site=SLUG, rooms=[{"offer_key": rooms[0]["offer_key"],
		                                            "extras": [{"code": "TRF", "quantity": 1}]},
		                                           {"offer_key": rooms[1]["offer_key"], "extras": []}],
		                         promo_code="BIG", session_id="g84-extra")
		self.assertEqual(self._discounts(out["rooms"]), [D("80.25"), D("32.10")])     # 842.50 + 321.00 ≥ 1 150
		b = public.book(site=SLUG, quote_ids=[q["quote_id"] for q in out["rooms"]], guest=GUEST,
		                payment_method="Pay at Hotel", session_id="g84-extra", idempotency_key="idem-g84-extra")
		frappe.set_user("Administrator")  # nosemgrep: frappe-setuser -- the agent removes the transfer
		p = modification.propose(b["rooms"][0]["reservation"], {"extras": []})
		self.assertEqual((p["proposed"]["totals"]["total"], p["basket_clawback"]["amount"]), ("834.60", "32.10"))

	def test_a_fixed_discount_granted_on_room_1_is_charged_to_the_cancelled_room(self):
		# 50 off from 1 000, once per booking on room 1; room 2, with no discount of its own, is cancelled
		frappe.set_user("Administrator")  # nosemgrep: frappe-setuser -- revenue manager sets up the code
		doc = policy_api.save_record("TEX Promotion", {
			"promotion_name": "Coupon FIFTY", "property": fx.PROPERTY, "trigger": "Code", "code": "FIFTY",
			"value_type": "FIXED_STAY", "value": 50, "currency": "EUR", "applies_to": "TOTAL", "min_basket": 1000})
		policy_api.activate("TEX Promotion", doc["name"], at=str(add_to_date(now_datetime(), minutes=-1)))
		quotes, _offer = two_rooms_quoted_together("g84-fifty", code="FIFTY")
		self.assertEqual(self._discounts(quotes), [D("50.00"), D("0")])
		b = public.book(site=SLUG, quote_ids=[q["quote_id"] for q in quotes], guest=GUEST,
		                payment_method="Pay at Hotel", session_id="g84-fifty", idempotency_key="idem-g84-fifty")
		frappe.set_user("Administrator")  # nosemgrep: frappe-setuser -- the agent cancels room 2
		out = booking.cancel_reservation(b["rooms"][1]["reservation"], reason="one room is enough")
		self.assertEqual(out["penalty"], "50.00")

	def test_a_change_that_keeps_the_booking_above_the_minimum_charges_nothing(self):
		self._big(minimum=1000)
		b = self._booked("g84-above")
		frappe.set_user("Administrator")  # nosemgrep: frappe-setuser -- the agent shortens room 2
		p = modification.propose(b["rooms"][1]["reservation"], {"check_out": str(fx.d(6, 12))})   # 1 016.50
		self.assertEqual(p["proposed"]["totals"]["total"], "192.60")
		self.assertIsNone(p["basket_clawback"])
		self.assertNotIn("BASKET", [ln["kind"] for ln in p["proposed"]["lines"]])

	def test_every_room_of_a_booking_records_it(self):
		# review L3: each room qualifies alone (no second pass), and still records the booking
		promo = self._big(minimum=300)
		quotes, _offer = two_rooms_quoted_together("g84-record", code="BIG")
		b = public.book(site=SLUG, quote_ids=[q["quote_id"] for q in quotes], guest=GUEST,
		                payment_method="Pay at Hotel", session_id="g84-record", idempotency_key="idem-g84-record")
		frappe.set_user("Administrator")  # nosemgrep: frappe-setuser -- read what was sold
		snap = json.loads(frappe.db.get_value("Reservation", b["rooms"][1]["reservation"], "tex_pricing_snapshot"))
		req = snap["request"]
		self.assertEqual((req.get("booking_basket"), req.get("booking_rooms"), req.get("booking_baskets")),
		                 ("1123.500000", 2, {promo: {"basket": "1123.500000", "rooms": 2}}))

	def test_an_old_snapshot_does_not_count_extras_added_after_booking(self):
		# review L4: a price recorded before G-84 has no basket; its totals include the add-ons
		snap = {"totals": {"accommodation_gross": "802.50", "extras": "100.00"},
		        "addons": [{"id": "A1", "quote": {"totals": {"extras": "60.00"}}}]}
		self.assertEqual(booking.room_basket(snap), D("842.50"))

	def test_a_change_is_judged_with_the_other_rooms_of_the_booking(self):
		# each room qualifies alone (802.50 and 321.00 ≥ 300) and is booked with the discount; room 2
		# shortened to 214.00 is below the minimum alone, not with room 1 (1 016.50)
		self._big(minimum=300)
		_quotes, b = two_rooms_book("g84-change", code="BIG")
		frappe.set_user("Administrator")  # nosemgrep: frappe-setuser -- the agent shortens room 2
		room2 = b["rooms"][1]["reservation"]
		p = modification.propose(room2, {"check_out": str(fx.d(6, 12))})
		code = next(x for x in p["proposed"]["promotions"] if x["code"] == "BIG")
		self.assertTrue(code["applied"], code["reason"])
		self.assertEqual(p["proposed"]["totals"]["total"], "192.60")

	def test_the_simulator_judges_the_booking_as_recorded(self):
		self._big()
		b = self._booked("g84-sim")
		frappe.set_user("Administrator")  # nosemgrep: frappe-setuser -- a revenue manager simulates room 2
		room1, room2 = (r["reservation"] for r in b["rooms"])
		at = str(now_datetime())
		first = modification.simulate(room2, at)
		self.assertEqual(first["simulated"]["totals"]["total"], "288.90")   # 321.00 less 10 %, with room 1
		booking.cancel_reservation(room1, reason="room 1 no longer needed")
		self.assertEqual(modification.simulate(room2, at)["simulated"]["totals"]["total"], "288.90")  # the same answer

	def test_the_call_center_quotes_the_rooms_of_a_booking_together(self):
		from kamra.tex.api import crs as crs_api

		self._big()
		frappe.set_user("Administrator")  # nosemgrep: frappe-setuser -- a call-centre agent
		res = crs_api.search(check_in=str(fx.d(6, 10)), check_out=str(fx.d(6, 13)),
		                     rooms=[{"adults": 2, "children": [8]}, {"adults": 1}], market="DE", channel="CALL_CENTER",
		                     properties=[fx.PROPERTY], promo_codes=["BIG"])
		rt = frappe.db.get_value("Room Type", {"property": fx.PROPERTY, "room_type_code": "STD"})
		rp = frappe.db.get_value("Rate Plan", {"property": fx.PROPERTY, "code": "FLEX"})
		offer = next(o for o in res["properties"][0]["offers"]
		             if o["room_type"] == rt and o["board"] == "AI" and o["rate_plan"] == rp)
		out = crs_api.quote_rooms(rooms=[{"offer_key": r["offer_key"], "extras": []} for r in offer["rooms"]])
		self.assertEqual(self._discounts(out["rooms"]), [D("80.25"), D("32.10")])
		b = crs_api.book(quote_ids=[q["quote_id"] for q in out["rooms"]], guest=dict(GUEST),
		                 payment_method="Pay at Hotel")
		self.assertEqual(D(b["total"]), D("1011.15"))


class TestBasketReviewInputs(TexTestCase):
	"""G-84 review M1 and L2: the hotel's "from" price is a price that can be booked, and the
	rooms quoted together are checked for their shape and count as quotes each."""

	def setUp(self):
		super().setUp()
		setup_site_and_payments(self.f)

	def _promo(self, name: str, **kw) -> str:
		frappe.set_user("Administrator")  # nosemgrep: frappe-setuser -- revenue manager sets up the promotion
		doc = policy_api.save_record("TEX Promotion", {"promotion_name": name, "property": fx.PROPERTY,
		                                               "trigger": "Automatic", "value_type": "PERCENT",
		                                               "applies_to": "ACCOMMODATION", "currency": "EUR", **kw})
		policy_api.activate("TEX Promotion", doc["name"], at=str(add_to_date(now_datetime(), minutes=-1)))
		return doc["name"]

	def test_the_from_price_is_the_price_the_rooms_book_at_together(self):
		# review M1: 5 % exclusive from 1 000 replaces 15 % once the two rooms are priced together,
		# so the rooms cost more together than alone: the "from" price is the price together
		self._promo("Five from 1000", value=5, min_basket=1000, exclusive=1, priority=10)
		self._promo("Fifteen", value=15, priority=1)
		from kamra.tex.tests.integration.test_critical_journey import search_std

		prop = search_std(fx.d(6, 10), fx.d(6, 13), [{"adults": 2, "children": [8]}, {"adults": 1}], internal=True)
		together = min(D(o["total"]) for o in prop["offers"] if o["complete"] and o["available"] >= 2)
		self.assertEqual(D(prop["from_total"]), together)
		cheapest = next(o for o in prop["offers"] if D(o["total"]) == together)
		fifteen = [x for r in cheapest["rooms"] for x in r["quote"]["promotions"] if x["name"] == "Fifteen"]
		self.assertTrue(fifteen and not any(x["applied"] for x in fifteen))            # excluded together

	def test_the_from_price_needs_that_many_rooms_free(self):
		dlx = frappe.db.get_value("Room Type", {"property": fx.PROPERTY, "room_type_code": "DLX"})   # 2 rooms
		ci, co = fx.d(6, 10), fx.d(6, 13)
		out = quoting.search_property(fx.PROPERTY, check_in=ci, check_out=co,
		                              parties=quoting.parse_rooms([{"adults": 1}] * 3, arrival=ci), market="DE",
		                              channel="DIRECT_WEB", currency="EUR", room_type=dlx)
		self.assertTrue(out["offers"])
		self.assertEqual((out["from_total"], out["from_currency"]), (None, None))

	def test_rooms_that_are_not_rooms_are_refused_cleanly(self):
		frappe.set_user("Guest")  # nosemgrep: frappe-setuser -- an API client sends junk
		res = public.search(site=SLUG, check_in=str(fx.d(6, 10)), check_out=str(fx.d(6, 13)), rooms=[{"adults": 2}],
		                    market="DE", session_id="l2-junk")
		key = res["properties"][0]["offers"][0]["rooms"][0]["offer_key"]
		for junk in ([1, 2], ["x"], [{"offer_key": 5}], [{"offer_key": key, "extras": ["TRF"]}],
		             [{"offer_key": key, "extras": [{"code": "TRF", "quantity": [1]}]}],
		             [{"offer_key": key, "extras": [{"code": "TRF", "service_dates": "2027-06-10"}]}],
		             {"offer_key": key}, "[1]"):
			with self.subTest(junk=junk), self.assertRaises(frappe.ValidationError):
				public.quote_rooms(site=SLUG, rooms=junk, session_id="l2-junk")
		with self.assertRaises(frappe.ValidationError):
			public.quote(site=SLUG, offer_key=key, extras=[7], session_id="l2-junk")
		frappe.set_user("Administrator")  # nosemgrep: frappe-setuser -- the call centre sends junk too
		with self.assertRaises(frappe.ValidationError):
			crs_quote_rooms([1])

	def test_each_room_quoted_together_counts_as_a_quote(self):
		ip = f"198.51.100.{frappe.generate_hash(length=4)}"
		frappe.set_user("Guest")  # nosemgrep: frappe-setuser -- a visitor quoting eight rooms at a time
		rooms = [{"offer_key": f"junk-{i}", "extras": []} for i in range(8)]
		with mock.patch.object(public, "_visitor_ip", return_value=ip), \
				mock.patch.dict(public.WRITE_LIMIT, {"limit": lambda: 20}):
			for _ in range(2):                                 # 16 of 20: refused as offers, not by the limit
				with self.assertRaises(frappe.ValidationError) as e:
					public.quote_rooms(site=SLUG, rooms=rooms, session_id="l2-rate")
				self.assertNotIsInstance(e.exception, frappe.RateLimitExceededError)
			with self.assertRaises(frappe.RateLimitExceededError):
				public.quote_rooms(site=SLUG, rooms=rooms, session_id="l2-rate")
		frappe.cache.delete(frappe.cache.make_key(f"rl:tex.public.rooms_quoted:{ip}:600"))


def crs_quote_rooms(rooms):
	from kamra.tex.api import crs as crs_api

	return crs_api.quote_rooms(rooms=rooms)


class TestCouponLimits(TexTestCase):
	"""G-07: the per-guest limit is enforced when the booking is made (the guest is known
	only then). G-09: repricing a booking never counts its own coupon use, and a
	modification records a code it adds and releases one it drops."""

	def setUp(self):
		super().setUp()
		setup_site_and_payments(self.f)

	def _code(self, code: str, **kw) -> str:
		frappe.set_user("Administrator")  # nosemgrep: frappe-setuser -- revenue manager sets up the code
		doc = policy_api.save_record("TEX Promotion", {
			"promotion_name": f"Code {code}", "property": fx.PROPERTY, "trigger": "Code", "code": code,
			"value_type": "PERCENT", "value": 10, "applies_to": "ACCOMMODATION", **kw})
		policy_api.activate("TEX Promotion", doc["name"], at=str(add_to_date(now_datetime(), minutes=-1)))
		return doc["name"]

	def _live(self, promo: str, booking: str | None = None) -> list:
		frappe.set_user("Administrator")  # nosemgrep: frappe-setuser -- read the ledger
		f = {"promotion": promo, "status": ("in", ["Reserved", "Committed"])}
		if booking:
			f["booking"] = booking
		return frappe.get_all("TEX Promotion Redemption", filters=f, fields=["name", "amount", "booking"])

	def test_per_guest_limit_is_enforced_at_booking(self):
		promo = self._code("ONCE", per_guest_limit=1)
		two_rooms_book("g07-a", code="ONCE")
		with self.assertRaisesRegex(frappe.ValidationError, "already been used by this guest"):
			two_rooms_book("g07-b", code="ONCE")
		two_rooms_book("g07-c", code="ONCE", guest={**GUEST, "email": "someone.else@example.com"})
		self.assertEqual(len(self._live(promo)), 2)

	def test_repricing_does_not_count_the_bookings_own_use(self):
		promo = self._code("LAST1", usage_limit=1)
		_quotes, b = two_rooms_book("g09-own", code="LAST1")
		frappe.set_user("Administrator")  # nosemgrep: frappe-setuser -- the agent extends the stay
		res = b["rooms"][0]["reservation"]
		p = modification.propose(res, {"check_out": str(fx.d(6, 14))})
		code = next(x for x in p["proposed"]["promotions"] if x["promo_id"] == promo)
		self.assertTrue(code["applied"], code["reason"])            # not "usage limit reached"
		modification.apply(p["proposal_token"], reason="one more night")
		self.assertEqual(len(self._live(promo, b["booking"])), 1)  # still one use, now for the longer stay

	def test_modification_records_and_releases_codes(self):
		promo = self._code("ADDME", usage_limit=5)
		_quotes, b = two_rooms_book("g09-add")
		frappe.set_user("Administrator")  # nosemgrep: frappe-setuser -- the agent adds the guest's code
		res = b["rooms"][0]["reservation"]
		p = modification.propose(res, {"promo_codes": ["ADDME"]})
		modification.apply(p["proposal_token"], reason="guest had a code")
		live = self._live(promo, b["booking"])
		self.assertEqual(len(live), 1)
		self.assertGreater(D(live[0].amount), 0)
		frappe.set_user("Administrator")  # nosemgrep: frappe-setuser -- the code is removed again
		p = modification.propose(res, {"promo_codes": []})
		modification.apply(p["proposal_token"], reason="code not valid for this guest")
		self.assertEqual(self._live(promo, b["booking"]), [])


class TestEffectiveDatedExtrasAndTaxes(TexTestCase):
	"""G-20: extras and tax rules are effective-dated revisions. A stay priced at sale time
	T uses the extra and tax revisions live at T; the snapshot records which ones."""

	def setUp(self):
		super().setUp()
		setup_site_and_payments(self.f)
		self.trf = frappe.db.get_value("TEX Extra", {"property": fx.PROPERTY, "extra_code": "TRF",
		                                             "tex_status": "Active"})

	def _revise(self, doctype: str, name: str, **changes) -> str:
		from kamra.tex.commercial import revisions

		frappe.set_user("Administrator")  # nosemgrep: frappe-setuser -- revenue manager
		draft = revisions.revise(doctype, name)
		doc = frappe.get_doc(doctype, draft)
		for k, v in changes.items():
			if k == "rules":
				for row, rate in zip(doc.rules, v, strict=True):
					row.rate = rate
			else:
				doc.set(k, v)
		doc.save(ignore_permissions=True)
		revisions.activate(doctype, draft)
		return draft

	def _extra(self, quote: dict, code: str) -> dict:
		return next(e for e in quote["extras"] if e["code"] == code)

	def test_a_live_extra_is_immutable_and_a_new_price_is_a_revision(self):
		from kamra.tex.api import crs as crs_api

		b = guest_books(session="g20-extra")
		frappe.set_user("Administrator")  # nosemgrep: frappe-setuser -- staff
		res = b["rooms"][0]["reservation"]
		snap = json.loads(frappe.db.get_value("Reservation", res, "tex_pricing_snapshot"))
		self.assertEqual(self._extra(snap, "TRF")["revision"], self.trf)          # the snapshot names the revision
		self.assertEqual(D(self._extra(snap, "TRF")["amount"]), D("40"))
		live = frappe.get_doc("TEX Extra", self.trf)
		live.amount = 60
		with self.assertRaises(frappe.ValidationError):                        # never edited in place
			live.save(ignore_permissions=True)
		rev2 = self._revise("TEX Extra", self.trf, amount=60)
		self.assertEqual([(e["extra_code"], D(e["amount"])) for e in crs_api.extras_for(fx.PROPERTY)
		                  if e["extra_code"] == "TRF"], [("TRF", D("60"))])     # one live revision listed
		change = {"check_out": str(fx.d(6, 14))}
		now = modification.propose(res, change, basis="CURRENT")
		then = modification.propose(res, change, basis="ORIGINAL_VERSION")
		self.assertEqual((D(self._extra(now["proposed"], "TRF")["amount"]), self._extra(now["proposed"], "TRF")["revision"]),
		                 (D("60"), rev2))
		self.assertEqual((D(self._extra(then["proposed"], "TRF")["amount"]),
		                  self._extra(then["proposed"], "TRF")["revision"]), (D("40"), self.trf))
		sim = modification.simulate(res, sale_at=snap["request"]["sale_at"])
		self.assertEqual(D(self._extra(sim["simulated"], "TRF")["amount"]), D("40"))

	def _no_tax_policy(self):
		"""The test hotel without a tax policy (rolled back with the test)."""
		names = frappe.get_all("TEX Tax Policy", filters={"property": fx.PROPERTY}, pluck="name")
		if names:
			frappe.db.delete("TEX Tax Rule", {"parenttype": "TEX Tax Policy", "parent": ("in", names)})
			frappe.db.delete("TEX Tax Policy", {"name": ("in", names)})
			frappe.clear_document_cache("TEX Tax Policy")

	def _tax_policy(self, rules, at="2020-01-01 00:00:00", **extra) -> str:
		from kamra.tex.commercial import revisions

		self._no_tax_policy()
		pol = frappe.get_doc({"doctype": "TEX Tax Policy", "policy_name": "Resort taxes", "property": fx.PROPERTY,
		                      "rules": rules, **extra}).insert(ignore_permissions=True)
		revisions.activate("TEX Tax Policy", pol.name, at=at, backdate=True)
		return pol.name

	def test_tax_policy_revisions_apply_from_their_activation(self):
		from kamra.tex.commercial import revisions

		frappe.set_user("Administrator")  # nosemgrep: frappe-setuser -- finance sets the hotel's taxes
		pol = frappe.get_doc("TEX Tax Policy", self._tax_policy(
			[{"code": "VAT", "tax_name": "VAT", "kind": "PERCENT", "rate": 10, "applies_to": "ACCOMMODATION"}]))
		b = guest_books(session="g20-tax")
		frappe.set_user("Administrator")  # nosemgrep: frappe-setuser -- staff
		res = b["rooms"][0]["reservation"]
		snap = json.loads(frappe.db.get_value("Reservation", res, "tex_pricing_snapshot"))
		accom = D(snap["totals"]["accommodation"])
		self.assertEqual([(t["code"], D(t["amount"]), t["source"]) for t in snap["taxes"]],
		                 [("VAT", (accom * D("0.10")).quantize(D("0.01")), f"tax_policy:{pol.name}")])
		step = next(s for s in snap["explanation"] if s["code"] == "TAX")
		self.assertEqual((step["rule"]["kind"], step["rule"]["source"]), ("tax", f"tax_policy:{pol.name}"))
		rev2 = self._revise("TEX Tax Policy", pol.name, rules=[12])
		change = {"check_out": str(fx.d(6, 14))}
		now = modification.propose(res, change, basis="CURRENT")["proposed"]
		then = modification.propose(res, change, basis="ORIGINAL_VERSION")["proposed"]
		self.assertEqual((D(now["taxes"][0]["rate"]), now["taxes"][0]["source"]), (D("12"), f"tax_policy:{rev2}"))
		self.assertEqual((D(then["taxes"][0]["rate"]), then["taxes"][0]["source"]),
		                 (D("10"), f"tax_policy:{pol.name}"))
		# one tax policy per hotel: a second one is never put live next to it
		other = frappe.get_doc({"doctype": "TEX Tax Policy", "policy_name": "Second", "property": fx.PROPERTY,
		                        "rules": [{"code": "CITY", "kind": "PERCENT", "rate": 2}]}).insert(ignore_permissions=True)
		with self.assertRaises(frappe.ValidationError):
			revisions.activate("TEX Tax Policy", other.name)

	def test_history_is_never_rewritten(self):
		from kamra.tex.commercial import revisions

		frappe.set_user("Administrator")  # nosemgrep: frappe-setuser -- revenue manager
		draft = revisions.revise("TEX Extra", self.trf)
		with self.assertRaises(frappe.ValidationError):             # back-dated: what was sold stays as it was
			policy_api.activate("TEX Extra", draft, at="2020-06-01 00:00:00")
		self.assertEqual(frappe.db.get_value("TEX Extra", draft, "tex_status"), "Draft")
		t0 = now_datetime()
		policy_api.activate("TEX Extra", draft, at=str(add_to_date(t0, minutes=-1)))   # a lagging client clock
		self.assertGreaterEqual(get_datetime(frappe.db.get_value("TEX Extra", draft, "active_from")), t0)
		self.assertEqual(frappe.db.get_value("TEX Extra", self.trf, "active_to"),
		                 frappe.db.get_value("TEX Extra", draft, "active_from"))
		# scheduled changes stay in order: nothing slips in before an already scheduled revision
		later = revisions.revise("TEX Extra", draft)
		policy_api.activate("TEX Extra", later, at=str(add_to_date(t0, days=10)))
		sooner = revisions.revise("TEX Extra", draft)
		with self.assertRaises(frappe.ValidationError):
			policy_api.activate("TEX Extra", sooner, at=str(add_to_date(t0, days=5)))
		# at every instant exactly one revision of the extra is on sale
		for at in (add_to_date(t0, minutes=1), add_to_date(t0, days=11)):
			live = [r.name for r in context.live_extras(fx.PROPERTY, at=at) if r.extra_code == "TRF"]
			self.assertEqual(len(live), 1, (at, live))
		# cancelling the scheduled revision keeps the current one on sale: no gap
		policy_api.archive("TEX Extra", later, reason="schedule dropped")
		self.assertEqual(frappe.db.get_value("TEX Extra", draft, ["tex_status", "active_to"]), ("Active", None))
		for at in (add_to_date(t0, minutes=1), add_to_date(t0, days=11)):
			self.assertEqual([r.name for r in context.live_extras(fx.PROPERTY, at=at) if r.extra_code == "TRF"],
			                 [draft], at)

	def test_cancelling_two_schedules_leaves_one_live_revision(self):
		from kamra.tex.commercial import revisions

		frappe.set_user("Administrator")  # nosemgrep: frappe-setuser -- revenue manager
		t0 = now_datetime()
		t1, t2 = add_to_date(t0, days=5), add_to_date(t0, days=10)
		r2 = revisions.revise("TEX Extra", self.trf)
		policy_api.activate("TEX Extra", r2, at=str(t1))
		r3 = revisions.revise("TEX Extra", self.trf)
		policy_api.activate("TEX Extra", r3, at=str(t2))
		policy_api.archive("TEX Extra", r2, reason="first change dropped")    # superseded by r3, not yet live
		policy_api.archive("TEX Extra", r3, reason="second change dropped")

		def live(at):
			return [r.name for r in context.live_extras(fx.PROPERTY, at=at) if r.extra_code == "TRF"]

		for at in (add_to_date(t0, minutes=1), add_to_date(t1, hours=1), add_to_date(t2, hours=1)):
			self.assertEqual(live(at), [self.trf], at)                        # never an archived one
		self.assertEqual(frappe.db.get_value("TEX Extra", self.trf, ["tex_status", "active_to"]), ("Active", None))
		r4 = revisions.revise("TEX Extra", self.trf)                          # and it can be revised again
		policy_api.activate("TEX Extra", r4)
		self.assertEqual(live(add_to_date(t1, hours=1)), [r4])

	def test_a_revision_stays_at_its_hotel(self):
		from kamra.tex.commercial import revisions

		frappe.set_user("Administrator")  # nosemgrep: frappe-setuser -- an admin of both hotels
		other = "TEX Other Hotel"                          # a hotel without extras: nothing else refuses it
		if not frappe.db.exists("Property", other):
			frappe.get_doc({"doctype": "Property", "property_name": other, "city": "Kemer", "country": "Turkey",
			                "currency": "EUR"}).insert(ignore_permissions=True)
		draft = frappe.get_doc("TEX Extra", revisions.revise("TEX Extra", self.trf))
		draft.property = other
		with self.assertRaisesRegex(frappe.ValidationError, "stays at its record's hotel"):
			draft.save(ignore_permissions=True)        # activating it would end this hotel's extra
		draft.reload()
		draft.extra_code = "TRF-NEW"
		with self.assertRaisesRegex(frappe.ValidationError, "keeps its code"):
			draft.save(ignore_permissions=True)        # the code is the extra's identity across revisions

	def test_live_taxes_are_never_switched_off(self):
		frappe.set_user("Administrator")  # nosemgrep: frappe-setuser -- finance
		from kamra.tex.commercial import revisions

		pol = self._tax_policy([{"code": "VAT", "kind": "PERCENT", "rate": 10}])
		with self.assertRaises(frappe.ValidationError):
			policy_api.archive("TEX Tax Policy", pol, reason="no more taxes")
		# a revision scheduled for later: the current one is superseded but still live until then
		later = revisions.revise("TEX Tax Policy", pol)
		policy_api.activate("TEX Tax Policy", later, at=str(add_to_date(now_datetime(), days=10)))
		with self.assertRaises(frappe.ValidationError):
			policy_api.archive("TEX Tax Policy", pol, reason="no more taxes")
		policy_api.archive("TEX Tax Policy", later, reason="schedule dropped")   # cancelling is fine
		self.assertEqual(frappe.db.get_value("TEX Tax Policy", pol, ["tex_status", "active_to"]), ("Active", None))
		# a gap made behind TEX's back stops pricing; it never falls back to older settings
		frappe.db.set_value("TEX Tax Policy", pol, "active_to", add_to_date(now_datetime(), days=-1))
		frappe.clear_document_cache("TEX Tax Policy")
		with self.assertRaises(Unsellable):
			context.tax_rules(fx.PROPERTY)

	def test_a_scheduled_time_from_another_time_zone_is_the_same_instant(self):
		from datetime import UTC, datetime, timedelta
		from zoneinfo import ZoneInfo

		from frappe.utils import get_system_timezone

		from kamra.tex.commercial import revisions

		frappe.set_user("Administrator")  # nosemgrep: frappe-setuser -- revenue manager
		draft = revisions.revise("TEX Extra", self.trf)
		at = (datetime.now(UTC) + timedelta(hours=3)).replace(microsecond=0)
		policy_api.activate("TEX Extra", draft, at=at.isoformat())        # what the browser sends
		self.assertEqual(get_datetime(frappe.db.get_value("TEX Extra", draft, "active_from")),
		                 at.astimezone(ZoneInfo(get_system_timezone())).replace(tzinfo=None))

	def test_drafts_and_scheduled_extras_can_be_translated_before_launch(self):
		from kamra.tex.services import content

		frappe.set_user("Administrator")  # nosemgrep: frappe-setuser -- content editor
		d = policy_api.save_record("TEX Extra", {"property": fx.PROPERTY, "extra_code": "G20NEW",
		                                         "extra_name": "Sunset cruise", "category": "Service",
		                                         "pricing_mode": "UNIT", "currency": "EUR", "amount": "30"})
		refs = {i["ref_name"]: i["label"] for i in content.items(fx.PROPERTY) if i["ref_doctype"] == "TEX Extra"}
		self.assertEqual(refs.get(d["name"]), "Sunset cruise")
		self.assertIn(self.trf, refs)

	def test_a_first_policy_counts_only_once_it_has_begun(self):
		from kamra.tex.commercial import revisions

		frappe.set_user("Administrator")  # nosemgrep: frappe-setuser -- finance
		self._no_tax_policy()
		pol = frappe.get_doc({"doctype": "TEX Tax Policy", "policy_name": "From October", "property": fx.PROPERTY,
		                      "rules": [{"code": "VAT", "kind": "PERCENT", "rate": 10}]}).insert(ignore_permissions=True)
		start = add_to_date(now_datetime(), days=10)
		revisions.activate("TEX Tax Policy", pol.name, at=start)
		prop = frappe.get_doc("Property", fx.PROPERTY)          # still what prices until the policy begins
		prop.append("tex_tax_rules", {"code": "CITY", "kind": "PERCENT", "rate": 1, "applies_to": "ACCOMMODATION"})
		prop.save(ignore_permissions=True)
		policy_api.archive("TEX Tax Policy", pol.name, reason="postponed")   # the schedule is cancelled
		later = add_to_date(start, days=1)
		self.assertEqual([(r.code, r.source) for r in context.tax_rules(fx.PROPERTY, at=later)],
		                 [("CITY", f"property:{fx.PROPERTY}")])            # the hotel still sells, as before

	def test_a_room_type_tax_change_says_it_does_not_reprice(self):
		frappe.set_user("Administrator")  # nosemgrep: frappe-setuser -- desk admin
		self._tax_policy([{"code": "VAT", "kind": "PERCENT", "rate": 10}])
		rt = frappe.get_doc("Room Type", {"property": fx.PROPERTY, "room_type_code": "STD"})
		if not rt.meta.has_field("tax_percent"):
			self.skipTest("no room-type tax field")
		frappe.local.message_log = []
		rt.tax_percent = (rt.tax_percent or 0) + 5
		rt.save(ignore_permissions=True)
		self.assertTrue(any("does not affect them" in str(m) for m in frappe.local.message_log))

	def test_a_new_tex_hotel_starts_with_a_tax_policy(self):
		frappe.set_user("Administrator")  # nosemgrep: frappe-setuser -- onboarding
		self._no_tax_policy()
		frappe.get_doc("Property", fx.PROPERTY).save(ignore_permissions=True)   # e.g. joins a hotel group
		pol = frappe.get_all("TEX Tax Policy", filters={"property": fx.PROPERTY}, fields=["tex_status", "currency"])
		self.assertEqual([(p.tex_status, p.currency) for p in pol], [("Active", "EUR")])
		self.assertTrue(all(r.source.startswith("tax_policy:") for r in context.tax_rules(fx.PROPERTY)))

	def test_an_unchanged_reprice_reproduces_the_sold_price(self):
		# a new extra price goes live between the quote and the booking: the booking keeps the
		# quoted price, and an unchanged ORIGINAL_* reprice gives exactly that price again
		b = guest_books(session="g20-quote-time", before_book=lambda: self._revise("TEX Extra", self.trf, amount=55))
		frappe.set_user("Administrator")  # nosemgrep: frappe-setuser -- staff
		res = b["rooms"][0]["reservation"]
		snap = json.loads(frappe.db.get_value("Reservation", res, "tex_pricing_snapshot"))
		self.assertEqual(D(self._extra(snap, "TRF")["amount"]), D("40"))
		for basis in ("ORIGINAL_VERSION", "ORIGINAL_SALE_DATE"):
			p = modification.propose(res, {"adults": 2}, basis=basis)
			self.assertEqual(D(self._extra(p["proposed"], "TRF")["amount"]), D("40"), basis)
			self.assertEqual(D(p["proposed"]["totals"]["total"]), D(snap["totals"]["total"]), basis)

	def test_tax_policies_belong_to_finance(self):
		rm = fx.ensure_user("g20-revenue@example.com", ["Revenue Manager"])
		fin = fx.ensure_user("g20-finance@example.com", ["Finance"])
		for user, profile in ((rm, "Revenue Manager"), (fin, "Finance")):
			fx.ensure("TEX Access Grant", {"user": user, "property": fx.PROPERTY},
			          {"user": user, "scope_level": "Hotel", "property": fx.PROPERTY, "permission_profile": profile})
		scope.clear_cache()
		payload = {"policy_name": "Finance taxes", "property": fx.PROPERTY,
		           "rules": [{"code": "VAT", "kind": "PERCENT", "rate": 10}]}
		frappe.set_user(rm)  # nosemgrep: frappe-setuser -- revenue manager: prices, not taxes
		with self.assertRaises(frappe.PermissionError):
			policy_api.save_record("TEX Tax Policy", payload)
		frappe.set_user(fin)  # nosemgrep: frappe-setuser -- finance owns the hotel's taxes
		d = policy_api.save_record("TEX Tax Policy", payload)
		self.assertEqual((d["tex_status"], d["currency"]), ("Draft", "EUR"))   # defaults to the hotel's currency

	def test_tax_rules_are_validated_and_levies_keep_their_currency(self):
		frappe.set_user("Administrator")  # nosemgrep: frappe-setuser -- finance
		bad = (
			[{"code": "VAT", "kind": "PERCENT", "rate": 10, "applies_to": "ACOMODATION"}],       # typo: taxes nothing
			[{"code": "CITY", "kind": "PER_PERSON_NIGHT", "amount": 2, "applies_to": "EXTRA:*"}],  # a levy is on the stay
			[{"code": "CITY", "kind": "PER_ROOM_NIGHT", "amount": 2, "compound": 1}],
			[{"code": "VAT", "kind": "PERCENT", "rate": 120}],
		)
		for rules in bad:
			with self.assertRaises(frappe.ValidationError, msg=rules):
				frappe.get_doc({"doctype": "TEX Tax Policy", "policy_name": "Bad", "property": fx.PROPERTY,
				                "rules": rules}).insert(ignore_permissions=True)
		fx.ensure_currency("CHF", "CHF")
		self._tax_policy([{"code": "CITY", "tax_name": "City tax", "kind": "PER_PERSON_NIGHT", "amount": 2,
		                   "applies_to": "ACCOMMODATION"}], currency="CHF")
		rules = context.tax_rules(fx.PROPERTY)
		self.assertEqual([(r.code, r.currency, r.amount) for r in rules], [("CITY", "CHF", D("2"))])
		frappe.set_user("Guest")  # nosemgrep: frappe-setuser -- a visitor searching
		res = public.search(site=SLUG, check_in=str(fx.d(6, 10)), check_out=str(fx.d(6, 13)),
		                    rooms=[{"adults": 2}], market="DE", session_id="g20-levy")
		# no CHF→EUR FX policy: the stay is not sold rather than charged "2 EUR"
		self.assertFalse([o for p in res["properties"] for o in p["offers"]])
		frappe.set_user("Administrator")  # nosemgrep: frappe-setuser -- finance sets the rate
		fx.ensure_live("TEX FX Policy", {"property": fx.PROPERTY, "from_currency": "CHF", "to_currency": "EUR"},
		               {"property": fx.PROPERTY, "from_currency": "CHF", "to_currency": "EUR", "mode": "MANUAL",
		                "manual_rate": 1.05})
		frappe.set_user("Guest")  # nosemgrep: frappe-setuser -- the visitor searches again
		res = public.search(site=SLUG, check_in=str(fx.d(6, 10)), check_out=str(fx.d(6, 13)),
		                    rooms=[{"adults": 2}], market="DE", session_id="g20-levy-fx")
		taxes = {t["code"]: t for o in res["properties"][0]["offers"] for t in o["rooms"][0]["quote"]["taxes"]}
		self.assertEqual((D(taxes["CITY"]["amount"]), D(taxes["CITY"]["fx_rate"])),
		                 (D("12.60"), D("1.05")))          # 2 CHF × 2 guests × 3 nights × 1.05

	def test_the_superseded_hotel_tax_table_cannot_be_edited(self):
		frappe.set_user("Administrator")  # nosemgrep: frappe-setuser -- desk admin
		self._tax_policy([{"code": "VAT", "kind": "PERCENT", "rate": 10}])
		prop = frappe.get_doc("Property", fx.PROPERTY)
		prop.append("tex_tax_rules", {"code": "VAT", "kind": "PERCENT", "rate": 20, "applies_to": "ACCOMMODATION"})
		with self.assertRaises(frappe.ValidationError):
			prop.save(ignore_permissions=True)

	def test_two_live_definitions_stop_selling_instead_of_guessing(self):
		frappe.set_user("Administrator")  # nosemgrep: frappe-setuser -- a corrupted catalog
		clone = frappe.copy_doc(frappe.get_doc("TEX Extra", self.trf))
		clone.extra_code = "TRF-COPY"
		clone.insert(ignore_permissions=True)          # then forced live under the same code, past validation
		frappe.db.set_value("TEX Extra", clone.name, {"extra_code": "TRF", "tex_status": "Active",
		                                              "active_from": "2020-01-01"})
		with self.assertRaises(Unsellable):
			context.extras_catalog(fx.PROPERTY)
		self.assertEqual(context.listed_extras(fx.PROPERTY), [])     # lists degrade, never fail a page
		first = self._tax_policy([{"code": "VAT", "kind": "PERCENT", "rate": 10}])
		second = frappe.copy_doc(frappe.get_doc("TEX Tax Policy", first))
		second.insert(ignore_permissions=True)
		frappe.db.set_value("TEX Tax Policy", second.name, {"tex_status": "Active", "active_from": "2020-01-01"})
		frappe.clear_document_cache("TEX Tax Policy")
		with self.assertRaises(Unsellable):
			context.tax_rules(fx.PROPERTY)
		# only this hotel stops selling: a search answers (a multi-hotel site keeps its other hotels)
		frappe.set_user("Guest")  # nosemgrep: frappe-setuser -- a visitor searching
		res = public.search(site=SLUG, check_in=str(fx.d(6, 10)), check_out=str(fx.d(6, 13)),
		                    rooms=[{"adults": 2}], market="DE", session_id="g20-ambiguous")
		self.assertFalse([o for p in res["properties"] for o in p["offers"]])

	def test_an_ambiguous_catalog_is_read_once_per_hotel_in_a_search(self):
		"""2D-1 0c: after Y-5 a search read the hotel's ambiguous extras catalog again for every context
		it priced (contract × room × rate plan × board × party), each time logging an error. It is read
		once per hotel per search: one log, that hotel's offers stay empty, another hotel still sells."""
		other = sellable_other_hotel(self.f)
		frappe.set_user("Administrator")  # nosemgrep: frappe-setuser -- a corrupted catalog
		clone = frappe.copy_doc(frappe.get_doc("TEX Extra", self.trf))
		clone.extra_code = "TRF-COPY"
		clone.insert(ignore_permissions=True)
		frappe.db.set_value("TEX Extra", clone.name, {"extra_code": "TRF", "tex_status": "Active",
		                                              "active_from": "2020-01-01"})
		with mock.patch("frappe.log_error") as log:
			res = quoting.search(properties=[fx.PROPERTY, other], check_in=str(fx.d(6, 10)),
			                     check_out=str(fx.d(6, 13)), rooms=[{"adults": 2}, {"adults": 2}], market="DE",
			                     channel="DIRECT_WEB", currency="EUR")
		ambiguous = [c for c in log.call_args_list if "ambiguous extras" in str(c.kwargs.get("title", ""))]
		self.assertEqual(len(ambiguous), 1, log.call_args_list)
		offers = {p["property"]: p["offers"] for p in res["properties"]}
		self.assertEqual(offers[fx.PROPERTY], [])
		self.assertTrue(offers[other])

	def test_a_draft_with_an_audit_trail_can_be_deleted(self):
		frappe.set_user("Administrator")  # nosemgrep: frappe-setuser -- revenue manager drafts, then drops it
		d = policy_api.save_record("TEX Tax Policy", {"policy_name": "Scratch", "property": fx.PROPERTY,
		                                              "rules": [{"code": "VAT", "kind": "PERCENT", "rate": 8}]})
		self.assertTrue(frappe.db.exists("TEX Audit Event", {"reference_name": d["name"]}))
		policy_api.delete_record("TEX Tax Policy", d["name"])
		self.assertFalse(frappe.db.exists("TEX Tax Policy", d["name"]))
		self.assertTrue(frappe.db.exists("TEX Audit Event", {"reference_name": d["name"]}))  # the trail stays

	def test_a_record_still_in_use_is_never_deleted(self):
		# only the audit trail is ignored on delete: an account that took a payment stays
		b = guest_books(session="g20-in-use")
		frappe.set_user("Administrator")  # nosemgrep: frappe-setuser -- hotel admin
		acc = frappe.db.get_value("TEX Payment Transaction", {"booking": b["booking"]}, "provider_account")
		self.assertTrue(acc)
		with self.assertRaises(frappe.LinkExistsError):
			policy_api.delete_record("TEX Payment Provider Account", acc)
		self.assertTrue(frappe.db.exists("TEX Payment Provider Account", acc))


class TestNonRefundablePolicy(TexTestCase):
	"""Y-4 (ADR-067): a price is refundable only when its rate plan row and its cancellation policy
	both say so. A refundable row on a non-refundable policy is not published; a payload frozen so
	before is read so: search, the quote and the cancellation fee all say non-refundable."""

	def test_a_refundable_row_on_a_non_refundable_policy_is_not_published(self):
		nrf_cxl = frappe.db.get_value("TEX Cancellation Policy", {"property": fx.PROPERTY,
		                                                         "policy_name": "Non-refundable"})
		v = fx.create_contract(self.f, code="Y4-PUB", publish=False)["version"]
		doc = frappe.get_doc("TEX Contract Version", v)
		row = next(r for r in doc.rate_plans if r.rate_plan == self.f["rate_plans"]["FLEX"])
		self.assertEqual(row.refundable, 1)
		row.cancellation_policy = nrf_cxl
		doc.save(ignore_permissions=True)
		issues = contracts.validate_version(v)["issues"]
		self.assertEqual([(i["level"], i["code"]) for i in issues if i["code"] == "RATE_PLAN_REFUNDABLE"],
		                 [("ERROR", "RATE_PLAN_REFUNDABLE")])
		with self.assertRaises(frappe.ValidationError) as cm:
			contracts.publish(v)
		self.assertIn("Non-refundable", str(cm.exception))
		self.assertEqual(frappe.db.get_value("TEX Contract Version", v, "status"), "Draft")

	def test_a_payload_frozen_so_before_sells_and_cancels_as_non_refundable(self):
		setup_site_and_payments(self.f)
		version = frappe.db.get_value("TEX Contract", {"contract_code": "PAY"}, "active_version")
		nr = fx.ensure("TEX Cancellation Policy", {"property": fx.PROPERTY, "policy_name": "Y4 no refunds"},
		               {"property": fx.PROPERTY, "policy_name": "Y4 no refunds", "refundable": 0})
		# what a publish froze before Y-4: the refundable FLEX row with a non-refundable policy without rules
		payload = json.loads(frappe.db.get_value("TEX Contract Version", version, "payload"))
		flex = next(r for r in payload["rate_plans"] if r["code"] == self.f["rate_plans"]["FLEX"])
		self.assertIs(flex["refundable"], True)
		flex["cancellation_policy"] = {"id": nr, "name": "Y4 no refunds", "refundable": False, "rules": [],
		                               "no_show": {"type": "NIGHTS", "value": "1"}, "description": ""}
		frappe.db.set_value("TEX Contract Version", version,
		                    {"payload": json.dumps(payload, sort_keys=True, ensure_ascii=False),
		                     "payload_hash": serialize.payload_hash(payload)}, update_modified=False)
		contracts.clear_terms_cache()

		frappe.set_user("Guest")  # nosemgrep: frappe-setuser -- anonymous booking-engine visitor
		res = public.search(site=SLUG, check_in=str(fx.d(6, 10)), check_out=str(fx.d(6, 13)),
		                    rooms=[{"adults": 2, "children": [8]}], market="DE", session_id="y4-search")
		rt = frappe.db.get_value("Room Type", {"property": fx.PROPERTY, "room_type_code": "STD"})
		offer = next(o for o in res["properties"][0]["offers"]
		             if o["room_type"] == rt and o["board"] == "AI" and o["rate_plan"] == self.f["rate_plans"]["FLEX"])
		self.assertIs(offer["refundable"], False)

		b = guest_books(session="y4-book")
		pmt = b["payment"]
		public.mock_pay(transaction=pmt["transaction"], outcome="success", sig=pmt["fields"]["success_sig"])
		frappe.set_user("Administrator")  # nosemgrep: frappe-setuser -- staff reads the fee
		room = frappe.get_doc("Reservation", {"tex_booking": b["booking"]})
		self.assertIs(json.loads(room.tex_pricing_snapshot)["rate_plan"]["refundable"], False)
		penalty, basis = booking.cancellation_penalty(room, today=fx.d(6, 9))
		self.assertEqual(basis["rule"], "non-refundable")
		self.assertEqual(penalty, D(room.tex_total_amount))
		self.assertGreater(penalty, D(0))


class TestPolicyCurrency(TexTestCase):
	"""Y-3 A (ADR-067, D-1): a payment or cancellation policy's fixed amounts are in the policy's
	currency, or the contract's when it names none; the currency is frozen with a policy that has a
	fixed amount. A fixed policy in another currency than the contract's is not published, so a
	fixed amount converts to the sale's currency at the one contract → sell rate the quote recorded."""

	def fixed_policies(self, currency: str | None = None) -> tuple[str, str]:
		pay = frappe.get_doc({"doctype": "TEX Payment Policy", "property": fx.PROPERTY, "policy_name": "Y3 100 now",
		                      "deposit_type": "FIXED", "deposit_value": 100, "currency": currency}).insert(
			ignore_permissions=True)
		cxl = frappe.get_doc({"doctype": "TEX Cancellation Policy", "property": fx.PROPERTY,
		                      "policy_name": "Y3 150 fee", "refundable": 1, "no_show_type": "NIGHTS",
		                      "no_show_value": 1, "currency": currency,
		                      "rules": [{"days_before_arrival": 7, "penalty_type": "FIXED", "penalty_value": 150}]}
		                     ).insert(ignore_permissions=True)
		return pay.name, cxl.name

	def draft(self, code: str, pay: str, cxl: str) -> str:
		v = fx.create_contract(self.f, code=code, publish=False)["version"]
		doc = frappe.get_doc("TEX Contract Version", v)
		row = next(r for r in doc.rate_plans if r.rate_plan == self.f["rate_plans"]["FLEX"])
		row.payment_policy, row.cancellation_policy = pay, cxl
		doc.save(ignore_permissions=True)
		return v

	def test_a_fixed_policy_in_another_currency_is_not_published(self):
		pay, cxl = self.fixed_policies("TRY")
		v = self.draft("Y3-TRY", pay, cxl)
		issues = contracts.validate_version(v)["issues"]
		self.assertEqual([(i["level"], i["code"]) for i in issues if i["code"] == "POLICY_CURRENCY"],
		                 [("ERROR", "POLICY_CURRENCY")] * 2)
		with self.assertRaises(frappe.ValidationError) as cm:
			contracts.publish(v)
		self.assertIn("are in TRY, the contract's currency is EUR", str(cm.exception))
		self.assertEqual(frappe.db.get_value("TEX Contract Version", v, "status"), "Draft")

	def test_a_fixed_policy_without_a_currency_is_frozen_in_the_contracts(self):
		from kamra.tex.tests.integration.test_contract_offer_currency import _policy

		pay, cxl = self.fixed_policies()
		v = self.draft("Y3-EUR", pay, cxl)
		contracts.publish(v)
		payload = json.loads(frappe.db.get_value("TEX Contract Version", v, "payload"))
		plans = {r["code"]: r for r in payload["rate_plans"]}
		flex, nrf = plans[self.f["rate_plans"]["FLEX"]], plans[self.f["rate_plans"]["NRF"]]
		self.assertEqual((flex["payment_policy"]["currency"], flex["cancellation_policy"]["currency"]), ("EUR", "EUR"))
		self.assertNotIn("currency", nrf["payment_policy"])                  # FULL: no fixed amount, as before
		self.assertNotIn("currency", nrf["cancellation_policy"])             # PERCENT rules: as before

		# the helper Y-3 B uses: 100 EUR is 5,100.00 in a TRY sale at 51, and 100 in a EUR one
		_policy("EUR", "TRY", 51)
		terms = contracts.load_terms(v)
		for sell, due in (("TRY", D("5100.00")), ("EUR", D("100"))):
			req = StayRequest(property=fx.PROPERTY, room_type=self.f["room_types"]["STD"], board="AI",
			                  rate_plan=self.f["rate_plans"]["FLEX"], check_in=fx.d(6, 10), check_out=fx.d(6, 13),
			                  adults=2, sale_at=now_datetime().replace(microsecond=0), market="DE",
			                  channel="DIRECT_WEB", sell_currency=sell)
			q = engine.price_stay(context.build_context(terms, req), req).to_dict(internal=True)
			self.assertEqual(policy_money.fixed_in_sell("100", q["rate_plan"]["payment_policy"], q), due, sell)


	# ── Y-3 B (ADR-067): the booking takes a fixed amount in the sale's currency, once per booking ──

	def quotes(self, sell: str, rooms: int = 1) -> list[str]:
		"""The fixed policies without a currency (frozen in the contract's, EUR) on a published EUR
		contract, sold in ``sell`` at 51 TRY per EUR: the quotes of one search of ``rooms`` rooms."""
		from kamra.tex.tests.integration.test_contract_offer_currency import _policy

		pay, cxl = self.fixed_policies()
		contracts.publish(self.draft("Y3B", pay, cxl))
		_policy("EUR", "TRY", 51)
		res = quoting.search(properties=[fx.PROPERTY], check_in=fx.d(6, 10), check_out=fx.d(6, 13),
		                     rooms=[{"adults": 2}] * rooms, market="DE", channel="DIRECT_WEB", currency=sell)
		offer = pick(res["properties"][0])
		out = quoting.create_quotes([{"offer_key": r["offer_key"], "extras": []}
		                             for r in sorted(offer["rooms"], key=lambda r: r["room_index"])])
		self.assertTrue(out["ok"], out)
		return [r["quote_id"] for r in out["rooms"]]

	def book(self, ids: list[str], key: str, *, confirm: bool = False) -> dict:
		return booking.create_booking(quote_ids=ids, guest=GUEST, payment_method="Card", idempotency_key=key,
		                              confirm_without_payment=confirm)

	def test_a_fixed_deposit_is_converted_to_the_sales_currency(self):
		ids = self.quotes("TRY")
		summary = booking.quotes_summary([quoting.load_quote(q) for q in ids], "Card")
		self.assertEqual((summary["currency"], summary["due_now"]), ("TRY", "5100.00"))   # 100 EUR × 51
		b = self.book(ids, "y3b-try")
		self.assertEqual(frappe.db.get_value("TEX Booking", b["booking"], "amount_due_now"), D("5100.00"))
		self.assertEqual(b["due_now"], "5100.00")
		self.assertEqual(booking.required_now(b["booking"]), D("5100.00"))

	def test_a_fixed_deposit_is_taken_once_per_booking(self):
		ids = self.quotes("EUR", rooms=3)
		summary = booking.quotes_summary([quoting.load_quote(q) for q in ids], "Card")
		self.assertEqual(summary["due_now"], "100.00")
		self.assertEqual([r["due_now"] for r in summary["rooms"]], ["100.00", "0.00", "0.00"])
		b = self.book(ids, "y3b-three")
		self.assertEqual(b["due_now"], "100.00")
		self.assertEqual(booking.required_now(b["booking"]), D("100.00"))
		# room 1 cancelled: the next live room carrying the policy takes the deposit
		first = next(r["reservation"] for r in b["rooms"]
		             if frappe.db.get_value("Reservation", r["reservation"], "tex_room_index") == 1)
		booking.cancel_reservation(first, reason="Y-3 B: room 1 leaves")
		self.assertEqual(frappe.db.get_value("Reservation", first, "status"), "Cancelled")
		self.assertEqual(booking.required_now(b["booking"]), D("100.00"))

	def test_a_fixed_penalty_is_converted_and_explained(self):
		b = self.book(self.quotes("TRY"), "y3b-fee", confirm=True)
		room = frappe.get_doc("Reservation", b["rooms"][0]["reservation"])
		penalty, basis = booking.cancellation_penalty(room, today=fx.d(6, 7))        # 3 days before arrival
		self.assertEqual(penalty, D("7650.00"))                                        # 150 EUR × 51
		self.assertEqual(basis["fx"], {"from": "EUR", "to": "TRY", "rate": "51.000000", "amount": "150.00"})

	def test_a_fixed_deposit_never_exceeds_the_stored_price(self):
		b = self.book(self.quotes("TRY"), "y3b-staff")
		frappe.db.set_value("Reservation", b["rooms"][0]["reservation"], "tex_total_amount", 3000)
		self.assertEqual(booking.required_now(b["booking"]), D("3000.00"))            # min(5,100.00, 3,000.00)

	def test_a_fixed_deposit_falls_to_the_next_room_when_the_first_cannot_take_it(self):
		"""One fixed deposit per booking and payment policy, taken room by room in room order, each room at
		most its own price: a first room priced below the deposit (a price staff set, a booking discount it
		carries) leaves the rest to the next room carrying the policy, never nothing."""
		b = self.book(self.quotes("TRY", rooms=2), "y3b-fall")
		rooms = sorted(b["rooms"], key=lambda r: frappe.db.get_value("Reservation", r["reservation"], "tex_room_index"))
		self.assertGreaterEqual(D(rooms[1]["amount"]), D("5100"))
		for first, due in ((0, D("5100.00")), (3000, D("5100.00")), (6000, D("5100.00"))):
			frappe.db.set_value("Reservation", rooms[0]["reservation"], "tex_total_amount", first)
			self.assertEqual(booking.required_now(b["booking"]), due, first)     # 0 + 5,100; 3,000 + 2,100; 5,100 + 0

	def test_a_stay_sold_before_its_policy_had_a_currency_keeps_the_amount_as_sold(self):
		b = self.book(self.quotes("TRY"), "y3b-old", confirm=True)
		name = b["rooms"][0]["reservation"]
		snap = json.loads(frappe.db.get_value("Reservation", name, "tex_pricing_snapshot"))
		for key in ("payment_policy", "cancellation_policy"):
			self.assertEqual(snap["rate_plan"][key].pop("currency"), "EUR")
		frappe.db.set_value("Reservation", name, "tex_pricing_snapshot", json.dumps(snap, sort_keys=True))
		self.assertEqual(booking.required_now(b["booking"]), D("100.00"))
		penalty, basis = booking.cancellation_penalty(frappe.get_doc("Reservation", name), today=fx.d(6, 7))
		self.assertEqual(penalty, D("150.00"))
		self.assertNotIn("fx", basis)


	def guest_changes(self, room: int) -> tuple[dict, str, dict]:
		"""A confirmed two-room TRY booking of the fixed policies; the guest prices a longer stay of its
		room ``room`` (1: the room that takes the fixed deposit) on the manage page."""
		b = self.book(self.quotes("TRY", rooms=2), f"y3b-change-{room}", confirm=True)
		frappe.db.set_value("Property", fx.PROPERTY, "tex_self_service", 1)
		res = next(r["reservation"] for r in b["rooms"]
		           if frappe.db.get_value("Reservation", r["reservation"], "tex_room_index") == room)
		frappe.set_user("Guest")  # nosemgrep: frappe-setuser -- the guest on the manage page
		return b, res, public.manage_propose(token=b["manage_token"], reservation=res,
		                                     changes={"check_out": str(fx.d(6, 14))})

	def assert_guest_priced(self, b: dict, res: str, up: dict) -> None:
		self.assertTrue(up["sellable"], up)
		self.assertTrue(up["proposal_token"])
		self.assertIsNotNone(up["settlement"])
		seen: set[str] = set()

		def keys(v):
			if isinstance(v, dict):
				seen.update(v)
				for x in v.values():
					keys(x)
			elif isinstance(v, list):
				for x in v:
					keys(x)

		keys(up)
		# what a guest is never told: rates, providers, the rule explanation, cost and margin
		self.assertFalse(seen & {"fx", "fx_rates", "original_fx_rates", "explanation", *quoting.INTERNAL_TOTALS},
		                 seen)
		# the guest accepts it at the price shown
		done = public.manage_apply(token=b["manage_token"], proposal_token=up["proposal_token"])
		self.assertIn(done["status"], ("payment_required", "requested", "applied"), done)
		frappe.set_user("Administrator")  # nosemgrep: frappe-setuser -- read what was recorded
		req = frappe.get_all("TEX Guest Change Request", filters={"reservation": res}, fields=["new_total", "old_total"])
		self.assertEqual(len(req), 1)
		self.assertEqual(D(req[0].new_total) - D(req[0].old_total), D(up["difference"]))

	def test_the_guest_prices_a_change_of_the_room_taking_the_deposit(self):
		b, res, up = self.guest_changes(1)
		self.assert_guest_priced(b, res, up)

	def test_the_guest_prices_a_change_of_another_room(self):
		b, res, up = self.guest_changes(2)
		self.assert_guest_priced(b, res, up)


class TestInfantsNotChildren(TexTestCase):
	"""O-2 (ADR-067, D-2): whether infants are children for combination rules and max_children is a
	version setting. The DocType's default (1) keeps what every version so far priced; a brand-new
	contract's first draft says 0; a draft made from a version keeps its value; a publish freezes
	the key only when it is 0 (every payload frozen so far, and its hash, is as before)."""

	def price(self, version: str, *kid_ages: int) -> D:
		terms = contracts.load_terms(version)
		req = StayRequest(property=fx.PROPERTY, room_type=self.f["room_types"]["STD"], board="AI",
		                  rate_plan=self.f["rate_plans"]["FLEX"], check_in=fx.d(6, 10), check_out=fx.d(6, 11),
		                  adults=1, sale_at=now_datetime().replace(microsecond=0), market="DE", channel="DIRECT_WEB",
		                  sell_currency="EUR", children=tuple(ChildSpec(age=a) for a in kid_ages))
		q = engine.price_stay(context.build_context(terms, req), req)
		self.assertTrue(q.sellable, q.reasons)
		return q.totals["accommodation"]

	def test_a_new_contracts_first_draft_does_not_count_infants_as_children(self):
		from kamra.tex.api import contracts as api

		out = api.save_contract(data={"property": fx.PROPERTY, "contract_code": "O2-NEW", "contract_name": "O2 new",
		                              "market": "DE", "contract_currency": "EUR", "pricing_basis": "PERSON"})
		draft = frappe.db.get_value("TEX Contract Version", {"contract": out["contract"]["name"]},
		                            "infants_count_as_children")
		self.assertEqual(draft, 0)

	def test_a_draft_made_from_a_version_keeps_its_setting(self):
		c = fx.create_contract(self.f, code="O2-OLD")          # inserted without the field: the DocType's 1
		self.assertEqual(frappe.db.get_value("TEX Contract Version", c["version"], "infants_count_as_children"), 1)
		draft = contracts.new_draft(c["contract"])
		self.assertEqual(frappe.db.get_value("TEX Contract Version", draft, "infants_count_as_children"), 1)

	def test_a_publish_freezes_the_setting_only_when_off(self):
		c = fx.create_contract(self.f, code="O2-PUB")
		frozen = json.loads(frappe.db.get_value("TEX Contract Version", c["version"], "payload"))
		self.assertNotIn("infants_count_as_children", frozen["settings"])
		self.assertEqual((self.price(c["version"], 8), self.price(c["version"], 8, 1)), (D("200.00"), D("150.00")))
		draft = contracts.new_draft(c["contract"])
		frappe.db.set_value("TEX Contract Version", draft, "infants_count_as_children", 0)
		contracts.publish(draft)
		frozen = json.loads(frappe.db.get_value("TEX Contract Version", draft, "payload"))
		self.assertIs(frozen["settings"]["infants_count_as_children"], False)
		self.assertEqual((self.price(draft, 8), self.price(draft, 8, 1)), (D("200.00"), D("200.00")))


class TestPromotionSaveChecks(TexTestCase):
	"""Part 2C-2 (ADR-068): a promotion no room could use as saved is refused when a draft is saved or
	activated. A record already live is never refused for it: it stays archivable."""

	def draft(self, **kw) -> str:
		return policy_api.save_record("TEX Promotion", {
			"promotion_name": "2C2 promo", "property": fx.PROPERTY, "value_type": "PERCENT", "value": 10, **kw})["name"]

	def assertRefused(self, fn, *args, **kw):
		with self.assertRaises(frappe.ValidationError):
			fn(*args, **kw)

	def live(self, **kw) -> str:
		"""A promotion put live before the check, then given ``kw`` behind the controller's back."""
		name = self.draft()
		policy_api.activate("TEX Promotion", name, at=str(add_to_date(now_datetime(), minutes=-1)))
		frappe.db.set_value("TEX Promotion", name, kw, update_modified=False)
		return name

	def test_a_discount_on_the_total_or_the_extras_no_room_could_use_is_refused(self):
		"""O-1: on the total or the extras only a percentage or a fixed amount for the stay is applied,
		and a cost-stage offer lowers the accommodation's cost only."""
		for kw in ({"value_type": "MULTIPLIER", "value": "0.9", "applies_to": "TOTAL"},
		           {"value_type": "FIXED_NIGHT", "value": 10, "currency": "EUR", "applies_to": "TOTAL"},
		           {"value_type": "FREE_NIGHTS", "free_nights_stay": 3, "free_nights_pay": 2, "applies_to": "EXTRAS"},
		           {"value_type": "VALUE_ADDED", "value_added": "Spa", "applies_to": "TOTAL"},
		           {"stage": "COST", "applies_to": "EXTRAS"},
		           {"stage": "COST", "applies_to": "TOTAL"}):
			with self.subTest(**kw):
				self.assertRefused(self.draft, **kw)
		for kw in ({"applies_to": "TOTAL"}, {"value_type": "FIXED_STAY", "value": 50, "currency": "EUR",
		                                      "applies_to": "EXTRAS"},
		           {"value_type": "MULTIPLIER", "value": "0.9"}, {"stage": "COST"}):
			with self.subTest(**kw):
				self.assertTrue(self.draft(**kw))

	def test_a_minimum_basket_needs_its_currency(self):
		"""O-7 (D-18): a minimum basket is compared in the promotion's currency, so it names one."""
		self.assertRefused(self.draft, min_basket=1000)
		self.assertEqual(frappe.db.get_value("TEX Promotion", self.draft(min_basket=1000, currency="EUR"), "currency"),
		                 "EUR")
		old = self.live(min_basket=1000, currency=None)
		policy_api.archive("TEX Promotion", old, reason="2C-2 clean-up")
		self.assertEqual(frappe.db.get_value("TEX Promotion", old, "tex_status"), "Archived")

	def test_a_code_with_a_turkish_i_is_stored_by_its_key(self):
		"""O-31: "wİnter" is stored as WINTER (not WİNTER), and a code whose key another draft or live
		promotion of the hotel already has is refused, however it was typed or stored."""
		name = self.draft(trigger="Code", code="wİnter")
		self.assertEqual(frappe.db.get_value("TEX Promotion", name, "code"), "WINTER")
		frappe.db.set_value("TEX Promotion", name, "code", "WİNTER")          # stored before this change
		self.assertRefused(self.draft, trigger="Code", code="winter")

	def test_a_member_only_promotion_is_refused_until_a_sale_knows_members(self):
		"""G-57: no search or quote tells the engine the guest is a member, so a members-only promotion
		never applied. It is refused on a draft's save and activation; a live one stays archivable."""
		self.assertRefused(self.draft, member_only=1)
		name = self.draft()
		frappe.db.set_value("TEX Promotion", name, "member_only", 1)
		self.assertRefused(policy_api.activate, "TEX Promotion", name)
		old = self.live(member_only=1)
		policy_api.archive("TEX Promotion", old, reason="2C-2 clean-up")
		self.assertEqual(frappe.db.get_value("TEX Promotion", old, "tex_status"), "Archived")

	def test_an_unusable_draft_is_not_activated_and_a_live_one_is_archived(self):
		name = self.draft()
		frappe.db.set_value("TEX Promotion", name, {"value_type": "MULTIPLIER", "value": "0.9", "applies_to": "TOTAL"})
		self.assertRefused(policy_api.activate, "TEX Promotion", name)
		self.assertEqual(frappe.db.get_value("TEX Promotion", name, "tex_status"), "Draft")
		old = self.live(stage="COST", applies_to="EXTRAS")
		policy_api.archive("TEX Promotion", old, reason="2C-2 clean-up")
		self.assertEqual(frappe.db.get_value("TEX Promotion", old, "tex_status"), "Archived")


class TestPromotionGroupTies(TexTestCase):
	"""O-4 (D-3): of one group the highest priority is applied, on equal priority the older promotion.
	Saving or activating one that ties with a live promotion of its group (same priority, dates that
	meet) warns, naming it."""

	def eb(self, value: int, **kw) -> dict:
		return policy_api.save_record("TEX Promotion", {
			"promotion_name": f"EB {value}", "property": fx.PROPERTY, "value_type": "PERCENT", "value": value,
			"promo_group": "EB", **kw})

	def activate(self, name: str) -> dict:
		return policy_api.activate("TEX Promotion", name)

	def test_the_second_early_booking_names_the_first(self):
		first = self.eb(10)
		self.assertNotIn("_warnings", self.activate(first["name"]))
		second = self.eb(25)
		for out in (second, self.activate(second["name"])):
			self.assertEqual([(w["code"], w["other"], w["other_name"]) for w in out["_warnings"]],
			                 [("PROMO_GROUP_TIE", first["name"], "EB 10")])
			self.assertIn(first["name"], out["_warnings"][0]["message"])

	def test_another_priority_or_group_is_no_tie(self):
		self.activate(self.eb(10)["name"])
		self.assertNotIn("_warnings", self.eb(25, priority=1))
		self.assertNotIn("_warnings", self.eb(25, promo_group="LS"))
		self.assertNotIn("_warnings", self.eb(25, promo_group=""))


class TestMarkupTies(TexTestCase):
	"""G-53: two live REPLACE markups of one scope and priority whose stay dates meet tie, and the
	engine took the newer silently. Activating the second is refused, naming the first."""

	def markup(self, **kw) -> str:
		return policy_api.save_record("TEX Markup Rule", {"label": "G53", "property": fx.PROPERTY, "market": "DE",
		                                                  "op": "ADJUST_PERCENT", "value": 7, **kw})["name"]

	def test_a_tie_with_a_scheduled_markup_says_so(self):
		first = self.markup()
		policy_api.activate("TEX Markup Rule", first, at=str(add_to_date(now_datetime(), days=1)))
		with self.assertRaises(frappe.ValidationError) as refused:
			policy_api.activate("TEX Markup Rule", self.markup(value=9))
		self.assertIn(f"live or scheduled markup {first}", str(refused.exception))

	def test_an_equal_markup_is_not_activated(self):
		first = self.markup()
		policy_api.activate("TEX Markup Rule", first)
		second = self.markup(value=9)
		with self.assertRaises(frappe.ValidationError) as refused:
			policy_api.activate("TEX Markup Rule", second)
		self.assertIn(f"live markup {first}", str(refused.exception))
		# 2D-1 0f: a tie cannot be revised away at the same priority; the way out is said
		self.assertIn("archive", str(refused.exception))
		self.assertNotIn("revise", str(refused.exception))
		self.assertEqual(frappe.db.get_value("TEX Markup Rule", second, "tex_status"), "Draft")
		# another priority, another scope, stacked, or a revision of the same record: activated
		for kw in ({"priority": 1}, {"room_type": self.f["room_types"]["STD"]}, {"combine": "STACK"}):
			with self.subTest(**kw):
				policy_api.activate("TEX Markup Rule", self.markup(**kw))
		revision = policy_api.revise("TEX Markup Rule", first)["name"]
		policy_api.activate("TEX Markup Rule", revision)
		self.assertEqual(frappe.db.get_value("TEX Markup Rule", revision, "tex_status"), "Active")


class TestPaymentMethodRules(TexTestCase):
	"""O-15 (audit 2F-2, ADR-041): the hotel's payment method rules bind every booking, the guest's and staff's.
	Where a rule matches the sale's market, currency and channel, the method must be one it offers; a hotel with
	no rule for the sale behaves as before; an unknown method is never stored; "Payment Link" is a staff method
	(K-2d) offered where a link can be paid (a card rule for the web)."""

	def setUp(self):
		super().setUp()
		setup_site_and_payments(self.f)
		self.rule = lambda method: frappe.db.get_value("TEX Payment Method Rule",
		                                               {"property": fx.PROPERTY, "method": method})

	def quote(self, channel: str = "DIRECT_WEB", user: str = "Administrator") -> str:
		"""An open quote of the STD / FLEX offer, made as ``user``."""
		frappe.set_user(user)  # nosemgrep: frappe-setuser -- the seller of the quote
		res = quoting.search(properties=[fx.PROPERTY], check_in=fx.d(6, 10), check_out=fx.d(6, 13),
		                     rooms=[{"adults": 2}], market="DE", channel=channel, currency="EUR")
		offer = pick(res["properties"][0])
		return quoting.create_quote(offer["rooms"][0]["offer_key"])["quote_id"]

	def assertOpen(self, quote_id: str) -> None:
		self.assertEqual(frappe.db.get_value("TEX Quote", quote_id, "status"), "Open")

	def test_a_disabled_pay_at_hotel_rule_refuses_the_guest_and_the_quote_stays_open(self):
		frappe.db.set_value("TEX Payment Method Rule", self.rule("Pay at Hotel"), "disabled", 1)
		qid = self.quote(user="Guest")
		with self.assertRaisesRegex(frappe.ValidationError, "not available"):
			public.book(site=SLUG, quote_ids=[qid], guest=GUEST, payment_method="Pay at Hotel", session_id="o15-a",
			            idempotency_key="idem-o15-a")
		self.assertOpen(qid)
		self.assertFalse(frappe.db.exists("TEX Booking", {"booker_email": GUEST["email"]}))

	def test_an_unknown_method_is_never_stored(self):
		qid = self.quote()
		with self.assertRaisesRegex(frappe.ValidationError, "not available"):
			ui_crs.book(quote_ids=[qid], guest=GUEST, payment_method="X")
		self.assertOpen(qid)
		self.assertFalse(frappe.db.exists("TEX Booking", {"payment_method": "X"}))

	def test_a_rule_for_another_channel_does_not_offer_pay_at_hotel_at_the_call_centre(self):
		frappe.db.set_value("TEX Payment Method Rule", self.rule("Pay at Hotel"), "sales_channel", "DIRECT_WEB")
		web, desk = self.quote("DIRECT_WEB"), self.quote("CALL_CENTER")
		with self.assertRaisesRegex(frappe.ValidationError, "not available"):
			booking.create_booking(quote_ids=[desk], guest=GUEST, payment_method="Pay at Hotel")
		self.assertOpen(desk)
		self.assertEqual(booking.create_booking(quote_ids=[web], guest=GUEST, payment_method="Pay at Hotel")["status"],
		                 "Confirmed")

	def test_payment_link_is_a_staff_method_offered_where_a_link_can_be_paid(self):
		qid = self.quote()
		frappe.set_user("Guest")  # nosemgrep: frappe-setuser -- a guest names a staff method
		with self.assertRaisesRegex(frappe.ValidationError, "not available"):
			booking.create_booking(quote_ids=[qid], guest=GUEST, payment_method="Payment Link")
		self.assertOpen(qid)
		frappe.set_user("Administrator")  # nosemgrep: frappe-setuser -- staff
		out = booking.create_booking(quote_ids=[qid], guest=GUEST, payment_method="Payment Link")
		self.assertEqual(out["status"], "Pending Payment")
		sale_at = frappe.db.get_value("TEX Booking", out["booking"], "sale_at")
		until = frappe.get_all("Reservation", filters={"tex_booking": out["booking"]}, pluck="hold_expires_on")[0]
		self.assertEqual(round((until - sale_at).total_seconds() / 60), 1440)       # K-2d: 24 hours
		# a link is paid by card on the web: where that is not offered, staff may not name it either
		frappe.db.set_value("TEX Payment Method Rule", self.rule("Card"), "disabled", 1)
		again = self.quote()
		with self.assertRaisesRegex(frappe.ValidationError, "not available"):
			booking.create_booking(quote_ids=[again], guest=GUEST, payment_method="Payment Link")

	def test_a_hotel_with_no_rule_behaves_as_before(self):
		frappe.db.delete("TEX Payment Method Rule", {"property": fx.PROPERTY})
		for method, status in (("Pay at Hotel", "Confirmed"), ("Bank Transfer", "Pending Payment"),
		                       (None, "Pending Payment")):
			with self.subTest(method=method):
				out = booking.create_booking(quote_ids=[self.quote()], guest=GUEST, payment_method=method)
				self.assertEqual(out["status"], status)

