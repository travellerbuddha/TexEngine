"""Cross-record lists behind the admin navigation's sub-sections (R-35, G-64, ADR-060).

Each list covers the hotel named by ``property`` (checked), or, without one, every hotel of
the caller where the list's capability is held. Rows of any other hotel never leave. The
capability is the one the records' own screen already requires:

* contract versions, and the rate plans of versions: ``price.view`` (``contracts.get_contract``,
  ``get_version``); a rate plan's adjustment only where the caller sees cost (G-11);
* price periods and occupancy rules of versions: ``price.view`` and cost (``price.view_cost``
  or ``contract.edit``), as ``contracts.get_version`` shows them only then;
* restrictions: ``price.view`` (the ARI grid, ``crs.ari_grid``);
* guest communications: ``crm.view`` (the guest profile);
* the booking engine's rooms: ``booking_site.edit`` at the hotel (``content.items``).

Read-only: every change still goes through the screen that owns the record.
"""

from __future__ import annotations

import frappe
from frappe import _
from frappe.utils import add_days, get_datetime, get_fullname, getdate, now_datetime, nowdate

from kamra.tex.api._util import as_int, text
from kamra.tex.commercial.decimals import api_fields, api_value
from kamra.tex.security import scope
from kamra.tex.security.scope import require_capability

COST = ("price.view_cost", "contract.edit")
VERSION_STATUSES = ("Draft", "Published", "Superseded", "Withdrawn")
# "current": what sells or is scheduled to, and what is being drafted
CURRENT = ("Draft", "Published")


def _hotels(cap: str, property: str | None, *, cost: bool = False) -> list[str]:
	"""The hotels a list covers: ``property`` when given (``cap`` there, else PermissionError), or
	every hotel in scope where the caller holds ``cap`` (and sees cost when ``cost``)."""

	def ok(p: str) -> bool:
		return scope.has_capability(cap, p) and (not cost or any(scope.has_capability(c, p) for c in COST))

	if property:
		scope.require(cap, property)
		if not ok(property):
			frappe.throw(_("Not permitted: {0}.").format(" / ".join(COST)), frappe.PermissionError)
		return [property]
	hotels = sorted(p for p in scope.permitted_properties() if ok(p))
	if not hotels:
		frappe.throw(_("Not permitted: {0}.").format(cap), frappe.PermissionError)
	return hotels


def _names(doctype: str, names, field: str) -> dict[str, str]:
	names = sorted({n for n in names if n})
	if not names:
		return {}
	return dict(frappe.get_all(doctype, filters={"name": ("in", names)}, fields=["name", field], as_list=True))


def _day(value) -> str | None:
	return str(value) if value else None


# ─── contract versions ───────────────────────────────────────────────────


def _contracts(hotels: list[str]) -> dict:
	return {c.name: c for c in frappe.get_all(
		"TEX Contract", filters={"property": ("in", hotels)},
		fields=["name", "property", "contract_code", "contract_name", "market", "status", "active_version"])}


def _state(v, contract, now) -> str:
	"""live (the contract's active version), scheduled (published, effective later), or the status."""
	if v.status == "Published":
		if contract.active_version == v.name:
			return "live"
		if v.effective_from and get_datetime(v.effective_from) > now:
			return "scheduled"
		return "published"
	return (v.status or "").lower()


def _status_filter(status: str | None, *, default: str | None) -> tuple | str | None:
	status = status or default
	if not status or status == "all":
		return None
	if status == "current":
		return ("in", CURRENT)
	if status not in VERSION_STATUSES:
		frappe.throw(_("Unknown version status."), frappe.ValidationError)
	return status


@frappe.whitelist()
@require_capability("price.view")
def versions(property: str | None = None, status: str | None = None, limit=500):
	"""Every contract version of the hotels (no payload, no amount)."""
	hotels = _hotels("price.view", property)
	contracts = _contracts(hotels)
	filters: dict = {"contract": ("in", list(contracts) or ["__none__"])}
	wanted = _status_filter(status, default=None)
	if wanted:
		filters["status"] = wanted
	limit = as_int(limit, 500, lo=1, hi=1000)
	rows = frappe.get_all("TEX Contract Version", filters=filters,
	                      fields=["name", "contract", "version_no", "status", "effective_from", "active_to",
	                              "published_at", "published_by", "change_note", "based_on", "modified"],
	                      order_by="modified desc", limit=limit + 1)
	now = now_datetime()
	out = []
	for v in rows[:limit]:
		c = contracts[v.contract]
		out.append({
			"name": v.name, "contract": c.name, "contract_code": c.contract_code, "contract_name": c.contract_name,
			"market": c.market, "property": c.property, "contract_status": c.status, "version_no": v.version_no,
			"status": v.status, "state": _state(v, c, now), "effective_from": _day(v.effective_from),
			"active_to": _day(v.active_to), "published_at": _day(v.published_at),
			"published_by": get_fullname(v.published_by) if v.published_by else None,
			"change_note": v.change_note, "based_on": v.based_on, "modified": _day(v.modified)})
	return {"rows": out, "truncated": len(rows) > limit}


