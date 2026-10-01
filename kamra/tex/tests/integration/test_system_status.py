"""System status, alerts and e-mail delivery status (ADR-047).

- ``kamra.tex.api.system.status`` (``system.monitor``): hotel-scoped checks show only the
  hotels where the user holds the capability; platform checks (scheduler, workers,
  encryption key, database snapshot isolation, the whole e-mail queue) only for platform
  administrators; no secret, token, guest data or stack trace in the payload.
- ``kamra.tex.ops.snapshot_isolation`` (ADR-063): every web request and background job runs
  with MariaDB ``innodb_snapshot_isolation`` OFF; the status page fails while it is ON.
- ``kamra.tex.api.system.ping`` (guest): ``ok`` and reachability booleans, nothing else.
- ``kamra.tex.ops.alerts.evaluate`` (every 15 minutes): one notice when a check gets worse
  and one when it recovers, never on every run.
- ``kamra.tex.services.mail_status.sync`` (every 5 minutes): a TEX Communication follows its
  Email Queue row (Sent / Error); "resend" reports what happened (queued), never "sent".
"""

import json
import threading
from datetime import datetime, time, timedelta
from unittest import mock

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import add_to_date, getdate, now_datetime, nowdate

from kamra.tex.payments import service as pay
from kamra.tex.security import scope
from kamra.tex.tests.integration import fixtures as fx
from kamra.tex.tests.integration.test_commercial_flows import SLUG, guest_books, setup_site_and_payments
from kamra.tex.tests.integration.test_critical_journey import TexTestCase
from kamra.tex.tests.integration.test_crm_segments import OTHER, agent, other_tenant
from kamra.tex.tests.integration.test_migrations_notify import ensure_test_outbox

PROFILE = "TEX Monitor Test"
RECIPIENT = "tex-ops-alerts@example.com"


def system_api():
	from kamra.tex.api import system

	return system


def monitor(email: str, prop: str) -> str:
	"""A user who holds only ``system.monitor``, at one hotel."""
	frappe.set_user("Administrator")  # nosemgrep: frappe-setuser -- grants are set up by the admin
	if not frappe.db.exists("TEX Permission Profile", PROFILE):
		frappe.get_doc({"doctype": "TEX Permission Profile", "profile_name": PROFILE,
		                "capabilities": [{"capability": "system.monitor"}]}).insert(ignore_permissions=True)
	user = fx.ensure_user(email, ["Call Center Agent"])
	fx.ensure("TEX Access Grant", {"user": user, "property": prop},
	          {"user": user, "scope_level": "Hotel", "property": prop, "permission_profile": PROFILE})
	scope.clear_cache()
	return user


def pms_connection(prop: str, label: str = "PMS log", **extra) -> str:
	return frappe.get_doc({"doctype": "TEX Integration Connection", "label": label, "property": prop,
	                       "category": "PMS", "adapter": "log", "environment": "Sandbox", "enabled": 1, **extra}
	                      ).insert(ignore_permissions=True).name


def outbox_row(conn: str, prop: str, status: str, *, minutes_ago: int = 0) -> str:
	name = frappe.get_doc({"doctype": "TEX Integration Outbox", "kind": "Reservation", "connection": conn,
	                       "property": prop, "event": "reservation.created", "status": status, "attempts": 8,
	                       "next_attempt_at": now_datetime(), "idempotency_key": frappe.generate_hash(length=20),
	                       "payload": "{}"}).insert(ignore_permissions=True).name
	if minutes_ago:
		frappe.db.set_value("TEX Integration Outbox", name, "creation", add_to_date(now_datetime(), minutes=-minutes_ago),
		                    update_modified=False)
	return name


def quiet_outbox(prop: str | None = None) -> None:
	"""Rows other runs left in the shared test database must not decide these checks (rolled
	back with the test)."""
	filters = {"status": ("in", ["Dead", "Pending", "Failed"]), "kind": "Reservation"}
	if prop:
		filters["property"] = prop
	for name in frappe.get_all("TEX Integration Outbox", filters=filters, pluck="name"):
		frappe.db.set_value("TEX Integration Outbox", name, "status", "Sent", update_modified=False)


def check(result: dict, key: str) -> dict | None:
	return next((c for c in result["checks"] if c["key"] == key), None)


PLATFORM_KEYS = {"scheduler", "scheduler.jobs", "scheduler.errors", "workers", "encryption_key",
                 "db.snapshot_isolation", "mail.queue"}


