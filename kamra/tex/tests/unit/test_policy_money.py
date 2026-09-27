"""Fixed policy amounts and their currency (Y-3 A, ADR-067; D-1).

A payment or cancellation policy's fixed amounts (a FIXED deposit, a FIXED cancellation rule or
no-show) are in the policy's currency, or the contract's when the policy names none. A policy is
frozen with that currency only when it has a fixed amount; a payload frozen before reads it so (the
K-1 pattern). A fixed amount is converted to the sale's currency at the contract → sell rate the
quote recorded; a fixed deposit is taken once per booking, on its first room that carries the
policy (ADR-029). ``validate_terms`` refuses a fixed policy in another currency than the contract's
(``POLICY_CURRENCY``), so the conversion is always that one rate.
"""

import unittest
from dataclasses import replace
from decimal import Decimal

from kamra.tex.pricing import policy_money, serialize, validate
from kamra.tex.pricing.model import PricingError, RatePlanTerms
from kamra.tex.tests.unit import fixtures as fx

D = Decimal

FIXED_DEPOSIT = {"id": "PAY-FIX", "name": "100 now", "deposit_type": "FIXED", "deposit_value": "100",
                 "balance_due_days": 0, "allow_pay_at_hotel": False, "description": ""}
PERCENT_DEPOSIT = {"id": "PAY-30", "name": "30 %", "deposit_type": "PERCENT", "deposit_value": "30",
                   "balance_due_days": 14, "allow_pay_at_hotel": True, "description": ""}
FIXED_FEE = {"id": "CXL-FIX", "name": "150 fee", "refundable": True,
             "rules": [{"days_before_arrival": 7, "penalty_type": "FIXED", "penalty_value": "150"}],
             "no_show": {"type": "NIGHTS", "value": "1"}, "description": ""}
FIXED_NO_SHOW = {"id": "CXL-NS", "name": "No-show 80", "refundable": True,
                 "rules": [{"days_before_arrival": 3, "penalty_type": "PERCENT", "penalty_value": "50"}],
                 "no_show": {"type": "FIXED", "value": "80"}, "description": ""}


def sold(sell: str, rate: str = "1", contract: str = "EUR", *, policy=None, room_index: int = 0) -> dict:
	"""A room's internal quote as a snapshot keeps it: what the helpers read."""
	return {"currency": sell, "contract": {"currency": contract},
	        "fx": {"from": contract, "to": sell, "sell_rate": rate},
	        "request": {"room_index": room_index}, "rate_plan": {"code": "FLEX", "payment_policy": policy}}


class TestFixedInSell(unittest.TestCase):
	def test_a_contract_currency_amount_is_converted_at_the_quotes_rate(self):
		pol = {**FIXED_DEPOSIT, "currency": "EUR"}
		self.assertEqual(policy_money.fixed_in_sell("100", pol, sold("TRY", "51")), D("5100.00"))

	def test_rounded_half_up_to_the_sale_currencys_minor_unit(self):
		pol = {**FIXED_DEPOSIT, "currency": "EUR"}
		self.assertEqual(policy_money.fixed_in_sell("1", pol, sold("USD", "1.225")), D("1.23"))
		self.assertEqual(policy_money.fixed_in_sell("1", pol, sold("KWD", "0.3335")), D("0.334"))

	def test_a_sale_in_the_policys_currency_keeps_the_amount(self):
		pol = {**FIXED_DEPOSIT, "currency": "EUR"}
		self.assertEqual(policy_money.fixed_in_sell("100", pol, sold("EUR")), D("100.00"))

	def test_a_policy_sold_before_it_had_a_currency_keeps_its_amount(self):
		"""A snapshot sold before this change holds the policy without ``currency``: the stay keeps the
		terms it was sold on (the audit's decision), in the sale's currency."""
		self.assertEqual(policy_money.fixed_in_sell("100", FIXED_DEPOSIT, sold("TRY", "51")), D("100"))

	def test_a_third_currency_is_refused(self):
		pol = {**FIXED_DEPOSIT, "currency": "USD"}
		with self.assertRaises(PricingError):
			policy_money.fixed_in_sell("100", pol, sold("TRY", "51"))


