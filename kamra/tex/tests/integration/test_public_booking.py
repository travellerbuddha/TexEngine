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


# what names a contract, its version, its market or its channel (G-71, R-52/R-53): never in a guest answer
IDENTITY_KEYS = frozenset({"contract", "contract_code", "contract_name", "version", "version_no", "payload_hash",
                           "market", "channel"})


def contract_identities() -> set[str]:
	"""Every contract docname, version id and payload hash: no guest answer carries one as a value."""
	out = set(frappe.get_all("TEX Contract", pluck="name"))
	for v in frappe.get_all("TEX Contract Version", fields=["name", "payload_hash"]):
		out.add(v.name)
		if v.payload_hash:
			out.add(v.payload_hash)
	return out


def identity_leaks(payload, secrets: set[str], path: str = "$") -> list[str]:
	"""Where ``payload`` names a contract's identity: an ``IDENTITY_KEYS`` key, or a value equal to a
	contract docname, version id or payload hash."""
	if isinstance(payload, dict):
		return [leak for k, v in payload.items()
		        for leak in ([f"{path}.{k}"] if k in IDENTITY_KEYS else []) + identity_leaks(v, secrets, f"{path}.{k}")]
	if isinstance(payload, list | tuple):
		return [leak for i, v in enumerate(payload) for leak in identity_leaks(v, secrets, f"{path}[{i}]")]
	return [f"{path}={payload}"] if isinstance(payload, str) and payload in secrets else []


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

	def test_guest_answers_name_no_contract(self):
		"""G-71: no guest answer names the contract, its version, its payload hash, the market or the channel
		(search, quote, quote_rooms and their refusals, basket, book, booking status, site); staff keep them."""
		secrets = contract_identities()
		self.assertTrue(secrets)

		def clean(name: str, payload) -> None:
			self.assertEqual(identity_leaks(payload, secrets), [], f"{name} names the contract")

		frappe.set_user("Guest")  # nosemgrep: frappe-setuser -- anonymous booking-engine visitor
		res = public.search(site=SLUG, check_in=str(fx.d(6, 10)), check_out=str(fx.d(6, 13)),
		                    rooms=[{"adults": 2, "children": []}], market="DE", session_id="sess-g71")
		clean("search", res)
		prop = res["properties"][0]
		offer = next(o for o in prop["offers"] if o["room_type"] == self.std and o["board"] == "AI"
		             and o["rate_plan"] == self.f["rate_plans"]["FLEX"])
		key = offer["rooms"][0]["offer_key"]
		q = public.quote(site=SLUG, offer_key=key, session_id="sess-g71")
		self.assertTrue(q["ok"], q)
		clean("quote", q)
		# what the booking app reads stays: the price, the promotions' names and the rate plan
		self.assertTrue(q["quote"]["totals"]["total"] and q["quote"]["rate_plan"]["name"])
		together = public.quote_rooms(site=SLUG, rooms=[{"offer_key": key, "extras": []}], session_id="sess-g71")
		self.assertTrue(together["ok"], together)
		clean("quote_rooms", together)
		clean("basket", public.basket(site=SLUG, quote_ids=[q["quote_id"]], session_id="sess-g71"))
		booked = public.book(site=SLUG, quote_ids=[q["quote_id"]], guest=GUEST, payment_method="Card",
		                     session_id="sess-g71", idempotency_key="idem-g71")
		clean("book", booked)
		clean("booking_status", public.booking_status(token=booked["manage_token"]))
		clean("site", public.site(slug=SLUG))

		# a refusal answers with codes, never the engine's text (which may name the contract)
		frappe.db.set_value("Room Type", self.std, "disabled", 1)
		for name, out in (("quote refused", public.quote(site=SLUG, offer_key=key, session_id="sess-g71")),
		                  ("quote_rooms refused", public.quote_rooms(site=SLUG, rooms=[{"offer_key": key, "extras": []}],
		                                                             session_id="sess-g71")["rooms"][0])):
			self.assertFalse(out["ok"], out)
			clean(name, out)
			self.assertEqual(out["reasons"], [{"code": "ROOM_NOT_SOLD"}], name)
		frappe.db.set_value("Room Type", self.std, "disabled", 0)
		# an extra refused for the market, the channel or the room type says only that it is not available
		extras = public._guest_quote({"extras": [{"ok": False, "reason": "not available for market DE"},
		                                         {"ok": False, "reason": "charged once per booking, on room 1"}]})
		self.assertEqual([e["reason"] for e in extras["extras"]], ["not available", "charged once per booking, on room 1"])

		# staff keep every identity (the call centre names the contract it sells)
		frappe.set_user("Administrator")  # nosemgrep: frappe-setuser -- the agent searches
		staff = crs.search(check_in=str(fx.d(6, 10)), check_out=str(fx.d(6, 13)), rooms=[{"adults": 2, "children": []}],
		                   market="DE", channel="CALL_CENTER", properties=[fx.PROPERTY])
		self.assertEqual((staff["market"], staff["channel"]), ("DE", "CALL_CENTER"))
		so = staff["properties"][0]["offers"][0]
		self.assertTrue(so["contract"] and so["contract_code"] and so["version"] and so["market"])
		sq = crs.quote(offer_key=so["rooms"][0]["offer_key"])
		self.assertTrue(sq["ok"], sq)
		self.assertTrue(sq["quote"]["contract"]["payload_hash"])
		self.assertEqual(sq["quote"]["request"]["channel"], "CALL_CENTER")

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

	def test_a_refused_link_is_a_funnel_event(self):
		"""G-55b (audit 2G-2, ADR-056 / ADR-070): the booking app reports a market link the server refused, with the
		refusal's code, an existing market's code and a two-letter country, nothing else (no contact data, no
		unknown string)."""
		def stored(session: str):
			return [frappe.parse_json(r.payload) for r in frappe.get_all(
				"TEX Funnel Event", filters={"site": SLUG, "session_id": session, "event": "market_refused"},
				fields=["payload"], ignore_permissions=True)]

		frappe.set_user("Guest")  # nosemgrep: frappe-setuser -- the visitor's browser reports it
		public.track(site=SLUG, session_id="mk-1", event="market_refused",
		             payload={"reason": "MARKET_NOT_ALLOWED", "market": "TR", "country": "de", "email": "x@example.com"})
		frappe.set_user("Administrator")  # nosemgrep: frappe-setuser -- read what was stored
		self.assertEqual(stored("mk-1"), [{"reason": "MARKET_NOT_ALLOWED", "market": "TR", "country": "DE"}])
		frappe.set_user("Guest")  # nosemgrep: frappe-setuser -- a browser sending anything
		public.track(site=SLUG, session_id="mk-2", event="market_refused",
		             payload={"reason": "<script>", "market": "NOPE", "country": "Deutschland", "phone": "+49 1"})
		frappe.set_user("Administrator")  # nosemgrep: frappe-setuser -- read what was stored
		self.assertEqual(stored("mk-2"), [{}])
		# a value of another type is dropped too, never a server error (review round 1)
		frappe.set_user("Guest")  # nosemgrep: frappe-setuser -- a browser sending anything
		public.track(site=SLUG, session_id="mk-3", event="market_refused",
		             payload={"reason": ["MARKET_UNKNOWN"], "market": {"x": 1}, "country": ["DE"]})
		public.track(site=SLUG, session_id="mk-3", event="room_view", payload={"board": ["AI"], "hotel": ["x"]})
		frappe.set_user("Administrator")  # nosemgrep: frappe-setuser -- read what was stored
		self.assertEqual(stored("mk-3"), [{}])

	def test_public_limits_can_only_be_raised(self):
		# independent of the bench's own site_config (E2E benches raise the limit)
		saved = frappe.conf.pop("tex_public_write_limit", None)
		try:
			self.assertEqual(public.WRITE_LIMIT["limit"](), 20)
			frappe.conf["tex_public_write_limit"] = 500
			self.assertEqual(public.WRITE_LIMIT["limit"](), 500)
			frappe.conf["tex_public_write_limit"] = 1
			self.assertEqual(public.WRITE_LIMIT["limit"](), 20)
		finally:
			frappe.conf.pop("tex_public_write_limit", None)
			if saved is not None:
				frappe.conf["tex_public_write_limit"] = saved


