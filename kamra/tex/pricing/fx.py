"""CurrencyResolver (R-15).

A rate always means ``1 from_currency = rate to_currency``. Selling-rate modes:

* MANUAL            sell = manual rate
* PROVIDER          sell = provider rate
* PROVIDER_PERCENT  sell = provider × (1 + adj/100)   e.g. EURTRY 50, +2 % → 51
* PROVIDER_FIXED    sell = provider + adj             e.g. EURTRY 50 + 1.50 → 51.50

Provider rates may be direct (EUR→TRY), inverse (TRY→EUR) or crossed through a
pivot (GBP→EUR via TRY with TCMB, via EUR with ECB). Conversion without an explicit
policy is refused - money is never converted with a silently assumed rate.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal

from kamra.tex.money import ONE, D, pct, quantize_rate
from kamra.tex.pricing.enums import FxMode
from kamra.tex.pricing.model import FxSnapshot, Unsellable


@dataclass(frozen=True, slots=True)
class FxPolicy:
	policy_id: str
	from_currency: str
	to_currency: str
	mode: FxMode
	manual_rate: Decimal | None = None
	provider: str | None = None
	rate_type: str = "FOREX_SELLING"
	adjustment: Decimal | None = None
	max_age_days: int = 4


@dataclass(frozen=True, slots=True)
class ProviderRate:
	rate_id: str
	provider: str
	base: str
	quote: str
	rate: Decimal
	rate_date: date
	rate_type: str = "FOREX_SELLING"


def _latest(rates: list[ProviderRate], base: str, quote: str, on: date) -> ProviderRate | None:
	cands = [r for r in rates if r.base == base and r.quote == quote and r.rate_date <= on]
	return max(cands, key=lambda r: (r.rate_date, r.rate_id)) if cands else None


def provider_rate(rates: tuple[ProviderRate, ...], provider: str, rate_type: str,
                  frm: str, to: str, on: date) -> tuple[Decimal, str, date]:
	pool = [r for r in rates if r.provider == provider and r.rate_type == rate_type and r.rate > 0]
	direct = _latest(pool, frm, to, on)
	if direct:
		return D(direct.rate), direct.rate_id, direct.rate_date
	inverse = _latest(pool, to, frm, on)
	if inverse:
		return ONE / D(inverse.rate), f"1/{inverse.rate_id}", inverse.rate_date
	pivots = sorted({r.quote for r in pool if r.base == frm} & {r.quote for r in pool if r.base == to})
	for p in pivots:
		a, b = _latest(pool, frm, p, on), _latest(pool, to, p, on)
		if a and b:
			return D(a.rate) / D(b.rate), f"{a.rate_id}/{b.rate_id}", min(a.rate_date, b.rate_date)
	pivots = sorted({r.base for r in pool if r.quote == frm} & {r.base for r in pool if r.quote == to})
	for p in pivots:
		a, b = _latest(pool, p, frm, on), _latest(pool, p, to, on)
		if a and b:
			return D(b.rate) / D(a.rate), f"{b.rate_id}/{a.rate_id}", min(a.rate_date, b.rate_date)
	raise Unsellable("FX_RATE_MISSING", f"no {provider} rate for {frm}→{to} on or before {on.isoformat()}",
	                 from_currency=frm, to_currency=to)


def identity(currency: str, as_of: datetime | None = None) -> FxSnapshot:
	return FxSnapshot(currency, currency, FxMode.IDENTITY, ONE, as_of=as_of)


def resolve_fx(frm: str, to: str, policy: FxPolicy | None, rates: tuple[ProviderRate, ...],
               as_of: datetime) -> FxSnapshot:
	frm, to = frm.upper(), to.upper()
	if frm == to:
		return identity(frm, as_of)
	if policy is None:
		raise Unsellable("NO_FX_POLICY", f"no FX policy converts {frm} to {to}",
		                 from_currency=frm, to_currency=to)
	if policy.mode == FxMode.MANUAL:
		if not policy.manual_rate or D(policy.manual_rate) <= 0:
			raise Unsellable("FX_MANUAL_RATE_MISSING", f"manual FX policy {policy.policy_id} has no rate")
		return FxSnapshot(frm, to, FxMode.MANUAL, quantize_rate(policy.manual_rate), policy_id=policy.policy_id,
		                  as_of=as_of)
	if not policy.provider:
		raise Unsellable("FX_PROVIDER_MISSING", f"FX policy {policy.policy_id} names no provider")
	on = as_of.date()
	raw, rate_id, rate_date = provider_rate(rates, policy.provider, policy.rate_type, frm, to, on)
	if (on - rate_date).days > policy.max_age_days:
		raise Unsellable("FX_RATE_STALE", f"latest {policy.provider} {frm}→{to} rate is from "
		                 f"{rate_date.isoformat()}, older than {policy.max_age_days} days")
	adj = D(policy.adjustment)
	if policy.mode == FxMode.PROVIDER:
		sell = raw
	elif policy.mode == FxMode.PROVIDER_PERCENT:
		sell = raw * (ONE + pct(adj))
	elif policy.mode == FxMode.PROVIDER_FIXED:
		sell = raw + adj
	else:
		raise Unsellable("FX_MODE_UNSUPPORTED", f"unsupported FX mode {policy.mode}")
	if sell <= 0:
		raise Unsellable("FX_RATE_INVALID", "FX policy produces a non-positive rate")
	return FxSnapshot(frm, to, policy.mode, quantize_rate(sell), provider=policy.provider,
	                  provider_rate=quantize_rate(raw), provider_rate_id=rate_id, rate_date=rate_date,
	                  adjustment=adj if policy.mode != FxMode.PROVIDER else None,
	                  policy_id=policy.policy_id, as_of=as_of)


def convert(amount: Decimal, fx: FxSnapshot) -> Decimal:
	"""Full-precision conversion; rounding happens at line level."""
	return D(amount) * fx.sell_rate
