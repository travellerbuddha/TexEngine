"""Rates & Contracts API (R-04, R-05, R-10, R-11, Phase 4)."""

from __future__ import annotations

import json
import time
from contextlib import contextmanager, nullcontext
from datetime import date

import frappe
from frappe import _
from frappe.utils import cint, get_datetime, getdate, now_datetime

from kamra.tex import money
from kamra.tex.api._util import as_int, doc_dict, parse, text
from kamra.tex.commercial import context as ctxmod
from kamra.tex.commercial import contracts as svc
from kamra.tex.commercial import decimals
from kamra.tex.pricing import ages, engine, matrix, occupancy
from kamra.tex.pricing.enums import Op
from kamra.tex.pricing.model import ChildSpec, PricingError, StayRequest, Unsellable
from kamra.tex.security import scope
from kamra.tex.security.audit import audit
from kamra.tex.services.txn import retry_on_deadlock

CONTRACT_FIELDS = ("contract_code", "contract_name", "market", "status", "pricing_basis", "contract_currency",
                   "sell_currency", "priority", "is_bar", "sale_from", "sale_to", "stay_from", "stay_to", "notes")
# fixed once a version was published (G-50, ADR-045): the controller refuses, the UI shows them read-only
LOCKED_AFTER_PUBLISH = (*svc.FIXED_FIELDS, *svc.SELLING_FIELDS, "channels")
VERSION_SETTINGS = svc.DRAFT_SETTINGS
VERSION_TABLES = ("rooms", "periods", "period_rates", "age_bands", "occupancy_rules", "boards", "rate_plans",
                  "offers")
# what a posted row carries that is not its content: the server's bookkeeping (client keys start with "_")
ROW_BOOKKEEPING = ("name", "parent", "parenttype", "parentfield", "doctype", "idx", "creation", "modified", "owner",
                   "modified_by", "docstatus")
# the most rows a draft previewed with unsaved changes may have, over all its tables (ADR-061)
OVERLAY_MAX_ROWS = 5000
# per user (ADR-061, S16 review): the calls a minute and the calls running at once of the workspace's
# heavy reads — "validate": validate_version (10–16 s near the row cap, with or without data);
# "matrix": price_matrix with unsaved data or sample parties; "preview": preview_price with unsaved
# data (the same overlay; the price test's Live mode). An aborted fetch does not stop the server, so
# the client's one-call-in-flight is no bound.
HEAVY_LIMITS = {"validate": (60, 3), "matrix": (120, 6), "preview": (120, 6)}
HEAVY_WINDOW = 60              # seconds of a budget
HEAVY_RUNNING_TTL = 300        # a crashed call's slot is freed this many seconds after the call started
# the budget in one step: counted, and given its window when it has none. Two separate steps (SET NX
# EX, then INCR) left a counter without a TTL when the window ran out between them, and its user was
# refused for good (S16 review); a counter left so is healed by its next use.
_BUDGET_SCRIPT = """local n = redis.call('INCR', KEYS[1])
if redis.call('TTL', KEYS[1]) < 0 then redis.call('EXPIRE', KEYS[1], ARGV[1]) end
return n"""
# a call's slot is its start time in a sorted set: slots older than the TTL are dropped first, so a
# crashed call's slot ages out however often its user retries meanwhile; → the calls running now
_SLOT_SCRIPT = """redis.call('ZREMRANGEBYSCORE', KEYS[1], '-inf', tonumber(ARGV[1]) - tonumber(ARGV[2]))
redis.call('ZADD', KEYS[1], ARGV[1], ARGV[3])
redis.call('EXPIRE', KEYS[1], ARGV[2])
return redis.call('ZCARD', KEYS[1])"""


class OverlayTooLarge(frappe.ValidationError):
	"""The overlay's refusal of a draft above ``OVERLAY_MAX_ROWS`` (still a ValidationError, 417):
	typed, so the workspace can tell it from any other refusal and ask for the saved draft by name,
	which has no cap (ADR-061, S8 review follow-up)."""


def _workspace(flag, *new_args) -> bool:
	"""Whether a call asks for the Pricing Workspace's additions (ADR-061, "Existing semantics kept,
	the workspace's additions opt-in"): the ``workspace`` flag it sends (``1``/``true``), or an
	argument only the workspace sends (``data``, ``parties``). Without either, an endpoint answers
	an existing caller exactly as main did; the security and tenancy fixes hold either way."""
	return str(flag).strip().lower() in ("1", "true") or any(_has_data(a) for a in new_args)


@frappe.whitelist()
def list_contracts(property: str | None = None, status: str | None = None, market: str | None = None):
	props = [property] if property else sorted(scope.permitted_properties())
	for p in props:
		scope.require("price.view", p)
	filters = {"property": ("in", props or ["__none__"])}
	if status:
		filters["status"] = status
	if market:
		filters["market"] = market
	rows = frappe.get_all("TEX Contract", filters=filters,
	                      fields=["name", "property", "contract_code", "contract_name", "market", "status",
	                              "pricing_basis", "contract_currency", "sale_from", "sale_to", "stay_from", "stay_to",
	                              "active_version", "latest_version_no", "priority", "modified"],
	                      order_by="property asc, status asc, contract_code asc")
	drafts = {r.contract for r in frappe.get_all("TEX Contract Version",
	                                             filters={"status": "Draft", "contract": ("in", [r.name for r in rows]
	                                                                                      or ["__none__"])},
	                                             fields=["contract"])}
	for r in rows:
		r["has_draft"] = r.name in drafts
	return rows


