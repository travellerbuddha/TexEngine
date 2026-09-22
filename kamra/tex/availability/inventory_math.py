"""Inventory arithmetic (R-17, ADR-008). Pure: no frappe imports.

Per pool and date:
    capacity  = base inventory + manual adjustment + oversell limit (explicit), 0 when closed
    free_pool = capacity − sold (all contracts) − withheld (unreleased guaranteed
                allotments of OTHER contracts, minus what those contracts already sold)
    available for contract X = min(free_pool, allotment_remaining(X)) when X has an allotment
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True, slots=True)
class Allotment:
	allotment_id: str
	contract: str
	day: date
	rooms: int
	release_days: int = 0
	guaranteed: bool = False

	def released(self, sale_date: date) -> bool:
		return (self.day - sale_date).days < self.release_days


@dataclass(frozen=True, slots=True)
class PoolDay:
	day: date
	base_inventory: int
	manual_adjustment: int = 0
	oversell_limit: int = 0
	closed: bool = False
	sold: int = 0                                # live reservations covering this night
	sold_by_contract: tuple[tuple[str, int], ...] = ()

	def sold_for(self, contract: str | None) -> int:
		return dict(self.sold_by_contract).get(contract or "", 0)


@dataclass(frozen=True, slots=True)
class DayAvailability:
	day: date
	capacity: int
	sold: int
	withheld: int
	free_pool: int
	allotment_remaining: int | None
	available: int
	reason: str = ""


def capacity(p: PoolDay) -> int:
	if p.closed:
		return 0
	return max(0, p.base_inventory + p.manual_adjustment + max(0, p.oversell_limit))


def day_availability(p: PoolDay, allotments: list[Allotment], contract: str | None, sale_date: date
                     ) -> DayAvailability:
	cap = capacity(p)
	withheld = 0
	own: Allotment | None = None
	for a in allotments:
		if a.day != p.day:
			continue
		if contract and a.contract == contract:
			own = a
			continue
		if a.guaranteed and not a.released(sale_date):
			withheld += max(0, a.rooms - p.sold_for(a.contract))
	free = max(0, cap - p.sold - withheld)
	remaining: int | None = None
	if own is not None and not own.released(sale_date):
		# an unreleased allotment caps what this contract may sell; a guaranteed one
		# was withheld from everyone else, so it is covered by the free pool computed
		# above (which excludes only OTHER contracts' blocks)
		remaining = max(0, own.rooms - p.sold_for(contract))
		avail = min(remaining, free)
	else:
		# no allotment, or released: the contract sells from the free pool
		avail = free
	reason = "" if avail > 0 else ("closed" if p.closed else ("allotment used" if remaining == 0 else "sold out"))
	return DayAvailability(p.day, cap, p.sold, withheld, free, remaining, max(0, avail), reason)


def stay_availability(days: list[PoolDay], allotments: list[Allotment], contract: str | None,
                      sale_date: date) -> tuple[int, list[DayAvailability]]:
	"""Rooms bookable for every night of the stay (the minimum over nights)."""
	per = [day_availability(p, allotments, contract, sale_date) for p in days]
	return (min((d.available for d in per), default=0), per)
