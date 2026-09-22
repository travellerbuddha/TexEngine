"""Helpers for the Rates & Contracts and Inventory screens (UI workstream A).

* ``lookups`` — the pickers every commercial editor needs for one hotel (room types,
  rate plans, contracts, cancellation / payment policies). Read-only.
* ``archive_record`` — archive a live selling-policy revision *with the reason* in the
  audit trail (``policies.archive`` takes no reason).

Every call re-checks TEX capabilities on the server; the UI only hides actions.
"""

from __future__ import annotations

import frappe
from frappe import _

from kamra.tex.api._util import text
from kamra.tex.api.policies import POLICY, _audit_prop, _check, _prop_of
from kamra.tex.commercial import revisions
from kamra.tex.security import scope
from kamra.tex.security.audit import audit


@frappe.whitelist()
def lookups(property: str):
	"""Room types, rate plans, contracts and linked policies of one hotel."""
	scope.require("price.view", property)
	return {
		"room_types": frappe.get_all(
			"Room Type", filters={"property": property, "disabled": 0},
			fields=["name", "room_type_name", "adults_capacity", "children_capacity", "max_total_occupants",
			        "base_occupancy"], order_by="room_type_name asc"),
		"rate_plans": frappe.get_all(
			"Rate Plan", filters={"property": property, "disabled": 0},
			fields=["name", "rate_plan_name", "code", "tex_refundable"], order_by="rate_plan_name asc"),
		"contracts": frappe.get_all(
			"TEX Contract", filters={"property": property},
			fields=["name", "contract_code", "contract_name", "market", "status", "active_version",
			        "contract_currency", "pricing_basis"], order_by="contract_code asc"),
		"cancellation_policies": frappe.get_all(
			"TEX Cancellation Policy", filters={"property": ("in", [property, ""])},
			fields=["name", "policy_name", "refundable"], order_by="policy_name asc"),
		"payment_policies": frappe.get_all(
			"TEX Payment Policy", filters={"property": ("in", [property, ""])},
			fields=["name", "policy_name", "deposit_type"], order_by="policy_name asc"),
	}


@frappe.whitelist(methods=["POST"])
def archive_record(doctype: str, name: str, reason: str):
	"""Archive a selling-policy revision; the reason is stored in the audit event."""
	reason = text(reason, 500)
	if not reason or len(reason) < 3:
		frappe.throw(_("A reason is required."))
	if doctype not in revisions.REVISIONED or doctype not in POLICY:
		frappe.throw(_("{0} has no revisions.").format(doctype))
	doc = frappe.get_doc(doctype, name)
	# same authority as policies.archive: the doctype's edit capability at the record's hotel
	_check(doctype, _prop_of(doctype, doc), write=True)
	revisions.archive(doctype, name)
	audit(f"{doctype.lower().replace(' ', '_')}.archive", reference_doctype=doctype, reference_name=name,
	      property=_audit_prop(doctype, doc), reason=reason)
	return {"ok": True}
