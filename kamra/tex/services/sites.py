"""Booking-site custom domains (R-31): ownership is proven with a DNS TXT record
``_tex-verify.<domain>`` holding the row's verification token, resolved over
DNS-over-HTTPS so no extra resolver dependency is needed."""

from __future__ import annotations

import frappe
import requests
from frappe import _

from kamra.tex.security import scope
from kamra.tex.security.audit import audit

DOH = "https://cloudflare-dns.com/dns-query"


def txt_records(name: str) -> list[str]:
	r = requests.get(DOH, params={"name": name, "type": "TXT"}, headers={"accept": "application/dns-json"},
	                 timeout=10)
	r.raise_for_status()
	return [a.get("data", "").strip('"') for a in r.json().get("Answer") or [] if a.get("type") == 16]


def site_properties(site) -> list[str]:
	if site.property:
		return [site.property]
	return sorted(frappe.get_all("Property", filters={"tex_hotel_group": site.hotel_group}, pluck="name"))


def require_site(site_name: str, cap: str = "booking_site.edit"):
	site = frappe.get_doc("TEX Booking Site", site_name)
	props = site_properties(site)
	if not props and not scope.is_platform_admin():
		frappe.throw(_("Not permitted."), frappe.PermissionError)
	for p in props:
		scope.require(cap, p)
	return site


def verify_domain(site_name: str, domain: str) -> dict:
	site = require_site(site_name)
	row = next((d for d in site.domains if d.domain == (domain or "").strip().lower()), None)
	if not row:
		frappe.throw(_("Domain not found on this site."))
	record = f"_tex-verify.{row.domain}"
	try:
		values = txt_records(record)
	except requests.RequestException:
		frappe.throw(_("DNS lookup failed, please try again later."))
	ok = row.verification_token in values
	if ok and not row.verified:
		row.verified = 1
		site.flags.tex_domain_verified = True
		site.save(ignore_permissions=True)
		frappe.clear_document_cache("TEX Booking Site", site.name)
		audit("booking_site.domain_verified", reference_doctype="TEX Booking Site", reference_name=site.name,
		      property=site.property, new={"domain": row.domain})
	return {"domain": row.domain, "verified": bool(row.verified), "record": record, "expected": row.verification_token,
	        "found": values[:5]}
