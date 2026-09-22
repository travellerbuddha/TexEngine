"""TEX administration API: access grants, permission profiles, TEX settings, booking
site domains, integrations and the audit trail (R-47, R-48, R-50).

Grants are validated by the TEX Access Grant controller (anti-escalation: nobody
grants a scope or capability they do not hold); profiles and settings are platform
level and need a platform administrator.
"""

from __future__ import annotations

import json

import frappe
from frappe import _

from kamra.tex.api._util import as_int, parse, text
from kamra.tex.security import scope
from kamra.tex.security.audit import audit
from kamra.tex.security.capabilities import CAPABILITIES


def _require_platform() -> None:
	if not scope.is_platform_admin():
		frappe.throw(_("Only platform administrators can do this."), frappe.PermissionError)


def _user_admin_props() -> list[str]:
	return sorted(p for p in scope.permitted_properties() if scope.has_capability("user.admin", p))


# ─── users & grants ──────────────────────────────────────────────────────


@frappe.whitelist()
def users():
	"""Users holding a grant that touches a hotel I administer (platform admins: all)."""
	props = set(_user_admin_props())
	if not props:
		frappe.throw(_("Not permitted: {0}.").format("user.admin"), frappe.PermissionError)
	grants = frappe.get_all("TEX Access Grant", fields=["name", "user", "scope_level", "property", "hotel_group",
	                                                     "enterprise", "permission_profile", "valid_until",
	                                                     "disabled", "notes"], order_by="user asc")
	visible = []
	for g in grants:
		covered = set(scope._grant_properties(g))
		if scope.is_platform_admin() or (covered and covered & props):
			g["valid_until"] = str(g["valid_until"]) if g["valid_until"] else None
			g["properties"] = sorted(covered)
			visible.append(g)
	names = sorted({g["user"] for g in visible})
	info = {u.name: u for u in frappe.get_all("User", filters={"name": ("in", names or [""])},
	                                         fields=["name", "full_name", "enabled", "last_login", "user_type"])}
	return {"users": [{"user": u, "full_name": info[u].full_name if u in info else u,
	                   "enabled": info[u].enabled if u in info else 0,
	                   "last_login": str(info[u].last_login) if u in info and info[u].last_login else None,
	                   "grants": [g for g in visible if g["user"] == u]} for u in names],
	        "profiles": frappe.get_all("TEX Permission Profile", fields=["name", "profile_name", "is_system"],
	                                   order_by="profile_name asc")}


@frappe.whitelist(methods=["POST"])
def save_grant(data):
	d = parse(data, {}) or {}
	doc = frappe.get_doc("TEX Access Grant", d["name"]) if d.get("name") else frappe.new_doc("TEX Access Grant")
	if d.get("name"):
		grants_mod().assert_can_manage(doc)    # may I touch the grant as it stands?
	for f in ("user", "scope_level", "property", "hotel_group", "enterprise", "permission_profile", "valid_until",
	          "disabled", "notes"):
		if f in d:
			doc.set(f, d[f] or (0 if f == "disabled" else None))
	if not frappe.db.exists("User", doc.user):
		frappe.throw(_("User {0} does not exist.").format(doc.user))
	doc.save(ignore_permissions=True)     # controller re-validates the new state (anti-escalation)
	return {"name": doc.name}


@frappe.whitelist(methods=["POST"])
def delete_grant(name: str):
	doc = frappe.get_doc("TEX Access Grant", name)
	grants_mod().assert_can_manage(doc)
	frappe.delete_doc("TEX Access Grant", name, ignore_permissions=True)
	return {"ok": True}


def grants_mod():
	from kamra.tex.security import grants

	return grants


