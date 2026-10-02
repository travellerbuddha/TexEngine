"""Rates & inventory grid service (R-36, Phase 5).

* Restrictions and inventory are operational: bulk edits upsert daily cells
  immediately (audited).
* Rates are contract terms: a rate edit over a date range is applied to the
  contract's DRAFT version as a plan of period edits (``pricing.ratesplit``, O-9,
  G-47, ADR-069): a period pricing edited nights only is edited in place, any other
  gets one clone per part of edited nights (above every period of its kind it
  overlaps) with copies of its period-scoped rules; the selected rooms get their new
  absolute unit. Unselected derived rooms keep following their base room (R-10).
  Nothing is sold at the new rate until the draft is published.
"""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal, InvalidOperation

import frappe
from frappe import _
from frappe.utils import getdate

from kamra.tex.availability import repository as avail
from kamra.tex.availability import restrictions as rs
from kamra.tex.availability.restrictions import FIELDS, RestrictionScope, effective
from kamra.tex.commercial import contracts
from kamra.tex.commercial.revisions import as_of
from kamra.tex.money import minor_units, quantize, to_str
from kamra.tex.pricing import ratesplit, validate
from kamra.tex.pricing import rooms as room_math
from kamra.tex.pricing.enums import Op
from kamra.tex.pricing.model import Unsellable
from kamra.tex.security import scope
from kamra.tex.security.audit import audit
from kamra.tex.security.changes import SEP, cells_diff
from kamra.tex_commercial.doctype.tex_ari_restriction.tex_ari_restriction import scope_key

WD = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")
RESTRICTION_EDIT = {"stop_sell", "stop_sell_mode", "min_los", "max_los", "cta", "ctd", "release_days",
                    "min_advance", "max_advance", "book_from", "book_to"}
RESTRICTION_TEXT = {"stop_sell", "stop_sell_mode", "cta", "ctd"}      # blank = "", dates None, the others 0
RESTRICTION_DATES = {"book_from", "book_to"}
INVENTORY_EDIT = {"closed", "manual_adjustment", "oversell_limit"}
RATE_OPS = ("ABSOLUTE", "ADJUST_PERCENT", "ADD", "SUBTRACT")
MAX_RATE_CHANGES = 400      # groups of nights in one grid edit (a 31-day month of 12 rooms, each night its own)


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


def _channel_scope(channel: str | None, channel_scope: str | None) -> str | None:
	if channel_scope and channel_scope not in rs.CHANNEL_SCOPES:
		frappe.throw(_("Choose the Booking Engine, the Call Center or both."))
	if channel and channel_scope:
		frappe.throw(_("Choose one sales channel or a channel scope, not both."))
	return channel_scope or None


def _view(cells: list, room_type: str | None, contract, market, rate_plan, channel, channel_scope):
	"""(cells, scope) the grid shows a row with: as sold on ``channel``, or — for a channel scope —
	what applies to every channel of that scope (G-48)."""
	if not channel_scope:
		return cells, avail.scope_for(room_type, contract, market, rate_plan, channel)
	surfaces = rs.CHANNEL_SCOPES[channel_scope]
	# a cell applies to the whole scope when it covers every surface of it (and names no channel)
	view = [c for c in cells if not c.channel and (not c.channel_scope or surfaces <= rs.CHANNEL_SCOPES.get(
		c.channel_scope, frozenset()))]
	return view, RestrictionScope(room_type=room_type, contract=contract, market=market, rate_plan=rate_plan,
	                              surface=sorted(surfaces)[0])


def _iso(v):
	return v.isoformat() if hasattr(v, "isoformat") else v


# ─── read ────────────────────────────────────────────────────────────────


