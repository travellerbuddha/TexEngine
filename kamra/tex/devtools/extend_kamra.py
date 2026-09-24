"""Add TEX fields to existing Kamra DocTypes (idempotent dev tool).

    python -m kamra.tex.devtools.extend_kamra

Only additive ``tex_*`` fields are appended (MIGRATION_PLAN §1); existing fields are
never removed or renamed. Meal Plan board codes are extended in place.
"""

from __future__ import annotations

import json
import pathlib

from kamra.tex.devtools.doctype_gen import CB, SB, TAB, TIMESTAMP, F

DOCTYPES = pathlib.Path(__file__).resolve().parents[2] / "kamra" / "doctype"

EXT = {
	"reservation": [
		TAB("TEX Commercial"),
		F("tex_booking", "Link", "TEX booking", "TEX Booking", in_standard_filter=1),
		F("tex_room_index", "Int", "Room # in booking"),
		F("tex_contract", "Link", "Contract", "TEX Contract"),
		F("tex_contract_version", "Link", "Contract version", "TEX Contract Version"),
		F("tex_payload_hash", "Data", "Contract payload hash", read_only=1),
		F("tex_market", "Link", "Market", "TEX Market", in_standard_filter=1),
		F("tex_sales_channel", "Link", "Sales channel", "TEX Sales Channel", in_standard_filter=1),
		F("tex_board", "Data", "Board"),
		F("tex_child_ages", "Data", "Child ages (JSON)"),
		CB(),
		F("tex_pricing_source", "Select", "Pricing source", ["", "TEX", "Legacy", "Manual", "Channel", "Imported"], read_only=1),
		F("tex_price_locked", "Check", "Price locked", read_only=1),
		F("tex_locked_at", "Datetime", "Locked at", read_only=1),
		F("tex_sale_at", "Datetime", "Sold at", read_only=1),
		F("tex_accepted_at", "Datetime", "Accepted at", read_only=1),
		F("tex_quote", "Link", "Quote", "TEX Quote", read_only=1),
		F("tex_revision_no", "Int", "Revision", read_only=1),
		SB("TEX money"),
		F("tex_currency", "Link", "Sell currency", "Currency", read_only=1),
		F("tex_fx_rate", "Float", "FX rate applied", read_only=1, precision="9", permlevel=1),
		F("tex_total_amount", "Currency", "Total (sell currency)", options="tex_currency", read_only=1),
		F("tex_extras_amount", "Currency", "Extras", options="tex_currency", read_only=1),
		CB(),
		# pricing internals: permlevel 1, read in Desk / REST by System Manager only (G-95, ADR-056)
		F("tex_cost_amount", "Currency", "Contract cost (sell ccy)", options="tex_currency", read_only=1, permlevel=1),
		F("tex_margin_amount", "Currency", "Margin", options="tex_currency", read_only=1, permlevel=1),
		F("tex_promotions", "Small Text", "Promotions applied", read_only=1),
		SB("Guest change"),
		F("tex_guest_change_pending", "Check", "Guest change awaiting staff", in_standard_filter=1),
		F("tex_guest_change_note", "Small Text", "Guest change note"),
		SB("Pricing snapshot", collapsible=1),
		F("tex_pricing_snapshot", "Long Text", "Pricing snapshot (JSON)", read_only=1, permlevel=1),
	],
	"property": [
		TAB("TEX"),
		F("tex_enterprise", "Link", "Enterprise", "TEX Enterprise", read_only=1),
		F("tex_hotel_group", "Link", "Hotel group", "TEX Hotel Group"),
		F("tex_default_market", "Link", "Default market", "TEX Market"),
		F("tex_live_from", "Datetime", "Live in TEX from", read_only=1,
		  description="Sold through TEX from this moment: the Desk no longer creates or re-prices this hotel's "
		              "stays. Set only in TEX (go live), by an administrator, with a reason."),
		F("tex_self_service", "Check", "Guest self-service", default="1"),
		CB(),
		F("tex_inventory_mode", "Select", "Inventory source", ["Physical rooms", "Configured"],
		  default="Physical rooms"),
		F("tex_lower_price_refund", "Select", "When a guest change costs less",
		  ["Staff approval", "Refund automatically", "Keep as credit"], default="Staff approval",
		  description="A guest change that costs less: Staff approval waits for the hotel; Refund automatically "
		              "refunds what was paid above the new total to the card(s) it came from; Keep as credit "
		              "keeps it as credit on the same booking (used by later changes and extras, not by other "
		              "bookings)"),
		F("tex_tax_profile", "Select", "Tax profile", ["Localization pack", "Custom"], default="Localization pack"),
		SB("TEX tax rules", depends_on="eval:doc.tex_tax_profile=='Custom'"),
		F("tex_tax_rules", "Table", "Tax rules", "TEX Tax Rule"),
	],
	"room_type": [
		SB("TEX inventory & content"),
		F("tex_inventory_pool", "Data", "Shared inventory pool",
		  description="Room types with the same pool key share inventory. Blank = own pool."),
		F("tex_sellable_inventory", "Int", "Sellable inventory",
		  description="Used when the hotel's inventory source is 'Configured'."),
		CB(),
		F("tex_size_sqm", "Float", "Size (m²)", precision="1"),
		F("tex_beds", "Data", "Beds (e.g. 1 King or 2 Twin)"),
	],
	"rate_plan": [
		SB("TEX policies"),
		F("tex_refundable", "Check", "Refundable", default="1"),
		F("tex_cancellation_policy", "Link", "Cancellation policy", "TEX Cancellation Policy"),
		F("tex_payment_policy", "Link", "Payment policy", "TEX Payment Policy"),
		CB(),
		F("tex_inclusions", "Small Text", "Inclusions"),
		F("tex_description", "Small Text", "Guest-facing description"),
	],
	"guest": [
		SB("TEX CRM"),
		F("tex_enterprise", "Link", "Enterprise", "TEX Enterprise"),
		F("tex_language", "Data", "Language"),
		F("tex_country", "Link", "Country of residence", "Country"),
		F("tex_market", "Link", "Market", "TEX Market"),
		F("tex_tags", "Small Text", "Tags"),
		F("tex_preferences", "Small Text", "Preferences"),
		CB(),
		F("tex_consent_email", "Check", "Marketing e-mail consent"),
		F("tex_consent_sms", "Check", "Marketing SMS consent"),
		F("tex_consent_whatsapp", "Check", "Marketing WhatsApp consent"),
		F("tex_consent_updated_at", "Datetime", "Consent updated", read_only=1),
		F("tex_consent_source", "Data", "Consent source", read_only=1),
		F("tex_consent_text_version", "Data", "Consent text version", read_only=1),
		# the right to erasure's durable marker: an erased profile is never merged (ADR-056 third review)
		F("tex_erased_at", "Datetime", "Erased at", read_only=1, no_copy=1,
		  description="Set by the right to erasure (anonymize): an erased profile is never merged "
		              "(ADR-056 third review)"),
		SB("TEX stats", collapsible=1),
		# totals over every tenant's stays and programs: permlevel 1, read in Desk / REST by System
		# Manager only; the TEX CRM shows each viewer the totals of their own hotels (G-65, ADR-056)
		F("tex_stays", "Int", "Stays", read_only=1, permlevel=1),
		F("tex_lifetime_value", "Currency", "Lifetime value", "tex_lifetime_currency", read_only=1, permlevel=1),
		F("tex_lifetime_currency", "Link", "Lifetime value currency", "Currency", read_only=1, permlevel=1),
		F("tex_last_stay", "Date", "Last stay", read_only=1, permlevel=1),
		F("tex_loyalty_points", "Int", "Loyalty points", read_only=1, permlevel=1),
	],
}

