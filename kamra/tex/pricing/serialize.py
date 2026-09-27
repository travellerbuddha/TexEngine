"""Canonical (de)serialisation of contract payloads and pricing requests.

The published payload of a Contract Version is canonical JSON (sorted keys, compact
separators, decimals as normalised strings). ``payload_hash`` is the sha256 of that
text, so any byte-level change to sold terms is detectable (ADR-004).
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from datetime import date, datetime
from decimal import Decimal

from kamra.tex.money import D, D_or_none, to_str, to_str6
from kamra.tex.pricing import policy_money
from kamra.tex.pricing.enums import (
	AgeBasis,
	ChildOrdering,
	Level,
	OccTarget,
	Op,
	PricingBasis,
	PromoAppliesTo,
	PromoStage,
	PromoValueType,
	RoomBasisExtraUnit,
	StackingMode,
	StayMatch,
)
from kamra.tex.pricing.model import (
	AgeBand,
	BoardRule,
	ChildSpec,
	ContractTerms,
	ExtraRequest,
	OccupancyRule,
	Period,
	PricingError,
	Promotion,
	RatePlanTerms,
	RoomRule,
	RoomSpec,
	StayRequest,
)
from kamra.tex.pricing.promotions import code_key, offer_currency

PAYLOAD_SCHEMA = "tex.contract.v1"


# ─── canonical json ──────────────────────────────────────────────────────


def dec_str(v) -> str | None:
	if v is None or v == "":
		return None
	d = D(v)
	if d == d.to_integral_value():
		return format(d.quantize(Decimal(1)), "f")
	return format(d.normalize(), "f")


def _default(o):
	if isinstance(o, Decimal):
		return dec_str(o)
	if isinstance(o, datetime):
		return o.isoformat()
	if isinstance(o, date):
		return o.isoformat()
	if isinstance(o, frozenset | set):
		return sorted(o)
	raise TypeError(f"not serialisable: {type(o).__name__}")


def canonical_json(obj) -> str:
	return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=_default)


def payload_hash(payload: dict) -> str:
	return hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()


def _d(v) -> date | None:
	if v in (None, ""):
		return None
	if isinstance(v, datetime):
		return v.date()
	if isinstance(v, date):
		return v
	return date.fromisoformat(str(v)[:10])


def _set(v) -> frozenset[str] | None:
	if v is None:
		return None
	if isinstance(v, str):
		v = [x.strip() for x in v.replace("\n", ",").split(",") if x.strip()]
	return frozenset(str(x) for x in v)


def _int(v) -> int | None:
	if v in (None, ""):
		return None
	return int(v)


# ─── promotions ──────────────────────────────────────────────────────────


def promotion_to_dict(p: Promotion) -> dict:
	return {
		"id": p.promo_id, "name": p.name, "kind": p.kind, "value_type": p.value_type.value,
		"value": dec_str(p.value), "stage": p.stage.value, "applies_to": p.applies_to.value,
		"currency": p.currency, "code": p.code,
		"sale_from": p.sale_from, "sale_to": p.sale_to, "stay_from": p.stay_from, "stay_to": p.stay_to,
		"stay_match": p.stay_match.value, "min_nights": p.min_nights, "max_nights": p.max_nights,
		"min_lead_days": p.min_lead_days, "max_lead_days": p.max_lead_days,
		"markets": p.markets, "channels": p.channels, "room_types": p.room_types, "boards": p.boards,
		"rate_plans": p.rate_plans, "contracts": p.contracts, "requires_extras": p.requires_extras,
		"member_only": p.member_only, "min_basket": dec_str(p.min_basket), "stackable": p.stackable,
		"exclusive": p.exclusive, "priority": p.priority, "group": p.group,
		"free_nights_stay": p.free_nights_stay, "free_nights_pay": p.free_nights_pay,
		"value_added": p.value_added, "source": p.source, "usage_limit": p.usage_limit,
		"per_guest_limit": p.per_guest_limit,
	}


def promotion_from_dict(d: dict) -> Promotion:
	return Promotion(
		promo_id=str(d["id"]), name=d.get("name") or str(d["id"]),
		value_type=PromoValueType(d.get("value_type") or "PERCENT"), value=D(d.get("value")),
		kind=d.get("kind") or "PROMOTION", stage=PromoStage(d.get("stage") or "SELL"),
		applies_to=PromoAppliesTo(d.get("applies_to") or "ACCOMMODATION"),
		currency=d.get("currency") or None, code=code_key(d.get("code")),
		sale_from=_d(d.get("sale_from")), sale_to=_d(d.get("sale_to")),
		stay_from=_d(d.get("stay_from")), stay_to=_d(d.get("stay_to")),
		stay_match=StayMatch(d.get("stay_match") or "ANY_NIGHT"),
		min_nights=_int(d.get("min_nights")), max_nights=_int(d.get("max_nights")),
		min_lead_days=_int(d.get("min_lead_days")), max_lead_days=_int(d.get("max_lead_days")),
		markets=_set(d.get("markets")), channels=_set(d.get("channels")), room_types=_set(d.get("room_types")),
		boards=_set(d.get("boards")), rate_plans=_set(d.get("rate_plans")), contracts=_set(d.get("contracts")),
		requires_extras=_set(d.get("requires_extras")), member_only=bool(d.get("member_only")),
		min_basket=D_or_none(d.get("min_basket")), stackable=bool(d.get("stackable", True)),
		exclusive=bool(d.get("exclusive")), priority=int(d.get("priority") or 0), group=d.get("group") or None,
		free_nights_stay=_int(d.get("free_nights_stay")), free_nights_pay=_int(d.get("free_nights_pay")),
		value_added=d.get("value_added") or "", source=d.get("source") or "promotion",
		usage_limit=_int(d.get("usage_limit")), per_guest_limit=_int(d.get("per_guest_limit")),
	)


# ─── contract payload ────────────────────────────────────────────────────


def terms_to_payload(t: ContractTerms) -> dict:
	return {
		"schema": PAYLOAD_SCHEMA,
		"contract": {
			"id": t.contract_id, "code": t.contract_code, "name": t.contract_name, "property": t.property,
			"market": t.market, "currency": t.currency, "basis": t.basis.value,
			"sale_from": t.sale_from, "sale_to": t.sale_to, "stay_from": t.stay_from, "stay_to": t.stay_to,
			"channels": t.channels, "priority": t.priority, "sell_currency": t.sell_currency,
		},
		"version": {"id": t.version_id, "no": t.version_no},
		"settings": {
			"child_ordering": t.child_ordering.value, "age_basis": t.age_basis.value,
			"children_over_max_as_adults": t.children_over_max_as_adults,
			"infants_count_as_occupants": t.infants_count_as_occupants,
			"prices_include_tax": t.prices_include_tax, "stacking": t.stacking.value,
			"room_basis_extra_unit": t.room_basis_extra_unit.value,
			"room_basis_children_fill_included": t.room_basis_children_fill_included,
			"occupancy_precedence": t.occupancy_precedence,
			# only when infants are not children (O-2, ADR-067): every payload frozen so far, and its
			# hash, stays as it was
			**({} if t.infants_count_as_children else {"infants_count_as_children": False}),
		},
		"rooms": [
			{"room_type": r.room_type, "name": r.name, "max_adults": r.max_adults, "max_children": r.max_children,
			 "max_occupants": r.max_occupants, "min_adults": r.min_adults, "included_adults": r.included_adults}
			for r in sorted(t.rooms.values(), key=lambda r: r.room_type)
		],
		"periods": [
			{"code": p.code, "name": p.name, "start": p.start, "end": p.end,
			 "weekdays": sorted(p.weekdays) if p.weekdays is not None else None,
			 "adjustment_op": p.adjustment_op.value if p.adjustment_op else None,
			 "adjustment_value": dec_str(p.adjustment_value), "priority": p.priority}
			for p in t.periods
		],
		"room_rules": [
			{"id": r.rule_id, "room_type": r.room_type, "period": r.period, "op": r.op.value,
			 "value": dec_str(r.value), "base_room_type": r.base_room_type}
			for r in t.room_rules
		],
		"occupancy_rules": [
			{"id": r.rule_id, "target": r.target.value, "op": r.op.value, "value": dec_str(r.value),
			 "position": r.position, "age_band": r.age_band, "room_type": r.room_type, "period": r.period,
			 "adults": r.adults, "children": r.children, "is_override": r.is_override,
			 "base_level": r.base_level.name, "scope_weight": r.scope_weight, "source": r.source, "note": r.note}
			for r in t.occupancy_rules
		],
		"age_bands": [
			{"code": b.code, "label": b.label, "from_months": b.from_months, "to_months": b.to_months,
			 "is_infant": b.is_infant}
			for b in t.age_bands
		],
		"boards": [
			{"id": b.rule_id, "board": b.board, "is_base": b.is_base, "op": b.op.value,
			 "adult_amount": dec_str(b.adult_amount), "child_percent": dec_str(b.child_percent),
			 "band_percents": {k: dec_str(v) for k, v in b.band_percents}, "infant_free": b.infant_free,
			 "room_type": b.room_type, "period": b.period, "label": b.label}
			for b in t.boards
		],
		"rate_plans": [
			{"code": r.code, "name": r.name, "op": r.op.value if r.op else None, "value": dec_str(r.value),
			 "refundable": r.refundable, "boards": r.boards, "cancellation_policy": r.cancellation_policy,
			 "payment_policy": r.payment_policy, "inclusions": list(r.inclusions)}
			for r in sorted(t.rate_plans.values(), key=lambda r: r.code)
		],
		"offers": [promotion_to_dict(p) for p in t.offers],
	}


def normalise_payload(payload: dict) -> dict:
	"""Round-trip through JSON so dates/decimals take their canonical string form."""
	return json.loads(canonical_json(payload))


def _offer(o: dict, contract_currency: str) -> Promotion:
	"""A contract offer of a frozen payload; a fixed amount frozen without a currency (before K-1)
	is in the contract's currency. The payload itself is never rewritten."""
	p = promotion_from_dict({**o, "source": "contract"})
	return replace(p, currency=offer_currency(p.value_type, p.currency, contract_currency))


