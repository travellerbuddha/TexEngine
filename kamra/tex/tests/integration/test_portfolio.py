"""Portfolio dashboard (G-25, R-47): the sales KPIs of every hotel a user may report on,
per scope, money per currency; another tenant's hotels are never included."""

import frappe
from frappe.utils import add_days, getdate, now_datetime, nowdate

from kamra.tex.api import reports as rep_api
from kamra.tex.money import D
from kamra.tex.services import booking
from kamra.tex.tests.integration import fixtures as fx
from kamra.tex.tests.integration.test_commercial_flows import guest_books, setup_site_and_payments
from kamra.tex.tests.integration.test_critical_journey import TexTestCase
from kamra.tex.tests.integration.test_crm_segments import OTHER, agent, other_tenant


class TestPortfolio(TexTestCase):
	def setUp(self):
		super().setUp()
		setup_site_and_payments(self.f)
		self.other_ent = other_tenant()
		self.rm = agent("g25-rm@example.com", fx.PROPERTY, "Revenue Manager")
		self.desk = agent("g25-desk@example.com", fx.PROPERTY)                    # no report.view
		frappe.set_user("Administrator")  # nosemgrep: frappe-setuser -- fixtures
		self.ent = frappe.db.get_value("Property", fx.PROPERTY, "tex_enterprise")

	def dash(self, user=None, **kw):
		frappe.set_user(user or self.rm)  # nosemgrep: frappe-setuser -- the viewer decides the hotels
		out = rep_api.portfolio(**kw)
		frappe.set_user("Administrator")  # nosemgrep: frappe-setuser -- back
		return out

	def test_the_sales_picture_of_a_scope(self):
		before = self.dash()
		b1 = guest_books(session="g25-web")                                 # booking engine, pending payment
		b2 = guest_books(session="g25-cc", guest={"first_name": "Ana", "last_name": "Call", "email": "ana@example.com",
		                                          "country": "Germany"})
		frappe.set_user("Administrator")  # nosemgrep: frappe-setuser -- one of them came through the call centre
		frappe.db.set_value("Reservation", b2["rooms"][0]["reservation"], "tex_sales_channel", "CALL_CENTER")
		b3 = guest_books(session="g25-cxl", guest={"first_name": "Cy", "last_name": "Cancel", "email": "cy@example.com",
		                                           "country": "Germany"})
		frappe.set_user("Administrator")  # nosemgrep: frappe-setuser -- and one is cancelled
		booking.cancel_reservation(b3["rooms"][0]["reservation"], reason="changed plans", waive_penalty=True)
		frappe.get_doc({"doctype": "TEX Abandoned Booking", "property": fx.PROPERTY, "session_id": "g25-ab",
		                "stage_reached": "guest_details", "status": "Open", "value": 500, "currency": "EUR",
		                "last_event_at": now_datetime()}).insert(ignore_permissions=True)
		tomorrow = add_days(nowdate(), 1)
		frappe.get_doc({"doctype": "TEX ARI Restriction", "property": fx.PROPERTY, "restriction_date": tomorrow,
		                "stop_sell": "STOP"}).insert(ignore_permissions=True)
		dlx = frappe.db.get_value("Room Type", {"property": fx.PROPERTY, "room_type_code": "DLX"})
		from kamra.tex_commercial.doctype.tex_inventory_day.tex_inventory_day import inventory_day_name

		frappe.get_doc({"doctype": "TEX Inventory Day", "name": inventory_day_name(dlx, getdate(tomorrow)),
		                "property": fx.PROPERTY, "room_type": dlx, "inventory_date": tomorrow, "closed": 1}
		               ).insert(ignore_permissions=True)
		out = self.dash()
		hotel = next(h for h in out["hotels"] if h["hotel"] == fx.PROPERTY)
		old = next(h for h in before["hotels"] if h["hotel"] == fx.PROPERTY)
		self.assertEqual(hotel["sold"] - old["sold"], 2)                       # the cancelled one is not a sale
		self.assertEqual(hotel["sold_today"] - old["sold_today"], 2)
		value = lambda h, k: D(h[k].get("EUR", "0"))  # noqa: E731
		web = D(frappe.db.get_value("Reservation", b1["rooms"][0]["reservation"], "tex_total_amount"))
		cc = D(frappe.db.get_value("Reservation", b2["rooms"][0]["reservation"], "tex_total_amount"))
		self.assertEqual(value(hotel, "booking_value") - value(old, "booking_value"), web + cc)
		self.assertEqual(value(hotel, "direct_value") - value(old, "direct_value"), web)
		self.assertEqual(value(hotel, "call_centre_value") - value(old, "call_centre_value"), cc)
		self.assertEqual(hotel["cancellations"] - old["cancellations"], 1)
		self.assertEqual(hotel["pending_payment"] - old["pending_payment"], 2)
		self.assertEqual(value(hotel, "abandoned_value") - value(old, "abandoned_value"), D(500))
		kinds = {(a["kind"], a["date"]) for a in out["alerts"] if a["hotel"] == fx.PROPERTY}
		self.assertIn(("stop_sell", str(tomorrow)), kinds)
		self.assertIn(("closed", str(tomorrow)), kinds)
		self.assertTrue(any(m["market"] == "DE" for m in out["markets"]))
		self.assertTrue(all(isinstance(v, str) for v in out["totals"]["booking_value"].values()))   # never float

	def test_only_the_viewers_hotels_whatever_the_scope(self):
		frappe.set_user("Administrator")  # nosemgrep: frappe-setuser -- a sale at another tenant's hotel
		agent("g25-both@example.com", OTHER, "Revenue Manager")
		both = "g25-both@example.com"
		frappe.set_user("Administrator")  # nosemgrep: frappe-setuser -- and at this one too
		fx.ensure("TEX Access Grant", {"user": both, "property": fx.PROPERTY},
		          {"user": both, "scope_level": "Hotel", "property": fx.PROPERTY,
		           "permission_profile": "Revenue Manager"})
		from kamra.tex.security import scope

		scope.clear_cache()
		self.assertEqual({h["hotel"] for h in self.dash(both)["hotels"]}, {fx.PROPERTY, OTHER})
		self.assertEqual({h["hotel"] for h in self.dash(both, level="Enterprise", name=self.ent)["hotels"]},
		                 {fx.PROPERTY})
		self.assertEqual([h["hotel"] for h in self.dash()["hotels"]], [fx.PROPERTY])       # all of *my* hotels
		for kw in ({"level": "Enterprise", "name": self.other_ent}, {"level": "Hotel", "name": OTHER}):
			with self.assertRaises(frappe.PermissionError):
				self.dash(**kw)
		with self.assertRaises(frappe.PermissionError):
			self.dash(self.desk)                                              # no report.view anywhere
		frappe.set_user(self.rm)  # nosemgrep: frappe-setuser -- the scope picker lists only their own
		scopes = rep_api.portfolio_scopes()
		self.assertEqual([h["name"] for h in scopes["hotels"]], [fx.PROPERTY])
		self.assertNotIn(self.other_ent, {e["name"] for e in scopes["enterprises"]})