class TestRefusalCodes(TexTestCase):
	"""G-70a (audit Part 2G-2, ADR-013 amendment): a guest refusal's stable code and its guest-safe params reach
	the JSON error body (``tex_code``, ``tex_params``) next to Frappe's message, so the booking app can tell
	refusals apart by code, never by their English wording."""

	def setUp(self):
		super().setUp()
		setup_site_and_payments(self.f)
		self.saved_response = frappe.local.response
		frappe.local.response = frappe._dict({"docs": []})      # as a request starts (frappe.init)

	def tearDown(self):
		frappe.local.response = self.saved_response
		frappe.clear_messages()
		super().tearDown()

	@staticmethod
	def error_body() -> dict:
		"""The JSON body Frappe answers a guest API request's error with (``handle_exception`` → ``report_error``),
		built inside the ``except`` that caught it."""
		import json
		from unittest import mock

		from frappe.utils.response import report_error
		from werkzeug.test import EnvironBuilder
		from werkzeug.wrappers import Request

		env = EnvironBuilder(method="POST", path="/api/method/kamra.tex.api.public.book").get_environ()
		with mock.patch.object(frappe.local, "request", Request(env), create=True):
			return json.loads(report_error(417).get_data())

	def test_a_coded_refusal_carries_its_code_and_params_into_the_error_body(self):
		from kamra.tex.services import refusals

		@refusals.coded
		def endpoint():
			frappe.throw("Sorry — Deluxe has just sold out for 2026-12-01.",
			             refusals.refusal("SOLD_OUT", room="Deluxe", date="2026-12-01"))

		with self.assertRaises(frappe.ValidationError) as cm:
			try:
				endpoint()
			except frappe.ValidationError:
				body = self.error_body()
				raise
		self.assertEqual((cm.exception.code, cm.exception.params), ("SOLD_OUT", {"room": "Deluxe", "date": "2026-12-01"}))
		self.assertEqual(str(cm.exception), "Sorry — Deluxe has just sold out for 2026-12-01.")   # staff keep the text
		self.assertEqual((body["tex_code"], body["tex_params"]), ("SOLD_OUT", {"room": "Deluxe", "date": "2026-12-01"}))
		self.assertEqual(body["exc_type"], "Refusal")
		self.assertIn("sold out", body["_server_messages"])

	def test_an_uncoded_error_keeps_frappes_body_and_a_later_answer_has_no_code(self):
		from kamra.tex.services import refusals

		@refusals.coded
		def refused():
			frappe.throw("Check-out must be after check-in.")          # not coded yet (G-70b)

		@refusals.coded
		def gone():
			frappe.throw("Booking site not found.", frappe.DoesNotExistError)

		@refusals.coded
		def ok():
			return {"ok": True}

		with self.assertRaises(frappe.DoesNotExistError):
			gone()
		self.assertEqual(frappe.local.response["tex_code"], "NOT_FOUND")    # an uncoded 404 says what it is
		self.assertTrue(ok()["ok"])
		self.assertNotIn("tex_code", frappe.local.response)                # one request's code, never the next's
		with self.assertRaises(frappe.ValidationError):
			refused()
		self.assertNotIn("tex_code", frappe.local.response)
		self.assertNotIn("tex_params", frappe.local.response)

	def test_the_error_body_carries_only_guest_safe_params(self):
		"""Review round 1: an exception with a registered code and params of its own (not a Refusal) gets the same
		cleaning as a Refusal's: JSON-safe values only."""
		from kamra.tex.services import refusals

		class Odd(frappe.ValidationError):
			code = "SOLD_OUT"

		@refusals.coded
		def endpoint():
			e = Odd("Sold out.")
			e.params = {"room": object(), "dates": {"2026-12-02", "2026-12-01"}}
			raise e

		with self.assertRaises(Odd):
			endpoint()
		params = frappe.local.response["tex_params"]
		self.assertEqual(params["dates"], ["2026-12-01", "2026-12-02"])
		self.assertIsInstance(params["room"], str)

	def test_a_guest_booking_refused_by_a_suspended_contract_says_CONTRACT_SUSPENDED(self):
		"""A real guest endpoint: the class code of ``ContractSuspended`` (raised through ``frappe.throw``) reaches the
		error body of ``public.book``."""
		from kamra.tex.api import contracts as contracts_api
		from kamra.tex.commercial import contracts

		def suspend():
			frappe.set_user("Administrator")  # nosemgrep: frappe-setuser -- the hotel suspends the contract
			contracts_api.set_contract_status(name=frappe.db.get_value("TEX Contract", {"contract_code": "PAY"}),
			                                  action="suspend", reason="Overbooked")

		with self.assertRaises(contracts.ContractSuspended):
			guest_books(session="g70a-suspended", before_book=suspend)
		self.assertEqual(frappe.local.response["tex_code"], "CONTRACT_SUSPENDED")
		self.assertNotIn("tex_params", frappe.local.response)


	# ── G-70b: every refusal a guest can meet carries its code (HANDOFF_STAGE3 §5f) ──

	def refused(self, code: str, fn, *args, params: dict | None = None, **kwargs) -> Exception:
		"""``fn`` (a guest endpoint) refuses with ``code``, on the exception and in the error body; → the exception."""
		from kamra.tex.services import refusals

		with self.assertRaises(frappe.ValidationError if code not in PERMISSION_CODES else frappe.PermissionError) as cm:
			fn(*args, **kwargs)
		self.assertEqual((refusals.code_of(cm.exception), frappe.local.response.get("tex_code")), (code, code),
		                 f"{fn.__name__}: {cm.exception!r}")
		if params is not None:
			self.assertEqual(frappe.local.response.get("tex_params"), params, fn.__name__)
		frappe.clear_messages()
		return cm.exception

	def test_a_search_and_its_party_are_refused_by_code(self):
		from frappe.utils import add_days

		from kamra.tex.pricing import engine

		frappe.set_user("Guest")  # nosemgrep: frappe-setuser -- anonymous booking-engine visitor
		ci, co = str(fx.d(6, 10)), str(fx.d(6, 13))

		def search(**kw):
			return public.search(**({"site": SLUG, "check_in": ci, "check_out": co, "rooms": [{"adults": 2}],
			                         "session_id": "g70b-s"} | kw))

		self.refused("SITE_NOT_FOUND", search, site="no-such-site")
		self.refused("HOTEL_NOT_FOUND", search, hotel="NO-SUCH-HOTEL")
		self.refused("CURRENCY_NOT_OFFERED", search, currency="JPY")
		self.refused("DATES_INVALID", search, check_out=ci)
		self.refused("STAY_TOO_LONG", search, check_out=str(add_days(fx.d(6, 10), engine.MAX_NIGHTS + 1)),
		             params={"max": engine.MAX_NIGHTS})
		self.refused("CHECKIN_PAST", search, check_in="2020-01-01", check_out="2020-01-03")
		self.refused("ROOMS_COUNT", search, rooms=[], params={"max": quoting.MAX_ROOMS})
		self.refused("PARTY_INVALID", search, rooms=[{"adults": 0}])
		self.refused("CHILD_AGE_INVALID", search, rooms=[{"adults": 2, "children": [30]}])
		self.refused("CHILD_DOB_INVALID", search, rooms=[{"adults": 2, "children": [{"dob": "not a date"}]}])
		self.refused("CHILD_TOO_OLD", search, rooms=[{"adults": 2, "children": [{"dob": "1990-01-01"}]}],
		             params={"child": 1, "age": 18})

	def test_offers_and_quotes_are_refused_by_code(self):
		room = next(o for o in _search([{"adults": 2, "children": []}], session="g70b-q")["offers"]
		            if o["room_type"] == self.f["room_types"]["STD"])["rooms"][0]
		self.refused("OFFER_INVALID", public.quote, site=SLUG, offer_key="not-a-key", session_id="g70b-q")
		stale = quoting.sign({**quoting.verify(room["offer_key"]), "exp": "2020-01-01T00:00:00"})
		self.refused("OFFER_EXPIRED", public.quote, site=SLUG, offer_key=stale, session_id="g70b-q")
		self.refused("EXTRA_NOT_ONLINE", public.quote, site=SLUG, offer_key=room["offer_key"],
		             extras=[{"code": "NO-SUCH-EXTRA", "quantity": 1}], session_id="g70b-q")
		self.refused("EXTRAS_INVALID", public.quote, site=SLUG, offer_key=room["offer_key"], extras="[1]",
		             session_id="g70b-q")
		self.refused("INVALID_REQUEST", public.quote, site=SLUG, offer_key=room["offer_key"], extras="{not json",
		             session_id="g70b-q")
		self.refused("ROOMS_COUNT", public.quote_rooms, site=SLUG, rooms=[], session_id="g70b-q",
		             params={"max": quoting.MAX_ROOMS})
		self.refused("QUOTE_INVALID", public.basket, site=SLUG, quote_ids=["TQ-NO-SUCH"], session_id="g70b-q")

	def test_a_booking_is_refused_by_code(self):
		import dataclasses
		from unittest import mock

		from kamra.tex.services import booking as booking_svc

		room = next(o for o in _search([{"adults": 2, "children": []}], session="g70b-b")["offers"]
		            if o["room_type"] == self.f["room_types"]["STD"] and o["board"] == "AI"
		            and o["rate_plan"] == self.f["rate_plans"]["FLEX"])["rooms"][0]     # payable at the hotel

		def quoted() -> str:
			frappe.set_user("Guest")  # nosemgrep: frappe-setuser -- the visitor quotes
			return public.quote(site=SLUG, offer_key=room["offer_key"], session_id="g70b-b")["quote_id"]

		def book(quote_id: str, key: str, **kw):
			frappe.set_user("Guest")  # nosemgrep: frappe-setuser -- the visitor books
			return public.book(**({"site": SLUG, "quote_ids": [quote_id], "guest": GUEST,
			                       "payment_method": "Pay at Hotel", "session_id": "g70b-b",
			                       "idempotency_key": key} | kw))

		q = quoted()
		self.refused("GUEST_FIRST_NAME_REQUIRED", book, q, "k-name", guest={**GUEST, "first_name": ""})
		self.refused("GUEST_CONTACT_REQUIRED", book, q, "k-contact", guest={**GUEST, "email": "", "phone": ""})
		self.refused("PAYMENT_METHOD_UNAVAILABLE", book, q, "k-method", payment_method="Crypto")
		# the last room went between the quote and the booking: the room's name and the night
		real = booking_svc.avail.stay_availability

		def none_left(*args, **kwargs):
			_count, days = real(*args, **kwargs)
			return 0, [dataclasses.replace(d, available=0) for d in days]

		std = frappe.db.get_value("Room Type", self.f["room_types"]["STD"], "room_type_name")
		with mock.patch.object(booking_svc.avail, "stay_availability", side_effect=none_left):
			self.refused("SOLD_OUT", book, q, "k-sold", params={"room": std, "date": str(fx.d(6, 10))})
		book(q, "k-ok")
		self.refused("QUOTE_USED", book, q, "k-again")
		late = quoted()
		frappe.db.set_value("TEX Quote", late, "expires_at", "2020-01-01 00:00:00")
		self.refused("QUOTE_EXPIRED", book, late, "k-late")
		withdrawn = quoted()
		frappe.db.set_value("TEX Quote", withdrawn, "status", "Expired")    # its version was withdrawn (O-13)
		self.refused("NOT_ON_SALE", book, withdrawn, "k-withdrawn")

	def test_an_expired_payment_link_says_LINK_EXPIRED(self):
		from kamra.tex.payments import service as pay

		b = guest_books(session="g70b-link", method="Pay at Hotel")
		frappe.set_user("Administrator")  # nosemgrep: frappe-setuser -- the call centre sends a link
		link = pay.create_link(property=fx.PROPERTY, amount="50", currency="EUR", description="Deposit",
		                       booking=b["booking"], idempotency_key="g70b-link")
		frappe.db.set_value("TEX Payment Link", link["link"], "expires_at", "2020-01-01 00:00:00")
		frappe.set_user("Guest")  # nosemgrep: frappe-setuser -- the guest opens the link
		self.refused("LINK_EXPIRED", public.pay_link, token=link["token"])
		self.refused("LINK_INVALID", public.pay_link, token="x" * 40)

	def test_the_booking_page_is_refused_by_code(self):
		b = guest_books(session="g70b-manage", method="Pay at Hotel")
		token, res = b["manage_token"], b["rooms"][0]["reservation"]
		frappe.set_user("Guest")  # nosemgrep: frappe-setuser -- the guest's booking page
		self.refused("MANAGE_LINK_INVALID", public.booking_status, token="y" * 40)
		self.refused("MANAGE_RESERVATION_INVALID", public.manage_cancel, token=token, reservation="RES-NO-SUCH")
		self.refused("PAYMENT_METHOD_UNAVAILABLE", public.pay_booking, token=token, payment_method="Crypto")
		frappe.db.set_value("TEX Booking", b["booking"], "manage_token_expires", "2020-01-01 00:00:00")
		self.refused("MANAGE_LINK_EXPIRED", public.booking_status, token=token)
		frappe.db.set_value("TEX Booking", b["booking"], "manage_token_expires", None)
		frappe.set_user("Administrator")  # nosemgrep: frappe-setuser -- staff cancel the room
		crs.cancel(reservation=res, reason="the guest phoned")
		frappe.set_user("Guest")  # nosemgrep: frappe-setuser -- the guest's page was open: the stale cancel
		self.refused("ROOM_NOT_ACTIVE", public.manage_cancel, token=token, reservation=res, params={"status": "Cancelled"})

	def test_the_very_busy_answer_is_BUSY(self):
		from unittest import mock

		from kamra.tex.services import txn

		frappe.set_user("Guest")  # nosemgrep: frappe-setuser -- anonymous booking-engine visitor
		deadlock = frappe.QueryDeadlockError("Deadlock found")
		# every attempt meets a deadlock (the rollback kept out: the test's fixtures are its transaction)
		with mock.patch.object(quoting, "verify", side_effect=deadlock), mock.patch.object(txn.time, "sleep"), \
				mock.patch.object(frappe.db, "rollback"):
			self.refused("BUSY", public.quote, site=SLUG, offer_key="k" * 30, session_id="g70b-busy")


