"""CRM privacy, second independent review of ADR-056 (H1, M1–M3, L1–L9).

H1 · a consent withdrawal reads the rows it clears through indexes and writes them by primary key
(no locking scan of the funnel inside the withdrawal); a deadlock or lock timeout while tracking or
mailing inside a booking's transaction is never swallowed: the booking is retried or fails, never
reported as booked after its transaction was rolled back.

M1 · an erasure withdraws every consent and leaves no contact behind: cases, funnel hashes, the
profile's change history, the booker data of its bookings; clearing an e-mail or a phone in Desk /
REST forgets the contact data it leaves behind.

M2 · a duplicate profile is merged into another by staff who may edit the guest at every hotel either
profile has records at, inside one enterprise: every link to the profile moves, the loyalty ledger
with it (one balance, the tier from the merged lifetime), consent is the stricter of the two, and
the merge is audited; a profile shows its possible duplicates (same phone or e-mail).

M3 · the loyalty ledger in Desk / REST follows the hotel of each entry, not the program's.

L1–L9 · consent sent as text to the CRM means what it says; no copies of contact data kept from the
change history; a case's session, quote and recovery booking and a funnel event's session and
payload are withheld from Desk / REST, and an anonymous case keeps no quote; another hotel's ledger
entries show no dates, reasons or actors; a browser's funnel fields are checked against the site's
hotels, their room types and rate plans, the board codes and the session's quotes; a phone finds
no profile when it is shared or the booker is anonymous; a withdrawal in Desk / REST is on the
consent record; a case written after a withdrawal keeps no contact; p40 on its own paths; p45.
"""

import hashlib
import inspect
import json
from unittest import mock

import frappe
import frappe.api.v1
import frappe.client
import frappe.desk.form.load
from frappe.utils import add_to_date, get_datetime, now_datetime

from kamra.tex.api import crm as crm_api
from kamra.tex.api import loyalty as loyalty_api
from kamra.tex.api import public
from kamra.tex.crm import loyalty
from kamra.tex.crm import service as crm
from kamra.tex.security import internals
from kamra.tex.security.audit import audit
from kamra.tex.services import booking, notify
from kamra.tex.tests.integration import fixtures as fx
from kamra.tex.tests.integration.test_commercial_flows import GUEST, SLUG
from kamra.tex.tests.integration.test_crm_privacy import (
	PrivacyCase,
	as_user,
	funnel,
	request_to,
	sister_hotel,
)
from kamra.tex.tests.integration.test_crm_segments import OTHER, agent
from kamra.tex.tests.integration.test_patches import migrate, never_ran, rerun_changes

P40 = "p40_crm_privacy_review"
P45 = "p45_crm_privacy_second_review"
LATER = 60                                     # minutes after which a quiet session is abandoned


def later(minutes: int = LATER):
	return add_to_date(now_datetime(), minutes=minutes)


def version_of(before, after) -> str:
	"""The change-history row Frappe writes on a save (tests skip it: ``frappe.in_test``)."""
	v = frappe.new_doc("Version")
	assert v.update_version_info(before, after)
	v.insert(ignore_permissions=True)
	return v.name


def quote_for(session: str) -> dict:
	"""search → quote on the test site, as an anonymous visitor (``guest_books`` without the booking)."""
	as_user("Guest")
	res = public.search(site=SLUG, check_in=str(fx.d(6, 10)), check_out=str(fx.d(6, 13)),
	                    rooms=[{"adults": 2, "children": [8]}], market="DE", session_id=session)
	rt = frappe.db.get_value("Room Type", {"property": fx.PROPERTY, "room_type_code": "STD"})
	rp = frappe.db.get_value("Rate Plan", {"property": fx.PROPERTY, "code": "FLEX"})
	offer = next(o for o in res["properties"][0]["offers"]
	             if o["room_type"] == rt and o["board"] == "AI" and o["rate_plan"] == rp)
	q = public.quote(site=SLUG, offer_key=offer["rooms"][0]["offer_key"], session_id=session)
	assert q["ok"], q
	return q


def tracked(event: str, *, at=None, rollback_to: str | None = None, error=frappe.QueryDeadlockError):
	"""``frappe.get_doc`` failing as a deadlock victim does for the funnel event ``event`` (once): the
	database rolled the transaction back (to ``rollback_to``, standing in for the whole transaction)."""
	real = frappe.get_doc
	failed = []

	def get_doc(*args, **kwargs):
		d = args[0] if args else None
		if not failed and isinstance(d, dict) and d.get("doctype") == "TEX Funnel Event" and d.get("event") == event:
			failed.append(event)
			if rollback_to:
				frappe.db.rollback(save_point=rollback_to)
			raise error("Deadlock found when trying to get lock; try restarting transaction")
		return real(*args, **kwargs)

	return mock.patch.object(frappe, "get_doc", side_effect=get_doc), failed


# ─── H1: the withdrawal and the booking transaction ──────────────────────


