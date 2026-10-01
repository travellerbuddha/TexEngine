"""Loyalty lots (ADR-071, audit Part 2H-1: Y-11, O-22): points expire first-to-expire first-used, and an expiry
takes only what is left of its lot.

The pure planner (``kamra.tex.crm.lots``, no frappe) reads a guest's final ledger rows and says which lots
expire (and how many points), which lots close, and how many points came back after their lot had closed.
``apply`` below does what ``loyalty.settle`` does with that plan, so each scenario can be followed over
several runs.
"""

import unittest
from datetime import date, datetime
from decimal import Decimal as D

from kamra.tex.crm import lots

D1, D2, D3 = date(2026, 1, 1), date(2026, 3, 1), date(2027, 6, 1)


def row(name, entry_type, points, status="Available", expires_on=None, available_on=None, reason=None, n=0):
	return {"name": name, "entry_type": entry_type, "points": points, "status": status, "expires_on": expires_on,
	        "available_on": available_on, "reason": reason, "creation": datetime(2025, 12, 1, 10, n)}


def apply(rows, plan, today):
	"""What ``settle`` writes for ``plan``: the Expire rows, the closed lots' status."""
	by_name = {r["name"]: r for r in rows}
	for i, (lot, pts) in enumerate(plan["expire"]):
		rows.append(row(f"X-{lot}", "Expire", -pts, "Expired", reason=lots.marker(lot), n=30 + i))
	if plan["excess"]:
		rows.append(row("X-excess", "Expire", -plan["excess"], "Expired", reason="returned points", n=50))
	for lot in plan["close"]:
		by_name[lot]["status"] = "Expired"
	return rows


def balance(rows):
	return sum(r["points"] for r in rows if r["status"] in lots.FINAL)


