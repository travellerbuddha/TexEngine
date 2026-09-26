"""What a rate plan's frozen payment and cancellation policies say about money (ADR-067).

Pure and deterministic: it reads the policy dicts a published payload froze (and a reservation's
pricing snapshot keeps) and never imports frappe.
"""

from __future__ import annotations


def refundable(row_flag: bool, cxl_policy: dict | None) -> bool:
	"""A price is refundable only when its rate plan row and its cancellation policy both say so.
	A policy that says nothing (or no policy) leaves the row's flag, as a frozen payload reads it."""
	return bool(row_flag) and (cxl_policy or {}).get("refundable", True) is not False
