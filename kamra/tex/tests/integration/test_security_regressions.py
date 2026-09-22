"""Regression tests for the adversarial security review (ADR-021, ADR-022).

H1 forged callbacks cannot fail a payment · H2 a guest cannot route a payment link
through another gateway · H3 idempotency replays never return a stranger's booking ·
H4 Desk/REST cannot bypass capabilities, scope, revision lifecycle or cost hiding ·
M2 guests of other tenants stay invisible · L4 shared FX rates are platform-only.
"""

import frappe

from kamra.tex.api import payments as pay_api
from kamra.tex.api import policies as policy_api
from kamra.tex.api import public
from kamra.tex.payments import service as pay
from kamra.tex.payments.providers.base import ProviderError
from kamra.tex.security import scope
from kamra.tex.services import booking, modification
from kamra.tex.tests.integration import fixtures as fx
from kamra.tex.tests.integration.test_commercial_flows import (
	GUEST,
	SLUG,
	guest_books,
	setup_site_and_payments,
)
from kamra.tex.tests.integration.test_critical_journey import TexTestCase

OTHER = "TEX Security Other Hotel"


def other_hotel_with_mock() -> str:
	if not frappe.db.exists("Property", OTHER):
		frappe.get_doc({"doctype": "Property", "property_name": OTHER, "city": "Side", "country": "Turkey",
		                "currency": "EUR"}).insert(ignore_permissions=True)
	return fx.ensure("TEX Payment Provider Account", {"property": OTHER, "provider": "Mock"},
	                 {"label": "Other sandbox", "property": OTHER, "provider": "Mock", "environment": "Sandbox",
	                  "enabled": 1, "currencies": "EUR"})


class TestPaymentIntegrity(TexTestCase):
	def setUp(self):
		super().setUp()
		self.p = setup_site_and_payments(self.f)

	def test_h1_unverifiable_callbacks_leave_the_payment_pending(self):
		b = guest_books(session="sec-h1")
		txn = b["payment"]["transaction"]
		with self.assertRaises(ProviderError):                     # unknown outcome is not "Failed"
			public.mock_pay(transaction=txn, outcome="nope", sig="x")
		with self.assertRaises(ProviderError):
			public.mock_pay(transaction=txn, outcome="fail", sig="0" * 64)
		self.assertEqual(frappe.db.get_value("TEX Payment Transaction", txn, "status"), "Pending")
		frappe.form_dict.update({"txn": txn, "cb": "forged"})
		try:
			with self.assertRaises(frappe.DoesNotExistError):         # unsigned return URL goes nowhere
				pay_api.callback(txn=txn)
		finally:
			frappe.form_dict.pop("cb", None)
			frappe.form_dict.pop("txn", None)
		ok = public.mock_pay(transaction=txn, outcome="success", sig=b["payment"]["fields"]["success_sig"])
		self.assertEqual(ok["status"], "Succeeded")                 # the genuine result still lands

	def test_h2_payment_link_cannot_use_another_gateway(self):
		foreign = other_hotel_with_mock()
		bank = fx.ensure("TEX Payment Provider Account", {"property": fx.PROPERTY, "provider": "Bank Transfer"},
		                 {"label": "Bank", "property": fx.PROPERTY, "provider": "Bank Transfer",
		                  "environment": "Sandbox", "enabled": 1})
		frappe.set_user("Administrator")  # nosemgrep: frappe-setuser -- agent creates the link
		link = pay.create_link(property=fx.PROPERTY, amount="1", currency="EUR", description="deposit",
		                       provider_account=bank)
		frappe.set_user("Guest")  # nosemgrep: frappe-setuser -- anonymous payer
		with self.assertRaises(frappe.ValidationError):
			public.pay_link(token=link["token"], provider_account=foreign)
		frappe.set_user("Administrator")  # nosemgrep: frappe-setuser -- service-level check
		with self.assertRaises(frappe.PermissionError):
			pay.start_payment(property=fx.PROPERTY, amount="1", currency="EUR", provider_account=foreign,
			                  description="x", customer={}, return_url=frappe.utils.get_url("/book/x"),
			                  idempotency_key="sec-h2")
		with self.assertRaises(frappe.ValidationError):             # open redirect refused in the service
			pay.start_payment(property=fx.PROPERTY, amount="1", currency="EUR", provider_account=self.p["account"],
			                  description="x", customer={}, return_url="https://evil.example.com/",
			                  idempotency_key="sec-h2b")

	def test_h3_idempotency_replay_is_scoped_to_the_caller(self):
		first = guest_books(session="sec-h3-a")
		frappe.set_user("Guest")  # nosemgrep: frappe-setuser -- a different visitor, same key
		res = public.search(site=SLUG, check_in=str(fx.d(6, 10)), check_out=str(fx.d(6, 13)),
		                    rooms=[{"adults": 2}], market="DE", session_id="sec-h3-b")
		offer = res["properties"][0]["offers"][0]
		q = public.quote(site=SLUG, offer_key=offer["rooms"][0]["offer_key"], session_id="sec-h3-b")
		second = public.book(site=SLUG, quote_ids=[q["quote_id"]], guest={**GUEST, "email": "b@example.com"},
		                     payment_method="Card", session_id="sec-h3-b", idempotency_key="idem-sec-h3-a")
		self.assertNotEqual(second["booking"], first["booking"])
		self.assertFalse(second.get("idempotent_replay"))

	def test_m1_proposals_expire_and_are_not_offers(self):
		b = guest_books(session="sec-m1")
		frappe.set_user("Administrator")  # nosemgrep: frappe-setuser -- staff
		p = modification.propose(b["rooms"][0]["reservation"], {"check_out": str(fx.d(6, 14))})
		with self.assertRaises(frappe.ValidationError):
			public.quote(site=SLUG, offer_key=p["proposal_token"])  # a proposal is never an offer
		from kamra.tex.services import quoting

		self.assertIsNotNone(quoting.verify(p["proposal_token"], kind="proposal").get("exp"))


