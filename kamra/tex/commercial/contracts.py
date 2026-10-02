"""Contract & contract-version service (ADR-004).

Draft versions are edited through their child tables. ``publish`` validates the
draft, resolves everything it inherits (every applicable pricing policy - global,
hotel, market, hotel + market, ADR-043 - room capacities, rate-plan policies) and
freezes the canonical payload + sha256 hash. Pricing always runs on that frozen
payload: a policy change reaches a contract only when it is republished.
"""

from __future__ import annotations

import copy
import hashlib
import json
from contextlib import nullcontext
from dataclasses import dataclass, replace
from datetime import date, datetime

import frappe
from frappe import _
from frappe.utils import get_datetime, getdate, now_datetime

from kamra.tex.commercial import diffs
from kamra.tex.money import D, D_or_none, db_dec, db_dec_or_none
from kamra.tex.pricing import ages as age_math
from kamra.tex.pricing import inherit, occupancy, policy_money, serialize, validate, versions
from kamra.tex.pricing.engine import GLOBAL_MARKET
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
from kamra.tex.pricing.promotions import offer_currency
from kamra.tex.security import scope
from kamra.tex.security.audit import audit, doc_values, row_values
from kamra.tex.services.refusals import refusal

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


def _policy_layers(property: str, market: str, at: datetime) -> list[inherit.PolicyLayer]:
	"""Every pricing policy live at ``at`` that applies to this hotel and market: global,
	hotel, market and hotel + market (G-30). ``inherit.cascade`` ranks them."""
	from kamra.tex.commercial.revisions import as_of

	layers = []
	for r in as_of("TEX Pricing Policy", at, fields=("name", "property", "market", "revision_no")):
		if (r.property and r.property != property) or (r.market and r.market != market):
			continue
		doc = frappe.get_doc("TEX Pricing Policy", r.name)
		layer = inherit.PolicyLayer(policy_id=r.name, revision=int(r.revision_no or 1),
		                            property=r.property or None, market=r.market or None, bands=age_bands_of(doc.age_bands))
		layers.append(replace(layer, rules=occupancy_rules_of(doc.occupancy_rules, base_level=layer.level,
		                                                      source=layer.source, scope_weight=layer.weight)))
	return layers


def band_source(version, terms: ContractTerms, at: datetime) -> str:
	"""Where the age bands of ``terms`` (built from ``version`` as of ``at``) come from: the
	version's own rows (``version``), else the policy they are inherited from, named by its
	source (``policy:<id>/r<rev>/<scope>``), or ``policy`` when the policies live at ``at`` no
	longer give that band set (ADR-061)."""
	if version.get("age_bands"):
		return "version"
	layer = inherit.band_layer(_policy_layers(terms.property, terms.market, at))
	return layer.source if layer is not None and tuple(layer.bands) == tuple(terms.age_bands) else "policy"


def age_bands_of(rows) -> tuple[AgeBand, ...]:
	"""Age bands from TEX Child Age Band rows (codes upper-cased, ages in exact months)."""
	return tuple(
		AgeBand(code=r.band_code.strip().upper(), label=r.label or r.band_code,
		        from_months=age_math.years_to_months(r.from_age or 0),
		        to_months=age_math.years_to_months(r.to_age or 0), is_infant=bool(r.is_infant))
		for r in rows)


def occupancy_rules_of(rows, *, base_level: Level, source: str,
                       scope_weight: int = 0) -> tuple[OccupancyRule, ...]:
	"""Occupancy rules from TEX Occupancy Rule rows, stamped with their origin."""
	out = []
	for r in rows:
		adults, children = parse_combination(r.combination)
		out.append(OccupancyRule(
			rule_id=r.name, target=OccTarget(r.target), op=Op(r.op),
			value=None if r.op == "INHERIT" else db_dec(r.value),
			position=_nz(r.position), age_band=(r.age_band or "").strip().upper() or None,
			room_type=r.room_type or None, period=(r.period_code or "").strip() or None,
			adults=adults, children=children, is_override=bool(r.is_override), base_level=base_level,
			source=source, note=r.note or "", scope_weight=scope_weight))
	return tuple(out)


# ─── selling terms (G-50, ADR-045) ───────────────────────────────────────

# Each version carries (and freezes at publish) when, where and in which order it sells. Until a
# contract's first publish they are edited on the contract header; from then on in a draft version,
# and the header only mirrors the live version. Hotel, market, currency and pricing basis never
# change once a version was published (another market or currency is another contract).
SELLING_FIELDS = ("sale_from", "sale_to", "stay_from", "stay_to", "priority", "sell_currency")
FIXED_FIELDS = ("property", "market", "contract_currency", "pricing_basis")
# what a draft edit changes besides its tables and selling terms (the editor's Settings tab)
DRAFT_SETTINGS = ("child_ordering", "age_basis", "children_over_max_as_adults", "infants_count_as_occupants",
                  "infants_count_as_children", "prices_include_tax", "stacking", "room_basis_extra_unit",
                  "room_basis_children_fill_included", "change_note")


def is_published(contract: str | None) -> bool:
	"""A version of this contract was published once (it may have sold): its commercial terms are fixed."""
	return bool(contract) and bool(
		frappe.db.exists("TEX Contract Version", {"contract": contract, "status": ("!=", "Draft")}))


def _iso(v) -> str | None:
	return str(getdate(v)) if v else None


def selling_values(doc) -> dict:
	"""Selling terms as entered on a contract header or a version."""
	return {"sale_from": _iso(doc.sale_from), "sale_to": _iso(doc.sale_to), "stay_from": _iso(doc.stay_from),
	        "stay_to": _iso(doc.stay_to), "priority": int(doc.priority or 0),
	        "sell_currency": doc.sell_currency or None,
	        "channels": sorted({c.sales_channel for c in (doc.get("channels") or [])})}


def selling_empty(doc) -> bool:
	"""A version (or header) with no selling terms of its own."""
	return not any(doc.get(f) for f in SELLING_FIELDS) and not doc.get("channels")