class TestPlan(unittest.TestCase):
	def test_y11_an_expiry_that_took_nothing_leaves_a_later_lot_alone(self):
		"""A = 100 (expires D1), spent in full; B = 80 matures later. A's run closes A with nothing to take;
		B's points are never taken for A's expiry (the old job wrote Expire -80 once B existed)."""
		rows = [row("A", "Earn", 100, expires_on=D1), row("S", "Burn", -100, "Used", n=5)]
		first = lots.plan(rows, date(2026, 1, 2))
		self.assertEqual(first, {"expire": [], "close": ["A"], "excess": 0})
		apply(rows, first, date(2026, 1, 2))
		rows.append(row("B", "Earn", 80, expires_on=D3, available_on=D2, n=10))
		self.assertEqual(lots.plan(rows, date(2026, 3, 2)), {"expire": [], "close": [], "excess": 0})
		self.assertEqual(balance(rows), 80)

	def test_o22_spent_points_come_from_the_lot_that_expires_first(self):
		"""A = 100 (D1), B = 100 (D3), 100 spent: the spend was A's, so A's expiry takes nothing."""
		rows = [row("A", "Earn", 100, expires_on=D1), row("B", "Earn", 100, expires_on=D3, n=1),
		        row("S", "Burn", -100, "Used", n=5)]
		plan = lots.plan(rows, date(2026, 1, 2))
		self.assertEqual(plan, {"expire": [], "close": ["A"], "excess": 0})
		self.assertEqual(balance(apply(rows, plan, date(2026, 1, 2))), 100)

	def test_a_partly_spent_lot_expires_what_is_left_of_it(self):
		rows = [row("A", "Earn", 100, expires_on=D1), row("B", "Earn", 100, expires_on=D3, n=1),
		        row("S", "Burn", -60, "Used", n=5)]
		plan = lots.plan(rows, date(2026, 1, 2))
		self.assertEqual(plan, {"expire": [("A", 40)], "close": ["A"], "excess": 0})
		self.assertEqual(balance(apply(rows, plan, date(2026, 1, 2))), 100)
		self.assertEqual(lots.plan(rows, date(2026, 1, 3)), {"expire": [], "close": [], "excess": 0})    # once

	def test_a_spend_after_a_lot_closed_is_the_next_lots(self):
		"""A expires untouched (100 taken); then 50 are spent: they are B's, so B's expiry takes 50, not 100."""
		rows = [row("A", "Earn", 100, expires_on=D1), row("B", "Earn", 100, expires_on=D3, n=1)]
		apply(rows, lots.plan(rows, date(2026, 1, 2)), date(2026, 1, 2))
		self.assertEqual(balance(rows), 100)
		rows.append(row("S", "Burn", -50, "Used", n=5))
		plan = lots.plan(rows, date(2027, 6, 2))
		self.assertEqual(plan, {"expire": [("B", 50)], "close": ["B"], "excess": 0})
		self.assertEqual(balance(apply(rows, plan, date(2027, 6, 2))), 0)

	def test_points_returned_after_their_lot_expired_are_taken_again(self):
		"""A expired (100 taken); a reversal then gives 100 back: they belong to a lot that no longer exists."""
		rows = [row("A", "Earn", 100, expires_on=D1)]
		apply(rows, lots.plan(rows, date(2026, 1, 2)), date(2026, 1, 2))
		self.assertEqual(balance(rows), 0)
		rows.append(row("R", "Reverse", 100, "Available", n=40))
		plan = lots.plan(rows, date(2026, 1, 3))
		self.assertEqual(plan, {"expire": [], "close": [], "excess": 100})
		self.assertEqual(balance(apply(rows, plan, date(2026, 1, 3))), 0)
		self.assertEqual(lots.plan(rows, date(2026, 1, 4)), {"expire": [], "close": [], "excess": 0})

	def test_points_returned_before_their_lot_expired_expire_with_it(self):
		rows = [row("A", "Earn", 100, expires_on=D1), row("S", "Burn", -100, "Used", n=5),
		        row("R", "Reverse", 100, "Available", n=6)]
		self.assertEqual(lots.plan(rows, date(2025, 12, 31)), {"expire": [], "close": [], "excess": 0})
		plan = lots.plan(rows, date(2026, 1, 2))
		self.assertEqual(plan, {"expire": [("A", 100)], "close": ["A"], "excess": 0})
		self.assertEqual(balance(apply(rows, plan, date(2026, 1, 2))), 0)

	def test_a_lot_without_an_expiry_and_an_adjustment_never_expire(self):
		rows = [row("E", "Earn", 100, expires_on=None), row("J", "Adjust", 40, n=3),
		        row("K", "Adjust", 25, expires_on=D1, n=4)]               # a manual lot has no expiry: even a stray date
		self.assertEqual(lots.plan(rows, date(2030, 1, 1)), {"expire": [], "close": [], "excess": 0})
		# and they are spent after the lots that do expire
		rows += [row("A", "Earn", 50, expires_on=D1, n=1), row("S", "Burn", -50, "Used", n=5)]
		self.assertEqual(lots.plan(rows, date(2026, 1, 2)), {"expire": [], "close": ["A"], "excess": 0})

	def test_an_expiry_marked_by_the_old_job_closes_its_lot(self):
		"""The old job wrote "expiry of <lot>" and left the lot Available: that lot is closed already (it is
		not closed again, and never expired twice), and it absorbed its own points, so a later lot is not
		touched."""
		rows = [row("A", "Earn", 100, "Available", expires_on=D1), row("S", "Burn", -30, "Used", n=5),
		        row("X", "Expire", -70, "Expired", reason="expiry of A", n=6),
		        row("B", "Earn", 80, expires_on=D3, available_on=D2, n=7)]
		self.assertEqual(lots.plan(rows, date(2026, 3, 2)), {"expire": [], "close": [], "excess": 0})
		self.assertEqual(balance(rows), 80)

	def test_a_reversal_limited_to_unspent_points_takes_nothing(self):
		"""An earning reversed after it was spent leaves the balance at zero through a positive Adjust; that
		lot never expires, and the reversed earning (not final) is no lot."""
		rows = [row("A", "Earn", 100, "Reversed", expires_on=D1), row("S", "Burn", -100, "Used", n=5),
		        row("J", "Adjust", 100, n=6)]
		self.assertEqual(lots.plan(rows, date(2030, 1, 1)), {"expire": [], "close": [], "excess": 0})
		self.assertEqual(balance(rows), 0)

	def test_a_debt_is_taken_from_the_next_lots_that_arrive(self):
		"""More was taken back than the lots hold (a modified stay): the debt stays, and the lot that comes
		next absorbs it, earliest expiry first."""
		rows = [row("A", "Earn", 100, expires_on=D1), row("S", "Burn", -100, "Used", n=5),
		        row("M", "Adjust", -50, n=6)]
		self.assertEqual(lots.plan(rows, date(2026, 1, 2)), {"expire": [], "close": ["A"], "excess": 0})
		apply(rows, {"expire": [], "close": ["A"], "excess": 0}, date(2026, 1, 2))
		rows.append(row("B", "Earn", 80, expires_on=D2, available_on=D2, n=9))
		rows.append(row("C", "Earn", 80, expires_on=D3, available_on=D2, n=10))
		self.assertEqual(lots.plan(rows, date(2026, 3, 2)), {"expire": [("B", 30)], "close": ["B"], "excess": 0})

	def test_lots_are_used_in_the_order_expiry_availability_creation_name(self):
		rows = [row("L3", "Earn", 10, expires_on=D2, available_on=D2, n=3), row("L1", "Earn", 10, expires_on=D1, n=2),
		        row("L2", "Earn", 10, expires_on=D2, available_on=D1, n=4), row("L0", "Earn", 10, expires_on=None, n=0),
		        row("S", "Burn", -20, "Used", n=9)]
		# the spend is L1's and L2's (earliest expiry; then the earlier availability); L3 keeps its 10
		plan = lots.plan(rows, date(2026, 3, 2))
		self.assertEqual(plan, {"expire": [("L3", 10)], "close": ["L1", "L2", "L3"], "excess": 0})

	def test_dates_may_be_text(self):
		rows = [row("A", "Earn", 100, expires_on="2026-01-01"), row("S", "Burn", -60, "Used", n=5)]
		self.assertEqual(lots.plan(rows, "2026-01-02"), {"expire": [("A", 40)], "close": ["A"], "excess": 0})


