"""Regression tests for the adversarial security review (ADR-021, ADR-022).

H1 forged callbacks cannot fail a payment · H2 a guest cannot route a payment link
through another gateway · H3 idempotency replays never return a stranger's booking ·
H4 Desk/REST cannot bypass capabilities, scope, revision lifecycle or cost hiding ·
M2 guests of other tenants stay invisible · L4 shared FX rates are platform-only ·
G-91 the session carries the site's day and time zone.
"""

import hashlib
import hmac
from unittest import mock

import frappe
from frappe.utils import add_days, add_to_date, now_datetime, nowdate

from kamra.tex.api import payments as pay_api
from kamra.tex.api import policies as policy_api
from kamra.tex.api import public
from kamra.tex.money import D
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

	def test_g11_agents_never_see_contract_cost(self):
		from kamra.tex.api import contracts as contract_api
		from kamra.tex.api import crs as crs_api

		contract = frappe.db.get_value("TEX Contract", {"property": fx.PROPERTY}, "name")
		version = frappe.db.get_value("TEX Contract Version", {"contract": contract, "status": "Published"}, "name")
		fx.create_markup()
		frappe.set_user(self.agent)  # nosemgrep: frappe-setuser -- a reservations agent sells, it never sees cost
		scope.clear_cache()
		info = contract_api.get_version(version)                 # what the modify drawer needs, nothing more
		self.assertTrue(info["cost_hidden"])
		self.assertLessEqual(set(info), {"name", "contract", "version_no", "status", "rooms", "boards", "rate_plans",
		                                 "room_types", "rate_plan_options", "contract_doc", "editable", "cost_hidden"})
		self.assertTrue(all(set(r) <= {"room_type"} for r in info["rooms"]))
		self.assertTrue(all(set(b) <= {"board"} for b in info["boards"]))
		self.assertTrue(all(set(r) <= {"rate_plan", "refundable"} for r in info["rate_plans"]))
		with self.assertRaises(frappe.PermissionError):
			contract_api.price_matrix(version)
		with self.assertRaises(frappe.PermissionError):
			policy_api.list_records(doctype="TEX Markup Rule", property=fx.PROPERTY)
		grid = crs_api.ari_grid(property=fx.PROPERTY, start=str(fx.d(6, 10)), days=3, contract=contract)
		self.assertTrue(all("rate" not in c and "draft_rate" not in c for r in grid["rows"] for c in r["cells"]))
		# a contract is only graphed on its own hotel (G-83)
		frappe.set_user(self.gm)  # nosemgrep: frappe-setuser -- another hotel's admin
		scope.clear_cache()
		with self.assertRaises(frappe.ValidationError):
			crs_api.ari_grid(property=OTHER, start=str(fx.d(6, 10)), days=3, contract=contract)
		# revenue management still sees everything
		frappe.set_user("Administrator")  # nosemgrep: frappe-setuser -- platform administrator
		self.assertIn("period_rates", contract_api.get_version(version))
		self.assertTrue(contract_api.price_matrix(version)["rooms"])
		grid = crs_api.ari_grid(property=fx.PROPERTY, start=str(fx.d(6, 10)), days=3, contract=contract)
		self.assertTrue(any(c.get("rate") for r in grid["rows"] for c in r["cells"]))

	def test_g13_a_draft_is_never_based_on_another_hotels_contract(self):
		from kamra.tex.commercial import contracts as contract_svc

		victim = frappe.db.get_value("TEX Contract", {"property": fx.PROPERTY}, "name")
		victim_version = frappe.db.get_value("TEX Contract Version", {"contract": victim, "status": "Published"},
		                                     "name")
		victim_drafts = frappe.db.count("TEX Contract Version", {"contract": victim, "status": "Draft"})
		own = frappe.get_doc({"doctype": "TEX Contract", "property": OTHER, "contract_code": "SEC-OWN",
		                      "contract_name": "Own contract", "market": "DE", "contract_currency": "EUR",
		                      "pricing_basis": "PERSON", "status": "Draft"}).insert(ignore_permissions=True).name
		frappe.set_user(self.gm)  # nosemgrep: frappe-setuser -- may edit contracts of its own hotel only
		scope.clear_cache()
		with self.assertRaises(frappe.PermissionError):
			contract_svc.new_draft(own, based_on=victim_version)
		frappe.set_user("Administrator")  # nosemgrep: frappe-setuser -- verify nothing was created
		self.assertEqual(frappe.db.count("TEX Contract Version", {"contract": victim, "status": "Draft"}), victim_drafts)
		self.assertFalse(frappe.db.exists("TEX Contract Version", {"contract": own}))

	def test_g12_a_hotels_grant_decides_over_frappe_role_defaults(self):
		viewer = fx.ensure_user("sec-viewer@example.com", ["Hotel Admin"])   # Frappe role: all TEX capabilities
		fx.ensure("TEX Access Grant", {"user": viewer, "property": fx.PROPERTY},
		          {"user": viewer, "scope_level": "Hotel", "property": fx.PROPERTY, "permission_profile": "Viewer"})
		frappe.set_user(viewer)  # nosemgrep: frappe-setuser -- granted only "Viewer" at this hotel
		scope.clear_cache()
		self.assertTrue(scope.has_capability("price.view", fx.PROPERTY))
		for cap in ("payment.refund", "contract.publish", "user.admin", "price.view_cost"):
			self.assertFalse(scope.has_capability(cap, fx.PROPERTY), cap)
			self.assertFalse(scope.has_capability(cap, None), cap)
		frappe.set_user(self.gm)  # nosemgrep: frappe-setuser -- a "Hotel Admin" grant still means all of it
		scope.clear_cache()
		self.assertTrue(scope.has_capability("payment.refund", OTHER))

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


class TestPriceLock(TexTestCase):
	"""G-01: a TEX-sold reservation cannot change commercially except through the TEX
	modification / cancellation services — not by unlocking and editing in one save, not by
	editing the snapshot, not alongside a status change."""

	def setUp(self):
		super().setUp()
		setup_site_and_payments(self.f)
		b = guest_books(session="sess-lock")
		frappe.set_user("Administrator")  # nosemgrep: frappe-setuser -- a Desk/REST writer with full rights
		self.res = b["rooms"][0]["reservation"]

	def _doc(self):
		return frappe.get_doc("Reservation", self.res)

	def test_unlock_and_edit_in_one_save_is_refused(self):
		doc = self._doc()
		doc.tex_price_locked = 0
		doc.tex_pricing_source = "Manual"
		doc.amount_after_tax = (doc.amount_after_tax or 0) + 100
		with self.assertRaises(frappe.ValidationError):
			doc.save()
		# unlocking alone is also a change of the commercial record
		doc = self._doc()
		doc.tex_price_locked = 0
		doc.tex_pricing_source = "Manual"
		with self.assertRaises(frappe.ValidationError):
			doc.save()

	def test_snapshot_fx_and_cost_cannot_be_edited(self):
		for field, value in (("tex_pricing_snapshot", '{"rate_plan": {"refundable": true}}'),
		                     ("tex_currency", "TRY"), ("tex_fx_rate", 99), ("tex_cost_amount", 1),
		                     ("tex_contract", None)):
			doc = self._doc()
			doc.set(field, value)
			with self.assertRaises(frappe.ValidationError, msg=field):
				doc.save()

	def test_status_change_does_not_open_the_lock(self):
		frappe.flags.kamra_status_transition = True   # as the legacy status flow does
		try:
			doc = self._doc()
			doc.status = "No Show"
			doc.amount_after_tax = 1
			with self.assertRaises(frappe.ValidationError):
				doc.save()
			doc = self._doc()
			doc.status = "Cancelled"
			doc.cancellation_fee = 0   # a TEX stay takes its penalty only from the TEX service
			before = frappe.db.get_value("Reservation", self.res, "cancellation_fee")
			if (before or 0) != 0:
				with self.assertRaises(frappe.ValidationError):
					doc.save()
		finally:
			frappe.flags.kamra_status_transition = False

	def test_non_commercial_edits_and_tex_services_still_work(self):
		doc = self._doc()
		doc.special_requests = "Quiet room, please"
		doc.save()
		self.assertEqual(frappe.db.get_value("Reservation", self.res, "special_requests"), "Quiet room, please")
		# the TEX cancellation service applies the frozen policy
		out = booking.cancel_reservation(self.res, reason="guest request")
		self.assertEqual(frappe.db.get_value("Reservation", self.res, "status"), "Cancelled")
		self.assertIn("penalty", out)


# argument names that always name a record in the legacy Kamra modules (G-02)
LEGACY_RECORD_ARGS = {"order", "task", "ticket", "session", "account", "function", "outlet", "menu", "menu_item",
                      "ingredient", "venue", "connection", "guest", "service_item", "from_folio", "to_folio",
                      "folios", "new_room", "name", "group"}
# checked inside the endpoint instead (linked_records resolves `doctype` + `name` itself)
LEGACY_CHECKED_IN_BODY = {("kamra.api.linked_records", "name")}
LEGACY_MODULES = ("kamra.api", "kamra.agents_api", "kamra.assistant", "kamra.banquet", "kamra.banquet_ops",
                  "kamra.cashier", "kamra.channel_manager", "kamra.inventory", "kamra.laundry", "kamra.ledger",
                  "kamra.marketplace", "kamra.menu_import", "kamra.pos", "kamra.whatsapp", "kamra.crs",
                  "kamra.dashboards", "kamra.accounting", "kamra.allocation", "kamra.reports")


