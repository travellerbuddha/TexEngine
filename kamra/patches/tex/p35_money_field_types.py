"""G-72 (ADR-055): TEX commercial decimal fields keep 9 decimal places.

Period rates, occupancy values, board amounts, rate plan and offer values, markups, promotion
values, FX policy adjustments, cancellation/payment values, tax rates and loyalty values were
Float fields of precision 6, which Frappe v16 makes DECIMAL(21,6) columns: a 7th decimal was
rounded away on save. Their DocTypes now declare precision 9 (money Currency, percentages
Percent), and the DocType sync that runs before this patch widens the columns to DECIMAL(21,9).

Widening keeps every stored value (none has more than 6 places), and a DECIMAL column never
holds binary noise (it rounds what is written to it), so no value is rewritten here. This
patch checks, and prints what it found:

- every G-72 column is DECIMAL(21,9); a column the sync left narrower is synced from its
  DocType file again;
- every published contract version's frozen payload still hashes to its recorded hash.
  Payloads are never changed (prices are computed from them); a mismatch is reported and
  logged, and ``load_terms`` refuses to price from such a version as it always did.

Re-runnable; prints counts only.
"""

import json

import frappe


def _scales() -> dict[tuple[str, str], int | None]:
	from kamra.tex.commercial.decimals import NINE_PLACES

	tables = sorted({f"tab{dt}" for dt, _ in NINE_PLACES})
	found = {(t[3:], c): s for t, c, s in frappe.db.sql(
		"""SELECT table_name, column_name, numeric_scale FROM information_schema.columns
		   WHERE table_schema = DATABASE() AND table_name IN %(tables)s""", {"tables": tables})}
	return {key: found.get(key) for key in NINE_PLACES}


def execute():
	from kamra.tex.pricing import serialize

	narrow = sorted(k for k, scale in _scales().items() if scale is not None and scale < 9)
	for doctype in sorted({dt for dt, _ in narrow}):
		module = frappe.db.get_value("DocType", doctype, "module")
		frappe.reload_doc(frappe.scrub(module), "doctype", frappe.scrub(doctype), force=True)
	still = sorted(k for k, scale in _scales().items() if scale is not None and scale < 9)

	checked, failed = 0, []
	for v in frappe.get_all("TEX Contract Version", filters={"status": ("!=", "Draft")},
	                        fields=["name", "payload", "payload_hash"], order_by="name asc"):
		if not v.payload:
			continue
		checked += 1
		try:
			ok = serialize.payload_hash(json.loads(v.payload)) == v.payload_hash
		except (TypeError, ValueError):
			ok = False
		if not ok:
			failed.append(v.name)

	if still or failed:
		frappe.log_error(title="p35: G-72 decimal fields", message=json.dumps(
			{"narrow_columns": [".".join(k) for k in still], "payload_hash_mismatch": failed}, indent=1))
	print(f"p35: {len(_scales())} decimal fields of 9 places, {len(narrow)} widened here, "
	      f"{len(still)} still narrower" + (f" ({', '.join('.'.join(k) for k in still)})" if still else "")
	      + f"; {checked} published payload(s) verified, {len(failed)} failed their hash"
	      + (f" ({', '.join(failed[:20])})" if failed else ""))