class TestPointsOf(unittest.TestCase):
	"""Part 2H-2 (ADR-071 §4): the points that come back with a share of the money they paid, pro rata and
	cumulative, half-up, so the shares of one payment add up to its points whatever they are."""

	def slices(self, points, value, takes):
		back, out = D(0), []
		for take in map(D, takes):
			out.append(lots.points_of(points, D(value), back, take))
			back += take
		return out

	def test_the_shares_of_a_payment_add_up_to_its_points(self):
		out = self.slices(300, "30.00", ("12.40", "0.01", "17.59"))
		self.assertEqual(out, [124, 0, 176])
		self.assertEqual(sum(out), 300)

	def test_thirds_never_lose_or_make_a_point(self):
		out = self.slices(100, "10.00", ("3.33", "3.33", "3.34"))
		self.assertEqual((out, sum(out)), ([33, 34, 33], 100))

	def test_half_a_point_rounds_up(self):
		self.assertEqual(lots.points_of(5, D("1.00"), D(0), D("0.10")), 1)       # 0.5 of a point
		self.assertEqual(lots.points_of(5, D("1.00"), D("0.10"), D("0.10")), 0)   # 1.0 in all: nothing more

	def test_a_whole_payment_returns_all_its_points_and_never_more(self):
		self.assertEqual(lots.points_of(300, D("30.00"), D(0), D("30.00")), 300)
		self.assertEqual(lots.points_of(300, D("30.00"), D("20.00"), D("40.00")), 100)    # past its value: clamped
		self.assertEqual(lots.points_of(300, D("30.00"), D("30.00"), D("5.00")), 0)

	def test_a_payment_worth_nothing_returns_nothing(self):
		self.assertEqual(lots.points_of(300, D(0), D(0), D("5.00")), 0)


if __name__ == "__main__":
	unittest.main()
