"""Serve a booking site on its own verified host (G-21, ADR-035).

``https://book.hotel.com/<anything>`` renders the TEX booking engine pinned to that host's
site: the page carries the site's slug in a ``<meta name="tex-booking-site">`` tag and the
SPA routes from ``/``. The platform's own paths keep working on the host (assets, files,
the API, ``/book/pay/…`` pages that payment providers return to); another site's
``/book/<slug>`` is not served there (kamra/www/book.py).
"""

from __future__ import annotations

import html
import os

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
		return f.read()


# payment pages send no Referer at all: a payment link e-mailed before G-83 carries its token
# in the path (/book/pay/<token>) until the page moves it out; nothing may repeat it meanwhile
DEFAULT_REFERRER = "strict-origin-when-cross-origin"
_META_REFERRER = f'<meta name="referrer" content="{DEFAULT_REFERRER}"'


def referrer_policy(path: str | None) -> str:
	"""The Referrer-Policy of a booking-engine page, by its path below the mount (``pay/…``)."""
	first = (path or "").strip("/").split("/", 1)[0]
	return "no-referrer" if first == "pay" else DEFAULT_REFERRER


def with_referrer_policy(page: str, policy: str) -> str:
	"""The page with its ``<meta name="referrer">`` saying ``policy`` (a meta tag overrides the header)."""
	return page.replace(_META_REFERRER, f'<meta name="referrer" content="{policy}"') if policy != DEFAULT_REFERRER \
		else page


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
		resp = Response(with_referrer_policy(pinned_page(self.slug), policy), status=200,
		                content_type="text/html; charset=utf-8")
		resp.headers["Content-Security-Policy"] = f"frame-ancestors {frame_ancestors(self.slug)}"
		resp.headers["Referrer-Policy"] = policy
		resp.headers["Cache-Control"] = "no-store"
		return resp
