"""Guest booking API details the booking engine relies on: per-room placement in
multi-room searches (R-29), the hotel "from" price, guest-safe quotes, the basket
(totals and deposit per payment method before booking), retried bookings, return
URLs and guest input normalisation."""

import frappe

from kamra.tex.api import crs, public
from kamra.tex.money import D
from kamra.tex.security import scope
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


class TestStaffBookingControls(TexTestCase):
	def setUp(self):
		super().setUp()
		setup_site_and_payments(self.f)
		self.agent = fx.ensure_user("unpaid-agent@example.com", ["Call Center Agent"])
		fx.ensure("TEX Access Grant", {"user": self.agent, "property": fx.PROPERTY},
		          {"user": self.agent, "scope_level": "Hotel", "property": fx.PROPERTY,
		           "permission_profile": "Reservations Agent"})
		scope.clear_cache()

	def _quote(self):
		res = crs.search(check_in=str(fx.d(6, 10)), check_out=str(fx.d(6, 13)),
		                 rooms=[{"adults": 2, "children": []}], market="DE", channel="CALL_CENTER",
		                 properties=[fx.PROPERTY])
		offers = res["properties"][0]["offers"]
		if not offers:
			self.skipTest("no call-centre contract in the fixtures")
		return crs.quote(offer_key=offers[0]["rooms"][0]["offer_key"])["quote_id"]

	def test_confirming_unpaid_needs_its_own_capability(self):
		frappe.set_user(self.agent)  # nosemgrep: frappe-setuser -- reservations agent
		scope.clear_cache()
		self.assertFalse(scope.has_capability("reservation.confirm_unpaid", fx.PROPERTY))
		with self.assertRaises(frappe.PermissionError):
			crs.book(quote_ids=[self._quote()], guest=GUEST, payment_method="Card", confirm_without_payment=1)
		# without the flag the agent books normally (pending payment)
		out = crs.book(quote_ids=[self._quote()], guest=GUEST, payment_method="Card")
		self.assertEqual(out["status"], "Pending Payment")
		frappe.set_user("Administrator")  # nosemgrep: frappe-setuser -- platform admin
		out = crs.book(quote_ids=[self._quote()], guest=GUEST, payment_method="Card", confirm_without_payment=1)
		self.assertEqual(out["status"], "Confirmed")

	def test_resend_confirmation_rotates_the_manage_link(self):
		b = guest_books(session="sess-resend")
		old = b["manage_token"]
		self.assertEqual(public.booking_status(token=old)["booking"], b["booking"])
		frappe.set_user(self.agent)  # nosemgrep: frappe-setuser -- reservations agent
		scope.clear_cache()
		out = crs.resend_confirmation(booking=b["booking"])
		self.assertEqual(out["booking"], b["booking"])
		frappe.set_user("Guest")  # nosemgrep: frappe-setuser -- the guest's old link
		with self.assertRaises(frappe.PermissionError):
			public.booking_status(token=old)
		frappe.set_user("Administrator")  # nosemgrep: frappe-setuser -- audit check
		self.assertTrue(frappe.db.exists("TEX Audit Event", {"action": "booking.confirmation_resent",
		                                                     "reference_name": b["booking"]}))

	def test_booking_payment_link_amounts_are_decimal_strings(self):
		b = guest_books(session="sess-links")
		frappe.set_user("Administrator")  # nosemgrep: frappe-setuser -- staff view
		from kamra.tex.payments import service as pay

		pay.create_link(property=fx.PROPERTY, amount="12.5", currency="EUR", description="Balance",
		                booking=b["booking"])
		out = crs.booking(name=b["booking"])
		self.assertEqual(out["payment_links"][-1]["amount"], "12.50")
		self.assertEqual(out["payment_links"][-1]["paid_amount"], "0.00")
		self.assertNotIn("public_url", out["payment_links"][-1])