class TestSystemStatusAccess(TexTestCase):
	def setUp(self):
		super().setUp()
		other_tenant()
		self.watcher = monitor("ops-watch@example.com", fx.PROPERTY)
		self.desk = agent("ops-desk@example.com", fx.PROPERTY)          # no system.monitor
		frappe.set_user("Administrator")  # nosemgrep: frappe-setuser -- fixtures

	def test_a_user_without_the_capability_is_refused(self):
		frappe.set_user(self.desk)  # nosemgrep: frappe-setuser -- reservations agent
		with self.assertRaises(frappe.PermissionError):
			system_api().status()
		with self.assertRaises(frappe.PermissionError):
			system_api().status(property=fx.PROPERTY)
		frappe.set_user(self.watcher)  # nosemgrep: frappe-setuser -- monitor of one hotel
		with self.assertRaises(frappe.PermissionError):
			system_api().status(property=OTHER)                        # not one of their hotels
		frappe.set_user("Guest")  # nosemgrep: frappe-setuser -- anonymous
		with self.assertRaises((frappe.PermissionError, frappe.AuthenticationError)):
			system_api().status()

	def test_a_hotel_user_sees_only_their_hotels(self):
		here, there = pms_connection(fx.PROPERTY), pms_connection(OTHER)
		quiet_outbox()
		outbox_row(here, fx.PROPERTY, "Dead")
		outbox_row(there, OTHER, "Dead")
		outbox_row(there, OTHER, "Dead")
		out = system_api().status()                                      # platform administrator
		self.assertEqual(check(out, "outbox.pms")["count"], 3)
		self.assertTrue(PLATFORM_KEYS <= {c["key"] for c in out["checks"]})
		frappe.set_user(self.watcher)  # nosemgrep: frappe-setuser -- monitor of one hotel
		out = system_api().status()
		pms = check(out, "outbox.pms")
		self.assertEqual((pms["status"], pms["count"], pms["properties"]), ("fail", 1, [fx.PROPERTY]))
		self.assertFalse(PLATFORM_KEYS & {c["key"] for c in out["checks"]})    # platform checks are hidden
		self.assertNotIn(OTHER, json.dumps(out, default=str))
		one = system_api().status(property=fx.PROPERTY)
		self.assertEqual({c["key"] for c in one["checks"]}, {c["key"] for c in out["checks"]})
		self.assertEqual(check(one, "outbox.pms")["count"], 1)

	def test_a_dead_outbox_job_turns_the_check_to_fail(self):
		conn = pms_connection(fx.PROPERTY)
		quiet_outbox(fx.PROPERTY)
		pms = check(system_api().status(property=fx.PROPERTY), "outbox.pms")
		self.assertEqual((pms["status"], pms["count"]), ("ok", 0))
		outbox_row(conn, fx.PROPERTY, "Pending", minutes_ago=45)         # late, not dead: a warning
		pms = check(system_api().status(property=fx.PROPERTY), "outbox.pms")
		self.assertEqual(pms["status"], "warn")
		outbox_row(conn, fx.PROPERTY, "Dead")
		out = system_api().status(property=fx.PROPERTY)
		pms = check(out, "outbox.pms")
		self.assertEqual((pms["status"], pms["count"]), ("fail", 1))
		self.assertEqual(out["overall"], "fail")                         # the worst check decides

	def test_an_old_fx_rate_warns_and_a_stale_one_fails(self):
		"""The warning counts business days (more than ``FX_WARN_BUSINESS_DAYS``), the failure calendar
		days (the policy's ``max_age_days``), so what a rate of a given age reads as depends on the
		weekday: the site's "now" is pinned to each day of a week, Monday to Sunday, and every day says
		the same four things (no rate, a stale rate, an old rate, a recent one)."""
		fx.ensure_currency("XTS", "¤")
		policy = fx.ensure_live("TEX FX Policy", {"property": fx.PROPERTY, "from_currency": "EUR", "to_currency": "XTS"},
		                        {"property": fx.PROPERTY, "from_currency": "EUR", "to_currency": "XTS",
		                         "mode": "PROVIDER", "provider": "ECB", "rate_type": "REFERENCE", "max_age_days": 7})
		self.assertEqual(frappe.db.get_value("TEX FX Policy", policy, "max_age_days"), 7)
		# weekday → (the oldest rate that is not yet old, the newest that is), in calendar days: the business
		# days after the rate's date up to and including today, 2 and 3 (worked out by hand, not with
		# checks.business_days)
		ages = {0: (4, 5), 1: (4, 5), 2: (2, 3), 3: (2, 3), 4: (2, 3), 5: (3, 4), 6: (4, 5)}
		first = getdate(nowdate()) + timedelta(days=7 - getdate(nowdate()).weekday())    # next Monday
		week = [first + timedelta(days=i) for i in range(7)]
		self.assertEqual([d.weekday() for d in week], list(range(7)))

		for today in week:
			pinned = datetime.combine(today, time(12, 0))
			quiet, old = ages[today.weekday()]
			with self.subTest(today=str(today), weekday=today.strftime("%A")), \
					mock.patch("kamra.tex.api.system.now_datetime", return_value=pinned):
				frappe.db.savepoint("fx_week")                                  # each day starts without a rate

				def rate(days_ago: int, pinned=pinned):
					frappe.get_doc({"doctype": "TEX FX Rate", "provider": "ECB", "base_currency": "EUR",
					                "quote_currency": "XTS", "rate_type": "REFERENCE", "rate": 1.25,
					                "rate_date": (pinned - timedelta(days=days_ago)).date(),
					                "fetched_at": pinned - timedelta(days=days_ago)}).insert(ignore_permissions=True)

				def issue():
					c = check(system_api().status(property=fx.PROPERTY), "fx.rates")
					found = next((i for i in c["issues"] if i["params"].get("pair") == "EUR/XTS"), None)
					return found and (found["status"], found["reason"], found["params"].get("days"),
					                  found["params"].get("max_days"))

				try:
					self.assertEqual(issue(), ("fail", "fx_missing", None, None))    # no rate at all: pricing refuses
					rate(8)
					self.assertEqual(issue(), ("fail", "fx_stale", 8, 7))           # older than the policy's 7 days
					rate(7)
					self.assertEqual(issue(), ("warn", "fx_old", 7, 7))             # the policy's age itself: old only
					rate(old)
					self.assertEqual(issue(), ("warn", "fx_old", old, 7))           # 3 business days: old
					rate(quiet)
					self.assertIsNone(issue())                                     # 2 business days: not yet
					rate(0)
					self.assertIsNone(issue())                                     # today's rate: nothing to say
				finally:
					frappe.db.rollback(save_point="fx_week")

	def test_a_manual_rate_turns_a_stale_provider_into_a_warning_and_never_shows_its_value(self):
		"""O-12 (2D-2): a pair no provider rate serves, bridged for every hotel by a dated manual rate, is
		WARN ``fx_bridged`` (pair, provider and ages only); a rate entered for another hotel does not
		bridge this one."""
		fx.ensure_currency("XTS", "¤")
		fx.ensure_live("TEX FX Policy", {"property": fx.PROPERTY, "from_currency": "EUR", "to_currency": "XTS"},
		               {"property": fx.PROPERTY, "from_currency": "EUR", "to_currency": "XTS",
		                "mode": "PROVIDER", "provider": "ECB", "rate_type": "REFERENCE", "max_age_days": 4})
		today = getdate(nowdate())

		def issue():
			c = check(system_api().status(property=fx.PROPERTY), "fx.rates")
			return next((i for i in c["issues"] if i["params"].get("pair") == "EUR/XTS"), None)

		def manual(property, rate="1.337"):
			frappe.get_doc({"doctype": "TEX FX Rate", "provider": "MANUAL", "base_currency": "EUR",
			                "quote_currency": "XTS", "rate_type": "REFERENCE", "rate": rate,
			                "rate_date": today - timedelta(days=1), "fetched_at": now_datetime(),
			                "property": property}).insert(ignore_permissions=True)

		self.assertEqual(issue()["reason"], "fx_missing")
		other = fx.ensure("Property", {"property_name": "FX Status Other"},
		                  {"doctype": "Property", "property_name": "FX Status Other", "city": "Side",
		                   "country": "Turkey", "currency": "EUR"})
		manual(other)
		self.assertEqual(issue()["reason"], "fx_missing")                    # another hotel's rate does not bridge this one
		manual(None)
		found = issue()
		self.assertEqual((found["status"], found["reason"], found["params"]["days"], found["params"]["manual_days"]),
		                 ("warn", "fx_bridged", None, 1))
		self.assertNotIn("1.337", json.dumps(system_api().status(property=fx.PROPERTY), default=str))

	def test_no_secret_appears_in_the_status_payload(self):
		conn = pms_connection(fx.PROPERTY, "PMS with a key", api_key="tex-ops-api-key-3c9d", secret="tex-ops-secret-77ab")
		frappe.db.set_value("TEX Integration Connection", conn, {"last_status": "Failed",
		                                                         "last_error": "refused by vendor"})
		out = json.dumps(system_api().status(), default=str)
		key = frappe.local.conf.get("encryption_key")
		self.assertTrue(key)
		self.assertNotIn(key, out)
		for secret in ("tex-ops-api-key-3c9d", "tex-ops-secret-77ab", "refused by vendor", "Traceback"):
			self.assertNotIn(secret, out)
		self.assertIn("connections", {c["key"] for c in json.loads(out)["checks"]})

	def test_the_guest_ping_reveals_nothing_but_ok(self):
		frappe.set_user("Guest")  # nosemgrep: frappe-setuser -- an uptime monitor
		out = system_api().ping()
		self.assertTrue(out["ok"])
		self.assertTrue(set(out) <= {"ok", "db", "cache", "scheduler"}, out)
		self.assertTrue(all(isinstance(v, bool) for v in out.values()), out)
		text = json.dumps(out)
		for leak in (fx.PROPERTY, frappe.local.site, "version"):
			self.assertNotIn(leak, text)


