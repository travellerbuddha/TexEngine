"""Entry screens and navigation sub-sections (G-60, G-64, ADR-060).

G-60: the site root leads somewhere (the TEX admin app for desk users, the sign-in page
otherwise) while a booking site's own host keeps serving its booking engine at "/"; the
app's display strings say TEX Engine (the app stays ``kamra``, ADR-001); every entry
screen can offer the source (AGPL-3.0 section 13).

G-64: the cross-record lists behind the new navigation entries return only the rows of
hotels where the caller holds the capability the entry's screen needs; without it they
refuse. The existing endpoints the other new entries open refuse too.

Review follow-up (ADR-060): the sign-in page reads Frappe's answer (M1: only "Logged In" is a
session; a two-factor account first gives its code); guests and Desk users are offered the source
too, of the version that runs, and served pages carry it (M2, L2, L3); a booking site's slug can
no longer name an admin page (M3); ``session.entry`` over HTTP (L1); one actor rule for
communications and only openable guests linked (L4, L6); ordered, honestly truncated version
tables (L5); the portal branch of "/" and mixed per-hotel cost (L9).
"""

import os
import subprocess
import tempfile
import threading
from unittest import mock

import frappe
from frappe.utils import add_days, add_to_date, getdate, nowdate, set_request
from frappe.website.serve import get_response

