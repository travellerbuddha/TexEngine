"""TEX Connect adapter registry (R-44).

Every category has one interface; vendors plug in by key. A PMS adapter implements
``push_reservation``, ``modify_reservation``, ``cancel_reservation`` and, where the
PMS supports it, ``fetch_availability``. ``deliver`` maps outbox events onto them.
"""

from __future__ import annotations

import json
from typing import ClassVar

import requests


class Adapter:
	category = "PMS"
	key = "base"
	label = "Base adapter"
	certified = False                     # may run in Production (see the connection's validation)

	def __init__(self, connection):
		self.connection = connection
		self.settings = json.loads(connection.settings_json or "{}") if connection.get("settings_json") else {}

	def deliver(self, event: str, payload: dict, *, idempotency_key: str) -> None:
		handler = {"reservation.created": self.push_reservation, "reservation.modified": self.modify_reservation,
		           "reservation.cancelled": self.cancel_reservation}.get(event)
		if handler is None:
			raise ValueError(f"{self.key} cannot handle {event}")
		handler(payload, idempotency_key=idempotency_key)

	def push_reservation(self, payload: dict, *, idempotency_key: str) -> None:
		raise NotImplementedError

	def modify_reservation(self, payload: dict, *, idempotency_key: str) -> None:
		raise NotImplementedError

	def cancel_reservation(self, payload: dict, *, idempotency_key: str) -> None:
		raise NotImplementedError

	def fetch_availability(self, room_type: str, start, end) -> list[dict] | None:
		return None

	def test(self) -> dict:
		"""Connectivity check used by the Connect screen; raises on failure."""
		return {"adapter": self.key}


class WebhookPMS(Adapter):
	"""Generic PMS bridge: POSTs signed JSON to the PMS integration endpoint."""

	key = "webhook"
	label = "Generic PMS webhook (signed JSON)"
	certified = True                      # the hotel's own endpoint: no third-party certification involved

	def test(self) -> dict:
		self._post("ping", {"ping": True}, "ping")
		return {"adapter": self.key, "endpoint": self.connection.endpoint_url}

	def _post(self, event: str, payload: dict, idempotency_key: str) -> None:
		import hashlib
		import hmac

		url = self.connection.endpoint_url
		if not url or not url.startswith("https://"):
			raise ValueError("webhook PMS needs an https endpoint")
		body = json.dumps({"event": event, "data": payload}, sort_keys=True, default=str).encode()
		secret = self.connection.get_password("secret", raise_exception=False) or ""
		if not secret:
			raise ValueError("webhook PMS needs a signing secret")      # never sign with an empty key
		sig = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
		r = requests.post(url, data=body, timeout=15, headers={
			"Content-Type": "application/json", "X-TEX-Signature": f"sha256={sig}",
			"Idempotency-Key": idempotency_key})
		r.raise_for_status()

	def push_reservation(self, payload, *, idempotency_key):
		self._post("reservation.created", payload, idempotency_key)

	def modify_reservation(self, payload, *, idempotency_key):
		self._post("reservation.modified", payload, idempotency_key)

	def cancel_reservation(self, payload, *, idempotency_key):
		self._post("reservation.cancelled", payload, idempotency_key)


class LogOnlyPMS(Adapter):
	"""Sandbox adapter that records deliveries without calling anything."""

	key = "log"
	label = "Sandbox (records deliveries, calls nothing)"
	delivered: ClassVar[list] = []

	def push_reservation(self, payload, *, idempotency_key):
		self.delivered.append(("created", payload["reservation"]))

	def modify_reservation(self, payload, *, idempotency_key):
		self.delivered.append(("modified", payload["reservation"]))

	def cancel_reservation(self, payload, *, idempotency_key):
		self.delivered.append(("cancelled", payload["reservation"]))


REGISTRY = {cls.key: cls for cls in (WebhookPMS, LogOnlyPMS)}


def get(connection) -> Adapter:
	cls = REGISTRY.get(connection.adapter)
	if cls is None:
		raise ValueError(f"no adapter '{connection.adapter}' is installed")
	return cls(connection)
