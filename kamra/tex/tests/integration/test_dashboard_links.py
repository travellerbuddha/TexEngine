"""The dashboard's "today" figures open the reservation list (UX revision 2026-10): the list for the
dashboard's day (``crs.reservations(arriving=…)`` / ``departing=…``) holds exactly the reservations the
dashboard counts, by the same statuses; a cancelled stay is in neither."""

import frappe
from frappe.utils import add_days, getdate, nowdate

from kamra.tex.api import crs
from kamra.tex.reports import service as reports
from kamra.tex.tests.integration import fixtures as fx
from kamra.tex.tests.integration.test_inventory import InventoryCase


class TestDashboardLinks(InventoryCase):
	def test_the_list_holds_what_the_dashboard_counts(self):
		today = getdate(nowdate())
		before = reports.dashboard(fx.PROPERTY)["today"]
		self.assertEqual(before["date"], str(today))
		# written on a free date far ahead, then moved to the day (inventory is checked on insert, and a
		# past check-in is refused): only the dates and statuses matter here
		def stay(status: str, check_in, check_out) -> str:
			far = add_days(today, 300)
			name = self.desk(code="STD", check_in=far, check_out=add_days(far, 1), status=status).name
			frappe.db.set_value("Reservation", name, {"check_in_date": check_in, "check_out_date": check_out})
			return name

		arriving = [stay(s, today, add_days(today, 2)) for s in ("Confirmed", "Pending Payment", "Cancelled")]
		leaving = [stay(s, add_days(today, -2), today) for s in ("Confirmed", "Checked In", "Cancelled")]
		after = reports.dashboard(fx.PROPERTY)["today"]
		self.assertEqual(after["arrivals"] - before["arrivals"], 2)
		self.assertEqual(after["departures"] - before["departures"], 2)

		arr = [r["name"] for r in crs.reservations(property=fx.PROPERTY, arriving=str(today), limit=200)]
		dep = [r["name"] for r in crs.reservations(property=fx.PROPERTY, departing=str(today), limit=200)]
		self.assertEqual(len(arr), after["arrivals"])
		self.assertEqual(len(dep), after["departures"])
		self.assertEqual(set(arriving) & set(arr), set(arriving[:2]))
		self.assertEqual(set(leaving) & set(dep), set(leaving[:2]))
		# another day's list is another list
		self.assertNotIn(arriving[0], [r["name"] for r in crs.reservations(property=fx.PROPERTY,
		                                                                      arriving=str(add_days(today, 1)))])