class TestLegacyTenancy(TexTestCase):
	"""G-02: legacy Kamra endpoints resolve every record argument (guest, POS order, action
	log, hurdle rate ...) to its hotel, and their lists only show the caller's hotels.
	G-16: with the PMS modules switched off, they are closed to hotel users altogether."""

	def setUp(self):
		super().setUp()
		frappe.db.set_single_value("TEX Settings", "show_legacy_pms", 1)  # a site that runs the PMS
		setup_site_and_payments(self.f)
		other_hotel_with_mock()
		self.gm = fx.ensure_user("sec-gm@example.com", ["Hotel Admin"])
		fx.ensure("TEX Access Grant", {"user": self.gm, "property": OTHER},
		          {"user": self.gm, "scope_level": "Hotel", "property": OTHER, "permission_profile": "Hotel Admin"})
		b = guest_books(session="sec-g02")  # this guest has stayed only at the test resort
		frappe.set_user("Administrator")  # nosemgrep: frappe-setuser -- fixtures
		self.reservation = b["rooms"][0]["reservation"]
		self.guest = frappe.db.get_value("Reservation", self.reservation, "guest")
		self.guest_name = frappe.db.get_value("Guest", self.guest, "full_name")
		self.twin = frappe.get_doc({"doctype": "Guest", "first_name": "Sec", "last_name": "Twin",
		                            "full_name": "Sec Twin"}).insert(ignore_permissions=True).name
		outlet = fx.ensure("POS Outlet", {"property": fx.PROPERTY, "outlet_name": "Sec Bar"},
		                   {"property": fx.PROPERTY, "outlet_name": "Sec Bar"})
		self.order = frappe.get_doc({"doctype": "POS Order", "property": fx.PROPERTY,
		                             "outlet": outlet}).insert(ignore_permissions=True).name
		self.log = frappe.get_doc({"doctype": "Agent Action Log", "property": fx.PROPERTY,
		                           "action_type": "sec_probe"}).insert(ignore_permissions=True).name
		self.own_log = frappe.get_doc({"doctype": "Agent Action Log", "property": OTHER,
		                               "action_type": "sec_probe"}).insert(ignore_permissions=True).name
		self.hurdle = frappe.get_doc({"doctype": "Hurdle Rate", "property": fx.PROPERTY,
		                              "occupancy_from": 80}).insert(ignore_permissions=True).name
		scope.clear_cache()
		frappe.set_user(self.gm)  # nosemgrep: frappe-setuser -- the other hotel's GM probes

	def test_another_hotels_guest_is_not_listed_or_opened(self):
		from kamra import api

		self.assertNotIn(self.guest, [g.name for g in api.guests_with_stats()])
		self.assertEqual(api.guests_with_stats(search=self.guest_name), [])
		self.assertEqual(api.guest_search(q=self.guest_name), [])
		for call in (lambda: api.guest_journey(guest=self.guest),
		             lambda: api.linked_records(doctype="Guest", name=self.guest),
		             lambda: api.linked_records(doctype="Reservation", name=self.reservation)):
			with self.assertRaises(frappe.PermissionError):
				call()
		with self.assertRaises(frappe.ValidationError):
			api.linked_records(doctype="User", name="Administrator")

	def test_another_hotels_guest_cannot_be_erased_or_merged(self):
		from kamra import api

		with self.assertRaises(frappe.PermissionError):
			api.anonymize_guest(guest=self.guest)
		with self.assertRaises(frappe.PermissionError):
			api.merge_guests(source=self.guest, target=self.twin)
		with self.assertRaises(frappe.PermissionError):
			api.merge_guests(source=self.twin, target=self.guest)
		self.assertEqual(frappe.db.get_value("Guest", self.guest, "full_name"), self.guest_name)
		self.assertTrue(frappe.db.exists("Guest", self.twin))

	def test_another_hotels_records_are_refused_by_id(self):
		from kamra import agents_api, api, assistant, pos

		for call in (lambda: pos.order_detail(order=self.order),
		             lambda: pos.cancel_order(order=self.order, reason="probe"),
		             lambda: api.delete_hurdle_rate(name=self.hurdle),
		             lambda: agents_api.activity_detail(name=self.log),
		             lambda: assistant.assistant_status(property=fx.PROPERTY)):
			with self.assertRaises(frappe.PermissionError):
				call()
		self.assertTrue(frappe.db.exists("Hurdle Rate", self.hurdle))
		self.assertNotEqual(frappe.db.get_value("POS Order", self.order, "status"), "Cancelled")
		# the GM's own hotel still works, and the feed shows only it
		self.assertEqual(agents_api.activity_detail(name=self.own_log)["property"], OTHER)
		feed = {r.name for r in agents_api.activity_feed(limit=200)}
		self.assertIn(self.own_log, feed)
		self.assertNotIn(self.log, feed)
		self.assertIn("enabled", assistant.assistant_status(property=OTHER))

	def test_new8_an_action_log_row_without_a_hotel_is_platform_level(self):
		"""NEW-8 (audit Part 2I): a legacy action log row without a hotel was taken for a platform-wide
		record: every tenant's roles read it in Desk / REST, and ``activity_detail`` returned it. New rows
		take their hotel from the record they are about; the feed and the front desk's minutes saved stay
		inside the caller's hotels."""
		from frappe.client import get as client_get

		from kamra import agents_api, api
		from kamra.savings import log_action

		frappe.set_user("Administrator")  # nosemgrep: frappe-setuser -- fixtures
		# a row as the legacy writers left it (folio moves, allowances, PIN resets...): no hotel
		bare = frappe.get_doc({"doctype": "Agent Action Log", "action_type": "sec_new8_bare",
		                       "minutes_saved": 7}).insert(ignore_permissions=True).name
		folio = frappe.get_doc({"doctype": "Folio", "property": fx.PROPERTY, "reservation": self.reservation,
		                        "guest": self.guest}).insert(ignore_permissions=True).name
		frappe.get_doc({"doctype": "Agent Action Log", "action_type": "sec_new8_mine", "property": OTHER,
		                "minutes_saved": 5}).insert(ignore_permissions=True)
		frappe.get_doc({"doctype": "Agent Action Log", "action_type": "sec_new8_theirs", "property": fx.PROPERTY,
		                "minutes_saved": 11}).insert(ignore_permissions=True)
		desk = fx.ensure_user("sec-new8-fd@example.com", ["Front Desk"])
		fx.ensure("TEX Access Grant", {"user": desk, "property": fx.PROPERTY},
		          {"user": desk, "scope_level": "Hotel", "property": fx.PROPERTY,
		           "permission_profile": "Reservations Agent"})
		self.assertEqual(client_get("Agent Action Log", bare)["name"], bare)       # platform administrators read it

		def as_user(user):
			frappe.set_user(user)  # nosemgrep: frappe-setuser -- each tenant's user probes
			scope.clear_cache()

		for pms in (1, 0):
			frappe.set_user("Administrator")  # nosemgrep: frappe-setuser -- the platform's PMS switch
			frappe.db.set_single_value("TEX Settings", "show_legacy_pms", pms)
			for user in (self.gm, desk):                                  # another tenant's GM, the hotel's desk
				as_user(user)
				with self.assertRaises(frappe.PermissionError, msg=f"{user} pms={pms}"):
					client_get("Agent Action Log", bare)
				self.assertEqual(frappe.get_list("Agent Action Log", filters={"name": bare}, pluck="name"), [],
				                 f"{user} pms={pms}")
				if pms:
					with self.assertRaises(frappe.PermissionError, msg=user):
						agents_api.activity_detail(name=bare)
					feed = agents_api.activity_feed(limit=200)
					self.assertFalse([r.name for r in feed if not frappe.db.get_value("Agent Action Log", r.name,
					                                                                  "property")], user)

		# new rows about a hotel's records carry that hotel: its staff read them, another tenant does not
		frappe.set_user("Administrator")  # nosemgrep: frappe-setuser -- the legacy writers' own calls
		frappe.db.set_single_value("TEX Settings", "show_legacy_pms", 1)
		logged = [log_action("allowance", "Folio", folio), log_action("anonymize_guest", "Guest", self.guest)]
		for row in logged:
			self.assertEqual(frappe.db.get_value("Agent Action Log", row, "property"), fx.PROPERTY, row)
			as_user(desk)
			self.assertEqual(client_get("Agent Action Log", row)["name"], row)
			as_user(self.gm)
			with self.assertRaises(frappe.PermissionError):
				client_get("Agent Action Log", row)
			frappe.set_user("Administrator")  # nosemgrep: frappe-setuser -- back

		# the front desk's "minutes saved" counts only the caller's hotels
		as_user(self.gm)
		since = add_days(nowdate(), -30)
		mine = frappe.db.sql("""select coalesce(sum(minutes_saved), 0) from `tabAgent Action Log`
		                        where property = %s and date(creation) >= %s""", (OTHER, since))[0][0]
		for snap in (api.front_desk_snapshot(), api.front_desk_snapshot(property=OTHER)):
			self.assertEqual(snap["minutes_saved_30d"], float(mine))

	def test_g16_switched_off_pms_is_closed_in_the_backend(self):
		from kamra import agents_api, api

		self.assertTrue(api.whoami()["legacy_pms"])
		self.assertEqual(agents_api.activity_detail(name=self.own_log)["property"], OTHER)
		frappe.set_user("Administrator")  # nosemgrep: frappe-setuser -- the platform switches the PMS off
		frappe.db.set_single_value("TEX Settings", "show_legacy_pms", 0)
		frappe.set_user(self.gm)  # nosemgrep: frappe-setuser -- the hotel's own records, PMS off
		self.assertFalse(api.whoami()["legacy_pms"])                   # the SPA sends the user to /tex
		with self.assertRaisesRegex(frappe.PermissionError, "switched off"):
			agents_api.activity_detail(name=self.own_log)
		with self.assertRaisesRegex(frappe.PermissionError, "switched off"):
			api.front_desk_snapshot(property=OTHER)
		frappe.set_user("Administrator")  # nosemgrep: frappe-setuser -- platform administrators keep it
		self.assertTrue(api.whoami()["legacy_pms"])
		self.assertEqual(agents_api.activity_detail(name=self.own_log)["property"], OTHER)

	def test_every_legacy_record_argument_is_scoped(self):
		import importlib
		import inspect

		from kamra.authz import SCOPED_ARGS, record_args

		scoped = {a for a, _dt in SCOPED_ARGS}
		missing, checked = [], 0
		for module in LEGACY_MODULES:
			mod = importlib.import_module(module)
			for fname, fn in vars(mod).items():
				if not callable(fn) or getattr(fn, "__module__", None) != module or fn not in frappe.whitelisted:
					continue
				if fn in frappe.guest_methods or not hasattr(fn, "_kamra_roles"):
					continue
				checked += 1
				records = record_args(fn)
				for arg in inspect.signature(fn).parameters:
					if arg in LEGACY_RECORD_ARGS and arg not in scoped and arg not in records \
							and (f"{module}.{fname}", arg) not in LEGACY_CHECKED_IN_BODY:
						missing.append(f"{module}.{fname}({arg})")
		self.assertGreater(checked, 250)  # the guarded legacy endpoints were really inspected
		self.assertEqual(missing, [], "record arguments without a hotel check")


