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

	def test_the_pms_outbox_job_is_watched_as_closely_as_the_5_minute_group(self):
		"""NEW-7 (2F-1): the outbox runs from its own 5-minute entry; a stalled PMS is late there, not in the
		group of the holds and payments."""
		self.assertEqual([c.JOB_MAX_AGE_MINUTES[f"kamra.tex.scheduler.{job}"]
		                  for job in ("every_5_minutes", "outbox_every_5_minutes")], [20, 20])
		fresh = {m: {"last_execution": NOW - timedelta(minutes=1), "stopped": False} for m in c.JOB_MAX_AGE_MINUTES}
		stalled = dict(fresh)
		stalled["kamra.tex.scheduler.outbox_every_5_minutes"] = {"last_execution": NOW - timedelta(minutes=25),
		                                                         "stopped": False}
		out = c.jobs_check(stalled, NOW, live=True)
		self.assertEqual((out["status"], out["issues"][0]["params"]),
		                 (c.WARN, {"job": "outbox_every_5_minutes", "minutes": 25}))

	def test_workers_and_redis(self):
		self.assertEqual(c.workers_check(reachable=False, workers=0, backlog=0, live=True)["status"], c.FAIL)
		self.assertEqual(c.workers_check(reachable=True, workers=0, backlog=0, live=False)["status"], c.WARN)
		self.assertEqual(c.workers_check(reachable=True, workers=2, backlog=10, live=True)["status"], c.OK)
		self.assertEqual(c.workers_check(reachable=True, workers=2, backlog=c.QUEUE_BACKLOG_WARN, live=True)["status"],
		                 c.WARN)
		self.assertEqual(c.workers_check(reachable=True, workers=2, backlog=c.QUEUE_BACKLOG_FAIL, live=True)["status"],
		                 c.FAIL)

	def test_snapshot_isolation_on_fails_globally_or_for_the_connection(self):
		"""ADR-063: ON turns a waiting booking's "sold out" into error 1020."""
		for values in (None, {"global": 0, "session": 0}):
			ok = c.snapshot_isolation_check(values)
			self.assertEqual((ok["status"], ok["scope"], ok["count"]), (c.OK, "platform", 0))
		server = c.snapshot_isolation_check({"global": 1, "session": 0})
		self.assertEqual((server["status"], server["issues"][0]["params"]), (c.FAIL, {"level": "@@GLOBAL"}))
		self.assertIn("innodb_snapshot_isolation = 0", server["detail"])
		conn = c.snapshot_isolation_check({"global": 0, "session": 1})
		self.assertEqual((conn["status"], conn["issues"][0]["params"]), (c.FAIL, {"level": "@@SESSION"}))
		both = c.snapshot_isolation_check({"global": 1, "session": 1})
		self.assertEqual((both["status"], both["count"], len(both["issues"])), (c.FAIL, 2, 2))

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

	def test_a_payment_tex_cannot_ask_its_gateway_about_fails_after_its_deadline(self):
		"""P1-8: a card payment of a gateway TEX cannot ask (the Virtual POS) still pending past its deadline
		fails the check, with how to settle it; the pending warning stays as it was."""
		self.assertEqual(c.PAYMENT_UNVERIFIED_FAIL_MINUTES, 10)
		out = c.pending_payments_check(3, NOW - timedelta(minutes=90), NOW, ["H1"], unverified=1,
		                               unverified_since=NOW - timedelta(minutes=45))
		self.assertEqual(out["status"], c.FAIL)
		self.assertEqual([(i["reason"], i["status"], i["params"]) for i in out["issues"]],
		                 [("payment_pending_unverified", c.FAIL, {"count": 1, "minutes": 45}),
		                  ("payment_pending", c.WARN, {"count": 3, "minutes": 90})])
		text = c.describe(out["issues"][0])
		for words in ("bank's panel", "Manual payment", "48 hours"):
			self.assertIn(words, text)
		# only the unverified one (its deadline passed; no pending one old enough to warn yet)
		alone = c.pending_payments_check(0, None, NOW, unverified=2, unverified_since=NOW - timedelta(minutes=12))
		self.assertEqual((alone["status"], [i["reason"] for i in alone["issues"]]),
		                 (c.FAIL, ["payment_pending_unverified"]))
		self.assertEqual(c.pending_payments_check(0, None, NOW)["status"], c.OK)

	def test_holds_past_their_deadline_fail(self):
		"""D9 (audit 1c): a booking still holding rooms well after its hold ended (its expiry keeps
		failing) blocks inventory: the check fails, with the count and the age of the oldest."""
		ok = c.overdue_holds_check(0, None, NOW)
		self.assertEqual((ok["key"], ok["status"], ok["scope"]), ("holds.overdue", c.OK, "hotel"))
		out = c.overdue_holds_check(2, NOW - timedelta(minutes=45), NOW, properties=["H1"])
		self.assertEqual((out["status"], out["issues"][0]["reason"], out["issues"][0]["params"]),
		                 (c.FAIL, "hold_overdue", {"count": 2, "minutes": 45}))
		self.assertIn("hold_overdue", c.REASONS)
		self.assertIn("holds.overdue", c.TITLES)

	def test_bookings_paid_more_than_they_cost_warn(self):
		"""P1-7 (audit 2B): a booking holding more money than its total is shown to staff with the
		count, the cancelled ones among them and the oldest; staff refund the excess or move it."""
		ok = c.overpaid_bookings_check(0, 0, None)
		self.assertEqual((ok["key"], ok["status"], ok["scope"]), ("payments.overpaid", c.OK, "hotel"))
		out = c.overpaid_bookings_check(3, 1, NOW - timedelta(hours=5), properties=["H1"])
		self.assertEqual((out["status"], out["count"], out["properties"]), (c.WARN, 3, ["H1"]))
		self.assertEqual([(i["reason"], i["params"]) for i in out["issues"]],
		                 [("bookings_overpaid", {"count": 3, "cancelled": 1})])
		self.assertEqual(out["since"], str(NOW - timedelta(hours=5)))
		self.assertIn("bookings_overpaid", c.REASONS)
		self.assertIn("payments.overpaid", c.TITLES)
		self.assertIn("3", c.describe(out["issues"][0]))

	def test_money_in_reconciliation_is_shown_with_its_age(self):
		"""B5: payments kept off every booking wait for staff (or a queued refund): each kind with its
		count and the age of its oldest item; staff have a day, a queued refund an hour."""
		ok = c.reconciliation_check(action=0, action_since=None, refund=0, refund_since=None, now=NOW)
		self.assertEqual((ok["key"], ok["status"], ok["scope"]), ("payments.reconciliation", c.OK, "hotel"))
		out = c.reconciliation_check(action=2, action_since=NOW - timedelta(minutes=90), refund=1,
		                             refund_since=NOW - timedelta(minutes=10), now=NOW, properties=["H1"])
		self.assertEqual(out["status"], c.WARN)
		self.assertEqual([(i["reason"], i["params"]) for i in out["issues"]],
		                 [("reconciliation_action", {"count": 2, "hours": 1.5}),
		                  ("reconciliation_refund", {"count": 1, "hours": 0.2})])
		self.assertEqual((out["since"], out["properties"]), (str(NOW - timedelta(minutes=90)), ["H1"]))
		old = c.reconciliation_check(action=1, action_since=NOW - timedelta(hours=c.RECONCILIATION_ACTION_FAIL_HOURS),
		                             refund=0, refund_since=None, now=NOW)
		self.assertEqual(old["status"], c.FAIL)
		stuck = c.reconciliation_check(action=0, action_since=None, refund=1, now=NOW,
		                               refund_since=NOW - timedelta(minutes=c.RECONCILIATION_REFUND_FAIL_MINUTES))
		self.assertEqual(stuck["status"], c.FAIL)
		self.assertIn("reconciliation_action", c.REASONS)
		self.assertIn("payments.reconciliation", c.TITLES)


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

	def test_every_weekday_warns_after_two_business_days(self):
		"""The table the integration test pins its week with (test_system_status): for each weekday, the
		oldest rate that is not yet old and the newest that is, in calendar days, worked out by hand."""
		ages = {0: (4, 5), 1: (4, 5), 2: (2, 3), 3: (2, 3), 4: (2, 3), 5: (3, 4), 6: (4, 5)}
		monday = date(2026, 9, 28)
		for today in (monday + timedelta(days=i) for i in range(7)):
			quiet, old = ages[today.weekday()]
			with self.subTest(weekday=today.strftime("%A")):
				seen = {d: c.fx_check(self.pair(today - timedelta(days=d), max_age=7), today) for d in (0, quiet, old, 7, 8)}
				self.assertEqual({d: v["status"] for d, v in seen.items()},
				                 {0: c.OK, quiet: c.OK, old: c.WARN, 7: c.WARN, 8: c.FAIL})
				self.assertEqual([(i["reason"], i["params"]["days"]) for d in (old, 7, 8) for i in seen[d]["issues"]],
				                 [("fx_old", old), ("fx_old", 7), ("fx_stale", 8)])
				self.assertEqual(c.business_days(today - timedelta(days=quiet), today), c.FX_WARN_BUSINESS_DAYS)