class TestWithdrawalLocksOnlyItsRows(PrivacyCase):
	def test_the_withdrawal_reads_through_indexes_and_writes_by_primary_key(self):
		statements = (
			(crm.CASES_OF_GUEST, {"guest": "G-none"}, "tex_abandoned_guest", "TEX Abandoned Booking"),
			(crm.FUNNEL_BY_HASH, {"hashes": ("ab" * 32,)}, "tex_funnel_hash_session", "TEX Funnel Event"),
			(crm.FUNNEL_BY_SESSION, {"sessions": ("h1-none",)}, "tex_funnel_session_time", "TEX Funnel Event"),
			(crm.FORGET_CASES, {"names": ("none",)}, "PRIMARY", "TEX Abandoned Booking"),
			(crm.FORGET_EVENTS, {"names": ("none",)}, "PRIMARY", "TEX Funnel Event"),
		)
		for sql, params, index, doctype in statements:
			self.assertNotIn("IFNULL", sql.upper())
			self.assertNotIn(" OR ", sql.upper())
			[plan] = frappe.db.sql(f"EXPLAIN {sql}", params, as_dict=True)
			self.assertIn(index, (plan.possible_keys or "").split(","), (sql, plan))
			# the optimizer may read a table of a few rows whole; the funnel is never that small for long
			if frappe.db.count(doctype) >= 1000:
				self.assertEqual((plan.key, plan.type != "ALL"), (index, True), (sql, plan))
		self.assertGreaterEqual(frappe.db.count("TEX Funnel Event"), 1000, "the test site's funnel")

	def test_a_deadlock_or_timeout_while_tracking_is_never_swallowed(self):
		site = frappe.get_cached_doc("TEX Booking Site", frappe.db.get_value("TEX Booking Site", {"site_slug": SLUG}))
		for error in (frappe.QueryDeadlockError, frappe.QueryTimeoutError):
			patch, failed = tracked("search", error=error)
			with patch, self.assertRaises(error):
				public._track(site, "h1-track", "search", {"check_in": "2027-01-01"})
			self.assertEqual(failed, ["search"])
		public._track(site, "h1-track", "search", {"check_in": "2027-01-01"})       # anything else: best effort
		self.assertEqual(len(funnel("h1-track")), 1)

	def test_a_booking_whose_tracking_deadlocks_is_retried_never_reported_booked(self):
		# the last funnel event of a booking: "payment_started" when a deposit is due, "booked" otherwise
		for event, method in (("booked", "Pay at Hotel"), ("payment_started", "Card")):
			session = f"h1-{event}"
			q = quote_for(session)
			frappe.db.savepoint("h1_book")
			patch, failed = tracked(event, rollback_to="h1_book")
			real_rollback = frappe.db.rollback
			with patch, mock.patch.object(frappe.local.db, "rollback",
			                              side_effect=lambda **kw: real_rollback(save_point="h1_book")):
				as_user("Guest")
				out = public.book(site=SLUG, quote_ids=[q["quote_id"]], guest={**GUEST, "email": f"{session}@example.com"},
				                  payment_method=method, session_id=session, idempotency_key=f"idem-{session}")
			as_user("Administrator")
			self.assertEqual(failed, [event])                        # the first attempt was the victim
			self.assertTrue(frappe.db.exists("TEX Booking", out["booking"]), f"{event}: reported a rolled-back booking")
			self.assertEqual(frappe.db.count("TEX Booking", {"booker_email": f"{session}@example.com"}), 1, event)
			self.assertEqual(len(funnel(session, event)), 1, event)

	def test_the_booking_itself_propagates_a_tracking_deadlock(self):
		q = quote_for("h1-raw")
		raw = inspect.unwrap(public.book)                        # below the retry: what it is handed
		patch, failed = tracked("payment_started")
		with patch, self.assertRaises(frappe.QueryDeadlockError):
			as_user("Guest")
			raw(site=SLUG, quote_ids=[q["quote_id"]], guest={**GUEST, "email": "h1-raw@example.com"},
			    payment_method="Card", session_id="h1-raw", idempotency_key="idem-h1-raw")
		self.assertEqual(failed, ["payment_started"])

	def test_a_deadlock_while_mailing_is_never_swallowed(self):
		args = {"reference": ("TEX Booking", "none"), "guest": None, "property": fx.PROPERTY, "template": "t",
		        "booking": None, "log_title": "h1 mail"}
		for target, error in (("_log", frappe.QueryDeadlockError), ("_send", frappe.QueryTimeoutError)):
			with mock.patch.object(notify, target, side_effect=error("lock")), self.assertRaises(error):
				notify._deliver("h1@example.com", "s", "<p>x</p>", **args)
		with mock.patch.object(notify, "_send", side_effect=RuntimeError("smtp down")):
			self.assertEqual(notify._deliver("h1@example.com", "s", "<p>x</p>", **args)["status"], "Failed")


# ─── M1: erasure ─────────────────────────────────────────────────────────


