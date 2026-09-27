"""An ARI grid rate edit as a plan of period edits (O-9, G-47, ADR-069, ``pricing.ratesplit``).

The grid used to clone every period segment of the range, every day of it, at the period's
priority + 100: a second weekend edit gave a clone the same priority as the first edit's, on the
same days, and the draft could not be published (PERIOD_OVERLAP). Now the edited nights (range ∩
weekdays) are split into parts by the period pricing them; a period pricing edited nights only is
edited in place, any other gets one clone per part above every period of its kind it overlaps."""

import random
import unittest
from datetime import date, datetime, timedelta
from decimal import Decimal

from kamra.tex.money import quantize
from kamra.tex.pricing import engine, matrix, ratesplit, rooms, validate
from kamra.tex.pricing.enums import Op
from kamra.tex.pricing.model import RoomRule
from kamra.tex.tests.unit import fixtures as fx

D = Decimal
WEEKEND, WEEKDAYS = [5, 6], [0, 1, 2, 3, 4]
SEASON = (date(2027, 6, 1), date(2027, 8, 31))
SAT, MON = date(2027, 6, 5), date(2027, 6, 7)


def edit(t, start, end, weekdays, room_types, op, value):
	steps = ratesplit.plan(t, start, end, weekdays, room_types, op, value)
	return ratesplit.apply(t, steps)[0]


def errors(t) -> list[str]:
	return [f"{i.code}: {i.message}" for i in validate.validate_terms(t) if i.level == "ERROR"]


def raw(t, room: str, night: date) -> Decimal:
	return rooms.room_unit(t, room, rooms.period_for(t, night))


def unit(t, room: str, night: date) -> Decimal:
	return quantize(raw(t, room, night), t.currency)


def two_adults(t, night: date) -> Decimal:
	q = engine.price_stay(fx.ctx(t), fx.req(check_in=night, check_out=night + timedelta(days=1), adults=2,
	                                        sale_at=datetime(2027, 1, 15, 10, 0)))
	assert q.sellable, q.reasons
	return quantize(q.totals["total"], t.currency)


def nights(start=SEASON[0], end=SEASON[1]):
	d = start
	while d <= end:
		yield d
		d += timedelta(days=1)


