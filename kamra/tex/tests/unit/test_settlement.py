"""Pure tests: how a guest's own change is settled (G-45, ADR-044 and its review).

The fixture booking: FLEX, 842.50 with a 30 % deposit (252.75); one more LOW night costs
267.50 (new total 1110.00, deposit 333.00); one night less makes it 575.00."""

import unittest
from decimal import Decimal

from kamra.tex.payments import settlement as st

D = Decimal


def settle(old, new, paid, required, *, pay_at_hotel=False, policy=st.LOWER_STAFF, card=True, penalty=False,
           auto=None, **kw):
	return st.settle(D(old), D(new), D(paid), D(required), pay_at_hotel=pay_at_hotel, lower_policy=policy,
	                 card_available=card, penalty_applies=penalty, auto_refundable=auto, **kw)


class TestHigherPrice(unittest.TestCase):
	def test_a_deposit_booking_pays_the_deposit_share_of_the_new_total(self):
		s = settle("842.50", "1110.00", "252.75", "333.00")
		self.assertEqual((s.kind, s.collect, s.amount), (st.PAY_NOW, D("80.25"), D("80.25")))
		self.assertEqual((s.balance_after, s.due_later), (D("777.00"), D("187.25")))

	def test_a_prepaid_booking_pays_the_whole_difference(self):
		s = settle("842.50", "1110.00", "842.50", "1110.00")
		self.assertEqual((s.kind, s.collect, s.balance_after), (st.PAY_NOW, D("267.50"), D("0.00")))

	def test_pay_at_hotel_collects_nothing_and_says_what_is_due_there(self):
		s = settle("842.50", "1110.00", "0", "0", pay_at_hotel=True)
		self.assertEqual((s.kind, s.collect, s.amount, s.balance_after),
		                 (st.PAY_AT_HOTEL, D("0"), D("267.50"), D("1110.00")))
		self.assertTrue(s.applies_now)

	def test_arrears_are_never_charged_by_a_change(self):
		s = settle("842.50", "1110.00", "0", "1110.00")
		self.assertEqual((s.kind, s.collect), (st.PAY_NOW, D("267.50")))

	def test_without_a_card_method_staff_collect_it(self):
		s = settle("842.50", "1110.00", "252.75", "333.00", card=False)
		self.assertEqual((s.kind, s.collect, s.amount), (st.STAFF, D("80.25"), D("80.25")))
		self.assertFalse(s.applies_now)

	def test_a_credit_is_used_before_anything_is_charged(self):
		s = settle("575.00", "842.50", "842.50", "252.75", policy=st.LOWER_CREDIT)
		self.assertEqual((s.kind, s.collect, s.amount, s.balance_after), (st.BALANCE, D("0"), D("0"), D("0.00")))

	def test_a_deposit_already_covering_the_new_terms_adds_to_the_balance(self):
		s = settle("842.50", "900.00", "300.00", "270.00")
		self.assertEqual((s.kind, s.collect, s.amount), (st.BALANCE, D("0"), D("57.50")))

	def test_an_unchanged_price(self):
		s = settle("842.50", "842.50", "252.75", "252.75")
		self.assertEqual((s.kind, s.amount, s.applies_now), (st.NONE, D("0"), True))


class TestLowerPrice(unittest.TestCase):
	def test_the_default_policy_waits_for_the_hotel(self):
		for policy in (st.LOWER_STAFF, None, "something new"):
			s = settle("842.50", "575.00", "842.50", "575.00", policy=policy)
			self.assertEqual((s.kind, s.refund, s.credit, s.amount), (st.STAFF_APPROVAL, D("0"), D("0"),
			                                                           D("267.50")))

	def test_refund_automatically_refunds_the_overpayment(self):
		s = settle("842.50", "575.00", "842.50", "575.00", policy=st.LOWER_REFUND)
		self.assertEqual((s.kind, s.refund, s.amount, s.balance_after), (st.REFUND, D("267.50"), D("267.50"),
		                                                                  D("0.00")))

	def test_a_deposit_only_booking_just_owes_less(self):
		s = settle("842.50", "575.00", "252.75", "172.50", policy=st.LOWER_REFUND)
		self.assertEqual((s.kind, s.refund, s.amount, s.balance_after), (st.BALANCE, D("0"), D("267.50"),
		                                                                  D("322.25")))

	def test_keep_as_credit(self):
		s = settle("842.50", "575.00", "842.50", "575.00", policy=st.LOWER_CREDIT)
		self.assertEqual((s.kind, s.credit, s.refund, s.balance_after), (st.CREDIT, D("267.50"), D("0"),
		                                                                  D("-267.50")))

	def test_a_lower_price_the_rate_would_charge_for_goes_to_the_hotel(self):
		# a non-refundable rate, or inside the cancellation penalty window (review of ADR-044)
		for policy in (st.LOWER_REFUND, st.LOWER_CREDIT, st.LOWER_STAFF):
			s = settle("842.50", "307.50", "842.50", "307.50", policy=policy, penalty=True)
			self.assertEqual((s.kind, s.refund, s.credit, s.amount), (st.STAFF_APPROVAL, D("0"), D("0"),
			                                                           D("535.00")))
		# a higher price is collected as usual
		self.assertEqual(settle("842.50", "1110.00", "842.50", "1110.00", penalty=True).kind, st.PAY_NOW)

	def test_moving_the_stay_inside_the_penalty_window_goes_to_the_hotel_at_any_price(self):
		# the stay moved later would leave the window: a later shortening would dodge the fee
		# (G-45 re-review F5)
		for new, paid in (("1110.00", "842.50"), ("842.50", "842.50"), ("575.00", "842.50")):
			s = st.settle(D("842.50"), D(new), D(paid), D("0"), pay_at_hotel=False, lower_policy=st.LOWER_REFUND,
			              card_available=True, terms_review=True)
			self.assertEqual((s.kind, s.collect, s.refund, s.credit), (st.STAFF_APPROVAL, D("0"), D("0"), D("0")))

	def test_what_no_card_can_take_back_is_refunded_by_the_hotel(self):
		s = settle("842.50", "575.00", "842.50", "575.00", policy=st.LOWER_REFUND, auto=D("100.00"))
		self.assertEqual((s.kind, s.refund, s.hotel_refund, s.amount), (st.REFUND, D("100.00"), D("167.50"),
		                                                                D("267.50")))
		s = settle("842.50", "575.00", "842.50", "575.00", policy=st.LOWER_REFUND, auto=D("0"))
		self.assertEqual((s.refund, s.hotel_refund), (D("0"), D("267.50")))
		s = settle("842.50", "575.00", "842.50", "575.00", policy=st.LOWER_REFUND, auto=D("900.00"))
		self.assertEqual((s.refund, s.hotel_refund), (D("267.50"), D("0")))

	def test_only_the_true_overpayment_is_refunded(self):
		s = settle("842.50", "575.00", "600.00", "172.50", policy=st.LOWER_REFUND)
		self.assertEqual((s.kind, s.refund), (st.REFUND, D("25.00")))