class TestCostRecordsInDesk(TexTestCase):
	"""G-97 (audit Part 2I): a contract version (and its rate tables), a markup rule and a pricing policy are
	cost. The TEX API serves them with ``price.view_cost``; Desk / REST let the Hotel Admin role read them,
	and the audit events carrying their compact diffs. They are platform administrators' in Desk / REST now."""

	COST = ("TEX Contract Version", "TEX Markup Rule", "TEX Pricing Policy")

	def setUp(self):
		super().setUp()
		from kamra.tex.security.audit import audit

		setup_site_and_payments(self.f)
		other_hotel_with_mock()
		self.version = fx.create_contract(self.f, code="G97")["version"]
		self.markup = fx.create_markup()
		self.policy = frappe.get_doc({"doctype": "TEX Pricing Policy", "policy_name": "G97 policy",
		                              "property": fx.PROPERTY}).insert(ignore_permissions=True).name
		self.event = audit("contract.version.save", reference_doctype="TEX Contract Version",
		                   reference_name=self.version, property=fx.PROPERTY, new={"collections": {}})
		self.grant_event = audit("grant.create", reference_doctype="TEX Access Grant", reference_name="G97",
		                         property=fx.PROPERTY)
		self.booking = guest_books(session="g97")["booking"]
		frappe.set_user("Administrator")  # nosemgrep: frappe-setuser -- fixtures
		self.ha = self.user("g97-ha@example.com", "Hotel Admin", fx.PROPERTY, "Hotel Admin")
		self.other = self.user("g97-other@example.com", "Hotel Admin", OTHER, "Hotel Admin")
		self.rm = self.user("g97-rm@example.com", "Revenue Manager", fx.PROPERTY, "Revenue Manager")

	def user(self, email, role, hotel, profile):
		fx.ensure_user(email, [role])
		fx.ensure("TEX Access Grant", {"user": email, "property": hotel},
		          {"user": email, "scope_level": "Hotel", "property": hotel, "permission_profile": profile})
		return email

	def as_user(self, user):
		frappe.set_user(user)  # nosemgrep: frappe-setuser -- each role probes
		scope.clear_cache()

	def test_g97_cost_records_are_platform_administrators_in_desk_and_rest(self):
		from frappe.client import get as client_get
		from frappe.client import get_list as client_get_list

		self.as_user(self.ha)
		for doctype, name in zip(self.COST, (self.version, self.markup, self.policy), strict=True):
			with self.assertRaises(frappe.PermissionError, msg=doctype):
				client_get(doctype, name)
		for user in (self.ha, self.other):                               # the rate tables go with their version
			self.as_user(user)
			with self.assertRaises(frappe.PermissionError, msg=user):
				client_get_list("TEX Period Rate", parent="TEX Contract Version", fields=["parent", "value"])
		# the compact rate diffs of the audit trail are cost too; other events stay readable
		self.as_user(self.ha)
		self.assertEqual(frappe.get_list("TEX Audit Event", filters={"reference_doctype": "TEX Contract Version"},
		                                 pluck="name"), [])
		self.assertFalse(frappe.has_permission("TEX Audit Event", "read", doc=frappe.get_doc("TEX Audit Event", self.event),
		                                       user=self.ha))
		self.assertTrue(frappe.has_permission("TEX Audit Event", "read",
		                                      doc=frappe.get_doc("TEX Audit Event", self.grant_event), user=self.ha))
		self.assertIn(self.grant_event, frappe.get_list("TEX Audit Event", pluck="name", limit_page_length=0))
		self.assertEqual(client_get("TEX Booking", self.booking)["name"], self.booking)   # booking reads unchanged
		# the TEX API is the one reader: price.view_cost
		self.as_user(self.rm)
		self.assertIn(self.markup, [r["name"] for r in policy_api.list_records("TEX Markup Rule", property=fx.PROPERTY)])
		self.assertIn(self.policy, [r["name"] for r in policy_api.list_records("TEX Pricing Policy",
		                                                                       property=fx.PROPERTY)])
		frappe.set_user("Administrator")  # nosemgrep: frappe-setuser -- platform administrators keep them
		for doctype, name in zip(self.COST, (self.version, self.markup, self.policy), strict=True):
			self.assertEqual(client_get(doctype, name)["name"], name)

	def test_g97_the_cost_doctypes_json_permissions_are_the_specs(self):
		import json
		import os

		from kamra.tex.devtools.doctype_gen import scrub
		from kamra.tex.devtools.doctype_specs import SPECS

		specs = {d["name"]: d for d in SPECS}
		for doctype in self.COST:
			spec = specs[doctype]
			path = frappe.get_app_path("kamra", scrub(spec["module"]), "doctype", scrub(doctype), f"{scrub(doctype)}.json")
			self.assertTrue(os.path.exists(path), path)
			with open(path, encoding="utf-8") as f:
				self.assertEqual(json.load(f)["permissions"], spec["permissions"], doctype)
			self.assertEqual([p["role"] for p in spec["permissions"]], ["System Manager"], doctype)


class TestLegacySelling(TexTestCase):
	"""G-03: the legacy booking engine (`/kamra/book`) and the legacy staff booking dialog
	price from Room Type.base_price; they must never price or sell a TEX hotel."""

	def setUp(self):
		super().setUp()
		setup_site_and_payments(self.f)
		other_hotel_with_mock()  # outside the TEX hierarchy: the legacy engine may still sell it
		self.stay = {"check_in_date": str(fx.d(6, 10)), "check_out_date": str(fx.d(6, 13))}
		self.room_type = self.f["room_types"]["STD"]

	def test_public_legacy_engine_refuses_a_tex_hotel(self):
		from kamra import public_api

		before = frappe.db.count("Reservation", {"property": fx.PROPERTY})
		frappe.set_user("Guest")  # nosemgrep: frappe-setuser -- anonymous visitor of /kamra/book
		for call in (lambda: public_api.showcase(property=fx.PROPERTY),
		             lambda: public_api.search_stay(property=fx.PROPERTY, **self.stay),
		             lambda: public_api.book(property=fx.PROPERTY, room_type=self.room_type, guest_name="Legacy Probe",
		                                     phone="+49 30 1234567", **self.stay)):
			with self.assertRaisesRegex(frappe.ValidationError, "/book"):
				call()
		self.assertFalse(public_api.check_voucher(property=fx.PROPERTY, code="ANY")["ok"])
		self.assertNotEqual(public_api.default_property(), fx.PROPERTY)
		idx = public_api.catalog_index()
		self.assertNotIn(fx.PROPERTY, [p["name"] for p in idx.get("properties", [])] + [idx.get("property")])
		self.assertEqual(public_api.search_stay(property=OTHER, **self.stay), [])  # a non-TEX hotel still works
		frappe.set_user("Administrator")  # nosemgrep: frappe-setuser -- count as admin
		self.assertEqual(frappe.db.count("Reservation", {"property": fx.PROPERTY}), before)

	def test_legacy_staff_booking_refuses_a_tex_hotel(self):
		from kamra import api

		with self.assertRaisesRegex(frappe.ValidationError, "/book"):
			api.get_quote(property=fx.PROPERTY, room_type=self.room_type, **self.stay)
		with self.assertRaisesRegex(frappe.ValidationError, "/book"):
			api.create_booking(property=fx.PROPERTY, room_type=self.room_type, guest_name="Legacy Probe",
			                   phone="+49 30 7654321", **self.stay)
		with self.assertRaisesRegex(frappe.ValidationError, "/book"):
			api.create_group_booking(property=fx.PROPERTY, group_name="Legacy group", guest_name="Legacy Probe",
			                         rooms=[{"room_type": self.room_type, "count": 1}], **self.stay)


class TestLegacyNightAudit(TexTestCase):
	"""G-04: the legacy night audit (daily 03:00) never flags a TEX-sold stay as a no-show,
	charges it a no-show fee or posts legacy room nights on it — only TEX changes it."""

	def setUp(self):
		super().setUp()
		setup_site_and_payments(self.f)
		b = guest_books(session="sec-g04")
		public.mock_pay(transaction=b["payment"]["transaction"], outcome="success",
		                sig=b["payment"]["fields"]["success_sig"])
		frappe.set_user("Administrator")  # nosemgrep: frappe-setuser -- the scheduler runs as Administrator
		self.tex = b["rooms"][0]["reservation"]
		guest = frappe.db.get_value("Reservation", self.tex, "guest")
		# a stay the legacy engine sold before the hotel joined TEX (since G-92 nothing else writes
		# one at a TEX hotel, ADR-052)
		with mock.patch("kamra.tex.legacy.is_tex_hotel", return_value=False):
			self.legacy = frappe.get_doc({"doctype": "Reservation", "property": fx.PROPERTY, "guest": guest,
			                              "room_type": self.f["room_types"]["DLX"], "check_in_date": fx.d(6, 10),
			                              "check_out_date": fx.d(6, 12), "status": "Confirmed"}).insert(
				ignore_permissions=True).name
		frappe.db.set_value("Property", fx.PROPERTY, "no_show_charge", "First Night")

	def test_night_audit_leaves_tex_stays_to_tex(self):
		from unittest.mock import patch

		from kamra.folio import run_night_audit

		self.assertEqual(frappe.db.get_value("Reservation", self.tex, "status"), "Confirmed")
		before = frappe.db.get_value("Reservation", self.tex, ["status", "amount_after_tax", "tex_total_amount"])
		with patch.object(frappe.db, "commit", lambda *a, **k: None):  # the test rolls back
			out = run_night_audit(fx.PROPERTY, business_date=str(fx.d(6, 11)))
		self.assertEqual(frappe.db.get_value("Reservation", self.tex, ["status", "amount_after_tax",
		                                                               "tex_total_amount"]), before)
		self.assertFalse(frappe.db.exists("Folio", {"reservation": self.tex}))
		self.assertEqual(frappe.db.get_value("Reservation", self.legacy, "status"), "No Show")  # legacy still audited
		self.assertEqual(out["no_shows_flagged"], 1)
		self.assertIn("left 1 TEX-sold reservations to TEX",
		              frappe.db.get_value("Night Audit Run", out["audit"], "log"))


class TestPaymentLinkTokens(TexTestCase):
	"""G-10: a payment link's bearer token is never stored in a transaction nor handed to
	someone who cannot prove the payment's signature."""

	def setUp(self):
		super().setUp()
		self.p = setup_site_and_payments(self.f)
		frappe.set_user("Administrator")  # nosemgrep: frappe-setuser -- the agent sends a link
		self.link = pay.create_link(property=fx.PROPERTY, amount="80", currency="EUR", description="deposit",
		                            provider_account=self.p["account"], guest_name="Link Guest")
		frappe.set_user("Guest")  # nosemgrep: frappe-setuser -- the guest opens the link
		self.start = public.pay_link(token=self.link["token"])
		self.txn = self.start["transaction"]

	def test_the_transaction_does_not_keep_the_link_token(self):
		frappe.set_user("Administrator")  # nosemgrep: frappe-setuser -- what hotel staff can read over REST
		stored = frappe.db.get_value("TEX Payment Transaction", self.txn, "return_url")
		self.assertNotIn(self.link["token"], stored)
		self.assertTrue(stored.endswith("/book/pay/return"))

	def test_a_replay_without_the_signature_learns_nothing(self):
		ok = public.mock_pay(transaction=self.txn, outcome="success", sig=self.start["fields"]["success_sig"])
		self.assertEqual(ok["status"], "Succeeded")
		self.assertNotIn(self.link["token"], ok.get("return_url") or "")
		with self.assertRaises(ProviderError):                      # the payment is final; a forged replay
			public.mock_pay(transaction=self.txn, outcome="success", sig="0" * 64)

	def test_old_transactions_are_scrubbed(self):
		from kamra.patches.tex import p10_scrub_link_return_urls

		frappe.set_user("Administrator")  # nosemgrep: frappe-setuser -- migration
		leaked = frappe.utils.get_url(f"/book/pay/{self.link['token']}")
		frappe.db.set_value("TEX Payment Transaction", self.txn, "return_url", leaked)
		p10_scrub_link_return_urls.execute()
		self.assertEqual(frappe.db.get_value("TEX Payment Transaction", self.txn, "return_url"),
		                 frappe.utils.get_url("/book/pay/return"))


