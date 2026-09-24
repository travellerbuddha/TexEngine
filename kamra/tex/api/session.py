"""Session bootstrap for the TEX admin/CRS/call-centre SPA."""

from __future__ import annotations

import frappe
from frappe.utils import get_system_timezone, now_datetime

from kamra.tex.security import scope
from kamra.tex.security.capabilities import CAPABILITIES


@frappe.whitelist()
def bootstrap():
	"""Who am I, which hotels may I work with and what may I do at each. The UI uses
	this only to decide what to show; every endpoint re-checks on the server."""
	user = frappe.session.user
	if user == "Guest":
		frappe.throw("Login required", frappe.AuthenticationError)
	props = sorted(scope.permitted_properties())
	rows = {p.name: p for p in frappe.get_all("Property", filters={"name": ("in", props or ["__none__"])},
	                                          fields=["name", "property_name", "city", "country", "currency",
	                                                  "tex_hotel_group", "tex_enterprise", "tex_default_market"])}
	settings = frappe.get_cached_doc("TEX Settings")
	out = {
		"user": {"name": user, "full_name": frappe.utils.get_fullname(user),
		         "roles": [r for r in frappe.get_roles(user) if r not in ("All", "Guest")],
		         "platform_admin": scope.is_platform_admin(user)},
		"properties": [{
			"name": p, "property_name": rows[p].property_name, "city": rows[p].city, "country": rows[p].country,
			"currency": rows[p].currency, "hotel_group": rows[p].tex_hotel_group, "enterprise": rows[p].tex_enterprise,
			"default_market": rows[p].tex_default_market,
			"capabilities": sorted(scope.capabilities(p, user)),
			# the channels the user may price and book on there: the CRS channel picker (ADR-050)
			"sales_channels": sorted(scope.sales_channels(p, user)),
		} for p in props if p in rows],
		"capabilities": CAPABILITIES,
		"settings": {"brand_name": settings.brand_name or "TEX Engine",
		             "show_legacy_pms": bool(settings.show_legacy_pms),
		             "default_market": settings.default_market, "default_sales_channel": settings.default_sales_channel},
		"markets": frappe.get_all("TEX Market", filters={"disabled": 0},
		                          fields=["name", "market_name", "is_global", "default_currency", "countries"],
		                          order_by="is_global desc, name asc"),
		"channels": frappe.get_all("TEX Sales Channel", filters={"disabled": 0},
		                           fields=["name", "channel_name", "channel_group"], order_by="name asc"),
		"currencies": frappe.get_all("Currency", filters={"enabled": 1}, pluck="name", order_by="name asc"),
	}
	# server datetimes are naive wall-clock times in this zone; ``now`` (read last, just before
	# the response leaves) lets the UI measure the offset to the browser clock (expiry
	# countdowns); ``today`` is the site's calendar day, where staff date pickers start (G-91),
	# taken from the same instant
	now = now_datetime()
	out["server"] = {"time_zone": get_system_timezone(), "now": now.isoformat(), "today": now.date().isoformat()}
	return out