class TestErasure(PrivacyCase):
	def test_an_erasure_withdraws_consent_and_leaves_no_contact_behind(self):
		from kamra import api

		b, guest = self.booked_guest("m1-erase", "m1-erase@example.com", consent_email=1, consent_sms=1,
		                             phone="+49 30 7770")
		crm.detect_abandoned(now=later())
		case = frappe.db.get_value("TEX Abandoned Booking", {"session_id": "m1-erase"})
		self.assertTrue(frappe.db.get_value("TEX Abandoned Booking", case, "email"))
		before = frappe.get_doc("Guest", guest)
		after = frappe.get_doc("Guest", guest)
		after.last_name, after.phone = "Kraus-Erased", "+49 30 7771"
		version_of(before, after)                                  # the Desk form's history of the profile
		api.anonymize_guest(guest)
		g = frappe.db.get_value("Guest", guest, ["email", "phone", "tex_consent_email", "tex_consent_sms",
		                                         "tex_consent_whatsapp", "tex_consent_source", "full_name"],
		                        as_dict=True)
		self.assertEqual((g.email or None, g.phone or None, g.tex_consent_email, g.tex_consent_sms,
		                  g.tex_consent_whatsapp, g.tex_consent_source), (None, None, 0, 0, 0, "erasure"))
		self.assertEqual(frappe.db.get_value("TEX Abandoned Booking", case, ["guest", "email", "phone",
		                                                                     "consent_marketing"]),
		                 (None, None, None, 0))
		self.assertEqual({e.email_hash for e in funnel("m1-erase")}, {None})
		history = json.dumps(frappe.get_all("Version", filters={"ref_doctype": "Guest", "docname": guest},
		                                    pluck="data"))
		for trace in ("m1-erase@", "+49 30 777", "Kraus"):
			self.assertNotIn(trace, history)
		self.assertEqual(frappe.db.get_value("TEX Booking", b["booking"], ["booker_name", "booker_email",
		                                                                   "booker_phone"]),
		                 (g.full_name, None, None))
		self.assertTrue(frappe.db.exists("TEX Audit Event", {"action": "guest.consent", "reference_name": guest,
		                                                     "reason": "erasure"}))
		self.assertTrue(frappe.db.exists("TEX Audit Event", {"action": "guest.erase", "reference_name": guest}))

	def test_clearing_an_email_or_a_phone_forgets_the_contact_left_behind(self):
		guests = {}
		for session in ("m1-no-mail", "m1-no-phone"):
			_b, guests[session] = self.booked_guest(session, f"{session}@example.com", consent_email=1,
			                                        phone="+49 30 7772")
		crm.detect_abandoned(now=later())
		for session, field in (("m1-no-mail", "email"), ("m1-no-phone", "phone")):
			g = frappe.get_doc("Guest", guests[session])              # a Desk / REST save; consent untouched
			g.set(field, None)
			g.save()
			self.assertEqual(frappe.db.get_value("Guest", guests[session], "tex_consent_email"), 1, session)
			case = frappe.db.get_value("TEX Abandoned Booking", {"session_id": session}, ["guest", "email", "phone"])
			self.assertEqual(case, (None, None, None), session)
			self.assertEqual({e.email_hash for e in funnel(session)}, {None}, session)


# ─── M2: merging duplicate profiles ──────────────────────────────────────


