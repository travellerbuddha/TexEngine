"""System-status verdicts (ADR-047). Pure: no frappe import.

The Frappe glue (``kamra.tex.ops.status``) counts rows and reads timestamps; the functions
here turn those numbers into checks. A check is a plain dict::

    {"key", "title", "scope": "platform"|"site"|"hotel", "status": "ok"|"warn"|"fail",
     "detail", "count", "since", "issues": [{"reason", "status", "params"}], "properties"?}

``scope``: "platform" checks are shown to platform administrators only; "site" checks (shared
configuration) to every monitor; "hotel" checks count only the viewer's hotels and name the
hotels with a problem in ``properties``. ``detail`` is English text for e-mails and logs; the staff UI translates ``reason`` with
``params`` instead. Nothing here ever carries a secret, a token, guest data or a stack
trace: only counts, ages, job names, currency pairs and hotel names.

Every threshold is a named constant so it can be tuned in one place.
"""

from __future__ import annotations

import html
import re
from collections.abc import Iterable
from datetime import date, datetime, timedelta

OK, WARN, FAIL = "ok", "warn", "fail"
RANK = {OK: 0, WARN: 1, FAIL: 2}

# ─── thresholds ──────────────────────────────────────────────────────────

# a TEX scheduled job is late when its last run is older than this (minutes); FAIL beyond
# JOB_LATE_FAIL_FACTOR times the limit
JOB_MAX_AGE_MINUTES: dict[str, int] = {
	"kamra.tex.scheduler.every_minute": 10,
	"kamra.tex.scheduler.every_5_minutes": 20,
	"kamra.tex.scheduler.outbox_every_5_minutes": 20,
	"kamra.tex.scheduler.every_15_minutes": 45,
	"kamra.tex.scheduler.fx_daily": 26 * 60,
	"kamra.tex.scheduler.daily": 26 * 60,
}
JOB_LATE_FAIL_FACTOR = 3
# TEX job errors (Error Log "TEX job …") counted over this window; FAIL from this many
JOB_ERROR_WINDOW_HOURS = 24
JOB_ERRORS_FAIL = 20

# background jobs waiting in the RQ queues of this bench
QUEUE_BACKLOG_WARN = 500
QUEUE_BACKLOG_FAIL = 5000

# outbox / inbound messages not delivered after this long (minutes): WARN, then FAIL
QUEUE_LATE_WARN_MINUTES = 30
QUEUE_LATE_FAIL_MINUTES = 240

# card charges still Pending after this long (minutes) and started within the window (hours):
# the gateway may hold money whose callback never arrived (or the guest left the checkout)
PAYMENT_PENDING_WARN_MINUTES = 60
PAYMENT_PENDING_WINDOW_HOURS = 48
# a card charge of a gateway TEX cannot ask for its outcome (the Virtual POS) still Pending this long
# after its deadline: FAIL (P1-8); the money may have been taken and nothing will tell TEX
PAYMENT_UNVERIFIED_FAIL_MINUTES = 10
# rejected or failed gateway callbacks (Error Log) counted over this window
CALLBACK_ERROR_WINDOW_HOURS = 24
# a stay whose loyalty earning (or its reversal) failed is shown this long: its points wait for staff (LO-47)
LOYALTY_EARNING_WINDOW_DAYS = 7
# captures TEX refused to count / links paid twice (audit trail) counted over this window
PAYMENT_AUDIT_WINDOW_DAYS = 7
# money kept off every booking (reconciliation, B5): staff act on it within this many hours, and a
# queued automatic refund runs within this many minutes; FAIL beyond
# a booking still holding rooms this long after its hold ended (the expiry runs every 5 minutes): its
# expiry keeps failing and its rooms stay blocked (D9)
EXPIRY_LATE_MINUTES = 20
RECONCILIATION_ACTION_FAIL_HOURS = 24
RECONCILIATION_REFUND_FAIL_MINUTES = 60

