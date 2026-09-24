"""CRM privacy, third review of ADR-056: the guest merge and the H1 fix.

M-6 · a best-effort step (a funnel event, a booking e-mail, the channel-push trigger) that meets a lock
wait timeout loses only its own statement (``innodb_rollback_on_timeout`` off): its writes are undone to
a savepoint and the booking goes on without it; a deadlock, which ends the whole transaction, is still
raised (the booking is retried or fails). The funnel purge reads old events through an index and deletes
them by primary key in small batches, each committed, so it never holds the funnel.

H-1 · a merge reads what it moves with locking reads (the latest committed rows, not the request's
snapshot): a booking of the duplicate committed while the merge waited moves with it (and its hotel is
checked); a merge whose duplicate is gone by the time it holds the lock (merged elsewhere) is refused;
the link writers (a booking's guest, a loyalty entry) lock the profile they link to, and a redemption
reads the balance with a lock. These tests need a second connection that COMMITS what another request
would have committed meanwhile, so they run only on a disposable site (``tex_disposable_test_site``;
CI's throwaway site, ``disposable_test.sh``); elsewhere they are skipped.

M-1 · comments, mail, tasks, shares and the activity log of the duplicate move to the kept profile
(``delete_doc`` deleted or unlinked them). M-2 · an erased profile is never merged, either way (a
durable marker, ``Guest.tex_erased_at``). M-3 · the merge event names every record moved, and the
duplicate itself is kept as a Deleted Document (platform administrators only) for a retention period,
removed earlier by an erasure of the profile it went into. M-4 · the legacy endpoint checks the hotels
of every record too. M-5 · p48 marks the profiles erased before, from their durable records, and
removes their contact data from bookings, payment links and the change history. Low · a name typed in
another case is the same profile; a record of a DocType that names no hotel is merged by a platform
administrator only.
"""

import json
from contextlib import contextmanager
from unittest import mock

import frappe
from frappe.utils import add_days, now_datetime

from kamra import api as legacy_api
from kamra.channel_manager import enqueue_property_push
from kamra.tex.api import public
from kamra.tex.crm import loyalty
from kamra.tex.crm import service as crm
from kamra.tex.money import D
from kamra.tex.payments import service as pay
from kamra.tex.security.audit import audit
from kamra.tex.services import booking, txn
from kamra.tex.tests.integration import fixtures as fx
from kamra.tex.tests.integration.test_commercial_flows import GUEST, SLUG
from kamra.tex.tests.integration.test_crm_privacy import PrivacyCase, as_user, funnel, sister_hotel
from kamra.tex.tests.integration.test_crm_privacy_review import (
	ROWS,
	WAIT,
	at_least,
	own_connection,
	quote_for,
	visit,
)
from kamra.tex.tests.integration.test_patches import (
	DISPOSABLE,
	disposable_site,
	migrate,
	never_ran,
	put,
	refuse_commits,
	rerun_changes,
)

P48 = "p48_crm_privacy_third_review"
ERASED_NOTE = "Profile anonymized on request."


def lock_wait(case, seconds: int) -> None:
	"""This connection waits at most ``seconds`` for a row lock until the test ends."""
	[(wait,)] = frappe.db.sql("SELECT @@SESSION.innodb_lock_wait_timeout")
	frappe.db.sql("SET SESSION innodb_lock_wait_timeout = %s", (seconds,))
	case.addCleanup(frappe.db.sql, "SET SESSION innodb_lock_wait_timeout = %s", (int(wait),))


def plain_guest(first: str, **values) -> str:
	return frappe.get_doc({"doctype": "Guest", "first_name": first, "last_name": "Third", **values}).insert(
		ignore_permissions=True).name


# ─── M-6: best effort is best effort; the purge never holds the funnel ──


