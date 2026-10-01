"""A TEX hotel's first tax policy (G-20, ADR-031).

A hotel's taxes are effective-dated once it has a TEX Tax Policy. ``seed`` gives a hotel
that has none a first revision holding exactly the taxes it sells with now (its custom
table or its localization pack), so the migration and every hotel that becomes a TEX
hotel later start from what was really charged.
"""

from __future__ import annotations

import frappe

from kamra.tex.commercial import context, revisions
from kamra.tex.pricing.model import Unsellable


def _fx_policy_or_none(frm: str, to: str, property: str):
	"""The pair's FX policy, for the seed's note. A pair with two live policies (O-11) has a policy: it
	is not "missing", and the seed never stops for it."""
	try:
		return context.fx_policy(frm, to, property, frappe.utils.now_datetime())
	except Unsellable:
		return True


def _key(r) -> tuple:
	return (r.code, r.kind.value, r.rate, r.amount, tuple(sorted(r.applies_to)), r.compound, r.order, r.slabs)


def current_rules(property: str) -> tuple[list[dict] | None, str]:
	"""(TEX Tax Rule rows the hotel sells with now, why not). ``None`` when they cannot be one
	hotel-wide policy: slab rates, or rates that differ by room type (some packs)."""
	from kamra.tex_commercial.doctype.tex_tax_policy.tex_tax_policy import APPLIES_TO

	room_types = frappe.get_all("Room Type", filters={"property": property}, pluck="name", order_by="name")
	variants = {tuple(_key(r) for r in context.tax_rules(property, rt)) for rt in room_types or [None]}
	if len(variants) > 1:
		return None, "tax rates differ by room type"
	rules = context.tax_rules(property, room_types[0] if room_types else None)
	if any(r.slabs for r in rules):
		return None, "slab tax rates"
	rows, dropped = [], []
	for r in rules:
		tokens = [t for t in sorted(r.applies_to) if t in APPLIES_TO]
		fixed = r.kind.value != "PERCENT"
		if not tokens or (fixed and "ACCOMMODATION" not in tokens):
			dropped.append(r.code)      # it matched nothing priced, so it never charged anything
			continue
		rows.append({"code": r.code, "tax_name": r.name, "kind": r.kind.value, "rate": r.rate, "amount": r.amount,
		             "applies_to": ",".join(tokens), "compound": 0 if fixed else int(r.compound),
		             "sort_order": r.order})
	return rows, (f"dropped {', '.join(dropped)} (applied to nothing)" if dropped else "")


def sell_currencies(property: str) -> set[str]:
	"""What the hotel's contracts that sell (or sold) stays sell in."""
	return set(frappe.db.sql_list("""SELECT DISTINCT IFNULL(NULLIF(sell_currency, ''), contract_currency)
	                                 FROM `tabTEX Contract` WHERE property=%s AND status IN ('Active', 'Suspended')""",
	                              property)) - {None, ""}


def levy_currency(property: str) -> str | None:
	"""The currency a hotel's fixed levies were charged in: the one its selling contracts sell
	in when they all sell in one, else the hotel's currency."""
	ccys = sell_currencies(property)
	return ccys.pop() if len(ccys) == 1 else frappe.db.get_value("Property", property, "currency") or None


def ensure(property: str) -> str | None:
	"""``seed`` for hooks: a hotel that has just become a TEX hotel gets its policy; a failure
	never blocks the save that triggered it (the Error Log says why)."""
	frappe.db.savepoint("tex_tax_seed")
	try:
		return seed(property)
	except Exception:
		frappe.db.rollback(save_point="tex_tax_seed")
		frappe.log_error(title=f"TEX tax policy not created for {property}")
		return None


def seed(property: str, *, at=None, backdate: bool = False) -> str | None:
	"""Create and activate the hotel's first tax policy from its current taxes, unless it has
	a live one already. Returns the new policy, or None (with the reason logged)."""
	if frappe.db.exists("TEX Tax Policy", {"property": property, "tex_status": ("in", ["Active", "Superseded"])}) \
			or context.policy_started(property):
		return None       # it has a policy (live or scheduled), or had one (a cancelled schedule does not count)
	frappe.clear_document_cache("Property", property)     # what is stored, not a stale cached copy
	rows, note = current_rules(property)
	if rows is None:
		frappe.log_error(title=f"TEX tax policy not created for {property}", message=note)
		return None
	source = (context.tax_rules(property)[0].source or "") if rows else "no taxes"
	currency = levy_currency(property)
	if any(r["kind"] != "PERCENT" for r in rows):
		# before, a fixed amount was charged as that number of whatever currency the stay was
		# sold in; it now has one currency, converted for other sales
		note = " ".join(x for x in (note, f"Fixed levies are now in {currency}.") if x)
		others = sorted(c for c in sell_currencies(property) if c != currency)
		if others:
			missing = [c for c in others if not _fx_policy_or_none(currency, c, property)]
			frappe.log_error(title=f"TEX tax policy of {property}: fixed levies in {currency}",
			                 message=f"Contracts also sell in {', '.join(others)}; levies are converted from "
			                         f"{currency}. Missing FX policies: {', '.join(missing) or 'none'}.")
	doc = frappe.get_doc({
		"doctype": "TEX Tax Policy", "policy_name": f"{property} taxes", "property": property,
		"currency": currency, "rules": rows,
		"description": " ".join(x for x in (f"The taxes the hotel sold with ({source.split(':')[0]}).", note) if x),
	})
	doc.insert(ignore_permissions=True)
	revisions.activate("TEX Tax Policy", doc.name, at=at, backdate=backdate)
	return doc.name
