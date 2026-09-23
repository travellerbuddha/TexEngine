"""Idempotent TEX setup. Called from ``after_install`` (fresh sites) and from the
``kamra.patches.tex.*`` patches (upgraded Kamra sites) — MIGRATION_PLAN §2.
Every function can run any number of times without duplicating data."""

from __future__ import annotations

import frappe

from kamra.tex.security.capabilities import DEFAULT_PROFILES

MARKETS = [
	# code, name, countries, currency, language, global
	("GLOBAL", "Global", "", "EUR", "en", 1),
	("TR", "Türkiye", "TR", "TRY", "tr", 0),
	("DE", "Germany", "DE", "EUR", "de", 0),
	("UK", "United Kingdom", "GB", "GBP", "en", 0),
	("RO", "Romania", "RO", "EUR", "ro", 0),
	("PL", "Poland", "PL", "EUR", "pl", 0),
	("RU", "Russia", "RU", "USD", "ru", 0),
	("CIS", "CIS", "AM, AZ, BY, KG, KZ, MD, TJ, UZ", "USD", "ru", 0),
	("DACH", "DACH", "AT, CH, DE", "EUR", "de", 0),
	("EU", "European Union", "AT, BE, BG, CY, CZ, DE, DK, EE, ES, FI, FR, GR, HR, HU, IE, IT, LT, LU, LV, MT, NL, "
	                         "PL, PT, RO, SE, SI, SK", "EUR", "en", 0),
]

CHANNELS = [
	("DIRECT_WEB", "Direct web (booking engine)", "Booking Engine"),
	("CALL_CENTER", "Call center", "Call Center"),
	("API", "API", "API"),
	("B2B", "B2B / tour operators", "B2B"),
	("META", "Metasearch", "Metasearch"),
	("OTA", "OTA / channel manager", "OTA"),
]


def ensure_custom_fields() -> None:
	from frappe.custom.doctype.custom_field.custom_field import create_custom_fields

	create_custom_fields({
		"User Permission": [{
			"fieldname": "tex_managed", "fieldtype": "Check", "label": "Managed by TEX access grants",
			"read_only": 1, "insert_after": "apply_to_all_doctypes",
		}],
	}, ignore_validate=True, update=True)


def ensure_profiles() -> None:
	for name, caps in {**DEFAULT_PROFILES, "Scope Only": frozenset()}.items():
		if frappe.db.exists("TEX Permission Profile", name):
			continue
		doc = frappe.get_doc({
			"doctype": "TEX Permission Profile", "profile_name": name, "is_system": 1,
			"description": "Access without extra capabilities (roles decide)" if not caps else "",
			"capabilities": [{"capability": c} for c in sorted(caps)],
		})
		doc.insert(ignore_permissions=True)


def ensure_masters() -> None:
	for code, name, countries, ccy, lang, is_global in MARKETS:
		if not frappe.db.exists("TEX Market", code):
			frappe.get_doc({"doctype": "TEX Market", "market_code": code, "market_name": name, "countries": countries,
			                "default_currency": ccy if frappe.db.exists("Currency", ccy) else None,
			                "default_language": lang, "is_global": is_global}).insert(ignore_permissions=True)
	for code, name, group in CHANNELS:
		if not frappe.db.exists("TEX Sales Channel", code):
			frappe.get_doc({"doctype": "TEX Sales Channel", "channel_code": code, "channel_name": name,
			                "channel_group": group}).insert(ignore_permissions=True)
	settings = frappe.get_single("TEX Settings")
	changed = False
	if not settings.default_sales_channel:
		settings.default_sales_channel = "DIRECT_WEB"
		changed = True
	if not settings.brand_name:
		settings.brand_name = "TEX Engine"
		changed = True
	if changed:
		settings.save(ignore_permissions=True)


def ensure_enterprise() -> None:
	"""Every property belongs to a hotel group and an enterprise (backfill)."""
	props = frappe.get_all("Property", fields=["name", "tex_hotel_group", "tex_enterprise"])
	orphans = [p for p in props if not p.tex_hotel_group]
	if not orphans:
		return
	ent = frappe.db.get_value("TEX Enterprise", {}, "name")
	if not ent:
		ent = frappe.get_doc({"doctype": "TEX Enterprise", "enterprise_name": "Default Enterprise"}).insert(
			ignore_permissions=True).name
	grp = frappe.db.get_value("TEX Hotel Group", {"enterprise": ent}, "name")
	if not grp:
		grp = frappe.get_doc({"doctype": "TEX Hotel Group", "group_name": "Default Hotel Group",
		                      "enterprise": ent}).insert(ignore_permissions=True).name
	for p in orphans:
		frappe.db.set_value("Property", p.name, {"tex_hotel_group": grp, "tex_enterprise": ent},
		                    update_modified=False)


KAMRA_ROLES = ("Hotel Admin", "Front Desk", "Revenue Manager", "Finance", "Housekeeping", "Kamra Agent",
               "Call Center Agent")


