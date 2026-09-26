"""TEX system status API (ADR-047).

- ``status``: the operational checks (``system.monitor``). Hotel-scoped checks count only
  the hotels where the caller holds the capability; platform checks (scheduler, workers,
  encryption key, the whole e-mail queue) are for platform administrators only. The payload
  carries counts, ages, job names, currency pairs and hotel names: never a secret, a token,
  guest data or a stack trace.
- ``ping``: an unauthenticated liveness probe for an uptime monitor. It answers only
  booleans (``ok``, ``db``, ``cache``, ``scheduler``), is rate limited per IP and returns
  HTTP 503 when the site cannot serve (database or cache unreachable).
"""

from __future__ import annotations

import frappe
from frappe.rate_limiter import rate_limit
from frappe.utils import now_datetime

from kamra.tex.api._util import text
from kamra.tex.ops import checks as C
from kamra.tex.ops import status as status_mod
from kamra.tex.security import scope
from kamra.tex.security.scope import require_capability

CAP = "system.monitor"
# per IP; an uptime monitor polls once a minute. site_config ``tex_ping_limit`` may raise it
PING_LIMIT = {"limit": lambda: max(30, int(frappe.conf.get("tex_ping_limit") or 0)), "seconds": 60}  # nosemgrep: frappe-breaks-multitenancy -- the lambda reads frappe.conf per call, on the request's site
# the every-minute TEX job must have run this recently for ``scheduler`` to be true
PING_JOB = "kamra.tex.scheduler.every_minute"


def monitored_properties() -> set[str]:
	return {p for p in scope.permitted_properties() if scope.has_capability(CAP, p)}


@frappe.whitelist(methods=["GET"])
@require_capability(CAP)
def status(property: str | None = None):
	"""Checks the caller may see and the overall status (the worst of them)."""
	prop = text(property, 140)
	platform = scope.is_platform_admin()
	if prop:
		props: set[str] | None = {prop}
	elif platform:
		props = None
	else:
		props = monitored_properties()
	now = now_datetime()
	checks = status_mod.collect(properties=props, platform=platform, now=now)
	return {
		"overall": C.worst(c["status"] for c in checks),
		"checked_at": now.replace(microsecond=0).isoformat(sep=" "),
		"platform": platform,
		"hotels": sorted(props) if props is not None else None,
		"checks": checks,
	}


def _db_ok() -> bool:
	try:
		return frappe.db.sql("SELECT 1")[0][0] == 1
	except Exception:
		return False


def _cache_ok() -> bool:
	try:
		return bool(frappe.cache.ping())
	except Exception:
		return False


def _scheduler_ok() -> bool:
	"""The scheduler is on and the every-minute TEX job ran within its limit."""
	try:
		from frappe.utils.scheduler import is_scheduler_inactive

		if is_scheduler_inactive(verbose=False):
			return False
		last = status_mod.last_runs().get(PING_JOB, {}).get("last_execution")
		limit = C.JOB_MAX_AGE_MINUTES[PING_JOB]
		return bool(last) and C.minutes_since(last, now_datetime()) <= limit
	except Exception:
		return False


@frappe.whitelist(allow_guest=True, methods=["GET"])
@rate_limit(**PING_LIMIT)
def ping():
	"""Liveness for an uptime monitor: booleans only (no counts, versions, host or hotel
	names). HTTP 503 when the database or the cache cannot be reached."""
	db = _db_ok()
	cache = _cache_ok()
	ok = db and cache
	if not ok:
		frappe.local.response["http_status_code"] = 503
	return {"ok": ok, "db": db, "cache": cache, "scheduler": _scheduler_ok() if db else False}
