# Copyright (c) 2026, TEX Engine contributors (derived from Kamra PMS, HeyKoala and contributors)
# For license information, please see license.txt

import json
import re

import frappe
from frappe import _
from frappe.model.document import Document

SECRETISH = re.compile(r"(secret|password|token|api[_-]?key|private)", re.IGNORECASE)


class TEXIntegrationConnection(Document):
	"""A connection is checked whoever saves it (G-69): its adapter is installed for its
	category, an uncertified adapter never runs in Production, endpoints are https, and
	secrets live in the encrypted fields, never in the settings."""

	def validate(self):
		from kamra.tex.connect import adapters as pms
		from kamra.tex.distribution import adapters as channels

		registry = {"PMS": pms.REGISTRY, "Channel Manager": channels.REGISTRY}.get(self.category)
		if registry is not None:
			cls = registry.get(self.adapter)
			if cls is None:
				frappe.throw(_("No {0} adapter '{1}' is installed. Available: {2}").format(
					self.category, self.adapter, ", ".join(sorted(registry)) or "—"))
			if self.environment == "Production" and not getattr(cls, "certified", False):
				frappe.throw(_("{0} is not certified for production: use the Sandbox environment.").format(
					getattr(cls, "label", self.adapter)))
		if self.category == "Channel Manager" and not self.property:
			frappe.throw(_("A channel connection belongs to one hotel."))
		if self.endpoint_url and not self.endpoint_url.startswith("https://"):
			frappe.throw(_("The endpoint must be an https:// address."))
		if self.settings_json:
			try:
				data = json.loads(self.settings_json)
				assert isinstance(data, dict)
			except (ValueError, AssertionError):
				frappe.throw(_("Settings must be a JSON object."))
			bad = [k for k in data if SECRETISH.search(str(k))]
			if bad:
				frappe.throw(_("Put secrets in the encrypted fields, not in the settings: {0}").format(", ".join(bad)))
		before = self.get_doc_before_save()
		if before and before.property != self.property and frappe.db.exists(
				"TEX Channel Mapping", {"connection": self.name}):
			frappe.throw(_("This connection has room mappings: it cannot move to another hotel."))

	def on_trash(self):
		for dt in ("TEX Channel Mapping", "TEX Channel Inbound", "TEX Integration Outbox"):
			if frappe.db.exists(dt, {"connection": self.name}):
				frappe.throw(_("This connection has {0} records: disable it instead.").format(dt))
