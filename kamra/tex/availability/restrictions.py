"""RestrictionResolver (R-16, ADR-008, ADR-057). Pure: no frappe imports.

Restrictions are daily cells scoped by (room_type, contract, market, rate_plan, channel); a
blank dimension means "all", so a cell without a room type is hotel-level (or market-level,
with a market). The channel dimension is one sales channel, or a product surface: the Booking
Engine, the Call Center, or both (``channel_scope``, G-48). For every date and every field the
most specific cell that sets the field wins. Specificity weights never tie: contract 32, room
16, rate plan 8, market 4, then the channel (a sales channel 3, one surface 2, both surfaces
1). Stop sell is tri-state: STOP / OPEN (explicitly re-open a broader stop) / unset.

The booking window (``book_from`` / ``book_to``) is a range of sale dates: a night is sold only
on a booking made inside its window (checked per night, like a stop sell). Minimum / maximum
advance and release are counted from the sale date to the arrival.

``evaluate_change`` applies the rules to a changed stay (ADR-057): only what the change newly
takes is checked, like a new booking would be.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta

STAY_THROUGH = "STAY_THROUGH"
ARRIVAL = "ARRIVAL"
DEPARTURE = "DEPARTURE"

# product surfaces a sales channel belongs to (the Frappe side decides which channel is which)
BOOKING_ENGINE = "BOOKING_ENGINE"
CALL_CENTER = "CALL_CENTER"
# a cell's channel scope (the stored values) → the surfaces it covers
SCOPE_BOOKING_ENGINE = "Booking Engine"
SCOPE_CALL_CENTER = "Call Center"
SCOPE_BOTH = "Booking Engine + Call Center"
CHANNEL_SCOPES: dict[str, frozenset[str]] = {
	SCOPE_BOOKING_ENGINE: frozenset({BOOKING_ENGINE}),
	SCOPE_CALL_CENTER: frozenset({CALL_CENTER}),
	SCOPE_BOTH: frozenset({BOOKING_ENGINE, CALL_CENTER}),
}

FIELDS = ("stop_sell", "stop_sell_mode", "min_los", "max_los", "cta", "ctd", "release_days",
          "min_advance", "max_advance", "book_from", "book_to")

# what each violation is about, for a changed stay (``evaluate_change``)
NIGHT_CODES = frozenset({"STOP_SELL", "BOOKING_WINDOW"})
ARRIVAL_CODES = frozenset({"STOP_SELL_ARRIVAL", "CTA", "RELEASE", "MIN_ADVANCE", "MAX_ADVANCE"})
DEPARTURE_CODES = frozenset({"STOP_SELL_DEPARTURE", "CTD"})
LENGTH_CODES = frozenset({"MIN_LOS", "MAX_LOS"})


@dataclass(frozen=True, slots=True)
class RestrictionCell:
	cell_id: str
	day: date
	room_type: str | None = None
	contract: str | None = None
	market: str | None = None
	rate_plan: str | None = None
	channel: str | None = None
	channel_scope: str | None = None    # SCOPE_* (a surface scope; never with ``channel``)
	stop_sell: str | None = None        # "STOP" / "OPEN" / None
	stop_sell_mode: str | None = None   # STAY_THROUGH / ARRIVAL / DEPARTURE
	min_los: int | None = None
	max_los: int | None = None
	cta: bool | None = None
	ctd: bool | None = None
	release_days: int | None = None
	min_advance: int | None = None
	max_advance: int | None = None
	book_from: date | None = None       # booking window: first sale date
	book_to: date | None = None         # booking window: last sale date

	@property
	def channel_level(self) -> int:
		if self.channel:
			return 3
		surfaces = CHANNEL_SCOPES.get(self.channel_scope or "")
		if surfaces is None:
			return 0
		return 2 if len(surfaces) == 1 else 1

	@property
	def weight(self) -> int:
		return ((32 if self.contract else 0) + (16 if self.room_type else 0) + (8 if self.rate_plan else 0)
		        + (4 if self.market else 0) + self.channel_level)

	def matches(self, s: RestrictionScope) -> bool:
		if self.channel_scope:
			surfaces = CHANNEL_SCOPES.get(self.channel_scope)
			if surfaces is None or s.surface not in surfaces:
				return False
		return ((self.room_type is None or self.room_type == s.room_type)
		        and (self.contract is None or self.contract == s.contract)
		        and (self.market is None or self.market == s.market)
		        and (self.rate_plan is None or self.rate_plan == s.rate_plan)
		        and (self.channel is None or self.channel == s.channel))


@dataclass(frozen=True, slots=True)
class RestrictionScope:
	room_type: str | None                # None: the hotel-level row of the grid (room-less cells only)
	contract: str | None = None
	market: str | None = None
	rate_plan: str | None = None
	channel: str | None = None
	surface: str | None = None           # BOOKING_ENGINE / CALL_CENTER / None (another channel)


@dataclass(frozen=True, slots=True)
class Effective:
	day: date
	stop_sell: bool = False
	stop_sell_mode: str = STAY_THROUGH
	min_los: int | None = None
	max_los: int | None = None
	cta: bool = False
	ctd: bool = False
	release_days: int | None = None
	min_advance: int | None = None
	max_advance: int | None = None
	book_from: date | None = None
	book_to: date | None = None
	sources: dict = field(default_factory=dict)   # field → winning cell id

	def to_dict(self) -> dict:
		return {"date": self.day.isoformat(), "stop_sell": self.stop_sell, "stop_sell_mode": self.stop_sell_mode,
		        "min_los": self.min_los, "max_los": self.max_los, "cta": self.cta, "ctd": self.ctd,
		        "release_days": self.release_days, "min_advance": self.min_advance,
		        "max_advance": self.max_advance, "book_from": _iso(self.book_from), "book_to": _iso(self.book_to),
		        "sources": dict(self.sources)}

	def sale_closed(self, sale_date: date) -> bool:
		"""This night cannot be sold on ``sale_date``: outside its booking window."""
		return bool((self.book_from and sale_date < self.book_from) or (self.book_to and sale_date > self.book_to))

	def arrival_closed(self, sale_date: date) -> bool:
		"""An arrival on this day cannot be sold on ``sale_date``: release, minimum or maximum
		advance (counted from the sale date to this day)."""
		lead = (self.day - sale_date).days
		return bool((self.release_days and lead < self.release_days)
		            or (self.min_advance and lead < self.min_advance)
		            or (self.max_advance and lead > self.max_advance))


def _iso(d: date | None) -> str | None:
	return d.isoformat() if d else None


@dataclass(frozen=True, slots=True)
class Violation:
	code: str
	day: date | None
	message: str
	cell_id: str | None = None

	def to_dict(self) -> dict:
		return {"code": self.code, "date": self.day.isoformat() if self.day else None,
		        "message": self.message, "cell": self.cell_id}


def effective(cells: list[RestrictionCell], scope: RestrictionScope, days: list[date]) -> dict[date, Effective]:
	by_day: dict[date, list[RestrictionCell]] = {}
	for c in cells:
		if c.matches(scope):
			by_day.setdefault(c.day, []).append(c)
	out: dict[date, Effective] = {}
	for d in days:
		ranked = sorted(by_day.get(d, []), key=lambda c: (c.weight, c.cell_id), reverse=True)
		vals: dict = {}
		src: dict = {}
		for f in FIELDS:
			for c in ranked:
				v = getattr(c, f)
				if v is None or v == "":
					continue
				vals[f] = v
				src[f] = c.cell_id
				break
		out[d] = Effective(
			day=d,
			stop_sell=vals.get("stop_sell") == "STOP",
			stop_sell_mode=vals.get("stop_sell_mode") or STAY_THROUGH,
			min_los=vals.get("min_los") or None,
			max_los=vals.get("max_los") or None,
			cta=bool(vals.get("cta")),
			ctd=bool(vals.get("ctd")),
			release_days=vals.get("release_days"),
			min_advance=vals.get("min_advance"),
			max_advance=vals.get("max_advance"),
			book_from=vals.get("book_from"),
			book_to=vals.get("book_to"),
			sources=src,
		)
	return out


def stay_days(check_in: date, check_out: date) -> list[date]:
	"""Arrival .. departure inclusive (departure matters for CTD / departure stop sell)."""
	return [check_in + timedelta(days=i) for i in range((check_out - check_in).days + 1)]


def evaluate(cells: list[RestrictionCell], scope: RestrictionScope, check_in: date, check_out: date,
             sale_date: date, *, min_los_basis: str = ARRIVAL) -> tuple[list[Violation], dict[date, Effective]]:
	"""Check a stay against the restrictions. → (violations, effective cells by day)."""
	days = stay_days(check_in, check_out)
	eff = effective(cells, scope, days)
	nights = days[:-1]
	los = len(nights)
	lead = (check_in - sale_date).days
	out: list[Violation] = []
	arr, dep = eff[check_in], eff[check_out]

	for n in nights:
		e = eff[n]
		if e.stop_sell and e.stop_sell_mode == STAY_THROUGH:
			out.append(Violation("STOP_SELL", n, f"stop sale on {n.isoformat()}", e.sources.get("stop_sell")))
		if e.book_from and sale_date < e.book_from:
			out.append(Violation("BOOKING_WINDOW", n, f"{n.isoformat()} is on sale from {e.book_from.isoformat()}",
			                     e.sources.get("book_from")))
		elif e.book_to and sale_date > e.book_to:
			out.append(Violation("BOOKING_WINDOW", n, f"{n.isoformat()} was on sale until {e.book_to.isoformat()}",
			                     e.sources.get("book_to")))
	if arr.stop_sell and arr.stop_sell_mode == ARRIVAL:
		out.append(Violation("STOP_SELL_ARRIVAL", check_in, "no arrivals on this date (stop sale)",
		                     arr.sources.get("stop_sell")))
	if dep.stop_sell and dep.stop_sell_mode == DEPARTURE:
		out.append(Violation("STOP_SELL_DEPARTURE", check_out, "no departures on this date (stop sale)",
		                     dep.sources.get("stop_sell")))
	if arr.cta:
		out.append(Violation("CTA", check_in, "closed to arrival", arr.sources.get("cta")))
	if dep.ctd:
		out.append(Violation("CTD", check_out, "closed to departure", dep.sources.get("ctd")))

	if min_los_basis == STAY_THROUGH:
		mins = [(eff[n].min_los, n) for n in nights if eff[n].min_los]
		need = max(mins, default=(None, None))
	else:
		need = (arr.min_los, check_in)
	if need[0] and los < need[0]:
		out.append(Violation("MIN_LOS", need[1], f"minimum stay {need[0]} nights", eff[need[1]].sources.get("min_los")))
	if arr.max_los and los > arr.max_los:
		out.append(Violation("MAX_LOS", check_in, f"maximum stay {arr.max_los} nights", arr.sources.get("max_los")))
	if arr.release_days is not None and arr.release_days > 0 and lead < arr.release_days:
		out.append(Violation("RELEASE", check_in, f"inside the {arr.release_days}-day release period",
		                     arr.sources.get("release_days")))
	if arr.min_advance is not None and arr.min_advance > 0 and lead < arr.min_advance:
		out.append(Violation("MIN_ADVANCE", check_in, f"book at least {arr.min_advance} days ahead",
		                     arr.sources.get("min_advance")))
	if arr.max_advance is not None and arr.max_advance > 0 and lead > arr.max_advance:
		out.append(Violation("MAX_ADVANCE", check_in, f"bookable at most {arr.max_advance} days ahead",
		                     arr.sources.get("max_advance")))
	return out, eff


def evaluate_change(cells: list[RestrictionCell], scope: RestrictionScope, check_in: date, check_out: date,
                    sale_date: date, *, before: tuple[date, date] | None, product_changed: bool = False,
                    min_los_basis: str = ARRIVAL) -> tuple[list[Violation], dict[date, Effective]]:
	"""Check a changed stay the way a new booking is checked, for what the change newly takes
	(G-48, ADR-057). ``before``: the (arrival, departure) the reservation holds now; None for a
	new sale, which is checked in full. ``product_changed``: the change sells another product
	(room type, contract, market or rate plan; the channel never changes).

	- a night the stay already holds is its own: a stop sell or a booking window on it never
	  refuses a change of the same product (held nights are not recounted for inventory either,
	  ADR-048); a new night, or every night of another product, is checked;
	- arrival rules (closed to arrival, arrival stop sell, release, minimum and maximum advance)
	  apply when the arrival changes or the product does; departure rules (closed to departure,
	  departure stop sell) when the departure changes or the product does;
	- the length of stay (minimum / maximum) is judged on the new stay when its dates change, or
	  when another product is sold for a stay not begun yet;
	- the past is not sold again: a night before the sale date is never judged, and neither is the
	  arrival of a stay under way (an in-house guest moved to another room or rate).
	An unchanged stay of the same product is never refused."""
	violations, eff = evaluate(cells, scope, check_in, check_out, sale_date, min_los_basis=min_los_basis)
	if before is None:
		return violations, eff
	held = set() if product_changed else set(stay_days(before[0], before[1])[:-1])
	arrival_moved = product_changed or check_in != before[0]
	departure_moved = product_changed or check_out != before[1]
	dates_moved = (check_in, check_out) != tuple(before)
	begun = check_in < sale_date
	out = []
	for v in violations:
		if v.code in NIGHT_CODES:
			keep = v.day not in held and v.day >= sale_date
		elif v.code in ARRIVAL_CODES:
			keep = arrival_moved and not begun
		elif v.code in DEPARTURE_CODES:
			keep = departure_moved
		elif v.code in LENGTH_CODES:
			keep = dates_moved or (product_changed and not begun)
		else:
			keep = True
		if keep:
			out.append(v)
	return out, eff