SECTIONS = {
	# section: (child DocType, parent field, fields, order inside a version)
	"periods": ("TEX Price Period", "periods",
	            ["period_code", "period_name", "start_date", "end_date", "weekdays", "adjustment_op",
	             "adjustment_value", "priority"]),
	"occupancy": ("TEX Occupancy Rule", "occupancy_rules",
	              ["target", "position", "age_band", "combination", "room_type", "period_code", "op", "value",
	               "is_override", "note"]),
	"rate_plans": ("TEX Contract Rate Plan", "rate_plans",
	               ["rate_plan", "op", "value", "refundable", "boards", "cancellation_policy", "payment_policy"]),
}
COST_SECTIONS = ("periods", "occupancy")
MAX_ROWS = 5000


@frappe.whitelist()
@require_capability("price.view")
def version_rows(section: str, property: str | None = None, status: str | None = None):
	"""One table of every version (``status``: "current" = drafts and published, "all", or a
	version status) of the hotels' contracts, each row with its contract and version."""
	if section not in SECTIONS:
		frappe.throw(_("Unknown section."), frappe.ValidationError)
	hotels = _hotels("price.view", property, cost=section in COST_SECTIONS)
	contracts = _contracts(hotels)
	filters: dict = {"contract": ("in", list(contracts) or ["__none__"])}
	wanted = _status_filter(status, default="current")
	if wanted:
		filters["status"] = wanted
	versions_ = {v.name: v for v in frappe.get_all(
		"TEX Contract Version", filters=filters, fields=["name", "contract", "version_no", "status", "effective_from"],
		limit=2000)}
	doctype, parentfield, fields = SECTIONS[section]
	rows = frappe.get_all(doctype, filters={"parenttype": "TEX Contract Version", "parentfield": parentfield,
	                                        "parent": ("in", list(versions_) or ["__none__"])},
	                      fields=["parent", "idx", *fields], order_by="parent asc, idx asc", limit=MAX_ROWS + 1)
	meta = frappe.get_meta(doctype)
	sees_cost = {p: any(scope.has_capability(c, p) for c in COST) for p in hotels}
	rooms = _names("Room Type", (r.get("room_type") for r in rows), "room_type_name")
	plans = {p.name: p for p in frappe.get_all(
		"Rate Plan", filters={"name": ("in", sorted({r.get("rate_plan") for r in rows if r.get("rate_plan")})
		                               or ["__none__"])}, fields=["name", "rate_plan_name", "code"])}
	cxl = _names("TEX Cancellation Policy", (r.get("cancellation_policy") for r in rows), "policy_name")
	pay = _names("TEX Payment Policy", (r.get("payment_policy") for r in rows), "policy_name")
	now = now_datetime()
	out = []
	for r in rows[:MAX_ROWS]:
		v = versions_[r.parent]
		c = contracts[v.contract]
		row = api_fields(dict(r), meta)
		row.pop("parent", None)
		for k in ("start_date", "end_date"):
			if k in row:
				row[k] = _day(row[k])
		if section == "rate_plans":
			if not sees_cost[c.property]:
				row.pop("op", None)
				row.pop("value", None)
			plan = plans.get(r.rate_plan)
			row.update(rate_plan_name=plan.rate_plan_name if plan else r.rate_plan,
			           rate_plan_code=plan.code if plan else None,
			           cancellation_policy_name=cxl.get(r.cancellation_policy),
			           payment_policy_name=pay.get(r.payment_policy))
		if section == "occupancy":
			row["room_type_name"] = rooms.get(r.room_type)
		out.append({"version": v.name, "version_no": v.version_no, "version_status": v.status,
		            "state": _state(v, c, now), "contract": c.name, "contract_code": c.contract_code,
		            "contract_name": c.contract_name, "market": c.market, "property": c.property, **row})
	return {"rows": out, "truncated": len(rows) > MAX_ROWS}


# ─── restrictions ────────────────────────────────────────────────────────

