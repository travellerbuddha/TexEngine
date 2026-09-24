"""Restriction gaps (G-48, ADR-057): the booking window, hotel- and market-level cells, the
Booking Engine / Call Center scopes, and how restrictions apply to a changed stay."""

import unittest
from datetime import date

from kamra.tex.availability import restrictions as rs

CI, CO = date(2027, 7, 10), date(2027, 7, 14)
SALE = date(2027, 7, 1)
WEB = rs.RestrictionScope("DLX", contract="C1", market="DE", channel="DIRECT_WEB", surface=rs.BOOKING_ENGINE)
CALL = rs.RestrictionScope("DLX", contract="C1", market="DE", channel="CALL_CENTER", surface=rs.CALL_CENTER)
OTA = rs.RestrictionScope("DLX", contract="C1", market="DE", channel="OTA")


def cell(cid, day, **kw):
	return rs.RestrictionCell(cid, day, **kw)


def codes(cells, scope=WEB, ci=CI, co=CO, sale=SALE, before=None, product_changed=False):
	v, _ = rs.evaluate_change(cells, scope, ci, co, sale, before=before, product_changed=product_changed)
	return sorted(x.code for x in v)


class TestBookingWindow(unittest.TestCase):
	"""A night is sold only when the booking is made inside its booking window (sale dates)."""

	def test_a_night_outside_its_booking_window_is_refused(self):
		night = date(2027, 7, 12)
		opens = [cell("w", night, book_from=date(2027, 7, 5))]
		self.assertEqual(codes(opens), ["BOOKING_WINDOW"])
		self.assertEqual(codes(opens, sale=date(2027, 7, 5)), [])
		closes = [cell("w", night, book_to=date(2027, 6, 30))]
		self.assertEqual(codes(closes), ["BOOKING_WINDOW"])
		self.assertEqual(codes(closes, sale=date(2027, 6, 30)), [])

	def test_the_departure_day_is_not_a_night(self):
		self.assertEqual(codes([cell("w", CO, book_from=date(2027, 7, 5))]), [])

	def test_the_message_names_the_night_and_the_window(self):
		v, _ = rs.evaluate([cell("w", CI, book_from=date(2027, 7, 5), book_to=date(2027, 7, 8))], WEB, CI, CO, SALE)
		self.assertEqual(v[0].day, CI)
		self.assertIn("2027-07-05", v[0].message)
		self.assertEqual(v[0].cell_id, "w")

	def test_from_and_to_resolve_per_field(self):
		# a hotel-wide "from" and a room's own "to": the window is both
		cells = [cell("hotel", CI, book_from=date(2027, 6, 1)), cell("room", CI, room_type="DLX", book_to=date(2027, 6, 15))]
		_, eff = rs.evaluate(cells, WEB, CI, CO, SALE)
		self.assertEqual((eff[CI].book_from, eff[CI].book_to), (date(2027, 6, 1), date(2027, 6, 15)))
		self.assertEqual((eff[CI].sources["book_from"], eff[CI].sources["book_to"]), ("hotel", "room"))
		self.assertEqual(codes(cells), ["BOOKING_WINDOW"])                       # sold 1 July, window closed 15 June


class TestSaleDateHelpers(unittest.TestCase):
	"""What the channels' ARI sends as of today's sale: a night outside its booking window is
	closed; an arrival inside its release or outside its advance window is closed to arrival."""

	def test_a_night_and_an_arrival_as_of_a_sale_date(self):
		e = rs.Effective(day=CI, book_from=date(2027, 7, 5), book_to=date(2027, 7, 8), release_days=7, min_advance=3,
		                 max_advance=30)
		self.assertEqual([e.sale_closed(date(2027, 7, d)) for d in (4, 5, 8, 9)], [True, False, False, True])
		self.assertTrue(e.arrival_closed(date(2027, 7, 4)))          # 6 days ahead: inside the 7-day release
		self.assertFalse(e.arrival_closed(date(2027, 7, 3)))         # 7 days ahead
		self.assertTrue(e.arrival_closed(date(2027, 6, 9)))          # 31 days ahead: beyond the maximum
		self.assertFalse(rs.Effective(day=CI).arrival_closed(date(2027, 7, 9)))