@frappe.whitelist()
def get_contract(name: str):
	c = frappe.get_doc("TEX Contract", name)
	scope.require("price.view", c.property)
	versions = frappe.get_all("TEX Contract Version", filters={"contract": name},
	                          fields=["name", "version_no", "status", "effective_from", "active_to", "published_at",
	                                  "published_by", "change_note", "payload_hash", "based_on"],
	                          order_by="version_no desc")
	can_publish = scope.has_capability("contract.publish", c.property)
	published = any(v.status != "Draft" for v in versions)
	now = now_datetime()
	for v in versions:
		# published but not yet selling: withdrawing it cancels it and the one before keeps selling (Y-2)
		v.scheduled = v.status == "Published" and bool(v.effective_from) and get_datetime(v.effective_from) > now
	live = svc.active_version_header(name, now)
	try:
		live_selling = svc.version_selling(live.version_id).as_dict() if live else None
	except frappe.ValidationError:          # a payload failing its integrity check sells nothing
		live_selling = None
	return {"contract": doc_dict(c), "versions": versions,
	        "can_edit": scope.has_capability("contract.edit", c.property), "can_publish": can_publish,
	        # G-50: after the first publish these belong to the versions (header = the live version's)
	        "published": published, "locked_fields": list(LOCKED_AFTER_PUBLISH) if published else [],
	        "status_actions": svc.status_actions(c.status) if can_publish else [],
	        # what the live version sells (a version frozen before G-50: narrowed by its header)
	        "live_selling": live_selling}


@frappe.whitelist(methods=["POST"])
def save_contract(data):
	data = parse(data, {})
	prop = data.get("property")
	if data.get("name"):
		doc = frappe.get_doc("TEX Contract", data["name"])
		prop = doc.property
	else:
		doc = frappe.new_doc("TEX Contract")
		doc.property = prop
	scope.require("contract.edit", prop)
	for f in CONTRACT_FIELDS:
		if f in data:
			doc.set(f, data[f])
	if "channels" in data:
		doc.set("channels", [{"sales_channel": c} for c in (data.get("channels") or [])])
	# the controller refuses a published contract's commercial fields and a free status change,
	# and audits every changed field, channels included (G-50)
	doc.save(ignore_permissions=True)
	if not frappe.db.exists("TEX Contract Version", {"contract": doc.name}):
		svc.new_draft(doc.name)
	return get_contract(doc.name)


@frappe.whitelist(methods=["POST"])
def duplicate_contract(name: str, contract_code: str, contract_name: str | None = None, market: str | None = None):
	"""Copy a contract and its latest version into a new draft contract (R-55)."""
	src = frappe.get_doc("TEX Contract", name)
	scope.require("contract.edit", src.property)
	new = frappe.copy_doc(src)
	new.contract_code = text(contract_code, 40)
	new.contract_name = text(contract_name, 140) or f"{src.contract_name} (copy)"
	new.market = market or src.market
	new.status = "Draft"
	new.active_version = None
	new.latest_version_no = 0
	new.insert(ignore_permissions=True)
	latest = frappe.db.get_value("TEX Contract Version", {"contract": name}, "name", order_by="version_no desc")
	if latest:
		v = frappe.copy_doc(frappe.get_doc("TEX Contract Version", latest))
		for f in ("status", "published_at", "published_by", "active_to", "effective_from", "payload", "payload_hash",
		          "validation_report", "change_note", "based_on"):
			v.set(f, None)
		v.contract = new.name
		v.status = "Draft"
		v.insert(ignore_permissions=True)
	audit("contract.duplicate", reference_doctype="TEX Contract", reference_name=new.name, property=src.property,
	      new={"from": name})
	return get_contract(new.name)


def _sees_cost(prop: str | None) -> bool:
	"""Contract rates, supplements, formulas and offers are cost (G-11): shown to who may see
	cost or edits contracts, never to an agent who only sells."""
	return scope.has_capability("price.view_cost", prop) or scope.has_capability("contract.edit", prop)


def _catalogue(v, prop: str, workspace: bool = False) -> dict:
	"""What selling needs from a version (rooms, boards, rate plans), without any amount; for the
	workspace also what it may offer (nothing: ``can_*`` false)."""
	c = frappe.db.get_value("TEX Contract", v.contract, ["name", "property", "contract_code", "contract_name",
	                                                     "market", "contract_currency", "status"], as_dict=True)
	return {
		"name": v.name, "contract": v.contract, "version_no": v.version_no, "status": v.status,
		"rooms": [{"room_type": r.room_type} for r in v.rooms],
		"boards": [{"board": b.board} for b in v.boards],
		"rate_plans": [{"rate_plan": r.rate_plan, "refundable": r.refundable} for r in v.rate_plans],
		"room_types": frappe.get_all("Room Type", filters={"property": prop, "disabled": 0},
		                             fields=["name", "room_type_name", "adults_capacity", "children_capacity"],
		                             order_by="room_type_name"),
		"rate_plan_options": frappe.get_all("Rate Plan", filters={"property": prop, "disabled": 0},
		                                    fields=["name", "rate_plan_name", "code", "tex_refundable"]),
		"contract_doc": dict(c or {}), "editable": False, "cost_hidden": True,
		**({"can_preview": False, "can_publish": False, "can_edit_contract": False} if workspace else {}),
	}


