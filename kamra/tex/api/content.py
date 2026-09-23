"""Guest-facing content translations (R-49): room, rate plan, extra, policy and hotel
texts in the booking languages. Needs ``booking_site.edit`` at the hotel."""

from __future__ import annotations

import frappe
from frappe import _

from kamra.tex.api._util import parse, text
from kamra.tex.security import scope
from kamra.tex.security.audit import audit
from kamra.tex.services import content


@frappe.whitelist()
def items(property: str):
	property = text(property, 140)
	scope.require("booking_site.edit", property)
	return {"languages": list(content.LANGS), "fields": {k: list(v) for k, v in content.FIELDS.items()},
	        "items": content.items(property)}


@frappe.whitelist(methods=["POST"])
def save(property: str, rows):
	property = text(property, 140)
	scope.require("booking_site.edit", property)
	rows = parse(rows, []) or []
	if not isinstance(rows, list) or len(rows) > 2000:
		frappe.throw(_("Too many changes at once."))
	out = content.save(property, rows)
	audit("content.translations_saved", reference_doctype="Property", reference_name=property, property=property,
	      new=out)
	return out