def terms_from_payload(payload: dict, payload_hash_value: str | None = None) -> ContractTerms:
	if payload.get("schema") != PAYLOAD_SCHEMA:
		raise PricingError(f"unsupported contract payload schema {payload.get('schema')!r}")
	c, v, s = payload["contract"], payload["version"], payload.get("settings") or {}
	rooms = {
		r["room_type"]: RoomSpec(
			room_type=r["room_type"], name=r.get("name") or r["room_type"], max_adults=int(r["max_adults"]),
			max_children=int(r.get("max_children") or 0), max_occupants=int(r["max_occupants"]),
			min_adults=int(r.get("min_adults") or 1), included_adults=int(r.get("included_adults") or 2))
		for r in payload.get("rooms") or []
	}
	periods = tuple(
		Period(code=p["code"], name=p.get("name") or p["code"], start=_d(p["start"]), end=_d(p["end"]),
		       weekdays=frozenset(int(x) for x in p["weekdays"]) if p.get("weekdays") is not None else None,
		       adjustment_op=Op(p["adjustment_op"]) if p.get("adjustment_op") else None,
		       adjustment_value=D_or_none(p.get("adjustment_value")), priority=int(p.get("priority") or 0))
		for p in payload.get("periods") or []
	)
	room_rules = tuple(
		RoomRule(rule_id=str(r["id"]), room_type=r["room_type"], period=r.get("period") or None, op=Op(r["op"]),
		         value=D_or_none(r.get("value")), base_room_type=r.get("base_room_type") or None)
		for r in payload.get("room_rules") or []
	)
	occ = tuple(
		OccupancyRule(
			rule_id=str(r["id"]), target=OccTarget(r["target"]), op=Op(r["op"]), value=D_or_none(r.get("value")),
			position=_int(r.get("position")), age_band=r.get("age_band") or None,
			room_type=r.get("room_type") or None, period=r.get("period") or None,
			adults=_int(r.get("adults")), children=_int(r.get("children")),
			is_override=bool(r.get("is_override")), base_level=Level[r.get("base_level") or "VERSION"],
			source=r.get("source") or "version", note=r.get("note") or "",
			scope_weight=int(r.get("scope_weight") or 0))
		for r in payload.get("occupancy_rules") or []
	)
	bands = tuple(
		AgeBand(code=b["code"], label=b.get("label") or b["code"], from_months=int(b["from_months"]),
		        to_months=int(b["to_months"]), is_infant=bool(b.get("is_infant")))
		for b in payload.get("age_bands") or []
	)
	board_rules = tuple(
		BoardRule(rule_id=str(b["id"]), board=b["board"], is_base=bool(b.get("is_base")),
		          op=Op(b.get("op") or "ADD"), adult_amount=D(b.get("adult_amount")),
		          child_percent=D(b.get("child_percent") if b.get("child_percent") is not None else 50),
		          band_percents=tuple(sorted((k, D(val)) for k, val in (b.get("band_percents") or {}).items())),
		          infant_free=bool(b.get("infant_free", True)), room_type=b.get("room_type") or None,
		          period=b.get("period") or None, label=b.get("label") or "")
		for b in payload.get("boards") or []
	)
	# a policy's fixed amounts frozen without a currency (before ADR-067) are in the contract's
	# currency, as K-1 reads a fixed offer; the payload itself is never rewritten
	rate_plans = {
		r["code"]: RatePlanTerms(
			code=r["code"], name=r.get("name") or r["code"], op=Op(r["op"]) if r.get("op") else None,
			value=D_or_none(r.get("value")), refundable=bool(r.get("refundable", True)),
			boards=_set(r.get("boards")),
			cancellation_policy=policy_money.with_currency(r.get("cancellation_policy"), c["currency"]),
			payment_policy=policy_money.with_currency(r.get("payment_policy"), c["currency"]),
			inclusions=tuple(r.get("inclusions") or ()))
		for r in payload.get("rate_plans") or []
	}
	return ContractTerms(
		contract_id=str(c["id"]), contract_code=c.get("code") or str(c["id"]), contract_name=c.get("name") or "",
		version_id=str(v["id"]), version_no=int(v["no"]),
		payload_hash=payload_hash_value or payload_hash(payload),
		property=c["property"], market=c["market"], currency=c["currency"].upper(),
		basis=PricingBasis(c.get("basis") or "PERSON"), rooms=rooms, periods=periods, room_rules=room_rules,
		occupancy_rules=occ, age_bands=bands, boards=board_rules, rate_plans=rate_plans,
		offers=tuple(_offer(o, c["currency"]) for o in payload.get("offers") or []),
		sale_from=_d(c.get("sale_from")), sale_to=_d(c.get("sale_to")),
		stay_from=_d(c.get("stay_from")), stay_to=_d(c.get("stay_to")), channels=_set(c.get("channels")),
		priority=_int(c.get("priority")),
		sell_currency=(c.get("sell_currency") or "").upper() or None,
		child_ordering=ChildOrdering(s.get("child_ordering") or "OLDEST_FIRST"),
		age_basis=AgeBasis(s.get("age_basis") or "ARRIVAL"),
		children_over_max_as_adults=bool(s.get("children_over_max_as_adults", True)),
		infants_count_as_occupants=bool(s.get("infants_count_as_occupants", True)),
		infants_count_as_children=bool(s.get("infants_count_as_children", True)),
		prices_include_tax=bool(s.get("prices_include_tax", True)),
		stacking=StackingMode(s.get("stacking") or "SEQUENTIAL"),
		room_basis_extra_unit=RoomBasisExtraUnit(s.get("room_basis_extra_unit") or "PER_PERSON_SHARE"),
		room_basis_children_fill_included=bool(s.get("room_basis_children_fill_included")),
		# frozen before occupancy precedence v2 → priced as sold (ADR-043)
		occupancy_precedence=int(s.get("occupancy_precedence") or 1),
	)


