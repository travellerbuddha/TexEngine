"""Read models of the Pricing Workspace's price matrix (ADR-061, GAP-2, GAP-2b). Pure: no frappe.

Both answer from the engine's own resolvers, so the workspace shows what the engine does and
never recomputes a price itself:

* ``unit_source``: which room rule priced a room's unit in a period, whether it is the period's
  own rule or the rule for every period, the rooms it was derived through and the rules it beat;
* ``party_total``: the occupancy total of a sample party in a room and period, built the way the
  publish sweep builds one (each child at the lower edge of its age band).
"""

from __future__ import annotations

from decimal import Decimal

from kamra.tex.money import to_str, to_str_min
from kamra.tex.pricing import ages, occupancy, rooms
from kamra.tex.pricing.enums import Op
from kamra.tex.pricing.explain import Explanation
from kamra.tex.pricing.model import ContractTerms, Period, PricingError


def rule_value(value: Decimal | None) -> str | None:
	"""A rule's value as exact decimal text without trailing zeros ("1", "1.15", "245")."""
	return to_str_min(value, 0)


def unit_source(terms: ContractTerms, room_type: str, period: Period) -> dict:
	"""Where the unit of ``room_type`` in ``period`` comes from. Raises ``Unsellable`` as
	``rooms.room_unit`` does (no price, a derivation without a base room, a cycle).

	→ ``{rule_id, scope: PERIOD | ALL, op, value, base_room_type, chain, overridden}``: ``chain``
	is the room and the rooms it is derived from, the room first; ``overridden`` the rules of
	the room that did not win (a generic rule beaten by the period's own, an INHERIT row)."""
	ex = Explanation()
	rooms.room_unit(terms, room_type, period, explain=ex)
	steps = [s for s in ex.steps if s.stage == "room"]
	step = steps[-1]                                  # the derivation recurses first: the room itself is last
	# the winner among the room's rules, taken in the order room_unit takes them
	rule = next(r for r in rooms._candidates(terms, room_type, period)
	            if r.op != Op.INHERIT and r.rule_id == step.rule.rule_id)
	chain = [s.params["room"] for s in reversed(steps)]
	return {
		"rule_id": rule.rule_id,
		"scope": "PERIOD" if rule.period else "ALL",
		"op": rule.op.value,
		"value": rule_value(rule.value),
		"base_room_type": chain[1] if len(chain) > 1 else None,
		"chain": chain,
		"overridden": [r.rule_id for r in step.overridden],
	}


def sample_party(terms: ContractTerms, adults: int, band_codes, reference) -> ages.Party:
	"""The party of ``adults`` and one child per band code, each child at the lower edge of its
	band and numbered in the contract's child order, as the publish sweep prices a combination.
	An unknown band code raises ``PricingError``."""
	bands = {b.code: b for b in terms.age_bands}
	children = []
	for i, code in enumerate(band_codes):
		band = bands.get(str(code or "").strip().upper())
		if band is None:
			raise PricingError(f"age band {code} is not a band of this contract")
		children.append((i, band.from_months, band))
	slots = ages.child_slots_in_order(children, terms.child_ordering)
	return ages.Party(adults=adults, declared_adults=adults, children=slots, children_as_adults=(),
	                  infants=sum(1 for s in slots if s.band.is_infant), reference_date=reference)


def party_total(terms: ContractTerms, room_type: str, period: Period, adults: int,
                band_codes) -> tuple[Decimal, list[dict]]:
	"""The occupancy total of the sample party (``sample_party``) in ``room_type`` for one night
	of ``period``, and its slots ``{target, position, age_band, amount, rule_id, included}``.

	As the engine prices a night: the room must hold the party (``occupancy.check_capacity``),
	then the unit (``rooms.room_unit``) is priced by the occupancy rules
	(``occupancy.price_occupancy``). Raises ``Unsellable`` as they do, ``PricingError`` for a
	room that is not in the contract or an unknown band."""
	spec = terms.rooms.get(room_type)
	if spec is None:
		raise PricingError(f"room {room_type} is not a room of this contract")
	party = sample_party(terms, adults, band_codes, period.start)
	occupancy.check_capacity(spec, party, terms.infants_count_as_occupants)
	unit = rooms.room_unit(terms, room_type, period)
	result = occupancy.price_occupancy(terms, spec, period, unit, party)
	slots = [{"target": s.kind.value, "position": s.position, "age_band": s.band, "amount": to_str(s.amount),
	          "rule_id": s.rule.rule_id if s.rule else None, "included": s.included}
	         for s in result.slots]
	return result.total, slots
