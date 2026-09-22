"""Publish-time validation of contract terms.

A version can only be published with zero ERRORs. WARNINGs (e.g. an occupancy
combination with no child rule, which will simply be unsellable) are shown to the
contract manager before publishing.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from kamra.tex.money import ZERO, D
from kamra.tex.pricing import ages, occupancy, rooms
from kamra.tex.pricing.ages import ChildSlot, Party
from kamra.tex.pricing.enums import OccTarget, Op, PricingBasis, PromoValueType
from kamra.tex.pricing.model import ContractTerms, PricingError, Unsellable


@dataclass(frozen=True, slots=True)
class Issue:
	level: str   # ERROR / WARNING
	code: str
	message: str

	def to_dict(self) -> dict:
		return {"level": self.level, "code": self.code, "message": self.message}


def _err(code, msg):
	return Issue("ERROR", code, msg)


def _warn(code, msg):
	return Issue("WARNING", code, msg)


def validate_terms(t: ContractTerms, *, sweep_combinations: bool = True, max_warnings: int = 200) -> list[Issue]:
	issues: list[Issue] = []
	if len(t.currency) != 3:
		issues.append(_err("CURRENCY", f"currency {t.currency!r} is not an ISO code"))
	if not t.rooms:
		issues.append(_err("NO_ROOMS", "the contract sells no rooms"))
	if not t.periods:
		issues.append(_err("NO_PERIODS", "the contract has no stay periods"))
	if t.sale_from and t.sale_to and t.sale_from > t.sale_to:
		issues.append(_err("SALE_WINDOW", "sale window ends before it starts"))
	if t.stay_from and t.stay_to and t.stay_from > t.stay_to:
		issues.append(_err("STAY_WINDOW", "stay window ends before it starts"))

	for r in t.rooms.values():
		if r.max_adults < 1 or r.max_occupants < 1:
			issues.append(_err("ROOM_CAPACITY", f"{r.room_type}: capacity must allow at least one adult"))
		if r.max_occupants < r.max_adults:
			issues.append(_err("ROOM_CAPACITY", f"{r.room_type}: max occupants below max adults"))
		if t.basis == PricingBasis.ROOM and not (1 <= r.included_adults <= r.max_adults):
			issues.append(_err("INCLUDED_ADULTS", f"{r.room_type}: included adults must be 1..max adults"))

	# periods
	codes = [p.code for p in t.periods]
	for c in sorted({c for c in codes if codes.count(c) > 1}):
		issues.append(_err("PERIOD_DUPLICATE", f"period code {c} is used twice"))
	for p in t.periods:
		if p.start > p.end:
			issues.append(_err("PERIOD_RANGE", f"period {p.code} ends before it starts"))
	for i, a in enumerate(t.periods):
		for b in t.periods[i + 1:]:
			if a.start <= b.end and b.start <= a.end:
				same_kind = (a.weekdays is None) == (b.weekdays is None)
				days_overlap = a.weekdays is None or b.weekdays is None or bool(a.weekdays & b.weekdays)
				if same_kind and days_overlap and a.priority == b.priority:
					issues.append(_err("PERIOD_OVERLAP",
					                   f"periods {a.code} and {b.code} overlap with equal priority"))

	# room rules
	keys = [(r.room_type, r.period) for r in t.room_rules]
	for k in sorted({k for k in keys if keys.count(k) > 1}, key=str):
		issues.append(_err("ROOM_RULE_DUPLICATE", f"room {k[0]} has two rules for period {k[1] or 'all'}"))
	for r in t.room_rules:
		if r.room_type not in t.rooms:
			issues.append(_err("ROOM_RULE_UNKNOWN_ROOM", f"rule {r.rule_id} prices unknown room {r.room_type}"))
		if r.period and r.period not in codes:
			issues.append(_err("ROOM_RULE_UNKNOWN_PERIOD", f"rule {r.rule_id} names unknown period {r.period}"))
		if r.op not in (Op.ABSOLUTE, Op.FIXED, Op.INHERIT) and not r.base_room_type:
			issues.append(_err("ROOM_RULE_NO_BASE", f"rule {r.rule_id} derives a price but names no base room"))
	for p in t.periods:
		for rt in sorted(t.rooms):
			try:
				unit = rooms.room_unit(t, rt, p)
				if unit < ZERO:
					issues.append(_err("ROOM_NEGATIVE", f"{rt} prices below zero in {p.code}"))
			except Unsellable as u:
				issues.append(_err(u.code, f"{rt} / {p.code}: {u.message}"))

	# age bands
	try:
		ages.validate_bands(t.age_bands)
	except PricingError as e:
		issues.append(_err("AGE_BANDS", str(e)))
	band_codes = {b.code for b in t.age_bands}

	# occupancy rules
	for r in t.occupancy_rules:
		if r.age_band and r.age_band not in band_codes:
			issues.append(_err("OCC_UNKNOWN_BAND", f"rule {r.rule_id} names unknown age band {r.age_band}"))
		if r.target == OccTarget.COMBINATION and r.adults is None and r.children is None:
			issues.append(_err("OCC_COMBINATION_QUALIFIER", f"combination rule {r.rule_id} needs adults/children"))
		if r.target == OccTarget.ADULT and r.age_band:
			issues.append(_err("OCC_ADULT_BAND", f"adult rule {r.rule_id} cannot name an age band"))
		if r.op != Op.INHERIT and r.value is None:
			issues.append(_err("OCC_NO_VALUE", f"rule {r.rule_id} has no value"))
		if r.room_type and r.room_type not in t.rooms:
			issues.append(_err("OCC_UNKNOWN_ROOM", f"rule {r.rule_id} names unknown room {r.room_type}"))
		if r.period and r.period not in codes:
			issues.append(_err("OCC_UNKNOWN_PERIOD", f"rule {r.rule_id} names unknown period {r.period}"))
	sig = [(r.target, r.position, r.age_band, r.room_type, r.period, r.adults, r.children, r.is_override,
	        r.base_level) for r in t.occupancy_rules if r.op != Op.INHERIT]
	for s in sorted({s for s in sig if sig.count(s) > 1}, key=str):
		issues.append(_err("OCC_DUPLICATE", f"two occupancy rules share the same scope {s}"))

	# boards
	if not any(b.is_base for b in t.boards):
		issues.append(_err("NO_BASE_BOARD", "no base board is included in the room price"))
	board_codes = {b.board for b in t.boards}
	for rp in t.rate_plans.values():
		for bd in sorted(rp.boards or ()):
			if bd not in board_codes:
				issues.append(_err("RATE_PLAN_BOARD", f"rate plan {rp.code} sells unknown board {bd}"))

	for o in t.offers:
		if o.value_type == PromoValueType.PERCENT and not (ZERO < D(o.value) <= D(100)):
			issues.append(_err("OFFER_VALUE", f"offer {o.promo_id}: percent must be in (0, 100]"))
		if o.value_type == PromoValueType.FREE_NIGHTS and (
				not o.free_nights_stay or o.free_nights_pay is None or o.free_nights_pay >= o.free_nights_stay):
			issues.append(_err("OFFER_FREE_NIGHTS", f"offer {o.promo_id}: stay X pay Y needs X > Y"))

	if sweep_combinations and not any(i.level == "ERROR" for i in issues):
		issues.extend(_sweep(t, max_warnings))
	return issues


def _sweep(t: ContractTerms, limit: int) -> list[Issue]:
	"""Price every valid combination (all children in one band) once per period and
	report the ones that cannot be priced."""
	out: list[Issue] = []
	seen: set[tuple] = set()
	for rt, spec in sorted(t.rooms.items()):
		for p in t.periods:
			try:
				unit = rooms.room_unit(t, rt, p)
			except Unsellable:
				continue
			for a in range(max(1, spec.min_adults), spec.max_adults + 1):
				for c in range(0, spec.max_children + 1):
					if a + c > spec.max_occupants:
						continue
					for band in (t.age_bands if c else (None,)):
						slots = tuple(ChildSlot(i + 1, band.from_months, band, i) for i in range(c)) if band else ()
						party = Party(adults=a, declared_adults=a, children=slots, children_as_adults=(),
						              infants=sum(1 for s in slots if s.band.is_infant), reference_date=p.start)
						try:
							occupancy.price_occupancy(t, spec, p, unit, party)
						except Unsellable as u:
							key = (rt, a, c, band.code if band else None, u.code)
							if key in seen:
								continue
							seen.add(key)
							out.append(_warn(u.code, f"{rt} {a}A+{c}C"
							                 f"{' [' + band.code + ']' if band else ''}: {u.message}"))
							if len(out) >= limit:
								return out
	return out
