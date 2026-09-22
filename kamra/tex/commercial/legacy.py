"""MIGRATION T8 (opt-in): draft a TEX contract from a hotel's legacy Kamra prices.

Legacy Kamra prices a room type with ``base_price`` for ``base_occupancy`` adults,
``single_occupancy_price``, ``extra_adult_price`` / ``child_price`` per extra person,
Seasons (Percent / Amount / Absolute, priority, weekdays, optional room type) and rate
plan modifiers. This module turns that into a ROOM-basis TEX contract **Draft** that a
revenue manager reviews and publishes; it is never published automatically.

Mapping (deterministic, Decimal only):
* one base period covering the stay window → ABSOLUTE base price per room type;
* one period per season (same dates, weekdays and priority, +1000 so seasons beat the
  base period) → per-room ABSOLUTE price = the season rule applied to that room's
  base price when the season covers the room, else the base price;
* occupancy: included adults = base occupancy; extra adults / children FIXED at the
  legacy extra prices; single use ABSOLUTE at the single price (combination 1+0);
* rate plans: Percent → ADJUST_PERCENT, Amount → ADD; Absolute modifiers cannot be
  expressed as an adjustment and are reported in the change note for review.
"""

from __future__ import annotations

import frappe
from frappe import _
from frappe.utils import add_days, getdate, nowdate

from kamra.tex.money import D, quantize, to_str
from kamra.tex.security import scope
from kamra.tex.security.audit import audit

WEEKDAYS = {"mon": "Mon", "tue": "Tue", "wed": "Wed", "thu": "Thu", "fri": "Fri", "sat": "Sat", "sun": "Sun"}


def _weekdays(raw: str | None) -> str | None:
	if not raw:
		return None
	out = []
	for part in str(raw).replace(";", ",").split(","):
		key = part.strip()[:3].lower()
		if key in WEEKDAYS:
			out.append(WEEKDAYS[key])
	return ",".join(out) or None


def season_price(base, season, ccy: str):
	v = D(season.adjustment_value or 0)
	kind = season.adjustment_type or "Percent"
	if kind == "Absolute":
		return quantize(v, ccy)
	if kind == "Amount":
		return quantize(D(base) + v, ccy)
	return quantize(D(base) * (D(100) + v) / D(100), ccy)


