"""TEX T7: legacy Experiences become TEX Extras (unit pricing, same price) linked
through ``legacy_experience``. The Experience rows are kept."""

import frappe

CATEGORY = {"Spa": "Spa", "Tour": "Excursion", "Dining": "Dining", "Activity": "Excursion",
            "Transport": "Transfer", "Other": "Other"}


def execute():
	if not frappe.db.table_exists("TEX Extra") or not frappe.db.table_exists("Experience"):
		return
	for e in frappe.get_all("Experience", fields=["name", "property", "experience_name", "category", "price",
	                                              "description", "image_url", "show_on_booking_page", "disabled"]):
		if not e.property or frappe.db.exists("TEX Extra", {"legacy_experience": e.name}):
			continue
		currency = frappe.db.get_value("Property", e.property, "currency") or "EUR"
		base = "".join(ch for ch in (e.experience_name or "EXP").upper() if ch.isalnum())[:10] or "EXP"
		code, n = base, 1
		while frappe.db.exists("TEX Extra", {"property": e.property, "extra_code": code}):
			n += 1
			code = f"{base[:8]}{n}"
		doc = frappe.get_doc({
			"doctype": "TEX Extra", "property": e.property, "extra_code": code,
			"extra_name": e.experience_name or code, "category": CATEGORY.get(e.category or "", "Other"),
			"description": e.description, "pricing_mode": "UNIT", "currency": currency, "amount": e.price or 0,
			"tax_category": "SERVICE", "bookable_online": 1 if e.show_on_booking_page else 0,
			"disabled": e.disabled or 0, "legacy_experience": e.name,
		})
		try:
			doc.insert(ignore_permissions=True)
		except frappe.ValidationError:
			frappe.log_error(title=f"TEX T7: experience {e.name} not copied")
