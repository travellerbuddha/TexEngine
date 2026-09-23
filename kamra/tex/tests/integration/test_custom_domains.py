"""Custom booking domains (G-21, ADR-035): a verified host name serves its booking site,
answers for that site only, and is where guest links point; nothing but the DNS check sets
or keeps a domain verified; the platform never trusts a request's Host header."""

from unittest import mock

import frappe
from werkzeug.test import EnvironBuilder
from werkzeug.wrappers import Request

from kamra.tex.api import public
from kamra.tex.booking_host import BookingHostRenderer
from kamra.tex.payments import service as pay
from kamra.tex.services import notify, sites
from kamra.tex.tests.integration import fixtures as fx
from kamra.tex.tests.integration.test_commercial_flows import SLUG, setup_site_and_payments
from kamra.tex.tests.integration.test_critical_journey import TexTestCase

HOST = "book.test-resort.example"
OTHER = "tex-other-site"


class DomainCase(TexTestCase):
	def setUp(self):
		super().setUp()
		setup_site_and_payments(self.f)
		sites.clear_host_cache()
		self.site = frappe.get_doc("TEX Booking Site", SLUG)

	def tearDown(self):
		frappe.local.request = None
		frappe.local.request_ip = None
		super().tearDown()
		sites.clear_host_cache()

	def add(self, site, host, primary=0):
		doc = frappe.get_doc("TEX Booking Site", site)
		doc.append("domains", {"domain": host, "is_primary": primary})
		doc.save(ignore_permissions=True)
		return next(d for d in doc.domains if d.domain == sites.normalize_host(host))

	def verify(self, site, host):
		token = next(d for d in frappe.get_doc("TEX Booking Site", site).domains if d.domain == host).verification_token
		with mock.patch.object(sites, "txt_records", return_value=["other", token]):
			return sites.verify_domain(site, host)

	def other_site(self):
		if not frappe.db.exists("TEX Booking Site", OTHER):
			frappe.get_doc({"doctype": "TEX Booking Site", "site_name": "Other", "site_slug": OTHER, "enabled": 1,
			                "property": fx.PROPERTY, "default_market": "DE", "default_currency": "EUR",
			                "currencies": "EUR"}).insert(ignore_permissions=True)
		return OTHER

	@staticmethod
	def request(host, path="/"):
		frappe.local.request = Request(EnvironBuilder(path=path, base_url=f"https://{host}/").get_environ())
		frappe.local.request_ip = "203.0.113.7"                        # the rate limiter keys on it


