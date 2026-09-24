"""Audit trail for commercially meaningful actions (R-54) and log redaction (R-53)."""

from __future__ import annotations

import json
import re
from contextlib import contextmanager

import frappe
from frappe.utils import now_datetime

from kamra.tex.security import changes

SENSITIVE = re.compile(r"(pass(word)?|secret|token|cvv|cvc|pan|card_?number|authorization|api_?key|pin)$", re.I)


def redact(value):
	"""Recursively mask values whose key looks sensitive. Never log secrets/tokens/cards."""
	if isinstance(value, dict):
		return {k: ("***" if isinstance(k, str) and SENSITIVE.search(k) else redact(v)) for k, v in value.items()}
	if isinstance(value, list | tuple):
		return [redact(v) for v in value]
	if isinstance(value, str) and re.fullmatch(r"\d{13,19}", value.replace(" ", "")):
		return "****" + value[-4:]
	return value


def _json(v) -> str | None:
	if v is None:
		return None
	return json.dumps(redact(v), default=str, ensure_ascii=False, sort_keys=True)


# how an action reached TEX (ADR-053): Desk = a signed-in staff session (the TEX app included),
# API = a token-authenticated call, Guest = an anonymous visitor, Gateway Return = the guest's
# browser coming back from a payment page, Webhook = a server-to-server notification (payment
# gateway, channel manager), Scheduler = a scheduled job, System = a queued job, a migration or
# the console, Agent = the AI assistant
SOURCES = ("Desk", "API", "Guest", "Gateway Return", "Webhook", "Scheduler", "System", "Agent")
_SCHEDULED_JOB = "frappe.core.doctype.scheduled_job_type.scheduled_job_type.run_scheduled_job"


def source_of_request() -> str:
	if getattr(frappe.flags, "tex_source", None):
		return frappe.flags.tex_source
	job = getattr(frappe.local, "job", None)
	if job:
		# a background job acts after the request that queued it: never the guest's or staff's
		return "Scheduler" if (job.get("method") == _SCHEDULED_JOB or getattr(frappe.flags, "in_scheduler", False)) \
			else "System"
	if frappe.session.user == "Guest":
		return "Guest"
	if getattr(frappe.flags, "in_scheduler", False):
		return "Scheduler"
	req = getattr(frappe.local, "request", None)
	if req is None:
		return "System"
	return "API" if (frappe.get_request_header("Authorization") or "").lower().startswith("token") else "Desk"


@contextmanager
def audit_source(source: str):
	"""Events audited inside the block record ``source`` (unless one names its own): the entry
	point knows how the action arrived (a gateway's return or notification, the scheduler)."""
	if source not in SOURCES:
		raise ValueError(f"unknown audit source {source!r}")
	before = frappe.flags.get("tex_source")
	frappe.flags.tex_source = source
	try:
		yield
	finally:
		frappe.flags.tex_source = before


def audit(action: str, *, reference_doctype: str | None = None, reference_name: str | None = None,
          property: str | None = None, old=None, new=None, reason: str | None = None,
          source: str | None = None, hotels=None, hotel_group: str | None = None,
          enterprise: str | None = None) -> str:
	"""Insert an immutable TEX Audit Event. Raises on failure: an unauditable
	commercial action must not silently succeed.

	``property`` is the hotel the event belongs to. An event of a hotel group or an enterprise
	(a group grant, a group-level record) names the group / enterprise and ``hotels``: every
	hotel it reached when it happened. Each of those hotels' staff see it (``TEX Audit Scope``,
	ADR-053); a hotel it did not reach never does."""
	user = frappe.session.user
	doc = frappe.get_doc({
		"doctype": "TEX Audit Event",
		"event_time": now_datetime(),
		"action": action,
		"actor": user,
		"actor_roles": ", ".join(sorted(r for r in frappe.get_roles(user) if r not in ("All", "Guest"))),
		"source": source or source_of_request(),
		"property": property,
		"hotel_group": hotel_group,
		"enterprise": enterprise,
		"reference_doctype": reference_doctype,
		"reference_name": reference_name,
		"old_value": _json(old),
		"new_value": _json(new),
		"reason": reason,
		"request_id": getattr(frappe.local, "request_id", None) or frappe.flags.get("request_id"),
	})
	doc.flags.ignore_permissions = True
	doc.flags.ignore_links = True          # history may name a record that was just deleted
	doc.insert(ignore_permissions=True)
	reached = sorted({h for h in (hotels or ()) if h} - {property})
	if reached and frappe.db.table_exists("TEX Audit Scope"):
		now = doc.creation
		frappe.db.bulk_insert(
			"TEX Audit Scope", fields=["name", "creation", "modified", "owner", "modified_by", "event", "property"],
			values=[(frappe.generate_hash(length=12), now, now, user, user, doc.name, h) for h in reached])
	return doc.name


