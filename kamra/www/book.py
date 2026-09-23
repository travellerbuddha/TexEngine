"""TEX guest booking engine (ADR-012): serves the separate booking bundle at
/book/<site>/… — search, rooms, extras, guest details, payment, confirmation,
manage-booking and payment-link pages. No login; every action goes through the
rate-limited public API (kamra.tex.api.public).

The page may be framed only by the booking site's allowed embed origins
(CSP frame-ancestors); everything else is same-origin.
"""

import frappe

from kamra.tex.booking_host import booking_html, frame_ancestors, referrer_policy, with_referrer_policy
from kamra.tex.services import sites

no_cache = 1


def get_context(context):
	html = booking_html()
	path = (frappe.form_dict.get("app_path") or "").strip("/")
	slug = path.split("/", 1)[0] if path else None
	pinned = sites.pinned_slug()
	if pinned and slug not in (pinned, "pay"):
		# a hotel's own host serves only its site (payment pages are site-less)
		frappe.local.flags.redirect_location = "/"
		raise frappe.Redirect(302)
	if not slug:
		# bare /book: the only TEX booking site, or the legacy Kamra page when none exists
		sites_ = frappe.get_all("TEX Booking Site", filters={"enabled": 1}, pluck="site_slug", limit=2)
		frappe.local.flags.redirect_location = f"/book/{sites_[0]}" if len(sites_) == 1 else "/kamra/book"
		raise frappe.Redirect(302)
	frappe.local.response_headers["Content-Security-Policy"] = f"frame-ancestors {frame_ancestors(slug)}"
	# payment pages send no Referer (an old /book/pay/<token> link must not leak its token, G-83)
	policy = referrer_policy(path)
	frappe.local.response_headers["Referrer-Policy"] = policy
	context.spa_html = with_referrer_policy(html, policy)
	context.no_cache = 1
	return context
