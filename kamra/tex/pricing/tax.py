"""TaxResolver.

Data-driven tax rules per line category (``ACCOMMODATION``, ``EXTRA:<category>``,
``EXTRA:*``). Percentage taxes may be compound (computed on base + earlier taxes).

* Exclusive prices: taxes are added on top of the (rounded) net amount.
* Inclusive prices: the gross amount is fixed; net = gross / factor, each tax is
  rounded, and net is taken as gross − Σ rounded taxes so the lines always add up.
* Fixed per-person-night / per-room-night taxes (city/accommodation levies) are
  always charged on top.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from kamra.tex.money import HUNDRED, ONE, ZERO, D, quantize, to_str
from kamra.tex.pricing.enums import TaxKind
from kamra.tex.pricing.model import TaxRule


@dataclass(frozen=True, slots=True)
class TaxLine:
	code: str
	name: str
	category: str
	base: Decimal
	rate: Decimal | None
	amount: Decimal
	included: bool

	def to_dict(self) -> dict:
		return {"code": self.code, "name": self.name, "category": self.category, "base": to_str(self.base),
		        "rate": to_str(self.rate), "amount": to_str(self.amount), "included": self.included}


def _applies(rule: TaxRule, category: str) -> bool:
	if category in rule.applies_to:
		return True
	return category.startswith("EXTRA:") and "EXTRA:*" in rule.applies_to


def _percent_rules(rules: tuple[TaxRule, ...], category: str) -> list[TaxRule]:
	return sorted((r for r in rules if r.kind == TaxKind.PERCENT and _applies(r, category)),
	              key=lambda r: (r.order, r.code))


def rate_for(rule: TaxRule, nightly: Decimal | None) -> Decimal:
	"""The rule's rate; slabbed rules pick the rate by the nightly tariff."""
	if not rule.slabs or nightly is None:
		return D(rule.rate)
	for threshold, rate in rule.slabs:
		if threshold is None or nightly <= D(threshold):
			return D(rate)
	return D(rule.slabs[-1][1])


def _stack(rules: list[TaxRule], net: Decimal, nightly: Decimal | None = None) -> list[tuple[TaxRule, Decimal]]:
	out: list[tuple[TaxRule, Decimal]] = []
	running = ZERO
	for r in rules:
		base = net + running if r.compound else net
		t = base * rate_for(r, nightly) / HUNDRED
		out.append((r, t))
		running += t
	return out


def compute_taxes(rules: tuple[TaxRule, ...], categories: dict[str, Decimal], *, inclusive: bool,
                  currency: str, persons: int, nights: int) -> tuple[list[TaxLine], dict[str, Decimal]]:
	"""→ (tax lines, net amount per category). Category amounts are already rounded;
	they are gross when ``inclusive`` else net."""
	lines: list[TaxLine] = []
	nets: dict[str, Decimal] = {}
	for category in sorted(categories):
		amount = D(categories[category])
		prules = _percent_rules(rules, category)
		if not prules:
			nets[category] = amount
			continue
		nightly = amount / max(nights, 1) if category == "ACCOMMODATION" else None
		if inclusive:
			factor = ONE + sum((t for _, t in _stack(prules, ONE, nightly)), ZERO)
			net_exact = amount / factor
			taxes = [(r, quantize(t, currency)) for r, t in _stack(prules, net_exact, nightly)]
			net = amount - sum((t for _, t in taxes), ZERO)
		else:
			net = amount
			taxes = [(r, quantize(t, currency)) for r, t in _stack(prules, net, nightly)]
		nets[category] = net
		for r, t in taxes:
			lines.append(TaxLine(r.code, r.name, category, net, rate_for(r, nightly), t, inclusive))

	accommodation = "ACCOMMODATION" in categories
	for r in sorted((r for r in rules if r.kind != TaxKind.PERCENT), key=lambda r: (r.order, r.code)):
		if not accommodation or not _applies(r, "ACCOMMODATION"):
			continue
		n = max(nights, 1)
		qty = persons * n if r.kind == TaxKind.PER_PERSON_NIGHT else n
		amt = quantize(D(r.amount) * qty, currency)
		if amt:
			lines.append(TaxLine(r.code, r.name, "ACCOMMODATION", D(qty), None, amt, False))
	return lines, nets
