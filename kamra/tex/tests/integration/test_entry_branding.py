"""Entry screens and navigation sub-sections (G-60, G-64, ADR-060).

G-60: the site root leads somewhere (the TEX admin app for desk users, the sign-in page
otherwise) while a booking site's own host keeps serving its booking engine at "/"; the
app's display strings say TEX Engine (the app stays ``kamra``, ADR-001); every entry
screen can offer the source (AGPL-3.0 section 13).

G-64: the cross-record lists behind the new navigation entries return only the rows of
hotels where the caller holds the capability the entry's screen needs; without it they
refuse. The existing endpoints the other new entries open refuse too.
"""

from unittest import mock

import frappe
from frappe.utils import add_days, getdate, nowdate, set_request
from frappe.website.serve import get_response

from kamra.tex.security import scope
from kamra.tex.services import sites
from kamra.tex.tests.integration import fixtures as fx
from kamra.tex.tests.integration.test_commercial_flows import SLUG
from kamra.tex.tests.integration.test_critical_journey import TexTestCase
from kamra.tex.tests.integration.test_custom_domains import DomainCase

OTHER = "TEX Entry Other Hotel"
HOST = "book.entry-test.example"
NO_RATES = "TEX Entry Reservations Only"


def root(user: str, host: str = "test.localhost", path: str = "/"):
	"""GET ``path`` on ``host`` as ``user`` through Frappe's website router. The site's home page
	is the SPA's ``kamra`` page, as ``kamra.install`` sets it."""
	frappe.set_user(user)  # nosemgrep: frappe-setuser -- a visitor or a staff user opening the site
	set_request(method="GET", path=path, base_url=f"https://{host}/")
	frappe.local.request_ip = "203.0.113.9"
	frappe.flags.redirect_location = None
	with mock.patch("frappe.website.path_resolver.get_home_page", return_value="kamra"):
		return get_response(path)


class TestSiteRoot(DomainCase):
	"""``/`` was a blank page: the SPA shell served outside the path its router is mounted at."""

	def tearDown(self):
		frappe.flags.redirect_location = None
		super().tearDown()

	def test_a_guest_is_sent_to_sign_in(self):
		resp = root("Guest")
		self.assertEqual(resp.status_code, 302)
		self.assertEqual(resp.headers["Location"], "/kamra/login")

	def test_a_desk_user_is_sent_to_the_tex_admin_app(self):
		user = fx.ensure_user("entry-desk@example.com", ["Revenue Manager"])
		resp = root(user)
		self.assertEqual(resp.status_code, 302)
		self.assertEqual(resp.headers["Location"], "/kamra/tex")
		resp = root("Administrator", path="/index")
		self.assertEqual((resp.status_code, resp.headers["Location"]), (302, "/kamra/tex"))

	def test_the_app_itself_is_still_served_below_its_mount(self):
		for path in ("/kamra", "/kamra/tex", "/kamra/login"):
			resp = root("Guest", path=path)
			self.assertEqual(resp.status_code, 200, path)
			self.assertIn('<div id="root">', resp.get_data(as_text=True), path)

	def test_a_booking_sites_own_host_still_serves_its_booking_engine_at_root(self):
		self.add(SLUG, HOST)
		self.verify(SLUG, HOST)
		sites.clear_host_cache()
		for user in ("Guest", "Administrator"):
			with mock.patch("kamra.tex.booking_host.booking_html", return_value="<html><head></head><body></body></html>"):
				resp = root(user, host=HOST)
			self.assertEqual(resp.status_code, 200, user)
			self.assertIn(f'<meta name="tex-booking-site" content="{SLUG}">', resp.get_data(as_text=True))
		frappe.set_user("Administrator")  # nosemgrep: frappe-setuser -- back to the test's user

	def test_the_page_title_is_the_brand_escaped(self):
		with mock.patch("kamra.tex.entry.brand_name", return_value="Aurora <b>&</b> Co"):
			html = root("Guest", path="/kamra/login").get_data(as_text=True)
		self.assertIn("<title>Aurora &lt;b&gt;&amp;&lt;/b&gt; Co</title>", html)
		self.assertNotIn("Kamra PMS", html)