class TestOverpaidBookings(TexTestCase):
	"""P1-7 (audit 2B, ADR-065): a booking holding more money than it costs is shown to staff, counted at
	its hotel only, the cancelled ones among them apart."""

	def setUp(self):
		super().setUp()
		setup_site_and_payments(self.f)
		other_tenant()
		self.watcher = monitor("ops-overpaid@example.com", fx.PROPERTY)
		frappe.set_user("Administrator")  # nosemgrep: frappe-setuser -- fixtures

	def overpaid(self, session: str, **row) -> str:
		b = guest_books(session=session, method="Pay at Hotel")["booking"]
		frappe.set_user("Administrator")  # nosemgrep: frappe-setuser -- the money came twice
		total = frappe.db.get_value("TEX Booking", b, "total_amount")
		frappe.db.set_value("TEX Booking", b, {"paid_amount": total + 50, **row}, update_modified=False)
		return b

	def test_a_booking_paid_more_than_it_costs_is_counted_at_its_hotel(self):
		before = check(system_api().status(property=fx.PROPERTY), "payments.overpaid")
		self.overpaid("p17-over-1")
		self.overpaid("p17-over-2", status="Cancelled")
		self.overpaid("p17-over-3", property=OTHER)
		here = check(system_api().status(property=fx.PROPERTY), "payments.overpaid")
		self.assertEqual((here["status"], here["count"] - before["count"]), ("warn", 2))
		self.assertEqual(here["issues"][0]["params"]["cancelled"] - (before["issues"][0]["params"]["cancelled"]
		                                                             if before["issues"] else 0), 1)
		self.assertIn(fx.PROPERTY, here["properties"])
		frappe.set_user(self.watcher)  # nosemgrep: frappe-setuser -- a monitor of this hotel only
		mine = check(system_api().status(), "payments.overpaid")
		self.assertEqual(mine["count"], here["count"])
		self.assertNotIn(OTHER, mine["properties"])

	def credit(self, booking: str, amount) -> None:
		"""A lower price of ``booking`` whose excess was kept as credit on it (a guest's change, or staff approving
		one)."""
		frappe.get_doc({"doctype": "TEX Guest Change Request", "property": fx.PROPERTY, "booking": booking,
		                "reservation": frappe.db.get_value("Reservation", {"tex_booking": booking}, "name"),
		                "status": "Applied", "currency": frappe.db.get_value("TEX Booking", booking, "currency"),
		                "settlement": "Credit on booking", "settlement_amount": amount}).insert(ignore_permissions=True)

	def test_a_credit_kept_on_purpose_is_not_an_overpayment(self):
		"""LO-17 (audit 2K-1): money above a booking's total that the guest kept as credit on it is not counted;
		money above that credit still is."""
		before = check(system_api().status(property=fx.PROPERTY), "payments.overpaid")["count"]
		kept = self.overpaid("p17-credit-1")                # 50 over, all of it kept as credit
		self.credit(kept, 50)
		more = self.overpaid("p17-credit-2")                # 50 over, 20 of it kept as credit
		self.credit(more, 20)
		# review round 1: each credit request stores the whole excess kept at its time (30, then 40 after a second
		# lower price), never added up: 40 is kept, the other 10 is money above it
		twice = self.overpaid("p17-credit-3")
		self.credit(twice, 30)
		self.credit(twice, 40)
		self.assertEqual(check(system_api().status(property=fx.PROPERTY), "payments.overpaid")["count"] - before, 2)


