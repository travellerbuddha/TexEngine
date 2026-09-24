"""Entry screens (G-60, ADR-060): the product name, the source offer and where "/" leads.

The Frappe app stays ``kamra`` (ADR-001); what people see says TEX Engine. The name shown
comes from TEX Settings > Brand name (a platform setting), never from a request.

TEX Engine is a network service derived from Kamra PMS under AGPL-3.0. Section 13 asks that
every user interacting with it can get its complete corresponding source, so the entry
screens link to where the source is offered: ``SOURCE_URL``, or the site config's
``tex_source_url`` (https only) when an operator offers it elsewhere.
"""

from __future__ import annotations

import frappe

PRODUCT = "TEX Engine"
SOURCE_URL = "https://github.com/travellerbuddha/TexEngine"
UPSTREAM = {"name": "Kamra PMS", "url": "https://github.com/Kamra-PMS/kamra-pms"}
LICENSE = {"name": "AGPL-3.0", "url": "https://www.gnu.org/licenses/agpl-3.0.html"}

# the SPA's router is mounted here (kamra/www/kamra.py, website_route_rules)
SPA_MOUNT = "kamra"
SIGN_IN = "/kamra/login"
ADMIN_APP = "/kamra/tex"
# a signed-in user without Desk access: Frappe's own portal page
PORTAL = "/me"
MAX_BRAND = 60


def brand_name() -> str:
	"""TEX Settings > Brand name, as plain text (the pages escape it), or the product name."""
	try:
		value = frappe.db.get_single_value("TEX Settings", "brand_name")
	except Exception:
		value = None
	value = " ".join(str(value or "").split())[:MAX_BRAND]
	return value or PRODUCT


def source_url() -> str:
	"""Where the running version's source is offered: the site config's ``tex_source_url`` when it
	is an https URL, otherwise the TEX Engine repository."""
	value = str(frappe.conf.get("tex_source_url") or "").strip()
	if value.startswith("https://") and len(value) <= 300 and not any(c.isspace() for c in value):
		return value
	return SOURCE_URL


def info() -> dict:
	"""What the public sign-in page shows: the name and the source offer. Nothing else."""
	return {"product": PRODUCT, "brand_name": brand_name(), "source_url": source_url(),
	        "upstream": dict(UPSTREAM), "license": dict(LICENSE)}


def below_mount(path: str | None) -> bool:
	"""Whether a request path is the SPA's own (``/kamra`` and below)."""
	first = (path or "").strip("/").split("/", 1)[0]
	return first == SPA_MOUNT


def root_target(user: str | None = None) -> str:
	"""Where the site root leads: the TEX admin app for a Desk user, the sign-in page for a
	visitor, Frappe's portal for a signed-in user without Desk access."""
	user = user or frappe.session.user
	if not user or user == "Guest":
		return SIGN_IN
	if user == "Administrator" or frappe.get_cached_value("User", user, "user_type") == "System User":
		return ADMIN_APP
	return PORTAL
