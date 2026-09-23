"""Channel-manager adapters (G-69, ADR-039).

One interface for every channel manager: TEX builds provider-neutral ARI runs and reads
provider-neutral reservations; an adapter only translates and transports. Only adapters
in ``REGISTRY`` can be selected, and an adapter whose ``certified`` is False can only be
used in the Sandbox environment (the connection refuses Production).

Real providers (Channex, SiteMinder, RateGain, …) are NOT implemented here: without their
credentials and certification TEX does not pretend to talk to them. Adding one means
subclassing ``ChannelAdapter``, translating to its documented API, passing its
certification, and only then setting ``certified = True``.
"""

from __future__ import annotations

import json
import time

from kamra.tex.distribution import signing
from kamra.tex.distribution.model import (
	AriRun,
	ChannelGuest,
	ChannelReservation,
	ChannelRoom,
	PushResult,
)


class AdapterError(Exception):
	"""A delivery failed. ``retryable``: False for a payload the channel rejects as is."""

	def __init__(self, message: str, *, retryable: bool = True):
		super().__init__(message)
		self.retryable = retryable


class ChannelAdapter:
	key = "base"
	label = "Channel manager"
	certified = False                     # True only after the provider's certification

	def __init__(self, connection, secret: str | None = None, api_key: str | None = None):
		self.connection = connection
		self.secret = secret
		self.api_key = api_key
		self.settings = json.loads(connection.get("settings_json") or "{}") if connection.get("settings_json") else {}

	# outbound
	def push_ari(self, runs: list[AriRun]) -> PushResult:
		raise NotImplementedError

	# inbound
	def verify_webhook(self, headers: dict, body: bytes, now: int) -> None:
		"""Raise ``signing.SignatureError`` unless the request is authentic (fail closed)."""
		signing.verify(self.secret, headers.get("X-TEX-Timestamp"), headers.get("X-TEX-Signature"), body, now)

	def parse_webhook(self, body: bytes) -> list[ChannelReservation]:
		raise NotImplementedError

	def fetch_reservations(self, since) -> list[ChannelReservation] | None:
		"""The channel's current view of its bookings, for reconciliation. None: the provider
		cannot be asked; reconciliation then compares with the inbound log."""
		return None

	def test(self) -> dict:
		return {"adapter": self.key, "certified": self.certified}


def _date(v):
	from datetime import date

	return date.fromisoformat(str(v)[:10])


def parse_neutral(data: dict) -> ChannelReservation:
	"""TEX's own provider-neutral booking message (the sandbox's wire format)."""
	from decimal import Decimal, InvalidOperation

	status = str(data.get("status") or "").lower()
	if status not in ChannelReservation.STATUSES:
		raise AdapterError(f"unknown booking status {status!r}", retryable=False)
	ref = str(data.get("provider_ref") or "").strip()
	if not ref or len(ref) > 140:
		raise AdapterError("a booking id is required", retryable=False)
	rooms = []
	for i, r in enumerate(data.get("rooms") or []):
		try:
			total = Decimal(str(r.get("total") or "0"))
		except InvalidOperation:
			raise AdapterError(f"room {i + 1}: total is not a number", retryable=False) from None
		try:
			ci, co = _date(r["check_in"]), _date(r["check_out"])
			adults = int(r.get("adults") or 0)
			kids = tuple(int(a) for a in r.get("children_ages") or [])
		except (KeyError, ValueError, TypeError):
			raise AdapterError(f"room {i + 1}: dates, adults or ages are invalid", retryable=False) from None
		if co <= ci or adults < 1 or total < 0 or not total.is_finite():
			raise AdapterError(f"room {i + 1}: stay, adults or total is invalid", retryable=False)
		rooms.append(ChannelRoom(str(r.get("room_code") or ""), str(r.get("rate_code") or ""), ci, co, adults, kids,
		                         total, str(r.get("currency") or "").upper(), str(r.get("line_ref") or i + 1)))
	if status != "cancelled" and not rooms:
		raise AdapterError("a booking needs at least one room", retryable=False)
	g = data.get("guest") or {}
	guest = ChannelGuest(str(g.get("first_name") or "").strip()[:140], str(g.get("last_name") or "").strip()[:140],
	                     (g.get("email") or None), (g.get("phone") or None), (g.get("country") or None)) if g else None
	return ChannelReservation(ref, status, tuple(rooms), guest, str(data.get("channel_name") or "")[:140],
	                          str(data.get("notes") or "")[:2000], str(data.get("version") or ""))


class SandboxChannel(ChannelAdapter):
	"""A channel manager that exists only inside TEX: it accepts ARI pushes (optionally
	rejecting or failing them, from the connection's settings, to exercise the error
	queue) and receives bookings in TEX's neutral format, signed with the connection's
	secret. For trying the whole flow, demos and tests — never for real distribution."""

	key = "sandbox_channel"
	label = "Sandbox channel manager (no real channel)"
	certified = False

	def push_ari(self, runs: list[AriRun]) -> PushResult:
		mode = self.settings.get("push")                    # None | "fail" | "reject"
		if mode == "fail":
			raise AdapterError("sandbox: the channel is unreachable (simulated)")
		if mode == "reject":
			raise AdapterError("sandbox: the channel rejected the update (simulated)", retryable=False)
		unknown = set(self.settings.get("unknown_rooms") or [])
		bad = [r for r in runs if r.room_code in unknown]
		if bad:
			raise AdapterError(f"sandbox: unknown room {bad[0].room_code}", retryable=False)
		return PushResult(True, accepted=len(runs), message="accepted by the sandbox",
		                  provider_ref=f"SBX-{int(time.time())}")

	def parse_webhook(self, body: bytes) -> list[ChannelReservation]:
		try:
			data = json.loads(body or b"{}")
		except ValueError:
			raise AdapterError("the body is not JSON", retryable=False) from None
		items = data if isinstance(data, list) else [data]
		return [parse_neutral(x) for x in items]

	def fetch_reservations(self, since) -> list[ChannelReservation] | None:
		return None


REGISTRY: dict[str, type[ChannelAdapter]] = {cls.key: cls for cls in (SandboxChannel,)}