@frappe.whitelist()
def get_version(name: str, workspace=None):
	"""A version as its viewer may read it. ``workspace`` (ADR-061 GAP-10, opt-in): also what the
	workspace may offer the viewer, whether the pricing basis is locked, the overlay's row cap and
	the currency's minor units. The report stored at publish is given to an editor without cost as
	the live check gives it, whoever asks (S16 re-review; a security fix, ADR-061)."""
	ws = _workspace(workspace)
	v = frappe.get_doc("TEX Contract Version", name)
	prop = scope.property_of("TEX Contract Version", name)
	scope.require("price.view", prop)
	if not _sees_cost(prop):
		return _catalogue(v, prop, ws)
	out = doc_dict(v, exclude=("payload",))
	# the report stored at publish, as the live check gives it to this viewer (S16 re-review); worked
	# out once per report, and a stored sweep at its limit run again as a bounded check (S16 re-review 5)
	out["validation_report"] = svc.stored_report(v, formula=scope.has_capability("price.view_cost", prop),
	                                             bound=lambda: _heavy("validate"))
	out["editable"] = v.status == "Draft" and scope.has_capability("contract.edit", prop)
	if ws:
		# what the workspace may offer this viewer (ADR-061); the endpoints check again
		out["can_preview"] = scope.has_capability("price.view_cost", prop)
		out["can_publish"] = scope.has_capability("contract.publish", prop)
		out["can_edit_contract"] = scope.has_capability("contract.edit", prop)
		# the header's pricing basis is fixed once a version was published (the controller's own test)
		out["basis_locked"] = svc.is_published(v.contract)
		if out["editable"]:
			# what the workspace previews with unsaved changes; above it, it asks for the saved draft
			out["overlay_max_rows"] = OVERLAY_MAX_ROWS
	c = frappe.get_doc("TEX Contract", v.contract)
	out["contract_doc"] = {f: c.get(f) for f in ("name", "property", "contract_code", "contract_name", "market",
	                                             "pricing_basis", "contract_currency", "status")}
	if ws:
		out["contract_doc"]["minor_units"] = money.minor_units(c.contract_currency)
	out.update(_selling(v, c))
	out["room_types"] = frappe.get_all("Room Type", filters={"property": c.property, "disabled": 0},
	                                   fields=["name", "room_type_name", "adults_capacity", "children_capacity",
	                                           "max_total_occupants", "base_occupancy"], order_by="room_type_name")
	out["rate_plan_options"] = frappe.get_all("Rate Plan", filters={"property": c.property, "disabled": 0},
	                                          fields=["name", "rate_plan_name", "code", "tex_refundable"])
	return out


def _selling(v, c) -> dict:
	"""A version's selling terms (G-50, ADR-045): what a published version froze; a draft's own
	once the contract was published; before that, the contract header's (edited there)."""
	if v.status != "Draft" and v.payload:
		# what it sells: a version frozen before G-50 stays narrowed by its header (``legacy``)
		return {"selling": svc.version_selling(v.name).as_dict(), "selling_source": "frozen",
		        "selling_editable": False}
	if svc.is_published(c.name):
		return {"selling": svc.selling_values(v), "selling_source": "version",
		        "selling_editable": scope.has_capability("contract.edit", c.property)}
	return {"selling": svc.selling_values(c), "selling_source": "header", "selling_editable": False}


def _set_selling(v, selling) -> None:
	if not isinstance(selling, dict):
		frappe.throw(_("Selling terms must be an object."))
	if not svc.is_published(v.contract):
		frappe.throw(_("Until the contract's first publish, its sale and stay windows, channels, priority and "
		               "sell currency are edited on the contract (Edit header)."))
	values = {}
	for f in ("sale_from", "sale_to", "stay_from", "stay_to", "sell_currency"):
		if f in selling:
			values[f] = text(selling[f], 20)
	if "priority" in selling:
		values["priority"] = as_int(selling["priority"], 0, lo=-9999, hi=9999)
	if "channels" in selling:
		chans = selling["channels"] or []
		if not isinstance(chans, list):
			frappe.throw(_("Channels must be a list."))
		values["channels"] = sorted({text(ch, 140) for ch in chans if text(ch, 140)})
	svc.set_selling(v, values)


@frappe.whitelist(methods=["POST"])
def save_version(name: str, data, workspace=None):
	"""Replace the draft's settings, selling terms and child tables in one call. The editor saves
	on demand (Save, Ctrl+S), never per keystroke; each save that changes something is audited
	old → new by the version's controller (G-74). ``workspace`` (ADR-061, opt-in): a blank rule
	value is refused (GAP-8) instead of being stored as 0 as main stores it, and the answer is
	``get_version``'s for the workspace."""
	ws = _workspace(workspace)
	data = parse(data, {})
	v = frappe.get_doc("TEX Contract Version", name)
	prop = scope.property_of("TEX Contract Version", name)
	scope.require("contract.edit", prop)
	if v.status != "Draft":
		frappe.throw(_("Only draft versions can be edited — create a new draft."))
	if "selling" in data:
		_set_selling(v, data["selling"])
	for f in VERSION_SETTINGS:
		if f in data:
			v.set(f, data[f])
	for t in VERSION_TABLES:
		if t in data:
			v.set(t, _clean_rows(data[t]))
	if ws:
		_require_values(v)
	v.save(ignore_permissions=True)
	return get_version(name, workspace=1 if ws else None)


def _clean_rows(rows) -> list[dict]:
	"""A posted table's rows without the client's keys (``_*``) and the server's bookkeeping."""
	return [{k: val for k, val in row.items() if not k.startswith("_") and k not in ROW_BOOKKEEPING}
	        for row in rows or []]


def _blank(value) -> bool:
	return value is None or (isinstance(value, str) and not value.strip())


# (table, value field, whether a row needs a value) — GAP-8
_VALUE_REQUIRED = (
	("period_rates", "value", lambda r: (r.op or "").strip() != "INHERIT"),
	("occupancy_rules", "value", lambda r: (r.op or "").strip() != "INHERIT"),
	("boards", "adult_amount", lambda r: not cint(r.is_base)),
	# an op needs its value: a blank night adjustment or rate plan value priced every night at 0
	("periods", "adjustment_value", lambda r: (r.adjustment_op or "").strip() not in ("", "INHERIT")),
	("rate_plans", "value", lambda r: (r.op or "").strip() not in ("", "INHERIT")),
)


