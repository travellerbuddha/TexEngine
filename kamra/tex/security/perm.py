"""Frappe permission hooks backed by TEX tenancy (ADR-011, ADR-019, ADR-022).

TEX records are written only through the TEX services/API (capability-checked);
business roles hold at most read access on TEX DocTypes (ADR-022). These hooks make
every Desk / REST read (``/api/resource``, ``frappe.client``, reports, ``get_list``)
follow the same hotel scope as the TEX API — including records whose hotel is only
known through a parent (revisions, contract versions, loyalty ledger) and guests.
"""

from __future__ import annotations

import frappe

from kamra.tex.security import scope

# rows carry the hotel in ``property``; blank = platform-wide record (global policy)
PROPERTY_DOCTYPES = (
	"Reservation", "Folio", "Room", "Room Type", "Rate Plan", "Group Booking", "TEX Booking", "TEX Contract",
	"TEX Payment Transaction", "TEX Payment Link", "TEX Payment Allocation", "TEX Quote", "TEX Allotment",
	"TEX ARI Restriction", "TEX Extra", "TEX Abandoned Booking", "TEX Integration Connection",
	"TEX Integration Outbox", "TEX Payment Provider Account", "TEX Payment Method Rule",
	"TEX Promotion Redemption", "TEX Inventory Day", "TEX Markup Rule", "TEX FX Policy", "TEX Pricing Policy",
	"TEX Tax Policy", "TEX Extra Inventory Day", "TEX Extra Allocation",
	"TEX Cancellation Policy", "TEX Payment Policy", "TEX Communication", "TEX Funnel Event",
	"TEX Content Translation", "TEX Channel Mapping", "TEX Channel ARI Day", "TEX Channel Inbound",
)
# belongs to a hotel or to a whole hotel group
GROUP_DOCTYPES = ("TEX Promotion", "TEX Loyalty Program", "TEX Booking Site")
# blank hotel means platform level: only platform administrators see those rows
STRICT_DOCTYPES = ("TEX Audit Event",)
# hotel known through a parent document
VIA_PARENT = {
	"TEX Reservation Revision": ("reservation", "Reservation"),
	"TEX Contract Version": ("contract", "TEX Contract"),
	"TEX Loyalty Ledger": ("program", "TEX Loyalty Program"),
}
# belongs to an enterprise; presets (``system_key``) are shared by every tenant
ENTERPRISE_DOCTYPES = ("TEX Guest Segment",)
SCOPED_DOCTYPES = (*PROPERTY_DOCTYPES, *GROUP_DOCTYPES, *STRICT_DOCTYPES, *VIA_PARENT, "Guest",
                   *ENTERPRISE_DOCTYPES)


def _sql_list(values) -> str:
	return ", ".join(frappe.db.escape(v) for v in sorted(values)) or "''"


def _groups(props: set[str]) -> set[str]:
	if not props:
		return set()
	return {g for g in frappe.get_all("Property", filters={"name": ("in", list(props))}, pluck="tex_hotel_group") if g}


def _enterprises(props: set[str]) -> set[str]:
	if not props:
		return set()
	return {e for e in frappe.get_all("Property", filters={"name": ("in", list(props))}, pluck="tex_enterprise") if e}


def _owner_condition(doctype: str, props: set[str]) -> str:
	t = f"`tab{doctype}`"
	if doctype in GROUP_DOCTYPES:
		return (f"({t}.`property` in ({_sql_list(props)}) or "
		        f"(ifnull({t}.`property`, '') = '' and {t}.`hotel_group` in ({_sql_list(_groups(props))})) or "
		        f"(ifnull({t}.`property`, '') = '' and ifnull({t}.`hotel_group`, '') = ''))")
	return f"{t}.`property` in ({_sql_list(props)})"


