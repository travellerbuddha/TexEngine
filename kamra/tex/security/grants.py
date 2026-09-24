"""TEX Access Grant management: User Permission sync and anti-escalation checks.

Grants are mirrored into Frappe ``User Permission`` rows on Property (marked
``tex_managed``) so Desk list views and ``frappe.get_list`` are tenant-isolated too.
Manually created User Permissions are never touched.
"""

from __future__ import annotations

import frappe
from frappe import _

from kamra.tex.security import scope
from kamra.tex.security.audit import audit
from kamra.tex.security.capabilities import profile_channels


def _desired_properties(user: str) -> tuple[set[str], bool]:
	props: set[str] = set()
	platform = False
	for g in scope._grants(user):
		if g.scope_level == "Platform":
			platform = True
			continue
		props.update(scope._grant_properties(g))
	return props, platform


def sync_user_permissions(user: str) -> dict:
	if not frappe.db.has_column("User Permission", "tex_managed"):
		return {"skipped": "tex_managed column missing"}
	desired, platform = _desired_properties(user)
	existing = frappe.get_all("User Permission", filters={"user": user, "allow": "Property"},
	                          fields=["name", "for_value", "tex_managed"])
	have = {r.for_value for r in existing}
	added, removed = [], []
	if platform:
		desired = set()
	for r in existing:
		if r.tex_managed and r.for_value not in desired:
			frappe.delete_doc("User Permission", r.name, ignore_permissions=True, force=True)
			removed.append(r.for_value)
	for p in sorted(desired - have):
		up = frappe.get_doc({"doctype": "User Permission", "user": user, "allow": "Property", "for_value": p,
		                     "apply_to_all_doctypes": 1, "tex_managed": 1})
		up.insert(ignore_permissions=True)
		added.append(p)
	scope.clear_cache()
	frappe.clear_cache(user=user)
	return {"added": added, "removed": removed}


def resync_for_properties(properties) -> None:
	"""A property moved between groups/enterprises: resync every group/enterprise grantee."""
	users = set(frappe.get_all("TEX Access Grant", filters={"scope_level": ("in", ["Hotel Group", "Enterprise"]),
	                                                        "disabled": 0}, pluck="user"))
	for u in sorted(users):
		sync_user_permissions(u)


def _granter_scope_level(user: str) -> set[str]:
	return {g.scope_level for g in scope._grants(user)}


def manage_refusal(grant) -> tuple[str, type[Exception]] | None:
	"""Why the current user may NOT create/change this grant (None: they may). They
	must administer users at (at least) the grant's scope and already hold every
	capability they hand out."""
	me = frappe.session.user
	if scope.is_platform_admin(me):
		return None
	if grant.user == me:
		return _("You cannot change your own access."), frappe.PermissionError
	levels = _granter_scope_level(me)
	order = ["Hotel", "Hotel Group", "Enterprise", "Platform"]
	mine = max((order.index(level) for level in levels), default=-1)
	if order.index(grant.scope_level) > mine:
		return _("You can only grant access up to your own scope."), frappe.PermissionError
	props = scope._grant_properties(grant)
	if not props:
		return _("The grant covers no hotel."), frappe.ValidationError
	profile_caps = set(frappe.get_all("TEX Profile Capability",
	                                  filters={"parent": grant.permission_profile}, pluck="capability"))
	# the sales channels the profile sells on (ADR-050): handed out only by someone who sells on them
	channels = profile_channels(profile_caps, scope._profile_listed_channels(grant.permission_profile),
	                            scope._every_channel())
	for p in props:
		held = scope.capabilities(p, me)
		if "user.admin" not in held:
			# never name a hotel outside the caller's own scope
			return _("This access covers a hotel where you don't administer users."), frappe.PermissionError
		missing = profile_caps - held
		if missing:
			return (_("You cannot grant capabilities you don't hold: {0}.").format(", ".join(sorted(missing))),
			        frappe.PermissionError)
		missing = channels - scope.sales_channels(p, me)
		if missing:
			return (_("You cannot grant sales channels you don't sell on: {0}.").format(", ".join(sorted(missing))),
			        frappe.PermissionError)
	return None


def assert_can_manage(grant) -> None:
	refusal = manage_refusal(grant)
	if refusal:
		frappe.throw(refusal[0], refusal[1])


def audit_grant(grant, action: str) -> None:
	before = grant.get_doc_before_save() if action == "grant.update" else None
	fields = ("user", "scope_level", "property", "hotel_group", "enterprise", "permission_profile", "valid_until",
	          "disabled")
	audit(action, reference_doctype="TEX Access Grant", reference_name=grant.name,
	      property=grant.property or None,
	      old={f: before.get(f) for f in fields} if before else None,
	      new={f: grant.get(f) for f in fields})
