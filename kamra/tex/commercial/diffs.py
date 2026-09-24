"""What a contract edit or a publish changed, for the audit trail (R-54, ADR-053). Pure.

Rows are compared by their natural key, never by row id: a draft's rows get new ids on
every save, and a new version copies them under new ids.
"""

from __future__ import annotations

from kamra.tex.security.changes import collection_diff, field_changes, section_diff

# a draft version's child tables → the fields that name a row
DRAFT_TABLES = {
	"rooms": ("room_type",),
	"periods": ("period_code",),
	"period_rates": ("room_type", "period_code"),
	"age_bands": ("band_code",),
	"occupancy_rules": ("target", "room_type", "period_code", "age_band", "position", "combination"),
	"boards": ("board", "room_type", "period_code"),
	"rate_plans": ("rate_plan",),
	"offers": ("offer_code",),
}

# a frozen payload's row sections → the fields that name a row (``id`` is a row id: ignored)
PAYLOAD_TABLES = {
	"rooms": ("room_type",),
	"periods": ("code",),
	"room_rules": ("room_type", "period"),
	"occupancy_rules": ("source", "target", "room_type", "period", "age_band", "position", "adults", "children"),
	"age_bands": ("code",),
	"boards": ("board", "room_type", "period"),
	"rate_plans": ("code",),
	"offers": ("id",),
}
PAYLOAD_SECTIONS = ("contract", "settings")
PAYLOAD_IGNORE = {"offers": ()}          # an offer's id is its code; every other row id is not a key


def draft_diff(before: dict, after: dict) -> tuple[dict, dict, dict]:
	"""``before`` / ``after``: {"fields": {field: value}, "tables": {table: [row, ...]}}.
	→ (old fields, new fields, {table: collection diff}) — only what changed."""
	old, new = field_changes(before.get("fields"), after.get("fields"))
	tables = {}
	for t, key in DRAFT_TABLES.items():
		d = collection_diff((before.get("tables") or {}).get(t), (after.get("tables") or {}).get(t), key)
		if d:
			tables[t] = d
	return old, new, tables


def payload_diff(before: dict | None, after: dict) -> dict:
	"""{section: diff} between two frozen payloads (``before`` None: a first publish, every row
	added). Only sections that differ."""
	before = before or {}
	out = {}
	for s in PAYLOAD_SECTIONS:
		d = section_diff(before.get(s), after.get(s), ignore=("id",))
		if d and before:
			out[s] = d
	for s, key in PAYLOAD_TABLES.items():
		d = collection_diff(before.get(s), after.get(s), key, ignore=PAYLOAD_IGNORE.get(s, ("id",)))
		if d:
			out[s] = d
	return out