class TestLevelsAndChannelScopes(unittest.TestCase):
	"""Cells without a room type are hotel- or market-level; a cell may be scoped to the Booking
	Engine, the Call Center or both."""

	def test_hotel_and_market_level_cells_apply_to_every_room(self):
		night = date(2027, 7, 11)
		hotel = [cell("h", night, stop_sell="STOP")]
		self.assertEqual(codes(hotel), ["STOP_SELL"])
		self.assertEqual(codes(hotel, scope=rs.RestrictionScope("STD", market="UK")), ["STOP_SELL"])
		market = [cell("m", night, market="DE", stop_sell="STOP")]
		self.assertEqual(codes(market), ["STOP_SELL"])
		self.assertEqual(codes(market, scope=rs.RestrictionScope("DLX", market="UK")), [])

	def test_a_room_less_scope_sees_only_room_less_cells(self):
		night = date(2027, 7, 11)
		cells = [cell("h", night, min_los=3), cell("r", night, room_type="DLX", min_los=5)]
		eff = rs.effective(cells, rs.RestrictionScope(None), [night])
		self.assertEqual(eff[night].min_los, 3)

	def test_booking_engine_and_call_center_scope(self):
		night = date(2027, 7, 11)
		both = [cell("be+cc", night, channel_scope=rs.SCOPE_BOTH, stop_sell="STOP")]
		self.assertEqual(codes(both, scope=WEB), ["STOP_SELL"])
		self.assertEqual(codes(both, scope=CALL), ["STOP_SELL"])
		self.assertEqual(codes(both, scope=OTA), [])                              # not a channel it names
		web_only = [cell("be", night, channel_scope=rs.SCOPE_BOOKING_ENGINE, stop_sell="STOP")]
		self.assertEqual((codes(web_only, scope=WEB), codes(web_only, scope=CALL)), (["STOP_SELL"], []))
		cc_only = [cell("cc", night, channel_scope=rs.SCOPE_CALL_CENTER, stop_sell="STOP")]
		self.assertEqual((codes(cc_only, scope=WEB), codes(cc_only, scope=CALL)), ([], ["STOP_SELL"]))

	def test_the_more_specific_channel_scope_wins(self):
		night = date(2027, 7, 11)
		cells = [cell("all", night, min_los=9), cell("both", night, channel_scope=rs.SCOPE_BOTH, min_los=7),
		         cell("be", night, channel_scope=rs.SCOPE_BOOKING_ENGINE, min_los=5),
		         cell("web", night, channel="DIRECT_WEB", min_los=3)]
		pick = lambda cs, scope: rs.effective(cs, scope, [night])[night].sources["min_los"]  # noqa: E731
		self.assertEqual(pick(cells, WEB), "web")
		self.assertEqual(pick(cells[:3], WEB), "be")
		self.assertEqual(pick(cells[:2], WEB), "both")
		self.assertEqual(pick(cells, CALL), "both")
		self.assertEqual(pick(cells, OTA), "all")

	def test_other_dimensions_still_outrank_the_channel(self):
		night = date(2027, 7, 11)
		cells = [cell("mkt", night, market="DE", min_los=4), cell("be", night, channel_scope=rs.SCOPE_BOTH, min_los=6)]
		self.assertEqual(rs.effective(cells, WEB, [night])[night].sources["min_los"], "mkt")

	def test_weights_never_tie(self):
		shapes = []
		for contract in (None, "C1"):
			for room in (None, "DLX"):
				for rp in (None, "FLEX"):
					for market in (None, "DE"):
						for ch in ({}, {"channel": "DIRECT_WEB"}, {"channel_scope": rs.SCOPE_BOOKING_ENGINE},
						           {"channel_scope": rs.SCOPE_BOTH}):
							shapes.append(cell("x", CI, contract=contract, room_type=room, rate_plan=rp, market=market,
							                   **ch).weight)
		self.assertEqual(len(shapes), len(set(shapes)))


