"""Frappe permission hooks backed by TEX tenancy (ADR-011).

Grants are mirrored into User Permissions, so a scoped user is already filtered by
Frappe. These hooks close the remaining gap: under strict tenancy a user with no
scope at all must see no hotel data through Desk lists, reports or ``get_list`` —
not every hotel, which is what an empty User Permission set means to Frappe.
"""

from __future__ import annotations

import frappe

from kamra.tex.security import scope

# DocTypes whose rows belong to one hotel through a ``property`` field.
PROPERTY_DOCTYPES = (
	"Reservation", "Folio", "Room", "Room Type", "Rate Plan", "Group Booking", "TEX Booking", "TEX Contract",
	"TEX Payment Transaction", "TEX Payment Link", "TEX Payment Allocation", "TEX Quote", "TEX Allotment",
	"TEX ARI Restriction", "TEX Extra", "TEX Abandoned Booking", "TEX Integration Connection",
	"TEX Integration Outbox", "TEX Payment Provider Account", "TEX Payment Method Rule",
)


def _sql_list(values) -> str:
	return ", ".join(frappe.db.escape(v) for v in sorted(values))


def query_conditions(user: str | None = None, doctype: str | None = None) -> str:
	user = user or frappe.session.user
	if scope.is_platform_admin(user):
		return ""
	props = scope.permitted_properties(user)
	if not props:
		return "1=0"
	# blank property = a platform-wide record (e.g. a global policy); readable like before
	return f"(`tab{doctype}`.`property` in ({_sql_list(props)}) or ifnull(`tab{doctype}`.`property`, '') = '')"


def property_query_conditions(user: str | None = None, doctype: str | None = None) -> str:
	user = user or frappe.session.user
	if scope.is_platform_admin(user):
		return ""
	props = scope.permitted_properties(user)
	if not props:
		return "1=0"
	return f"`tabProperty`.`name` in ({_sql_list(props)})"


def has_permission(doc, ptype=None, user=None, debug=False) -> bool:
	"""Frappe controller hook: may only deny (False); True defers to role permissions."""
	user = user or frappe.session.user
	if scope.is_platform_admin(user):
		return True
	prop = doc.name if doc.doctype == "Property" else doc.get("property")
	if not prop or (doc.doctype == "Property" and doc.is_new()):
		return True
	return prop in scope.permitted_properties(user)
