"""The sell price beside the grid's contract price (UX revision 2026-10, ``grid.sell_prices`` /
``crs.ari_sell_prices``).

* a night's sell price is what the CRS search sells that night for: the same room, party (2 adults),
  base board, rate plan, market and channel, with the markups and promotions in force now;
* a promotion in force changes it, and the cell names it; a draft (not activated) one does not;
* a contract with rate plans prices the one asked, else its first, and says which; an unknown plan
  is refused, never replaced;
* a contract with no version on sale answers so (nothing to sell yet), and nothing is written;
* ``price.view`` at the hotel: an outsider is refused.
"""

from datetime import timedelta

import frappe
from frappe.utils import add_days

from kamra.tex.api import crs as crs_api
from kamra.tex.services import quoting
from kamra.tex.tests.integration import fixtures as fx
from kamra.tex.tests.integration.test_inventory import InventoryCase


class TestGridSellPrices(InventoryCase):
	def setUp(self):
		super().setUp()
		self.contract = self.c["contract"]
		self.night = self.ci
		self.flex, self.nrf = self.f["rate_plans"]["FLEX"], self.f["rate_plans"]["NRF"]

	def sell(self, **kw) -> dict:
		args = {"property": fx.PROPERTY, "contract": self.contract, "start": str(self.night), "days": 2,
		        "channel": "CALL_CENTER", **kw}
		return crs_api.ari_sell_prices(**args)

	def cell(self, out: dict, room_type: str, night) -> dict:
		return next(c for c in out["cells"] if c["room_type"] == room_type and c["date"] == str(night))

	def searched(self, room_type: str, rate_plan: str) -> str:
		res = quoting.search(properties=[fx.PROPERTY], check_in=self.night, check_out=add_days(self.night, 1),
		                     rooms=[{"adults": 2}], market="DE", channel="CALL_CENTER", currency="EUR")
		res = res["properties"][0]
		e = next(e for e in res["offers"] + res["unavailable"]
		         if e["room_type"] == room_type and e["board"] == "AI" and e["rate_plan"] == rate_plan)
		return e["rooms"][0]["quote"]["totals"]["total"]

	def test_a_night_sells_at_what_the_search_sells_it_for(self):
		out = self.sell(rate_plan=self.flex)
		self.assertTrue(out["on_sale"])
		self.assertEqual((out["rate_plan"], out["board"], out["market"], out["currency"], out["adults"]),
		                 (self.flex, "AI", "DE", "EUR", 2))
		for rt in (self.std, self.dlx):
			self.assertEqual(self.cell(out, rt, self.night)["total"], self.searched(rt, self.flex))
		# the non-refundable plan (-10 %) is its own price, asked by name
		nrf = self.sell(rate_plan=self.nrf)
		self.assertEqual(self.cell(nrf, self.std, self.night)["total"], self.searched(self.std, self.nrf))
		self.assertNotEqual(self.cell(nrf, self.std, self.night)["total"], self.cell(out, self.std, self.night)["total"])

	def test_the_plan_is_named_never_guessed(self):
		out = self.sell()
		self.assertIn(out["rate_plan"], (self.flex, self.nrf))
		self.assertEqual({p["code"] for p in out["rate_plans"]}, {self.flex, self.nrf})
		self.assertRaises(frappe.ValidationError, self.sell, rate_plan="NO-SUCH-PLAN")

	def test_a_promotion_in_force_changes_it_and_is_named(self):
		before = self.cell(self.sell(rate_plan=self.flex), self.std, self.night)
		promo = frappe.get_doc({"doctype": "TEX Promotion", "promotion_name": "Grid sell 10", "property": fx.PROPERTY,
		                        "kind": "SPECIAL_OFFER", "trigger": "Automatic", "value_type": "PERCENT", "value": 10,
		                        "stay_from": self.night - timedelta(days=1), "stay_to": self.night + timedelta(days=5),
		                        "tex_status": "Draft"}).insert()
		# a draft sells nothing: the grid's price is unchanged
		self.assertEqual(self.cell(self.sell(rate_plan=self.flex), self.std, self.night)["total"], before["total"])
		from kamra.tex.commercial import revisions

		revisions.activate("TEX Promotion", promo.name)
		after = self.cell(self.sell(rate_plan=self.flex), self.std, self.night)
		self.assertLess(float(after["total"]), float(before["total"]))
		self.assertIn("Grid sell 10", after["promotions"])
		self.assertEqual(after["total"], self.searched(self.std, self.flex))

	def test_nothing_on_sale_and_nothing_written(self):
		draft = fx.create_contract(self.f, code="DE-SELL-DRAFT", publish=False)
		modified = frappe.db.get_value("TEX Contract", draft["contract"], "modified")
		out = self.sell(contract=draft["contract"])
		self.assertFalse(out["on_sale"])
		self.assertEqual(out["cells"], [])
		self.assertEqual(frappe.db.get_value("TEX Contract", draft["contract"], "modified"), modified)

	def test_an_outsider_is_refused(self):
		frappe.set_user("Guest")  # nosemgrep: frappe-setuser -- test: an outsider
		try:
			self.assertRaises(frappe.PermissionError, self.sell)
		finally:
			frappe.set_user("Administrator")  # nosemgrep: frappe-setuser -- test: back to the test user
