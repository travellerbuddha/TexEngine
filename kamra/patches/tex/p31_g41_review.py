"""G-41 review follow-up (ADR-050) and G-94.

- A booking site sells only on a web channel (DIRECT_WEB, META). A site saved with another
  channel before (B2B, OTA, API, CALL_CENTER) now sells nothing: its search, quotes and
  bookings are refused, so its prices no longer reach the public. Such sites are not changed
  here (moving them to the web channel would put them on sale at web prices, an owner's
  decision): each is reported and audited (``booking_site.non_web_channel``) for the owner to
  set a web channel or disable the site.
- Grants that ended before today lose the User Permission rows mirrored from them (G-94),
  as the daily job at the site's midnight does from now on; each ended grant is audited once
  (``grant.expired``). The TEX scope ignores mirrored rows already.

Re-runnable; prints what it found.
"""

import frappe

from kamra.tex.security.capabilities import WEB_CHANNELS


def execute():
	from kamra.tex.security import grants
	from kamra.tex.security.audit import audit

	sites = [s for s in frappe.get_all("TEX Booking Site", fields=["name", "site_slug", "sales_channel", "enabled",
	                                                                "property", "hotel_group"], order_by="name asc")
	         if s.sales_channel and s.sales_channel not in WEB_CHANNELS]
	for s in sites:
		if frappe.db.exists("TEX Audit Event", {"action": "booking_site.non_web_channel", "reference_name": s.name}):
			continue
		audit("booking_site.non_web_channel", reference_doctype="TEX Booking Site", reference_name=s.name,
		      property=s.property or None, source="System",
		      new={"sales_channel": s.sales_channel, "enabled": s.enabled, "hotel_group": s.hotel_group},
		      reason="A booking site sells only on a web channel (ADR-050): this site sells nothing until a web "
		             "channel is set or it is disabled.")
	out = grants.remove_expired_grants()
	print(f"p31: {len(sites)} booking site(s) on a non-web channel sell nothing until fixed"
	      + (": " + ", ".join(f"{s.site_slug} ({s.sales_channel})" for s in sites) if sites else "")
	      + f"; mirrored rows of {len(out['grants'])} ended grant(s) removed for {len(out['users'])} user(s)")
