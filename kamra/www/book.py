"""TEX guest booking engine (ADR-012): serves the separate booking bundle at
/book/<site>/… — search, rooms, extras, guest details, payment, confirmation,
manage-booking and payment-link pages. No login; every action goes through the
rate-limited public API (kamra.tex.api.public).

The page may be framed only by the booking site's allowed embed origins
(CSP frame-ancestors); everything else is same-origin.
"""

import os

import frappe

no_cache = 1

RESERVED = {"pay"}


def _frame_ancestors(slug: str | None) -> str:
	origins = []
	if slug and slug not in RESERVED:
		raw = frappe.db.get_value("TEX Booking Site", {"site_slug": slug, "enabled": 1}, "allowed_embed_origins")
		origins = [o.strip() for o in (raw or "").splitlines() if o.strip().startswith("https://")]
	return " ".join(["'self'", *origins])


def get_context(context):
	index_path = frappe.get_app_path("kamra", "public", "frontend", "booking.html")
	if not os.path.exists(index_path):
		frappe.throw(frappe._("The booking engine is not built."), title="TEX booking not built")
	with open(index_path, encoding="utf-8") as f:  # nosemgrep: frappe-security-file-traversal -- fixed app path, not user input
		html = f.read()
	path = (frappe.form_dict.get("app_path") or "").strip("/")
	slug = path.split("/", 1)[0] if path else None
	frappe.local.response_headers["Content-Security-Policy"] = f"frame-ancestors {_frame_ancestors(slug)}"
	frappe.local.response_headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
	context.spa_html = html
	context.no_cache = 1
	return context
