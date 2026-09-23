"""Webhook signatures (G-69). Pure — no frappe import.

TEX's own scheme for the sandbox channel and any provider without one:
``X-TEX-Timestamp: <unix seconds>`` and ``X-TEX-Signature: sha256=<hex HMAC of
"<timestamp>.<body>">`` with the connection's secret. Verification fails closed: no
secret, no header, a stale timestamp or a wrong MAC all refuse.
"""

from __future__ import annotations

import hashlib
import hmac

TOLERANCE_SECONDS = 300


class SignatureError(Exception):
	pass


def sign(secret: str, timestamp: int, body: bytes) -> str:
	if not secret:
		raise SignatureError("no secret")
	mac = hmac.new(secret.encode(), str(int(timestamp)).encode() + b"." + body, hashlib.sha256).hexdigest()
	return f"sha256={mac}"


def verify(secret: str | None, timestamp: str | None, signature: str | None, body: bytes, now: int) -> None:
	if not secret:
		raise SignatureError("the connection has no webhook secret")
	if not timestamp or not signature:
		raise SignatureError("missing signature")
	try:
		ts = int(timestamp)
	except ValueError:
		raise SignatureError("bad timestamp") from None
	if abs(now - ts) > TOLERANCE_SECONDS:
		raise SignatureError("stale or future timestamp")
	if not hmac.compare_digest(sign(secret, ts, body), signature.strip()):
		raise SignatureError("signature mismatch")
