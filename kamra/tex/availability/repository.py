"""Availability & restrictions repository (Frappe side of ADR-008).

Inventory pools, sold counts, allotments and restriction cells are loaded here and
evaluated with the pure functions in ``inventory_math`` / ``restrictions``.
``lock_nights`` serialises concurrent bookings of the same pool: it row-locks one
``TEX Inventory Day`` per night (created lazily, ascending date order), and the
caller recounts availability under the lock before inserting reservations.
``guard_reservation`` applies the same lock and recount to a reservation of a TEX hotel
written outside the TEX services (Desk, REST, imports; ADR-048).
"""

from __future__ import annotations

from datetime import date, timedelta

import frappe
from frappe import _
from frappe.utils import getdate, nowdate

from kamra.reservation_state import LIVE_STATUSES, holds_inventory
from kamra.tex.availability import inventory_math as inv
from kamra.tex.availability import restrictions as rs


def nights(check_in: date, check_out: date) -> list[date]:
	return [check_in + timedelta(days=i) for i in range((check_out - check_in).days)]


def pool_of(room_type: str) -> tuple[str, list[str]]:
	"""(pool key, room types in the pool). The key is the pool's first room type."""
	# an unknown room type (a write that skipped link validation) is a pool of its own, with no rooms
	prop, pool = frappe.db.get_value("Room Type", room_type, ["property", "tex_inventory_pool"]) or (None, None)
	if not pool:
		return room_type, [room_type]
	members = sorted(frappe.get_all("Room Type", filters={"property": prop, "tex_inventory_pool": pool,
	                                                      "disabled": 0}, pluck="name"))
	return members[0], members


def base_inventory(property: str, room_types: list[str]) -> int:
	mode = frappe.db.get_value("Property", property, "tex_inventory_mode") or "Physical rooms"
	if mode == "Configured":
		return int(sum(frappe.get_all("Room Type", filters={"name": ("in", room_types)},
		                              pluck="tex_sellable_inventory")) or 0)
	return frappe.db.count("Room", {"room_type": ("in", room_types)})


def _sold(room_types: list[str], days: list[date], exclude: list[str] | None = None, *, locking: bool = False
          ) -> tuple[dict[date, int], dict[date, dict[str, int]]]:
	"""Live reservation nights per day. ``locking=True`` makes it a locking read, which
	under REPEATABLE READ sees rows committed after this transaction's snapshot —
	mandatory for the recount done after ``lock_nights`` (a plain read would still see
	the snapshot taken before a competing booking committed, and oversell)."""
	if not days:
		return {}, {}
	start, end = days[0], days[-1] + timedelta(days=1)
	lock = " LOCK IN SHARE MODE" if locking else ""
	rows = frappe.db.sql(
		"""SELECT name, check_in_date, check_out_date, IFNULL(tex_contract, '') AS contract
		   FROM `tabReservation`
		   WHERE room_type IN %(rts)s AND status IN %(live)s
		     AND check_in_date < %(end)s
		     AND GREATEST(check_out_date, DATE_ADD(check_in_date, INTERVAL 1 DAY)) > %(start)s
		     AND name NOT IN %(ex)s""" + lock,
		{"rts": tuple(room_types), "live": LIVE_STATUSES, "start": start, "end": end,
		 "ex": tuple(exclude or ["__none__"])}, as_dict=True)
	total = {d: 0 for d in days}
	by_contract: dict[date, dict[str, int]] = {d: {} for d in days}
	wanted = set(days)
	for r in rows:
		ci, co = getdate(r.check_in_date), getdate(r.check_out_date)
		co = max(co, ci + timedelta(days=1))
		d = max(ci, start)
		while d < co:
			if d in wanted:
				total[d] += 1
				by_contract[d][r.contract] = by_contract[d].get(r.contract, 0) + 1
			d += timedelta(days=1)
	return total, by_contract


