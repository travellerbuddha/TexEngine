"""TEX commercial decimal fields (G-72, ADR-055): what is typed is what is stored and read.

Frappe v16 stores Float, Currency and Percent fields as DECIMAL(21, precision) columns; TEX
declares precision 9 on its commercial inputs (rates, occupancy values, board amounts,
promotion and markup values, FX rates and policies, cancellation, payment and tax values,
loyalty values). Three rules keep such a value exact end to end:

* write — ``check_inputs`` runs ``before_validate`` on every TEX DocType users type decimals
  into (wired in kamra/hooks.py), whoever saves (the TEX API, Desk, an import or a script).
  Each decimal field of the document and of its rows goes through ``money.db_input``: typed
  text with more places than the field keeps, more than 15 significant digits or too large is
  refused naming the field, never rounded silently; a script's binary float is rounded to the
  field's places as the column would round it.
* read — the loaders read these fields with ``money.db_dec`` (pure, ``kamra/tex/money.py``).
* API — ``api_value`` gives a decimal field to JSON as an exact decimal string, never a float.
"""

from __future__ import annotations

import frappe
from frappe import _

from kamra.tex import money
from kamra.tex.pricing.serialize import dec_str

FLOAT_LIKE = ("Float", "Currency", "Percent")

# the fields G-72 moved from DECIMAL(21,6) (Float, precision 6) to DECIMAL(21,9), with their type
G72_FIELDS: dict[tuple[str, str], str] = {
	("TEX Price Period", "adjustment_value"): "Float",
	("TEX Period Rate", "value"): "Float",
	("TEX Occupancy Rule", "value"): "Float",
	("TEX Board Rule", "adult_amount"): "Float",
	("TEX Board Rule", "child_percent"): "Percent",
	("TEX Contract Rate Plan", "value"): "Float",
	("TEX Contract Offer", "value"): "Float",
	("TEX Markup Rule", "value"): "Float",
	("TEX Promotion", "value"): "Float",
	("TEX FX Policy", "adjustment"): "Float",
	("TEX Cancellation Rule", "penalty_value"): "Float",
	("TEX Cancellation Policy", "no_show_value"): "Float",
	("TEX Payment Policy", "deposit_value"): "Float",
	("TEX Tax Rule", "rate"): "Percent",
	("TEX Loyalty Tier", "earn_multiplier"): "Float",
	("TEX Loyalty Earn Rule", "rate"): "Float",
	("TEX Loyalty Program", "point_value"): "Currency",
}
# already 9 places before G-72, now declared explicitly where they were not
NINE_PLACES: dict[tuple[str, str], str] = {
	**G72_FIELDS,
	("TEX FX Rate", "rate"): "Float",
	("TEX FX Policy", "manual_rate"): "Float",
	("TEX Loyalty Program", "max_redeem_percent"): "Percent",
}


def places_of(df) -> int:
	"""Decimal places a field's column keeps: its precision (Frappe sizes the column by it),
	9 by default and at most."""
	try:
		p = int(df.precision) if df.precision not in (None, "") else money.DB_PLACES
	except (TypeError, ValueError):
		p = money.DB_PLACES
	return max(0, min(p, money.DB_PLACES))


def _refusal(e: money.DecimalInputError, label: str, value, places: int) -> str:
	shown = str(value).strip()
	if e.code == "PLACES":
		return _("{0}: {1} has more than {2} decimal places; this field keeps {2}.").format(label, shown, places)
	if e.code == "DIGITS":
		return _("{0}: {1} has more than {2} significant digits.").format(label, shown, money.DB_SAFE_DIGITS)
	if e.code == "RANGE":
		return _("{0}: {1} is too large.").format(label, shown)
	return _("{0}: {1} is not a number.").format(label, shown)


def typed(value, label: str, places: int = money.DB_PLACES):
	"""A value typed for a decimal field (an API argument) → its exact Decimal (None: blank), or
	the save is refused as ``check_inputs`` refuses it."""
	try:
		return money.db_input(value, places=places)
	except money.DecimalInputError as e:
		frappe.throw(_refusal(e, label, value, places), title=_("Invalid number"))


def check_inputs(doc, method=None) -> None:
	"""doc_event ``before_validate``: every decimal field of ``doc`` and its rows holds exactly
	what was typed (up to the field's places) or the save is refused, naming the field."""
	for d in (doc, *doc.get_all_children()):
		for df in d.meta.fields:
			if df.fieldtype not in FLOAT_LIKE:
				continue
			value = d.get(df.fieldname)
			if value is None or value == "":
				continue
			places = places_of(df)
			try:
				exact = money.db_input(value, places=places)
			except money.DecimalInputError as e:
				label = _(df.label or df.fieldname)
				if d is not doc:
					table = doc.meta.get_field(d.parentfield)
					label = _("{0}, row {1}, {2}").format(_(table.label if table else d.doctype), d.idx, label)
				frappe.throw(_refusal(e, label, value, places), title=_("Invalid number"))
			if not isinstance(value, str) and exact != money.D(value):
				d.set(df.fieldname, float(exact))      # binary noise: stored as the column rounds it


def api_value(value):
	"""A decimal field's value for JSON: exact decimal text ("0.333333333", "12.5", "100"),
	never a float. None stays None."""
	if value is None or value == "":
		return None
	return dec_str(money.db_dec(value))


def api_fields(row: dict, meta) -> dict:
	"""``row`` (a dict of a record of ``meta``'s DocType) with its decimal fields as ``api_value``."""
	for df in meta.fields:
		if df.fieldtype in FLOAT_LIKE and df.fieldname in row:
			row[df.fieldname] = api_value(row[df.fieldname])
	return row
