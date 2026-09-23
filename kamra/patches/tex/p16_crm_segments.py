"""CRM segments per tenant (G-23): segments are named per enterprise (no longer one global
namespace), presets are seeded (they never were on upgraded sites), and each existing
custom segment is given to its enterprise when the site has exactly one. A money
condition saved without a currency is left as is: it matches nobody until someone picks
the currency in the editor (money is never compared across currencies)."""

import json

import frappe

from kamra.tex.crm import segments as seg


def execute():
	frappe.reload_doc("tex_crm", "doctype", "tex_guest_segment")
	from kamra.tex.crm.service import ensure_system_segments
	from kamra.tex.setup import ensure_indexes

	ensure_system_segments()
	ents = frappe.get_all("TEX Enterprise", pluck="name")
	for s in frappe.get_all("TEX Guest Segment", filters={"system_key": ("is", "not set")},
	                        fields=["name", "segment_name", "enterprise", "rules_json"]):
		if not s.enterprise and len(ents) == 1:
			frappe.db.set_value("TEX Guest Segment", s.name, "enterprise", ents[0], update_modified=False)
		elif not s.enterprise:
			print(f"p16: segment {s.segment_name!r} has no enterprise; only platform admins see it until one is set")
		try:
			rules = json.loads(s.rules_json or "{}")
			if any(seg.FIELDS.get(c.get("field")) == "money" and not c.get("currency")
			       for c in rules.get("conditions") or []):
				print(f"p16: segment {s.segment_name!r} compares money without a currency; it matches nobody "
				      "until a currency is chosen")
		except ValueError:
			print(f"p16: segment {s.segment_name!r} has unreadable rules")
	ensure_indexes()