def _inventory_rows(pool_key: str, days: list[date], *, locking: bool = False) -> dict[date, dict]:
	cols = "inventory_date, base_inventory, manual_adjustment, oversell_limit, closed"
	if locking:
		# after lock_nights: the rows this transaction already holds, read by primary key.
		# A range read would take next-key (gap) locks reaching into other pools' rows, and
		# two bookings of different room types then deadlock
		from kamra.tex_commercial.doctype.tex_inventory_day.tex_inventory_day import inventory_day_name

		rows = frappe.db.sql(f"SELECT {cols} FROM `tabTEX Inventory Day` WHERE name IN %(n)s FOR UPDATE",
		                     {"n": tuple(inventory_day_name(pool_key, d) for d in days)}, as_dict=True)
	else:
		rows = frappe.db.sql(f"""SELECT {cols} FROM `tabTEX Inventory Day`
		                         WHERE room_type=%(p)s AND inventory_date BETWEEN %(a)s AND %(b)s""",
		                     {"p": pool_key, "a": days[0], "b": days[-1]}, as_dict=True)
	return {getdate(r.inventory_date): r for r in rows}


def _allotments(property: str, room_types: list[str], days: list[date]) -> list[inv.Allotment]:
	rows = frappe.get_all("TEX Allotment",
	                      filters={"property": property, "room_type": ("in", room_types), "disabled": 0,
	                               "date_from": ("<=", days[-1]), "date_to": (">=", days[0])},
	                      fields=["name", "contract", "date_from", "date_to", "rooms", "release_days", "guaranteed",
	                              "cutoff_days"])
	out = []
	for r in rows:
		d = max(getdate(r.date_from), days[0])
		while d <= min(getdate(r.date_to), days[-1]):
			out.append(inv.Allotment(r.name, r.contract, d, int(r.rooms or 0), int(r.release_days or 0),
			                         bool(r.guaranteed), int(r.cutoff_days or 0)))
			d += timedelta(days=1)
	return out


def pool_days(property: str, room_type: str, days: list[date], *, exclude: list[str] | None = None,
              locking: bool = False) -> tuple[list[inv.PoolDay], list[inv.Allotment]]:
	pool_key, members = pool_of(room_type)
	base = base_inventory(property, members)
	sold, by_contract = _sold(members, days, exclude, locking=locking)
	rows = _inventory_rows(pool_key, days, locking=locking) if days else {}
	out = []
	for d in days:
		r = rows.get(d)
		out.append(inv.PoolDay(
			day=d, base_inventory=int(r.base_inventory) if r and r.base_inventory else base,
			manual_adjustment=int(r.manual_adjustment or 0) if r else 0,
			oversell_limit=int(r.oversell_limit or 0) if r else 0, closed=bool(r.closed) if r else False,
			sold=sold.get(d, 0), sold_by_contract=tuple(sorted(by_contract.get(d, {}).items()))))
	return out, _allotments(property, members, days) if days else []


def stay_availability(property: str, room_type: str, contract: str | None, check_in: date, check_out: date,
                      sale_date: date, *, exclude: list[str] | None = None, locking: bool = False,
                      held: frozenset[date] | None = None) -> tuple[int, list[inv.DayAvailability]]:
	"""Rooms bookable for the stay. Pass ``locking=True`` after ``lock_nights``.

	``held``: for a change of a booked stay, the nights it already holds in this pool
	(``held_nights``). Only the other nights are read and checked (G-49 review, ADR-048)."""
	held = held or frozenset()
	days = [d for d in nights(check_in, check_out) if d not in held]
	pdays, allot = pool_days(property, room_type, days, exclude=exclude, locking=locking)
	return inv.stay_availability(pdays, allot, contract, sale_date, held=held)


def stay_nights(check_in, check_out) -> list[date]:
	"""The nights a stay holds; a day-use stay (out the day it arrives) holds its day."""
	ci = getdate(check_in)
	return nights(ci, max(getdate(check_out), ci + timedelta(days=1)))


def held_nights(room_type: str, holder) -> frozenset[date]:
	"""The nights ``holder`` (a reservation as it is stored) holds in ``room_type``'s pool: none
	when it holds no room or holds them in another pool (another hotel or room type pool)."""
	if holder is None or not holds_inventory(holder.get("status")) or not holder.get("room_type"):
		return frozenset()
	if not holder.get("check_in_date") or not holder.get("check_out_date"):
		return frozenset()
	if pool_of(holder.get("room_type"))[0] != pool_of(room_type)[0]:
		return frozenset()
	return frozenset(stay_nights(holder.get("check_in_date"), holder.get("check_out_date")))