from kamra.tex.security import scope
from kamra.tex.services import sites
from kamra.tex.tests.integration import fixtures as fx
from kamra.tex.tests.integration.test_commercial_flows import SLUG
from kamra.tex.tests.integration.test_critical_journey import TexTestCase
from kamra.tex.tests.integration.test_custom_domains import DomainCase
from kamra.tex.tests.integration.test_patches import refuse_commits

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

	def test_a_signed_in_user_without_desk_access_is_sent_to_the_portal(self):
		"""L9: the third branch of ``entry.root_target``."""
		user = "entry-portal@example.com"
		if not frappe.db.exists("User", user):
			frappe.get_doc({"doctype": "User", "email": user, "first_name": "Portal", "user_type": "Website User",
			                "send_welcome_email": 0}).insert(ignore_permissions=True)
		self.assertEqual(frappe.db.get_value("User", user, "user_type"), "Website User")
		resp = root(user)
		self.assertEqual((resp.status_code, resp.headers["Location"]), (302, "/me"))

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

		with mock.patch.dict(frappe.local.conf, {"tex_source_url": "https://git.example.com/tex",
		                                         "tex_source_commit": "0123abc"}):
			self.assertEqual(entry.source_url(), "https://git.example.com/tex")
		with mock.patch.dict(frappe.local.conf, {"tex_source_url": "javascript:alert(1)",
		                                         "tex_source_commit": "0123abc"}):
			self.assertEqual(entry.source_url(), f"{entry.SOURCE_URL}/tree/0123abc")


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


	def test_cost_is_judged_per_hotel(self):
		"""L9: price.view at both hotels, cost at one only: the cost tables cover that hotel alone,
		and a rate plan's adjustment shows only on its rows."""
		from kamra.tex.api import lists

		other = self.contract_at(OTHER, "ENTRY-G64-B")
		mixed = fx.ensure_user("entry-mixed@example.com", ["Revenue Manager"])
		for prop, profile in ((fx.PROPERTY, "Revenue Manager"), (OTHER, "Reservations Agent")):
			fx.ensure("TEX Access Grant", {"user": mixed, "property": prop},
			          {"user": mixed, "scope_level": "Hotel", "property": prop, "permission_profile": profile})
		self.as_user(mixed)
		self.assertTrue(scope.has_capability("price.view", OTHER))
		self.assertFalse(any(scope.has_capability(c, OTHER) for c in lists.COST))
		periods = lists.version_rows(section="periods")["rows"]
		self.assertIn(self.c["version"], {r["version"] for r in periods})
		self.assertEqual({r["property"] for r in periods}, {fx.PROPERTY})           # B's periods never leave
		self.refused(lists.version_rows, section="periods", property=OTHER)
		self.refused(lists.version_rows, section="occupancy", property=OTHER)
		plans = lists.version_rows(section="rate_plans")["rows"]
		mine = [r for r in plans if r["version"] == self.c["version"]]
		theirs = [r for r in plans if r["version"] == other]
		self.assertEqual(len(mine), 2)
		self.assertTrue(all("op" in r and "value" in r for r in mine))
		self.assertEqual(len(theirs), 1)
		self.assertTrue(all("op" not in r and "value" not in r for r in theirs))
		only_b = lists.version_rows(section="rate_plans", property=OTHER)["rows"]
		self.assertEqual([r["version"] for r in only_b], [other])
		self.assertNotIn("value", only_b[0])

	def contract_at(self, prop: str, code: str) -> str:
		"""A draft contract version at ``prop`` with one period and one rate plan, written below the
		controllers (the other hotel has no rooms or rate plans of its own here)."""
		now = frappe.utils.now_datetime()
		stamp = {"creation": now, "modified": now, "owner": "Administrator", "modified_by": "Administrator"}
		contract = frappe.get_doc({"doctype": "TEX Contract", "property": prop, "contract_code": code,
		                           "contract_name": code, "market": "DE", "contract_currency": "EUR",
		                           "pricing_basis": "PERSON", "status": "Draft", **stamp})
		contract.db_insert()
		version = frappe.get_doc({"doctype": "TEX Contract Version", "contract": contract.name, "status": "Draft",
		                          "version_no": 1, **stamp})
		version.db_insert()
		for doctype, field, row in (
				("TEX Price Period", "periods", {"period_code": "B-LOW", "period_name": "Low",
				                                 "start_date": nowdate(), "end_date": add_days(nowdate(), 30)}),
				("TEX Contract Rate Plan", "rate_plans", {"rate_plan": self.f["rate_plans"]["NRF"],
				                                          "op": "ADJUST_PERCENT", "value": -12, "refundable": 0})):
			frappe.get_doc({"doctype": doctype, "parent": version.name, "parenttype": "TEX Contract Version",
			                "parentfield": field, "idx": 1, **stamp, **row}).db_insert()
		return version.name

	def test_the_most_recently_changed_versions_come_first_and_a_cut_is_told(self):
		"""L5: the versions are read in a fixed order (the most recently changed first) and the
		answer says when the version cap or the row cap left something out."""
		from kamra.tex.api import lists

		newer = fx.create_contract(self.f, code="ENTRY-G64-NEW", publish=False)["version"]
		frappe.db.set_value("TEX Contract Version", self.c["version"], "modified", add_days(nowdate(), -30),
		                    update_modified=False)
		frappe.db.set_value("TEX Contract Version", newer, "modified", add_days(nowdate(), 1),
		                    update_modified=False)
		self.as_user(self.rev)
		out = lists.version_rows(section="periods")
		self.assertFalse(out["truncated"])
		self.assertEqual({self.c["version"], newer} - {r["version"] for r in out["rows"]}, set())
		with mock.patch.object(lists, "MAX_VERSIONS", 1, create=True):
			out = lists.version_rows(section="periods")
		self.assertTrue(out["truncated"])
		self.assertEqual({r["version"] for r in out["rows"]}, {newer})
		with mock.patch.object(lists, "MAX_ROWS", 2):
			out = lists.version_rows(section="periods")
		self.assertTrue(out["truncated"])
		self.assertEqual([(r["version"], r["period_code"]) for r in out["rows"]], [(newer, "LOW"), (newer, "HIGH")])

	def archived_drafts(self, n: int) -> list[str]:
		"""``n`` archived contracts, each with a Draft version changed after every other version (one of
		them Published, as an archived contract's live version stays Published), and a period, an
		occupancy rule and a rate plan in it: what E2E runs leave behind (they archive what they made)."""
		now = frappe.utils.now_datetime()
		later = add_to_date(now, days=1)
		tag = frappe.generate_hash(length=6)
		contracts = [f"TEX-ARCH-{tag}-{i:05d}" for i in range(n)]
		versions = [f"tex-arch-{tag}-{i:05d}" for i in range(n)]
		frappe.db.bulk_insert("TEX Contract", ("name", "creation", "modified", "owner", "modified_by", "property",
		                                       "contract_code", "contract_name", "market", "contract_currency",
		                                       "pricing_basis", "status"),
		                      [(c, now, now, "Administrator", "Administrator", fx.PROPERTY, c, c, "DE", "EUR", "PERSON",
		                        "Archived") for c in contracts])
		frappe.db.bulk_insert("TEX Contract Version", ("name", "creation", "modified", "owner", "modified_by",
		                                               "contract", "status", "version_no"),
		                      [(v, now, add_to_date(later, seconds=i), "Administrator", "Administrator", c,
		                        "Published" if i == 0 else "Draft", 1)
		                       for i, (c, v) in enumerate(zip(contracts, versions, strict=True))])
		child = ("name", "creation", "modified", "owner", "modified_by", "parent", "parenttype", "parentfield", "idx")
		for doctype, field, cols, values in (
				("TEX Price Period", "periods", ("period_code", "start_date", "end_date"),
				 ("ARCH", nowdate(), add_days(nowdate(), 30))),
				("TEX Occupancy Rule", "occupancy_rules", ("target", "position", "op", "value"), ("ADULT", 1, "MULTIPLY", 1)),
				("TEX Contract Rate Plan", "rate_plans", ("rate_plan", "op", "value", "refundable"),
				 (self.f["rate_plans"]["NRF"], "ADJUST_PERCENT", -5, 0))):
			frappe.db.bulk_insert(doctype, (*child, *cols),
			                      [(frappe.generate_hash(length=14), now, now, "Administrator", "Administrator", v,
			                        "TEX Contract Version", field, 1, *values) for v in versions])
		return versions

	def test_archived_contracts_never_crowd_the_current_versions_out(self):
		"""The version cap counted the Draft versions of archived contracts as current: with more of them
		than the cap (on the shared test site one hotel had 2,114, left by E2E runs), changed after every
		live version, the current tables of every hotel came back empty and cut. The current tables list
		the versions of contracts that are not archived; the cap counts only the versions with a row in
		the table; "all" still lists the archived contracts' versions, the most recently changed first,
		and says what it cut."""
		from kamra.tex.api import lists

		archived = self.archived_drafts(lists.MAX_VERSIONS + 20)
		draft = fx.create_contract(self.f, code="ENTRY-G64-DRAFT", publish=False)["version"]
		mine = {self.c["version"], draft}
		self.as_user(self.rev)
		for section in ("periods", "occupancy", "rate_plans"):
			with self.subTest(section=section):
				out = lists.version_rows(section=section, property=fx.PROPERTY)
				versions = list(dict.fromkeys(r["version"] for r in out["rows"]))
				self.assertEqual(mine - set(versions), set())                   # the live version and the draft
				self.assertEqual(set(versions) & set(archived), set())          # no archived contract's version
				self.assertFalse(out["truncated"])
				modified = dict(frappe.get_all("TEX Contract Version", filters={"name": ("in", versions)},
				                               fields=["name", "modified"], as_list=True))
				self.assertEqual(versions, sorted(versions, key=lambda v: (modified[v], v), reverse=True))
				self.assertEqual({r["state"] for r in out["rows"] if r["version"] in mine}, {"live", "draft"})

				every = lists.version_rows(section=section, property=fx.PROPERTY, status="all")
				self.assertTrue(every["truncated"])                             # more archived versions than the cap
				shown = list(dict.fromkeys(r["version"] for r in every["rows"]))
				self.assertEqual(len(shown), lists.MAX_VERSIONS)
				self.assertEqual(shown, archived[::-1][:lists.MAX_VERSIONS])     # the most recently changed first


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

	def comm(self, guest: str, actor: str | None, subject: str) -> str:
		return frappe.get_doc({"doctype": "TEX Communication", "guest": guest, "property": fx.PROPERTY,
		                       "channel": "Email", "direction": "Outbound", "status": "Logged",
		                       "consent_basis": "Transactional", "subject": subject, "actor": actor,
		                       "body": "<p>Private</p>"}).insert(ignore_permissions=True).name

	def test_the_list_and_the_profile_name_the_actor_by_one_rule(self):
		"""L4: an online booking's visitor ("Guest") and the system (Administrator) are TEX itself
		(no name), staff by their full name, on the list and on the guest's profile alike."""
		from kamra.tex.api import lists
		from kamra.tex.crm import service as crm

		guest = frappe.get_doc({"doctype": "Guest", "first_name": "Ada", "last_name": "Actorrule",
		                        "email": "ada.actorrule@example.com",
		                        "tex_enterprise": self.f["enterprise"]}).insert(ignore_permissions=True).name
		staff = "entry-actor@example.com"
		if not frappe.db.exists("User", staff):
			frappe.get_doc({"doctype": "User", "email": staff, "first_name": "Rita", "last_name": "Revenue",
			                "send_welcome_email": 0}).insert(ignore_permissions=True)
		for actor, subject in (("Guest", "Booking confirmed"), ("Administrator", "Reminder"),
		                       (staff, "Called about the transfer"), (None, "Imported")):
			self.comm(guest, actor, subject)
		expected = {"Booking confirmed": None, "Reminder": None, "Called about the transfer": "Rita Revenue",
		            "Imported": None}
		self.as_user(self.rev)
		rows = lists.communications(q="Actorrule")["rows"]
		self.assertEqual({r["subject"]: r["actor_name"] for r in rows}, expected)
		profile = crm.profile(guest)
		self.assertEqual({c["subject"]: c["actor_name"] for c in profile["communications"]}, expected)

	def test_a_row_opens_only_a_guest_the_viewer_may_open(self):
		"""L6: the list names every guest of the viewer's hotels' communications, but the profile
		opens only for a guest with a booking at one of their hotels or of their enterprise
		(``require_guest``): the others are not links."""
		from kamra.tex.api import lists
		from kamra.tex.crm import service as crm

		stranger = frappe.get_doc({"doctype": "Guest", "first_name": "Sol", "last_name": "Openrule",
		                           "email": "sol.openrule@example.com"}).insert(ignore_permissions=True).name
		member = frappe.get_doc({"doctype": "Guest", "first_name": "Mia", "last_name": "Openrule",
		                         "email": "mia.openrule@example.com",
		                         "tex_enterprise": self.f["enterprise"]}).insert(ignore_permissions=True).name
		for g in (stranger, member):
			self.comm(g, "Guest", "Your booking")
		self.as_user(self.rev)
		rows = {r["guest"]: r for r in lists.communications(q="Openrule")["rows"]}
		self.assertEqual({g: rows[g]["guest_openable"] for g in rows}, {stranger: False, member: True})
		with self.assertRaises(frappe.PermissionError):                          # what the link would open
			crm.require_guest(stranger)
		self.assertTrue(crm.require_guest(member))


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