def draft_from_legacy(property: str, market: str = "GLOBAL", contract_code: str = "LEGACY-BAR") -> dict:
	scope.require("contract.edit", property)
	if frappe.db.exists("TEX Contract", {"property": property, "contract_code": contract_code}):
		frappe.throw(_("Contract {0} already exists for this hotel.").format(contract_code))
	ccy = frappe.db.get_value("Property", property, "currency") or "EUR"
	rts = frappe.get_all("Room Type", filters={"property": property, "disabled": 0},
	                     fields=["name", "room_type_name", "base_price", "base_occupancy", "single_occupancy_price",
	                             "extra_adult_price", "child_price", "adults_capacity", "children_capacity"],
	                     order_by="base_price asc")
	if not rts:
		frappe.throw(_("This hotel has no room types."))
	seasons = frappe.get_all("Season", filters={"property": property, "disabled": 0},
	                         fields=["name", "season_name", "room_type", "start_date", "end_date", "adjustment_type",
	                                 "adjustment_value", "priority", "days_of_week"], order_by="start_date asc")
	today = getdate(nowdate())
	stay_to = max([getdate(s.end_date) for s in seasons] + [add_days(today, 730)])
	notes: list[str] = []

	periods = [{"period_code": "BASE", "period_name": "Base (legacy room prices)", "start_date": today,
	            "end_date": stay_to, "priority": 0}]
	rates = [{"room_type": rt.name, "period_code": "BASE", "op": "ABSOLUTE",
	          "value": to_str(quantize(D(rt.base_price or 0), ccy))} for rt in rts]
	for i, s in enumerate(seasons, start=1):
		if getdate(s.end_date) < today:
			continue
		code = f"S{i:02d}"
		periods.append({"period_code": code, "period_name": (s.season_name or code)[:140],
		                "start_date": max(getdate(s.start_date), today), "end_date": getdate(s.end_date),
		                "weekdays": _weekdays(s.days_of_week), "priority": 1000 + int(s.priority or 0)})
		for rt in rts:
			applies = not s.room_type or s.room_type == rt.name
			price = season_price(rt.base_price or 0, s, ccy) if applies else quantize(D(rt.base_price or 0), ccy)
			rates.append({"room_type": rt.name, "period_code": code, "op": "ABSOLUTE", "value": to_str(price)})
		if s.room_type:
			notes.append(f"Season '{s.season_name}' applies to one room type; other rooms keep the base price on "
			             f"its dates. Check overlaps with other seasons.")

	occupancy = []
	for rt in rts:
		if D(rt.extra_adult_price or 0) > 0:
			occupancy.append({"target": "ADULT", "position": 0, "room_type": rt.name, "op": "FIXED",
			                  "value": to_str(quantize(D(rt.extra_adult_price), ccy)),
			                  "note": "legacy extra adult"})
		if D(rt.child_price or 0) > 0:
			occupancy.append({"target": "CHILD", "position": 0, "room_type": rt.name, "op": "FIXED",
			                  "value": to_str(quantize(D(rt.child_price), ccy)), "note": "legacy child price"})
		if D(rt.single_occupancy_price or 0) > 0:
			occupancy.append({"target": "COMBINATION", "combination": "1+0", "room_type": rt.name, "op": "ABSOLUTE",
			                  "value": to_str(quantize(D(rt.single_occupancy_price), ccy)),
			                  "note": "legacy single use"})

	plans = []
	for rp in frappe.get_all("Rate Plan", filters={"property": property, "disabled": 0},
	                         fields=["name", "rate_plan_name", "modifier_type", "modifier_value", "tex_refundable"]):
		row = {"rate_plan": rp.name, "refundable": 1 if rp.tex_refundable or rp.tex_refundable is None else 0}
		v = D(rp.modifier_value or 0)
		if v and rp.modifier_type == "Percent":
			row.update({"op": "ADJUST_PERCENT", "value": to_str(v)})
		elif v and rp.modifier_type == "Amount":
			row.update({"op": "ADD", "value": to_str(v)})
		elif v:
			notes.append(f"Rate plan '{rp.rate_plan_name}' uses an absolute legacy price; set it manually.")
		plans.append(row)

	contract = frappe.get_doc({
		"doctype": "TEX Contract", "property": property, "contract_code": contract_code,
		"contract_name": "Legacy BAR (generated)", "market": market, "contract_currency": ccy,
		"pricing_basis": "ROOM", "status": "Draft", "is_bar": 1, "sale_from": today, "sale_to": stay_to,
		"stay_from": today, "stay_to": stay_to,
		"notes": "Generated from legacy Kamra room prices and seasons. Review before publishing."})
	contract.insert(ignore_permissions=True)
	version = frappe.get_doc({
		"doctype": "TEX Contract Version", "contract": contract.name, "prices_include_tax": 1,
		"change_note": "\n".join(["Generated from legacy prices.", *notes])[:2000],
		"rooms": [{"room_type": rt.name, "is_base": 1 if i == 0 else 0,
		           "included_adults": int(rt.base_occupancy or 2)} for i, rt in enumerate(rts)],
		"periods": periods, "period_rates": rates,
		"age_bands": [{"band_code": "CHD", "label": "Child 0–11", "from_age": 0, "to_age": 11.99}],
		"occupancy_rules": occupancy, "boards": [{"board": "RO", "is_base": 1}], "rate_plans": plans,
	})
	version.insert(ignore_permissions=True)
	audit("contract.legacy_draft", reference_doctype="TEX Contract", reference_name=contract.name,
	      property=property, new={"version": version.name, "periods": len(periods), "notes": notes})
	return {"contract": contract.name, "version": version.name, "notes": notes}