class TestRestBypass(TexTestCase):
	def setUp(self):
		super().setUp()
		setup_site_and_payments(self.f)
		self.agent = fx.ensure_user("sec-agent@example.com", ["Call Center Agent", "Front Desk"])
		fx.ensure("TEX Access Grant", {"user": self.agent, "property": fx.PROPERTY},
		          {"user": self.agent, "scope_level": "Hotel", "property": fx.PROPERTY,
		           "permission_profile": "Reservations Agent"})
		other_hotel_with_mock()
		self.gm = fx.ensure_user("sec-gm@example.com", ["Hotel Admin"])
		fx.ensure("TEX Access Grant", {"user": self.gm, "property": OTHER},
		          {"user": self.gm, "scope_level": "Hotel", "property": OTHER, "permission_profile": "Hotel Admin"})
		scope.clear_cache()

	def test_h4_business_roles_cannot_write_tex_doctypes_directly(self):
		for dt in ("TEX Promotion", "TEX Markup Rule", "TEX Contract", "TEX Booking", "TEX Payment Link",
		           "TEX Permission Profile", "TEX Payment Provider Account"):
			for user in (self.agent, self.gm):
				for ptype in ("write", "create"):
					self.assertFalse(frappe.has_permission(dt, ptype, user=user), f"{user} {ptype} {dt}")
		# cost-bearing revisions are not readable by agents at all
		self.assertFalse(frappe.has_permission("TEX Reservation Revision", "read", user=self.agent))

	def test_h4_hotel_admin_reads_only_own_hotel(self):
		b = guest_books(session="sec-h4")
		frappe.set_user(self.gm)  # nosemgrep: frappe-setuser -- other hotel's admin
		scope.clear_cache()
		self.assertEqual(frappe.get_list("TEX Booking", filters={"name": b["booking"]}, pluck="name"), [])
		rev = frappe.get_list("TEX Reservation Revision", pluck="name")
		mine = frappe.get_all("TEX Reservation Revision", filters={"booking": b["booking"]}, pluck="name")
		self.assertFalse(set(mine) & set(rev))
		guest = frappe.db.get_value("TEX Booking", b["booking"], "booker_guest")
		self.assertNotIn(guest, frappe.get_list("Guest", pluck="name"))          # M2
		self.assertFalse(frappe.has_permission("Guest", "read", doc=frappe.get_doc("Guest", guest)))
		self.assertEqual(frappe.get_list("TEX Audit Event", filters={"property": fx.PROPERTY}, pluck="name"), [])

	def test_h4_new_policy_rows_are_always_drafts(self):
		doc = frappe.get_doc({"doctype": "TEX Promotion", "promotion_name": "sneaky", "property": fx.PROPERTY,
		                      "trigger": "Code", "code": "SNEAKY", "value_type": "PERCENT", "value": 50,
		                      "tex_status": "Active", "active_from": frappe.utils.now_datetime(),
		                      "times_redeemed": 0}).insert(ignore_permissions=True)
		self.assertEqual((doc.tex_status, doc.active_from), ("Draft", None))

	def test_h4_modification_hides_cost_without_price_view_cost(self):
		b = guest_books(session="sec-cost")
		frappe.set_user(self.agent)  # nosemgrep: frappe-setuser -- agent without price.view_cost
		scope.clear_cache()
		self.assertFalse(scope.has_capability("price.view_cost", fx.PROPERTY))
		p = modification.propose(b["rooms"][0]["reservation"], {"check_out": str(fx.d(6, 14))})
		self.assertNotIn("cost", p["proposed"]["totals"])
		self.assertNotIn("margin", p["proposed"]["totals"])
		self.assertNotIn("explanation", p["proposed"])
		self.assertNotIn("cost", p["old"]["totals"] or {})
		self.assertTrue(all("cost" not in n for n in p["proposed"]["nights"]))

	def test_staff_idempotency_replay_is_per_user(self):
		frappe.set_user("Administrator")  # nosemgrep: frappe-setuser -- staff booking
		first = guest_books(session="sec-staff-a")
		key = booking.scoped_idempotency_key("same-key", staff=True, booking_site=None, session_id=None)
		frappe.set_user(self.agent)  # nosemgrep: frappe-setuser -- another staff user
		other = booking.scoped_idempotency_key("same-key", staff=True, booking_site=None, session_id=None)
		self.assertNotEqual(key, other)
		self.assertTrue(first["booking"])

	def test_l4_fx_rates_are_platform_only(self):
		frappe.set_user(self.gm)  # nosemgrep: frappe-setuser -- hotel admin
		scope.clear_cache()
		with self.assertRaises(frappe.PermissionError):
			policy_api.add_manual_rate("EUR", "TRY", "48.10", frappe.utils.nowdate())

	def test_group_sites_listed_only_for_their_group(self):
		grp = frappe.db.get_value("Property", fx.PROPERTY, "tex_hotel_group")
		site = frappe.get_doc({"doctype": "TEX Booking Site", "site_name": "Group site", "site_slug": "sec-group-site",
		                       "enabled": 1, "hotel_group": grp}).insert(ignore_permissions=True)
		frappe.set_user(self.gm)  # nosemgrep: frappe-setuser -- admin of a hotel outside the group
		scope.clear_cache()
		names = [r["name"] for r in policy_api.list_records(doctype="TEX Booking Site", property=OTHER)]
		self.assertNotIn(site.name, names)
		frappe.set_user(self.agent)  # nosemgrep: frappe-setuser -- a user of the group's hotel sees it
		scope.clear_cache()
		self.assertIn(site.name, [r["name"] for r in policy_api.list_records(doctype="TEX Booking Site")])
