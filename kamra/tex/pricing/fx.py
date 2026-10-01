"""CurrencyResolver (R-15).

A rate always means ``1 from_currency = rate to_currency``. Selling-rate modes:

* MANUAL            sell = manual rate
* PROVIDER          sell = provider rate
* PROVIDER_PERCENT  sell = provider × (1 + adj/100)   e.g. EURTRY 50, +2 % → 51
* PROVIDER_FIXED    sell = provider + adj             e.g. EURTRY 50 + 1.50 → 51.50

Provider rates may be direct (EUR→TRY), inverse (TRY→EUR) or crossed through a
pivot (GBP→EUR via TRY with TCMB, via EUR with ECB). Conversion without an explicit
policy is refused - money is never converted with a silently assumed rate.

Every conversion a quote makes is recorded (G-56, ADR-051): ``FxLog`` keeps each rate
once, with what it converted, and the quote carries it as ``fx_rates`` - so a sold
price is re-explained from its snapshot, and ``pins`` turns the record back into the
snapshots a reprice on the sold rates uses.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal

from kamra.tex.money import DB_PLACES, ONE, D, display_pct, pct, quantize_rate, to_str_rate
from kamra.tex.pricing.enums import FxMode
from kamra.tex.pricing.model import FxSnapshot, RuleRef, Unsellable


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
	property: str | None = None       # the hotel it is for; None: every hotel


def choose_policy(policies: list[FxPolicy]) -> FxPolicy | None:
	"""The policy that converts a pair (O-11, 2D-2): the hotel's own, else a global one. Two live in
	the one scope that decides are never ranked by name (the older used to win silently): the pair
	is unsellable (``FX_POLICY_AMBIGUOUS``) until one is archived."""
	own = [p for p in policies if p.property]
	pool = own or [p for p in policies if not p.property]
	if len(pool) > 1:
		ids = ", ".join(sorted(p.policy_id for p in pool))
		pair = pool[0]
		raise Unsellable("FX_POLICY_AMBIGUOUS", f"more than one FX policy is live for {pair.from_currency}→"
		                 f"{pair.to_currency} in one scope ({ids})", from_currency=pair.from_currency,
		                 to_currency=pair.to_currency)
	return pool[0] if pool else None


@dataclass(frozen=True, slots=True)
class ProviderRate:
	rate_id: str
	provider: str
	base: str
	quote: str
	rate: Decimal
	rate_date: date
	rate_type: str = "FOREX_SELLING"
	property: str | None = None         # a manual rate: the hotel it was entered for; None: every hotel
	entered_at: datetime | None = None  # a manual rate: when it was entered (the latest correction wins)


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


def manual_bridge(manual: tuple[ProviderRate, ...], frm: str, to: str, on: date,
                  max_age_days: int) -> tuple[Decimal, str, date] | None:
	"""A dated manual rate for the pair, direct or inverse, as of ``on`` and at most ``max_age_days``
	old (O-12). Of several: the newest date, then the hotel's row before a global one, then the
	latest entry (a correction), then the id: never a guess."""
	cands = []
	for r in manual:
		if r.rate <= 0 or not (r.rate_date <= on and (on - r.rate_date).days <= max_age_days):
			continue
		if (r.base, r.quote) == (frm, to):
			value, rid = D(r.rate), r.rate_id
		elif (r.base, r.quote) == (to, frm):
			value, rid = ONE / D(r.rate), f"1/{r.rate_id}"
		else:
			continue
		cands.append(((r.rate_date, r.property is not None, r.entered_at or datetime.min, r.rate_id),
		              (value, rid, r.rate_date)))
	return max(cands, key=lambda c: c[0])[1] if cands else None


def resolve_fx(frm: str, to: str, policy: FxPolicy | None, rates: tuple[ProviderRate, ...],
               as_of: datetime, *, manual: tuple[ProviderRate, ...] = ()) -> FxSnapshot:
	"""``manual``: dated manual rates, used only when a provider mode finds the provider's rate stale or
	missing. The manual rate stands in for the provider's REFERENCE rate: the policy's own mode and
	margin apply on top (manual 50.5, +2 % → 51.51), and the snapshot says it was bridged."""
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
	bridged_from = None
	try:
		raw, rate_id, rate_date = provider_rate(rates, policy.provider, policy.rate_type, frm, to, on)
		if (on - rate_date).days > policy.max_age_days:
			raise Unsellable("FX_RATE_STALE", f"latest {policy.provider} {frm}→{to} rate is from "
			                 f"{rate_date.isoformat()}, older than {policy.max_age_days} days")
	except Unsellable as e:
		if e.code not in ("FX_RATE_STALE", "FX_RATE_MISSING"):
			raise
		found = manual_bridge(manual, frm, to, on, policy.max_age_days)
		if found is None:
			raise
		raw, rate_id, rate_date = found
		bridged_from = policy.provider
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
	return FxSnapshot(frm, to, policy.mode, quantize_rate(sell), provider="MANUAL" if bridged_from else policy.provider,
	                  provider_rate=quantize_rate(raw), provider_rate_id=rate_id, rate_date=rate_date,
	                  adjustment=adj if policy.mode != FxMode.PROVIDER else None,
	                  policy_id=policy.policy_id, as_of=as_of, bridged_from=bridged_from)


def convert(amount: Decimal, fx: FxSnapshot) -> Decimal:
	"""Full-precision conversion; rounding happens at line level."""
	return D(amount) * fx.sell_rate


# ─── the record of a quote's conversions (G-56) ──────────────────────────


def describe(snap: FxSnapshot) -> str:
	"""Where a rate came from, for the explanation: "TCMB 50.000000 of 2027-01-14 +2%,
	policy FXP-0001". A rate reused from a reservation's snapshot says so."""
	adj = D(snap.adjustment) if snap.adjustment is not None else None
	if snap.mode == FxMode.IDENTITY:
		text = "same currency"
	elif snap.mode == FxMode.MANUAL:
		text = "manual rate"
	elif snap.mode == FxMode.RECORDED:
		text = "rate recorded on the sold line"
	else:
		text = f"{snap.provider or '?'} {to_str_rate(snap.provider_rate)}"
		if snap.rate_date:
			text += f" of {snap.rate_date.isoformat()}"
		if snap.mode == FxMode.PROVIDER_PERCENT and adj is not None:
			text += f" {'+' if adj >= 0 else '−'}{display_pct(abs(adj), DB_PLACES)}%"
		elif snap.mode == FxMode.PROVIDER_FIXED and adj is not None:
			text += f" {'+' if adj >= 0 else '−'} {to_str_rate(abs(adj))}"
		if snap.bridged_from:
			text += f" (bridging {snap.bridged_from})"
	if snap.policy_id:
		text += f", policy {snap.policy_id}"
	if snap.origin:
		text += f"; recorded at sale ({snap.origin})"
	return text


