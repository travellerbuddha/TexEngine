"""Contract & contract-version service (ADR-004).

Draft versions are edited through their child tables. ``publish`` validates the
draft, resolves everything it inherits (hotel/market pricing policy, room
capacities, rate-plan policies) and freezes the canonical payload + sha256 hash.
Pricing always runs on that frozen payload.
"""

from __future__ import annotations

import json
from datetime import datetime

import frappe
from frappe import _
from frappe.utils import get_datetime, getdate, now_datetime

from kamra.tex.money import D, D_or_none
from kamra.tex.pricing import ages as age_math
from kamra.tex.pricing import serialize, validate, versions
from kamra.tex.pricing.enums import (
	AgeBasis,
	ChildOrdering,
	Level,
	OccTarget,
	Op,
	PricingBasis,
	PromoStage,
	PromoValueType,
	RoomBasisExtraUnit,
	StackingMode,
	StayMatch,
)
from kamra.tex.pricing.model import (
	AgeBand,
	BoardRule,
	ContractTerms,
	OccupancyRule,
	Period,
	Promotion,
	RatePlanTerms,
	RoomRule,
	RoomSpec,
)
from kamra.tex.security import scope
from kamra.tex.security.audit import audit

WEEKDAYS = {"mon": 0, "tue": 1, "wed": 2, "thu": 3, "fri": 4, "sat": 5, "sun": 6}


# ─── parsing helpers ─────────────────────────────────────────────────────


def parse_weekdays(text: str | None) -> frozenset[int] | None:
	if not text or not text.strip():
		return None
	out = set()
	for part in text.replace(";", ",").split(","):
		p = part.strip().lower()[:3]
		if not p:
			continue
		if p in ("wee",):   # weekend / weekday shorthands
			raise frappe.ValidationError(_("Use explicit days, e.g. Fri,Sat"))
		if p not in WEEKDAYS:
			frappe.throw(_("Unknown weekday '{0}'").format(part.strip()))
		out.add(WEEKDAYS[p])
	return frozenset(out) or None


def parse_combination(text: str | None) -> tuple[int | None, int | None]:
	"""'2+1' → (2, 1); '2+*' → (2, None); '*+1' → (None, 1); '' → (None, None)."""
	if not text or not text.strip():
		return None, None
	t = text.replace(" ", "").upper().replace("A", "").replace("C", "")
	if "+" not in t:
		frappe.throw(_("Combination must look like 2+1 (adults+children), got '{0}'").format(text))
	a, c = t.split("+", 1)
	conv = lambda x: None if x in ("*", "") else int(x)  # noqa: E731
	try:
		return conv(a), conv(c)
	except ValueError:
		frappe.throw(_("Combination must look like 2+1 (adults+children), got '{0}'").format(text))


def _csv(text) -> frozenset[str] | None:
	if not text:
		return None
	items = [x.strip() for x in str(text).replace("\n", ",").split(",") if x.strip()]
	return frozenset(items) or None


def _nz(v) -> int | None:
	return int(v) if v else None


# ─── inherited policy ────────────────────────────────────────────────────


def _policy_for(property: str, market: str, at: datetime):
	"""Most specific live pricing policy: hotel+market > hotel > market > global."""
	from kamra.tex.commercial.revisions import as_of

	rows = as_of("TEX Pricing Policy", at, fields=("name", "property", "market"))
	best, best_rank = None, -1
	for r in rows:
		if r.property and r.property != property:
			continue
		if r.market and r.market != market:
			continue
		rank = (2 if r.property else 0) + (1 if r.market else 0)
		if rank > best_rank:
			best, best_rank = r, rank
	if not best:
		return None, None
	level = Level.HOTEL if best.property else (Level.MARKET if best.market else Level.GLOBAL)
	if best.property and best.market:
		level = Level.MARKET
	return frappe.get_doc("TEX Pricing Policy", best.name), level


def _bands(rows) -> tuple[AgeBand, ...]:
	return tuple(
		AgeBand(code=r.band_code.strip().upper(), label=r.label or r.band_code,
		        from_months=age_math.years_to_months(r.from_age or 0),
		        to_months=age_math.years_to_months(r.to_age or 0), is_infant=bool(r.is_infant))
		for r in rows)


