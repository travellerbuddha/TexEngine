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
from frappe.utils import add_to_date, get_datetime, getdate, now_datetime

from kamra.tex.availability import repository as avail
from kamra.tex.availability.restrictions import RestrictionScope
from kamra.tex.commercial import contracts
from kamra.tex.money import D, from_db, quantize, to_str
from kamra.tex.pricing import addons, serialize
from kamra.tex.pricing.extras import guest_reason
from kamra.tex.pricing.model import ChildSpec
from kamra.tex.security import scope
from kamra.tex.security.audit import audit
from kamra.tex.services import booking as booking_svc
from kamra.tex.services import quoting

BASES = ("ORIGINAL_VERSION", "ORIGINAL_SALE_DATE", "HISTORICAL_SALE_DATE", "CURRENT")
CAPACITY_REASONS = ("sold out on ", "only ", "closed on ")     # pricing.extras.capacity_refusal
EDITABLE = ("check_in", "check_out", "room_type", "adults", "children", "board", "rate_plan", "market",
            "promo_codes", "extras", "sale_at", "drop_addons")


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
	if {"channel", "sales_channel"} & set(changes):
		# a change is priced on the channel the stay was sold on; selling it on another channel
		# is a new sale on that channel, by someone entitled to it (ADR-050)
		frappe.throw(_("A reservation keeps the sales channel it was sold on. To sell it on another channel, "
		               "cancel it and book again on that channel."))
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
		elif k not in ("sale_at", "drop_addons"):
			base[k] = v
	base["sale_at"] = sale_at.isoformat()
	return serialize.request_from_dict(base), snap


def priced_at(res, snap) -> datetime:
	"""When the snapshot's price was computed: its quote's (or modification's) sale time."""
	return get_datetime((snap.get("request") or {}).get("sale_at") or res.tex_sale_at or snap.get("accepted_at"))


def original_priced_at(res, snap) -> datetime:
	"""When the booking was first priced: its quote's sale time, which precedes the booking by
	up to the quote's lifetime. Extras and taxes are resolved as of it (G-20), so an unchanged
	ORIGINAL_* reprice reproduces the sold price. Carried across modifications."""
	if snap.get("original_priced_at"):
		return get_datetime(snap["original_priced_at"])
	if not snap.get("basis"):         # the booking's own snapshot, not a modification's
		sale = (snap.get("request") or {}).get("sale_at")
		if sale:
			return get_datetime(sale)
	return get_datetime(res.tex_sale_at or snap.get("accepted_at"))


def _resolve(res, snap, req, basis: str, basis_sale_at, sale_at=None) -> tuple[str, datetime, str]:
	"""→ (contract version, effective sale time, how decided). ``sale_at`` pins CURRENT to the
	moment a proposal was priced (a guest's paid change applies at the price they accepted)."""
	original_sale = original_priced_at(res, snap)
	if basis == "ORIGINAL_VERSION":
		return snap["contract"]["version"], original_sale, "original contract version"
	if basis == "CURRENT":
		at = get_datetime(sale_at) if sale_at else now_datetime()
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


PROPOSAL_TTL_MINUTES = 30
# a guest's change that waits for its payment keeps the accepted price this long after the
# proposal expired: the guest may still be on the gateway's page (G-45, ADR-044)
PAYMENT_GRACE_MINUTES = 60


def payment_deadline(p: dict) -> datetime:
	"""Until when a payment for this proposal still applies it at the accepted price."""
	return add_to_date(get_datetime(p["exp"]), minutes=PAYMENT_GRACE_MINUTES)


