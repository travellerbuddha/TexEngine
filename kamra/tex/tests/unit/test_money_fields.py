"""G-72 (R-02, R-03, ADR-055): TEX commercial decimal fields and FX precision.

* ``money.db_dec`` is THE reader of a TEX Float/Currency/Percent column: the binary float
  Frappe hands over becomes exactly the Decimal the DECIMAL(21,9) column holds, never a
  value with binary noise; ``money.db_input`` checks a typed value so that what is stored is
  exactly what was typed (up to 9 decimals) or it is refused.
* FX rates keep at least 10 significant digits (TRY→EUR 0.02941176471, not 0.029412); a rate
  recorded before G-72 (6 places) is read back as recorded, so a price-locked reservation
  reprices to its sold total.
* The explanation shows a 7–9-decimal rule value as it is, not rounded to 6 (or 4).
"""

from __future__ import annotations

import random
import unittest
from datetime import date, datetime
from decimal import Decimal
from unittest import mock

from kamra.tex import money
from kamra.tex.money import D
from kamra.tex.pricing import engine, fx
from kamra.tex.pricing.enums import FxMode, OccTarget, Op
from kamra.tex.pricing.model import FxSnapshot, OccupancyRule, RoomRule
from kamra.tex.tests.unit import fixtures

AS_OF = datetime(2027, 1, 15, 12, 0)
TCMB = (fx.ProviderRate("FXR-EURTRY", "TCMB", "EUR", "TRY", D("34"), date(2027, 1, 14)),)
TRY_EUR = fx.FxPolicy("FXP-TRYEUR", "TRY", "EUR", FxMode.PROVIDER, provider="TCMB")


def column(text: str) -> float:
	"""What Frappe hands back for a DECIMAL column holding ``text`` (pymysql: float(bytes))."""
	return float(text)


class TestColumnValuesReadExactly(unittest.TestCase):
	def test_binary_noise_never_reaches_the_engine(self):
		self.assertEqual(money.db_dec(0.1 + 0.2), Decimal("0.3"))                 # 0.30000000000000004
		self.assertEqual(money.db_dec(0.7 + 0.1), Decimal("0.8"))                 # 0.7999999999999999
		self.assertEqual(money.db_dec(1.1 * 3), Decimal("3.3"))                   # 3.3000000000000003

	def test_a_stored_value_round_trips_exactly(self):
		for text in ("12.345678901", "0.333333333", "0.029411765", "34.123456789", "999999.999999999",
		             "1234567.123456789", "0.000000001", "-12.5", "100", "999999999999.99", "18.123456789"):
			self.assertEqual(money.db_dec(column(text)), Decimal(text), text)

	def test_any_nine_place_value_below_a_million_round_trips(self):
		rnd = random.Random(72)
		for _ in range(20000):
			text = f"{rnd.randrange(-10**15 + 1, 10**15)}"
			value = Decimal(text).scaleb(-9)                                        # |v| < 10^6, 9 places
			self.assertEqual(money.db_dec(float(format(value, "f"))), value, text)

	def test_money_of_any_column_size_round_trips(self):
		rnd = random.Random(55)
		for _ in range(20000):
			value = Decimal(rnd.randrange(-10**14 + 1, 10**14)).scaleb(-2)          # |v| < 10^12, cents
			self.assertEqual(money.db_dec(float(format(value, "f"))), value)

	def test_the_decimal_is_the_one_a_float_repr_gives(self):
		# a clean value keeps the representation D() always gave it (the payload hash is value-based,
		# explanations and API output keep their text)
		for v in (12.5, 100.0, 0.3, 1.35, 12.345678901):
			self.assertEqual(str(money.db_dec(v)), str(D(v)))
		self.assertEqual(str(money.db_dec(0.1 + 0.2)), "0.3")
		self.assertEqual(money.db_dec(None), Decimal(0))
		self.assertIsNone(money.db_dec_or_none(""))
		self.assertEqual(money.db_dec("0.1234567891"), Decimal("0.123456789"))    # beyond the column

	def test_typed_values_are_stored_as_typed_or_refused(self):
		self.assertEqual(money.db_input("0.333333333"), Decimal("0.333333333"))
		self.assertEqual(money.db_input(" 12.5 "), Decimal("12.5"))
		self.assertEqual(money.db_input("0.1000000000"), Decimal("0.100000000"))  # trailing zeros are no digits
		self.assertIsNone(money.db_input(""))
		for text, code in (("0.1234567891", "PLACES"), ("12,5", "NOT_A_NUMBER"), ("abc", "NOT_A_NUMBER"),
		                   ("NaN", "NOT_A_NUMBER"), ("1234567.123456789", "DIGITS"),
		                   ("1000000000000", "RANGE"), ("-1000000000000.5", "RANGE")):
			with self.assertRaises(money.DecimalInputError, msg=text) as cm:
				money.db_input(text)
			self.assertEqual(cm.exception.code, code, text)
		self.assertEqual(money.db_input("999999999999.99"), Decimal("999999999999.99"))
		self.assertEqual(money.db_input("2.95", places=2), Decimal("2.95"))
		with self.assertRaises(money.DecimalInputError):
			money.db_input("2.955", places=2)
		# a binary float (a script's number) has no typed digits: rounded as the column would
		self.assertEqual(money.db_input(0.1 + 0.2), Decimal("0.3"))
		self.assertEqual(money.db_input(0.12345678912), Decimal("0.123456789"))