def _require_values(v) -> None:
	"""A rule's value is never left blank (GAP-8, ADR-061): Frappe would store a blank as 0 and
	the draft would price it as 0. INHERIT rules and the included board have no value; to remove
	a price the editor removes its row. A period's night adjustment and a rate plan's adjustment
	need a value only with an op (S16 review)."""
	for table, field, needs in _VALUE_REQUIRED:
		for row in v.get(table) or []:
			if needs(row) and _blank(row.get(field)):
				label = _(v.meta.get_field(table).label)
				frappe.throw(_("{0}, row {1}: a value is required; clear the cell to remove the price.")
				             .format(label, row.idx))


def _overlay(name: str, data):
	"""The draft ``name`` with the editor's unsaved ``data`` applied in memory, never saved
	(GAP-1, ADR-061): the Pricing Workspace prices, validates and quotes what it shows before
	anyone saves. ``data`` is what ``save_version`` takes and is applied the same way (the same
	row cleaning, selling terms and settings), then checked as a save checks it: blank values,
	decimal places, mandatory fields, select options and lengths. Each row is named after its
	client key (``~<_key>``, else ``~<table>-<position>``), so the rule ids of an explanation or an
	issue point back to the row; a name used twice in one table is refused. Only drafts, only for
	who may edit them; nothing is written or audited."""
	data = parse(data, {})
	if not isinstance(data, dict):
		frappe.throw(_("Invalid JSON payload."))
	v = frappe.get_doc("TEX Contract Version", name)
	prop = scope.property_of("TEX Contract Version", name)
	scope.require("contract.edit", prop)
	if v.status != "Draft":
		frappe.throw(_("Only draft versions can be previewed with unsaved changes."))
	for t in VERSION_TABLES:
		rows = data.get(t)
		if t in data and rows is not None and not (isinstance(rows, list) and all(isinstance(r, dict) for r in rows)):
			frappe.throw(_("Invalid JSON payload."))
	total = sum(len(data[t] or []) if t in data else len(v.get(t) or []) for t in VERSION_TABLES)
	if total > OVERLAY_MAX_ROWS:
		frappe.throw(_("A draft previewed with unsaved changes has at most {0} rows; this one has {1}.")
		             .format(OVERLAY_MAX_ROWS, total), OverlayTooLarge)
	if "selling" in data:
		_set_selling(v, data["selling"])
	for f in VERSION_SETTINGS:
		if f in data:
			v.set(f, data[f])
	for t in VERSION_TABLES:
		if t in data:
			keys = [text(row.get("_key"), 100) for row in data[t] or []]
			names = [f"~{key}" if key else f"~{t}-{i + 1}" for i, key in enumerate(keys)]
			# issue refs and matrix sources name a row by this: it must name one row of the table
			seen: set[str] = set()
			for row_name in names:
				if row_name in seen:
					frappe.throw(_("{0}: two rows have the key {1}; each row needs its own key.")
					             .format(_(v.meta.get_field(t).label), row_name[1:]))
				seen.add(row_name)
			v.set(t, _clean_rows(data[t]))
			for child, row_name in zip(v.get(t), names, strict=True):
				child.name = row_name
	_require_values(v)
	# what a save runs before it writes, none of which writes: the DocType defaults, the decimal
	# check (before_validate) and Frappe's own field checks
	v._set_defaults()
	decimals.check_inputs(v)
	v._validate_mandatory()
	for d in (v, *v.get_all_children()):
		d._validate_data_fields()
		d._validate_selects()
		d._validate_non_negative()
		d._validate_length()
	for d in (v, *v.get_all_children()):
		_as_stored(d)
	return v


def _as_stored(d) -> None:
	"""``d``'s values as a save stores them and a load reads them back: checks 0/1, integers,
	decimals as the exact Decimal (a blank one is 0), a blank date none. The overlay then prices
	what a save would."""
	for df in d.meta.fields:
		f, value = df.fieldname, d.get(df.fieldname)
		if df.fieldtype == "Check":
			d.set(f, 1 if cint(value) else 0)
		elif df.fieldtype == "Int":
			d.set(f, cint(value))
		elif df.fieldtype in decimals.FLOAT_LIKE:
			d.set(f, money.db_input(value, places=decimals.places_of(df)) or money.ZERO)
		elif df.fieldtype in ("Date", "Datetime") and value == "":
			d.set(f, None)


def _has_data(data) -> bool:
	return data is not None and data != ""


def _in_request() -> bool:
	"""A web request (what the heavy-read budget counts); a job, the console or a test calling the
	function directly is not counted."""
	return bool(getattr(frappe.local, "request", None))


def _heavy_key(kind: str, what: str, user: str | None = None) -> str:
	return frappe.cache.make_key(f"tex:heavy:{kind}:{what}:{user or frappe.session.user}")


def _now() -> float:
	return time.time()


@contextmanager
def _heavy(kind: str):
	"""A heavy read of ``kind`` (``HEAVY_LIMITS``) by the session user: refused with
	``RateLimitExceededError`` (429) above its budget a minute, or while as many of the user's own
	calls of that kind are still running (ADR-061, S16 review). Both counts are kept in redis, each in
	one atomic step (``_BUDGET_SCRIPT``, ``_SLOT_SCRIPT``)."""
	if not _in_request():
		yield
		return
	per_minute, at_once = HEAVY_LIMITS[kind]
	if frappe.cache.eval(_BUDGET_SCRIPT, 1, _heavy_key(kind, "minute"), HEAVY_WINDOW) > per_minute:
		frappe.throw(_("Too many price checks in a minute; wait a moment and try again."),
		             frappe.RateLimitExceededError)
	slots, token = _heavy_key(kind, "slots"), frappe.generate_hash(length=16)
	count = frappe.cache.eval(_SLOT_SCRIPT, 1, slots, repr(_now()), HEAVY_RUNNING_TTL, token)
	try:
		if count > at_once:
			frappe.throw(_("Your other price checks are still running; try again when they have finished."),
			             frappe.RateLimitExceededError)
		yield
	finally:
		frappe.cache.zrem(slots, token)


