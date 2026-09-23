"""Deterministic guest segment rules (R-37). Pure — no frappe import.

A segment is ``{"match": "all"|"any", "conditions": [{"field", "op", "value"[, "currency"]}]}``.
Only whitelisted fields and operators are accepted, so a rule can never become a
query injection or reach data the CRM does not expose.

Facts are derived per tenant (``derive_facts``): from the reservations and abandoned
bookings at the hotels the viewer may see, never from another tenant's stays (G-23/G-26).
Money is never compared across currencies: a lifetime-value condition names its currency
and is compared with the guest's value in that currency.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

FIELDS: dict[str, str] = {
	"stays": "int", "lifetime_value": "money", "lifetime_currency": "str", "last_stay_days_ago": "int",
	"country": "str", "market": "str", "language": "str", "vip": "bool", "tags": "list", "consent_email": "bool",
	"consent_sms": "bool", "consent_whatsapp": "bool", "loyalty_points": "int", "nationality": "str",
	"blacklisted": "bool", "has_upcoming_stay": "bool",
	# G-23: the named segments of R-37
	"has_children": "bool", "last_lead_days": "int", "cancellations": "int", "last_cancel_days_ago": "int",
	"abandoned_days_ago": "int", "days_to_birthday": "int",
}
OPS: dict[str, set[str]] = {
	"int": {"eq", "ne", "gt", "gte", "lt", "lte"}, "money": {"eq", "ne", "gt", "gte", "lt", "lte"},
	"str": {"eq", "ne", "in", "not_in", "empty", "not_empty"}, "bool": {"is"},
	"list": {"contains", "not_contains", "empty", "not_empty"},
}
MAX_CONDITIONS = 25
MAX_TEXT = 140
# a reservation in one of these is not (yet or any more) a stay or a sale
NOT_SOLD = {"Inquiry", "Waitlist", "Quoted"}
NOT_STAYED = {"Cancelled", "No Show"}
UPCOMING = {"Confirmed", "Pending Payment", "Checked In", "Held", "Requested"}
TRUE = (True, 1, "1", "true", "yes")
FALSE = (False, 0, "0", "false", "no")


class SegmentError(ValueError):
	pass


def _currency(v) -> str:
	c = str(v or "").strip().upper()
	if len(c) != 3 or not c.isalpha():
		raise SegmentError("a money condition needs a 3-letter currency")
	return c


def _check_value(field: str, kind: str, op: str, value):
	"""The condition's value, typed; refuses what could never be compared (strict)."""
	if kind in ("int", "money"):
		_num(value, kind)
		return int(value) if kind == "int" else str(Decimal(str(value)))
	if kind == "bool":
		if value not in TRUE and value not in FALSE:
			raise SegmentError(f"{field}: yes or no")
		return value in TRUE
	if op in ("empty", "not_empty"):
		return None
	if isinstance(value, list | tuple):
		items = [str(x).strip()[:MAX_TEXT] for x in value if str(x).strip()]
		if not items:
			raise SegmentError(f"{field}: a value is required")
		return items
	text = str(value if value is not None else "").strip()
	if not text:
		raise SegmentError(f"{field}: a value is required")
	return text[:MAX_TEXT * 4]


def validate(rules: dict, *, strict: bool = False) -> dict:
	"""``strict`` (saving): every value is typed and a money condition names its
	currency. Reading older rows is lenient; a money condition without a currency then
	never matches (the editor asks for it)."""
	if not isinstance(rules, dict):
		raise SegmentError("rules must be an object")
	match = rules.get("match", "all")
	if match not in ("all", "any"):
		raise SegmentError("match must be 'all' or 'any'")
	conds = rules.get("conditions") or []
	if not isinstance(conds, list) or len(conds) > MAX_CONDITIONS:
		raise SegmentError(f"conditions must be a list of at most {MAX_CONDITIONS} items")
	clean = []
	for c in conds:
		if not isinstance(c, dict):
			raise SegmentError("a condition must be an object")
		f, op = c.get("field"), c.get("op")
		kind = FIELDS.get(f)
		if kind is None:
			raise SegmentError(f"unknown field {f!r}")
		if op not in OPS[kind]:
			raise SegmentError(f"operator {op!r} is not valid for {f}")
		out = {"field": f, "op": op, "value": _check_value(f, kind, op, c.get("value")) if strict else c.get("value")}
		if kind == "money" and (strict or c.get("currency")):
			out["currency"] = _currency(c.get("currency"))
		clean.append(out)
	return {"match": match, "conditions": clean}


