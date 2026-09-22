"""Demo data for TEX Engine (development, visual QA and the browser E2E journey).

    bench --site <site> execute kamra.tex.devtools.demo_seed.execute \
        --kwargs "{'password': '<choose one>'}"

Idempotent (get-or-create). Creates an enterprise with two hotels, published
contracts, markup, a promotion code, extras, a booking site ("aurora") with the
sandbox payment gateway, staff users with scoped access and a few bookings.
Never run on a production site: it creates a Sandbox gateway and demo users.
"""

from __future__ import annotations

import frappe
from frappe.utils import add_days, getdate, now_datetime, nowdate

ENTERPRISE = "Aurora Hospitality (demo)"
GROUP = "Aurora Riviera Collection"
HOTELS = {
	"Aurora Beach Resort": {"city": "Antalya", "rooms": (("STD", "Standard Sea View", 110, 12, 3, 2),
	                                                    ("FAM", "Family Suite", 160, 6, 4, 3),
	                                                    ("VIL", "Garden Villa", 260, 3, 4, 2))},
	"Aurora City Hotel": {"city": "Istanbul", "rooms": (("CLS", "Classic Room", 90, 10, 2, 1),
	                                                   ("EXE", "Executive Room", 130, 6, 3, 1))},
}
SITE = "aurora"


def _ensure(doctype: str, filters: dict, payload: dict) -> str:
	name = frappe.db.get_value(doctype, filters)
	if name:
		return name
	doc = frappe.get_doc({"doctype": doctype, **payload})
	doc.insert(ignore_permissions=True)
	return doc.name


def _user(email: str, first: str, roles: list[str], password: str | None) -> str:
	if not frappe.db.exists("User", email):
		frappe.get_doc({"doctype": "User", "email": email, "first_name": first, "enabled": 1,
		                "user_type": "System User", "send_welcome_email": 0,
		                "roles": [{"role": r} for r in roles]}).insert(ignore_permissions=True)
	if password:
		from frappe.utils.password import update_password

		update_password(email, password)
	return email


def _hotel(name: str, spec: dict, group: str) -> dict:
	if not frappe.db.exists("Property", name):
		frappe.get_doc({"doctype": "Property", "property_name": name, "city": spec["city"], "country": "Turkey",
		                "currency": "EUR", "tex_hotel_group": group, "tex_tax_profile": "Custom",
		                "minimum_nights": 1}).insert(ignore_permissions=True)
	rts = {}
	for code, label, base, count, adults, kids in spec["rooms"]:
		rts[code] = _ensure("Room Type", {"property": name, "room_type_code": code},
		                    {"property": name, "room_type_code": code, "room_type_name": label, "base_price": base,
		                     "adults_capacity": adults, "children_capacity": kids,
		                     "max_total_occupants": adults + kids, "base_occupancy": 2})
		for i in range(count):
			_ensure("Room", {"property": name, "room_number": f"{code}{101 + i}"},
			        {"property": name, "room_number": f"{code}{101 + i}", "room_type": rts[code]})
	flex = _ensure("TEX Cancellation Policy", {"property": name, "policy_name": "Free until 7 days"}, {
		"property": name, "policy_name": "Free until 7 days", "refundable": 1, "no_show_type": "NIGHTS",
		"no_show_value": 1, "rules": [{"days_before_arrival": 7, "penalty_type": "NIGHTS", "penalty_value": 1}],
		"description": "Free cancellation until 7 days before arrival; later, the first night is charged."})
	nrf = _ensure("TEX Cancellation Policy", {"property": name, "policy_name": "Non-refundable"}, {
		"property": name, "policy_name": "Non-refundable", "refundable": 0, "no_show_type": "PERCENT",
		"no_show_value": 100, "rules": [{"days_before_arrival": 9999, "penalty_type": "PERCENT",
		                                 "penalty_value": 100}], "description": "Not refundable."})
	deposit = _ensure("TEX Payment Policy", {"property": name, "policy_name": "30% deposit"},
	                  {"property": name, "policy_name": "30% deposit", "deposit_type": "PERCENT",
	                   "deposit_value": 30, "allow_pay_at_hotel": 1})
	full = _ensure("TEX Payment Policy", {"property": name, "policy_name": "Pay in full"},
	               {"property": name, "policy_name": "Pay in full", "deposit_type": "FULL"})
	rps = {}
	for code, label, cxl, pay in (("FLEX", "Flexible", flex, deposit), ("NRF", "Non-refundable saver", nrf, full)):
		rps[code] = _ensure("Rate Plan", {"property": name, "code": code},
		                    {"property": name, "code": code, "rate_plan_name": label, "modifier_type": "Percent",
		                     "modifier_value": 0, "tex_refundable": 1 if code == "FLEX" else 0,
		                     "tex_cancellation_policy": cxl, "tex_payment_policy": pay})
	for code, label, cat, mode, amount in (("TRF", "Airport transfer", "Transfer", "RESERVATION", 45),
	                                       ("SPA", "Spa access", "Spa", "PERSON_NIGHT", 18),
	                                       ("LCO", "Late check-out", "Service", "RESERVATION", 35)):
		_ensure("TEX Extra", {"property": name, "extra_code": code},
		        {"property": name, "extra_code": code, "extra_name": label, "category": cat, "pricing_mode": mode,
		         "currency": "EUR", "amount": amount, "bookable_online": 1,
		         "tax_category": "TRANSFER" if code == "TRF" else "SERVICE"})
	return {"room_types": rts, "rate_plans": rps}