class TestBestEffortUnderLocks(PrivacyCase):
	def test_a_booking_while_the_funnel_is_held_is_booked_without_its_events(self):
		"""Another connection holds every funnel row and gap (the old purge's unindexed DELETE did, until it
		committed). Each funnel event of the visit waits 1 s, times out, loses only its own statement, and
		the booking goes on."""
		lock_wait(self, 1)
		with own_connection() as holder:
			with holder.cursor() as cur:
				cur.execute("SELECT name FROM `tabTEX Funnel Event` FOR UPDATE")
			q = quote_for("m6-held")
			as_user("Guest")
			out = public.book(site=SLUG, quote_ids=[q["quote_id"]], guest={**GUEST, "email": "m6-held@example.com"},
			                  payment_method="Pay at Hotel", session_id="m6-held", idempotency_key="idem-m6-held")
			as_user("Administrator")
		self.assertTrue(frappe.db.exists("TEX Booking", out["booking"]), "the booking itself was written")
		self.assertEqual(frappe.db.get_value("TEX Booking", out["booking"], "status"), "Confirmed")
		self.assertEqual(funnel("m6-held"), [], "no funnel event: each waited, timed out and was dropped")

	def test_a_payment_start_and_the_channel_push_tell_a_timeout_from_a_deadlock(self):
		# the gateway call meets a lock wait timeout: the start fails as a gateway failure does (the
		# request answers "could not be started"); a deadlock is raised as it is, for the retry
		account = frappe.db.get_value("TEX Payment Provider Account", {"property": fx.PROPERTY, "provider": "Mock"})
		provider = type(pay.provider_for(account))
		args = {"property": fx.PROPERTY, "amount": D("10.00"), "currency": "EUR", "provider_account": account,
		        "description": "m6", "customer": {"name": "M6"}, "method": "Card",
		        "return_url": f"http://{sorted(pay.allowed_return_hosts(fx.PROPERTY))[0]}/r"}
		with mock.patch.object(provider, "create_checkout", side_effect=frappe.QueryTimeoutError("lock")), \
				self.assertRaises(frappe.ValidationError) as ctx:
			pay.start_payment(**args, idempotency_key="m6-timeout")
		self.assertNotIsInstance(ctx.exception, frappe.QueryTimeoutError)
		with mock.patch.object(provider, "create_checkout", side_effect=frappe.QueryDeadlockError("dl")), \
				self.assertRaises(frappe.QueryDeadlockError):
			pay.start_payment(**args, idempotency_key="m6-deadlock")
		# the channel push is only queued after the commit: a timeout while asking is logged, a deadlock raised
		with mock.patch("kamra.channel_manager._connections", side_effect=frappe.QueryTimeoutError("lock")):
			enqueue_property_push(fx.PROPERTY)
		with mock.patch("kamra.channel_manager._connections", side_effect=frappe.QueryDeadlockError("dl")), \
				self.assertRaises(frappe.QueryDeadlockError):
			enqueue_property_push(fx.PROPERTY)
		# where the server ends the whole transaction on a timeout (innodb_rollback_on_timeout), a timeout
		# is a deadlock's case
		with mock.patch("kamra.channel_manager._connections", side_effect=frappe.QueryTimeoutError("lock")), \
				mock.patch.object(txn, "_rollback_on_timeout", return_value=True), \
				self.assertRaises(frappe.QueryTimeoutError):
			enqueue_property_push(fx.PROPERTY)


