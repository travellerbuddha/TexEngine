"""Shared helpers for TEX API endpoints."""

from __future__ import annotations

import json

import frappe
from frappe import _

from kamra.tex.services.refusals import refusal


def parse(value, default=None):
	"""Accept JSON strings (form posts) or already-parsed values."""
	if value is None or value == "":
		return default
	if isinstance(value, str):
		try:
			return json.loads(value)
		except json.JSONDecodeError:
			frappe.throw(_("Invalid JSON payload."), refusal("INVALID_REQUEST"))
	return value


def text(value, max_len: int = 200) -> str | None:
	if value is None:
		return None
	v = str(value).strip()
	return v[:max_len] or None


def as_int(value, default=0, *, lo=None, hi=None) -> int:
	try:
		v = int(value)
	except (TypeError, ValueError):
		v = default
	if lo is not None:
		v = max(lo, v)
	if hi is not None:
		v = min(hi, v)
	return v


def rows(doc, table: str) -> list[dict]:
	"""A child table's rows; decimal fields as exact decimal strings (G-72), never floats."""
	from kamra.tex.commercial.decimals import api_fields

	return [api_fields({k: v for k, v in r.as_dict().items()
	                    if k not in ("owner", "creation", "modified", "modified_by", "parent", "parentfield",
	                                 "parenttype", "docstatus", "doctype")}, r.meta)
	        for r in (doc.get(table) or [])]


def doc_dict(doc, exclude=()) -> dict:
	"""A record for the TEX screens: tables as ``rows``, decimal fields as exact decimal strings
	(G-72, ADR-055), no password."""
	from kamra.tex.commercial.decimals import api_fields

	d = api_fields(doc.as_dict(no_default_fields=False), doc.meta)
	for k in ("owner", "docstatus", "doctype", "idx", "_user_tags", "_comments", "_assign", "_liked_by", *exclude):
		d.pop(k, None)
	for df in doc.meta.fields:
		if df.fieldtype == "Password":
			d.pop(df.fieldname, None)
		if df.fieldtype in ("Table", "Table MultiSelect"):
			d[df.fieldname] = rows(doc, df.fieldname)
	return d
