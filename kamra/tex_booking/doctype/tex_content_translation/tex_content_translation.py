# Copyright (c) 2026, TEX Engine contributors (derived from Kamra PMS, HeyKoala and contributors)
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document


class TEXContentTranslation(Document):
	def validate(self):
		from kamra.tex.services import content

		if self.field not in content.FIELDS.get(self.ref_doctype, ()):
			frappe.throw(_("{0} has no translatable field {1}.").format(self.ref_doctype, self.field))
		owner = content.record_property(self.ref_doctype, self.ref_name)
		if owner != self.property:
			frappe.throw(_("{0} {1} does not belong to this hotel.").format(self.ref_doctype, self.ref_name))
		self.text = (self.text or "").strip()
		dup = frappe.db.exists("TEX Content Translation", {
			"ref_doctype": self.ref_doctype, "ref_name": self.ref_name, "field": self.field,
			"language": self.language, "name": ("!=", self.name)})
		if dup:
			frappe.throw(_("A translation for this text and language already exists."))

	def on_change(self):
		from kamra.tex.services import content

		content.clear_cache(self.property)

	def on_trash(self):
		from kamra.tex.services import content

		content.clear_cache(self.property)
