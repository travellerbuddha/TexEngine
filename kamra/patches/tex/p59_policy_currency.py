"""Y-3 A (ADR-067, D-1): a payment or cancellation policy's fixed amounts have a currency.

``TEX Payment Policy.currency`` and ``TEX Cancellation Policy.currency``: the currency of the
policy's fixed amounts (a FIXED deposit, penalty or no-show). Empty is the contract's currency, as
every policy was read before, so nothing is filled in: only the DocTypes are synced and no row
changes. A publish freezes the currency with a policy that has a fixed amount.

Reported for the owner, never changed (audited once; again only when what is reported changed, G-76):

* ``policy.fixed_currency_ambiguous``: a fixed policy without a currency used by contracts in two or
  more currencies. Each contract reads its fixed amounts in its own currency, which may not be what
  was meant: give the policy a currency, or one policy per currency.
* ``reservation.fixed_policy_currency``: a live or future stay with a fixed deposit or fee, sold in
  another currency than its contract's. It keeps the terms it was sold on (its snapshot); staff
  should know its fixed amount was read in the sale's currency.
"""

import json

import frappe
from frappe.utils import nowdate

from kamra.tex.pricing import policy_money
from kamra.tex.security.audit import audit, recorded

# a stay still to be settled: sold (or held for its payment) and not over
LIVE = ("Held", "Pending Payment", "Confirmed", "Checked In")


def execute():
	frappe.reload_doc("tex_commercial", "doctype", "tex_payment_policy")
	frappe.reload_doc("tex_commercial", "doctype", "tex_cancellation_policy")
	policies = _ambiguous_policies()
	stays = _stays_sold_in_another_currency()
	print(f"p59: {len(policies)} fixed polic(ies) without a currency used by contracts in several currencies"
	      + (": " + ", ".join(name for _dt, name, _new, _prop in policies) if policies else "")
	      + f"; {len(stays)} live or future stay(s) with a fixed deposit or fee sold in another currency")


def _fixed_policies() -> dict[tuple[str, str], str | None]:
	"""(doctype, name) → hotel of every policy with a fixed amount and no currency."""
	out = {}
	for p in frappe.get_all("TEX Payment Policy", filters={"deposit_type": "FIXED"},
	                        fields=["name", "currency", "property"], order_by="name asc"):
		if not p.currency:
			out[("TEX Payment Policy", p.name)] = p.property
	fixed_rules = set(frappe.get_all("TEX Cancellation Rule", filters={"parenttype": "TEX Cancellation Policy",
	                                                                    "penalty_type": "FIXED"}, pluck="parent"))
	for p in frappe.get_all("TEX Cancellation Policy", fields=["name", "currency", "property", "no_show_type"],
	                        order_by="name asc"):
		if not p.currency and (p.no_show_type == "FIXED" or p.name in fixed_rules):
			out[("TEX Cancellation Policy", p.name)] = p.property
	return out


def _ambiguous_policies() -> list[tuple]:
	fixed = _fixed_policies()
	if not fixed:
		return []
	contract_of = {v.name: v.contract for v in frappe.get_all("TEX Contract Version", fields=["name", "contract"])}
	currency_of = {c.name: (c.contract_currency or "").upper()
	               for c in frappe.get_all("TEX Contract", fields=["name", "contract_currency"])}
	defaults = {r.name: r for r in frappe.get_all("Rate Plan", fields=["name", "tex_payment_policy",
	                                                                    "tex_cancellation_policy"])}
	used: dict[tuple[str, str], set[tuple[str, str]]] = {}
	for row in frappe.get_all("TEX Contract Rate Plan", filters={"parenttype": "TEX Contract Version"},
	                          fields=["parent", "rate_plan", "payment_policy", "cancellation_policy"]):
		contract = contract_of.get(row.parent)
		if not contract:
			continue
		plan = defaults.get(row.rate_plan) or frappe._dict()
		for doctype, name in (("TEX Payment Policy", row.payment_policy or plan.tex_payment_policy),
		                      ("TEX Cancellation Policy", row.cancellation_policy or plan.tex_cancellation_policy)):
			if (doctype, name) in fixed:
				used.setdefault((doctype, name), set()).add((contract, currency_of.get(contract, "")))
	out = []
	for (doctype, name), contracts in sorted(used.items()):
		currencies = sorted({ccy for _c, ccy in contracts})
		if len(currencies) < 2:
			continue
		new = {"currencies": currencies, "contracts": sorted(c for c, _ccy in contracts)}
		out.append((doctype, name, new, fixed[(doctype, name)]))
		if recorded("policy.fixed_currency_ambiguous", reference_doctype=doctype, reference_name=name, new=new):
			continue
		audit("policy.fixed_currency_ambiguous", reference_doctype=doctype, reference_name=name,
		      property=fixed[(doctype, name)] or None, source="System", new=new,
		      reason="A fixed amount without a currency is read in each contract's currency, and these contracts "
		             "are in several: give the policy a currency, or one policy per currency (ADR-067).")
	return out


def _stays_sold_in_another_currency() -> list[str]:
	out = []
	for r in frappe.get_all("Reservation", filters={"status": ("in", LIVE), "check_out_date": (">=", nowdate()),
	                                                 "tex_pricing_snapshot": ("like", '%"FIXED"%')},
	                        fields=["name", "property", "tex_booking", "tex_pricing_snapshot"], order_by="name asc"):
		try:
			snap = json.loads(r.tex_pricing_snapshot or "{}")
		except ValueError:
			continue
		plan = snap.get("rate_plan") or {}
		fixed = [k for k in ("payment_policy", "cancellation_policy") if policy_money.has_fixed(plan.get(k))]
		sold = (snap.get("currency") or "").upper()
		contract = ((snap.get("contract") or {}).get("currency") or "").upper()
		if not fixed or not sold or not contract or sold == contract:
			continue
		out.append(r.name)
		new = {"sold_in": sold, "contract_currency": contract, "policies": fixed, "booking": r.tex_booking}
		if recorded("reservation.fixed_policy_currency", reference_doctype="Reservation", reference_name=r.name,
		            new=new):
			continue
		audit("reservation.fixed_policy_currency", reference_doctype="Reservation", reference_name=r.name,
		      property=r.property, source="System", new=new,
		      reason="Sold with a fixed deposit or fee in another currency than its contract's: the stay keeps the "
		             "terms it was sold on, its fixed amount read in the sale's currency (ADR-067).")
	return out
