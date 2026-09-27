"""System status (ADR-047): the numbers behind each check, read from the database, Redis and
the site config (Frappe glue). ``kamra.tex.ops.checks`` judges them.

- Hotel-scoped checks count only rows of ``properties`` (None = every hotel) and name the
  hotels that have a problem.
- Platform checks (scheduler, TEX jobs, TEX job errors, workers, encryption key, database
  snapshot isolation, the whole e-mail queue) run only when ``platform`` is set: they describe
  the installation, not a hotel.
- A probe that raises becomes a failed check; the error goes to the Error Log without frame
  locals and never stops the other probes. Nothing read here is returned raw: only counts,
  ages, job names, currency pairs and hotel names reach the checks.
"""

from __future__ import annotations

from datetime import timedelta

import frappe
from frappe.utils import cint, get_datetime, getdate, now_datetime

from kamra.tex.ops import checks as C
from kamra.tex.security.audit import log_exception

TEX_JOBS = tuple(C.JOB_MAX_AGE_MINUTES)
FX_LOOKBACK_DAYS = 60


def production() -> bool:
	"""The site is flagged live (``tex_production`` in site_config)."""
	return bool(frappe.conf.get("tex_production"))


def live() -> bool:
	"""A site that must run everything: flagged live, or simply not a developer site."""
	return production() or not frappe.conf.get("developer_mode")


def _scope(column: str, props: frozenset[str] | None, params: dict) -> str:
	if props is None:
		return ""
	params["props"] = tuple(sorted(props)) or ("",)
	return f" AND {column} IN %(props)s"


def _sum(rows) -> tuple[int, object, set[str]]:
	"""(count, oldest, hotels) of rows grouped by hotel: {property, n, since}."""
	count = sum(int(r.n or 0) for r in rows)
	oldest = min((r.since for r in rows if r.since), default=None)
	return count, oldest, {r.property for r in rows if r.property and r.n}


# ─── platform ────────────────────────────────────────────────────────────


def _scheduler(now) -> dict:
	from frappe.utils.scheduler import is_scheduler_disabled

	reason = None
	if frappe.local.conf.get("maintenance_mode"):
		reason = "maintenance"
	elif frappe.local.conf.get("pause_scheduler"):
		reason = "paused"
	elif is_scheduler_disabled(verbose=False):
		reason = "disabled"
	return C.scheduler_check(inactive_reason=reason, live=live())


def last_runs() -> dict[str, dict]:
	"""{method: {last_execution, stopped}} of the TEX jobs' Scheduled Job Types."""
	jobs: dict[str, dict] = {}
	for r in frappe.get_all("Scheduled Job Type", filters={"method": ("in", TEX_JOBS)},
	                        fields=["method", "last_execution", "stopped"]):
		seen = jobs.get(r.method)
		last = get_datetime(r.last_execution) if r.last_execution else None
		if seen is None or (last and (not seen["last_execution"] or last > seen["last_execution"])):
			jobs[r.method] = {"last_execution": last, "stopped": bool(r.stopped)}
	return jobs


def _jobs(now) -> dict:
	return C.jobs_check(last_runs(), now, live=live())


def _job_errors(now) -> dict:
	# a booking whose expiry failed is logged on its own (the job goes on with the others, D9)
	row = frappe.db.sql("""SELECT COUNT(*) n, MIN(creation) since FROM `tabError Log`
	                       WHERE (method LIKE 'TEX job %%' OR method LIKE 'TEX booking expiry failed %%')
	                         AND creation >= %(t)s""",
	                    {"t": now - timedelta(hours=C.JOB_ERROR_WINDOW_HOURS)}, as_dict=True)[0]
	return C.job_errors_check(int(row.n or 0), since=row.since)


