"""Availability & restrictions repository (Frappe side of ADR-008).

Inventory pools, sold counts, allotments and restriction cells are loaded here and
evaluated with the pure functions in ``inventory_math`` / ``restrictions``.
``lock_nights`` serialises concurrent bookings of the same pool: it row-locks one
``TEX Inventory Day`` per night (created lazily, ascending date order), and the
caller recounts availability under the lock before inserting reservations.
"""

from __future__ import annotations

from datetime import date, timedelta

import frappe
from frappe.utils import getdate

from kamra.reservation_state import LIVE_STATUSES
from kamra.tex.availability import inventory_math as inv
from kamra.tex.availability import restrictions as rs


def nights(check_in: date, check_out: date) -> list[date]:
	return [check_in + timedelta(days=i) for i in range((check_out - check_in).days)]


def pool_of(room_type: str) -> tuple[str, list[str]]:
	"""(pool key, room types in the pool). The key is the pool's first room type."""
	prop, pool = frappe.db.get_value("Room Type", room_type, ["property", "tex_inventory_pool"])
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
	rows = frappe.db.sql(
		"""SELECT inventory_date, base_inventory, manual_adjustment, oversell_limit, closed
		   FROM `tabTEX Inventory Day` WHERE room_type=%(p)s AND inventory_date BETWEEN %(a)s AND %(b)s"""
		+ (" LOCK IN SHARE MODE" if locking else ""), {"p": pool_key, "a": days[0], "b": days[-1]}, as_dict=True)
	return {getdate(r.inventory_date): r for r in rows}


def _allotments(property: str, room_types: list[str], days: list[date]) -> list[inv.Allotment]:
	rows = frappe.get_all("TEX Allotment",
	                      filters={"property": property, "room_type": ("in", room_types), "disabled": 0,
	                               "date_from": ("<=", days[-1]), "date_to": (">=", days[0])},
	                      fields=["name", "contract", "date_from", "date_to", "rooms", "release_days", "guaranteed"])
	out = []
	for r in rows:
		d = max(getdate(r.date_from), days[0])
		while d <= min(getdate(r.date_to), days[-1]):
			out.append(inv.Allotment(r.name, r.contract, d, int(r.rooms or 0), int(r.release_days or 0),
			                         bool(r.guaranteed)))
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
                      sale_date: date, *, exclude: list[str] | None = None,
                      locking: bool = False) -> tuple[int, list[inv.DayAvailability]]:
	"""Rooms bookable for the stay. Pass ``locking=True`` after ``lock_nights``."""
	days = nights(check_in, check_out)
	pdays, allot = pool_days(property, room_type, days, exclude=exclude, locking=locking)
	return inv.stay_availability(pdays, allot, contract, sale_date)


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