# ─── review follow-up (ADR-060) ──────────────────────────────────────────


def write(path: str, text: str) -> None:
	os.makedirs(os.path.dirname(path), exist_ok=True)
	with open(path, "w", encoding="utf-8") as f:
		f.write(text)


# a running commit named by the site config: what every offer below links
CONF = {"tex_source_commit": "0123abc", "tex_source_url": None}


class TestSourceOffer(DomainCase):
	"""AGPL-3.0 section 13 (M2, L2, L3): guests and staff are offered the source of the version that
	runs; an address with credentials is never offered; the pages carry the offer themselves, so a
	rate-limited or failing API never replaces it with another address."""

	def test_the_offer_is_the_source_of_the_running_commit(self):
		from kamra.tex import entry

		with mock.patch.dict(frappe.local.conf, CONF):
			self.assertEqual(entry.source_url(), f"{entry.SOURCE_URL}/tree/0123abc")
		for configured, offered in (
				("https://git.example.com/tex/-/tree/{commit}", "https://git.example.com/tex/-/tree/0123abc"),
				("https://git.example.com/tex/releases/v1.4", "https://git.example.com/tex/releases/v1.4")):
			with mock.patch.dict(frappe.local.conf, {**CONF, "tex_source_url": configured}):
				self.assertEqual(entry.source_url(), offered)
		with mock.patch.dict(frappe.local.conf, {**CONF, "tex_source_commit": "not a commit"}), \
				mock.patch.object(entry, "_git_head", return_value=None), mock.patch.object(entry, "_head", entry._UNSET):
			self.assertEqual(entry.source_url(), entry.SOURCE_URL)             # nothing to tell: the repository

	def test_without_configuration_the_checkouts_head_is_linked(self):
		from kamra.tex import entry

		root = os.path.dirname(frappe.get_app_path("kamra"))
		try:
			head = subprocess.run(["git", "-C", root, "rev-parse", "HEAD"], capture_output=True, text=True,
			                      check=True).stdout.strip()
		except (OSError, subprocess.CalledProcessError):
			self.skipTest("the app is not a git checkout here")
		self.assertEqual(entry._git_head(root), head)
		with mock.patch.dict(frappe.local.conf, {"tex_source_commit": None, "tex_source_url": None}):
			self.assertEqual(entry.source_url(), f"{entry.SOURCE_URL}/tree/{head}")

	def test_the_head_is_read_from_a_checkout_a_worktree_and_packed_refs(self):
		from kamra.tex import entry

		one, two = "a" * 40, "b" * 40
		with tempfile.TemporaryDirectory() as tmp:
			repo, wt = os.path.join(tmp, "repo"), os.path.join(tmp, "wt")
			git = os.path.join(repo, ".git")
			write(os.path.join(git, "HEAD"), "ref: refs/heads/main\n")
			write(os.path.join(git, "refs", "heads", "main"), one + "\n")
			self.assertEqual(entry._git_head(repo), one)
			write(os.path.join(git, "HEAD"), "ref: refs/heads/release\n")          # packed only
			write(os.path.join(git, "packed-refs"), f"# pack-refs with: peeled\n{two} refs/heads/release\n")
			self.assertEqual(entry._git_head(repo), two)
			wtgit = os.path.join(git, "worktrees", "wt")                           # a linked worktree
			write(os.path.join(wt, ".git"), f"gitdir: {wtgit}\n")
			write(os.path.join(wtgit, "HEAD"), "ref: refs/heads/main\n")
			write(os.path.join(wtgit, "commondir"), "../..\n")
			self.assertEqual(entry._git_head(wt), one)
			write(os.path.join(wtgit, "HEAD"), two + "\n")                         # detached
			self.assertEqual(entry._git_head(wt), two)
			write(os.path.join(git, "HEAD"), "ref: refs/heads/gone\n")
			self.assertIsNone(entry._git_head(repo))
			self.assertIsNone(entry._git_head(tmp))                               # not a checkout

	def test_an_address_with_credentials_or_another_scheme_is_never_offered(self):
		"""L2: an operator's token in ``tex_source_url`` would be shown to every visitor."""
		from kamra.tex import entry

		for bad in ("https://user:token@git.example.com/tex", "https://ghp_secret@git.example.com/tex",
		            "https://:secret@git.example.com/tex", "https://git.example.com@evil.example/tex",
		            "http://git.example.com/tex", "javascript:alert(1)", "https://", "https:///path",
		            "https://git.example.com/a b", "https://git.example.com/" + "x" * 300):
			with mock.patch.dict(frappe.local.conf, {**CONF, "tex_source_url": bad}):
				self.assertEqual(entry.source_url(), f"{entry.SOURCE_URL}/tree/0123abc", bad)

	def test_served_pages_carry_the_offer_and_the_brand(self):
		"""L3: the admin app's page, the booking engine's and a booking host's carry the offer (and
		the sign-in page the brand), escaped, so they never depend on the rate-limited API."""
		from kamra.tex import booking_host

		conf = {**CONF, "tex_source_url": "https://git.example.com/tex/{commit}?tab=src&x=1"}
		meta = '<meta name="tex-source-url" content="https://git.example.com/tex/0123abc?tab=src&amp;x=1"'
		with mock.patch.dict(frappe.local.conf, conf), \
				mock.patch("kamra.tex.entry.brand_name", return_value='Aurora <b>&</b> "Co"'):
			admin = root("Guest", path="/kamra/login").get_data(as_text=True)
			book = root("Guest", path=f"/book/{SLUG}").get_data(as_text=True)
			pinned = booking_host.pinned_page(SLUG)
		for page in (admin, book, pinned):
			self.assertIn(meta, page)
			self.assertIn('<meta name="tex-brand" content="Aurora &lt;b&gt;&amp;&lt;/b&gt; &quot;Co&quot;"', page)
			self.assertLess(page.index(meta), page.index("</head>"))

	def test_desk_offers_the_source_in_its_about_dialog(self):
		"""M2: Desk users interact with TEX Engine too. Its About dialog gets the offer from a script
		every Desk page loads, with the address from the boot."""
		from kamra.tex import entry

		self.assertIn("/assets/kamra/js/tex_source.js", frappe.get_hooks("app_include_js", app_name="kamra"))
		script = frappe.get_app_path("kamra", "public", "js", "tex_source.js")
		self.assertTrue(os.path.isfile(script))
		src = open(script, encoding="utf-8").read()
		self.assertIn("frappe.boot.tex_source_url", src)
		self.assertIn("AGPL-3.0", src)
		self.assertIn("kamra.tex.entry.extend_bootinfo", frappe.get_hooks("extend_bootinfo", app_name="kamra"))
		boot = frappe._dict()
		with mock.patch.dict(frappe.local.conf, CONF):
			entry.extend_bootinfo(boot)
		self.assertEqual(boot.tex_source_url, f"{entry.SOURCE_URL}/tree/0123abc")


