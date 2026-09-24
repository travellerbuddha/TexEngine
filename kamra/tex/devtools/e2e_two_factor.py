"""A second sign-in factor for one test user, for the browser E2E (G-60 review M1, ADR-060).

    bench --site <site> execute kamra.tex.devtools.e2e_two_factor.enable --kwargs "{'password': '…'}"
    bench --site <site> execute kamra.tex.devtools.e2e_two_factor.disable

``enable`` makes one user, and no one else, sign in with a code from an authenticator app:
- a role of its own marked for two-factor sign-in, held only by that user;
- the site's two-factor switch set directly in the database. Saving System Settings instead would
  mark the role "All", i.e. everyone.
It refuses when another role on the site is marked already (those users would need a code too).
The user's authenticator secret is made here and returned, with the user, for the test to compute
codes with (``TEX_E2E_2FA_USER`` / ``TEX_E2E_2FA_SECRET``).

``disable`` puts the switch and the method back as they were and deletes the user and the role.
Run both under the bench-test lock. Never on a production site.
"""

from __future__ import annotations

import frappe

USER = "tex-e2e-2fa@example.com"
ROLE = "TEX E2E Two Factor"
# what the switch and the method were before ``enable`` (restored by ``disable``)
KEPT = "tex_e2e_2fa_before"


def enable(password: str) -> dict:
	import pyotp
	from frappe import twofactor
	from frappe.utils.password import encrypt, update_password

	others = frappe.get_all("Role", filters={"two_factor_auth": 1, "name": ("!=", ROLE)}, pluck="name")
	if others:
		frappe.throw(f"Roles {', '.join(others)} need a second factor already: they would need a code too.")
	if not frappe.db.get_default(KEPT):
		frappe.db.set_default(KEPT, frappe.as_json({
			"enable_two_factor_auth": frappe.db.get_single_value("System Settings", "enable_two_factor_auth"),
			"two_factor_method": frappe.db.get_single_value("System Settings", "two_factor_method")}))
	if not frappe.db.exists("Role", ROLE):
		frappe.get_doc({"doctype": "Role", "role_name": ROLE, "desk_access": 1, "two_factor_auth": 1}).insert(
			ignore_permissions=True)
	frappe.db.set_value("Role", ROLE, "two_factor_auth", 1)
	if not frappe.db.exists("User", USER):
		frappe.get_doc({"doctype": "User", "email": USER, "first_name": "Two Factor", "last_name": "E2E",
		                "user_type": "System User", "send_welcome_email": 0,
		                "roles": [{"role": ROLE}]}).insert(ignore_permissions=True)
	update_password(USER, password)
	secret = pyotp.random_base32()
	# where Frappe keeps a user's authenticator secret, and that its set-up is done (frappe.twofactor)
	twofactor.set_default(f"{USER}_otpsecret", encrypt(secret))
	twofactor.set_default(f"{USER}_otplogin", 1)
	frappe.db.set_single_value("System Settings", {"enable_two_factor_auth": 1, "two_factor_method": "OTP App"})
	frappe.db.commit()
	frappe.clear_cache()
	return {"user": USER, "secret": secret}


def disable() -> dict:
	before = frappe.parse_json(frappe.db.get_default(KEPT) or "{}") or {}
	frappe.db.set_single_value("System Settings", {
		"enable_two_factor_auth": before.get("enable_two_factor_auth") or 0,
		"two_factor_method": before.get("two_factor_method") or "OTP App"})
	frappe.db.sql("DELETE FROM `tabDefaultValue` WHERE parent = '__default' AND defkey = %s", KEPT)
	frappe.db.sql("DELETE FROM `tabDefaultValue` WHERE defkey IN %s",
	              ((f"{USER}_otpsecret", f"{USER}_otplogin"),))
	if frappe.db.exists("User", USER):
		frappe.delete_doc("User", USER, ignore_permissions=True, force=True)
	if frappe.db.exists("Role", ROLE):
		frappe.delete_doc("Role", ROLE, ignore_permissions=True, force=True)
	frappe.db.commit()
	frappe.clear_cache()
	return {"enable_two_factor_auth": frappe.db.get_single_value("System Settings", "enable_two_factor_auth")}
