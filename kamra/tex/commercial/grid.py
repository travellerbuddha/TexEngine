"""Rates & inventory grid service (R-36, Phase 5).

* Restrictions and inventory are operational: bulk edits upsert daily cells
  immediately (audited).
* Rates are contract terms: a rate edit over a date range is applied to the
  contract's DRAFT version as a *period split* — for each underlying period segment
  a clone period (higher priority, optional weekday mask) is created with copies of
  all its period-scoped rules, then the selected rooms get their new absolute unit.
  Unselected derived rooms keep following their base room (R-10). Nothing is sold at
  the new rate until the draft is published.
"""

from __future__ import annotations

from datetime import date, timedelta

import frappe
from frappe import _
from frappe.utils import getdate

from kamra.tex.availability import repository as avail
from kamra.tex.availability.restrictions import FIELDS, RestrictionScope, effective
from kamra.tex.commercial import contracts
from kamra.tex.commercial.revisions import as_of
from kamra.tex.money import D, quantize, to_str
from kamra.tex.pricing import rooms as room_math
from kamra.tex.pricing.enums import Op
from kamra.tex.pricing.model import Unsellable
from kamra.tex.pricing.ops import apply_op
from kamra.tex.security import scope
from kamra.tex.security.audit import audit
from kamra.tex.security.changes import SEP, cells_diff
from kamra.tex_commercial.doctype.tex_ari_restriction.tex_ari_restriction import scope_key

WD = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")
RESTRICTION_EDIT = {"stop_sell", "stop_sell_mode", "min_los", "max_los", "cta", "ctd", "release_days",
                    "min_advance", "max_advance"}
RESTRICTION_TEXT = {"stop_sell", "stop_sell_mode", "cta", "ctd"}      # blank = "", the others 0
INVENTORY_EDIT = {"closed", "manual_adjustment", "oversell_limit"}


def _days(start: date, end: date, weekdays: list[int] | None) -> list[date]:
	out, d = [], start
	while d <= end:
		if not weekdays or d.weekday() in weekdays:
			out.append(d)
		d += timedelta(days=1)
	return out


def _editable_version(contract: str) -> tuple[str | None, str | None]:
	"""(draft, active) version names of a contract."""
	draft = frappe.db.get_value("TEX Contract Version", {"contract": contract, "status": "Draft"}, "name")
	active = contracts.active_version_header(contract, frappe.utils.now_datetime())
	return draft, active.version_id if active else None


# ─── read ────────────────────────────────────────────────────────────────


def grid(property: str, start, days: int = 14, contract: str | None = None, market: str | None = None,
         channel: str | None = None, rate_plan: str | None = None) -> dict:
	scope.require("price.view", property)
	if contract and frappe.db.get_value("TEX Contract", contract, "property") != property:
		frappe.throw(_("This contract belongs to another hotel."))
	# contract rates are cost: only for who may see cost (G-11)
	show_cost = scope.has_capability("price.view_cost", property)
	start = getdate(start)
	days = max(1, min(int(days or 14), 62))
	dates = [start + timedelta(days=i) for i in range(days)]
	end = dates[-1]
	room_types = frappe.get_all("Room Type", filters={"property": property, "disabled": 0},
	                            fields=["name", "room_type_name"], order_by="room_type_name asc")
	cells = avail.restriction_cells(property, start, end)
	terms = draft_terms = None
	version = draft = None
	if contract:
		draft, version = _editable_version(contract)
		if version:
			terms = contracts.load_terms(version)
		if draft:
			draft_terms = contracts.build_terms(frappe.get_doc("TEX Contract Version", draft))
	now = frappe.utils.now_datetime()
	promos = [p for p in as_of("TEX Promotion", now, fields=("name", "promotion_name", "property", "stay_from",
	                                                         "stay_to", "room_types", "tex_status"))
	          if not p.property or p.property == property]
	sale = now.date()
	out_rows = []
	for rt in room_types:
		sc = RestrictionScope(room_type=rt.name, contract=contract, market=market, rate_plan=rate_plan,
		                      channel=channel)
		eff = effective(cells, sc, dates)
		own = {c.day: c for c in cells if (c.room_type, c.contract, c.market, c.rate_plan, c.channel) ==
		       (rt.name, contract, market, rate_plan, channel)}
		pdays, allot = avail.pool_days(property, rt.name, dates)
		from kamra.tex.availability import inventory_math as inv

		row = {"room_type": rt.name, "name": rt.room_type_name, "cells": []}
		for pd, d in zip(pdays, dates, strict=True):
			da = inv.day_availability(pd, allot, contract, sale)
			e = eff[d]
			cell = {
				"date": d.isoformat(), "available": da.available, "capacity": da.capacity, "sold": da.sold,
				"closed": pd.closed, "manual_adjustment": pd.manual_adjustment,
				"stop_sell": e.stop_sell, "min_los": e.min_los, "max_los": e.max_los, "cta": e.cta, "ctd": e.ctd,
				"release_days": e.release_days, "own": {f: getattr(own[d], f) for f in FIELDS} if d in own else None,
				"promo": any((not p.stay_from or getdate(p.stay_from) <= d) and (not p.stay_to or getdate(p.stay_to)
				                                                                   >= d)
				             and (not p.room_types or rt.name in p.room_types) for p in promos),
			}
			for label, t in (("rate", terms), ("draft_rate", draft_terms)):
				if show_cost and t and rt.name in t.rooms:
					period = room_math.period_for(t, d)
					try:
						cell[label] = to_str(quantize(room_math.room_unit(t, rt.name, period), t.currency)) \
							if period else None
					except Unsellable:
						cell[label] = None
			row["cells"].append(cell)
		out_rows.append(row)
	return {"property": property, "start": start.isoformat(), "days": days, "dates": [d.isoformat() for d in dates],
	        "contract": contract, "version": version, "draft": draft, "rates_hidden": not show_cost,
	        "basis": (terms or draft_terms).basis.value if (terms or draft_terms) else None,
	        "currency": (terms or draft_terms).currency if (terms or draft_terms) else None, "rows": out_rows}


