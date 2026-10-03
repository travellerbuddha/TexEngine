"""C-04 on the web (owner, 2026-10-03; ADR-078): a guest signs in on a booking site, or joins its hotels' loyalty
program, by a one-time link sent to their e-mail; the link opens a session on that device for 30 days. A new guest
joins with their e-mail, name and an explicit tick, confirmed by the link: nobody is joined with another's e-mail."""

import re
from unittest import mock

import frappe
from frappe.utils import add_days, add_to_date, now_datetime

from kamra.tex.api import public
from kamra.tex.crm import loyalty, members
from kamra.tex.services import notify
from kamra.tex.tests.integration import fixtures as fx
from kamra.tex.tests.integration.test_commercial_flows import SLUG
from kamra.tex.tests.integration.test_loyalty_membership import MembershipCase


def code_of(exc) -> str | None:
	return getattr(exc, "code", None)


class WebMemberCase(MembershipCase):
	def setUp(self):
		super().setUp()
		frappe.db.set_value("Guest", self.guest, {"first_name": "Mia", "last_name": "Member"})
		self.email = frappe.db.get_value("Guest", self.guest, "email")
		self.mails: list[tuple[str, str, str]] = []
		patcher = mock.patch.object(notify, "_send", side_effect=self._capture)
		patcher.start()
		self.addCleanup(patcher.stop)

	def _capture(self, to, subject, html, **kw):
		self.mails.append((to, subject, html))
		return f"EQ-{len(self.mails)}"

	def as_guest(self, fn, *args, **kw):
		frappe.set_user("Guest")  # nosemgrep: frappe-setuser -- a visitor of the booking site
		try:
			return fn(*args, **kw)
		finally:
			frappe.set_user("Administrator")  # nosemgrep: frappe-setuser -- back

	def ask(self, email: str, purpose: str = "sign_in", **kw) -> dict:
		return self.as_guest(public.member_link, site=SLUG, email=email, purpose=purpose, **kw)

	def token(self, mail_index: int = -1) -> str | None:
		m = re.search(r"#token=([A-Za-z0-9_\-]+)", self.mails[mail_index][2])
		return m.group(1) if m else None

	def verify(self, token: str) -> dict:
		return self.as_guest(public.member_verify, site=SLUG, token=token)

	def refused(self, fn, *args, **kw) -> str | None:
		with self.assertRaises(frappe.ValidationError) as caught:
			self.as_guest(fn, *args, **kw)
		return code_of(caught.exception)