class TestGuestStats(TexTestCase):
	def setUp(self):
		super().setUp()
		setup_site_and_payments(self.f)

	def test_upcoming_bookings_are_not_stays_yet(self):
		from kamra.tex.crm import service as crm_svc

		b = guest_books(session="sess-stats", guest={**GUEST, "email": "stats.guest@example.com"})
		frappe.set_user("Administrator")  # nosemgrep: frappe-setuser -- stats check
		res = b["rooms"][0]["reservation"]
		guest = frappe.db.get_value("Reservation", res, "guest")
		g = frappe.db.get_value("Guest", guest, ["tex_stays", "tex_last_stay", "tex_lifetime_currency"], as_dict=True)
		self.assertEqual((g.tex_stays, g.tex_last_stay, g.tex_lifetime_currency), (0, None, None))
		# the stay happened: check-out in the past (moved directly; the price lock guards the form)
		frappe.db.set_value("Reservation", res, {"check_in_date": frappe.utils.add_days(frappe.utils.nowdate(), -3),
		                                         "check_out_date": frappe.utils.add_days(frappe.utils.nowdate(), -1)})
		self.assertGreaterEqual(crm_svc.refresh_recent_checkouts(), 1)
		g = frappe.db.get_value("Guest", guest, ["tex_stays", "tex_lifetime_value", "tex_lifetime_currency"],
		                        as_dict=True)
		self.assertEqual(g.tex_stays, 1)
		self.assertEqual(g.tex_lifetime_currency, "EUR")
		self.assertEqual(D(g.tex_lifetime_value), D(b["total"]))
		row = next(r for r in crm_svc.list_guests(q="stats.guest@example.com")["rows"] if r["name"] == guest)
		self.assertEqual(row["tex_lifetime_value"], b["total"])


