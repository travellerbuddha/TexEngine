"""A promotion's effect on a price before it is activated (UX revision 2026-10,
``policies.promotion_check``), and what the promotions list says each one covers.

Staff create a discount for a market and stay dates and want to see what it does to a price with
the pricing engine, not with a calculator. A draft promotion is priced nowhere until it is
activated, so the check prices the stay twice: without any revision of the promotion and with the
record as saved now. These tests pin that it uses the engine's own outcome, that it never changes
what is sold, and its permissions.
"""

from decimal import Decimal

import frappe
from frappe.utils import add_to_date, now_datetime

from kamra.tex.api import policies as policy_api
from kamra.tex.security import scope
from kamra.tex.tests.integration import fixtures as fx
from kamra.tex.tests.integration.test_inventory import InventoryCase

D = Decimal


class TestPromotionCheck(InventoryCase):
	def promo(self, **kw) -> str:
		return policy_api.save_record("TEX Promotion", {
			"promotion_name": "UX check 15", "property": fx.PROPERTY, "trigger": "Automatic", "value_type": "PERCENT",
			"value": 15, "applies_to": "ACCOMMODATION", "markets": "DE", **kw})["name"]

	def check(self, name: str, **kw) -> dict:
		args = {"name": name, "contract": self.c["contract"], "room_type": self.dlx, "board": "AI",
		        "check_in": str(self.ci), "check_out": str(self.co), "adults": 2,
		        "rate_plan": self.f["rate_plans"]["FLEX"], "market": "DE", "channel": "CALL_CENTER", **kw}
		return policy_api.promotion_check(**args)

	def test_a_draft_is_priced_by_the_engine_without_being_activated(self):
		name = self.promo()
		sold_before = self.entry()["rooms"][0]["quote"]["totals"]["total"]
		out = self.check(name)
		self.assertTrue(out["sellable"], out)
		self.assertTrue(out["outcome"]["applied"], out["outcome"])
		self.assertLess(D(out["with"]["total"]), D(out["without"]["total"]))
		# 15 % of the accommodation, as the engine applies a sell-stage percentage
		self.assertEqual(D(out["without"]["discounts"]), D("0"))
		self.assertEqual(D(out["with"]["discounts"]), (D(out["without"]["accommodation"]) * D("0.15")).quantize(D("0.01")))
		# what is sold did not change: the draft is still a draft and the search prices as before
		self.assertEqual(frappe.db.get_value("TEX Promotion", name, "tex_status"), "Draft")
		self.assertEqual(self.entry()["rooms"][0]["quote"]["totals"]["total"], sold_before)
		self.assertEqual(D(out["without"]["total"]), D(sold_before))

	def test_another_market_is_not_applied_and_the_engine_says_why(self):
		name = self.promo(markets="UK")
		out = self.check(name)
		self.assertFalse(out["outcome"]["applied"])
		self.assertTrue(out["outcome"]["reason"])
		self.assertEqual(out["with"]["total"], out["without"]["total"])

	def test_a_revision_is_checked_in_place_of_its_live_revision(self):
		live = self.promo(value=10)
		policy_api.activate("TEX Promotion", live, at=str(add_to_date(now_datetime(), minutes=-1)))
		draft = policy_api.revise("TEX Promotion", live)["name"]
		policy_api.save_record("TEX Promotion", {"name": draft, "value": 20})
		ten = self.check(live)
		twenty = self.check(draft)
		# the live 10 % is not counted next to the 20 %: one revision at a time
		self.assertEqual(ten["without"]["total"], twenty["without"]["total"])
		self.assertFalse([p for p in twenty["applied_others"] if p["promo_id"] == live])
		self.assertLess(D(twenty["with"]["total"]), D(ten["with"]["total"]))

	def test_cost_viewers_only_and_the_contract_s_hotel(self):
		name = self.promo()
		viewer = fx.ensure_user("ux-promo-viewer@example.com", ["Hotel Admin"])
		fx.ensure("TEX Access Grant", {"user": viewer, "property": fx.PROPERTY},
		          {"user": viewer, "scope_level": "Hotel", "property": fx.PROPERTY, "permission_profile": "Viewer"})
		frappe.set_user(viewer)  # nosemgrep: frappe-setuser -- a viewer without price.view_cost
		scope.clear_cache()
		with self.assertRaises(frappe.PermissionError):
			self.check(name)

	def test_the_list_says_what_each_promotion_covers(self):
		name = self.promo(sale_to=str(fx.d(5, 31)), stay_from=str(fx.d(7, 1)), stay_to=str(fx.d(7, 31)), room_types=self.dlx)
		row = next(r for r in policy_api.list_records("TEX Promotion", property=fx.PROPERTY) if r["name"] == name)
		self.assertEqual((row["markets"], row["room_types"], row["value_type"], row["trigger"]), ("DE", self.dlx, "PERCENT", "Automatic"))
		self.assertEqual((str(row["stay_from"]), str(row["stay_to"]), str(row["sale_to"])), (str(fx.d(7, 1)), str(fx.d(7, 31)), str(fx.d(5, 31))))
		self.assertEqual(D(str(row["value"])), D("15"))