class TestSignIn(WebMemberCase):
	def test_c04e_a_member_signs_in_by_a_link_and_stays_signed_in_for_30_days(self):
		self.join(self.guest)
		out = self.ask(self.email)
		self.assertEqual(out, {"ok": True})
		[(to, _subject, html)] = self.mails
		self.assertEqual(to, self.email)
		token = self.token()
		self.assertTrue(token and len(token) >= 40)
		self.assertIn("/member#token=", html)                                  # the token in the fragment only
		signed = self.verify(token)
		self.assertTrue(signed["session"] and signed["session"] != token)
		self.assertEqual((signed["status"]["signed_in"], signed["status"]["member"], signed["status"]["first_name"]),
		                 (True, True, "Mia"))
		row = frappe.db.get_value("TEX Member Session", {"guest": self.guest},
		                          ["token_hash", "expires_at", "site", "revoked_at"], as_dict=True)
		self.assertEqual(len(row.token_hash), 64)
		self.assertNotIn(signed["session"], row.token_hash)                     # only its hash is stored
		self.assertEqual(row.site, SLUG)
		self.assertAlmostEqual((row.expires_at - now_datetime()).total_seconds() / 86400, members.SESSION_DAYS,
		                       delta=0.01)
		status = self.as_guest(public.member_status, site=SLUG, member_session=signed["session"])
		self.assertEqual((status["signed_in"], status["member"]), (True, True))
		# the link is used once
		self.assertEqual(self.refused(public.member_verify, site=SLUG, token=token), "MEMBER_LINK_INVALID")

	def test_c04e_the_answer_is_the_same_whoever_asks(self):
		"""Nobody learns from the site whether an e-mail has a profile or a membership; an address without one
		gets a mail that says so and links to joining, with no token."""
		known = self.ask(self.email)
		unknown = self.ask("c04e-nobody@example.com")
		self.assertEqual(known, unknown)
		self.assertEqual([m[0] for m in self.mails], [self.email, "c04e-nobody@example.com"])
		self.assertIsNone(self.token(1))
		self.assertFalse(frappe.db.exists("Guest", {"email": "c04e-nobody@example.com"}))

	def test_c04e_a_link_opens_its_own_site_only_and_expires(self):
		self.join(self.guest)
		self.ask(self.email)
		token = self.token()
		other = frappe.get_doc({"doctype": "TEX Booking Site", "site_name": "C04E Other", "site_slug": "c04e-other",
		                        "enabled": 1, "property": fx.PROPERTY, "default_market": "DE",
		                        "default_currency": "EUR", "currencies": "EUR"}).insert(ignore_permissions=True)
		self.assertEqual(self.refused(public.member_verify, site=other.site_slug, token=token), "MEMBER_LINK_INVALID")
		# a link opened anywhere is spent (read and deleted in one step): its owner asks for a new one
		self.assertEqual(self.refused(public.member_verify, site=SLUG, token=token), "MEMBER_LINK_INVALID")
		self.ask(self.email)
		late = self.token()
		with mock.patch.object(members, "now_datetime", return_value=add_to_date(now_datetime(), minutes=31)):
			self.assertEqual(self.refused(public.member_verify, site=SLUG, token=late), "MEMBER_LINK_INVALID")

	def test_c04e_links_are_limited_per_address(self):
		for _ in range(members.LINKS_PER_ADDRESS + 2):
			self.assertEqual(self.ask(self.email), {"ok": True})              # the same answer every time
		self.assertEqual(len(self.mails), members.LINKS_PER_ADDRESS)

	def test_c04e_sign_out_and_expiry_end_the_session(self):
		self.join(self.guest)
		self.ask(self.email)
		session = self.verify(self.token())["session"]
		self.as_guest(public.member_sign_out, site=SLUG, member_session=session)
		self.assertTrue(frappe.db.get_value("TEX Member Session", {"guest": self.guest}, "revoked_at"))
		self.assertEqual(self.refused(public.member_status, site=SLUG, member_session=session),
		                 "MEMBER_SESSION_ENDED")
		self.ask(self.email)
		again = self.verify(self.token())["session"]
		frappe.db.set_value("TEX Member Session", {"token_hash": members.digest(again)}, "expires_at",
		                    add_days(now_datetime(), -1))
		self.assertEqual(self.refused(public.member_status, site=SLUG, member_session=again), "MEMBER_SESSION_ENDED")
		self.assertIsNone(members.session_guest(frappe.get_doc("TEX Booking Site", SLUG), again))


