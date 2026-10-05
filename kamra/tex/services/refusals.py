"""Coded guest refusals: the transport (G-70a, audit Part 2G-2; ADR-013 amendment).

A refusal a guest can act on carries a stable ``code`` (``kamra.tex.refusal_codes.CODES``) and guest-safe
``params``. Every guest endpoint (``kamra/tex/api/public.py``) is wrapped in :func:`coded`, which copies them into
the request's JSON error body as ``tex_code`` / ``tex_params``: Frappe answers an error with the whole
``frappe.local.response`` (``report_error`` → ``as_json``), next to its ``exc_type`` and message. The booking app
classifies by the code and shows its own text in the guest's language; the English message stays for staff, API
clients and logs.

Raise one through ``frappe.throw`` so the guest also gets the message::

    frappe.throw(_("Sorry — {0} has just sold out for {1}.").format(room, day), refusal("SOLD_OUT", room=room,
                                                                                           date=day.isoformat()))

``frappe.throw(msg, instance)`` raises that instance, its ``code`` and ``params`` kept. Existing exception classes
may declare a class ``code`` instead (``ContractSuspended``, ``HoldExpired`` …).
"""

from __future__ import annotations

import functools

import frappe

from kamra.tex.refusal_codes import CODES

# what a guest's error body never carries, whatever a refusal's own params say (staff keep them on the exception): the
# market and the channel a sale was priced on (G-71; 2G-3 review round 1)
GUEST_HIDDEN = frozenset({"market", "channel"})

# what an uncoded refusal of these kinds tells the guest: a 429, a 404, a 403 (checked in this order: the rate
# limit error is a ValidationError, a missing record is not a permission error)
FALLBACK: tuple[tuple[type[Exception], str], ...] = (
	(frappe.RateLimitExceededError, "RATE_LIMITED"),
	(frappe.DoesNotExistError, "NOT_FOUND"),
	(frappe.PermissionError, "NOT_PERMITTED"),
)


class Refusal(frappe.ValidationError):
	"""A refusal a guest can act on (417): a stable ``code`` and guest-safe ``params`` — ISO dates, decimal strings,
	ISO currency and country codes, hotel content in the guest's language; never a token, an e-mail, a contract,
	version or connection id (G-70, ADR-013)."""

	code: str | None = None

	def __init__(self, message: str = "", *, code: str | None = None, params: dict | None = None):
		super().__init__(message)
		if code is not None:
			self.code = _known(code)
		self.params = _safe(params)


class MarketRefused(Refusal):
	"""A market a booking site does not sell, or a residents-only market the guest does not qualify for (O-8,
	ADR-070). Its ``exc_type`` tells the Call Center that an override with a reason is possible."""


def _known(code: str) -> str:
	if code not in CODES:
		# a programming error, never a guest's: an unregistered code would never reach the booking app
		raise ValueError(f"unknown refusal code {code!r}: add it to kamra.tex.refusal_codes")
	return code


def _safe(params: dict | None) -> dict:
	"""Params as JSON the error body can carry: str keys; str, int, bool, None or lists of them (anything else as
	its text). Never put a token, an e-mail or an internal id in them."""
	out = {}
	for k, v in (params or {}).items():
		if isinstance(v, list | tuple | set | frozenset):
			v = [x if isinstance(x, str | int | bool) or x is None else str(x)
			     for x in (sorted(v, key=str) if isinstance(v, set | frozenset) else v)]
		elif not (isinstance(v, str | int | bool) or v is None):
			v = str(v)
		out[str(k)] = v
	return out


def refusal(code: str, base: type[Exception] | None = None, *, staff_detail: str | None = None,
            names: dict | None = None, **params) -> Exception:
	"""A coded refusal to raise with ``frappe.throw(message, refusal(...))``. ``base`` keeps a refusal's class where
	callers or its HTTP status depend on it (``frappe.PermissionError`` 403, ``frappe.DoesNotExistError`` 404, an
	existing subclass); default :class:`Refusal` (417). ``staff_detail``: what staff are told where the guest's message
	leaves it out (the engine's reasons), kept on the exception only, never in its params or the guest's error body
	(batch 2P). ``names``: param → (doctype, hotel, record) of hotel content a param names by the hotel's own text
	(a room type, an extra's code), told to the guest in their language (``coded``; batch 2Q); the exception keeps
	the hotel's text."""
	if base is None or issubclass(base, Refusal):
		e = (base or Refusal)(code=code, params=params)
	else:
		e = base()
		e.code = _known(code)
		e.params = _safe(params)
	if staff_detail:
		e.staff_detail = staff_detail
	if names:
		e.tex_names = names
	return e


def _localised(params: dict, names: dict | None) -> dict:
	"""``params`` with the hotel content ``names`` points at in the guest's language (batch 2Q): a room type's name,
	an extra's name (by its code); the hotel's own text where there is no translation."""
	if not names:
		return params
	from kamra.tex.services import content

	lang = content.guest_language()
	if not lang:
		return params
	loc = content.Localizer(lang)
	out = dict(params)
	try:
		for key, (doctype, property, ref) in names.items():
			if key in out and doctype == "Room Type":
				out[key] = loc.room_type_name(property, ref, out[key])
			elif key in out and doctype == "TEX Extra":
				out[key] = loc.extra_name(property, ref, out[key])
	except Exception:
		return params                      # a refusal is never changed by its names: the hotel's own text stays
	return out


def with_code(e: Exception, code: str | None = None, *, names: dict | None = None, **params) -> Exception:
	"""``e`` (an instance of an existing exception class, its message kept) with a refusal code (default: its
	class's) and guest-safe params, for a refusal raised without ``frappe.throw``::

	    raise with_code(ExtraSoldOut(msg), extra=name, date=day.isoformat())

	``names``: as ``refusal``'s."""
	if code is not None:
		e.code = _known(code)
	e.params = _safe(params)
	if names:
		e.tex_names = names
	return e


def code_of(e: BaseException) -> str | None:
	"""The refusal code ``e`` carries: a registered string only (a werkzeug error's ``code`` is its HTTP status)."""
	code = getattr(e, "code", None)
	return code if isinstance(code, str) and code in CODES else None


def guest_code(e: BaseException) -> str | None:
	"""What the guest is told: ``e``'s own code, else the code of its kind (404, 403, 429), else none."""
	return code_of(e) or next((code for cls, code in FALLBACK if isinstance(e, cls)), None)


def coded(fn):
	"""Guest endpoints: a refusal's code (and params) go into the request's error body. Inside ``rate_limit``,
	outside ``retry_on_deadlock`` (it sees the final answer); ``functools.wraps`` keeps the endpoint's signature
	(Frappe filters the request's arguments by it) and ``__wrapped__`` (the static retry tests walk it). It only
	annotates and re-raises: a step a refusal committed first (an expiry, a failed checkout) stays as it is."""

	@functools.wraps(fn)
	def wrapper(*args, **kwargs):
		resp = getattr(frappe.local, "response", None)
		if resp is not None:
			# one request's code, never the last one's (tests call endpoints in one process)
			resp.pop("tex_code", None)
			resp.pop("tex_params", None)
		try:
			return fn(*args, **kwargs)
		except Exception as e:
			resp = getattr(frappe.local, "response", None)
			code = guest_code(e)
			if code and resp is not None:
				resp["tex_code"] = code
				params = {k: v for k, v in _safe(e.params).items() if k not in GUEST_HIDDEN} \
					if code_of(e) and isinstance(getattr(e, "params", None), dict) else None
				if params:
					params = _localised(params, getattr(e, "tex_names", None))
				if params:
					resp["tex_params"] = params
			raise

	return wrapper
