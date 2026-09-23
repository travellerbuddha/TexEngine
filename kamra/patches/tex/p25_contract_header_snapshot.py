"""Contract header snapshot (G-50 review, ADR-045): header narrowings survive the upgrade.

Before G-50, selection read the contract header (market, sale window, channels) and pricing the
version's frozen payload, so a header narrowed after publish (a channel removed, the sale window
closed, the market changed) stopped sales. Since G-50 selection reads the version, and such a
version keeps selling only where both its payload and the header allow. This patch copies the
header's selling terms (and market) onto every published version frozen before G-50 — the
version's own selling-term columns, ``header_market`` and ``header_snapshot_at`` — so the
narrowing is fixed from now on and no longer follows later header changes. Payloads and their
hashes are never touched.

Every contract whose header differs from its live version's payload is printed and audited
(``contract.header_differs``: payload values as old, header values as new), so staff can publish
a corrective version where the difference was not meant to narrow sales. Versions that already
have a snapshot are skipped: the patch can run again safely and reports nothing twice.
"""

import json

import frappe
from frappe.utils import now_datetime

from kamra.tex.commercial.contracts import SELLING_FIELDS, active_version_header, selling_values
from kamra.tex.security.audit import audit

COMPARED = ("market", "sale_from", "sale_to", "stay_from", "stay_to", "channels")


def _payload_contract(payload: str | None) -> dict | None:
	"""The contract block of a payload frozen before G-50 (no priority key), else None."""
	try:
		block = (json.loads(payload or "{}") or {}).get("contract") or {}
	except ValueError:
		return None         # an unreadable payload never sells (integrity check); nothing to snapshot
	return block if block and "priority" not in block else None


def _payload_terms(block: dict) -> dict:
	return {"market": block.get("market"), "sale_from": block.get("sale_from"), "sale_to": block.get("sale_to"),
	        "stay_from": block.get("stay_from"), "stay_to": block.get("stay_to"),
	        "channels": sorted(block.get("channels") or [])}


def execute():
	frappe.reload_doc("tex_commercial", "doctype", "tex_contract_version")
	now = now_datetime()
	taken = reported = 0
	for c in frappe.get_all("TEX Contract", fields=["name", "property", "contract_code"], order_by="name asc"):
		rows = frappe.get_all("TEX Contract Version",
		                      filters={"contract": c.name, "status": ("!=", "Draft"), "header_snapshot_at": ("is", "not set")},
		                      fields=["name", "payload"])
		legacy = {r.name: block for r in rows if (block := _payload_contract(r.payload))}
		if not legacy:
			continue
		header = frappe.get_doc("TEX Contract", c.name)
		values = selling_values(header)
		for version in legacy:
			frappe.db.set_value("TEX Contract Version", version,
			                    {**{f: values[f] for f in SELLING_FIELDS}, "header_market": header.market,
			                     "header_snapshot_at": now}, update_modified=False)
			frappe.db.delete("TEX Contract Channel", {"parent": version, "parenttype": "TEX Contract Version"})
			for idx, channel in enumerate(values["channels"], 1):
				frappe.get_doc({"doctype": "TEX Contract Channel", "parent": version,
				                "parenttype": "TEX Contract Version", "parentfield": "channels", "idx": idx,
				                "sales_channel": channel}).db_insert()
			taken += 1
		live = active_version_header(c.name, now)
		if not live or live.version_id not in legacy:
			continue
		sold = _payload_terms(legacy[live.version_id])
		kept = {"market": header.market, **{f: values[f] for f in COMPARED if f != "market"}}
		diff = [f for f in COMPARED if (sold[f] or None) != (kept[f] or None)]
		if not diff:
			continue
		reported += 1
		audit("contract.header_differs", reference_doctype="TEX Contract", reference_name=c.name,
		      property=c.property, old={f: sold[f] for f in diff}, new={f: kept[f] for f in diff}, source="System",
		      reason=f"The header of {c.contract_code} differs from its live version {live.version_id}, frozen before "
		             "G-50; the version now sells only where both allow. Publish a corrective version if the "
		             "header was not meant to narrow it.")
		print(f"TEX contract header snapshot: {c.contract_code} ({c.property}) header differs from live version "
		      f"{live.version_id} in {', '.join(diff)}: " + "; ".join(f"{f} {sold[f]} -> {kept[f]}" for f in diff))
	print(f"TEX contract header snapshot: {taken} version(s) frozen before G-50 took their header's selling terms; "
	      f"{reported} contract(s) with a header that differs from the live payload (audit contract.header_differs)")
