"""C-04 on the web (owner, 2026-10-03; ADR-078): a guest signs in on a booking site, or joins its hotels' loyalty
program, by a one-time link sent to their e-mail; the link opens a session on that device for 30 days. A new guest
joins with their e-mail, name and an explicit tick, confirmed by the link: nobody is joined with another's e-mail."""

import re
from unittest import mock

import frappe
from frappe.utils import add_days, add_to_date, now_datetime

from kamra.tex.api import public
from kamra.tex.crm import loyalty, members
from kamra.tex.money import D
from kamra.tex.services import notify
from kamra.tex.tests.integration import fixtures as fx
from kamra.tex.tests.integration.test_commercial_flows import SLUG
from kamra.tex.tests.integration.test_loyalty_membership import CLUB, OTHER, MembershipCase


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
		self.assertEqual(signed["expires_in"], members.SESSION_DAYS * 86400)   # the device counts from its own clock
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
		"""Review round 1 (B1): the join of a signed-in guest is confirmed by a link sent to their e-mail, as every web
		join (the owner's choice), never by the session alone: a script that holds a session joins nobody."""
		self.ask(self.email)                                                   # a past guest: a profile, no membership
		signed = self.verify(self.token())
		self.assertEqual((signed["status"]["signed_in"], signed["status"]["member"]), (True, False))
		session = signed["session"]
		self.assertEqual(self.refused(public.member_join, site=SLUG, member_session=session, accepted=0),
		                 "MEMBER_CONSENT_REQUIRED")
		out = self.as_guest(public.member_join, site=SLUG, member_session=session, accepted=1)
		self.assertEqual(out, {"ok": True})
		self.assertFalse(loyalty.is_member(self.guest, fx.PROPERTY))            # not before the link is opened
		to, _subject, html = self.mails[-1]
		self.assertEqual(to, self.email)
		self.assertIn("/member#token=", html)
		joined = self.verify(self.token())
		self.assertTrue(joined["status"]["member"])
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


STAY = {"check_in": str(fx.d(6, 10)), "check_out": str(fx.d(6, 13)), "rooms": [{"adults": 2, "children": []}]}


