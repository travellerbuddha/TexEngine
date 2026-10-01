"""Extras added after booking (G-22): a guest (or staff) adds extras to a booked stay. They
are priced on their own; the stay stays price-locked; the balance grows; limited extras keep
their capacity; a later date change carries them over."""

from unittest import mock

import frappe
from frappe.utils import add_to_date, now_datetime

from kamra.tex.api import crs as crs_api
from kamra.tex.api import public
from kamra.tex.commercial import revisions
from kamra.tex.money import D
from kamra.tex.security import scope
from kamra.tex.services import booking, modification
from kamra.tex.tests.integration import fixtures as fx
from kamra.tex.tests.integration.test_commercial_flows import GUEST, SLUG, setup_site_and_payments
from kamra.tex.tests.integration.test_critical_journey import TexTestCase


def extra(code: str, **kw) -> str:
	return fx.ensure_live("TEX Extra", {"property": fx.PROPERTY, "extra_code": code}, {
		"property": fx.PROPERTY, "extra_code": code, "extra_name": code.title(), "category": "Service",
		"pricing_mode": "UNIT", "currency": "EUR", "amount": 50, "bookable_online": 1, "bookable_after_booking": 1,
		**kw})


class AddonCase(TexTestCase):
	def setUp(self):
		super().setUp()
		setup_site_and_payments(self.f)
		self.massage = extra("MASSAGE")

	def book(self, session: str, *, extras=(), method="Pay at Hotel", rooms=1) -> dict:
		frappe.set_user("Guest")  # nosemgrep: frappe-setuser -- a booking-engine visitor
		res = public.search(site=SLUG, check_in=str(fx.d(6, 10)), check_out=str(fx.d(6, 13)),
		                    rooms=[{"adults": 2}] * rooms, market="DE", session_id=session)
		rt = frappe.db.get_value("Room Type", {"property": fx.PROPERTY, "room_type_code": "STD"})
		rp = frappe.db.get_value("Rate Plan", {"property": fx.PROPERTY, "code": "FLEX"})
		offer = next(o for o in res["properties"][0]["offers"]
		             if o["room_type"] == rt and o["board"] == "AI" and o["rate_plan"] == rp)
		quotes = [public.quote(site=SLUG, offer_key=r["offer_key"], extras=list(extras) if r["room_index"] == 0
		                       else [], session_id=session)["quote_id"]
		          for r in sorted(offer["rooms"], key=lambda r: r["room_index"])]
		return public.book(site=SLUG, quote_ids=quotes, guest={**GUEST, "email": f"{session}@example.com"},
		                   payment_method=method, session_id=session, idempotency_key=f"idem-{session}")

	def add(self, b: dict, extras, room: int = 0) -> dict:
		frappe.set_user("Guest")  # nosemgrep: frappe-setuser -- the guest on the manage page
		res = b["rooms"][room]["reservation"]
		p = public.manage_extras_propose(token=b["manage_token"], reservation=res, extras=extras)
		assert p["ok"], p
		return public.manage_extras_apply(token=b["manage_token"], proposal_token=p["proposal_token"])

	@staticmethod
	def snapshot(res: str) -> dict:
		import json

		return json.loads(frappe.db.get_value("Reservation", res, "tex_pricing_snapshot"))


