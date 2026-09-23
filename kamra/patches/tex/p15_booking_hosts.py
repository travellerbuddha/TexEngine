"""Custom booking domains are host names (G-21, ADR-035). A domain saved with a path
("hotel.com/book") can never be served by TEX: it is un-verified so no guest link points at
it, and the hotel is asked to replace it with a host such as book.hotel.com. Verified hosts
get the time they were verified (the site's last change: the best evidence available)."""

import frappe

from kamra.tex.services import sites


def execute():
	frappe.reload_doc("tex_booking", "doctype", "tex_booking_domain")
	for r in frappe.get_all("TEX Booking Domain", filters={"parenttype": "TEX Booking Site"},
	                        fields=["name", "parent", "domain", "verified", "verified_at"]):
		host = sites.normalize_host(r.domain)
		if not sites.HOST.match(host):
			if r.verified:
				frappe.db.set_value("TEX Booking Domain", r.name, "verified", 0, update_modified=False)
				print(f"p15: {r.parent}: {r.domain} is not a host name; un-verified, replace it with a host")
			continue
		values = {}
		if host != r.domain:
			values["domain"] = host
		if r.verified and not r.verified_at:
			values["verified_at"] = frappe.db.get_value("TEX Booking Site", r.parent, "modified")
		if values:
			frappe.db.set_value("TEX Booking Domain", r.name, values, update_modified=False)
	frappe.db.sql("UPDATE `tabTEX Booking Domain` SET check_failures=0 WHERE check_failures IS NULL")
	sites.clear_host_cache()