RESTRICTION_SCOPE = ("room_type", "contract", "market", "rate_plan", "sales_channel")
RESTRICTION_VALUES = ("stop_sell", "stop_sell_mode", "min_los", "max_los", "cta", "ctd", "release_days",
                      "min_advance", "max_advance")
# listed when the schema has them (channel scope and booking window, G-48)
RESTRICTION_OPTIONAL = ("channel_scope", "book_from", "book_to")
MAX_DAYS = 366
MAX_RECORDS = 5000


def _blank(value):
	"""A restriction value as listed: blank and 0 are "not set" (None); a date as text."""
	if value in (None, "", 0):
		return None
	return str(value) if hasattr(value, "isoformat") else value


def group_ranges(records: list[dict], keys: tuple[str, ...]) -> list[dict]:
	"""Consecutive days of one scope with the same values → one range (``date_from``..``date_to``)."""
	out: list[dict] = []
	last: dict[tuple, dict] = {}
	for r in sorted(records, key=lambda r: getdate(r["restriction_date"])):
		key = tuple(_blank(r.get(k)) for k in keys)
		day = getdate(r["restriction_date"])
		prev = last.get(key)
		if prev and getdate(prev["date_to"]) == add_days(day, -1):
			prev["date_to"] = str(day)
			prev["days"] += 1
			continue
		row = {k: v for k, v in zip(keys, key, strict=True)}
		row.update(date_from=str(day), date_to=str(day), days=1)
		out.append(row)
		last[key] = row
	return out


@frappe.whitelist()
@require_capability("price.view")
def restrictions(property: str | None = None, date_from: str | None = None, date_to: str | None = None,
                 room_type: str | None = None):
	"""Restrictions of the hotels in a period (default: 90 days from today), as ranges of days."""
	hotels = _hotels("price.view", property)
	a = getdate(date_from or nowdate())
	b = getdate(date_to) if date_to else getdate(add_days(a, 89))
	if b < a or (b - a).days >= MAX_DAYS:
		frappe.throw(_("Choose a period of at most a year."), frappe.ValidationError)
	meta = frappe.get_meta("TEX ARI Restriction")
	optional = tuple(f for f in RESTRICTION_OPTIONAL if meta.has_field(f))
	filters: dict = {"property": ("in", hotels), "restriction_date": ("between", [a, b])}
	if room_type:
		filters["room_type"] = text(room_type, 140)
	keys = ("property", *RESTRICTION_SCOPE, *RESTRICTION_VALUES, *optional, "note")
	recs = frappe.get_all("TEX ARI Restriction", filters=filters, fields=["restriction_date", *keys],
	                      order_by="restriction_date asc, name asc", limit=MAX_RECORDS + 1)
	ranges = group_ranges(recs[:MAX_RECORDS], keys)
	rooms = _names("Room Type", (r["room_type"] for r in ranges), "room_type_name")
	codes = _names("TEX Contract", (r["contract"] for r in ranges), "contract_code")
	plans = _names("Rate Plan", (r["rate_plan"] for r in ranges), "rate_plan_name")
	for r in ranges:
		r.update(room_type_name=rooms.get(r["room_type"]), contract_code=codes.get(r["contract"]),
		         rate_plan_name=plans.get(r["rate_plan"]))
	ranges.sort(key=lambda r: (r["date_from"], r["property"], r["room_type_name"] or "", r["date_to"]))
	return {"from": str(a), "to": str(b), "rows": ranges, "optional_fields": list(optional),
	        "truncated": len(recs) > MAX_RECORDS}


# ─── guest communications ────────────────────────────────────────────────

COMM_FILTERS = {"channel": ("Email", "SMS", "WhatsApp", "Phone", "Note"),
                "status": ("Queued", "Sent", "Delivered", "Failed", "Logged"),
                "direction": ("Outbound", "Inbound", "Internal")}