# the latest provider rate of a currency pair in use is older than this many business days:
# WARN (weekends are not counted: TCMB and the ECB publish on weekdays). FAIL once it is
# older than the policy's own ``max_age_days`` (calendar days), where pricing refuses it.
FX_WARN_BUSINESS_DAYS = 2

# guest e-mail: failed over the window (FAIL from this many), or still unsent after this long
MAIL_FAILED_WINDOW_HOURS = 24
MAIL_FAILED_FAIL_COUNT = 5
MAIL_UNSENT_WARN_MINUTES = 30
MAIL_UNSENT_FAIL_MINUTES = 240
# rows older than this are not looked at (Frappe clears its e-mail queue after ~31 days)
MAIL_WINDOW_DAYS = 7

# a contract that should sell and has no version on sale is a failure unless one starts within this;
# the version on sale ending within it with nothing after is a warning (Y-2, 2D-1)
CONTRACT_START_WARN_DAYS = 7

# ─── texts ───────────────────────────────────────────────────────────────

TITLES: dict[str, str] = {
	"scheduler": "Scheduler",
	"scheduler.jobs": "TEX scheduled jobs",
	"scheduler.errors": "TEX job errors",
	"workers": "Background workers",
	"encryption_key": "Encryption key",
	"db.snapshot_isolation": "Database snapshot isolation",
	"outbox.pms": "PMS delivery queue",
	"outbox.channel": "Channel ARI queue",
	"channel.inbound": "Channel bookings received",
	"connections": "Integration connections",
	"payments.pending": "Pending card payments",
	"payments.callbacks": "Payment callbacks",
	"payments.reconciliation": "Payments in reconciliation",
	"payments.overpaid": "Bookings paid more than they cost",
	"holds.overdue": "Holds past their deadline",
	"fx.rates": "FX rates",
	"mail.account": "Outgoing e-mail account",
	"mail.delivery": "Guest e-mail delivery",
	"mail.queue": "E-mail queue",
	"contracts.live": "Contracts on sale",
	"loyalty.earnings": "Loyalty earnings",
}

OK_DETAIL = "No problems found."

