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
	"TEX Promotion Redemption", "TEX Inventory Day", "TEX Markup Rule", "TEX FX Policy", "TEX FX Rate",
	"TEX Pricing Policy",
	"TEX Tax Policy", "TEX Extra Inventory Day", "TEX Extra Allocation",
	"TEX Cancellation Policy", "TEX Payment Policy", "TEX Communication", "TEX Funnel Event",
	"TEX Content Translation", "TEX Channel Mapping", "TEX Channel ARI Day", "TEX Channel Inbound",
	"TEX Guest Change Request", "TEX Member Session",
)
# belongs to a hotel or to a whole hotel group
GROUP_DOCTYPES = ("TEX Promotion", "TEX Loyalty Program", "TEX Booking Site")
# blank hotel means platform level: only platform administrators see those rows. An audit event
# of a hotel group or an enterprise is seen at each hotel it reached (its TEX Audit Scope rows,
# ADR-053); a scope row only at its own hotel, so no hotel reads another's name. A legacy action log
# row without a hotel is platform level too (NEW-8): its before/after snapshots name guests and folios
STRICT_DOCTYPES = ("TEX Audit Event", "TEX Audit Scope", "Agent Action Log")
# hotel known through a parent document
VIA_PARENT = {
	"TEX Reservation Revision": ("reservation", "Reservation"),
	"TEX Contract Version": ("contract", "TEX Contract"),
}
# a loyalty entry belongs to its own hotel (``property``: its stay's or booking's, or the hotel a manual
# adjustment was made for), not to every hotel of its (group) program: each hotel reads its own entries,
# their bookings, reasons and actors. An entry of no hotel belongs to its program's hotel in a hotel's
# program, and is platform level in a group's (ADR-056 second review). A membership the same: the hotel it
# was made at (C-04, ADR-077)
LEDGER_DOCTYPE = "TEX Loyalty Ledger"
LOYALTY_DOCTYPES = (LEDGER_DOCTYPE, "TEX Loyalty Member")
# belongs to an enterprise; presets (``system_key``) are shared by every tenant
ENTERPRISE_DOCTYPES = ("TEX Guest Segment",)
# guest activity of a booking site: a group site's rows have no hotel yet and belong to the
# site's hotels (G-26); a row with neither is platform-level
SITE_DOCTYPES = ("TEX Funnel Event", "TEX Abandoned Booking", "TEX Member Session")
# the tenant structure itself: grants, enterprises and hotel groups are seen only inside the
# tenant (G-26); a platform-scope grant only by platform administrators
TENANT_DOCTYPES = ("TEX Access Grant", "TEX Enterprise", "TEX Hotel Group")
# the legacy Kamra DocTypes bound to a hotel by a ``property`` link (G-94): their Desk / REST reads
# follow the TEX scope (live grants and the user's own User Permissions), not only Frappe's User
# Permission filter, which a user left without mirrored rows (a grant deleted or ended) escapes
LEGACY_PROPERTY_DOCTYPES = (
	"AI Assistant Settings", "Banquet Checklist Template", "Banquet Dish",
	"Banquet Function Task", "Banquet Menu", "Banquet Service Item", "Cancelled Invoice", "Cashier",
	"Cashier Session", "Cashier Transaction", "Channel Manager Connection", "Channel Provider Connection",
	"City Ledger Account", "City Ledger Entry", "Copilot Conversation", "Credit Note", "Discount Voucher",
	"Exchange Rate", "Exchange Transaction", "Experience", "Folio Ledger Entry", "Folio Reprint",
	"Housekeeping Task", "Hurdle Rate", "Ingredient", "Ingredient Stock", "Laundry Order", "Laundry Rate",
	"Lost And Found Item", "Meal Plan", "Menu Item", "Night Audit Run", "POS Order", "POS Outlet",
	"POS Table Reservation", "Payment Gateway Settings", "Petty Cash Voucher", "Proforma Folio",
	"Rate Guardrail", "Revenue Budget", "Room Block", "Season", "Security Deposit", "Sellable Unit",
	"Service Ticket", "Shift Handover", "Stock Ledger Entry", "Transaction Code", "Turnover Profile",
	"Venue", "Venue Booking", "WhatsApp Message",
)
# cost (G-97): a contract, its versions and their rate tables (the audit trail's TRAIL_COST, which the
# TEX API reads with price.view_cost or contract.edit), and markups and pricing policies (price.view_cost).
# In Desk / REST their records are platform administrators' (DocType permissions), and so are the audit
# events about them, whose compact diffs carry the prices
CONTRACT_COST_DOCTYPES = frozenset({"TEX Contract", "TEX Contract Version",
                                    # a contract version's rate tables
                                    "TEX Price Period", "TEX Period Rate", "TEX Child Age Band", "TEX Occupancy Rule",
                                    "TEX Board Rule", "TEX Contract Room", "TEX Contract Rate Plan",
                                    "TEX Contract Offer", "TEX Contract Channel"})
