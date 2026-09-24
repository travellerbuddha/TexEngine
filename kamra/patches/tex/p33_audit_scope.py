"""G-74 (ADR-053): an audit event of a hotel group or an enterprise is seen at the hotels it reached.

Grant events of a hotel-group or enterprise grant were recorded without a hotel, so only
platform administrators saw them. Each such event now names its group / enterprise and gets a
``TEX Audit Scope`` row per hotel it reaches. Events written before this patch are given the
hotels their group / enterprise has now (the membership when they happened was not recorded):
the recorded old / new values are not changed. A hotel grant's event keeps its hotel.

Re-runnable; prints what it did.
"""

import json

import frappe


def _values(raw: str | None) -> dict | None:
	try:
		v = json.loads(raw) if raw else None
	except ValueError:
		return None
	return frappe._dict(v) if isinstance(v, dict) else None


def execute():
	from kamra.tex.security import grants

	if not frappe.db.table_exists("TEX Audit Scope"):
		return
	rows = frappe.get_all("TEX Audit Event", filters={"reference_doctype": "TEX Access Grant"},
	                      fields=["name", "property", "hotel_group", "enterprise", "old_value", "new_value",
	                              "creation", "owner"], order_by="creation asc")
	done = 0
	for r in rows:
		if r.hotel_group or r.enterprise or frappe.db.exists("TEX Audit Scope", {"event": r.name}):
			continue
		versions = [v for v in (_values(r.old_value), _values(r.new_value)) if v]
		if not versions:
			continue
		if all(v.get("scope_level") in (None, "Hotel", "Platform") for v in versions) \
				and len({v.get("property") for v in versions}) <= 1:
			continue                                   # a hotel's own grant, or a platform grant
		where = grants.grant_scope(*versions)
		frappe.db.set_value("TEX Audit Event", r.name, {"hotel_group": where["hotel_group"],
		                                                "enterprise": where["enterprise"]}, update_modified=False)
		reached = sorted(set(where["hotels"]) - {r.property})
		if reached:
			frappe.db.bulk_insert(
				"TEX Audit Scope", fields=["name", "creation", "modified", "owner", "modified_by", "event", "property"],
				values=[(frappe.generate_hash(length=12), r.creation, r.creation, r.owner, r.owner, r.name, h)
				        for h in reached])
		done += 1
	print(f"p33: {done} group / enterprise grant event(s) given their hotels")
