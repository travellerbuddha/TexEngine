"""Price explanation builder.

Every pricing step records what it did, which rule won (with its precedence level)
and which rules it overrode, so the admin UI can answer "why this price?" and
"which rule won?" (PRODUCT_SPEC R-09, R-45). Messages are English templates with
parameters so the UI can localise them.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal

from kamra.tex.money import display, to_str6
from kamra.tex.pricing.model import RuleRef


@dataclass(frozen=True, slots=True)
class Step:
	stage: str
	code: str
	message: str
	params: dict
	night: str | None = None
	before: Decimal | None = None
	after: Decimal | None = None
	currency: str | None = None
	rule: RuleRef | None = None
	overridden: tuple[RuleRef, ...] = ()

	def render(self) -> str:
		values = {"currency": self.currency or "", "night": self.night or ""}
		values.update({k: display(v) for k, v in self.params.items()})
		try:
			return self.message.format(**values)
		except (KeyError, IndexError, ValueError):
			return self.message

	def to_dict(self) -> dict:
		return {
			"stage": self.stage,
			"text": self.render(),
			"code": self.code,
			"message": self.message,
			"params": {k: (to_str6(v) if isinstance(v, Decimal) else v) for k, v in self.params.items()},
			"night": self.night,
			"before": to_str6(self.before),
			"after": to_str6(self.after),
			"currency": self.currency,
			"rule": self.rule.to_dict() if self.rule else None,
			"overridden": [r.to_dict() for r in self.overridden],
		}


@dataclass
class Explanation:
	steps: list[Step] = field(default_factory=list)

	def add(self, stage: str, code: str, message: str, /, *, night=None, before=None, after=None,
	        currency=None, rule=None, overridden=(), **params) -> None:
		self.steps.append(Step(
			stage=stage, code=code, message=message, params=params,
			night=night.isoformat() if hasattr(night, "isoformat") else night,
			before=before, after=after, currency=currency, rule=rule,
			overridden=tuple(overridden),
		))

	def to_list(self) -> list[dict]:
		return [s.to_dict() for s in self.steps]

	def summary_lines(self) -> list[str]:
		"""Flat human-readable lines (used in admin tooltips and tests)."""
		return [(f"[{s.night}] " if s.night else "") + s.render() for s in self.steps]
