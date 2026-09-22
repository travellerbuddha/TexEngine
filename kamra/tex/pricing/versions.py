"""ContractVersionResolver and MarketResolver (pure)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from kamra.tex.pricing.model import Unsellable

SELLABLE_HISTORY = ("Published", "Superseded", "Withdrawn")


@dataclass(frozen=True, slots=True)
class VersionHeader:
	version_id: str
	version_no: int
	status: str                    # Draft / Published / Superseded / Withdrawn
	effective_from: datetime | None
	active_to: datetime | None = None   # superseded_at or withdrawn_at


def active_version(headers: list[VersionHeader], at: datetime) -> VersionHeader | None:
	"""The version that was (or is) on sale at ``at``.

	A version is on sale from ``effective_from`` until ``active_to`` (the moment it
	was superseded or withdrawn). Drafts never sell. Ties (two versions with the same
	effective time) resolve to the higher version number.
	"""
	cands = [h for h in headers
	         if h.status in SELLABLE_HISTORY and h.effective_from is not None and h.effective_from <= at
	         and (h.active_to is None or h.active_to > at)]
	if not cands:
		return None
	return max(cands, key=lambda h: (h.effective_from, h.version_no))


@dataclass(frozen=True, slots=True)
class MarketDef:
	code: str
	countries: frozenset[str]
	is_global: bool = False
	disabled: bool = False


class MarketResolutionError(Unsellable):
	pass


def resolve_market(*, explicit: str | None, country: str | None, markets: list[MarketDef],
                   allowed: set[str] | None = None, default: str | None = None) -> tuple[str, str]:
	"""→ (market code, how it was decided). Never guesses when ambiguous (R-13).

	1. an explicit market (user, campaign, call-centre, API) must exist and be enabled;
	2. else the guest's country maps to the market with the smallest country list
	   containing it (DE → "DE" before "DACH" before "EU"); two equally specific
	   candidates are ambiguous → error, the caller must ask;
	3. else the configured default market (business rule) if any;
	4. else error — the market must be chosen explicitly.
	"""
	live = {m.code: m for m in markets if not m.disabled and (allowed is None or m.code in allowed)}
	if explicit:
		code = explicit.strip().upper()
		if code not in live:
			raise MarketResolutionError("MARKET_UNKNOWN", f"market {code} is not available")
		return code, "explicit"
	if country:
		cc = country.strip().upper()
		cands = [m for m in live.values() if not m.is_global and cc in m.countries]
		if cands:
			size = min(len(m.countries) for m in cands)
			best = sorted(m.code for m in cands if len(m.countries) == size)
			if len(best) > 1:
				raise MarketResolutionError("MARKET_AMBIGUOUS",
				                            f"country {cc} belongs to markets {', '.join(best)}; choose one",
				                            candidates=best)
			return best[0], f"country:{cc}"
	if default:
		code = default.strip().upper()
		if code in live:
			return code, "default"
	raise MarketResolutionError("MARKET_REQUIRED", "the market could not be determined; choose one explicitly")
