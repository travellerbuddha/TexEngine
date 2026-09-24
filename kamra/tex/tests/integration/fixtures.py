"""Deterministic TEX fixtures for integration tests (bench required).

Builds: TEST enterprise → group → hotel "TEX Test Resort" (EUR), room types
STD×6, DLX×2, rate plans FLEX / NRF with frozen policies, a DE contract (PERSON
basis) with periods, room derivations, child bands, occupancy formulas and boards,
a Germany markup of +7 %, and an airport-transfer extra. Everything is
get-or-create so tests can run on any site; tests roll back their own writes.
"""

from __future__ import annotations

import frappe
from frappe.utils import add_days, getdate, now_datetime

PROPERTY = "TEX Test Resort"
ENTERPRISE = "TEST Enterprise"
GROUP = "TEST Hotel Group"
YEAR = getdate(now_datetime()).year + 1
STAY_FROM = getdate(f"{YEAR}-05-01")
STAY_TO = getdate(f"{YEAR}-10-31")


def d(month: int, day: int):
	return getdate(f"{YEAR}-{month:02d}-{day:02d}")


def ensure_currency(code: str, symbol: str):
	if not frappe.db.exists("Currency", code):
		frappe.get_doc({"doctype": "Currency", "currency_name": code, "symbol": symbol, "enabled": 1,
		                "fraction_units": 100}).insert(ignore_permissions=True)


def ensure(doctype: str, filters: dict, payload: dict) -> str:
	name = frappe.db.get_value(doctype, filters)
	if name:
		return name
	doc = frappe.get_doc({"doctype": doctype, **payload})
	doc.insert(ignore_permissions=True)
	return doc.name


def ensure_live(doctype: str, filters: dict, payload: dict, at: str = "2020-01-01 00:00:00") -> str:
	"""A revisioned record (G-20) that is live: created as a draft, then activated."""
	from kamra.tex.commercial import revisions

	name = frappe.db.get_value(doctype, {**filters, "tex_status": ("in", ["Draft", "Active"])}) \
		or ensure(doctype, filters, payload)
	if frappe.db.get_value(doctype, name, "tex_status") == "Draft":
		revisions.activate(doctype, name, at=at, backdate=True)   # a fixture states what was on sale
	return name


def ensure_user(email: str, roles: list[str]) -> str:
	if not frappe.db.exists("User", email):
		frappe.get_doc({"doctype": "User", "email": email, "first_name": email.split("@")[0], "enabled": 1,
		                "user_type": "System User", "send_welcome_email": 0,
		                "roles": [{"role": r} for r in roles]}).insert(ignore_permissions=True)
	return email


def base_setup() -> dict:
	from kamra.tex import setup

	setup.ensure_custom_fields()
	setup.ensure_profiles()
	setup.ensure_masters()
	for code, sym in (("EUR", "€"), ("TRY", "₺"), ("GBP", "£"), ("USD", "$")):
		ensure_currency(code, sym)
	ent = ensure("TEX Enterprise", {"enterprise_name": ENTERPRISE}, {"enterprise_name": ENTERPRISE})
	grp = ensure("TEX Hotel Group", {"group_name": GROUP}, {"group_name": GROUP, "enterprise": ent})
	if not frappe.db.exists("Property", PROPERTY):
		frappe.get_doc({"doctype": "Property", "property_name": PROPERTY, "city": "Antalya", "country": "Turkey",
		                "currency": "EUR", "tex_hotel_group": grp, "tex_tax_profile": "Custom",
		                "minimum_nights": 1}).insert(ignore_permissions=True)
	if frappe.db.has_column("Property", "tex_live_from") and not frappe.db.get_value("Property", PROPERTY,
	                                                                                 "tex_live_from"):
		# the test hotel is sold through TEX (ADR-052 review: live in TEX, not onboarding)
		frappe.db.set_value("Property", PROPERTY, "tex_live_from", "2020-01-01 00:00:00")
	rts = {}
	for code, name, base, rooms, adults, kids in (("STD", "Standard Room", 100, 6, 3, 2),
	                                             ("DLX", "Deluxe Room", 135, 2, 3, 3)):
		rts[code] = ensure("Room Type", {"property": PROPERTY, "room_type_code": code},
		                   {"property": PROPERTY, "room_type_code": code, "room_type_name": name, "base_price": base,
		                    "adults_capacity": adults, "children_capacity": kids, "max_total_occupants": adults + kids,
		                    "base_occupancy": 2})
		for i in range(rooms):
			ensure("Room", {"property": PROPERTY, "room_number": f"{code}{i + 1}"},
			       {"property": PROPERTY, "room_number": f"{code}{i + 1}", "room_type": rts[code]})
	flex_cxl = ensure("TEX Cancellation Policy", {"property": PROPERTY, "policy_name": "Flexible 7d"}, {
		"property": PROPERTY, "policy_name": "Flexible 7d", "refundable": 1, "no_show_type": "NIGHTS",
		"no_show_value": 1, "rules": [{"days_before_arrival": 7, "penalty_type": "NIGHTS", "penalty_value": 1}],
		"description": "Free cancellation until 7 days before arrival."})
	nrf_cxl = ensure("TEX Cancellation Policy", {"property": PROPERTY, "policy_name": "Non-refundable"}, {
		"property": PROPERTY, "policy_name": "Non-refundable", "refundable": 0, "no_show_type": "PERCENT",
		"no_show_value": 100, "rules": [{"days_before_arrival": 9999, "penalty_type": "PERCENT",
		                                 "penalty_value": 100}]})
	full = ensure("TEX Payment Policy", {"property": PROPERTY, "policy_name": "Pay now"},
	              {"property": PROPERTY, "policy_name": "Pay now", "deposit_type": "FULL"})
	deposit = ensure("TEX Payment Policy", {"property": PROPERTY, "policy_name": "30% deposit"},
	                 {"property": PROPERTY, "policy_name": "30% deposit", "deposit_type": "PERCENT",
	                  "deposit_value": 30, "allow_pay_at_hotel": 1})
	rps = {}
	for code, name, cxl, pay in (("FLEX", "Flexible", flex_cxl, deposit), ("NRF", "Non-refundable", nrf_cxl, full)):
		rps[code] = ensure("Rate Plan", {"property": PROPERTY, "code": code},
		                   {"property": PROPERTY, "code": code, "rate_plan_name": name, "modifier_type": "Percent",
		                    "modifier_value": 0, "tex_refundable": 1 if code == "FLEX" else 0,
		                    "tex_cancellation_policy": cxl, "tex_payment_policy": pay})
	ensure_live("TEX Extra", {"property": PROPERTY, "extra_code": "TRF"},
	            {"property": PROPERTY, "extra_code": "TRF", "extra_name": "Airport transfer", "category": "Transfer",
	             "pricing_mode": "RESERVATION", "currency": "EUR", "amount": 40, "tax_category": "TRANSFER"})
	return {"enterprise": ent, "group": grp, "property": PROPERTY, "room_types": rts, "rate_plans": rps}