class TestLegacyWebhooks(TexTestCase):
	"""G-15: legacy webhooks fail closed (no secret, no signature: nothing happens), and the
	legacy channel manager never prices or books a TEX hotel (ADR-028)."""

	def setUp(self):
		super().setUp()
		setup_site_and_payments(self.f)
		b = guest_books(session="sec-g15")
		frappe.set_user("Administrator")  # nosemgrep: frappe-setuser -- fixtures
		res = b["rooms"][0]["reservation"]
		self.folio = frappe.get_doc({"doctype": "Folio", "property": fx.PROPERTY, "reservation": res,
		                             "guest": frappe.db.get_value("Reservation", res, "guest")}).insert(
			ignore_permissions=True).name
		fx.ensure("Payment Gateway Settings", {"property": fx.PROPERTY},
		          {"property": fx.PROPERTY, "gateway": "Razorpay", "enabled": 1, "test_mode": 1})
		self.conn = frappe.get_doc({"doctype": "Channel Manager Connection", "property": fx.PROPERTY,
		                            "provider": "Channex", "active": 1}).insert(ignore_permissions=True).name

	def _post(self, body: bytes, headers: dict | None = None):
		from werkzeug.test import EnvironBuilder
		from werkzeug.wrappers import Request

		frappe.local.request = Request(EnvironBuilder(method="POST", data=body, headers=headers or {}).get_environ())

	def tearDown(self):
		frappe.local.request = None
		super().tearDown()

	def test_unsigned_razorpay_post_records_nothing(self):
		from kamra import payments

		body = frappe.as_json({"event": "payment_link.paid", "payload": {"payment_link": {"entity": {
			"id": "plink_forged", "amount_paid": 99900, "notes": {"folio": self.folio}}}}}).encode()
		frappe.set_user("Guest")  # nosemgrep: frappe-setuser -- anyone on the internet
		self._post(body)
		with self.assertRaises(frappe.PermissionError):         # test mode no longer skips the signature
			payments.razorpay_webhook()
		frappe.set_user("Administrator")  # nosemgrep: frappe-setuser -- inspect the folio
		self.assertEqual(len(frappe.get_doc("Folio", self.folio).payments), 0)

	def test_channel_manager_needs_a_secret_and_stays_off_tex_hotels(self):
		from kamra import channel_manager

		frappe.set_user("Guest")  # nosemgrep: frappe-setuser -- the channel manager's server
		with self.assertRaises(frappe.PermissionError):         # no secret configured: nothing is accepted
			channel_manager.webhook(connection=self.conn, event="new", ota_ref="X-1")
		frappe.set_user("Administrator")  # nosemgrep: frappe-setuser -- configure the secret
		conn = frappe.get_doc("Channel Manager Connection", self.conn)
		conn.webhook_secret = "cm-secret-1"
		conn.save(ignore_permissions=True)
		frappe.set_user("Guest")  # nosemgrep: frappe-setuser -- authenticated, but the hotel sells through TEX
		with self.assertRaisesRegex(frappe.ValidationError, "through TEX"):
			channel_manager.webhook(connection=self.conn, secret="cm-secret-1", event="new", ota_ref="X-1")
		frappe.set_user("Administrator")  # nosemgrep: frappe-setuser -- a manual ARI push
		with self.assertRaisesRegex(frappe.ValidationError, "through TEX"):
			channel_manager.push_ari(connection=self.conn)
		# G-87: a job queued before the guard, the room import and AioSell's own webhook refuse too
		with self.assertRaisesRegex(frappe.ValidationError, "through TEX"):
			channel_manager.process_webhook_events(self.conn, {"event": "new", "ota_ref": "X-2"})
		with self.assertRaisesRegex(frappe.ValidationError, "through TEX"):
			channel_manager.import_room_mappings(self.conn, dry_run=1)
		import base64

		from kamra.channels import aiosell

		frappe.get_doc({"doctype": "Channel Manager Connection", "property": fx.PROPERTY, "provider": "AioSell",
		                "active": 1, "api_username": "aio", "api_key": "aio-key-1",
		                "external_property_id": "TEX-G87"}).insert(ignore_permissions=True)
		frappe.local.flags.aiosell_webhook_auth = "Basic " + base64.b64encode(b"aio:aio-key-1").decode()
		frappe.set_user("Guest")  # nosemgrep: frappe-setuser -- AioSell's server, authenticated
		try:
			with self.assertRaisesRegex(frappe.ValidationError, "through TEX"):
				aiosell.reservation_webhook(hotelCode="TEX-G87", action="book", bookingId="AIO-1")
		finally:
			frappe.local.flags.aiosell_webhook_auth = None
		self.assertFalse(frappe.db.exists("Reservation", {"ota_ref": ("like", "AIO-1%")}))


class TestAdminDataTenancy(TexTestCase):
	"""G-26: another enterprise's hotel admin, through Desk/REST, neither reads nor changes this
	tenant's access grants, enterprise, hotel group or group-site guest activity; permission
	profiles are listed only to user administrators."""

	def setUp(self):
		super().setUp()
		from kamra.tex.tests.integration.test_crm_segments import OTHER as THERE
		from kamra.tex.tests.integration.test_crm_segments import agent, other_tenant

		self.there_hotel = THERE
		other_tenant()
		self.here = agent("g26-here@example.com", fx.PROPERTY)
		self.grant = frappe.db.get_value("TEX Access Grant", {"user": self.here, "property": fx.PROPERTY})
		grouped = fx.ensure_user("g26-group@example.com", ["Call Center Agent"])
		self.group_grant = fx.ensure("TEX Access Grant", {"user": grouped, "hotel_group": fx.GROUP},
		                             {"user": grouped, "scope_level": "Hotel Group", "hotel_group": fx.GROUP,
		                              "permission_profile": "Reservations Agent"})
		self.there = agent("g26-there@example.com", THERE, "Hotel Admin")
		frappe.get_doc("User", self.there).add_roles("Hotel Admin")                 # Desk / REST role
		frappe.set_user("Administrator")  # nosemgrep: frappe-setuser -- fixtures
		self.group_site = frappe.get_doc({"doctype": "TEX Booking Site", "site_name": "G26 group site",
		                                  "site_slug": "g26-group", "enabled": 1, "hotel_group": fx.GROUP,
		                                  "default_market": "DE", "default_currency": "EUR", "currencies": "EUR"}
		                                 ).insert(ignore_permissions=True).name
		self.funnel = frappe.get_doc({"doctype": "TEX Funnel Event", "event": "search", "site": self.group_site,
		                              "session_id": "g26"}).insert(ignore_permissions=True).name
		self.abandoned = frappe.get_doc({"doctype": "TEX Abandoned Booking", "site": self.group_site,
		                                 "session_id": "g26", "email": "g26.guest@example.com",
		                                 "stage_reached": "guest_details"}).insert(ignore_permissions=True).name

	def as_there(self):
		frappe.set_user(self.there)  # nosemgrep: frappe-setuser -- the other tenant's admin
		scope.clear_cache()

	def test_grants_of_another_tenant_are_hidden_and_untouchable(self):
		self.as_there()
		self.assertFalse({self.grant, self.group_grant} & set(frappe.get_list("TEX Access Grant", pluck="name")))
		self.assertFalse(frappe.get_doc("TEX Access Grant", self.group_grant).has_permission("read"))
		doc = frappe.get_doc("TEX Access Grant", self.grant)
		self.assertFalse(doc.has_permission("read"))
		with self.assertRaises(frappe.PermissionError):                             # REST DELETE
			frappe.delete_doc("TEX Access Grant", self.grant)
		with self.assertRaises(frappe.PermissionError):                             # REST PUT, moving it here
			doc.property = self.there_hotel
			doc.save()
		doc.reload()
		doc.property = self.there_hotel
		with self.assertRaises(frappe.PermissionError):                             # even from trusted code
			doc.save(ignore_permissions=True)
		with self.assertRaises(frappe.PermissionError):
			frappe.get_doc("TEX Access Grant", self.grant).delete(ignore_permissions=True)
		frappe.set_user("Administrator")  # nosemgrep: frappe-setuser -- verify
		self.assertEqual(frappe.db.get_value("TEX Access Grant", self.grant, "property"), fx.PROPERTY)
		own = frappe.db.get_value("TEX Access Grant", {"user": self.there})
		self.as_there()
		self.assertIn(own, frappe.get_list("TEX Access Grant", pluck="name"))           # its own tenant's grants

	def test_enterprise_and_group_names_stay_in_their_tenant(self):
		self.as_there()
		self.assertNotIn(fx.ENTERPRISE, frappe.get_list("TEX Enterprise", pluck="name"))
		self.assertNotIn(fx.GROUP, frappe.get_list("TEX Hotel Group", pluck="name"))
		self.assertFalse(frappe.get_doc("TEX Hotel Group", fx.GROUP).has_permission("read"))
		self.assertFalse(frappe.get_doc("TEX Enterprise", fx.ENTERPRISE).has_permission("read"))
		self.assertTrue(frappe.get_list("TEX Enterprise", pluck="name"))                # its own is listed

	def test_group_site_activity_stays_with_the_groups_hotels(self):
		self.as_there()
		self.assertNotIn(self.funnel, frappe.get_list("TEX Funnel Event", pluck="name"))
		self.assertNotIn(self.abandoned, frappe.get_list("TEX Abandoned Booking", pluck="name"))
		self.assertFalse(frappe.get_doc("TEX Abandoned Booking", self.abandoned).has_permission("read"))
		frappe.set_user("Administrator")  # nosemgrep: frappe-setuser -- fixtures
		frappe.get_doc("User", self.here).add_roles("Hotel Admin")                  # may read the list in Desk
		frappe.set_user(self.here)  # nosemgrep: frappe-setuser -- a user of the group's hotel
		scope.clear_cache()
		self.assertIn(self.abandoned, frappe.get_list("TEX Abandoned Booking", pluck="name"))

	def test_permission_profiles_need_user_administration(self):
		from kamra.tex.api import admin

		frappe.set_user(self.here)  # nosemgrep: frappe-setuser -- a reservations agent
		scope.clear_cache()
		with self.assertRaises(frappe.PermissionError):
			admin.profiles()
		self.as_there()
		self.assertTrue(admin.profiles()["profiles"])


