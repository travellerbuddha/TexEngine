"""A cost-stage offer reduces the contract cost: its discount is a cost figure (G-46 review,
ADR-059 review follow-up). Guests and staff without ``price.view_cost`` never see a cost-stage
outcome (applied or refused, its discount or a basket it was compared with); staff with it see
each outcome with its stage."""

import json
import unittest
from dataclasses import replace
from decimal import Decimal

from kamra.tex.pricing import engine
from kamra.tex.pricing.enums import PromoStage
from kamra.tex.services import quoting
from kamra.tex.tests.unit import fixtures as fx
from kamra.tex.tests.unit.test_engine import DE_MARKUP, EB, spec_request, spec_terms

D = Decimal

EB_COST = replace(EB, stage=PromoStage.COST)                         # −15 % of the contract cost 330.00
NET_MIN = replace(EB, promo_id="NETMIN", name="Net minimum", stage=PromoStage.COST, min_basket=D("1000"))


def quote(*offers):
	return engine.price_stay(fx.ctx(replace(spec_terms(), offers=offers), markups=(DE_MARKUP,)), spec_request())


def ids(d: dict) -> set[str]:
	return {p["promo_id"] for p in d.get("promotions") or []}


class TestCostStageOutcomes(unittest.TestCase):
	def test_each_outcome_names_its_stage(self):
		q = quote(EB_COST)
		self.assertEqual([(p.promo_id, p.stage) for p in q.promotions], [("EB15", "COST")])
		self.assertEqual([(p.promo_id, p.stage) for p in quote(EB).promotions], [("EB15", "SELL")])
		self.assertEqual(q.totals["cost"], D("280.50"))                   # 330.00 − 49.50

	def test_the_guest_view_never_shows_a_cost_stage_offer(self):
		guest = quote(EB_COST).to_dict(internal=False)
		self.assertNotIn("EB15", ids(guest))
		text = json.dumps(guest)
		self.assertNotIn("49.5", text)                                     # the cost reduction
		self.assertNotIn("330", text)                                      # nor the cost it reveals
		self.assertEqual(ids(quote(EB).to_dict(internal=False)), {"EB15"})  # a selling offer: shown

	def test_cost_access_keeps_it_with_its_stage(self):
		full = quote(EB_COST).to_dict(internal=True)
		self.assertEqual([(p["promo_id"], p["stage"], p["discount"]) for p in full["promotions"]],
		                 [("EB15", "COST", "49.500000")])

	def test_staff_without_cost_access_never_see_it_applied_or_refused(self):
		full = quote(EB_COST, NET_MIN).to_dict(internal=True)
		refused = next(p for p in full["promotions"] if p["promo_id"] == "NETMIN")
		self.assertIn("330", refused["reason"])                           # the contract cost, as its basket
		for staff in (True, False):
			shown = quoting.strip_internal(json.loads(json.dumps(full)), staff=staff)
			self.assertEqual(ids(shown), set(), staff)
			self.assertNotIn("49.5", json.dumps(shown))
			self.assertNotIn("330", json.dumps(shown))

	def test_a_snapshot_written_before_the_stage_was_recorded(self):
		"""Older snapshots carry no ``stage``: the explanation says which offers were cost-stage."""
		full = quote(EB_COST, NET_MIN).to_dict(internal=True)
		for p in full["promotions"]:
			p.pop("stage", None)
		self.assertEqual(ids(quoting.strip_internal(json.loads(json.dumps(full)), staff=True)), set())
		sell = quote(EB).to_dict(internal=True)
		for p in sell["promotions"]:
			p.pop("stage", None)
		self.assertEqual(ids(quoting.strip_internal(sell, staff=True)), {"EB15"})   # a selling offer stays

	def test_what_a_reservation_records_as_its_promotions(self):
		"""The promotions granted on the selling price: never a cost-stage offer, with or without
		its stage recorded (the reservation's ``tex_promotions``, read in Desk)."""
		full = quote(EB_COST, NET_MIN).to_dict(internal=True)
		self.assertEqual(quoting.sold_promotions(full), [])
		for p in full["promotions"]:
			p.pop("stage", None)
		self.assertEqual(quoting.sold_promotions(full), [])
		sold = quote(EB).to_dict(internal=True)
		self.assertEqual([p["promo_id"] for p in quoting.sold_promotions(sold)], ["EB15"])