class TestPostBookingExtras(AddonCase):
	def test_an_added_extra_leaves_the_stay_price_locked(self):
		b = self.book("g22-lock", extras=[{"code": "TRF"}])
		res = b["rooms"][0]["reservation"]
		before = self.snapshot(res)
		frappe.set_user("Administrator")  # nosemgrep: frappe-setuser -- revenue manager raises the markup
		mk = frappe.db.get_value("TEX Markup Rule", {"property": fx.PROPERTY, "market": "DE", "tex_status": "Active"})
		draft = frappe.get_doc("TEX Markup Rule", revisions.revise("TEX Markup Rule", mk))
		draft.value = 27
		draft.save(ignore_permissions=True)
		revisions.activate("TEX Markup Rule", draft.name)           # today's price of the stay is now higher
		out = self.add(b, [{"code": "MASSAGE", "quantity": 2}])
		after = self.snapshot(res)
		stay = lambda s: [ln for ln in s["lines"] if ln["kind"] in ("ACCOMMODATION", "DISCOUNT")]  # noqa: E731
		self.assertEqual(stay(after), stay(before))                   # the room is not repriced
		self.assertEqual(D(after["totals"]["total"]), D(before["totals"]["total"]) + D("100"))  # 2 × 50, no tax
		self.assertEqual([e["code"] for e in after["extras"]], ["TRF", "MASSAGE"])      # nothing dropped
		self.assertEqual(D(out["total"]), D(after["totals"]["total"]))
		rev = frappe.get_all("TEX Reservation Revision", filters={"reservation": res, "pricing_basis": "ADD_ON"},
		                     fields=["change_type", "source", "difference"])
		self.assertEqual([(r.change_type, r.source, D(r.difference)) for r in rev], [("Extras", "Guest", D("100"))])
		self.assertEqual(frappe.db.get_value("Reservation", res, "tex_guest_change_pending"), 1)

	def test_an_extra_added_to_a_price_staff_set_adds_to_that_price(self):
		"""Y-7 (audit 2B, ADR-065): the new stored price is the old stored price plus the extras; a price
		staff set stays theirs, never the engine's total the snapshot explains."""
		b = self.book("y7-manual")                                      # FLEX, paid at the hotel
		res = b["rooms"][0]["reservation"]
		frappe.set_user("Administrator")  # nosemgrep: frappe-setuser -- staff set the price
		p = modification.propose(res, {})
		modification.apply(p["proposal_token"], reason="the price agreed by phone", override_amount="600")
		frappe.set_user("Guest")  # nosemgrep: frappe-setuser -- the guest adds a massage
		p = public.manage_extras_propose(token=b["manage_token"], reservation=res, extras=[{"code": "MASSAGE"}])
		self.assertEqual((p["old_total"], p["new_total"]), ("600.00", "650.00"))
		public.manage_extras_apply(token=b["manage_token"], proposal_token=p["proposal_token"])
		frappe.set_user("Administrator")  # nosemgrep: frappe-setuser -- staff read what was stored
		self.assertEqual(D(frappe.db.get_value("Reservation", res, "tex_total_amount")), D("650"))
		self.assertEqual(self.snapshot(res)["override_amount"], "650.00")
		rev = frappe.get_all("TEX Reservation Revision", filters={"reservation": res, "pricing_basis": "ADD_ON"},
		                     fields=["change_type", "old_amount", "new_amount", "difference", "override_amount",
		                             "changes_json"])
		self.assertEqual([(r.change_type, D(r.old_amount), D(r.new_amount), D(r.difference), D(r.override_amount))
		                  for r in rev], [("Extras", D(600), D(650), D(50), D(650))])
		self.assertEqual(frappe.parse_json(rev[0].changes_json)["manual_price"], {"before": "600.00", "after": "650.00"})
		self.assertEqual(D(frappe.db.get_value("TEX Booking", b["booking"], "total_amount")), D("650"))
		audit = frappe.parse_json(frappe.db.get_value("TEX Audit Event", {"action": "reservation.addon",
		                                                                   "reference_name": res}, "new_value"))
		self.assertEqual((audit["total_before"], audit["total_after"]), ("600.00", "650.00"))

	def test_extras_lock_the_booking_before_their_room_and_read_the_room_under_the_lock(self):
		"""2F-1 (P1-4): the order is booking, then room (as a payment and the expiry take it), and the room is read
		with a locking read, the state after the lock, not the snapshot taken before it."""
		from kamra.tex.services import addons
		from kamra.tex.tests.integration.test_security_regressions import SqlSpy

		b = self.book("p14-order")
		res = b["rooms"][0]["reservation"]
		frappe.set_user("Guest")  # nosemgrep: frappe-setuser -- the guest adds a massage
		p = public.manage_extras_propose(token=b["manage_token"], reservation=res, extras=[{"code": "MASSAGE"}])
		with SqlSpy() as spy:
			addons.apply(p["proposal_token"], source="Guest", guest=True)

		def first_lock(table: str):
			return next((i for i, q in enumerate(spy.seen) if f"`tab{table}`" in q and "FOR UPDATE" in q), None)

		loads = spy.loads("Reservation")
		self.assertTrue(loads and loads[0].endswith("FOR UPDATE"), loads)
		self.assertIsNotNone(first_lock("TEX Booking"))
		self.assertLess(first_lock("TEX Booking"), first_lock("Reservation"))

	def test_only_extras_sold_online_after_booking_can_be_added(self):
		extra("BACKSTAGE", bookable_online=0)
		extra("WELCOME", bookable_after_booking=0)
		b = self.book("g22-offer")
		res = b["rooms"][0]["reservation"]
		frappe.set_user("Guest")  # nosemgrep: frappe-setuser -- the guest
		offered = [x["code"] for x in public.manage_extras(token=b["manage_token"], reservation=res)["extras"]]
		self.assertIn("MASSAGE", offered)
		self.assertFalse({"BACKSTAGE", "WELCOME"} & set(offered))
		for code in ("BACKSTAGE", "WELCOME", "NOSUCH"):
			p = public.manage_extras_propose(token=b["manage_token"], reservation=res, extras=[{"code": code}])
			self.assertEqual((p["ok"], p["reasons"][0]["code"], p["proposal_token"]),
			                 (False, "ADDON_NOT_AVAILABLE", None), code)
		# the date/guests change of the manage page no longer carries extras (they go through the above)
		p = public.manage_propose(token=b["manage_token"], reservation=res,
		                          changes={"check_out": str(fx.d(6, 14)), "extras": [{"code": "BACKSTAGE"}]})
		self.assertNotIn("BACKSTAGE", [ln["code"] for ln in p["lines"]])

	def test_the_balance_grows_and_is_paid_like_any_balance(self):
		at_hotel = self.book("g22-hotel")
		before = D(at_hotel["balance"])
		out = self.add(at_hotel, [{"code": "MASSAGE"}])
		self.assertEqual((D(out["balance"]), out["payment_status"]), (before + D("50"), "Pay at Hotel"))
		card = self.book("g22-card", method="Card")
		frappe.set_user("Guest")  # nosemgrep: frappe-setuser -- the guest pays the deposit
		public.mock_pay(transaction=card["payment"]["transaction"], outcome="success",
		                sig=card["payment"]["fields"]["success_sig"])
		out = self.add(card, [{"code": "MASSAGE"}])
		frappe.set_user("Guest")  # nosemgrep: frappe-setuser -- and pays online from the manage page
		pay = public.pay_booking(token=card["manage_token"])
		self.assertEqual(D(frappe.db.get_value("TEX Payment Transaction", pay["transaction"], "amount")),
		                 D(out["balance"]))

	def test_a_proposal_is_applied_once_and_only_where_it_belongs(self):
		b = self.book("g22-once")
		res = b["rooms"][0]["reservation"]
		frappe.set_user("Guest")  # nosemgrep: frappe-setuser -- the guest
		p = public.manage_extras_propose(token=b["manage_token"], reservation=res, extras=[{"code": "MASSAGE"}])
		first = public.manage_extras_apply(token=b["manage_token"], proposal_token=p["proposal_token"])
		again = public.manage_extras_apply(token=b["manage_token"], proposal_token=p["proposal_token"])
		self.assertEqual((again["replay"], again["total"]), (True, first["total"]))
		later = add_to_date(now_datetime(), minutes=45)                  # the retry comes after the token expired
		with mock.patch("kamra.tex.services.quoting.now_datetime", return_value=later):
			late = public.manage_extras_apply(token=b["manage_token"], proposal_token=p["proposal_token"])
		self.assertEqual((late["replay"], late["total"]), (True, first["total"]))
		p_old = public.manage_extras_propose(token=b["manage_token"], reservation=res, extras=[{"code": "MASSAGE"}])
		with mock.patch("kamra.tex.services.quoting.now_datetime", return_value=later):
			with self.assertRaisesRegex(frappe.ValidationError, "expired"):   # a fresh one is still refused
				public.manage_extras_apply(token=b["manage_token"], proposal_token=p_old["proposal_token"])
		self.assertEqual(frappe.db.count("TEX Reservation Revision", {"reservation": res, "pricing_basis": "ADD_ON"}), 1)
		with self.assertRaises(frappe.ValidationError):              # an add-on is not a date change
			public.manage_apply(token=b["manage_token"], proposal_token=p["proposal_token"])
		p2 = public.manage_extras_propose(token=b["manage_token"], reservation=res, extras=[{"code": "MASSAGE"}])
		other = self.book("g22-other")
		frappe.set_user("Guest")  # nosemgrep: frappe-setuser -- another guest's link
		with self.assertRaises((frappe.PermissionError, frappe.ValidationError)):
			public.manage_extras_propose(token=other["manage_token"], reservation=res, extras=[{"code": "MASSAGE"}])
		with self.assertRaises((frappe.PermissionError, frappe.ValidationError)):
			public.manage_extras_apply(token=other["manage_token"], proposal_token=p2["proposal_token"])
		self.assertEqual(frappe.db.count("TEX Reservation Revision", {"reservation": res, "pricing_basis": "ADD_ON"}), 1)
		frappe.set_user("Administrator")  # nosemgrep: frappe-setuser -- staff cannot apply a guest proposal
		with self.assertRaises(frappe.ValidationError):
			crs_api.addon_apply(p["proposal_token"])

	def test_a_moved_price_or_a_late_day_is_refused(self):
		b = self.book("g22-moved")
		res = b["rooms"][0]["reservation"]
		frappe.set_user("Guest")  # nosemgrep: frappe-setuser -- the guest
		p = public.manage_extras_propose(token=b["manage_token"], reservation=res, extras=[{"code": "MASSAGE"}])
		frappe.set_user("Administrator")  # nosemgrep: frappe-setuser -- revenue manager changes the price
		draft = frappe.get_doc("TEX Extra", revisions.revise("TEX Extra", self.massage))
		draft.amount = 55
		draft.save(ignore_permissions=True)
		revisions.activate("TEX Extra", draft.name)
		frappe.set_user("Guest")  # nosemgrep: frappe-setuser -- the guest confirms
		with self.assertRaisesRegex(frappe.ValidationError, "price moved"):
			public.manage_extras_apply(token=b["manage_token"], proposal_token=p["proposal_token"])
		p = public.manage_extras_propose(token=b["manage_token"], reservation=res, extras=[{"code": "MASSAGE"}])
		self.assertEqual(D(p["totals"]["total"]), D(55))
		frappe.set_user("Administrator")  # nosemgrep: frappe-setuser -- the hotel now wants ten years' notice
		draft = frappe.get_doc("TEX Extra", revisions.revise("TEX Extra", draft.name))
		draft.order_cutoff_hours = 24 * 3650
		draft.save(ignore_permissions=True)
		revisions.activate("TEX Extra", draft.name)
		frappe.set_user("Guest")  # nosemgrep: frappe-setuser -- the guest confirms the priced proposal
		with self.assertRaisesRegex(frappe.ValidationError, "can no longer be added"):
			public.manage_extras_apply(token=b["manage_token"], proposal_token=p["proposal_token"])
		late = public.manage_extras_propose(token=b["manage_token"], reservation=res, extras=[{"code": "MASSAGE"}])
		self.assertEqual(late["reasons"][0]["code"], "ADDON_TOO_LATE")

	def test_a_per_booking_extra_is_added_on_the_first_room_only(self):
		b = self.book("g22-rooms", rooms=2)
		frappe.set_user("Guest")  # nosemgrep: frappe-setuser -- the guest
		p = public.manage_extras_propose(token=b["manage_token"], reservation=b["rooms"][1]["reservation"],
		                                 extras=[{"code": "TRF"}])
		self.assertIn("charged once per booking, on room 1", p["reasons"][0]["message"])
		self.add(b, [{"code": "TRF"}], room=0)

	def test_a_later_date_change_carries_the_extra_over(self):
		b = self.book("g22-carry")
		res = b["rooms"][0]["reservation"]
		self.add(b, [{"code": "MASSAGE", "service_dates": [str(fx.d(6, 12))]}])
		frappe.set_user("Administrator")  # nosemgrep: frappe-setuser -- the agent extends the stay
		longer = modification.propose(res, {"check_out": str(fx.d(6, 14))})
		massage = [e for e in longer["proposed"]["extras"] if e["code"] == "MASSAGE"]
		self.assertEqual([D(e["amount"]) for e in massage], [D("50")])      # at the price it was added for
		modification.apply(longer["proposal_token"], reason="one more night")
		self.assertEqual([e["code"] for e in self.snapshot(res)["extras"]], ["MASSAGE"])
		frappe.set_user("Guest")  # nosemgrep: frappe-setuser -- the guest moves past the massage day
		shorter = public.manage_propose(token=b["manage_token"], reservation=res,
		                                changes={"check_in": str(fx.d(6, 13)), "check_out": str(fx.d(6, 15))})
		self.assertFalse(shorter["sellable"])
		self.assertIn("ADDON_OUTSIDE_STAY", [w["code"] for w in shorter["warnings"]])

	def test_a_limited_extra_keeps_its_capacity(self):
		extra("SPA", inventory_tracked=1, daily_capacity=1)
		first, second = self.book("g22-cap1"), self.book("g22-cap2")
		self.add(first, [{"code": "SPA"}])
		frappe.set_user("Guest")  # nosemgrep: frappe-setuser -- another guest wants the same slot
		p = public.manage_extras_propose(token=second["manage_token"], reservation=second["rooms"][0]["reservation"],
		                                 extras=[{"code": "SPA"}])
		self.assertEqual(p["reasons"][0]["code"], "ADDON_SOLD_OUT")
		frappe.set_user("Administrator")  # nosemgrep: frappe-setuser -- the first stay is cancelled
		booking.cancel_reservation(first["rooms"][0]["reservation"], reason="cancelled", waive_penalty=True)
		self.add(second, [{"code": "SPA"}])

	def test_guests_see_no_internal_figures(self):
		b = self.book("g22-safe")
		frappe.set_user("Guest")  # nosemgrep: frappe-setuser -- the guest
		p = public.manage_extras_propose(token=b["manage_token"], reservation=b["rooms"][0]["reservation"],
		                                 extras=[{"code": "MASSAGE"}])
		self.assertNotIn("explanation", str(p))
		self.assertFalse({"cost", "margin", "margin_percent"} & set(p["totals"]))
		from kamra.tex.services import addons as addon_svc

		self.assertNotIn("explanation", addon_svc.propose(b["rooms"][0]["reservation"], [{"code": "MASSAGE"}],
		                                                  guest=True)["addon"])
		res = b["rooms"][0]["reservation"]
		self.add(b, [{"code": "MASSAGE"}])
		frappe.set_user("Administrator")  # nosemgrep: frappe-setuser -- an agent without cost access
		agent = fx.ensure_user("g22-desk@example.com", ["Call Center Agent"])
		fx.ensure("TEX Access Grant", {"user": agent, "property": fx.PROPERTY},
		          {"user": agent, "scope_level": "Hotel", "property": fx.PROPERTY,
		           "permission_profile": "Reservations Agent"})
		scope.clear_cache()
		frappe.set_user(agent)  # nosemgrep: frappe-setuser -- the agent opens the reservation
		self.assertNotIn("explanation", str(crs_api.reservation(res)["pricing"]["addons"]))
		p = modification.propose(res, {"adults": 2})
		self.assertNotIn("explanation", str(p["proposed"]))

	def test_staff_add_extras_at_their_hotel_only(self):
		b = self.book("g22-staff")
		res = b["rooms"][0]["reservation"]
		frappe.set_user("Administrator")  # nosemgrep: frappe-setuser -- the admin grants another hotel's agent
		other = "TEX Other Hotel"
		if not frappe.db.exists("Property", other):
			frappe.get_doc({"doctype": "Property", "property_name": other, "city": "Kemer", "country": "Turkey",
			                "currency": "EUR"}).insert(ignore_permissions=True)
		agent = fx.ensure_user("g22-agent@example.com", ["Call Center Agent"])
		fx.ensure("TEX Access Grant", {"user": agent, "property": other},
		          {"user": agent, "scope_level": "Hotel", "property": other, "permission_profile": "Reservations Agent"})
		scope.clear_cache()
		frappe.set_user(agent)  # nosemgrep: frappe-setuser -- an agent of another hotel
		with self.assertRaises(frappe.PermissionError):
			crs_api.addon_propose(res, [{"code": "MASSAGE"}])
		frappe.set_user("Administrator")  # nosemgrep: frappe-setuser -- an agent of this hotel
		p = crs_api.addon_propose(res, [{"code": "MASSAGE"}])
		out = crs_api.addon_apply(p["proposal_token"], reason="guest called")
		self.assertEqual(D(out["total"]), D(p["new_total"]))
		self.assertEqual(frappe.db.get_value("TEX Reservation Revision", {"reservation": res, "pricing_basis": "ADD_ON"},
		                                     "source"), "Desk")
		self.assertIsNotNone(add_to_date(now_datetime(), days=1))

	def test_staff_remove_an_added_extra_and_its_units_come_back(self):
		extra("SPA", inventory_tracked=1, daily_capacity=1)
		b = self.book("g22-drop")
		res = b["rooms"][0]["reservation"]
		before = D(frappe.db.get_value("Reservation", res, "tex_total_amount"))
		self.add(b, [{"code": "SPA"}])
		addon_id = self.snapshot(res)["addons"][0]["id"]
		frappe.set_user("Guest")  # nosemgrep: frappe-setuser -- a guest cannot remove it online
		p = public.manage_propose(token=b["manage_token"], reservation=res, changes={"drop_addons": [addon_id]})
		self.assertEqual(D(p["new_total"]), before + D(50))
		frappe.set_user("Administrator")  # nosemgrep: frappe-setuser -- the agent removes it
		with self.assertRaises(frappe.ValidationError):
			modification.propose(res, {"drop_addons": ["ADD-unknown"]})
		p = modification.propose(res, {"drop_addons": [addon_id]}, basis="ORIGINAL_VERSION")
		self.assertEqual(D(p["proposed"]["totals"]["total"]), before)
		modification.apply(p["proposal_token"], reason="guest changed their mind")
		self.assertEqual(D(frappe.db.get_value("Reservation", res, "tex_total_amount")), before)
		self.assertEqual(self.snapshot(res).get("addons") or [], [])
		self.assertEqual(D(frappe.db.get_value("TEX Reservation Revision", {
			"reservation": res, "change_type": "Extras", "pricing_basis": "ORIGINAL_VERSION"}, "new_amount")), before)
		other = self.book("g22-drop2")
		self.add(other, [{"code": "SPA"}])                          # the slot is free again

	def test_guests_never_see_how_many_are_left(self):
		import json

		extra("SPA", inventory_tracked=1, daily_capacity=1)
		b = self.book("g22-count")
		res = b["rooms"][0]["reservation"]
		frappe.set_user("Guest")  # nosemgrep: frappe-setuser -- the guest asks for two
		p = public.manage_extras_propose(token=b["manage_token"], reservation=res,
		                                 extras=[{"code": "SPA", "quantity": 2}])
		self.assertEqual(p["reasons"][0]["code"], "ADDON_SOLD_OUT")
		self.assertIn("not enough left on", p["reasons"][0]["message"])
		self.assertNotRegex(json.dumps(p), r"\d+ left")
		frappe.set_user("Administrator")  # nosemgrep: frappe-setuser -- staff see the count
		staff = crs_api.addon_propose(res, [{"code": "SPA", "quantity": 2}])
		self.assertIn("only 1 left on", staff["reasons"][0]["message"])
		frappe.set_user("Guest")  # nosemgrep: frappe-setuser -- a new visitor quotes two
		found = public.search(site=SLUG, check_in=str(fx.d(6, 10)), check_out=str(fx.d(6, 13)),
		                      rooms=[{"adults": 2}], market="DE", session_id="g22-count2")
		offer = found["properties"][0]["offers"][0]
		q = public.quote(site=SLUG, offer_key=offer["rooms"][0]["offer_key"], extras=[{"code": "SPA", "quantity": 2}],
		                 session_id="g22-count2")
		spa = next(e for e in q["quote"]["extras"] if e["code"] == "SPA")
		self.assertEqual((spa["ok"], spa["reason"]), (False, f"not enough left on {fx.d(6, 10)}"))
		self.assertNotRegex(json.dumps(q), r"\d+ left")
