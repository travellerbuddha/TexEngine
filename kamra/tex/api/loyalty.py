"""Loyalty program administration (R-39, G-24).

Reading needs ``crm.view`` at a hotel the program reaches; changing a program needs
``loyalty.edit`` at every (enabled) hotel it reaches — a group program is a group
decision. Every change is audited with its old and new values. Earnings already made are
never rewritten by a rule change (kamra.tex.crm.loyalty.stay_fingerprint)."""

from __future__ import annotations

import frappe
from frappe import _

from kamra.tex.api._util import as_int, parse, text
from kamra.tex.commercial.decimals import api_value
from kamra.tex.crm import loyalty
from kamra.tex.money import db_dec, quantize, to_str
from kamra.tex.security import scope
from kamra.tex.security.audit import audit

FIELDS = ("program_name", "property", "hotel_group", "enabled", "currency", "point_value", "min_redeem_points",
          "max_redeem_percent", "pending_days", "expiry_months")
CHILDREN = {
	"earn_rules": ("basis", "rate", "room_type", "extra", "date_from", "date_to"),
	"tiers": ("tier_name", "min_points", "earn_multiplier"),
	"blackouts": ("date_from", "date_to", "note", "applies_to"),
}


def _props(cap: str) -> set[str]:
	return {p for p in scope.permitted_properties() if scope.has_capability(cap, p)}


def _require(prog, cap: str, *, every: bool):
	hotels = loyalty.program_properties(prog)
	if scope.is_platform_admin():
		return hotels
	allowed = _props(cap)
	ok = hotels and (set(hotels) <= allowed if every else bool(set(hotels) & allowed))
	if not ok:
		if cap == "crm.view" or not set(hotels) & _props("crm.view"):
			frappe.throw(_("Program not found."), frappe.DoesNotExistError)     # another tenant's: not even its name
		frappe.throw(_("Not permitted: {0}.").format(cap), frappe.PermissionError)
	return hotels


def _stats(name: str, point_value, currency) -> dict:
	row = frappe.db.sql(
		"""SELECT COUNT(DISTINCT guest) members,
		          COALESCE(SUM(CASE WHEN status IN ('Available','Used','Expired') THEN points END), 0) available,
		          COALESCE(SUM(CASE WHEN status = 'Pending' THEN points END), 0) pending
		   FROM `tabTEX Loyalty Ledger` WHERE program = %s""", name, as_dict=True)[0]
	available = int(row.available or 0)
	return {"members": int(row.members or 0), "available_points": available, "pending_points": int(row.pending or 0),
	        # what the points in guests' hands are worth: the program's liability
	        "liability": to_str(quantize(db_dec(point_value) * available, currency or "EUR"))}


@frappe.whitelist()
def programs():
	props = _props("crm.view")
	scope.require("crm.view", None)
	names = loyalty.visible_programs(props) if not scope.is_platform_admin() else set(
		frappe.get_all("TEX Loyalty Program", pluck="name"))
	rows = frappe.get_all("TEX Loyalty Program", filters={"name": ("in", list(names) or [""])},
	                      fields=["name", *FIELDS, "modified"], order_by="program_name asc")
	edit = _props("loyalty.edit")
	for r in rows:
		r.update(_stats(r.name, r.point_value, r.currency))
		r["point_value"] = api_value(r.point_value or 0)
		r["max_redeem_percent"] = api_value(r.max_redeem_percent or 0)
		hotels = loyalty.program_properties(r)
		r["hotels"] = hotels
		r["can_edit"] = scope.is_platform_admin() or (bool(hotels) and set(hotels) <= edit)
		r["modified"] = str(r["modified"])
	return {"programs": rows, "scopes": _scopes(edit)}