class TestGuestMerge(PrivacyCase):
	def setUp(self):
		super().setUp()
		self.club = frappe.get_doc({"doctype": "TEX Loyalty Program", "program_name": "Merge Club", "enabled": 1,
		                            "currency": "EUR", "point_value": "0.1", "property": fx.PROPERTY,
		                            "tiers": [{"tier_name": "Silver", "min_points": 100, "earn_multiplier": 1},
		                                      {"tier_name": "Gold", "min_points": 300, "earn_multiplier": 1}]}
		                           ).insert(ignore_permissions=True).name

	def pair(self, tag: str, **target_values) -> tuple[str, str, dict]:
		"""The profile that stays (booked online, e-mail consent) and its duplicate (a phone booking by
		staff under another e-mail, no consent), each with a stay, points and a case."""
		kept_b, kept = self.booked_guest(f"{tag}-a", f"{tag}-a@example.com", consent_email=1, phone="+49 30 8880")
		dup_b, dup = self.booked_guest(f"{tag}-b", f"{tag}-b@example.com", phone="+49 30 8880")
		frappe.db.set_value("Guest", dup, {"date_of_birth": "1990-05-04", "vip": 1})
		if target_values:
			frappe.db.set_value("Guest", kept, target_values)
		self.points(self.club, kept, 200, booking=kept_b["booking"], entry_type="Earn", reason="stay a")
		self.points(self.club, dup, 150, booking=dup_b["booking"], entry_type="Earn", reason="stay b")
		loyalty._sync_guest(kept)
		loyalty._sync_guest(dup)
		comm = frappe.get_doc({"doctype": "TEX Communication", "guest": dup, "property": fx.PROPERTY,
		                       "channel": "Phone", "direction": "Inbound", "status": "Logged",
		                       "consent_basis": "Transactional", "subject": "called"}).insert(ignore_permissions=True)
		crm.detect_abandoned(now=later())
		return kept, dup, {"kept_booking": kept_b["booking"], "dup_booking": dup_b["booking"], "comm": comm.name}

	def test_a_duplicate_moves_whole_into_the_profile_that_stays(self):
		kept, dup, rec = self.pair("m2-all")
		audit("guest.consent", reference_doctype="Guest", reference_name=dup, new={"tex_consent_sms": False},
		      reason="the duplicate's own record")
		as_user(self.here)
		dups = crm_api.guest(kept)["possible_duplicates"]
		self.assertEqual([(d["name"], d["match"]) for d in dups], [(dup, ["phone"])])
		out = crm_api.merge_guests(source=dup, target=kept)
		as_user("Administrator")
		self.assertFalse(frappe.db.exists("Guest", dup))
		self.assertEqual(out["target"], kept)
		self.assertEqual(frappe.db.get_value("TEX Booking", rec["dup_booking"], "booker_guest"), kept)
		self.assertEqual(frappe.db.get_value("TEX Communication", rec["comm"], "guest"), kept)
		self.assertEqual(frappe.db.count("Reservation", {"guest": dup}), 0)
		self.assertEqual(frappe.db.count("TEX Loyalty Ledger", {"guest": dup}), 0)
		for link in ("TEX Booking", "TEX Loyalty Ledger", "TEX Communication", "Reservation"):
			self.assertIn(link, out["moved"])
		# one balance, the tier from the merged lifetime
		[account] = loyalty.summary(kept, {self.club})
		self.assertEqual((account["available"], account["lifetime_earned"], account["tier"]), (350, 350, "Gold"))
		self.assertEqual(frappe.db.get_value("Guest", kept, "tex_loyalty_points"), 350)
		# the stricter consent: the duplicate never agreed, so the merged profile has not
		g = frappe.db.get_value("Guest", kept, ["tex_consent_email", "tex_consent_source", "date_of_birth", "vip",
		                                        "email"], as_dict=True)
		self.assertEqual((g.tex_consent_email, g.tex_consent_source, str(g.date_of_birth), g.vip, g.email),
		                 (0, "merge", "1990-05-04", 1, "m2-all-a@example.com"))
		for session in ("m2-all-a", "m2-all-b"):                     # no case keeps its contact
			self.assertEqual(frappe.db.get_value("TEX Abandoned Booking", {"session_id": session},
			                                     ["guest", "email"]), (None, None), session)
		[merge] = frappe.get_all("TEX Audit Event", filters={"action": "guest.merge", "reference_name": kept},
		                         fields=["old_value", "new_value", "property", "actor"])
		self.assertEqual((json.loads(merge.old_value)["source"], merge.actor), (dup, self.here))
		self.assertNotIn("@", merge.old_value + merge.new_value)       # no contact data in the trail
		self.assertTrue(frappe.db.exists("TEX Audit Event", {"action": "guest.consent", "reference_name": kept,
		                                                     "reason": "merge"}))
		# the merged profile's consent record includes the duplicate's
		as_user(self.here)
		self.assertIn("the duplicate's own record", {c["reason"] for c in crm_api.guest(kept)["consent_history"]})

	def test_consent_both_gave_stays_given(self):
		kept, dup, _rec = self.pair("m2-both")
		frappe.db.set_value("Guest", dup, "tex_consent_email", 1)
		as_user(self.here)
		crm_api.merge_guests(source=dup, target=kept)
		self.assertEqual(frappe.db.get_value("Guest", kept, "tex_consent_email"), 1)

	def test_only_staff_who_may_edit_everywhere_either_profile_is_known_may_merge(self):
		kept, dup, _rec = self.pair("m2-perm")
		sister = sister_hotel(self.f["group"], self.ent)
		elsewhere = frappe.get_doc({"doctype": "TEX Booking", "property": sister, "status": "Confirmed",
		                            "booker_guest": dup, "currency": "EUR"}).insert(ignore_permissions=True).name
		as_user(self.here)                                             # edits here, not at the sister hotel
		with self.assertRaises(frappe.PermissionError):
			crm_api.merge_guests(source=dup, target=kept)
		as_user(agent("m2-viewer@example.com", fx.PROPERTY, "Viewer"))  # may not edit guests at all
		with self.assertRaises(frappe.PermissionError):
			crm_api.merge_guests(source=dup, target=kept)
		as_user(self.there)                                            # another enterprise sees neither
		with self.assertRaises(frappe.PermissionError):
			crm_api.merge_guests(source=dup, target=kept)
		as_user("Administrator")
		self.assertTrue(frappe.db.exists("Guest", dup))
		self.assertEqual(frappe.db.get_value("TEX Booking", elsewhere, "booker_guest"), dup)

	def test_profiles_of_two_enterprises_are_never_merged(self):
		kept, dup, _rec = self.pair("m2-ent")
		frappe.db.set_value("Guest", dup, "tex_enterprise", self.other_ent)
		frappe.db.set_value("Reservation", {"guest": dup}, "property", OTHER)
		as_user("Administrator")
		with self.assertRaises(frappe.ValidationError):
			crm.merge_guests(dup, kept)
		self.assertTrue(frappe.db.exists("Guest", dup))

	def test_the_legacy_merge_moves_tex_records_too(self):
		from kamra import api

		kept, dup, rec = self.pair("m2-legacy")
		as_user("Administrator")
		api.merge_guests(source=dup, target=kept)
		self.assertFalse(frappe.db.exists("Guest", dup))
		self.assertEqual(frappe.db.get_value("TEX Booking", rec["dup_booking"], "booker_guest"), kept)
		self.assertEqual(frappe.db.get_value("Guest", kept, "tex_loyalty_points"), 350)

	def test_possible_duplicates_are_only_those_the_viewer_may_see(self):
		kept, dup, _rec = self.pair("m2-dups")
		hidden = frappe.get_doc({"doctype": "Guest", "first_name": "Other", "last_name": "Tenant",
		                         "phone": "+49 30 8880", "tex_enterprise": self.other_ent}).insert(
			ignore_permissions=True).name
		as_user(self.here)
		names = {d["name"] for d in crm_api.guest(kept)["possible_duplicates"]}
		self.assertEqual(names, {dup})
		self.assertNotIn(hidden, names)


# ─── M3 and L4: the loyalty ledger across the hotels of a group ──────────