COST_DOCTYPES = CONTRACT_COST_DOCTYPES | {"TEX Markup Rule", "TEX Pricing Policy"}
SCOPED_DOCTYPES = (*PROPERTY_DOCTYPES, *GROUP_DOCTYPES, *STRICT_DOCTYPES, *VIA_PARENT, *LOYALTY_DOCTYPES, "Guest",
                   *ENTERPRISE_DOCTYPES, *TENANT_DOCTYPES, *LEGACY_PROPERTY_DOCTYPES)


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
	if doctype == "TEX Audit Event":
		return (f"({t}.`property` in ({_sql_list(props)}) or {t}.`name` in (select s.`event` from "
		        f"`tabTEX Audit Scope` s where s.`property` in ({_sql_list(props)})))"
		        f" and ifnull({t}.`reference_doctype`, '') not in ({_sql_list(COST_DOCTYPES)})")
	if doctype in STRICT_DOCTYPES:
		return f"{t}.`property` in ({_sql_list(props)})"
	if doctype in GROUP_DOCTYPES:
		return _owner_condition(doctype, props)
	if doctype in VIA_PARENT:
		field, parent = VIA_PARENT[doctype]
		return f"{t}.`{field}` in (select name from `tab{parent}` where {_owner_condition(parent, props)})"
	if doctype in LOYALTY_DOCTYPES:
		return (f"({t}.`property` in ({_sql_list(props)}) or (ifnull({t}.`property`, '') = '' and {t}.`program` in "
		        f"(select name from `tabTEX Loyalty Program` where `property` in ({_sql_list(props)}))))")
	if doctype in ENTERPRISE_DOCTYPES:
		return (f"(ifnull({t}.`system_key`, '') != '' or "
		        f"{t}.`enterprise` in ({_sql_list(_enterprises(props))}))")
	if doctype == "TEX Enterprise":
		return f"{t}.`name` in ({_sql_list(_enterprises(props))})"
	if doctype == "TEX Hotel Group":
		return f"{t}.`name` in ({_sql_list(_groups(props))})"
	if doctype == "TEX Access Grant":
		return (f"({t}.`user` = {frappe.db.escape(user)}"
		        f" or ({t}.`scope_level` = 'Hotel' and {t}.`property` in ({_sql_list(props)}))"
		        f" or ({t}.`scope_level` = 'Hotel Group' and {t}.`hotel_group` in ({_sql_list(_groups(props))}))"
		        f" or ({t}.`scope_level` = 'Enterprise' and {t}.`enterprise` in ({_sql_list(_enterprises(props))})))")
	if doctype in SITE_DOCTYPES:
		return (f"({t}.`property` in ({_sql_list(props)}) or (ifnull({t}.`property`, '') = '' and "
		        f"{t}.`site` in (select name from `tabTEX Booking Site` where "
		        f"{_owner_condition('TEX Booking Site', props)})))")
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
	if dt in LOYALTY_DOCTYPES:
		hotel = doc.get("property") or (frappe.db.get_value("TEX Loyalty Program", doc.get("program"), "property")
		                                if doc.get("program") else None)
		return ({hotel}, False) if hotel else (None, True)
	if dt in GROUP_DOCTYPES and not doc.get("property") and doc.get("hotel_group"):
		return set(frappe.get_all("Property", filters={"tex_hotel_group": doc.hotel_group}, pluck="name")), False
	prop = doc.get("property")
	if prop:
		return {prop}, False
	if dt == "TEX Audit Event" and doc.name:
		reached = set(frappe.get_all("TEX Audit Scope", filters={"event": doc.name}, pluck="property"))
		return (reached, False) if reached else (None, True)
	if dt in SITE_DOCTYPES:
		site = frappe.db.get_value("TEX Booking Site", doc.get("site"), ["property", "hotel_group"],
		                           as_dict=True) if doc.get("site") else None
		if site and site.property:
			return {site.property}, False
		if site and site.hotel_group:
			return set(frappe.get_all("Property", filters={"tex_hotel_group": site.hotel_group}, pluck="name")), False
		return None, True
	return None, dt in STRICT_DOCTYPES


def _tenant_doc_permitted(doc, user: str) -> bool:
	"""TEX Enterprise / Hotel Group / Access Grant for a non-platform user (G-26)."""
	props = scope.permitted_properties(user)
	if doc.doctype == "TEX Enterprise":
		return doc.name in _enterprises(props)
	if doc.doctype == "TEX Hotel Group":
		return doc.name in _groups(props)
	if doc.is_new():
		return True                                  # the controller decides who may grant what
	# who may change or delete it is decided by the TEX Access Grant controller, on every path
	if doc.scope_level == "Platform":
		return doc.user == user
	return doc.user == user or bool(set(scope._grant_properties(doc)) & props)


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
	if doc.doctype in TENANT_DOCTYPES:
		return _tenant_doc_permitted(doc, user)
	if doc.doctype == "TEX Audit Event" and doc.get("reference_doctype") in COST_DOCTYPES:
		return False                              # cost: the TEX audit log serves it by price.view_cost (G-97)
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