@frappe.whitelist(methods=["POST"])
def invite_user(email: str, first_name: str, last_name: str | None = None):
	"""Create a disabled-password Desk user a grant can then be attached to (the user
	sets a password through Frappe's standard reset e-mail)."""
	if not _user_admin_props():
		frappe.throw(_("Not permitted: {0}.").format("user.admin"), frappe.PermissionError)
	email = (text(email, 140) or "").lower()
	if "@" not in email:
		frappe.throw(_("Invalid email address."))
	if frappe.db.exists("User", email):
		return {"user": email, "existing": True}
	u = frappe.get_doc({"doctype": "User", "email": email, "first_name": text(first_name, 80) or email,
	                    "last_name": text(last_name, 80), "user_type": "System User", "send_welcome_email": 1})
	u.insert(ignore_permissions=True)
	audit("user.invite", reference_doctype="User", reference_name=email)
	return {"user": email, "existing": False}


# ─── permission profiles (platform) ──────────────────────────────────────


@frappe.whitelist()
def profiles():
	rows = frappe.get_all("TEX Permission Profile", fields=["name", "profile_name", "description", "is_system"],
	                      order_by="profile_name asc")
	for r in rows:
		r["capabilities"] = sorted(frappe.get_all("TEX Profile Capability", filters={"parent": r["name"]},
		                                          pluck="capability"))
	return {"profiles": rows, "capabilities": CAPABILITIES}


@frappe.whitelist(methods=["POST"])
def save_profile(data):
	_require_platform()
	d = parse(data, {}) or {}
	caps = sorted(set(d.get("capabilities") or []))
	unknown = [c for c in caps if c not in CAPABILITIES]
	if unknown:
		frappe.throw(_("Unknown capabilities: {0}").format(", ".join(unknown)))
	doc = frappe.get_doc("TEX Permission Profile", d["name"]) if d.get("name") else frappe.new_doc(
		"TEX Permission Profile")
	before = sorted(r.capability for r in doc.get("capabilities") or [])
	doc.profile_name = text(d.get("profile_name"), 140) or doc.profile_name
	doc.description = text(d.get("description"), 500)
	doc.set("capabilities", [{"capability": c} for c in caps])
	doc.save(ignore_permissions=True)
	scope.clear_cache()
	audit("profile.save", reference_doctype="TEX Permission Profile", reference_name=doc.name,
	      old={"capabilities": before}, new={"capabilities": caps})
	return {"name": doc.name}


# ─── settings (platform) ─────────────────────────────────────────────────

SETTINGS_FIELDS = ("strict_tenancy", "show_legacy_pms", "brand_name", "support_email", "default_market",
                   "default_sales_channel", "offer_ttl_minutes", "quote_ttl_minutes", "hold_minutes",
                   "manage_link_days", "fx_provider_default", "fx_max_age_days")


@frappe.whitelist()
def settings():
	_require_platform()
	s = frappe.get_single("TEX Settings")
	return {f: s.get(f) for f in SETTINGS_FIELDS}


@frappe.whitelist(methods=["POST"])
def save_settings(data):
	_require_platform()
	d = parse(data, {}) or {}
	s = frappe.get_single("TEX Settings")
	before = {f: s.get(f) for f in SETTINGS_FIELDS}
	for f in SETTINGS_FIELDS:
		if f in d:
			s.set(f, d[f])
	s.save(ignore_permissions=True)
	after = {f: s.get(f) for f in SETTINGS_FIELDS}
	audit("settings.save", reference_doctype="TEX Settings", reference_name="TEX Settings",
	      old={k: v for k, v in before.items() if before[k] != after[k]},
	      new={k: v for k, v in after.items() if before[k] != after[k]})
	return after


# ─── booking sites ───────────────────────────────────────────────────────


@frappe.whitelist(methods=["POST"])
def verify_domain(site: str, domain: str):
	from kamra.tex.services import sites

	return sites.verify_domain(site, domain)


@frappe.whitelist()
def embed_snippet(site: str):
	from kamra.tex.services import sites

	s = sites.require_site(site, "price.view")
	base = frappe.utils.get_url()
	return {
		"script": f'<script type="module" src="{base}/assets/kamra/tex/tex-widget.js" defer></script>',
		"element": f'<tex-booking-widget site="{s.site_slug}" api="{base}" mode="{s.widget_mode or "search"}">'
		           f"</tex-booking-widget>",
		"link": f"{base}/book/{s.site_slug}",
		"allowed_origins": (s.allowed_embed_origins or "").splitlines(),
	}