def queue_probe() -> dict:
	"""{reachable, workers, backlog} of this bench's RQ queues. Never raises: an unreachable
	Redis is a finding, not an error. One connection attempt (Frappe retries five times)."""
	try:
		from frappe.utils.background_jobs import generate_qname, get_queue_list, get_redis_conn
		from rq import Queue, Worker

		connect = getattr(get_redis_conn, "retry_with", None)
		if connect:
			from tenacity import stop_after_attempt

			conn = connect(stop=stop_after_attempt(1))()
		else:
			conn = get_redis_conn()
		conn.ping()
		names = {generate_qname(q) for q in get_queue_list()}
		backlog = sum(Queue(n, connection=conn).count for n in names)
		workers = [w for w in Worker.all(connection=conn) if set(w.queue_names()) & names]
		return {"reachable": True, "workers": len(workers), "backlog": int(backlog)}
	except Exception:
		return {"reachable": False, "workers": 0, "backlog": 0}


def _workers(now) -> dict:
	return C.workers_check(**queue_probe(), live=live())


def _encryption_key(now) -> dict:
	# presence only: the key itself never leaves site_config
	return C.encryption_key_check(bool(frappe.local.conf.get("encryption_key")))


def _snapshot_isolation(now) -> dict:
	from kamra.tex.ops import snapshot_isolation

	return C.snapshot_isolation_check(snapshot_isolation.values())


def _mail_queue(now) -> dict:
	failed = frappe.db.sql("""SELECT COUNT(*) FROM `tabEmail Queue` WHERE status = 'Error' AND modified >= %(t)s""",
	                       {"t": now - timedelta(hours=C.MAIL_FAILED_WINDOW_HOURS)})[0][0]
	row = frappe.db.sql("""SELECT COUNT(*) n, MIN(creation) since FROM `tabEmail Queue`
	                       WHERE status IN ('Not Sent', 'Sending', 'Partially Sent') AND creation < %(cut)s
	                         AND creation >= %(start)s AND (send_after IS NULL OR send_after <= %(now)s)""",
	                    {"cut": now - timedelta(minutes=C.MAIL_UNSENT_WARN_MINUTES),
	                     "start": now - timedelta(days=C.MAIL_WINDOW_DAYS), "now": now}, as_dict=True)[0]
	return C.mail_check("mail.queue", failed=int(failed or 0), unsent=int(row.n or 0), oldest_unsent=row.since,
	                    now=now, scope="platform")


# ─── hotels ──────────────────────────────────────────────────────────────


def _outbox(key: str, kind: str, props, now) -> dict:
	"""Delivery queue of enabled connections (a disabled connection's messages wait for it)."""
	params = {"kind": kind, "cut": now - timedelta(minutes=C.QUEUE_LATE_WARN_MINUTES)}
	cond = _scope("o.property", props, params)
	base = f"""FROM `tabTEX Integration Outbox` o
	           JOIN `tabTEX Integration Connection` c ON c.name = o.connection AND c.enabled = 1
	           WHERE o.kind = %(kind)s{cond}"""
	dead = frappe.db.sql(f"SELECT o.property, COUNT(*) n, MIN(o.creation) since {base} AND o.status = 'Dead' "
	                     "GROUP BY o.property", params, as_dict=True)
	late = frappe.db.sql(f"SELECT o.property, COUNT(*) n, MIN(o.creation) since {base} "
	                     "AND o.status IN ('Pending', 'Failed') AND o.creation < %(cut)s GROUP BY o.property",
	                     params, as_dict=True)
	d, d_since, d_props = _sum(dead)
	lt, l_since, l_props = _sum(late)
	return C.queue_check(key, dead=d, dead_since=d_since, late=lt, late_since=l_since, now=now,
	                     properties=d_props | l_props)


def _outbox_pms(props, now) -> dict:
	return _outbox("outbox.pms", "Reservation", props, now)


def _outbox_channel(props, now) -> dict:
	return _outbox("outbox.channel", "ARI", props, now)


