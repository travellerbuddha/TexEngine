"""FX provider adapters: TCMB (Central Bank of the Republic of Türkiye) and ECB.

Parsers are pure (XML text → rate tuples) so they are unit-tested offline; the
fetch functions store immutable TEX FX Rate rows (idempotent per provider/pair/
type/date). Rates are expressed as 1 base = rate quote.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

TCMB_URL = "https://www.tcmb.gov.tr/kurlar/today.xml"
ECB_URL = "https://www.ecb.europa.eu/stats/eurofxref/eurofxref-daily.xml"

TCMB_FIELDS = {"ForexSelling": "FOREX_SELLING", "ForexBuying": "FOREX_BUYING",
               "BanknoteSelling": "BANKNOTE_SELLING", "BanknoteBuying": "BANKNOTE_BUYING"}


def _dec(text: str | None) -> Decimal | None:
	if not text or not text.strip():
		return None
	try:
		v = Decimal(text.strip().replace(",", "."))
	except InvalidOperation:
		return None
	return v if v > 0 else None


def parse_tcmb(xml_text: str) -> tuple[date, list[tuple[str, str, str, Decimal]]]:
	"""→ (rate date, [(base, 'TRY', rate_type, rate)]); rates are normalised per 1 unit."""
	root = ET.fromstring(xml_text)
	raw_date = root.attrib.get("Date") or root.attrib.get("Tarih")
	if "/" in (raw_date or ""):
		m, d, y = raw_date.split("/")
		rate_date = date(int(y), int(m), int(d))
	else:
		d, m, y = (raw_date or "").split(".")
		rate_date = date(int(y), int(m), int(d))
	out = []
	for cur in root.findall("Currency"):
		code = cur.attrib.get("CurrencyCode") or cur.attrib.get("Kod")
		if not code or code == "XDR":
			continue
		unit = _dec(cur.findtext("Unit")) or Decimal(1)
		for field, rate_type in TCMB_FIELDS.items():
			v = _dec(cur.findtext(field))
			if v:
				out.append((code, "TRY", rate_type, v / unit))
	return rate_date, out


def parse_ecb(xml_text: str) -> tuple[date, list[tuple[str, str, str, Decimal]]]:
	ns = {"e": "http://www.ecb.int/vocabulary/2002-08-01/eurofxref"}
	root = ET.fromstring(xml_text)
	day = root.find(".//e:Cube[@time]", ns)
	rate_date = datetime.strptime(day.attrib["time"], "%Y-%m-%d").date()
	out = []
	for c in day.findall("e:Cube", ns):
		v = _dec(c.attrib.get("rate"))
		if v:
			out.append(("EUR", c.attrib["currency"], "REFERENCE", v))
	return rate_date, out


def fetch(provider: str = "TCMB") -> dict:
	import frappe
	import requests

	url = {"TCMB": TCMB_URL, "ECB": ECB_URL}.get(provider)
	if not url:
		frappe.throw(f"Unknown FX provider {provider}")
	r = requests.get(url, timeout=20)
	r.raise_for_status()
	rate_date, rates = (parse_tcmb if provider == "TCMB" else parse_ecb)(r.text)
	now = frappe.utils.now_datetime()
	added = 0
	for base, quote, rate_type, rate in rates:
		if frappe.db.exists("TEX FX Rate", {"provider": provider, "base_currency": base, "quote_currency": quote,
		                                    "rate_type": rate_type, "rate_date": rate_date}):
			continue
		frappe.get_doc({"doctype": "TEX FX Rate", "provider": provider, "base_currency": base,
		                "quote_currency": quote, "rate_type": rate_type, "rate": rate, "rate_date": rate_date,
		                "fetched_at": now, "source_ref": url}).insert(ignore_permissions=True)
		added += 1
	return {"provider": provider, "rate_date": str(rate_date), "added": added, "seen": len(rates)}


def daily_fetch() -> None:
	"""Scheduler entry: fetch both providers; failures are logged, never raised."""
	from kamra.tex.security.audit import log_exception

	for provider in ("TCMB", "ECB"):
		try:
			fetch(provider)
		except Exception:
			log_exception(f"TEX FX fetch {provider}")