def _occ_rules(rows, *, base_level: Level, source: str) -> tuple[OccupancyRule, ...]:
	out = []
	for r in rows:
		adults, children = parse_combination(r.combination)
		out.append(OccupancyRule(
			rule_id=r.name, target=OccTarget(r.target), op=Op(r.op),
			value=None if r.op == "INHERIT" else D(r.value),
			position=_nz(r.position), age_band=(r.age_band or "").strip().upper() or None,
			room_type=r.room_type or None, period=(r.period_code or "").strip() or None,
			adults=adults, children=children, is_override=bool(r.is_override), base_level=base_level,
			source=source, note=r.note or ""))
	return tuple(out)


# ─── build terms from a draft ────────────────────────────────────────────


def _cancellation_policy(name: str | None) -> dict | None:
	if not name:
		return None
	p = frappe.get_doc("TEX Cancellation Policy", name)
	return {"id": p.name, "name": p.policy_name, "refundable": bool(p.refundable),
	        "rules": [{"days_before_arrival": int(r.days_before_arrival or 0), "penalty_type": r.penalty_type,
	                   "penalty_value": serialize.dec_str(D(r.penalty_value))}
	                  for r in sorted(p.rules, key=lambda r: -(r.days_before_arrival or 0))],
	        "no_show": {"type": p.no_show_type, "value": serialize.dec_str(D(p.no_show_value))},
	        "description": p.description or ""}


def _payment_policy(name: str | None) -> dict | None:
	if not name:
		return None
	p = frappe.get_doc("TEX Payment Policy", name)
	return {"id": p.name, "name": p.policy_name, "deposit_type": p.deposit_type,
	        "deposit_value": serialize.dec_str(D(p.deposit_value)), "balance_due_days": int(p.balance_due_days or 0),
	        "allow_pay_at_hotel": bool(p.allow_pay_at_hotel), "description": p.description or ""}


