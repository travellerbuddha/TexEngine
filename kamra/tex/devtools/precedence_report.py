"""Occupancy precedence v2 rollout report (G-30, G-31, ADR-043). Read-only.

    bench --site <site> execute kamra.tex.devtools.precedence_report.run
    bench --site <site> execute kamra.tex.devtools.precedence_report.run \
        --kwargs "{'property': 'Aurora Beach Resort', 'rebuild': 0}"

A published contract version keeps the occupancy ranking it was sold with: a payload
frozen before v2 has no ``occupancy_precedence`` and is priced with the legacy ranking
until the contract is republished. This report tells ops which versions to look at:

* ``precedence``: for every version on sale now or scheduled whose payload is still on
  the legacy ranking, a representative grid of parties (every room and period, every
  adult count, every mix of child ages up to the room's child capacity - one age at the
  start of each age band of either side) is priced from the frozen payload under both
  rankings; cells that differ are listed (e.g. an infant priced by a band-less "child 2
  of 2A+2C" rule under the legacy one).
* ``rebuild`` (default on): the same grid priced from the version rebuilt as a
  republish would build it - every applicable pricing policy cascaded (G-30) as of the
  version's start (now, or its scheduled ``effective_from``) - so policy changes that
  reach the contract only on republish show too. A version frozen without age bands (its
  children sold as adults) is compared on the rebuilt version's bands.
* ``cannot_rebuild``: versions a republish would refuse, and why: the rebuild fails
  (e.g. two live pricing policies of one scope) or the publish check reports an ERROR
  (e.g. a pricing-policy row activated before the policy checks existed).
* ``ambiguous_policy_scopes``: (hotel, market) scopes with more than one pricing policy
  live now or scheduled. No contract of such a scope can be published until one is
  archived.

Nothing is written. The pure grid comparison (``differences``) has no frappe import.
"""

from __future__ import annotations

from dataclasses import replace
from decimal import Decimal
from itertools import combinations_with_replacement

from kamra.tex.money import display
from kamra.tex.pricing import ages, occupancy, rooms, validate
from kamra.tex.pricing.model import ChildSpec, ContractTerms, PricingError, Unsellable


def _child_ages(before: ContractTerms, after: ContractTerms) -> tuple[int, ...]:
	"""One child age (months) per age band of either side: its first month. A side without
	bands prices these children as adults; the other side shows what they cost now."""
	return tuple(sorted({b.from_months for b in (*before.age_bands, *after.age_bands)}))


def _grid(before: ContractTerms, after: ContractTerms):
	"""(room, period, adults, child ages) of every party a room of ``before`` can sell."""
	sample = _child_ages(before, after)
	for rt, spec in sorted(before.rooms.items()):
		for p in before.periods:
			for n_a in range(max(1, spec.min_adults), spec.max_adults + 1):
				for n_c in range(0, spec.max_children + 1):
					if n_c and not sample:
						break
					for mix in combinations_with_replacement(sample, n_c):
						yield rt, p, n_a, mix


def _child_label(months: int, before: ContractTerms, after: ContractTerms) -> str:
	codes = [b.code for b in (ages.band_for(months, before.age_bands), ages.band_for(months, after.age_bands)) if b]
	return "/".join(dict.fromkeys(codes)) or ages.format_months(months)


def _price(t: ContractTerms, rt: str, period, adults: int, mix) -> Decimal | str:
	"""The occupancy amount of one night, or the code of why it cannot be sold."""
	kids = tuple(ChildSpec(age_months=m) for m in mix)
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
	for rt, p, n_a, mix in _grid(before, after):
		if rt not in after.rooms or p.code not in {x.code for x in after.periods}:
			continue
		a = _price(before, rt, p, n_a, mix)
		b = _price(after, rt, p, n_a, mix)
		if a != b:   # Decimals compare by value (250.00 == 250.0000)
			kids = ",".join(_child_label(m, before, after) for m in mix)
			out.append({"room": rt, "period": p.code, "party": f"{n_a}A" + (f"+[{kids}]" if mix else ""),
			            "sold_as": display(a), "now": display(b)})
	return out


def republish_errors(rebuilt: ContractTerms) -> list[str]:
	"""The ERRORs that would refuse publishing ``rebuilt`` ("CODE: message"). Pure."""
	return [f"{i.code}: {i.message}" for i in validate.validate_terms(rebuilt) if i.level == "ERROR"]


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
	"""Scopes with more than one pricing policy (root) live now or scheduled: the window the
	activation guard (one live policy per scope) looks at."""
	import frappe
	from frappe.utils import now_datetime

	scopes: dict[tuple, set[str]] = {}
	for r in frappe.db.sql("""SELECT IFNULL(revision_of, name) AS root, IFNULL(property, '') AS property,
	                                 IFNULL(market, '') AS market
	                          FROM `tabTEX Pricing Policy`
	                          WHERE tex_status IN ('Active','Superseded')
	                            AND (active_to IS NULL OR active_to > %(now)s)""", {"now": now_datetime()},
	                       as_dict=True):
		scopes.setdefault((r.property, r.market), set()).add(r.root)
	return [{"property": k[0] or None, "market": k[1] or None, "policies": sorted(v)}
	        for k, v in sorted(scopes.items()) if len(v) > 1]


def run(property: str | None = None, rebuild: bool = True, examples: int = 5) -> dict:
	import frappe
	from frappe.utils import get_datetime, now_datetime

	from kamra.tex.commercial import contracts

	report = {"checked": 0, "already_v2": 0, "precedence": [], "rebuild": [], "cannot_rebuild": [],
	          "ambiguous_policy_scopes": _ambiguous_policy_scopes()}
	now = now_datetime()
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
			# as a republish would build it: the policies live when the version starts
			at = max(now, get_datetime(v.effective_from)) if v.effective_from else now
			try:
				rebuilt = contracts.build_terms(frappe.get_doc("TEX Contract Version", v.name), at=at)
			except frappe.ValidationError as e:
				report["cannot_rebuild"].append({**head, "reason": str(e)})
				continue
			errors = republish_errors(rebuilt)
			if errors:
				report["cannot_rebuild"].append({**head, "reason": "publishing would be refused: "
				                                 + "; ".join(errors[:examples])})
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