def _return_url() -> str:
	from kamra.tex.services import sites

	return sites.guest_url(sites.site_for(fx.PROPERTY), "pay/return", site_scoped=False)


class TestGoLivePayments(TexTestCase):
	"""Go-live payments hardening (ADR-041). G-67: an uncertified gateway never runs in
	Production (save and run time), a Production account takes no gateway URL override, and
	a gateway's success must carry the charged amount and currency. G-68: a payment link
	starts one charge at a time and a second success is kept but flagged; a refund comes out
	of the booking that holds the money. G-89: signatures never fall back to the site name."""

	def setUp(self):
		super().setUp()
		self.p = setup_site_and_payments(self.f)

	def account(self, provider, environment="Sandbox", **kw):
		return frappe.get_doc({"doctype": "TEX Payment Provider Account", "label": f"{provider} {environment}",
		                       "property": fx.PROPERTY, "provider": provider, "environment": environment,
		                       "enabled": 1, "currencies": "EUR", **kw}).insert(ignore_permissions=True)

	def charge(self, key: str, amount="100", **kw) -> str:
		return pay.start_payment(property=fx.PROPERTY, amount=amount, currency="EUR",
		                         provider_account=self.p["account"], description="test", customer={},
		                         return_url=_return_url(), idempotency_key=key, **kw)["transaction"]

	# ─── G-67 production gating ──────────────────────────────────────────

	def test_g67_an_uncertified_gateway_cannot_be_saved_for_production(self):
		for provider in ("iyzico", "Sipay", "Virtual POS"):
			with self.assertRaisesRegex(frappe.ValidationError, "not certified for production", msg=provider):
				self.account(provider, "Production")
		with self.assertRaisesRegex(frappe.ValidationError, "only be used in Sandbox"):
			self.account("Mock", "Production")
		with self.assertRaisesRegex(frappe.ValidationError, "gateway URL"):     # overrides are for test hosts
			self.account("Bank Transfer", "Production", gateway_url="https://pay.example.com")
		self.account("Bank Transfer", "Production", bank_name="Test Bank", iban="TR000000")  # no gateway to certify
		self.account("Pay at Hotel", "Production")
		self.account("iyzico", gateway_url="https://sandbox-api.iyzipay.com")    # a sandbox host may be overridden
		with self.assertRaisesRegex(frappe.ValidationError, "not certified for production"):  # the TEX API too
			pay_api.save_account(property=fx.PROPERTY, data={"label": "Live iyzico", "provider": "iyzico",
			                                                 "environment": "Production"})
		listed = {a["provider"]: a["production_verified"] for a in pay_api.accounts(property=fx.PROPERTY)["accounts"]}
		self.assertEqual((listed["Bank Transfer"], listed["Pay at Hotel"], listed["iyzico"], listed["Mock"]),
		                 (True, True, False, False))

	def test_g67_run_time_refuses_an_uncertified_or_overridden_production_account(self):
		iyz = self.account("iyzico")
		iyz.db_set("environment", "Production")          # e.g. changed in SQL, bypassing the controller
		with self.assertRaisesRegex(frappe.ValidationError, "not certified for production"):
			pay.provider_for(iyz.name)
		bank = self.account("Bank Transfer", "Production", bank_name="Test Bank", iban="TR000000")
		self.assertEqual(pay.provider_for(bank.name).name, "Bank Transfer")
		bank.db_set("gateway_url", "https://pay.example.com")
		with self.assertRaisesRegex(frappe.ValidationError, "gateway URL"):
			pay.provider_for(bank.name)
		frappe.db.set_value("TEX Payment Provider Account", self.p["account"], "environment", "Production")
		with self.assertRaises((frappe.ValidationError, ProviderError)):
			pay.provider_for(self.p["account"])
		self.assertFalse([m for m in pay.payment_methods(fx.PROPERTY, market=None, currency="EUR", channel=None)
		                  if m["provider_account"] == self.p["account"]])   # not offered either

	def test_g67_a_gateway_success_must_carry_the_amount_and_currency(self):
		from kamra.tex.payments.providers.base import Outcome

		class Gateway:
			name, reports_amount, sandbox = "iyzico", True, True

			def __init__(self, outcome):
				self.outcome = outcome

			def handle_callback(self, *args, **kwargs):
				return self.outcome

		cases = [(None, "EUR", "AMOUNT_MISMATCH"), (D("0"), "EUR", "AMOUNT_MISMATCH"),
		         (D("99.99"), "EUR", "AMOUNT_MISMATCH"), (D("100"), "TRY", "CURRENCY_MISMATCH")]
		for i, (amount, ccy, code) in enumerate(cases):
			txn = self.charge(f"g67-amount-{i}")
			gw = Gateway(Outcome(status="Succeeded", provider_ref="GW-1", amount=amount, currency=ccy))
			with mock.patch.object(pay, "provider_for", return_value=gw):
				self.assertEqual(pay.complete(txn, params={})["status"], "Failed", msg=code)
			self.assertEqual(frappe.db.get_value("TEX Payment Transaction", txn, "error_code"), code)
		txn = self.charge("g67-amount-ok")
		gw = Gateway(Outcome(status="Succeeded", provider_ref="GW-2", amount=D("100.00"), currency="eur"))
		with mock.patch.object(pay, "provider_for", return_value=gw):
			self.assertEqual(pay.complete(txn, params={})["status"], "Succeeded")

	# ─── G-89 signing keys ───────────────────────────────────────────────

	def test_g89_signatures_need_the_site_encryption_key(self):
		from kamra.tex.services import quoting

		key = str(frappe.local.conf.get("encryption_key") or "")
		self.assertTrue(key, "the test site must have an encryption key")
		# with a key, every signature is exactly what it was (issued offers and callbacks stay valid)
		self.assertEqual(pay._mock_secret(), hashlib.sha256(("tex-mock-pay:" + key).encode()).hexdigest())
		self.assertEqual(pay.callback_signature("PTX-1"),
		                 hmac.new(("tex-callback:" + key).encode(), b"PTX-1", hashlib.sha256).hexdigest()[:32])
		self.assertEqual(quoting._secret(), hashlib.sha256(("tex-offer:" + key).encode()).digest())
		token = quoting.sign({"kind": "offer", "n": 1})
		with mock.patch.dict(frappe.local.conf):
			frappe.local.conf.pop("encryption_key", None)
			for signing in (lambda: quoting.sign({"kind": "offer"}), lambda: quoting.verify(token),
			                lambda: pay.callback_signature("PTX-1"), pay._mock_secret):
				with self.assertRaisesRegex(frappe.ValidationError, "encryption key") as caught:
					signing()
				self.assertNotIn(key, str(caught.exception))
				self.assertNotIn(frappe.local.site, str(caught.exception))
		self.assertEqual(quoting.verify(token)["n"], 1)

	# ─── G-68 payment links ──────────────────────────────────────────────

	def link(self, amount="80"):
		frappe.set_user("Administrator")  # nosemgrep: frappe-setuser -- the agent sends a link
		out = pay.create_link(property=fx.PROPERTY, amount=amount, currency="EUR", description="deposit",
		                      provider_account=self.p["account"], guest_name="Link Guest")
		frappe.set_user("Guest")  # nosemgrep: frappe-setuser -- the guest opens the link
		return out

	def test_g68_a_link_starts_one_charge_until_that_one_fails(self):
		link = self.link()
		first = public.pay_link(token=link["token"])
		again = public.pay_link(token=link["token"])                     # a second tab or a double click
		self.assertEqual(again["transaction"], first["transaction"])
		public.mock_pay(transaction=first["transaction"], outcome="fail", sig=first["fields"]["fail_sig"])
		retry = public.pay_link(token=link["token"])                     # after a failure: a new charge
		self.assertNotEqual(retry["transaction"], first["transaction"])
		self.assertEqual(public.pay_link(token=link["token"])["transaction"], retry["transaction"])
		public.mock_pay(transaction=retry["transaction"], outcome="success", sig=retry["fields"]["success_sig"])
		frappe.set_user("Administrator")  # nosemgrep: frappe-setuser -- verify
		self.assertEqual(frappe.db.get_value("TEX Payment Link", link["link"], "status"), "Paid")
		self.assertEqual(frappe.db.count("TEX Payment Transaction", {"payment_link": link["link"],
		                                                             "status": "Succeeded"}), 1)
		frappe.set_user("Guest")  # nosemgrep: frappe-setuser -- the guest tries again
		with self.assertRaises(frappe.ValidationError):
			public.pay_link(token=link["token"])

	def test_g68_a_charge_paid_in_one_tab_after_failing_in_another_is_recorded(self):
		link = self.link()
		tab1 = public.pay_link(token=link["token"])
		tab2 = public.pay_link(token=link["token"])                      # the same charge, a second checkout
		public.mock_pay(transaction=tab1["transaction"], outcome="fail", sig=tab1["fields"]["fail_sig"])
		out = public.mock_pay(transaction=tab2["transaction"], outcome="success", sig=tab2["fields"]["success_sig"])
		self.assertEqual(out["status"], "Succeeded")                      # captured money is never ignored
		frappe.set_user("Administrator")  # nosemgrep: frappe-setuser -- verify
		self.assertEqual(frappe.db.get_value("TEX Payment Link", link["link"], "status"), "Paid")
		again = public.mock_pay(transaction=tab1["transaction"], outcome="fail", sig=tab1["fields"]["fail_sig"])
		self.assertEqual((again["status"], again.get("replay")), ("Succeeded", True))   # a late failure changes nothing

	def test_g68_a_reused_charge_is_never_rerouted_or_repriced(self):
		frappe.set_user("Administrator")  # nosemgrep: frappe-setuser -- service-level check
		first = self.charge("g68-reuse")
		self.assertEqual(self.charge("g68-reuse"), first)                 # the same start again: the same charge
		other = self.account("Mock", label="Second sandbox").name
		with self.assertRaisesRegex(frappe.ValidationError, "another method or amount"):
			pay.start_payment(property=fx.PROPERTY, amount="100", currency="EUR", provider_account=other,
			                  description="test", customer={}, return_url=_return_url(), idempotency_key="g68-reuse")
		with self.assertRaisesRegex(frappe.ValidationError, "another method or amount"):
			self.charge("g68-reuse", amount="90")

	def test_g68_a_failed_restart_keeps_the_first_checkout_payable(self):
		from kamra.tex.payments.providers import simple

		frappe.set_user("Administrator")  # nosemgrep: frappe-setuser -- service-level check
		key = "g68-restart"
		first = pay.start_payment(property=fx.PROPERTY, amount="100", currency="EUR",
		                          provider_account=self.p["account"], description="test", customer={},
		                          return_url=_return_url(), idempotency_key=key)
		with mock.patch.object(simple.MockProvider, "create_checkout", side_effect=ProviderError("gateway down")):
			with self.assertRaises(pay.ChargeSuperseded):                 # the second tab cannot start...
				self.charge(key)
		# superseded, so the caller can start a new charge (G-68 review)...
		self.assertEqual(frappe.db.get_value("TEX Payment Transaction", first["transaction"], "status"), "Cancelled")
		out = public.mock_pay(transaction=first["transaction"], outcome="success", sig=first["fields"]["success_sig"])
		self.assertEqual(out["status"], "Succeeded")                     # ...and the first one is still paid

	def test_g68_a_second_success_on_a_paid_link_is_kept_and_flagged(self):
		link = self.link()
		first = public.pay_link(token=link["token"])
		frappe.set_user("Administrator")  # nosemgrep: frappe-setuser -- a charge started before this fix
		stale = pay.start_payment(property=fx.PROPERTY, amount="80", currency="EUR",
		                          provider_account=self.p["account"], payment_link=link["link"], description="deposit",
		                          customer={}, return_url=_return_url(), idempotency_key="g68-stale-tab")
		frappe.set_user("Guest")  # nosemgrep: frappe-setuser -- the guest pays in both tabs
		public.mock_pay(transaction=first["transaction"], outcome="success", sig=first["fields"]["success_sig"])
		public.mock_pay(transaction=stale["transaction"], outcome="success", sig=stale["fields"]["success_sig"])
		frappe.set_user("Administrator")  # nosemgrep: frappe-setuser -- finance looks
		self.assertEqual(frappe.db.get_value("TEX Payment Transaction", stale["transaction"], "status"), "Succeeded")
		lk = frappe.get_doc("TEX Payment Link", link["link"])
		self.assertEqual((lk.status, D(lk.paid_amount)), ("Paid", D("160")))  # the money is recorded, never lost
		self.assertTrue(frappe.db.exists("TEX Audit Event", {"action": "payment_link.overpaid",
		                                                     "reference_name": link["link"]}))
		self.assertEqual(frappe.db.count("TEX Audit Event", {"action": "payment_link.overpaid",
		                                                     "reference_name": link["link"]}), 1)

	# ─── G-68 refund target ──────────────────────────────────────────────

	def paid_and_second(self, session):
		b1 = guest_books(session=f"{session}-1")
		p1 = b1["payment"]
		public.mock_pay(transaction=p1["transaction"], outcome="success", sig=p1["fields"]["success_sig"])
		b2 = guest_books(session=f"{session}-2", guest={**GUEST, "email": f"{session}.second@example.com"})
		frappe.set_user("Administrator")  # nosemgrep: frappe-setuser -- finance user
		return b1["booking"], b2["booking"], p1["transaction"]

	def test_g68_a_refund_after_a_transfer_comes_from_the_booking_holding_the_money(self):
		b1, b2, txn = self.paid_and_second("g68-rf")
		pay.transfer(txn, from_booking=b1, to_booking=b2, amount="252.75", reason="guest moved the deposit")
		paid = lambda b: D(frappe.db.get_value("TEX Booking", b, "paid_amount"))  # noqa: E731
		balance = lambda b: D(frappe.db.get_value("TEX Booking", b, "balance_amount"))  # noqa: E731
		before = (paid(b1), balance(b1))
		self.assertEqual((paid(b1), paid(b2)), (D("0"), D("252.75")))
		r = pay.refund(txn, amount="50", reason="goodwill", idempotency_key="g68-rf-1")
		self.assertEqual(r["status"], "Succeeded")
		rows = frappe.get_all("TEX Payment Allocation", filters={"transaction": txn, "allocation_type": "Refund"},
		                      fields=["booking", "amount"])
		self.assertEqual([(x.booking, D(x.amount)) for x in rows], [(b2, D("50"))])
		self.assertEqual((paid(b1), balance(b1)), before)                 # the first booking is untouched
		self.assertEqual(paid(b2), D("202.75"))
		self.assertEqual(frappe.db.get_value("TEX Payment Transaction", r["refund"], "booking"), b2)
		with self.assertRaises(frappe.ValidationError):                   # the first booking holds nothing now
			pay.refund(txn, amount="10", reason="wrong booking", idempotency_key="g68-rf-2", booking=b1)

	def test_g68_a_refund_split_over_bookings_must_name_one(self):
		b1, b2, txn = self.paid_and_second("g68-amb")
		pay.transfer(txn, from_booking=b1, to_booking=b2, amount="20", reason="part of the deposit")
		with self.assertRaisesRegex(frappe.ValidationError, "which booking"):
			pay.refund(txn, amount="10", reason="goodwill", idempotency_key="g68-amb-1")
		with self.assertRaises(frappe.ValidationError):                   # more than that booking holds
			pay.refund(txn, amount="30", reason="goodwill", idempotency_key="g68-amb-2", booking=b2)
		r = pay.refund(txn, amount="10", reason="goodwill", idempotency_key="g68-amb-3", booking=b2)
		self.assertEqual(r["status"], "Succeeded")
		self.assertEqual(D(frappe.db.get_value("TEX Booking", b2, "paid_amount")), D("10"))
		self.assertEqual(D(frappe.db.get_value("TEX Booking", b1, "paid_amount")), D("232.75"))