def over_http(method: str, path: str, ip: str, **kw):
	"""``path`` requested as a browser does: through Frappe's WSGI application, in a thread of its own
	with its own connection, as the web server runs it (nothing it does joins this test's
	transaction; a GET is rolled back, as is a refused POST)."""
	from frappe.app import application
	from werkzeug.test import Client

	site, out = frappe.local.site, {}

	def run():
		with mock.patch("frappe.app.get_site_name", return_value=site):
			out["response"] = Client(application).open(path, method=method, headers={"X-Forwarded-For": ip}, **kw)

	thread = threading.Thread(target=run)
	thread.start()
	thread.join()
	return out["response"]


class TestEntryOverHttp(TexTestCase):
	"""L1: ``session.entry`` as the public sign-in page reaches it: a guest's GET answers, any other
	method is refused, and one address gets 60 answers a minute."""

	PATH = "/api/method/kamra.tex.api.session.entry"

	def setUp(self):
		super().setUp()
		# an address of its own (TEST-NET-2), so no other client's requests count against it
		n = int(frappe.generate_hash(length=6), 16)
		self.ip = f"198.51.{n % 250}.{n // 250 % 250 + 1}"
		self.addCleanup(self.forget_limits)

	def forget_limits(self):
		for key in frappe.cache.get_keys(f"rl:*{self.ip}*"):
			frappe.cache.delete(key)

	def test_a_guest_gets_the_brand_and_the_offer_only(self):
		from kamra.tex import entry

		r = over_http("GET", self.PATH, self.ip)
		self.assertEqual(r.status_code, 200, r.get_data(as_text=True)[:300])
		info = r.get_json()["message"]
		self.assertEqual(set(info), {"product", "brand_name", "source_url", "upstream", "license"})
		self.assertEqual(info["product"], "TEX Engine")
		self.assertEqual(info["source_url"], entry.source_url())
		self.assertEqual(info["license"]["name"], "AGPL-3.0")

	def test_only_get_is_answered(self):
		for method in ("POST", "PUT", "DELETE"):
			r = over_http(method, self.PATH, self.ip)
			self.assertIn(r.status_code, (403, 405), method)
			self.assertNotIn("source_url", r.get_data(as_text=True), method)

	def test_an_address_gets_sixty_answers_a_minute(self):
		codes = [over_http("GET", self.PATH, self.ip).status_code for _ in range(61)]
		self.assertEqual(codes[:60], [200] * 60)
		self.assertEqual(codes[60], 429)
		other = self.ip.rsplit(".", 1)[0] + ".251"
		self.addCleanup(lambda: [frappe.cache.delete(k) for k in frappe.cache.get_keys(f"rl:*{other}*")])
		self.assertEqual(over_http("GET", self.PATH, other).status_code, 200)   # per address


