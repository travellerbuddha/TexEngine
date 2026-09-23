"""Pure tests: gateway signatures, FX feed parsers and CRM segment rules."""

import base64
import hashlib
import hmac
import unittest
from datetime import date
from decimal import Decimal

from kamra.tex.connect import fx_providers as fx
from kamra.tex.payments.providers import simple, turkey

TCMB_XML = """<?xml version="1.0" encoding="UTF-8"?>
<Tarih_Date Tarih="22.09.2026" Date="09/22/2026" Bulten_No="2026/180">
  <Currency CrossOrder="0" Kod="USD" CurrencyCode="USD">
    <Unit>1</Unit><Isim>ABD DOLARI</Isim><CurrencyName>US DOLLAR</CurrencyName>
    <ForexBuying>41.2345</ForexBuying><ForexSelling>41.3088</ForexSelling>
    <BanknoteBuying>41.2056</BanknoteBuying><BanknoteSelling>41.3708</BanknoteSelling>
  </Currency>
  <Currency CrossOrder="9" Kod="EUR" CurrencyCode="EUR">
    <Unit>1</Unit><ForexBuying>48.1000</ForexBuying><ForexSelling>48.1867</ForexSelling>
    <BanknoteBuying>48.0663</BanknoteBuying><BanknoteSelling>48.2590</BanknoteSelling>
  </Currency>
  <Currency CrossOrder="3" Kod="JPY" CurrencyCode="JPY">
    <Unit>100</Unit><ForexBuying>27.9000</ForexBuying><ForexSelling>28.0800</ForexSelling>
    <BanknoteBuying></BanknoteBuying><BanknoteSelling></BanknoteSelling>
  </Currency>
  <Currency CrossOrder="99" Kod="XDR" CurrencyCode="XDR">
    <Unit>1</Unit><ForexBuying>56.0</ForexBuying><ForexSelling></ForexSelling>
  </Currency>
</Tarih_Date>"""

ECB_XML = """<?xml version="1.0" encoding="UTF-8"?>
<gesmes:Envelope xmlns:gesmes="http://www.gesmes.org/xml/2002-08-01"
  xmlns="http://www.ecb.int/vocabulary/2002-08-01/eurofxref">
  <gesmes:subject>Reference rates</gesmes:subject>
  <Cube><Cube time="2026-09-22">
    <Cube currency="USD" rate="1.1672"/><Cube currency="TRY" rate="48.1543"/><Cube currency="GBP" rate="0.8671"/>
  </Cube></Cube>
</gesmes:Envelope>"""


class TestFxParsers(unittest.TestCase):
	def test_tcmb_rates_are_per_unit_and_skip_blank_and_xdr(self):
		day, rates = fx.parse_tcmb(TCMB_XML)
		self.assertEqual(day, date(2026, 9, 22))
		got = {(b, q, t): r for b, q, t, r in rates}
		self.assertEqual(got[("EUR", "TRY", "FOREX_SELLING")], Decimal("48.1867"))
		self.assertEqual(got[("USD", "TRY", "BANKNOTE_BUYING")], Decimal("41.2056"))
		self.assertEqual(got[("JPY", "TRY", "FOREX_BUYING")], Decimal("0.279"))       # quoted per 100 yen
		self.assertNotIn(("JPY", "TRY", "BANKNOTE_BUYING"), got)
		self.assertFalse(any(b == "XDR" for b, *_ in rates))
		self.assertTrue(all(isinstance(r, Decimal) for *_, r in rates))

	def test_ecb_reference_rates(self):
		day, rates = fx.parse_ecb(ECB_XML)
		self.assertEqual(day, date(2026, 9, 22))
		self.assertIn(("EUR", "TRY", "REFERENCE", Decimal("48.1543")), rates)
		self.assertEqual(len(rates), 3)

	def test_decimal_parser_rejects_garbage(self):
		self.assertIsNone(fx._dec("abc"))
		self.assertIsNone(fx._dec("0"))
		self.assertEqual(fx._dec("1,5"), Decimal("1.5"))