class TestFunnelPurge(PrivacyCase):
	def old_events(self, n: int, days: int = 200) -> list[str]:
		at = add_days(now_datetime(), -days)
		return [frappe.get_doc({"doctype": "TEX Funnel Event", "event": "search", "occurred_at": at, "site": SLUG,
		                        "property": fx.PROPERTY, "session_id": f"m6-old-{i}", "payload": "{}"}).insert(
			ignore_permissions=True).name for i in range(n)]

	def test_the_purge_reads_through_an_index_and_deletes_by_primary_key(self):
		at_least("TEX Funnel Event", ROWS, ("event", "occurred_at", "property", "session_id", "consent_marketing",
		                                    "payload"), lambda i: ("search", now_datetime(), fx.PROPERTY, f"m6-fill-{i}",
		                                                           0, "{}"))
		cutoff = add_days(now_datetime(), -180)
		for sql, params, index in ((crm.PURGE_OLD, {"cutoff": cutoff, "n": crm.PURGE_BATCH}, "tex_funnel_time_session"),
		                           (crm.PURGE_EVENTS, {"names": ("none",)}, "PRIMARY")):
			self.assertNotIn("IFNULL", sql.upper())
			[plan] = frappe.db.sql(f"EXPLAIN {sql}", params, as_dict=True)
			self.assertEqual((plan.key, plan.type != "ALL"), (index, True), (sql, plan))

	def test_the_purge_goes_in_small_batches_each_committed(self):
		old = self.old_events(5)
		recent = self.old_events(1, days=10)
		commits = []
		with mock.patch.object(crm, "PURGE_BATCH", 2), mock.patch.object(crm, "_commit",
		                                                                 side_effect=lambda: commits.append(1)):
			purged = crm.purge_funnel()
		self.assertGreaterEqual(purged, 5)
		self.assertEqual([n for n in old if frappe.db.exists("TEX Funnel Event", n)], [])
		self.assertTrue(frappe.db.exists("TEX Funnel Event", recent[0]))
		self.assertGreaterEqual(len(commits), 3, "one commit per batch of 2")

	def test_new_events_never_wait_for_a_purge(self):
		self.old_events(3)
		with mock.patch.object(crm, "_commit"):
			crm.purge_funnel()                                    # not committed: its locks are held
		with own_connection() as visitor:
			visit(visitor, "m6-during-purge", "m6-purge@example.com")   # waits at most WAIT s, or fails


# ─── H-1: the merge reads what it moves with locking reads ───────────────


@contextmanager
def committing():
	"""A second connection that commits, as another request does: only on a disposable site."""
	import pymysql

	assert disposable_site(), "commits only on a disposable site"
	c = frappe.conf
	conn = pymysql.connect(host=c.db_host or "127.0.0.1", port=int(c.db_port or 3306), user=c.db_user or c.db_name,
	                       password=c.db_password, database=c.db_name, charset="utf8mb4", autocommit=False)
	try:
		with conn.cursor() as cur:
			cur.execute("SET SESSION innodb_lock_wait_timeout = %s", (WAIT,))
		yield conn
	finally:
		conn.rollback()
		conn.close()


def run(conn, sql: str, *params) -> None:
	with conn.cursor() as cur:
		cur.execute(sql, params)


def row(conn, doctype: str, name: str, **values) -> None:
	cols = ["name", "creation", "modified", "owner", "modified_by", *values]
	run(conn, f"INSERT INTO `tab{doctype}` ({', '.join(f'`{c}`' for c in cols)}) VALUES "
	          f"(%s, NOW(6), NOW(6), 'Administrator', 'Administrator'{', %s' * len(values)})", name, *values.values())


PREFIX = "M3C-"
# guests the tests need in every snapshot: committed before any test of the class reads
CLASS_GUESTS = {f"{PREFIX}{k}": f"{k.lower()}@m3c.example.com"
                for k in ("A-S", "A-T", "A2-S", "A2-T", "C-S", "C-T", "C-U", "D-G", "D2-G", "W-G", "V-G")}