def _scopes(edit: set[str]) -> dict:
	"""Where the user may create a program: hotels, and groups whose every hotel they edit."""
	groups = {}
	for p in frappe.get_all("Property", filters={"name": ("in", list(edit) or [""])},
	                        fields=["name", "property_name", "tex_hotel_group"]):
		if p.tex_hotel_group:
			groups.setdefault(p.tex_hotel_group, []).append(p.name)
	whole = [g for g, members in groups.items()
	         if set(frappe.get_all("Property", filters={"tex_hotel_group": g, "disabled": 0}, pluck="name")) <= edit]
	return {"hotels": sorted(edit), "groups": sorted(whole)}


@frappe.whitelist()
def program(name: str):
	prog = frappe.get_doc("TEX Loyalty Program", name)
	hotels = _require(prog, "crm.view", every=False)
	out = {f: prog.get(f) for f in ("name", *FIELDS)}
	out["point_value"] = api_value(prog.point_value or 0)
	out["max_redeem_percent"] = api_value(prog.max_redeem_percent or 0)
	for table, cols in CHILDREN.items():
		out[table] = [{c: (str(r.get(c)) if c.startswith("date") and r.get(c) else r.get(c)) for c in cols}
		              for r in prog.get(table) or []]
	for r in out["earn_rules"]:
		r["rate"] = api_value(r["rate"] or 0)
	for t in out["tiers"]:
		t["earn_multiplier"] = api_value(t["earn_multiplier"] if t["earn_multiplier"] is not None else 1)
	out.update(_stats(prog.name, prog.point_value, prog.currency))
	out["hotels"] = hotels
	out["can_edit"] = scope.is_platform_admin() or set(hotels) <= _props("loyalty.edit")
	out["lookups"] = _lookups(hotels)
	return out


def _lookups(hotels: list[str]) -> dict:
	"""Room types, live extras and currencies of a program's hotels (for its rules)."""
	return {
		"room_types": frappe.get_all("Room Type", filters={"property": ("in", hotels or [""])},
		                             fields=["name", "room_type_name", "property"], order_by="room_type_name asc"),
		"extras": frappe.get_all("TEX Extra", filters={"property": ("in", hotels or [""]), "tex_status": "Active"},
		                         fields=["name", "extra_name", "extra_code", "property"], order_by="extra_name asc"),
		"currencies": sorted({c for c in frappe.get_all("Property", filters={"name": ("in", hotels or [""])},
		                                                pluck="currency") if c} | {"EUR"}),
	}


@frappe.whitelist()
def lookups(property: str | None = None, hotel_group: str | None = None):
	"""Lookups for a program being created (the scope must be one the user may edit)."""
	prog = frappe._dict(property=property, hotel_group=None if property else hotel_group)
	return _lookups(_require(prog, "loyalty.edit", every=True))


@frappe.whitelist(methods=["POST"])
def save_program(data):
	data = parse(data, {}) or {}
	if data.get("name"):
		doc = frappe.get_doc("TEX Loyalty Program", data["name"])
		_require(doc, "loyalty.edit", every=True)
		old = _snapshot(doc)
	else:
		doc = frappe.new_doc("TEX Loyalty Program")
		old = None
	for f in FIELDS:
		if f in data:
			doc.set(f, text(data[f], 140) if f == "program_name" else data[f])
	if doc.property:
		doc.hotel_group = None
	for table, cols in CHILDREN.items():
		if table in data:
			doc.set(table, [])
			for row in data[table] or []:
				doc.append(table, {c: row.get(c) for c in cols if row.get(c) not in ("", None)})
	_require(doc, "loyalty.edit", every=True)            # the (new) scope too
	doc.save(ignore_permissions=True)
	audit("loyalty.program_save", reference_doctype="TEX Loyalty Program", reference_name=doc.name,
	      property=doc.property, old=old, new=_snapshot(doc))
	return {"name": doc.name}


def _snapshot(doc) -> dict:
	out = {f: str(doc.get(f)) if doc.get(f) is not None else None for f in FIELDS}
	for table, cols in CHILDREN.items():
		out[table] = [{c: str(r.get(c)) if r.get(c) is not None else None for c in cols} for r in doc.get(table) or []]
	return out


