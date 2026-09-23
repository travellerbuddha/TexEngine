"""Contract header lock (G-50, ADR-045): selling terms move from the contract header to the versions.

From now on every version carries its sale and stay windows, channels, priority and default sell
currency, and a draft of a contract that was already published is priced with its own. Drafts of
published contracts therefore get the header's values: exactly what their publish would have
frozen before G-50. Each such draft gets one audit entry.

Published versions and their payloads are NOT touched, so no payload hash changes: their windows
and channels are in the payload already; a payload frozen before G-50 has no priority or sell
currency, and selection keeps reading those two from the contract header (ADR-045). Drafts of
contracts never published need nothing: until the first publish the header is their source.
"""

import frappe

from kamra.tex.commercial.contracts import SELLING_FIELDS, is_published, selling_values
from kamra.tex.security.audit import audit


def execute():
	frappe.reload_doc("tex_commercial", "doctype", "tex_contract_version")
	frappe.reload_doc("tex_commercial", "doctype", "tex_contract")
	done = 0
	for d in frappe.get_all("TEX Contract Version", filters={"status": "Draft"}, fields=["name", "contract"]):
		if not is_published(d.contract):
			continue
		header = frappe.get_doc("TEX Contract", d.contract)
		values = selling_values(header)
		# written below the controllers: a draft is editable anyway, and a half-valid legacy header
		# must not stop the migration (the draft is checked again when it is published)
		frappe.db.set_value("TEX Contract Version", d.name, {f: values[f] for f in SELLING_FIELDS},
		                    update_modified=False)
		frappe.db.delete("TEX Contract Channel", {"parent": d.name, "parenttype": "TEX Contract Version"})
		for idx, channel in enumerate(values["channels"], 1):
			frappe.get_doc({"doctype": "TEX Contract Channel", "parent": d.name, "parenttype": "TEX Contract Version",
			                "parentfield": "channels", "idx": idx, "sales_channel": channel}).db_insert()
		audit("contract.version.selling_backfill", reference_doctype="TEX Contract Version", reference_name=d.name,
		      property=header.property, new=values, source="System")
		done += 1
	print(f"TEX contract header lock: {done} draft version(s) of published contracts took their header's "
	      "selling terms")