def _channel_inbound(props, now) -> dict:
	"""Bookings a channel sent: a dead one is a sale TEX never applied, whatever the connection."""
	params = {"cut": now - timedelta(minutes=C.QUEUE_LATE_WARN_MINUTES)}
	cond = _scope("property", props, params)
	dead = frappe.db.sql(f"""SELECT property, COUNT(*) n, MIN(creation) since FROM `tabTEX Channel Inbound`
	                         WHERE status = 'Dead'{cond} GROUP BY property""", params, as_dict=True)
	late = frappe.db.sql(f"""SELECT property, COUNT(*) n, MIN(creation) since FROM `tabTEX Channel Inbound`
	                         WHERE status IN ('Received', 'Failed') AND creation < %(cut)s{cond}
	                         GROUP BY property""", params, as_dict=True)
	d, d_since, d_props = _sum(dead)
	lt, l_since, l_props = _sum(late)
	return C.queue_check("channel.inbound", dead=d, dead_since=d_since, late=lt, late_since=l_since, now=now,
	                     properties=d_props | l_props)


def _connections(props, now) -> dict:
	params: dict = {}
	cond = _scope("property", props, params)
	rows = frappe.db.sql(f"""SELECT property, COUNT(*) n, NULL since FROM `tabTEX Integration Connection`
	                         WHERE enabled = 1 AND IFNULL(last_error, '') != ''{cond} GROUP BY property""",
	                     params, as_dict=True)
	n, _since, hotels = _sum(rows)
	return C.connections_check(n, hotels)


def gateway_providers() -> tuple[str, ...]:
	from kamra.tex.payments.providers import REGISTRY

	return tuple(sorted(name for name, cls in REGISTRY.items() if cls.gateway))


def _payments_pending(props, now) -> dict:
	params = {"gw": gateway_providers(), "cut": now - timedelta(minutes=C.PAYMENT_PENDING_WARN_MINUTES),
	          "start": now - timedelta(hours=C.PAYMENT_PENDING_WINDOW_HOURS)}
	cond = _scope("property", props, params)
	rows = frappe.db.sql(f"""SELECT property, COUNT(*) n, MIN(creation) since FROM `tabTEX Payment Transaction`
	                         WHERE txn_type = 'Charge' AND status = 'Pending' AND provider IN %(gw)s
	                           AND creation < %(cut)s AND creation >= %(start)s{cond} GROUP BY property""",
	                     params, as_dict=True)
	n, oldest, hotels = _sum(rows)
	return C.pending_payments_check(n, oldest, now, hotels)


def _payments_callbacks(props, now) -> dict:
	"""Rejected or failed gateway callbacks (Error Log, titled with the transaction), captures
	TEX refused to count and links paid twice (audit trail)."""
	titles = frappe.db.sql("""SELECT method FROM `tabError Log` WHERE creation >= %(t)s
	                          AND (method LIKE 'TEX payment callback rejected %%'
	                               OR method LIKE 'TEX payment callback error %%')""",
	                       {"t": now - timedelta(hours=C.CALLBACK_ERROR_WINDOW_HOURS)}, pluck=True)
	txns = sorted({t.rsplit(" ", 1)[-1] for t in titles if t})
	owner = dict(frappe.get_all("TEX Payment Transaction", filters={"name": ("in", txns or [""])},
	                            fields=["name", "property"], as_list=True))
	errors = [owner.get(t.rsplit(" ", 1)[-1]) for t in titles if t]
	errors = [p for p in errors if p and (props is None or p in props)]
	since = now - timedelta(days=C.PAYMENT_AUDIT_WINDOW_DAYS)
	audit_filters = [["event_time", "is", "set"], ["event_time", ">=", since]]
	if props is not None:
		audit_filters.append(["property", "in", sorted(props) or [""]])
	mismatches = frappe.get_all("TEX Audit Event", filters=[*audit_filters, ["action", "=", "payment.capture_mismatch"]],
	                            pluck="property")
	overpaid = frappe.get_all("TEX Audit Event", filters=[*audit_filters, ["action", "=", "payment_link.overpaid"]],
	                          pluck="property")
	# refunds the gateway never answered (``payments.service.RefundUnknown``), at any age, and any
	# refund still Pending after a few minutes (the run asking for it died): staff check them at
	# the gateway (G-45 re-review F2)
	from kamra.tex.payments import service as pay

	unknown_filters = {"txn_type": "Refund", "status": "Pending"}
	if props is not None:
		unknown_filters["property"] = ("in", sorted(props) or [""])
	unknown = [r.property for r in frappe.get_all("TEX Payment Transaction", filters=unknown_filters,
	                                              fields=["property", "error_code", "creation"])
	           if pay.stuck(r, now)]
	# a gateway answer that contradicts the outcome recorded for a refund, at any age, until staff
	# record what the gateway actually did (third and fourth review of ADR-044)
	conflict_filters = {"action": "payment.refund_outcome_conflict"}
	if props is not None:
		conflict_filters["property"] = ("in", sorted(props) or [""])
	resolved = set(frappe.get_all("TEX Audit Event", filters={"action": "payment.refund_conflict_resolved"},
	                              pluck="reference_name"))
	conflicts = [r.property for r in frappe.get_all("TEX Audit Event", filters=conflict_filters,
	                                                fields=["property", "reference_name"])
	             if r.reference_name not in resolved]
	hotels = {p for p in (*errors, *mismatches, *overpaid, *unknown, *conflicts) if p}
	return C.callbacks_check(errors=len(errors), overpaid=len(overpaid), mismatches=len(mismatches),
	                         refunds_unknown=len(unknown), refund_conflicts=len(conflicts), properties=hotels)


