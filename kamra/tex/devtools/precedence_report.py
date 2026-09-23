"""Occupancy precedence v2 rollout report (G-30, G-31, ADR-042). Read-only.

    bench --site <site> execute kamra.tex.devtools.precedence_report.run
    bench --site <site> execute kamra.tex.devtools.precedence_report.run \
        --kwargs "{'property': 'Aurora Beach Resort', 'rebuild': 0}"

A published contract version keeps the occupancy ranking it was sold with: a payload
frozen before v2 has no ``occupancy_precedence`` and is priced with the legacy ranking
until the contract is republished. This report tells ops which versions to look at:

* ``precedence``: for every version on sale now or scheduled whose payload is still on
  the legacy ranking, a representative grid of parties (every room and period, every
  adult count, every mix of the contract's age bands up to the room's child capacity)
  is priced from the frozen payload under both rankings; cells that differ are listed
  (e.g. an infant priced by a band-less "child 2 of 2A+2C" rule under the legacy one).
* ``rebuild`` (default on): the same grid priced from the version rebuilt as a
  republish would build it now - every applicable pricing policy cascaded (G-30) - so
  policy changes that reach the contract only on republish show too. A version that
  cannot be rebuilt says why (e.g. two live pricing policies of one scope).
* ``ambiguous_policy_scopes``: (hotel, market) scopes with more than one live pricing
  policy. No contract of such a scope can be published until one is archived.

Nothing is written. The pure grid comparison (``differences``) has no frappe import.
"""

from __future__ import annotations

from dataclasses import replace
from decimal import Decimal
from itertools import combinations_with_replacement

from kamra.tex.money import display
from kamra.tex.pricing import ages, occupancy, rooms
from kamra.tex.pricing.model import ChildSpec, ContractTerms, PricingError, Unsellable


def _grid(t: ContractTerms):
	"""(room, period, adults, band mix) of every party a room can sell."""
	bands = tuple(sorted(t.age_bands, key=lambda b: b.from_months))
	for rt, spec in sorted(t.rooms.items()):
		for p in t.periods:
			for n_a in range(max(1, spec.min_adults), spec.max_adults + 1):
				for n_c in range(0, spec.max_children + 1):
					if n_c and not bands:
						break
					for mix in combinations_with_replacement(bands, n_c):
						yield rt, p, n_a, mix


def _price(t: ContractTerms, rt: str, period, adults: int, mix) -> Decimal | str:
	"""The occupancy amount of one night, or the code of why it cannot be sold."""
	kids = tuple(ChildSpec(age_months=b.from_months) for b in mix)
	try:
		party = ages.classify_party(t, adults, kids, period.start, period.start)
		spec = t.rooms[rt]
		occupancy.check_capacity(spec, party, t.infants_count_as_occupants)
		return occupancy.price_occupancy(t, spec, period, rooms.room_unit(t, rt, period), party).total
	except Unsellable as u:
		return u.code
	except PricingError as e:
		return f"ERROR: {e}"


def differences(before: ContractTerms, after: ContractTerms | None = None) -> list[dict]:
	"""Grid cells priced differently by ``before`` and ``after`` (default: ``before`` under
	the v2 ranking). Pure."""
	if after is None:
		after = replace(before, occupancy_precedence=occupancy.CASCADE)
	out = []
	for rt, p, n_a, mix in _grid(before):
		if rt not in after.rooms or p.code not in {x.code for x in after.periods}:
			continue
		a = _price(before, rt, p, n_a, mix)
		b = _price(after, rt, p, n_a, mix)
		if a != b:   # Decimals compare by value (250.00 == 250.0000)
			out.append({"room": rt, "period": p.code,
			            "party": f"{n_a}A" + (f"+[{','.join(x.code for x in mix)}]" if mix else ""),
			            "sold_as": display(a), "now": display(b)})
	return out


def _live_versions(property: str | None) -> list[dict]:
	import frappe
	from frappe.utils import get_datetime, now_datetime

	now = now_datetime()
	rows = frappe.db.sql("""SELECT v.name, v.contract, v.version_no, v.effective_from, v.active_to,
	                               c.contract_code, c.property, c.market
	                        FROM `tabTEX Contract Version` v JOIN `tabTEX Contract` c ON c.name = v.contract
	                        WHERE v.status = 'Published' AND (%(p)s = '' OR c.property = %(p)s)
	                        ORDER BY c.property, c.contract_code, v.version_no""", {"p": property or ""}, as_dict=True)
	return [r for r in rows if not r.active_to or get_datetime(r.active_to) > now]


def _ambiguous_policy_scopes() -> list[dict]:
	from frappe.utils import now_datetime

	from kamra.tex.commercial.revisions import as_of

	scopes: dict[tuple, list[str]] = {}
	for r in as_of("TEX Pricing Policy", now_datetime(), fields=("name", "property", "market")):
		scopes.setdefault((r.property or "", r.market or ""), []).append(r.name)
	return [{"property": k[0] or None, "market": k[1] or None, "policies": v}
	        for k, v in sorted(scopes.items()) if len(v) > 1]


def run(property: str | None = None, rebuild: bool = True, examples: int = 5) -> dict:
	import frappe
	from frappe.utils import now_datetime

	from kamra.tex.commercial import contracts

	report = {"checked": 0, "already_v2": 0, "precedence": [], "rebuild": [], "cannot_rebuild": [],
	          "ambiguous_policy_scopes": _ambiguous_policy_scopes()}
	for v in _live_versions(property):
		report["checked"] += 1
		frozen = contracts.load_terms(v.name)
		head = {"version": v.name, "contract": v.contract, "contract_code": v.contract_code,
		        "property": v.property, "market": v.market, "version_no": v.version_no}
		if frozen.occupancy_precedence >= occupancy.CASCADE:
			report["already_v2"] += 1
		else:
			diff = differences(frozen)
			if diff:
				report["precedence"].append({**head, "cells": len(diff), "examples": diff[:examples]})
		if rebuild:
			try:
				rebuilt = contracts.build_terms(frappe.get_doc("TEX Contract Version", v.name), at=now_datetime())
			except frappe.ValidationError as e:
				report["cannot_rebuild"].append({**head, "reason": str(e)})
				continue
			diff = differences(frozen, rebuilt)
			if diff:
				report["rebuild"].append({**head, "cells": len(diff), "examples": diff[:examples]})
	_print(report)
	return report


def _print(report: dict) -> None:
	print(f"checked {report['checked']} version(s) on sale or scheduled; {report['already_v2']} already on v2")
	for s in report["ambiguous_policy_scopes"]:
		print(f"! two live pricing policies for {s['property'] or 'every hotel'} / {s['market'] or 'every market'}: "
		      f"{', '.join(s['policies'])} (archive one: publishing is refused meanwhile)")
	for key, title in (("precedence", "prices change under the v2 ranking (same frozen rules)"),
	                   ("rebuild", "prices change when republished now (v2 ranking + every live policy)")):
		print(f"\n{title}: {len(report[key])} version(s)")
		for row in report[key]:
			print(f"  {row['property']} {row['contract_code']} v{row['version_no']} ({row['version']}): "
			      f"{row['cells']} cell(s)")
			for d in row["examples"]:
				print(f"      {d['room']} {d['period']} {d['party']}: {d['sold_as']} → {d['now']}")
	for row in report["cannot_rebuild"]:
		print(f"! {row['property']} {row['contract_code']} v{row['version_no']} cannot be republished: {row['reason']}")
