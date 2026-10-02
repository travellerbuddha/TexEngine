"""Finding a reservation (UX revision 2026-10, ``crs.reservations``): staff are often given only the
channel's own booking number (an OTA's reference). The search finds a reservation by it too and
returns it, so the list can show it; everything else the search matched it still matches."""

import frappe

from kamra.tex.api import crs
from kamra.tex.tests.integration import fixtures as fx
from kamra.tex.tests.integration.test_inventory import InventoryCase


class TestReservationSearch(InventoryCase):
	def test_the_channel_s_reference_finds_the_reservation(self):
		res = self.tex_book("DLX", who="uxsearch")
		booking = frappe.db.get_value("Reservation", res, "tex_booking")
		frappe.db.set_value("TEX Booking", booking, "external_ref", "BDC-UX-4711-2026")
		found = crs.reservations(property=fx.PROPERTY, q="UX-4711")
		self.assertEqual([r["name"] for r in found], [res])
		self.assertEqual(found[0]["channel_ref"], "BDC-UX-4711-2026")
		# what it matched before, it still matches
		self.assertIn(res, [r["name"] for r in crs.reservations(property=fx.PROPERTY, q=res)])
		self.assertIn(res, [r["name"] for r in crs.reservations(property=fx.PROPERTY, q="uxsearch.g49@")])
		self.assertEqual(crs.reservations(property=fx.PROPERTY, q="BDC-NOPE-0000"), [])