class TestChangedStay(unittest.TestCase):
	"""A change is checked like a new booking for what it newly takes (ADR-057): the nights it
	does not hold yet (stop sell, booking window), a new arrival (CTA, arrival stop sell,
	release, advance) or departure (CTD, departure stop sell), and the new length (LOS)."""

	BEFORE = (CI, CO)

	def test_a_stop_sell_on_a_night_already_held_does_not_refuse_the_change(self):
		cells = [cell("s", date(2027, 7, 11), stop_sell="STOP")]
		self.assertEqual(codes(cells, co=date(2027, 7, 15), before=self.BEFORE), [])      # one night more
		self.assertEqual(codes(cells, co=date(2027, 7, 12), before=self.BEFORE), [])      # leaves early
		self.assertEqual(codes(cells, before=None), ["STOP_SELL"])                      # a new sale is refused

	def test_a_stop_sell_on_a_new_night_refuses_the_change(self):
		cells = [cell("s", CO, stop_sell="STOP")]
		self.assertEqual(codes(cells, co=date(2027, 7, 15), before=self.BEFORE), ["STOP_SELL"])

	def test_the_booking_window_applies_to_new_nights_only(self):
		cells = [cell("w", d, book_to=date(2027, 6, 1)) for d in (date(2027, 7, 12), CO)]
		self.assertEqual(codes(cells, co=date(2027, 7, 15), before=self.BEFORE), ["BOOKING_WINDOW"])
		self.assertEqual(codes(cells[:1], co=date(2027, 7, 15), before=self.BEFORE), [])

	def test_arrival_rules_only_when_the_arrival_changes(self):
		for kw, code in (({"cta": True}, "CTA"), ({"release_days": 30}, "RELEASE"), ({"min_advance": 30}, "MIN_ADVANCE"),
		                 ({"stop_sell": "STOP", "stop_sell_mode": rs.ARRIVAL}, "STOP_SELL_ARRIVAL")):
			with self.subTest(code):
				self.assertEqual(codes([cell("a", CI, **kw)], co=date(2027, 7, 15), before=self.BEFORE), [])
				moved = date(2027, 7, 11)
				self.assertIn(code, codes([cell("a", moved, **kw)], ci=moved, before=self.BEFORE))

	def test_departure_rules_only_when_the_departure_changes(self):
		self.assertEqual(codes([cell("d", CO, ctd=True)], ci=date(2027, 7, 11), before=self.BEFORE), [])
		new_out = date(2027, 7, 13)
		self.assertEqual(codes([cell("d", new_out, ctd=True)], co=new_out, before=self.BEFORE), ["CTD"])
		self.assertEqual(codes([cell("d", new_out, stop_sell="STOP", stop_sell_mode=rs.DEPARTURE)], co=new_out,
		                       before=self.BEFORE), ["STOP_SELL_DEPARTURE"])

	def test_length_of_stay_is_judged_on_the_new_stay(self):
		self.assertEqual(codes([cell("l", CI, min_los=3)], co=date(2027, 7, 12), before=self.BEFORE), ["MIN_LOS"])
		self.assertEqual(codes([cell("l", CI, max_los=4)], co=date(2027, 7, 15), before=self.BEFORE), ["MAX_LOS"])
		self.assertEqual(codes([cell("l", CI, max_los=4)], before=self.BEFORE), [])      # dates unchanged

	def test_a_change_toward_the_minimum_stay_is_not_refused(self):
		# review L1: a 2-night stay held under a 5-night minimum (set after it was sold) may grow
		short = (CI, date(2027, 7, 12))
		mins = [cell("l", CI, min_los=5)]
		self.assertEqual(codes(mins, co=date(2027, 7, 13), before=short), [])
		self.assertEqual(codes(mins, co=date(2027, 7, 11), before=short), ["MIN_LOS"])     # shorter: refused
		# … but a minimum stay through a night it did not hold is that night's, newly taken
		through = [cell("t", date(2027, 7, 13), min_los=7)]
		v, _ = rs.evaluate_change(through, WEB, CI, date(2027, 7, 14), SALE, before=short, min_los_basis=rs.STAY_THROUGH)
		self.assertEqual([x.code for x in v], ["MIN_LOS"])
		# … a new arrival is judged as one
		moved = date(2027, 7, 11)
		self.assertEqual(codes([cell("l", moved, min_los=5)], ci=moved, co=date(2027, 7, 14), before=short),
		                 ["MIN_LOS"])

	def test_a_change_toward_the_maximum_stay_is_not_refused(self):
		long = (CI, date(2027, 7, 16))                                             # 6 nights, maximum 3
		maxs = [cell("l", CI, max_los=3)]
		self.assertEqual(codes(maxs, co=date(2027, 7, 15), before=long), [])
		self.assertEqual(codes(maxs, co=date(2027, 7, 17), before=long), ["MAX_LOS"])      # longer: refused

	def test_another_product_is_a_new_sale_of_the_stay(self):
		cells = [cell("s", date(2027, 7, 11), stop_sell="STOP"), cell("a", CI, cta=True, min_los=5)]
		self.assertEqual(codes(cells, before=self.BEFORE, product_changed=True), ["CTA", "MIN_LOS", "STOP_SELL"])

	def test_the_past_of_a_stay_under_way_is_not_sold_again(self):
		# an in-house guest (arrived 10 July) moved to another room on 12 July
		cells = [cell("s", date(2027, 7, 11), stop_sell="STOP"), cell("w", date(2027, 7, 10), book_to=date(2027, 7, 1)),
		         cell("a", CI, cta=True, release_days=30, min_los=5)]
		today = date(2027, 7, 12)
		self.assertEqual(codes(cells, sale=today, before=self.BEFORE, product_changed=True), [])
		# … but a night still to come is sold as the new product
		cells.append(cell("n", date(2027, 7, 13), stop_sell="STOP"))
		self.assertEqual(codes(cells, sale=today, before=self.BEFORE, product_changed=True), ["STOP_SELL"])
		# a stay under way whose dates change is judged on its new nights; leaving early is not a sale
		# (review L1): the minimum stay does not keep an in-house guest
		self.assertEqual(codes(cells[:3], sale=today, co=date(2027, 7, 13), before=self.BEFORE), [])
		self.assertEqual(codes([cell("x", CI, max_los=4)], sale=today, co=date(2027, 7, 15), before=self.BEFORE),
		                 ["MAX_LOS"])
		self.assertEqual(codes([*cells[:3], cell("m", CO, stop_sell="STOP")], sale=today, co=date(2027, 7, 15),
		                       before=self.BEFORE), ["STOP_SELL"])

	def test_an_unchanged_stay_is_never_refused(self):
		cells = [cell("x", CI, cta=True, min_los=9, stop_sell="STOP", book_to=date(2027, 1, 1)),
		         cell("y", CO, ctd=True)]
		self.assertEqual(codes(cells, before=self.BEFORE), [])


if __name__ == "__main__":
	unittest.main()