# ─── integrations ────────────────────────────────────────────────────────


@frappe.whitelist()
def outbox(property: str, status: str | None = None, limit=100):
	scope.require("connect.admin", property)
	filters: dict = {"property": property}
	if status:
		filters["status"] = status
	rows = frappe.get_all("TEX Integration Outbox", filters=filters,
	                      fields=["name", "connection", "event", "status", "attempts", "next_attempt_at", "sent_at",
	                              "last_error", "reference_doctype", "reference_name", "creation"],
	                      order_by="creation desc", limit_page_length=as_int(limit, 100, lo=1, hi=500))
	for r in rows:
		for k in ("next_attempt_at", "sent_at", "creation"):
			r[k] = str(r[k]) if r[k] else None
	return rows


@frappe.whitelist(methods=["POST"])
def retry_outbox(name: str):
	row = frappe.get_doc("TEX Integration Outbox", name)
	scope.require("connect.admin", row.property)
	if row.status not in ("Failed", "Dead"):
		frappe.throw(_("Only failed deliveries can be retried."))
	row.status = "Pending"
	row.next_attempt_at = frappe.utils.now_datetime()
	row.save(ignore_permissions=True)
	audit("outbox.retry", reference_doctype="TEX Integration Outbox", reference_name=name, property=row.property)
	return {"ok": True}


@frappe.whitelist(methods=["POST"])
def test_connection(name: str):
	from kamra.tex.connect import adapters

	conn = frappe.get_doc("TEX Integration Connection", name)
	scope.require("connect.admin", conn.property)
	try:
		result = adapters.get(conn).test()
		conn.db_set({"last_status": "OK", "last_error": None}, update_modified=False)
		return {"ok": True, **(result or {})}
	except Exception as e:
		conn.db_set({"last_status": "Error", "last_error": str(e)[:500]}, update_modified=False)
		return {"ok": False, "error": str(e)[:300]}


@frappe.whitelist()
def adapters():
	from kamra.tex.connect import adapters as reg

	return [{"key": k, "category": c.category, "label": c.label} for k, c in sorted(reg.REGISTRY.items())]


# ─── audit trail ─────────────────────────────────────────────────────────


@frappe.whitelist()
def audit_log(property: str | None = None, reference_doctype: str | None = None,
              reference_name: str | None = None, action: str | None = None, actor: str | None = None,
              date_from: str | None = None, date_to: str | None = None, start=0, limit=100):
	filters: dict = {}
	if property:
		scope.require("settings.admin", property)
		filters["property"] = property
	elif reference_doctype and reference_name:
		prop = scope.property_of(reference_doctype, reference_name)
		if prop:
			scope.require("reservation.view", prop)
		elif not scope.is_platform_admin():
			frappe.throw(_("Not permitted."), frappe.PermissionError)
	else:
		_require_platform()
	if reference_doctype:
		filters["reference_doctype"] = reference_doctype
	if reference_name:
		filters["reference_name"] = reference_name
	if action:
		filters["action"] = ("like", f"{text(action, 60)}%")
	if actor:
		filters["actor"] = actor
	if date_from and date_to:
		filters["event_time"] = ("between", [date_from, f"{date_to} 23:59:59"])
	rows = frappe.get_all("TEX Audit Event", filters=filters,
	                      fields=["name", "event_time", "action", "actor", "actor_roles", "source", "property",
	                              "reference_doctype", "reference_name", "reason", "old_value", "new_value"],
	                      order_by="event_time desc", limit_start=as_int(start, 0, lo=0),
	                      limit_page_length=as_int(limit, 100, lo=1, hi=500))
	for r in rows:
		r["event_time"] = str(r["event_time"])
		for k in ("old_value", "new_value"):
			try:
				r[k] = json.loads(r[k]) if r[k] else None
			except ValueError:
				pass
	return rows