REASONS: dict[str, str] = {
	"scheduler_disabled": "The scheduler is disabled: no TEX job runs.",
	"scheduler_paused": "The scheduler is paused: no TEX job runs.",
	"maintenance_mode": "The site is in maintenance mode: no TEX job runs.",
	"job_missing": "The TEX job {job} is not registered (run bench migrate).",
	"job_stopped": "The TEX job {job} is stopped.",
	"job_never_ran": "The TEX job {job} has never run.",
	"job_late": "The TEX job {job} last ran {minutes} minutes ago.",
	"job_waiting": "The TEX job {job} has waited {minutes} minutes for a background worker.",
	"job_errors": "{count} TEX job error(s) in the last {hours} hours (see the Error Log).",
	"redis_unreachable": "The background job queue (Redis) cannot be reached.",
	"no_workers": "No background worker is running.",
	"queue_unserved": "No background worker listens on the {queue} queue: the jobs queued there never run.",
	"backlog": "{count} background job(s) are waiting in the queues.",
	"key_missing": "The site has no encryption_key: offers, payment callbacks and webhooks cannot be signed.",
	"snapshot_isolation_on": "MariaDB innodb_snapshot_isolation is ON ({level}): a booking that waited for the last "
	                         "room fails with an error instead of being told it sold out. Set "
	                         "innodb_snapshot_isolation = 0 in the database server's configuration.",
	"dead": "{count} message(s) are dead and will not be retried.",
	"late": "{count} message(s) are late; the oldest has waited {minutes} minutes.",
	"connection_errors": "{count} enabled connection(s) report an error.",
	"payment_pending": "{count} card payment(s) are still pending; the oldest started {minutes} minutes ago.",
	"payment_pending_unverified": "{count} card payment(s) of a gateway TEX cannot ask are still pending after their "
	                              "deadline; the oldest started {minutes} minutes ago. Check them in the bank's panel; "
	                              "if one was charged, record it as a Manual payment with the bank's reference. The "
	                              "alert clears 48 hours after the payment. A payment the bank did not charge can be "
	                              "marked not paid on its page (Payments).",
	"callback_errors": "{count} payment callback(s) failed or were rejected in the last {hours} hours.",
	"overpaid": "{count} payment link(s) were paid more than once in the last {days} days.",
	"capture_mismatch": "{count} gateway capture(s) did not match their charge in the last {days} days.",
	"refund_unknown": "{count} refund(s) the gateway never confirmed: check them at the gateway before refunding "
	                  "again, then record the outcome (Payments → the refund).",
	"refund_conflict": "{count} refund(s) were answered by the gateway differently from the outcome recorded for them: "
	                   "check them at the gateway and record what it actually did (Payments → the refund).",
	"hold_overdue": "{count} booking(s) still hold rooms although their hold ended; the oldest ended {minutes} "
	                "minutes ago: their expiry keeps failing (see the Error Log).",
	"reconciliation_action": "{count} payment(s) are kept off their booking and wait for staff (Payments → the "
	                         "payment); the oldest has waited {hours} hours.",
	"reconciliation_refund": "{count} payment(s) are queued for an automatic refund; the oldest has waited {hours} "
	                         "hours.",
	"loyalty_earning_failed": "{count} stay(s) could not earn or take back their loyalty points in the last {days} "
	                          "days (see the Error Log): the stay was kept; correct the guest's points by hand once "
	                          "the cause is fixed.",
	"bookings_overpaid": "{count} booking(s) hold more money than they cost ({cancelled} of them cancelled): refund "
	                     "the excess, or move it to the booking it was meant for (Payments). A refund still on its "
	                     "way counts as paid until the gateway answers it.",
	"fx_missing": "No {provider} rate for {pair}: prices that need it cannot be computed.",
	"fx_stale": "The latest {provider} rate for {pair} is {days} days old, older than its policy allows "
	            "({max_days}): prices that need it cannot be computed.",
	"fx_old": "The latest {provider} rate for {pair} is {days} days old.",
	"fx_bridged": "The {provider} rate for {pair} is stale or missing: prices use a manual rate dated {manual_days} "
	              "days ago, with each policy's margin on it.",
	"no_outgoing_account": "No default outgoing e-mail account is set up: guest e-mails cannot be sent.",
	"mail_suspended": "Sending e-mail is suspended on this site.",
	"mail_failed": "{count} e-mail(s) failed in the last {hours} hours.",
	"mail_unsent": "{count} e-mail(s) are still unsent; the oldest has waited {minutes} minutes.",
	"contract_not_selling": "{count} active contract(s) within their sale window have no version on sale and none "
	                        "starting within {days} days: they sell nothing.",
	"contract_starts_soon": "{count} active contract(s) within their sale window have no version on sale; one starts "
	                        "within {days} days.",
	"contract_ends_soon": "{count} contract(s) stop selling within {days} days: their version on sale ends and no "
	                      "version starts then.",
	"check_error": "This check could not run (see the Error Log).",
}


def issue(reason: str, status: str, **params) -> dict:
	return {"reason": reason, "status": status, "params": params}


def describe(i: dict) -> str:
	template = REASONS.get(i["reason"], i["reason"])
	try:
		return template.format(**i["params"])
	except (KeyError, IndexError, ValueError):
		return template


def worst(statuses: Iterable[str]) -> str:
	out = OK
	for s in statuses:
		if RANK.get(s, 0) > RANK[out]:
			out = s
	return out


def _stamp(v) -> str | None:
	if v is None:
		return None
	if isinstance(v, datetime):
		return v.replace(microsecond=0).isoformat(sep=" ")
	return str(v)


def make(key: str, issues: list[dict], *, scope: str, since=None, properties: Iterable[str] | None = None,
         count: int | None = None) -> dict:
	"""A check from its issues: the worst issue decides the status and the count."""
	issues = sorted(issues, key=lambda i: -RANK[i["status"]])           # stable: equal ranks keep order
	status = issues[0]["status"] if issues else OK
	out = {
		"key": key, "title": TITLES.get(key, key), "scope": scope, "status": status,
		"detail": " ".join(describe(i) for i in issues) or OK_DETAIL,
		"count": count if count is not None else (int(issues[0]["params"].get("count") or 0) if issues else 0),
		"since": _stamp(since), "issues": issues,
	}
	if scope == "hotel":
		out["properties"] = sorted(set(properties or ()))
	return out