class TestLedgerAcrossHotels(PrivacyCase):
	def setUp(self):
		super().setUp()
		self.sister = sister_hotel(self.f["group"], self.ent)
		self.club = self.program("Group Club", hotel_group=self.f["group"])
		self.b, self.guest = self.booked_guest("m3-led", "m3-led@example.com")
		self.elsewhere = frappe.get_doc({"doctype": "TEX Booking", "property": self.sister, "status": "Confirmed",
		                                 "booker_guest": self.guest, "currency": "EUR"}).insert(
			ignore_permissions=True).name
		self.here_earn = self.points(self.club, self.guest, 200, booking=self.b["booking"], entry_type="Earn",
		                             reason="stay here")
		self.there_earn = self.points(self.club, self.guest, 300, booking=self.elsewhere, entry_type="Earn",
		                              reason="stay 2027-07-01→2027-07-05")
		frappe.db.set_value("TEX Loyalty Ledger", self.there_earn, {"available_on": "2027-07-05",
		                                                           "expires_on": "2029-07-05"})
		self.sister_desk = agent("m3-sister@example.com", self.sister)
		as_user(self.sister_desk)                                      # a manual adjustment at the sister hotel
		self.there_adjust = loyalty.adjust(self.guest, self.club, 25, "goodwill after a noisy room")
		as_user(self.here)
		self.here_adjust = loyalty.adjust(self.guest, self.club, 10, "birthday", property=fx.PROPERTY)
		as_user("Administrator")

	def test_every_entry_belongs_to_a_hotel(self):
		hotel = dict(frappe.get_all("TEX Loyalty Ledger", filters={"program": self.club},
		                            fields=["name", "property"], as_list=True))
		self.assertEqual((hotel[self.here_earn], hotel[self.there_earn], hotel[self.there_adjust],
		                  hotel[self.here_adjust]), (fx.PROPERTY, self.sister, self.sister, fx.PROPERTY))

	def test_another_hotels_entries_show_no_dates_reasons_or_actors(self):
		as_user(self.here)
		[account] = crm_api.loyalty_summary(self.guest)
		entries = {e["name"]: e for e in account["entries"]}
		for name in (self.there_earn, self.there_adjust):
			e = entries[name]
			self.assertEqual((e["other_hotel"], e["booking"], e["reason"], e["available_on"], e["expires_on"]),
			                 (True, None, None, None, None), name)
			self.assertRegex(e["creation"], r"^\d{4}-\d{2}$")            # the month only
		self.assertEqual((entries[self.here_adjust]["reason"], entries[self.here_adjust]["other_hotel"]),
		                 ("birthday", False))
		rows = {r["name"]: r for r in loyalty_api.ledger(self.club, limit=200)["rows"]}
		for name in (self.there_earn, self.there_adjust):
			r = rows[name]
			self.assertEqual((r["other_hotel"], r["reason"], r["actor"], r["available_on"], r["expires_on"]),
			                 (True, None, None, None, None), name)
			self.assertRegex(r["creation"], r"^\d{4}-\d{2}$")
		self.assertEqual((rows[self.here_adjust]["reason"], rows[self.here_adjust]["actor"]), ("birthday", self.here))

	def test_desk_and_rest_show_each_hotel_its_own_entries(self):
		admin = fx.ensure_user("m3-sister-admin@example.com", ["Hotel Admin"])
		fx.ensure("TEX Access Grant", {"user": admin, "property": self.sister},
		          {"user": admin, "scope_level": "Hotel", "property": self.sister, "permission_profile": "Hotel Admin"})
		legacy = self.points(self.club, self.guest, 5, reason="a group adjustment nobody can place")
		as_user(admin)
		frappe.local.form_dict = frappe._dict({"fields": json.dumps(["name", "booking", "reason", "actor"]),
		                                       "filters": json.dumps({"program": self.club}), "limit_page_length": 100})
		try:
			listed = frappe.api.v1.document_list("TEX Loyalty Ledger")          # GET /api/resource
		finally:
			frappe.local.form_dict = frappe._dict()
		self.assertEqual({r["name"] for r in listed}, {self.there_earn, self.there_adjust})
		for name in (self.here_earn, self.here_adjust, legacy):
			with self.assertRaises(frappe.PermissionError, msg=name):
				frappe.api.v1.read_doc("TEX Loyalty Ledger", name)
			frappe.clear_messages()
		self.assertEqual(frappe.api.v1.read_doc("TEX Loyalty Ledger", self.there_adjust).get("reason"),
		                 "goodwill after a noisy room")

	def test_a_group_adjustment_names_its_hotel(self):
		sister_admin = agent("m3-both@example.com", fx.PROPERTY)
		fx.ensure("TEX Access Grant", {"user": sister_admin, "property": self.sister},
		          {"user": sister_admin, "scope_level": "Hotel", "property": self.sister,
		           "permission_profile": "Reservations Agent"})
		as_user(sister_admin)                                          # two hotels: which one must be said
		with self.assertRaises(frappe.ValidationError):
			crm_api.loyalty_adjust(self.guest, self.club, 5, "which hotel?")
		frappe.clear_messages()
		with self.assertRaises(frappe.PermissionError):
			crm_api.loyalty_adjust(self.guest, self.club, 5, "not mine", property=OTHER)
		frappe.clear_messages()
		name = crm_api.loyalty_adjust(self.guest, self.club, 5, "said", property=self.sister)["name"]
		self.assertEqual(frappe.db.get_value("TEX Loyalty Ledger", name, "property"), self.sister)


# ─── L1–L9 ───────────────────────────────────────────────────────────────


