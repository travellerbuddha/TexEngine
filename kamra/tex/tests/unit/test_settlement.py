"""Pure tests: how a guest's own change is settled (G-45, ADR-044).

The fixture booking: FLEX, 842.50 with a 30 % deposit (252.75); one more LOW night costs
267.50 (new total 1110.00, deposit 333.00); one night less makes it 575.00."""

import unittest
from decimal import Decimal

from kamra.tex.payments import settlement as st

D = Decimal


def settle(old, new, paid, required, *, pay_at_hotel=False, policy=st.LOWER_STAFF, card=True):
	return st.settle(D(old), D(new), D(paid), D(required), pay_at_hotel=pay_at_hotel, lower_policy=policy,
	                 card_available=card)


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

	def test_only_the_true_overpayment_is_refunded(self):
		s = settle("842.50", "575.00", "600.00", "172.50", policy=st.LOWER_REFUND)
		self.assertEqual((s.kind, s.refund), (st.REFUND, D("25.00")))


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

	def test_nothing_to_refund_from(self):
		self.assertEqual(st.plan_refunds(D("10"), []), ([], D("10")))
		self.assertEqual(st.plan_refunds(D("0"), [self.T1]), ([], D("0")))