def minutes_since(then: datetime | None, now: datetime) -> int | None:
	if then is None:
		return None
	return max(0, int((now - then).total_seconds() // 60))


def business_days(since: date, today: date) -> int:
	"""Weekdays after ``since`` up to and including ``today``."""
	if today <= since:
		return 0
	days = (today - since).days
	weeks, rest = divmod(days, 7)
	n = weeks * 5
	d = since + timedelta(days=weeks * 7)
	for _ in range(rest):
		d += timedelta(days=1)
		if d.weekday() < 5:
			n += 1
	return n


# ─── platform checks ─────────────────────────────────────────────────────


SCHEDULER_OFF = {"disabled": "scheduler_disabled", "paused": "scheduler_paused", "maintenance": "maintenance_mode"}


def scheduler_check(*, inactive_reason: str | None, live: bool) -> dict:
	"""``inactive_reason``: None, "maintenance", "paused" or "disabled". A switched-off
	scheduler fails a live site; on a developer site it is a warning."""
	issues = []
	if inactive_reason:
		issues.append(issue(SCHEDULER_OFF.get(inactive_reason, "scheduler_disabled"), FAIL if live else WARN))
	return make("scheduler", issues, scope="platform")


def jobs_check(jobs: dict[str, dict], now: datetime, *, live: bool, waiting: dict[str, int] | None = None) -> dict:
	"""``jobs``: {method: {"last_execution": datetime|None, "stopped": bool}} of the Scheduled
	Job Types found for the TEX jobs in ``JOB_MAX_AGE_MINUTES``. ``waiting``: {method: minutes} of the work a
	cron entry only queues (the PMS outbox, LO-08) still waiting in its queue for a worker: late as the job would
	be."""
	issues, since = [], None
	for method, limit in JOB_MAX_AGE_MINUTES.items():
		job = method.rsplit(".", 1)[-1]
		row = jobs.get(method)
		if row is None:
			issues.append(issue("job_missing", FAIL, job=job))
		elif row.get("stopped"):
			issues.append(issue("job_stopped", FAIL, job=job))
		elif not row.get("last_execution"):
			issues.append(issue("job_never_ran", FAIL if live else WARN, job=job))
		else:
			age = minutes_since(row["last_execution"], now)
			if age > limit:
				issues.append(issue("job_late", FAIL if age > limit * JOB_LATE_FAIL_FACTOR else WARN, job=job,
				                    minutes=age))
				since = min(since, row["last_execution"]) if since else row["last_execution"]
		waited = (waiting or {}).get(method)
		if waited is not None and waited > limit:
			issues.append(issue("job_waiting", FAIL if waited > limit * JOB_LATE_FAIL_FACTOR else WARN, job=job,
			                    minutes=waited))
			queued_at = now - timedelta(minutes=waited)
			since = min(since, queued_at) if since else queued_at
	return make("scheduler.jobs", issues, scope="platform", since=since, count=len(issues))


def job_errors_check(count: int, since=None) -> dict:
	issues = []
	if count:
		issues.append(issue("job_errors", FAIL if count >= JOB_ERRORS_FAIL else WARN, count=count,
		                    hours=JOB_ERROR_WINDOW_HOURS))
	return make("scheduler.errors", issues, scope="platform", since=since)


def workers_check(*, reachable: bool, workers: int, backlog: int, live: bool, unserved: Iterable[str] = ()) -> dict:
	"""``unserved``: the queues TEX queues jobs on that no running worker listens on (LO-08: the PMS outbox runs on
	``long``); named only while some worker runs (none at all is ``no_workers``)."""
	issues = []
	if not reachable:
		issues.append(issue("redis_unreachable", FAIL))
	else:
		if workers <= 0:
			issues.append(issue("no_workers", FAIL if live else WARN))
		else:
			issues += [issue("queue_unserved", FAIL if live else WARN, queue=q) for q in unserved]
		if backlog >= QUEUE_BACKLOG_WARN:
			issues.append(issue("backlog", FAIL if backlog >= QUEUE_BACKLOG_FAIL else WARN, count=backlog))
	return make("workers", issues, scope="platform", count=backlog if reachable else 0)


def encryption_key_check(present: bool) -> dict:
	return make("encryption_key", [] if present else [issue("key_missing", FAIL)], scope="platform")


def snapshot_isolation_check(values: dict | None) -> dict:
	"""``values``: {"global": 0|1, "session": 0|1} of the database connection, None when the server
	has no ``innodb_snapshot_isolation`` (before MariaDB 10.6.18: nothing to check). ON fails, the
	server default as well as this connection's (ADR-063)."""
	issues = [issue("snapshot_isolation_on", FAIL, level=f"@@{level.upper()}")
	          for level in ("global", "session") if values and int(values.get(level) or 0)]
	return make("db.snapshot_isolation", issues, scope="platform", count=len(issues))


# ─── hotel checks ────────────────────────────────────────────────────────


def queue_check(key: str, *, dead: int, dead_since=None, late: int = 0, late_since: datetime | None = None,
                now: datetime, properties: Iterable[str] = ()) -> dict:
	"""An outbox or inbound queue: any dead message fails (nothing retries it); messages still
	waiting after ``QUEUE_LATE_WARN_MINUTES`` warn, after ``QUEUE_LATE_FAIL_MINUTES`` fail.
	``late`` counts only the messages older than the warning threshold."""
	issues = []
	if dead:
		issues.append(issue("dead", FAIL, count=dead))
	age = minutes_since(late_since, now)
	if late and age is not None and age >= QUEUE_LATE_WARN_MINUTES:
		issues.append(issue("late", FAIL if age >= QUEUE_LATE_FAIL_MINUTES else WARN, count=late, minutes=age))
	return make(key, issues, scope="hotel", since=dead_since if dead else late_since, properties=properties)


def connections_check(errors: int, properties: Iterable[str] = ()) -> dict:
	return make("connections", [issue("connection_errors", WARN, count=errors)] if errors else [], scope="hotel",
	            properties=properties)


def pending_payments_check(count: int, oldest: datetime | None, now: datetime,
                           properties: Iterable[str] = (), *, unverified: int = 0,
                           unverified_since: datetime | None = None) -> dict:
	"""Card charges still Pending: a WARN (the guest may have left the checkout, or its news is late),
	and a FAIL for ``unverified`` ones TEX cannot ask its gateway about, past their deadline (P1-8)."""
	issues = []
	if unverified:
		issues.append(issue("payment_pending_unverified", FAIL, count=unverified,
		                    minutes=minutes_since(unverified_since, now)))
	if count:
		issues.append(issue("payment_pending", WARN, count=count, minutes=minutes_since(oldest, now)))
	since = min((t for t in (oldest, unverified_since) if t), default=None)
	return make("payments.pending", issues, scope="hotel", since=since, properties=properties)


def callbacks_check(*, errors: int, overpaid: int, mismatches: int, refunds_unknown: int = 0,
                    refund_conflicts: int = 0, properties: Iterable[str] = ()) -> dict:
	issues = []
	if refund_conflicts:
		# the books and the gateway disagree about money that left (third review of ADR-044)
		issues.append(issue("refund_conflict", FAIL, count=refund_conflicts))
	if refunds_unknown:
		# the money may be gone or not: nothing refunds it again until staff checked (ADR-044 review)
		issues.append(issue("refund_unknown", FAIL, count=refunds_unknown))
	if mismatches:
		issues.append(issue("capture_mismatch", FAIL, count=mismatches, days=PAYMENT_AUDIT_WINDOW_DAYS))
	if errors:
		issues.append(issue("callback_errors", WARN, count=errors, hours=CALLBACK_ERROR_WINDOW_HOURS))
	if overpaid:
		issues.append(issue("overpaid", WARN, count=overpaid, days=PAYMENT_AUDIT_WINDOW_DAYS))
	return make("payments.callbacks", issues, scope="hotel", properties=properties)


def overdue_holds_check(count: int, oldest: datetime | None, now: datetime, properties: Iterable[str] = ()) -> dict:
	"""D9: bookings still holding rooms ``EXPIRY_LATE_MINUTES`` after their hold ended, with no payment
	attempt open: their expiry keeps failing and the rooms are blocked."""
	issues = [issue("hold_overdue", FAIL, count=count, minutes=minutes_since(oldest, now))] if count else []
	return make("holds.overdue", issues, scope="hotel", since=oldest, properties=properties)


def reconciliation_check(*, action: int, action_since: datetime | None, refund: int, refund_since: datetime | None,
                         now: datetime, properties: Iterable[str] = ()) -> dict:
	"""Money kept off every booking (B5): waiting for staff (``Action Required``) or for its queued
	automatic refund, each with the age of its oldest item in hours."""
	issues = []
	for reason, count, since, fail_minutes in (
			("reconciliation_action", action, action_since, RECONCILIATION_ACTION_FAIL_HOURS * 60),
			("reconciliation_refund", refund, refund_since, RECONCILIATION_REFUND_FAIL_MINUTES)):
		if count:
			age = minutes_since(since, now)
			issues.append(issue(reason, FAIL if age is not None and age >= fail_minutes else WARN, count=count,
			                    hours=round(age / 60, 1) if age is not None else None))
	oldest = min((t for t in (action_since, refund_since) if t), default=None)
	return make("payments.reconciliation", issues, scope="hotel", since=oldest, properties=properties)


def loyalty_earnings_check(count: int, properties: Iterable[str] = ()) -> dict:
	"""LO-47: stays whose loyalty earning or reversal failed (and was undone alone, the stay kept) in the last
	days."""
	issues = [issue("loyalty_earning_failed", WARN, count=count, days=LOYALTY_EARNING_WINDOW_DAYS)] if count else []
	return make("loyalty.earnings", issues, scope="hotel", properties=properties)


def overpaid_bookings_check(count: int, cancelled: int, oldest: datetime | None,
                            properties: Iterable[str] = ()) -> dict:
	"""P1-7 (audit 2B): bookings holding more money than they cost (``cancelled`` of them cancelled),
	since the oldest one's last change: staff refund the excess or move it."""
	issues = [issue("bookings_overpaid", WARN, count=count, cancelled=cancelled)] if count else []
	return make("payments.overpaid", issues, scope="hotel", since=oldest, properties=properties)


def _bridge(p: dict, today: date) -> int | None:
	"""The age in days of the oldest manual rate that bridges a stale or missing provider rate for every
	hotel the pair concerns (a hotel's own rate or a global one, the newer of the two), or None when a
	hotel has none. ``p["manual"]``: {hotel or None (every hotel): the rate's date}."""
	manual = p.get("manual") or {}
	if not manual:
		return None
	hotels = p.get("affected") or set()
	best = [max((d for d in (manual.get(h), manual.get(None)) if d), default=None) for h in sorted(hotels)] \
		if hotels else [manual.get(None)]
	if any(d is None for d in best):
		return None
	return (today - min(best)).days


def fx_check(pairs: list[dict], today: date, properties: Iterable[str] = ()) -> dict:
	"""``pairs``: [{"pair": "EUR/TRY", "provider", "rate_date": date|None, "max_age_days": int,
	"affected": the hotels it concerns, "manual": {hotel or None: date of a valid manual rate}}], one per
	provider currency pair an active FX policy of these hotels uses. A stale or missing provider rate
	that every affected hotel has a manual rate for (O-12, ADR-069) is a WARN ``fx_bridged``: prices are
	still computed, on the manual rate; one hotel without it keeps the FAIL."""
	issues = []
	for p in sorted(pairs, key=lambda p: (p["pair"], p["provider"])):
		base = {"pair": p["pair"], "provider": p["provider"]}
		max_days = int(p.get("max_age_days") or 4)
		days = (today - p["rate_date"]).days if p.get("rate_date") is not None else None
		if days is None or days > max_days:
			manual_days = _bridge(p, today)
			if manual_days is not None:
				issues.append(issue("fx_bridged", WARN, days=days, manual_days=manual_days, **base))
			elif days is None:
				issues.append(issue("fx_missing", FAIL, **base))
			else:
				issues.append(issue("fx_stale", FAIL, days=days, max_days=max_days, **base))
		elif business_days(p["rate_date"], today) > FX_WARN_BUSINESS_DAYS:
			issues.append(issue("fx_old", WARN, days=days, max_days=max_days, **base))
	return make("fx.rates", issues, scope="hotel", properties=properties, count=len(issues))


def contracts_live_check(rows: list[dict], now: datetime) -> dict:
	"""Y-2 (2D-1): the Active contracts whose sale window includes today and whose stays are not over,
	one row each: {"property", "live": a version on sale now, "live_ends": when it ends (None:
	open-ended), "handover": a version sells from that moment, "next_start": the earliest published
	version starting later}. FAIL: none on sale and none starting within ``CONTRACT_START_WARN_DAYS``;
	WARN: none on sale but one starts within it, or the one on sale ends within it and nothing sells
	from then (data a withdraw broke before 2D-1). Counts and hotels only."""
	soon = now + timedelta(days=CONTRACT_START_WARN_DAYS)
	kinds: dict[str, list[str]] = {"contract_not_selling": [], "contract_starts_soon": [], "contract_ends_soon": []}
	for r in rows:
		if not r["live"]:
			starts = r.get("next_start")
			kinds["contract_starts_soon" if starts is not None and starts <= soon else "contract_not_selling"].append(
				r["property"])
		elif r.get("live_ends") is not None and r["live_ends"] <= soon and not r.get("handover"):
			kinds["contract_ends_soon"].append(r["property"])
	level = {"contract_not_selling": FAIL, "contract_starts_soon": WARN, "contract_ends_soon": WARN}
	issues = [issue(k, level[k], count=len(v), days=CONTRACT_START_WARN_DAYS) for k, v in kinds.items() if v]
	return make("contracts.live", issues, scope="hotel", properties={p for v in kinds.values() for p in v})


def mail_account_check(*, has_account: bool, suspended: bool, production: bool) -> dict:
	"""SMTP is an owner input: a missing account fails a production site (``tex_production``)
	and warns anywhere else."""
	issues = []
	if not has_account:
		issues.append(issue("no_outgoing_account", FAIL if production else WARN))
	if suspended:
		issues.append(issue("mail_suspended", WARN))
	return make("mail.account", issues, scope="site")


def mail_check(key: str, *, failed: int, unsent: int, oldest_unsent: datetime | None, now: datetime,
               properties: Iterable[str] = (), scope: str = "hotel") -> dict:
	"""Delivery of queued e-mail: ``unsent`` counts only mails older than the warning threshold."""
	issues = []
	if failed:
		issues.append(issue("mail_failed", FAIL if failed >= MAIL_FAILED_FAIL_COUNT else WARN, count=failed,
		                    hours=MAIL_FAILED_WINDOW_HOURS))
	age = minutes_since(oldest_unsent, now)
	if unsent and age is not None and age >= MAIL_UNSENT_WARN_MINUTES:
		issues.append(issue("mail_unsent", FAIL if age >= MAIL_UNSENT_FAIL_MINUTES else WARN, count=unsent,
		                    minutes=age))
	return make(key, issues, scope=scope, since=oldest_unsent if unsent else None, properties=properties)


def check_error(key: str, scope: str) -> dict:
	return make(key, [issue("check_error", FAIL)], scope=scope)


# ─── transitions and alerts ──────────────────────────────────────────────


def state_of(checks: list[dict]) -> dict[str, str]:
	"""What is remembered between runs: the status of every check that is not ok."""
	return {c["key"]: c["status"] for c in checks if c["status"] != OK}


def transitions(previous: dict[str, str], current: dict[str, str]) -> dict:
	"""A missing key is ok. A check that gets worse (ok→warn, ok→fail, warn→fail) is alerted;
	one that comes back to ok is a recovery. fail→warn is recorded but not sent."""
	worse, recovered = [], []
	for key in sorted(set(previous) | set(current)):
		before, after = previous.get(key, OK), current.get(key, OK)
		if RANK.get(after, 0) > RANK.get(before, 0):
			worse.append(key)
		elif after == OK and before != OK:
			recovered.append(key)
	return {"worse": worse, "recovered": recovered, "changed": previous != current}


MAX_ALERT_RECIPIENTS = 20


def parse_recipients(raw: str | None) -> list[str]:
	"""E-mail addresses from a comma, semicolon or newline separated list, deduplicated."""
	out, seen = [], set()
	for part in re.split(r"[\s,;]+", raw or ""):
		p = part.strip()
		if p and p.lower() not in seen:
			seen.add(p.lower())
			out.append(p)
	return out


def _line(c: dict) -> str:
	where = f" (hotels: {', '.join(c['properties'])})" if c.get("properties") else ""
	return f"[{c['status'].upper()}] {c.get('title') or c['key']}: {c.get('detail') or ''}{where}"


def alert_message(site: str, checks: list[dict], worse: list[str], recovered: list[str],
                  at: datetime) -> tuple[str, str]:
	"""(subject, html) of one notice for all the changes of a run."""
	by_key = {c["key"]: c for c in checks}
	bad = [by_key[k] for k in worse if k in by_key]
	good = [by_key.get(k) or {"key": k, "title": TITLES.get(k, k), "status": OK, "detail": OK_DETAIL}
	        for k in recovered]
	parts = []
	if bad:
		parts.append(f"{worst(c['status'] for c in bad).upper()}: " + ", ".join(c.get("title") or c["key"] for c in bad))
	if good:
		parts.append("recovered: " + ", ".join(c.get("title") or c["key"] for c in good))
	subject = f"[TEX] {site} system status: " + "; ".join(parts)
	rows = [f"<p>TEX system status on <b>{html.escape(site)}</b> changed at {html.escape(_stamp(at) or '')}.</p>"]
	if bad:
		rows.append("<p>Needs attention:</p><ul>" + "".join(f"<li>{html.escape(_line(c))}</li>" for c in bad) + "</ul>")
	if good:
		rows.append("<p>Back to normal:</p><ul>" + "".join(f"<li>{html.escape(_line(c))}</li>" for c in good)
		            + "</ul>")
	rows.append("<p>Details: TEX → Settings → System status.</p>")
	return subject[:140], "\n".join(rows)


# ─── e-mail delivery (Email Queue → TEX Communication) ───────────────────

# Frappe's Email Queue status → TEX Communication status. "Sent" means the mail server took
# it (TEX never claims "Delivered"). Not Sent, Sending and Partially Sent (a single-recipient
# TEX mail being retried) stay Queued. "Expired" existed in older Frappe versions.
QUEUE_TO_COMMUNICATION = {"Sent": "Sent", "Error": "Failed", "Expired": "Failed"}

_EXC = re.compile(r"^([A-Za-z_][\w.]{0,120})(?::|$)")
_SMTP_CODE = re.compile(r"\b([45]\d\d)\b")


def communication_status(queue_status: str | None) -> str | None:
	return QUEUE_TO_COMMUNICATION.get(queue_status or "")


def delivery_error(error: str | None) -> str | None:
	"""A short, address-free reason from an Email Queue error (a traceback):
	``smtplib.SMTPRecipientsRefused: {'a@b.c': (550, …)}`` → ``SMTPRecipientsRefused (550)``."""
	lines = [x.strip() for x in (error or "").splitlines() if x.strip()]
	if not lines:
		return None
	last = lines[-1]
	m = _EXC.match(last)
	name = m.group(1).rsplit(".", 1)[-1] if m else "Error"
	code = _SMTP_CODE.search(last[m.end():] if m else last)
	return f"{name} ({code.group(1)})" if code else name
