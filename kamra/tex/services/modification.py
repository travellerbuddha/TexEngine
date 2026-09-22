"""Reservation modification, repricing and historical simulation (R-21, R-22, R-23).

``propose`` never writes: it re-prices the changed stay on a chosen basis and
returns OLD vs PROPOSED, the difference and the full explanation, plus a signed
proposal token. ``apply`` re-derives the same proposal (deterministically), checks
availability under inventory locks, writes a TEX Reservation Revision and updates
the reservation — never a silent price rewrite.

Calculation bases:
  ORIGINAL_VERSION      the contract version the reservation was sold on, selling
                        policies as of the original sale time
  ORIGINAL_SALE_DATE    whatever contract/policies were on sale at the original sale time
  HISTORICAL_SALE_DATE  as if sold at a chosen past moment (needs price.override)
  CURRENT               today's contracts and policies
"""

from __future__ import annotations

import json
from datetime import datetime

import frappe
from frappe import _
from frappe.utils import get_datetime, getdate, now_datetime

from kamra.tex.availability import repository as avail
from kamra.tex.availability.restrictions import RestrictionScope
from kamra.tex.commercial import contracts
from kamra.tex.money import D, from_db, quantize, to_str
from kamra.tex.pricing import serialize
from kamra.tex.pricing.model import ChildSpec
from kamra.tex.security import scope
from kamra.tex.security.audit import audit
from kamra.tex.services import booking as booking_svc
from kamra.tex.services import quoting

BASES = ("ORIGINAL_VERSION", "ORIGINAL_SALE_DATE", "HISTORICAL_SALE_DATE", "CURRENT")
EDITABLE = ("check_in", "check_out", "room_type", "adults", "children", "board", "rate_plan", "market",
            "promo_codes", "extras", "sale_at")


def _snapshot(res) -> dict:
	if not res.tex_pricing_snapshot:
		frappe.throw(_("Reservation {0} was not priced by TEX; it cannot be re-priced here.").format(res.name))
	return json.loads(res.tex_pricing_snapshot)


def _children(raw) -> tuple[ChildSpec, ...]:
	out = []
	for c in raw or []:
		if isinstance(c, dict):
			out.append(ChildSpec(age=c.get("age") if c.get("age") is not None else None,
			                     dob=getdate(c["dob"]) if c.get("dob") else None))
		else:
			out.append(ChildSpec(age=int(c)))
	return tuple(out)


def build_changed_request(res, changes: dict, sale_at: datetime):
	snap = _snapshot(res)
	base = dict(snap["request"])
	unknown = set(changes) - set(EDITABLE)
	if unknown:
		frappe.throw(_("Cannot change: {0}").format(", ".join(sorted(unknown))))
	for k, v in changes.items():
		if k in ("check_in", "check_out"):
			base[k] = getdate(v).isoformat()
		elif k == "children":
			base[k] = [{"age": c.age, "dob": c.dob.isoformat() if c.dob else None} for c in _children(v)]
		elif k == "adults":
			base[k] = int(v)
		elif k == "promo_codes":
			base[k] = [x.strip().upper() for x in (v or []) if x and x.strip()]
		elif k == "extras":
			base[k] = [{"code": e["code"].upper(), "quantity": int(e.get("quantity") or 1),
			            "service_dates": list(e.get("service_dates") or [])} for e in (v or [])]
		elif k == "market":
			base[k] = str(v).upper()
		elif k == "rate_plan":
			base[k] = v or None
		elif k != "sale_at":
			base[k] = v
	base["sale_at"] = sale_at.isoformat()
	return serialize.request_from_dict(base), snap