def _contract(hotel: str, h: dict, code: str, market: str, base_code: str, uplift: dict) -> None:
	from kamra.tex.commercial import contracts

	if frappe.db.exists("TEX Contract", {"property": hotel, "contract_code": code}):
		return
	year = getdate(nowdate()).year
	stay_from, stay_to = getdate(f"{year}-01-01"), getdate(f"{year + 1}-12-31")
	rts = h["room_types"]
	base_rt = rts[base_code]
	c = frappe.get_doc({
		"doctype": "TEX Contract", "property": hotel, "contract_code": code, "contract_name": f"{hotel} {market}",
		"market": market, "contract_currency": "EUR", "pricing_basis": "PERSON", "status": "Draft",
		"sale_from": add_days(now_datetime(), -60), "sale_to": stay_to, "stay_from": stay_from, "stay_to": stay_to,
	}).insert(ignore_permissions=True)
	periods, rates = [], []
	seasons = [("LOW", "Low season", "01-01", "04-30", 0), ("MID", "Shoulder", "05-01", "06-30", 25),
	           ("HIGH", "High season", "07-01", "08-31", 55), ("MID2", "Shoulder autumn", "09-01", "10-31", 25),
	           ("WIN", "Winter", "11-01", "12-31", 0)]
	base = uplift["base"]
	for y in (year, year + 1):
		for pc, label, a, b, add in seasons:
			code_y = f"{pc}{str(y)[2:]}"
			periods.append({"period_code": code_y, "period_name": f"{label} {y}", "start_date": f"{y}-{a}",
			                "end_date": f"{y}-{b}"})
			rates.append({"room_type": base_rt, "period_code": code_y, "op": "ABSOLUTE", "value": base + add})
	for rc, factor in uplift["derived"].items():
		if rc in rts:
			rates.append({"room_type": rts[rc], "op": "MULTIPLY", "value": factor, "base_room_type": base_rt})
	v = frappe.get_doc({
		"doctype": "TEX Contract Version", "contract": c.name, "prices_include_tax": 0,
		"rooms": [{"room_type": rt, "is_base": 1 if rt == base_rt else 0} for rt in rts.values()],
		"periods": periods, "period_rates": rates,
		"age_bands": [{"band_code": "INF", "label": "Infant 0–2", "from_age": 0, "to_age": 2.99, "is_infant": 1},
		              {"band_code": "CHA", "label": "Child 3–6", "from_age": 3, "to_age": 6.99},
		              {"band_code": "CHB", "label": "Child 7–12", "from_age": 7, "to_age": 12.99}],
		"occupancy_rules": [
			{"target": "ADULT", "position": 3, "op": "MULTIPLY", "value": 0.7},
			{"target": "ADULT", "position": 4, "op": "MULTIPLY", "value": 0.7},
			{"target": "CHILD", "age_band": "INF", "op": "MULTIPLY", "value": 0},
			{"target": "CHILD", "age_band": "CHA", "op": "PERCENT_OF", "value": 0},
			{"target": "CHILD", "age_band": "CHB", "op": "PERCENT_OF", "value": 50},
		],
		"boards": [{"board": "BB", "is_base": 1}, {"board": "HB", "op": "ADD", "adult_amount": 22, "child_percent": 50},
		           {"board": "AI", "op": "ADD", "adult_amount": 45, "child_percent": 50}],
		"rate_plans": [{"rate_plan": h["rate_plans"]["FLEX"], "refundable": 1},
		               {"rate_plan": h["rate_plans"]["NRF"], "op": "ADJUST_PERCENT", "value": -12, "refundable": 0}],
	}).insert(ignore_permissions=True)
	contracts.publish(v.name)


