"""Market master data administration (R-13): platform-only writes, audited, and a
warning when two equally specific markets claim the same country (the guest would
get no market automatically)."""

import frappe

from kamra.tex.api import admin
from kamra.tex.security import scope
from kamra.tex.tests.integration import fixtures as fx
from kamra.tex.tests.integration.test_critical_journey import TexTestCase


class TestMarketAdmin(TexTestCase):
	def test_platform_admin_creates_and_edits_markets(self):
		out = admin.save_market({"market_code": "nordx", "market_name": "Nordics test", "countries": "se, no,dk",
		                         "default_currency": "EUR", "default_language": "en"})
		self.assertEqual(out["name"], "NORDX")
		self.assertEqual(out["overlaps"], [])
		self.assertEqual(frappe.db.get_value("TEX Market", "NORDX", "countries"), "DK, NO, SE")
		self.assertTrue(frappe.db.exists("TEX Audit Event", {"action": "market.save", "reference_name": "NORDX"}))
		with self.assertRaises(frappe.ValidationError):
			admin.save_market({"market_code": "NORDX", "market_name": "again"})
		# same-size market claiming a shared country is reported, not silently accepted
		out = admin.save_market({"market_code": "SCANX", "market_name": "Scandinavia test", "countries": "SE,NO,FI"})
		self.assertEqual(out["overlaps"], [{"market": "NORDX", "countries": ["NO", "SE"]}])
		rows = {r["name"]: r for r in admin.markets()}
		self.assertTrue(rows["NORDX"]["overlaps"])
		# the code is fixed; name, countries and state are editable
		admin.save_market({"name": "SCANX", "market_code": "OTHER", "market_name": "Scandinavia", "countries": "FI",
		                   "disabled": 1})
		row = frappe.db.get_value("TEX Market", "SCANX", ["market_code", "market_name", "disabled"], as_dict=True)
		self.assertEqual((row.market_code, row.market_name, row.disabled), ("SCANX", "Scandinavia", 1))
		self.assertFalse(frappe.db.exists("TEX Market", "OTHER"))

	def test_hotel_users_can_read_but_not_write_markets(self):
		user = fx.ensure_user("market-rm@example.com", ["Revenue Manager"])
		fx.ensure("TEX Access Grant", {"user": user, "property": fx.PROPERTY},
		          {"user": user, "scope_level": "Hotel", "property": fx.PROPERTY,
		           "permission_profile": "Hotel Admin"})
		scope.clear_cache()
		frappe.set_user(user)  # nosemgrep: frappe-setuser -- hotel admin, not platform
		self.assertTrue(any(m["name"] == "DE" for m in admin.markets()))
		with self.assertRaises(frappe.PermissionError):
			admin.save_market({"market_code": "XX", "market_name": "nope"})
		frappe.set_user("Guest")  # nosemgrep: frappe-setuser -- anonymous
		with self.assertRaises(frappe.PermissionError):
			admin.markets()
