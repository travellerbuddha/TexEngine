"""Serve a booking site on its own verified host (G-21, ADR-035).

``https://book.hotel.com/<anything>`` renders the TEX booking engine pinned to that host's
site: the page carries the site's slug in a ``<meta name="tex-booking-site">`` tag and the
SPA routes from ``/``. The platform's own paths keep working on the host (assets, files,
the API, ``/book/pay/…`` pages that payment providers return to); another site's
``/book/<slug>`` is not served there (kamra/www/book.py).
"""

from __future__ import annotations

import html
import json
import os
import re

import frappe
from werkzeug.wrappers import Response

from kamra.tex.services import sites

# first path segments that are never the booking SPA on a custom host
PASS_THROUGH = {"api", "assets", "files", "private", ".well-known", "book", "mcp", "socket.io", "robots.txt",
                "favicon.ico", "website_script.js", "app", "desk", "login", "logout", "update-password"}


def booking_html() -> str:
	path = frappe.get_app_path("kamra", "public", "frontend", "booking.html")
	if not os.path.exists(path):
		frappe.throw(frappe._("The booking engine is not built."), title="TEX booking not built")
	with open(path, encoding="utf-8") as f:  # nosemgrep: frappe-security-file-traversal -- fixed app path, not user input
		page = f.read()
	# the guests' source offer (AGPL-3.0 section 13, ADR-060 review): in the page, not behind an API
	from kamra.tex import entry

	return page.replace("</head>", entry.source_meta() + "</head>", 1)


def with_session_token(page: str) -> str:
	"""The page with the session's CSRF token, for a signed-in user only (O-28).

	Frappe asks every POST of a session that holds a token to echo it, `allow_guest` or not: staff who
	had opened /kamra or /app saw the booking engine refuse its first call. A guest has no session token
	and gets none. The engine loads no third-party tracker on a page that carries one (ADR-046 note)."""
	if frappe.session.user == "Guest":
		return page
	token = json.dumps(frappe.sessions.get_csrf_token()).replace("<", "\\u003c")
	tag = f"<script>window.csrf_token={token};</script>"
	return page.replace("</head>", f"{tag}</head>", 1) if "</head>" in page else tag + page


# payment pages send no Referer at all: a payment link e-mailed before G-83 carries its token
# in the path (/book/pay/<token>) until the page moves it out; nothing may repeat it meanwhile
DEFAULT_REFERRER = "strict-origin-when-cross-origin"
_META_REFERRER = re.compile(r"<meta\s+name=[\"']?referrer[\"']?[^>]*>", re.IGNORECASE)


def referrer_policy(path: str | None) -> str:
	"""The Referrer-Policy of a booking-engine page, by its path below the mount (``pay/…``)."""
	first = (path or "").strip("/").split("/", 1)[0]
	return "no-referrer" if first == "pay" else DEFAULT_REFERRER


def with_referrer_policy(page: str, policy: str) -> str:
	"""The page with its ``<meta name="referrer">`` saying ``policy``: the page's own tag would
	override the header, and it comes before the page's scripts and styles load."""
	if policy == DEFAULT_REFERRER:
		return page
	tag = f'<meta name="referrer" content="{policy}" />'
	if _META_REFERRER.search(page):
		return _META_REFERRER.sub(tag, page, count=1)
	return page.replace("<head>", f"<head>{tag}", 1)


def frame_ancestors(slug: str | None) -> str:
	origins = []
	if slug and slug != "pay":
		raw = frappe.db.get_value("TEX Booking Site", {"site_slug": slug, "enabled": 1}, "allowed_embed_origins")
		origins = [o.strip() for o in (raw or "").splitlines() if o.strip().startswith("https://")]
	return " ".join(["'self'", *origins])


def pinned_page(slug: str) -> str:
	"""The SPA page pinned to one site (routes from ``/``)."""
	meta = f'<meta name="tex-booking-site" content="{html.escape(slug, quote=True)}">'
	page = booking_html()
	return page.replace("</head>", f"{meta}</head>", 1) if "</head>" in page else meta + page


class BookingHostRenderer:
	"""Frappe ``page_renderer``: claims website paths on a verified custom host."""

	def __init__(self, path, http_status_code=None):
		self.path = (path or "").strip("/")
		self.http_status_code = http_status_code
		self.slug = None

	def can_render(self) -> bool:
		first = self.path.split("/", 1)[0]
		if first in PASS_THROUGH:
			return False
		self.slug = sites.pinned_slug()
		return bool(self.slug)

	def render(self) -> Response:
		policy = referrer_policy(self.path)
		resp = Response(with_referrer_policy(with_session_token(pinned_page(self.slug)), policy), status=200,
		                content_type="text/html; charset=utf-8")
		resp.headers["Content-Security-Policy"] = f"frame-ancestors {frame_ancestors(self.slug)}"
		resp.headers["Referrer-Policy"] = policy
		resp.headers["Cache-Control"] = "no-store"
		return resp
