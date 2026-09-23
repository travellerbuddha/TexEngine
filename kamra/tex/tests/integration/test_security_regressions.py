"""Regression tests for the adversarial security review (ADR-021, ADR-022).

H1 forged callbacks cannot fail a payment · H2 a guest cannot route a payment link
through another gateway · H3 idempotency replays never return a stranger's booking ·
H4 Desk/REST cannot bypass capabilities, scope, revision lifecycle or cost hiding ·
M2 guests of other tenants stay invisible · L4 shared FX rates are platform-only.
"""

import hashlib
import hmac
from unittest import mock

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


class TestGoLivePayments(TexTestCase):
	"""Go-live hardening (ADR-041). G-89: signatures never fall back to the site name."""

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
