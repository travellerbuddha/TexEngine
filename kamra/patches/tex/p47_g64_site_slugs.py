"""G-64 review follow-up (M3, ADR-060): booking sites named like one of the admin area's pages.

The admin app opened a site at ``/tex/booking-engine/<name>``, next to the area's own pages
``new``, ``content``, ``rooms`` and ``analytics``: a site named like one of them opened that page
instead. A site now opens at ``/tex/booking-engine/sites/<name>``, and an old link to it is
redirected there, except for those names (and ``sites``): an old link keeps opening the page of
that name. New sites may no longer take them (``TEX Booking Site.ADMIN_SLUGS``).

Existing sites with such a name are reported (``booking_site.admin_slug``), never renamed: a
site's name is its first slug, which guests, widgets and campaigns may use. The owner decides
whether to create the site again under another slug. Each is audited once: a re-run writes an
entry only for a site not reported yet (G-76).
"""

import frappe

from kamra.tex.security.audit import audit, recorded
from kamra.tex_booking.doctype.tex_booking_site.tex_booking_site import ADMIN_SLUGS

SITE = "TEX Booking Site"


def execute():
	found = frappe.get_all(SITE, filters={"name": ("in", ADMIN_SLUGS)}, fields=["name", "site_slug", "property",
	                                                                              "hotel_group", "enabled"],
	                       order_by="name asc")
	for s in found:
		new = {"name": s.name, "site_slug": s.site_slug, "old_link": f"/tex/booking-engine/{s.name}",
		       "opens": f"/tex/booking-engine/sites/{s.name}"}
		if recorded("booking_site.admin_slug", reference_doctype=SITE, reference_name=s.name, new=new):
			continue
		audit("booking_site.admin_slug", reference_doctype=SITE, reference_name=s.name, property=s.property or None,
		      source="System", new=new,
		      reason="The site is named like a page of the admin area: an old link to it opens that page. It now "
		             "opens under /tex/booking-engine/sites/; it keeps its name and slug (G-64).")
	print(f"p47: {len(found)} booking site(s) named like an admin page"
	      + (": " + ", ".join(s.name for s in found) if found else ""))