@dataclass
class FxLog:
	"""The conversions one quote made: each rate once, in the order first used, with what
	it converted ("accommodation", "cost", "extra:SPA", "promotion:P1",
	"promotion:P1:min_basket", "tax:CITY"). A same-currency 'conversion' is not one."""

	entries: list[tuple[FxSnapshot, list[str]]] = field(default_factory=list)
	unexplained: list[tuple[FxSnapshot, str]] = field(default_factory=list)

	def note(self, snap: FxSnapshot | None, use: str) -> None:
		if snap is None or snap.from_currency == snap.to_currency:
			return
		for s, uses in self.entries:
			if s == snap:
				if use not in uses:
					uses.append(use)
					self.unexplained.append((snap, use))
				return
		self.entries.append((snap, [use]))
		self.unexplained.append((snap, use))

	def take_unexplained(self) -> list[tuple[FxSnapshot, str]]:
		out, self.unexplained = self.unexplained, []
		return out

	def to_list(self) -> list[dict]:
		return [{**s.to_dict(), "used_for": list(uses)} for s, uses in self.entries]


def explain_new(log: FxLog | None, explain) -> None:
	"""One explanation step per conversion not explained yet: the pair, the exact rate, its
	source and policy, and what it converted."""
	if log is None or explain is None:
		return
	for snap, use in log.take_unexplained():
		rule = RuleRef("fx_policy", snap.policy_id, None, f"fx_policy:{snap.policy_id}",
		               f"{snap.from_currency}→{snap.to_currency}") if snap.policy_id else None
		extra = {"bridged_from": snap.bridged_from} if snap.bridged_from else {}
		explain.add("fx", "FX", "{use}: 1 {from} = {rate} {to} ({source})", rule=rule, use=use,
		            **{"from": snap.from_currency}, to=snap.to_currency, rate=to_str_rate(snap.sell_rate),
		            mode=snap.mode.value, provider=snap.provider, provider_rate=to_str_rate(snap.provider_rate),
		            provider_rate_id=snap.provider_rate_id,
		            rate_date=snap.rate_date.isoformat() if snap.rate_date else None,
		            adjustment=to_str_rate(snap.adjustment), policy=snap.policy_id,
		            as_of=snap.as_of.isoformat() if snap.as_of else None, origin=snap.origin,
		            source=describe(snap), **extra)


