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
  HISTORICAL_SALE_DATE  as if sold at a chosen past moment (needs price.override, on propose and
                        on apply)
  CURRENT               today's contracts and policies

The sale time is the basis's: a change never carries one of its own, and a chosen historical
sale date is checked on the server (given, valid, not in the future). A past sale time selects
the contracts that were Active then (their audited status, G-51, ADR-054); CURRENT reads the
live status. Coupon uses are counted as they are now: a code a change keeps or adds is recorded
under today's limits (G-09); the simulator alone counts them as held at its sale time.

A proposal token is bound to whoever proposed it (G-51, ADR-054): staff apply only their own
proposals at the hotel they were made for; a guest's proposal is applied only through the manage
page of its booking.

FX (G-56, ADR-051): the ORIGINAL_* bases convert with the rates the original sale recorded
(``original_fx``), never the FX tables, for every pair the sale converted; a pair it did not
convert (another contract currency, a new extra's currency) is resolved as of the original
sale time. HISTORICAL_SALE_DATE and CURRENT resolve every rate as of their own sale time.
"""

from __future__ import annotations

import json
from datetime import datetime

import frappe
from frappe import _
from frappe.utils import add_to_date, convert_utc_to_system_timezone, get_datetime, getdate, now_datetime

from kamra.tex.availability import repository as avail
from kamra.tex.commercial import contracts
from kamra.tex.money import D, db_dec, from_db, quantize, to_str
from kamra.tex.pricing import addons, engine, serialize
from kamra.tex.pricing import fx as fx_math
from kamra.tex.pricing.extras import guest_reason
from kamra.tex.pricing.model import ChildSpec
from kamra.tex.security import scope
from kamra.tex.security.audit import audit
from kamra.tex.services import booking as booking_svc
from kamra.tex.services import quoting, sold_terms

BASES = ("ORIGINAL_VERSION", "ORIGINAL_SALE_DATE", "HISTORICAL_SALE_DATE", "CURRENT")
CAPACITY_REASONS = ("sold out on ", "only ", "closed on ")     # pricing.extras.capacity_refusal
EDITABLE = ("check_in", "check_out", "room_type", "adults", "children", "board", "rate_plan", "market",
            "promo_codes", "extras", "drop_addons")
# a change to another product sells it at the reservation's channel's prices: staff need the right
# to book on that channel; dates, occupancy, extras and codes are servicing (ADR-050 review)
PRODUCT_FIELDS = ("room_type", "rate_plan", "board", "market")


def _snapshot(res) -> dict:
	if not res.tex_pricing_snapshot:
		frappe.throw(_("Reservation {0} was not priced by TEX; it cannot be re-priced here.").format(res.name))
	return json.loads(res.tex_pricing_snapshot)


def _children(raw, arrival=None) -> tuple[ChildSpec, ...]:
	"""The changed party's children: an age in whole years or a date of birth, checked
	against the (new) arrival like a search's (G-52)."""
	return tuple(quoting.Party.parse({"adults": 1, "children": list(raw or [])},
	                                 arrival=getdate(arrival) if arrival else None).children)


def product_changes(res, changes: dict) -> list[str]:
	"""Which of room type, rate plan, board and market ``changes`` really change."""
	req = _snapshot(res).get("request") or {}
	out = []
	for k in PRODUCT_FIELDS:
		if k not in changes:
			continue
		new, old = changes[k], req.get(k)
		if k == "market":
			new, old = str(new or "").upper(), str(old or "").upper()
		if (new or None) != (old or None):
			out.append(k)
	return out


def require_product_channel(res, changes: dict) -> None:
	"""A staff change to another product needs the right to book on the reservation's channel
	at its hotel (ADR-050 review): a call-centre agent does not turn a B2B booking into another
	stay at the B2B rate."""
	if product_changes(res, changes):
		channel = res.get("tex_sales_channel") or (_snapshot(res).get("request") or {}).get("channel")
		scope.require_channel(channel, res.property, to="book")


def build_changed_request(res, changes: dict, sale_at: datetime):
	snap = _snapshot(res)
	base = dict(snap["request"])
	# the booking's basket is judged again with the rooms as they are now (G-84): ``booked_price``
	base.pop("booking_basket", None)
	base.pop("booking_rooms", None)
	# the channel is not EDITABLE: a change is priced on the channel the stay was sold on (ADR-050)
	unknown = set(changes) - set(EDITABLE)
	if unknown:
		frappe.throw(_("Cannot change: {0}").format(", ".join(sorted(unknown))))
	arrival = getdate(changes.get("check_in") or base["check_in"])
	for k, v in changes.items():
		if k in ("check_in", "check_out"):
			base[k] = getdate(v).isoformat()
		elif k == "children":
			base[k] = [{"age": c.age, "dob": c.dob.isoformat() if c.dob else None} for c in _children(v, arrival)]
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
		elif k != "drop_addons":
			base[k] = v
	base["sale_at"] = sale_at.isoformat()
	return serialize.request_from_dict(base), snap


def priced_at(res, snap) -> datetime:
	"""When the snapshot's price was computed: its quote's (or modification's) sale time. Recorded
	as ``priced_at`` since G-73; a snapshot written before holds it as its request's sale time."""
	return get_datetime(snap.get("priced_at") or (snap.get("request") or {}).get("sale_at") or res.tex_sale_at
	                    or snap.get("accepted_at"))


def original_priced_at(res, snap) -> datetime:
	"""When the booking was first priced: its quote's sale time, which precedes the booking by
	up to the quote's lifetime. Extras and taxes are resolved as of it (G-20), so an unchanged
	ORIGINAL_* reprice reproduces the sold price. Carried across modifications."""
	if snap.get("original_priced_at"):
		return get_datetime(snap["original_priced_at"])
	if not snap.get("basis"):         # the booking's own snapshot, not a modification's
		sale = snap.get("priced_at") or (snap.get("request") or {}).get("sale_at")
		if sale:
			return get_datetime(sale)
	return get_datetime(res.tex_sale_at or snap.get("accepted_at"))


RECORDED_FX_BASES = ("ORIGINAL_VERSION", "ORIGINAL_SALE_DATE")


def original_fx(res, snap) -> list[dict]:
	"""The FX conversions the original sale recorded (G-56): the booking's own snapshot has
	them; a modification carries them on (``original_fx_rates``), like ``original_priced_at``.
	A modification made before G-56 did not: they are then read from the Original revision."""
	if isinstance(snap.get("original_fx_rates"), list):
		return snap["original_fx_rates"]
	if not snap.get("basis"):         # the booking's own snapshot, not a modification's
		return _recorded(snap)
	first = frappe.db.get_value("TEX Reservation Revision", {"reservation": res.name, "change_type": "Original"},
	                            "snapshot_after", order_by="revision_no asc")
	return _recorded(json.loads(first)) if first else []


def _recorded(snap: dict) -> list[dict]:
	"""``fx.recorded``, told the currency of each converted line of a snapshot priced before
	G-56: an extra's is its revision's, a fixed levy's its tax policy's (G-56 review)."""
	if isinstance(snap.get("fx_rates"), list):
		return fx_math.recorded(snap)
	extra, tax = {}, {}
	for e in snap.get("extras") or []:
		rev = e.get("revision") if isinstance(e, dict) else None
		if rev and e.get("fx_rate") not in (None, "") and rev not in extra:
			ccy = frappe.db.get_value("TEX Extra", rev, "currency")
			if ccy:
				extra[rev] = ccy
	for t in snap.get("taxes") or []:
		src = (t.get("source") or "") if isinstance(t, dict) else ""
		if src.startswith("tax_policy:") and t.get("fx_rate") not in (None, "") and src not in tax:
			ccy = frappe.db.get_value("TEX Tax Policy", src.split(":", 1)[1], "currency")
			if ccy:
				tax[src] = ccy
	return fx_math.recorded(snap, extra_currency=extra, tax_currency=tax)


def fx_pins(res, snap, basis: str) -> dict | None:
	"""The rates a reprice on ``basis`` converts with instead of the FX tables."""
	if basis not in RECORDED_FX_BASES:
		return None
	return fx_math.pins(original_fx(res, snap), origin=f"reservation:{res.name}")


def past_sale_time(value, *, missing: str, future: str) -> datetime:
	"""A sale time a price is computed as of (a historical sale date, the simulator), checked on
	the server: given, a valid date and time, not in the future (G-51). ``missing`` and
	``future`` are the messages. A time with a UTC offset ("…Z", "…+03:00") is that moment in
	the site's time zone, which every sale time is kept in (G-51 review)."""
	if value in (None, ""):
		frappe.throw(missing)
	try:
		at = get_datetime(value)
	except (ValueError, TypeError, OverflowError):
		at = None
	if not isinstance(at, datetime):
		frappe.throw(_("The sale time is not a valid date and time."))
	if at.tzinfo is not None:
		at = convert_utc_to_system_timezone(at).replace(tzinfo=None)
	if at > now_datetime():
		frappe.throw(future)
	return at


def historical_sale_at(value) -> datetime:
	return past_sale_time(value, missing=_("Choose the historical sale date."),
	                      future=_("A historical sale date cannot be in the future."))


def _resolve(res, snap, req, basis: str, basis_sale_at, sale_at=None) -> tuple[str, datetime, str]:
	"""→ (contract version, effective sale time, how decided). ``sale_at`` pins CURRENT to the
	moment a proposal was priced (a guest's paid change applies at the price they accepted).

	A sale time in the past (the original or a historical sale date, a pinned CURRENT) selects
	among the contracts Active then; CURRENT now reads the live status (G-51, ADR-054). A pinned
	CURRENT finds the contract that priced the guest's change; ``apply`` then refuses a staff
	approval on a contract that no longer sells (G-51 review M1)."""
	original_sale = original_priced_at(res, snap)
	if basis == "ORIGINAL_VERSION":
		return snap["contract"]["version"], original_sale, "original contract version"
	if basis == "CURRENT":
		at = get_datetime(sale_at) if sale_at else now_datetime()
	elif basis == "ORIGINAL_SALE_DATE":
		at = original_sale
	elif basis == "HISTORICAL_SALE_DATE":
		at = historical_sale_at(basis_sale_at)
	else:
		frappe.throw(_("Unknown pricing basis {0}.").format(basis))
	historical = basis != "CURRENT" or bool(sale_at)
	cands = contracts.candidate_contracts(res.property, req.market, req.channel, at, historical=historical)
	same = [c for c in cands if c[0].name == snap["contract"]["contract"]]
	pick = (same or cands or [None])[0]
	if not pick:
		frappe.throw(_("No contract sold this stay for market {0} at {1}.").format(req.market, at))
	return pick[1], at, f"contract {pick[0].contract_code} on sale at {at}"


def booked_price(res, version: str, req, *, others: tuple | None = None, **kw):
	"""Price a room of a booking again (a change, the simulator): alone, then — when a minimum
	basket refused a promotion and the booking has other rooms — with the booking's basket: this
	room's new basket plus the others'. ``others`` (their basket, how many): by default the other
	live rooms as they are priced now — a change is judged on the booking it makes, and rooms that
	are not changed keep their locked price (G-84, ADR-057). → (quote, terms)."""
	quote, terms = quoting.price_request(version, req, **kw)
	total, n = others if others is not None else booking_svc.other_rooms_basket(res, quote.currency)
	again = engine.booking_request(req, quote, others_basket=total, others_rooms=n)
	if again is not None:
		q2, t2 = quoting.price_request(version, again, **kw)
		if q2.sellable:
			return q2, t2
	return quote, terms


def recorded_others(snap: dict) -> tuple:
	"""(basket, how many) of the other rooms of the booking a stay was last priced in, as its
	snapshot records it (G-84): none when it was priced alone."""
	req = snap.get("request") or {}
	if req.get("booking_basket") in (None, ""):
		return D(0), 0
	return D(req["booking_basket"]) - booking_svc.room_basket(snap), int(req.get("booking_rooms") or 1) - 1


def restriction_violations(res, snap: dict, req, contract: str | None, sale_date) -> list:
	"""What the restrictions refuse in a change (G-48, ADR-057): the changed stay is checked like
	a new booking of its scope, on ``sale_date``, for what it newly takes. With the same product
	(room type, contract, market, rate plan; the channel never changes) the nights it holds are
	its own and arrival, departure and length rules apply only when those change; another product
	is a new sale of the stay, its past aside (``restrictions.evaluate_change``). A change of
	neither dates nor product is never checked."""
	old = snap.get("request") or {}
	before = (getdate(res.check_in_date), getdate(res.check_out_date))
	same_product = (req.room_type == (old.get("room_type") or res.room_type)
	                and (req.rate_plan or None) == (old.get("rate_plan") or None)
	                and str(req.market or "").upper() == str(old.get("market") or res.tex_market or "").upper()
	                and contract == ((snap.get("contract") or {}).get("contract") or res.tex_contract))
	if same_product and (req.check_in, req.check_out) == before:
		return []
	sc = avail.scope_for(req.room_type, contract, req.market, req.rate_plan, req.channel)
	return avail.check_restrictions(res.property, sc, req.check_in, req.check_out, sale_date, before=before,
	                                product_changed=not same_product)


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
	``_sale_at`` (internal only) prices CURRENT as of that moment instead of now.

	``basis_sale_at`` is the HISTORICAL_SALE_DATE basis's sale time and is refused with any
	other basis; ``changes`` never carry a sale time (G-51). The proposal token names who
	proposed it, for which hotel and booking (``apply`` checks it)."""
	res = frappe.get_doc("Reservation", reservation)
	if internal is None:
		internal = _check_permission and scope.has_capability("price.view_cost", res.property)
	if _check_permission:
		scope.require("reservation.modify", res.property)
		if basis == "HISTORICAL_SALE_DATE":
			scope.require("price.override", res.property)
	if basis not in BASES:
		frappe.throw(_("Unknown pricing basis {0}.").format(basis))
	if basis == "HISTORICAL_SALE_DATE":
		basis_sale_at = str(historical_sale_at(basis_sale_at))
	elif basis_sale_at not in (None, ""):
		# never silently ignored: a sale date prices only on the historical sale date basis
		frappe.throw(_("A sale date is used only with the historical sale date basis."))
	else:
		basis_sale_at = None
	if res.status in ("Cancelled", "No Show", "Checked Out"):
		frappe.throw(_("A {0} reservation cannot be modified.").format(res.status.lower()))
	if res.get("tex_pricing_source") == "Channel":
		# its price and its stay are the channel's: changes arrive from the channel (G-69)
		frappe.throw(_("This booking came from a channel: change it in the channel, and the change arrives here."))
	changes = {k: v for k, v in (changes or {}).items() if v is not None}
	if "sale_at" in changes:
		frappe.throw(_("A change has no sale time of its own: to price it as if sold at another time, "
		               "choose the historical sale date basis and its date."))
	if _check_permission:
		require_product_channel(res, changes)
	if "drop_addons" in changes:
		raw = changes.pop("drop_addons")
		ids = sorted({raw} if isinstance(raw, str) else {str(x) for x in raw or []})
		if ids:
			changes["drop_addons"] = ids
	placeholder_at = now_datetime()
	req, snap = build_changed_request(res, changes, placeholder_at)
	version = None
	try:
		version, at, how = _resolve(res, snap, req, basis, basis_sale_at, _sale_at)
		req, _s = build_changed_request(res, changes, at)
		# the booking's own coupon uses never count against it when it is repriced (G-09); the
		# ORIGINAL_* bases convert with the rates the sale recorded (G-56); the version the stay
		# was sold on prices it only while its payload is the one the sale recorded (G-73); a
		# minimum basket is the booking's, with its other rooms as they are priced now (G-84)
		quote, terms = booked_price(res, version, req, exclude_booking=res.tex_booking, exclude_reservation=res.name,
		                            gkey=booking_svc.booking_guest_key(res.tex_booking, res.guest),
		                            fx_pins=fx_pins(res, snap, basis),
		                            expected_hash=sold_terms.expected_hash(res, snap, version))
	except contracts.PayloadMismatch as e:
		sold_terms.refuse(res, snap, e, use="reprice", basis=basis, version=version)
	req = quote.request
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
	# restrictions refuse a change as they refuse a new booking, for what it newly takes (G-48); a
	# stored proposal (a guest's change paid or approved later) is judged as of when it was priced
	sale_day = get_datetime(_sale_at).date() if _sale_at else now.date()
	violations = [v.to_dict() for v in restriction_violations(res, snap, req, terms.contract_id, sale_day)]
	warnings.extend(violations)
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
	# sellable but for the restrictions: what staff who may edit restrictions can override (G-48)
	sellable_otherwise = quote.sellable and not any(w.get("code") == "SOLD_OUT" for w in warnings) \
		and not (not _check_permission and any(w.get("code") == "ADDON_OUTSIDE_STAY" for w in warnings))
	proposal = {
		"reservation": res.name, "modified": str(res.modified), "changes": changes, "basis": basis,
		"basis_sale_at": basis_sale_at, "version": version,
		"new_total": to_str(new_total) if quote.sellable else None, "currency": quote.currency,
		# the moment the price was computed: a paid guest change re-derives it as of then (G-45)
		"pricing_sale_at": str(at),
		# who may apply it (G-51): staff only their own proposal at this hotel; a guest's only
		# through the manage page of this booking
		"origin": "staff" if _check_permission else "guest", "by": frappe.session.user,
		"property": res.property, "booking": res.tex_booking,
	}
	return {
		"reservation": res.name,
		"basis": basis, "basis_detail": how, "pricing_sale_at": str(at),
		"old": {"total": to_str(old_total), "currency": old_ccy, "request": snap["request"],
		        "contract": snap.get("contract"), "lines": snap.get("lines"), "totals": old_totals},
		"proposed": new,
		"sellable": sellable_otherwise and not violations,
		# the restrictions the change breaks; staff with ``restriction.edit`` may override them when
		# applying (with the reason, audited); a guest never (G-48, ADR-057)
		"restrictions": violations,
		"sellable_ignoring_restrictions": sellable_otherwise,
		"restriction_override": bool(violations) and sellable_otherwise and _check_permission
		and scope.has_capability("restriction.edit", res.property),
		"difference": to_str(diff) if diff is not None else None,
		"currency_changed": quote.currency != old_ccy,
		"warnings": warnings,
		"proposal_token": quoting.sign({**proposal, "kind": "proposal",
		                                "exp": add_to_date(now, minutes=PROPOSAL_TTL_MINUTES).isoformat()}),
	}


def approval_refusal(contract: str | None, *, lock: bool = False) -> contracts.ContractNotOnSale | None:
	"""Why staff cannot approve a guest's change priced on ``contract`` now: the contract is not
	Active (suspended, archived), or None (G-51 review M1). ``lock``: read under a shared row
	lock (``contracts.not_on_sale``)."""
	stopped = contracts.not_on_sale(contract, lock=lock) if contract else None
	if not stopped:
		return None
	code, status = frappe.db.get_value("TEX Contract", contract, ["contract_code", "status"]) or (contract, None)
	return type(stopped)(_("{0} no longer sells ({1}): this change cannot be approved at the price the guest "
	                       "was shown. Reject the request, or change the reservation yourself.").format(
		code, _(status or "—")))


def require_proposer(p: dict, *, guest: bool) -> None:
	"""A proposal token is applied only by whoever made it (G-51, ADR-054): through the guest
	path only a guest's own proposal (the manage token proves the booking); by staff only the
	user who proposed it (``apply`` also checks the hotel and booking). A token made before
	G-51 names nobody and is refused: it expired within ``PROPOSAL_TTL_MINUTES`` anyway."""
	if guest:
		if p.get("origin") != "guest":
			frappe.throw(_("This change was not proposed on your booking page."), frappe.PermissionError)
		return
	if p.get("origin") != "staff" or p.get("by") != frappe.session.user:
		frappe.throw(_("This proposal was made by another user: propose the change again."),
		             frappe.PermissionError)


def apply(proposal_token: str | None, *, reason: str, override_amount=None, source: str = "Desk",
          override_restrictions: bool = False, _guest_authorized: bool = False, _proposal: dict | None = None,
          _from_payment: bool = False, _paid_at=None) -> dict:
	"""``_guest_authorized``: set only by the self-service API after verifying the
	guest's manage token owns the proposal's reservation. Guests can never override.

	``_proposal``: a proposal the server verified and stored (a TEX Guest Change Request); it
	is re-derived at the moment it was priced, so the price the guest accepted is the price
	applied (G-45). ``_from_payment``: the guest paid for it (at ``_paid_at``, when the gateway
	confirmed the charge); a payment made by the proposal's payment deadline (its expiry plus
	``PAYMENT_GRACE_MINUTES``) applies it, whenever the job applying it runs.

	A proposal token is applied only by whoever proposed it (``require_proposer``; G-51). The
	HISTORICAL_SALE_DATE basis and a manual ``override_amount`` need ``price.override`` at the
	hotel here too, whoever proposed the change; guests apply only CURRENT proposals. A stored
	proposal approved by staff (not paid) is refused while its contract does not sell
	(``approval_refusal``; G-51 review).

	A change the restrictions refuse is refused (G-48, ADR-057). ``override_restrictions``: staff
	applying their own proposal who hold ``restriction.edit`` sell it anyway; the reason is
	required, the revision records the restrictions overridden and an audit event
	(``reservation.restriction_override``) names them. Never on a guest's path.

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
		require_proposer(p, guest=_guest_authorized)
		pin = None
	# the booking first, then the reservation as it is now (a locking read, not the caller's
	# snapshot of it): the lock order of every change to a TEX booking
	booking = frappe.db.get_value("Reservation", p["reservation"], "tex_booking")
	if booking:
		frappe.db.get_value("TEX Booking", booking, "name", for_update=True)
	res = frappe.get_doc("Reservation", p["reservation"], for_update=True)
	if _proposal is None and (p.get("property") != res.property or p.get("booking") != res.tex_booking):
		frappe.throw(_("This proposal was made for another reservation: propose the change again."),
		             frappe.PermissionError)
	if _guest_authorized:
		if override_amount not in (None, ""):
			frappe.throw(_("Guests cannot override prices."), frappe.PermissionError)
		if p["basis"] != "CURRENT":
			# a guest changes the stay at today's prices, the only basis the manage page proposes
			frappe.throw(_("This change cannot be made online. Please contact the hotel."), frappe.PermissionError)
	else:
		scope.require("reservation.modify", res.property)
		# whoever applies a proposal needs the right to make it: a token carries the change,
		# not the entitlement of whoever proposed it
		require_product_channel(res, p["changes"])
		if p["basis"] == "HISTORICAL_SALE_DATE":
			# a price no longer on sale is an override of today's: checked again here, not only on
			# propose (G-51); a manual override amount is checked below
			scope.require("price.override", res.property)
	if override_restrictions:
		# only staff applying their own proposal, who may change the restrictions themselves (G-48)
		if _guest_authorized or _proposal is not None:
			frappe.throw(_("Restrictions cannot be overridden here."), frappe.PermissionError)
		scope.require("restriction.edit", res.property)
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
	overridden_restrictions = result["restrictions"] if override_restrictions and \
		result["sellable_ignoring_restrictions"] else []
	if not result["sellable"] and not overridden_restrictions:
		why = "; ".join(w["message"] for w in result["warnings"]) or result["proposed"].get("reasons")
		frappe.throw(_("The modified stay cannot be sold: {0}").format(
			guest_reason(str(why)) if _guest_authorized else why))
	new = result["proposed"]
	if _proposal is not None and not _from_payment:
		# staff approving a guest's request (ADR-044), maybe days later: at the price the guest
		# was shown, on the contract that priced it, and only while that contract sells; a stop
		# sale since is never bypassed (ADR-045; G-51 review M1). The paid path is bounded by its
		# payment deadline instead. A shared lock, as a booking takes: a suspend waits for it.
		stopped = approval_refusal(new["contract"]["contract"], lock=True)
		if stopped:
			frappe.throw(str(stopped), type(stopped))
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
		"tex_fx_rate": db_dec((new.get("fx") or {}).get("sell_rate") or 1),   # 9 places, as stored (G-72)
		# priced_at: the moment it was priced on its basis (G-73), next to when it was accepted
		"tex_pricing_snapshot": json.dumps({**new, "accepted_at": str(now_datetime()),
		                                    "priced_at": str(get_datetime(result["pricing_sale_at"])),
		                                    "original_priced_at": str(original_priced_at(res, snap)),
		                                    "original_fx_rates": original_fx(res, snap),
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
	if p["basis"] == "HISTORICAL_SALE_DATE":
		types.add("Sale Date")          # priced as if sold at another time
	if override_amount not in (None, ""):
		types.add("Price Override")
	change_type = types.pop() if len(types) == 1 else ("Multiple" if types else "Guest Request"
	                                                    if source == "Guest" else "Multiple")
	old_total = D(result["old"]["total"])
	overridden = override_amount not in (None, "")
	# an override's revision is MANUAL at the amount set; "priced" keeps the basis and the total the
	# engine computed (basis_sale_at is that basis's sale time), so the revision alone says both
	priced = {"priced": {"basis": p["basis"], "total": to_str(new_total)}} if overridden else {}
	rev = booking_svc._record_revision(
		res.name, res.tex_booking, change_type=change_type, old_amount=old_total, new_amount=final_total,
		currency=ccy, basis="MANUAL" if overridden else p["basis"],
		basis_sale_at=result["pricing_sale_at"], reason=reason,
		changes=changed_fields | {"requested": changes} | priced
		| ({"restrictions_overridden": overridden_restrictions} if overridden_restrictions else {}),
		before=snap, after=json.loads(res.tex_pricing_snapshot), source=source,
		override=final_total if overridden else None)
	if overridden_restrictions:
		audit("reservation.restriction_override", reference_doctype="Reservation", reference_name=res.name,
		      property=res.property, new={"restrictions": overridden_restrictions, "revision": rev}, reason=reason)
	if res.tex_booking:
		booking_svc.sync_redemptions(res.tex_booking)
		booking_svc._refresh_booking_after_change(res.tex_booking)
	audit("reservation.modify", reference_doctype="Reservation", reference_name=res.name, property=res.property,
	      old={"total": to_str(old_total), **{k: v[0] for k, v in changed_fields.items()}},
	      new={"total": to_str(final_total), **{k: v[1] for k, v in changed_fields.items()}, "revision": rev,
	           "basis": p["basis"], "pricing_sale_at": result["pricing_sale_at"],
	           # an override records what the engine computed next to the amount staff set
	           **({"computed_total": to_str(new_total), "override": True}
	              if override_amount not in (None, "") else {})}, reason=reason)
	return {"reservation": res.name, "revision": rev, "old_total": to_str(old_total),
	        "new_total": to_str(final_total), "difference": to_str(final_total - old_total), "currency": ccy}


def simulate(reservation: str, sale_at) -> dict:
	"""What would this exact stay have cost if sold at ``sale_at``? Read-only (R-22).

	Deterministic (G-51, ADR-054): everything it reads is as of ``sale_at``, so the answer for a
	past moment does not change with what happened since:
	- the contracts Active then (``candidate_contracts(historical=True)``), the version live then
	  and its frozen payload and selling terms (G-50);
	- markups, promotions and their limits, extras, the tax policy, FX policies and rates (G-20);
	- coupon uses held then: made by then and not given back by then, this booking's own excluded.
	The stay itself is the reservation's (its request, channel and guest), and so is its booking: a minimum
	basket is judged with the other rooms as recorded with the stay (G-84). Not checked:
	availability, restrictions and the capacity of limited extras (the stay is sold already).
	``sale_at`` must be a valid time, not in the future; ``price.view`` and ``reservation.view``
	at the hotel (it writes nothing: pricing a change as of a past time needs ``price.override``)."""
	res = frappe.get_doc("Reservation", reservation)
	scope.require("price.view", res.property)
	scope.require("reservation.view", res.property)
	snap = _snapshot(res)
	at = past_sale_time(sale_at, missing=_("Choose the sale time to simulate."),
	                    future=_("A simulated sale time cannot be in the future."))
	req = serialize.request_from_dict({**snap["request"], "sale_at": at.isoformat(), "booking_basket": None,
	                                    "booking_rooms": 1})
	try:
		cands = contracts.candidate_contracts(res.property, req.market, req.channel, at, historical=True)
	except contracts.PayloadMismatch as e:        # a live payload failing its integrity check (G-73)
		sold_terms.refuse(res, snap, e, use="simulate")
	if not cands:
		return {"sellable": False, "simulated_sale_at": str(at),
		        "reasons": [{"code": "NO_CONTRACT", "message": _("No contract was on sale at that time.")}]}
	pick = next((c for c in cands if c[0].name == snap["contract"]["contract"]), cands[0])
	# a minimum basket is the booking's: with the other rooms as recorded with this stay when it was
	# last priced, not as they are now, so the answer for a past moment never changes (G-51, G-84)
	try:
		quote, _terms = booked_price(res, pick[1], req, others=recorded_others(snap), exclude_booking=res.tex_booking,
		                             check_capacity=False, gkey=booking_svc.booking_guest_key(res.tex_booking, res.guest),
		                             usage_at=at, expected_hash=sold_terms.expected_hash(res, snap, pick[1]))
	except contracts.PayloadMismatch as e:
		sold_terms.refuse(res, snap, e, use="simulate", version=pick[1])
	internal = scope.has_capability("price.view_cost", res.property)
	actual = from_db(res.tex_total_amount or res.amount_after_tax, res.tex_currency or "EUR")
	return {
		"reservation": res.name, "simulated_sale_at": str(at), "contract_version": pick[1],
		"contract": {"contract": pick[0].name, "code": pick[0].contract_code, "status_now": pick[0].status_now},
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

