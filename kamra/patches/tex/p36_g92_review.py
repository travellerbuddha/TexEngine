"""G-92 review (ADR-052): hotels already in TEX stay live in TEX.

Before this change a hotel was sold only through TEX from the moment it joined TEX (a hotel group,
an enterprise or any contract): the Desk form and REST were refused at once. Now a hotel that joins
TEX is *onboarding* until an administrator sets it live (``Property.tex_live_from``). Every hotel
that is in TEX when this patch runs keeps today's behaviour: it is set live now, and audited
(``hotel.go_live``, reason "upgrade"). Hotels outside TEX are untouched.

Re-runnable: a hotel that is live already is left as it is. Prints what it did.
"""

import frappe
from frappe.utils import now_datetime


def execute():
	if not frappe.db.has_column("Property", "tex_live_from"):
		return
	from kamra.tex.legacy import is_tex_hotel
	from kamra.tex.security.audit import audit

	now = now_datetime()
	done = []
	for p in frappe.get_all("Property", filters={"tex_live_from": ("is", "not set")}, pluck="name", order_by="name"):
		if not is_tex_hotel(p):
			continue
		# a plain column write: the Property controller accepts this field only from TEX's go-live
		frappe.db.set_value("Property", p, "tex_live_from", now, update_modified=False)
		audit("hotel.go_live", reference_doctype="Property", reference_name=p, property=p,
		      new={"tex_live_from": str(now)}, reason="upgrade: already sold through TEX", source="System")
		done.append(p)
	print(f"p36: {len(done)} TEX hotel(s) set live in TEX: {', '.join(done) or '-'}")