def grid(property: str, start, days: int = 14, contract: str | None = None, market: str | None = None,
         channel: str | None = None, rate_plan: str | None = None, *, channel_scope: str | None = None) -> dict:
	"""Rows: one per room type, and first a hotel-level row (``room_type`` None, ``level``
	"hotel") with the cells that name no room type — hotel-wide, or market-wide with a market
	(G-48). A room row's values are what applies to it, whatever the level they are set at."""
	scope.require("price.view", property)
	if contract and frappe.db.get_value("TEX Contract", contract, "property") != property:
		frappe.throw(_("This contract belongs to another hotel."))
	channel_scope = _channel_scope(channel, channel_scope)
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

	def restriction_values(room_type: str | None) -> tuple[dict, dict]:
		view, sc = _view(cells, room_type, contract, market, rate_plan, channel, channel_scope)
		own = {c.day: c for c in cells if (c.room_type, c.contract, c.market, c.rate_plan, c.channel,
		                                   c.channel_scope) == (room_type, contract, market, rate_plan, channel,
		                                                        channel_scope)}
		return effective(view, sc, dates), own

	def restriction_cell(e, own_cell) -> dict:
		return {"stop_sell": e.stop_sell, "min_los": e.min_los, "max_los": e.max_los, "cta": e.cta, "ctd": e.ctd,
		        "release_days": e.release_days, "min_advance": e.min_advance, "max_advance": e.max_advance,
		        "book_from": _iso(e.book_from), "book_to": _iso(e.book_to),
		        "own": {f: _iso(getattr(own_cell, f)) for f in FIELDS} if own_cell else None}

	# the hotel-level row: cells without a room type (hotel- or market-wide), restrictions only
	eff, own = restriction_values(None)
	out_rows.append({"room_type": None, "name": _("All room types"), "level": "hotel",
	                 "cells": [{"date": d.isoformat(), "available": None, "capacity": None, "sold": None,
	                            "closed": False, "manual_adjustment": 0, "promo": False,
	                            **restriction_cell(eff[d], own.get(d))} for d in dates]})
	for rt in room_types:
		eff, own = restriction_values(rt.name)
		pdays, allot = avail.pool_days(property, rt.name, dates)
		from kamra.tex.availability import inventory_math as inv

		row = {"room_type": rt.name, "name": rt.room_type_name, "level": "room", "cells": []}
		for pd, d in zip(pdays, dates, strict=True):
			da = inv.day_availability(pd, allot, contract, sale)
			cell = {
				"date": d.isoformat(), "available": da.available, "capacity": da.capacity, "sold": da.sold,
				"closed": pd.closed, "manual_adjustment": pd.manual_adjustment,
				**restriction_cell(eff[d], own.get(d)),
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
	        "contract": contract, "channel_scope": channel_scope, "version": version, "draft": draft,
	        "rates_hidden": not show_cost,
	        "basis": (terms or draft_terms).basis.value if (terms or draft_terms) else None,
	        "currency": (terms or draft_terms).currency if (terms or draft_terms) else None,
	        # how many decimals a typed price has in that currency (the grid reads "1.500" by it)
	        "minor_units": minor_units((terms or draft_terms).currency) if (terms or draft_terms) else 2,
	        "rows": out_rows}


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
		if k in RESTRICTION_DATES:
			try:
				v = getdate(v) if v not in (None, "") else None
			except Exception:
				frappe.throw(_("The booking window needs dates."))
			out[k] = v
			continue
		out[k] = v or ("" if k in RESTRICTION_TEXT else 0)
	if out.get("book_from") and out.get("book_to") and out["book_from"] > out["book_to"]:
		frappe.throw(_("The booking window ends before it starts."))
	return out


def _blank_restriction(fields) -> dict:
	return {f: None if f in RESTRICTION_DATES else ("" if f in RESTRICTION_TEXT else 0) for f in fields}


