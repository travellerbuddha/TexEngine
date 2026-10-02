"""Money primitives for TEX Engine.

Every monetary value in TEX code is a :class:`decimal.Decimal`. Binary floats are
never used for money (ADR-003). Intermediate results keep full precision; values are
rounded once, to the currency's minor unit, when they become an output line.

This module must not import frappe.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_DOWN, ROUND_HALF_UP, Context, Decimal, InvalidOperation, localcontext

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

# FX rates (G-72, ADR-055). A rate keeps at least FX_SIGNIFICANT significant digits and never
# fewer than FX_PLACES decimals: TRY→EUR 0.02941176471 (was 0.029412, 5 significant digits),
# EUR→TRY 51.00000000. Rates recorded before G-72 were rounded to FX_PLACES; they are read back
# exactly as recorded, so a price-locked reservation reprices with its own sold rate.
FX_PLACES = 6
FX_SIGNIFICANT = 10

# Decimal columns of TEX commercial inputs (G-72, ADR-055). Frappe's Float, Currency and Percent
# all map to DECIMAL(21, precision); TEX declares precision 9: 12 integer and 9 decimal digits.
# A value of at most DB_SAFE_DIGITS significant digits crosses the binary float Frappe carries
# between the column and Python unchanged (an IEEE 754 double holds 15 decimal digits).
DB_PLACES = 9
DB_WIDTH = 21
DB_SAFE_DIGITS = 15
_DB_Q = {p: Decimal(1).scaleb(-p) for p in range(DB_PLACES + 1)}


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


def whole_number(value) -> int | None:
	"""A count stored as a decimal string ("2.000000", ``to_str6``) → its int, read as Decimal, never through
	``float`` (LO-48, as ``loyalty.extra_units``). None when it is not a whole number (a fraction, not a number,
	not finite): the caller says what that means. ``None`` and ``""`` are zero, as in ``D``."""
	try:
		q = D(value)
	except (TypeError, ValueError):
		return None
	if not q.is_finite() or q != q.to_integral_value():
		return None
	return int(q)


def minor_units(currency: str) -> int:
	return MINOR_UNITS.get((currency or "").upper(), 2)


def quantum(currency: str) -> Decimal:
	return Decimal(1).scaleb(-minor_units(currency))


def quantize(amount: Decimal, currency: str) -> Decimal:
	"""Round to the currency's minor unit, half-up (commercial rounding)."""
	return D(amount).quantize(quantum(currency), rounding=ROUND_HALF_UP)


def split_evenly(total: Decimal, parts: int, currency: str) -> list[Decimal]:
	"""``total`` in ``parts`` equal shares of the currency's minor unit, the remainder on the last
	share, so the shares always add up to the total (a locked price over its nights, G-96)."""
	if parts < 1:
		raise ValueError("at least one part")
	total = quantize(D(total), currency)
	if total < 0:
		raise ValueError("a negative total is not split")
	share = (total / parts).quantize(quantum(currency), rounding=ROUND_DOWN)
	return [share] * (parts - 1) + [total - share * (parts - 1)]


def rate_places(rate) -> int:
	"""Decimal places an FX rate keeps (G-72): at least ``FX_PLACES``, and as many as it takes
	to keep ``FX_SIGNIFICANT`` significant digits — 51.0 → 8, 0.0294… → 11, 27123.4… → 6."""
	d = D(rate)
	if not d.is_finite() or d == 0:
		return FX_PLACES
	return max(FX_PLACES, FX_SIGNIFICANT - 1 - d.adjusted())


def quantize_rate(rate: Decimal, places: int | None = None) -> Decimal:
	"""An FX rate rounded half-up to its significant-digit precision (``rate_places``), or to
	``places`` decimals when given."""
	d = D(rate)
	return d.quantize(Decimal(1).scaleb(-(rate_places(d) if places is None else places)), rounding=ROUND_HALF_UP)


def from_db(value, currency: str) -> Decimal:
	"""Read a DB Currency value (which frappe may hand back as float) as money."""
	return quantize(D(value), currency)


# ─── TEX decimal columns (G-72, ADR-055) ─────────────────────────────────


def _plain(d: Decimal) -> Decimal:
	"""``d`` written the way a float's repr writes it ("0.3", "12.0", "12.345678901")."""
	text = format(d, "f")
	if "." in text:
		text = text.rstrip("0")
		if text.endswith("."):
			text += "0"
	return Decimal(text)


def db_dec(value, places: int = DB_PLACES) -> Decimal:
	"""The exact Decimal a TEX decimal column holds: THE way loaders read a Float, Currency or
	Percent field of a TEX commercial DocType, whatever Frappe hands over (G-72, ADR-055).

	Frappe returns DECIMAL columns as binary floats. The shortest repr of such a float is the
	stored decimal for every value of up to 15 significant digits (any rate, percent or factor
	below 10^6 with 9 places, any money amount the column holds), so ``D(float)`` is exact; a
	float carrying more (binary noise: 0.1 + 0.2) is rounded to the column's ``places``, as the
	column itself rounds what is written to it. Strings and Decimals are exact and only rounded
	when they carry more places than the column keeps. ``None`` and ``""`` are zero."""
	d = D(value)
	if d.is_finite() and d.as_tuple().exponent < -places:
		d = _plain(d.quantize(_DB_Q[places], rounding=ROUND_HALF_UP))
	return d


