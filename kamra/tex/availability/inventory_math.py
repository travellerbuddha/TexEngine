"""Inventory arithmetic (R-17, ADR-008, ADR-048). Pure: no frappe imports.

Per pool and date:
    capacity  = base inventory + manual adjustment + oversell limit (explicit), 0 when closed
    free_pool = capacity − sold (all contracts) − withheld (unreleased guaranteed
                allotments of OTHER contracts, minus what those contracts already sold)
    available for contract X = min(free_pool, allotment_remaining(X)) when X has an unreleased
                allotment; free_pool once it is released; 0 once X's allotment is cut off

An allotment has two separate deadlines, both in days before the night (ADR-048):
    release — the hotel's side: unsold rooms go back to general sale (a guaranteed allotment
              stops being withheld, the contract's cap ends and it sells from general sale);
    cutoff  — the partner's side: the contract's booking deadline for that night; from then
              on it sells nothing more for it, and its unsold rooms go back to general sale at
              the latest then (nobody could book them otherwise). 0 = no cutoff.

A change of a booked stay is checked only on the nights it would newly take: the nights it
already holds in the pool are its own, whatever the capacity, a closure or a cutoff says now.
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
	cutoff_days: int = 0

	def released(self, sale_date: date) -> bool:
		"""Unsold rooms are back in general sale: at the release, or at the cutoff when that comes
		first (from then on the contract cannot book them, so nobody could)."""
		return (self.day - sale_date).days < max(self.release_days, self.cutoff_days)

	def cut_off(self, sale_date: date) -> bool:
		"""The contract's booking deadline for this night has passed."""
		return self.cutoff_days > 0 and (self.day - sale_date).days < self.cutoff_days


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
	if own is not None and own.cut_off(sale_date):
		# past the contract's booking deadline for this night: its rooms stay withheld from
		# everyone else until the release, but the contract itself sells nothing more
		return DayAvailability(p.day, cap, p.sold, withheld, free, None, 0, "closed" if p.closed else "cutoff")
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
                      sale_date: date, held: frozenset[date] = frozenset()) -> tuple[int, list[DayAvailability]]:
	"""Rooms bookable for every night of the stay (the minimum over nights).

	``held``: the nights a stay being changed already holds in this pool. They are not checked
	again, so only the nights it would newly take count (``per`` lists those); a change that
	takes no new night fits: 1."""
	per = [day_availability(p, allotments, contract, sale_date) for p in days if p.day not in held]
	if held and not per:
		return 1, []
	return (min((d.available for d in per), default=0), per)