def propose(reservation: str, changes: dict | None = None, *, basis: str = "CURRENT", basis_sale_at=None,
            _check_permission: bool = True, _locked: bool = False, internal: bool | None = None,
            _sale_at=None) -> dict:
	"""``internal`` (cost, margin, explanation) defaults to the caller's price.view_cost;
	guest calls (``_check_permission=False``) never get it unless the service asks.
	``_sale_at`` (internal only) prices CURRENT as of that moment instead of now."""
	res = frappe.get_doc("Reservation", reservation)
	if internal is None:
		internal = _check_permission and scope.has_capability("price.view_cost", res.property)
	if _check_permission:
		scope.require("reservation.modify", res.property)
		if basis == "HISTORICAL_SALE_DATE":
			scope.require("price.override", res.property)
	if basis not in BASES:
		frappe.throw(_("Unknown pricing basis {0}.").format(basis))
	if res.status in ("Cancelled", "No Show", "Checked Out"):
		frappe.throw(_("A {0} reservation cannot be modified.").format(res.status.lower()))
	if res.get("tex_pricing_source") == "Channel":
		# its price and its stay are the channel's: changes arrive from the channel (G-69)
		frappe.throw(_("This booking came from a channel: change it in the channel, and the change arrives here."))
	changes = {k: v for k, v in (changes or {}).items() if v is not None}
	if "drop_addons" in changes:
		raw = changes.pop("drop_addons")
		ids = sorted({raw} if isinstance(raw, str) else {str(x) for x in raw or []})
		if ids:
			changes["drop_addons"] = ids
	placeholder_at = now_datetime()
	req, snap = build_changed_request(res, changes, placeholder_at)
	version, at, how = _resolve(res, snap, req, basis, basis_sale_at, _sale_at)
	req, _s = build_changed_request(res, changes, at)
	# the booking's own coupon uses never count against it when it is repriced (G-09)
	quote, terms = quoting.price_request(version, req, exclude_booking=res.tex_booking, exclude_reservation=res.name,
	                                     gkey=booking_svc.booking_guest_key(res.tex_booking, res.guest))
	old_ccy = res.tex_currency or snap.get("currency")
	old_total = from_db(res.tex_total_amount or res.amount_after_tax, old_ccy or "EUR")

	# availability & restrictions for the new stay, not counting this reservation itself
	now = now_datetime()
	warnings = []
	stay_changed = any(k in changes for k in ("check_in", "check_out", "room_type"))
	if stay_changed:
		# the nights the stay already holds stay its own: only the new ones are checked (ADR-048)
		count, _days = avail.stay_availability(res.property, req.room_type, terms.contract_id, req.check_in,
		                                      req.check_out, now.date(), exclude=[res.name], locking=_locked,
		                                      held=avail.held_nights(req.room_type, res))
		if count < 1:
			warnings.append({"code": "SOLD_OUT", "message": _("No availability for the new stay.")})
		sc = RestrictionScope(room_type=req.room_type, contract=terms.contract_id, market=req.market,
		                      rate_plan=req.rate_plan, channel=req.channel)
		for v in avail.check_restrictions(res.property, sc, req.check_in, req.check_out, now.date()):
			warnings.append(v.to_dict())
	for e in quote.extras:
		if not e.ok and e.reason.startswith(CAPACITY_REASONS):
			# a limited extra left: the change is shown, and the extra is dropped only if applied (G-19)
			warnings.append({"code": "EXTRA_SOLD_OUT", "message": f"{e.name}: {e.reason}"})

	new = quote.to_dict(internal=True)
	# extras added after booking are carried over at the price they were added for, unless
	# staff remove them (G-22)
	drop = set(changes.get("drop_addons") or ())
	unknown = drop - {a["id"] for a in snap.get("addons") or []}
	if unknown:
		frappe.throw(_("Not added to this reservation: {0}").format(", ".join(sorted(unknown))))
	for a in snap.get("addons") or []:
		if a["id"] in drop:
			continue
		new = addons.merge_addons(new, a["quote"], addon_id=a["id"], at=a["at"])
		new["addons"][-1].update({k: a[k] for k in ("requests", "source") if k in a})
		for e in a["quote"].get("extras") or []:
			days = [getdate(u["date"]) for u in e.get("usage") or []]
			if any(not (req.check_in <= d <= req.check_out) for d in days):
				warnings.append({"code": "ADDON_OUTSIDE_STAY",
				                 "message": _("{0} was added for a day outside the new stay.").format(e["name"])})
	new_total = D(new["totals"]["total"]) if quote.sellable else None
	old_totals = dict(snap.get("totals") or {})
	if not internal:
		quoting.strip_internal(new)
		for k in quoting.INTERNAL_TOTALS:
			old_totals.pop(k, None)
	diff = (new_total - old_total) if quote.sellable and quote.currency == old_ccy else None
	proposal = {
		"reservation": res.name, "modified": str(res.modified), "changes": changes, "basis": basis,
		"basis_sale_at": str(basis_sale_at) if basis_sale_at else None, "version": version,
		"new_total": to_str(new_total) if quote.sellable else None, "currency": quote.currency,
		# the moment the price was computed: a paid guest change re-derives it as of then (G-45)
		"pricing_sale_at": str(at),
	}
	return {
		"reservation": res.name,
		"basis": basis, "basis_detail": how, "pricing_sale_at": str(at),
		"old": {"total": to_str(old_total), "currency": old_ccy, "request": snap["request"],
		        "contract": snap.get("contract"), "lines": snap.get("lines"), "totals": old_totals},
		"proposed": new,
		"sellable": quote.sellable and not any(w.get("code") == "SOLD_OUT" for w in warnings)
		and not (not _check_permission and any(w.get("code") == "ADDON_OUTSIDE_STAY" for w in warnings)),
		"difference": to_str(diff) if diff is not None else None,
		"currency_changed": quote.currency != old_ccy,
		"warnings": warnings,
		"proposal_token": quoting.sign({**proposal, "kind": "proposal",
		                                "exp": add_to_date(now, minutes=PROPOSAL_TTL_MINUTES).isoformat()}),
	}