@frappe.whitelist()
def validate_version(name: str, data=None, workspace=None):
	"""Validate the saved draft, or with ``data`` the draft with those unsaved changes (ADR-061).
	For the workspace (``workspace`` or ``data``, opt-in): its board checks (GAP-5), each issue's
	``ref`` (D9), and bounded per user (``_heavy``: near the row cap one call takes 10–16 s).
	Without them the issues are main's and the call is not bounded, as on main.

	A viewer without ``price.view_cost`` gets no issue whose presence depends on the value of an
	inherited pricing-policy rule (its formula is cost, G-11): an overlay probe rule would otherwise
	find it by bisection without a save or an audit entry (S16 review; ``validate_terms(hidden=…)``).
	A security fix: it holds for every caller."""
	ws = _workspace(workspace, data)
	with _heavy("validate") if ws else nullcontext():
		formula = scope.has_capability("price.view_cost", scope.property_of("TEX Contract Version", name))
		if _has_data(data):
			return svc.validate_doc(_overlay(name, data), formula=formula, workspace=True)
		return svc.validate_version(name, formula=formula, workspace=ws)


@frappe.whitelist(methods=["POST"])
def publish_version(name: str, effective_from: str | None = None, change_note: str | None = None, workspace=None):
	"""Publish a draft. ``workspace`` (ADR-061, opt-in): the workspace's board checks block it as its
	live check reports them, and the stored report carries each issue's ``ref``. The ``warnings``
	answered are the stored report as ``get_version`` gives it to the caller: without
	``price.view_cost``, nothing that depends on a pricing policy's formulas (S16 re-review 4); without
	``contract.edit`` either, None (S16 re-review 5). A refused publish names to a caller without
	``price.view_cost`` only the errors its own live check shows (S16 re-review 5). Security fixes,
	for every caller."""
	return svc.publish(name, effective_from=effective_from or None, change_note=text(change_note, 500),
	                   workspace=_workspace(workspace))


@frappe.whitelist(methods=["POST"])
def new_draft(contract: str, based_on: str | None = None):
	return {"version": svc.new_draft(contract, based_on)}


@frappe.whitelist(methods=["POST"])
def set_contract_status(name: str, action: str, reason: str):
	"""Suspend (stop selling now), resume, archive or restore a contract (G-50): the only way a
	contract's status changes besides publishing; needs ``contract.publish``, a reason, and is audited."""
	return svc.set_status(name, (action or "").strip().lower(), text(reason, 500))


@frappe.whitelist(methods=["POST"])
@retry_on_deadlock
def withdraw_version(name: str, reason: str):
	# a booking locking its rooms' quotes in another order may meet the withdraw's quote locks: the
	# victim is rolled back whole and run again (O-13; booking.create_booking is retried the same way)
	svc.withdraw(name, text(reason, 500))
	return {"ok": True}


@frappe.whitelist(methods=["POST"])
def preview_price(version: str, room_type: str, board: str, check_in: str, check_out: str, adults: int = 2,
                  children=None, rate_plan: str | None = None, market: str | None = None, channel: str = "DIRECT_WEB",
                  currency: str | None = None, sale_at: str | None = None, promo_codes=None, data=None,
                  workspace=None):
	"""Price a stay on any version — including an unpublished draft — with the full
	explanation (contract editor 'test price' panel; also answers 'which rule won').

	For the Pricing Workspace's price test (``workspace`` or ``data``, opt-in, ADR-061): with
	``data`` on the draft with those unsaved changes (GAP-1); ``children`` each an age in whole
	years, ``{age_months}`` or ``{dob}``, anything else refused (``_child_specs``, GAP-6); each night
	reports the running totals the Explain ladder shows (``subtotal_*``, GAP-12). Without them the
	answer is main's: each child ``int()`` of what was sent, main's night keys."""
	v = frappe.get_doc("TEX Contract Version", version)
	prop = scope.property_of("TEX Contract Version", version)
	scope.require("price.view_cost", prop)
	if not _workspace(workspace, data):
		return _mains_preview(v, version, prop, room_type, board, check_in, check_out, adults, children, rate_plan,
		                      market, channel, currency, sale_at, promo_codes)
	# with data it builds the matrix's overlay (up to 5,000 rows): bounded per user as the matrix is
	with _heavy("preview") if _has_data(data) else nullcontext():
		return _preview_price(v, version, prop, room_type, board, check_in, check_out, adults, children, rate_plan,
		                      market, channel, currency, sale_at, promo_codes, data)


def _mains_preview(v, version, prop, room_type, board, check_in, check_out, adults, children, rate_plan, market,
                   channel, currency, sale_at, promo_codes) -> dict:
	"""``preview_price`` for an existing caller: main's body, unchanged (ADR-061)."""
	at = frappe.utils.get_datetime(sale_at) if sale_at else now_datetime()
	try:
		terms = svc.load_terms(version) if v.status != "Draft" else svc.build_terms(v, at=at)
	except frappe.ValidationError as e:
		return {"sellable": False, "reasons": [{"code": "BUILD", "message": str(e)}]}
	kids = tuple(ChildSpec(age=int(a)) for a in (parse(children, []) or []))
	req = StayRequest(property=prop, room_type=room_type, board=board, rate_plan=rate_plan or None,
	                  check_in=getdate(check_in), check_out=getdate(check_out), adults=as_int(adults, 2, lo=1, hi=12),
	                  children=kids, sale_at=at, market=(market or terms.market).upper(), channel=channel,
	                  sell_currency=(currency or terms.currency).upper(),
	                  promo_codes=tuple(parse(promo_codes, []) or ()))
	try:
		ctx = ctxmod.build_context(terms, req)
		q = engine.price_stay(ctx, req)
	except (Unsellable, PricingError) as e:
		return {"sellable": False, "reasons": [{"code": getattr(e, "code", "PRICING_ERROR"), "message": str(e)}]}
	return q.to_dict(internal=True)


