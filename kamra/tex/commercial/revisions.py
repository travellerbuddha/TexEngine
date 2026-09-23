"""Effective-dated revisions for selling policies (ADR-005) and immutability guards.

Markup rules, promotions, FX policies and pricing policies are never edited in place
once Active: ``revise`` clones the record into a Draft, ``activate`` makes the draft
Active and stamps ``active_to`` on the predecessor. ``as_of`` queries rebuild the rule
set that was in force at any past sale time — the basis of the historical simulator.
"""

from __future__ import annotations

from datetime import datetime, timedelta

import frappe
from frappe import _
from frappe.utils import get_datetime, now_datetime

REVISION_META = ("tex_status", "active_from", "active_to", "revision_no", "revision_of")
REVISIONED = frozenset({"TEX Markup Rule", "TEX Promotion", "TEX FX Policy", "TEX Pricing Policy", "TEX Extra",
                        "TEX Tax Policy"})


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
	if doc.get("revision_of") and doc.meta.has_field("property"):
		# a revision belongs to its record's hotel: a draft moved to another hotel would,
		# once activated, end the first hotel's record
		root_prop = frappe.db.get_value(doc.doctype, doc.revision_of, "property")
		if (root_prop or None) != (doc.get("property") or None):
			frappe.throw(_("A revision stays at its record's hotel ({0}).").format(root_prop or _("all hotels")))
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


def system_time(at) -> datetime:
	"""A naive datetime in the site's time zone. A time with an offset (the browser sends one,
	so a picker in another time zone means the same instant) is converted."""
	dt = get_datetime(at)
	if dt.tzinfo:
		from zoneinfo import ZoneInfo

		from frappe.utils import get_system_timezone

		dt = dt.astimezone(ZoneInfo(get_system_timezone())).replace(tzinfo=None)
	return dt


# a client's "now" (minute-precision picker, clock skew) may trail the server's; within
# this window it means now, beyond it the activation would rewrite history
BACKDATE_TOLERANCE = timedelta(minutes=5)


def activate(doctype: str, name: str, at=None, *, backdate: bool = False) -> None:
	"""Put a draft live from ``at`` (default now; a future time schedules it).

	History is never rewritten: ``as_of`` must answer what was on sale at any past time,
	so a revision cannot go live in the past, nor before a revision already scheduled.
	Only trusted code (migrations, test fixtures) passes ``backdate`` (G-20)."""
	_check_doctype(doctype)
	doc = frappe.get_doc(doctype, name)
	if doc.tex_status != "Draft":
		frappe.throw(_("Only drafts can be activated."))
	now = now_datetime()
	at = system_time(at) if at else now
	if at < now and not backdate:
		if now - at > BACKDATE_TOLERANCE:
			frappe.throw(_("A revision cannot go live in the past ({0}); what was on sale then stays as it was.")
			             .format(at), title=_("Back-dated activation"))
		at = now
	root = doc.revision_of
	if root:
		later = frappe.db.sql(f"""SELECT name, active_from FROM `tab{doctype}` WHERE (name=%s OR revision_of=%s)
		                          AND tex_status IN ('Active','Superseded') AND active_from > %s
		                          ORDER BY active_from LIMIT 1""", (root, root, at), as_dict=True)
		if later:
			frappe.throw(_("{0} is already scheduled from {1}; activate this revision after that time, or "
			               "archive that one first.").format(later[0].name, later[0].active_from))
		# every sibling still live at ``at`` ends there, so one revision of a record is live at a time
		for pred in frappe.db.sql_list(f"""SELECT name FROM `tab{doctype}` WHERE (name=%s OR revision_of=%s)
		                                   AND tex_status IN ('Active','Superseded')
		                                   AND (active_to IS NULL OR active_to > %s)""", (root, root, at)):
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


def archive(doctype: str, name: str) -> None:
	"""Take a revision out of sale from now (a draft is simply deleted). Archiving a
	revision scheduled for later cancels it: it never goes live and the revision it was
	to replace stays live, so archiving never leaves a gap that nobody chose."""
	_check_doctype(doctype)
	doc = frappe.get_doc(doctype, name)
	if doc.tex_status == "Draft":
		doc.flags.tex_system_update = True
		frappe.delete_doc(doctype, name, ignore_permissions=True)  # its audit events stay
		return
	now = now_datetime()
	start = get_datetime(doc.active_from) if doc.active_from else now
	live_now = start <= now and (not doc.active_to or get_datetime(doc.active_to) > now)
	if live_now:
		# off sale from now, whether it is the current revision or one still live until its
		# scheduled successor starts
		doc.active_to = now
	elif start > now:
		# a cancelled schedule (Active, or Superseded by a later schedule): it never goes live,
		# and the revision it was to replace takes its window over, so an archived revision is
		# never live and nothing is left uncovered
		old_to = doc.active_to
		doc.active_to = start
		root = doc.revision_of or doc.name
		for pred in frappe.db.sql_list(f"""SELECT name FROM `tab{doctype}` WHERE (name=%s OR revision_of=%s)
		                                   AND name != %s AND tex_status='Superseded' AND active_to=%s""",
		                               (root, root, doc.name, start)):
			p = frappe.get_doc(doctype, pred)
			p.tex_status = "Active" if old_to is None else "Superseded"
			p.active_to = old_to
			p.flags.tex_revision_transition = True
			p.save(ignore_permissions=True)
	doc.tex_status = "Archived"
	doc.flags.tex_revision_transition = True
	doc.save(ignore_permissions=True)


def live_or_scheduled_roots(doctype: str, filters: dict, *, exclude_root: str | None = None,
                            for_update: bool = False) -> list[str]:
	"""Roots of ``doctype`` records matching ``filters`` with a revision live now or later
	(by window, not by status: a superseded revision stays live until its successor starts).

	A None filter value matches a blank field, as in ``as_of`` (a global pricing policy has
	no hotel and no market). ``for_update`` makes it a locking read: it sees what another
	transaction committed meanwhile and holds the rows until commit, so two activations of
	one scope run one after the other."""
	_check_doctype(doctype)
	conds, params = [], {"now": now_datetime(), "ex": exclude_root or ""}
	for i, (k, v) in enumerate(filters.items()):
		if not k.isidentifier():
			raise ValueError("invalid field name")
		if v is None:
			conds.append(f"IFNULL(`{k}`, '') = ''")
		else:
			conds.append(f"`{k}` = %(f{i})s")
			params[f"f{i}"] = v
	return frappe.db.sql_list(
		f"""SELECT DISTINCT IFNULL(revision_of, name) FROM `tab{doctype}`
		    WHERE {' AND '.join(conds) or '1=1'} AND tex_status IN ('Active','Superseded')
		      AND (active_to IS NULL OR active_to > %(now)s) AND IFNULL(revision_of, name) != %(ex)s
		    {'FOR UPDATE' if for_update else ''}""", params)


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
