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
# the booking engine's own paths under /book
RESERVED_SLUGS = ("pay", "api", "assets", "manage", "widget")
# the admin area's own pages under /tex/booking-engine (G-64 review M3): a new site (named after its
# slug) or a site moved to another slug may not take one; sites named so before keep their name and
# slug, and patch p47 reports them
ADMIN_SLUGS = ("new", "sites", "content", "rooms", "analytics")
# the analytics ids the booking engine loads, with the engine's own patterns (booking/lib/analyticsIds.ts,
# G-62): a value is trimmed, then must match. ASCII only, as in the browser
ANALYTICS_IDS = {
	"ga4_measurement_id": (re.compile(r"G-[A-Z0-9]{4,20}", re.ASCII), "G-XXXXXXXXXX"),
	"gtm_container_id": (re.compile(r"GTM-[A-Z0-9]{4,12}", re.ASCII), "GTM-XXXXXXX"),
	"meta_pixel_id": (re.compile(r"[0-9]{6,20}", re.ASCII), "123456789012345"),
}


class TEXBookingSite(Document):
	def validate(self):
		self.site_slug = re.sub(r"[^a-z0-9-]+", "-", (self.site_slug or "").lower()).strip("-")
		if not self.site_slug:
			frappe.throw(_("Slug is required."))
		if self.site_slug in RESERVED_SLUGS or (
				self.site_slug in ADMIN_SLUGS and (self.is_new() or self.has_value_changed("site_slug"))):
			frappe.throw(_("{0} is reserved; choose another slug.").format(self.site_slug))
		if not self.property and not self.hotel_group:
			frappe.throw(_("A booking site serves a hotel or a hotel group."))
		# a booking site is the public Booking Engine: anyone may book there, so it sells only on a
		# web channel; B2B, OTA, API and call-centre prices are sold by entitled staff and connections
		# (ADR-050 review)
		if self.sales_channel and self.sales_channel not in WEB_CHANNELS:
			frappe.throw(_("A booking site sells on a web channel ({0}), not on {1}.").format(
				", ".join(sorted(WEB_CHANNELS)), self.sales_channel))
		self._validate_markets()
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
		for f, (pattern, example) in ANALYTICS_IDS.items():
			# only a new or changed id is judged: the engine ignores an older invalid one, and it must
			# not make the site unsavable (a domain check saves the site as it is)
			if not (self.is_new() or self.has_value_changed(f)):
				continue
			value = (self.get(f) or "").strip()
			self.set(f, value)
			if value and not pattern.fullmatch(value):
				frappe.throw(_("{0} is not valid: it looks like {1}.").format(self.meta.get_label(f), example))
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

	def _validate_markets(self):
		"""The markets a link may choose on this site (O-8, ADR-070); blank: every enabled market. Judged only when
		the list or the default market changes: a market disabled later must not make the site unsavable (a domain
		check saves the site as it is), and a disabled market is not sold anyway (``versions.resolve_market``)."""
		codes = list(dict.fromkeys(c.strip().upper() for c in (self.allowed_markets or "").replace("\n", ",").split(",")
		                           if c.strip()))
		self.allowed_markets = ", ".join(codes) or None
		changed = self.is_new() or self.has_value_changed("allowed_markets") or self.has_value_changed("default_market")
		if changed and self.default_market and frappe.db.get_value("TEX Market", self.default_market, "residency_required"):
			# allowed (a domestic site), but said: a guest whose country no other market of the site takes is priced
			# on it, and only its residents can book those prices
			frappe.msgprint(_("The default market {0} is for residents only: guests from elsewhere see its prices but "
			                  "cannot book them unless a link or their country picks another market of this site. A "
			                  "market for everyone (such as GLOBAL) is the usual default.").format(self.default_market),
			                indicator="orange", alert=True)
		if not codes or not changed:
			return
		enabled = set(frappe.get_all("TEX Market", filters={"name": ("in", codes), "disabled": 0}, pluck="name"))
		bad = [c for c in codes if c not in enabled]
		if bad:
			frappe.throw(_("Markets this site sells: {0} is not an enabled market.").format(", ".join(bad)))
		if self.default_market and self.default_market not in codes:
			frappe.throw(_("The default market {0} must be one of the markets this site sells.").format(
				self.default_market))

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