class TestContentTranslation(TexTestCase):
	def setUp(self):
		super().setUp()
		setup_site_and_payments(self.f)

	def tearDown(self):
		frappe.local.lang = "en"
		super().tearDown()

	def test_guest_sees_hotel_texts_in_their_language(self):
		from kamra.tex.api import content as content_api
		from kamra.tex.services import content

		std = self.f["room_types"]["STD"]
		flex = frappe.db.get_value("Rate Plan", {"property": fx.PROPERTY, "code": "FLEX"})
		trf = frappe.db.get_value("TEX Extra", {"property": fx.PROPERTY, "extra_code": "TRF"})
		frappe.set_user("Administrator")  # nosemgrep: frappe-setuser -- hotel content editor
		out = content_api.save(fx.PROPERTY, [
			{"ref_doctype": "Room Type", "ref_name": std, "field": "room_type_name", "language": "de",
			 "text": "Standardzimmer"},
			{"ref_doctype": "Rate Plan", "ref_name": flex, "field": "rate_plan_name", "language": "de",
			 "text": "Flexibel"},
			{"ref_doctype": "TEX Extra", "ref_name": trf, "field": "extra_name", "language": "de",
			 "text": "Flughafentransfer"},
		])
		self.assertEqual(out["created"], 3)
		items = {(i["ref_doctype"], i["ref_name"]): i for i in content_api.items(fx.PROPERTY)["items"]}
		self.assertEqual(items[("Room Type", std)]["translations"]["de"]["room_type_name"], "Standardzimmer")

		frappe.set_user("Guest")  # nosemgrep: frappe-setuser -- anonymous visitor
		frappe.local.lang = "de"
		prop = _search([{"adults": 2, "children": []}], session="sess-de")
		self.assertEqual(prop["rooms"][std]["name"], "Standardzimmer")
		offer = next(o for o in prop["offers"] if o["room_type"] == std and o["rate_plan"] == flex)
		self.assertEqual(offer["rate_plan_info"]["name"], "Flexibel")
		q = public.quote(site=SLUG, offer_key=offer["rooms"][0]["offer_key"], extras=[{"code": "TRF", "quantity": 1}],
		                 session_id="sess-de")
		accom = next(ln for ln in q["quote"]["lines"] if ln["kind"] == "ACCOMMODATION")
		self.assertTrue(accom["description"].startswith("Standardzimmer · "), accom["description"])
		self.assertTrue(accom["description"].endswith("3 Nächte"), accom["description"])
		self.assertIn("Flughafentransfer", [ln["description"] for ln in q["quote"]["lines"] if ln["kind"] == "EXTRA"])
		site = public.site(slug=SLUG)
		self.assertIn("Flughafentransfer", [e["extra_name"] for e in site["extras"][fx.PROPERTY]])
		self.assertNotIn("name", site["extras"][fx.PROPERTY][0])

		# other languages (and the cached contract terms) keep the hotel's own texts
		frappe.local.lang = "en"
		prop = _search([{"adults": 2, "children": []}], session="sess-en")
		offer = next(o for o in prop["offers"] if o["room_type"] == std and o["rate_plan"] == flex)
		self.assertNotEqual(prop["rooms"][std]["name"], "Standardzimmer")
		self.assertNotEqual(offer["rate_plan_info"]["name"], "Flexibel")
		self.assertEqual(content.nights_label(2, "ru"), "2 ночи")
		self.assertEqual(content.nights_label(5, "pl"), "5 nocy")

	def test_translations_are_bound_to_the_hotel(self):
		from kamra.tex.api import content as content_api

		other = "TEX Content Other Hotel"
		if not frappe.db.exists("Property", other):
			frappe.get_doc({"doctype": "Property", "property_name": other, "city": "Side", "country": "Turkey",
			                "currency": "EUR"}).insert(ignore_permissions=True)
		std = self.f["room_types"]["STD"]
		with self.assertRaises(frappe.PermissionError):
			content_api.save(other, [{"ref_doctype": "Room Type", "ref_name": std, "field": "room_type_name",
			                          "language": "de", "text": "x"}])
		with self.assertRaises(frappe.ValidationError):
			content_api.save(fx.PROPERTY, [{"ref_doctype": "Room Type", "ref_name": std, "field": "base_price",
			                                "language": "de", "text": "1"}])
		agent = fx.ensure_user("content-agent@example.com", ["Call Center Agent"])
		fx.ensure("TEX Access Grant", {"user": agent, "property": fx.PROPERTY},
		          {"user": agent, "scope_level": "Hotel", "property": fx.PROPERTY,
		           "permission_profile": "Reservations Agent"})
		scope.clear_cache()
		frappe.set_user(agent)  # nosemgrep: frappe-setuser -- no booking_site.edit
		with self.assertRaises(frappe.PermissionError):
			content_api.items(fx.PROPERTY)


class TestMarketLinks(TexTestCase):
	def setUp(self):
		super().setUp()
		setup_site_and_payments(self.f)

	def test_unknown_market_link_is_a_clean_validation_error(self):
		from kamra.tex.pricing.versions import MarketResolutionError

		frappe.set_user("Guest")  # nosemgrep: frappe-setuser -- anonymous visitor
		with self.assertRaises(frappe.ValidationError) as ctx:
			public.search(site=SLUG, check_in=str(fx.d(6, 10)), check_out=str(fx.d(6, 13)),
			              rooms=[{"adults": 2, "children": []}], market="NOPE", session_id="sess-mk")
		self.assertNotIsInstance(ctx.exception, MarketResolutionError)
		self.assertIn("NOPE", str(ctx.exception))

	def test_public_limits_can_only_be_raised(self):
		self.assertEqual(public.WRITE_LIMIT["limit"](), 20)
		frappe.conf["tex_public_write_limit"] = 500
		try:
			self.assertEqual(public.WRITE_LIMIT["limit"](), 500)
			frappe.conf["tex_public_write_limit"] = 1
			self.assertEqual(public.WRITE_LIMIT["limit"](), 20)
		finally:
			frappe.conf.pop("tex_public_write_limit", None)
