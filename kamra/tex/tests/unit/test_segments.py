"""Guest segments (R-37, G-23): the rule language, per-tenant facts and the named presets."""

import unittest
from datetime import date
from decimal import Decimal

from kamra.tex.crm import segments as seg
from kamra.tex.crm.segments import StayFact

TODAY = date(2026, 9, 22)
D = Decimal


def stay(status="Checked Out", ci=date(2025, 8, 1), co=date(2025, 8, 5), **kw):
	return StayFact(status, ci, co, **{"sold_on": date(2025, 6, 1), "amount": D("800"), "currency": "EUR", **kw})


def facts(stays=(), abandoned=(), **guest):
	row = {"tex_country": "DE", "tex_market": "DE", "vip": 0, "tex_tags": "golf, family", "tex_consent_email": 1,
	       **guest}
	return seg.derive_facts(row, list(stays), list(abandoned), TODAY)


def rule(*conds, match="all"):
	return seg.validate({"match": match, "conditions": [dict(zip(("field", "op", "value", "currency"), c, strict=False))
	                                                    for c in conds]}, strict=True)


class TestRules(unittest.TestCase):
	def test_all_and_any(self):
		three = [stay(), stay(ci=date(2025, 2, 1), co=date(2025, 2, 4)), stay(ci=date(2024, 5, 1), co=date(2024, 5, 3))]
		r = rule(("stays", "gte", 2), ("tags", "contains", "GOLF"), ("lifetime_value", "gt", "2000", "EUR"))
		self.assertTrue(seg.matches(facts(three), r))
		self.assertFalse(seg.matches(facts(three[:1]), r))
		anyr = rule(("vip", "is", True), ("country", "in", "at, ch"), match="any")
		self.assertFalse(seg.matches(facts(), anyr))
		self.assertTrue(seg.matches(facts(tex_country="CH"), anyr))

	def test_money_is_compared_in_its_own_currency(self):
		try_stays = [stay(amount=D("600"), currency="TRY")]
		self.assertFalse(seg.matches(facts(try_stays), rule(("lifetime_value", "gte", "500", "EUR"))))
		self.assertTrue(seg.matches(facts(try_stays), rule(("lifetime_value", "gte", "500", "TRY"))))
		mixed = facts([stay(amount=D("300")), stay(amount=D("300"), currency="GBP"), stay(amount=D("250"))])
		self.assertEqual(mixed["lifetime_value"], {"EUR": D("550"), "GBP": D("300")})
		self.assertEqual(mixed["lifetime_currency"], "EUR")
		legacy = seg.validate({"conditions": [{"field": "lifetime_value", "op": "gte", "value": "1"}]})
		self.assertFalse(seg.matches(mixed, legacy))                     # no currency: never compared
		with self.assertRaises(seg.SegmentError):
			seg.validate(legacy, strict=True)                            # and cannot be saved

	def test_values_are_typed_when_saved(self):
		for bad in (("stays", "gte", "abc"), ("stays", "gte", True), ("lifetime_value", "gt", "x", "EUR"),
		            ("lifetime_value", "gt", "10", "EURO"), ("vip", "is", "maybe"), ("country", "eq", " "),
		            ("lifetime_value", "gt", "NaN", "EUR")):
			with self.assertRaises(seg.SegmentError, msg=str(bad)):
				rule(bad)
		self.assertEqual(rule(("stays", "gte", "2"))["conditions"][0]["value"], 2)
		self.assertEqual(rule(("lifetime_value", "gte", "500", "eur"))["conditions"][0],
		                 {"field": "lifetime_value", "op": "gte", "value": "500", "currency": "EUR"})

	def test_an_unknown_fact_equals_nothing(self):
		nothing = facts()
		self.assertIsNone(nothing["last_stay_days_ago"])
		self.assertTrue(seg.matches(nothing, rule(("last_stay_days_ago", "ne", 5))))
		self.assertFalse(seg.matches(nothing, rule(("last_stay_days_ago", "gte", 0))))

	def test_only_whitelisted_fields_and_ops(self):
		for bad in ({"conditions": [{"field": "password", "op": "eq", "value": 1}]},
		            {"conditions": [{"field": "stays", "op": "contains", "value": 1}]},
		            {"match": "xor", "conditions": []},
		            {"conditions": ["stays"]},
		            {"conditions": [{"field": "stays", "op": "eq", "value": 1}] * 26}):
			with self.assertRaises(seg.SegmentError):
				seg.validate(bad)