class TestFxSignificantDigits(unittest.TestCase):
	def test_try_to_eur_keeps_ten_significant_digits(self):
		s = fx.resolve_fx("TRY", "EUR", TRY_EUR, TCMB, AS_OF)
		self.assertEqual(s.sell_rate, D("0.02941176471"))          # 1/34; was 0.029412 (5 significant digits)
		self.assertEqual(s.provider_rate, D("0.02941176471"))
		self.assertEqual(s.to_dict()["sell_rate"], "0.02941176471")
		self.assertEqual(fx.from_dict(s.to_dict()).sell_rate, s.sell_rate)   # the record is exact

	def test_rate_precision(self):
		self.assertEqual(money.quantize_rate(D(1) / D(34)), D("0.02941176471"))
		self.assertEqual(money.quantize_rate(D("1.10") / D("0.85")), D("1.294117647"))
		self.assertEqual(money.quantize_rate(D("51")), D("51.00000000"))
		self.assertEqual(money.quantize_rate(D("27123.4567891")), D("27123.456789"))    # never below 6 places
		self.assertEqual(money.quantize_rate(D(1) / D(34), places=6), D("0.029412"))     # the pre-G-72 rounding
		self.assertEqual(money.rate_places(D("0.00007")), 14)

	def test_a_rate_serialises_as_recorded(self):
		# rates recorded before G-72 (6 places) serialise byte-identically to their record
		for text in ("51.000000", "0.029412", "40.000000", "1.294118", "0.020000"):
			self.assertEqual(money.to_str_rate(D(text)), text)
			self.assertEqual(money.to_str_rate(D(text).normalize()), text)       # whatever the exponent
		self.assertEqual(money.to_str_rate(D("0.02941176471")), "0.02941176471")
		self.assertEqual(money.to_str_rate(D("51.00000000")), "51.000000")
		self.assertEqual(money.to_str_rate(D("-1.5")), "-1.500000")
		self.assertIsNone(money.to_str_rate(None))

	def test_an_old_pinned_rate_reproduces_the_old_total(self):
		t = fixtures.terms(currency="TRY", room_rules=(RoomRule("R-STD", "STD", None, Op.ABSOLUTE, D("25000")),))
		req = fixtures.req(sell_currency="EUR", check_out=date(2027, 6, 5))      # 3 nights, 2 adults: 150,000 TRY

		with mock.patch.object(money, "FX_SIGNIFICANT", 0):                      # the pre-G-72 precision
			old_rate = fx.resolve_fx("TRY", "EUR", TRY_EUR, TCMB, AS_OF)
		self.assertEqual(old_rate.to_dict()["sell_rate"], "0.029412")
		sold = engine.price_stay(fixtures.ctx(t, fx=old_rate), req)
		self.assertEqual(sold.totals["total"], D("4411.80"))                      # 150,000 × 0.029412

		# today's resolution: the new precision
		now = engine.price_stay(fixtures.ctx(t, fx=fx.resolve_fx("TRY", "EUR", TRY_EUR, TCMB, AS_OF)), req)
		self.assertEqual(now.totals["total"], D("4411.76"))                       # 150,000 / 34
		self.assertEqual(now.to_dict()["fx"]["sell_rate"], "0.02941176471")

		# a reprice on the sold terms converts with the rate the sale recorded, read back exactly
		record = sold.to_dict()["fx_rates"]
		self.assertEqual([r["sell_rate"] for r in record], ["0.029412"])
		pin = fx.pins(record, origin="reservation:RES-1")[("TRY", "EUR")]
		again = engine.price_stay(fixtures.ctx(t, fx=pin), req)
		self.assertEqual(again.totals["total"], sold.totals["total"])
		strip = lambda rates: [{k: v for k, v in r.items() if k != "origin"} for r in rates]  # noqa: E731
		self.assertEqual(strip(again.to_dict()["fx_rates"]), record)
		self.assertEqual([s["params"]["rate"] for s in again.to_dict()["explanation"] if s["code"] == "FX"],
		                 [s["params"]["rate"] for s in sold.to_dict()["explanation"] if s["code"] == "FX"])


class TestExplanationShowsTheRuleValue(unittest.TestCase):
	def test_a_nine_place_factor_is_explained_as_it_is(self):
		third = OccupancyRule("O-A3", OccTarget.ADULT, Op.MULTIPLY, D("0.333333333"), position=2)
		t = fixtures.terms(occupancy_rules=(*(r for r in fixtures.occ_rules() if r.rule_id != "O-A2"), third))
		q = engine.price_stay(fixtures.ctx(t), fixtures.req()).to_dict()
		self.assertEqual(q["totals"]["total"], "133.33")                          # 100 + 100 × 0.333333333
		step = next(s for s in q["explanation"] if s["code"] == "ADULT_SLOT" and s["params"]["pos"] == 2)
		self.assertEqual(step["params"]["op"], "× 0.333333333")
		self.assertIn("× 0.333333333", step["text"])
		self.assertEqual(step["params"]["amount"], "33.3333333")                  # was 33.333333
		# values of up to 6 places explain exactly as before
		plain = engine.price_stay(fixtures.ctx(), fixtures.req()).to_dict()
		slot = next(s for s in plain["explanation"] if s["code"] == "ADULT_SLOT")
		self.assertEqual((slot["params"]["op"], slot["params"]["unit"]), ("× 1.00", "100.000000"))


if __name__ == "__main__":
	unittest.main()

