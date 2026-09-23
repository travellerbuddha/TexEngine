"""Mock (sandbox), bank transfer and pay-at-hotel providers."""

from __future__ import annotations

import hashlib
import hmac
from decimal import Decimal

from kamra.tex.payments.providers.base import Checkout, Intent, Outcome, PaymentProvider, ProviderError


def mock_signature(secret: str, transaction: str, outcome: str) -> str:
	return hmac.new(secret.encode(), f"{transaction}|{outcome}".encode(), hashlib.sha256).hexdigest()


class MockProvider(PaymentProvider):
	"""Deterministic sandbox gateway for tests, demos and the E2E journey. It can
	never run against a Production account (it would fake real money)."""

	name = "Mock"
	supports_refund = True

	def __init__(self, account, secret: str):
		super().__init__(account)
		if not self.sandbox:
			raise ProviderError("The mock provider only runs in Sandbox.")
		self._secret = secret

	def create_checkout(self, intent: Intent) -> Checkout:
		return Checkout(kind="redirect", url=f"/book/pay/mock/{intent.transaction}",
		                provider_ref=f"MOCK-{intent.transaction}",
		                fields={"success_sig": mock_signature(self._secret, intent.transaction, "success"),
		                        "fail_sig": mock_signature(self._secret, intent.transaction, "fail")})

	def handle_callback(self, transaction: str, params: dict, headers: dict, body: bytes, *,
	                    provider_ref: str | None = None) -> Outcome:
		outcome = params.get("outcome")
		if outcome not in ("success", "fail"):
			raise ProviderError("unknown mock outcome")
		expected = mock_signature(self._secret, transaction, outcome)
		if not hmac.compare_digest(expected, str(params.get("sig") or "")):
			raise ProviderError("invalid mock signature")
		if outcome == "fail":
			return Outcome(status="Failed", provider_ref=f"MOCK-{transaction}", raw_status="DECLINED",
			               error_code="DECLINED", error_message="Test card declined")
		return Outcome(status="Succeeded", provider_ref=f"MOCK-{transaction}", raw_status="APPROVED",
		               card_brand="TESTCARD", card_last4="4242")

	def refund(self, provider_ref: str, amount: Decimal, currency: str) -> Outcome:
		return Outcome(status="Succeeded", provider_ref=f"{provider_ref}-R", amount=amount, currency=currency,
		               raw_status="REFUNDED")


class BankTransferProvider(PaymentProvider):
	name = "Bank Transfer"
	# no gateway: TEX only shows the hotel's bank details and staff confirm the money
	# received, so there is nothing to certify before Production
	production_verified = True
	gateway = False

	def create_checkout(self, intent: Intent) -> Checkout:
		a = self.account
		return Checkout(kind="instructions", provider_ref=intent.transaction, instructions={
			"bank": a.get("bank_name"), "iban": a.get("iban"), "account_holder": a.get("account_holder"),
			"reference": intent.transaction, "amount": str(intent.amount), "currency": intent.currency,
			"note": a.get("transfer_instructions") or ""})

	def handle_callback(self, transaction: str, params: dict, headers: dict, body: bytes, *,
	                    provider_ref: str | None = None) -> Outcome:
		raise ProviderError("Bank transfers are confirmed by staff, not by a callback.")


class PayAtHotelProvider(PaymentProvider):
	name = "Pay at Hotel"
	production_verified = True          # no gateway and no money moves through TEX
	gateway = False

	def create_checkout(self, intent: Intent) -> Checkout:
		return Checkout(kind="none")

	def handle_callback(self, transaction: str, params: dict, headers: dict, body: bytes, *,
	                    provider_ref: str | None = None) -> Outcome:
		raise ProviderError("Pay at hotel has no callback.")