def frozen_selling(terms: ContractTerms) -> dict:
	"""The selling terms a payload froze (a version published since G-50)."""
	return {"sale_from": _iso(terms.sale_from), "sale_to": _iso(terms.sale_to), "stay_from": _iso(terms.stay_from),
	        "stay_to": _iso(terms.stay_to), "priority": terms.priority, "sell_currency": terms.sell_currency,
	        "channels": sorted(terms.channels or ())}


def _later(a, b):
	return max(a, b) if a and b else (a or b)


def _earlier(a, b):
	return min(a, b) if a and b else (a or b)


def _both(a: frozenset | None, b: frozenset | None) -> frozenset | None:
	"""Channels both allow (None = every channel; an empty set = none)."""
	return b if a is None else (a if b is None else a & b)


@dataclass(frozen=True)
class SellingTerms:
	"""What selection applies to one published version (ADR-045)."""
	markets: tuple[str, ...]            # each must be the requested market or GLOBAL
	sale_from: date | None
	sale_to: date | None
	stay_from: date | None
	stay_to: date | None
	channels: frozenset[str] | None     # None = every channel; empty = none
	priority: int
	sell_currency: str | None
	source: str                         # frozen | snapshot | header
	snapshot: dict | None = None        # the header terms a version frozen before G-50 is narrowed by

	def admits(self, market: str, channel: str, sale: date) -> bool:
		if any(m not in (market, GLOBAL_MARKET) for m in self.markets):
			return False
		if (self.sale_from and sale < self.sale_from) or (self.sale_to and sale > self.sale_to):
			return False
		return self.channels is None or channel in self.channels

	def as_dict(self) -> dict:
		return {"sale_from": _iso(self.sale_from), "sale_to": _iso(self.sale_to), "stay_from": _iso(self.stay_from),
		        "stay_to": _iso(self.stay_to), "priority": self.priority, "sell_currency": self.sell_currency,
		        "channels": sorted(self.channels or ()), "no_channel": self.channels is not None and not self.channels,
		        "legacy": self.snapshot is not None, "header_market": (self.snapshot or {}).get("market")}

	def draft_values(self) -> dict:
		"""Selling terms for a draft based on this version: what it sold. Where a version frozen
		before G-50 sold nothing (its header and payload windows or channels do not overlap), the
		draft takes the header's value, the terms staff last set."""
		out = {k: v for k, v in self.as_dict().items() if k in (*SELLING_FIELDS, "channels")}
		snap = self.snapshot
		if snap and self.sale_from and self.sale_to and self.sale_from > self.sale_to:
			out["sale_from"], out["sale_to"] = _iso(snap["sale_from"]), _iso(snap["sale_to"])
		if snap and self.channels is not None and not self.channels:
			out["channels"] = sorted(snap["channels"] or ())
		return out


def _header_terms(parent: str, parenttype: str, row, market: str | None) -> dict:
	d = lambda v: getdate(v) if v else None  # noqa: E731
	chans = frappe.get_all("TEX Contract Channel", filters={"parent": parent, "parenttype": parenttype},
	                       pluck="sales_channel")
	return {"market": market, "sale_from": d(row.sale_from), "sale_to": d(row.sale_to),
	        "stay_from": d(row.stay_from), "stay_to": d(row.stay_to), "channels": frozenset(chans) or None,
	        "priority": int(row.priority or 0), "sell_currency": row.sell_currency or None}


def legacy_snapshot(version: str, contract: str) -> tuple[dict, str]:
	"""The header terms a version frozen before G-50 is narrowed by: the snapshot the upgrade
	(p25) stored on the version, or, before it ran, the live contract header."""
	row = frappe.db.get_value("TEX Contract Version", version,
	                          ["header_snapshot_at", "header_market", *SELLING_FIELDS], as_dict=True)
	if row and row.header_snapshot_at:
		return _header_terms(version, "TEX Contract Version", row, row.header_market), "snapshot"
	h = frappe.db.get_value("TEX Contract", contract, ["market", *SELLING_FIELDS], as_dict=True)
	return _header_terms(contract, "TEX Contract", h, h.market), "header"


def selling_terms(version: str, terms: ContractTerms) -> SellingTerms:
	"""Selling terms of a published version (ADR-045). A version published since G-50 sells on
	what its payload froze. Before G-50, selection read the header and pricing the payload, so a
	header narrowed after publish stopped sales; a version frozen then keeps selling only where
	both its payload and that header allow (market, sale window, channels), in the header's
	priority and sell currency. The header's stay window never narrowed anything."""
	if terms.priority is not None:
		return SellingTerms(markets=(terms.market,), sale_from=terms.sale_from, sale_to=terms.sale_to,
		                    stay_from=terms.stay_from, stay_to=terms.stay_to, channels=terms.channels,
		                    priority=terms.priority, sell_currency=terms.sell_currency, source="frozen")
	snap, source = legacy_snapshot(version, terms.contract_id)
	return SellingTerms(markets=(terms.market, snap["market"] or terms.market),
	                    sale_from=_later(terms.sale_from, snap["sale_from"]),
	                    sale_to=_earlier(terms.sale_to, snap["sale_to"]), stay_from=terms.stay_from,
	                    stay_to=terms.stay_to, channels=_both(terms.channels, snap["channels"]),
	                    priority=snap["priority"], sell_currency=snap["sell_currency"], source=source,
	                    snapshot=snap)


def version_selling(version: str) -> SellingTerms:
	return selling_terms(version, load_terms(version))


def set_selling(doc, values: dict) -> None:
	for f in SELLING_FIELDS:
		if f in values:
			doc.set(f, values[f])
	if "channels" in values:
		doc.set("channels", [{"sales_channel": c} for c in (values["channels"] or [])])


def selling_source(version, contract):
	"""Where a draft's selling terms come from: the contract header until the contract's first
	publish, the draft itself afterwards."""
	return version if is_published(contract.name) else contract


# ─── build terms from a draft ────────────────────────────────────────────


def _fixed_currency(policy: dict, p, contract_currency: str) -> dict:
	"""A policy with a fixed amount is frozen with the currency of its fixed amounts: its own, else
	the contract's (ADR-067, D-1). Any other policy is frozen as before, without one."""
	if policy_money.has_fixed(policy):
		policy["currency"] = (p.currency or contract_currency).upper()
	return policy