def _resolve(res, snap, req, basis: str, basis_sale_at) -> tuple[str, datetime, str]:
	"""→ (contract version, effective sale time, how decided)."""
	original_sale = get_datetime(res.tex_sale_at or snap.get("accepted_at"))
	if basis == "ORIGINAL_VERSION":
		return snap["contract"]["version"], original_sale, "original contract version"
	if basis == "CURRENT":
		at = now_datetime()
	elif basis == "ORIGINAL_SALE_DATE":
		at = original_sale
	elif basis == "HISTORICAL_SALE_DATE":
		if not basis_sale_at:
			frappe.throw(_("Choose the historical sale date."))
		at = get_datetime(basis_sale_at)
		if at > now_datetime():
			frappe.throw(_("A historical sale date cannot be in the future."))
	else:
		frappe.throw(_("Unknown pricing basis {0}.").format(basis))
	cands = contracts.candidate_contracts(res.property, req.market, req.channel, at)
	same = [c for c in cands if c[0].name == snap["contract"]["contract"]]
	pick = (same or cands or [None])[0]
	if not pick:
		frappe.throw(_("No contract sold this stay for market {0} at {1}.").format(req.market, at))
	return pick[1], at, f"contract {pick[0].contract_code} on sale at {at}"


def propose(reservation: str, changes: dict | None = None, *, basis: str = "CURRENT", basis_sale_at=None,
            _check_permission: bool = True, _locked: bool = False) -> dict:
	res = frappe.get_doc("Reservation", reservation)
	if _check_permission:
		scope.require("reservation.modify", res.property)
		if basis == "HISTORICAL_SALE_DATE":
			scope.require("price.override", res.property)
	if basis not in BASES:
		frappe.throw(_("Unknown pricing basis {0}.").format(basis))
	if res.status in ("Cancelled", "No Show", "Checked Out"):
		frappe.throw(_("A {0} reservation cannot be modified.").format(res.status.lower()))
	changes = {k: v for k, v in (changes or {}).items() if v is not None}
	placeholder_at = now_datetime()
	req, snap = build_changed_request(res, changes, placeholder_at)
	version, at, how = _resolve(res, snap, req, basis, basis_sale_at)
	req, _s = build_changed_request(res, changes, at)
	quote, terms = quoting.price_request(version, req)
	old_ccy = res.tex_currency or snap.get("currency")
	old_total = from_db(res.tex_total_amount or res.amount_after_tax, old_ccy or "EUR")

	# availability & restrictions for the new stay, not counting this reservation itself
	now = now_datetime()
	warnings = []
	stay_changed = any(k in changes for k in ("check_in", "check_out", "room_type"))
	if stay_changed:
		count, _days = avail.stay_availability(res.property, req.room_type, terms.contract_id, req.check_in,
		                                      req.check_out, now.date(), exclude=[res.name], locking=_locked)
		if count < 1:
			warnings.append({"code": "SOLD_OUT", "message": _("No availability for the new stay.")})
		sc = RestrictionScope(room_type=req.room_type, contract=terms.contract_id, market=req.market,
		                      rate_plan=req.rate_plan, channel=req.channel)
		for v in avail.check_restrictions(res.property, sc, req.check_in, req.check_out, now.date()):
			warnings.append(v.to_dict())

	new = quote.to_dict(internal=True)
	diff = (quote.total - old_total) if quote.sellable and quote.currency == old_ccy else None
	proposal = {
		"reservation": res.name, "modified": str(res.modified), "changes": changes, "basis": basis,
		"basis_sale_at": str(basis_sale_at) if basis_sale_at else None, "version": version,
		"new_total": to_str(quote.total) if quote.sellable else None, "currency": quote.currency,
	}
	return {
		"reservation": res.name,
		"basis": basis, "basis_detail": how, "pricing_sale_at": str(at),
		"old": {"total": to_str(old_total), "currency": old_ccy, "request": snap["request"],
		        "contract": snap.get("contract"), "lines": snap.get("lines"), "totals": snap.get("totals")},
		"proposed": new,
		"sellable": quote.sellable and not any(w.get("code") == "SOLD_OUT" for w in warnings),
		"difference": to_str(diff) if diff is not None else None,
		"currency_changed": quote.currency != old_ccy,
		"warnings": warnings,
		"proposal_token": quoting.sign({**proposal, "exp": None}),
	}


