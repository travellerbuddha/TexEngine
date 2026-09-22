"""TEX flows around a booking: guest booking API with the sandbox gateway, payment
idempotency, refunds, transfers, payment links, guest self-service, CRM consent,
loyalty, abandoned-booking detection, reports and tenant isolation."""

import frappe
from frappe.utils import add_to_date, now_datetime

from kamra.tex.api import crm as crm_api
from kamra.tex.api import payments as pay_api
from kamra.tex.api import policies as policy_api
from kamra.tex.api import public
from kamra.tex.crm import loyalty
from kamra.tex.crm import service as crm
from kamra.tex.money import D
from kamra.tex.payments import service as pay
from kamra.tex.payments.providers.base import ProviderError
from kamra.tex.reports import service as reports
from kamra.tex.security import scope
from kamra.tex.services import booking
from kamra.tex.tests.integration import fixtures as fx
from kamra.tex.tests.integration.test_critical_journey import TexTestCase

SLUG = "tex-test-resort"
GUEST = {"first_name": "Lena", "last_name": "Kraus", "email": "lena@example.com", "country": "Germany"}


def setup_site_and_payments(f: dict) -> dict:
	fx.create_contract(f, code="PAY")
	fx.create_markup("DE", 7)
	acc = fx.ensure("TEX Payment Provider Account", {"property": fx.PROPERTY, "provider": "Mock"},
	                {"label": "Sandbox gateway", "property": fx.PROPERTY, "provider": "Mock",
	                 "environment": "Sandbox", "enabled": 1, "currencies": "EUR"})
	fx.ensure("TEX Payment Method Rule", {"property": fx.PROPERTY, "method": "Card"},
	          {"property": fx.PROPERTY, "method": "Card", "provider_account": acc, "priority": 10})
	if not frappe.db.exists("TEX Booking Site", SLUG):
		frappe.get_doc({"doctype": "TEX Booking Site", "site_name": "TEX Test Resort", "site_slug": SLUG,
		                "enabled": 1, "property": fx.PROPERTY, "default_market": "DE", "default_currency": "EUR",
		                "currencies": "EUR", "self_service_enabled": 1}).insert(ignore_permissions=True)
	return {"account": acc}


def guest_books(session="sess-1", method="Card", guest=None) -> dict:
	"""search → quote → book through the public API, as an anonymous visitor."""
	frappe.set_user("Guest")  # nosemgrep: frappe-setuser -- anonymous booking-engine visitor
	res = public.search(site=SLUG, check_in=str(fx.d(6, 10)), check_out=str(fx.d(6, 13)),
	                    rooms=[{"adults": 2, "children": [8]}], market="DE", session_id=session)
	prop = res["properties"][0]
	rt = frappe.db.get_value("Room Type", {"property": fx.PROPERTY, "room_type_code": "STD"})
	rp = frappe.db.get_value("Rate Plan", {"property": fx.PROPERTY, "code": "FLEX"})
	offer = next(o for o in prop["offers"] if o["room_type"] == rt and o["board"] == "AI" and o["rate_plan"] == rp)
	assert "contract" not in offer, "guest offers must not expose contract ids"
	q = public.quote(site=SLUG, offer_key=offer["rooms"][0]["offer_key"], extras=[{"code": "TRF", "quantity": 1}],
	                 session_id=session)
	assert q["ok"], q
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

		# a forged signature is rejected and changes nothing
		with self.assertRaises(ProviderError):
			public.mock_pay(transaction=txn, outcome="success", sig="0" * 64)
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
		done = public.manage_apply(token=token, proposal_token=up["proposal_token"])
		self.assertEqual(done["status"], "applied")
		self.assertEqual(frappe.db.get_value("Reservation", res, "tex_guest_change_pending"), 1)
		self.assertEqual(str(frappe.db.get_value("Reservation", res, "check_out_date")), str(fx.d(6, 14)))
		total_after = D(frappe.db.get_value("Reservation", res, "tex_total_amount"))

		down = public.manage_propose(token=token, reservation=res, changes={"check_out": str(fx.d(6, 12))})
		self.assertLess(D(down["difference"]), 0)
		req = public.manage_apply(token=token, proposal_token=down["proposal_token"])
		self.assertEqual(req["status"], "requested")             # default policy: staff approval
		self.assertEqual(D(frappe.db.get_value("Reservation", res, "tex_total_amount")), total_after)

		# a token only reaches its own booking
		other = self._paid_booking("sess-ss2")
		with self.assertRaises(frappe.PermissionError):
			public.manage_cancel(token=token, reservation=other["rooms"][0]["reservation"])

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
		self.assertIn("DE guests", prof["segments"])
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