class TestFxBridged(unittest.TestCase):
	"""O-12 (2D-2): a pair whose provider rate is stale or missing but which every affected hotel has a
	valid dated manual rate for is WARN ``fx_bridged``; one hotel without it keeps the FAIL. Pairs, ages
	and hotels only: never a rate value, never a user."""

	WED = date(2026, 9, 23)

	def pair(self, rate_date, manual, affected=("A", "B"), max_age=4):
		return [{"pair": "EUR/TRY", "provider": "TCMB", "rate_date": rate_date, "max_age_days": max_age,
		         "affected": set(affected), "manual": manual}]

	def test_every_affected_hotel_bridged_by_a_global_or_its_own_manual_rate_warns(self):
		stale = date(2026, 9, 14)
		for manual in ({None: date(2026, 9, 21)}, {"A": date(2026, 9, 21), "B": date(2026, 9, 22)},
		               {"A": date(2026, 9, 21), None: date(2026, 9, 20)}):
			with self.subTest(manual=manual):
				out = c.fx_check(self.pair(stale, manual), self.WED)
				self.assertEqual(out["status"], c.WARN)
				(i,) = out["issues"]
				self.assertEqual((i["reason"], i["status"]), ("fx_bridged", c.WARN))
				self.assertEqual(set(i["params"]), {"pair", "provider", "days", "manual_days"})
				self.assertEqual((i["params"]["pair"], i["params"]["provider"], i["params"]["days"]),
				                 ("EUR/TRY", "TCMB", 9))
		# the oldest manual rate in use is the one it says
		self.assertEqual(c.fx_check(self.pair(stale, {"A": date(2026, 9, 21), "B": date(2026, 9, 22)}),
		                            self.WED)["issues"][0]["params"]["manual_days"], 2)

	def test_a_missing_provider_rate_is_bridged_too(self):
		(i,) = c.fx_check(self.pair(None, {None: date(2026, 9, 22)}), self.WED)["issues"]
		self.assertEqual((i["reason"], i["params"]["days"], i["params"]["manual_days"]), ("fx_bridged", None, 1))

	def test_one_hotel_without_a_manual_rate_keeps_the_fail(self):
		for rate_date, reason in ((date(2026, 9, 14), "fx_stale"), (None, "fx_missing")):
			out = c.fx_check(self.pair(rate_date, {"A": date(2026, 9, 21)}), self.WED)
			self.assertEqual((out["status"], out["issues"][0]["reason"]), (c.FAIL, reason))
		self.assertEqual(c.fx_check(self.pair(date(2026, 9, 14), {}), self.WED)["status"], c.FAIL)

	def test_a_fresh_provider_rate_never_says_bridged(self):
		self.assertEqual(c.fx_check(self.pair(self.WED, {None: self.WED}), self.WED)["status"], c.OK)