class TestSignInContract(TexTestCase):
	"""M1: what Frappe answers ``/api/method/login``, which the sign-in page must read. Only
	``message: "Logged In"`` (or "No App") comes with a session. A two-factor account gets
	``verification`` and ``tmp_id`` and no session until its code is posted with the ``tmp_id``; an
	expired password gets ``message: "Password Reset"`` and ``redirect_to``, no session.

	Two-factor sign-in is on for one test user only: a role of its own, marked for it, in this
	test's transaction; the site's switch is read as on inside the test and never written
	(saving System Settings would mark the role "All"). Making a session commits, so the step that
	makes it is recorded, not run, and the test refuses any commit."""

	PASSWORD = "Entry#2fa-Test-2026"
	ROLE = "TEX Entry Two Factor"

	def setUp(self):
		refuse_commits(self)
		super().setUp()
		import pyotp
		from frappe.utils.password import encrypt, update_password

		if not frappe.db.exists("Role", self.ROLE):
			frappe.get_doc({"doctype": "Role", "role_name": self.ROLE, "desk_access": 1,
			                "two_factor_auth": 1}).insert(ignore_permissions=True)
		self.user = fx.ensure_user("entry-2fa@example.com", [self.ROLE])
		self.plain = fx.ensure_user("entry-expired@example.com", ["Revenue Manager"])
		for u in (self.user, self.plain):
			update_password(u, self.PASSWORD)
		from frappe import twofactor

		self.secret = pyotp.random_base32()
		twofactor.set_default(f"{self.user}_otpsecret", encrypt(self.secret))
		twofactor.set_default(f"{self.user}_otplogin", 1)                     # the app is set up
		# the defaults read from this transaction are cached: forget them after the rollback
		self.addCleanup(frappe.client_cache.delete_value, f"defaults::{twofactor.PARENT_FOR_DEFAULTS}")
		self.settings = {"enable_two_factor_auth": 1, "two_factor_method": "OTP App"}
		real = frappe.get_system_settings
		settings = mock.patch("frappe.get_system_settings",
		                      side_effect=lambda key: self.settings[key] if key in self.settings else real(key))
		settings.start()
		self.addCleanup(settings.stop)
		self.sessions = []
		response, form = frappe.local.response, frappe.local.form_dict

		def restore():
			frappe.local.response, frappe.local.form_dict, frappe.local.request = response, form, None

		self.addCleanup(restore)

	def sign_in(self, **form) -> dict:
		"""POST /api/method/login with ``form`` as Frappe handles it → the answer. A session is
		recorded (``self.sessions``) instead of made; a refusal raises as Frappe's does."""
		from frappe.auth import CookieManager, LoginManager

		set_request(method="POST", path="/api/method/login")
		frappe.local.request_ip = "203.0.113.20"
		frappe.local.form_dict = frappe._dict(form)
		frappe.local.response = frappe._dict()
		frappe.local.cookie_manager = CookieManager()

		def post_login(manager, *args, **kwargs):
			self.sessions.append(manager.user)

		def fail(manager, message, user=None):
			frappe.local.response["message"] = message
			raise frappe.AuthenticationError(message)

		try:
			with mock.patch("frappe.auth.LoginManager.post_login", post_login), \
					mock.patch("frappe.auth.LoginManager.fail", fail):
				LoginManager()
			return dict(frappe.local.response)
		finally:
			frappe.set_user("Administrator")  # nosemgrep: frappe-setuser -- back to the test's user

	def code(self) -> str:
		"""The authenticator's code now; a code about to expire is not risked (Frappe accepts only the
		current 30 s step)."""
		import time

		import pyotp

		if time.time() % 30 > 26:
			time.sleep(30.2 - time.time() % 30)
		return pyotp.TOTP(self.secret).now()

	def test_a_two_factor_account_has_no_session_until_its_code(self):
		first = self.sign_in(usr=self.user, pwd=self.PASSWORD)
		self.assertNotIn(first.get("message"), ("Logged In", "No App"))
		self.assertEqual(first["verification"], {"method": "OTP App", "setup": True})
		self.assertTrue(first["tmp_id"])
		self.assertEqual(self.sessions, [])                                  # the page must not call this signed in
		wrong = f"{(int(self.code()) + 1) % 1_000_000:06d}"
		with self.assertRaises(frappe.AuthenticationError):
			self.sign_in(otp=wrong, tmp_id=first["tmp_id"])
		self.assertEqual(self.sessions, [])
		self.sign_in(otp=self.code(), tmp_id=first["tmp_id"])
		self.assertEqual(self.sessions, [self.user])                         # the code, with the tmp_id, signs in

	def test_only_the_two_factor_account_is_asked_for_a_code(self):
		self.sign_in(usr=self.plain, pwd=self.PASSWORD)
		self.assertEqual(self.sessions, [self.plain])

	def test_an_expired_password_makes_no_session_and_names_the_reset_page(self):
		self.settings["force_user_to_reset_password"] = 30
		frappe.db.set_value("User", self.plain, "last_password_reset_date", add_days(nowdate(), -60))
		r = self.sign_in(usr=self.plain, pwd=self.PASSWORD)
		self.assertEqual(r["message"], "Password Reset")
		self.assertIn("/update-password?key=", r["redirect_to"])
		self.assertEqual(self.sessions, [])