def recorded(action: str, *, reference_doctype: str, reference_name: str, new=None) -> bool:
	"""Whether this event is on record already: the same action on the same record, with the same
	new values when ``new`` is given. A report a migration writes is written once, however often
	the migration runs (G-76)."""
	filters = {"action": action, "reference_doctype": reference_doctype, "reference_name": reference_name}
	if new is not None:
		filters["new_value"] = _json(new)
	return bool(frappe.db.exists("TEX Audit Event", filters))


def audit_refusal(action: str, *, reference_doctype: str | None = None, reference_name: str | None = None,
                  property: str | None = None, old=None, new=None, reason: str | None = None,
                  source: str | None = None) -> None:
	"""Audit a refusal the caller raises next (G-73, ADR-058). The refused request is rolled back,
	and an event written in its transaction would go with it; so a job writes the event in a
	transaction of its own. It is queued now, not after a commit that never comes, and runs as
	the refused user. Tests keep one transaction: the job runs inline there."""
	frappe.enqueue("kamra.tex.security.audit.record_refusal", queue="short", now=bool(frappe.flags.in_test),
	               action=action, reference_doctype=reference_doctype, reference_name=reference_name,
	               property=property, old=old, new=new, reason=reason, source=source or source_of_request())


def record_refusal(action: str, **kw) -> str:
	"""The job of ``audit_refusal``."""
	return audit(action, **kw)


# ─── canonical values of a document (ADR-053) ────────────────────────────

_NO_VALUE = frozenset({"Section Break", "Column Break", "Tab Break", "HTML", "Button", "Image", "Fold", "Heading",
                       "Password", "Table", "Table MultiSelect"})
_DECIMAL = frozenset({"Float", "Currency", "Percent"})
_INT = frozenset({"Int", "Rating"})


def field_value(df, value):
	"""A field's value as the audit records it, whether it came from the database or from a
	request: decimals as strings (never float), Int as int, Check as bool, dates ISO."""
	ft = df.fieldtype if df else None
	if ft == "Check":
		return bool(frappe.utils.cint(value))
	if value is None or value == "":
		return None
	if ft in _INT:
		return frappe.utils.cint(value)
	if ft in _DECIMAL:
		return changes.dec_str(value)
	if ft == "Date":
		return str(frappe.utils.getdate(value))
	if ft == "Datetime":
		return str(frappe.utils.get_datetime(value))
	return changes.canon(value)


def doc_values(doc, fields=None, *, exclude=()) -> dict:
	"""{field: canonical value} of a document's data fields (never a Password field, never a
	child table: those are compared as collections)."""
	meta = doc.meta
	if fields is None:
		fields = [df.fieldname for df in meta.fields if df.fieldtype not in _NO_VALUE]
	out = {}
	for f in fields:
		if f in exclude:
			continue
		df = meta.get_field(f)
		if df and df.fieldtype in ("Password",):
			continue
		out[f] = field_value(df, doc.get(f))
	return out


def row_values(rows, *, exclude=()) -> list[dict]:
	"""Child rows as canonical dicts (no row ids, parents or timestamps)."""
	return [doc_values(r, exclude=exclude) for r in rows or ()]


def diff(before: dict | None, after: dict | None, fields) -> dict:
	"""{field: [old, new]} for changed fields."""
	out = {}
	before, after = before or {}, after or {}
	for f in fields:
		a, b = before.get(f), after.get(f)
		if str(a if a is not None else "") != str(b if b is not None else ""):
			out[f] = [a, b]
	return out


def log_exception(title: str) -> None:
	"""Log the current exception WITHOUT frame variables (Frappe's default traceback
	includes locals, which can hold guest data, callback headers or link tokens)."""
	import sys
	import traceback

	exc = sys.exc_info()[1]
	lines = traceback.format_exception(type(exc), exc, exc.__traceback__) if exc else []
	frappe.log_error(title=title[:140], message=redact_text("".join(lines))[-8000:])


def redact_text(text: str) -> str:
	"""Mask token-like values that could appear in exception messages."""
	import re

	text = re.sub(r"(token|sig|secret|password|pwd|authorization)([\"'=:\s]+)[^\s\"'&,]+", r"\1\2********", text,
	              flags=re.IGNORECASE)
	return re.sub(r"\b\d{13,19}\b", "****************", text)