class TestDisplayStrings(TexTestCase):
	def test_hooks_say_tex_engine_and_keep_the_app_name(self):
		from kamra import hooks

		self.assertEqual(hooks.app_name, "kamra")                           # ADR-001
		self.assertEqual(hooks.app_title, "TEX Engine")
		self.assertEqual(frappe.get_hooks("app_title", app_name="kamra"), ["TEX Engine"])
		self.assertNotIn("PMS", hooks.app_description)
		self.assertEqual(hooks.app_license, "agpl-3.0")
		tile = hooks.add_to_apps_screen[0]
		self.assertEqual((tile["name"], tile["title"], tile["route"]), ("kamra", "TEX Engine", "/kamra"))

	def test_the_sign_in_page_reads_the_brand_and_the_source_offer_as_a_guest(self):
		from kamra.tex.api import session

		frappe.set_user("Guest")  # nosemgrep: frappe-setuser -- the sign-in page is public
		frappe.local.request_ip = "203.0.113.9"
		info = session.entry()
		self.assertEqual(info["product"], "TEX Engine")
		self.assertTrue(info["brand_name"])
		self.assertEqual(info["upstream"]["name"], "Kamra PMS")
		self.assertEqual(info["license"]["name"], "AGPL-3.0")
		self.assertTrue(info["source_url"].startswith("https://"))
		self.assertEqual(set(info), {"product", "brand_name", "source_url", "upstream", "license"})

	def test_only_an_https_source_url_from_the_site_config_is_used(self):
		from kamra.tex import entry

		with mock.patch.dict(frappe.local.conf, {"tex_source_url": "https://git.example.com/tex"}):
			self.assertEqual(entry.source_url(), "https://git.example.com/tex")
		with mock.patch.dict(frappe.local.conf, {"tex_source_url": "javascript:alert(1)"}):
			self.assertEqual(entry.source_url(), entry.SOURCE_URL)


class ListCase(TexTestCase):
	"""Users: ``rev`` Revenue Manager at the test hotel; ``agent`` Reservations Agent there (no
	cost, no booking site, no reports); ``blind`` only ``reservation.view`` there; ``foreign``
	Hotel Admin of another hotel."""

	def setUp(self):
		super().setUp()
		if not frappe.db.exists("Property", OTHER):
			frappe.get_doc({"doctype": "Property", "property_name": OTHER, "city": "Kemer", "country": "Turkey",
			                "currency": "EUR"}).insert(ignore_permissions=True)
		fx.ensure("TEX Permission Profile", {"profile_name": NO_RATES},
		          {"profile_name": NO_RATES, "capabilities": [{"capability": "reservation.view"}]})
		self.rev = fx.ensure_user("entry-rev@example.com", ["Revenue Manager"])
		self.agent = fx.ensure_user("entry-agent@example.com", ["Call Center Agent"])
		self.blind = fx.ensure_user("entry-blind@example.com", ["Front Desk"])
		self.foreign = fx.ensure_user("entry-foreign@example.com", ["Hotel Admin"])
		for user, prop, profile in ((self.rev, fx.PROPERTY, "Revenue Manager"),
		                            (self.agent, fx.PROPERTY, "Reservations Agent"),
		                            (self.blind, fx.PROPERTY, NO_RATES), (self.foreign, OTHER, "Hotel Admin")):
			fx.ensure("TEX Access Grant", {"user": user, "property": prop},
			          {"user": user, "scope_level": "Hotel", "property": prop, "permission_profile": profile})
		scope.clear_cache()

	def as_user(self, user):
		frappe.set_user(user)  # nosemgrep: frappe-setuser -- the caller whose scope is tested
		scope.clear_cache()

	def refused(self, fn, **kw):
		with self.assertRaises(frappe.PermissionError, msg=f"{frappe.session.user} {fn.__name__} {kw}"):
			fn(**kw)

	def assert_tenancy(self, fn, *, own, **kw):
		"""``foreign`` sees none of the test hotel's rows and is refused it by name; ``blind`` is
		refused everywhere. ``own(rows)`` → the rows of the test hotel."""
		self.as_user(self.foreign)
		self.assertEqual(own(fn(**kw)), [])
		self.refused(fn, property=fx.PROPERTY, **kw)
		self.as_user(self.blind)
		self.refused(fn, **kw)
		self.refused(fn, property=fx.PROPERTY, **kw)


