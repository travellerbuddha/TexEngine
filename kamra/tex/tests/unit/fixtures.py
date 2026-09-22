"""Deterministic fixtures for the pure pricing tests.

Reference contract "DE-S27" (Germany Summer 2027), PERSON basis, EUR:

  periods  P1 01–15 Jun (base person 100), P2 16–30 Jun (110), P3 01 Jul–31 Aug (120)
  rooms    STD base; SUP ×1.15; DLX ×1.35; SUITE ×1.80 with 01–15 Aug override 245 (P3A)
  adults   A1 ×1.00, A2 ×1.00, A3 ×0.70
  bands    INF 0–2.99, CHA 3–6.99, CHB 7–11.99, TEEN 12–15.99
  children INF ×0, CHA 25 %, CHB 50 %, TEEN 70 %;
           1A+1C: child 1 100 %; 2A+2C: child 2 25 %
  boards   AI base; UAI +20/adult/night, children 50 %
"""

from __future__ import annotations

from dataclasses import replace
from datetime import date, datetime
from decimal import Decimal

from kamra.tex.pricing.enums import FxMode, Level, OccTarget, Op, PricingBasis
from kamra.tex.pricing.model import (
	AgeBand,
	BoardRule,
	ChildSpec,
	ContractTerms,
	FxSnapshot,
	OccupancyRule,
	Period,
	PricingContext,
	RatePlanTerms,
	RoomRule,
	RoomSpec,
	StayRequest,
)

D = Decimal


def bands():
	return (
		AgeBand("INF", "Infant", 0, 36, is_infant=True),
		AgeBand("CHA", "Child A", 36, 84),
		AgeBand("CHB", "Child B", 84, 144),
		AgeBand("TEEN", "Teen", 144, 192),
	)


def rooms():
	return {
		"STD": RoomSpec("STD", "Standard", max_adults=3, max_children=2, max_occupants=4),
		"SUP": RoomSpec("SUP", "Superior", max_adults=3, max_children=2, max_occupants=4),
		"DLX": RoomSpec("DLX", "Deluxe", max_adults=3, max_children=3, max_occupants=5),
		"SUITE": RoomSpec("SUITE", "Suite", max_adults=4, max_children=3, max_occupants=6),
	}


def periods():
	return (
		Period("P1", "1–15 Jun", date(2027, 6, 1), date(2027, 6, 15)),
		Period("P2", "16–30 Jun", date(2027, 6, 16), date(2027, 6, 30)),
		Period("P3", "Jul–Aug", date(2027, 7, 1), date(2027, 8, 31)),
		Period("P3A", "1–15 Aug", date(2027, 8, 1), date(2027, 8, 15), priority=1),
	)


def room_rules():
	return (
		RoomRule("R-STD-P1", "STD", "P1", Op.ABSOLUTE, D("100")),
		RoomRule("R-STD-P2", "STD", "P2", Op.ABSOLUTE, D("110")),
		RoomRule("R-STD-P3", "STD", "P3", Op.ABSOLUTE, D("120")),
		RoomRule("R-STD-P3A", "STD", "P3A", Op.ABSOLUTE, D("130")),
		RoomRule("R-SUP", "SUP", None, Op.MULTIPLY, D("1.15"), "STD"),
		RoomRule("R-DLX", "DLX", None, Op.MULTIPLY, D("1.35"), "STD"),
		RoomRule("R-SUITE", "SUITE", None, Op.MULTIPLY, D("1.80"), "STD"),
		RoomRule("R-SUITE-P3A", "SUITE", "P3A", Op.ABSOLUTE, D("245")),
	)


def occ_rules():
	return (
		OccupancyRule("O-A1", OccTarget.ADULT, Op.MULTIPLY, D("1.00"), position=1),
		OccupancyRule("O-A2", OccTarget.ADULT, Op.MULTIPLY, D("1.00"), position=2),
		OccupancyRule("O-A3", OccTarget.ADULT, Op.MULTIPLY, D("0.70"), position=3),
		OccupancyRule("O-INF", OccTarget.CHILD, Op.MULTIPLY, D("0"), age_band="INF"),
		OccupancyRule("O-CHA", OccTarget.CHILD, Op.PERCENT_OF, D("25"), age_band="CHA"),
		OccupancyRule("O-CHB", OccTarget.CHILD, Op.PERCENT_OF, D("50"), age_band="CHB"),
		OccupancyRule("O-TEEN", OccTarget.CHILD, Op.PERCENT_OF, D("70"), age_band="TEEN"),
		OccupancyRule("O-1A1C", OccTarget.CHILD, Op.PERCENT_OF, D("100"), position=1, adults=1, children=1,
		              age_band="CHB"),
		OccupancyRule("O-2A2C-C2", OccTarget.CHILD, Op.PERCENT_OF, D("25"), position=2, adults=2, children=2),
	)


def board_rules():
	return (
		BoardRule("B-AI", "AI", is_base=True),
		BoardRule("B-UAI", "UAI", op=Op.ADD, adult_amount=D("20"), child_percent=D("50")),
	)


def terms(**overrides) -> ContractTerms:
	base = ContractTerms(
		contract_id="C-DE-S27", contract_code="DE-S27", contract_name="Germany Summer 2027",
		version_id="C-DE-S27-V1", version_no=1, payload_hash="test", property="HOTEL-A", market="DE",
		currency="EUR", basis=PricingBasis.PERSON, rooms=rooms(), periods=periods(), room_rules=room_rules(),
		occupancy_rules=occ_rules(), age_bands=bands(), boards=board_rules(), rate_plans={},
		sale_from=date(2026, 10, 1), sale_to=date(2027, 8, 31), stay_from=date(2027, 6, 1),
		stay_to=date(2027, 8, 31), prices_include_tax=False,
	)
	return replace(base, **overrides)


def with_rate_plans(t: ContractTerms) -> ContractTerms:
	return replace(t, rate_plans={
		"FLEX": RatePlanTerms("FLEX", "Flexible", refundable=True),
		"NRF": RatePlanTerms("NRF", "Non-refundable", op=Op.ADJUST_PERCENT, value=D("-10"), refundable=False),
	})


def eur(as_of=None) -> FxSnapshot:
	return FxSnapshot("EUR", "EUR", FxMode.IDENTITY, D(1), as_of=as_of)


def ctx(t: ContractTerms | None = None, **kw) -> PricingContext:
	t = t or terms()
	fx = kw.pop("fx", None) or FxSnapshot(t.currency, t.currency, FxMode.IDENTITY, D(1))
	return PricingContext(terms=t, fx=fx, **kw)


def req(**kw) -> StayRequest:
	base = dict(property="HOTEL-A", room_type="STD", board="AI", check_in=date(2027, 6, 2),
	            check_out=date(2027, 6, 3), adults=2, sale_at=datetime(2027, 1, 15, 10, 0), market="DE",
	            channel="DIRECT_WEB", sell_currency="EUR")
	base.update(kw)
	if "children" in kw and kw["children"] and isinstance(kw["children"][0], int):
		base["children"] = tuple(ChildSpec(age=a) for a in kw["children"])
	return StayRequest(**base)


POLICY_HOTEL = Level.HOTEL