def _num(v, kind):
	try:
		if kind == "int":
			if isinstance(v, bool) or (isinstance(v, str) and not v.strip().lstrip("-").isdigit()):
				raise ValueError
			return int(v)
		d = Decimal(str(v))
		if not d.is_finite():
			raise ValueError
		return d
	except (TypeError, ValueError, InvalidOperation):
		raise SegmentError(f"not a number: {v!r}") from None


def _cmp(op, a, b) -> bool:
	return {"eq": a == b, "ne": a != b, "gt": a > b, "gte": a >= b, "lt": a < b, "lte": a <= b}[op]


def _values(v) -> set[str]:
	if isinstance(v, list | tuple | set):
		return {str(x).strip().upper() for x in v if str(x).strip()}
	return {x.strip().upper() for x in str(v or "").split(",") if x.strip()}


def _condition(guest: dict, c: dict) -> bool:
	f, op, want = c["field"], c["op"], c["value"]
	kind = FIELDS[f]
	have = guest.get(f)
	if kind == "money":
		ccy = c.get("currency")
		if not ccy:
			return False                        # never compare money without knowing its currency
		values = have if isinstance(have, dict) else {}
		return _cmp(op, _num(values.get(ccy, 0), kind), _num(want, kind))
	if kind == "int":
		if have is None:
			return op == "ne"                   # an unknown fact equals nothing
		return _cmp(op, _num(have, kind), _num(want, kind))
	if kind == "bool":
		return bool(have) == (want in TRUE)
	if kind == "str":
		h = (have or "").strip().upper()
		if op == "empty":
			return not h
		if op == "not_empty":
			return bool(h)
		if op in ("in", "not_in"):
			return (h in _values(want)) == (op == "in")
		return (h == str(want or "").strip().upper()) == (op == "eq")
	tags = _values(have)
	if op == "empty":
		return not tags
	if op == "not_empty":
		return bool(tags)
	return bool(tags & _values(want)) == (op == "contains")


def matches(guest: dict, rules: dict, today: date | None = None) -> bool:
	"""``guest`` is a flat dict with the FIELDS keys (see ``derive_facts``)."""
	results = [_condition(guest, c) for c in rules["conditions"]]
	if not results:
		return True
	return all(results) if rules["match"] == "all" else any(results)


# ─── facts ───────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class StayFact:
	"""One reservation at a hotel the viewer may see."""
	status: str
	check_in: date
	check_out: date
	children: int = 0
	sold_on: date | None = None           # when it was sold (TEX sale time, else created)
	cancelled_on: date | None = None
	amount: Decimal = Decimal(0)
	currency: str | None = None


def _day(v) -> date | None:
	if v is None or v == "":
		return None
	if isinstance(v, datetime):
		return v.date()
	if isinstance(v, date):
		return v
	return date.fromisoformat(str(v)[:10])


def days_to_birthday(dob, today: date) -> int | None:
	"""Days until the next birthday (0 = today); 29 February counts on 28 February in other years."""
	dob = _day(dob)
	if not dob:
		return None

	def on(year: int) -> date:
		try:
			return dob.replace(year=year)
		except ValueError:                   # 29 February
			return date(year, 2, 28)

	nxt = on(today.year)
	if nxt < today:
		nxt = on(today.year + 1)
	return (nxt - today).days


