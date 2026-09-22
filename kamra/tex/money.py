"""Money primitives for TEX Engine.

Every monetary value in TEX code is a :class:`decimal.Decimal`. Binary floats are
never used for money (ADR-003). Intermediate results keep full precision; values are
rounded once, to the currency's minor unit, when they become an output line.

This module must not import frappe.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Context, Decimal, InvalidOperation, localcontext

# ISO 4217 minor units for currencies TEX sells in or is likely to meet. Anything
# missing defaults to 2, which is right for the vast majority of currencies.
MINOR_UNITS: dict[str, int] = {
	"TRY": 2, "EUR": 2, "GBP": 2, "USD": 2, "CHF": 2, "RUB": 2, "RON": 2, "PLN": 2,
	"SEK": 2, "NOK": 2, "DKK": 2, "CZK": 2, "HUF": 2, "AED": 2, "SAR": 2, "INR": 2,
	"THB": 2, "MYR": 2, "IDR": 2, "VND": 0, "JPY": 0, "KRW": 0, "KWD": 3, "BHD": 3,
	"OMR": 3, "JOD": 3, "TND": 3,
}

ZERO = Decimal("0")
ONE = Decimal("1")
HUNDRED = Decimal("100")

# Precision for intermediate arithmetic: far beyond what any hotel price needs, so
# products of rates, multipliers and FX never lose significant digits.
_CTX = Context(prec=34, rounding=ROUND_HALF_UP)

FX_PLACES = 6


def D(value) -> Decimal:
	"""Parse a value into Decimal without ever passing through binary float math.

	Floats are converted via ``str()`` (shortest repr) so ``0.1`` becomes
	``Decimal('0.1')``, not ``0.1000000000000000055…``. ``None`` and ``""`` are zero.
	"""
	if value is None or value == "":
		return ZERO
	if isinstance(value, Decimal):
		return value
	if isinstance(value, bool):
		raise TypeError("bool is not a monetary value")
	if isinstance(value, int):
		return Decimal(value)
	if isinstance(value, float):
		return Decimal(repr(value))
	try:
		return Decimal(str(value).strip())
	except InvalidOperation as e:
		raise ValueError(f"not a decimal value: {value!r}") from e


def D_or_none(value) -> Decimal | None:
	if value is None or value == "":
		return None
	return D(value)


def minor_units(currency: str) -> int:
	return MINOR_UNITS.get((currency or "").upper(), 2)


def quantum(currency: str) -> Decimal:
	return Decimal(1).scaleb(-minor_units(currency))


def quantize(amount: Decimal, currency: str) -> Decimal:
	"""Round to the currency's minor unit, half-up (commercial rounding)."""
	return D(amount).quantize(quantum(currency), rounding=ROUND_HALF_UP)


def quantize_rate(rate: Decimal, places: int = FX_PLACES) -> Decimal:
	return D(rate).quantize(Decimal(1).scaleb(-places), rounding=ROUND_HALF_UP)


def from_db(value, currency: str) -> Decimal:
	"""Read a DB Currency value (which frappe may hand back as float) as money."""
	return quantize(D(value), currency)


def to_str(amount: Decimal | None) -> str | None:
	"""Serialise money for JSON/API: a plain decimal string, never a float."""
	if amount is None:
		return None
	d = D(amount)
	# normalise "-0.00" to "0.00"
	if d == 0:
		d = abs(d)
	return format(d, "f")


def to_str6(value: Decimal | None) -> str | None:
	"""Canonical full-precision serialisation (fixed 6 dp) — byte-stable regardless of
	the Decimal's internal exponent, so snapshots re-price to identical JSON."""
	if value is None:
		return None
	return to_str(quantize_rate(D(value), FX_PLACES))


def display(v):
	"""Human display of a Decimal with 2–4 decimals ("1.20", "120.00", "52.965"),
	independent of the Decimal's internal exponent. Non-decimals pass through."""
	if not isinstance(v, Decimal):
		return v
	q = format(v.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP), "f")
	whole, _, frac = q.partition(".")
	return f"{whole}.{frac.rstrip('0').ljust(2, '0')}"


def display_pct(v) -> str:
	"""Percent display: "10", "7.5" — no forced decimals."""
	q = format(D(v).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP), "f")
	return q.rstrip("0").rstrip(".") if "." in q else q


def calc():
	"""Context manager giving the high-precision arithmetic context."""
	return localcontext(_CTX)


def pct(value: Decimal) -> Decimal:
	"""Percentage number → factor (15 → 0.15)."""
	return D(value) / HUNDRED


@dataclass(frozen=True, slots=True)
class Money:
	amount: Decimal
	currency: str

	def __post_init__(self):
		object.__setattr__(self, "amount", D(self.amount))
		object.__setattr__(self, "currency", (self.currency or "").upper())

	def _same(self, other: Money):
		if not isinstance(other, Money) or other.currency != self.currency:
			raise ValueError(f"currency mismatch: {self.currency} vs {getattr(other, 'currency', other)}")

	def __add__(self, other: Money) -> Money:
		self._same(other)
		return Money(self.amount + other.amount, self.currency)

	def __sub__(self, other: Money) -> Money:
		self._same(other)
		return Money(self.amount - other.amount, self.currency)

	def __mul__(self, factor) -> Money:
		if isinstance(factor, Money):
			raise TypeError("cannot multiply money by money")
		return Money(self.amount * D(factor), self.currency)

	__rmul__ = __mul__

	def __neg__(self) -> Money:
		return Money(-self.amount, self.currency)

	def rounded(self) -> Money:
		return Money(quantize(self.amount, self.currency), self.currency)

	def to_dict(self) -> dict:
		return {"amount": to_str(self.amount), "currency": self.currency}

	@classmethod
	def zero(cls, currency: str) -> Money:
		return cls(ZERO, currency)
