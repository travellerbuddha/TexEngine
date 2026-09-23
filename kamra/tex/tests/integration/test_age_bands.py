"""G-52 (R-08): child age bands through publish, per hotel and per market, and a child's
date of birth as an alternative to an age.

Bands are entered in years and priced in whole months: "2.95" ends at 35 months, so next
to a band from 3 years a child of 2y11m has no band. Publishing (and saving a pricing
policy) refuses such a gap and names the months. A contract takes the version's bands,
else those of the most specific live pricing policy that defines bands (ADR-043)."""

import frappe
from frappe.utils import add_days, add_months, getdate, now_datetime

from kamra.tex.commercial import contracts
from kamra.tex.money import D
from kamra.tex.pricing.model import ChildSpec, StayRequest
from kamra.tex.services import quoting
from kamra.tex.tests.integration import fixtures as fx
from kamra.tex.tests.integration.test_critical_journey import pick
from kamra.tex.tests.integration.test_pricing_policies import INF, PolicyCase, child, policy

INF_295 = {"band_code": "INF", "label": "Infant", "from_age": 0, "to_age": 2.95, "is_infant": 1}
CHA = {"band_code": "CHA", "label": "Child A", "from_age": 3, "to_age": 6.99}
CHB = {"band_code": "CHB", "label": "Child B", "from_age": 7, "to_age": 11.99}
HOTEL_BANDS = [{"band_code": "INF", "label": "Infant", "from_age": 0, "to_age": 1.99, "is_infant": 1},
               {"band_code": "CHD", "label": "Child", "from_age": 2, "to_age": 11.99}]
DE_BANDS = [INF, CHA, CHB]
HOTEL_DE_BANDS = [{"band_code": "BABY", "label": "Baby", "from_age": 0, "to_age": 0.99, "is_infant": 1},
                  {"band_code": "KID", "label": "Kid", "from_age": 1, "to_age": 11.99}]


def band_months(version: str) -> list[tuple]:
	return [(b.code, b.from_months, b.to_months) for b in contracts.load_terms(version).age_bands]


class TestAgeBandHygiene(PolicyCase):
	def test_a_gap_in_a_version_is_refused_at_publish_naming_the_months(self):
		c = fx.create_contract(self.f, code="GAP", publish=False, age_bands=[INF_295, CHA, CHB],
		                       occupancy_rules=[child("INF", "MULTIPLY", 0), child("CHA", "PERCENT_OF", 25),
		                                        child("CHB", "PERCENT_OF", 50)])
		report = contracts.validate_version(c["version"])
		self.assertFalse(report["ok"])
		gap = next(i for i in report["issues"] if i["code"] == "AGE_BANDS")
		self.assertIn("gap at 35 months (2y11m)", gap["message"])
		with self.assertRaises(frappe.ValidationError) as cm:
			contracts.publish(c["version"])
		self.assertIn("35 months (2y11m)", str(cm.exception))
		self.assertEqual(frappe.db.get_value("TEX Contract Version", c["version"], "status"), "Draft")

	def test_a_pricing_policy_with_a_gap_is_refused_when_saved(self):
		with self.assertRaisesRegex(frappe.ValidationError, r"gap at 35 months \(2y11m\)"):
			policy("PP gap", market="DE", live=False, bands=[INF_295, CHA, CHB])
		with self.assertRaisesRegex(frappe.ValidationError, r"gap at 24–35 months"):
			policy("PP gap 2", market="DE", live=False, bands=[HOTEL_BANDS[0], CHA, CHB])


