"""Deterministic guest segment rules (R-37). Pure — no frappe import.

A segment is ``{"match": "all"|"any", "conditions": [{"field", "op", "value"}]}``.
Only whitelisted fields and operators are accepted, so a rule can never become a
query injection or reach data the CRM does not expose.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal, InvalidOperation

FIELDS: dict[str, str] = {
	"stays": "int", "lifetime_value": "money", "lifetime_currency": "str", "last_stay_days_ago": "int", "country": "str", "market": "str",
	"language": "str", "vip": "bool", "tags": "list", "consent_email": "bool", "consent_sms": "bool",
	"consent_whatsapp": "bool", "loyalty_points": "int", "nationality": "str", "blacklisted": "bool",
	"has_upcoming_stay": "bool",
}
OPS: dict[str, set[str]] = {
	"int": {"eq", "ne", "gt", "gte", "lt", "lte"}, "money": {"eq", "ne", "gt", "gte", "lt", "lte"},
	"str": {"eq", "ne", "in", "not_in", "empty", "not_empty"}, "bool": {"is"},
	"list": {"contains", "not_contains", "empty", "not_empty"},
}


class SegmentError(ValueError):
	pass


def validate(rules: dict) -> dict:
	if not isinstance(rules, dict):
		raise SegmentError("rules must be an object")
	match = rules.get("match", "all")
	if match not in ("all", "any"):
		raise SegmentError("match must be 'all' or 'any'")
	conds = rules.get("conditions") or []
	if not isinstance(conds, list) or len(conds) > 25:
		raise SegmentError("conditions must be a list of at most 25 items")
	clean = []
	for c in conds:
		f, op = c.get("field"), c.get("op")
		kind = FIELDS.get(f)
		if kind is None:
			raise SegmentError(f"unknown field {f!r}")
		if op not in OPS[kind]:
			raise SegmentError(f"operator {op!r} is not valid for {f}")
		clean.append({"field": f, "op": op, "value": c.get("value")})
	return {"match": match, "conditions": clean}


def _num(v, kind):
	try:
		return int(v) if kind == "int" else Decimal(str(v))
	except (TypeError, ValueError, InvalidOperation):
		raise SegmentError(f"not a number: {v!r}") from None


def _cmp(op, a, b) -> bool:
	return {"eq": a == b, "ne": a != b, "gt": a > b, "gte": a >= b, "lt": a < b, "lte": a <= b}[op]


def _values(v) -> set[str]:
	if isinstance(v, list | tuple | set):
		return {str(x).strip().upper() for x in v if str(x).strip()}
	return {x.strip().upper() for x in str(v or "").split(",") if x.strip()}


def matches(guest: dict, rules: dict, today: date) -> bool:
	"""``guest`` is a flat dict with the FIELDS keys (see ``guest_facts``)."""
	results = []
	for c in rules["conditions"]:
		f, op, want = c["field"], c["op"], c["value"]
		kind = FIELDS[f]
		have = guest.get(f)
		if kind in ("int", "money"):
			if have is None:
				results.append(False)
				continue
			results.append(_cmp(op, _num(have, kind), _num(want, kind)))
		elif kind == "bool":
			results.append(bool(have) == bool(want in (True, 1, "1", "true", "yes")))
		elif kind == "str":
			h = (have or "").strip().upper()
			if op == "empty":
				results.append(not h)
			elif op == "not_empty":
				results.append(bool(h))
			elif op in ("in", "not_in"):
				results.append((h in _values(want)) == (op == "in"))
			else:
				results.append((h == str(want or "").strip().upper()) == (op == "eq"))
		else:
			tags = _values(have)
			if op == "empty":
				results.append(not tags)
			elif op == "not_empty":
				results.append(bool(tags))
			else:
				hit = bool(tags & _values(want))
				results.append(hit == (op == "contains"))
	if not results:
		return True
	return all(results) if rules["match"] == "all" else any(results)


def guest_facts(row: dict, today: date, upcoming: bool = False) -> dict:
	last = row.get("tex_last_stay")
	if isinstance(last, str) and last:
		last = date.fromisoformat(last[:10])
	return {
		"stays": int(row.get("tex_stays") or 0), "lifetime_value": row.get("tex_lifetime_value") or 0,
		"lifetime_currency": row.get("tex_lifetime_currency"),
		"last_stay_days_ago": (today - last).days if last else None, "country": row.get("tex_country"),
		"market": row.get("tex_market"), "language": row.get("tex_language"), "vip": row.get("vip"),
		"tags": row.get("tex_tags"), "consent_email": row.get("tex_consent_email"),
		"consent_sms": row.get("tex_consent_sms"), "consent_whatsapp": row.get("tex_consent_whatsapp"),
		"loyalty_points": int(row.get("tex_loyalty_points") or 0), "nationality": row.get("nationality"),
		"blacklisted": row.get("blacklisted"), "has_upcoming_stay": upcoming,
	}


SYSTEM_SEGMENTS: dict[str, tuple[str, dict]] = {
	"REPEAT": ("Repeat guests", {"match": "all", "conditions": [{"field": "stays", "op": "gte", "value": 2}]}),
	"VIP": ("VIP", {"match": "all", "conditions": [{"field": "vip", "op": "is", "value": True}]}),
	"EMAIL_OPT_IN": ("Email opt-in", {"match": "all", "conditions": [
		{"field": "consent_email", "op": "is", "value": True},
		{"field": "blacklisted", "op": "is", "value": False}]}),
	"LAPSED": ("Lapsed (no stay in 18 months)", {"match": "all", "conditions": [
		{"field": "stays", "op": "gte", "value": 1}, {"field": "last_stay_days_ago", "op": "gt", "value": 548},
		{"field": "has_upcoming_stay", "op": "is", "value": False}]}),
}
