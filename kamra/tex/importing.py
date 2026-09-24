"""Amounts read from a migration file (ADR-052 review, G-92 H1/L2/L3). Pure: no frappe.

The legacy importers stripped every character but digits and dots, so "150,00" became 15000.00,
"1.250,50" became 1.25 and "-120" became 120, and at a TEX hotel such a row is then price-locked.
A cell is now read strictly and never guessed:

- the decimal mark is the last ``,`` or ``.`` when exactly one or two digits follow it (or four or
  more: a thousands group has three); a separator that appears more than once groups thousands;
- a single separator followed by exactly three digits is ambiguous ("1.500" is 1500 or 1.5): the
  cell is refused unless the import says which decimal mark the file uses (``decimal``);
- thousands may be grouped by the other separator, a space (also no-break and thin spaces) or an
  apostrophe, in groups of three (or the Indian 2-2-3), never mixed;
- currency symbols and codes before or after the number are stripped and reported; an ambiguous
  symbol ("$", "¥", "kr") reports every currency it may be;
- a minus sign (also after the number) or parentheses make it negative, which is refused; anything
  else is "not an amount".
"""

from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation

from kamra.tex.money import minor_units, quantize

DECIMAL_MARKS = (".", ",")

# symbols and local abbreviations → the currencies they may mean (lower case keys)
SYMBOLS: dict[str, frozenset[str]] = {
	"€": frozenset({"EUR"}), "£": frozenset({"GBP"}), "₺": frozenset({"TRY"}), "tl": frozenset({"TRY"}),
	"₹": frozenset({"INR"}), "rs": frozenset({"INR"}), "rs.": frozenset({"INR"}), "₽": frozenset({"RUB"}),
	"zł": frozenset({"PLN"}), "lei": frozenset({"RON"}), "fr.": frozenset({"CHF"}),
	"$": frozenset({"USD", "CAD", "AUD", "NZD", "SGD", "HKD", "MXN"}),
	"us$": frozenset({"USD"}), "¥": frozenset({"JPY", "CNY"}), "kr": frozenset({"SEK", "NOK", "DKK", "ISK"}),
}
_GROUPING = (" ", "'")
_NEGATIVE = ("-", "−", "(", ")")
_CORE = re.compile(r"\d[\d.,' ]*\d|\d")


class AmountError(ValueError):
	"""The cell cannot be read as an amount; the message says why, for the import's row list."""


def currency_code(text: str | None) -> str | None:
	"""The ISO code a currency cell or token names, or None (unknown, ambiguous or empty). Whether
	the code exists on the site is checked by the caller."""
	t = (text or "").strip().lower()
	if not t:
		return None
	named = SYMBOLS.get(t)
	if named is not None:
		return next(iter(named)) if len(named) == 1 else None
	return t.upper() if re.fullmatch(r"[a-z]{3}", t) else None


def _named(tokens: list[str], cell: str) -> frozenset[str]:
	named: frozenset[str] = frozenset()
	for token in tokens:
		t = token.lower()
		this = SYMBOLS.get(t) or (frozenset({t.upper()}) if re.fullmatch(r"[a-z]{3}", t) else None)
		if this is None:
			raise AmountError(f"'{cell}' is not an amount")
		if named and not (named & this):
			raise AmountError(f"'{cell}' names two currencies")
		named = (named & this) if named else this
	return named


def _integer(part: str, groupers: set[str], cell: str) -> str:
	"""Digits of an integer part whose thousands may be grouped by one of ``groupers``."""
	used = {ch for ch in part if not ch.isdigit()}
	if not used:
		return part
	if len(used) > 1 or not used <= groupers:
		raise AmountError(f"'{cell}' is not an amount")
	sep = re.escape(used.pop())
	if re.fullmatch(rf"\d{{1,3}}({sep}\d{{3}})+", part) or re.fullmatch(rf"\d{{1,2}}({sep}\d{{2}})*{sep}\d{{3}}", part):
		return re.sub(sep, "", part)
	raise AmountError(f"'{cell}' is not an amount")