class TestPointsOfALowerPrice(unittest.TestCase):
	"""LO-01 (O-19b, audit 2K-2 review round 1): under "refund automatically" the points' share of an overpayment comes
	back as points by itself; only what neither a card nor points take back is the hotel's."""

	def test_the_points_share_comes_back_as_points_the_rest_to_the_card(self):
		s = settle("842.50", "575.00", "842.50", "575.00", policy=st.LOWER_REFUND, auto=D("167.50"),
		           points_back=D("100.00"))
		self.assertEqual((s.kind, s.refund, s.points_back, s.hotel_refund, s.amount),
		                 (st.REFUND, D("167.50"), D("100.00"), D("0"), D("267.50")))

	def test_points_holding_more_than_the_overpayment_give_back_only_it(self):
		s = settle("842.50", "575.00", "842.50", "575.00", policy=st.LOWER_REFUND, auto=D("0"), points_back=D("300"))
		self.assertEqual((s.refund, s.points_back, s.hotel_refund, s.amount), (D("0"), D("267.50"), D("0"),
		                                                                        D("267.50")))

	def test_what_neither_a_card_nor_points_take_back_is_the_hotels(self):
		s = settle("842.50", "575.00", "842.50", "575.00", policy=st.LOWER_REFUND, auto=D("100.00"),
		           points_back=D("50.00"))
		self.assertEqual((s.refund, s.points_back, s.hotel_refund), (D("100.00"), D("50.00"), D("117.50")))


class TestPlanRefunds(unittest.TestCase):
	T1 = st.Charge("T1", D("252.75"), at="2027-01-01 10:00:00")          # the deposit
	T2 = st.Charge("T2", D("589.75"), at="2027-01-02 10:00:00")          # the balance, paid later

	def test_the_newest_charge_first(self):
		self.assertEqual(st.plan_refunds(D("267.50"), [self.T1, self.T2]), ([("T2", D("267.50"))], D("0")))

	def test_a_refund_larger_than_one_charge_spills_to_the_older(self):
		self.assertEqual(st.plan_refunds(D("700.00"), [self.T1, self.T2]),
		                 ([("T2", D("589.75")), ("T1", D("110.25"))], D("0")))

	def test_a_charge_the_provider_cannot_refund_is_skipped(self):
		t2 = st.Charge("T2", D("589.75"), supported=False, at=self.T2.at)
		self.assertEqual(st.plan_refunds(D("267.50"), [self.T1, t2]), ([("T1", D("252.75"))], D("14.75")))

	def test_an_overpayment_comes_off_the_points_first(self):
		"""O-19 (audit 2B): points are never paid back as cash: a card gets only what the refund is over
		the points holding the booking's money; the points' part is the hotel's to settle."""
		card = st.Charge("CARD", D("1000"), at="2027-01-01 10:00:00")
		points = st.Charge("PTS", D("500"), supported=False, at="2027-01-02 10:00:00", points=True)
		self.assertEqual(st.plan_refunds(D("600"), [card, points]), ([("CARD", D("100"))], D("500")))
		self.assertEqual(st.plan_refunds(D("400"), [card, points]), ([], D("400")))
		self.assertEqual(st.plan_refunds(D("600"), [card]), ([("CARD", D("600"))], D("0")))

	def test_nothing_to_refund_from(self):
		self.assertEqual(st.plan_refunds(D("10"), []), ([], D("10")))
		self.assertEqual(st.plan_refunds(D("0"), [self.T1]), ([], D("0")))
