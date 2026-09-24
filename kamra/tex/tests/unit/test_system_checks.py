"""System-status verdicts (ADR-047): thresholds, transitions, alert text and the e-mail
status mapping. Pure: runs without frappe."""

import ast
import pathlib
import unittest
from datetime import date, datetime, timedelta

from kamra.tex.ops import checks as c

NOW = datetime(2026, 9, 23, 12, 0, 0)          # a Wednesday


class TestVerdicts(unittest.TestCase):
	def test_worst_decides_and_ok_is_the_default(self):
		self.assertEqual(c.worst([]), c.OK)
		self.assertEqual(c.worst([c.OK, c.WARN, c.OK]), c.WARN)
		self.assertEqual(c.worst([c.WARN, c.FAIL, c.OK]), c.FAIL)

	def test_a_dead_message_fails_and_a_late_one_warns_then_fails(self):
		ok = c.queue_check("outbox.pms", dead=0, now=NOW)
		self.assertEqual((ok["status"], ok["count"], ok["properties"]), (c.OK, 0, []))
		late = c.queue_check("outbox.pms", dead=0, late=2, late_since=NOW - timedelta(minutes=45), now=NOW,
		                     properties=["H1"])
		self.assertEqual((late["status"], late["count"], late["issues"][0]["params"]["minutes"]), (c.WARN, 2, 45))
		very_late = c.queue_check("outbox.pms", dead=0, late=1, late_since=NOW - timedelta(hours=5), now=NOW)
		self.assertEqual(very_late["status"], c.FAIL)
		dead = c.queue_check("outbox.pms", dead=1, late=3, late_since=NOW - timedelta(minutes=45), now=NOW)
		self.assertEqual((dead["status"], dead["count"], dead["issues"][0]["reason"]), (c.FAIL, 1, "dead"))
		self.assertIn("1 message(s) are dead", dead["detail"])

	def test_scheduler_off_fails_a_live_site_and_warns_a_developer_site(self):
		self.assertEqual(c.scheduler_check(inactive_reason=None, live=True)["status"], c.OK)
		self.assertEqual(c.scheduler_check(inactive_reason="disabled", live=True)["status"], c.FAIL)
		self.assertEqual(c.scheduler_check(inactive_reason="disabled", live=False)["status"], c.WARN)

	def test_tex_jobs_late_stopped_missing(self):
		fresh = {m: {"last_execution": NOW - timedelta(minutes=1), "stopped": False} for m in c.JOB_MAX_AGE_MINUTES}
		self.assertEqual(c.jobs_check(fresh, NOW, live=True)["status"], c.OK)
		late = dict(fresh)
		late["kamra.tex.scheduler.every_minute"] = {"last_execution": NOW - timedelta(minutes=15), "stopped": False}
		out = c.jobs_check(late, NOW, live=True)
		self.assertEqual((out["status"], out["issues"][0]["params"]), (c.WARN, {"job": "every_minute", "minutes": 15}))
		late["kamra.tex.scheduler.every_minute"] = {"last_execution": NOW - timedelta(minutes=31), "stopped": False}
		self.assertEqual(c.jobs_check(late, NOW, live=True)["status"], c.FAIL)
		stopped = dict(fresh)
		stopped["kamra.tex.scheduler.daily"] = {"last_execution": NOW, "stopped": True}
		self.assertEqual(c.jobs_check(stopped, NOW, live=False)["issues"][0]["reason"], "job_stopped")
		missing = {k: v for k, v in fresh.items() if not k.endswith("fx_daily")}
		self.assertEqual(c.jobs_check(missing, NOW, live=False)["issues"][0]["reason"], "job_missing")

	def test_workers_and_redis(self):
		self.assertEqual(c.workers_check(reachable=False, workers=0, backlog=0, live=True)["status"], c.FAIL)
		self.assertEqual(c.workers_check(reachable=True, workers=0, backlog=0, live=False)["status"], c.WARN)
		self.assertEqual(c.workers_check(reachable=True, workers=2, backlog=10, live=True)["status"], c.OK)
		self.assertEqual(c.workers_check(reachable=True, workers=2, backlog=c.QUEUE_BACKLOG_WARN, live=True)["status"],
		                 c.WARN)
		self.assertEqual(c.workers_check(reachable=True, workers=2, backlog=c.QUEUE_BACKLOG_FAIL, live=True)["status"],
		                 c.FAIL)

	def test_mail_account_is_an_owner_input(self):
		self.assertEqual(c.mail_account_check(has_account=False, suspended=False, production=False)["status"], c.WARN)
		self.assertEqual(c.mail_account_check(has_account=False, suspended=False, production=True)["status"], c.FAIL)
		self.assertEqual(c.mail_account_check(has_account=True, suspended=True, production=True)["status"], c.WARN)
		self.assertNotIn("properties", c.mail_account_check(has_account=True, suspended=False, production=True))

	def test_mail_delivery(self):
		self.assertEqual(c.mail_check("mail.delivery", failed=0, unsent=0, oldest_unsent=None, now=NOW)["status"], c.OK)
		self.assertEqual(c.mail_check("mail.delivery", failed=1, unsent=0, oldest_unsent=None, now=NOW)["status"], c.WARN)
		self.assertEqual(c.mail_check("mail.delivery", failed=c.MAIL_FAILED_FAIL_COUNT, unsent=0, oldest_unsent=None,
		                              now=NOW)["status"], c.FAIL)
		self.assertEqual(c.mail_check("mail.delivery", failed=0, unsent=3, oldest_unsent=NOW - timedelta(hours=5),
		                              now=NOW)["status"], c.FAIL)

	def test_payment_checks(self):
		self.assertEqual(c.callbacks_check(errors=0, overpaid=0, mismatches=0)["status"], c.OK)
		self.assertEqual(c.callbacks_check(errors=2, overpaid=0, mismatches=0)["status"], c.WARN)
		out = c.callbacks_check(errors=2, overpaid=1, mismatches=1)
		self.assertEqual((out["status"], out["issues"][0]["reason"], out["count"]), (c.FAIL, "capture_mismatch", 1))
		# a refund the gateway never confirmed fails the check (G-45 review)
		unknown = c.callbacks_check(errors=0, overpaid=0, mismatches=0, refunds_unknown=2)
		self.assertEqual((unknown["status"], unknown["issues"][0]["reason"], unknown["issues"][0]["params"]),
		                 (c.FAIL, "refund_unknown", {"count": 2}))
		# a gateway answer contradicting a recorded refund outcome fails it too (third review)
		conflict = c.callbacks_check(errors=0, overpaid=0, mismatches=0, refund_conflicts=1)
		self.assertEqual((conflict["status"], conflict["issues"][0]["reason"], conflict["issues"][0]["params"]),
		                 (c.FAIL, "refund_conflict", {"count": 1}))
		self.assertEqual(c.pending_payments_check(2, NOW - timedelta(minutes=90), NOW)["issues"][0]["params"],
		                 {"count": 2, "minutes": 90})


