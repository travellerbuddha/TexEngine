"""G-48 (ADR-057): restriction cells gain a channel scope and a booking window.

``TEX ARI Restriction`` gains ``channel_scope`` (the Booking Engine, the Call Center or both,
instead of one sales channel) and ``book_from`` / ``book_to`` (the sale dates on which the night
is sold). The DocType sync adds the columns, blank: every existing cell keeps its meaning.

A cell's ``scope_key`` (one cell per scope and date) appends the channel scope only when it is
set, so a cell stored before keeps its key. This patch checks that: a row whose stored key is
not the key of its scope is re-keyed (none is expected), and it prints what it found.
Re-runnable.
"""

import frappe


def execute():
	frappe.reload_doc("tex_commercial", "doctype", "tex_ari_restriction")
	if not frappe.db.has_column("TEX ARI Restriction", "channel_scope"):
		return
	from kamra.tex_commercial.doctype.tex_ari_restriction.tex_ari_restriction import SCOPE, scope_key

	rows = frappe.get_all("TEX ARI Restriction", fields=["name", "scope_key", "channel_scope", *SCOPE])
	fixed = 0
	for r in rows:
		key = scope_key(r)
		if key != r.scope_key:
			frappe.db.set_value("TEX ARI Restriction", r.name, "scope_key", key, update_modified=False)
			fixed += 1
	print(f"p38: {len(rows)} restriction cell(s), {fixed} re-keyed")