def build_terms(version, *, at: datetime | None = None) -> ContractTerms:
	"""Terms of a (draft) version with inheritance resolved as of ``at``."""
	contract = frappe.get_doc("TEX Contract", version.contract)
	at = at or now_datetime()

	rooms = {}
	for r in version.rooms:
		rt = frappe.db.get_value("Room Type", r.room_type,
		                         ["room_type_name", "adults_capacity", "children_capacity", "max_total_occupants",
		                          "base_occupancy", "property"], as_dict=True)
		if not rt:
			frappe.throw(_("Room type {0} does not exist").format(r.room_type))
		if rt.property != contract.property:
			frappe.throw(_("Room type {0} belongs to another hotel").format(r.room_type))
		max_a = int(r.max_adults or rt.adults_capacity or 2)
		max_c = int(r.max_children or rt.children_capacity or 0)
		max_o = int(r.max_occupants or rt.max_total_occupants or (max_a + max_c))
		rooms[r.room_type] = RoomSpec(room_type=r.room_type, name=rt.room_type_name or r.room_type,
		                              max_adults=max_a, max_children=max_c, max_occupants=max_o,
		                              min_adults=int(r.min_adults or 1),
		                              included_adults=int(r.included_adults or rt.base_occupancy or 2))

	periods = tuple(
		Period(code=p.period_code.strip(), name=p.period_name or p.period_code, start=get_datetime(p.start_date).date(),
		       end=get_datetime(p.end_date).date(), weekdays=parse_weekdays(p.weekdays),
		       adjustment_op=Op(p.adjustment_op) if p.adjustment_op else None,
		       adjustment_value=D_or_none(p.adjustment_value) if p.adjustment_op else None,
		       priority=int(p.priority or 0))
		for p in version.periods)

	room_rules = tuple(
		RoomRule(rule_id=r.name, room_type=r.room_type, period=(r.period_code or "").strip() or None, op=Op(r.op),
		         value=None if r.op == "INHERIT" else D(r.value), base_room_type=r.base_room_type or None)
		for r in version.period_rates)

	policy, level = _policy_for(contract.property, contract.market, at)
	bands = _bands(version.age_bands) if version.age_bands else (
		_bands(policy.age_bands) if policy else ())
	occ = _occ_rules(version.occupancy_rules, base_level=Level.VERSION, source="version")
	if policy:
		occ = occ + _occ_rules(policy.occupancy_rules, base_level=level,
		                       source=f"policy:{policy.name}/r{policy.revision_no}")

	board_rules = tuple(
		BoardRule(rule_id=b.name, board=b.board, is_base=bool(b.is_base), op=Op(b.op or "ADD"),
		          adult_amount=D(b.adult_amount), child_percent=D(b.child_percent if b.child_percent is not None else 50),
		          infant_free=bool(b.infant_free), room_type=b.room_type or None,
		          period=(b.period_code or "").strip() or None, label=b.label or "")
		for b in version.boards)

	rate_plans = {}
	for rp in version.rate_plans:
		rp_doc = frappe.db.get_value("Rate Plan", rp.rate_plan,
		                             ["rate_plan_name", "tex_inclusions", "tex_cancellation_policy",
		                              "tex_payment_policy"], as_dict=True) or {}
		rate_plans[rp.rate_plan] = RatePlanTerms(
			code=rp.rate_plan, name=rp_doc.get("rate_plan_name") or rp.rate_plan,
			op=Op(rp.op) if rp.op else None, value=D_or_none(rp.value) if rp.op else None,
			refundable=bool(rp.refundable), boards=_csv(rp.boards),
			cancellation_policy=_cancellation_policy(rp.cancellation_policy or rp_doc.get("tex_cancellation_policy")),
			payment_policy=_payment_policy(rp.payment_policy or rp_doc.get("tex_payment_policy")),
			inclusions=tuple(x.strip() for x in (rp_doc.get("tex_inclusions") or "").splitlines() if x.strip()))

	offers = tuple(
		Promotion(promo_id=o.offer_code.strip().upper(), name=o.offer_name or o.offer_code, kind=o.kind,
		          value_type=PromoValueType(o.value_type), value=D(o.value), stage=PromoStage(o.stage or "SELL"),
		          sale_from=o.sale_from and get_datetime(o.sale_from).date(),
		          sale_to=o.sale_to and get_datetime(o.sale_to).date(),
		          stay_from=o.stay_from and get_datetime(o.stay_from).date(),
		          stay_to=o.stay_to and get_datetime(o.stay_to).date(), stay_match=StayMatch(o.stay_match or "ANY_NIGHT"),
		          min_nights=_nz(o.min_nights), max_nights=_nz(o.max_nights), min_lead_days=_nz(o.min_lead_days),
		          max_lead_days=_nz(o.max_lead_days), room_types=_csv(o.room_types), boards=_csv(o.boards),
		          stackable=bool(o.stackable), exclusive=bool(o.exclusive), priority=int(o.priority or 0),
		          group=o.offer_group or None, free_nights_stay=_nz(o.free_nights_stay),
		          free_nights_pay=o.free_nights_pay if o.value_type == "FREE_NIGHTS" else None, source="contract")
		for o in version.offers)

	channels = frozenset(c.sales_channel for c in contract.channels) or None
	d = lambda v: get_datetime(v).date() if v else None  # noqa: E731
	return ContractTerms(
		contract_id=contract.name, contract_code=contract.contract_code, contract_name=contract.contract_name,
		version_id=version.name, version_no=int(version.version_no or 0), payload_hash="",
		property=contract.property, market=contract.market, currency=contract.contract_currency,
		basis=PricingBasis(contract.pricing_basis), rooms=rooms, periods=periods, room_rules=room_rules,
		occupancy_rules=occ, age_bands=bands, boards=board_rules, rate_plans=rate_plans, offers=offers,
		sale_from=d(contract.sale_from), sale_to=d(contract.sale_to), stay_from=d(contract.stay_from),
		stay_to=d(contract.stay_to), channels=channels,
		child_ordering=ChildOrdering(version.child_ordering or "OLDEST_FIRST"),
		age_basis=AgeBasis(version.age_basis or "ARRIVAL"),
		children_over_max_as_adults=bool(version.children_over_max_as_adults),
		infants_count_as_occupants=bool(version.infants_count_as_occupants),
		prices_include_tax=bool(version.prices_include_tax), stacking=StackingMode(version.stacking or "SEQUENTIAL"),
		room_basis_extra_unit=RoomBasisExtraUnit(version.room_basis_extra_unit or "PER_PERSON_SHARE"),
		room_basis_children_fill_included=bool(version.room_basis_children_fill_included),
	)


def validate_version(name: str) -> dict:
	version = frappe.get_doc("TEX Contract Version", name)
	scope.require("contract.edit", scope.property_of("TEX Contract Version", name))
	try:
		terms = build_terms(version)
	except frappe.ValidationError as e:
		return {"ok": False, "issues": [{"level": "ERROR", "code": "BUILD", "message": str(e)}]}
	issues = validate.validate_terms(terms)
	return {"ok": not any(i.level == "ERROR" for i in issues), "issues": [i.to_dict() for i in issues]}