def _cancellation_policy(name: str | None, contract_currency: str) -> dict | None:
	if not name:
		return None
	p = frappe.get_doc("TEX Cancellation Policy", name)
	return _fixed_currency({
		"id": p.name, "name": p.policy_name, "refundable": bool(p.refundable),
		"rules": [{"days_before_arrival": int(r.days_before_arrival or 0), "penalty_type": r.penalty_type,
		           "penalty_value": serialize.dec_str(db_dec(r.penalty_value))}
		          for r in sorted(p.rules, key=lambda r: -(r.days_before_arrival or 0))],
		"no_show": {"type": p.no_show_type, "value": serialize.dec_str(db_dec(p.no_show_value))},
		"description": p.description or ""}, p, contract_currency)


def _payment_policy(name: str | None, contract_currency: str) -> dict | None:
	if not name:
		return None
	p = frappe.get_doc("TEX Payment Policy", name)
	return _fixed_currency({
		"id": p.name, "name": p.policy_name, "deposit_type": p.deposit_type,
		"deposit_value": serialize.dec_str(db_dec(p.deposit_value)), "balance_due_days": int(p.balance_due_days or 0),
		"allow_pay_at_hotel": bool(p.allow_pay_at_hotel), "description": p.description or ""}, p, contract_currency)


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
		       adjustment_value=db_dec_or_none(p.adjustment_value) if p.adjustment_op else None,
		       priority=int(p.priority or 0))
		for p in version.periods)

	room_rules = tuple(
		RoomRule(rule_id=r.name, room_type=r.room_type, period=(r.period_code or "").strip() or None, op=Op(r.op),
		         value=None if r.op == "INHERIT" else db_dec(r.value), base_room_type=r.base_room_type or None)
		for r in version.period_rates)

	# the version's own bands and rules, then every applicable pricing policy's (G-30, ADR-043)
	try:
		bands, occ = inherit.cascade(age_bands_of(version.age_bands),
		                             occupancy_rules_of(version.occupancy_rules, base_level=Level.VERSION, source="version"),
		                             _policy_layers(contract.property, contract.market, at))
	except inherit.PolicyAmbiguous as e:   # never ranked by guesswork (PRICING_POLICY_AMBIGUOUS)
		frappe.throw(_("Pricing policies cannot be combined: {0}.").format(str(e)), title=_("Pricing policy ambiguous"))

	board_rules = tuple(
		BoardRule(rule_id=b.name, board=b.board, is_base=bool(b.is_base), op=Op(b.op or "ADD"),
		          adult_amount=db_dec(b.adult_amount),
		          child_percent=db_dec(b.child_percent if b.child_percent is not None else 50),
		          infant_free=bool(b.infant_free), room_type=b.room_type or None,
		          period=(b.period_code or "").strip() or None, label=b.label or "")
		for b in version.boards)

	rate_plans = {}
	for rp in version.rate_plans:
		rp_doc = frappe.db.get_value("Rate Plan", rp.rate_plan,
		                             ["rate_plan_name", "tex_inclusions", "tex_cancellation_policy",
		                              "tex_payment_policy", "property"], as_dict=True) or {}
		# never another hotel's rate plan or terms, as for room types (S16 review: the overlay and
		# the price test read them back); a policy of no hotel is shared. A tenancy fix, so it holds
		# for every caller, never opt-in (ADR-061, "Existing semantics kept"): main priced,
		# validated and published such a draft
		if rp_doc and rp_doc.get("property") != contract.property:
			frappe.throw(_("Rate plan {0} belongs to another hotel").format(rp.rate_plan))
		for doctype, name in (("TEX Cancellation Policy", rp.cancellation_policy),
		                      ("TEX Payment Policy", rp.payment_policy)):
			owner = frappe.db.get_value(doctype, name, "property") if name else None
			if owner and owner != contract.property:
				frappe.throw(_("{0} {1} belongs to another hotel").format(_(doctype), name))
		rate_plans[rp.rate_plan] = RatePlanTerms(
			code=rp.rate_plan, name=rp_doc.get("rate_plan_name") or rp.rate_plan,
			op=Op(rp.op) if rp.op else None, value=db_dec_or_none(rp.value) if rp.op else None,
			refundable=bool(rp.refundable), boards=_csv(rp.boards),
			cancellation_policy=_cancellation_policy(rp.cancellation_policy or rp_doc.get("tex_cancellation_policy"),
			                                         contract.contract_currency),
			payment_policy=_payment_policy(rp.payment_policy or rp_doc.get("tex_payment_policy"),
			                               contract.contract_currency),
			inclusions=tuple(x.strip() for x in (rp_doc.get("tex_inclusions") or "").splitlines() if x.strip()))

	offers = tuple(
		Promotion(promo_id=o.offer_code.strip().upper(), name=o.offer_name or o.offer_code, kind=o.kind,
		          value_type=PromoValueType(o.value_type), value=db_dec(o.value), stage=PromoStage(o.stage or "SELL"),
		          # a fixed amount is in the contract's currency, as the contract screen shows it (K-1)
		          currency=offer_currency(PromoValueType(o.value_type), None, contract.contract_currency),
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

	src = selling_source(version, contract)
	channels = frozenset(c.sales_channel for c in src.channels) or None
	d = lambda v: get_datetime(v).date() if v else None  # noqa: E731
	return ContractTerms(
		contract_id=contract.name, contract_code=contract.contract_code, contract_name=contract.contract_name,
		version_id=version.name, version_no=int(version.version_no or 0), payload_hash="",
		property=contract.property, market=contract.market, currency=contract.contract_currency,
		basis=PricingBasis(contract.pricing_basis), rooms=rooms, periods=periods, room_rules=room_rules,
		occupancy_rules=occ, age_bands=bands, boards=board_rules, rate_plans=rate_plans, offers=offers,
		sale_from=d(src.sale_from), sale_to=d(src.sale_to), stay_from=d(src.stay_from),
		stay_to=d(src.stay_to), channels=channels, priority=int(src.priority or 0),
		sell_currency=(src.sell_currency or contract.contract_currency).upper(),
		child_ordering=ChildOrdering(version.child_ordering or "OLDEST_FIRST"),
		age_basis=AgeBasis(version.age_basis or "ARRIVAL"),
		children_over_max_as_adults=bool(version.children_over_max_as_adults),
		infants_count_as_occupants=bool(version.infants_count_as_occupants),
		# unset (a document made before the field) is the DocType's default: infants are children
		infants_count_as_children=version.get("infants_count_as_children") is None
		or bool(version.infants_count_as_children),
		prices_include_tax=bool(version.prices_include_tax), stacking=StackingMode(version.stacking or "SEQUENTIAL"),
		room_basis_extra_unit=RoomBasisExtraUnit(version.room_basis_extra_unit or "PER_PERSON_SHARE"),
		room_basis_children_fill_included=bool(version.room_basis_children_fill_included),
		occupancy_precedence=occupancy.CASCADE,
	)


def validate_version(name: str, *, formula: bool = True, workspace: bool = False) -> dict:
	version = frappe.get_doc("TEX Contract Version", name)
	scope.require("contract.edit", scope.property_of("TEX Contract Version", name))
	return validate_doc(version, formula=formula, workspace=workspace)


def validate_doc(version, *, formula: bool = True, workspace: bool = False) -> dict:
	"""Validation of a version document as it is: a loaded draft, or a draft with unsaved changes
	applied in memory (ADR-061). The caller checks who may validate it. Without ``formula`` (a
	viewer who may not read the pricing policies' formulas, S16 review) no issue whose presence
	depends on an inherited rule's value is reported (``validate_terms(hidden=…)``), whoever asks.
	``workspace`` (the Pricing Workspace's opt-in, ADR-061): its board checks (GAP-5) and each
	issue's ``ref`` (D9); without it the issues are main's."""
	try:
		terms = build_terms(version)
	except frappe.ValidationError as e:
		return {"ok": False, "issues": [{"level": "ERROR", "code": "BUILD", "message": str(e)}]}
	issues = validate.validate_terms(terms, hidden=frozenset() if formula else policy_rules(terms),
	                                 board_checks=workspace)
	return {"ok": not any(i.level == "ERROR" for i in issues),
	        "issues": [i.to_dict(ref=workspace) for i in issues]}


def policy_rules(terms) -> frozenset[str]:
	"""The ids of the occupancy rules ``terms`` inherit from pricing policies: their formulas are
	cost (G-11), which a viewer without ``price.view_cost`` may not read (ADR-061, S16 review)."""
	return frozenset(r.rule_id for r in terms.occupancy_rules if r.source != "version")


# a stored report as a viewer without cost reads it, by (payload hash, report hash, sweep limit): a
# published version's payload and report never change, and working it out can mean running the whole
# sweep again (S16 re-review 5). Per process, as the frozen terms are (``_TERMS``); the oldest goes first.
_VISIBLE: dict[tuple, list] = {}
_VISIBLE_MAX = 256


def stored_report(version, *, formula: bool = True, bound=None) -> list | None:
	"""The validation report stored when ``version`` was published (made with nothing hidden).
	Without ``formula`` it is given as the live check gives a viewer without ``price.view_cost``
	its issues (S16 re-review): ``validate.visible_issues`` of the frozen terms leaves out an
	outranked policy override and a sweep issue whose presence depends on a policy rule's value;
	if the frozen terms cannot be read, every issue of those codes is left out.

	That is worked out once per report (``_VISIBLE``). ``bound``: a context manager factory the
	work runs in when it may run the sweep again (``validate.reruns_sweep``: a stored sweep at its
	limit), e.g. the API's per-user bound on heavy checks (S16 re-review 5)."""
	if not version.validation_report:
		return None
	report = json.loads(version.validation_report)
	if formula:
		return report
	if not isinstance(report, list):
		return []
	try:
		terms = load_terms(version.name) if version.payload else None
	except frappe.ValidationError:
		terms = None
	if terms is None:
		return [i for i in report if isinstance(i, dict) and i.get("code") not in validate.HIDEABLE_CODES]
	key = (terms.payload_hash, hashlib.sha256(version.validation_report.encode()).hexdigest(), validate.SWEEP_LIMIT)
	visible = _VISIBLE.get(key)
	if visible is None:
		with bound() if bound and validate.reruns_sweep(report) else nullcontext():
			visible = validate.visible_issues(terms, report, policy_rules(terms))
		while len(_VISIBLE) >= _VISIBLE_MAX:
			_VISIBLE.pop(next(iter(_VISIBLE)))
		_VISIBLE[key] = visible
	return copy.deepcopy(visible)


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
		if src.status != "Draft" and src.payload:
			# what the source version sold, not whatever its fields say (G-50, ADR-045)
			set_selling(doc, version_selling(src.name).draft_values())
	else:
		doc = frappe.new_doc("TEX Contract Version")
		doc.contract = contract
		set_selling(doc, selling_values(frappe.get_doc("TEX Contract", contract)))
		# a brand-new contract does not count infants as children (O-2, ADR-067, D-2); the DocType's
		# default (1) keeps every other way a version is made pricing as before
		doc.infants_count_as_children = 0
	doc.status = "Draft"
	doc.insert(ignore_permissions=True)
	audit("contract.version.draft", reference_doctype="TEX Contract Version", reference_name=doc.name,
	      property=prop, new={"based_on": based_on})
	return doc.name


def publish(name: str, effective_from=None, change_note: str | None = None, *, workspace: bool = False) -> dict:
	"""Freeze a draft and put it on sale at ``effective_from``. ``workspace`` (the Pricing
	Workspace's opt-in, ADR-061): its board checks block the publish as its live check reports them
	(GAP-5), and the report stored and returned carries each issue's ``ref`` (D9); without it a
	publish decides and stores exactly what main did. The report is stored whole; the ``warnings``
	returned are that report as ``get_version`` gives it to the caller (``stored_report``): to a
	publisher without ``price.view_cost``, without what depends on a pricing policy's formulas (S16
	re-review 4; a security fix for every caller, like the stored report's); to one who neither sees
	cost nor edits contracts, None (``get_version`` gives it no report, S16 re-review 5). A refused
	publish names to a publisher without ``price.view_cost`` only the errors its own live check shows
	(``_refusal``), and the audit counts the warnings such a viewer is shown (S16 re-review 5)."""
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
	previous = _previous_version(contract.name, name, eff)
	terms = build_terms(version, at=eff)
	issues = validate.validate_terms(terms, board_checks=workspace)
	errors = [i for i in issues if i.level == "ERROR"]
	if errors:
		frappe.throw(_("Cannot publish: {0}").format(_refusal(terms, errors, contract.property, workspace)),
		             title=_("Contract has errors"))
	payload = serialize.normalise_payload(serialize.terms_to_payload(terms))
	digest = serialize.payload_hash(payload)
	selling = frozen_selling(terms)
	selling_before = selling_values(contract)      # the header shows the live version's (or the first draft's)

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
	set_selling(version, selling)                 # the version records what it froze
	version.status = "Published"
	version.effective_from = eff
	version.published_at = now
	version.published_by = frappe.session.user
	version.payload = json.dumps(payload, sort_keys=True, ensure_ascii=False)
	version.payload_hash = digest
	version.validation_report = json.dumps([i.to_dict(ref=workspace) for i in issues])
	if change_note:
		version.change_note = change_note
	version.save(ignore_permissions=True)

	contract.reload()
	contract.latest_version_no = max(int(contract.latest_version_no or 0), int(version.version_no))
	if eff <= now:
		contract.active_version = version.name
		set_selling(contract, selling)            # the header mirrors the live version
	if contract.status == "Draft":
		contract.status = "Active"
	contract.flags.tex_lifecycle = True
	contract.save(ignore_permissions=True)
	# the report just stored as a viewer without price.view_cost reads it: the same whatever a pricing
	# policy's formulas (worked out once, ``stored_report``)
	visible = stored_report(version, formula=False) or []
	# what was frozen, and how it differs from what sold before (G-74, ADR-053). The warnings counted
	# are the ones a viewer without cost is shown: the audit trail is read with reservation.view, and
	# the full count would say how many a policy's formulas decide (S16 re-review 5)
	audit("contract.publish", reference_doctype="TEX Contract Version", reference_name=version.name,
	      property=contract.property, old={"selling": selling_before},
	      new={"payload_hash": digest, "effective_from": str(eff), "warnings": len(visible), "selling": selling,
	           "previous": {"version": previous.name, "payload_hash": previous.payload_hash} if previous else None,
	           "collections": diffs.payload_diff(json.loads(previous.payload) if previous else None, payload)},
	      reason=change_note)
	clear_terms_cache()
	# the report just stored, as get_version gives it to this caller: all of it to who sees cost; to an
	# editor without price.view_cost what that viewer's live check tells (S16 re-review 4); nothing to
	# who neither sees cost nor edits contracts, whom get_version gives the catalogue (S16 re-review 5)
	if scope.has_capability("price.view_cost", contract.property):
		warnings = [i.to_dict(ref=workspace) for i in issues]
	elif scope.has_capability("contract.edit", contract.property):
		warnings = visible
	else:
		warnings = None
	return {"version": version.name, "payload_hash": digest, "effective_from": str(eff), "warnings": warnings}


# a refused publish's message to a publisher without cost when every error depends on a pricing
# policy's rules (``_refusal``): it names none of them
UNEXPLAINED_REFUSAL = ("the rules this draft inherits from a pricing policy make it unpublishable; someone who "
                       "may see cost can say why")


def _refusal(terms, errors: list, prop: str, workspace: bool) -> str:
	"""What a refused publish names (S16 re-review 5). Who sees cost: the full check's ``errors``, as
	before. A publisher without ``price.view_cost``: only the errors its own live check shows
	(``validate.refusal_errors``), which no hidden policy rule's op decides, so the message reads the
	same whatever those ops are; when that check shows none, every error depends on a hidden rule and
	none is named (``UNEXPLAINED_REFUSAL``). The refusal itself says only that the full check failed:
	where the viewer's check shows an error that no op decides (an unknown band, say) it is refused
	whatever the ops; otherwise not being refused is a real, audited publish (ADR-061)."""
	if not scope.has_capability("price.view_cost", prop):
		errors = validate.refusal_errors(terms, errors, policy_rules(terms), board_checks=workspace)
		if not errors:
			return _(UNEXPLAINED_REFUSAL)
	return "; ".join(i.message for i in errors[:8])


def _previous_version(contract: str, publishing: str, at) -> frappe._dict | None:
	"""The version a publish is compared with: the one selling at its effective time, else the
	latest version published before (a withdrawn or superseded one); None for a first publish."""
	live = active_version_header(contract, at)
	name = live.version_id if live and live.version_id != publishing else frappe.db.get_value(
		"TEX Contract Version", {"contract": contract, "status": ("!=", "Draft"), "name": ("!=", publishing),
		                         "payload": ("is", "set")}, "name", order_by="version_no desc")
	return frappe.db.get_value("TEX Contract Version", name, ["name", "payload", "payload_hash"], as_dict=True) \
		if name else None


def draft_state(version) -> dict:
	"""A draft as the audit compares it: settings and selling terms, and its rows."""
	fields = doc_values(version, (*DRAFT_SETTINGS, *SELLING_FIELDS))
	fields["channels"] = sorted({c.sales_channel for c in version.get("channels") or []})
	return {"fields": fields, "tables": {t: row_values(version.get(t)) for t in diffs.DRAFT_TABLES}}


def audit_draft_save(before, after) -> None:
	"""A saved draft edit, whatever the path (TEX editor, grid rate change, Desk, REST): the
	settings that changed old → new and each table's rows by natural key, bounded (G-74,
	ADR-053). A save that changed nothing records nothing."""
	old, new, tables = diffs.draft_diff(draft_state(before), draft_state(after))
	if not (old or tables):
		return
	if tables:
		new["collections"] = tables
	audit("contract.version.save", reference_doctype="TEX Contract Version", reference_name=after.name,
	      property=frappe.db.get_value("TEX Contract", after.contract, "property"), old=old or None, new=new,
	      reason=after.flags.tex_audit_reason)


def withdraw(name: str, reason: str) -> None:
	"""Take a published version off sale (Y-2 + O-13, ADR-069).

	Locks in ``create_booking``'s order: the version's open quotes, the contract, then the version
	is read again under them. A version that has not started (scheduled) is cancelled: it ends at its
	own start, and a version that was to end at that start gets the window back, to the next
	published version's start (or open-ended); no other version is ever shortened. The version on
	sale stops now, and no older version comes back. Its open quotes are expired (a booking of one
	is refused), and the contract's live version is worked out again."""
	contract = frappe.db.get_value("TEX Contract Version", name, "contract")
	if not contract:
		frappe.throw(_("Only published versions can be withdrawn."))
	prop = frappe.db.get_value("TEX Contract", contract, "property")
	scope.require("contract.publish", prop)
	if not (reason or "").strip():
		frappe.throw(_("A reason is required."))
	now = now_datetime()
	# the version's quotes that can still be booked, locked first as ``create_booking`` locks them.
	# expires_at NULL: never written (``_persist`` always writes it); such a row counts as usable
	# here and is expired with the others
	quotes = frappe.db.sql_list("""SELECT name FROM `tabTEX Quote` WHERE contract_version=%(v)s AND status='Open'
	                               AND (expires_at IS NULL OR expires_at > %(now)s) ORDER BY name FOR UPDATE""",
	                            {"v": name, "now": now})
	# the plain reads above fixed the read view (ADR-063): from here on only locking reads, which see
	# what is committed now (a quote committed while the scan waited, a publish or a roll)
	held = frappe.db.get_value("TEX Contract", contract, ["name", "active_version"], as_dict=True, for_update=True)
	version = frappe.get_doc("TEX Contract Version", name, for_update=True)
	if version.status != "Published":
		frappe.throw(_("Only published versions can be withdrawn."))
	# effective_from NULL (a version published before p56): on sale, never scheduled
	start = get_datetime(version.effective_from) if version.effective_from else None
	scheduled = bool(start and start > now)
	restored = []
	if scheduled:
		# the other published versions, compared in Python (no date filter): a version that was to end
		# at this one's start sells again until the next published version starts, or open-ended
		# (locked: get_all takes no lock). No date filter: a NULL date is read as open, in Python below
		others = frappe.db.sql("""SELECT name, effective_from, active_to FROM `tabTEX Contract Version`
		                          WHERE contract=%s AND status='Published' AND name!=%s FOR UPDATE""",
		                       (contract, name), as_dict=True)
		later = [get_datetime(o.effective_from) for o in others
		         if o.effective_from and get_datetime(o.effective_from) > start]
		new_to = min(later) if later else None
		for o in others:
			if o.active_to and get_datetime(o.active_to) == start:
				ov = frappe.get_doc("TEX Contract Version", o.name, for_update=True)
				ov.flags.tex_lifecycle = True
				ov.active_to = new_to
				ov.save(ignore_permissions=True)
				restored.append({"version": o.name, "active_to": [str(start), str(new_to) if new_to else None]})
	version.flags.tex_lifecycle = True
	version.status = "Withdrawn"
	# a cancelled schedule ends at its start (publish, p56); a started one now, never later than it
	# already ended (what sold before stays as it was)
	ended = get_datetime(version.active_to) if version.active_to else None
	version.active_to = start if scheduled else min(ended, now) if ended else now
	version.save(ignore_permissions=True)
	for q in quotes:
		doc = frappe.get_doc("TEX Quote", q, for_update=True)     # the scan locked it; read it under that lock
		doc.status = "Expired"
		doc.save(ignore_permissions=True)
	live = active_version_header(contract, now, locked=True)
	live_name = live.version_id if live else None
	if held["active_version"] != live_name:
		_go_live(contract, live_name)
	audit("contract.withdraw", reference_doctype="TEX Contract Version", reference_name=name, property=prop,
	      new={"scheduled": scheduled, "restored": restored, "quotes_expired": len(quotes)}, reason=reason)
	clear_terms_cache()


def _isolated(label: str, fn) -> None:
	"""Run one scheduler step in a savepoint: a record that fails is rolled back and logged, and
	never stops the others (one legacy header must not stall every hotel's contracts)."""
	frappe.db.savepoint("tex_contract_roll")
	try:
		fn()
	except Exception:
		frappe.db.rollback(save_point="tex_contract_roll")
		from kamra.tex.security.audit import log_exception

		log_exception(f"TEX contract roll {label}")
	else:
		frappe.db.release_savepoint("tex_contract_roll")


def _supersede(version: str) -> None:
	doc = frappe.get_doc("TEX Contract Version", version)
	doc.flags.tex_lifecycle = True
	doc.status = "Superseded"
	doc.save(ignore_permissions=True)


def _go_live(contract: str, version: str | None) -> None:
	doc = frappe.get_doc("TEX Contract", contract, for_update=True)
	doc.active_version = version
	selling = None
	if version:
		st = version_selling(version)
		selling = st.as_dict()
		if st.source == "frozen":
			set_selling(doc, frozen_selling(load_terms(version)))   # the header mirrors the live version
		# a version frozen before G-50 is narrowed by the header it had: nothing to mirror
	doc.flags.tex_lifecycle = True
	doc.save(ignore_permissions=True)
	audit("contract.version_live", reference_doctype="TEX Contract", reference_name=contract, property=doc.property,
	      new={"version": version, "selling": selling})


def roll_version_statuses() -> None:
	"""Scheduler: flip scheduled versions live and superseded ones to Superseded."""
	now = now_datetime()
	# a version without an end (live or scheduled) is never over: get_all reads a missing date as
	# 0001-01-01 for <= (NEW-1, ADR-064)
	for v in frappe.get_all("TEX Contract Version", filters=[["status", "=", "Published"], ["active_to", "is", "set"],
	                                                         ["active_to", "<=", now]], pluck="name"):
		_isolated(v, lambda v=v: _supersede(v))
	for c in frappe.get_all("TEX Contract", filters={"status": "Active"}, pluck="name"):
		live = active_version_header(c, now)
		new = live.version_id if live else None
		if frappe.db.get_value("TEX Contract", c, "active_version") != new:
			_isolated(c, lambda c=c, new=new: _go_live(c, new))


# ─── loading frozen terms ────────────────────────────────────────────────


_TERMS: dict[str, ContractTerms] = {}


class PayloadMismatch(frappe.ValidationError):
	"""A frozen payload is not the one it should be (G-73, ADR-058): it fails its own integrity
	check, or it is not the payload a price-locked snapshot recorded (``expected_hash``). It names
	the version that failed and the hash on its row (review of G-73, L3): selection loads every
	contract on sale, so the one that failed may not be the stay's."""

	code = "RATE_UNAVAILABLE"                    # the guest's refusal code (G-70a)

	def __init__(self, message: str = "", *, version: str | None = None, found_hash: str | None = None,
	             detail: str | None = None):
		super().__init__(message)
		self.version = version
		self.found_hash = found_hash
		# what failed, for staff and the audit, when the message is a guest's (G-70b review round 1)
		self.detail = detail


def clear_terms_cache() -> None:
	_TERMS.clear()


def load_terms(version_name: str, *, expected_hash: str | None = None) -> ContractTerms:
	"""Frozen terms of a published version (safe to cache: payloads are immutable).

	``expected_hash``: the payload hash a price-locked snapshot recorded for this version (G-73).
	A snapshot keeps its periods and rules by reference (version and hash), so whoever reprices,
	simulates or re-explains it from that version passes the hash: the terms are refused
	(``PayloadMismatch``) unless the payload still hashes to it."""
	digest = frappe.db.get_value("TEX Contract Version", version_name, "payload_hash")
	cached = _TERMS.get(version_name)
	# a guest (a quote raced by a withdraw, a change of a booked stay) is never told the version (G-71, G-70b)
	guest = frappe.session.user == "Guest"
	unavailable = _("This rate cannot be sold right now. Please search again.")
	if digest and cached and cached.payload_hash == digest:
		terms = cached      # selection loads every live version: the payload is read only on a miss
	else:
		row = frappe.db.get_value("TEX Contract Version", version_name, ["payload", "payload_hash"], as_dict=True)
		if not row or not row.payload:
			detail = _("Contract version {0} is not published.").format(version_name)
			frappe.throw(_("This rate is no longer on sale. Please search again.") if guest else detail,
			             PayloadMismatch(version=version_name, detail=detail) if expected_hash else refusal("NOT_ON_SALE"))
		payload = json.loads(row.payload)
		if serialize.payload_hash(payload) != row.payload_hash:
			detail = _("Contract version {0} failed its integrity check.").format(version_name)
			frappe.throw(unavailable if guest else detail,
			             PayloadMismatch(version=version_name, found_hash=row.payload_hash, detail=detail))
		terms = serialize.terms_from_payload(payload, row.payload_hash)
		_TERMS[version_name] = terms
	if expected_hash and terms.payload_hash != expected_hash:
		detail = _("Contract version {0} is not the terms it was sold on: its payload hash is {1}…, the sale recorded "
		           "{2}….").format(version_name, terms.payload_hash[:12], expected_hash[:12])
		frappe.throw(unavailable if guest else detail,
		             PayloadMismatch(version=version_name, found_hash=terms.payload_hash, detail=detail))
	return terms


def version_headers(contract: str, *, locked: bool = False) -> list[versions.VersionHeader]:
	"""``locked``: read under ``LOCK IN SHARE MODE``, which sees what is committed now, not the read
	view the transaction fixed earlier (a withdraw, 2D-2). No date filter: a NULL date is open."""
	if locked:
		rows = frappe.db.sql("""SELECT name, version_no, status, effective_from, active_to
		                        FROM `tabTEX Contract Version` WHERE contract=%s LOCK IN SHARE MODE""",
		                     contract, as_dict=True)
	else:
		rows = frappe.get_all("TEX Contract Version", filters={"contract": contract},
		                      fields=["name", "version_no", "status", "effective_from", "active_to"])
	return [versions.VersionHeader(r.name, int(r.version_no), r.status,
	                               get_datetime(r.effective_from) if r.effective_from else None,
	                               get_datetime(r.active_to) if r.active_to else None) for r in rows]


def active_version_header(contract: str, at: datetime, *, locked: bool = False) -> versions.VersionHeader | None:
	return versions.active_version(version_headers(contract, locked=locked), get_datetime(at))


STATUS_AUDIT = "contract.status"       # every status change, on every path (TEXContract.on_update)


def _audited_status(value) -> str | None:
	try:
		return (json.loads(value) or {}).get("status") if value else None
	except (TypeError, ValueError, AttributeError):
		return None


def statuses_at(rows, at: datetime) -> dict[str, str | None]:
	"""Each contract's status at ``at`` (G-51, ADR-054). ``rows``: contracts with their current
	``status``. The history is the audit trail: the controller audits every status change
	(publish, the status actions, any save) as ``contract.status`` in the same transaction, and
	audit events are immutable; a contract with no recorded change still has its status."""
	rows = list(rows)
	if not rows:
		return {}
	events = frappe.get_all("TEX Audit Event",
	                        filters={"action": STATUS_AUDIT, "reference_doctype": "TEX Contract",
	                                 "reference_name": ("in", [r.name for r in rows])},
	                        fields=["reference_name", "event_time", "old_value", "new_value"],
	                        order_by="event_time asc, creation asc, name asc")
	changes: dict[str, list[versions.StatusChange]] = {}
	for e in events:
		changes.setdefault(e.reference_name, []).append(versions.StatusChange(
			get_datetime(e.event_time), _audited_status(e.old_value), _audited_status(e.new_value)))
	at = get_datetime(at)
	return {r.name: versions.status_at(changes.get(r.name, []), at, r.status) for r in rows}


def candidate_contracts(property: str, market: str, channel: str, at: datetime, *,
                        historical: bool = False) -> list[tuple[dict, str]]:
	"""Contracts that can sell for this hotel/market/channel at sale time ``at``
	→ [(contract row, version name)], highest priority first.

	The header only says whether a contract sells at all (its status); market, channels, sale
	window, priority and default sell currency are those of the version live at ``at``
	(``selling_terms``: what it froze, narrowed by its header snapshot if it was frozen before
	G-50), so selection is the same whenever it is re-run for ``at`` (G-50, ADR-045).

	``historical``: selection for a moment that has passed (the simulator, a reprice on the
	original or a historical sale date, a guest's change re-derived as of its price): the status
	is the one the contract had at ``at`` (``statuses_at``), so a contract archived or suspended
	since is a candidate for a time it was Active, and one suspended then is not (G-51,
	ADR-054). Otherwise the live status: a stop sale acts now (ADR-045)."""
	fields = ["name", "contract_code", "contract_name", "is_bar", "status"]
	if historical:
		# a Draft contract never published a version: it never sold
		rows = frappe.get_all("TEX Contract", filters={"property": property, "status": ("!=", "Draft")},
		                      fields=fields, order_by="name asc")
		then = statuses_at(rows, at)
		rows = [r for r in rows if then.get(r.name) == "Active"]
	else:
		rows = frappe.get_all("TEX Contract", filters={"property": property, "status": "Active"},
		                      fields=fields, order_by="name asc")
	out = []
	sale = getdate(at)
	for r in rows:
		h = active_version_header(r.name, at)
		if not h:
			continue
		t = load_terms(h.version_id)
		if t.property != property:
			continue
		st = selling_terms(h.version_id, t)
		# closed for this market, sale date (G-17) or channel: never a candidate
		if not st.admits(market, channel, sale):
			continue
		out.append((frappe._dict(
			name=r.name, contract_code=r.contract_code, contract_name=r.contract_name, is_bar=r.is_bar,
			status_now=r.status, market=t.market, specific=market in st.markets, contract_currency=t.currency,
			priority=st.priority, sell_currency=st.sell_currency, channels=sorted(st.channels or ()),
			sale_from=st.sale_from, sale_to=st.sale_to, stay_from=st.stay_from, stay_to=st.stay_to), h.version_id))
	# a market-specific contract beats the GLOBAL fallback; then priority
	out.sort(key=lambda x: (not x[0].specific, -(x[0].priority or 0), x[0].name))
	return out


class DraftChanged(frappe.TimestampMismatchError):
	"""A draft save made from a read older than the draft (O-10, ADR-069): someone else saved it since."""


def check_draft_token(name: str, expected) -> None:
	"""O-10 (ADR-069): refuse a draft save made from a read older than the draft. The draft's
	``modified`` (never NULL) and who changed it are read under a row lock, so two saves from one read
	cannot both pass; a different time raises ``DraftChanged`` naming who changed it and when."""
	row = frappe.db.get_value("TEX Contract Version", name, ["modified", "modified_by"], as_dict=True,
	                          for_update=True)
	if not row:
		frappe.throw(_("Contract version {0} not found.").format(name), frappe.DoesNotExistError)
	if get_datetime(row.modified) != get_datetime(expected):
		who = frappe.utils.get_fullname(row.modified_by) if row.modified_by else _("someone")
		frappe.throw(_("This draft was changed by {0} at {1}; reload it before saving.").format(
			who, get_datetime(row.modified).replace(microsecond=0)), DraftChanged, title=_("Draft changed"))


class ContractNotOnSale(frappe.ValidationError):
	"""An offer or quote of a contract that stopped selling after it was made (ADR-045)."""
	code = "CONTRACT_NOT_ON_SALE"


class ContractSuspended(ContractNotOnSale):
	code = "CONTRACT_SUSPENDED"


def not_on_sale(contract: str, *, lock: bool = False) -> ContractNotOnSale | None:
	"""Why a contract's offers and quotes no longer sell (it is not Active), or None. ``lock``
	reads the status under a shared row lock, so a suspend waits for bookings in flight and every
	booking after it sees it."""
	if lock:
		row = frappe.db.sql("SELECT status FROM `tabTEX Contract` WHERE name=%s LOCK IN SHARE MODE", contract)
		status = row[0][0] if row else None
	else:
		status = frappe.db.get_value("TEX Contract", contract, "status")
	if status == "Active":
		return None
	cls = ContractSuspended if status == "Suspended" else ContractNotOnSale
	return cls(_("This rate is no longer on sale. Please search again."))


# ─── status (G-50, ADR-045) ──────────────────────────────────────────────

# action → (statuses it applies to, new status); a status never changes through a header edit
STATUS_ACTIONS = {
	"suspend": (("Active",), "Suspended"),                    # stop selling now; resume later
	"resume": (("Suspended",), "Active"),
	"archive": (("Draft", "Active", "Suspended"), "Archived"),
	"restore": (("Archived",), None),                         # → Suspended (or Draft if never published)
}


def status_actions(status: str | None) -> list[str]:
	return [a for a, (frm, _to) in STATUS_ACTIONS.items() if status in frm]


def set_status(contract: str, action: str, reason: str | None) -> dict:
	"""Suspend, resume, archive or restore a contract: capability-checked, locked and audited."""
	prop = frappe.db.get_value("TEX Contract", contract, "property")
	if not prop:
		frappe.throw(_("Contract {0} not found.").format(contract), frappe.DoesNotExistError)
	scope.require("contract.publish", prop)
	if action not in STATUS_ACTIONS:
		frappe.throw(_("Unknown contract action {0}.").format(action))
	if not (reason or "").strip():
		frappe.throw(_("A reason is required."))
	frappe.db.get_value("TEX Contract", contract, "name", for_update=True)
	doc = frappe.get_doc("TEX Contract", contract)
	allowed, target = STATUS_ACTIONS[action]
	if doc.status not in allowed:
		frappe.throw(_("A contract that is {0} cannot be changed this way (possible: {1}).").format(
			_(doc.status), ", ".join(status_actions(doc.status)) or "—"))
	if action == "resume" and not frappe.db.exists("TEX Contract Version",
	                                               {"contract": contract, "status": "Published"}):
		frappe.throw(_("Publish a version before resuming sales: this contract has nothing on sale."))
	if action == "restore":
		target = "Suspended" if is_published(contract) else "Draft"
	doc.status = target
	doc.flags.tex_status_action = True
	doc.flags.tex_status_reason = reason.strip()
	doc.save(ignore_permissions=True)
	return {"status": doc.status}