def _overdue_holds(props, now) -> dict:
	"""D9: bookings still holding rooms after their hold ended, beyond the expiry's own delay, with no
	payment attempt open."""
	params = {"cut": now - timedelta(minutes=C.EXPIRY_LATE_MINUTES), "now": now, "holding": ("Pending Payment", "Held")}
	cond = _scope("b.property", props, params)
	rows = frappe.db.sql(f"""SELECT b.property, COUNT(DISTINCT b.name) n, MIN(r.hold_expires_on) since
	                         FROM `tabTEX Booking` b JOIN `tabReservation` r ON r.tex_booking = b.name
	                         WHERE b.status IN %(holding)s AND r.status IN %(holding)s AND r.hold_expires_on < %(cut)s
	                           AND (b.payment_attempt_until IS NULL OR b.payment_attempt_until < %(now)s){cond}
	                         GROUP BY b.property""", params, as_dict=True)
	n, oldest, hotels = _sum(rows)
	return C.overdue_holds_check(n, oldest, now, hotels)


def _payments_reconciliation(props, now) -> dict:
	"""Money kept off every booking (B5), per state, aged from when it went to reconciliation."""
	params: dict = {}
	cond = _scope("t.property", props, params)
	rows = frappe.db.sql(f"""SELECT t.property, t.reconciliation state, COUNT(*) n,
	                                MIN(IFNULL((SELECT MAX(a.event_time) FROM `tabTEX Audit Event` a
	                                            WHERE a.action = 'payment.reconciliation_required'
	                                              AND a.reference_name = t.name), t.completed_at)) since
	                         FROM `tabTEX Payment Transaction` t
	                         WHERE t.reconciliation IN ('Action Required', 'Refund Queued'){cond}
	                         GROUP BY t.property, t.reconciliation""", params, as_dict=True)
	action, action_since, hotels = _sum([r for r in rows if r.state == "Action Required"])
	refund, refund_since, refund_hotels = _sum([r for r in rows if r.state == "Refund Queued"])
	return C.reconciliation_check(action=action, action_since=action_since, refund=refund, refund_since=refund_since,
	                              now=now, properties=hotels | refund_hotels)


def _bookings_overpaid(props, now) -> dict:
	"""P1-7: bookings (not drafts) holding more money than they cost, per hotel; the cancelled ones
	counted apart; aged from the oldest one's last change."""
	params: dict = {}
	cond = _scope("property", props, params)
	rows = frappe.db.sql(f"""SELECT property, COUNT(*) n, SUM(status = 'Cancelled') cancelled, MIN(modified) since
	                         FROM `tabTEX Booking` WHERE paid_amount > total_amount AND status != 'Draft'{cond}
	                         GROUP BY property""", params, as_dict=True)
	n, oldest, hotels = _sum(rows)
	return C.overpaid_bookings_check(n, sum(int(r.cancelled or 0) for r in rows), oldest, hotels)