def db_dec_or_none(value, places: int = DB_PLACES) -> Decimal | None:
	if value is None or value == "":
		return None
	return db_dec(value, places)


class DecimalInputError(ValueError):
	"""A value a TEX decimal column cannot hold as it was typed. ``code``: NOT_A_NUMBER,
	PLACES (more decimals than kept), DIGITS (more than 15 significant digits), RANGE."""

	def __init__(self, code: str, message: str):
		super().__init__(message)
		self.code = code


def db_input(value, places: int = DB_PLACES, width: int = DB_WIDTH) -> Decimal | None:
	"""Check a value about to be written to a TEX decimal column so that what is stored, and
	read back, is exactly what was typed (G-72, ADR-055) → the Decimal to store (None: blank).

	Text — what a person typed — is refused, never rounded, when it has more than ``places``
	decimals (trailing zeros aside), more than 15 significant digits (it would not survive the
	binary float Frappe writes it through) or more integer digits than the column holds. A
	binary float or a Decimal from code has no typed digits: it is rounded to ``places`` as the
	column would round it, and refused only when it does not fit."""
	if value is None or (isinstance(value, str) and not value.strip()):
		return None
	if isinstance(value, bool):
		raise DecimalInputError("NOT_A_NUMBER", f"{value!r} is not a number")
	typed = isinstance(value, str)
	if typed:
		try:
			d = Decimal(value.strip())
		except InvalidOperation:
			raise DecimalInputError("NOT_A_NUMBER", f"{value!r} is not a number") from None
		if not d.is_finite():
			raise DecimalInputError("NOT_A_NUMBER", f"{value!r} is not a number")
		if d.as_tuple().exponent < -places:
			if d != d.quantize(_DB_Q[places]):
				raise DecimalInputError("PLACES", f"{value.strip()} has more than {places} decimal places")
			d = d.quantize(_DB_Q[places])
	else:
		d = db_dec(value, places)
		if not d.is_finite():
			raise DecimalInputError("NOT_A_NUMBER", f"{value!r} is not a number")
	if d != 0:
		if typed and len(d.normalize().as_tuple().digits) > DB_SAFE_DIGITS:
			raise DecimalInputError("DIGITS", f"{value} has more than {DB_SAFE_DIGITS} significant digits")
		if d.adjusted() >= width - places:
			raise DecimalInputError("RANGE", f"{value} is too large (at most {width - places} digits before "
			                                 "the decimal point)")
	return d


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


def to_str_min(value: Decimal | None, min_places: int = FX_PLACES, max_places: int | None = None) -> str | None:
	"""Canonical decimal text with at least ``min_places`` decimals and every further digit
	(up to ``max_places``, rounded half-up there; all when None), without trailing zeros beyond
	``min_places`` — byte-stable regardless of the Decimal's internal exponent. For any value
	of at most ``min_places`` decimals it is exactly ``to_str6``'s text (with ``min_places`` 6)."""
	if value is None:
		return None
	d = D(value)
	if max_places is not None and d.as_tuple().exponent < -max_places:
		d = d.quantize(Decimal(1).scaleb(-max_places), rounding=ROUND_HALF_UP)
	if d == 0:
		d = abs(d)
	whole, _, frac = format(d, "f").partition(".")
	return f"{whole}.{frac.rstrip('0').ljust(min_places, '0')}" if min_places or frac.rstrip("0") else whole


def to_str_rate(value: Decimal | None) -> str | None:
	"""An FX rate (or FX adjustment) as recorded in a quote (G-72, ADR-055): every digit it has,
	at least 6 decimals. A rate recorded before G-72 (6 places: "51.000000", "0.029412")
	serialises byte-identically to its record; 0.02941176471 as "0.02941176471"."""
	return to_str_min(value, FX_PLACES)


def to_str_param(value: Decimal | None) -> str | None:
	"""A pricing value in an explanation: at least 6 decimals, exact to the 9 places a TEX
	decimal column keeps (a rule value of 0.333333333 shows as it is), as ``to_str6`` for any
	value of at most 6 places."""
	return to_str_min(value, FX_PLACES, DB_PLACES)


def display(v, places: int = 4):
	"""Human display of a Decimal with 2–``places`` decimals ("1.20", "120.00", "52.965"),
	independent of the Decimal's internal exponent. Non-decimals pass through."""
	if not isinstance(v, Decimal):
		return v
	q = format(v.quantize(Decimal(1).scaleb(-places), rounding=ROUND_HALF_UP), "f")
	whole, _, frac = q.partition(".")
	return f"{whole}.{frac.rstrip('0').ljust(2, '0')}"


def display_pct(v, places: int = 4) -> str:
	"""Percent display: "10", "7.5" — no forced decimals, at most ``places``."""
	q = format(D(v).quantize(Decimal(1).scaleb(-places), rounding=ROUND_HALF_UP), "f")
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