@frappe.whitelist()
@require_capability("crm.view")
def communications(property: str | None = None, channel: str | None = None, status: str | None = None,
                   direction: str | None = None, q: str | None = None, start=0, limit=50):
	"""Guest communications logged or sent at the hotels, newest first; the message body stays
	on the guest's profile."""
	from kamra.tex.crm.service import _like

	hotels = _hotels("crm.view", property)
	where = ["c.property IN %(hotels)s"]
	params: dict = {"hotels": tuple(hotels)}
	for field, value in (("channel", channel), ("status", status), ("direction", direction)):
		if value:
			if value not in COMM_FILTERS[field]:
				frappe.throw(_("Unknown {0}.").format(field), frappe.ValidationError)
			where.append(f"c.`{field}` = %({field})s")
			params[field] = value
	q = text(q, 80)
	if q:
		where.append("(c.subject LIKE %(q)s OR g.full_name LIKE %(q)s OR g.email LIKE %(q)s "
		             "OR c.booking LIKE %(q)s OR c.reservation LIKE %(q)s)")
		params["q"] = _like(q)
	cond = " AND ".join(where)
	join = "FROM `tabTEX Communication` c LEFT JOIN `tabGuest` g ON g.name = c.guest"
	total = frappe.db.sql(f"SELECT COUNT(*) {join} WHERE {cond}", params)[0][0]  # nosemgrep -- static SQL, values bound
	rows = frappe.db.sql(  # nosemgrep -- static columns and conditions, values bound
		f"""SELECT c.name, c.guest, g.full_name AS guest_name, c.property, c.channel, c.direction, c.status,
		c.consent_basis, c.subject, c.template, c.sent_at, c.creation, c.actor, c.booking, c.reservation,
		c.delivery_error {join} WHERE {cond} ORDER BY c.creation DESC, c.name DESC
		LIMIT %(_limit)s OFFSET %(_start)s""",
		{**params, "_limit": as_int(limit, 50, lo=1, hi=200), "_start": as_int(start, 0, lo=0)}, as_dict=True)
	for r in rows:
		r["sent_at"], r["creation"] = _day(r["sent_at"]), _day(r["creation"])
		# a message sent while a guest booked online has the visitor ("Guest") as its actor
		r["actor_name"] = get_fullname(r["actor"]) if r["actor"] and r["actor"] != "Guest" else None
	return {"rows": rows, "total": total}


# ─── the booking engine's rooms ──────────────────────────────────────────


@frappe.whitelist()
@require_capability("booking_site.edit")
def rooms(property: str | None = None):
	"""The hotel's room types as the booking engine shows them: texts, picture, size, beds,
	occupancy, which translations exist and which live contracts sell each room."""
	from kamra.tex.services import content

	if not property:
		frappe.throw(_("A hotel must be specified."), frappe.ValidationError)
	rts = frappe.get_all("Room Type", filters={"property": property, "disabled": 0},
	                     fields=["name", "room_type_code", "room_type_name", "description", "image", "bed_type",
	                             "tex_beds", "tex_size_sqm", "room_view", "amenities", "adults_capacity",
	                             "children_capacity", "max_total_occupants"], order_by="room_type_name asc")
	names = [r.name for r in rts] or ["__none__"]
	gallery: dict[str, int] = {}
	for m in frappe.get_all("Room Type Media", filters={"parenttype": "Room Type", "parent": ("in", names)},
	                        pluck="parent"):
		gallery[m] = gallery.get(m, 0) + 1
	translated: dict[str, dict[str, list[str]]] = {}
	for t in frappe.get_all("TEX Content Translation",
	                        filters={"property": property, "ref_doctype": "Room Type", "ref_name": ("in", names)},
	                        fields=["ref_name", "field", "language"]):
		translated.setdefault(t.ref_name, {}).setdefault(t.language, []).append(t.field)
	live = {c.active_version: c.contract_code for c in frappe.get_all(
		"TEX Contract", filters={"property": property, "status": "Active", "active_version": ("is", "set")},
		fields=["active_version", "contract_code"])}
	sold_by: dict[str, set[str]] = {}
	for r in frappe.get_all("TEX Contract Room", filters={"parenttype": "TEX Contract Version",
	                                                      "parent": ("in", list(live) or ["__none__"])},
	                        fields=["parent", "room_type"]):
		sold_by.setdefault(r.room_type, set()).add(live[r.parent])
	fields = list(content.FIELDS["Room Type"])
	out = []
	for r in rts:
		langs = translated.get(r.name, {})
		out.append({
			"name": r.name, "code": r.room_type_code, "room_type_name": r.room_type_name,
			"description": r.description, "image": r.image, "gallery": gallery.get(r.name, 0),
			"bed_type": r.bed_type, "beds": r.tex_beds,
			"size_sqm": api_value(r.tex_size_sqm) if r.tex_size_sqm else None,
			"view": r.room_view,
			"amenities": [a.strip() for a in (r.amenities or "").replace("\n", ",").split(",") if a.strip()],
			"adults": r.adults_capacity, "children": r.children_capacity, "max_occupants": r.max_total_occupants,
			"translations": {lang: sorted(langs.get(lang, [])) for lang in content.LANGS},
			"contracts": sorted(sold_by.get(r.name, set()))})
	return {"property": property, "languages": list(content.LANGS), "fields": fields, "rooms": out}