# the codes whose refusal stays a 403 (``frappe.PermissionError``): the manage link and its rooms
PERMISSION_CODES = frozenset({"MANAGE_LINK_INVALID", "MANAGE_LINK_EXPIRED", "MANAGE_RESERVATION_INVALID",
                              "MANAGE_REQUEST_INVALID", "SITE_CLOSED"})


def market_stay() -> dict:
	return {"check_in": str(fx.d(6, 10)), "check_out": str(fx.d(6, 13)), "rooms": [{"adults": 2, "children": []}]}


class TestMarketIntegrity(TexTestCase):
	"""O-8 (audit Part 2G-2, ADR-070, D-5): a link chooses only a market its booking site sells, and the domestic
	market (residents only) is sold on the web only to a guest whose country of residence or nationality is
	among its countries. Staff may book anyway in the Call Center with a reason, audited."""

	def setUp(self):
		super().setUp()
		setup_site_and_payments(self.f)
		fx.create_contract(self.f, code="TR-DOM", market="TR")
		frappe.db.set_value("TEX Market", "TR", "residency_required", 1)

	def sell_only(self, markets: str) -> None:
		site = frappe.get_doc("TEX Booking Site", SLUG)
		site.allowed_markets = markets
		site.save(ignore_permissions=True)

	@staticmethod
	def search(session: str, **link) -> dict:
		frappe.set_user("Guest")  # nosemgrep: frappe-setuser -- anonymous booking-engine visitor
		return public.search(site=SLUG, session_id=session, **market_stay(), **link)

	def flex(self, res: dict) -> dict:
		"""The standard room's flexible all-inclusive offer (its 30 % deposit rule takes payment at the hotel)."""
		return next(o for o in res["properties"][0]["offers"] if o["room_type"] == self.f["room_types"]["STD"]
		            and o["board"] == "AI" and o["rate_plan"] == self.f["rate_plans"]["FLEX"])

	def quote(self, session: str, **link) -> tuple[dict, str]:
		res = self.search(session, **link)
		offer = self.flex(res)
		q = public.quote(site=SLUG, offer_key=offer["rooms"][0]["offer_key"], session_id=session)
		self.assertTrue(q["ok"], q)
		return res, q["quote_id"]

	def book(self, session: str, quote_id: str, guest: dict, key: str | None = None) -> dict:
		frappe.set_user("Guest")  # nosemgrep: frappe-setuser -- the visitor books
		return public.book(site=SLUG, quote_ids=[quote_id], guest=guest, payment_method="Pay at Hotel",
		                   session_id=session, idempotency_key=key or f"idem-{session}")

	def market_of(self, result: dict) -> str:
		return frappe.db.get_value("TEX Quote", frappe.db.get_value("TEX Quote", {"booking": result["booking"]}),
		                           "market")

	def assertRefused(self, code: str, fn, *args, **kwargs):
		from kamra.tex.services import refusals

		with self.assertRaises(refusals.MarketRefused) as cm:
			fn(*args, **kwargs)
		self.assertEqual(cm.exception.code, code)
		return cm.exception

	def test_a_market_the_site_does_not_sell_is_refused_in_search(self):
		self.sell_only("DE, GLOBAL")
		self.assertRefused("MARKET_NOT_ALLOWED", self.search, "o8-1", market="TR")
		self.assertEqual(frappe.local.response.get("tex_code"), "MARKET_NOT_ALLOWED")
		# the guest's country picks among the site's markets: TR is not one, so the site's default (DE) prices
		res = self.search("o8-1b", country="TR")
		self.assertIsNone(res["residency"])
		totals = lambda r: sorted(o["total"] for o in r["properties"][0]["offers"])  # noqa: E731
		self.assertTrue(totals(res))
		self.assertEqual(totals(res), totals(self.search("o8-1c", market="DE")))

	def test_a_guest_error_body_names_no_market(self):
		"""2G-3 review round 1 (S2): a guest's error body names no market (G-71): a residents-only refusal carries the
		countries only, and a link country two markets share is refused without naming them. The exception keeps the
		market for staff (the Call Center)."""
		saved, frappe.local.response = frappe.local.response, frappe._dict({"docs": []})
		try:
			e = self.assertRefused("MARKET_RESIDENCY", self.search, "r1-mk", market="TR", country="DE")
			self.assertEqual(e.params, {"market": "TR", "countries": ["TR"]})
			self.assertEqual(frappe.local.response["tex_params"], {"countries": ["TR"]})
			frappe.set_user("Administrator")  # nosemgrep: frappe-setuser -- two markets share a country
			for code in ("RAT1", "RAT2"):
				fx.ensure("TEX Market", {"market_code": code}, {"market_code": code, "market_name": code, "countries": "AT"})
			e = self.assertRefused("MARKET_AMBIGUOUS", self.search, "r1-mk2", country="AT")
			self.assertNotIn("RAT1", str(e))
			self.assertNotIn("tex_params", frappe.local.response)
		finally:
			frappe.local.response = saved
			frappe.clear_messages()

	def test_a_residents_only_market_is_refused_for_another_link_country(self):
		e = self.assertRefused("MARKET_RESIDENCY", self.search, "o8-2", market="TR", country="DE")
		self.assertEqual(e.params, {"market": "TR", "countries": ["TR"]})
		self.assertEqual(self.search("o8-2b", market="TR", country="tr")["residency"], {"countries": ["TR"]})

	def test_the_guest_declares_residence_at_booking(self):
		res, quote_id = self.quote("o8-3", market="TR")
		self.assertEqual(res["residency"], {"countries": ["TR"]})          # priced; checkout asks for the residence
		self.assertEqual(public.basket(site=SLUG, quote_ids=[quote_id], session_id="o8-3")["residency"],
		                 {"countries": ["TR"]})
		bookings = frappe.db.count("TEX Booking")
		e = self.assertRefused("MARKET_RESIDENCY", self.book, "o8-3", quote_id, GUEST)        # resident of Germany
		self.assertEqual(e.params, {"market": "TR", "countries": ["TR"]})
		self.assertNotIn("TR-DOM", str(e))
		self.assertEqual(frappe.db.count("TEX Booking"), bookings)
		event = frappe.get_all("TEX Audit Event", filters={"action": "booking.market_refused", "reference_name": quote_id},
		                       fields=["new_value", "property"])
		self.assertEqual(len(event), 1)
		self.assertEqual(frappe.parse_json(event[0].new_value),
		                 {"market": "TR", "countries": ["TR"], "country": "DE", "nationality": None, "site": SLUG})
		# the guest corrects the country: the same quote and the same retry key book (the refusal kept neither)
		ok = self.book("o8-3", quote_id, {**GUEST, "country": "TR"})
		self.assertEqual((ok["status"], self.market_of(ok)), ("Confirmed", "TR"))
		# a guest living abroad with Turkish nationality books too
		_res, other = self.quote("o8-3b", market="TR")
		self.assertEqual(self.book("o8-3b", other, {**GUEST, "email": "o8-nat@example.com",
		                                           "nationality": "Türkiye"})["status"], "Confirmed")

	def test_staff_override_in_the_crs_is_audited(self):
		from kamra.tex.services import refusals

		agent = fx.ensure_user("o8-agent@example.com", ["Call Center Agent"])
		fx.ensure("TEX Access Grant", {"user": agent, "property": fx.PROPERTY},
		          {"user": agent, "scope_level": "Hotel", "property": fx.PROPERTY,
		           "permission_profile": "Reservations Agent"})
		scope.clear_cache()
		frappe.set_user(agent)  # nosemgrep: frappe-setuser -- a call-centre agent
		offer = self.flex(crs.search(**market_stay(), market="TR", channel="CALL_CENTER", properties=[fx.PROPERTY]))
		quote_id = crs.quote(offer_key=offer["rooms"][0]["offer_key"])["quote_id"]
		guest = {"first_name": "Jonas", "last_name": "Weber", "email": "o8-crs@example.com", "country": "DE"}
		e = self.assertRefused("MARKET_RESIDENCY", crs.book, quote_ids=[quote_id], guest=guest,
		                       payment_method="Pay at Hotel")
		self.assertIn("anyway", str(e))                                    # the agent is told the way out
		with self.assertRaises(frappe.ValidationError) as no_reason:
			crs.book(quote_ids=[quote_id], guest=guest, payment_method="Pay at Hotel", market_override=1)
		self.assertNotIsInstance(no_reason.exception, refusals.MarketRefused)     # the override was heard: a reason
		self.assertIn("reason", str(no_reason.exception))
		out = crs.book(quote_ids=[quote_id], guest=guest, payment_method="Pay at Hotel", market_override=1,
		               market_override_reason="Guest works in Antalya, residence permit shown")
		self.assertEqual(out["status"], "Confirmed")
		event = frappe.get_all("TEX Audit Event", filters={"action": "booking.market_override",
		                                                    "reference_name": out["booking"]},
		                       fields=["new_value", "reason", "actor"])
		self.assertEqual(len(event), 1)
		self.assertEqual(frappe.parse_json(event[0].new_value),
		                 {"market": "TR", "countries": ["TR"], "country": "DE", "nationality": None})
		self.assertEqual((event[0].reason, event[0].actor),
		                 ("Guest works in Antalya, residence permit shown", agent))

	def agent(self) -> str:
		agent = fx.ensure_user("o8-agent@example.com", ["Call Center Agent"])
		fx.ensure("TEX Access Grant", {"user": agent, "property": fx.PROPERTY},
		          {"user": agent, "scope_level": "Hotel", "property": fx.PROPERTY,
		           "permission_profile": "Reservations Agent"})
		scope.clear_cache()
		return agent

	def test_the_call_centres_country_codes_reach_the_guest_profile(self):
		"""Review round 1: the Call Center sends ISO codes; the profile keeps Frappe's Country (a Link). An existing
		profile without a country of residence gets it, and a booking for it never fails on the code."""
		guest = frappe.get_doc({"doctype": "Guest", "first_name": "Ayşe", "last_name": "Kaya",
		                        "email": "o8-known@example.com"}).insert(ignore_permissions=True)
		frappe.db.set_value("Guest", guest.name, {"tex_country": None, "nationality": None})
		frappe.set_user(self.agent())  # nosemgrep: frappe-setuser -- a call-centre agent
		offer = self.flex(crs.search(**market_stay(), market="TR", channel="CALL_CENTER", properties=[fx.PROPERTY]))
		quote_id = crs.quote(offer_key=offer["rooms"][0]["offer_key"])["quote_id"]
		out = crs.book(quote_ids=[quote_id], guest={"first_name": "Ayşe", "last_name": "Kaya", "email": "o8-known@example.com",
		                                            "country": "tr"}, payment_method="Pay at Hotel")
		self.assertEqual(out["status"], "Confirmed")
		self.assertEqual(frappe.db.get_value("Guest", guest.name, "tex_country"), "Türkiye")

	def test_a_quote_of_a_market_the_site_no_longer_sells_is_refused_at_booking(self):
		"""Review round 1: a quote made while the site sold TR (or on another site of the hotel) is refused when the
		site's list no longer has it; nothing is booked and the quote stays open."""
		_res, quote_id = self.quote("o8-gone", market="TR")
		frappe.set_user("Administrator")  # nosemgrep: frappe-setuser -- the hotel narrows the site
		self.sell_only("DE, GLOBAL")
		frappe.clear_document_cache("TEX Booking Site", SLUG)
		e = self.assertRefused("MARKET_NOT_ALLOWED", self.book, "o8-gone", quote_id, {**GUEST, "country": "TR"})
		self.assertEqual(e.params, {"market": "TR"})
		self.assertEqual(frappe.db.get_value("TEX Quote", quote_id, "status"), "Open")

	def test_a_residents_only_default_is_priced_for_a_country_no_market_takes(self):
		"""Review round 1: on a site whose default market is residents-only, a link country that no market of the site
		takes (JP) falls to that default: priced with its residency (refusing it would only send the search back to
		the same market), and the site's save warns that non-residents get no price they can book there."""
		site = frappe.get_doc("TEX Booking Site", SLUG)
		site.default_market = "TR"
		site.allowed_markets = "TR, DE"
		frappe.clear_messages()
		site.save(ignore_permissions=True)
		self.assertIn("residents", " ".join(str(m) for m in frappe.get_message_log()))
		res = self.search("o8-jp", country="JP")
		self.assertEqual(res["residency"], {"countries": ["TR"]})
		self.assertRefused("MARKET_RESIDENCY", self.search, "o8-de-tr", market="TR", country="DE")   # the link's own

	def test_staff_on_a_booking_site_follow_the_site(self):
		_res, quote_id = self.quote("o8-5", market="TR")
		frappe.set_user("Administrator")  # nosemgrep: frappe-setuser -- signed-in staff on the public site
		with self.assertRaises(frappe.ValidationError) as cm:
			public.book(site=SLUG, quote_ids=[quote_id], guest=GUEST, payment_method="Pay at Hotel",
			            session_id="o8-5", idempotency_key="idem-o8-5")
		self.assertEqual(getattr(cm.exception, "code", None), "MARKET_RESIDENCY")
		self.assertFalse(frappe.db.exists("TEX Quote", {"name": quote_id, "status": "Used"}))

	def test_markets_and_sites_are_validated(self):
		frappe.db.set_value("TEX Market", "PL", "disabled", 1)
		for markets in ("DE, NOPE", "DE, PL", "GLOBAL, TR"):                  # unknown, disabled, default not listed
			with self.assertRaises(frappe.ValidationError, msg=markets):
				self.sell_only(markets)
		self.sell_only(" de , global,de")
		self.assertEqual(frappe.db.get_value("TEX Booking Site", SLUG, "allowed_markets"), "DE, GLOBAL")
		for name, values in (("GLOBAL", {"residency_required": 1}), ("DE", {"residency_required": 1, "countries": ""})):
			doc = frappe.get_doc("TEX Market", name)
			doc.update(values)
			with self.assertRaises(frappe.ValidationError, msg=name):
				doc.save(ignore_permissions=True)