def _preview_price(v, version, prop, room_type, board, check_in, check_out, adults, children, rate_plan, market,
                   channel, currency, sale_at, promo_codes, data) -> dict:
	at = frappe.utils.get_datetime(sale_at) if sale_at else now_datetime()
	kids = _child_specs(children, getdate(check_in))
	draft = _overlay(version, data) if _has_data(data) else None
	try:
		if draft is not None:
			terms = svc.build_terms(draft, at=at)
		else:
			terms = svc.load_terms(version) if v.status != "Draft" else svc.build_terms(v, at=at)
	except frappe.ValidationError as e:
		return {"sellable": False, "reasons": [{"code": "BUILD", "message": str(e)}]}
	req = StayRequest(property=prop, room_type=room_type, board=board, rate_plan=rate_plan or None,
	                  check_in=getdate(check_in), check_out=getdate(check_out), adults=as_int(adults, 2, lo=1, hi=12),
	                  children=kids, sale_at=at, market=(market or terms.market).upper(), channel=channel,
	                  sell_currency=(currency or terms.currency).upper(),
	                  promo_codes=tuple(parse(promo_codes, []) or ()))
	try:
		ctx = ctxmod.build_context(terms, req)
		q = engine.price_stay(ctx, req)
	except (Unsellable, PricingError) as e:
		return {"sellable": False, "reasons": [{"code": getattr(e, "code", "PRICING_ERROR"), "message": str(e)}]}
	return q.to_dict(internal=True, subtotals=True)


# the most children a preview prices (ADR-061 GAP-6); ages the way a guest's are given (0–17 years)
PREVIEW_CHILDREN_MAX = 12
CHILD_MONTHS_MAX = (ages.MAX_CHILD_AGE + 1) * 12 - 1      # 215: 17 years and 11 months


def _child_specs(children, check_in: date) -> tuple[ChildSpec, ...]:
	"""The preview's children (ADR-061 GAP-6), each one of:

	* an age in whole years 0–17: an int, a digit-only string or an integral float (as before);
	* ``{"age_months": n}``, an int 0–215, for the exact month a band starts or ends at;
	* ``{"dob": "YYYY-MM-DD"}``, checked as a booking checks it (``ages.check_child_dob``: not in the
	  future, under 18 on ``check_in``) and priced in completed months by the engine.

	Anything else (a bool, ``7.5``, ``"7.5"``, a negative or adult age, another key) is refused, and
	so are more than 12 children. A refusal never repeats a date of birth."""
	items = parse(children, [])
	if items is None:
		items = []
	if not isinstance(items, list):
		frappe.throw(_("Child ages are whole years (0–17), {age_months} or {dob}."))
	if len(items) > PREVIEW_CHILDREN_MAX:
		frappe.throw(_("A price test takes at most {0} children.").format(PREVIEW_CHILDREN_MAX))
	return tuple(_child_spec(item, n, check_in) for n, item in enumerate(items, 1))


def _child_spec(item, n: int, check_in: date) -> ChildSpec:
	years = None
	if isinstance(item, bool):
		years = None
	elif isinstance(item, int):
		years = item
	elif isinstance(item, float) and item.is_integer():
		years = int(item)
	elif isinstance(item, str) and item.strip().isascii() and item.strip().isdigit():
		years = int(item.strip())
	elif isinstance(item, dict) and set(item) == {"age_months"}:
		months = item["age_months"]
		if isinstance(months, int) and not isinstance(months, bool) and 0 <= months <= CHILD_MONTHS_MAX:
			return ChildSpec(age_months=months)
	elif isinstance(item, dict) and set(item) == {"dob"}:
		dob = _iso_date(item["dob"])
		if dob is not None:
			try:
				ages.check_child_dob(dob, check_in, today=getdate())
			except PricingError as e:
				frappe.throw(_("Child {0}: {1}").format(n, str(e)))
			return ChildSpec(dob=dob)
	if years is not None and 0 <= years <= ages.MAX_CHILD_AGE:
		return ChildSpec(age=years)
	frappe.throw(_("Child {0}: {1}").format(n, _("Child ages are whole years (0–17), {age_months} or {dob}.")))


def _iso_date(value) -> date | None:
	"""``YYYY-MM-DD`` → the date; anything else None (never echoed: a date of birth is personal)."""
	if not isinstance(value, str) or len(value.strip()) != 10:
		return None
	try:
		return date.fromisoformat(value.strip())
	except ValueError:
		return None


# the ops an entered price is adjusted by (ADR-061 GAP-7: the base room's relative entry, O4, and the
# bulk Adjust…), and the most prices one call adjusts
ADJUST_OPS = (Op.ABSOLUTE, Op.MULTIPLY, Op.PERCENT_OF, Op.ADJUST_PERCENT, Op.ADD, Op.SUBTRACT)
ADJUST_VALUES_MAX = 500


