"""Audit trail for commercially meaningful actions (R-54) and log redaction (R-53)."""

from __future__ import annotations

import json
import re

import frappe
from frappe.utils import now_datetime

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


def source_of_request() -> str:
	if getattr(frappe.flags, "tex_source", None):
		return frappe.flags.tex_source
	if frappe.session.user == "Guest":
		return "Guest"
	if getattr(frappe.flags, "in_scheduler", False):
		return "Scheduler"
	req = getattr(frappe.local, "request", None)
	if req is None:
		return "System"
	return "API" if (frappe.get_request_header("Authorization") or "").lower().startswith("token") else "Desk"


def audit(action: str, *, reference_doctype: str | None = None, reference_name: str | None = None,
          property: str | None = None, old=None, new=None, reason: str | None = None,
          source: str | None = None) -> str:
	"""Insert an immutable TEX Audit Event. Raises on failure: an unauditable
	commercial action must not silently succeed."""
	user = frappe.session.user
	doc = frappe.get_doc({
		"doctype": "TEX Audit Event",
		"event_time": now_datetime(),
		"action": action,
		"actor": user,
		"actor_roles": ", ".join(sorted(r for r in frappe.get_roles(user) if r not in ("All", "Guest"))),
		"source": source or source_of_request(),
		"property": property,
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
	return doc.name


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