class TestUnverifiedPayments(TexTestCase):
	"""P1-8 (audit 2E-2): a card payment of a gateway TEX cannot ask for its outcome (the Virtual POS) still
	pending 10 minutes after its deadline fails the hotel's pending-payments check; one without a deadline
	(a link's, a change's, a balance's) is judged by its checkout's 30 minutes. A gateway TEX asks
	(iyzico) is not in it: TEX re-verifies those."""

	def pending(self, provider: str, *, expires=None, created_ago: int = 0) -> str:
		name = pay._new_txn(property=fx.PROPERTY, txn_type="Charge", method="Card", amount=100, currency="EUR",
		                    provider=provider, idempotency_key=f"p18-{frappe.generate_hash(length=8)}",
		                    expires_at=expires).name
		frappe.db.sql("UPDATE `tabTEX Payment Transaction` SET creation = %s WHERE name = %s",
		              (add_to_date(now_datetime(), minutes=-created_ago), name))
		return name

	def unverified(self) -> int:
		found = check(system_api().status(property=fx.PROPERTY), "payments.pending")
		return next((i["params"]["count"] for i in found["issues"] if i["reason"] == "payment_pending_unverified"), 0)

	def test_a_payment_tex_cannot_verify_fails_after_its_deadline(self):
		before = self.unverified()
		self.pending("Virtual POS", expires=add_to_date(now_datetime(), minutes=-15), created_ago=50)
		self.pending("Virtual POS", created_ago=45)            # no deadline: 45 − 30 = 15 minutes past
		self.pending("Virtual POS", created_ago=35)            # no deadline: 5 minutes past, not yet
		self.pending("Virtual POS", expires=add_to_date(now_datetime(), minutes=-5), created_ago=50)
		self.pending("iyzico", expires=add_to_date(now_datetime(), minutes=-60), created_ago=90)
		self.pending("Mock", expires=add_to_date(now_datetime(), minutes=-60), created_ago=90)
		self.assertEqual(self.unverified() - before, 2)
		found = check(system_api().status(property=fx.PROPERTY), "payments.pending")
		self.assertEqual(found["status"], "fail")
		self.assertIn(fx.PROPERTY, found["properties"])

	def test_staff_mark_a_payment_the_bank_never_took_as_not_paid(self):
		"""LO-18 (audit 2K-1): staff checked a Virtual POS payment in the bank's panel and it was never charged:
		"Not paid" closes it Failed with their reason, audited, and the check no longer counts it. Finance only
		(``payment.refund``), a reason required; a gateway TEX can ask is re-verified instead."""
		from kamra.tex.api import payments as payments_api

		before = self.unverified()
		txn = self.pending("Virtual POS", expires=add_to_date(now_datetime(), minutes=-15), created_ago=50)
		asked = self.pending("iyzico", expires=add_to_date(now_datetime(), minutes=-15), created_ago=50)
		self.assertEqual(self.unverified() - before, 1)
		self.assertTrue(payments_api.transaction(name=txn)["can_close_unpaid"])
		self.assertFalse(payments_api.transaction(name=asked)["can_close_unpaid"])
		frappe.set_user(agent("lo18-agent@example.com", fx.PROPERTY))  # nosemgrep: frappe-setuser -- payment.view only
		with self.assertRaises(frappe.PermissionError):
			payments_api.close_unpaid(transaction=txn, reason="Not in the bank's panel")
		frappe.set_user("Administrator")  # nosemgrep: frappe-setuser -- finance
		with self.assertRaisesRegex(frappe.ValidationError, "reason"):
			payments_api.close_unpaid(transaction=txn, reason="  ")
		with self.assertRaisesRegex(frappe.ValidationError, "re-verify"):
			payments_api.close_unpaid(transaction=asked, reason="Not in the bank's panel")
		self.assertEqual(payments_api.close_unpaid(transaction=txn, reason="Not in the bank's panel")["status"], "Failed")
		row = frappe.db.get_value("TEX Payment Transaction", txn, ["status", "error_code", "error_message", "completed_at"],
		                          as_dict=True)
		self.assertEqual((row.status, row.error_code, row.error_message), ("Failed", "CLOSED_UNPAID",
		                                                                  "Not in the bank's panel"))
		self.assertIsNotNone(row.completed_at)
		event = frappe.get_all("TEX Audit Event", filters={"action": "payment.closed_unpaid", "reference_name": txn},
		                       fields=["reason", "property"])
		self.assertEqual([(e.reason, e.property) for e in event], [("Not in the bank's panel", fx.PROPERTY)])
		self.assertEqual(self.unverified(), before)
		self.assertFalse(payments_api.transaction(name=txn)["can_close_unpaid"])
		with self.assertRaisesRegex(frappe.ValidationError, "already processed"):
			payments_api.close_unpaid(transaction=txn, reason="again")
		self.assertEqual(frappe.db.get_value("TEX Payment Transaction", asked, "status"), "Pending")