class TestContractLists(ListCase):
	def setUp(self):
		super().setUp()
		self.c = fx.create_contract(self.f, code="ENTRY-G64")

	def test_versions_of_every_granted_hotel(self):
		from kamra.tex.api import lists

		self.as_user(self.rev)
		rows = lists.versions()["rows"]
		mine = [r for r in rows if r["name"] == self.c["version"]]
		self.assertEqual(len(mine), 1)
		self.assertEqual((mine[0]["contract_code"], mine[0]["state"], mine[0]["property"]),
		                 ("ENTRY-G64", "live", fx.PROPERTY))
		self.assertNotIn("payload", mine[0])
		self.assertEqual({r["property"] for r in rows}, {fx.PROPERTY})
		self.assertTrue(lists.versions(property=fx.PROPERTY, status="Published")["rows"])
		self.assertFalse([r for r in lists.versions(status="Draft")["rows"] if r["name"] == self.c["version"]])
		self.assert_tenancy(lists.versions, own=lambda out: [r for r in out["rows"] if r["property"] == fx.PROPERTY])

	def test_periods_and_occupancy_rules_are_cost(self):
		from kamra.tex.api import lists

		self.as_user(self.rev)
		periods = [r for r in lists.version_rows(section="periods")["rows"] if r["version"] == self.c["version"]]
		self.assertEqual(sorted(r["period_code"] for r in periods), ["HIGH", "LOW"])
		self.assertEqual(periods[0]["contract_code"], "ENTRY-G64")
		occ = [r for r in lists.version_rows(section="occupancy")["rows"] if r["version"] == self.c["version"]]
		self.assertEqual(len(occ), 5)
		self.assertIsInstance(occ[0]["value"], str)                         # decimals as strings, never floats
		for section in ("periods", "occupancy"):
			self.as_user(self.agent)                                         # sells, sees no cost
			self.refused(lists.version_rows, section=section)
			self.refused(lists.version_rows, section=section, property=fx.PROPERTY)
			own = lambda out: [r for r in out["rows"] if r["property"] == fx.PROPERTY]  # noqa: E731
			self.assert_tenancy(lists.version_rows, own=own, section=section)
		self.as_user(self.rev)
		with self.assertRaises(frappe.ValidationError):
			lists.version_rows(section="period_rates")

	def test_rate_plans_show_amounts_only_to_who_sees_cost(self):
		from kamra.tex.api import lists

		self.as_user(self.rev)
		plans = [r for r in lists.version_rows(section="rate_plans")["rows"] if r["version"] == self.c["version"]]
		nrf = next(r for r in plans if r["rate_plan"] == self.f["rate_plans"]["NRF"])
		self.assertEqual((nrf["op"], nrf["refundable"], nrf["rate_plan_code"]), ("ADJUST_PERCENT", 0, "NRF"))
		self.as_user(self.agent)
		plans = [r for r in lists.version_rows(section="rate_plans")["rows"] if r["version"] == self.c["version"]]
		self.assertEqual(len(plans), 2)
		self.assertTrue(all("op" not in r and "value" not in r for r in plans))
		own = lambda out: [r for r in out["rows"] if r["property"] == fx.PROPERTY]  # noqa: E731
		self.assert_tenancy(lists.version_rows, own=own, section="rate_plans")


class TestRestrictionList(ListCase):
	def restrict(self, day, room="STD", **values):
		return frappe.get_doc({"doctype": "TEX ARI Restriction", "property": fx.PROPERTY,
		                       "room_type": self.f["room_types"][room], "restriction_date": day,
		                       **values}).insert(ignore_permissions=True).name

	def test_days_with_the_same_restriction_read_as_one_range(self):
		from kamra.tex.api import lists

		first = getdate(add_days(nowdate(), 200))
		for i in range(3):
			self.restrict(add_days(first, i), min_los=3)
		self.restrict(add_days(first, 5), min_los=3)                       # a gap: a second range
		self.restrict(add_days(first, 1), room="DLX", stop_sell="STOP")
		self.as_user(self.rev)
		out = lists.restrictions(date_from=str(first), date_to=str(add_days(first, 10)))
		std = [r for r in out["rows"] if r["room_type"] == self.f["room_types"]["STD"]]
		self.assertEqual([(r["date_from"], r["date_to"], r["days"], r["min_los"]) for r in std],
		                 [(str(first), str(add_days(first, 2)), 3, 3),
		                  (str(add_days(first, 5)), str(add_days(first, 5)), 1, 3)])
		dlx = [r for r in out["rows"] if r["room_type"] == self.f["room_types"]["DLX"]]
		self.assertEqual([(r["stop_sell"], r["days"], r["room_type_name"]) for r in dlx], [("STOP", 1, "Deluxe Room")])
		own = lambda out: [r for r in out["rows"] if r["property"] == fx.PROPERTY]  # noqa: E731
		self.assert_tenancy(lists.restrictions, own=own, date_from=str(first), date_to=str(add_days(first, 10)))
		self.as_user(self.rev)
		with self.assertRaises(frappe.ValidationError):                       # at most a year at once
			lists.restrictions(date_from=str(first), date_to=str(add_days(first, 400)))


