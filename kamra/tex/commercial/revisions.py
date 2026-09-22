"""Effective-dated revisions for selling policies (ADR-005) and immutability guards.

Markup rules, promotions, FX policies and pricing policies are never edited in place
once Active: ``revise`` clones the record into a Draft, ``activate`` makes the draft
Active and stamps ``active_to`` on the predecessor. ``as_of`` queries rebuild the rule
set that was in force at any past sale time — the basis of the historical simulator.
"""

from __future__ import annotations

import frappe
from frappe import _
from frappe.utils import get_datetime, now_datetime

REVISION_META = ("tex_status", "active_from", "active_to", "revision_no", "revision_of")
REVISIONED = frozenset({"TEX Markup Rule", "TEX Promotion", "TEX FX Policy", "TEX Pricing Policy"})


def _check_doctype(doctype: str) -> None:
	# table names are interpolated into SQL below: only the known revisioned DocTypes
	if doctype not in REVISIONED:
		raise ValueError(f"{doctype} is not a revisioned DocType")
LIVE = ("Active", "Superseded", "Archived")


def _changed_fields(doc, ignore=()) -> list[str]:
	before = doc.get_doc_before_save()
	if not before:
		return []
	ignore = set(ignore) | {"modified", "modified_by", "idx"}
	changed = []
	for df in doc.meta.fields:
		if df.fieldtype in ("Section Break", "Column Break", "Tab Break") or df.fieldname in ignore:
			continue
		if df.fieldtype in ("Table", "Table MultiSelect"):
			a = [row.as_dict(no_default_fields=True) for row in (before.get(df.fieldname) or [])]
			b = [row.as_dict(no_default_fields=True) for row in (doc.get(df.fieldname) or [])]
			strip = lambda rows: [{k: v for k, v in r.items() if k not in ("name", "idx", "parent", "modified")}  # noqa: E731
			                      for r in rows]
			if strip(a) != strip(b):
				changed.append(df.fieldname)
			continue
		if not _same(df.fieldtype, before.get(df.fieldname), doc.get(df.fieldname)):
			changed.append(df.fieldname)
	return changed


NUMERIC = ("Currency", "Float", "Int", "Percent", "Check", "Rating")


def _same(fieldtype: str, a, b) -> bool:
	"""Value equality as stored: numbers compare numerically (DB 100.0 == Decimal 100.00)."""
	if fieldtype in NUMERIC:
		from kamra.tex.money import D

		try:
			return D(a or 0) == D(b or 0)
		except (ValueError, TypeError):
			pass
	return str(a or "") == str(b or "")


def guard_revisioned(doc) -> None:
	"""Controller hook (validate): live revisions are immutable except their lifecycle
	fields, which only the revision service changes (flag ``tex_revision_transition``)."""
	if doc.is_new():
		# a new record is always a Draft: going live is Activate's job, whatever the
		# payload says (no mass-assigned live rows through generic REST inserts)
		if not doc.flags.tex_revision_transition:
			doc.tex_status = "Draft"
			doc.active_from = None
			doc.active_to = None
			doc.revision_of = None
			doc.revision_no = 1
			if doc.meta.has_field("times_redeemed"):
				doc.times_redeemed = 0
		if not doc.get("tex_status"):
			doc.tex_status = "Draft"
		if not doc.get("revision_no"):
			doc.revision_no = 1
		return
	before = doc.get_doc_before_save()
	if not before or before.get("tex_status") == "Draft":
		if doc.get("tex_status") != (before.get("tex_status") if before else "Draft") \
				and not doc.flags.tex_revision_transition:
			frappe.throw(_("Use Activate to put a revision live."))
		return
	changed = [f for f in _changed_fields(doc) if f not in REVISION_META]
	if changed:
		frappe.throw(_("{0} {1} is live and cannot be edited ({2}). Create a new revision instead.").format(
			doc.doctype, doc.name, ", ".join(changed)), title=_("Immutable revision"))
	if not doc.flags.tex_revision_transition and any(
			str(before.get(f) or "") != str(doc.get(f) or "") for f in REVISION_META):
		frappe.throw(_("Revision lifecycle fields are managed by TEX."))


