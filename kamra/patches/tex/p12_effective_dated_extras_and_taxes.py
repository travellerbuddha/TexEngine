"""Extras and tax rules become effective-dated revisions (G-20).

* Every existing extra becomes a live first revision from its creation. A disabled one
  stays disabled (off sale) and can be switched back on by a revision.
* Every TEX hotel gets a TEX Tax Policy holding the taxes it is sold with today (its
  custom table, or its localization pack's rules), live from the hotel's creation. From
  then on a tax change is a revision, so pricing at an earlier sale time uses the taxes in
  force then. Stays sold before this migration are reproduced with the taxes as of the
  migration (their price-locked snapshot stays the record).
* Tax policies are a legal/finance setting: the new ``tax.edit`` capability goes to the
  seeded profiles that carry it (Hotel/Group/Enterprise Admin, Finance).

Idempotent: the extras step runs on the first execution only (a draft made since is
never put live by a re-run); hotels that already have a live tax policy are left alone.
"""

import frappe

from kamra.tex.security.capabilities import DEFAULT_PROFILES

CAP = "tax.edit"


def execute():
	frappe.reload_doc("tex_commercial", "doctype", "tex_extra")
	frappe.reload_doc("tex_commercial", "doctype", "tex_tax_rule")
	frappe.reload_doc("tex_commercial", "doctype", "tex_tax_policy")
	_extras()
	_capability()
	if frappe.db.has_column("Property", "tex_tax_profile"):
		_tax_policies()
	from kamra.tex.setup import ensure_indexes

	ensure_indexes()
	frappe.clear_cache()


def _extras():
	# a disabled extra stays a live revision with disabled=1: it is off sale, and a later
	# revision can switch it back on in the same chain (translations and links follow)
	if frappe.db.exists("Patch Log", {"patch": __name__}):
		return       # a forced re-run: the drafts made since the first run are never put live
	frappe.db.sql("""UPDATE `tabTEX Extra` SET tex_status='Active', active_from=creation, active_to=NULL,
	                 revision_no=1 WHERE IFNULL(tex_status, '') IN ('', 'Draft')
	                 AND IFNULL(revision_of, '') = ''""")


def _capability():
	for name, caps in DEFAULT_PROFILES.items():
		if CAP not in caps or not frappe.db.exists("TEX Permission Profile", name):
			continue
		if frappe.db.exists("TEX Profile Capability", {"parent": name, "parenttype": "TEX Permission Profile",
		                                               "capability": CAP}):
			continue
		doc = frappe.get_doc("TEX Permission Profile", name)
		doc.append("capabilities", {"capability": CAP})
		doc.save(ignore_permissions=True)


def _tax_policies():
	from kamra.tex.commercial import tax_policies
	from kamra.tex.legacy import is_tex_hotel

	for p in frappe.get_all("Property", fields=["name", "creation"], order_by="name"):
		if not is_tex_hotel(p.name):
			continue
		frappe.db.savepoint("g20_tax_policy")
		try:
			# trusted: the migration states what has been on sale since the hotel was set up
			name = tax_policies.seed(p.name, at=p.creation, backdate=True)
		except Exception:
			# a hotel whose old rules the policy refuses keeps them (not effective-dated):
			# the migration never stops for one hotel
			frappe.db.rollback(save_point="g20_tax_policy")
			frappe.log_error(title=f"G-20: no tax policy for {p.name}")
			print(f"G-20: {p.name}: no tax policy created (see Error Log); it keeps its current rules")
			continue
		if name:
			print(f"G-20: {p.name}: tax policy {name}")