class TestContractsLive(TexTestCase):
	"""Y-2 (2D-1): an Active contract within its sale window with no version on sale (and none starting
	within 7 days) sells nothing: ``contracts.live`` fails and names its hotel."""

	def test_withdrawing_the_version_on_sale_fails_the_check(self):
		from kamra.tex.commercial import contracts

		c = fx.create_contract(self.f, code="Y2-LIVE")
		before = check(system_api().status(property=fx.PROPERTY), "contracts.live")
		contracts.withdraw(c["version"], reason="wrong prices")
		after = check(system_api().status(property=fx.PROPERTY), "contracts.live")
		self.assertEqual(after["status"], "fail")
		failing = next(i for i in after["issues"] if i["reason"] == "contract_not_selling")
		before_n = next((i["params"]["count"] for i in before["issues"] if i["reason"] == "contract_not_selling"), 0)
		self.assertEqual(failing["params"]["count"] - before_n, 1)
		self.assertIn(fx.PROPERTY, after["properties"])
		self.assertNotIn(c["contract"], json.dumps(after))                   # counts and hotels only


class TestStatusAlerts(TexTestCase):
	def setUp(self):
		super().setUp()
		ensure_test_outbox()
		frappe.db.set_single_value("TEX Settings", "status_alert_recipients", RECIPIENT)
		self.started = add_to_date(now_datetime(), seconds=-1)
		# Error Log is MyISAM: rows of earlier tests survive their rollback, so count the new ones
		self.logs_before = self.alert_logs()

	def alert_logs(self) -> int:
		return frappe.db.count("Error Log", {"method": ("like", "TEX status alert:%")})

	def mails(self) -> int:
		return frappe.db.count("Email Queue Recipient", {"recipient": RECIPIENT, "creation": (">=", self.started)})

	def test_an_alert_goes_out_once_on_transition_and_once_on_recovery(self):
		from kamra.tex.ops import alerts

		ok = [{"key": "outbox.pms", "status": "ok", "detail": "No problems.", "issues": []}]
		bad = [{"key": "outbox.pms", "status": "fail", "detail": "1 dead job.", "count": 1,
		        "issues": [{"reason": "dead", "status": "fail", "params": {"count": 1}}]}]
		runs = []
		with mock.patch("kamra.tex.ops.status.collect", side_effect=lambda **kw: runs[-1]):
			for checks, mails in ((ok, 0), (bad, 1), (bad, 1), (bad, 1), (ok, 2), (ok, 2)):
				runs.append(checks)
				alerts.evaluate()
				self.assertEqual(self.mails(), mails, [c["status"] for c in checks])
		self.assertEqual(self.alert_logs() - self.logs_before, 1)         # the worsening, not the recovery
		events = frappe.get_all("TEX Audit Event", filters={"action": "system.status_changed",
		                                                    "creation": (">=", self.started)}, pluck="name")
		self.assertEqual(len(events), 2)                                  # ok→fail, fail→ok

	def test_a_real_dead_job_alerts_once(self):
		from kamra.tex.ops import alerts

		conn = pms_connection(fx.PROPERTY)
		quiet_outbox()
		alerts.evaluate()                                                  # whatever the site's state is now
		before = self.mails()
		outbox_row(conn, fx.PROPERTY, "Dead")
		out = alerts.evaluate()
		self.assertIn("outbox.pms", out["alerted"])
		self.assertEqual(self.mails(), before + 1)
		self.assertNotIn("outbox.pms", alerts.evaluate()["alerted"])     # the next run stays quiet
		self.assertEqual(self.mails(), before + 1)

	def test_the_alert_jobs_are_scheduled(self):
		from kamra.tex import scheduler

		self.assertIn("kamra.tex.ops.alerts.evaluate", scheduler.EVERY_15_MINUTES)
		self.assertIn("kamra.tex.services.mail_status.sync", scheduler.EVERY_5_MINUTES)

	def test_the_pms_outbox_is_its_own_watched_5_minute_job(self):
		"""NEW-7 (2F-1): holds, payments and links never wait behind a PMS: the outbox is not in the group of the
		expiry, runs from its own cron entry (its own RQ job and time limit) and the status page watches it."""
		from kamra import hooks
		from kamra.tex import scheduler
		from kamra.tex.ops import checks
		from kamra.tex.ops import status as ops_status

		self.assertEqual(hooks.scheduler_events["cron"]["*/5 * * * *"],
		                 ["kamra.tex.scheduler.every_5_minutes", "kamra.tex.scheduler.outbox_every_5_minutes"])
		self.assertEqual(scheduler.OUTBOX_EVERY_5_MINUTES, ("kamra.tex.connect.outbox.deliver_pending",))
		self.assertNotIn("kamra.tex.connect.outbox.deliver_pending", scheduler.EVERY_5_MINUTES)
		for job in ("every_5_minutes", "outbox_every_5_minutes"):
			self.assertIn(f"kamra.tex.scheduler.{job}", checks.JOB_MAX_AGE_MINUTES)
			self.assertIn(f"kamra.tex.scheduler.{job}", ops_status.TEX_JOBS)

	def test_payments_are_verified_first_in_the_5_minute_jobs(self):
		"""NEW-2: the re-verification job runs first in its group — before the PMS outbox (which may use most
		of the tick) and before the expiry, so money it finds confirms its booking in that tick."""
		from kamra.tex import scheduler

		self.assertEqual(scheduler.EVERY_5_MINUTES[0], "kamra.tex.payments.service.reverify_pending")
		self.assertLess(scheduler.EVERY_5_MINUTES.index("kamra.tex.payments.service.reverify_pending"),
		                scheduler.EVERY_5_MINUTES.index("kamra.tex.services.booking.expire_pending_bookings"))