def bulk_update(property: str, start, end, *, room_types: list[str], weekdays: list[int] | None = None,
                contract: str | None = None, market: str | None = None, channel: str | None = None,
                rate_plan: str | None = None, restrictions: dict | None = None, inventory: dict | None = None,
                rate: dict | None = None, channel_scope: str | None = None, hotel_level: bool = False) -> dict:
	"""``hotel_level``: one restriction cell per date without a room type — hotel-wide, or
	market-wide with a market (G-48); inventory and rates are per room type. ``channel_scope``:
	the Booking Engine, the Call Center or both, instead of one sales channel."""
	start, end = getdate(start), getdate(end)
	if end < start or (end - start).days > 400:
		frappe.throw(_("Choose a date range of at most 400 days."))
	channel_scope = _channel_scope(channel, channel_scope)
	if hotel_level:
		if inventory or rate:
			frappe.throw(_("Inventory and rates are set per room type: choose room types."))
		targets: list[str | None] = [None]
	else:
		valid_rts = set(frappe.get_all("Room Type", filters={"property": property}, pluck="name"))
		if not room_types or not set(room_types) <= valid_rts:
			frappe.throw(_("Choose room types of this hotel."))
		targets = list(room_types)
	if contract and frappe.db.get_value("TEX Contract", contract, "property") != property:
		frappe.throw(_("The contract belongs to another hotel."))
	dates = _days(start, end, weekdays)
	summary = {"dates": len(dates), "rooms": len(targets)}
	# each cell's old value next to the new one, bounded (G-74, ADR-053)
	collections = {}

	if restrictions:
		scope.require("restriction.edit", property)
		changes = _clean_restriction(restrictions)
		cells = []
		for rt in targets:
			for d in dates:
				vals = {"property": property, "room_type": rt, "contract": contract, "market": market,
				        "rate_plan": rate_plan, "sales_channel": channel, "channel_scope": channel_scope,
				        "restriction_date": d}
				# the key the cell's controller stores (the same function, on the same values): a set
				# or a clear finds the cell of this exact scope, whatever set it
				name = frappe.db.get_value("TEX ARI Restriction", {"scope_key": scope_key(vals)})
				if name is None and all(not v for v in changes.values()):
					# a clear where no cell is set: nothing to clear, and no empty cell is written
					cells.append((f"{rt or '*'}{SEP}{d}", _blank_restriction(changes), changes))
					continue
				doc = frappe.get_doc("TEX ARI Restriction", name) if name else frappe.get_doc(
					{"doctype": "TEX ARI Restriction", **vals})
				old = {f: doc.get(f) for f in changes} if name else _blank_restriction(changes)
				doc.update(changes)
				if name and all(not doc.get(f) for f in RESTRICTION_EDIT):
					# every restriction of the cell blank: the cell goes (never left behind empty)
					frappe.delete_doc("TEX ARI Restriction", name, ignore_permissions=True)
				else:
					doc.save(ignore_permissions=True) if name else doc.insert(ignore_permissions=True)
				cells.append((f"{rt or '*'}{SEP}{d}", old, changes))
		summary["restriction_cells"] = len(cells)
		summary["restrictions"] = {k: _iso(v) for k, v in changes.items()}
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
	                                                  "room_types": room_types, "hotel_level": bool(hotel_level),
	                                                  "contract": contract, "market": market, "channel": channel,
	                                                  "channel_scope": channel_scope, "rate_plan": rate_plan,
	                                                  **summary, "collections": collections})
	return summary


# ─── write: rates (draft period split) ───────────────────────────────────


def _copy_rules(v, source: str, code: str, selected: set[str]) -> None:
	"""The source period's rules, onto its clone ``code`` (as the grid always copied them): the
	unselected rooms' own rules, the occupancy rules and the boards."""
	def of(rows):
		return [r for r in rows if (r.period_code or "").strip() == source]

	for r in of(v.period_rates):
		if r.room_type not in selected:
			v.append("period_rates", {"room_type": r.room_type, "period_code": code, "op": r.op, "value": r.value,
			                          "base_room_type": r.base_room_type})
	for r in of(v.occupancy_rules):
		v.append("occupancy_rules", {**{k: r.get(k) for k in ("target", "position", "age_band", "combination",
		                                                     "room_type", "op", "value", "is_override", "note")},
		                             "period_code": code})
	for r in of(v.boards):
		v.append("boards", {**{k: r.get(k) for k in ("board", "is_base", "op", "adult_amount", "child_percent",
		                                            "infant_free", "room_type", "label")}, "period_code": code})


