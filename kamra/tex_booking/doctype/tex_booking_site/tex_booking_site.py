# Copyright (c) 2026, TEX Engine contributors (derived from Kamra PMS, HeyKoala and contributors)
# For license information, please see license.txt

import re

import frappe
from frappe import _
from frappe.model.document import Document

HEX = re.compile(r"^#[0-9a-fA-F]{6}$")
ORIGIN = re.compile(r"^https://[a-z0-9.-]+(:\d+)?$")
DOMAIN = re.compile(r"^[a-z0-9.-]+\.[a-z]{2,}(/[a-z0-9._~-]+)*$")


class TEXBookingSite(Document):
	def validate(self):
		self.site_slug = re.sub(r"[^a-z0-9-]+", "-", (self.site_slug or "").lower()).strip("-")
		if not self.site_slug:
			frappe.throw(_("Slug is required."))
		if self.site_slug in ("pay", "api", "assets", "manage", "widget"):
			frappe.throw(_("{0} is reserved; choose another slug.").format(self.site_slug))
		if not self.property and not self.hotel_group:
			frappe.throw(_("A booking site serves a hotel or a hotel group."))
		for f in ("primary_color", "accent_color", "background_color"):
			if self.get(f) and not HEX.match(self.get(f)):
				frappe.throw(_("{0} must be a #RRGGBB colour.").format(self.meta.get_label(f)))
		origins = [o.strip().lower().rstrip("/") for o in (self.allowed_embed_origins or "").splitlines() if o.strip()]
		bad = [o for o in origins if not ORIGIN.match(o)]
		if bad:
			frappe.throw(_("Embed origins must be https origins: {0}").format(", ".join(bad)))
		self.allowed_embed_origins = "\n".join(origins)
		primaries = 0
		before = self.get_doc_before_save()
		verified_before = {(d.domain, d.verification_token) for d in (before.domains if before else []) if d.verified}
		for d in self.domains:
			d.domain = d.domain.strip().lower().removeprefix("https://").removeprefix("http://").rstrip("/")
			if not DOMAIN.match(d.domain):
				frappe.throw(_("Invalid domain {0}").format(d.domain))
			if not d.verification_token:
				d.verification_token = frappe.generate_hash(length=24)
			# "verified" is set only by the DNS check (kamra.tex.services.sites), never by an edit
			if d.verified and (d.domain, d.verification_token) not in verified_before \
					and not self.flags.tex_domain_verified:
				d.verified = 0
			taken = frappe.db.get_value("TEX Booking Domain", {"domain": d.domain, "parent": ("!=", self.name)},
			                            "parent")
			if taken:
				frappe.throw(_("{0} is already used by booking site {1}.").format(d.domain, taken))
			primaries += int(d.is_primary or 0)
		if primaries > 1:
			frappe.throw(_("Only one primary domain."))
		if self.custom_texts:
			try:
				data = frappe.parse_json(self.custom_texts)
				assert isinstance(data, dict)
			except Exception:
				frappe.throw(_("Custom texts must be a JSON object keyed by language."))