def fx_pairs(props, now) -> list[dict]:
	"""The provider currency pairs the active FX policies of these hotels (and the global
	ones) use, each with the date of its latest rate as pricing would find it."""
	from kamra.tex.commercial.context import provider_rates
	from kamra.tex.commercial.revisions import as_of
	from kamra.tex.pricing import fx as fx_math
	from kamra.tex.pricing.model import Unsellable

	policies = [r for r in as_of("TEX FX Policy", now, fields=("name", "property", "from_currency", "to_currency",
	                                                             "mode", "provider", "rate_type", "max_age_days"))
	            if r.mode != "MANUAL" and r.provider and (props is None or not r.property or r.property in props)]
	wanted: dict[tuple, dict] = {}
	for r in policies:
		key = (r.provider, r.rate_type or "FOREX_SELLING", r.from_currency, r.to_currency)
		w = wanted.setdefault(key, {"max_age_days": int(r.max_age_days or 4), "hotels": set()})
		w["max_age_days"] = min(w["max_age_days"], int(r.max_age_days or 4))
		if r.property:
			w["hotels"].add(r.property)
	rates: dict[str, tuple] = {}
	pairs = []
	for (provider, rate_type, frm, to), w in sorted(wanted.items()):
		if provider not in rates:
			rates[provider] = provider_rates(provider, now, FX_LOOKBACK_DAYS)
		try:
			_rate, _id, rate_date = fx_math.provider_rate(rates[provider], provider, rate_type, frm, to, now.date())
		except Unsellable:
			rate_date = None
		pairs.append({"pair": f"{frm}/{to}", "provider": provider, "rate_date": rate_date,
		              "max_age_days": w["max_age_days"], "hotels": w["hotels"]})
	return pairs


def _fx(props, now) -> dict:
	pairs = fx_pairs(props, now)
	out = C.fx_check(pairs, now.date())
	bad = {i["params"]["pair"] + "|" + i["params"]["provider"] for i in out["issues"]}
	hotels = set()
	for p in pairs:
		if f"{p['pair']}|{p['provider']}" in bad:
			hotels |= p["hotels"] if p["hotels"] else (set(props) if props is not None else set())
	out["properties"] = sorted(hotels)
	return out


def _contracts_live(props, now) -> dict:
	"""Y-2 (2D-1): the Active contracts that should sell now and what their versions say
	(``checks.contracts_live_check``). A contract should sell when its sale window includes today and its
	stays are not over. Its dates are compared in Python, never by a date filter: an empty ``sale_from``
	is "since always", an empty ``sale_to`` or ``stay_to`` "for ever" (NEW-1, ADR-064)."""
	from kamra.tex.pricing import versions

	filters: dict = {"status": "Active"}
	if props is not None:
		filters["property"] = ("in", sorted(props) or [""])
	today = now.date()
	due = [c for c in frappe.get_all("TEX Contract", filters=filters,
	                                 fields=["name", "property", "sale_from", "sale_to", "stay_to"])
	       if (not c.sale_from or getdate(c.sale_from) <= today) and (not c.sale_to or getdate(c.sale_to) >= today)
	       and (not c.stay_to or getdate(c.stay_to) >= today)]
	headers: dict[str, list] = {}
	if due:
		for v in frappe.get_all("TEX Contract Version",
		                        filters={"contract": ("in", [c.name for c in due]),
		                                 "status": ("in", list(versions.SELLABLE_HISTORY))},
		                        fields=["contract", "name", "version_no", "status", "effective_from", "active_to"]):
			headers.setdefault(v.contract, []).append(versions.VersionHeader(
				v.name, int(v.version_no or 0), v.status, get_datetime(v.effective_from) if v.effective_from else None,
				get_datetime(v.active_to) if v.active_to else None))
	rows = []
	for c in due:
		hs = headers.get(c.name, [])
		live = versions.active_version(hs, now)
		ends = live.active_to if live else None
		later = [h.effective_from for h in hs if h.status == "Published" and h.effective_from and h.effective_from > now]
		rows.append({"property": c.property, "live": live is not None, "live_ends": ends,
		             "handover": bool(ends and versions.active_version(hs, ends)), "next_start": min(later, default=None)})
	return C.contracts_live_check(rows, now)