@frappe.whitelist(methods=["POST"])
def apply_op_values(version: str, values, op: str, value):
	"""Entered prices of a draft changed once by ``op`` ``value`` (ADR-061 GAP-7, D2): the workspace
	never computes money, so a relative entry on the base room (O4: "+10%" on 70.00 is stored as
	ABSOLUTE 77.00) and the bulk Adjust… preview ask the server. Each value is computed as the ARI
	grid's rate change computes one (``matrix.adjust_amount``: the op on the price, HALF_UP to the
	contract currency). Read-only: nothing is written or audited.

	``values``: at most 500 decimal strings (None or "" for a cell without a price). → one
	``{value, error}`` per value, in order: the new price as exact decimal text, or None with
	``NO_VALUE`` (no price given) or ``NEGATIVE`` (the result would be below zero)."""
	row = frappe.db.get_value("TEX Contract Version", version, ["contract", "status"], as_dict=True)
	if not row:
		frappe.throw(_("{0} {1} not found").format(_("TEX Contract Version"), version), frappe.DoesNotExistError)
	prop = scope.property_of("TEX Contract Version", version)
	scope.require("contract.edit", prop)
	if row.status != "Draft":
		frappe.throw(_("Only draft versions can be edited — create a new draft."))
	if op not in {o.value for o in ADJUST_OPS}:
		frappe.throw(_("An adjustment is an amount, a factor, a percentage or a change by an amount or a "
		               "percentage."))
	amount = _typed(value, _("Value"))
	if amount is None:
		frappe.throw(_("Value: a value is required."))
	items = parse(values, None)
	if not isinstance(items, list) or len(items) > ADJUST_VALUES_MAX:
		frappe.throw(_("Prices to adjust are a list of at most {0} values.").format(ADJUST_VALUES_MAX))
	currents = [_typed(v, _("Price {0}").format(i)) for i, v in enumerate(items, 1)]
	currency = frappe.db.get_value("TEX Contract", row.contract, "contract_currency")
	out = []
	for current in currents:
		if current is None:
			out.append({"value": None, "error": "NO_VALUE"})
			continue
		try:
			out.append({"value": money.to_str(matrix.adjust_amount(current, Op(op), amount, currency)),
			            "error": None})
		except PricingError as e:
			if str(e) != "NEGATIVE":
				raise
			out.append({"value": None, "error": "NEGATIVE"})
	return out


def _typed(value, label: str):
	"""``decimals.typed`` for an argument of any JSON shape: a list or an object is not a number."""
	if isinstance(value, (list, dict)):
		frappe.throw(_("{0}: {1} is not a number.").format(label, json.dumps(value)[:40]), title=_("Invalid number"))
	return decimals.typed(value, label)


# sample parties priced by ``price_matrix`` (ADR-061, GAP-2b): at most this many, of at most so many
# adults and children each
MATRIX_PARTIES_MAX, PARTY_ADULTS_MAX, PARTY_CHILDREN_MAX = 12, 12, 8


def _parties(raw) -> list[tuple[int, tuple[str, ...]]] | None:
	"""The sample parties ``[{adults, children: [band code]}]`` of ``price_matrix``, checked;
	None when none were asked for."""
	if raw is None or raw == "":
		return None
	items = parse(raw, None)
	if not isinstance(items, list) or len(items) > MATRIX_PARTIES_MAX:
		frappe.throw(_("Sample parties are a list of at most {0} parties.").format(MATRIX_PARTIES_MAX))
	out = []
	for i, p in enumerate(items, 1):
		adults = p.get("adults") if isinstance(p, dict) else None
		kids = p.get("children", []) if isinstance(p, dict) else None
		kids = [] if kids is None else kids
		if (not isinstance(adults, int) or isinstance(adults, bool) or not 1 <= adults <= PARTY_ADULTS_MAX
		        or not isinstance(kids, list) or len(kids) > PARTY_CHILDREN_MAX
		        or not all(isinstance(k, str) and k.strip() for k in kids)):
			frappe.throw(_("Sample party {0}: 1 to {1} adults and at most {2} children, each named by an age "
			               "band code.").format(i, PARTY_ADULTS_MAX, PARTY_CHILDREN_MAX))
		out.append((adults, tuple(k.strip().upper()[:40] for k in kids)))
	return out


def _rule_dict(r, formula: bool = True) -> dict:
	"""An occupancy rule of the built terms, as the workspace shows an inherited one. Without
	``formula`` (a viewer who does not see cost, S16 review) it says which rule applies where, not
	its op or value (``hidden``)."""
	out = {"rule_id": r.rule_id, "target": r.target.value, "position": r.position, "age_band": r.age_band,
	       "adults": r.adults, "children": r.children, "room_type": r.room_type, "period": r.period,
	       "op": r.op.value, "value": matrix.rule_value(r.value), "is_override": r.is_override, "source": r.source,
	       "hidden": False}
	if not formula:
		out.update(op=None, value=None, hidden=True)
	return out


def _occupancy_defaults() -> dict:
	"""What the engine assumes where no rule prices a slot (D12): every adult pays the full unit
	(``occupancy.GLOBAL_ADULT_DEFAULT``); a child has no default (ADR-007: NO_CHILD_RULE)."""
	a = occupancy.GLOBAL_ADULT_DEFAULT
	return {"adult": {"rule_id": a.rule_id, "target": a.target.value, "op": a.op.value,
	                  "value": matrix.rule_value(a.value), "source": a.source, "note": a.note},
	        "child": None}


def _party_cells(terms, room_type: str, parties, hidden_rules: frozenset[str] = frozenset()) -> list[dict]:
	"""Each sample party's total per period. A party whose answer can depend on the op or value of
	one of ``hidden_rules`` (inherited policy rules a viewer without cost may not read, S16 review;
	``matrix.party_hidden``) is left out: its period is listed in ``hidden`` without a total, slots or
	error, so no formula can be worked back (a total next to its slots, or a negative total that a
	probe rule of the draft provokes), and which periods are hidden is the same whatever the hidden
	rules' ops, INHERIT or not (S16 re-review 4). A failure no hidden rule decides (a child band
	without a rule, a tie of the draft's own rules) is said (S16 re-review)."""
	out = []
	for adults, kids in parties:
		cell = {"cells": {}, "slots": {}, "errors": {}, "hidden": []}
		for p in terms.periods:
			if hidden_rules and matrix.party_hidden(terms, room_type, p, adults, kids, hidden_rules):
				cell["cells"][p.code] = None
				cell["hidden"].append(p.code)
				continue
			try:
				total, slots = matrix.party_total(terms, room_type, p, adults, kids)
			except (Unsellable, PricingError) as e:
				cell["cells"][p.code] = None
				cell["errors"][p.code] = getattr(e, "message", None) or str(e)
				continue
			cell["cells"][p.code] = money.to_str(total)
			cell["slots"][p.code] = slots
		out.append(cell)
	return out


