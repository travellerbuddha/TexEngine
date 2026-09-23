"""Payment providers (ADR-016, ADR-041).

``REGISTRY`` maps the ``provider`` value of a TEX Payment Provider Account to its class. The
account controller (save time) and ``payments.service.provider_for`` (run time) read the same
class attributes from it: ``production_verified`` decides whether the provider may run in
Production, ``reports_amount`` whether a success must carry the captured amount.
"""

from __future__ import annotations

from kamra.tex.payments.providers.base import PaymentProvider
from kamra.tex.payments.providers.simple import BankTransferProvider, MockProvider, PayAtHotelProvider
from kamra.tex.payments.providers.turkey import IyzicoProvider, NestPayProvider, SipayProvider

REGISTRY: dict[str, type[PaymentProvider]] = {cls.name: cls for cls in (
	MockProvider, BankTransferProvider, PayAtHotelProvider, IyzicoProvider, SipayProvider, NestPayProvider)}


def account_problem(provider: str | None, environment: str | None, gateway_url: str | None) -> str | None:
	"""Why an account with these settings may not run, or None. Pure: the caller translates.

	- an unknown provider never runs;
	- the sandbox mock runs only in Sandbox (it would fake real money);
	- Production needs a provider certified against the live gateway;
	- a gateway URL override is for sandbox and test hosts only: in Production the live host
	  comes from the provider code, so a typo or a hostile edit cannot divert payments."""
	cls = REGISTRY.get(provider or "")
	if cls is None:
		return "unknown"
	if (environment or "Sandbox") == "Sandbox":
		return None
	if cls is MockProvider:
		return "mock"
	if not cls.production_verified:
		return "uncertified"
	if (gateway_url or "").strip():
		return "gateway_url"
	return None