# ─── write: restrictions & inventory ─────────────────────────────────────


def _clean_restriction(changes: dict) -> dict:
	out = {}
	for k, v in changes.items():
		if k not in RESTRICTION_EDIT:
			continue
		if k == "stop_sell" and v not in ("", "STOP", "OPEN", None):
			frappe.throw(_("Stop sell must be STOP, OPEN or blank."))
		if k in ("cta", "ctd") and v not in ("", "Yes", "No", None):
			frappe.throw(_("CTA/CTD must be Yes, No or blank."))
		if k == "stop_sell_mode" and v not in ("", "STAY_THROUGH", "ARRIVAL", "DEPARTURE", None):
			frappe.throw(_("Invalid stop-sell mode."))
		if k in ("min_los", "max_los", "release_days", "min_advance", "max_advance"):
			v = int(v or 0)
			if v < 0 or v > 365:
				frappe.throw(_("{0} must be between 0 and 365.").format(k))
		out[k] = v or ("" if k in RESTRICTION_TEXT else 0)
	return out


def _blank_restriction(fields) -> dict:
	return {f: "" if f in RESTRICTION_TEXT else 0 for f in fields}


def bulk_update(property: str, start, end, *, room_types: list[str], weekdays: list[int] | None = None,
                contract: str | None = None, market: str | None = None, channel: str | None = None,
                rate_plan: str | None = None, restrictions: dict | None = None, inventory: dict | None = None,
                rate: dict | None = None) -> dict:
	start, end = getdate(start), getdate(end)
	if end < start or (end - start).days > 400:
		frappe.throw(_("Choose a date range of at most 400 days."))
	valid_rts = set(frappe.get_all("Room Type", filters={"property": property}, pluck="name"))
	if not room_types or not set(room_types) <= valid_rts:
		frappe.throw(_("Choose room types of this hotel."))
	if contract and frappe.db.get_value("TEX Contract", contract, "property") != property:
		frappe.throw(_("The contract belongs to another hotel."))
	dates = _days(start, end, weekdays)
	summary = {"dates": len(dates), "rooms": len(room_types)}
	# each cell's old value next to the new one, bounded (G-74, ADR-053)
	collections = {}

	if restrictions:
		scope.require("restriction.edit", property)
		changes = _clean_restriction(restrictions)
		cells = []
		for rt in room_types:
			for d in dates:
				vals = {"property": property, "room_type": rt, "contract": contract, "market": market,
				        "rate_plan": rate_plan, "sales_channel": channel, "restriction_date": d}
				key = scope_key(vals)
				name = frappe.db.get_value("TEX ARI Restriction", {"scope_key": key})
				doc = frappe.get_doc("TEX ARI Restriction", name) if name else frappe.get_doc(
					{"doctype": "TEX ARI Restriction", **vals})
				old = {f: doc.get(f) for f in changes} if name else _blank_restriction(changes)
				doc.update(changes)
				if name and all(not doc.get(f) for f in RESTRICTION_EDIT):
					frappe.delete_doc("TEX ARI Restriction", name, ignore_permissions=True)
				else:
					doc.save(ignore_permissions=True) if name else doc.insert(ignore_permissions=True)
				cells.append((f"{rt}{SEP}{d}", old, changes))
		summary["restriction_cells"] = len(cells)
		summary["restrictions"] = changes
		collections["restrictions"] = cells_diff(cells)

	if inventory:
		scope.require("inventory.edit", property)
		from kamra.tex_commercial.doctype.tex_inventory_day.tex_inventory_day import inventory_day_name

		edit = {k: int(v or 0) for k, v in inventory.items() if k in INVENTORY_EDIT}
		pools = sorted({avail.pool_of(rt)[0] for rt in room_types})
		cells = []
		for pool in pools:
			for d in dates:
				name = inventory_day_name(pool, d)
				doc = frappe.get_doc("TEX Inventory Day", name) if frappe.db.exists("TEX Inventory Day", name) \
					else frappe.get_doc({"doctype": "TEX Inventory Day", "property": property, "room_type": pool,
					                     "inventory_date": d})
				old = {k: int(doc.get(k) or 0) for k in edit}
				for k, v in edit.items():
					doc.set(k, v)
				doc.save(ignore_permissions=True) if not doc.is_new() else doc.insert(ignore_permissions=True)
				cells.append((f"{pool}{SEP}{d}", old, edit))
		summary["inventory"] = {k: v for k, v in inventory.items() if k in INVENTORY_EDIT}
		collections["inventory"] = cells_diff(cells)

	if rate:
		if not contract:
			frappe.throw(_("Choose the contract whose rates you are editing."))
		summary["rate"] = apply_rate_change(contract, room_types, start, end, weekdays, rate.get("op"),
		                                    rate.get("value"))
		collections["rates"] = cells_diff(summary["rate"].pop("_cells"))

	audit("grid.bulk_update", property=property, new={"start": str(start), "end": str(end), "weekdays": weekdays,
	                                                  "room_types": room_types, "contract": contract,
	                                                  "market": market, "channel": channel,
	                                                  "rate_plan": rate_plan, **summary, "collections": collections})
	return summary