def migrate_legacy_access() -> dict:
	"""Make every user's current property access explicit (MIGRATION_PLAN T4):
	User Permissions → Hotel grants; users with a Kamra role and NO property
	restriction (legacy "sees every hotel") → Hotel grants for every property.
	Then strict tenancy is switched on without anyone losing access."""
	created = 0
	props = frappe.get_all("Property", pluck="name")
	users = frappe.get_all("Has Role", filters={"role": ("in", KAMRA_ROLES), "parenttype": "User"},
	                       pluck="parent", distinct=True)
	for user in sorted(set(users)):
		if user in ("Administrator", "Guest") or not frappe.db.get_value("User", user, "enabled"):
			continue
		ups = frappe.get_all("User Permission", filters={"user": user, "allow": "Property"}, pluck="for_value")
		targets = ups or props
		for p in targets:
			if frappe.db.exists("TEX Access Grant", {"user": user, "scope_level": "Hotel", "property": p}):
				continue
			g = frappe.get_doc({"doctype": "TEX Access Grant", "user": user, "scope_level": "Hotel", "property": p,
			                    "permission_profile": "Scope Only",
			                    "notes": "Migrated from Kamra property access"})
			g.flags.ignore_permissions = True
			g.flags.tex_migration = True
			g.insert(ignore_permissions=True)
			created += 1
	frappe.db.set_single_value("TEX Settings", "strict_tenancy", 1)
	return {"grants": created}


def ensure_all_hotels_scope(user: str) -> None:
	"""Platform-wide hotel scope with no extra capabilities (the user's roles still
	decide what they may do). For service / test accounts that work across every
	hotel, e.g. the eval personas."""
	if frappe.db.exists("TEX Access Grant", {"user": user, "scope_level": "Platform", "disabled": 0}):
		return
	ensure_profiles()
	g = frappe.get_doc({"doctype": "TEX Access Grant", "user": user, "scope_level": "Platform",
	                    "permission_profile": "Scope Only", "notes": "All hotels (service account)"})
	g.insert(ignore_permissions=True)


def default_legacy_pms_visibility() -> None:
	"""Upgraded sites that run the PMS keep seeing it; fresh TEX sites don't."""
	in_use = frappe.db.exists("Reservation", {"status": ("in", ["Checked In", "Checked Out"])}) or \
		frappe.db.exists("POS Order", {}) or frappe.db.exists("Housekeeping Task", {})
	frappe.db.set_single_value("TEX Settings", "show_legacy_pms", 1 if in_use else 0)


def ensure_indexes() -> None:
	for dt, fields, name in (
		("Reservation", ["room_type", "status", "check_in_date"], "tex_rt_status_ci"),
		("Reservation", ["tex_booking"], "tex_booking_idx"),
		("TEX ARI Restriction", ["property", "restriction_date"], "tex_ari_prop_date"),
		("TEX Inventory Day", ["room_type", "inventory_date"], "tex_inv_rt_date"),
		("TEX FX Rate", ["provider", "base_currency", "quote_currency", "rate_date"], "tex_fx_lookup"),
		("TEX Promotion", ["property", "tex_status"], "tex_promo_prop_status"),
		("TEX Markup Rule", ["property", "tex_status"], "tex_markup_prop_status"),
		("TEX Extra", ["property", "tex_status"], "tex_extra_prop_status"),
		("TEX Tax Policy", ["property", "tex_status"], "tex_taxpol_prop_status"),
		("TEX Extra Allocation", ["reservation"], "tex_xalloc_res"),
		("TEX Extra Allocation", ["property", "extra_code", "service_date"], "tex_xalloc_day"),
		("TEX Extra Inventory Day", ["property", "extra_code", "service_date"], "tex_xday_lookup"),
		("Reservation", ["guest", "property"], "tex_res_guest_prop"),              # CRM facts (G-23)
		("TEX Abandoned Booking", ["guest", "property"], "tex_abandoned_guest"),
		("TEX Channel ARI Day", ["mapping", "ari_date"], "tex_ari_day_lookup"),            # G-69
		("TEX Channel Inbound", ["connection", "provider_ref"], "tex_inbound_ref"),
		("TEX Channel Inbound", ["status", "next_attempt_at"], "tex_inbound_due"),
		("TEX Integration Outbox", ["kind", "status", "next_attempt_at"], "tex_outbox_due"),
		("TEX Booking", ["channel_connection", "external_ref"], "tex_booking_channel_ref"),
		("TEX Communication", ["status", "creation"], "tex_comm_status_created"),          # ADR-047
		("TEX Communication", ["email_queue"], "tex_comm_email_queue"),
	):
		try:
			frappe.db.add_index(dt, fields, name)
		except Exception:
			frappe.log_error(title=f"TEX index {name}")


def after_install() -> None:
	ensure_custom_fields()
	ensure_profiles()
	ensure_masters()
	ensure_enterprise()
	ensure_indexes()
	from kamra.tex.crm.service import ensure_system_segments

	ensure_system_segments()                     # the CRM presets (G-23)
	frappe.db.set_single_value("TEX Settings", "strict_tenancy", 1)
	frappe.db.set_single_value("TEX Settings", "show_legacy_pms", 0)