class TestGatewaySignatures(unittest.TestCase):
	def test_iyzico_v2_header(self):
		header = turkey.iyzico_auth_header("apiKey1", "secretKey1", "/payment/test", '{"a":1}', "123456")
		self.assertTrue(header.startswith("IYZWSv2 "))
		raw = base64.b64decode(header.removeprefix("IYZWSv2 ")).decode()
		sig = hmac.new(b"secretKey1", b'123456/payment/test{"a":1}', hashlib.sha256).hexdigest()
		self.assertEqual(raw, f"apiKey:apiKey1&randomKey:123456&signature:{sig}")

	def test_nestpay_hash_v3_escaping_and_order(self):
		params = {"clientid": "100", "oid": "PTX-1", "amount": "10.00", "Instalment": "", "hash": "ignored",
		          "encoding": "utf-8", "okUrl": "https://x/cb", "rnd": "a|b\\c"}
		h = turkey.nestpay_hash_v3(params, "STORE|KEY")
		plain = "10.00|100||PTX-1|https://x/cb|a\\|b\\\\c|STORE\\|KEY"      # sorted case-insensitively
		self.assertEqual(h, base64.b64encode(hashlib.sha512(plain.encode()).digest()).decode())

	def test_sipay_hash_roundtrip(self):
		key = turkey.sipay_hash_key("842.50", "1", "EUR", "MK", "PTX-9", "app-secret")
		self.assertNotIn("/", key)
		self.assertEqual(turkey.sipay_parse_hash_key(key, "app-secret"), ["842.50", "1", "EUR", "MK", "PTX-9"])
		with self.assertRaises(Exception):
			turkey.sipay_parse_hash_key(key, "wrong-secret")

	def test_mock_provider_refuses_production_and_checks_signature(self):
		class Acc(dict):
			def get(self, k, default=None):
				return super().get(k, default)

		with self.assertRaises(turkey.ProviderError):
			simple.MockProvider(Acc(environment="Production"), "s")
		p = simple.MockProvider(Acc(environment="Sandbox"), "secret")
		good = simple.mock_signature("secret", "PTX-1", "success")
		self.assertEqual(p.handle_callback("PTX-1", {"outcome": "success", "sig": good}, {}, b"").status,
		                 "Succeeded")
		with self.assertRaises(turkey.ProviderError):
			p.handle_callback("PTX-2", {"outcome": "success", "sig": good}, {}, b"")     # sig bound to txn
		fail = simple.mock_signature("secret", "PTX-1", "fail")
		self.assertEqual(p.handle_callback("PTX-1", {"outcome": "fail", "sig": fail}, {}, b"").status, "Failed")

	def test_nestpay_callback_needs_valid_hash_and_matching_order(self):
		class Acc(dict):
			def get(self, k, default=None):
				return super().get(k, default)

			def get_password(self, field, raise_exception=False):
				return "SK" if field == "store_key" else None

		p = turkey.NestPayProvider(Acc(environment="Sandbox"))
		params = {"oid": "PTX-5", "Response": "Approved", "ProcReturnCode": "00", "mdStatus": "1",
		          "amount": "10.00", "TransId": "T1", "MaskedPan": "454360***4242"}
		params["HASH"] = turkey.nestpay_hash_v3(params, "SK")
		out = p.handle_callback("PTX-5", dict(params), {}, b"")
		self.assertEqual(out.status, "Succeeded")
		self.assertEqual(out.card_last4, "4242")
		self.assertEqual(out.amount, Decimal("10.00"))
		with self.assertRaises(turkey.ProviderError):
			p.handle_callback("PTX-6", dict(params), {}, b"")
		tampered = {**params, "amount": "1.00"}
		with self.assertRaises(turkey.ProviderError):
			p.handle_callback("PTX-5", tampered, {}, b"")
