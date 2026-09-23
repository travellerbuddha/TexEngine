"""Tenant scope and capability checks (ADR-011).

Hierarchy: Platform → Enterprise → Hotel Group → Hotel (Property).

A user's permitted properties come from
  * Frappe ``User Permission`` rows on Property (legacy Kamra mechanism), and
  * ``TEX Access Grant`` rows (Hotel / Hotel Group / Enterprise / Platform).
Without any of those, a non-admin user sees **nothing** when TEX Settings
``strict_tenancy`` is on (default), or every property in legacy mode.

Capabilities at a property = default capabilities of the user's roles ∪ the
capabilities of every grant covering that property. Every check happens here, in
the backend; the frontend only mirrors it for display.
"""

from __future__ import annotations

from functools import wraps

import frappe
from frappe import _

from kamra.tex.security.capabilities import ALL, PLATFORM_ROLES, ROLE_DEFAULTS

_CACHE_KEY = "tex_scope_cache"


def _cache() -> dict:
	c = getattr(frappe.local, _CACHE_KEY, None)
	if c is None:
		c = {}
		setattr(frappe.local, _CACHE_KEY, c)
	return c


def clear_cache() -> None:
	if hasattr(frappe.local, _CACHE_KEY):
		delattr(frappe.local, _CACHE_KEY)


def is_platform_admin(user: str | None = None) -> bool:
	user = user or frappe.session.user
	if user == "Administrator":
		return True
	return bool(set(PLATFORM_ROLES) & set(frappe.get_roles(user)))


def strict_tenancy() -> bool:
	try:
		return bool(frappe.db.get_single_value("TEX Settings", "strict_tenancy"))
	except Exception:
		return True


def _all_properties() -> list[str]:
	return frappe.get_all("Property", filters={"disabled": 0}, pluck="name", order_by="name asc")


def _grants(user: str) -> list[dict]:
	if not frappe.db.table_exists("TEX Access Grant"):
		return []
	today = frappe.utils.nowdate()
	rows = frappe.get_all(
		"TEX Access Grant",
		filters={"user": user, "disabled": 0},
		fields=["name", "scope_level", "property", "hotel_group", "enterprise", "permission_profile", "valid_until"],
	)
	return [r for r in rows if not r.valid_until or str(r.valid_until) >= today]


def _grant_properties(g) -> list[str]:
	if g.scope_level == "Platform":
		return _all_properties()
	if g.scope_level == "Enterprise" and g.enterprise:
		return frappe.get_all("Property", filters={"tex_enterprise": g.enterprise, "disabled": 0}, pluck="name")
	if g.scope_level == "Hotel Group" and g.hotel_group:
		return frappe.get_all("Property", filters={"tex_hotel_group": g.hotel_group, "disabled": 0}, pluck="name")
	if g.scope_level == "Hotel" and g.property:
		return [g.property]
	return []


def _scope(user: str) -> dict:
	"""{property: set(grant profiles)} for the user (cached per request)."""
	cache = _cache()
	if user in cache:
		return cache[user]
	scope: dict[str, set[str]] = {}
	for p in frappe.get_all("User Permission", filters={"user": user, "allow": "Property"}, pluck="for_value"):
		scope.setdefault(p, set())
	for g in _grants(user):
		for p in _grant_properties(g):
			scope.setdefault(p, set()).add(g.permission_profile)
	if not scope and not strict_tenancy():
		scope = {p: set() for p in _all_properties()}
	cache[user] = scope
	return scope


def permitted_properties(user: str | None = None) -> set[str]:
	user = user or frappe.session.user
	if is_platform_admin(user):
		return set(_all_properties())
	return set(_scope(user))


def _profile_caps(profile: str) -> frozenset[str]:
	cache = _cache().setdefault("__profiles__", {})
	if profile not in cache:
		cache[profile] = frozenset(frappe.get_all("TEX Profile Capability",
		                                          filters={"parent": profile, "parenttype": "TEX Permission Profile"},
		                                          pluck="capability"))
	return cache[profile]