class TestMailDeliveryStatus(TexTestCase):
	def setUp(self):
		super().setUp()
		setup_site_and_payments(self.f)
		ensure_test_outbox()

	def booked_mail(self, session: str) -> tuple[dict, str, str]:
		b = guest_books(session=session)
		frappe.set_user("Administrator")  # nosemgrep: frappe-setuser -- the scheduler
		comm = frappe.get_all("TEX Communication", filters={"booking": b["booking"], "channel": "Email"},
		                      fields=["name", "status", "email_queue"])
		self.assertEqual(len(comm), 1)
		self.assertEqual(comm[0].status, "Queued")
		self.assertTrue(frappe.db.exists("Email Queue", comm[0].email_queue))
		return b, comm[0].name, comm[0].email_queue

	def test_an_email_queue_row_moving_to_sent_or_error_updates_the_communication(self):
		from kamra.tex.services import mail_status

		_b, sent, sent_q = self.booked_mail("mail-sent")
		_b, failed, failed_q = self.booked_mail("mail-error")
		_b, waiting, _q = self.booked_mail("mail-wait")
		frappe.db.set_value("Email Queue", sent_q, "status", "Sent")
		frappe.db.set_value("Email Queue", failed_q, {
			"status": "Error", "error": "Traceback (most recent call last):\n  File smtp.py\nsmtplib.SMTPRecipientsRefused: "
			                            "{'lena@example.com': (550, b'5.1.1 no such user')}\n"})
		mail_status.sync()
		self.assertEqual(frappe.db.get_value("TEX Communication", sent, "status"), "Sent")
		row = frappe.db.get_value("TEX Communication", failed, ["status", "delivery_error"], as_dict=True)
		self.assertEqual(row.status, "Failed")
		self.assertEqual(row.delivery_error, "SMTPRecipientsRefused (550)")     # no address, no traceback
		self.assertEqual(frappe.db.get_value("TEX Communication", waiting, "status"), "Queued")  # still in the queue
		self.assertEqual(mail_status.sync()["updated"], 0)                # idempotent
		mail = check(system_api().status(property=fx.PROPERTY), "mail.delivery")
		self.assertIn(mail["status"], ("warn", "fail"))
		self.assertGreaterEqual(mail["count"], 1)

	def test_guest_mail_is_sent_in_the_hotels_name_from_the_sites_account(self):
		import email as email_lib
		from email.utils import parseaddr

		account = frappe.db.get_value("Email Account", {"default_outgoing": 1, "enable_outgoing": 1}, "email_id")
		frappe.db.set_value("Property", fx.PROPERTY, "email", "reservations@tex-test-resort.example")
		_b, _comm, queue = self.booked_mail("mail-sender")
		q = frappe.get_doc("Email Queue", queue)
		name, address = parseaddr(q.sender)
		self.assertEqual((name, address), (fx.PROPERTY, account))            # the hotel's name, our own address
		msg = email_lib.message_from_string(q.message)
		self.assertEqual(parseaddr(msg["From"])[1], account)                # never the hotel's domain
		self.assertEqual(parseaddr(msg["Reply-To"])[1], "reservations@tex-test-resort.example")
		frappe.db.set_value("Property", fx.PROPERTY, "email", "not an address")
		frappe.db.set_value("TEX Booking Site", {"site_slug": SLUG}, "contact_email", None)
		_b, _comm, queue = self.booked_mail("mail-no-reply-to")
		msg = email_lib.message_from_string(frappe.db.get_value("Email Queue", queue, "message"))
		self.assertEqual(parseaddr(msg["Reply-To"])[1], account)           # Frappe's default: the sender

	def test_resend_reports_queued_never_sent(self):
		from kamra.tex.api import crs

		b = guest_books(session="mail-resend")
		frappe.set_user("Administrator")  # nosemgrep: frappe-setuser -- staff re-sends
		out = crs.resend_confirmation(booking=b["booking"])
		self.assertTrue(out["queued"])
		self.assertEqual(out["status"], "Queued")
		self.assertNotIn("sent", out)
		for acc in frappe.get_all("Email Account", filters={"enable_outgoing": 1}, pluck="name"):
			frappe.db.set_value("Email Account", acc, {"enable_outgoing": 0, "default_outgoing": 0})
		frappe.local.outgoing_email_account = {}           # drop the per-process account cache
		out = crs.resend_confirmation(booking=b["booking"])
		self.assertFalse(out["queued"])
		self.assertEqual(out["status"], "Failed")
		last = frappe.get_all("TEX Communication", filters={"booking": b["booking"], "channel": "Email"},
		                      fields=["status", "delivery_error"], order_by="creation desc", limit=1)[0]
		self.assertEqual((last.status, last.delivery_error), ("Failed", "OutgoingEmailError"))


