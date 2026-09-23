"""System-status alerts (ADR-047), run every 15 minutes by ``kamra.tex.scheduler``.

The checks are evaluated as a platform administrator sees them (every hotel, platform checks
included). What is remembered between runs is the status of every check that is not ok, kept
in the audit trail: a ``system.status_changed`` event is written only when that state
changes, so the trail shows when each problem started and ended.

- A check that gets worse (ok→warn, ok→fail, warn→fail) is notified once: an Error Log entry
  (``TEX status alert: …``) and one e-mail to the TEX Settings ``status_alert_recipients``
  through the normal e-mail queue.
- A check that comes back to ok is notified once (e-mail only).
- A check that stays bad, or improves from fail to warn, sends nothing. All the changes of a
  run go out in one e-mail, so a run sends at most one message.
"""

from __future__ import annotations

import json

import frappe
from frappe.utils import get_datetime, now_datetime

from kamra.tex.ops import checks as C
from kamra.tex.ops import status as status_mod
from kamra.tex.security.audit import audit, log_exception

ACTION = "system.status_changed"


def recipients() -> list[str]:
	raw = frappe.db.get_single_value("TEX Settings", "status_alert_recipients")
	return C.parse_recipients(raw)[: C.MAX_ALERT_RECIPIENTS]


def last_state() -> dict[str, str]:
	rows = frappe.get_all("TEX Audit Event", filters={"action": ACTION}, fields=["new_value"],
	                      order_by="event_time desc, creation desc", limit=1)
	if not rows:
		return {}
	try:
		state = (json.loads(rows[0].new_value or "{}") or {}).get("state") or {}
	except ValueError:
		return {}
	return {k: v for k, v in state.items() if v in C.RANK}


def evaluate(now=None) -> dict:
	"""Evaluate every check; record and notify what changed. Returns what happened."""
	now = get_datetime(now) if now else now_datetime()
	checks = status_mod.collect(properties=None, platform=True, now=now)
	current = C.state_of(checks)
	t = C.transitions(last_state(), current)
	out = {"alerted": t["worse"], "recovered": t["recovered"], "changed": t["changed"], "notified": False,
	       "overall": C.worst(current.values())}
	if not t["changed"]:
		return out
	audit(ACTION, reference_doctype="TEX Settings", reference_name="TEX Settings", source="Scheduler",
	      new={"state": current, "worse": t["worse"], "recovered": t["recovered"]})
	by_key = {c["key"]: c for c in checks}
	if t["worse"]:
		bad = [by_key[k] for k in t["worse"] if k in by_key]
		frappe.log_error(title=f"TEX status alert: {C.worst(c['status'] for c in bad).upper()} "
		                       f"{', '.join(t['worse'])}"[:140],
		                 message="\n".join(f"[{c['status'].upper()}] {c['key']}: {c['detail']}" for c in bad))
	to = recipients()
	if to and (t["worse"] or t["recovered"]):
		subject, body = C.alert_message(frappe.local.site, checks, t["worse"], t["recovered"], now)
		try:
			frappe.sendmail(recipients=to, subject=subject, message=body, delayed=True, add_unsubscribe_link=0)
			out["notified"] = True
		except Exception:
			# no outgoing account: the change is still in the audit trail and the Error Log
			log_exception("TEX status alert e-mail not sent")
	return out
