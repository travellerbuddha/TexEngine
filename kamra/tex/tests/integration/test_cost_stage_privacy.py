"""Cost-stage offers never reach guests or staff without ``price.view_cost`` (G-46 review, High;
ADR-059 review follow-up).

A cost-stage offer lowers the contract cost before the markup: its discount (and a basket it
was compared with) is a cost figure. The test contract sells at cost 750.00 (+7 % markup =
802.50); a 10 % cost-stage contract offer takes 75.00 off the cost (675.00, sold at 722.25), and
a cost-stage promotion with a minimum basket of 5000 is refused against the cost of 750.00.
Neither may show on the booking engine (search, quote, booking, manage page, e-mail), nor to an
agent (CRS search and quote, the reservation, a proposed change, the simulator); a revenue
manager sees both with their stage."""

import json
from unittest import mock

import frappe
from frappe.utils import add_to_date, now_datetime

from kamra.tex.api import crs as crs_api
from kamra.tex.api import policies as policy_api
from kamra.tex.api import public, ui_crs
from kamra.tex.security import scope
from kamra.tex.services import modification, notify
from kamra.tex.tests.integration import fixtures as fx
from kamra.tex.tests.integration.test_commercial_flows import GUEST, SLUG, setup_site_and_payments
from kamra.tex.tests.integration.test_critical_journey import TexTestCase
from kamra.tex.tests.integration.test_crm_segments import agent

NET = "NETEB"
COST_OFFER = {"offer_code": NET, "offer_name": "Net early booking", "kind": "EARLY_BOOKING",
              "value_type": "PERCENT", "value": 10, "stage": "COST"}
# figures that reveal the contract cost: the cost, the cost after the offer, the offer's discount
COST_FIGURES = ("750.0", "675.0", "75.000000")


def cost_leaks(payload) -> list[str]:
	text = json.dumps(payload, default=str)
	return [f for f in COST_FIGURES if f in text]


def promo_ids(q: dict | None) -> set[str]:
	return {p.get("promo_id") for p in (q or {}).get("promotions") or []}