class TestFx(unittest.TestCase):
	def pair(self, rate_date, max_age=4):
		return [{"pair": "EUR/TRY", "provider": "TCMB", "rate_date": rate_date, "max_age_days": max_age}]

	def test_business_days_skip_weekends(self):
		wed = date(2026, 9, 23)
		self.assertEqual(c.business_days(wed, wed), 0)
		self.assertEqual(c.business_days(date(2026, 9, 18), date(2026, 9, 21)), 1)      # Friday → Monday
		self.assertEqual(c.business_days(date(2026, 9, 16), wed), 5)
		self.assertEqual(c.business_days(date(2025, 9, 23), wed), 261)

	def test_old_warns_stale_and_missing_fail(self):
		wed = date(2026, 9, 23)
		self.assertEqual(c.fx_check(self.pair(wed), wed)["status"], c.OK)
		self.assertEqual(c.fx_check(self.pair(date(2026, 9, 21)), wed)["status"], c.OK)   # Monday's rate
		old = c.fx_check(self.pair(date(2026, 9, 18), max_age=7), wed)                      # Friday: 3 weekdays
		self.assertEqual((old["status"], old["issues"][0]["params"]["days"]), (c.WARN, 5))
		stale = c.fx_check(self.pair(date(2026, 9, 18)), date(2026, 9, 28))
		self.assertEqual((stale["status"], stale["issues"][0]["reason"]), (c.FAIL, "fx_stale"))
		self.assertEqual(c.fx_check(self.pair(None), wed)["issues"][0]["reason"], "fx_missing")

	def test_monday_morning_before_the_fetch_is_not_an_alarm(self):
		self.assertEqual(c.fx_check(self.pair(date(2026, 9, 18)), date(2026, 9, 21))["status"], c.OK)