# ─── request ─────────────────────────────────────────────────────────────


def request_to_dict(r: StayRequest) -> dict:
	return {
		"property": r.property, "room_type": r.room_type, "board": r.board, "rate_plan": r.rate_plan,
		"check_in": r.check_in.isoformat(), "check_out": r.check_out.isoformat(), "adults": r.adults,
		"children": [{"age": c.age, "dob": c.dob.isoformat() if c.dob else None, "age_months": c.age_months}
		             for c in r.children],
		"sale_at": r.sale_at.isoformat(), "market": r.market, "channel": r.channel,
		"sell_currency": r.sell_currency, "promo_codes": list(r.promo_codes), "member": r.member,
		"extras": [{"code": e.code, "quantity": e.quantity, "service_dates": [d.isoformat() for d in e.service_dates]}
		           for e in r.extras],
		"room_index": r.room_index,
		# only for a room priced in a booking of several rooms (G-84), so a room priced alone keeps
		# the request it always had
		**({"booking_basket": to_str(r.booking_basket), "booking_rooms": r.booking_rooms}
		   if r.booking_basket is not None else {}),
		**({"booking_baskets": {p: {"basket": to_str6(b), "rooms": n} for p, b, n in r.booking_baskets}}
		   if r.booking_baskets else {}),
	}