@frappe.whitelist()
def price_matrix(version: str, adults: int = 2, data=None, parties=None, party_room: str | None = None,
                 workspace=None):
	"""Nightly unit (base person / room price) per room × period for the editor grid. ``adults`` is
	accepted for older callers and unused: the unit does not depend on the party. Without the
	workspace's arguments the answer is main's (ADR-061, "Existing semantics kept").

	For the Pricing Workspace (``workspace``, ``data`` or ``parties``, opt-in): with ``data`` of the
	draft with those unsaved changes (GAP-1; a draft that cannot be built answers ``build_error``),
	and besides the cells (GAP-2/2b/3): each cell's source (``rooms[].sources``, the rule that
	priced it), each room's effective capacity, the age bands with their origin, the occupancy
	rules inherited from pricing policies and the engine's defaults (``occupancy_defaults``); with
	``parties`` (``[{adults, children: [band code]}]``) and ``party_room``, the occupancy total of
	each sample party per period (``party_cells``).

	The inherited rules are a pricing policy's formulas, which are cost (G-11, the policies API's
	READ_CAP): an editor without ``price.view_cost`` is told which inherited rule applies where
	without its op or value, and a party total priced with one is left out (``hidden``, S16
	review). With ``data`` or ``parties`` the call is bounded per user (``_heavy``)."""
	v = frappe.get_doc("TEX Contract Version", version)
	prop = scope.property_of("TEX Contract Version", version)
	scope.require("price.view", prop)
	if not _sees_cost(prop):
		frappe.throw(_("Not permitted: {0}.").format("price.view_cost"), frappe.PermissionError)
	if not _workspace(workspace, data, parties):
		return _mains_matrix(v, version)
	if _has_data(data) or _has_data(parties):
		with _heavy("matrix"):
			return _price_matrix(v, version, prop, data, parties, party_room)
	return _price_matrix(v, version, prop, data, parties, party_room)


def _mains_matrix(v, version: str) -> dict:
	"""``price_matrix`` for an existing caller: main's body, unchanged (ADR-061)."""
	from kamra.tex.pricing import rooms as room_math

	terms = svc.load_terms(version) if v.status != "Draft" else svc.build_terms(v)
	out = []
	for rt in sorted(terms.rooms):
		row = {"room_type": rt, "name": terms.rooms[rt].name, "cells": {}}
		for p in terms.periods:
			try:
				row["cells"][p.code] = str(room_math.room_unit(terms, rt, p))
			except Unsellable as u:
				row["cells"][p.code] = None
				row.setdefault("errors", {})[p.code] = u.message
		out.append(row)
	return {"periods": [{"code": p.code, "name": p.name, "start": str(p.start), "end": str(p.end)}
	                    for p in terms.periods], "rooms": out, "basis": terms.basis.value, "currency": terms.currency}


def _price_matrix(v, version: str, prop: str, data, parties, party_room: str | None) -> dict:
	wanted = _parties(parties)
	at = now_datetime()
	if _has_data(data):
		doc = _overlay(version, data)
		try:
			terms = svc.build_terms(doc, at=at)
		except frappe.ValidationError as e:
			return {"build_error": str(e), "rooms": [], "periods": []}
	else:
		doc = v
		if v.status != "Draft":
			terms = svc.load_terms(version)
			at = get_datetime(v.effective_from) if v.effective_from else at    # what the payload froze
		else:
			terms = svc.build_terms(v, at=at)
	if wanted is not None and party_room not in terms.rooms:
		frappe.throw(_("The sample parties' room {0} is not a room of this contract.").format(party_room or "—"))
	from kamra.tex.pricing import rooms as room_math

	out = []
	for rt in sorted(terms.rooms):
		spec = terms.rooms[rt]
		row = {"room_type": rt, "name": spec.name, "cells": {}}
		sources = {}
		for p in terms.periods:
			try:
				row["cells"][p.code] = str(room_math.room_unit(terms, rt, p))
			except Unsellable as u:
				row["cells"][p.code] = None
				row.setdefault("errors", {})[p.code] = u.message
				continue
			sources[p.code] = matrix.unit_source(terms, rt, p)
		row["sources"] = sources
		row["capacity"] = {"max_adults": spec.max_adults, "max_children": spec.max_children,
		                   "max_occupants": spec.max_occupants, "min_adults": spec.min_adults,
		                   "included_adults": spec.included_adults}
		out.append(row)
	band_source = svc.band_source(doc, terms, at) if terms.age_bands else "version"
	inherited = [r for r in terms.occupancy_rules if r.source != "version"]
	formula = scope.has_capability("price.view_cost", prop)
	result = {"periods": [{"code": p.code, "name": p.name, "start": str(p.start), "end": str(p.end)}
	                      for p in terms.periods], "rooms": out, "basis": terms.basis.value, "currency": terms.currency,
	          "age_bands": [{"code": b.code, "label": b.label, "from_months": b.from_months, "to_months": b.to_months,
	                         "is_infant": b.is_infant, "source": band_source} for b in terms.age_bands],
	          "inherited_rules": [_rule_dict(r, formula) for r in inherited],
	          "occupancy_defaults": _occupancy_defaults()}
	if wanted is not None:
		hidden = frozenset() if formula else frozenset(r.rule_id for r in inherited)
		result["party_cells"] = _party_cells(terms, party_room, wanted, hidden)
	return result


@frappe.whitelist(methods=["POST"])
def legacy_draft(property: str, market: str = "GLOBAL", contract_code: str = "LEGACY-BAR"):
	"""MIGRATION T8 (opt-in): draft a contract from the hotel's legacy Kamra prices."""
	from kamra.tex.commercial import legacy

	return legacy.draft_from_legacy(property, market=market, contract_code=(contract_code or "LEGACY-BAR")[:40])