def derive_facts(guest: dict, stays: list[StayFact], abandoned: list, today: date) -> dict:
	"""Segment facts of one guest, from that tenant's reservations and abandoned bookings."""
	done = [s for s in stays if s.status not in NOT_STAYED | NOT_SOLD and s.check_out <= today]
	ltv: dict[str, Decimal] = {}
	count: dict[str, int] = {}
	for s in done:
		ccy = (s.currency or "").upper()
		if ccy:
			ltv[ccy] = ltv.get(ccy, Decimal(0)) + Decimal(s.amount or 0)
			count[ccy] = count.get(ccy, 0) + 1
	main = min(count, key=lambda c: (-count[c], c)) if count else None
	sold = [s for s in stays if s.status not in NOT_SOLD and s.sold_on]
	latest = max(sold, key=lambda s: (s.sold_on, s.check_in)) if sold else None
	cancelled = [s for s in stays if s.status == "Cancelled"]
	cancel_days = [s.cancelled_on for s in cancelled if s.cancelled_on]
	gave_up = [d for d in (_day(a) for a in abandoned) if d]
	return {
		"stays": len(done), "lifetime_value": ltv, "lifetime_currency": main,
		"last_stay_days_ago": (today - max(s.check_out for s in done)).days if done else None,
		"has_upcoming_stay": any(s.status in UPCOMING and s.check_in >= today for s in stays),
		"has_children": any(s.children > 0 for s in stays if s.status not in NOT_STAYED | NOT_SOLD),
		"last_lead_days": max((latest.check_in - latest.sold_on).days, 0) if latest else None,
		"cancellations": len(cancelled),
		"last_cancel_days_ago": (today - max(cancel_days)).days if cancel_days else None,
		"abandoned_days_ago": (today - max(gave_up)).days if gave_up else None,
		"days_to_birthday": days_to_birthday(guest.get("date_of_birth"), today),
		"country": guest.get("tex_country"), "market": guest.get("tex_market"), "language": guest.get("tex_language"),
		"vip": guest.get("vip"), "tags": guest.get("tex_tags"), "consent_email": guest.get("tex_consent_email"),
		"consent_sms": guest.get("tex_consent_sms"), "consent_whatsapp": guest.get("tex_consent_whatsapp"),
		"loyalty_points": int(guest.get("tex_loyalty_points") or 0), "nationality": guest.get("nationality"),
		"blacklisted": guest.get("blacklisted"),
	}


def _all(*conds) -> dict:
	return {"match": "all", "conditions": [{"field": f, "op": op, "value": v} for f, op, v in conds]}


# presets every tenant sees (read-only); a hotel copies one to make its own
SYSTEM_SEGMENTS: dict[str, tuple[str, dict]] = {
	"REPEAT": ("Repeat guests", _all(("stays", "gte", 2))),
	"VIP": ("VIP", _all(("vip", "is", True))),
	"EMAIL_OPT_IN": ("Email opt-in", _all(("consent_email", "is", True), ("blacklisted", "is", False))),
	"LAPSED": ("No stay in 12 months", _all(("stays", "gte", 1), ("last_stay_days_ago", "gt", 365),
	                                        ("has_upcoming_stay", "is", False))),
	"FAMILY": ("Families", _all(("has_children", "is", True))),
	"LAST_MINUTE": ("Last-minute bookers", _all(("last_lead_days", "lte", 3))),
	"CANCELLED": ("Cancelled in the last 90 days", _all(("last_cancel_days_ago", "lte", 90))),
	"ABANDONED": ("Abandoned a booking (30 days)", _all(("abandoned_days_ago", "lte", 30),
	                                                    ("has_upcoming_stay", "is", False))),
	"BIRTHDAY": ("Birthday in the next 30 days", _all(("days_to_birthday", "lte", 30))),
}
