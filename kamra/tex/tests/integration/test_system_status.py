"""System status, alerts and e-mail delivery status (ADR-047).

- ``kamra.tex.api.system.status`` (``system.monitor``): hotel-scoped checks show only the
  hotels where the user holds the capability; platform checks (scheduler, workers,
  encryption key, the whole e-mail queue) only for platform administrators; no secret,
  token, guest data or stack trace in the payload.
- ``kamra.tex.api.system.ping`` (guest): ``ok`` and reachability booleans, nothing else.
- ``kamra.tex.ops.alerts.evaluate`` (every 15 minutes): one notice when a check gets worse
  and one when it recovers, never on every run.
- ``kamra.tex.services.mail_status.sync`` (every 5 minutes): a TEX Communication follows its
  Email Queue row (Sent / Error); "resend" reports what happened (queued), never "sent".
"""

import json
from unittest import mock

import frappe
from frappe.utils import add_days, add_to_date, now_datetime, nowdate

from kamra.tex.security import scope
from kamra.tex.tests.integration import fixtures as fx
from kamra.tex.tests.integration.test_commercial_flows import guest_books, setup_site_and_payments
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


PLATFORM_KEYS = {"scheduler", "scheduler.jobs", "scheduler.errors", "workers", "encryption_key", "mail.queue"}


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
		fx.ensure_currency("XTS", "¤")
		fx.ensure_live("TEX FX Policy", {"property": fx.PROPERTY, "from_currency": "EUR", "to_currency": "XTS"},
		               {"property": fx.PROPERTY, "from_currency": "EUR", "to_currency": "XTS", "mode": "PROVIDER",
		                "provider": "ECB", "rate_type": "REFERENCE", "max_age_days": 4})

		def rate(days_ago: int):
			frappe.get_doc({"doctype": "TEX FX Rate", "provider": "ECB", "base_currency": "EUR", "quote_currency": "XTS",
			                "rate_type": "REFERENCE", "rate": 1.25, "rate_date": add_days(nowdate(), -days_ago),
			                "fetched_at": add_days(now_datetime(), -days_ago)}).insert(ignore_permissions=True)

		def issue():
			c = check(system_api().status(property=fx.PROPERTY), "fx.rates")
			return next((i for i in c["issues"] if i["params"].get("pair") == "EUR/XTS"), None)

		self.assertEqual(issue()["status"], "fail")                      # no rate at all: pricing refuses
		rate(6)
		self.assertEqual((issue()["status"], issue()["reason"]), ("fail", "fx_stale"))    # older than the policy's 4 days
		rate(3)
		self.assertEqual((issue()["status"], issue()["reason"], issue()["params"]["days"]), ("warn", "fx_old", 3))
		rate(0)
		self.assertIsNone(issue())                                        # today's rate: nothing to say

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