class TestMergeUnderConcurrency(PrivacyCase):
	"""What other requests commit while a merge (or a redemption) runs: rows committed after this
	transaction's snapshot, which its plain reads do not see and its locking reads do."""

	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		if not disposable_site():
			return
		with committing() as other:
			for name, email in CLASS_GUESTS.items():
				row(other, "Guest", name, first_name=name, last_name="M3C", full_name=f"{name} M3C", email=email,
				    tex_enterprise=fx.ENTERPRISE, tex_language="en", tex_market="DE")
			row(other, "TEX Loyalty Ledger", f"{PREFIX}LED-C", program=f"{PREFIX}PROG", guest=f"{PREFIX}C-S",
			    entry_type="Earn", points=10, status="Available", property=fx.PROPERTY)
			other.commit()

	@classmethod
	def tearDownClass(cls):
		if disposable_site():
			with committing() as other:
				for doctype in ("Guest", "TEX Booking", "TEX Loyalty Ledger"):
					run(other, f"DELETE FROM `tab{doctype}` WHERE name LIKE %s", f"{PREFIX}%")
				other.commit()
		super().tearDownClass()

	def setUp(self):
		if not disposable_site():
			self.skipTest(f"commits on a second connection: runs only on a site with {DISPOSABLE} set")
		super().setUp()
		lock_wait(self, WAIT)

	def commit_meanwhile(self, *rows_) -> None:
		with committing() as other:
			for doctype, name, values in rows_:
				row(other, doctype, name, **values)
			other.commit()

	def test_a_booking_committed_during_the_merge_moves_with_it(self):
		s, t = f"{PREFIX}A-S", f"{PREFIX}A-T"
		self.assertTrue(frappe.db.exists("Guest", s))                 # in this transaction's snapshot
		self.commit_meanwhile(("TEX Booking", f"{PREFIX}BKG-A", {"property": fx.PROPERTY, "status": "Confirmed",
		                                                           "booker_guest": s, "currency": "EUR"}))
		as_user("Administrator")
		out = crm.merge_guests(s, t)
		[[booker]] = frappe.db.sql("SELECT booker_guest FROM `tabTEX Booking` WHERE name = %s FOR UPDATE",
		                           f"{PREFIX}BKG-A")
		self.assertEqual(booker, t, "the booking committed meanwhile points at the profile that stays")
		self.assertIn(f"{PREFIX}BKG-A", out["records"]["TEX Booking"])

	def test_the_hotel_of_a_booking_committed_meanwhile_is_checked(self):
		s, t = f"{PREFIX}A2-S", f"{PREFIX}A2-T"
		sister = sister_hotel(self.f["group"], self.ent)
		self.commit_meanwhile(("TEX Booking", f"{PREFIX}BKG-A2", {"property": sister, "status": "Confirmed",
		                                                            "booker_guest": s, "currency": "EUR"}))
		as_user(self.here)                                          # edits guests here, not at the sister hotel
		with self.assertRaises(frappe.PermissionError):
			crm.merge_guests(s, t)

	def test_a_duplicate_merged_elsewhere_meanwhile_is_not_merged_again(self):
		s, t, u = f"{PREFIX}C-S", f"{PREFIX}C-T", f"{PREFIX}C-U"
		self.assertTrue(frappe.db.exists("Guest", s))
		with committing() as other:                                 # another merge of s, into t, commits first
			run(other, "UPDATE `tabTEX Loyalty Ledger` SET guest = %s WHERE guest = %s", t, s)
			run(other, "DELETE FROM `tabGuest` WHERE name = %s", s)
			other.commit()
		as_user("Administrator")
		with self.assertRaises(frappe.DoesNotExistError):
			crm.merge_guests(s, u)
		[[owner]] = frappe.db.sql("SELECT guest FROM `tabTEX Loyalty Ledger` WHERE name = %s FOR UPDATE",
		                          f"{PREFIX}LED-C")
		self.assertEqual(owner, t, "the entry stays with the profile the first merge moved it to")

	def redeemable(self, guest: str) -> str:
		frappe.get_doc({"doctype": "TEX Loyalty Program", "program_name": "M3C Club", "property": fx.PROPERTY,
		                "enabled": 1, "currency": "EUR", "point_value": "0.1", "min_redeem_points": 1,
		                "max_redeem_percent": 100}).insert(ignore_permissions=True)
		b = frappe.get_doc({"doctype": "TEX Booking", "property": fx.PROPERTY, "status": "Confirmed",
		                    "booker_guest": guest, "currency": "EUR", "total_amount": 500, "balance_amount": 500}
		                   ).insert(ignore_permissions=True).name
		return b

	def test_a_redemption_sees_points_spent_meanwhile(self):
		guest = f"{PREFIX}D-G"
		b = self.redeemable(guest)
		program = loyalty.program_for(fx.PROPERTY)
		frappe.get_doc({"doctype": "TEX Loyalty Ledger", "program": program, "guest": guest, "entry_type": "Earn",
		                "points": 100, "status": "Available", "reason": "m3c"}).insert(ignore_permissions=True)
		self.assertEqual(loyalty.balances(guest, program)["available"], 100)
		# another redemption of 80 points commits while this one runs
		self.commit_meanwhile(("TEX Loyalty Ledger", f"{PREFIX}LED-D", {
			"program": program, "guest": guest, "entry_type": "Burn", "points": -80, "status": "Used",
			"property": fx.PROPERTY}))
		as_user("Administrator")
		with self.assertRaises(frappe.ValidationError) as ctx:
			loyalty.redeem(guest, b, 50, idempotency_key="m3c-d")
		self.assertIn("Not enough points", str(ctx.exception))

	def test_a_redemption_for_a_profile_gone_meanwhile_is_refused(self):
		guest = f"{PREFIX}D2-G"
		b = self.redeemable(guest)
		with committing() as other:
			run(other, "DELETE FROM `tabGuest` WHERE name = %s", guest)
			other.commit()
		as_user("Administrator")
		with self.assertRaises(frappe.DoesNotExistError):
			loyalty.redeem(guest, b, 50, idempotency_key="m3c-d2")

	def test_link_writers_lock_the_profile_they_link_to(self):
		guest = f"{PREFIX}W-G"
		program = frappe.get_doc({"doctype": "TEX Loyalty Program", "program_name": "M3C W", "property": fx.PROPERTY,
		                          "enabled": 1, "currency": "EUR", "point_value": "0.1"}).insert(
			ignore_permissions=True).name
		with own_connection() as merging:                           # a merge holds the profile
			run(merging, "SELECT name FROM `tabGuest` WHERE name = %s FOR UPDATE", guest)
			with self.assertRaises(frappe.QueryTimeoutError):
				booking.resolve_guest({"first_name": "W", "last_name": "M3C", "email": CLASS_GUESTS[guest]},
				                      property=fx.PROPERTY, market="DE", language="en", staff=False)
			with self.assertRaises(frappe.QueryTimeoutError):
				frappe.get_doc({"doctype": "TEX Loyalty Ledger", "program": program, "guest": guest,
				                "entry_type": "Adjust", "points": 5, "status": "Available", "reason": "w"}).insert(
					ignore_permissions=True)

	def test_a_booking_for_a_profile_merged_meanwhile_finds_no_ghost(self):
		guest = f"{PREFIX}V-G"
		self.assertTrue(frappe.db.exists("Guest", guest))
		with committing() as other:                                 # merged into another profile, committed
			run(other, "DELETE FROM `tabGuest` WHERE name = %s", guest)
			other.commit()
		name, _granted, _asked = booking.resolve_guest({"first_name": "V", "last_name": "M3C",
		                                                 "email": CLASS_GUESTS[guest]},
		                                                property=fx.PROPERTY, market="DE", language="en", staff=False)
		self.assertNotEqual(name, guest)
		self.assertTrue(frappe.db.sql("SELECT name FROM `tabGuest` WHERE name = %s FOR UPDATE", name))


