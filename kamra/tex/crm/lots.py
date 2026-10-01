"""Loyalty lots (ADR-071): points are used first-to-expire first, and an expiry takes only what is left.

Pure and deterministic, like ``kamra.tex.pricing``: no frappe here. The ledger holds signed rows, not lots'
remainders; a lot's remainder is derived from the rows by this one function and never stored.

* A **lot** is a final (Available / Used / Expired) Earn or Adjust row with points > 0.
* A lot is **closed** when its status is Expired, or when the old expiry job marked it (an Expire row with the
  reason ``"expiry of <lot>"``, written before lots existed). A closed lot has absorbed exactly its own points.
* Every other final row is a debit: a Burn, a negative Adjust, an Expire. A positive row that is no lot (a
  Reverse, a refund of points) lowers the debits.
* The debits left after the closed lots took theirs (``T_open``) are spent by the open lots in order: earliest
  expiry first (none last), then availability, creation and name.
* An Earn lot whose ``expires_on`` is before ``today`` gives up what is left of it and closes (a lot with
  nothing left closes without a row). A lot without an expiry, and every Adjust lot, never expires.
* ``T_open`` below zero means points came back after their lot closed (a refund of a spent lot): the
  ``excess``, which expires too.

``plan`` says what to write; ``loyalty.settle`` writes it under the guest's lock.

A cancellation or an expiry gives back as points what the booking's Loyalty charges hold beyond what it now
costs (``points_of`` says how many points a share of the money is worth): a positive Reverse row, which is no
lot and only lowers the debits. A lot that closed meanwhile is never reopened: the points that came back for
it are its ``excess`` and expire at once (ADR-071 §4).
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal

FINAL = ("Available", "Used", "Expired")
LOT_TYPES = ("Earn", "Adjust")
MARKER = "expiry of "

_FAR = date.max
_NEVER = date.min


def marker(lot: str) -> str:
	"""The reason of the Expire row that takes what is left of ``lot``."""
	return f"{MARKER}{lot}"


def _day(v) -> date | None:
	if v is None or v == "":
		return None
	if isinstance(v, datetime):
		return v.date()
	if isinstance(v, date):
		return v
	return date.fromisoformat(str(v)[:10])


def is_lot(row: dict) -> bool:
	return row["entry_type"] in LOT_TYPES and int(row["points"] or 0) > 0 and row["status"] in FINAL


def _expiry(lot: dict) -> date | None:
	"""Only an earning expires; an adjustment (a manual lot) never does."""
	return _day(lot.get("expires_on")) if lot["entry_type"] == "Earn" else None


def _order(lot: dict):
	created = lot.get("creation")
	return (_expiry(lot) or _FAR, _day(lot.get("available_on")) or _NEVER, created is None, created, lot["name"])


def marked(rows: list[dict]) -> set[str]:
	"""The lots an Expire row names (``marker``): what the expiry job wrote, before and after lots existed."""
	out = set()
	for r in rows:
		reason = (r.get("reason") or "").strip()
		if r["status"] in FINAL and r["entry_type"] == "Expire" and reason.startswith(MARKER):
			out.add(reason[len(MARKER):])
	return out


def plan(rows: list[dict], today) -> dict:
	"""The expiry of one guest's points in one program, from their ledger rows (rows that are not final are
	ignored): ``{"expire": [(lot, points)], "close": [lot], "excess": points}``. ``expire`` lists the lots
	that give up points now, ``close`` every lot that closes now (also one with nothing left), ``excess`` the
	points that came back after their lot closed."""
	today = _day(today)
	final = [r for r in rows if r["status"] in FINAL]
	lots = [r for r in final if is_lot(r)]
	debits = -sum(int(r["points"] or 0) for r in final if not is_lot(r))
	named = marked(final)
	closed = [lot for lot in lots if lot["status"] == "Expired" or lot["name"] in named]
	open_t = debits - sum(int(lot["points"]) for lot in closed)
	owed = max(open_t, 0)
	expire: list[tuple[str, int]] = []
	close: list[str] = []
	shut = {lot["name"] for lot in closed}
	for lot in sorted((lot for lot in lots if lot["name"] not in shut), key=_order):
		points = int(lot["points"])
		spent = min(points, owed)
		owed -= spent
		due = _expiry(lot)
		if due is not None and due < today:
			if points - spent > 0:
				expire.append((lot["name"], points - spent))
			close.append(lot["name"])
	return {"expire": expire, "close": close, "excess": max(0, -open_t)}


def points_of(points: int, value, back, take) -> int:
	"""The points that come back with ``take`` of the money of a payment of ``value`` that ``points`` paid, ``back``
	of that money having come back already: pro rata and cumulative, half-up (the points due for ``back + take``
	less those due for ``back``), so the shares of one payment, however they come, add up to its points exactly:
	300 points of 30.00 given back as 12.40, 0.01 and 17.59 are 124, 0 and 176."""
	value = Decimal(value)
	if value <= 0 or points <= 0:
		return 0

	def upto(money: Decimal) -> int:
		money = min(max(money, Decimal(0)), value)
		return int((Decimal(points) * money / value).to_integral_value(rounding=ROUND_HALF_UP))

	return upto(Decimal(back) + Decimal(take)) - upto(Decimal(back))
