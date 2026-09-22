"""Back-office CRM screen helpers (UI workstream D).

Only what the CRM / Payments screens need and ``kamra.tex.api.crm`` /
``kamra.tex.api.payments`` do not expose. Read-only; every call is capability
checked and scoped to the hotels the user may see the guest through.
"""

from __future__ import annotations

import frappe

from kamra.tex.crm import loyalty
from kamra.tex.crm import service as crm
from kamra.tex.security import scope


@frappe.whitelist()
def loyalty_programs(guest: str):
	"""Loyalty programs a guest can collect in, through the hotels the user may see
	them at. Lets staff adjust points before the guest's first ledger entry (the
	ledger summary only lists programs the guest already has entries in)."""
	scope.require("crm.view", None)
	via = crm.require_guest(guest)
	out: dict[str, dict] = {}
	for prop in sorted(via):
		scope.require("crm.view", prop)
		name = loyalty.program_for(prop)
		if not name or name in out:
			continue
		prog = frappe.get_cached_doc("TEX Loyalty Program", name)
		out[name] = {
			"program": name,
			"program_name": prog.program_name,
			"currency": prog.currency,
			"property": prop,
			"min_redeem_points": int(prog.min_redeem_points or 0),
			"max_redeem_percent": str(prog.max_redeem_percent or 100),
		}
	return list(out.values())