class TestDepositOncePerBooking(unittest.TestCase):
	def deposits(self, results) -> list[Decimal]:
		first = policy_money.first_rooms_per_policy(results)
		return [D("100") if first.get(r["rate_plan"]["payment_policy"]["id"]) == i else D(0)
		        for i, r in enumerate(results)]

	def test_three_rooms_take_it_on_the_first_room_only(self):
		rooms = [sold("EUR", policy=FIXED_DEPOSIT, room_index=i) for i in range(3)]
		self.assertEqual(self.deposits(rooms), [D("100"), D(0), D(0)])

	def test_room_one_takes_it_wherever_it_is_listed(self):
		rooms = [sold("EUR", policy=FIXED_DEPOSIT, room_index=i) for i in (2, 0, 1)]
		self.assertEqual(self.deposits(rooms), [D(0), D("100"), D(0)])

	def test_two_policies_are_each_taken_once(self):
		other = {**FIXED_DEPOSIT, "id": "PAY-FIX-2"}
		rooms = [sold("EUR", policy=FIXED_DEPOSIT, room_index=0), sold("EUR", policy=other, room_index=1),
		         sold("EUR", policy=FIXED_DEPOSIT, room_index=2), sold("EUR", policy=other, room_index=3)]
		self.assertEqual(policy_money.first_rooms_per_policy(rooms), {"PAY-FIX": 0, "PAY-FIX-2": 1})
		self.assertEqual(self.deposits(rooms), [D("100"), D("100"), D(0), D(0)])

	def test_a_room_without_a_payment_policy_takes_none(self):
		rooms = [sold("EUR", policy=None, room_index=0), sold("EUR", policy=FIXED_DEPOSIT, room_index=1)]
		self.assertEqual(policy_money.first_rooms_per_policy(rooms), {"PAY-FIX": 1})


class TestFrozenCurrency(unittest.TestCase):
	def test_which_policies_have_a_fixed_amount(self):
		for pol, fixed in ((FIXED_DEPOSIT, True), (FIXED_FEE, True), (FIXED_NO_SHOW, True), (PERCENT_DEPOSIT, False),
		                   ({"refundable": False, "rules": []}, False), (None, False)):
			with self.subTest(pol=pol):
				self.assertIs(policy_money.has_fixed(pol), fixed)

	def test_a_payload_frozen_without_it_reads_the_contracts_currency(self):
		t = replace(fx.terms(), rate_plans={
			"FLEX": RatePlanTerms("FLEX", "Flexible", cancellation_policy=FIXED_FEE, payment_policy=FIXED_DEPOSIT),
			"SAVER": RatePlanTerms("SAVER", "Saver", cancellation_policy=FIXED_NO_SHOW, payment_policy=PERCENT_DEPOSIT)})
		payload = serialize.normalise_payload(serialize.terms_to_payload(t))
		self.assertNotIn("currency", payload["rate_plans"][0]["payment_policy"])      # frozen as it was
		back = serialize.terms_from_payload(payload)
		flex, saver = back.rate_plans["FLEX"], back.rate_plans["SAVER"]
		self.assertEqual(flex.payment_policy, {**FIXED_DEPOSIT, "currency": "EUR"})
		self.assertEqual(flex.cancellation_policy, {**FIXED_FEE, "currency": "EUR"})
		self.assertEqual(saver.cancellation_policy, {**FIXED_NO_SHOW, "currency": "EUR"})
		self.assertEqual(saver.payment_policy, PERCENT_DEPOSIT)                      # a percentage: as frozen
		self.assertNotIn("currency", saver.payment_policy)

	def test_a_frozen_currency_is_kept(self):
		t = replace(fx.terms(), rate_plans={"FLEX": RatePlanTerms(
			"FLEX", "Flexible", payment_policy={**FIXED_DEPOSIT, "currency": "try"})})
		back = serialize.terms_from_payload(serialize.normalise_payload(serialize.terms_to_payload(t)))
		self.assertEqual(back.rate_plans["FLEX"].payment_policy["currency"], "try")
		self.assertEqual(policy_money.with_currency({**FIXED_DEPOSIT, "currency": "TRY"}, "EUR")["currency"], "TRY")


class TestPolicyCurrencyIssue(unittest.TestCase):
	def issues(self, **plan):
		t = replace(fx.terms(), rate_plans={"FLEX": RatePlanTerms("FLEX", "Flexible", **plan)})
		return [(i.level, i.code) for i in validate.validate_terms(t) if i.code == "POLICY_CURRENCY"]

	def test_a_fixed_policy_in_another_currency_is_an_error(self):
		for plan in ({"payment_policy": {**FIXED_DEPOSIT, "currency": "TRY"}},
		             {"cancellation_policy": {**FIXED_FEE, "currency": "TRY"}},
		             {"cancellation_policy": {**FIXED_NO_SHOW, "currency": "USD"}}):
			with self.subTest(plan=plan):
				self.assertEqual(self.issues(**plan), [("ERROR", "POLICY_CURRENCY")])

	def test_the_contracts_currency_or_none_or_a_percentage_is_fine(self):
		for plan in ({"payment_policy": {**FIXED_DEPOSIT, "currency": "EUR"}},
		             {"payment_policy": {**FIXED_DEPOSIT, "currency": "eur"}},
		             {"payment_policy": FIXED_DEPOSIT},
		             {"payment_policy": {**PERCENT_DEPOSIT, "currency": "TRY"}},
		             {"cancellation_policy": {**FIXED_FEE, "currency": "EUR"}}):
			with self.subTest(plan=plan):
				self.assertEqual(self.issues(**plan), [])


if __name__ == "__main__":
	unittest.main()