class TestMandatoryExtrasInSearch(TexTestCase):
	"""Y-5: a search prices the hotel's mandatory extras as the quote does, so the price a guest or an
	agent sees in the results is the one the quote confirms (``price_changed`` False) — not the stay
	without its mandatory gala dinner (2 adults × 150)."""

	def setUp(self):
		super().setUp()
		setup_site_and_payments(self.f)
		fx.ensure_live("TEX Extra", {"property": fx.PROPERTY, "extra_code": "GALA"},
		               {"property": fx.PROPERTY, "extra_code": "GALA", "extra_name": "Gala dinner",
		                "category": "Dining", "pricing_mode": "ADULT", "currency": "EUR", "amount": 150,
		                "tax_category": "SERVICE", "is_mandatory": 1})

	def pick(self, offers) -> dict:
		rt = frappe.db.get_value("Room Type", {"property": fx.PROPERTY, "room_type_code": "STD"})
		return next(o for o in offers if o["room_type"] == rt and o["board"] == "AI"
		            and o["rate_plan"] == self.f["rate_plans"]["FLEX"])

	def test_the_guest_search_shows_what_the_quote_confirms(self):
		offer = self.pick(_search([{"adults": 2, "children": []}], session="y5-web")["offers"])
		room = offer["rooms"][0]
		self.assertIn("GALA", {e["code"] for e in room["quote"]["extras"] if e.get("ok")})
		q = public.quote(site=SLUG, offer_key=room["offer_key"], session_id="y5-web")
		self.assertTrue(q["ok"], q)
		self.assertEqual(D(q["quote"]["totals"]["total"]), D(room["quote"]["totals"]["total"]))
		self.assertEqual(D(offer["total"]), D(q["quote"]["totals"]["total"]))
		self.assertFalse(q["price_changed"])

	def test_the_call_centre_search_shows_what_the_quote_confirms(self):
		res = crs.search(check_in=str(fx.d(6, 10)), check_out=str(fx.d(6, 13)), rooms=[{"adults": 2, "children": []}],
		                 market="DE", channel="CALL_CENTER", properties=[fx.PROPERTY])
		room = self.pick(res["properties"][0]["offers"])["rooms"][0]
		q = crs.quote(offer_key=room["offer_key"])
		self.assertTrue(q["ok"], q)
		self.assertEqual(D(q["quote"]["totals"]["total"]), D(room["quote"]["totals"]["total"]))
		self.assertFalse(q["price_changed"])
