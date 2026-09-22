"""Türkiye localization pack (TEX Engine).

Accommodation: KDV 10 % and Konaklama Vergisi (accommodation tax). KV is levied on
the room fee excluding KDV; KDV is computed on the fee including KV, so KDV is a
compound tax in TEX's data-driven rules. Rates are defaults that a hotel can
override with a Custom TEX tax profile — confirm current rates with your accountant
(the accommodation-tax rate has been changed by law several times).

Food & beverage KDV 10 %; other services (spa, transfer…) KDV 20 %.
"""

from decimal import Decimal

import frappe

KDV_ACCOMMODATION = Decimal("10")
KONAKLAMA_VERGISI = Decimal("2")
KDV_FOOD = Decimal("10")
KDV_SERVICES = Decimal("20")


def calculate_room_tax(property, room_type_doc, nightly_rate) -> Decimal:
	"""Legacy single-rate interface (folios): effective combined rate of KV + KDV."""
	kv = KONAKLAMA_VERGISI / 100
	kdv = KDV_ACCOMMODATION / 100
	return ((kv + kdv * (1 + kv)) * 100).quantize(Decimal("0.01"))


def fnb_tax_rate(property) -> float:
	return float(KDV_FOOD)


def tax_rate_options(property) -> list:
	return [0, 1, 10, 20]


def invoice_context(prop_doc) -> dict:
	return {
		"tax_label": "KDV",
		"tax_id_label": "VKN",
		"service_code": None,
		"sac": None,
		"place_of_supply": prop_doc.get("city"),
		"split": [("tax", Decimal("1"))],
		"footer": "Bu belge elektronik ortamda oluşturulmuştur.",
	}


def locale(prop_doc) -> dict:
	currency = prop_doc.get("currency") or "TRY"
	symbol = frappe.db.get_value("Currency", currency, "symbol")
	return {
		"currency_symbol": symbol or "₺",
		"locale": "tr-TR",
		"currency": currency,
		"tax_label": "KDV",
		"tax_id_label": "VKN",
		"tax_rates": tax_rate_options(prop_doc.name),
	}


def tex_tax_rules(prop_doc, room_type_doc=None) -> list[dict]:
	"""Data-driven TEX tax rules (kamra.tex.pricing.model.TaxRule fields)."""
	return [
		{"code": "KV", "name": "Konaklama Vergisi", "rate": KONAKLAMA_VERGISI, "applies_to": ["ACCOMMODATION"],
		 "compound": False, "order": 1},
		{"code": "KDV", "name": "KDV", "rate": KDV_ACCOMMODATION, "applies_to": ["ACCOMMODATION"],
		 "compound": True, "order": 2},
		{"code": "KDV-FOOD", "name": "KDV", "rate": KDV_FOOD, "applies_to": ["EXTRA:FOOD"], "order": 3},
		{"code": "KDV-SVC", "name": "KDV", "rate": KDV_SERVICES,
		 "applies_to": ["EXTRA:SERVICE", "EXTRA:TRANSFER"], "order": 4},
		{"code": "KDV-ACC", "name": "KDV", "rate": KDV_ACCOMMODATION, "applies_to": ["EXTRA:ACCOMMODATION"],
		 "order": 5},
	]
