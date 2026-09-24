"""Coupon uses carry when they were given back (G-51, ADR-054).

The historical simulator counts a limited promotion's uses as they were held at the simulated
sale time: a use counts from its creation until its release. ``TEX Promotion Redemption`` gains
``released_at``, written once by its controller when the use is released.

A use released before this patch was last written when it was released (nothing writes a
released use: the booking service only re-states the amount of held ones, and the controller
now refuses to take a released use again), so its ``modified`` is its release time. The patch
copies it; rows that already have a release time are left alone, so it can run again safely.

Approximate by construction (G-51 review L3): a released row that something did write after its
release before this patch (a Desk or data-import edit; TEX itself never does) gets that later
time, so for such a row the simulator's coupon history counts the use a little longer than it
was held. Rows released after this patch carry their exact release time.
"""

import frappe


def execute():
	frappe.reload_doc("tex_commercial", "doctype", "tex_promotion_redemption")
	frappe.db.sql("""UPDATE `tabTEX Promotion Redemption` SET released_at = modified
	                 WHERE status = 'Released' AND released_at IS NULL""")
	frappe.db.sql("""UPDATE `tabTEX Promotion Redemption` SET released_at = NULL
	                 WHERE status != 'Released' AND released_at IS NOT NULL""")