class TestCustomDomains(DomainCase):
	def test_a_domain_is_a_host_name(self):
		row = self.add(SLUG, "HTTPS://Book.Test-Resort.Example/")
		self.assertEqual((row.domain, row.verified, bool(row.verification_token)), (HOST, 0, True))
		for bad in ("hotel.example/book", "localhost", "-bad.example", "a..example"):
			with self.assertRaises(frappe.ValidationError, msg=bad):
				self.add(SLUG, bad)
		with self.assertRaises(frappe.ValidationError):
			self.add(SLUG, HOST)                                           # twice on one site

	def test_only_the_dns_check_sets_or_keeps_verification(self):
		self.add(SLUG, HOST)
		doc = frappe.get_doc("TEX Booking Site", SLUG)
		doc.domains[0].verified = 1                                        # an edit cannot verify
		doc.save(ignore_permissions=True)
		self.assertEqual(frappe.get_doc("TEX Booking Site", SLUG).domains[0].verified, 0)
		out = self.verify(SLUG, HOST)
		self.assertTrue(out["verified"])
		row = frappe.get_doc("TEX Booking Site", SLUG).domains[0]
		self.assertTrue(row.verified_at and row.last_checked_at)
		doc = frappe.get_doc("TEX Booking Site", SLUG)                    # the admin UI sends rows back
		doc.domains[0].update({"verified": 0, "verified_at": None, "check_failures": 7})
		doc.save(ignore_permissions=True)
		row = frappe.get_doc("TEX Booking Site", SLUG).domains[0]
		self.assertEqual((row.verified, row.check_failures, bool(row.verified_at)), (1, 0, True))
		self.assertTrue(out["present"])
		with mock.patch.object(sites, "txt_records", return_value=["other"]):      # the record was removed
			again = sites.verify_domain(SLUG, HOST)
		self.assertEqual((again["verified"], again["present"]), (True, False))    # still verified, but not found

	def test_one_site_holds_a_verified_host(self):
		self.add(SLUG, HOST)
		self.verify(SLUG, HOST)
		self.add(self.other_site(), HOST)                                  # claiming is allowed…
		with self.assertRaises(frappe.ValidationError):
			self.verify(OTHER, HOST)                                       # …holding it is not
		self.assertEqual(sites.host_map().get(HOST), SLUG)

	def test_the_record_is_checked_every_day(self):
		self.add(SLUG, HOST)
		self.verify(SLUG, HOST)
		def recheck():                                                     # other sites' hosts (demo data) aside
			return [r for r in sites.recheck_domains() if r["site"] == SLUG]

		with mock.patch.object(sites, "txt_records", side_effect=sites.DnsLookupFailed("timeout")):
			self.assertEqual(recheck(), [])                                # a resolver failure is not evidence
		with mock.patch.object(sites, "txt_records", return_value=[]):
			for _ in range(sites.UNVERIFY_AFTER - 1):
				self.assertEqual(recheck(), [])
			self.assertEqual(sites.host_map().get(HOST), SLUG)
			self.assertEqual(recheck(), [{"site": SLUG, "domain": HOST}])
		self.assertIsNone(sites.host_map().get(HOST))
		self.assertTrue(frappe.db.exists("TEX Audit Event", {"action": "booking_site.domain_unverified",
		                                                     "reference_name": SLUG}))

	def test_dns_answers_are_read_strictly(self):
		def answer(payload):
			r = mock.Mock()
			r.json.return_value = payload
			r.raise_for_status.return_value = None
			return r

		with mock.patch.object(sites.requests, "get", return_value=answer({"Status": 2})):
			with self.assertRaises(sites.DnsLookupFailed):
				sites.txt_records("_tex-verify.x.example")
		with mock.patch.object(sites.requests, "get", return_value=answer({"Status": 3})):
			self.assertEqual(sites.txt_records("_tex-verify.x.example"), [])
		with mock.patch.object(sites.requests, "get", return_value=answer(
				{"Status": 0, "Answer": [{"type": 16, "data": '"abc" "def"'}, {"type": 5, "data": "cname"}]})):
			self.assertEqual(sites.txt_records("_tex-verify.x.example"), ["abcdef"])

	def test_the_host_serves_its_site_only(self):
		self.add(SLUG, HOST)
		self.verify(SLUG, HOST)
		self.other_site()
		self.request(f"{HOST}:443", "/manage")
		self.assertEqual(sites.pinned_slug(), SLUG)
		frappe.set_user("Guest")  # nosemgrep: frappe-setuser -- a visitor on the hotel's host
		self.assertEqual(public.site(slug=SLUG)["slug"], SLUG)
		with self.assertRaises(frappe.DoesNotExistError):
			public.site(slug=OTHER)                                        # another site is not served here
		for path, claimed in (("", True), ("manage", True), ("confirmation/TEX-1", True), ("pay/abc", True),
		                      ("book/x", False), ("assets/x.js", False), ("api/method/x", False), ("app", False)):
			self.assertEqual(BookingHostRenderer(path).can_render(), claimed, path)
		page = BookingHostRenderer("manage")
		page.can_render()
		with mock.patch("kamra.tex.booking_host.booking_html", return_value="<html><head></head><body></body></html>"):
			resp = page.render()
		body = resp.get_data(as_text=True)
		self.assertIn(f'<meta name="tex-booking-site" content="{SLUG}">', body)
		self.assertTrue(resp.headers["Content-Security-Policy"].startswith("frame-ancestors 'self'"))
		from kamra.www import book

		frappe.local.response_headers = {}
		with mock.patch("kamra.www.book.booking_html", return_value="<html></html>"):
			frappe.form_dict.app_path = f"{OTHER}/manage"
			with self.assertRaises(frappe.Redirect):                       # /book/<another site> is not served here
				book.get_context(frappe._dict())
			for own in (f"{SLUG}/manage", "pay/abc"):                      # its own site and payment pages are
				frappe.form_dict.app_path = own
				self.assertTrue(book.get_context(frappe._dict()).spa_html)
		frappe.form_dict.pop("app_path", None)
		self.request("platform.example", "/")                              # the platform host pins nothing
		self.assertIsNone(sites.pinned_slug())
		self.assertFalse(BookingHostRenderer("manage").can_render())
		self.assertEqual(public.site(slug=OTHER)["slug"], OTHER)

	def test_guest_links_use_the_hotels_host(self):
		platform = sites.platform_url(f"/book/{SLUG}/manage#token=t")
		self.assertEqual(notify.manage_url(fx.PROPERTY, SLUG, "t"), platform)
		self.add(SLUG, "unverified.test-resort.example", primary=1)
		self.assertEqual(notify.manage_url(fx.PROPERTY, SLUG, "t"), platform)   # unverified: never linked
		self.add(SLUG, HOST)
		self.verify(SLUG, HOST)
		self.assertEqual(notify.manage_url(fx.PROPERTY, SLUG, "t"), f"https://{HOST}/manage#token=t")
		link = pay.create_link(property=fx.PROPERTY, amount="10", currency="EUR", description="x")
		self.assertTrue(link["url"].startswith(f"https://{HOST}/pay/"), link["url"])
		self.assertIn(HOST, pay.allowed_return_hosts(fx.PROPERTY))
		self.assertEqual(public._safe_return_url(self.site, f"https://{HOST}/confirmation/{{booking}}", "B-1"),
		                 f"https://{HOST}/confirmation/B-1")
		frappe.db.set_value("TEX Booking Site", SLUG, "enabled", 0)       # a disabled site's host is not a target
		self.assertNotIn(HOST, pay.allowed_return_hosts(fx.PROPERTY))

	def test_a_forged_host_header_is_never_trusted(self):
		self.request("evil.example", "/")
		self.assertNotIn("evil.example", notify.manage_url(fx.PROPERTY, SLUG, "t"))
		self.assertNotIn("evil.example", pay.allowed_return_hosts(fx.PROPERTY))
		self.assertIsNone(public._safe_return_url(self.site, "https://evil.example/x"))
		link = pay.create_link(property=fx.PROPERTY, amount="10", currency="EUR", description="x")
		self.assertNotIn("evil.example", link["url"])


class TestBookingHostMigration(DomainCase):
	def setUp(self):
		super().setUp()
		# the schema is migrated already: a re-sync would commit this test's rows (see p12's test)
		self.enterContext(mock.patch.object(frappe, "reload_doc"))

	def test_a_path_domain_is_unverified_and_hosts_are_kept(self):
		from kamra.patches.tex import p15_booking_hosts

		self.add(SLUG, HOST)
		self.verify(SLUG, HOST)
		row = frappe.get_doc("TEX Booking Site", SLUG).domains[0]
		frappe.db.set_value("TEX Booking Domain", row.name, "verified_at", None)
		path_row = frappe.get_doc({"doctype": "TEX Booking Domain", "parent": SLUG, "parenttype": "TEX Booking Site",
		                           "parentfield": "domains", "domain": "hotel.example/book", "verified": 1,
		                           "verification_token": "x", "idx": 9})
		path_row.db_insert()
		p15_booking_hosts.execute()
		self.assertEqual(frappe.db.get_value("TEX Booking Domain", path_row.name, "verified"), 0)
		self.assertTrue(frappe.db.get_value("TEX Booking Domain", row.name, "verified_at"))
		self.assertEqual(frappe.db.get_value("TEX Booking Domain", row.name, "verified"), 1)