class TestBookingSiteSlugs(TexTestCase):
	"""M3: the admin area's own pages (``/tex/booking-engine/new``, ``sites``, ``content``, ``rooms``,
	``analytics``) are no site's slug: a new site, or a site moved to another slug, may not take
	one. A site that has one already keeps it and stays savable (patch p47 reports it)."""

	def site(self, slug: str, **values):
		return frappe.get_doc({"doctype": "TEX Booking Site", "site_name": f"Slug {slug}", "site_slug": slug,
		                       "property": fx.PROPERTY, "enabled": 0, **values})

	def test_a_new_site_may_not_take_an_admin_pages_name(self):
		from kamra.tex_booking.doctype.tex_booking_site.tex_booking_site import ADMIN_SLUGS

		self.assertEqual(set(ADMIN_SLUGS), {"new", "sites", "content", "rooms", "analytics"})
		for slug in ("rooms", "Analytics", "content", "sites", "new", "pay", "widget"):
			with self.assertRaisesRegex(frappe.ValidationError, "reserved", msg=slug):
				self.site(slug).insert(ignore_permissions=True)
		self.site("rooms-and-suites").insert(ignore_permissions=True)            # a word inside a slug is fine

	def test_an_existing_site_keeps_its_slug_but_none_moves_to_one(self):
		now = frappe.utils.now_datetime()
		old = self.site("analytics", name="analytics", creation=now, modified=now, owner="Administrator",
		                modified_by="Administrator")
		old.db_insert()                                                          # saved before the rule
		doc = frappe.get_doc("TEX Booking Site", "analytics")
		doc.site_name = "Analytics Beach"
		doc.save(ignore_permissions=True)
		self.assertEqual(frappe.db.get_value("TEX Booking Site", "analytics", "site_name"), "Analytics Beach")
		other = self.site("g64-slug-move").insert(ignore_permissions=True)
		other.site_slug = "rooms"
		with self.assertRaisesRegex(frappe.ValidationError, "reserved"):
			other.save(ignore_permissions=True)