# ─── lifecycle ───────────────────────────────────────────────────────────


def new_draft(contract: str, based_on: str | None = None) -> str:
	prop = frappe.db.get_value("TEX Contract", contract, "property")
	scope.require("contract.edit", prop)
	existing = frappe.db.get_value("TEX Contract Version", {"contract": contract, "status": "Draft"})
	if existing:
		frappe.throw(_("Contract already has a draft version ({0}).").format(existing))
	if not based_on:
		based_on = frappe.db.get_value("TEX Contract Version", {"contract": contract}, "name",
		                               order_by="version_no desc")
	if based_on:
		src = frappe.get_doc("TEX Contract Version", based_on)
		if src.contract != contract:
			# never another contract's terms (another hotel's cost), never a draft on its contract (G-13)
			frappe.throw(_("A draft can only be based on a version of the same contract."), frappe.PermissionError)
		doc = frappe.copy_doc(src)
		for f in ("status", "published_at", "published_by", "active_to", "effective_from", "payload",
		          "payload_hash", "validation_report", "change_note"):
			doc.set(f, None)
		doc.based_on = src.name
	else:
		doc = frappe.new_doc("TEX Contract Version")
		doc.contract = contract
	doc.status = "Draft"
	doc.insert(ignore_permissions=True)
	audit("contract.version.draft", reference_doctype="TEX Contract Version", reference_name=doc.name,
	      property=prop, new={"based_on": based_on})
	return doc.name


def publish(name: str, effective_from=None, change_note: str | None = None) -> dict:
	version = frappe.get_doc("TEX Contract Version", name)
	contract = frappe.get_doc("TEX Contract", version.contract)
	scope.require("contract.publish", contract.property)
	if version.status != "Draft":
		frappe.throw(_("Only draft versions can be published."))
	now = now_datetime()
	eff = get_datetime(effective_from) if effective_from else now
	if eff < now.replace(microsecond=0):
		frappe.throw(_("A version cannot take effect in the past — sold reservations keep their terms."))

	# lock the contract row: two publishers can't race each other
	frappe.db.get_value("TEX Contract", contract.name, "name", for_update=True)
	terms = build_terms(version, at=eff)
	issues = validate.validate_terms(terms)
	errors = [i for i in issues if i.level == "ERROR"]
	if errors:
		frappe.throw(_("Cannot publish: {0}").format("; ".join(i.message for i in errors[:8])),
		             title=_("Contract has errors"))
	payload = serialize.normalise_payload(serialize.terms_to_payload(terms))
	digest = serialize.payload_hash(payload)

	# supersede what was on sale at `eff`; withdraw versions scheduled after it
	others = frappe.get_all("TEX Contract Version",
	                        filters={"contract": contract.name, "status": "Published", "name": ("!=", name)},
	                        fields=["name", "effective_from", "active_to"])
	for o in others:
		ov = frappe.get_doc("TEX Contract Version", o.name)
		ov.flags.tex_lifecycle = True
		if get_datetime(o.effective_from) >= eff:
			ov.status = "Withdrawn"
			ov.active_to = o.effective_from
		elif not o.active_to or get_datetime(o.active_to) > eff:
			ov.active_to = eff
			if eff <= now:
				ov.status = "Superseded"
		ov.save(ignore_permissions=True)

	version.flags.tex_lifecycle = True
	version.status = "Published"
	version.effective_from = eff
	version.published_at = now
	version.published_by = frappe.session.user
	version.payload = json.dumps(payload, sort_keys=True, ensure_ascii=False)
	version.payload_hash = digest
	version.validation_report = json.dumps([i.to_dict() for i in issues])
	if change_note:
		version.change_note = change_note
	version.save(ignore_permissions=True)

	contract.reload()
	contract.latest_version_no = max(int(contract.latest_version_no or 0), int(version.version_no))
	if eff <= now:
		contract.active_version = version.name
	if contract.status == "Draft":
		contract.status = "Active"
	contract.save(ignore_permissions=True)
	audit("contract.publish", reference_doctype="TEX Contract Version", reference_name=version.name,
	      property=contract.property, new={"payload_hash": digest, "effective_from": str(eff),
	                                       "warnings": len(issues)}, reason=change_note)
	clear_terms_cache()
	return {"version": version.name, "payload_hash": digest, "effective_from": str(eff),
	        "warnings": [i.to_dict() for i in issues]}


