"""RestrictionResolver (R-16, ADR-008). Pure: no frappe imports.

Restrictions are daily cells scoped by (room_type, contract, market, rate_plan,
channel); a blank dimension means "all". For every date and every field the most
specific cell that sets the field wins. Specificity weights are unique powers of two
(contract 16, room 8, rate plan 4, market 2, channel 1), so two different scopes never
tie. Stop sell is tri-state: STOP / OPEN (explicitly re-open a broader stop) / unset.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta

STAY_THROUGH = "STAY_THROUGH"
ARRIVAL = "ARRIVAL"
DEPARTURE = "DEPARTURE"

FIELDS = ("stop_sell", "stop_sell_mode", "min_los", "max_los", "cta", "ctd", "release_days",
          "min_advance", "max_advance")


@dataclass(frozen=True, slots=True)
class RestrictionCell:
	cell_id: str
	day: date
	room_type: str | None = None
	contract: str | None = None
	market: str | None = None
	rate_plan: str | None = None
	channel: str | None = None
	stop_sell: str | None = None        # "STOP" / "OPEN" / None
	stop_sell_mode: str | None = None   # STAY_THROUGH / ARRIVAL / DEPARTURE
	min_los: int | None = None
	max_los: int | None = None
	cta: bool | None = None
	ctd: bool | None = None
	release_days: int | None = None
	min_advance: int | None = None
	max_advance: int | None = None

	@property
	def weight(self) -> int:
		return ((16 if self.contract else 0) | (8 if self.room_type else 0) | (4 if self.rate_plan else 0)
		        | (2 if self.market else 0) | (1 if self.channel else 0))

	def matches(self, s: RestrictionScope) -> bool:
		return ((self.room_type is None or self.room_type == s.room_type)
		        and (self.contract is None or self.contract == s.contract)
		        and (self.market is None or self.market == s.market)
		        and (self.rate_plan is None or self.rate_plan == s.rate_plan)
		        and (self.channel is None or self.channel == s.channel))


@dataclass(frozen=True, slots=True)
class RestrictionScope:
	room_type: str
	contract: str | None = None
	market: str | None = None
	rate_plan: str | None = None
	channel: str | None = None


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
	sources: dict = field(default_factory=dict)   # field → winning cell id

	def to_dict(self) -> dict:
		return {"date": self.day.isoformat(), "stop_sell": self.stop_sell, "stop_sell_mode": self.stop_sell_mode,
		        "min_los": self.min_los, "max_los": self.max_los, "cta": self.cta, "ctd": self.ctd,
		        "release_days": self.release_days, "min_advance": self.min_advance,
		        "max_advance": self.max_advance, "sources": dict(self.sources)}


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