@frappe.whitelist(methods=["POST"])
def set_enabled(name: str, enabled):
	doc = frappe.get_doc("TEX Loyalty Program", name)
	_require(doc, "loyalty.edit", every=True)
	doc.enabled = 1 if as_int(enabled, 0) else 0
	doc.save(ignore_permissions=True)
	audit("loyalty.program_enable" if doc.enabled else "loyalty.program_disable",
	      reference_doctype="TEX Loyalty Program", reference_name=name, property=doc.property)
	return {"name": name, "enabled": bool(doc.enabled)}


@frappe.whitelist(methods=["POST"])
def delete_program(name: str):
	doc = frappe.get_doc("TEX Loyalty Program", name)
	_require(doc, "loyalty.edit", every=True)
	old = _snapshot(doc)
	frappe.delete_doc("TEX Loyalty Program", name, ignore_permissions=True)
	audit("loyalty.program_delete", reference_doctype="TEX Loyalty Program", reference_name=name,
	      property=doc.property, old=old)
	return {"ok": True}


# what an entry tied to another hotel's booking or stay never shows (ADR-056 review): which booking,
# the stay's dates (reason), how its points were earned (explanation: rate × value) and who made it
OTHER_HOTEL_FIELDS = ("booking", "reservation", "reason", "actor", "explanation")


def _visible_guests(guests: set[str], props: set[str]) -> set[str]:
	"""Of ``guests``, those the viewer may see through ``props`` (``crm.require_guest``'s rule)."""
	if not guests or not props:
		return set()
	from kamra.tex.crm import service as crm

	cond, params = crm._visible_guest_sql(props)
	return set(frappe.db.sql(f"SELECT g.name FROM `tabGuest` g WHERE g.name IN %(names)s AND {cond}",  # nosemgrep
	                         {**params, "names": tuple(guests)}, pluck=True))


@frappe.whitelist()
def ledger(name: str, guest: str | None = None, entry_type: str | None = None, start=0, limit=50):
	"""A program's ledger, newest first. The program reaches the viewer's hotels, the rows do not
	all belong to them (a group program): an entry tied to a booking or stay at a hotel outside the
	viewer's ``crm.view`` scope shows its points, status and dates only (``other_hotel``), and a
	guest the viewer may not see is not named (ADR-056 review)."""
	prog = frappe.get_doc("TEX Loyalty Program", name)
	_require(prog, "crm.view", every=False)
	platform = scope.is_platform_admin()
	props = _props("crm.view")
	filters = {"program": name}
	if guest:
		if not platform:
			from kamra.tex.crm import service as crm

			crm.require_guest(guest)                       # never learn about a guest one may not see
		filters["guest"] = guest
	if entry_type in ("Earn", "Burn", "Adjust", "Expire", "Reverse"):
		filters["entry_type"] = entry_type
	rows = frappe.get_all("TEX Loyalty Ledger", filters=filters,
	                      fields=["name", "guest", "entry_type", "points", "status", "available_on", "expires_on",
	                              "booking", "reservation", "reason", "actor", "creation", "explanation"],
	                      order_by="creation desc", start=as_int(start, 0, lo=0), page_length=as_int(limit, 50, lo=1,
	                                                                                                  hi=200))
	where = loyalty._entry_hotels(rows)
	seen = {r.guest for r in rows if r.guest} if platform else _visible_guests({r.guest for r in rows if r.guest},
	                                                                            props)
	names = dict(frappe.get_all("Guest", filters={"name": ("in", list(seen))}, fields=["name", "full_name"],
	                            as_list=True)) if seen else {}
	for r in rows:
		r["other_hotel"] = bool(not platform and where[r.name] and where[r.name] not in props)
		if r["other_hotel"]:
			for k in OTHER_HOTEL_FIELDS:
				r[k] = None
		if r.guest not in seen:
			r["guest"] = None
		r["guest_name"] = names.get(r.guest) if r.guest else None
		for k in ("available_on", "expires_on", "creation"):
			r[k] = str(r[k]) if r[k] else None
	return {"rows": rows, "total": frappe.db.count("TEX Loyalty Ledger", filters)}