def capabilities(property: str | None, user: str | None = None) -> frozenset[str]:
	user = user or frappe.session.user
	if is_platform_admin(user):
		return ALL
	scope = _scope(user)
	role_caps: set[str] = set()
	for role in frappe.get_roles(user):
		role_caps |= ROLE_DEFAULTS.get(role, frozenset())

	def at(profiles) -> set[str]:
		# a hotel's granted profiles decide there; Frappe role defaults only apply where the
		# user has no granted profile (legacy User Permission scope) (G-12)
		granted = {p for p in profiles if p}
		if not granted:
			return set(role_caps)
		caps: set[str] = set()
		for prof in granted:
			caps |= _profile_caps(prof)
		return caps

	if property is None:
		# capability anywhere in scope (for list screens); still requires some scope
		caps: set[str] = set()
		for profiles in scope.values():
			caps |= at(profiles)
		return frozenset(caps)
	if property not in scope:
		return frozenset()
	return frozenset(at(scope[property]))


def has_capability(cap: str, property: str | None = None, user: str | None = None) -> bool:
	return cap in capabilities(property, user)


def assert_property(property: str) -> None:
	if not property:
		frappe.throw(_("A hotel must be specified."), frappe.ValidationError)
	if property not in permitted_properties():
		frappe.throw(_("You don't have access to {0}.").format(property), frappe.PermissionError)


def require(cap: str, property: str | None) -> None:
	"""Raise PermissionError unless the current user holds ``cap`` at ``property``."""
	if property is not None:
		assert_property(property)
	if not has_capability(cap, property):
		frappe.throw(_("Not permitted: {0}.").format(cap), frappe.PermissionError)


def require_capability(cap: str, *, property_arg: str | None = "property", doc_arg: tuple[str, str] | None = None):
	"""Decorator for whitelisted endpoints (place below ``@frappe.whitelist()``).

	``property_arg`` names the kwarg holding the property; ``doc_arg=(kwarg, doctype)``
	resolves the property from a document instead.
	"""

	def deco(fn):
		@wraps(fn)
		def guarded(*args, **kwargs):
			prop = None
			if doc_arg:
				name = kwargs.get(doc_arg[0])
				prop = property_of(doc_arg[1], name) if name else None
				if name and not prop:
					frappe.throw(_("{0} {1} not found").format(doc_arg[1], name), frappe.DoesNotExistError)
			elif property_arg:
				prop = kwargs.get(property_arg)
			require(cap, prop)
			return fn(*args, **kwargs)

		guarded._tex_capability = cap
		return guarded

	return deco


# Which field carries the property for documents endpoints refer to.
_PROPERTY_FIELD = {
	"TEX Booking": "property", "Reservation": "property", "TEX Contract": "property", "Folio": "property",
	"TEX Payment Link": "property", "TEX Payment Transaction": "property", "TEX Extra": "property",
	"TEX Allotment": "property", "TEX ARI Restriction": "property", "Room Type": "property", "Room": "property",
	"Group Booking": "property", "Rate Plan": "property", "Meal Plan": "property", "Housekeeping Task": "property",
	"Service Ticket": "property", "Room Block": "property", "Security Deposit": "property",
	"TEX Quote": "property", "TEX Booking Site": "property", "TEX Abandoned Booking": "property",
	"TEX Cancellation Policy": "property", "TEX Payment Policy": "property", "Laundry Order": "property",
	"POS Order": "property", "Venue Booking": "property", "City Ledger Account": "property",
	"Cashier Session": "property", "Credit Note": "property", "Proforma Folio": "property",
	"TEX Tax Policy": "property", "TEX Extra Inventory Day": "property", "TEX Extra Allocation": "property",
}


def property_of(doctype: str, name: str) -> str | None:
	if doctype == "TEX Contract Version":
		contract = frappe.db.get_value("TEX Contract Version", name, "contract")
		return frappe.db.get_value("TEX Contract", contract, "property") if contract else None
	if doctype == "Property":
		return name if frappe.db.exists("Property", name) else None
	field = _PROPERTY_FIELD.get(doctype)
	if not field:
		return None
	return frappe.db.get_value(doctype, name, field)


def filter_permitted(properties) -> list[str]:
	allowed = permitted_properties()
	return [p for p in properties if p in allowed]
