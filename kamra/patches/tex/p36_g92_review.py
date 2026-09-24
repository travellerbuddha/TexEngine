"""G-92 review (ADR-052): hotels TEX already sold stay live in TEX.

Before this change a hotel was sold only through TEX from the moment it joined TEX (a hotel group,
an enterprise or any contract): the Desk form and REST were refused at once. Now a hotel that joins
TEX is *onboarding* until an administrator sets it live (``Property.tex_live_from``). Every hotel
TEX already sold when this patch runs keeps today's behaviour: it is set live now, and audited
(``hotel.go_live``, reason "upgrade"). TEX sold it when one of its contracts was published (the
CRS, the booking engine and the channels could sell it) or TEX booked a stay there.

A hotel in TEX that TEX never sold is onboarding (G-76, ADR-058): its Desk keeps selling it until
an administrator sets it live. That is every hotel of a Kamra database upgraded to TEX, which p01
puts in a hotel group in the same migration: setting them live would stop their Desk before TEX
could sell anything, what ADR-052 M3 set out to avoid. Hotels outside TEX are untouched.

Re-runnable: a hotel that is live already is left as it is. Prints what it did.
"""

import frappe
from frappe.utils import now_datetime


def sold_through_tex(property: str) -> bool:
	"""A contract version of the hotel was published (it may be superseded or archived since), or
	TEX booked a stay there."""
	published = frappe.db.sql(
		"""SELECT 1 FROM `tabTEX Contract Version` v JOIN `tabTEX Contract` c ON c.name = v.contract
		   WHERE c.property = %s AND v.status != 'Draft' AND IFNULL(v.payload_hash, '') != '' LIMIT 1""", property)
	return bool(published) or bool(frappe.db.exists("TEX Booking", {"property": property}))


def execute():
	if not frappe.db.has_column("Property", "tex_live_from"):
		return
	from kamra.tex.legacy import is_tex_hotel
	from kamra.tex.security.audit import audit

	now = now_datetime()
	done, onboarding = [], []
	for p in frappe.get_all("Property", filters={"tex_live_from": ("is", "not set")}, pluck="name", order_by="name"):
		if not is_tex_hotel(p):
			continue
		if not sold_through_tex(p):
			onboarding.append(p)
			continue
		# a plain column write: the Property controller accepts this field only from TEX's go-live
		frappe.db.set_value("Property", p, "tex_live_from", now, update_modified=False)
		audit("hotel.go_live", reference_doctype="Property", reference_name=p, property=p,
		      new={"tex_live_from": str(now)}, reason="upgrade: already sold through TEX", source="System")
		done.append(p)
	print(f"p36: {len(done)} TEX hotel(s) set live in TEX: {', '.join(done) or '-'}; {len(onboarding)} onboarding "
	      f"(TEX never sold them: the Desk sells them until an administrator sets them live): "
	      f"{', '.join(onboarding) or '-'}")