def guard_immutable(doc, allowed=()) -> None:
	"""Controller hook: once inserted, only ``allowed`` fields may change."""
	if doc.is_new() or doc.flags.tex_system_update:
		return
	changed = [f for f in _changed_fields(doc) if f not in allowed]
	if changed:
		frappe.throw(_("{0} records are immutable ({1}).").format(doc.doctype, ", ".join(changed)),
		             title=_("Immutable record"))


def block_delete(doc, when=lambda d: True) -> None:
	if when(doc) and not doc.flags.tex_system_update:
		frappe.throw(_("{0} {1} cannot be deleted; archive it instead.").format(doc.doctype, doc.name))


def revise(doctype: str, name: str) -> str:
	_check_doctype(doctype)
	src = frappe.get_doc(doctype, name)
	if src.tex_status not in ("Active", "Superseded"):
		frappe.throw(_("Only live revisions can be revised; edit the draft instead."))
	root = src.revision_of or src.name
	max_no = frappe.db.sql(f"SELECT MAX(revision_no) FROM `tab{doctype}` WHERE name=%s OR revision_of=%s",
	                       (root, root))[0][0] or 1
	new = frappe.copy_doc(src)
	new.tex_status = "Draft"
	new.active_from = None
	new.active_to = None
	new.revision_of = root
	new.revision_no = int(max_no) + 1
	new.flags.tex_revision_transition = True
	new.insert(ignore_permissions=True)
	return new.name


def activate(doctype: str, name: str, at=None) -> None:
	doc = frappe.get_doc(doctype, name)
	if doc.tex_status != "Draft":
		frappe.throw(_("Only drafts can be activated."))
	at = get_datetime(at) if at else now_datetime()
	root = doc.revision_of
	if root:
		for pred in frappe.get_all(doctype, filters={"tex_status": "Active"},
		                           or_filters={"name": root, "revision_of": root}, pluck="name"):
			p = frappe.get_doc(doctype, pred)
			p.tex_status = "Superseded"
			p.active_to = at
			p.flags.tex_revision_transition = True
			p.save(ignore_permissions=True)
	doc.tex_status = "Active"
	doc.active_from = at
	doc.active_to = None
	doc.flags.tex_revision_transition = True
	doc.save(ignore_permissions=True)


def archive(doctype: str, name: str, at=None) -> None:
	doc = frappe.get_doc(doctype, name)
	if doc.tex_status == "Draft":
		doc.flags.tex_system_update = True
		frappe.delete_doc(doctype, name, ignore_permissions=True)
		return
	if doc.tex_status == "Active":
		doc.active_to = get_datetime(at) if at else now_datetime()
	doc.tex_status = "Archived"
	doc.flags.tex_revision_transition = True
	doc.save(ignore_permissions=True)


def as_of(doctype: str, at, filters: dict | None = None, fields=("name",)) -> list[dict]:
	"""Records that were live at ``at`` (active_from <= at < active_to)."""
	_check_doctype(doctype)
	at = get_datetime(at)
	conds = ["tex_status IN ('Active','Superseded','Archived')", "active_from <= %(at)s",
	         "(active_to IS NULL OR active_to > %(at)s)"]
	params = {"at": at}
	for i, (k, v) in enumerate((filters or {}).items()):
		if not k.isidentifier() or not all(f.isidentifier() for f in fields):
			raise ValueError("invalid field name")
		if isinstance(v, list | tuple):
			conds.append(f"`{k}` IN %(f{i})s")
			params[f"f{i}"] = tuple(v)
		elif v is None:
			conds.append(f"IFNULL(`{k}`, '') = ''")
		else:
			conds.append(f"`{k}` = %(f{i})s")
			params[f"f{i}"] = v
	cols = ", ".join(f"`{f}`" for f in fields)
	return frappe.db.sql(f"SELECT {cols} FROM `tab{doctype}` WHERE {' AND '.join(conds)} ORDER BY name",
	                     params, as_dict=True)