def _set_unit(v, room_type: str, code: str, unit) -> None:
	"""``room_type``'s rule in period ``code`` becomes the ABSOLUTE ``unit`` (its own row, else a new one)."""
	rows = [r for r in v.period_rates if r.room_type == room_type and (r.period_code or "").strip() == code]
	for r in rows[1:]:
		v.remove(r)
	if rows:
		rows[0].update({"op": "ABSOLUTE", "value": unit, "base_room_type": None})
	else:
		v.append("period_rates", {"room_type": room_type, "period_code": code, "op": "ABSOLUTE", "value": unit})


def _write_plan(v, steps, taken: set[str], alias: dict[str, str]) -> tuple[list[str], list[str]]:
	"""Write a ``ratesplit.plan`` into the draft document ``v`` (in memory): a period that prices
	edited nights only is edited in place, any other gets its clone (with the source's rules), and
	the selected rooms their new ABSOLUTE unit. ``taken`` (period codes) and ``alias`` (clone →
	the period it was cut from, through earlier clones) are updated. → (edited period codes, the
	clones' codes in step order: what ``ratesplit.apply`` names them in the terms)."""
	edited, clones = [], []
	for idx, s in enumerate(steps):
		code = s.source.code
		if s.clone:
			code = ratesplit.clone_code(s, idx, taken)
			taken.add(code)
			clones.append(code)
			alias[code] = alias.get(s.source.code, s.source.code)
			v.append("periods", {"period_code": code, "period_name": ratesplit.clone_name(s),
			                     "start_date": s.start, "end_date": s.end,
			                     "weekdays": ",".join(WD[i] for i in sorted(s.weekdays)) if s.weekdays else None,
			                     "adjustment_op": s.source.adjustment_op.value if s.source.adjustment_op else None,
			                     "adjustment_value": s.source.adjustment_value, "priority": s.priority})
			_copy_rules(v, s.source.code, code, {u.room_type for u in s.units})
		for u in s.units:
			_set_unit(v, u.room_type, code, u.new)
		edited.append(code)
	return edited, clones


def _plan_or_throw(terms, start, end, weekdays, room_types, op, value):
	try:
		return ratesplit.plan(terms, getdate(start), getdate(end), weekdays, room_types, Op(op), value)
	except ratesplit.RateSplitError as e:
		if e.code == "NO_PERIOD":
			frappe.throw(_("No stay period covers {0}; add one first.").format(e.ref["night"]))
		if e.code == "NO_NIGHTS":
			frappe.throw(_("No night of this range is on the chosen weekdays."))
		frappe.throw(_("A rate cannot be negative."))