BOARD_CODES = ["RO", "BB", "HB", "FB", "AI", "UAI"]


def extend() -> list[str]:
	done = []
	for folder, fields in EXT.items():
		path = DOCTYPES / folder / f"{folder}.json"
		d = json.loads(path.read_text())
		existing = {f["fieldname"] for f in d["fields"]}
		# layout breaks are regenerated with unique names per doctype
		added = 0
		for i, f in enumerate(fields):
			f = dict(f)
			if f["fieldtype"] in ("Section Break", "Column Break", "Tab Break"):
				kind = {"Section Break": "section", "Column Break": "column", "Tab Break": "tab"}[f["fieldtype"]]
				f["fieldname"] = f"tex_{kind}_{i}"
			if f["fieldname"] in existing:
				continue
			d["fields"].append(f)
			d["field_order"].append(f["fieldname"])
			existing.add(f["fieldname"])
			added += 1
		if added:
			d["modified"] = TIMESTAMP
			path.write_text(json.dumps(d, indent=1, ensure_ascii=False) + "\n")
			done.append(f"{folder} +{added}")

	meal = DOCTYPES / "meal_plan" / "meal_plan.json"
	d = json.loads(meal.read_text())
	for f in d["fields"]:
		if f["fieldname"] == "code":
			opts = [o for o in (f.get("options") or "").split("\n") if o]
			new = opts + [c for c in BOARD_CODES if c not in opts]
			if new != opts:
				f["options"] = "\n".join(new)
				d["modified"] = TIMESTAMP
				meal.write_text(json.dumps(d, indent=1, ensure_ascii=False) + "\n")
				done.append("meal_plan board codes")
	return done


if __name__ == "__main__":
	print(extend())