class TestMemberPricesOnTheWeb(WebMemberCase):
	"""C-04 on the web: a signed-in member is priced as one at the site's hotels whose program they are a member of;
	anyone else sees the member price as "Member price" (applied only when signed in, the owner's choice), never an
	offer they could book at it; a member's price books for that member only (MEMBERS_ONLY)."""

	def setUp(self):
		super().setUp()
		from kamra.tex.api import policies as policy_api

		doc = policy_api.save_record("TEX Promotion", {"promotion_name": "Web members 10", "property": fx.PROPERTY,
		                                               "trigger": "Automatic", "value_type": "PERCENT", "value": 10,
		                                               "applies_to": "ACCOMMODATION", "member_only": 1})
		policy_api.activate("TEX Promotion", doc["name"], at=str(add_to_date(now_datetime(), minutes=-1)))
		self.members_ten = doc["name"]

	def signed_in(self, guest: str | None = None) -> str:
		self.ask(frappe.db.get_value("Guest", guest or self.guest, "email"))
		return self.verify(self.token())["session"]

	def search(self, session: str | None = None) -> dict:
		return self.as_guest(public.search, site=SLUG, member_session=session, **STAY)

	def flex(self, res: dict) -> dict:
		return next(o for o in res["properties"][0]["offers"] if o["room_type"] == self.f["room_types"]["STD"]
		            and o["board"] == "AI" and o["rate_plan"] == self.f["rate_plans"]["FLEX"])

	def book(self, offer: dict, email: str, session: str | None = None) -> dict:
		q = self.as_guest(public.quote, site=SLUG, offer_key=offer["rooms"][0]["offer_key"])
		return self.as_guest(public.book, site=SLUG, quote_ids=[q["quote_id"]],
		                     guest={"first_name": "Mia", "last_name": "Member", "email": email, "country": "DE"},
		                     payment_method="Pay at Hotel", idempotency_key=f"c04f-{frappe.generate_hash(length=8)}")

	def test_c04f_a_visitor_sees_the_member_price_but_cannot_book_it(self):
		from kamra.tex.services import quoting

		res = self.search()
		offer = self.flex(res)
		self.assertEqual(res["member"], {"signed_in": False, "hotels": []})
		self.assertFalse(offer["member_price"])
		self.assertLess(D(offer["member_total"]), D(offer["total"]))            # the teaser: 10 % less
		self.assertEqual(D(offer["member_total"]), D(offer["total"]) * D("0.9"))
		self.assertLess(D(offer["rooms"][0]["member_total"]), D(offer["rooms"][0]["quote"]["totals"]["total"]))
		for o in res["properties"][0]["offers"]:                                # every key is anyone's price
			for r in o["rooms"]:
				self.assertFalse(quoting.verify(r["offer_key"])["member"])

	def test_c04f_a_signed_in_member_is_priced_as_one_and_books_at_it(self):
		self.join(self.guest)
		session = self.signed_in()
		anyone = self.flex(self.search())
		res = self.search(session)
		offer = self.flex(res)
		self.assertEqual(res["member"], {"signed_in": True, "hotels": [fx.PROPERTY]})
		self.assertTrue(offer["member_price"])
		self.assertEqual(D(offer["total"]), D(anyone["member_total"]))
		self.assertNotIn("member_total", offer)                                 # no teaser: it is their price
		self.assertIn(True, [p.get("member_only") for p in offer["rooms"][0]["quote"]["promotions"]])
		done = self.book(offer, self.email, session)
		self.assertEqual(D(done["total"]), D(offer["total"]))
		self.assertEqual(frappe.db.get_value("TEX Booking", done["booking"], "booker_guest"), self.guest)

	def test_c04f_a_members_price_books_for_that_member_only(self):
		self.join(self.guest)
		offer = self.flex(self.search(self.signed_in()))
		with self.assertRaises(frappe.ValidationError) as caught:
			self.book(offer, "c04f-friend@example.com")                         # a friend's booking at it
		self.assertEqual(code_of(caught.exception), "MEMBERS_ONLY")
		self.assertFalse(frappe.db.exists("Guest", {"email": "c04f-friend@example.com"}))

	def test_c04f_a_signed_in_guest_who_is_no_member_sees_the_teaser(self):
		session = self.signed_in()                                              # a profile, no membership
		res = self.search(session)
		offer = self.flex(res)
		self.assertEqual(res["member"], {"signed_in": True, "hotels": []})
		self.assertFalse(offer["member_price"])
		self.assertTrue(offer["member_total"])

	def test_c04f_an_ended_session_is_priced_as_anyone(self):
		self.join(self.guest)
		session = self.signed_in()
		self.as_guest(public.member_sign_out, site=SLUG, member_session=session)
		res = self.search(session)
		self.assertEqual(res["member"], {"signed_in": False, "hotels": []})
		self.assertFalse(self.flex(res)["member_price"])

	def test_c04f_no_members_promotion_no_teaser(self):
		from kamra.tex.api import policies as policy_api

		policy_api.archive("TEX Promotion", self.members_ten, reason="over")
		offer = self.flex(self.search())
		self.assertNotIn("member_total", offer)
		self.assertNotIn("member_total", offer["rooms"][0])