def query_conditions(user: str | None = None, doctype: str | None = None) -> str:
	user = user or frappe.session.user
	if scope.is_platform_admin(user):
		return ""
	props = scope.permitted_properties(user)
	if not props:
		return "1=0"
	t = f"`tab{doctype}`"
	if doctype in STRICT_DOCTYPES:
		return f"{t}.`property` in ({_sql_list(props)})"
	if doctype in GROUP_DOCTYPES:
		return _owner_condition(doctype, props)
	if doctype in VIA_PARENT:
		field, parent = VIA_PARENT[doctype]
		return f"{t}.`{field}` in (select name from `tab{parent}` where {_owner_condition(parent, props)})"
	if doctype in ENTERPRISE_DOCTYPES:
		return (f"(ifnull({t}.`system_key`, '') != '' or "
		        f"{t}.`enterprise` in ({_sql_list(_enterprises(props))}))")
	if doctype == "Guest":
		ents = _enterprises(props)
		return (f"({t}.name in (select r.guest from `tabReservation` r where r.property in ({_sql_list(props)}))"
		        f" or {t}.tex_enterprise in ({_sql_list(ents)})"
		        f" or (ifnull({t}.tex_enterprise, '') = '' and not exists "
		        f"(select 1 from `tabReservation` r2 where r2.guest = {t}.name)))")
	# blank property = a platform-wide record (e.g. a global policy); readable like before
	return f"({t}.`property` in ({_sql_list(props)}) or ifnull({t}.`property`, '') = '')"


def property_query_conditions(user: str | None = None, doctype: str | None = None) -> str:
	user = user or frappe.session.user
	if scope.is_platform_admin(user):
		return ""
	props = scope.permitted_properties(user)
	if not props:
		return "1=0"
	return f"`tabProperty`.`name` in ({_sql_list(props)})"


def _doc_properties(doc) -> tuple[set[str] | None, bool]:
	"""→ (hotels the record belongs to, is_platform_level). None = not hotel-bound."""
	dt = doc.doctype
	if dt == "Property":
		return {doc.name}, False
	if dt in VIA_PARENT:
		field, parent = VIA_PARENT[dt]
		name = doc.get(field)
		if not name:
			return None, False
		fields = ["property", "hotel_group"] if parent in GROUP_DOCTYPES else ["property"]
		pdoc = frappe.db.get_value(parent, name, fields, as_dict=True) or {}
		if pdoc.get("property"):
			return {pdoc["property"]}, False
		if pdoc.get("hotel_group"):
			return set(frappe.get_all("Property", filters={"tex_hotel_group": pdoc["hotel_group"]}, pluck="name")), False
		return None, False
	if dt in GROUP_DOCTYPES and not doc.get("property") and doc.get("hotel_group"):
		return set(frappe.get_all("Property", filters={"tex_hotel_group": doc.hotel_group}, pluck="name")), False
	prop = doc.get("property")
	if prop:
		return {prop}, False
	return None, dt in STRICT_DOCTYPES


def has_permission(doc, ptype=None, user=None, debug=False) -> bool:
	"""Frappe controller hook: may only deny (False); True defers to role permissions."""
	user = user or frappe.session.user
	if scope.is_platform_admin(user):
		return True
	if doc.doctype == "Guest":
		if doc.is_new() or not doc.name:
			return True
		return _guest_visible(doc, user)
	if doc.doctype == "Property" and doc.is_new():
		return True
	if doc.doctype in ENTERPRISE_DOCTYPES:
		return bool(doc.get("system_key")) or (bool(doc.get("enterprise"))
		                                        and doc.enterprise in _enterprises(scope.permitted_properties(user)))
	props, platform_level = _doc_properties(doc)
	if platform_level:
		return False
	if not props:
		return True
	return bool(props & scope.permitted_properties(user))


def _guest_visible(doc, user: str) -> bool:
	props = scope.permitted_properties(user)
	if not props:
		return False
	if doc.get("tex_enterprise") and doc.tex_enterprise in _enterprises(props):
		return True
	stays = set(frappe.get_all("Reservation", filters={"guest": doc.name}, pluck="property", distinct=True))
	if stays:
		return bool(stays & props)
	return not doc.get("tex_enterprise")


def stamp_guest_enterprise(doc, method=None) -> None:
	"""Guest.before_insert: a guest created by a user who works for exactly one
	enterprise belongs to it (keeps legacy walk-in profiles inside their tenant)."""
	if doc.get("tex_enterprise") or frappe.session.user in ("Administrator", "Guest"):
		return
	ents = _enterprises(scope.permitted_properties())
	if len(ents) == 1:
		doc.tex_enterprise = ents.pop()
