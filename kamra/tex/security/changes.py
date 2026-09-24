"""Compact, bounded change records for the audit trail (R-54, ADR-053).

Pure (no frappe): values are made canonical first, so a value read from the database and
the same value as an API sent it compare equal, and money never passes through float.

A *collection diff* describes what happened to a set of rows (a contract table, the
sections of a frozen payload, the cells of an ARI bulk edit), each row known by a natural
key (``"<room type> · LOW"``), never by a row id that changes on every save::

    {"count": [before, after],                      # rows before and after
     "totals": {"added": n, "removed": n, "changed": n},
     "added": [key, ...], "removed": [key, ...],     # at most LIST_LIMIT keys each
     "changed": {key: {field: [old, new]}},          # at most DETAIL_LIMIT rows in detail
     "changed_keys": [key, ...],                     # further changed rows, keys only
     "fields": {field: [old, new]}}                  # a section of single values

Everything is bounded: a thousand-row edit records its counts and a few hundred keys at most.
"""

from __future__ import annotations

from collections import Counter
from datetime import date, datetime, time, timedelta
from decimal import Decimal, InvalidOperation

LIST_LIMIT = 50          # keys listed per added / removed / changed_keys list
DETAIL_LIMIT = 25        # changed rows recorded field by field
CELL_LIMIT = 50          # ARI cells recorded field by field
HISTOGRAM_LIMIT = 10     # distinct old values counted per field
TEXT_LIMIT = 300         # characters kept of a long text value
SEP = " · "


def dec_str(value) -> str | None:
	"""A plain decimal string (no exponent, no trailing zeros): 100.0 → "100", "0.70" → "0.7"."""
	if value is None or value == "":
		return None
	try:
		d = value if isinstance(value, Decimal) else Decimal(str(value))
	except (InvalidOperation, ValueError):
		return str(value)
	if not d.is_finite():
		return str(d)
	d = d.normalize()
	if d == 0:
		return "0"
	return format(d, "f")


def canon(value):
	"""JSON-safe and comparable: numbers other than int as decimal strings (never float),
	dates ISO, blank → None, sets sorted, sequences as lists, mappings recursively."""
	if value is None or value == "":
		return None
	if isinstance(value, bool | int):
		return value
	if isinstance(value, float | Decimal):
		return dec_str(value)
	if isinstance(value, datetime):
		return value.replace(microsecond=0).isoformat(sep=" ")
	if isinstance(value, date | time):
		return value.isoformat()
	if isinstance(value, timedelta):
		return str(value)
	if isinstance(value, dict):
		return {str(k): canon(v) for k, v in value.items()}
	if isinstance(value, set | frozenset):
		return sorted(canon(v) for v in value)
	if isinstance(value, list | tuple):
		return [canon(v) for v in value]
	text = str(value)
	return text if len(text) <= TEXT_LIMIT else text[:TEXT_LIMIT] + "…"


def field_changes(before: dict | None, after: dict | None, fields=None) -> tuple[dict, dict]:
	"""(old, new): the fields whose canonical values differ, each side keyed by field."""
	before, after = before or {}, after or {}
	names = fields if fields is not None else list(dict.fromkeys([*before, *after]))
	old, new = {}, {}
	for f in names:
		a, b = canon(before.get(f)), canon(after.get(f))
		if a != b:
			old[f], new[f] = a, b
	return old, new


def key_of(row: dict, key_fields) -> str:
	"""A row's natural key: its key values joined, ``*`` for a blank one, blanks at the end
	dropped ("HB" rather than "HB · * · *")."""
	parts = ["*" if row.get(f) in (None, "") else str(canon(row.get(f))) for f in key_fields]
	while len(parts) > 1 and parts[-1] == "*":
		parts.pop()
	return SEP.join(parts)


def _index(rows, key_fields, ignore) -> dict[str, dict]:
	out: dict[str, dict] = {}
	seen: Counter = Counter()
	for r in rows or ():
		k = key_of(r, key_fields)
		seen[k] += 1
		if seen[k] > 1:                               # a duplicate key stays told apart
			k = f"{k} #{seen[k]}"
		out[k] = {f: canon(v) for f, v in r.items() if f not in ignore}
	return out


def collection_diff(before, after, key_fields, *, ignore=(), detail_limit: int = DETAIL_LIMIT,
                    list_limit: int = LIST_LIMIT) -> dict | None:
	"""What happened to a set of rows, bounded (see the module docstring). None: nothing."""
	a, b = _index(before, key_fields, ignore), _index(after, key_fields, ignore)
	added = [k for k in b if k not in a]
	removed = [k for k in a if k not in b]
	changed: dict[str, dict] = {}
	for k, old in a.items():
		if k not in b:
			continue
		new = b[k]
		fields = {f: [old.get(f), new.get(f)] for f in dict.fromkeys([*old, *new]) if old.get(f) != new.get(f)}
		if fields:
			changed[k] = fields
	if not (added or removed or changed):
		return None
	out: dict = {"count": [len(a), len(b)],
	             "totals": {"added": len(added), "removed": len(removed), "changed": len(changed)}}
	if added:
		out["added"] = added[:list_limit]
	if removed:
		out["removed"] = removed[:list_limit]
	if changed:
		keys = list(changed)
		out["changed"] = {k: changed[k] for k in keys[:detail_limit]}
		if len(keys) > detail_limit:
			out["changed_keys"] = keys[detail_limit:detail_limit + list_limit]
	return out


def section_diff(before: dict | None, after: dict | None, *, ignore=()) -> dict | None:
	"""A section of single values (a payload's settings): ``{"fields": {f: [old, new]}}``."""
	keys = [k for k in dict.fromkeys([*(before or {}), *(after or {})]) if k not in ignore]
	old, new = field_changes(before, after, keys)
	return {"fields": {f: [old[f], new[f]] for f in old}} if old else None


def cells_diff(cells, *, limit: int = CELL_LIMIT, list_limit: int = LIST_LIMIT) -> dict:
	"""An ARI bulk edit: ``cells`` = [(key, old values, new values)] for every cell it touched.
	Changed cells old → new (bounded), how many were already at the new value, and every old
	value counted per field (so the prior state is known even beyond the detailed cells)."""
	changed: dict[str, dict] = {}
	histogram: dict[str, Counter] = {}
	unchanged = 0
	for key, old, new in cells:
		fields = {}
		for f in dict.fromkeys([*old, *new]):
			a, b = canon(old.get(f)), canon(new.get(f))
			if a != b:
				fields[f] = [a, b]
				histogram.setdefault(f, Counter())["" if a is None else str(a)] += 1
		if fields:
			changed[key] = fields
		else:
			unchanged += 1
	keys = list(changed)
	out: dict = {"count": [len(cells), len(cells)], "totals": {"added": 0, "removed": 0, "changed": len(keys)},
	             "unchanged": unchanged}
	if keys:
		out["changed"] = {k: changed[k] for k in keys[:limit]}
		if len(keys) > limit:
			out["changed_keys"] = keys[limit:limit + list_limit]
		out["old_values"] = {f: _bounded_histogram(c) for f, c in histogram.items()}
	return out


def _bounded_histogram(counter: Counter) -> dict[str, int]:
	common = counter.most_common()
	out = dict(sorted(common[:HISTOGRAM_LIMIT]))
	rest = sum(n for _v, n in common[HISTOGRAM_LIMIT:])
	if rest:
		out["…"] = rest
	return out
