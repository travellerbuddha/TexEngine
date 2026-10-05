"""Extras capacity (G-19): which days an extra consumes, and a full day refuses it."""

import unittest
from datetime import date
from decimal import Decimal

from kamra.tex.pricing import engine, extras
from kamra.tex.pricing.enums import ExtraPricingMode as M
from kamra.tex.pricing.model import ExtraDayAvailability, ExtraDef, ExtraRequest
from kamra.tex.tests.unit import fixtures

D = Decimal
CI, CO = date(2027, 6, 2), date(2027, 6, 5)          # three nights: 2, 3, 4 June
CTX = extras.ExtraContext(sale_date=date(2027, 1, 15), check_in=CI, check_out=CO, nights=3, market="DE",
                          channel="DIRECT_WEB", room_type="STD", adults=2, children=1, infants=1,
                          sell_currency="EUR")


def xdef(mode, code="SPA", **kw):
	return ExtraDef(code, code.title(), mode, "EUR", D("20"), **kw)


class TestUsage(unittest.TestCase):
	def use(self, mode, qty=1, dates=()):
		return extras.usage(xdef(mode), ExtraRequest("SPA", qty, tuple(dates)), CTX)

	def test_days_and_units_per_pricing_mode(self):
		d2, d3, d4 = date(2027, 6, 2), date(2027, 6, 3), date(2027, 6, 4)
		self.assertEqual(self.use(M.SERVICE_DATE, 2, [d3, d4]), ((d3, 2), (d4, 2)))
		self.assertEqual(self.use(M.NIGHT), ((d2, 1), (d3, 1), (d4, 1)))
		self.assertEqual(self.use(M.PERSON_NIGHT), ((d2, 4), (d3, 4), (d4, 4)))    # 2 adults + child + infant
		self.assertEqual(self.use(M.PERSON), ((CI, 4),))
		self.assertEqual(self.use(M.ADULT, 2), ((CI, 4),))
		self.assertEqual(self.use(M.CHILD), ((CI, 1),))
		self.assertEqual(self.use(M.INFANT), ((CI, 1),))
		for mode in (M.RESERVATION, M.ROOM, M.STAY, M.UNIT, M.USAGE):
			self.assertEqual(self.use(mode, 3), ((CI, 3),), mode)
		self.assertEqual(self.use(M.UNIT, 1, [d4]), ((d4, 1),))                  # a chosen day counts
		self.assertEqual(self.use(M.SERVICE_DATE, 1, [d3, d3]), ((d3, 2),))       # twice the same day

	def test_no_units_no_days(self):
		ctx = extras.ExtraContext(**{**{f: getattr(CTX, f) for f in CTX.__slots__}, "children": 0, "infants": 0})
		self.assertEqual(extras.usage(xdef(M.CHILD), ExtraRequest("SPA"), ctx), ())


