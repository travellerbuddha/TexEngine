"""A change to one room of a booking and the discounts the booking's basket granted (G-84 review
H1, ADR-057). Pure: no database, deterministic.

A promotion with a minimum basket is judged on the basket of the booking's rooms it covers. A
room granted it only on that basket records what it would cost without it (its ``forfeit``,
``engine.BasketTerm``). When a room is changed or cancelled, the rooms that are not changed keep
their locked price; if the rooms the promotion covers no longer reach its minimum, the changed
room carries the discount those rooms keep (``clawback``).

What a room carries is recorded with it (its ledger, ``Carried`` per promotion) — a cancelled
room's too, in its cancellation charge — so the booking as a whole owes each promotion's
forfeits exactly once: a later change of any room charges what is owed and not yet carried by
another room, and credits what other rooms carry but is no longer owed (the booking qualifies
again, or the room whose discount they paid for now pays its own full price or is cancelled)."""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal

from kamra.tex.money import ZERO, D, quantize, to_str


@dataclass(frozen=True)
class Term:
	"""A promotion with a minimum basket a room is eligible for (``engine.BasketTerm``, as the
	room's snapshot records it)."""

	promo_id: str
	name: str
	minimum: Decimal
	applied: bool
	forfeit: Decimal = ZERO
	forfeit_net: Decimal = ZERO
	forfeit_tax: Decimal = ZERO

	@classmethod
	def from_dict(cls, d: dict) -> Term:
		forfeit = D(d.get("forfeit"))
		return cls(str(d["promo_id"]), str(d.get("name") or d["promo_id"]), D(d.get("minimum")),
		           bool(d.get("applied")), forfeit,
		           D(d["forfeit_net"]) if d.get("forfeit_net") not in (None, "") else forfeit, D(d.get("forfeit_tax")))


@dataclass(frozen=True)
class Carried:
	"""What a room carries for one promotion: charged (positive) or credited (negative)."""

	amount: Decimal
	net: Decimal
	tax: Decimal


@dataclass(frozen=True)
class BookedRoom:
	"""A live room of a booking: its basket, the promotions with a minimum it is eligible for,
	and what it carries for the other rooms."""

	name: str
	basket: Decimal
	terms: tuple[Term, ...] = ()
	carried: dict[str, Carried] = field(default_factory=dict)

	def term(self, promo_id: str) -> Term | None:
		return next((t for t in self.terms if t.promo_id == promo_id), None)


@dataclass
class Clawback:
	"""What a changed (or cancelled) room carries for the other rooms: per promotion, the
	forfeits owed less what other rooms carry already. Positive: charged; negative: credited."""

	currency: str
	amount: Decimal = ZERO
	net: Decimal = ZERO
	tax: Decimal = ZERO
	promotions: list[dict] = field(default_factory=list)

	@property
	def text(self) -> str:
		return " ".join(p["text"] for p in self.promotions)

	def to_dict(self) -> dict:
		return {"currency": self.currency, "amount": to_str(self.amount), "net": to_str(self.net),
		        "tax": to_str(self.tax), "promotions": self.promotions}


def _money(v: Decimal, ccy: str) -> str:
	return to_str(quantize(v, ccy))


def clawback(others, changed: BookedRoom | None, currency: str, *, before: BookedRoom | None = None,
             settled=()) -> Clawback:
	"""``others``: the other live rooms of the booking, not changed (locked). ``changed``: the
	changed room as it is priced now, or None when it is cancelled. ``before``: the changed room as
	it was (only for the basket before, in the explanation). ``settled``: the booking's rooms that
	are no longer live (cancelled): only what they carry counts. → what the changed room carries."""
	others = sorted(others, key=lambda r: r.name)
	settled = sorted(settled, key=lambda r: r.name)
	after_rooms = [*others, *([changed] if changed is not None else [])]
	ids = sorted({t.promo_id for o in others for t in o.terms if t.applied and t.forfeit > ZERO}
	             | {pid for o in (*others, *settled) for pid in o.carried})
	out = Clawback(currency)
	for pid in ids:
		covered = [r for r in after_rooms if r.term(pid) is not None]
		after = sum((r.basket for r in covered), ZERO)
		owed = [(o, t) for o in others if (t := o.term(pid)) is not None and t.applied and t.forfeit > ZERO
		        and after < t.minimum]
		held = [(o, o.carried[pid]) for o in (*others, *settled) if pid in o.carried]
		amount = sum((t.forfeit for _o, t in owed), ZERO) - sum((c.amount for _o, c in held), ZERO)
		net = sum((t.forfeit_net for _o, t in owed), ZERO) - sum((c.net for _o, c in held), ZERO)
		tax = sum((t.forfeit_tax for _o, t in owed), ZERO) - sum((c.tax for _o, c in held), ZERO)
		if not (amount or net or tax):
			continue
		ref = next((t for r in [*others, *([changed] if changed else []), *([before] if before else [])]
		            if (t := r.term(pid)) is not None), None)
		name, minimum = (ref.name, ref.minimum) if ref else (pid, None)
		was = None
		if before is not None:
			was = sum((o.basket for o in others if o.term(pid) is not None), ZERO) \
				+ (before.basket if before.term(pid) is not None else ZERO)
		entry = {
			"promo_id": pid, "name": name, "minimum": _money(minimum, currency) if minimum is not None else None,
			"basket_before": _money(was, currency) if was is not None else None,
			"basket_after": _money(after, currency), "rooms_after": len(covered),
			"amount": _money(amount, currency), "net": _money(net, currency), "tax": _money(tax, currency),
			"rooms": [{"reservation": o.name, "amount": _money(t.forfeit, currency)} for o, t in owed],
			"carried_by": [{"reservation": o.name, "amount": _money(c.amount, currency)} for o, c in held],
		}
		entry["text"] = _text(entry, currency, owed=bool(owed))
		out.promotions.append(entry)
		out.amount += amount
		out.net += net
		out.tax += tax
	out.amount, out.net, out.tax = (quantize(v, currency) for v in (out.amount, out.net, out.tax))
	return out


def _text(e: dict, ccy: str, *, owed: bool) -> str:
	was = f" (was {e['basket_before']} {ccy})" if e["basket_before"] else ""
	need = f" needs a booking of at least {e['minimum']} {ccy};" if e["minimum"] else ":"
	head = f"{e['name']}{need} the rooms it covers now come to {e['basket_after']} {ccy}{was}."
	amount = D(e["amount"])
	if amount > ZERO:
		owed_total = sum((D(r["amount"]) for r in e["rooms"]), ZERO)
		less = f", less {_money(owed_total - amount, ccy)} {ccy} another room carries already" \
			if owed_total != amount else ""
		return f"{head} The {_money(owed_total, ccy)} {ccy} discount the other rooms keep is charged here{less}."
	back = f"{_money(-amount, ccy)} {ccy} charged on another room of this booking"
	if owed or (e["minimum"] and D(e["basket_after"]) < D(e["minimum"])):
		return f"{head} {back} for a discount no room keeps any more is credited here."
	return f"{e['name']} is earned by the rooms it covers again ({e['basket_after']} {ccy}): the {back} is credited here."