# ─── write: rates (draft period split) ───────────────────────────────────


def apply_rate_change(contract: str, room_types: list[str], start: date, end: date, weekdays: list[int] | None,
                      op: str, value) -> dict:
	prop = frappe.db.get_value("TEX Contract", contract, "property")
	scope.require("contract.edit", prop)
	if op not in ("ABSOLUTE", "ADJUST_PERCENT", "ADD", "SUBTRACT"):
		frappe.throw(_("Rate change must be absolute, a percentage or an amount."))
	draft, _active = _editable_version(contract)
	if not draft:
		draft = contracts.new_draft(contract)
	v = frappe.get_doc("TEX Contract Version", draft)
	terms = contracts.build_terms(v)
	mask = frozenset(weekdays) if weekdays else None

	# segment the range by underlying period
	segments: list[tuple[object, date, date]] = []
	d = start
	while d <= end:
		p = room_math.period_for(terms, d)
		if p is None:
			frappe.throw(_("No stay period covers {0}; add one first.").format(d))
		seg_start = d
		while d + timedelta(days=1) <= end and room_math.period_for(terms, d + timedelta(days=1)) == p:
			d += timedelta(days=1)
		segments.append((p, seg_start, d))
		d += timedelta(days=1)

	created, cells = [], []
	for idx, (p, s, e) in enumerate(segments):
		code = f"G{s.strftime('%y%m%d')}{e.strftime('%m%d')}{'W' if mask else ''}{idx}"
		n = 2
		while any(x.period_code == code for x in v.periods):
			code, n = f"{code[:-1]}{n}", n + 1
		days_mask = (mask & p.weekdays) if (mask and p.weekdays) else (mask or p.weekdays)
		v.append("periods", {"period_code": code, "period_name": f"{p.name} · edit {s:%d %b}–{e:%d %b}",
		                     "start_date": s, "end_date": e,
		                     "weekdays": ",".join(WD[i] for i in sorted(days_mask)) if days_mask else None,
		                     "adjustment_op": p.adjustment_op.value if p.adjustment_op else None,
		                     "adjustment_value": p.adjustment_value, "priority": int(p.priority) + 100})
		# clone every rule scoped to the underlying period
		for r in list(v.period_rates):
			if (r.period_code or "") == p.code and r.room_type not in room_types:
				v.append("period_rates", {"room_type": r.room_type, "period_code": code, "op": r.op, "value": r.value,
				                          "base_room_type": r.base_room_type})
		for r in list(v.occupancy_rules):
			if (r.period_code or "") == p.code:
				v.append("occupancy_rules", {**{k: r.get(k) for k in ("target", "position", "age_band", "combination",
				                                                     "room_type", "op", "value", "is_override",
				                                                     "note")}, "period_code": code})
		for r in list(v.boards):
			if (r.period_code or "") == p.code:
				v.append("boards", {**{k: r.get(k) for k in ("board", "is_base", "op", "adult_amount", "child_percent",
				                                            "infant_free", "room_type", "label")}, "period_code": code})
		# selected rooms: explicit new unit
		for rt in room_types:
			if rt not in terms.rooms:
				continue
			current = room_math.room_unit(terms, rt, p)
			new = D(value) if op == "ABSOLUTE" else apply_op(Op(op), D(value), reference=current, current=current)
			if new < 0:
				frappe.throw(_("A rate cannot be negative."))
			v.append("period_rates", {"room_type": rt, "period_code": code, "op": "ABSOLUTE",
			                          "value": quantize(new, terms.currency)})
			# the draft's unit before and after, per room and date range (the audit's cells)
			cells.append((f"{rt}{SEP}{s}/{e}", {"unit": to_str(quantize(current, terms.currency))},
			              {"unit": to_str(quantize(new, terms.currency))}))
		created.append(code)
	v.flags.tex_audit_reason = "ARI grid rate change"
	v.save(ignore_permissions=True)
	# ``_cells`` is for the caller's audit only, never part of the response
	return {"draft": draft, "periods": created, "note": _("Saved to the draft — publish to sell at the new rates."),
	        "_cells": cells}