def request_from_dict(d: dict) -> StayRequest:
	sale_at = d["sale_at"]
	if isinstance(sale_at, str):
		sale_at = datetime.fromisoformat(sale_at)
	return StayRequest(
		property=d["property"], room_type=d["room_type"], board=d["board"], rate_plan=d.get("rate_plan") or None,
		check_in=_d(d["check_in"]), check_out=_d(d["check_out"]), adults=int(d["adults"]),
		children=tuple(ChildSpec(age=_int(c.get("age")), dob=_d(c.get("dob")), age_months=_int(c.get("age_months")))
		               for c in d.get("children") or []),
		sale_at=sale_at, market=d["market"], channel=d["channel"], sell_currency=d["sell_currency"],
		promo_codes=tuple(d.get("promo_codes") or ()), member=bool(d.get("member")),
		extras=tuple(ExtraRequest(code=e["code"], quantity=int(e.get("quantity") or 1),
		                          service_dates=tuple(_d(x) for x in e.get("service_dates") or []))
		             for e in d.get("extras") or []),
		room_index=int(d.get("room_index") or 0),
		booking_basket=D(d["booking_basket"]) if d.get("booking_basket") not in (None, "") else None,
		booking_rooms=int(d.get("booking_rooms") or 1),
		booking_baskets=tuple(sorted((str(p), D(v["basket"]), int(v["rooms"]))
		                             for p, v in (d.get("booking_baskets") or {}).items())),
	)
