"""A change that takes a booking below a promotion's minimum basket (G-84 review H1, ADR-057).

The rooms that are not changed keep their locked price; the changed (or cancelled) room carries
the discount the other live rooms were granted only on the booking's basket and no longer earn
(their recorded ``forfeit``). What a room carries is recorded with it, so a later change charges
it once, and gives it back when the booking qualifies again or the room whose discount it paid
for pays its own full price."""

import unittest
from decimal import Decimal

from kamra.tex.pricing import basket

D = Decimal


def term(promo="BIG", minimum="1100", applied=True, forfeit="0", tax="0", net=None, name="Code BIG"):
	return basket.Term(promo, name, D(minimum), applied, D(forfeit), D(net if net is not None else forfeit), D(tax))


def room(name, amount, *terms, carried=None):
	return basket.BookedRoom(name, D(amount), tuple(terms), {k: basket.Carried(D(v), D(v), D("0"))
	                                                          for k, v in (carried or {}).items()})


class TestClawback(unittest.TestCase):
	def test_a_change_below_the_minimum_charges_the_other_rooms_forfeit(self):
		others = [room("R1", "802.50", term(forfeit="80.25"))]
		c = basket.clawback(others, room("R2", "214.00", term(applied=False)), "EUR",
		                    before=room("R2", "321.00", term(forfeit="32.10")))
		self.assertEqual((c.amount, c.net, c.tax), (D("80.25"), D("80.25"), D("0")))
		(p,) = c.promotions
		self.assertEqual((p["promo_id"], p["minimum"], p["basket_before"], p["basket_after"], p["amount"]),
		                 ("BIG", "1100.00", "1123.50", "1016.50", "80.25"))
		self.assertEqual(p["rooms"], [{"reservation": "R1", "amount": "80.25"}])
		self.assertIn("Code BIG", p["text"])
		self.assertIn("1100.00", p["text"])
		self.assertIn("1016.50", p["text"])

	def test_a_booking_still_above_the_minimum_charges_nothing(self):
		others = [room("R1", "802.50", term(minimum="1000", forfeit="80.25"))]
		c = basket.clawback(others, room("R2", "214.00", term(minimum="1000")), "EUR")
		self.assertEqual((c.amount, c.promotions), (D("0"), []))

	def test_a_cancelled_room_carries_the_fixed_discount_of_room_1(self):
		# 50 off from 250 on rooms of 200 and 100, granted once on room 1: the second room is cancelled
		others = [room("R0", "200.00", term("C", "250", forfeit="50.00", name="50 off"))]
		c = basket.clawback(others, None, "EUR", before=room("R1", "100.00", term("C", "250", applied=False)))
		self.assertEqual(c.amount, D("50.00"))
		self.assertEqual((c.promotions[0]["basket_before"], c.promotions[0]["basket_after"]), ("300.00", "200.00"))

	def test_only_the_rooms_the_promotion_covers_count(self):
		# review M2: a room the promotion does not cover never holds its basket up
		others = [room("R1", "200.00", term("P", "250", forfeit="20.00")), room("R3", "500.00")]
		c = basket.clawback(others, room("R2", "40.00", term("P", "250", applied=False)), "EUR")
		self.assertEqual(c.amount, D("20.00"))

	def test_tax_follows_the_forfeit(self):
		others = [room("R1", "802.50", term(forfeit="96.30", net="80.25", tax="16.05"))]
		c = basket.clawback(others, room("R2", "214.00", term(applied=False)), "EUR")
		self.assertEqual((c.amount, c.net, c.tax), (D("96.30"), D("80.25"), D("16.05")))

	def test_what_another_room_carries_is_not_charged_twice(self):
		# R2 was shortened and carries R1's and R3's discount; R3 is now cancelled: R1's is still
		# carried by R2, and R3's own discount, paid by R2, is credited to R3's cancellation
		others = [room("R1", "300.00", term("P", "1000", forfeit="30.00")),
		          room("R2", "100.00", term("P", "1000", applied=False), carried={"P": "40.00"})]
		c = basket.clawback(others, None, "EUR", before=room("R3", "300.00", term("P", "1000", forfeit="10.00")))
		self.assertEqual(c.amount, D("-10.00"))
		self.assertIn("credit", c.promotions[0]["text"])

	def test_what_another_room_carries_is_given_back_when_the_booking_qualifies_again(self):
		others = [room("R1", "600.00", term("P", "1000", forfeit="30.00")),
		          room("R2", "100.00", term("P", "1000", applied=False), carried={"P": "30.00"})]
		c = basket.clawback(others, room("R3", "400.00", term("P", "1000", forfeit="20.00")), "EUR")
		self.assertEqual(c.amount, D("-30.00"))

	def test_a_room_repriced_at_its_full_price_gets_back_its_own_discount_paid_elsewhere(self):
		# R1 carries R2's discount (and R3's); R2 is changed and now pays its full price itself
		others = [room("R1", "100.00", term("P", "1000", applied=False), carried={"P": "50.00"}),
		          room("R3", "300.00", term("P", "1000", forfeit="20.00"))]
		c = basket.clawback(others, room("R2", "250.00", term("P", "1000", applied=False)), "EUR")
		self.assertEqual(c.amount, D("-30.00"))            # R3's 20 still owed, 50 already paid by R1

	def test_the_last_room_cancelled_gets_back_what_a_cancelled_room_paid_for_it(self):
		# R2 was cancelled first and its charge carried R1's 80.25; R1 is now cancelled too
		settled = [room("R2", "321.00", term(applied=False), carried={"BIG": "80.25"})]
		c = basket.clawback([], None, "EUR", before=room("R1", "802.50", term(forfeit="80.25")), settled=settled)
		self.assertEqual(c.amount, D("-80.25"))
		self.assertEqual(c.promotions[0]["carried_by"], [{"reservation": "R2", "amount": "80.25"}])

	def test_a_room_with_nothing_recorded_charges_nothing(self):
		others = [room("R1", "802.50", term(forfeit="0"))]
		self.assertEqual(basket.clawback(others, None, "EUR").amount, D("0"))

	def test_deterministic_and_json_safe(self):
		others = [room("R1", "802.50", term(forfeit="80.25")), room("R0", "10.00", term(forfeit="1.00"))]
		a = basket.clawback(others, room("R2", "214.00", term(applied=False)), "EUR").to_dict()
		b = basket.clawback(list(reversed(others)), room("R2", "214.00", term(applied=False)), "EUR").to_dict()
		self.assertEqual(a, b)
		self.assertEqual(a["amount"], "81.25")
		self.assertEqual([r["reservation"] for r in a["promotions"][0]["rooms"]], ["R0", "R1"])


if __name__ == "__main__":
	unittest.main()