class TestReviewRound1(WebMemberCase):
	"""2N-2 review round 1 (ADR-078)."""

	def site(self):
		return frappe.get_doc("TEX Booking Site", SLUG)

	def test_r1_s1_one_plain_address_only(self):
		"""Frappe's own check takes a display name, a list or an invisible character: each would key the limit, the
		profile and the mail differently. Only one plain address is taken, in lower case."""
		for raw in ("Mia <mia.r1@example.com>", "junk, mia.r1@example.com", "mia.r1@example.com\u200b",
		            "mia.r1@example.com;eve@example.com", "mia r1@example.com"):
			self.assertEqual(self.refused(public.member_link, site=SLUG, email=raw), "GUEST_EMAIL_INVALID", raw)
		self.assertEqual(self.mails, [])
		self.assertEqual(self.ask("  " + self.email.upper() + " "), {"ok": True})
		self.assertEqual(self.mails[-1][0], self.email)                       # the member's own address
		self.assertIn("#token=", self.mails[-1][2])                            # their profile: a sign-in link

	def test_r1_s2_a_deadlock_retries_with_the_link_in_hand(self):
		from kamra.tex.services import txn

		self.join(self.guest)
		self.ask(self.email)
		token, real, calls = self.token(), members._profile, []

		def victim_once(*a, **kw):
			calls.append(1)
			if len(calls) == 1:
				raise frappe.QueryDeadlockError("Deadlock found when trying to get lock (simulated)")
			return real(*a, **kw)

		# the rollback kept out: the test's fixtures are its transaction
		with mock.patch.object(members, "_profile", side_effect=victim_once), mock.patch.object(txn.time, "sleep"), \
				mock.patch.object(frappe.db, "rollback"):
			signed = self.verify(token)
		self.assertEqual(len(calls), 2)
		self.assertTrue(signed["status"]["member"])

	def test_r1_s2_a_busy_answer_keeps_the_link(self):
		from kamra.tex.services import txn

		self.join(self.guest)
		self.ask(self.email)
		token = self.token()
		deadlock = frappe.QueryDeadlockError("Deadlock found")
		with mock.patch.object(members, "_profile", side_effect=deadlock), mock.patch.object(txn.time, "sleep"), \
				mock.patch.object(frappe.db, "rollback"):
			self.assertEqual(self.refused(public.member_verify, site=SLUG, token=token), "BUSY")
		self.assertTrue(self.verify(token)["status"]["member"])                 # the link still works, once
		self.assertEqual(self.refused(public.member_verify, site=SLUG, token=token), "MEMBER_LINK_INVALID")

	def test_r1_s4_a_stranger_is_greeted_with_no_typed_name(self):
		"""A join mail to an address with no profile never carries what the visitor typed (anyone could send text of
		their choice in the hotel's name)."""
		self.ask("c04-r1-stranger@example.com", "join", first_name="Visit", last_name="evil.example now", accepted=1)
		self.assertNotIn("evil.example", self.mails[-1][2])
		self.assertNotIn("Visit", self.mails[-1][2])
		# the names typed are still the new profile's, once the link proves the address
		self.verify(self.token())
		self.assertEqual(frappe.db.get_value("Guest", {"email": "c04-r1-stranger@example.com"},
		                                     ["first_name", "last_name"]), ("Visit", "evil.example now"))

	def test_r1_s5_a_group_sites_join_belongs_to_one_of_its_hotels(self):
		from kamra.tex.api import loyalty as loyalty_api

		group = frappe.db.get_value("Property", fx.PROPERTY, "tex_hotel_group")
		frappe.db.set_value("TEX Loyalty Program", self.club, "enabled", 0)
		shared = loyalty_api.save_program({**CLUB, "program_name": "Group Club R1", "hotel_group": group})["name"]
		site = frappe._dict(name=SLUG, property=None, hotel_group=group)
		members.join_site(site, self.guest)
		m = loyalty.membership(self.guest, shared)
		self.assertEqual(m.status, "Active")
		self.assertIn(m.property, members.site_properties(site))                 # a hotel of the site, never none
		event = frappe.db.get_value("TEX Audit Event", {"action": "loyalty.member_join", "reference_name": m.name},
		                            "property")
		self.assertEqual(event, m.property)                                    # its staff see the join

	def test_r1_n5_a_disabled_hotel_is_not_the_sites(self):
		group = frappe.db.get_value("Property", fx.PROPERTY, "tex_hotel_group")
		closed = fx.ensure("Property", {"property_name": "TEX C04 R1 Closed"},
		                   {"property_name": "TEX C04 R1 Closed", "city": "Kemer", "country": "Turkey", "currency": "EUR"})
		frappe.db.set_value("Property", closed, {"tex_hotel_group": group, "disabled": 1})
		self.assertNotIn(closed, members.site_properties(frappe._dict(name=SLUG, property=None, hotel_group=group)))

	def test_r1_n1_an_erasure_counts_the_sessions_apart(self):
		self.join(self.guest)
		self.ask(self.email)
		self.verify(self.token())
		frappe.db.set_value("Guest", self.guest, "tex_erased_at", now_datetime())
		from kamra.tex.crm import service as crm

		out = crm.erase_traces(self.guest, "Erased guest", emails=(), audit_event=False)
		self.assertEqual((out["memberships_ended"], out["sessions_ended"]), (1, 1))

	def test_r1_n3_the_language_is_one_the_booking_app_speaks(self):
		self.ask("c04-r1-lang@example.com", "join", first_name="Lia", last_name="Lang", accepted=1,
		         language="zz-<b>")
		self.verify(self.token())
		self.assertIn(frappe.db.get_value("Guest", {"email": "c04-r1-lang@example.com"}, "tex_language"), (None, "en"))

	def test_r1_n4_the_counter_always_expires(self):
		"""The counter is made with its hour in one step: never one without an expiry (the address capped for good)."""
		real = members._cache()

		class SeesAnOldCounter:
			def __getattr__(self, name):
				return getattr(real, name)

			def get(self, key):                                                # the old counter seen, then gone
				return b"1"

		key = frappe.cache.make_key(f"{members.COUNT_KEY}{SLUG}:{members.digest(self.email)}")
		frappe.cache.delete(key)  # nosemgrep: frappe-cache-breaks-multitenancy -- key is site-scoped by make_key
		with mock.patch.object(members, "_cache", return_value=SeesAnOldCounter()):
			self.ask(self.email)
		self.assertGreater(frappe.cache.ttl(key), 0)  # nosemgrep: frappe-cache-breaks-multitenancy -- site-scoped key

	def test_r1_n16_a_retried_request_sends_one_mail(self):
		self.join(self.guest)
		for _ in range(2):
			self.assertEqual(self.ask(self.email, idempotency_key="r1-retry-once"), {"ok": True})
		self.assertEqual(len(self.mails), 1)

	def test_r1_n19_a_session_counts_on_its_own_site_only(self):
		self.join(self.guest)
		self.ask(self.email)
		session = self.verify(self.token())["session"]
		self.assertEqual(members.session_guest(self.site(), session), self.guest)
		self.assertIsNone(members.session_guest(frappe._dict(name="another-site"), session))

	def test_r1_n19_a_join_never_takes_another_enterprises_profile(self):
		theirs = frappe.get_doc({"doctype": "Guest", "first_name": "Other", "last_name": "Tenant",
		                         "email": "c04-r1-shared@example.com",
		                         "tex_enterprise": frappe.db.get_value("Property", OTHER, "tex_enterprise")}
		                        ).insert(ignore_permissions=True).name
		self.ask("c04-r1-shared@example.com", "join", first_name="Our", last_name="Guest", accepted=1)
		self.verify(self.token())
		ours = frappe.db.get_value("Guest", {"email": "c04-r1-shared@example.com", "name": ("!=", theirs)},
		                           ["name", "tex_enterprise", "first_name"], as_dict=True)
		self.assertEqual((ours.tex_enterprise, ours.first_name),
		                 (frappe.db.get_value("Property", fx.PROPERTY, "tex_enterprise"), "Our"))
		self.assertIsNone(loyalty.membership(theirs, self.club))
		self.assertEqual(frappe.db.get_value("Guest", theirs, "first_name"), "Other")

	def test_r1_n19_a_member_who_left_rejoins_on_the_web(self):
		self.join(self.guest)
		frappe.set_user(self.desk)  # nosemgrep: frappe-setuser -- staff end the membership
		from kamra.tex.api import crm as crm_api

		crm_api.loyalty_leave(guest=self.guest, program=self.club, reason="Guest asked to leave")
		frappe.set_user("Administrator")  # nosemgrep: frappe-setuser -- back
		self.assertFalse(loyalty.is_member(self.guest, fx.PROPERTY))
		self.ask(self.email, "join", first_name="Mia", last_name="Member", accepted=1)
		self.verify(self.token())
		m = loyalty.membership(self.guest, self.club)
		self.assertEqual((m.status, m.source), ("Active", "Web"))

	def test_r1_n19_an_erased_profiles_join_link_joins_nobody(self):
		self.ask(self.email, "join", first_name="Mia", last_name="Member", accepted=1)
		token = self.token()
		frappe.db.set_value("Guest", self.guest, "tex_erased_at", now_datetime())
		self.assertEqual(self.refused(public.member_verify, site=SLUG, token=token), "NOT_A_MEMBER")
		self.assertIsNone(loyalty.membership(self.guest, self.club))
		self.assertFalse(frappe.db.exists("TEX Member Session", {"guest": self.guest}))

	def test_r1_n19_signed_out_sessions_are_purged_too(self):
		self.ask(self.email)
		session = self.verify(self.token())["session"]
		self.as_guest(public.member_sign_out, site=SLUG, member_session=session)
		frappe.db.set_value("TEX Member Session", {"token_hash": members.digest(session)}, "revoked_at",
		                    add_days(now_datetime(), -(members.PURGE_AFTER_DAYS + 1)))
		self.assertEqual(members.purge_sessions(), 1)


