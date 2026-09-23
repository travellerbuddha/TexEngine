"""Payment provider interface (ADR-016).

Providers never receive or return full card numbers or CVV: checkout happens on
the provider's hosted page / 3D form; TEX stores at most brand + last 4.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from decimal import Decimal


@dataclass(frozen=True)
class Intent:
	transaction: str          # TEX Payment Transaction name (also the merchant order id)
	amount: Decimal
	currency: str
	description: str
	return_url: str           # where the guest lands after the provider
	callback_url: str         # server-to-server / redirect callback
	customer: dict = field(default_factory=dict)   # name, email, phone, ip, country (no card data)
	locale: str = "en"


@dataclass(frozen=True)
class Checkout:
	kind: str                 # "redirect" | "form_post" | "instructions" | "none"
	url: str | None = None
	fields: dict = field(default_factory=dict)
	provider_ref: str | None = None
	instructions: dict = field(default_factory=dict)


@dataclass(frozen=True)
class Outcome:
	status: str               # "Succeeded" | "Failed" | "Pending" | "Cancelled"
	provider_ref: str | None = None
	amount: Decimal | None = None
	currency: str | None = None
	card_brand: str | None = None
	card_last4: str | None = None
	raw_status: str | None = None
	error_code: str | None = None
	error_message: str | None = None


class ProviderError(Exception):
	pass


class PaymentProvider(ABC):
	name: str = "base"
	supports_refund: bool = False
	production_verified: bool = False   # True only after certification against the live gateway
	# the gateway states the amount (and currency) it captured: a success without them is
	# not trusted (G-67); offline methods and the sandbox mock report nothing
	reports_amount: bool = False
	# money moves through a gateway (the sandbox mock included): in Sandbox that is test money,
	# which must never confirm a booking on a live site (ADR-041)
	gateway: bool = True
	# the only hosts a Sandbox account's gateway URL override may point at; empty for a
	# provider that never reads the override (ADR-041)
	sandbox_hosts: tuple[str, ...] = ()

	def __init__(self, account):
		self.account = account

	@property
	def sandbox(self) -> bool:
		return (self.account.get("environment") or "Sandbox") == "Sandbox"

	@abstractmethod
	def create_checkout(self, intent: Intent) -> Checkout: ...

	@abstractmethod
	def handle_callback(self, transaction: str, params: dict, headers: dict, body: bytes, *,
	                    provider_ref: str | None = None) -> Outcome:
		"""Return the outcome the gateway AUTHENTICATED for this transaction.
		Raise ProviderError when the request cannot be verified; return status
		"Pending" while the gateway has no final answer. Never return Failed for an
		unverified request — that would let anyone fail someone else's payment."""

	def refund(self, provider_ref: str, amount: Decimal, currency: str, *, reference: str | None = None) -> Outcome:
		"""Refund ``amount`` of the capture ``provider_ref``. ``reference``: TEX's id of this
		refund, sent to a gateway that keeps one with the refund (so staff can find it there).
		Raise ProviderError only for a definite "no"; any other exception means the outcome is
		unknown (the gateway may have refunded)."""
		raise ProviderError(f"{self.name} does not support refunds through TEX")

	def can_add_checkout(self, provider_ref: str | None) -> bool:
		"""Whether a Pending charge that already has checkouts may get another one (a second
		tab, a restart, G-68). By default yes: the gateway knows the charge by TEX's own id."""
		return True

	def merge_ref(self, previous: str | None, new: str | None) -> str | None:
		"""The reference to keep when a Pending charge gets another checkout. By default the
		new one: the gateway knows the charge by TEX's own id."""
		return new or previous

	def secret(self, field_name: str) -> str | None:
		try:
			return self.account.get_password(field_name, raise_exception=False)
		except Exception:
			return None
