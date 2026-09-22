"""TEX T6: every legacy Discount Voucher gets a TEX Promotion twin (code trigger,
same validity, limits and usage count). The voucher itself is kept untouched; the
promotion links back through ``legacy_voucher`` so the copy is never repeated.
Copies start as Draft revisions: a revenue manager activates them deliberately."""

import frappe


def execute():
	if not frappe.db.table_exists("TEX Promotion") or not frappe.db.table_exists("Discount Voucher"):
		return
	for v in frappe.get_all("Discount Voucher", fields=["name", "property", "voucher_code", "discount_type", "value",
	                                                    "valid_from", "valid_to", "min_nights", "max_uses",
	                                                    "times_used", "disabled"]):
		if not v.voucher_code or frappe.db.exists("TEX Promotion", {"legacy_voucher": v.name}):
			continue
		currency = frappe.db.get_value("Property", v.property, "currency") if v.property else None
		percent = (v.discount_type or "Percent") == "Percent"
		doc = frappe.get_doc({
			"doctype": "TEX Promotion", "promotion_name": f"{v.voucher_code} (legacy voucher)",
			"property": v.property, "kind": "PROMO_CODE", "trigger": "Code", "code": v.voucher_code.strip().upper(),
			"value_type": "PERCENT" if percent else "FIXED_STAY", "value": v.value or 0,
			"currency": None if percent else currency, "sale_from": v.valid_from, "sale_to": v.valid_to,
			"min_nights": v.min_nights or None, "usage_limit": v.max_uses or None,
			"times_redeemed": v.times_used or 0, "stackable": 0, "legacy_voucher": v.name,
		})
		doc.flags.ignore_permissions = True
		try:
			doc.insert(ignore_permissions=True)
		except frappe.ValidationError:
			# e.g. a 0 % voucher or a code already used by a live promotion: keep the
			# legacy voucher, log it for review, never block the upgrade
			frappe.log_error(title=f"TEX T6: voucher {v.name} not copied")
