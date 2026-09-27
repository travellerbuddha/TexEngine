"""NEW-8 (audit Part 2I): a legacy action log row without a hotel is platform level.

The Agent Action Log is now a strict hotel-scoped DocType (``perm.STRICT_DOCTYPES``): a row without a hotel
is read only by platform administrators, where every tenant's roles read it before. ``savings.log_action``
takes the hotel from the record a new row is about; this patch gives the rows written before theirs, with
the same rule (``savings.hotel_of``): a Property, a record with a ``property`` field, a guest's one hotel, a
user's one hotel. A row with none (several hotels, no reference) stays platform level.

Batches by name, without touching ``modified``. Prints how many rows got a hotel and how many stayed
platform level (numbers only); a second run gives none."""

import frappe

from kamra.savings import hotel_of

DOCTYPE = "Agent Action Log"
BATCH = 500


def execute():
	given = left = 0
	last = ""
	while True:
		rows = frappe.get_all(DOCTYPE, filters={"property": ("is", "not set"), "name": (">", last)},
		                      fields=["name", "reference_doctype", "reference_name"], order_by="name asc",
		                      limit=BATCH)
		if not rows:
			break
		for row in rows:
			try:
				hotel = hotel_of(row.reference_doctype, row.reference_name)
			except Exception:
				hotel = None
			if hotel:
				frappe.db.set_value(DOCTYPE, row.name, "property", hotel, update_modified=False)
				given += 1
			else:
				left += 1
		last = rows[-1].name
	print(f"p65: {given} action log row(s) given their hotel, {left} left platform level")