def _markup_and_promo(hotel: str) -> None:
	from kamra.tex.commercial import revisions

	if not frappe.db.exists("TEX Markup Rule", {"property": hotel, "market": "DE"}):
		m = frappe.get_doc({"doctype": "TEX Markup Rule", "label": "DACH direct +8%", "property": hotel, "market": "DE",
		                    "op": "ADJUST_PERCENT", "value": 8}).insert(ignore_permissions=True)
		revisions.activate("TEX Markup Rule", m.name)
	if not frappe.db.exists("TEX Promotion", {"property": hotel, "code": "EARLY10"}):
		p = frappe.get_doc({"doctype": "TEX Promotion", "promotion_name": "Early booker 10%", "property": hotel,
		                    "kind": "PROMO_CODE", "trigger": "Code", "code": "EARLY10", "value_type": "PERCENT",
		                    "value": 10, "min_lead_days": 30, "stackable": 0}).insert(ignore_permissions=True)
		revisions.activate("TEX Promotion", p.name)


def _payments(hotel: str) -> None:
	acc = _ensure("TEX Payment Provider Account", {"property": hotel, "provider": "Mock"},
	              {"label": "Sandbox card gateway", "property": hotel, "provider": "Mock", "environment": "Sandbox",
	               "enabled": 1, "currencies": "EUR"})
	bank = _ensure("TEX Payment Provider Account", {"property": hotel, "provider": "Bank Transfer"},
	               {"label": "Bank transfer", "property": hotel, "provider": "Bank Transfer",
	                "environment": "Sandbox", "enabled": 1, "bank_name": "Demo Bank",
	                "iban": "TR00 0000 0000 0000 0000 0000 00", "account_holder": hotel})
	_ensure("TEX Payment Method Rule", {"property": hotel, "method": "Card"},
	        {"property": hotel, "method": "Card", "provider_account": acc, "priority": 10})
	_ensure("TEX Payment Method Rule", {"property": hotel, "method": "Bank Transfer"},
	        {"property": hotel, "method": "Bank Transfer", "provider_account": bank, "priority": 5})
	_ensure("TEX Payment Method Rule", {"property": hotel, "method": "Pay at Hotel"},
	        {"property": hotel, "method": "Pay at Hotel", "priority": 1})


