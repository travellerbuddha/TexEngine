"""Booking-site custom domains (R-31, ADR-035).

A custom domain is a hostname (``book.hotel.com``) pointed at the TEX platform. Its owner
proves control with a DNS TXT record ``_tex-verify.<host>`` holding the row's verification
token, resolved over DNS-over-HTTPS (no extra resolver dependency). A verified host serves
that one booking site (``kamra.tex.booking_host``), the public API on it answers for that
site only, and the guest links TEX builds (e-mails, payment links, return pages) use the
site's primary verified host. Verified domains are checked again every day; a record that
stays missing un-verifies the domain. Platform links never trust the request's Host header.
"""

from __future__ import annotations

import re

import frappe
import requests
from frappe import _
from frappe.utils import get_url, now_datetime

from kamra.tex.security import scope
from kamra.tex.security.audit import audit

DOH = "https://cloudflare-dns.com/dns-query"
HOST = re.compile(r"^(?=.{4,253}$)([a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}$")
UNVERIFY_AFTER = 3          # consecutive daily checks without the record
HOSTS_CACHE = "tex:booking_hosts"


class DnsLookupFailed(Exception):
	"""The resolver could not answer (not the same as "the record is missing")."""


def normalize_host(value: str | None) -> str:
	return (value or "").strip().lower().removeprefix("https://").removeprefix("http://").rstrip("/").rstrip(".")


def txt_records(name: str) -> list[str]:
	try:
		r = requests.get(DOH, params={"name": name, "type": "TXT"}, headers={"accept": "application/dns-json"},
		                 timeout=10)
		r.raise_for_status()
		data = r.json()
	except (requests.RequestException, ValueError) as e:
		raise DnsLookupFailed(str(e)) from e
	status = data.get("Status")
	if status == 3:                       # NXDOMAIN: the name has no records at all
		return []
	if status != 0:
		raise DnsLookupFailed(f"DNS status {status}")
	# a long TXT value arrives as several quoted strings: join them
	return ["".join(re.findall(r'"([^"]*)"', a.get("data", ""))) or a.get("data", "").strip('"')
	        for a in data.get("Answer") or [] if a.get("type") == 16]


def record_name(host: str) -> str:
	return f"_tex-verify.{host}"


# ─── serving ─────────────────────────────────────────────────────────────


def host_map() -> dict[str, str]:
	"""Verified host → site slug, for enabled sites (cached; cleared on every site change)."""
	cached = frappe.cache.get_value(HOSTS_CACHE)
	if cached is not None:
		return cached
	rows = frappe.db.sql(
		"""SELECT d.domain, s.site_slug FROM `tabTEX Booking Domain` d
		   JOIN `tabTEX Booking Site` s ON s.name = d.parent
		   WHERE d.parenttype = 'TEX Booking Site' AND d.verified = 1 AND s.enabled = 1""", as_dict=True)
	out = {r.domain: r.site_slug for r in rows}
	frappe.cache.set_value(HOSTS_CACHE, out, expires_in_sec=3600)
	return out


def clear_host_cache(*_args, **_kwargs) -> None:
	frappe.cache.delete_value(HOSTS_CACHE)


def request_host() -> str | None:
	req = getattr(frappe.local, "request", None)
	host = getattr(req, "host", None) if req else None
	return normalize_host(host.rsplit(":", 1)[0] if host and not host.endswith("]") else host) if host else None


def pinned_slug() -> str | None:
	"""The booking site this request's custom host serves, or None on the platform host."""
	host = request_host()
	return host_map().get(host) if host else None


def platform_url(uri: str = "") -> str:
	"""A URL on the TEX platform host: ``host_name`` from the site config, else the site
	name — never the request's Host header (links in e-mails and gateway callbacks)."""
	return get_url(uri or None, allow_header_override=False)


def site_for(property: str | None, booking_site: str | None = None) -> str | None:
	"""The booking site that sells for a hotel: the booking's own, else the hotel's, else its group's."""
	if booking_site and frappe.db.exists("TEX Booking Site", booking_site):
		return booking_site
	if not property:
		return None
	name = frappe.db.get_value("TEX Booking Site", {"property": property, "enabled": 1})
	if name:
		return name
	group = frappe.db.get_value("Property", property, "tex_hotel_group")
	return frappe.db.get_value("TEX Booking Site", {"hotel_group": group, "enabled": 1}) if group else None


