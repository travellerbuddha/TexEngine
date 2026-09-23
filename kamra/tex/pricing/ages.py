"""ChildAgeResolver (ADR-007).

Ages are integer months - never floats - so band boundaries such as
2.99/3.00, 6.99/7.00 and 11.99/12.00 are exact:

* date of birth + reference date → completed months;
* a declared age of N years → 12·N months (a 2-year-old is in 0–2.99, a 3-year-old in 3–6.99);
* bands are half-open ``[from_months, to_months)``; "0–2.99" is stored as 0–36 months.

Band hygiene (G-52) is judged on that same month scale: a band ending at "2.95" ends at 35
months, so next to a band starting at 3 years month 35 is covered by no band and a child
of 2y11m cannot be sold. Such a gap, like an overlap, is refused (``band_problems``); a
band set starting above 0 months is a minimum child age, which only warns at publish.

A child's date of birth is the precise alternative to an age (``check_child_dob``): the
age is its completed months at the reference date, and a child is under
``MAX_CHILD_AGE`` + 1 years on arrival, the same ceiling a declared age has.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from itertools import pairwise

from kamra.tex.pricing.enums import AgeBasis, ChildOrdering
from kamra.tex.pricing.model import AgeBand, ChildSpec, ContractTerms, PricingError, Unsellable


def completed_months(dob: date, on: date) -> int:
	"""Whole months lived from ``dob`` to ``on`` (a birthday on 29 Feb is reached on
	1 Mar in non-leap years)."""
	if dob > on:
		raise PricingError(f"date of birth {dob.isoformat()} is after {on.isoformat()}")
	months = (on.year - dob.year) * 12 + (on.month - dob.month)
	if on.day < dob.day:
		months -= 1
	return months


def years_to_months(years) -> int:
	"""Band boundary in years (may be fractional, e.g. 2.5) → months, exact."""
	from decimal import ROUND_HALF_UP

	from kamra.tex.money import D

	return int((D(years) * 12).to_integral_value(rounding=ROUND_HALF_UP))


def child_months(spec: ChildSpec, reference: date) -> int:
	if spec.age_months is not None:
		if spec.age_months < 0:
			raise PricingError("child age cannot be negative")
		return int(spec.age_months)
	if spec.dob is not None:
		return completed_months(spec.dob, reference)
	if spec.age is None:
		raise PricingError("every child needs an age or a date of birth")
	if int(spec.age) < 0:
		raise PricingError("child age cannot be negative")
	return int(spec.age) * 12


MAX_CHILD_AGE = 17     # whole years; at 18 a guest is an adult (a declared age is 0–17 too)


def months_span(lo: int, hi: int) -> str:
	"""The months ``[lo, hi)`` for a message: "35 months (2y11m)", "24–35 months (2y–2y11m)"."""
	last = hi - 1
	if last <= lo:
		return f"{lo} months ({format_months(lo)})"
	return f"{lo}–{last} months ({format_months(lo)}–{format_months(last)})"


def band_problems(bands: tuple[AgeBand, ...]) -> list[str]:
	"""What makes a band set unusable, on the month scale pricing uses: an invalid range,
	two bands covering the same months, months between two bands that no band covers."""
	out = []
	ordered = sorted(bands, key=lambda b: (b.from_months, b.to_months, b.code))
	for b in ordered:
		if b.from_months < 0 or b.to_months <= b.from_months:
			out.append(f"age band {b.code} has an invalid range ({b.from_months}–{b.to_months} months)")
	valid = [b for b in ordered if 0 <= b.from_months < b.to_months]
	for a, b in pairwise(valid):
		if b.from_months < a.to_months:
			out.append(f"age bands {a.code} and {b.code} overlap at "
			           f"{months_span(b.from_months, min(a.to_months, b.to_months))}")
		elif b.from_months > a.to_months:
			out.append(f"age bands {a.code} and {b.code} leave a gap at {months_span(a.to_months, b.from_months)}: "
			           f"a child of that age matches no band and cannot be sold ({a.code} covers "
			           f"{months_span(a.from_months, a.to_months)}, {b.code} starts at {b.from_months} months); "
			           f"end {a.code} where {b.code} starts")
	return out


def validate_bands(bands: tuple[AgeBand, ...]) -> None:
	problems = band_problems(bands)
	if problems:
		raise PricingError("; ".join(problems))


def youngest_uncovered(bands: tuple[AgeBand, ...]) -> tuple[int, int] | None:
	"""``[0, first band)`` when the lowest band starts above 0 months: children that young
	match no band (a minimum child age)."""
	valid = [b for b in bands if 0 <= b.from_months < b.to_months]
	if not valid:
		return None
	first = min(b.from_months for b in valid)
	return (0, first) if first > 0 else None


def check_child_dob(dob: date, reference: date, *, today: date) -> int:
	"""A child's date of birth, checked: not in the future, and under ``MAX_CHILD_AGE`` + 1
	years on ``reference`` (arrival). → completed months on ``reference``."""
	if dob > today:
		raise PricingError(f"a child's date of birth ({dob.isoformat()}) is in the future")
	months = completed_months(dob, reference)
	if months >= (MAX_CHILD_AGE + 1) * 12:
		raise PricingError(f"a guest born on {dob.isoformat()} is {MAX_CHILD_AGE + 1} or older on arrival: "
		                   "book them as an adult")
	return months


def band_for(months: int, bands: tuple[AgeBand, ...]) -> AgeBand | None:
	for b in bands:
		if b.from_months <= months < b.to_months:
			return b
	return None


def format_months(months: int) -> str:
	y, m = divmod(months, 12)
	return f"{y}y{m}m" if m else f"{y}y"


@dataclass(frozen=True, slots=True)
class ChildSlot:
	position: int          # 1-based after ordering
	months: int
	band: AgeBand
	input_index: int       # index in the request's children list


@dataclass(frozen=True, slots=True)
class Party:
	adults: int                       # including children counted as adults
	declared_adults: int
	children: tuple[ChildSlot, ...]   # ordered per contract child_ordering
	children_as_adults: tuple[int, ...]  # input indexes of children priced as adults
	infants: int
	reference_date: date

	@property
	def child_count(self) -> int:
		return len(self.children)

	@property
	def occupants(self) -> int:
		return self.adults + len(self.children)


def classify_party(terms: ContractTerms, adults: int, children: tuple[ChildSpec, ...],
                   check_in: date, sale_date: date) -> Party:
	"""Map declared children to age bands and order them into child slots."""
	if adults < 0:
		raise PricingError("adults cannot be negative")
	reference = check_in if terms.age_basis == AgeBasis.ARRIVAL else sale_date
	bands = tuple(sorted(terms.age_bands, key=lambda b: b.from_months))
	top = max((b.to_months for b in bands), default=0)

	slots: list[tuple[int, int, AgeBand]] = []   # (input_index, months, band)
	as_adults: list[int] = []
	for idx, spec in enumerate(children):
		months = child_months(spec, reference)
		band = band_for(months, bands)
		if band is None:
			if months >= top and terms.children_over_max_as_adults:
				as_adults.append(idx)
				continue
			raise Unsellable("NO_AGE_BAND",
			                 f"child {idx + 1} (age {format_months(months)}) matches no age band of this contract",
			                 child=idx + 1)
		slots.append((idx, months, band))

	if terms.child_ordering == ChildOrdering.OLDEST_FIRST:
		slots.sort(key=lambda s: (-s[1], s[0]))
	elif terms.child_ordering == ChildOrdering.YOUNGEST_FIRST:
		slots.sort(key=lambda s: (s[1], s[0]))

	child_slots = tuple(
		ChildSlot(position=i + 1, months=m, band=b, input_index=idx)
		for i, (idx, m, b) in enumerate(slots)
	)
	return Party(
		adults=adults + len(as_adults),
		declared_adults=adults,
		children=child_slots,
		children_as_adults=tuple(as_adults),
		infants=sum(1 for s in child_slots if s.band.is_infant),
		reference_date=reference,
	)
