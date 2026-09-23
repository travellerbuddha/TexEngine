"""Payment providers (ADR-016, ADR-041).

``REGISTRY`` maps the ``provider`` value of a TEX Payment Provider Account to its class. The
account controller (save time) and ``payments.service.provider_for`` (run time) read the same
class attributes from it: ``production_verified`` decides whether the provider may run in
Production, ``reports_amount`` whether a success must carry the captured amount, ``gateway``
whether it moves money through a gateway, ``sandbox_hosts`` where a Sandbox override may go.
"""

from __future__ import annotations

from urllib.parse import urlparse

from kamra.tex.payments.providers.base import PaymentProvider
from kamra.tex.payments.providers.simple import BankTransferProvider, MockProvider, PayAtHotelProvider
from kamra.tex.payments.providers.turkey import IyzicoProvider, NestPayProvider, SipayProvider

REGISTRY: dict[str, type[PaymentProvider]] = {cls.name: cls for cls in (
	MockProvider, BankTransferProvider, PayAtHotelProvider, IyzicoProvider, SipayProvider, NestPayProvider)}


LOCAL_HOSTS = ("localhost", "127.0.0.1", "::1")


def sandbox_host_ok(cls: type[PaymentProvider], url: str, *, developer_mode: bool = False) -> bool:
	"""A Sandbox gateway URL override goes to one of the provider's own sandbox hosts over
	https, or to this machine in developer mode. Anything else could be the live gateway."""
	try:
		u = urlparse(url)
		host = (u.hostname or "").lower()
		u.port                                   # a malformed port raises ValueError
	except ValueError:
		return False
	if developer_mode and host in LOCAL_HOSTS:
		return u.scheme in ("http", "https")
	return u.scheme == "https" and host in cls.sandbox_hosts


def account_problem(provider: str | None, environment: str | None, gateway_url: str | None, *,
                    live_site: bool = False, developer_mode: bool = False, settling: bool = False) -> str | None:
	"""Why an account with these settings may not run, or None. Pure: the caller translates.

	- an unknown provider never runs;
	- Sandbox moves test money: on a live site (``tex_production``) no sandbox gateway runs,
	  the mock included, since its "payments" would confirm real bookings; and a gateway URL
	  override must be one of the provider's own sandbox hosts (https), or a Sandbox account
	  could take real money through a live, uncertified gateway;
	- the sandbox mock never runs in Production (it would fake real money);
	- Production needs a provider certified against the live gateway, except to *settle*
	  money a gateway already holds (``settling``: record a capture, re-verify, refund);
	- a Production account takes no gateway URL override: the live host comes from the
	  provider code, so a typo or a hostile edit cannot divert payments."""
	cls = REGISTRY.get(provider or "")
	if cls is None:
		return "unknown"
	override = (gateway_url or "").strip()
	if (environment or "Sandbox") == "Sandbox":
		if live_site and cls.gateway:
			return "sandbox_live_site"
		if override and cls.sandbox_hosts and not sandbox_host_ok(cls, override, developer_mode=developer_mode):
			return "sandbox_host"
		return None
	if cls is MockProvider:
		return "mock"
	if not cls.production_verified and not settling:
		return "uncertified"
	if override:
		return "gateway_url"
	return None