class TestEngineCapacity(unittest.TestCase):
	SPA = ExtraDef("SPA", "Spa", M.UNIT, "EUR", D("30"), inventory_tracked=True)
	DINNER = ExtraDef("DINNER", "Dinner", M.NIGHT, "EUR", D("25"), inventory_tracked=True)
	TRF = ExtraDef("TRF", "Transfer", M.RESERVATION, "EUR", D("40"))

	def quote(self, availability, *requests, **kw):
		ctx = fixtures.ctx(extras={"SPA": self.SPA, "DINNER": self.DINNER, "TRF": self.TRF},
		                   extra_availability=availability)
		return engine.price_stay(ctx, fixtures.req(check_in=date(2027, 6, 2), check_out=date(2027, 6, 5),
		                                           extras=tuple(requests), **kw))

	def outcome(self, q, code):
		return next(e for e in q.extras if e.code == code)

	def test_a_full_day_refuses_the_extra_and_it_is_not_charged(self):
		ok = self.quote({"SPA": {CI: ExtraDayAvailability(2)}}, ExtraRequest("SPA", 2))
		self.assertTrue(self.outcome(ok, "SPA").ok)
		self.assertEqual(ok.totals["extras"], D("60"))
		q = self.quote({"SPA": {CI: ExtraDayAvailability(1)}}, ExtraRequest("SPA", 2), ExtraRequest("TRF"))
		spa = self.outcome(q, "SPA")
		self.assertEqual((spa.ok, spa.reason), (False, "only 1 left on 2027-06-02"))
		self.assertEqual(q.totals["extras"], D("40"))                  # the transfer only
		self.assertTrue(q.sellable)
		self.assertIn("EXTRA_SOLD_OUT", [s.code for s in q.explanation.steps])
		none = self.quote({"SPA": {CI: ExtraDayAvailability(0)}}, ExtraRequest("SPA"))
		self.assertEqual(self.outcome(none, "SPA").reason, "sold out on 2027-06-02")

	def test_a_closed_day_and_a_full_middle_night(self):
		closed = self.quote({"SPA": {CI: ExtraDayAvailability(5, closed=True)}}, ExtraRequest("SPA"))
		self.assertEqual(self.outcome(closed, "SPA").reason, "closed on 2027-06-02")
		days = {date(2027, 6, 2): ExtraDayAvailability(3), date(2027, 6, 3): ExtraDayAvailability(0),
		        date(2027, 6, 4): ExtraDayAvailability(3)}
		q = self.quote({"DINNER": days}, ExtraRequest("DINNER"))
		self.assertEqual(self.outcome(q, "DINNER").reason, "sold out on 2027-06-03")

	def test_2q_a_capacity_refusal_carries_its_code_and_day(self):
		"""Batch 2Q (§6G3): why a limited extra was not added was text only ("sold out on …"), which the booking app
		parsed to tell the guest in their language. The outcome carries its code and day (never a count); an outcome
		without a refusal has neither key, as quotes always had (ADR-061)."""
		cases = ((ExtraDayAvailability(0), 1, ("SOLD_OUT", "2027-06-02")),
		         (ExtraDayAvailability(1), 2, ("NOT_ENOUGH", "2027-06-02")),
		         (ExtraDayAvailability(5, closed=True), 1, ("CLOSED", "2027-06-02")))
		for day, qty, expected in cases:
			with self.subTest(expected=expected):
				spa = self.outcome(self.quote({"SPA": {CI: day}}, ExtraRequest("SPA", qty)), "SPA")
				self.assertEqual((spa.reason_code, spa.reason_date), expected)
				out = spa.to_dict()
				self.assertEqual((out["reason_code"], out["reason_date"]), expected)
		ok = self.outcome(self.quote({"SPA": {CI: ExtraDayAvailability(5)}}, ExtraRequest("SPA")), "SPA").to_dict()
		self.assertFalse({"reason_code", "reason_date"} & set(ok))

	def test_untracked_or_unchecked_never_blocks(self):
		self.assertTrue(self.outcome(self.quote({}, ExtraRequest("SPA")), "SPA").ok)       # not tracked now
		self.assertTrue(self.outcome(self.quote(None, ExtraRequest("SPA")), "SPA").ok)     # not checked (history)
		q = self.quote({"SPA": {CI: ExtraDayAvailability(0)}}, ExtraRequest("TRF"))
		self.assertTrue(self.outcome(q, "TRF").ok)

	def test_the_quote_records_the_days_it_uses(self):
		q = self.quote({"DINNER": {d: ExtraDayAvailability(9) for d in (date(2027, 6, 2), date(2027, 6, 3),
		                                                                  date(2027, 6, 4))}},
		               ExtraRequest("DINNER", 2))
		self.assertEqual(self.outcome(q, "DINNER").to_dict()["usage"],
		                 [{"date": "2027-06-02", "units": 2}, {"date": "2027-06-03", "units": 2},
		                  {"date": "2027-06-04", "units": 2}])


class TestGuestReason(unittest.TestCase):
	def test_guests_never_see_the_market_channel_or_room_an_extra_is_limited_to(self):
		"""2G-3 review round 1 (S2): an extra not sold with the stay's market, channel or room type says only that it
		is not available (G-71), in a quote, a change's warnings and an extra added after booking alike."""
		for reason in ("not available for market DE", "not available on channel OTA",
		               "not available with room Standard Sea View-Aurora"):
			self.assertEqual(extras.guest_reason(reason), "not available")
		self.assertEqual(extras.guest_reason("Spa: not available for market DE; Gala: only 2 left on 2027-06-02"),
		                 "Spa: not available; Gala: not enough left on 2027-06-02")
		self.assertEqual(extras.guest_safe({"reasons": [{"message": "Spa: not available on channel OTA"}]}),
		                 {"reasons": [{"message": "Spa: not available"}]})
		for same in ("Spa: charged once per booking, on room 1", "not available on 2027-06-02"):
			self.assertEqual(extras.guest_reason(same), same)

	def test_guests_never_see_how_many_are_left(self):
		self.assertEqual(extras.guest_reason("Spa: only 3 left on 2027-06-02"), "Spa: not enough left on 2027-06-02")
		for same in ("sold out on 2027-06-02", "closed on 2027-06-02", "Pay only 3 nights"):
			self.assertEqual(extras.guest_reason(same), same)
		out = extras.guest_safe({"extras": [{"reason": "only 12 left on 2027-06-03", "amount": "20.00"}],
		                         "warnings": ({"message": "Spa: only 1 left on 2027-06-04"},), "n": 3})
		self.assertEqual(out, {"extras": [{"reason": "not enough left on 2027-06-03", "amount": "20.00"}],
		                       "warnings": [{"message": "Spa: not enough left on 2027-06-04"}], "n": 3})