def lock_nights(property: str, requests: list[tuple[str, date, date]]) -> None:
	"""Row-lock the inventory days of every (room_type, check_in, check_out), in a
	global (pool, date) order so concurrent multi-room bookings cannot deadlock."""
	from kamra.tex_commercial.doctype.tex_inventory_day.tex_inventory_day import inventory_day_name

	keys = set()
	for rt, ci, co in requests:
		pool_key, _ = pool_of(rt)
		for d in nights(ci, co):
			keys.add((pool_key, d))
	for pool_key, d in sorted(keys):
		# INSERT … ON DUPLICATE KEY UPDATE takes the EXCLUSIVE row lock straight away,
		# whether it creates the row or finds it. (INSERT IGNORE would take a shared lock
		# on an existing row and a later FOR UPDATE would upgrade it — two racers holding
		# shared locks then deadlock on the upgrade.)
		frappe.db.sql(
			"""INSERT INTO `tabTEX Inventory Day`
			   (name, creation, modified, owner, modified_by, docstatus, property, room_type, inventory_date,
			    base_inventory, manual_adjustment, oversell_limit, closed)
			   VALUES (%(n)s, NOW(), NOW(), 'Administrator', 'Administrator', 0, %(p)s, %(rt)s, %(d)s, 0, 0, 0, 0)
			   ON DUPLICATE KEY UPDATE `modified` = `modified`""",
			{"n": inventory_day_name(pool_key, d), "p": property, "rt": pool_key, "d": d})


# ─── reservations written outside the TEX services (G-49, ADR-048) ───────

STAY_FIELDS = ("property", "room_type", "check_in_date", "check_out_date")


def takes_inventory(doc) -> bool:
	"""This save makes the reservation hold rooms it did not hold before: a new live stay, a
	stay moving into a live status, or a live stay whose hotel, room type or nights change.
	Anything else (a note, a room assignment, check-in, payment) takes no room."""
	if not holds_inventory(doc.status):
		return False
	before = None if doc.is_new() else doc.get_doc_before_save()
	if before is None or not holds_inventory(before.status):
		return True
	for f in STAY_FIELDS:
		a, b = before.get(f), doc.get(f)
		if f.endswith("_date"):
			a, b = getdate(a) if a else None, getdate(b) if b else None
		if (a or None) != (b or None):
			return True
	return False


class InventoryBusy(frappe.ValidationError, frappe.QueryDeadlockError):
	"""A write outside TEX was chosen as a deadlock victim while it took or recounted a TEX
	hotel's nights: nothing of it was saved. Shown as "try again"; still a deadlock for the TEX
	endpoints' retry and for imports, which must stop (G-49 review)."""


def _busy() -> None:
	frappe.throw(_("Another booking was changing these nights at the same moment, so nothing was saved. "
	               "Please try again."), InventoryBusy, title=_("Please try again"))


def _outside_tex(doc) -> bool:
	return not (doc.flags.get("tex_inventory_checked") or doc.flags.get("tex_channel_accept"))


def _hotel_of(doc) -> str | None:
	"""The hotel whose inventory a reservation's room type is: its room type's hotel. None when
	the room type is another hotel's (``Reservation.validate`` refuses that, G-49 review)."""
	owner = frappe.db.get_value("Room Type", doc.room_type, "property") or doc.property
	return owner if owner == doc.property else None


def lock_before_naming(doc) -> None:
	"""``before_insert`` of a TEX hotel's reservation written outside TEX: take the nights'
	inventory locks before the reservation takes its name (the naming series row lock). A TEX
	booking locks in that order — inventory days, then names — so the two never wait on each
	other in a cycle. ``guard_reservation`` then recounts under these locks."""
	if not _outside_tex(doc) or not doc.room_type or not holds_inventory(doc.status):
		return
	if not doc.check_in_date or not doc.check_out_date:
		return
	hotel = _hotel_of(doc)
	if not hotel:
		return
	ci = getdate(doc.check_in_date)
	try:
		lock_nights(hotel, [(doc.room_type, ci, max(getdate(doc.check_out_date), ci + timedelta(days=1)))])
	except frappe.QueryDeadlockError:
		_busy()