class TestWeekendEdits(unittest.TestCase):
	def setUp(self):
		self.t = fx.terms()
		self.first = edit(self.t, *SEASON, WEEKEND, ["STD"], Op.ABSOLUTE, "150")

	def test_two_weekend_edits_validate_clean(self):
		self.assertEqual(errors(self.first), [])
		self.assertEqual(len(self.first.periods), 9)            # P1–P3A and one clone per part
		second = edit(self.first, *SEASON, WEEKEND, ["STD"], Op.ABSOLUTE, "160")
		self.assertEqual(errors(second), [])                    # was PERIOD_OVERLAP
		self.assertEqual(len(second.periods), 9)                # the clones are edited in place
		self.assertEqual(two_adults(second, SAT), D("320.00"))
		self.assertEqual(two_adults(second, MON), D("200.00"))
		self.assertEqual(unit(second, "SUITE", date(2027, 8, 7)), D("245.00"))   # its own P3A rule
		third = edit(second, *SEASON, WEEKEND, ["STD"], Op.ABSOLUTE, "170")
		self.assertEqual((errors(third), len(third.periods)), ([], 9))
		self.assertEqual(two_adults(third, SAT), D("340.00"))

	def test_a_weekday_edit_after_a_weekend_edit(self):
		first = edit(self.t, *SEASON, WEEKEND, ["STD"], Op.ABSOLUTE, "140")
		after = edit(first, *SEASON, WEEKDAYS, ["STD"], Op.ABSOLUTE, "300")
		self.assertEqual(errors(after), [])
		self.assertEqual((two_adults(after, MON), two_adults(after, SAT)), (D("600.00"), D("280.00")))
		self.assertEqual(len(after.periods), 9)                 # the base periods price weekdays only now

	def test_a_partial_range(self):
		after = edit(self.first, date(2027, 6, 10), date(2027, 6, 20), None, ["STD"], Op.ABSOLUTE, "175")
		self.assertEqual(errors(after), [])
		for night in nights(date(2027, 6, 10), date(2027, 6, 20)):
			self.assertEqual(unit(after, "STD", night), D("175.00"), night)
		self.assertEqual(unit(after, "STD", date(2027, 6, 9)), D("100.00"))
		self.assertEqual(unit(after, "STD", date(2027, 6, 21)), D("110.00"))
		self.assertEqual(unit(after, "STD", SAT), D("150.00"))              # the first edit's, outside the range
		self.assertEqual(unit(after, "STD", date(2027, 6, 26)), D("150.00"))

	def test_an_all_days_edit_inside_a_clone(self):
		for weekdays in (None, list(range(7))):
			with self.subTest(weekdays=weekdays):
				after = edit(self.first, SAT, SAT + timedelta(days=1), weekdays, ["STD"], Op.ADD, "5")
				self.assertEqual(errors(after), [])
				self.assertEqual([unit(after, "STD", SAT), unit(after, "STD", SAT + timedelta(days=1))],
				                 [D("155.00")] * 2)
				self.assertEqual(unit(after, "STD", date(2027, 6, 12)), D("150.00"))   # the clone's other nights

	def test_the_clone_is_above_every_period_it_overlaps(self):
		# P1 prices the weekdays of 1–15 Jun only now and its weekend clone the rest: both in place
		steps = ratesplit.plan(self.first, date(2027, 6, 1), date(2027, 6, 15), None, ["STD"], Op.ABSOLUTE, "99")
		self.assertEqual([(s.source.code, s.source.weekdays, s.clone, len(s.parts)) for s in steps],
		                 [("P1", None, False, 3), (steps[1].source.code, frozenset(WEEKEND), False, 2)])
		steps = ratesplit.plan(self.first, SAT, SAT, None, ["STD"], Op.ABSOLUTE, "99")
		(clone,) = steps
		self.assertTrue(clone.clone)
		self.assertEqual((clone.start, clone.end, clone.weekdays), (SAT, SAT, frozenset(WEEKEND)))
		self.assertGreater(clone.priority, max(p.priority for p in self.first.periods if p.weekdays))