def default_age_bands() -> list[dict]:
	return [{"band_code": "INF", "label": "Infant", "from_age": 0, "to_age": 2.99, "is_infant": 1},
	        {"band_code": "CHA", "label": "Child A", "from_age": 3, "to_age": 6.99},
	        {"band_code": "CHB", "label": "Child B", "from_age": 7, "to_age": 11.99}]


def default_occupancy_rules() -> list[dict]:
	return [
		{"target": "ADULT", "position": 3, "op": "MULTIPLY", "value": 0.7},
		{"target": "CHILD", "age_band": "INF", "op": "MULTIPLY", "value": 0},
		{"target": "CHILD", "age_band": "CHA", "op": "PERCENT_OF", "value": 25},
		{"target": "CHILD", "age_band": "CHB", "op": "PERCENT_OF", "value": 50},
		{"target": "CHILD", "position": 1, "age_band": "CHB", "combination": "1+1", "op": "PERCENT_OF",
		 "value": 100},
	]


def create_contract(f: dict, *, code="DE-TEST", market="DE", base=100, publish=True, age_bands=None,
                    occupancy_rules=None) -> dict:
	"""``age_bands`` / ``occupancy_rules``: None → the defaults above; [] → none (the contract
	inherits them from the pricing policies)."""
	from kamra.tex.commercial import contracts

	std, dlx = f["room_types"]["STD"], f["room_types"]["DLX"]
	contract = frappe.get_doc({
		"doctype": "TEX Contract", "property": PROPERTY, "contract_code": code, "contract_name": f"{code} contract",
		"market": market, "contract_currency": "EUR", "pricing_basis": "PERSON", "status": "Draft",
		"sale_from": add_days(now_datetime(), -30), "sale_to": STAY_TO, "stay_from": STAY_FROM, "stay_to": STAY_TO,
	}).insert(ignore_permissions=True)
	version = frappe.get_doc({
		"doctype": "TEX Contract Version", "contract": contract.name, "prices_include_tax": 0,
		"rooms": [{"room_type": std, "is_base": 1}, {"room_type": dlx}],
		"periods": [{"period_code": "LOW", "period_name": "Low", "start_date": STAY_FROM, "end_date": d(6, 30)},
		            {"period_code": "HIGH", "period_name": "High", "start_date": d(7, 1), "end_date": STAY_TO}],
		"period_rates": [{"room_type": std, "period_code": "LOW", "op": "ABSOLUTE", "value": base},
		                 {"room_type": std, "period_code": "HIGH", "op": "ABSOLUTE", "value": base + 20},
		                 {"room_type": dlx, "op": "MULTIPLY", "value": 1.35, "base_room_type": std}],
		"age_bands": default_age_bands() if age_bands is None else age_bands,
		"occupancy_rules": default_occupancy_rules() if occupancy_rules is None else occupancy_rules,
		"boards": [{"board": "AI", "is_base": 1}, {"board": "UAI", "op": "ADD", "adult_amount": 20,
		                                          "child_percent": 50}],
		"rate_plans": [{"rate_plan": f["rate_plans"]["FLEX"], "refundable": 1},
		               {"rate_plan": f["rate_plans"]["NRF"], "op": "ADJUST_PERCENT", "value": -10, "refundable": 0}],
	}).insert(ignore_permissions=True)
	out = {"contract": contract.name, "version": version.name}
	if publish:
		out.update(contracts.publish(version.name))
	return out


def create_markup(market="DE", value=7):
	from kamra.tex.commercial import revisions

	doc = frappe.get_doc({"doctype": "TEX Markup Rule", "label": f"{market} markup", "property": PROPERTY,
	                      "market": market, "op": "ADJUST_PERCENT", "value": value}).insert(ignore_permissions=True)
	revisions.activate("TEX Markup Rule", doc.name)
	return doc.name
