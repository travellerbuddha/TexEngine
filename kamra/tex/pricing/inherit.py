"""Pricing-policy cascade (G-30, ADR-043). Pure: no frappe.

A contract version inherits from EVERY live pricing policy that applies to its hotel
and market, not only the most specific one:

    scope         weight   level     explanation source
    global          0      GLOBAL    policy:<id>/r<rev>/global
    hotel           1      HOTEL     policy:<id>/r<rev>/hotel
    market          2      MARKET    policy:<id>/r<rev>/market
    hotel + market  3      MARKET    policy:<id>/r<rev>/hotel+market

The weight is a bit set (hotel 1 | market 2), as in ``markup.weight``, so a market
policy outranks a hotel one (PRODUCT_SPEC R-09: GLOBAL < HOTEL < MARKET) and hotel +
market outranks both. Every inherited rule keeps its origin (``base_level``,
``scope_weight``, ``source``); ``occupancy.specificity`` ranks origin before qualifiers,
so a contract version rule beats any policy rule and rules cascade by band code: an
INHERIT rule passes to the next policy's rule for the same slot.

Age bands are REPLACED, never merged: the version's bands if it has any, else the band
set of the most specific policy that defines one. Two policies of one scope are never
ranked by guesswork: ``cascade`` refuses them.
"""

from __future__ import annotations

from dataclasses import dataclass, replace

from kamra.tex.pricing.enums import Level
from kamra.tex.pricing.model import AgeBand, OccupancyRule, PricingError

HOTEL_BIT, MARKET_BIT = 1, 2
_LABELS = {0: "global", HOTEL_BIT: "hotel", MARKET_BIT: "market", HOTEL_BIT | MARKET_BIT: "hotel+market"}


def weight_of(property: str | None, market: str | None) -> int:
	return (HOTEL_BIT if property else 0) | (MARKET_BIT if market else 0)


def level_for(weight: int) -> Level:
	return Level.MARKET if weight & MARKET_BIT else Level.HOTEL if weight & HOTEL_BIT else Level.GLOBAL


def scope_label(weight: int) -> str:
	return _LABELS[weight]


@dataclass(frozen=True, slots=True)
class PolicyLayer:
	"""One live pricing policy (a revision) that applies to the contract."""

	policy_id: str
	revision: int
	property: str | None
	market: str | None
	bands: tuple[AgeBand, ...] = ()
	rules: tuple[OccupancyRule, ...] = ()

	@property
	def weight(self) -> int:
		return weight_of(self.property, self.market)

	@property
	def level(self) -> Level:
		return level_for(self.weight)

	@property
	def source(self) -> str:
		return f"policy:{self.policy_id}/r{self.revision}/{scope_label(self.weight)}"

	def scoped_rules(self) -> tuple[OccupancyRule, ...]:
		"""The policy's rules stamped with its origin."""
		return tuple(replace(r, base_level=self.level, scope_weight=self.weight, source=self.source)
		             for r in self.rules)


class PolicyAmbiguous(PricingError):
	"""Two live pricing policies share one scope (hotel, market): nothing ranks them."""

	code = "PRICING_POLICY_AMBIGUOUS"


def _ordered(layers) -> list[PolicyLayer]:
	"""Most specific policy first."""
	return sorted(layers, key=lambda x: (-x.weight, x.policy_id))


def band_layer(layers) -> PolicyLayer | None:
	"""The policy whose age bands a contract without bands of its own takes: the most specific
	one that defines bands (None: no policy does)."""
	return next((x for x in _ordered(layers) if x.bands), None)


def cascade(version_bands: tuple[AgeBand, ...], version_rules: tuple[OccupancyRule, ...],
            layers) -> tuple[tuple[AgeBand, ...], tuple[OccupancyRule, ...]]:
	"""→ (age bands, occupancy rules) of a contract: the version's rules first, then every
	policy's rules, most specific policy first."""
	ordered = _ordered(layers)
	seen: dict[int, PolicyLayer] = {}
	for layer in ordered:
		other = seen.get(layer.weight)
		if other is not None:
			raise PolicyAmbiguous(
				f"pricing policies {other.policy_id} and {layer.policy_id} both apply to the "
				f"{scope_label(layer.weight)} scope ({layer.property or '*'} / {layer.market or '*'}); "
				"archive one of them")
		seen[layer.weight] = layer
	inherited = band_layer(ordered)
	bands = tuple(version_bands) or (tuple(inherited.bands) if inherited else ())
	rules = tuple(version_rules) + tuple(r for x in ordered for r in x.scoped_rules())
	return bands, rules