class TestRooms(unittest.TestCase):
	def test_a_derived_room_follows_its_base_and_an_own_rule_is_kept(self):
		t = fx.terms()
		for weekdays in (None, WEEKEND):           # P3A in place, then a weekend clone of it
			with self.subTest(weekdays=weekdays):
				after = edit(t, date(2027, 8, 1), date(2027, 8, 15), weekdays, ["STD"], Op.ABSOLUTE, "200")
				self.assertEqual(errors(after), [])
				self.assertEqual(unit(after, "STD", date(2027, 8, 7)), D("200.00"))
				self.assertEqual(unit(after, "SUP", date(2027, 8, 7)), D("230.00"))     # ×1.15 of STD
				self.assertEqual(unit(after, "SUITE", date(2027, 8, 7)), D("245.00"))   # its own rule
				self.assertEqual(unit(after, "STD", date(2027, 8, 16)), D("120.00"))

	def test_a_selected_derived_room_gets_its_own_unit(self):
		after = edit(fx.terms(), *SEASON, WEEKEND, ["SUP"], Op.ADJUST_PERCENT, "10")
		self.assertEqual(errors(after), [])
		self.assertEqual(unit(after, "SUP", SAT), D("126.50"))                  # 115 + 10 %
		self.assertEqual(unit(after, "STD", SAT), D("100.00"))

	def test_a_night_without_a_period_and_a_negative_unit_are_refused(self):
		with self.assertRaises(ratesplit.RateSplitError) as e:
			ratesplit.plan(fx.terms(), date(2027, 8, 30), date(2027, 9, 2), None, ["STD"], Op.ABSOLUTE, "1")
		self.assertEqual((e.exception.code, e.exception.ref), ("NO_PERIOD", {"night": date(2027, 9, 1)}))
		with self.assertRaises(ratesplit.RateSplitError) as e:
			ratesplit.plan(fx.terms(), SAT, SAT, None, ["STD"], Op.SUBTRACT, "100.01")
		self.assertEqual((e.exception.code, e.exception.ref), ("NEGATIVE", {"room_type": "STD"}))
		with self.assertRaises(ratesplit.RateSplitError) as e:
			ratesplit.plan(fx.terms(), MON, MON, WEEKEND, ["STD"], Op.ABSOLUTE, "1")
		self.assertEqual(e.exception.code, "NO_NIGHTS")

	def test_an_added_error_is_named_and_one_the_draft_had_is_not(self):
		sub = RoomRule("R-SUP", "SUP", None, Op.SUBTRACT, D("50"), "STD")
		t = fx.terms(room_rules=tuple(sub if r.rule_id == "R-SUP" else r for r in fx.room_rules()))
		steps = ratesplit.plan(t, SAT, SAT, None, ["STD"], Op.ABSOLUTE, "30")
		after, alias = ratesplit.apply(t, steps)
		added = ratesplit.added_errors(validate.validate_terms(t), validate.validate_terms(after), alias)
		self.assertEqual([(i.code, i.ref["room_type"]) for i in added], [("ROOM_NEGATIVE", "SUP")])
		# an error the draft had (DLX without a price) is not added again by a clone of P1
		broken = fx.terms(room_rules=tuple(r for r in fx.room_rules() if r.rule_id != "R-DLX"))
		after, alias = ratesplit.apply(broken, ratesplit.plan(broken, SAT, SAT, None, ["STD"], Op.ABSOLUTE, "9"))
		self.assertIn("NO_ROOM_PRICE", {i.code for i in validate.validate_terms(after) if i.ref.get("period") in alias})
		self.assertEqual(ratesplit.added_errors(validate.validate_terms(broken), validate.validate_terms(after),
		                                        alias), [])


class TestSweep(unittest.TestCase):
	"""Edits on random ranges, weekdays and ops, one after another: every edited night of the
	selected room changes to the new unit, no other night of any room changes, and the terms
	always validate clean."""

	def test_every_edited_night_changes_and_no_other(self):
		rng = random.Random(2027)
		t = fx.terms()
		masks = (None, WEEKEND, WEEKDAYS, [2], [4, 5], list(range(7)))
		kinds = set()
		for i in range(40):
			a = SEASON[0] + timedelta(days=rng.randrange(92))
			b = min(SEASON[1], a + timedelta(days=rng.randrange(40)))
			mask, room = rng.choice(masks), rng.choice(("STD", "SUP", "SUITE"))
			op, value = rng.choice(((Op.ABSOLUTE, str(rng.randrange(80, 300))), (Op.ADD, "3"),
			                        (Op.ADJUST_PERCENT, "-5")))
			edited = set(ratesplit.edited_nights(a, b, mask))
			if not edited:
				continue
			with self.subTest(i=i, range=(a, b), mask=mask, room=room, op=op, value=value):
				before = {(rt, n): raw(t, rt, n) for rt in t.rooms for n in nights()}
				steps = ratesplit.plan(t, a, b, mask, [room], op, value)
				kinds |= {s.clone for s in steps}
				after = ratesplit.apply(t, steps)[0]
				self.assertEqual(errors(after), [])
				for n in nights():
					for rt in after.rooms:
						now = raw(after, rt, n)
						if n in edited and rt == room:
							self.assertEqual(now, matrix.adjust_amount(before[(rt, n)], op, D(value), "EUR"), (rt, n))
						elif n not in edited:
							self.assertEqual(now, before[(rt, n)], (rt, n))
				t = after
		self.assertEqual(kinds, {True, False})                  # clones and edits in place both swept
