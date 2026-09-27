"""Helpers for the Rates & Contracts and Inventory screens (UI workstream A).

* ``lookups`` — the pickers every commercial editor needs for one hotel (room types,
  rate plans, contracts, cancellation / payment policies). Read-only.
* ``archive_record`` — archive a live selling-policy revision *with the reason* in the
  audit trail (thin alias of ``policies.archive``).

Every call re-checks TEX capabilities on the server; the UI only hides actions.
"""

from __future__ import annotations

import frappe

from kamra.tex.security import scope


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
			# the default cancellation policy: a contract's rate plan row without its own uses it (O-2b)
			fields=["name", "rate_plan_name", "code", "tex_refundable", "tex_cancellation_policy"],
			order_by="rate_plan_name asc"),
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
	"""Archive a selling-policy revision with a reason (same checks as policies.archive)."""
	from kamra.tex.api import policies

	return policies.archive(doctype, name, reason)