def withdraw(name: str, reason: str) -> None:
	version = frappe.get_doc("TEX Contract Version", name)
	prop = frappe.db.get_value("TEX Contract", version.contract, "property")
	scope.require("contract.publish", prop)
	if version.status not in ("Published",):
		frappe.throw(_("Only published versions can be withdrawn."))
	if not (reason or "").strip():
		frappe.throw(_("A reason is required."))
	version.flags.tex_lifecycle = True
	version.status = "Withdrawn"
	version.active_to = now_datetime()
	version.save(ignore_permissions=True)
	contract = frappe.get_doc("TEX Contract", version.contract)
	if contract.active_version == name:
		contract.active_version = None
		contract.save(ignore_permissions=True)
	audit("contract.withdraw", reference_doctype="TEX Contract Version", reference_name=name, property=prop,
	      reason=reason)
	clear_terms_cache()


def roll_version_statuses() -> None:
	"""Scheduler: flip scheduled versions live and superseded ones to Superseded."""
	now = now_datetime()
	for v in frappe.get_all("TEX Contract Version", filters={"status": "Published", "active_to": ("<=", now)},
	                        pluck="name"):
		doc = frappe.get_doc("TEX Contract Version", v)
		doc.flags.tex_lifecycle = True
		doc.status = "Superseded"
		doc.save(ignore_permissions=True)
	for c in frappe.get_all("TEX Contract", filters={"status": "Active"}, pluck="name"):
		live = active_version_header(c, now)
		if frappe.db.get_value("TEX Contract", c, "active_version") != (live.version_id if live else None):
			frappe.db.set_value("TEX Contract", c, "active_version", live.version_id if live else None)


# ─── loading frozen terms ────────────────────────────────────────────────


_TERMS: dict[str, ContractTerms] = {}


def clear_terms_cache() -> None:
	_TERMS.clear()


def load_terms(version_name: str) -> ContractTerms:
	"""Frozen terms of a published version (safe to cache: payloads are immutable)."""
	row = frappe.db.get_value("TEX Contract Version", version_name, ["payload", "payload_hash", "status"],
	                          as_dict=True)
	if not row or not row.payload:
		frappe.throw(_("Contract version {0} is not published.").format(version_name))
	cached = _TERMS.get(version_name)
	if cached and cached.payload_hash == row.payload_hash:
		return cached
	payload = json.loads(row.payload)
	if serialize.payload_hash(payload) != row.payload_hash:
		frappe.throw(_("Contract version {0} failed its integrity check.").format(version_name))
	terms = serialize.terms_from_payload(payload, row.payload_hash)
	_TERMS[version_name] = terms
	return terms


def version_headers(contract: str) -> list[versions.VersionHeader]:
	rows = frappe.get_all("TEX Contract Version", filters={"contract": contract},
	                      fields=["name", "version_no", "status", "effective_from", "active_to"])
	return [versions.VersionHeader(r.name, int(r.version_no), r.status,
	                               get_datetime(r.effective_from) if r.effective_from else None,
	                               get_datetime(r.active_to) if r.active_to else None) for r in rows]


def active_version_header(contract: str, at: datetime) -> versions.VersionHeader | None:
	return versions.active_version(version_headers(contract), get_datetime(at))


def candidate_contracts(property: str, market: str, channel: str, at: datetime) -> list[tuple[dict, str]]:
	"""Contracts that can sell for this hotel/market/channel at sale time ``at``
	→ [(contract row, version name)], highest priority first."""
	rows = frappe.get_all("TEX Contract", filters={"property": property, "status": "Active",
	                                               "market": ("in", [market, "GLOBAL"])},
	                      fields=["name", "contract_code", "contract_name", "market", "priority", "sale_from",
	                              "sale_to", "contract_currency", "sell_currency", "is_bar"])
	out = []
	sale = getdate(at)
	for r in rows:
		# closed for sale at this time: never a candidate (G-17)
		if (r.sale_from and sale < getdate(r.sale_from)) or (r.sale_to and sale > getdate(r.sale_to)):
			continue
		chans = frappe.get_all("TEX Contract Channel", filters={"parent": r.name, "parenttype": "TEX Contract"},
		                       pluck="sales_channel")
		if chans and channel not in chans:
			continue
		h = active_version_header(r.name, at)
		if h:
			out.append((r, h.version_id))
	# a market-specific contract beats the GLOBAL fallback; then priority
	out.sort(key=lambda x: (x[0].market != market, -(x[0].priority or 0), x[0].name))
	return out