def outgoing_account() -> bool:
	return bool(frappe.db.exists("Email Account", {"enable_outgoing": 1, "default_outgoing": 1}))


def _mail_account(props, now) -> dict:
	suspended = bool(cint(frappe.conf.get("mute_emails"))) or cint(frappe.db.get_default("suspend_email_queue")) == 1
	return C.mail_account_check(has_account=outgoing_account(), suspended=suspended, production=production())


def _mail_delivery(props, now) -> dict:
	"""Guest e-mail as staff see it: TEX Communication rows, whose status follows the e-mail
	queue (``services.mail_status``). Rows never linked to a queued mail are not judged."""
	params = {"failed_from": now - timedelta(hours=C.MAIL_FAILED_WINDOW_HOURS),
	          "cut": now - timedelta(minutes=C.MAIL_UNSENT_WARN_MINUTES),
	          "start": now - timedelta(days=C.MAIL_WINDOW_DAYS)}
	cond = _scope("property", props, params)
	failed = frappe.db.sql(f"""SELECT property, COUNT(*) n, MIN(creation) since FROM `tabTEX Communication`
	                           WHERE channel = 'Email' AND direction = 'Outbound' AND status = 'Failed'
	                             AND creation >= %(failed_from)s{cond} GROUP BY property""", params, as_dict=True)
	unsent = frappe.db.sql(f"""SELECT property, COUNT(*) n, MIN(creation) since FROM `tabTEX Communication`
	                           WHERE channel = 'Email' AND direction = 'Outbound' AND status = 'Queued'
	                             AND IFNULL(email_queue, '') != '' AND creation < %(cut)s
	                             AND creation >= %(start)s{cond} GROUP BY property""", params, as_dict=True)
	f, _f_since, f_props = _sum(failed)
	u, u_since, u_props = _sum(unsent)
	return C.mail_check("mail.delivery", failed=f, unsent=u, oldest_unsent=u_since, now=now,
	                    properties=f_props | u_props)


PLATFORM_PROBES = (
	("scheduler", _scheduler), ("scheduler.jobs", _jobs), ("scheduler.errors", _job_errors),
	("workers", _workers), ("encryption_key", _encryption_key), ("db.snapshot_isolation", _snapshot_isolation),
	("mail.queue", _mail_queue),
)
HOTEL_PROBES = (
	("outbox.pms", _outbox_pms), ("outbox.channel", _outbox_channel), ("channel.inbound", _channel_inbound),
	("connections", _connections), ("payments.pending", _payments_pending),
	("payments.callbacks", _payments_callbacks), ("payments.reconciliation", _payments_reconciliation),
	("payments.overpaid", _bookings_overpaid),
	("holds.overdue", _overdue_holds),
	("fx.rates", _fx), ("mail.account", _mail_account),
	("mail.delivery", _mail_delivery),
	("contracts.live", _contracts_live),
)


def collect(*, properties=None, platform: bool = False, now=None) -> list[dict]:
	"""Every check the caller may see. ``properties``: the hotels to count (None = all)."""
	now = get_datetime(now) if now else now_datetime()
	props = None if properties is None else frozenset(properties)
	out = []
	for key, probe in PLATFORM_PROBES if platform else ():
		out.append(_safely(key, "platform", lambda probe=probe: probe(now)))
	for key, probe in HOTEL_PROBES:
		out.append(_safely(key, "site" if key == "mail.account" else "hotel", lambda probe=probe: probe(props, now)))
	return out


def _safely(key: str, scope: str, run) -> dict:
	try:
		return run()
	except Exception:
		log_exception(f"TEX status check failed: {key}")
		return C.check_error(key, scope)