def execute(password: str | None = None, bookings: int = 6) -> dict:
	if frappe.conf.get("tex_production"):
		frappe.throw("demo_seed refuses to run on a site flagged tex_production")
	from kamra.tex import setup

	setup.ensure_custom_fields()
	setup.ensure_profiles()
	setup.ensure_masters()
	ent = _ensure("TEX Enterprise", {"enterprise_name": ENTERPRISE}, {"enterprise_name": ENTERPRISE,
	                                                                  "default_currency": "EUR"})
	grp = _ensure("TEX Hotel Group", {"group_name": GROUP}, {"group_name": GROUP, "enterprise": ent,
	                                                         "default_currency": "EUR"})
	hotels = {}
	for name, spec in HOTELS.items():
		h = _hotel(name, spec, grp)
		hotels[name] = h
		first = next(iter(h["room_types"]))
		derived = {code: 1 + 0.35 * i for i, code in enumerate(list(h["room_types"])[1:], start=1)}
		_contract(name, h, "DE-" + first, "DE", first, {"base": 70 if "Beach" in name else 60, "derived": derived})
		_contract(name, h, "GL-" + first, "GLOBAL", first, {"base": 80 if "Beach" in name else 68, "derived": derived})
		_markup_and_promo(name)
		_payments(name)
	if not frappe.db.exists("TEX Booking Site", SITE):
		frappe.get_doc({"doctype": "TEX Booking Site", "site_name": "Aurora Riviera Collection", "site_slug": SITE,
		                "enabled": 1, "hotel_group": grp, "default_market": "GLOBAL", "default_currency": "EUR",
		                "currencies": "EUR", "languages": "en,tr,de,ru,ro,pl", "default_language": "en",
		                "self_service_enabled": 1, "primary_color": "#1C3FA8", "accent_color": "#E0A526",
		                "contact_phone": "+90 242 000 00 00", "contact_email": "reservations@example.com",
		                "policies": "Check-in from 14:00, check-out until 12:00. City tax is paid at the hotel.",
		                "consent_banner": 1}).insert(ignore_permissions=True)

	users = {
		"revenue@demo.tex": ("Rana", ["Revenue Manager"], "Revenue Manager", "Hotel Group"),
		"agent@demo.tex": ("Deniz", ["Call Center Agent"], "Reservations Agent", "Hotel Group"),
		"finance@demo.tex": ("Selin", ["Finance"], "Finance", "Hotel Group"),
		"beach.gm@demo.tex": ("Kaan", ["Hotel Admin"], "Hotel Admin", "Hotel"),
	}
	for email, (first, roles, profile, level) in users.items():
		_user(email, first, roles, password)
		filters = {"user": email, "scope_level": level}
		payload = {"user": email, "scope_level": level, "permission_profile": profile}
		if level == "Hotel":
			filters["property"] = payload["property"] = "Aurora Beach Resort"
		else:
			filters["hotel_group"] = payload["hotel_group"] = grp
		_ensure("TEX Access Grant", filters, payload)

	made = _demo_bookings(bookings) if bookings else 0
	frappe.db.commit()  # nosemgrep: frappe-manual-commit -- bench execute seed script boundary
	return {"enterprise": ent, "group": grp, "hotels": list(HOTELS), "site": SITE, "bookings": made}


def _demo_bookings(n: int) -> int:
	from kamra.tex.services import booking, quoting

	if frappe.db.count("TEX Booking", {"booking_site": SITE}) >= n:
		return 0
	guests = [("Anna", "Schmidt", "DE"), ("Emre", "Yılmaz", "TR"), ("Olga", "Ivanova", "RU"),
	          ("Andrei", "Popescu", "RO"), ("Marta", "Nowak", "PL"), ("James", "Walker", "GLOBAL")]
	made = 0
	today = getdate(nowdate())
	for i in range(n):
		first, last, market = guests[i % len(guests)]
		hotel = list(HOTELS)[i % 2]
		ci = add_days(today, 20 + i * 9)
		co = add_days(ci, 3 + i % 4)
		res = quoting.search(properties=[hotel], check_in=ci, check_out=co, rooms=[{"adults": 2, "children": []}],
		                     market=market if market in ("DE",) else "GLOBAL", channel="DIRECT_WEB", currency="EUR")
		flex = frappe.db.get_value("Rate Plan", {"property": hotel, "code": "FLEX"})
		offers = [o for o in (res["properties"][0]["offers"] if res["properties"] else []) if o["rate_plan"] == flex]
		if not offers:
			continue
		q = quoting.create_quote(offers[i % len(offers)]["rooms"][0]["offer_key"])
		if not q.get("ok"):
			continue
		b = booking.create_booking(quote_ids=[q["quote_id"]], guest={
			"first_name": first, "last_name": last, "email": f"{first.lower()}.{last.lower()}@example.com",
			"country": None}, payment_method="Pay at Hotel", idempotency_key=f"demo-{i}", booking_site=SITE)
		if b.get("status") != "Confirmed":
			booking.confirm_booking(b["booking"], reason="demo data")
		made += 1
	return made