class FakeIyzico:
	"""Stands in for iyzico's API (``IyzicoProvider._post``): each checkout form gets its own
	token; ``answers`` says what DETAIL answers for a token (a dict, or an exception to raise)."""

	def __init__(self):
		self.issued: list[str] = []
		self.answers: dict = {}
		self.calls: list[tuple[str, dict]] = []

	@staticmethod
	def paid(txn: str, payment: str, price="100.00", paid_price=None, currency="EUR") -> dict:
		return {"status": "success", "paymentStatus": "SUCCESS", "conversationId": txn, "basketId": txn,
		        "price": price, "paidPrice": paid_price or price, "currency": currency, "paymentId": payment,
		        "itemTransactions": [{"paymentTransactionId": f"{payment}-I"}], "cardAssociation": "VISA",
		        "lastFourDigits": "4242", "fraudStatus": 1}

	@staticmethod
	def failed(txn: str) -> dict:
		return {"status": "success", "paymentStatus": "FAILURE", "conversationId": txn, "errorCode": "10051",
		        "errorMessage": "Insufficient funds"}

	def patch(self):
		from kamra.tex.payments.providers import turkey

		fake = self

		def _post(provider, path, payload):
			fake.calls.append((path, payload))
			if path == turkey.IyzicoProvider.INIT:
				token = f"tok-{len(fake.issued) + 1}"
				fake.issued.append(token)
				return {"status": "success", "token": token, "paymentPageUrl": f"https://sandbox-cpp.test/?t={token}"}
			if path == turkey.IyzicoProvider.REFUND:
				return {"status": "success", "paymentTransactionId": f"R-{payload['paymentTransactionId']}"}
			answer = fake.answers.get(payload.get("token"))
			if isinstance(answer, Exception):
				raise answer
			return answer(payload["conversationId"]) if callable(answer) else (answer or {"status": "failure"})

		return mock.patch.object(turkey.IyzicoProvider, "_post", _post)


class SqlSpy:
	"""Records every SQL statement (whitespace-collapsed) sent through ``frappe.db.sql``."""

	def __init__(self, fail_on: str | None = None):
		self.seen: list[str] = []
		self.fail_on = fail_on

	def __enter__(self):
		db = frappe.local.db
		real = db.sql

		def sql(query, *args, **kwargs):
			q = " ".join(str(query).split())
			self.seen.append(q)
			if self.fail_on and self.fail_on in q:
				raise frappe.QueryTimeoutError("Lock wait timeout exceeded")
			return real(query, *args, **kwargs)

		self._patch = mock.patch.object(db, "sql", side_effect=sql)
		self._patch.start()
		return self

	def __exit__(self, *exc):
		self._patch.stop()

	def loads(self, table: str, start: int = 0) -> list[str]:
		"""Full-row document loads of ``table`` (``frappe.get_doc``) from position ``start``."""
		return [q for q in self.seen[start:] if q.startswith(f"SELECT * FROM `tab{table}` WHERE `name` = %s")]