def apply(proposal_token: str, *, reason: str, override_amount=None, source: str = "Desk",
          _guest_authorized: bool = False) -> dict:
	"""``_guest_authorized``: set only by the self-service API after verifying the
	guest's manage token owns the proposal's reservation. Guests can never override."""
	p = quoting.verify(proposal_token)
	res = frappe.get_doc("Reservation", p["reservation"])
	if _guest_authorized:
		if override_amount not in (None, ""):
			frappe.throw(_("Guests cannot override prices."), frappe.PermissionError)
	else:
		scope.require("reservation.modify", res.property)
	if str(res.modified) != p["modified"]:
		frappe.throw(_("The reservation changed since this proposal was made — review it again."))
	if not (reason or "").strip():
		frappe.throw(_("A reason is required for every modification."))
	if override_amount not in (None, ""):
		scope.require("price.override", res.property)

	# lock the new nights first, then recompute deterministically under the lock
	changes = p["changes"]
	snap = _snapshot(res)
	req0 = snap["request"]
	ci = getdate(changes.get("check_in") or req0["check_in"])
	co = getdate(changes.get("check_out") or req0["check_out"])
	rt = changes.get("room_type") or req0["room_type"]
	avail.lock_nights(res.property, [(rt, ci, co)])
	result = propose(res.name, changes, basis=p["basis"], basis_sale_at=p.get("basis_sale_at"),
	                 _check_permission=False, _locked=True)
	if not result["sellable"]:
		frappe.throw(_("The modified stay cannot be sold: {0}").format(
			"; ".join(w["message"] for w in result["warnings"]) or result["proposed"].get("reasons")))
	new = result["proposed"]
	if new["totals"]["total"] != p["new_total"]:
		frappe.throw(_("The price moved since this proposal was made — review it again."))
	ccy = new["currency"]
	new_total = D(new["totals"]["total"])
	final_total = quantize(D(override_amount), ccy) if override_amount not in (None, "") else new_total
	if final_total < 0:
		frappe.throw(_("A price cannot be negative."))

	before = {f: res.get(f) for f in ("check_in_date", "check_out_date", "room_type", "adults", "children",
	                                   "tex_board", "rate_plan", "tex_market", "tex_total_amount",
	                                   "tex_contract_version")}
	req = new["request"]
	amounts = booking_svc.reservation_amounts(new)
	if override_amount not in (None, ""):
		factor = final_total / new_total if new_total else D(1)
		amounts.update({"amount_after_tax": final_total, "tex_total_amount": final_total,
		                "tax_amount": quantize(D(amounts["tax_amount"]) * factor, ccy),
		                "amount_before_tax": final_total - quantize(D(amounts["tax_amount"]) * factor, ccy),
		                "tex_margin_amount": D(amounts["tex_margin_amount"]) + (final_total - new_total)})
	res.flags.tex_modification = True
	res.update({
		"check_in_date": req["check_in"], "check_out_date": req["check_out"], "room_type": req["room_type"],
		"adults": int(req["adults"]), "children": len(req.get("children") or []), "rate_plan": req.get("rate_plan"),
		"tex_board": req["board"], "tex_market": req["market"], "tex_child_ages": json.dumps(req.get("children") or []),
		"tex_contract": new["contract"]["contract"], "tex_contract_version": new["contract"]["version"],
		"tex_payload_hash": new["contract"]["payload_hash"], "tex_currency": ccy,
		"tex_fx_rate": D((new.get("fx") or {}).get("sell_rate") or 1),
		"tex_pricing_snapshot": json.dumps({**new, "accepted_at": str(now_datetime()),
		                                    "basis": p["basis"], "override_amount": to_str(final_total)
		                                    if override_amount not in (None, "") else None},
		                                   sort_keys=True, ensure_ascii=False),
		"tex_promotions": ", ".join(x["promo_id"] for x in new.get("promotions") or [] if x["applied"]),
		**amounts,
	})
	if res.room and before["room_type"] != res.room_type:
		res.room = None      # physical room of the old type no longer fits
	res.save(ignore_permissions=True)
	after = {f: res.get(f) for f in before}
	changed_fields = {k: [before[k], after[k]] for k in before if str(before[k]) != str(after[k])}
	kinds = {"check_in_date": "Dates", "check_out_date": "Dates", "room_type": "Room", "adults": "Occupancy",
	         "children": "Occupancy", "tex_board": "Board", "tex_market": "Market", "rate_plan": "Board"}
	types = {kinds[k] for k in changed_fields if k in kinds}
	if "extras" in changes:
		types.add("Extras")
	if "promo_codes" in changes:
		types.add("Discount")
	if override_amount not in (None, ""):
		types.add("Price Override")
	change_type = types.pop() if len(types) == 1 else ("Multiple" if types else "Guest Request"
	                                                    if source == "Guest" else "Multiple")
	old_total = D(result["old"]["total"])
	rev = booking_svc._record_revision(
		res.name, res.tex_booking, change_type=change_type, old_amount=old_total, new_amount=final_total,
		currency=ccy, basis="MANUAL" if override_amount not in (None, "") else p["basis"],
		basis_sale_at=result["pricing_sale_at"], reason=reason, changes=changed_fields | {"requested": changes},
		before=snap, after=json.loads(res.tex_pricing_snapshot), source=source,
		override=final_total if override_amount not in (None, "") else None)
	if res.tex_booking:
		booking_svc._refresh_booking_after_change(res.tex_booking)
	audit("reservation.modify", reference_doctype="Reservation", reference_name=res.name, property=res.property,
	      old={"total": to_str(old_total), **{k: v[0] for k, v in changed_fields.items()}},
	      new={"total": to_str(final_total), **{k: v[1] for k, v in changed_fields.items()}, "revision": rev,
	           "basis": p["basis"]}, reason=reason)
	return {"reservation": res.name, "revision": rev, "old_total": to_str(old_total),
	        "new_total": to_str(final_total), "difference": to_str(final_total - old_total), "currency": ccy}