def session_snapshot_isolation() -> int:
	return int(frappe.db.sql("SELECT @@SESSION.innodb_snapshot_isolation")[0][0])


class TestSnapshotIsolation(IntegrationTestCase):
	"""ADR-063: MariaDB >= 11.6.2 hands every new connection innodb_snapshot_isolation ON. TEX turns
	it off for each web request and background job, and the status page fails while it is on."""

	def setUp(self):
		super().setUp()
		frappe.set_user("Administrator")  # nosemgrep: frappe-setuser -- a platform administrator
		self.before = session_snapshot_isolation()

	def tearDown(self):
		frappe.db.sql("SET SESSION innodb_snapshot_isolation = %s", self.before)
		super().tearDown()

	def test_a_web_request_runs_with_it_off(self):
		from frappe.database.database import Database
		from frappe.utils import get_test_client

		real_connect, seen, responses = Database.connect, {}, []

		def connect_as_a_new_server_does(db):
			real_connect(db)
			db.sql("SET SESSION innodb_snapshot_isolation = 1")
			seen.setdefault("connected", int(db.sql("SELECT @@SESSION.innodb_snapshot_isolation")[0][0]))

		def db_ok():                                   # runs inside the request, on its connection
			seen["in_request"] = session_snapshot_isolation()
			return True

		def request():
			responses.append(get_test_client().get("/api/method/kamra.tex.api.system.ping"))

		with (mock.patch.object(Database, "connect", connect_as_a_new_server_does),
		      mock.patch("kamra.tex.api.system._db_ok", side_effect=db_ok),
		      mock.patch("frappe.app.get_site_name", return_value=frappe.local.site)):
			t = threading.Thread(target=request)       # its own frappe.local and connection, as a worker's
			t.start()
			t.join(timeout=60)
		self.assertEqual(responses[0].status_code, 200, responses[0].get_data(as_text=True))
		self.assertEqual(seen, {"connected": 1, "in_request": 0})

	def test_a_background_job_runs_with_it_off(self):
		from frappe.database.database import Database
		from frappe.utils.background_jobs import execute_job

		frappe.db.sql("SET SESSION innodb_snapshot_isolation = 1")
		seen, had_job = [], hasattr(frappe.local, "job")
		try:
			with mock.patch.object(Database, "commit"):  # the job's own commit: nothing of the test is kept
				execute_job(frappe.local.site, method=lambda: seen.append(session_snapshot_isolation()), event=None,
				            job_name="tex-snapshot-isolation-probe", kwargs={}, is_async=False)
		finally:
			if not had_job:
				del frappe.local.job
		self.assertEqual(seen, [0])

	def test_the_status_page_fails_while_it_is_on(self):
		from kamra.tex.ops import status as status_mod

		frappe.db.sql("SET SESSION innodb_snapshot_isolation = 1")          # this connection has it on
		on = check(system_api().status(), "db.snapshot_isolation")
		self.assertEqual((on["status"], on["scope"]), ("fail", "platform"))
		self.assertIn("@@SESSION", [i["params"]["level"] for i in on["issues"]])
		frappe.db.sql("SET SESSION innodb_snapshot_isolation = 0")
		for values, status, levels in (({"global": 1, "session": 0}, "fail", ["@@GLOBAL"]),
		                               ({"global": 0, "session": 0}, "ok", []),
		                               (None, "ok", [])):                   # before MariaDB 10.6.18: no variable
			with mock.patch("kamra.tex.ops.snapshot_isolation.values", return_value=values):
				c = check({"checks": status_mod.collect(platform=True)}, "db.snapshot_isolation")
			self.assertEqual((c["status"], [i["params"]["level"] for i in c["issues"]]), (status, levels), values)

	def test_a_server_without_the_variable_has_nothing_to_turn_off(self):
		from kamra.tex.ops import snapshot_isolation

		unknown = frappe.db.OperationalError(1193, "Unknown system variable 'innodb_snapshot_isolation'")
		with mock.patch("frappe.database.database.Database.sql", side_effect=unknown):
			snapshot_isolation.turn_off()
			self.assertIsNone(snapshot_isolation.values())
		lost = frappe.db.OperationalError(2013, "Lost connection to server during query")
		with (mock.patch("frappe.database.database.Database.sql", side_effect=lost),
		      self.assertRaises(frappe.db.OperationalError)):
			snapshot_isolation.turn_off()