def guard_reservation(doc) -> None:
	"""A TEX hotel's rooms are TEX inventory, whoever writes the reservation (ADR-048).

	The TEX services that sell or change a stay (booking, modification) lock the nights and
	recount for their contract before they write, and mark the document
	``flags.tex_inventory_checked`` for that one save; a channel's sale is accepted as sold
	(``flags.tex_channel_accept``, G-69). Flags live only in this process: a REST payload
	cannot set them. Every other write that takes rooms — the Desk form, REST, legacy imports
	and PMS actions — takes the same inventory lock here and is refused when TEX has no room
	left on a night it newly takes: closures, manual adjustments, the oversell limit, pools,
	configured inventory and guaranteed allotments all apply. The nights it already holds in
	the pool stay its own, so leaving early or moving to a room type of the same pool is never
	refused. It sells from general sale (no contract): it never uses a contract's allotment.
	Restrictions (stop sell, LOS, …) are selling rules of the TEX channels and do not apply."""
	# the service's word covers the save it was given for, not a later save of the same object
	if doc.flags.pop("tex_inventory_checked", None) or doc.flags.get("tex_channel_accept"):
		return
	if not doc.room_type or not takes_inventory(doc):
		return
	hotel = _hotel_of(doc)
	if not hotel:
		return
	before = None if doc.is_new() else doc.get_doc_before_save()
	held = held_nights(doc.room_type, before)
	new = [d for d in stay_nights(doc.check_in_date, doc.check_out_date) if d not in held]
	if not new:
		return
	try:
		lock_nights(hotel, [(doc.room_type, d, d + timedelta(days=1)) for d in new])
		count, per_day = stay_availability(hotel, doc.room_type, None, new[0], new[-1] + timedelta(days=1),
		                                   getdate(nowdate()), exclude=[doc.name] if doc.name else None,
		                                   locking=True, held=held)
	except frappe.QueryDeadlockError:
		_busy()
	if count >= 1:
		return
	day = next(d for d in per_day if d.available < 1)
	name = frappe.db.get_value("Room Type", doc.room_type, "room_type_name") or doc.room_type
	frappe.throw(
		_("{0} has no room left in TEX inventory on {1} ({2} sold, capacity {3}{4}). This hotel is sold "
		  "through TEX; to sell above its capacity, set a manual adjustment or an oversell limit in "
		  "Inventory.").format(name, day.day.isoformat(), day.sold, day.capacity,
		                       _(", closed") if day.reason == "closed" else
		                       (_(", {0} held for allotments").format(day.withheld) if day.withheld else "")),
		title=_("Sold out"))


# ─── restrictions ────────────────────────────────────────────────────────


def restriction_cells(property: str, start: date, end: date) -> list[rs.RestrictionCell]:
	rows = frappe.get_all("TEX ARI Restriction",
	                      filters={"property": property, "restriction_date": ("between", [start, end])},
	                      fields=["name", "restriction_date", "room_type", "contract", "market", "rate_plan",
	                              "sales_channel", "stop_sell", "stop_sell_mode", "min_los", "max_los", "cta", "ctd",
	                              "release_days", "min_advance", "max_advance"])

	def tri(v):
		return True if v == "Yes" else (False if v == "No" else None)

	return [rs.RestrictionCell(
		cell_id=r.name, day=getdate(r.restriction_date), room_type=r.room_type or None, contract=r.contract or None,
		market=r.market or None, rate_plan=r.rate_plan or None, channel=r.sales_channel or None,
		stop_sell=r.stop_sell or None, stop_sell_mode=r.stop_sell_mode or None,
		min_los=r.min_los or None, max_los=r.max_los or None, cta=tri(r.cta), ctd=tri(r.ctd),
		release_days=r.release_days or None, min_advance=r.min_advance or None,
		max_advance=r.max_advance or None) for r in rows]


def check_restrictions(property: str, scope: rs.RestrictionScope, check_in: date, check_out: date,
                       sale_date: date, cells: list[rs.RestrictionCell] | None = None) -> list[rs.Violation]:
	cells = cells if cells is not None else restriction_cells(property, check_in, check_out)
	violations, _ = rs.evaluate(cells, scope, check_in, check_out, sale_date)
	return violations