class TestGoLivePaymentsReview(TexTestCase):
	"""Review of the go-live hardening (ADR-041). G-67: a Sandbox account stays on its sandbox
	host, a live site runs no sandbox gateway, a gated account still settles money a gateway
	holds, a refused capture is on record and refundable, guests hear a generic reason. G-68:
	callbacks ask the gateway before locking and read what they lock; a refund takes the
	unallocated money first and names the booking it comes from; an iyzico charge has one
	checkout, a charge whose restart fails is superseded; a late payment on a closed link is
	flagged; re-verification survives a gateway error."""

	def setUp(self):
		super().setUp()
		self.p = setup_site_and_payments(self.f)

	def account(self, provider, environment="Sandbox", **kw):
		return frappe.get_doc({"doctype": "TEX Payment Provider Account", "label": kw.pop("label", None) or
		                       f"{provider} {environment} {frappe.generate_hash(length=4)}", "property": fx.PROPERTY,
		                       "provider": provider, "environment": environment, "enabled": 1, "currencies": "EUR",
		                       **kw}).insert(ignore_permissions=True)

	def iyzico(self, **kw):
		return self.account("iyzico", api_key="ak-test", secret_key="sk-test", **kw)

	def charge(self, account: str, key: str, amount="100", **kw) -> dict:
		return pay.start_payment(property=fx.PROPERTY, amount=amount, currency="EUR", provider_account=account,
		                         description="test", customer={}, return_url=_return_url(), idempotency_key=key, **kw)

	def link(self, amount="80", account=None):
		frappe.set_user("Administrator")  # nosemgrep: frappe-setuser -- the agent sends a link
		out = pay.create_link(property=fx.PROPERTY, amount=amount, currency="EUR", description="deposit",
		                      provider_account=account or self.p["account"], guest_name="Link Guest")
		frappe.set_user("Guest")  # nosemgrep: frappe-setuser -- the guest opens the link
		return out

	def audits(self, action: str, name: str) -> list[dict]:
		import json

		return [json.loads(v or "{}") for v in frappe.get_all("TEX Audit Event", filters={
			"action": action, "reference_name": name}, pluck="new_value")]

	# ─── G-67 ────────────────────────────────────────────────────────────

	def test_g67_a_sandbox_account_never_reaches_a_live_gateway(self):
		for provider, live in (("iyzico", "https://api.iyzipay.com"), ("Sipay", "https://app.sipay.com.tr/ccpayment"),
		                       ("Virtual POS", "https://sanalpos.isbank.com.tr/fim/est3Dgate"),
		                       ("iyzico", "http://sandbox-api.iyzipay.com")):
			with self.assertRaisesRegex(pay.AccountRefused, "sandbox host", msg=live):
				self.account(provider, gateway_url=live)
		ok = self.iyzico(gateway_url="https://sandbox-api.iyzipay.com")
		ok.db_set("gateway_url", "https://api.iyzipay.com")                # changed behind the controller
		with self.assertRaisesRegex(pay.AccountRefused, "sandbox host"):
			pay.provider_for(ok.name)
		with self.assertRaisesRegex(pay.AccountRefused, "sandbox host"):
			pay.provider_for(ok.name, purpose="settle")                     # a live host never settles either
		self.account("Bank Transfer", gateway_url="https://ignored.test")  # never read by an offline method
		local = "http://localhost:8080"
		self.iyzico(gateway_url=local)                                     # the test site is in developer mode
		with mock.patch.dict(frappe.local.conf, {"developer_mode": 0}):
			with self.assertRaises(pay.AccountRefused):
				self.iyzico(gateway_url=local)

	def test_g67_a_live_site_takes_no_sandbox_payment(self):
		b = guest_books(session="g67-live")
		txn = b["payment"]["transaction"]                                  # a sandbox checkout, before the flag
		frappe.set_user("Administrator")  # nosemgrep: frappe-setuser -- set up
		with mock.patch.dict(frappe.local.conf, {"tex_production": 1}):
			self.assertFalse([m for m in pay.payment_methods(fx.PROPERTY, market=None, currency="EUR", channel=None)
			                  if m["provider_account"] == self.p["account"]])
			with self.assertRaisesRegex(pay.AccountRefused, "tex_production"):
				pay.provider_for(self.p["account"])
			with self.assertRaisesRegex(pay.AccountRefused, "tex_production"):
				self.account("Mock")
			self.account("Mock", enabled=0)                                   # a disabled one can be kept
			self.account("Bank Transfer", bank_name="Test Bank", iban="TR000000")   # no test money moves
			frappe.set_user("Guest")  # nosemgrep: frappe-setuser -- anyone clicks "success" on the mock page
			with self.assertRaisesRegex(pay.AccountRefused, "not available"):
				public.mock_pay(transaction=txn, outcome="success", sig=b["payment"]["fields"]["success_sig"])
		frappe.set_user("Administrator")  # nosemgrep: frappe-setuser -- verify
		self.assertEqual(frappe.db.get_value("TEX Payment Transaction", txn, "status"), "Pending")
		self.assertEqual(frappe.db.get_value("TEX Booking", b["booking"], "payment_status"), "Unpaid")

	def test_g67_a_gated_account_still_settles_money_the_gateway_holds(self):
		gw = FakeIyzico()
		acc = self.iyzico()
		with gw.patch():
			txn = self.charge(acc.name, "g67-gated")["transaction"]
			# a Production account from before certification was required (or changed in SQL)
			acc.db_set("environment", "Production")
			with self.assertRaisesRegex(pay.AccountRefused, "not certified"):
				self.charge(acc.name, "g67-gated-new")                       # no new money
			gated = {r["account"]: r for r in pay.gated_accounts(fx.PROPERTY)}
			self.assertEqual((gated[acc.name]["problem"], gated[acc.name]["open_charges"]), ("uncertified", 1))
			from kamra.patches.tex.p19_payments_go_live_check import execute

			execute()                                                      # the go-live check reports it
			self.assertEqual(self.audits("payment_account.gated", acc.name)[0]["open_charge_names"], [txn])
			gw.answers["tok-1"] = lambda t: gw.paid(t, "P1")
			self.assertEqual(pay.complete(txn, params={"token": "tok-1"})["status"], "Succeeded")   # ...but settles
			self.assertTrue(self.audits("payment_account.settled_while_gated", acc.name))
			r = pay.refund(txn, amount="10", reason="goodwill", idempotency_key="g67-gated-r")
			self.assertEqual(r["status"], "Succeeded")
		acc.reload()
		acc.label = "renamed"
		with self.assertRaisesRegex(pay.AccountRefused, "not certified"):
			acc.save()                                                     # not enabled as it is...
		acc.reload()
		acc.enabled = 0
		acc.save()                                                         # ...but it can be switched off

	def test_a_gated_accounts_charge_the_job_keeps_asking_is_on_record_once_a_day(self):
		"""LO-20 (2K-4): each question about a charge of a gated account wrote a ``settled_while_gated`` audit, and
		the re-verification job asks a Pending charge every 5 minutes for up to 2 hours past its deadline: one
		charge filled the trail. It is on record once per charge and day; another charge has its own."""
		gw = FakeIyzico()
		acc = self.iyzico()
		with gw.patch():
			first = self.charge(acc.name, "lo20-a")["transaction"]
			second = self.charge(acc.name, "lo20-b")["transaction"]
			acc.db_set("environment", "Production")                        # gated: uncertified (G-67)
			for token in gw.issued:
				gw.answers[token] = {"status": "success", "paymentStatus": "WAITING"}   # the guest has not paid
			later = add_to_date(now_datetime(), minutes=5)
			for tick in range(3):
				pay.reverify_pending(now=add_to_date(later, minutes=5 * tick))
		audited = [a["transaction"] for a in self.audits("payment_account.settled_while_gated", acc.name)]
		self.assertEqual(sorted(audited), sorted([first, second]))
		self.assertEqual({frappe.db.get_value("TEX Payment Transaction", t, "status") for t in (first, second)},
		                 {"Pending"})

	def test_a_refund_on_a_gated_account_is_on_record_however_often_its_charge_was_asked(self):
		"""2K-4 review round 1 (LO-20): only the questions about a charge (a callback, a re-verification) are on
		record once a day; money a gated account gives back is on record every time."""
		gw = FakeIyzico()
		acc = self.iyzico()
		with gw.patch():
			txn = self.charge(acc.name, "lo20-refund")["transaction"]
			acc.db_set("environment", "Production")
			gw.answers["tok-1"] = lambda t: gw.paid(t, "P1")
			self.assertEqual(pay.complete(txn, params={"token": "tok-1"})["status"], "Succeeded")
			for n in range(2):
				pay.refund(txn, amount="10", reason="goodwill", idempotency_key=f"lo20-refund-{n}")
		audited = [a["transaction"] for a in self.audits("payment_account.settled_while_gated", acc.name)]
		self.assertEqual(audited, [txn] * 3)

	def test_g67_a_capture_tex_refused_is_on_record_and_refundable(self):
		gw = FakeIyzico()
		acc = self.iyzico()
		with gw.patch():
			txn = self.charge(acc.name, "g67-refused")["transaction"]
			gw.answers["tok-1"] = lambda t: gw.paid(t, "P7", price="99.99")
			self.assertEqual(pay.complete(txn, params={"token": "tok-1"})["status"], "Failed")
			row = frappe.db.get_value("TEX Payment Transaction", txn, ["error_code", "provider_ref"], as_dict=True)
			self.assertEqual((row.error_code, row.provider_ref), ("AMOUNT_MISMATCH", "tok-1"))  # the token is kept
			self.assertEqual(pay.complete(txn, params={"token": "tok-1"}).get("replay"), True)
			records = self.audits("payment.capture_mismatch", txn)
			self.assertEqual(len(records), 1)                               # once per capture
			self.assertEqual({k: records[0][k] for k in ("provider_ref", "amount", "currency", "code")},
			                 {"provider_ref": "P7|P7-I", "amount": "99.99", "currency": "EUR",
			                  "code": "AMOUNT_MISMATCH"})
			detail = pay_api.transaction(txn)
			self.assertEqual((detail["refundable"], detail["refund_currency"]), ("99.99", "EUR"))
			with self.assertRaises(frappe.ValidationError):
				pay.refund(txn, amount="100", reason="too much", idempotency_key="g67-refused-0")
			r = pay.refund(txn, amount="99.99", reason="captured but refused", idempotency_key="g67-refused-1")
			self.assertEqual(r["status"], "Succeeded")
			self.assertEqual(gw.calls[-1][1]["paymentTransactionId"], "P7-I")   # the captured payment
			self.assertEqual(frappe.db.get_value("TEX Payment Transaction", r["refund"], ["currency", "booking"]),
			                 ("EUR", None))
			self.assertEqual(pay_api.transaction(txn)["refundable"], "0.00")

	def test_g67_guests_hear_a_generic_reason(self):
		acc = self.account("Mock", label="Fixed sandbox")
		link = self.link(account=acc.name)
		frappe.set_user("Administrator")  # nosemgrep: frappe-setuser -- the account goes wrong behind the controller
		acc.db_set("environment", "Production")
		with self.assertRaisesRegex(pay.AccountRefused, "only be used in Sandbox"):   # staff hear why, at once
			pay.create_link(property=fx.PROPERTY, amount="10", currency="EUR", description="x",
			                provider_account=acc.name)
		from kamra.tex.services import quoting

		offer_key = quoting.sign({"kind": "offer"})
		frappe.set_user("Guest")  # nosemgrep: frappe-setuser -- the guest opens the link
		with self.assertRaises(pay.AccountRefused) as caught:
			public.pay_link(token=link["token"])
		self.assertEqual(str(caught.exception), "This payment method is not available.")
		with mock.patch.dict(frappe.local.conf):
			frappe.local.conf.pop("encryption_key", None)
			with self.assertRaises(frappe.ValidationError) as caught:
				public.quote(site=SLUG, offer_key=offer_key)
		self.assertNotIn("encryption", str(caught.exception))
		self.assertIn("temporarily unavailable", str(caught.exception))

	# ─── G-68 locks ──────────────────────────────────────────────────────

	def test_g68_callbacks_ask_the_gateway_first_then_read_what_they_lock(self):
		from kamra.tex.payments.providers import simple

		link = self.link()
		first = public.pay_link(token=link["token"])
		with SqlSpy() as spy:
			self.assertEqual(public.pay_link(token=link["token"])["transaction"], first["transaction"])  # a second tab
		self.assertTrue(any("tabTEX Payment Link" in q and q.endswith("FOR UPDATE NOWAIT") for q in spy.seen))
		loads = spy.loads("TEX Payment Transaction")
		self.assertTrue(loads and loads[0].endswith("FOR UPDATE"), loads)          # the reused charge as it is now
		keyed = [q for q in spy.seen if q.startswith("SELECT") and "tabTEX Payment Transaction" in q
		         and "idempotency_key" in q]
		# looked up by key without locking: a missing key would lock a gap of the unique index
		# and hold up other payments' inserts during this one's gateway call
		self.assertTrue(keyed and not any("FOR UPDATE" in q for q in keyed), keyed)
		with SqlSpy(fail_on="NOWAIT"), self.assertRaisesRegex(pay.PaymentBusy, "being started"):
			public.pay_link(token=link["token"])                          # another start holds the link
		asked: list[int] = []
		real = simple.MockProvider.handle_callback

		def handle_callback(provider, *args, **kwargs):
			asked.append(len(spy.seen))
			return real(provider, *args, **kwargs)

		with SqlSpy() as spy, mock.patch.object(simple.MockProvider, "handle_callback", handle_callback):
			public.mock_pay(transaction=first["transaction"], outcome="success", sig=first["fields"]["success_sig"])
		locks = [i for i, q in enumerate(spy.seen) if "FOR UPDATE" in q]
		self.assertTrue(asked and locks and asked[0] <= locks[0], "the gateway is asked before any lock")
		for table in ("TEX Payment Transaction", "TEX Payment Link"):
			loads = spy.loads(table, locks[0])
			self.assertTrue(loads and loads[0].endswith("FOR UPDATE"), (table, loads))
		b = guest_books(session="g68-lockread")
		frappe.set_user("Administrator")  # nosemgrep: frappe-setuser -- a payment reaches the booking
		from kamra.tex.services import booking as booking_svc

		with SqlSpy() as spy:
			booking_svc.apply_payment(b["booking"], D("0"), reference="spy")
		self.assertTrue(spy.loads("TEX Booking")[0].endswith("FOR UPDATE"), spy.loads("TEX Booking"))

	# ─── G-68 refunds ────────────────────────────────────────────────────

	def paid_booking(self, session):
		b = guest_books(session=session)
		p = b["payment"]
		public.mock_pay(transaction=p["transaction"], outcome="success", sig=p["fields"]["success_sig"])
		frappe.set_user("Administrator")  # nosemgrep: frappe-setuser -- finance user
		return b["booking"], p["transaction"]

	def test_g68_a_refund_takes_the_unallocated_money_first(self):
		b1, txn = self.paid_booking("g68-unalloc")
		paid = lambda: D(frappe.db.get_value("TEX Booking", b1, "paid_amount"))  # noqa: E731
		pay.release(txn, booking=b1, amount="40", reason="overpaid")        # 40 of the payment is on no booking
		self.assertEqual(paid(), D("212.75"))
		r = pay.refund(txn, amount="30", reason="the overpayment", idempotency_key="g68-unalloc-1")
		self.assertEqual(paid(), D("212.75"))                              # the booking keeps its money
		self.assertIsNone(frappe.db.get_value("TEX Payment Transaction", r["refund"], "booking"))
		r = pay.refund(txn, amount="5", reason="named, but unallocated", idempotency_key="g68-unalloc-2", booking=b1)
		self.assertEqual(paid(), D("212.75"))
		self.assertIsNone(frappe.db.get_value("TEX Payment Transaction", r["refund"], "booking"))  # nothing came off it
		r = pay.refund(txn, amount="20", reason="rest and more", idempotency_key="g68-unalloc-3", booking=b1)
		self.assertEqual(paid(), D("197.75"))                              # 5 unallocated, then 15 from it
		self.assertEqual(frappe.db.get_value("TEX Payment Transaction", r["refund"], "booking"), b1)
		self.assertEqual([D(x) for x in frappe.get_all("TEX Payment Allocation", filters={
			"transaction": txn, "allocation_type": "Refund"}, pluck="amount")], [D("15")])
		self.assertEqual(pay_api.transaction(txn)["booking_nets"], {b1: "197.75"})

	def test_g68_the_refund_screen_offers_only_bookings_holding_money(self):
		b1, txn = self.paid_booking("g68-nets-1")
		b2 = guest_books(session="g68-nets-2", guest={**GUEST, "email": "nets.second@example.com"})["booking"]
		frappe.set_user("Administrator")  # nosemgrep: frappe-setuser -- finance user
		pay.transfer(txn, from_booking=b1, to_booking=b2, amount="252.75", reason="moved")
		detail = pay_api.transaction(txn)
		self.assertEqual(detail["booking"], b1)
		self.assertEqual(detail["booking_nets"], {b2: "252.75"})           # b1 holds nothing any more

	# ─── G-68 superseded charges ─────────────────────────────────────────

	def test_g68_another_tab_supersedes_an_iyzico_charge(self):
		gw = FakeIyzico()
		acc = self.iyzico()
		link = self.link(account=acc.name)
		with gw.patch():
			tab1 = public.pay_link(token=link["token"])
			frappe.local.message_log = []
			tab2 = public.pay_link(token=link["token"])
			self.assertNotEqual(tab2["transaction"], tab1["transaction"])  # one checkout form per charge
			self.assertFalse(frappe.local.message_log)                     # the guest sees no error
			first = frappe.db.get_value("TEX Payment Transaction", tab1["transaction"],
			                            ["status", "error_code", "provider_ref"], as_dict=True)
			self.assertEqual((first.status, first.error_code, first.provider_ref), ("Cancelled", "SUPERSEDED", "tok-1"))
			gw.answers["tok-1"] = lambda t: gw.paid(t, "P1", price="80.00")
			gw.answers["tok-2"] = lambda t: gw.paid(t, "P2", price="80.00")
			# the guest pays both pages: both payments are recorded, never lost, and flagged
			self.assertEqual(pay.complete(tab1["transaction"], params={"token": "tok-1"})["status"], "Succeeded")
			self.assertEqual(pay.complete(tab2["transaction"], params={"token": "tok-2"})["status"], "Succeeded")
		frappe.set_user("Administrator")  # nosemgrep: frappe-setuser -- finance looks
		self.assertEqual(D(frappe.db.get_value("TEX Payment Link", link["link"], "paid_amount")), D("160"))
		self.assertTrue(self.audits("payment_link.overpaid", link["link"]))

	def test_g68_a_link_whose_gateway_refuses_a_restart_starts_a_new_charge(self):
		from kamra.tex.payments.providers import simple

		link = self.link()
		first = public.pay_link(token=link["token"])
		real = simple.MockProvider.create_checkout
		refused: list[str] = []

		def create_checkout(provider, intent):
			if intent.transaction == first["transaction"]:
				refused.append(intent.transaction)
				raise ProviderError("duplicate order id")                   # e.g. Sipay's invoice_id
			return real(provider, intent)

		with mock.patch.object(simple.MockProvider, "create_checkout", create_checkout):
			again = public.pay_link(token=link["token"])
		self.assertEqual(refused, [first["transaction"]])
		self.assertNotEqual(again["transaction"], first["transaction"])      # the link can still be paid
		self.assertEqual(frappe.db.get_value("TEX Payment Transaction", first["transaction"], "status"), "Cancelled")
		out = public.mock_pay(transaction=first["transaction"], outcome="success", sig=first["fields"]["success_sig"])
		self.assertEqual(out["status"], "Succeeded")                         # a late payment is still recorded
		frappe.set_user("Administrator")  # nosemgrep: frappe-setuser -- verify
		self.assertEqual(frappe.db.get_value("TEX Payment Link", link["link"], "status"), "Paid")

	def test_g68_a_late_payment_on_a_cancelled_link_is_flagged(self):
		link = self.link()
		tab = public.pay_link(token=link["token"])
		frappe.set_user("Administrator")  # nosemgrep: frappe-setuser -- staff cancel the link
		pay.cancel_link(link["link"], "sent by mistake")
		frappe.set_user("Guest")  # nosemgrep: frappe-setuser -- the open page is still paid
		public.mock_pay(transaction=tab["transaction"], outcome="success", sig=tab["fields"]["success_sig"])
		frappe.set_user("Administrator")  # nosemgrep: frappe-setuser -- finance looks
		flagged = self.audits("payment_link.paid_after_close", link["link"])
		self.assertEqual([(f["status_before"], f["transaction"]) for f in flagged],
		                 [("Cancelled", tab["transaction"])])

	# ─── G-68 re-verification ────────────────────────────────────────────

	def test_g68_reverify_recovers_a_real_gateway_payment(self):
		import requests

		gw = FakeIyzico()
		acc = self.iyzico()
		with gw.patch():
			txn = self.charge(acc.name, "g68-reverify")["transaction"]
			gw.answers["tok-1"] = lambda t: gw.failed(t)
			self.assertEqual(pay.complete(txn, params={"token": "tok-1"})["status"], "Failed")
			gw.answers["tok-1"] = requests.ConnectionError("gateway unreachable")
			with self.assertRaisesRegex(frappe.ValidationError, "did not confirm"):
				pay_api.reverify(txn)
			self.assertEqual(frappe.db.get_value("TEX Payment Transaction", txn, "status"), "Failed")
			gw.answers["tok-1"] = lambda t: gw.paid(t, "P3")                  # the gateway did capture it
			self.assertEqual(pay_api.reverify(txn)["status"], "Succeeded")   # Failed → Succeeded, verified
			# a charge that still carries two tokens (checkouts from before one-per-charge): the newest
			# errors, the older one holds the payment
			second = self.charge(acc.name, "g68-reverify-2")["transaction"]
			frappe.db.set_value("TEX Payment Transaction", second, "provider_ref", "tok-9 tok-2")
			gw.answers["tok-9"] = requests.ConnectionError("gateway unreachable")
			gw.answers["tok-2"] = lambda t: gw.paid(t, "P4")
			self.assertEqual(pay_api.reverify(second)["status"], "Succeeded")


class TestSessionSiteDay(TexTestCase):
	"""G-91: staff date pickers start on the site's day, not the browser's. The session
	bootstrap carries that day (and the site's time zone) for the whole staff app."""

	def test_g91_the_session_carries_the_sites_day_and_zone(self):
		from datetime import datetime

		from frappe.utils import get_system_timezone, getdate

		from kamra.tex.api import session

		before = str(getdate())
		server = session.bootstrap()["server"]
		self.assertIn(server["today"], {before, str(getdate())})
		self.assertEqual(server["time_zone"], get_system_timezone())
		self.assertEqual(server["now"][:10], server["today"])          # one instant: day and clock agree
		# the day is the date on the site's wall clock, not UTC's or the server process's
		just_after_midnight = datetime(2026, 3, 10, 0, 0, 30)
		with mock.patch.object(session, "now_datetime", return_value=just_after_midnight):
			server = session.bootstrap()["server"]
		self.assertEqual(server["today"], "2026-03-10")
		self.assertEqual(server["now"], "2026-03-10T00:00:30")