def primary_host(site) -> str | None:
	"""The host guest links use: the verified primary domain, else the first verified one."""
	site = frappe.get_cached_doc("TEX Booking Site", site) if isinstance(site, str) else site
	if not site or not site.enabled:
		return None
	verified = [d for d in site.domains or [] if d.verified]
	best = next((d for d in verified if d.is_primary), verified[0] if verified else None)
	return best.domain if best else None


def guest_url(site, path: str = "", *, site_scoped: bool = True) -> str:
	"""Where a guest opens ``path`` of a booking site: ``https://<host>/<path>`` on its custom
	domain, else ``/book/<slug>/<path>`` (``/book/<path>`` for site-less pages such as
	payment links) on the platform."""
	path = path.lstrip("/")
	doc = frappe.get_cached_doc("TEX Booking Site", site) if isinstance(site, str) else site
	host = primary_host(doc) if doc else None
	if host:
		return f"https://{host}/{path}"
	if doc and site_scoped:
		return platform_url(f"/book/{doc.site_slug}/{path}".rstrip("/"))
	return platform_url(f"/book/{path}".rstrip("/"))


def return_hosts(sites: list[str]) -> set[str]:
	"""Hosts a payment may return to: the platform and the verified domains of these (enabled) sites."""
	from urllib.parse import urlparse

	hosts = {urlparse(platform_url()).hostname}
	enabled = frappe.get_all("TEX Booking Site", filters={"name": ("in", sites or ["__none__"]), "enabled": 1},
	                         pluck="name")
	if enabled:
		hosts |= set(frappe.get_all("TEX Booking Domain", filters={"parent": ("in", enabled), "verified": 1,
		                                                           "parenttype": "TEX Booking Site"}, pluck="domain"))
	return hosts


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


def _verified_elsewhere(host: str, site_name: str) -> str | None:
	return frappe.db.get_value("TEX Booking Domain", {"domain": host, "verified": 1, "parent": ("!=", site_name),
	                                                  "parenttype": "TEX Booking Site"}, "parent")


def verify_domain(site_name: str, domain: str) -> dict:
	site = require_site(site_name)
	host = normalize_host(domain)
	row = next((d for d in site.domains if d.domain == host), None)
	if not row:
		frappe.throw(_("Domain not found on this site."))
	record = record_name(row.domain)
	try:
		values = txt_records(record)
	except DnsLookupFailed:
		frappe.throw(_("DNS lookup failed, please try again later."))
	ok = row.verification_token in values
	other = _verified_elsewhere(row.domain, site.name) if ok else None
	if other:
		frappe.throw(_("{0} is already verified for another booking site.").format(row.domain))
	now = now_datetime()
	row.last_checked_at = now
	if ok:
		if not row.verified:
			row.verified_at = now
		row.verified = 1
		row.check_failures = 0
	site.flags.tex_domain_verified = True
	site.save(ignore_permissions=True)
	frappe.clear_document_cache("TEX Booking Site", site.name)
	clear_host_cache()
	if ok:
		audit("booking_site.domain_verified", reference_doctype="TEX Booking Site", reference_name=site.name,
		      property=site.property, new={"domain": row.domain})
	return {"domain": row.domain, "verified": bool(row.verified), "record": record, "expected": row.verification_token,
	        "found": values[:5]}


def recheck_domains() -> list[dict]:
	"""Daily: every verified domain must still carry its record. A record missing on
	``UNVERIFY_AFTER`` consecutive checks un-verifies the domain; a resolver failure does not
	count against it."""
	changes = []
	for r in frappe.get_all("TEX Booking Domain", filters={"verified": 1, "parenttype": "TEX Booking Site"},
	                        fields=["name", "parent", "domain", "verification_token", "check_failures"]):
		try:
			present = r.verification_token in txt_records(record_name(r.domain))
		except DnsLookupFailed:
			continue
		failures = 0 if present else int(r.check_failures or 0) + 1
		values = {"last_checked_at": now_datetime(), "check_failures": failures}
		if failures >= UNVERIFY_AFTER:
			values["verified"] = 0
		frappe.db.set_value("TEX Booking Domain", r.name, values, update_modified=False)
		if failures >= UNVERIFY_AFTER:
			prop = frappe.db.get_value("TEX Booking Site", r.parent, "property")
			audit("booking_site.domain_unverified", reference_doctype="TEX Booking Site", reference_name=r.parent,
			      property=prop, old={"domain": r.domain}, reason=f"TXT record missing on {failures} daily checks")
			changes.append({"site": r.parent, "domain": r.domain})
			frappe.clear_document_cache("TEX Booking Site", r.parent)
	clear_host_cache()
	return changes