def apply(proposal_token: str | None, *, reason: str, override_amount=None, source: str = "Desk",
          _guest_authorized: bool = False, _proposal: dict | None = None, _from_payment: bool = False,
          _paid_at=None) -> dict:
	"""``_guest_authorized``: set only by the self-service API after verifying the
	guest's manage token owns the proposal's reservation. Guests can never override.

	``_proposal``: a proposal the server verified and stored (a TEX Guest Change Request); it
	is re-derived at the moment it was priced, so the price the guest accepted is the price
	applied (G-45). ``_from_payment``: the guest paid for it (at ``_paid_at``, when the gateway
	confirmed the charge); a payment made by the proposal's payment deadline (its expiry plus
	``PAYMENT_GRACE_MINUTES``) applies it, whenever the job applying it runs.

	Locks: the booking, then the reservation, then the inventory days: the order every path that
	changes a TEX booking takes (review of ADR-044)."""
	if _proposal is not None:
		p = _proposal
		if not p.get("pricing_sale_at") or p.get("kind") != "proposal":
			frappe.throw(_("This change cannot be applied: its proposal carries no price time."))
		if _from_payment and get_datetime(_paid_at or now_datetime()) > payment_deadline(p):
			frappe.throw(_("The payment arrived after the price of this change expired."))
		pin = p["pricing_sale_at"] if p["basis"] == "CURRENT" else None
	else:
		if _from_payment:
			frappe.throw(_("A paid change applies from its stored proposal."))
		p = quoting.verify(proposal_token, kind="proposal")
		pin = None
	# the booking first, then the reservation as it is now (a locking read, not the caller's
	# snapshot of it): the lock order of every change to a TEX booking
	booking = frappe.db.get_value("Reservation", p["reservation"], "tex_booking")
	if booking:
		frappe.db.get_value("TEX Booking", booking, "name", for_update=True)
	res = frappe.get_doc("Reservation", p["reservation"], for_update=True)
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
	                 _check_permission=False, _locked=True, internal=True, _sale_at=pin)
	if not result["sellable"]:
		why = "; ".join(w["message"] for w in result["warnings"]) or result["proposed"].get("reasons")
		frappe.throw(_("The modified stay cannot be sold: {0}").format(
			guest_reason(str(why)) if _guest_authorized else why))
	new = result["proposed"]
	if new["totals"]["total"] != p["new_total"]:
		frappe.throw(_("The price moved since this proposal was made — review it again."))
	# limited extras: give back the old units and take the new ones under the day locks (G-19)
	from kamra.tex.availability import extras_repository as xinv

	xinv.replace_for_reservation(res.property, res.tex_booking, res.name, new,
	                             "Held" if res.status in ("Held", "Pending Payment") else "Confirmed")
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
	# the new nights were locked and recounted for the contract above (ADR-048)
	res.flags.tex_inventory_checked = True
	res.update({
		"check_in_date": req["check_in"], "check_out_date": req["check_out"], "room_type": req["room_type"],
		"adults": int(req["adults"]), "children": len(req.get("children") or []), "rate_plan": req.get("rate_plan"),
		"tex_board": req["board"], "tex_market": req["market"], "tex_child_ages": json.dumps(req.get("children") or []),
		"tex_contract": new["contract"]["contract"], "tex_contract_version": new["contract"]["version"],
		"tex_payload_hash": new["contract"]["payload_hash"], "tex_currency": ccy,
		"tex_fx_rate": D((new.get("fx") or {}).get("sell_rate") or 1),
		"tex_pricing_snapshot": json.dumps({**new, "accepted_at": str(now_datetime()),
		                                    "original_priced_at": str(original_priced_at(res, snap)),
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
	if "extras" in changes or "drop_addons" in changes:
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
		booking_svc.sync_redemptions(res.tex_booking)
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
	quote, _terms = quoting.price_request(pick[1], req, exclude_booking=res.tex_booking, check_capacity=False,
	                                      gkey=booking_svc.booking_guest_key(res.tex_booking, res.guest))
	internal = scope.has_capability("price.view_cost", res.property)
	actual = from_db(res.tex_total_amount or res.amount_after_tax, res.tex_currency or "EUR")
	return {
		"reservation": res.name, "simulated_sale_at": str(at), "contract_version": pick[1],
		"actual": {"total": to_str(actual), "currency": res.tex_currency, "sale_at": str(res.tex_sale_at),
		           "priced_at": str(priced_at(res, snap)), "version": snap["contract"]["version"]},
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

