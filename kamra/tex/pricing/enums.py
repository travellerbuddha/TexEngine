"""Enumerations of the TEX pricing domain (ADR-006, ADR-007). No frappe imports."""

from __future__ import annotations

from enum import IntEnum, StrEnum


class PricingBasis(StrEnum):
	ROOM = "ROOM"      # price per room per night, covering the included adults
	PERSON = "PERSON"  # base person rate; every occupant is a priced slot


class Op(StrEnum):
	"""Explicit rule operations. There is no implicit stacking anywhere.

	INHERIT         no value at this scope - use the next less specific rule
	ABSOLUTE        set the value (money) - e.g. Suite 01-15 Aug = 245
	FIXED           set a fixed money amount for a slot/unit (same maths as ABSOLUTE)
	MULTIPLY        reference x v            - e.g. Deluxe = base x 1.35
	PERCENT_OF      reference x v/100 (share) - e.g. child pays 50 % of the unit
	ADJUST_PERCENT  input x (1 + v/100)       - e.g. +10 %, -15 %
	ADD / SUBTRACT  input +/- v (money)
	"""

	INHERIT = "INHERIT"
	ABSOLUTE = "ABSOLUTE"
	FIXED = "FIXED"
	MULTIPLY = "MULTIPLY"
	PERCENT_OF = "PERCENT_OF"
	ADJUST_PERCENT = "ADJUST_PERCENT"
	ADD = "ADD"
	SUBTRACT = "SUBTRACT"


class Level(IntEnum):
	"""Rule precedence, least to most specific (PRODUCT_SPEC R-09)."""

	GLOBAL = 0
	HOTEL = 1
	MARKET = 2
	CONTRACT = 3
	VERSION = 4
	ROOM = 5
	PERIOD = 6
	COMBINATION = 7
	OVERRIDE = 8


class ChildOrdering(StrEnum):
	OLDEST_FIRST = "OLDEST_FIRST"      # 1st child = the oldest (default; TO convention)
	YOUNGEST_FIRST = "YOUNGEST_FIRST"
	AS_ENTERED = "AS_ENTERED"


class AgeBasis(StrEnum):
	ARRIVAL = "ARRIVAL"            # age evaluated on the check-in date (default)
	BOOKING_DATE = "BOOKING_DATE"  # age evaluated on the sale date


class SlotKind(StrEnum):
	ADULT = "ADULT"
	CHILD = "CHILD"


class OccTarget(StrEnum):
	ADULT = "ADULT"
	CHILD = "CHILD"
	COMBINATION = "COMBINATION"  # the whole room-night occupancy amount


class RoomBasisExtraUnit(StrEnum):
	PER_PERSON_SHARE = "PER_PERSON_SHARE"  # extra slots priced against room / included adults
	ROOM_PRICE = "ROOM_PRICE"              # extra slots priced against the full room price


class StayMatch(StrEnum):
	ANY_NIGHT = "ANY_NIGHT"    # applies to the nights inside the stay window
	ALL_NIGHTS = "ALL_NIGHTS"  # whole stay must be inside the window
	ARRIVAL = "ARRIVAL"        # arrival date inside the window -> whole stay
	DEPARTURE = "DEPARTURE"    # departure date inside the window -> whole stay


class PromoValueType(StrEnum):
	PERCENT = "PERCENT"            # discount %
	FIXED_STAY = "FIXED_STAY"      # money off once per room-stay
	FIXED_NIGHT = "FIXED_NIGHT"    # money off per eligible night
	MULTIPLIER = "MULTIPLIER"      # price x v (e.g. 0.85)
	FREE_NIGHTS = "FREE_NIGHTS"    # stay X pay Y (cheapest nights free)
	VALUE_ADDED = "VALUE_ADDED"    # no price change; adds an inclusion


class PromoStage(StrEnum):
	COST = "COST"  # reduces the contract cost before markup (e.g. EB on net)
	SELL = "SELL"  # reduces the selling price after markup and FX


class PromoAppliesTo(StrEnum):
	ACCOMMODATION = "ACCOMMODATION"
	EXTRAS = "EXTRAS"
	TOTAL = "TOTAL"


class StackingMode(StrEnum):
	SEQUENTIAL = "SEQUENTIAL"  # each promotion applies to the running price
	ADDITIVE = "ADDITIVE"      # percentages summed on the pre-promotion price


class MarkupCombine(StrEnum):
	REPLACE = "REPLACE"  # most specific REPLACE rule wins
	STACK = "STACK"      # applied on top of the REPLACE result, explicitly


class FxMode(StrEnum):
	IDENTITY = "IDENTITY"
	MANUAL = "MANUAL"
	PROVIDER = "PROVIDER"
	PROVIDER_PERCENT = "PROVIDER_PERCENT"
	PROVIDER_FIXED = "PROVIDER_FIXED"
	# a rate known only from a sold line of a snapshot priced before G-56 (``fx.recorded``):
	# reused, never resolved (no FX policy has this mode)
	RECORDED = "RECORDED"


class ExtraPricingMode(StrEnum):
	RESERVATION = "RESERVATION"      # once per booking
	ROOM = "ROOM"                    # once per room
	STAY = "STAY"                    # once per room-stay (flat)
	PERSON = "PERSON"                # per occupant (adult/child/infant amounts)
	ADULT = "ADULT"                  # per adult
	CHILD = "CHILD"                  # per non-infant child
	INFANT = "INFANT"                # per infant
	NIGHT = "NIGHT"                  # per night per room
	PERSON_NIGHT = "PERSON_NIGHT"    # per occupant per night
	SERVICE_DATE = "SERVICE_DATE"    # per selected service date
	UNIT = "UNIT"                    # per unit ordered
	USAGE = "USAGE"                  # per usage (e.g. spa session)


class TaxKind(StrEnum):
	PERCENT = "PERCENT"
	PER_PERSON_NIGHT = "PER_PERSON_NIGHT"
	PER_ROOM_NIGHT = "PER_ROOM_NIGHT"


class LineKind(StrEnum):
	ACCOMMODATION = "ACCOMMODATION"
	DISCOUNT = "DISCOUNT"
	EXTRA = "EXTRA"
	COUPON = "COUPON"
	TAX = "TAX"
