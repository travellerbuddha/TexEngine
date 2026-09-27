"""What a rate plan's frozen payment and cancellation policies say about money (ADR-067).

Pure and deterministic: it reads the policy dicts a published payload froze (and a reservation's
pricing snapshot keeps) and never imports frappe.

* Refunds (Y-4): a price is refundable only when its rate plan row and its cancellation policy both
  say so (``refundable``).
* Fixed amounts (Y-3 A, D-1): a FIXED deposit, cancellation rule or no-show is in the policy's
  ``currency``, frozen only on a policy with a fixed amount: the policy's own, else the contract's
  (``with_currency`` is the reading default of a payload frozen before). It is converted to the
  sale's currency at the contract → sell rate the quote recorded (``fixed_in_sell``), and a fixed
  deposit is taken once per booking, on its first room carrying the policy (``first_rooms_per_policy``,
  ADR-029).
"""

from __future__ import annotations

from decimal import Decimal

from kamra.tex.money import D, quantize
from kamra.tex.pricing.model import PricingError

FIXED = "FIXED"


def refundable(row_flag: bool, cxl_policy: dict | None) -> bool:
	"""A price is refundable only when its rate plan row and its cancellation policy both say so.
	A policy that says nothing (or no policy) leaves the row's flag, as a frozen payload reads it."""
	return bool(row_flag) and (cxl_policy or {}).get("refundable", True) is not False


def has_fixed(policy: dict | None) -> bool:
	"""A frozen payment or cancellation policy with a fixed amount: a FIXED deposit, a FIXED rule or
	a FIXED no-show."""
	if not policy:
		return False
	return (policy.get("deposit_type") == FIXED or (policy.get("no_show") or {}).get("type") == FIXED
	        or any((r or {}).get("penalty_type") == FIXED for r in policy.get("rules") or ()))


def with_currency(policy: dict | None, contract_currency: str) -> dict | None:
	"""``policy`` as a payload is read: one with a fixed amount frozen without a currency (before
	ADR-067) is in the contract's currency; any other is returned as frozen, the same dict."""
	if not has_fixed(policy) or policy.get("currency"):
		return policy
	return {**policy, "currency": contract_currency.upper()}


def fixed_in_sell(amount, policy: dict | None, result: dict) -> Decimal:
	"""A fixed amount of ``policy`` in the currency ``result`` (a room's internal quote, as a
	reservation's snapshot keeps it) was sold in.

	A policy without ``currency`` was sold before it had one: the amount is kept as sold. In the
	sale's currency it is kept too. In the contract's currency it is converted at the contract → sell
	rate the quote recorded (``result["fx"]``), rounded half-up to the sale currency's minor unit.
	Any other currency cannot be converted by that rate (``POLICY_CURRENCY`` keeps it from being
	published): refused."""
	amount = D(amount)
	ccy = ((policy or {}).get("currency") or "").upper()
	sell = str(result["currency"]).upper()
	if not ccy or ccy == sell:
		return amount
	rate = result.get("fx") or {}
	if ccy != str(rate.get("from") or "").upper():
		raise PricingError(f"a fixed amount in {ccy} cannot be converted to {sell} at this quote's rate "
		                   f"({rate.get('from')} → {rate.get('to')})")
	return quantize(amount * D(rate["sell_rate"]), sell)


def first_rooms_per_policy(results: list[dict]) -> dict[str, int]:
	"""Per payment policy (by id) of the rooms of one booking (their internal quotes), the position
	in ``results`` of the room that takes its fixed deposit: the booking's first room (room index 0)
	when it carries the policy, else the lowest room index that does."""
	best: dict[str, tuple[int, int]] = {}
	for pos, r in enumerate(results):
		policy = (r.get("rate_plan") or {}).get("payment_policy")
		if not policy:
			continue
		key = str(policy.get("id") or policy.get("name") or "")
		rank = (int((r.get("request") or {}).get("room_index") or 0), pos)
		if key not in best or rank < best[key]:
			best[key] = rank
	return {key: pos for key, (_index, pos) in best.items()}
