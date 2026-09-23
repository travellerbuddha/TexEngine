"""Guest booking API details the booking engine relies on: per-room placement in
multi-room searches (R-29), the hotel "from" price, guest-safe quotes, the basket
(totals and deposit per payment method before booking), retried bookings, return
URLs and guest input normalisation."""

import frappe

from kamra.tex.api import crs, public
from kamra.tex.money import D
from kamra.tex.services import quoting
from kamra.tex.tests.integration import fixtures as fx
from kamra.tex.tests.integration.test_commercial_flows import (
	GUEST,
	SLUG,
	guest_books,
	setup_site_and_payments,
)
from kamra.tex.tests.integration.test_critical_journey import TexTestCase

# STD takes at most 2 children, DLX 3 (fixtures): the second party fits DLX only
TWO_ROOMS = [{"adults": 2, "children": []}, {"adults": 1, "children": [4, 5, 8]}]


def _search(rooms, session="sess-s"):
	frappe.set_user("Guest")  # nosemgrep: frappe-setuser -- anonymous booking-engine visitor
	return public.search(site=SLUG, check_in=str(fx.d(6, 10)), check_out=str(fx.d(6, 13)), rooms=rooms,
	                     market="DE", session_id=session)["properties"][0]


class TestPublicBooking(TexTestCase):
	def setUp(self):
		super().setUp()
		self.p = setup_site_and_payments(self.f)
		self.std = self.f["room_types"]["STD"]
		self.dlx = self.f["room_types"]["DLX"]

	def test_each_room_is_placed_on_its_own(self):
		prop = _search(TWO_ROOMS)
		std = [o for o in prop["offers"] if o["room_type"] == self.std]
		dlx = [o for o in prop["offers"] if o["room_type"] == self.dlx]
		self.assertTrue(std, "a room type that fits room 1 must still be offered for room 1")
		for o in std:
			self.assertEqual(o["room_indexes"], [0])
			self.assertFalse(o["complete"])
			self.assertNotIn("total", o, "no grand total when a room type cannot take every room")
			self.assertEqual({r["room_index"] for r in o["rooms"]}, {0})
			self.assertTrue(any(r["room_index"] == 1 for r in o["room_reasons"]))
		for o in dlx:
			self.assertEqual(o["room_indexes"], [0, 1])
			self.assertTrue(o["complete"])
			self.assertEqual(D(o["total"]), sum(D(r["quote"]["totals"]["total"]) for r in o["rooms"]))
		# complete offers sort first
		self.assertTrue(prop["offers"][0]["complete"])
		self.assertNotIn("unplaced_rooms", prop)

		# cheapest placement: cheapest option per room, possibly of different types
		best = {}
		for o in prop["offers"]:
			for r in o["rooms"]:
				t = D(r["quote"]["totals"]["total"])
				best[r["room_index"]] = min(best.get(r["room_index"], t), t)
		self.assertEqual(D(prop["from_total"]), best[0] + best[1])
		self.assertEqual(prop["from_currency"], "EUR")

		# a booking may mix room types: STD for room 1, DLX for room 2
		o0 = next(o for o in std if o["board"] == "AI")
		o1 = next(o for o in dlx if o["board"] == "AI" and o["rate_plan"] == o0["rate_plan"])
		k0 = o0["rooms"][0]["offer_key"]
		k1 = next(r["offer_key"] for r in o1["rooms"] if r["room_index"] == 1)
		q0 = public.quote(site=SLUG, offer_key=k0, session_id="sess-s")
		q1 = public.quote(site=SLUG, offer_key=k1, session_id="sess-s")
		self.assertTrue(q0["ok"] and q1["ok"])
		basket = public.basket(site=SLUG, quote_ids=[q0["quote_id"], q1["quote_id"]], session_id="sess-s")
		self.assertEqual(D(basket["total"]), D(q0["quote"]["totals"]["total"]) + D(q1["quote"]["totals"]["total"]))

	def test_room_that_fits_nowhere_is_reported(self):
		prop = _search([{"adults": 2, "children": []}, {"adults": 4, "children": []}])
		self.assertEqual(prop.get("unplaced_rooms"), [1])
		self.assertIsNone(prop["from_total"])

	def test_from_total_compares_amounts_not_text(self):
		# with several offers the "from" price is the numerically smallest total
		prop = _search([{"adults": 2, "children": []}])
		totals = [D(o["total"]) for o in prop["offers"]]
		self.assertGreater(len(totals), 1)
		self.assertEqual(D(prop["from_total"]), min(totals))
		self.assertEqual(totals, sorted(totals))
		self.assertTrue(quoting._from_total([], 1) == (None, None))

	def test_guest_quotes_never_carry_cost(self):
		prop = _search([{"adults": 2, "children": [8]}])
		for o in prop["offers"] + prop["unavailable"]:
			for r in o["rooms"]:
				for k in quoting.INTERNAL_TOTALS:
					self.assertNotIn(k, r["quote"]["totals"])
				self.assertNotIn("explanation", r["quote"])
		q = public.quote(site=SLUG, offer_key=prop["offers"][0]["rooms"][0]["offer_key"], session_id="sess-s")
		for k in quoting.INTERNAL_TOTALS:
			self.assertNotIn(k, q["quote"]["totals"])

	def test_basket_lists_amount_due_per_method(self):
		prop = _search([{"adults": 2, "children": [8]}], session="sess-b")
		rp = frappe.db.get_value("Rate Plan", {"property": fx.PROPERTY, "code": "FLEX"})
		offer = next(o for o in prop["offers"] if o["room_type"] == self.std and o["board"] == "AI"
		             and o["rate_plan"] == rp)
		q = public.quote(site=SLUG, offer_key=offer["rooms"][0]["offer_key"], session_id="sess-b")
		out = public.basket(site=SLUG, quote_ids=[q["quote_id"]], session_id="sess-b")
		self.assertEqual(out["total"], q["quote"]["totals"]["total"])
		card = next(m for m in out["methods"] if m["method"] == "Card")
		self.assertTrue(card["available"])
		self.assertEqual(D(card["due_now"]), (D(out["total"]) * D("0.30")).quantize(D("0.01")))
		self.assertEqual(D(card["due_now"]) + D(card["balance_after"]), D(out["total"]))
		self.assertNotIn("payment_policy", out["rooms"][0])
		# another visitor's session cannot read this basket
		with self.assertRaises(frappe.ValidationError):
			public.basket(site=SLUG, quote_ids=[q["quote_id"]], session_id="someone-else")

	def test_retried_booking_returns_a_way_to_pay(self):
		first = guest_books(session="sess-retry")
		self.assertTrue(first["manage_token"])
		# same visitor, same key: the first response was lost
		quote_id = frappe.db.get_value("TEX Quote", {"booking": first["booking"]}, "name")
		self.assertTrue(quote_id)
		again = public.book(site=SLUG, quote_ids=[quote_id], guest=GUEST, payment_method="Card",
		                    session_id="sess-retry", idempotency_key="idem-sess-retry")
		self.assertTrue(again["idempotent_replay"])
		self.assertEqual(again["booking"], first["booking"])
		self.assertEqual(again["payment"]["transaction"], first["payment"]["transaction"])
		# the replay token opens the booking like the manage link, but is not the manage link
		self.assertNotEqual(again["manage_token"], first["manage_token"])
		self.assertEqual(public.booking_status(token=again["manage_token"])["booking"], first["booking"])
		# a tampered resume token is refused
		with self.assertRaises(frappe.PermissionError):
			public.booking_status(token=again["manage_token"][:-4] + "AAAA")
		# once the attempt failed, the replay no longer restarts it (pay_booking does)
		pmt = first["payment"]
		public.mock_pay(transaction=pmt["transaction"], outcome="fail", sig=pmt["fields"]["fail_sig"])
		third = public.book(site=SLUG, quote_ids=[quote_id], guest=GUEST, payment_method="Card",
		                    session_id="sess-retry", idempotency_key="idem-sess-retry")
		self.assertIsNone(third["payment"])
		retry = public.pay_booking(token=third["manage_token"])
		self.assertNotEqual(retry["transaction"], pmt["transaction"])

	def test_return_url_booking_placeholder(self):
		site = frappe.get_doc("TEX Booking Site", SLUG)
		own = frappe.utils.get_url("/book/x/confirmation/{booking}")
		if own.startswith("https://") or frappe.conf.get("developer_mode"):
			self.assertEqual(public._safe_return_url(site, own, "TB-1"), own.replace("{booking}", "TB-1"))
		self.assertIsNone(public._safe_return_url(site, own))   # placeholder left unresolved
		self.assertIsNone(public._safe_return_url(site, "https://evil.example.com/{booking}", "TB-1"))

	def test_guest_input_is_normalised(self):
		code = frappe.db.get_value("Country", "Germany", "code")
		self.assertEqual(public._country((code or "de").upper()), "Germany")
		self.assertEqual(public._country("Germany"), "Germany")
		self.assertIsNone(public._country("Atlantis"))
		b = guest_books(session="sess-sr", guest={**GUEST, "country": "DE", "special_requests": "x" * 900})
		res = frappe.db.get_value("TEX Booking Room", {"parent": b["booking"]}, "reservation")
		self.assertEqual(len(frappe.db.get_value("Reservation", res, "special_requests") or ""), 900)

	def test_agent_booking_response_has_no_guest_token(self):
		frappe.set_user("Administrator")  # nosemgrep: frappe-setuser -- staff booking in the test
		res = crs.search(check_in=str(fx.d(6, 10)), check_out=str(fx.d(6, 13)),
		                 rooms=[{"adults": 2, "children": []}], market="DE", channel="CALL_CENTER",
		                 properties=[fx.PROPERTY])
		offers = res["properties"][0]["offers"]
		if not offers:
			self.skipTest("no call-centre contract in the fixtures")
		q = crs.quote(offer_key=offers[0]["rooms"][0]["offer_key"])
		out = crs.book(quote_ids=[q["quote_id"]], guest=GUEST, payment_method="Card",
		               confirm_without_payment=1)
		self.assertNotIn("manage_token", out)
