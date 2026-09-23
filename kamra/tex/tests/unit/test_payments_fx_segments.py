"""Pure tests: gateway signatures, FX feed parsers and CRM segment rules."""

import base64
import hashlib
import hmac
import unittest
from datetime import date
from decimal import Decimal
from unittest import mock

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


class _Acc(dict):
	"""A provider account as the providers read it (``get`` and write-only secrets)."""

	def __init__(self, secrets=None, **kw):
		super().__init__(**kw)
		self._secrets = secrets or {}

	def get(self, k, default=None):
		return super().get(k, default)

	def get_password(self, field, raise_exception=False):
		return self._secrets.get(field)


class TestProviderRegistry(unittest.TestCase):
	"""G-67 (ADR-041): one registry decides what each provider may do."""

	def test_only_offline_methods_are_production_verified(self):
		from kamra.tex.payments.providers import REGISTRY

		self.assertEqual({k for k, cls in REGISTRY.items() if cls.production_verified}, {"Bank Transfer", "Pay at Hotel"})
		# Sipay's check-status field names are not yet confirmed by a recorded sandbox answer
		self.assertEqual({k for k, cls in REGISTRY.items() if cls.reports_amount}, {"iyzico", "Virtual POS"})
		self.assertEqual({k for k, cls in REGISTRY.items() if cls.gateway}, {"Mock", "iyzico", "Sipay", "Virtual POS"})
		self.assertEqual({k: cls.name for k, cls in REGISTRY.items()}, {k: k for k in REGISTRY})

	def test_a_sandbox_override_stays_on_the_providers_sandbox_host(self):
		from kamra.tex.payments.providers import account_problem

		def sandbox(provider, url, **kw):
			return account_problem(provider, "Sandbox", url, **kw)

		for provider, live, test in (
				("iyzico", "https://api.iyzipay.com", "https://sandbox-api.iyzipay.com"),
				("Sipay", "https://app.sipay.com.tr/ccpayment", "https://provisioning.sipay.com.tr/ccpayment"),
				("Virtual POS", "https://sanalpos.isbank.com.tr/fim/est3Dgate",
				 "https://entegrasyon.asseco-see.com.tr/fim/est3Dgate")):
			self.assertEqual(sandbox(provider, live), "sandbox_host", provider)            # the live gateway
			self.assertIsNone(sandbox(provider, test), provider)
			self.assertEqual(sandbox(provider, test.replace("https:", "http:")), "sandbox_host", provider)
		for sneaky in ("https://sandbox-api.iyzipay.com@api.iyzipay.com", "https://sandbox-api.iyzipay.com.evil.test",
		               "https://evil.test/?sandbox-api.iyzipay.com", "https://sandbox-api.iyzipay.com:x", "//api.iyzipay.com"):
			self.assertEqual(sandbox("iyzico", sneaky), "sandbox_host", sneaky)
		self.assertEqual(sandbox("iyzico", "http://localhost:8080"), "sandbox_host")    # only in developer mode
		self.assertIsNone(sandbox("iyzico", "http://localhost:8080", developer_mode=True))
		self.assertIsNone(sandbox("Bank Transfer", "https://anything.test"))           # never read by it
		self.assertIsNone(sandbox("iyzico", "  "))

	def test_a_live_site_runs_no_sandbox_gateway(self):
		from kamra.tex.payments.providers import account_problem

		for provider in ("Mock", "iyzico", "Sipay", "Virtual POS"):
			self.assertEqual(account_problem(provider, "Sandbox", None, live_site=True), "sandbox_live_site", provider)
			self.assertIsNone(account_problem(provider, "Sandbox", None), provider)
		for provider in ("Bank Transfer", "Pay at Hotel"):                             # no test money moves
			self.assertIsNone(account_problem(provider, "Sandbox", None, live_site=True), provider)

	def test_captured_money_settles_on_an_uncertified_production_account(self):
		from kamra.tex.payments.providers import account_problem

		self.assertEqual(account_problem("iyzico", "Production", None), "uncertified")
		self.assertIsNone(account_problem("iyzico", "Production", None, settling=True))
		# settling never goes through an override or the mock
		self.assertEqual(account_problem("iyzico", "Production", "https://x.test", settling=True), "gateway_url")
		self.assertEqual(account_problem("Mock", "Production", None, settling=True), "mock")
		self.assertEqual(account_problem("Nope", "Sandbox", None, settling=True), "unknown")

	def test_nestpay_reports_the_currency_it_charged(self):
		p = turkey.NestPayProvider(_Acc(secrets={"store_key": "SK"}, environment="Sandbox"))
		params = {"oid": "PTX-7", "Response": "Approved", "ProcReturnCode": "00", "mdStatus": "1",
		          "amount": "10.00", "currency": "978", "TransId": "T7"}
		params["HASH"] = turkey.nestpay_hash_v3(params, "SK")
		self.assertEqual(p.handle_callback("PTX-7", dict(params), {}, b"").currency, "EUR")
		odd = {**params, "currency": "999"}
		odd["HASH"] = turkey.nestpay_hash_v3({k: v for k, v in odd.items() if k != "HASH"}, "SK")
		self.assertEqual(p.handle_callback("PTX-7", odd, {}, b"").currency, "999")   # never mistaken for ours

	def test_iyzico_takes_one_checkout_per_charge(self):
		p = turkey.IyzicoProvider(_Acc(secrets={"secret_key": "sk", "api_key": "ak"}, environment="Sandbox"))
		self.assertTrue(p.can_add_checkout(None))
		self.assertFalse(p.can_add_checkout("tok-a"))          # another tab supersedes the charge (G-68)
		self.assertTrue(simple.MockProvider(_Acc(environment="Sandbox"), "s").can_add_checkout("MOCK-1"))
		self.assertEqual(turkey.iyzico_tokens("P1|I1 tok-b tok-a"), ["tok-b", "tok-a"])
		self.assertEqual(turkey.iyzico_payment("P1|I1 tok-b"), "P1|I1")
		detail = {"status": "success", "paymentStatus": "SUCCESS", "conversationId": "PTX-1", "basketId": "PTX-1",
		          "price": "80.00", "paidPrice": "80.00", "currency": "EUR", "paymentId": "P1",
		          "itemTransactions": [{"paymentTransactionId": "I1"}]}
		with mock.patch.object(p, "_post", return_value=detail):
			out = p.handle_callback("PTX-1", {"token": "tok-a"}, {}, b"", provider_ref="tok-a")
			self.assertEqual((out.status, out.amount, out.currency, out.provider_ref),
			                 ("Succeeded", Decimal("80.00"), "EUR", "P1|I1"))
			for forged in ("tok-x", "", "P1|I1"):
				with self.assertRaises(turkey.ProviderError):
					p.handle_callback("PTX-1", {"token": forged}, {}, b"", provider_ref="P1|I1 tok-a")
		with mock.patch.object(p, "_post", return_value={"status": "success", "paymentTransactionId": "R1"}) as post:
			p.refund("P1|I1 tok-a", Decimal("10"), "EUR")
			self.assertEqual(post.call_args.args[1]["paymentTransactionId"], "I1")
		with self.assertRaises(turkey.ProviderError):
			p.refund("tok-a", Decimal("10"), "EUR")                                    # no captured payment

	def test_iyzico_counts_the_basket_price_not_the_instalment_interest(self):
		p = turkey.IyzicoProvider(_Acc(secrets={"secret_key": "sk", "api_key": "ak"}, environment="Sandbox"))
		base = {"status": "success", "paymentStatus": "SUCCESS", "conversationId": "PTX-2", "basketId": "PTX-2",
		        "currency": "EUR", "paymentId": "P2", "itemTransactions": [{"paymentTransactionId": "I2"}]}
		for answer, amount in (({"price": "80.00", "paidPrice": "83.20"}, Decimal("80.00")),   # interest on top
		                       ({"price": "80.00", "paidPrice": "79.00"}, Decimal("79.00")),   # less paid
		                       ({"paidPrice": "80.00"}, Decimal("80.00")),
		                       ({"price": "", "paidPrice": None}, None),
		                       ({"price": "abc"}, None)):
			with mock.patch.object(p, "_post", return_value={**base, **answer}):
				out = p.handle_callback("PTX-2", {"token": "t"}, {}, b"", provider_ref="t")
			self.assertEqual(out.amount, amount, answer)

	def test_sipay_status_query(self):
		"""The answer shape follows Sipay's public documentation; it is not yet a recorded
		sandbox answer (certification is BLOCKED on merchant credentials), so a success
		without an amount is accepted and a stated amount is checked by ``complete``."""
		# the app id is an encrypted secret (G-83): the column only ever holds its mask
		p = turkey.SipayProvider(_Acc(secrets={"secret_key": "app-secret", "merchant_key": "MK", "api_key": "app-id"},
		                              environment="Sandbox", api_key="******"))

		def answer(status):
			def post(url, json=None, headers=None, timeout=None):
				r = mock.Mock()
				r.raise_for_status.return_value = None
				r.json.return_value = {"status_code": 100, "data": {"token": "T"}} if url.endswith("/api/token") \
					else status
				post.calls.append((url, json))
				return r
			post.calls = []
			return post

		ok = answer({"status_code": 100, "transaction_status": "Completed", "order_no": "O9", "amount": "842.50",
		             "currency_code": "EUR"})
		with mock.patch.object(turkey.requests, "post", ok):
			out = p.handle_callback("PTX-9", {}, {}, b"")
		self.assertEqual((out.status, out.provider_ref, out.amount, out.currency),
		                 ("Succeeded", "O9", Decimal("842.50"), "EUR"))
		self.assertEqual(ok.calls[0][1]["app_id"], "app-id")                  # decrypted, never the mask
		url, body = ok.calls[-1]
		self.assertTrue(url.startswith("https://provisioning.sipay.com.tr/ccpayment/api/checkstatus"))
		self.assertEqual((body["invoice_id"], body["merchant_key"]), ("PTX-9", "MK"))
		self.assertEqual(turkey.sipay_parse_hash_key(body["hash_key"], "app-secret"), ["PTX-9", "MK"])
		with mock.patch.object(turkey.requests, "post", answer({"status_code": 100, "transaction_status": "Completed"})):
			self.assertIsNone(p.handle_callback("PTX-9", {}, {}, b"").amount)
		with mock.patch.object(turkey.requests, "post", answer({"status_code": 41, "transaction_status": "Failed"})):
			self.assertEqual(p.handle_callback("PTX-9", {}, {}, b"").status, "Failed")
		with mock.patch.object(turkey.requests, "post", answer({"status_code": 1})):
			self.assertEqual(p.handle_callback("PTX-9", {}, {}, b"").status, "Pending")   # never failed on doubt