def simulate(reservation: str, sale_at) -> dict:
	"""What would this exact stay have cost if sold at ``sale_at``? Read-only (R-22)."""
	res = frappe.get_doc("Reservation", reservation)
	scope.require("price.view", res.property)
	snap = _snapshot(res)
	at = get_datetime(sale_at)
	req = serialize.request_from_dict({**snap["request"], "sale_at": at.isoformat()})
	cands = contracts.candidate_contracts(res.property, req.market, req.channel, at)
	if not cands:
		return {"sellable": False, "reasons": [{"code": "NO_CONTRACT",
		                                        "message": _("No contract was on sale at that time.")}]}
	pick = next((c for c in cands if c[0].name == snap["contract"]["contract"]), cands[0])
	quote, _terms = quoting.price_request(pick[1], req)
	internal = scope.has_capability("price.view_cost", res.property)
	actual = from_db(res.tex_total_amount or res.amount_after_tax, res.tex_currency or "EUR")
	return {
		"reservation": res.name, "simulated_sale_at": str(at), "contract_version": pick[1],
		"actual": {"total": to_str(actual), "currency": res.tex_currency, "sale_at": str(res.tex_sale_at),
		           "version": snap["contract"]["version"]},
		"simulated": quote.to_dict(internal=internal),
		"difference": to_str(quote.total - actual) if quote.sellable and quote.currency == res.tex_currency else None,
	}


def revisions(reservation: str) -> list[dict]:
	res = frappe.get_doc("Reservation", reservation)
	scope.require("reservation.view", res.property)
	rows = frappe.get_all("TEX Reservation Revision", filters={"reservation": reservation},
	                      fields=["name", "revision_no", "change_type", "actor", "creation", "old_amount", "new_amount",
	                              "difference", "currency", "pricing_basis", "reason", "approval_status", "source",
	                              "changes_json", "override_amount"], order_by="revision_no asc")
	for r in rows:
		r["changes"] = json.loads(r.pop("changes_json") or "{}")
		for f in ("old_amount", "new_amount", "difference", "override_amount"):
			r[f] = to_str(from_db(r[f], r.currency or "EUR")) if r[f] is not None else None
	return rows

