"""Guest change refunds made, named on the request (G-45 re-review 4, ADR-044).

``TEX Guest Change Request.refund_rows`` names every refund a guest change asked the gateway
for; what it refunded is counted from those that succeeded, never from a counter a refund run
increments. Requests made before the field existed are filled here from their refunds on
record: the gateway refunds whose reason names the request (every refund a guest change makes
is reasoned ``Guest change <request>: …``; their idempotency keys ``change:<request>:…`` are
stored hashed, so they cannot be matched by prefix) and the request's ``refund_in_flight`` and
``unknown_refund``. Refunds recorded as made outside TEX (Manual) are money staff gave back, not
the change's card refunds, and are left out. It can run again safely: a refund already named is
never named twice, and nothing else changes.
"""

import frappe

DT = "TEX Guest Change Request"
TXN = "TEX Payment Transaction"


def execute():
	frappe.reload_doc("tex_booking", "doctype", "tex_guest_change_request")
	for r in frappe.get_all(DT, fields=["name", "refund_rows", "refund_in_flight", "unknown_refund"]):
		named = [n for n in (r.refund_rows or "").split() if n]
		found = set(frappe.get_all(TXN, filters={"txn_type": "Refund", "provider": ("!=", "Manual"),
		                                         "reason": ("like", f"Guest change {r.name}: %")}, pluck="name"))
		for name in (r.refund_in_flight, r.unknown_refund):
			row = frappe.db.get_value(TXN, name, ["txn_type", "provider"], as_dict=True) if name else None
			if row and row.txn_type == "Refund" and row.provider != "Manual":
				found.add(name)
		new = [n for n in sorted(found) if n not in named]
		if new:
			frappe.db.set_value(DT, r.name, "refund_rows", "\n".join(named + new), update_modified=False)
