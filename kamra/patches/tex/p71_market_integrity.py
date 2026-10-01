"""Market integrity (O-8, ADR-070, owner decision D-5).

- TEX Market gets ``residency_required`` ("Residents only (web)") and TEX Booking Site ``allowed_markets``
  ("Markets this site sells"; blank = every enabled market, as before).
- The domestic market TR becomes residents-only, once, at the upgrade (G-76): a web booking on it needs a
  country of residence or a nationality among its countries. A forced re-run never sets it again after an
  administrator switched it off. Fresh sites get it from the seed (``setup.MARKETS``).

No site's market list is set: every site keeps selling what it sold. No price, snapshot or payload moves."""

import frappe

from kamra.tex.security.audit import audit
from kamra.tex.setup import ran_before


def execute():
	frappe.reload_doc("tex_commercial", "doctype", "tex_market")
	frappe.reload_doc("tex_booking", "doctype", "tex_booking_site")
	if ran_before(__name__):
		return
	if frappe.db.exists("TEX Market", "TR") and not frappe.db.get_value("TEX Market", "TR", "residency_required"):
		frappe.db.set_value("TEX Market", "TR", "residency_required", 1, update_modified=False)
		audit("market.save", reference_doctype="TEX Market", reference_name="TR", old={"residency_required": 0},
		      new={"residency_required": 1}, reason="p71 (O-8, D-5): the domestic market is residents-only on the web")
