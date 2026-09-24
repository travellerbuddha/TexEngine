# Copyright (c) 2026, TEX Engine contributors (derived from Kamra PMS, HeyKoala and contributors)
# For license information, please see license.txt

import re

import frappe
from frappe import _
from frappe.model.document import Document

from kamra.tex.security.capabilities import WEB_CHANNELS
from kamra.tex.security.filetypes import safe_image_url
from kamra.tex.services import sites

HEX = re.compile(r"^#[0-9a-fA-F]{6}$")
ORIGIN = re.compile(r"^https://[a-z0-9.-]+(:\d+)?$")


class TEXBookingSite(Document):
	def validate(self):
		self.site_slug = re.sub(r"[^a-z0-9-]+", "-", (self.site_slug or "").lower()).strip("-")
		if not self.site_slug:
			frappe.throw(_("Slug is required."))
		if self.site_slug in ("pay", "api", "assets", "manage", "widget"):
			frappe.throw(_("{0} is reserved; choose another slug.").format(self.site_slug))
		if not self.property and not self.hotel_group:
			frappe.throw(_("A booking site serves a hotel or a hotel group."))
		# a booking site is the public Booking Engine: anyone may book there, so it sells only on a
		# web channel; B2B, OTA, API and call-centre prices are sold by entitled staff and connections
		# (ADR-050 review)
		if self.sales_channel and self.sales_channel not in WEB_CHANNELS:
			frappe.throw(_("A booking site sells on a web channel ({0}), not on {1}.").format(
				", ".join(sorted(WEB_CHANNELS)), self.sales_channel))
		for f in ("primary_color", "accent_color", "background_color"):
			if self.get(f) and not HEX.match(self.get(f)):
				frappe.throw(_("{0} must be a #RRGGBB colour.").format(self.meta.get_label(f)))
		for f in ("logo", "hero_image"):
			# guests' pages show these: a PNG/JPEG/GIF/WebP in the public files or an https address on
			# another host; never script, markup (SVG, HTML), another path of the platform or another
			# scheme (G-83). Only a changed value is judged: a site saved with an older image stays
			# savable (a domain check saves the site as it is); patch p24 lists those sites
			if self.get(f) and (self.is_new() or self.has_value_changed(f)) and not safe_image_url(
					self.get(f), sites.own_hosts()):
				frappe.throw(_("{0} must be an uploaded PNG, JPEG, GIF or WebP image or an https:// address on "
				               "another site.").format(self.meta.get_label(f)))
		origins = [o.strip().lower().rstrip("/") for o in (self.allowed_embed_origins or "").splitlines() if o.strip()]
		bad = [o for o in origins if not ORIGIN.match(o)]
		if bad:
			frappe.throw(_("Embed origins must be https origins: {0}").format(", ".join(bad)))
		self.allowed_embed_origins = "\n".join(origins)
		self._validate_domains()
		if self.custom_texts:
			try:
				data = frappe.parse_json(self.custom_texts)
				assert isinstance(data, dict)
			except Exception:
				frappe.throw(_("Custom texts must be a JSON object keyed by language."))

	def _validate_domains(self):
		"""Custom domains are hostnames (ADR-035). Whether one is verified, when, and how its
		daily checks went are written only by the DNS check (kamra.tex.services.sites): an
		edit — including the admin UI, which sends the rows back — never sets them."""
		before = self.get_doc_before_save()
		kept = {(d.domain, d.verification_token): d for d in (before.domains if before else [])}
		seen, primaries = set(), 0
		for d in self.domains:
			d.domain = sites.normalize_host(d.domain)
			if not sites.HOST.match(d.domain):
				frappe.throw(_("{0} is not a host name. Use a host such as book.yourhotel.com (no path): "
				               "point it at TEX and verify it.").format(d.domain or "—"))
			if d.domain in seen:
				frappe.throw(_("{0} is listed twice.").format(d.domain))
			seen.add(d.domain)
			if not d.verification_token:
				d.verification_token = frappe.generate_hash(length=24)
			old = kept.get((d.domain, d.verification_token))
			if not self.flags.tex_domain_verified:
				for f in ("verified", "verified_at", "last_checked_at", "check_failures"):
					d.set(f, old.get(f) if old else (0 if f in ("verified", "check_failures") else None))
			# several sites may claim a host while unverified; only one can hold it verified
			if d.verified:
				taken = frappe.db.get_value("TEX Booking Domain", {"domain": d.domain, "verified": 1,
				                                                   "parent": ("!=", self.name),
				                                                   "parenttype": "TEX Booking Site"}, "parent")
				if taken:
					frappe.throw(_("{0} is already verified for booking site {1}.").format(d.domain, taken))
			primaries += int(d.is_primary or 0)
		if primaries > 1:
			frappe.throw(_("Only one primary domain."))

	def on_update(self):
		sites.clear_host_cache()

	def on_trash(self):
		sites.clear_host_cache()