def apply_rate_change(contract: str, room_types: list[str], start: date, end: date, weekdays: list[int] | None,
                      op: str, value) -> dict:
	"""The draft's rates changed as ``ratesplit.plan`` says (O-9, G-47, ADR-069): a period that
	prices edited nights only is edited in place, any other gets one clone per part. The draft is
	validated before and after: a change that adds an ERROR is refused and nothing is saved."""
	prop = frappe.db.get_value("TEX Contract", contract, "property")
	scope.require("contract.edit", prop)
	if op not in RATE_OPS:
		frappe.throw(_("Rate change must be absolute, a percentage or an amount."))
	draft, _active = _editable_version(contract)
	if not draft:
		draft = contracts.new_draft(contract)
	v = frappe.get_doc("TEX Contract Version", draft)
	terms = contracts.build_terms(v)
	steps = _plan_or_throw(terms, start, end, weekdays, room_types, op, value)
	before = validate.validate_terms(terms)

	taken = {(p.period_code or "").strip() for p in v.periods}
	alias: dict[str, str] = {}
	edited, _clones = _write_plan(v, steps, taken, alias)
	# the draft's unit before and after, per room and part (the audit's cells)
	cells = [(f"{u.room_type}{SEP}{a}/{b}", {"unit": to_str(u.current)}, {"unit": to_str(u.new)})
	         for s in steps for u in s.units for a, b in s.parts]

	frappe.db.savepoint("tex_grid_rate")
	v.flags.tex_audit_reason = "ARI grid rate change"
	v.save(ignore_permissions=True)
	added = ratesplit.added_errors(before, validate.validate_terms(contracts.build_terms(v)), alias)
	if added:
		frappe.db.rollback(save_point="tex_grid_rate")
		frappe.throw(_("This rate change would give the draft errors: {0}").format(
			"; ".join(i.message for i in added[:5])), title=_("Rate change refused"))
	# ``_cells`` is for the caller's audit only, never part of the response
	return {"draft": draft, "periods": edited, "note": _("Saved to the draft — publish to sell at the new rates."),
	        "_cells": cells}


# ─── write: several rate edits as one (UX revision 2026-10) ──────────────


def _rate_cells(terms, changes) -> list[dict]:
	"""Each change planned on ``terms`` (the draft as it is, or the version a new draft copies) and
	read as the absolute units it sets, per room and run of nights. A relative change (+10 %) is
	worked out from the price every night has before ANY of the changes: a derived room selected
	with its base is changed once, whatever the order of the changes. A night changed twice is
	refused (the grid sends each changed cell once)."""
	if not isinstance(changes, list) or not changes:
		frappe.throw(_("Choose the prices to change."))
	if len(changes) > MAX_RATE_CHANGES:
		frappe.throw(_("Change at most {0} groups of prices at once.").format(MAX_RATE_CHANGES))
	out, seen = [], set()
	for ch in changes:
		if not isinstance(ch, dict):
			frappe.throw(_("Choose the prices to change."))
		op, value = ch.get("op"), ch.get("value")
		if op not in RATE_OPS:
			frappe.throw(_("Rate change must be absolute, a percentage or an amount."))
		try:
			amount = Decimal(str(value).strip())
		except (InvalidOperation, ValueError):
			amount = None
		if amount is None or not amount.is_finite() or value is None or str(value).strip() == "":
			frappe.throw(_("Rate change: a number is required."))
		rts = ch.get("room_types")
		if not isinstance(rts, list) or not rts or not all(isinstance(r, str) for r in rts):
			frappe.throw(_("Choose room types of this contract."))
		for rt in rts:
			if rt not in terms.rooms:
				frappe.throw(_("{0} is not a room of this contract.").format(rt))
		# never getdate(None): it is today
		if not ch.get("start") or not ch.get("end"):
			frappe.throw(_("Choose the dates to change."))
		try:
			start, end = getdate(ch.get("start")), getdate(ch.get("end"))
		except Exception:
			frappe.throw(_("Choose the dates to change."))
		if not start or not end or end < start or (end - start).days > 400:
			frappe.throw(_("Choose a date range of at most 400 days."))
		for s in _plan_or_throw(terms, start, end, None, rts, op, amount):
			for u in s.units:
				for a, b in s.parts:
					d = a
					while d <= b:
						if (u.room_type, d) in seen:
							frappe.throw(_("{0} on {1} is changed twice: change each night once.").format(
								u.room_type, d.isoformat()))
						seen.add((u.room_type, d))
						d += timedelta(days=1)
					out.append({"room_type": u.room_type, "start": a, "end": b, "current": u.current, "new": u.new})
	return out


def _groups(cells: list[dict]) -> list[tuple[date, date, Decimal, list[str]]]:
	"""The cells as absolute edits: one per run of nights and new unit, with every room it sets."""
	groups: dict[tuple, list[str]] = {}
	for c in cells:
		groups.setdefault((c["start"], c["end"], c["new"]), []).append(c["room_type"])
	return [(a, b, new, rts) for (a, b, new), rts in groups.items()]