def from_dict(d: dict, *, origin: str | None = None) -> FxSnapshot:
	"""A snapshot back from its ``to_dict`` (a quote's record). ``origin`` marks it reused."""
	def dec(v):
		return D(v) if v not in (None, "") else None

	def day(v):
		return date.fromisoformat(str(v)[:10]) if v else None

	return FxSnapshot(
		from_currency=str(d["from"]).upper(), to_currency=str(d["to"]).upper(), mode=FxMode(d["mode"]),
		sell_rate=D(d["sell_rate"]), provider=d.get("provider"), provider_rate=dec(d.get("provider_rate")),
		provider_rate_id=d.get("provider_rate_id"), rate_date=day(d.get("rate_date")),
		adjustment=dec(d.get("adjustment")), policy_id=d.get("policy_id"),
		as_of=datetime.fromisoformat(d["as_of"]) if d.get("as_of") else None,
		origin=origin if origin is not None else d.get("origin"), bridged_from=d.get("bridged_from") or None)


def recorded(snapshot: dict, *, extra_currency: dict[str, str] | None = None,
             tax_currency: dict[str, str] | None = None) -> list[dict]:
	"""The conversions a priced snapshot records: its ``fx_rates``. A snapshot priced before
	G-56 recorded the contract → sell rate in full (``fx``) and each converted line's rate:
	``extras[].fx_rate`` (the extra's currency is its revision's: ``extra_currency`` maps the
	revision, or the code, to it) and ``taxes[].fx_rate`` of a fixed levy (``tax_currency``
	maps the line's source, e.g. "tax_policy:TXP-0003", to the policy's currency). A line
	whose currency the caller cannot say is not recorded: that pair is resolved as of the sale.
	Extras added after booking (``addon``) keep their own price and are never repriced."""
	if isinstance(snapshot.get("fx_rates"), list):
		return [r for r in snapshot["fx_rates"] if isinstance(r, dict)]
	out: list[dict] = []
	room = snapshot.get("fx")
	if isinstance(room, dict) and room.get("from") and room.get("to") and room["from"] != room["to"]:
		out.append({**room, "used_for": ["accommodation"]})
	sell = str(snapshot.get("currency") or (room or {}).get("to") or "").upper()

	def line(ccy: str | None, rate, use: str) -> None:
		ccy = str(ccy or "").upper()
		if not ccy or not sell or ccy == sell or rate in (None, ""):
			return
		try:
			rate = D(rate)
		except ValueError:
			return
		if rate <= 0:
			return
		for r in out:
			if (r["from"], r["to"]) == (ccy, sell):
				if D(r["sell_rate"]) == rate and use not in r["used_for"]:
					r["used_for"].append(use)
				return            # one rate per pair; a differing line rate is not guessed between
		out.append({"from": ccy, "to": sell, "mode": FxMode.RECORDED.value, "sell_rate": to_str_rate(rate),
		            "provider": None, "provider_rate": None, "provider_rate_id": None, "rate_date": None,
		            "adjustment": None, "policy_id": None, "as_of": None, "used_for": [use]})

	for e in snapshot.get("extras") or []:
		if isinstance(e, dict) and e.get("ok", True) and not e.get("addon") and e.get("fx_rate") not in (None, ""):
			line((extra_currency or {}).get(e.get("revision") or e.get("code") or ""), e["fx_rate"],
			     f"extra:{e.get('code')}")
	for t in snapshot.get("taxes") or []:
		if isinstance(t, dict) and t.get("fx_rate") not in (None, ""):
			line((tax_currency or {}).get(t.get("source") or ""), t["fx_rate"], f"tax:{t.get('code')}")
	return out


def pins(record: list[dict], *, origin: str) -> dict[tuple[str, str], FxSnapshot]:
	"""(from, to) → the recorded snapshot, marked with ``origin``: the rates a reprice on
	the sold terms converts with instead of today's. The first record of a pair wins."""
	out: dict[tuple[str, str], FxSnapshot] = {}
	for r in record:
		try:
			snap = from_dict(r, origin=origin)
		except (KeyError, ValueError, TypeError):
			continue      # an unreadable entry pins nothing: that pair is resolved as of the sale
		if snap.from_currency != snap.to_currency:
			out.setdefault((snap.from_currency, snap.to_currency), snap)
	return out