# ─── M-1 … M-4 and Low: what a merge moves, refuses and records ──────────


class TestMergeRecords(PrivacyCase):
	def test_every_link_to_a_profile_is_indexed(self):
		"""The merge's locking reads lock a profile's rows only when an index starts with the link (else a
		locking read holds the whole table until the merge ends): a new Link to Guest needs its index in
		``setup.TEX_INDEXES``."""
		for parent, field in crm._guest_links():
			first = frappe.db.sql(f"SHOW INDEX FROM `tab{parent}` WHERE Seq_in_index = 1 AND Column_name = %s", field)
			self.assertTrue(first, f"{parent}.{field} has no index that starts with it")

	def pair(self, tag: str) -> tuple[str, str, dict]:
		kept_b, kept = self.booked_guest(f"{tag}-a", f"{tag}-a@example.com", phone="+49 30 3330")
		dup_b, dup = self.booked_guest(f"{tag}-b", f"{tag}-b@example.com", phone="+49 30 3331")
		return kept, dup, {"kept_booking": kept_b["booking"], "dup_booking": dup_b["booking"]}

	def test_comments_mail_tasks_shares_and_activity_move_with_the_profile(self):
		kept, dup, _rec = self.pair("m1-dyn")
		user = fx.ensure_user("m1-dyn-share@example.com", ["Call Center Agent"])
		made = {
			"Comment": frappe.get_doc({"doctype": "Comment", "comment_type": "Comment", "reference_doctype": "Guest",
			                           "reference_name": dup, "content": "prefers a quiet room"}).insert(
				ignore_permissions=True).name,
			"ToDo": frappe.get_doc({"doctype": "ToDo", "description": "call back", "reference_type": "Guest",
			                        "reference_name": dup, "allocated_to": "Administrator"}).insert(
				ignore_permissions=True).name,
			"Communication": frappe.get_doc({"doctype": "Communication", "communication_type": "Communication",
			                                 "communication_medium": "Phone", "sent_or_received": "Received",
			                                 "subject": "called", "content": "asked for a late check-out",
			                                 "reference_doctype": "Guest", "reference_name": dup}).insert(
				ignore_permissions=True).name,
			"Activity Log": frappe.get_doc({"doctype": "Activity Log", "subject": "viewed", "reference_doctype": "Guest",
			                                "reference_name": dup}).insert(ignore_permissions=True).name,
			"DocShare": frappe.get_doc({"doctype": "DocShare", "user": user, "share_doctype": "Guest", "share_name": dup,
			                            "read": 1}).insert(ignore_permissions=True).name,
		}
		link = frappe.get_doc("Communication", made["Communication"])
		link.add_link("Guest", dup)
		link.save(ignore_permissions=True)
		as_user("Administrator")
		out = crm.merge_guests(dup, kept)
		where = {"Comment": ("reference_doctype", "reference_name"), "ToDo": ("reference_type", "reference_name"),
		         "Communication": ("reference_doctype", "reference_name"),
		         "Activity Log": ("reference_doctype", "reference_name"), "DocShare": ("share_doctype", "share_name")}
		for doctype, name in made.items():
			self.assertTrue(frappe.db.exists(doctype, name), f"{doctype} was deleted with the duplicate")
			self.assertEqual(frappe.db.get_value(doctype, name, list(where[doctype])), ("Guest", kept), doctype)
			self.assertIn(name, out["records"].get(doctype, []), doctype)
		self.assertEqual(set(frappe.get_all("Communication Link", filters={"parent": made["Communication"],
		                                                                  "link_doctype": "Guest"}, pluck="link_name")),
		                 {kept})

	def test_an_erased_profile_is_never_merged_either_way(self):
		kept, dup, _rec = self.pair("m2-erased")
		as_user("Administrator")
		legacy_api.anonymize_guest(dup)
		self.assertTrue(frappe.db.get_value("Guest", dup, "tex_erased_at"))
		for source, target in ((dup, kept), (kept, dup)):
			with self.assertRaises(frappe.ValidationError):
				crm.merge_guests(source, target)
		self.assertTrue(frappe.db.exists("Guest", dup))
		self.assertEqual(frappe.db.count("Reservation", {"guest": dup}), 1, "the erased stays stay anonymous")

	def test_a_merge_names_what_it_moved_and_keeps_the_duplicate_for_a_while(self):
		kept, dup, rec = self.pair("m3-rec")
		stay = frappe.db.get_value("Reservation", {"guest": dup})
		as_user("Administrator")
		out = crm.merge_guests(dup, kept)
		[event] = frappe.get_all("TEX Audit Event", filters={"action": "guest.merge", "reference_name": kept},
		                         fields=["new_value"])
		records = json.loads(event.new_value)["records"]
		self.assertEqual(records, out["records"])
		self.assertIn(rec["dup_booking"], records["TEX Booking"])
		self.assertIn(stay, records["Reservation"])
		self.assertNotIn("@", event.new_value)                          # names, never contact data
		copy = frappe.db.get_value("Deleted Document", {"deleted_doctype": "Guest", "deleted_name": dup}, "name")
		self.assertTrue(copy, "the duplicate is kept as a Deleted Document")
		self.assertEqual(json.loads(event.new_value)["copy"], copy)
		self.assertIn("m3-rec-b@example.com", frappe.db.get_value("Deleted Document", copy, "data"))
		# platform administrators only
		as_user(self.here)
		with self.assertRaises(frappe.PermissionError):
			frappe.client.get("Deleted Document", copy)
		as_user("Administrator")
		# kept for crm.MERGE_COPY_DAYS, then removed by the daily job
		self.assertEqual(crm.purge_merge_copies(), 0)
		with mock.patch.object(crm, "now_datetime", return_value=add_days(now_datetime(), crm.MERGE_COPY_DAYS + 1)):
			self.assertGreaterEqual(crm.purge_merge_copies(), 1)
		self.assertFalse(frappe.db.exists("Deleted Document", copy))

	def test_an_erasure_removes_the_copies_of_the_profiles_merged_into_it(self):
		kept, dup, _rec = self.pair("m3-erase")
		as_user("Administrator")
		crm.merge_guests(dup, kept)
		self.assertTrue(frappe.db.exists("Deleted Document", {"deleted_doctype": "Guest", "deleted_name": dup}))
		legacy_api.anonymize_guest(kept)
		self.assertFalse(frappe.db.exists("Deleted Document", {"deleted_doctype": "Guest", "deleted_name": dup}))

	def test_the_legacy_merge_checks_the_hotel_of_every_record(self):
		kept, dup, _rec = self.pair("m4-legacy")
		frappe.db.set_single_value("TEX Settings", "show_legacy_pms", 1)       # a site that runs the PMS
		admin = fx.ensure_user("m4-legacy-admin@example.com", ["Hotel Admin"])
		fx.ensure("TEX Access Grant", {"user": admin, "property": fx.PROPERTY},
		          {"user": admin, "scope_level": "Hotel", "property": fx.PROPERTY, "permission_profile": "Hotel Admin"})
		sister = sister_hotel(self.f["group"], self.ent)
		elsewhere = frappe.get_doc({"doctype": "TEX Booking", "property": sister, "status": "Confirmed",
		                            "booker_guest": dup, "currency": "EUR"}).insert(ignore_permissions=True).name
		as_user(admin)                            # every stay of both is at their hotel: the PMS guard passes
		with self.assertRaises(frappe.PermissionError):
			legacy_api.merge_guests(source=dup, target=kept)
		as_user("Administrator")
		self.assertEqual(frappe.db.get_value("TEX Booking", elsewhere, "booker_guest"), dup)
		frappe.db.delete("TEX Booking", elsewhere)
		as_user(admin)                            # every record at their hotel: merged
		legacy_api.merge_guests(source=dup, target=kept)
		as_user("Administrator")
		self.assertFalse(frappe.db.exists("Guest", dup))

	def test_a_name_in_another_case_is_the_same_profile(self):
		_kept, dup, _rec = self.pair("low-case")
		as_user("Administrator")
		for other in (dup.lower(), f" {dup} "):
			with self.assertRaises(frappe.ValidationError):
				crm.merge_guests(other, dup)
			self.assertTrue(frappe.db.exists("Guest", dup), other)

	def test_a_record_that_names_no_hotel_is_merged_by_a_platform_administrator_only(self):
		kept, dup, _rec = self.pair("low-nohotel")
		note = frappe.get_doc({"doctype": "ToDo", "description": dup, "allocated_to": "Administrator"}).insert(
			ignore_permissions=True).name
		links = crm._guest_links()
		with mock.patch.object(crm, "_guest_links", return_value=[*links, ("ToDo", "description")]):
			as_user(self.here)
			with self.assertRaises(frappe.PermissionError):
				crm.merge_guests(dup, kept)
			as_user("Administrator")
			crm.merge_guests(dup, kept)
		self.assertEqual(frappe.db.get_value("ToDo", note, "description"), kept)