class TestCostStageOffersStayInternal(TexTestCase):
	def setUp(self):
		super().setUp()
		setup_site_and_payments(self.f, offers=[COST_OFFER])
		doc = policy_api.save_record("TEX Promotion", {
			"promotion_name": "Net minimum", "property": fx.PROPERTY, "stage": "COST", "value_type": "PERCENT",
			"value": 5, "applies_to": "ACCOMMODATION", "min_basket": 5000, "currency": "EUR"})
		policy_api.activate("TEX Promotion", doc["name"], at=str(add_to_date(now_datetime(), minutes=-1)))
		self.net_min = doc["name"]
		self.agent = agent("g46r-agent@example.com", fx.PROPERTY)                     # Reservations Agent
		self.rm = agent("g46r-rm@example.com", fx.PROPERTY, "Revenue Manager")
		frappe.set_user("Administrator")  # nosemgrep: frappe-setuser -- fixtures

	def as_user(self, user, fn, *a, **kw):
		frappe.set_user(user)  # nosemgrep: frappe-setuser -- the viewer decides what is shown
		scope.clear_cache()
		try:
			return fn(*a, **kw)
		finally:
			frappe.set_user("Administrator")  # nosemgrep: frappe-setuser -- back
			scope.clear_cache()

	def guest_offer(self, session):
		res = self.as_user("Guest", public.search, site=SLUG, check_in=str(fx.d(6, 10)), check_out=str(fx.d(6, 13)),
		                   rooms=[{"adults": 2, "children": [8]}], market="DE", session_id=session)
		rt = frappe.db.get_value("Room Type", {"property": fx.PROPERTY, "room_type_code": "STD"})
		rp = frappe.db.get_value("Rate Plan", {"property": fx.PROPERTY, "code": "FLEX"})
		offer = next(o for o in res["properties"][0]["offers"]
		             if o["room_type"] == rt and o["board"] == "AI" and o["rate_plan"] == rp)
		return res, offer

	def test_the_offer_prices_the_stay(self):
		"""The fixture: the cost offer applies (722.25 = 675.00 + 7 %), the promotion is refused."""
		_res, offer = self.guest_offer("g46r-fix")
		self.assertEqual(offer["rooms"][0]["quote"]["totals"]["accommodation"], "722.25")

	def test_the_booking_engine_never_shows_it(self):
		res, offer = self.guest_offer("g46r-web")
		self.assertEqual(cost_leaks(res), [])
		self.assertNotIn(NET, promo_ids(offer["rooms"][0]["quote"]))
		q = self.as_user("Guest", public.quote, site=SLUG, offer_key=offer["rooms"][0]["offer_key"],
		                 session_id="g46r-web")
		self.assertTrue(q["ok"], q)
		self.assertEqual((cost_leaks(q), promo_ids(q["quote"]) & {NET, self.net_min}), ([], set()))
		sent = []
		with mock.patch.object(notify, "_deliver",
		                       side_effect=lambda *a, **kw: sent.append((a, kw)) or {"queued": True}):
			b = self.as_user("Guest", public.book, site=SLUG, quote_ids=[q["quote_id"]], guest=GUEST,
			                 payment_method="Card", session_id="g46r-web", idempotency_key="idem-g46r-web")
			notify.booking_mail(b["booking"], b["manage_token"])                  # the booking e-mail
		self.assertEqual(cost_leaks({k: v for k, v in b.items() if k != "payment"}), [])
		page = self.as_user("Guest", public.booking_status, token=b["manage_token"])
		self.assertEqual(cost_leaks(page), [])
		self.assertTrue(sent)
		self.assertEqual(cost_leaks(sent), [])
		# the rooms of a booking quoted together answer as one room does
		_res, again = self.guest_offer("g46r-web2")
		rooms = self.as_user("Guest", public.quote_rooms, site=SLUG, rooms=[{"offer_key": again["rooms"][0]["offer_key"]}],
		                     session_id="g46r-web2")
		self.assertTrue(rooms["ok"], rooms)
		self.assertEqual((cost_leaks(rooms), promo_ids(rooms["rooms"][0]["quote"]) & {NET, self.net_min}), ([], set()))

	def test_the_reservation_records_only_what_the_guest_was_granted(self):
		"""``tex_promotions`` (read in Desk by every role that reads reservations) names the promotions
		of the selling price, never a cost-stage offer; the snapshot keeps it, with its stage, for cost
		access. Also after a change."""
		b = self.as_user("Guest", public.book, site=SLUG, quote_ids=[self._web_quote("g46r-rec")], guest=GUEST,
		                 payment_method="Card", session_id="g46r-rec", idempotency_key="idem-g46r-rec")
		name = b["rooms"][0]["reservation"]
		snap = json.loads(frappe.db.get_value("Reservation", name, "tex_pricing_snapshot"))
		self.assertIn((NET, True, "COST"), [(p["promo_id"], p["applied"], p.get("stage")) for p in snap["promotions"]])
		self.assertNotIn(NET, frappe.db.get_value("Reservation", name, "tex_promotions") or "")
		p = modification.propose(name, {"check_out": str(fx.d(6, 14))}, basis="ORIGINAL_VERSION")
		modification.apply(p["proposal_token"], reason="one more night")
		snap = json.loads(frappe.db.get_value("Reservation", name, "tex_pricing_snapshot"))
		self.assertIn(NET, promo_ids(snap))
		self.assertNotIn(NET, frappe.db.get_value("Reservation", name, "tex_promotions") or "")

	def test_an_agent_never_sees_it_applied_or_refused(self):
		res = self.as_user(self.agent, crs_api.search, properties=[fx.PROPERTY], check_in=str(fx.d(6, 10)),
		                   check_out=str(fx.d(6, 13)), rooms=[{"adults": 2, "children": [8]}], market="DE",
		                   channel="CALL_CENTER")
		prop = res["properties"][0]
		self.assertEqual(cost_leaks(prop), [])
		for o in prop["offers"]:
			for r in o["rooms"]:
				self.assertEqual(promo_ids(r["quote"]) & {NET, self.net_min}, set())
		offer = prop["offers"][0]["rooms"][0]
		q = self.as_user(self.agent, crs_api.quote, offer_key=offer["offer_key"])
		self.assertEqual((cost_leaks(q.get("quote")), promo_ids(q.get("quote")) & {NET, self.net_min}), ([], set()))
		b = self.as_user("Guest", public.book, site=SLUG, quote_ids=[self._web_quote("g46r-agent")], guest=GUEST,
		                 payment_method="Card", session_id="g46r-agent", idempotency_key="idem-g46r-agent")
		name = b["rooms"][0]["reservation"]
		seen = self.as_user(self.agent, crs_api.reservation, name=name)
		self.assertEqual((cost_leaks(seen["pricing"]), promo_ids(seen["pricing"]) & {NET, self.net_min}), ([], set()))
		change = self.as_user(self.agent, modification.propose, name, {"check_out": str(fx.d(6, 14))},
		                      basis="ORIGINAL_VERSION")
		self.assertEqual(promo_ids(change.get("proposed")) & {NET, self.net_min}, set())
		self.assertEqual(cost_leaks(change.get("proposed")), [])
		# the screens' own endpoints, the rooms quoted together and the historical simulator
		ui = self.as_user(self.agent, ui_crs.search, properties=[fx.PROPERTY], check_in=str(fx.d(6, 10)),
		                  check_out=str(fx.d(6, 13)), rooms=[{"adults": 2, "children": [8]}], market="DE",
		                  channel="CALL_CENTER")
		self.assertEqual(cost_leaks(ui), [])
		self.assertEqual({i for o in ui["properties"][0]["offers"] for r in o["rooms"] for i in promo_ids(r["quote"])}
		                 & {NET, self.net_min}, set())
		rooms = self.as_user(self.agent, crs_api.quote_rooms, rooms=[{"offer_key": offer["offer_key"]}])
		self.assertEqual((cost_leaks(rooms), promo_ids(rooms["rooms"][0].get("quote")) & {NET, self.net_min}),
		                 ([], set()))
		detail = self.as_user(self.agent, ui_crs.reservation, name=name)
		self.assertEqual((cost_leaks(detail), promo_ids(detail["pricing"]) & {NET, self.net_min}), ([], set()))
		sim = self.as_user(self.agent, crs_api.simulate, reservation=name, sale_at=str(now_datetime()))
		self.assertTrue(sim["simulated"]["sellable"], sim)
		self.assertEqual((cost_leaks(sim), promo_ids(sim["simulated"]) & {NET, self.net_min}), ([], set()))
		# the revenue manager sees both, each with its stage
		rm = self.as_user(self.rm, crs_api.reservation, name=name)
		stages = {p["promo_id"]: (p["applied"], p.get("stage")) for p in rm["pricing"]["promotions"]}
		self.assertEqual((stages[NET], stages[self.net_min]), ((True, "COST"), (False, "COST")))

	def _web_quote(self, session) -> str:
		_res, offer = self.guest_offer(session)
		q = self.as_user("Guest", public.quote, site=SLUG, offer_key=offer["rooms"][0]["offer_key"], session_id=session)
		return q["quote_id"]
