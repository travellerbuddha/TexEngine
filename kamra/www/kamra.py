import html as html_lib
import os
import re

import frappe

from kamra.tex import entry

# The SPA owns its own routing; never cache the boot shell.
no_cache = 1

_TITLE = re.compile(r"<title>.*?</title>", re.IGNORECASE | re.DOTALL)


def get_context(context):
	"""Serve the built React SPA shell with the session CSRF token injected.

	The front-end is built by Vite into kamra/public/frontend (served by Frappe
	at /assets/kamra/frontend/). We read that index.html at request time — so
	asset hashes never need to be hard-coded — and inject window.csrf_token so
	the SPA can POST to whitelisted endpoints once the user is logged in.

	TEX (G-60, ADR-060): the site's home page is this page, but the SPA's router
	is mounted at /kamra and rendered nothing at "/". The root now leads to the
	TEX admin app or the sign-in page (``entry.root_target``). A booking site's
	own host never gets here: its renderer claims "/" first (booking_host.py).
	The tab title is the brand (TEX Settings), escaped.
	"""
	request = getattr(frappe.local, "request", None)
	if request is not None and not entry.below_mount(request.path):
		frappe.local.flags.redirect_location = entry.root_target()
		raise frappe.Redirect(302)

	index_path = frappe.get_app_path("kamra", "public", "frontend", "index.html")
	if not os.path.exists(index_path):
		frappe.throw(
			frappe._(
				"The TEX Engine front-end is not built. Run "
				"<code>cd apps/kamra/frontend && yarn install && yarn build</code> "
				"(Frappe Cloud runs this automatically on deploy)."
			),
			title="TEX Engine not built",
		)

	with open(index_path, encoding="utf-8") as f:  # nosemgrep: frappe-security-file-traversal -- serves the app's own built index.html from a fixed app path, not user input
		html = f.read()

	title = f"<title>{html_lib.escape(entry.brand_name())}</title>"
	html = _TITLE.sub(lambda _m: title, html, count=1)

	csrf = frappe.sessions.get_csrf_token()
	# the source offer is part of the page (AGPL-3.0 section 13): shown even when the API is not
	boot = f'<script>window.csrf_token = "{csrf}";</script>' + entry.source_meta()
	# Inject before the module script so the token is set before the app boots.
	html = html.replace("</head>", boot + "</head>", 1)

	context.spa_html = html
	context.no_cache = 1
	return context
