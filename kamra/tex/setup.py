"""Idempotent TEX setup. Called from ``after_install`` (fresh sites) and from the
``kamra.patches.tex.*`` patches (upgraded Kamra sites) — MIGRATION_PLAN §2.
Every function can run any number of times without duplicating data."""

from __future__ import annotations

import frappe

from kamra.tex.security.capabilities import DEFAULT_PROFILES

MARKETS = [
	# code, name, countries, currency, language, global, residents only on the web (O-8, D-5: the domestic market)
	("GLOBAL", "Global", "", "EUR", "en", 1, 0),
	("TR", "Türkiye", "TR", "TRY", "tr", 0, 1),
	("DE", "Germany", "DE", "EUR", "de", 0, 0),
	("UK", "United Kingdom", "GB", "GBP", "en", 0, 0),
	("RO", "Romania", "RO", "EUR", "ro", 0, 0),
	("PL", "Poland", "PL", "EUR", "pl", 0, 0),
	("RU", "Russia", "RU", "USD", "ru", 0, 0),
	("CIS", "CIS", "AM, AZ, BY, KG, KZ, MD, TJ, UZ", "USD", "ru", 0, 0),
	("DACH", "DACH", "AT, CH, DE", "EUR", "de", 0, 0),
	("EU", "European Union", "AT, BE, BG, CY, CZ, DE, DK, EE, ES, FI, FR, GR, HR, HU, IE, IT, LT, LU, LV, MT, NL, "
	                         "PL, PT, RO, SE, SI, SK", "EUR", "en", 0, 0),
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
	for code, name, countries, ccy, lang, is_global, residents_only in MARKETS:
		if not frappe.db.exists("TEX Market", code):
			# on create only: an administrator's choice is never undone (an upgraded site gets TR's rule from p71)
			frappe.get_doc({"doctype": "TEX Market", "market_code": code, "market_name": name, "countries": countries,
			                "default_currency": ccy if frappe.db.exists("Currency", ccy) else None,
			                "default_language": lang, "is_global": is_global,
			                "residency_required": residents_only}).insert(ignore_permissions=True)
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


def ensure_enterprise() -> list[str]:
	"""Every property belongs to a hotel group and an enterprise (backfill), where that is not a
	guess: a site without an enterprise (a Kamra upgrade) gets "Default Enterprise" with "Default
	Hotel Group"; a site with one enterprise and at most one hotel group puts a hotel without a
	group there. On a site of several tenants (or one with several groups) a hotel without a group
	is never given to one of them: it is printed, stays outside TEX and is seen by platform
	administrators only, until an administrator adds it to its hotel group (G-76). → the hotels
	left without a group."""
	props = frappe.get_all("Property", fields=["name", "tex_hotel_group", "tex_enterprise"], order_by="name asc")
	orphans = [p for p in props if not p.tex_hotel_group]
	if not orphans:
		return []
	ents = frappe.get_all("TEX Enterprise", pluck="name")
	groups = frappe.get_all("TEX Hotel Group", filters={"enterprise": ents[0]}, pluck="name") if len(ents) == 1 else []
	if len(ents) > 1 or len(groups) > 1:
		names = [p.name for p in orphans]
		print(f"TEX: {len(names)} hotel(s) without a hotel group on a site of several tenants or groups, left out "
		      f"of TEX until an administrator adds each to its group: {', '.join(names)}")
		return names
	ent = ents[0] if ents else frappe.get_doc({"doctype": "TEX Enterprise", "enterprise_name": "Default Enterprise"}
	                                          ).insert(ignore_permissions=True).name
	grp = groups[0] if groups else frappe.get_doc({"doctype": "TEX Hotel Group", "group_name": "Default Hotel Group",
	                                               "enterprise": ent}).insert(ignore_permissions=True).name
	for p in orphans:
		frappe.db.set_value("Property", p.name, {"tex_hotel_group": grp, "tex_enterprise": ent},
		                    update_modified=False)
	return []


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


def ran_before(patch: str) -> bool:
	"""Whether the migration ran ``patch`` already: a Patch Log row Frappe wrote after the patch
	succeeded. A step that converts data or grants a capability once, at the upgrade that brings it,
	is skipped when an operator forces the patch again: a re-run never undoes what administrators
	changed since (G-76, ADR-058).

	As Frappe reads its log (review of G-76, H1): a row ``skipped`` by ``bench migrate
	--skip-failing`` is a failed attempt, and Frappe runs the patch again next time, so that run is a
	first run; a patch line re-issued with a suffix (``<module> #<date>``) is logged under that line."""
	like = patch.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + " %"
	return bool(frappe.db.sql("""SELECT 1 FROM `tabPatch Log` WHERE IFNULL(skipped, 0) = 0
	                             AND (patch = %s OR patch LIKE %s) LIMIT 1""", (patch, like)))


# composite indexes for availability, restrictions, FX, extras, CRM, channels and audit lookups:
# (doctype, columns, index name). Each has at least two columns: Frappe drops a single-column index
# on a field without ``search_index`` whenever it syncs that DocType again (and ``add_index`` keeps
# no property setter during a migration), so single-column ones did not survive (G-76, p39).
TEX_INDEXES = (
	("Reservation", ["room_type", "status", "check_in_date"], "tex_rt_status_ci"),
	("Reservation", ["tex_booking", "tex_room_index"], "tex_booking_room"),
	("TEX ARI Restriction", ["property", "restriction_date"], "tex_ari_prop_date"),
	("TEX Inventory Day", ["room_type", "inventory_date"], "tex_inv_rt_date"),
	("TEX FX Rate", ["provider", "base_currency", "quote_currency", "rate_date"], "tex_fx_lookup"),
	("TEX Promotion", ["property", "tex_status"], "tex_promo_prop_status"),
	("TEX Markup Rule", ["property", "tex_status"], "tex_markup_prop_status"),
	("TEX Extra", ["property", "tex_status"], "tex_extra_prop_status"),
	("TEX Tax Policy", ["property", "tex_status"], "tex_taxpol_prop_status"),
	("TEX Extra Allocation", ["reservation", "status"], "tex_xalloc_res_status"),
	("TEX Extra Allocation", ["property", "extra_code", "service_date"], "tex_xalloc_day"),
	("TEX Extra Inventory Day", ["property", "extra_code", "service_date"], "tex_xday_lookup"),
	("Reservation", ["guest", "property"], "tex_res_guest_prop"),              # CRM facts (G-23)
	("TEX Abandoned Booking", ["guest", "property"], "tex_abandoned_guest"),
	("TEX Channel ARI Day", ["mapping", "ari_date"], "tex_ari_day_lookup"),            # G-69
	("TEX Channel Inbound", ["connection", "provider_ref"], "tex_inbound_ref"),
	("TEX Channel Inbound", ["status", "next_attempt_at"], "tex_inbound_due"),
	("TEX Integration Outbox", ["kind", "status", "next_attempt_at"], "tex_outbox_due"),
	# a claim asks whether a due message has an earlier undelivered one of its reservation through this (LO-10, p74)
	("TEX Integration Outbox", ["connection", "reference_name", "status", "creation"], "tex_outbox_ref_order"),
	("TEX Booking", ["channel_connection", "external_ref"], "tex_booking_channel_ref"),
	("TEX Audit Event", ["action", "event_time"], "tex_audit_action_time"),            # ADR-047
	("TEX Communication", ["status", "creation"], "tex_comm_status_created"),
	("TEX Communication", ["email_queue", "status"], "tex_comm_queue_status"),
	# a consent withdrawal reads the funnel rows it clears through these, never scanning (ADR-056 second
	# review); the scheduler reads a session's events and case through them too
	("TEX Funnel Event", ["email_hash", "session_id"], "tex_funnel_hash_session"),
	("TEX Funnel Event", ["session_id", "occurred_at"], "tex_funnel_session_time"),
	("TEX Abandoned Booking", ["session_id", "status"], "tex_abandoned_session"),
	# a booking finds its guest by e-mail or phone within the enterprise; a profile its possible duplicates
	("Guest", ["email", "tex_enterprise"], "tex_guest_email_ent"),
	("Guest", ["phone", "tex_enterprise"], "tex_guest_phone_ent"),
	# the daily purge reads old funnel events through this, never scanning the funnel (third review)
	("TEX Funnel Event", ["occurred_at", "session_id"], "tex_funnel_time_session"),
	# a redemption reads a guest's balance with a lock through this
	("TEX Loyalty Ledger", ["guest", "program"], "tex_ledger_guest_program"),
	# a points return finds who spent a booking's points through this, wherever they are now (LO-06, p73)
	("TEX Loyalty Ledger", ["booking", "entry_type"], "tex_ledger_booking_type"),
	# a guest's membership of a program, read on every member-priced search and moved by a merge (C-04)
	("TEX Loyalty Member", ["guest", "program"], "tex_member_guest_program"),
	# a guest's web sessions: moved by a merge, removed by an erasure (C-04 on the web, ADR-078)
	("TEX Member Session", ["guest", "site"], "tex_member_session_guest"),
	# a merge reads and moves a profile's records with locking reads: every Link to Guest has an index
	# that starts with it, so those reads lock the profile's rows only (third review of ADR-056)
	("TEX Booking", ["booker_guest", "property"], "tex_booking_guest_prop"),
	("TEX Communication", ["guest", "property"], "tex_comm_guest_prop"),
	("TEX Funnel Event", ["guest", "property"], "tex_funnel_guest_prop"),
	("Folio", ["guest", "property"], "tex_folio_guest_prop"),
	("Security Deposit", ["guest", "property"], "tex_deposit_guest_prop"),
	("Service Ticket", ["guest", "property"], "tex_ticket_guest_prop"),
	("Lost And Found Item", ["guest", "property"], "tex_lost_guest_prop"),
	("Exchange Transaction", ["guest", "property"], "tex_exchange_guest_prop"),
	("Venue Booking", ["customer", "property"], "tex_venue_customer_prop"),
	("WhatsApp Message", ["guest", "property"], "tex_whatsapp_guest_prop"),
	# reports read a hotel's stays by arrival and a hotel's (or group site's) funnel by time (G-46, p46)
	("Reservation", ["property", "check_in_date"], "tex_res_prop_ci"),
	("TEX Funnel Event", ["property", "occurred_at"], "tex_funnel_prop_time"),
	("TEX Funnel Event", ["site", "occurred_at"], "tex_funnel_site_time"),
	# a withdraw locks its version's open quotes through this, never the whole quote table (O-13, p69)
	("TEX Quote", ["contract_version", "status", "expires_at"], "tex_quote_version_open"),
)


def missing_indexes() -> list[tuple]:
	"""The ``TEX_INDEXES`` this site does not have yet (a read: no DDL). An index whose table cannot
	be read is logged and left out: one broken table never stops the others (review of G-76, L6)."""
	out = []
	for dt, fields, name in TEX_INDEXES:
		try:
			if not frappe.db.has_index(f"tab{dt}", name):
				out.append((dt, fields, name))
		except Exception:
			frappe.log_error(title=f"TEX index {name}")
	return out


def ensure_indexes() -> None:
	"""Create the missing ``TEX_INDEXES``. Index creation is DDL, which commits: only what is missing
	is created, so a site that has them all runs none (and a test never commits)."""
	for dt, fields, name in missing_indexes():
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
	close_oauth_registration()


def close_oauth_registration() -> None:
	"""Frappe's OAuth provider registers no client for a guest on a TEX site (ADR-073): its dynamic client
	registration is on by default and ``register_client`` is a guest endpoint, while TEX uses no Frappe OAuth
	client. An administrator may switch it on again for a reviewed integration. Written with
	``get_single().save()``: ``set_single_value`` on a Single never saved stores that one field, and its other
	fields (both metadata switches, the resource name) would then read as blank."""
	if not frappe.db.exists("DocType", "OAuth Settings"):
		return
	settings = frappe.get_single("OAuth Settings")
	if settings.enable_dynamic_client_registration:
		settings.enable_dynamic_client_registration = 0
		settings.save(ignore_permissions=True)