class TestPrivacyDetails(PrivacyCase):
	def test_consent_sent_as_text_to_the_crm_means_what_it_says(self):
		_b, guest = self.booked_guest("l1-crm", "l1-crm@example.com")
		as_user(self.here)
		for value, meant in (("0", 0), ("false", 0), ("no", 0), ("1", 1), ("true", 1), (0, 0)):
			crm_api.update_guest(guest, json.dumps({"tex_consent_sms": value}), consent_source="phone call")
			self.assertEqual(frappe.db.get_value("Guest", guest, "tex_consent_sms"), meant, repr(value))

	def test_no_copy_of_contact_data_is_kept_from_the_change_history(self):
		self.booked_guest("l2-hist", "l2-hist@example.com", consent_email=1, phone="+49 30 1212")
		crm.detect_abandoned(now=later())
		case = frappe.get_doc("TEX Abandoned Booking", frappe.db.get_value("TEX Abandoned Booking",
		                                                                    {"session_id": "l2-hist"}))
		after = frappe.get_doc("TEX Abandoned Booking", case.name)
		after.email, after.phone = "l2-other@example.com", "+49 30 1213"
		version = version_of(case, after)
		self.assertNotIn("l2-", frappe.db.get_value("Version", version, "data"))
		self.assertFalse(frappe.db.exists("TEX Audit Event", {"action": "version.withheld",
		                                                      "reference_doctype": "TEX Abandoned Booking",
		                                                      "reference_name": case.name}))

	def test_a_cases_links_to_a_person_are_withheld_and_an_anonymous_case_keeps_none(self):
		b, _guest = self.booked_guest("l3-anon", "l3-anon@example.com", phone="+49 30 3434")   # no consent
		self.assertTrue(b["payment"])
		crm.detect_abandoned(now=later())
		case = frappe.db.get_value("TEX Abandoned Booking", {"session_id": "l3-anon"},
		                           ["name", "quote", "stage_reached", "consent_marketing"], as_dict=True)
		self.assertEqual((case.stage_reached, case.consent_marketing, case.quote), ("payment_started", 0, None))
		frappe.db.set_value("TEX Abandoned Booking", case.name, "recovered_booking", b["booking"])
		as_user(self.here)
		listed = next(r for r in crm_api.abandoned(fx.PROPERTY) if r["name"] == case.name)
		self.assertEqual(listed["recovered_booking"], None)          # the booking would name the person
		as_user("Administrator")
		viewer = fx.ensure_user("l3-viewer@example.com", ["Hotel Admin"])
		fx.ensure("TEX Access Grant", {"user": viewer, "property": fx.PROPERTY},
		          {"user": viewer, "scope_level": "Hotel", "property": fx.PROPERTY, "permission_profile": "Viewer"})
		as_user(viewer)
		shown = frappe.client.get("TEX Abandoned Booking", case.name)
		self.assertEqual([f for f in ("session_id", "quote", "recovered_booking") if shown.get(f)], [])
		events = frappe.client.get_list("TEX Funnel Event", fields=["name", "session_id", "payload"],
		                                filters={"property": fx.PROPERTY}, limit_page_length=500)
		self.assertTrue(events)
		self.assertEqual([e for e in events if e.get("session_id") or e.get("payload")], [])
		for doctype, field in (("TEX Abandoned Booking", "session_id"), ("TEX Funnel Event", "session_id")):
			with self.assertRaises(frappe.PermissionError):
				frappe.client.get_list(doctype, fields=["name"], filters={field: "l3-anon"})
			frappe.clear_messages()

	def test_a_withdrawal_clears_the_quote_of_the_guests_cases(self):
		self.booked_guest("l3-wd", "l3-wd@example.com", consent_email=1)
		crm.detect_abandoned(now=later())
		name, guest, quote = frappe.db.get_value("TEX Abandoned Booking", {"session_id": "l3-wd"},
		                                         ["name", "guest", "quote"])
		self.assertTrue(quote)
		crm.forget_contact(guest)
		self.assertEqual(frappe.db.get_value("TEX Abandoned Booking", name, "quote"), None)

	def test_a_browser_event_names_only_what_the_site_sells(self):
		q = quote_for("l5-web")
		rt = frappe.db.get_value("Room Type", {"property": fx.PROPERTY, "room_type_code": "STD"})
		rp = frappe.db.get_value("Rate Plan", {"property": fx.PROPERTY, "code": "FLEX"})
		other_q = quote_for("l5-other")["quote_id"]                  # another visitor's quote
		as_user("Guest")
		for payload in ({"hotel": fx.PROPERTY, "room_type": rt, "board": "AI", "rate_plan": rp},
		                {"hotel": OTHER, "room_type": rt},
		                {"hotel": fx.PROPERTY, "room_type": "Somebody's Name", "board": "call me", "rate_plan": "x"}):
			public.track(site=SLUG, session_id="l5-web", event="room_view", payload=json.dumps(payload))
		public.track(site=SLUG, session_id="l5-web", event="abandoned", payload=json.dumps({
			"quotes": [q["quote_id"], other_q, "Q-0000-lena@example.com"], "hotel": fx.PROPERTY}))
		as_user("Administrator")
		payloads = [json.loads(e.payload) for e in funnel("l5-web") if e.event in ("room_view", "abandoned")]
		self.assertEqual(payloads, [{"hotel": fx.PROPERTY, "room_type": rt, "board": "AI", "rate_plan": rp}, {},
		                            {"hotel": fx.PROPERTY}, {"quotes": [q["quote_id"]], "hotel": fx.PROPERTY}])

	def test_a_phone_finds_no_profile_when_shared_or_given_by_an_anonymous_booker(self):
		shared = "+49 170 6660000"
		one, two = (frappe.get_doc({"doctype": "Guest", "first_name": n, "last_name": "Shared", "phone": shared,
		                            "tex_enterprise": self.ent}).insert(ignore_permissions=True).name
		            for n in ("Anna", "Ben"))
		as_user(self.here)
		name, _g, _a = booking.resolve_guest({"first_name": "Cleo", "last_name": "Shared", "phone": shared},
		                                     property=fx.PROPERTY, market="DE", language="en", staff=True)
		self.assertNotIn(name, (one, two))                           # a shared phone is nobody's identity
		self.assertEqual({d["name"] for d in crm_api.guest(name)["possible_duplicates"]}, {one, two})
		as_user("Administrator")
		alone = frappe.get_doc({"doctype": "Guest", "first_name": "Dana", "last_name": "Phone",
		                        "phone": "+49 170 6660001", "tex_enterprise": self.ent}).insert(
			ignore_permissions=True).name
		as_user(self.here)
		name, _g, _a = booking.resolve_guest({"first_name": "Dana", "last_name": "Phone", "phone": "+49 170 6660001"},
		                                     property=fx.PROPERTY, market="DE", language="en", staff=True)
		self.assertEqual(name, alone)                                 # staff: one profile, no e-mail: found
		_b, booked = self.booked_guest("l6-anon", "l6-anon@example.com", phone="+49 170 6660001")
		self.assertNotEqual(booked, alone)                           # an anonymous booker's phone is unverified
		as_user(self.here)
		self.assertEqual({d["name"] for d in crm_api.guest(booked)["possible_duplicates"]}, {alone})

	def test_a_withdrawal_in_desk_or_rest_is_on_the_consent_record(self):
		_b, guest = self.booked_guest("l7-desk", "l7-desk@example.com", consent_email=1)
		frappe.db.set_value("Guest", guest, "tex_consent_updated_at", "2026-01-01 00:00:00")
		consents = {"action": "guest.consent", "reference_name": guest}
		recorded = frappe.db.count("TEX Audit Event", consents)             # the booking's own
		with request_to(f"/api/resource/Guest/{guest}", "PUT"):
			frappe.client.set_value("Guest", guest, "tex_consent_email", 0)
		g = frappe.db.get_value("Guest", guest, ["tex_consent_updated_at", "tex_consent_source"], as_dict=True)
		self.assertGreater(get_datetime(g.tex_consent_updated_at), get_datetime("2026-01-02"))
		self.assertEqual(g.tex_consent_source, "Desk")
		[event] = frappe.get_all("TEX Audit Event", filters={**consents, "reason": "Desk"},
		                         fields=["new_value", "reason"])
		self.assertEqual(json.loads(event.new_value), {"tex_consent_email": False})
		as_user(self.here)                                          # the CRM records its own change once
		crm_api.update_guest(guest, json.dumps({"tex_consent_email": 1}), consent_source="guest asked")
		self.assertEqual(frappe.db.count("TEX Audit Event", consents), recorded + 2)

	def test_a_case_written_after_a_withdrawal_keeps_no_contact(self):
		_b, guest = self.booked_guest("l8-race", "l8-race@example.com", consent_email=1, phone="+49 30 8181")
		# the scheduler read the consent before the withdrawal committed, and writes the case after it
		real = frappe.db.get_value

		def stale(doctype, filters=None, fieldname="name", *args, **kwargs):
			out = real(doctype, filters, fieldname, *args, **kwargs)
			if doctype == "Guest" and filters == guest and isinstance(fieldname, list) and "tex_consent_email" in fieldname:
				frappe.db.set_value("Guest", guest, "tex_consent_email", 0, update_modified=False)
			return out

		with mock.patch.object(frappe.local.db, "get_value", side_effect=stale):
			crm.detect_abandoned(now=later())
		case = frappe.db.get_value("TEX Abandoned Booking", {"session_id": "l8-race"},
		                           ["guest", "email", "phone", "consent_marketing", "quote"])
		self.assertEqual(case, (None, None, None, 0, None))

	def test_p40_on_its_own_paths(self):
		# a funnel hash of a profile that never consented, with no case at all
		for first, email, consent in (("No", "l9-quiet@example.com", 0), ("Yes", "l9-agreed@example.com", 1)):
			frappe.get_doc({"doctype": "Guest", "first_name": first, "last_name": "Case", "email": email,
			                "tex_consent_email": consent}).insert(ignore_permissions=True)
		events = {}
		for email, session in (("l9-quiet@example.com", "l9-q"), ("l9-agreed@example.com", "l9-a"),
		                       ("l9-loose@example.com", "l9-loose")):
			events[session] = frappe.get_doc({
				"doctype": "TEX Funnel Event", "event": "guest_details", "occurred_at": now_datetime(), "site": SLUG,
				"property": fx.PROPERTY, "session_id": session, "consent_marketing": 1,
				"payload": "{}"}).insert(ignore_permissions=True).name
			frappe.db.set_value("TEX Funnel Event", events[session], "email_hash",
			                    hashlib.sha256(email.encode()).hexdigest())
		# a case with contact data but no profile (written before profiles were linked)
		loose = frappe.get_doc({"doctype": "TEX Abandoned Booking", "property": fx.PROPERTY, "session_id": "l9-loose",
		                        "stage_reached": "payment_started", "status": "Open", "email": "l9-loose@example.com",
		                        "phone": "+49 30 9", "consent_marketing": 1, "last_event_at": now_datetime()})
		loose.db_insert()
		never_ran(P40)
		migrate(P40)
		self.assertEqual(frappe.db.get_value("TEX Funnel Event", events["l9-q"], "email_hash"), None)
		self.assertTrue(frappe.db.get_value("TEX Funnel Event", events["l9-a"], "email_hash"))
		self.assertEqual(frappe.db.get_value("TEX Abandoned Booking", loose.name, ["email", "phone",
		                                                                           "consent_marketing"]),
		                 (None, None, 0))
		self.assertEqual(frappe.db.get_value("TEX Funnel Event", events["l9-loose"], "email_hash"), None)
		self.assertEqual(rerun_changes(P40), {})