class TestJoinOnTheWeb(WebMemberCase):
	def test_c04e_a_new_guest_joins_with_the_link_and_the_tick(self):
		email = "c04e-new@example.com"
		self.assertEqual(self.refused(public.member_link, site=SLUG, email=email, purpose="join", first_name="Nora",
		                              last_name="New", accepted=0), "MEMBER_CONSENT_REQUIRED")
		self.assertEqual(self.refused(public.member_link, site=SLUG, email=email, purpose="join", first_name="",
		                              last_name="New", accepted=1), "GUEST_FIRST_NAME_REQUIRED")
		self.assertEqual(self.mails, [])
		self.assertEqual(self.ask(email, "join", first_name="Nora", last_name="New", accepted=1), {"ok": True})
		self.assertFalse(frappe.db.exists("Guest", {"email": email}))          # nothing until the link is opened
		signed = self.verify(self.token())
		guest = frappe.db.get_value("Guest", {"email": email}, ["name", "first_name", "last_name", "tex_enterprise"],
		                            as_dict=True)
		self.assertEqual((guest.first_name, guest.last_name, guest.tex_enterprise),
		                 ("Nora", "New", frappe.db.get_value("Property", fx.PROPERTY, "tex_enterprise")))
		m = loyalty.membership(guest.name, self.club)
		self.assertEqual((m.status, m.source, m.property), ("Active", "Web", fx.PROPERTY))
		self.assertTrue(signed["status"]["member"])
		self.assertTrue(frappe.db.exists("TEX Audit Event", {"action": "loyalty.member_join", "reference_name": m.name}))
		# nothing marketing: joining is not consent to marketing mail
		self.assertEqual(frappe.db.get_value("Guest", guest.name, ["tex_consent_email", "tex_consent_sms"]), (0, 0))

	def test_c04e_joining_with_an_e_mail_that_has_a_profile_joins_that_profile(self):
		"""The link proves the e-mail is theirs: the profile with that e-mail joins, its names unchanged."""
		self.assertFalse(loyalty.is_member(self.guest, fx.PROPERTY))
		self.ask(self.email, "join", first_name="Someone", last_name="Else", accepted=1)
		self.verify(self.token())
		self.assertTrue(loyalty.is_member(self.guest, fx.PROPERTY))
		self.assertEqual(frappe.db.get_value("Guest", self.guest, "first_name"), "Mia")
		self.assertEqual(frappe.db.count("Guest", {"email": self.email}), 1)

	def test_c04e_a_signed_in_guest_who_is_no_member_joins_with_a_tick(self):
		self.ask(self.email)                                                   # a past guest: a profile, no membership
		signed = self.verify(self.token())
		self.assertEqual((signed["status"]["signed_in"], signed["status"]["member"]), (True, False))
		session = signed["session"]
		self.assertEqual(self.refused(public.member_join, site=SLUG, member_session=session, accepted=0),
		                 "MEMBER_CONSENT_REQUIRED")
		out = self.as_guest(public.member_join, site=SLUG, member_session=session, accepted=1)
		self.assertTrue(out["member"])
		self.assertEqual(loyalty.membership(self.guest, self.club).source, "Web")

	def test_c04e_no_program_no_web_membership(self):
		frappe.db.set_value("TEX Loyalty Program", self.club, "enabled", 0)
		self.assertEqual(self.refused(public.member_link, site=SLUG, email=self.email, purpose="sign_in"),
		                 "MEMBERSHIP_UNAVAILABLE")
		self.assertIsNone(self.as_guest(public.site, slug=SLUG).get("membership"))
		frappe.db.set_value("TEX Loyalty Program", self.club, "enabled", 1)
		self.assertEqual(self.as_guest(public.site, slug=SLUG)["membership"]["programs"], ["Resort Club"])


class TestMemberSessionsAndPrivacy(WebMemberCase):
	def test_c04e_an_erased_guest_is_signed_out(self):
		self.join(self.guest)
		self.ask(self.email)
		session = self.verify(self.token())["session"]
		frappe.db.set_value("Guest", self.guest, "tex_erased_at", now_datetime())
		from kamra.tex.crm import service as crm

		crm.erase_traces(self.guest, "Erased guest", emails=(), audit_event=False)
		self.assertFalse(frappe.db.exists("TEX Member Session", {"guest": self.guest}))
		self.assertEqual(self.refused(public.member_status, site=SLUG, member_session=session),
		                 "MEMBER_SESSION_ENDED")

	def test_c04e_a_merge_moves_the_sessions(self):
		dup = self.profile("dupweb")
		self.ask(frappe.db.get_value("Guest", dup, "email"))
		session = self.verify(self.token())["session"]
		frappe.db.set_value("Guest", dup, "email", self.email)
		from kamra.tex.api import crm as crm_api

		frappe.set_user(self.desk)  # nosemgrep: frappe-setuser -- staff merge the duplicate
		crm_api.merge_guests(source=dup, target=self.guest)
		frappe.set_user("Administrator")  # nosemgrep: frappe-setuser -- back
		self.assertEqual(members.session_guest(frappe.get_doc("TEX Booking Site", SLUG), session), self.guest)

	def test_c04e_old_sessions_are_purged(self):
		self.ask(self.email)
		session = self.verify(self.token())["session"]
		frappe.db.set_value("TEX Member Session", {"token_hash": members.digest(session)}, "expires_at",
		                    add_days(now_datetime(), -(members.PURGE_AFTER_DAYS + 1)))
		self.assertEqual(members.purge_sessions(), 1)
		self.assertFalse(frappe.db.exists("TEX Member Session", {"guest": self.guest}))