def _number(core: str, decimal: str | None, cell: str) -> Decimal:
	if decimal is not None:
		other = "," if decimal == "." else "."
		if core.count(decimal) > 1:
			raise AmountError(f"'{cell}' does not fit the decimal mark '{decimal}'")
		whole, _, frac = core.partition(decimal)
		if frac and not frac.isdigit():
			raise AmountError(f"'{cell}' does not fit the decimal mark '{decimal}'")
		if decimal in core and not frac:
			raise AmountError(f"'{cell}' is not an amount")
		return Decimal(_integer(whole, {other, *_GROUPING}, cell) + (f".{frac}" if frac else ""))
	marks = [i for i, ch in enumerate(core) if ch in DECIMAL_MARKS]
	if not marks:
		return Decimal(_integer(core, set(_GROUPING), cell))
	last = marks[-1]
	mark, tail = core[last], core[last + 1:]
	if core.count(mark) > 1:                       # a repeated separator groups thousands
		return Decimal(_integer(core, {mark, *_GROUPING}, cell))
	if not tail.isdigit():
		raise AmountError(f"'{cell}' is not an amount")
	if len(tail) == 3:
		raise AmountError(f"'{cell}' is ambiguous: say which decimal mark the file uses (',' or '.')")
	whole = core[:last]
	if not whole:
		raise AmountError(f"'{cell}' is not an amount")
	other = "," if mark == "." else "."
	return Decimal(_integer(whole, {other, *_GROUPING}, cell) + "." + tail)


def parse_amount(value, *, decimal: str | None = None) -> tuple[Decimal | None, frozenset[str]]:
	"""(amount, currencies the cell names). ``(None, ∅)`` for an empty cell. Raises
	``AmountError`` (negative, ambiguous, not an amount) and ``ValueError`` for a ``decimal``
	that is not "." or ","."""
	if decimal not in (None, *DECIMAL_MARKS):
		raise ValueError(f"the decimal mark is '.' or ',', not {decimal!r}")
	if value is None:
		return None, frozenset()
	if isinstance(value, bool):
		raise AmountError(f"'{value}' is not an amount")
	if isinstance(value, int | float | Decimal):
		try:
			amount = Decimal(repr(value)) if isinstance(value, float) else Decimal(value)
		except InvalidOperation as e:
			raise AmountError(f"'{value}' is not an amount") from e
		if not amount.is_finite():
			raise AmountError(f"'{value}' is not an amount")
		if amount < 0:
			raise AmountError(f"'{value}' is negative")
		return amount, frozenset()
	cell = str(value)
	text = re.sub(r"[   \t]", " ", cell).strip()
	if not text:
		return None, frozenset()
	cores = list(_CORE.finditer(text))
	if len(cores) > 1:
		raise AmountError(f"'{cell}' is not an amount")
	rest = (text[:cores[0].start()] + " " + text[cores[0].end():]) if cores else text
	if any(ch in rest for ch in _NEGATIVE):
		raise AmountError(f"'{cell}' is negative")
	if not cores:
		raise AmountError(f"'{cell}' is not an amount")
	named = _named(rest.split(), cell)
	return _number(cores[0].group().strip(), decimal, cell), named


def check_currency(amount: Decimal, named: frozenset[str], currency: str) -> Decimal:
	"""The amount in the row's ``currency``: refused when the cell named another currency or
	carries more decimals than the currency has (never rounded silently)."""
	if named and currency not in named:
		raise AmountError(f"the amount is in {', '.join(sorted(named))}, not {currency}")
	places = minor_units(currency)
	exponent = amount.normalize().as_tuple().exponent
	if isinstance(exponent, int) and -exponent > places:
		raise AmountError(f"{amount} has more decimals than {currency} has ({places})")
	return quantize(amount, currency)