class TestTransitions(unittest.TestCase):
	def test_only_worsening_and_recovery_are_sent(self):
		t = c.transitions({}, {})
		self.assertEqual((t["worse"], t["recovered"], t["changed"]), ([], [], False))
		t = c.transitions({}, {"outbox.pms": c.FAIL})
		self.assertEqual((t["worse"], t["recovered"], t["changed"]), (["outbox.pms"], [], True))
		t = c.transitions({"outbox.pms": c.FAIL}, {"outbox.pms": c.FAIL})
		self.assertEqual((t["worse"], t["changed"]), ([], False))
		t = c.transitions({"outbox.pms": c.WARN}, {"outbox.pms": c.FAIL})
		self.assertEqual(t["worse"], ["outbox.pms"])
		t = c.transitions({"outbox.pms": c.FAIL}, {"outbox.pms": c.WARN})
		self.assertEqual((t["worse"], t["recovered"], t["changed"]), ([], [], True))     # recorded, not sent
		t = c.transitions({"outbox.pms": c.WARN}, {})
		self.assertEqual(t["recovered"], ["outbox.pms"])

	def test_state_keeps_only_problems(self):
		checks = [c.queue_check("outbox.pms", dead=1, now=NOW), c.encryption_key_check(True)]
		self.assertEqual(c.state_of(checks), {"outbox.pms": c.FAIL})

	def test_alert_text_names_checks_and_escapes(self):
		bad = c.queue_check("outbox.pms", dead=1, now=NOW, properties=["<Hotel>"])
		subject, body = c.alert_message("tex.example", [bad], ["outbox.pms"], ["fx.rates"], NOW)
		self.assertIn("FAIL: PMS delivery queue", subject)
		self.assertIn("recovered: FX rates", subject)
		self.assertIn("&lt;Hotel&gt;", body)
		self.assertNotIn("<Hotel>", body)


class TestMailStatus(unittest.TestCase):
	def test_queue_status_maps_to_the_communication(self):
		self.assertEqual(c.communication_status("Sent"), "Sent")
		self.assertEqual(c.communication_status("Error"), "Failed")
		self.assertEqual(c.communication_status("Expired"), "Failed")
		for waiting in ("Not Sent", "Sending", "Partially Sent", None):
			self.assertIsNone(c.communication_status(waiting))

	def test_delivery_error_is_short_and_address_free(self):
		tb = ("Traceback (most recent call last):\n  File \"x.py\", line 1\nsmtplib.SMTPRecipientsRefused: "
		      "{'lena@example.com': (550, b'5.1.1 no such user')}\n")
		self.assertEqual(c.delivery_error(tb), "SMTPRecipientsRefused (550)")
		self.assertEqual(c.delivery_error("frappe.exceptions.OutgoingEmailError: Please set up an account"),
		                 "OutgoingEmailError")
		self.assertEqual(c.delivery_error("TimeoutError"), "TimeoutError")
		self.assertEqual(c.delivery_error("connection to mx.example.com lost"), "Error")
		self.assertIsNone(c.delivery_error(""))


class TestPurity(unittest.TestCase):
	def test_checks_never_import_frappe(self):
		src = pathlib.Path(c.__file__).read_text()
		for node in ast.walk(ast.parse(src)):
			names = [a.name for a in node.names] if isinstance(node, ast.Import) else \
				[node.module or ""] if isinstance(node, ast.ImportFrom) else []
			self.assertFalse(any(n == "frappe" or n.startswith("frappe.") for n in names))