def rate_changes(property: str, contract: str, changes, *, apply: bool = False) -> dict:
	"""Several rate edits of the grid (typed cells, a pasted block, "+10 %" on a selection) as ONE
	edit of the contract's draft (UX revision 2026-10): every changed night is priced from the
	prices before any edit, then written as absolute units through the same period plan as
	``apply_rate_change`` (in place, or one clone per part). Without ``apply`` nothing is written:
	the answer says what each room's price is now and would be, how many periods the draft would
	gain and which errors it would get (an edit that adds an ERROR is refused on apply). With
	``apply`` the draft (made from the latest version when there is none) is saved once, checked
	once and audited once: all of it or nothing. Nothing is sold at the new prices until the draft
	is published."""
	if frappe.db.get_value("TEX Contract", contract, "property") != property:
		frappe.throw(_("The contract belongs to another hotel."))
	scope.require("contract.edit", property)
	draft, _active = _editable_version(contract)
	creates = not draft
	if apply and creates:
		draft = contracts.new_draft(contract)
	source = draft or frappe.db.get_value("TEX Contract Version", {"contract": contract}, "name",
	                                      order_by="version_no desc")
	if not source:
		frappe.throw(_("This contract has no version yet: add its rooms and periods first."))
	v = frappe.get_doc("TEX Contract Version", source)
	terms0 = contracts.build_terms(v)
	cells = _rate_cells(terms0, changes)
	before = validate.validate_terms(terms0)

	# the same plan, written into the terms (and, on apply, into the draft) group by group
	terms, alias, taken, new_periods, edited = terms0, {}, {(p.period_code or "").strip() for p in v.periods}, 0, []
	for a, b, new, rts in _groups(cells):
		steps = _plan_or_throw(terms, a, b, None, rts, "ABSOLUTE", new)
		new_periods += sum(1 for s in steps if s.clone)
		if apply:
			codes, clones = _write_plan(v, steps, taken, alias)
			edited += codes
			terms, _al = ratesplit.apply(terms, steps, clones)
		else:
			terms, al = ratesplit.apply(terms, steps)
			for k, src in al.items():
				alias[k] = alias.get(src, src)
	answer = {
		"contract": contract, "draft": draft, "creates_draft": creates, "based_on": source,
		"currency": terms0.currency, "basis": terms0.basis.value, "new_periods": new_periods,
		"cells": [{"room_type": c["room_type"], "start": c["start"].isoformat(), "end": c["end"].isoformat(),
		           "current": to_str(c["current"]), "new": to_str(c["new"])} for c in cells],
	}
	if not apply:
		added = ratesplit.added_errors(before, validate.validate_terms(terms), alias)
		return {**answer, "errors": [i.message for i in added[:10]], "applied": False}

	frappe.db.savepoint("tex_grid_rates")
	v.flags.tex_audit_reason = "ARI grid rate change"
	v.save(ignore_permissions=True)
	added = ratesplit.added_errors(before, validate.validate_terms(contracts.build_terms(v)), alias)
	if added:
		frappe.db.rollback(save_point="tex_grid_rates")
		frappe.throw(_("This rate change would give the draft errors: {0}").format(
			"; ".join(i.message for i in added[:5])), title=_("Rate change refused"))
	audit("grid.rate_changes", property=property, reference_doctype="TEX Contract Version", reference_name=draft,
	      new={"contract": contract, "draft": draft, "created_draft": creates, "periods": edited,
	           "changes": len(changes), "nights": sum((c["end"] - c["start"]).days + 1 for c in cells),
	           "collections": {"rates": cells_diff([(f"{c['room_type']}{SEP}{c['start']}/{c['end']}",
	                                                  {"unit": to_str(c["current"])}, {"unit": to_str(c["new"])})
	                                                 for c in cells])}})
	return {**answer, "periods": edited, "errors": [], "applied": True}