class TestCommunicationList(ListCase):
	def test_communications_of_the_viewers_hotels(self):
		from kamra.tex.api import lists

		guest = frappe.get_doc({"doctype": "Guest", "first_name": "Lena", "last_name": "Entrylist",
		                        "email": "lena.entrylist@example.com"}).insert(ignore_permissions=True).name
		for channel, subject in (("Email", "Your stay at the resort"), ("Phone", "Asked about transfer")):
			frappe.get_doc({"doctype": "TEX Communication", "guest": guest, "property": fx.PROPERTY,
			                "channel": channel, "direction": "Outbound", "status": "Logged",
			                "consent_basis": "Transactional", "subject": subject,
			                "body": "<p>Private note</p>"}).insert(ignore_permissions=True)
		self.as_user(self.rev)
		out = lists.communications(q="Entrylist")
		self.assertEqual(out["total"], 2)
		self.assertEqual({r["guest_name"] for r in out["rows"]}, {"Lena Entrylist"})
		self.assertEqual([r["subject"] for r in lists.communications(q="Entrylist", channel="Phone")["rows"]],
		                 ["Asked about transfer"])
		self.assertTrue(all("body" not in r for r in out["rows"]))
		own = lambda out: [r for r in out["rows"] if r["property"] == fx.PROPERTY]  # noqa: E731
		self.assert_tenancy(lists.communications, own=own, q="Entrylist")
		self.as_user(self.foreign)
		self.assertEqual(lists.communications(q="Entrylist")["total"], 0)


class TestRoomsForTheBookingEngine(ListCase):
	def test_rooms_as_guests_see_them(self):
		from kamra.tex.api import lists

		fx.create_contract(self.f, code="ENTRY-ROOMS")
		self.as_user(self.rev)
		out = lists.rooms(property=fx.PROPERTY)
		std = next(r for r in out["rooms"] if r["name"] == self.f["room_types"]["STD"])
		self.assertEqual((std["room_type_name"], std["adults"], std["children"]), ("Standard Room", 3, 2))
		self.assertIn("ENTRY-ROOMS", std["contracts"])
		self.assertEqual(set(std["translations"]), set(out["languages"]))
		self.as_user(self.agent)                                             # no booking_site.edit
		self.refused(lists.rooms, property=fx.PROPERTY)
		self.as_user(self.foreign)
		self.refused(lists.rooms, property=fx.PROPERTY)
		self.assertEqual(lists.rooms(property=OTHER)["rooms"], [])
		self.as_user(self.blind)
		self.refused(lists.rooms, property=fx.PROPERTY)


class TestEntriesOpenGuardedScreens(ListCase):
	"""The new entries that open an existing screen: its endpoint refuses a user without the
	capability the entry is shown for (hiding the entry is never the control)."""

	def test_existing_endpoints_refuse_without_the_capability(self):
		from kamra.tex.api import content, crm, crs, loyalty, policies, reports

		today = nowdate()
		self.as_user(self.blind)
		self.refused(reports.dashboard, property=fx.PROPERTY)                 # Booking Engine > Analytics
		self.refused(crs.ari_grid, property=fx.PROPERTY, start=today)        # Bulk editor, the ARI grid
		self.refused(content.items, property=fx.PROPERTY)                    # Booking Engine > Content
		self.refused(loyalty.programs)                                       # CRM > Loyalty
		self.refused(crm.abandoned, property=fx.PROPERTY)                    # CRM > Abandoned bookings
		self.refused(policies.list_records, doctype="TEX Promotion", property=fx.PROPERTY)  # Promotions
		self.as_user(self.agent)
		self.refused(reports.dashboard, property=fx.PROPERTY)
		self.refused(content.items, property=fx.PROPERTY)
		self.as_user(self.foreign)
		self.refused(reports.dashboard, property=fx.PROPERTY)
		self.refused(crs.ari_grid, property=fx.PROPERTY, start=today)