class TestBandsPerHotelAndMarket(PolicyCase):
	def setUp(self):
		super().setUp()
		policy("PP Hotel bands", property=fx.PROPERTY, bands=HOTEL_BANDS,
		       rules=[child("INF", "MULTIPLY", 0), child("CHD", "PERCENT_OF", 50)])
		policy("PP DE bands", market="DE", bands=DE_BANDS,
		       rules=[child("INF", "MULTIPLY", 0), child("CHA", "PERCENT_OF", 25), child("CHB", "PERCENT_OF", 40)])

	def occupancy(self, version: str, market: str, *kids: ChildSpec) -> D:
		"""Occupancy of one LOW night in STD for 2 adults and ``kids``."""
		req = StayRequest(property=fx.PROPERTY, room_type=self.std, board="AI", check_in=fx.d(6, 10),
		                  check_out=fx.d(6, 11), adults=2, children=kids, sale_at=now_datetime(), market=market,
		                  channel="DIRECT_WEB", sell_currency="EUR", rate_plan=self.flex)
		q, _terms = quoting.price_request(version, req, check_capacity=False)
		self.assertTrue(q.sellable, q.reasons)
		return q.nights[0].occupancy

	def test_each_contract_takes_the_band_set_of_its_hotel_and_market(self):
		de = fx.create_contract(self.f, code="BDE", market="DE", age_bands=[], occupancy_rules=[])
		uk = fx.create_contract(self.f, code="BUK", market="UK", age_bands=[], occupancy_rules=[])
		self.assertEqual(band_months(de["version"]), [("INF", 0, 36), ("CHA", 36, 84), ("CHB", 84, 144)])   # market
		self.assertEqual(band_months(uk["version"]), [("INF", 0, 24), ("CHD", 24, 144)])                    # hotel
		# a hotel + market policy with bands beats both for this hotel's DE contracts
		policy("PP Hotel DE bands", property=fx.PROPERTY, market="DE", bands=HOTEL_DE_BANDS,
		       rules=[child("BABY", "MULTIPLY", 0), child("KID", "PERCENT_OF", 30)])
		de2 = fx.create_contract(self.f, code="BDE2", market="DE", age_bands=[], occupancy_rules=[])
		self.assertEqual(band_months(de2["version"]), [("BABY", 0, 12), ("KID", 12, 144)])
		# the version's own bands replace every policy set
		own = fx.create_contract(self.f, code="BOWN", market="DE")
		self.assertEqual([b[0] for b in band_months(own["version"])], ["INF", "CHA", "CHB"])
		# sold contracts keep the set frozen at their publish
		self.assertEqual(band_months(de["version"])[0], ("INF", 0, 36))

	def test_the_same_child_is_priced_by_the_band_of_that_set(self):
		de = fx.create_contract(self.f, code="PDE", market="DE", age_bands=[], occupancy_rules=[])
		uk = fx.create_contract(self.f, code="PUK", market="UK", age_bands=[], occupancy_rules=[])
		two_and_a_half = ChildSpec(dob=add_months(fx.d(6, 10), -30))       # 30 months on arrival
		self.assertEqual(self.occupancy(de["version"], "DE", two_and_a_half), D("200.00"))   # DE infant ×0
		self.assertEqual(self.occupancy(uk["version"], "UK", two_and_a_half), D("250.00"))   # hotel child 50 %


class TestChildDateOfBirth(PolicyCase):
	def setUp(self):
		super().setUp()
		fx.create_contract(self.f, code="DOB", occupancy_rules=[child("INF", "MULTIPLY", 0),
		                                                        child("CHA", "PERCENT_OF", 25),
		                                                        child("CHB", "PERCENT_OF", 50)])
		self.ci, self.co = fx.d(6, 10), fx.d(6, 11)

	def search(self, *children):
		return quoting.search(properties=[fx.PROPERTY], check_in=self.ci, check_out=self.co,
		                      rooms=[{"adults": 2, "children": list(children)}], market="DE", channel="DIRECT_WEB",
		                      currency="EUR", internal=True)

	def test_a_date_of_birth_prices_the_child_in_months_on_arrival(self):
		# 2y11m on arrival: an infant, although "3" would already be a child A
		dob = add_days(add_months(self.ci, -36), 1)
		offer = pick(self.search({"dob": str(dob)})["properties"][0])
		quote = offer["rooms"][0]["quote"]
		self.assertEqual(quote["request"]["children"][0]["dob"], str(dob))
		slot = next(s for s in quote["explanation"] if s["code"] == "CHILD_SLOT")
		self.assertIn("Child 1 (2y11m, Infant)", slot["text"])
		third_birthday = add_months(self.ci, -36)
		offer = pick(self.search({"dob": str(third_birthday)})["properties"][0])
		slot = next(s for s in offer["rooms"][0]["quote"]["explanation"] if s["code"] == "CHILD_SLOT")
		self.assertIn("Child 1 (3y, Child A)", slot["text"])
		# the offer carries the child's age on arrival for display; pricing used the date of birth
		self.assertEqual(offer["rooms"][0]["quote"]["request"]["children"][0]["age"], 3)

	def test_a_date_of_birth_is_checked_on_the_server(self):
		tomorrow = add_days(getdate(now_datetime()), 1)
		with self.assertRaisesRegex(frappe.ValidationError, "cannot be in the future"):
			self.search({"dob": str(tomorrow)})
		eighteen_on_arrival = add_months(self.ci, -18 * 12)
		with self.assertRaisesRegex(frappe.ValidationError, "18 or older on arrival"):
			self.search({"dob": str(eighteen_on_arrival)})
		with self.assertRaisesRegex(frappe.ValidationError, "Invalid date of birth"):
			self.search({"dob": "31.02.2020"})
		# the day before the 18th birthday, still a child
		self.assertTrue(self.search({"dob": str(add_days(eighteen_on_arrival, 1))})["properties"])
