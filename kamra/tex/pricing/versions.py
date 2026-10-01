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
class StatusChange:
	"""One recorded change of a contract's status (``contract.status`` in the audit trail)."""

	at: datetime
	old: str | None
	new: str | None


def status_at(changes: list[StatusChange], at: datetime, current: str | None) -> str | None:
	"""A contract's status at ``at`` from its recorded status changes (G-51, ADR-054).

	A change takes effect at its time: at or after it, the last such change's new status;
	before every change, the first change's old status (the status it replaced held until
	then); no change recorded, ``current`` (it never changed). ``changes`` may come in any
	order; two at the same instant keep the order given.
	"""
	ordered = sorted(changes, key=lambda c: c.at)
	before = [c for c in ordered if c.at <= at]
	if before:
		return before[-1].new
	if ordered:
		return ordered[0].old
	return current


@dataclass(frozen=True, slots=True)
class MarketDef:
	code: str
	countries: frozenset[str]
	is_global: bool = False
	disabled: bool = False
	# sold on the web only to a guest whose country of residence or nationality is one of ``countries`` (O-8, D-5)
	residency_required: bool = False


class MarketResolutionError(Unsellable):
	pass


def resolve_market(*, explicit: str | None, country: str | None, markets: list[MarketDef],
                   allowed: set[str] | None = None, default: str | None = None) -> tuple[str, str]:
	"""→ (market code, how it was decided). Never guesses when ambiguous (R-13).

	1. an explicit market (user, campaign, call-centre, API) must exist and be enabled, and be one the
	   caller sells (``allowed``: a booking site's markets, O-8) — else ``MARKET_NOT_ALLOWED``, never
	   "unknown";
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
			if any(m.code == code and not m.disabled for m in markets):
				raise MarketResolutionError("MARKET_NOT_ALLOWED", f"market {code} is not sold here")
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


def residency_refusal(market: MarketDef, *, country: str | None, nationality: str | None) -> str | None:
	"""Why a guest may not book ``market`` (``"MARKET_RESIDENCY"``), or None (O-8, D-5, ADR-070). A residents-only
	market sells to a guest whose country of residence or nationality (ISO 3166-1 alpha-2) is one of its
	countries; any other market asks nothing. Eligibility, never a price: the frozen payload is not read."""
	if not market.residency_required:
		return None
	declared = {(c or "").strip().upper() for c in (country, nationality)} - {""}
	return None if declared & market.countries else "MARKET_RESIDENCY"