class TestReviewRound2(WebMemberCase):
	"""2N-2 review round 2 (ADR-078): the address is Frappe's own pattern, in ASCII."""

	def test_r2_an_apostrophe_is_part_of_an_address(self):
		"""o'brien@example.ie books, so it signs in and joins too (round 1's deny-list refused it)."""
		email = "o'brien.r2@example.ie"
		self.assertEqual(self.ask(email, "join", first_name="Sean", last_name="O'Brien", accepted=1), {"ok": True})
		self.assertEqual(self.mails[-1][0], email)
		self.verify(self.token())
		self.assertTrue(frappe.db.exists("Guest", {"email": email}))

	def test_r2_an_address_outside_ascii_is_refused(self):
		"""The database compares accents away (utf8mb4_unicode_ci): an accented domain would find an ASCII member's
		profile and mail its sign-in link to the look-alike address."""
		for raw in ("x@mail.exämple.de", "anna@mail.exámple.de", "ſam@example.com", "x@gmail.cöm"):
			self.assertEqual(self.refused(public.member_link, site=SLUG, email=raw), "GUEST_EMAIL_INVALID", repr(raw))
		self.assertEqual(self.mails, [])


class TestRejoinBlocked(WebMemberCase):
	"""C-04h (owner, 2026-10-04; HANDOFF §2 6b, option b): staff who end a membership may block a rejoin on the web
	(a reason such as abuse). A web join then never makes it active again: the site answers as it answers anyone, and
	the mail, which only the address's owner reads, says to ask the hotel, with no link. Staff joining the guest lift
	it; a membership ended without the block is rejoined on the web as before (``test_r1_n19_…_rejoins_on_the_web``)."""

	def leave(self, *, block: bool, guest: str | None = None) -> dict:
		from kamra.tex.api import crm as crm_api

		frappe.set_user(self.desk)  # nosemgrep: frappe-setuser -- staff end the membership
		try:
			return crm_api.loyalty_leave(guest=guest or self.guest, program=self.club, reason="Abused member prices",
			                             block_rejoin=int(block))
		finally:
			frappe.set_user("Administrator")  # nosemgrep: frappe-setuser -- back

	def audited(self, action: str, name: str) -> dict:
		import json

		raw = frappe.get_all("TEX Audit Event", filters={"action": action, "reference_name": name},
		                     pluck="new_value", order_by="creation desc", limit=1)
		return json.loads(raw[0]) if raw else {}

	def test_c04h_a_blocked_member_cannot_rejoin_on_the_web(self):
		self.join(self.guest)
		name = self.leave(block=True)["name"]
		self.assertEqual(frappe.db.get_value("TEX Loyalty Member", name, ["status", "rejoin_blocked"]), ("Left", 1))
		self.assertTrue(self.audited("loyalty.member_leave", name).get("rejoin_blocked"))
		# a visitor's join: the same answer as anyone's; the mail says to ask the hotel and carries no link
		self.assertEqual(self.ask(self.email, "join", first_name="Mia", last_name="Member", accepted=1), {"ok": True})
		to, _subject, html = self.mails[-1]
		self.assertEqual(to, self.email)
		self.assertIsNone(self.token())
		self.assertNotIn("/member", html)
		self.assertIn("contact the hotel", html)
		self.assertEqual(loyalty.membership(self.guest, self.club).status, "Left")
		# a signed-in guest's join is answered the same way
		self.ask(self.email)
		session = self.verify(self.token())["session"]
		self.assertEqual(self.as_guest(public.member_join, site=SLUG, member_session=session, accepted=1), {"ok": True})
		self.assertIsNone(self.token())
		self.assertIn("contact the hotel", self.mails[-1][2])
		self.assertFalse(loyalty.is_member(self.guest, fx.PROPERTY))

	def test_c04h_a_join_link_asked_before_the_block_rejoins_nobody(self):
		self.join(self.guest)
		self.leave(block=False)                                                # the guest asked to leave
		self.ask(self.email, "join", first_name="Mia", last_name="Member", accepted=1)
		token = self.token()
		self.assertIsNotNone(token)                                            # not blocked yet: a link
		self.leave(block=True)                                                 # staff block before it is opened
		signed = self.verify(token)
		self.assertFalse(signed["status"]["member"])
		m = loyalty.membership(self.guest, self.club)
		self.assertEqual((m.status, m.rejoin_blocked), ("Left", 1))

	def test_c04h_staff_who_join_the_guest_lift_the_block(self):
		self.join(self.guest)
		name = self.leave(block=True)["name"]
		self.join(self.guest)
		self.assertEqual(frappe.db.get_value("TEX Loyalty Member", name, ["status", "rejoin_blocked"]), ("Active", 0))
		self.assertTrue(self.audited("loyalty.member_join", name).get("unblocked"))
		self.leave(block=False)
		self.ask(self.email, "join", first_name="Mia", last_name="Member", accepted=1)
		self.assertTrue(self.verify(self.token())["status"]["member"])

	def test_c04h_staff_see_the_block(self):
		from kamra.tex.api import crm as crm_api

		self.join(self.guest)
		self.leave(block=True)
		frappe.set_user(self.desk)  # nosemgrep: frappe-setuser -- the hotel's staff read the profile
		try:
			accounts = crm_api.loyalty_summary(self.guest)
		finally:
			frappe.set_user("Administrator")  # nosemgrep: frappe-setuser -- back
		m = next(a for a in accounts if a["program"] == self.club)["membership"]
		self.assertEqual((m["status"], m["rejoin_blocked"]), ("Left", True))

	def test_c04h_a_merge_keeps_the_block_of_the_last_word(self):
		from kamra.tex.api import crm as crm_api

		kept, dup = self.guest, self.profile("blocked-dup")
		mine = self.join(kept)["name"]
		self.join(dup)
		theirs = self.leave(block=True, guest=dup)["name"]
		frappe.db.set_value("TEX Loyalty Member", mine, "modified", "2026-01-01 10:00:00", update_modified=False)
		frappe.set_user(self.desk)  # nosemgrep: frappe-setuser -- staff merge the duplicate
		crm_api.merge_guests(source=dup, target=kept)
		frappe.set_user("Administrator")  # nosemgrep: frappe-setuser -- back
		self.assertFalse(frappe.db.exists("TEX Loyalty Member", theirs))
		self.assertEqual(frappe.db.get_value("TEX Loyalty Member", mine, ["status", "rejoin_blocked"]), ("Left", 1))