class TestFacts(unittest.TestCase):
	def test_stays_count_only_completed_non_cancelled_ones(self):
		f = facts([stay(), stay(status="Cancelled", cancelled_on=date(2026, 9, 1)),
		           stay(status="No Show"), stay(status="Inquiry"),
		           stay(status="Confirmed", ci=date(2026, 10, 1), co=date(2026, 10, 4))])
		self.assertEqual((f["stays"], f["last_stay_days_ago"], f["has_upcoming_stay"], f["cancellations"]),
		                 (1, (TODAY - date(2025, 8, 5)).days, True, 1))

	def test_the_rooms_of_one_booking_are_one_stay(self):
		"""O-23 (audit Part 2H-1): a reservation is a room. A booking of two rooms is one visit of the guest:
		one stay, not a repeat guest; the value is the rooms' together."""
		two_rooms = [stay(visit="B1"), stay(visit="B1", amount=D("200"))]
		f = facts(two_rooms)
		self.assertEqual((f["stays"], f["lifetime_value"]), (1, {"EUR": D("1000")}))
		self.assertFalse(seg.matches(f, seg.validate(seg.SYSTEM_SEGMENTS["REPEAT"][1], strict=True)))
		again = facts([*two_rooms, stay(visit="B2", ci=date(2026, 3, 1), co=date(2026, 3, 4))])
		self.assertEqual(again["stays"], 2)
		self.assertTrue(seg.matches(again, seg.validate(seg.SYSTEM_SEGMENTS["REPEAT"][1], strict=True)))
		# a stay without a visit (a legacy reservation) counts on its own
		self.assertEqual(facts([stay(), stay(ci=date(2026, 3, 1), co=date(2026, 3, 4))])["stays"], 2)

	def test_the_main_currency_is_the_one_of_most_visits_not_most_rooms(self):
		rooms = [stay(visit="B1", currency="EUR"), stay(visit="B1", currency="EUR"), stay(visit="B1", currency="EUR"),
		         stay(visit="B2", currency="GBP"), stay(visit="B3", currency="GBP", ci=date(2026, 3, 1),
		                                              co=date(2026, 3, 4))]
		f = facts(rooms)
		self.assertEqual((f["lifetime_currency"], f["stays"]), ("GBP", 3))

	def test_an_inquiry_is_not_an_upcoming_stay(self):
		self.assertFalse(facts([stay(status="Inquiry", ci=date(2026, 10, 1), co=date(2026, 10, 2))])["has_upcoming_stay"])

	def test_birthday(self):
		self.assertEqual(seg.days_to_birthday("1980-09-22", TODAY), 0)
		self.assertEqual(seg.days_to_birthday("1980-09-21", TODAY), 364)
		self.assertEqual(seg.days_to_birthday(date(1992, 2, 29), date(2027, 2, 1)), 27)     # 28 Feb in 2027
		self.assertEqual(seg.days_to_birthday(date(1992, 2, 29), date(2028, 2, 1)), 28)     # a leap year
		self.assertIsNone(seg.days_to_birthday(None, TODAY))


class TestPresets(unittest.TestCase):
	def is_in(self, key, f):
		return seg.matches(f, seg.validate(seg.SYSTEM_SEGMENTS[key][1], strict=True))

	def test_every_preset_is_a_valid_strict_rule(self):
		for label, rules in seg.SYSTEM_SEGMENTS.values():
			self.assertTrue(label)
			seg.validate(rules, strict=True)

	def test_family(self):
		self.assertTrue(self.is_in("FAMILY", facts([stay(children=1)])))
		self.assertTrue(self.is_in("FAMILY", facts([stay(status="Confirmed", ci=date(2026, 12, 1),
		                                                 co=date(2026, 12, 5), children=2)])))
		self.assertFalse(self.is_in("FAMILY", facts([stay(status="Cancelled", children=2)])))
		self.assertFalse(self.is_in("FAMILY", facts([stay()])))

	def test_last_minute(self):
		late = stay(status="Confirmed", ci=date(2026, 9, 25), co=date(2026, 9, 27), sold_on=date(2026, 9, 23))
		self.assertTrue(self.is_in("LAST_MINUTE", facts([stay(), late])))            # the latest booking decides
		self.assertFalse(self.is_in("LAST_MINUTE", facts([late, stay(ci=date(2026, 12, 1), co=date(2026, 12, 3),
		                                                             status="Confirmed",
		                                                             sold_on=date(2026, 9, 24))])))
		self.assertFalse(self.is_in("LAST_MINUTE", facts()))

	def test_cancelled_abandoned_birthday_lapsed(self):
		self.assertTrue(self.is_in("CANCELLED", facts([stay(status="Cancelled", cancelled_on=date(2026, 8, 1))])))
		self.assertFalse(self.is_in("CANCELLED", facts([stay(status="Cancelled", cancelled_on=date(2026, 1, 1))])))
		self.assertTrue(self.is_in("ABANDONED", facts(abandoned=["2026-09-10 10:00:00"])))
		self.assertFalse(self.is_in("ABANDONED", facts([stay(status="Confirmed", ci=date(2026, 10, 1),
		                                                     co=date(2026, 10, 3))], abandoned=["2026-09-10"])))
		self.assertTrue(self.is_in("BIRTHDAY", facts(date_of_birth="1990-10-15")))
		self.assertFalse(self.is_in("BIRTHDAY", facts(date_of_birth="1990-12-15")))
		self.assertTrue(self.is_in("LAPSED", facts([stay(ci=date(2025, 5, 1), co=date(2025, 5, 3))])))
		self.assertFalse(self.is_in("LAPSED", facts([stay(ci=date(2025, 10, 1), co=date(2025, 10, 3))])))
