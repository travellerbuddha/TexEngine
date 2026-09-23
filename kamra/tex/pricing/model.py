"""Immutable data structures of the TEX pricing domain.

The contract structures mirror the frozen payload of a published Contract Version
(ADR-004). Everything here is plain data - no behaviour that touches a database.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal

from kamra.tex.pricing.enums import (
	AgeBasis,
	ChildOrdering,
	ExtraPricingMode,
	FxMode,
	Level,
	MarkupCombine,
	OccTarget,
	Op,
	PricingBasis,
	PromoAppliesTo,
	PromoStage,
	PromoValueType,
	RoomBasisExtraUnit,
	StackingMode,
	StayMatch,
	TaxKind,
)


class PricingError(Exception):
	"""Raised for invalid inputs/configuration the caller must fix (not 'unsellable')."""


class Unsellable(Exception):
	"""The requested product cannot be sold as asked (no price for a night, no
	occupancy rule for a child band, over capacity, outside the sale window...).
	Carries a machine code and a human message; the engine turns it into an
	unsellable quote rather than guessing a price."""

	def __init__(self, code: str, message: str, **params):
		super().__init__(message)
		self.code = code
		self.message = message
		self.params = params


# ─── references & explanation ────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class RuleRef:
	"""Identifies the rule that produced a value, for the explanation/audit."""

	kind: str               # "room_rule", "occupancy_rule", "markup", "promotion", ...
	rule_id: str
	level: Level | None = None
	source: str = ""        # "version", "policy:<name>", "global-default", "promotion:<rev>"
	label: str = ""

	def to_dict(self) -> dict:
		return {
			"kind": self.kind, "rule_id": self.rule_id,
			"level": self.level.name if self.level is not None else None,
			"source": self.source, "label": self.label,
		}


# ─── contract terms (frozen payload) ─────────────────────────────────────


@dataclass(frozen=True, slots=True)
class AgeBand:
	code: str
	label: str
	from_months: int   # inclusive
	to_months: int     # exclusive
	is_infant: bool = False


@dataclass(frozen=True, slots=True)
class Period:
	code: str
	name: str
	start: date        # inclusive
	end: date          # inclusive
	weekdays: frozenset[int] | None = None   # 0=Mon..6=Sun; None = every day
	adjustment_op: Op | None = None          # optional night adjustment for this period
	adjustment_value: Decimal | None = None
	priority: int = 0

	def covers(self, d: date) -> bool:
		if not (self.start <= d <= self.end):
			return False
		return self.weekdays is None or d.weekday() in self.weekdays


@dataclass(frozen=True, slots=True)
class RoomSpec:
	room_type: str
	name: str
	max_adults: int
	max_children: int
	max_occupants: int
	min_adults: int = 1
	included_adults: int = 2   # ROOM basis: adults covered by the room price


@dataclass(frozen=True, slots=True)
class RoomRule:
	"""Room price for (room_type, period). period=None → applies to every period.

	ABSOLUTE sets the unit; MULTIPLY/ADJUST_PERCENT/ADD/SUBTRACT/PERCENT_OF derive it
	from ``base_room_type``'s unit in the same period; INHERIT defers to the
	less-specific rule.
	"""

	rule_id: str
	room_type: str
	period: str | None
	op: Op
	value: Decimal | None
	base_room_type: str | None = None


@dataclass(frozen=True, slots=True)
class OccupancyRule:
	rule_id: str
	target: OccTarget
	op: Op
	value: Decimal | None
	position: int | None = None        # slot position (1-based) for ADULT/CHILD
	age_band: str | None = None        # CHILD only
	room_type: str | None = None
	period: str | None = None
	adults: int | None = None          # combination qualifier
	children: int | None = None        # combination qualifier
	is_override: bool = False          # SPECIFIC OVERRIDE level
	base_level: Level = Level.VERSION  # GLOBAL/HOTEL/MARKET for inherited policy rules
	source: str = "version"
	note: str = ""


@dataclass(frozen=True, slots=True)
class BoardRule:
	"""Board (meal plan) pricing. The base board is included in the room price.

	op=ADD: adult_amount per adult per night; children pay child_percent % of it
	(or band_percents[band]); infants free unless infant_free is False.
	op=ADJUST_PERCENT: the night's occupancy amount is adjusted by adult_amount %.
	"""

	rule_id: str
	board: str
	is_base: bool = False
	op: Op = Op.ADD
	adult_amount: Decimal = Decimal(0)
	child_percent: Decimal = Decimal(50)
	band_percents: tuple[tuple[str, Decimal], ...] = ()
	infant_free: bool = True
	room_type: str | None = None
	period: str | None = None
	label: str = ""


@dataclass(frozen=True, slots=True)
class RatePlanTerms:
	code: str
	name: str
	op: Op | None = None               # adjustment on the night amount (e.g. NRF -10 %)
	value: Decimal | None = None
	refundable: bool = True
	boards: frozenset[str] | None = None  # allowed boards; None = all
	cancellation_policy: dict | None = None
	payment_policy: dict | None = None
	inclusions: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class Promotion:
	promo_id: str
	name: str
	value_type: PromoValueType
	value: Decimal = Decimal(0)
	kind: str = "PROMOTION"   # EARLY_BOOKING, LAST_MINUTE, LONG_STAY, MEMBER, PROMO_CODE, ...
	stage: PromoStage = PromoStage.SELL
	applies_to: PromoAppliesTo = PromoAppliesTo.ACCOMMODATION
	currency: str | None = None        # for fixed amounts
	code: str | None = None            # coupon / promo code (None = automatic)
	sale_from: date | None = None
	sale_to: date | None = None
	stay_from: date | None = None
	stay_to: date | None = None
	stay_match: StayMatch = StayMatch.ANY_NIGHT
	min_nights: int | None = None
	max_nights: int | None = None
	min_lead_days: int | None = None   # days between sale date and arrival
	max_lead_days: int | None = None
	markets: frozenset[str] | None = None
	channels: frozenset[str] | None = None
	room_types: frozenset[str] | None = None
	boards: frozenset[str] | None = None
	rate_plans: frozenset[str] | None = None
	contracts: frozenset[str] | None = None
	requires_extras: frozenset[str] | None = None   # package promotions
	member_only: bool = False
	min_basket: Decimal | None = None
	stackable: bool = True
	exclusive: bool = False
	priority: int = 0
	group: str | None = None           # incompatible group
	free_nights_stay: int | None = None
	free_nights_pay: int | None = None
	value_added: str = ""
	source: str = "promotion"          # "contract" for contract offers
	usage_limit: int | None = None
	per_guest_limit: int | None = None


@dataclass(frozen=True, slots=True)
class ContractTerms:
	contract_id: str
	contract_code: str
	contract_name: str
	version_id: str
	version_no: int
	payload_hash: str
	property: str
	market: str
	currency: str
	basis: PricingBasis
	rooms: dict[str, RoomSpec]
	periods: tuple[Period, ...]
	room_rules: tuple[RoomRule, ...]
	occupancy_rules: tuple[OccupancyRule, ...]
	age_bands: tuple[AgeBand, ...]
	boards: tuple[BoardRule, ...]
	rate_plans: dict[str, RatePlanTerms]
	offers: tuple[Promotion, ...] = ()
	sale_from: date | None = None
	sale_to: date | None = None
	stay_from: date | None = None
	stay_to: date | None = None
	channels: frozenset[str] | None = None
	# selection order and default sell currency (G-50, ADR-045); None = the payload was frozen
	# before they were, and selection falls back to the contract header
	priority: int | None = None
	sell_currency: str | None = None
	child_ordering: ChildOrdering = ChildOrdering.OLDEST_FIRST
	age_basis: AgeBasis = AgeBasis.ARRIVAL
	children_over_max_as_adults: bool = True
	infants_count_as_occupants: bool = True
	prices_include_tax: bool = True
	stacking: StackingMode = StackingMode.SEQUENTIAL
	room_basis_extra_unit: RoomBasisExtraUnit = RoomBasisExtraUnit.PER_PERSON_SHARE
	room_basis_children_fill_included: bool = False   # children occupy unused included places


# ─── selling policies ────────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class MarkupRule:
	rule_id: str
	op: Op                        # ADJUST_PERCENT / MULTIPLY / ADD
	value: Decimal
	property: str | None = None   # None = global
	market: str | None = None
	contract: str | None = None
	room_type: str | None = None
	channel: str | None = None
	stay_from: date | None = None
	stay_to: date | None = None
	currency: str | None = None   # for ADD amounts
	combine: MarkupCombine = MarkupCombine.REPLACE
	priority: int = 0
	label: str = ""
	revision: str = ""


@dataclass(frozen=True, slots=True)
class FxSnapshot:
	from_currency: str
	to_currency: str
	mode: FxMode
	sell_rate: Decimal
	provider: str | None = None
	provider_rate: Decimal | None = None
	provider_rate_id: str | None = None
	rate_date: date | None = None
	adjustment: Decimal | None = None
	policy_id: str | None = None
	as_of: datetime | None = None

	def to_dict(self) -> dict:
		from kamra.tex.money import to_str6

		return {
			"from": self.from_currency, "to": self.to_currency, "mode": self.mode.value,
			"sell_rate": to_str6(self.sell_rate), "provider": self.provider,
			"provider_rate": to_str6(self.provider_rate), "provider_rate_id": self.provider_rate_id,
			"rate_date": self.rate_date.isoformat() if self.rate_date else None,
			"adjustment": to_str6(self.adjustment), "policy_id": self.policy_id,
			"as_of": self.as_of.isoformat() if self.as_of else None,
		}


@dataclass(frozen=True, slots=True)
class TaxRule:
	code: str
	name: str
	kind: TaxKind = TaxKind.PERCENT
	rate: Decimal = Decimal(0)        # percent for PERCENT
	amount: Decimal = Decimal(0)      # money for fixed kinds, in ``currency``
	applies_to: frozenset[str] = frozenset({"ACCOMMODATION"})  # ACCOMMODATION, EXTRA:<cat>, EXTRA:*
	compound: bool = False            # computed on base + previous taxes
	order: int = 0
	# optional rate slabs by nightly tariff: ((threshold or None=∞, rate), …), first match wins
	slabs: tuple[tuple[Decimal | None, Decimal], ...] = ()
	source: str | None = None         # where it came from: "tax_policy:<rev>", "property:<hotel>", "pack:<pack>"
	currency: str | None = None       # currency of a fixed ``amount``; None: the sell currency (G-20)


@dataclass(frozen=True, slots=True)
class ExtraPriceRule:
	rule_id: str
	amount: Decimal
	child_amount: Decimal | None = None
	infant_amount: Decimal | None = None
	market: str | None = None
	room_type: str | None = None
	channel: str | None = None
	stay_from: date | None = None
	stay_to: date | None = None
	sale_from: date | None = None
	sale_to: date | None = None
	service_from: date | None = None
	service_to: date | None = None
	priority: int = 0


@dataclass(frozen=True, slots=True)
class ExtraDef:
	code: str
	name: str
	pricing_mode: ExtraPricingMode
	currency: str
	amount: Decimal
	child_amount: Decimal | None = None
	infant_amount: Decimal | None = None
	category: str = "SERVICE"
	tax_category: str = "SERVICE"
	mandatory: bool = False
	sale_from: date | None = None
	sale_to: date | None = None
	service_from: date | None = None
	service_to: date | None = None
	markets: frozenset[str] | None = None
	channels: frozenset[str] | None = None
	room_types: frozenset[str] | None = None
	max_quantity: int | None = None
	price_rules: tuple[ExtraPriceRule, ...] = ()
	inventory_tracked: bool = False
	revision: str | None = None       # the extra revision live at the sale time (G-20)
	cutoff_hours: int = 0             # added after booking: at least this long before the day it is used (G-22)


@dataclass(frozen=True, slots=True)
class ExtraDayAvailability:
	"""How many more units of a capacity-limited extra can be sold on one day (G-19)."""

	remaining: int
	closed: bool = False


# ─── request ─────────────────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class ChildSpec:
	"""A child in the party. Give ``dob`` when known (preferred), else ``age``
	in whole years, or ``age_months`` explicitly."""

	age: int | None = None
	dob: date | None = None
	age_months: int | None = None


@dataclass(frozen=True, slots=True)
class ExtraRequest:
	code: str
	quantity: int = 1
	service_dates: tuple[date, ...] = ()


@dataclass(frozen=True, slots=True)
class StayRequest:
	property: str
	room_type: str
	board: str
	check_in: date
	check_out: date
	adults: int
	sale_at: datetime
	market: str
	channel: str
	sell_currency: str
	children: tuple[ChildSpec, ...] = ()
	rate_plan: str | None = None
	promo_codes: tuple[str, ...] = ()
	member: bool = False
	extras: tuple[ExtraRequest, ...] = ()
	# position of this room in its booking (0-based). Room 0 carries the booking-level
	# terms: per-booking extras and fixed booking discounts are priced once, there (ADR-029)
	room_index: int = 0


# ─── context ─────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class PricingContext:
	"""Everything the engine needs, resolved as of the sale time by the caller."""

	terms: ContractTerms
	fx: FxSnapshot                                  # contract currency → sell currency
	markups: tuple[MarkupRule, ...] = ()
	promotions: tuple[Promotion, ...] = ()          # standalone (incl. coupons)
	tax_rules: tuple[TaxRule, ...] = ()
	extras: dict[str, ExtraDef] = field(default_factory=dict)
	extra_fx: dict[str, FxSnapshot] = field(default_factory=dict)   # extra ccy → sell ccy
	promo_fx: dict[str, FxSnapshot] = field(default_factory=dict)   # promo ccy → sell ccy
	tax_fx: dict[str, FxSnapshot] = field(default_factory=dict)     # fixed levy ccy → sell ccy
	# capacity of the extras tracked now: code → day → availability (G-19). A code that is
	# absent is not limited; None means capacity is not checked (a historical simulation)
	extra_availability: dict[str, dict[date, ExtraDayAvailability]] | None = None
	coupon_usage: dict[str, tuple[int, int]] = field(default_factory=dict)  # promo_id → (total, this guest)