# ─── M-5: p48 ────────────────────────────────────────────────────────────


class TestP48(PrivacyCase):
	def setUp(self):
		refuse_commits(self)                     # before anything is written (review of G-76, C1)
		super().setUp()

	def old_version(self, doctype: str, docname: str, changed: list) -> str:
		return put("Version", ref_doctype=doctype, docname=docname, data=json.dumps({"changed": changed}))

	def test_p48_marks_earlier_erasures_and_removes_what_they_left(self):
		from kamra.tex import setup

		# erased by the old endpoint: the profile blanked, nothing else (no marker, contact data left)
		b, old = self.booked_guest("p48-old", "p48-old@example.com", phone="+49 30 4848")
		link = put("TEX Payment Link", property=fx.PROPERTY, amount=10, currency="EUR", booking=b["booking"],
		           guest_name="Lena Kraus", guest_email="p48-old@example.com", status="Active")
		frappe.db.set_value("Guest", old, {"first_name": "Guest OLD48A", "last_name": "", "full_name": "Guest OLD48A",
		                                   "email": "", "phone": "", "guest_notes": ERASED_NOTE, "date_of_birth": "1980-01-02",
		                                   "tex_consent_email": 0})
		for doctype, name, changed in (("Guest", old, [["email", "p48-old@example.com", ""]]),
		                               ("TEX Booking", b["booking"], [["booker_email", "a@example.com", "p48-old@example.com"]]),
		                               ("TEX Payment Link", link, [["guest_email", None, "p48-old@example.com"]])):
			self.old_version(doctype, name, changed)
		put("Agent Action Log", action_type="anonymize_guest", reference_doctype="Guest", reference_name=old,
		    actor="Administrator", approval_status="Executed", executed_at=now_datetime())
		# erased by the second review's code: scrubbed, but no marker yet
		second = plain_guest("Guest SEC48B", guest_notes=ERASED_NOTE)
		audit("guest.erase", reference_doctype="Guest", reference_name=second, new={"bookings": 0})
		# a live profile whose notes say it (a merge could have copied them): no durable record, never marked
		live = plain_guest("Lena", email="p48-live@example.com", guest_notes=ERASED_NOTE)

		new = {"tex_funnel_time_session", "tex_ledger_guest_program", "tex_booking_guest_prop"}
		self.assertTrue(new <= {name for _dt, _f, name in setup.TEX_INDEXES})
		never_ran(P48)
		real = frappe.local.db.has_index
		with mock.patch.object(frappe.local.db, "has_index",
		                       side_effect=lambda table, index: index not in new and real(table, index)):
			seen = migrate(P48)
		self.assertTrue(new <= {name for _dt, _f, name in seen["add_index"]})
		self.assertTrue(frappe.db.get_value("Guest", old, "tex_erased_at"))
		self.assertTrue(frappe.db.get_value("Guest", second, "tex_erased_at"))
		self.assertFalse(frappe.db.get_value("Guest", live, "tex_erased_at"))
		self.assertEqual(frappe.db.get_value("Guest", live, "email"), "p48-live@example.com")
		self.assertEqual(frappe.db.get_value("Guest", old, "date_of_birth"), None)
		self.assertEqual(frappe.db.get_value("TEX Booking", b["booking"], ["booker_name", "booker_email", "booker_phone"]),
		                 ("Guest OLD48A", None, None))
		self.assertEqual(frappe.db.get_value("TEX Payment Link", link, ["guest_name", "guest_email"]),
		                 ("Guest OLD48A", None))
		self.assertEqual(frappe.get_all("Version", filters={"ref_doctype": "Guest", "docname": old}), [])
		history = json.dumps(frappe.get_all("Version", filters={"ref_doctype": ("in", ["TEX Booking", "TEX Payment Link"]),
		                                                         "docname": ("in", [b["booking"], link])},
		                                    pluck="data"))
		self.assertNotIn("p48-old@", history)
		self.assertIn("1 profile(s) with the erasure note but no record of an erasure",
		              " ".join(str(c) for c in seen["print"].call_args_list))
		self.assertEqual(rerun_changes(P48), {})