class TestContractsLive(unittest.TestCase):
	"""Y-2 (2D-1): an Active contract whose sale window includes today and whose stays are not over
	should have a version on sale. ``live_ends``: when the version on sale ends (None: open-ended);
	``handover``: a version sells from that moment; ``next_start``: the earliest published version
	starting later."""

	def row(self, prop="H1", *, live=True, live_ends=None, handover=False, next_start=None):
		return {"property": prop, "live": live, "live_ends": live_ends, "handover": handover, "next_start": next_start}

	def test_no_version_on_sale_and_none_starting_soon_fails(self):
		for nxt in (None, NOW + timedelta(days=8)):
			with self.subTest(next_start=nxt):
				out = c.contracts_live_check([self.row(live=False, next_start=nxt), self.row("H2")], NOW)
				self.assertEqual((out["key"], out["status"], out["count"], out["properties"]),
				                 ("contracts.live", c.FAIL, 1, ["H1"]))
				self.assertEqual(out["issues"][0]["reason"], "contract_not_selling")
		self.assertIn("contracts.live", c.TITLES)

	def test_one_starting_within_seven_days_warns(self):
		out = c.contracts_live_check([self.row(live=False, next_start=NOW + timedelta(days=6))], NOW)
		self.assertEqual((out["status"], out["issues"][0]["reason"], out["count"]), (c.WARN, "contract_starts_soon", 1))

	def test_the_version_on_sale_ending_soon_with_nothing_after_warns(self):
		ends = self.row(live_ends=NOW + timedelta(days=3))
		out = c.contracts_live_check([ends, self.row("H2", live_ends=NOW + timedelta(days=3), handover=True)], NOW)
		self.assertEqual((out["status"], out["issues"][0]["reason"], out["properties"]),
		                 (c.WARN, "contract_ends_soon", ["H1"]))

	def test_selling_contracts_are_quiet(self):
		rows = [self.row(), self.row(live_ends=NOW + timedelta(days=30)),
		        self.row(live_ends=NOW + timedelta(days=2), handover=True)]
		out = c.contracts_live_check(rows, NOW)
		self.assertEqual((out["status"], out["count"], out["properties"], out["detail"]), (c.OK, 0, [], c.OK_DETAIL))
		self.assertEqual(c.contracts_live_check([], NOW)["status"], c.OK)


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
