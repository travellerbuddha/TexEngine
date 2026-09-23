"""Allotment cutoff and release (G-49, ADR-048): two separate deadlines.

``TEX Allotment.release_days`` keeps its meaning: unsold rooms go back to general sale that many
days before each night. The new ``cutoff_days`` is the contract's booking deadline. It starts at 0
(no cutoff), so every existing allotment sells exactly as before: capped by its allotment until
the release, then from general sale until the night.

The controller now keeps both within 0 to 365 days. A negative release day count behaved like 0 for
every night still on sale, so it is set to 0 here. A count above 365 is left as it is and printed:
its owner decides the right value the next time the allotment is saved. The patch can run again
safely.
"""

import frappe

from kamra.tex_commercial.doctype.tex_allotment.tex_allotment import MAX_DAYS


def execute():
	frappe.reload_doc("tex_commercial", "doctype", "tex_allotment")
	frappe.db.sql("UPDATE `tabTEX Allotment` SET cutoff_days = 0 WHERE cutoff_days IS NULL OR cutoff_days < 0")
	frappe.db.sql("UPDATE `tabTEX Allotment` SET release_days = 0 WHERE release_days IS NULL OR release_days < 0")
	for name, days in frappe.db.sql("SELECT name, release_days FROM `tabTEX Allotment` WHERE release_days > %s",
	                                MAX_DAYS):
		print(f"TEX Allotment {name}: release {days} days is above {MAX_DAYS}; review it before its next save")