# ─── p45 ─────────────────────────────────────────────────────────────────


class TestP45(PrivacyCase):
	def old_version(self, doctype: str, docname: str, changed: list) -> str:
		v = frappe.get_doc({"doctype": "Version", "ref_doctype": doctype, "docname": docname,
		                    "data": json.dumps({"changed": changed})})
		v.name = frappe.generate_hash(length=10)
		v.owner = v.modified_by = "Administrator"
		v.creation = v.modified = now_datetime()
		v.db_insert()                                             # as rows written before this change are
		return v.name

	def test_p45_indexes_history_ledger_hotels_erased_profiles_and_anonymous_cases(self):
		from kamra.tex import setup

		# the change history of a case, written before its contact fields were withheld, and the copies
		# p37 kept of it
		self.booked_guest("p45-hist", "p45-hist@example.com", consent_email=1)
		crm.detect_abandoned(now=later())
		case = frappe.db.get_value("TEX Abandoned Booking", {"session_id": "p45-hist"})
		old = self.old_version("TEX Abandoned Booking", case, [["email", "a@example.com", "p45-hist@example.com"],
		                                                       ["status", "Open", "Contacted"]])
		internals.keep("Reservation", "RES-none", "V-none", [["tex_cost_amount", "1", "2"]])   # pricing: stays
		kept = frappe.get_doc({"doctype": "TEX Audit Event", "event_time": now_datetime(),
		                       "action": "version.withheld", "actor": "Administrator", "source": "System",
		                       "reference_doctype": "TEX Abandoned Booking", "reference_name": case,
		                       "new_value": json.dumps({"version": old, "changed": [["email", "a@example.com",
		                                                                             "p45-hist@example.com"]]})})
		kept.db_insert()
		# ledger entries without their hotel, as written before
		sister = sister_hotel(self.f["group"], self.ent)
		club = self.program("P45 Club", hotel_group=self.f["group"])
		b, guest = self.booked_guest("p45-led", "p45-led@example.com")
		earn = self.points(club, guest, 100, booking=b["booking"], entry_type="Earn")
		desk = agent("p45-sister@example.com", sister)
		by_one = self.points(club, guest, 5, reason="one hotel's adjustment")
		frappe.db.set_value("TEX Loyalty Ledger", by_one, "actor", desk)
		nobody = self.points(club, guest, 5, reason="nobody's")
		frappe.db.set_value("TEX Loyalty Ledger", nobody, "actor", "Administrator")
		frappe.db.sql("UPDATE `tabTEX Loyalty Ledger` SET property = NULL WHERE name IN %(n)s",
		              {"n": (earn, by_one, nobody)})
		# a profile erased before erasure withdrew its consent
		erased = frappe.get_doc({"doctype": "Guest", "first_name": "Guest ABC123", "last_name": "",
		                         "guest_notes": "Profile anonymized on request.", "tex_consent_email": 1,
		                         "tex_consent_sms": 1, "tex_enterprise": self.ent}).insert(
			ignore_permissions=True).name
		erased_case = frappe.get_doc({"doctype": "TEX Abandoned Booking", "property": fx.PROPERTY,
		                              "session_id": "p45-erased", "stage_reached": "quote", "status": "Open",
		                              "guest": erased, "email": "p45-erased@example.com", "consent_marketing": 1,
		                              "last_event_at": now_datetime()})
		erased_case.db_insert()
		self.old_version("Guest", erased, [["email", "p45-erased@example.com", ""]])
		# an anonymous case that kept its quote
		quote = frappe.db.get_value("TEX Quote", {}, "name")
		anon = frappe.get_doc({"doctype": "TEX Abandoned Booking", "property": fx.PROPERTY, "session_id": "p45-anon",
		                       "stage_reached": "quote", "status": "Open", "consent_marketing": 0, "quote": quote,
		                       "last_event_at": now_datetime()})
		anon.db_insert()

		new = {"tex_funnel_hash_session", "tex_funnel_session_time", "tex_guest_email_ent", "tex_guest_phone_ent",
		       "tex_abandoned_session"}
		self.assertTrue(new <= {name for _dt, _f, name in setup.TEX_INDEXES})
		never_ran(P45)
		real = frappe.local.db.has_index
		with mock.patch.object(frappe.local.db, "has_index",
		                       side_effect=lambda table, index: index not in new and real(table, index)):
			seen = migrate(P45)
		self.assertEqual({name for _dt, _f, name in seen["add_index"]}, new)
		self.assertNotIn("p45-hist@", frappe.db.get_value("Version", old, "data"))
		self.assertFalse(frappe.db.exists("TEX Audit Event", kept.name))
		self.assertTrue(frappe.db.exists("TEX Audit Event", {"action": "version.withheld",
		                                                     "reference_doctype": "Reservation",
		                                                     "reference_name": "RES-none"}))
		hotel = dict(frappe.get_all("TEX Loyalty Ledger", filters={"name": ("in", [earn, by_one, nobody])},
		                            fields=["name", "property"], as_list=True))
		self.assertEqual((hotel[earn], hotel[by_one], hotel[nobody]), (fx.PROPERTY, sister, None))
		self.assertEqual(frappe.db.get_value("Guest", erased, ["tex_consent_email", "tex_consent_sms"]), (0, 0))
		self.assertEqual(frappe.db.get_value("TEX Abandoned Booking", erased_case.name, ["guest", "email"]),
		                 (None, None))
		self.assertEqual(frappe.get_all("Version", filters={"ref_doctype": "Guest", "docname": erased}), [])
		self.assertEqual(frappe.db.get_value("TEX Abandoned Booking", anon.name, "quote"), None)
		self.assertEqual(rerun_changes(P45), {})
