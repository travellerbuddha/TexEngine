"""Capacity-limited extras (G-19): an extra with a daily capacity never sells more units on a
day than it has; cancellation, expiry and modification give units back; staff see and edit
the capacity; guests are told what is left."""

import frappe
from frappe.utils import add_to_date, now_datetime

from kamra.tex.api import crs as crs_api
from kamra.tex.api import public
from kamra.tex.availability import extras_repository as xinv
from kamra.tex.availability.extras_repository import ExtraSoldOut
from kamra.tex.money import D
from kamra.tex.security import scope
from kamra.tex.services import booking, modification
from kamra.tex.tests.integration import fixtures as fx
from kamra.tex.tests.integration.test_commercial_flows import GUEST, SLUG, setup_site_and_payments
from kamra.tex.tests.integration.test_critical_journey import TexTestCase


def limited(code: str, mode: str = "UNIT", capacity: int = 1, **kw) -> str:
	return fx.ensure_live("TEX Extra", {"property": fx.PROPERTY, "extra_code": code}, {
		"property": fx.PROPERTY, "extra_code": code, "extra_name": code.title(), "category": "Service",
		"pricing_mode": mode, "currency": "EUR", "amount": 30, "bookable_online": 1, "inventory_tracked": 1,
		"daily_capacity": capacity, **kw})


class ExtrasCase(TexTestCase):
	def setUp(self):
		super().setUp()
		setup_site_and_payments(self.f)
		self.spa = limited("SPA")

	def quotes(self, session: str, extras, *, check_in=(6, 10), check_out=(6, 13), rooms=1) -> list[dict]:
		"""Search and quote ``rooms`` Standard rooms (FLEX, all-inclusive) with these extras each."""
		frappe.set_user("Guest")  # nosemgrep: frappe-setuser -- a booking-engine visitor
		res = public.search(site=SLUG, check_in=str(fx.d(*check_in)), check_out=str(fx.d(*check_out)),
		                    rooms=[{"adults": 2}] * rooms, market="DE", session_id=session)
		rt = frappe.db.get_value("Room Type", {"property": fx.PROPERTY, "room_type_code": "STD"})
		rp = frappe.db.get_value("Rate Plan", {"property": fx.PROPERTY, "code": "FLEX"})
		offer = next(o for o in res["properties"][0]["offers"]
		             if o["room_type"] == rt and o["board"] == "AI" and o["rate_plan"] == rp)
		out = []
		for room in sorted(offer["rooms"], key=lambda r: r["room_index"]):
			q = public.quote(site=SLUG, offer_key=room["offer_key"], extras=list(extras), session_id=session)
			assert q["ok"], q
			out.append(q)
		return out

	def book(self, session: str, quotes, *, method="Pay at Hotel", email=None) -> dict:
		frappe.set_user("Guest")  # nosemgrep: frappe-setuser -- the visitor books
		return public.book(site=SLUG, quote_ids=[q["quote_id"] for q in quotes],
		                   guest={**GUEST, "email": email or f"{session}@example.com"}, payment_method=method,
		                   session_id=session, idempotency_key=f"idem-{session}")

	@staticmethod
	def extra(q: dict, code: str) -> dict:
		return next(e for e in q["quote"]["extras"] if e["code"] == code)

	@staticmethod
	def sold(code: str, day) -> int:
		return int(frappe.db.get_value("TEX Extra Inventory Day", {"property": fx.PROPERTY, "extra_code": code,
		                                                           "service_date": day}, "sold") or 0)

	@staticmethod
	def allocations(reservation: str) -> list[tuple]:
		return [(a.extra_code, str(a.service_date), a.units, a.status) for a in frappe.get_all(
			"TEX Extra Allocation", filters={"reservation": reservation},
			fields=["extra_code", "service_date", "units", "status"], order_by="service_date asc, status asc")]


class TestExtrasCapacity(ExtrasCase):
	def test_the_last_unit_goes_to_the_first_booking(self):
		first, second = self.quotes("g19-a", [{"code": "SPA"}]), self.quotes("g19-b", [{"code": "SPA"}])
		self.assertTrue(self.extra(first[0], "SPA")["ok"] and self.extra(second[0], "SPA")["ok"])  # 1 left for both
		b = self.book("g19-a", first)
		res = b["rooms"][0]["reservation"]
		self.assertEqual(self.allocations(res), [("SPA", str(fx.d(6, 10)), 1, "Confirmed")])
		self.assertEqual(self.sold("SPA", fx.d(6, 10)), 1)
		with self.assertRaises(ExtraSoldOut) as cm:                # quoted before, booked after: refused
			self.book("g19-b", second)
		# raised without frappe.throw, its code and the extra's name and day still reach the guest (G-70b)
		params = {"extra": "Spa", "date": str(fx.d(6, 10))}
		self.assertEqual((cm.exception.code, cm.exception.params), ("EXTRA_SOLD_OUT", params))
		self.assertEqual((frappe.local.response["tex_code"], frappe.local.response["tex_params"]),
		                 ("EXTRA_SOLD_OUT", params))
		late = self.extra(self.quotes("g19-c", [{"code": "SPA"}])[0], "SPA")
		self.assertEqual((late["ok"], late["reason"]), (False, f"sold out on {fx.d(6, 10)}"))

	def test_the_rooms_of_one_booking_count_together(self):
		quotes = self.quotes("g19-rooms", [{"code": "SPA"}], rooms=2)
		self.assertTrue(all(self.extra(q, "SPA")["ok"] for q in quotes))   # each room alone fits
		with self.assertRaises(ExtraSoldOut):
			self.book("g19-rooms", quotes)
		frappe.set_user("Administrator")  # nosemgrep: frappe-setuser -- revenue manager adds a slot
		crs_api.extras_bulk_update(fx.PROPERTY, ["SPA"], str(fx.d(6, 10)), str(fx.d(6, 10)), capacity=2)
		b = self.book("g19-rooms2", self.quotes("g19-rooms2", [{"code": "SPA"}], rooms=2))
		self.assertEqual(self.sold("SPA", fx.d(6, 10)), 2)
		self.assertEqual(len(b["rooms"]), 2)

	def test_a_nightly_extra_takes_every_night(self):
		limited("DINNER", "NIGHT")
		self.book("g19-n1", self.quotes("g19-n1", [{"code": "DINNER"}]))              # 10, 11, 12 June
		self.assertEqual([self.sold("DINNER", fx.d(6, d)) for d in (10, 11, 12, 13)], [1, 1, 1, 0])
		overlap = self.extra(self.quotes("g19-n2", [{"code": "DINNER"}], check_in=(6, 12), check_out=(6, 14))[0],
		                     "DINNER")
		self.assertEqual((overlap["ok"], overlap["reason"]), (False, f"sold out on {fx.d(6, 12)}"))
		after = self.quotes("g19-n3", [{"code": "DINNER"}], check_in=(6, 13), check_out=(6, 15))
		self.assertTrue(self.extra(after[0], "DINNER")["ok"])

	def test_a_chosen_service_date_is_the_day_it_uses(self):
		q = self.quotes("g19-sd", [{"code": "SPA", "service_dates": [str(fx.d(6, 12))]}])
		self.assertEqual(self.extra(q[0], "SPA")["usage"], [{"date": str(fx.d(6, 12)), "units": 1}])
		self.book("g19-sd", q)
		self.assertEqual((self.sold("SPA", fx.d(6, 10)), self.sold("SPA", fx.d(6, 12))), (0, 1))

	def test_cancelling_gives_the_units_back(self):
		b = self.book("g19-c1", self.quotes("g19-c1", [{"code": "SPA"}]))
		res = b["rooms"][0]["reservation"]
		frappe.set_user("Administrator")  # nosemgrep: frappe-setuser -- the agent cancels
		booking.cancel_reservation(res, reason="guest cancelled", waive_penalty=True)
		self.assertEqual(self.allocations(res), [("SPA", str(fx.d(6, 10)), 1, "Released")])
		self.assertEqual(self.sold("SPA", fx.d(6, 10)), 0)
		self.book("g19-c2", self.quotes("g19-c2", [{"code": "SPA"}]))       # the slot sells again

	def test_a_held_unit_is_confirmed_by_the_payment(self):
		b = self.book("g19-h1", self.quotes("g19-h1", [{"code": "SPA"}]), method="Card")
		res = b["rooms"][0]["reservation"]
		self.assertEqual(b["status"], "Pending Payment")
		self.assertEqual(self.allocations(res), [("SPA", str(fx.d(6, 10)), 1, "Held")])
		public.mock_pay(transaction=b["payment"]["transaction"], outcome="success",
		                sig=b["payment"]["fields"]["success_sig"])
		self.assertEqual(self.allocations(res), [("SPA", str(fx.d(6, 10)), 1, "Confirmed")])
		self.assertEqual(self.sold("SPA", fx.d(6, 10)), 1)

	def test_an_expired_hold_gives_the_unit_back(self):
		from kamra.reservation_state import expire_holds

		b = self.book("g19-x1", self.quotes("g19-x1", [{"code": "SPA"}]), method="Card")
		res = b["rooms"][0]["reservation"]
		frappe.set_user("Administrator")  # nosemgrep: frappe-setuser -- the scheduler
		frappe.db.set_value("Reservation", res, "hold_expires_on", add_to_date(now_datetime(), minutes=-1))
		# its checkout is over too: a payment attempt keeps the rooms only until then (K-2a)
		frappe.db.set_value("TEX Booking", b["booking"], "payment_attempt_until",
		                    add_to_date(now_datetime(), minutes=-1))
		expire_holds()                               # the PMS job leaves a TEX booking's rooms alone
		from kamra.tex.services import booking as booking_svc

		booking_svc.expire_pending_bookings()        # the booking and its rooms expire together (K-2a)
		self.assertEqual(frappe.db.get_value("Reservation", res, ["status", "cancellation_reason"]),
		                 ("Cancelled", "Payment failed"))             # G-86: it used to fail on the reason
		self.assertEqual(self.sold("SPA", fx.d(6, 10)), 0)


class TestExtrasModification(ExtrasCase):
	def test_a_change_moves_frees_and_credits_the_units(self):
		b = self.book("g19-m1", self.quotes("g19-m1", [{"code": "SPA"}]))
		res = b["rooms"][0]["reservation"]
		frappe.set_user("Administrator")  # nosemgrep: frappe-setuser -- the agent changes the stay
		same = modification.propose(res, {"adults": 2})                    # its own unit counts as left to it
		self.assertNotIn("EXTRA_SOLD_OUT", [w["code"] for w in same["warnings"]])
		self.assertTrue(next(e for e in same["proposed"]["extras"] if e["code"] == "SPA")["ok"])
		moved = modification.propose(res, {"check_in": str(fx.d(6, 11)), "check_out": str(fx.d(6, 14))})
		modification.apply(moved["proposal_token"], reason="later arrival")
		self.assertEqual((self.sold("SPA", fx.d(6, 10)), self.sold("SPA", fx.d(6, 11))), (0, 1))
		self.assertEqual([a for a in self.allocations(res) if a[3] != "Released"],
		                 [("SPA", str(fx.d(6, 11)), 1, "Confirmed")])
		other = self.book("g19-m2", self.quotes("g19-m2", [{"code": "SPA"}], check_in=(6, 12), check_out=(6, 14)))
		frappe.set_user("Administrator")  # nosemgrep: frappe-setuser -- the agent
		# moving onto a full day: the change shows it, and applying it drops the extra
		clash = modification.propose(res, {"check_in": str(fx.d(6, 12)), "check_out": str(fx.d(6, 15))})
		self.assertIn("EXTRA_SOLD_OUT", [w["code"] for w in clash["warnings"]])
		self.assertIsNotNone(other)
		dropped = modification.propose(res, {"extras": []})
		modification.apply(dropped["proposal_token"], reason="no spa")
		self.assertEqual(self.sold("SPA", fx.d(6, 11)), 0)
		self.assertFalse([a for a in self.allocations(res) if a[3] != "Released"])


	def test_a_modification_never_takes_more_than_is_left(self):
		import json

		a = self.book("g19-m3", self.quotes("g19-m3", [{"code": "SPA"}]))
		b = self.book("g19-m4", self.quotes("g19-m4", []))
		frappe.set_user("Administrator")  # nosemgrep: frappe-setuser -- the modification service
		res_a, res_b = a["rooms"][0]["reservation"], b["rooms"][0]["reservation"]
		with_spa = json.loads(frappe.db.get_value("Reservation", res_a, "tex_pricing_snapshot"))
		# under the day locks: a change that would add the spa to B is refused (A holds the last unit)
		with self.assertRaises(ExtraSoldOut):
			xinv.replace_for_reservation(fx.PROPERTY, b["booking"], res_b, with_spa, "Confirmed")
		# A keeping its own unit is fine: what it holds counts as available to it
		xinv.replace_for_reservation(fx.PROPERTY, a["booking"], res_a, with_spa, "Confirmed")
		self.assertEqual(self.sold("SPA", fx.d(6, 10)), 1)


class TestExtrasAdministration(ExtrasCase):
	def test_the_grid_shows_and_edits_capacity(self):
		self.book("g19-g1", self.quotes("g19-g1", [{"code": "SPA"}]))
		frappe.set_user("Administrator")  # nosemgrep: frappe-setuser -- revenue manager
		g = crs_api.extras_grid(fx.PROPERTY, str(fx.d(6, 9)), 4)
		spa = next(x for x in g["extras"] if x["code"] == "SPA")
		self.assertEqual([(c["date"], c["sold"], c["remaining"]) for c in spa["cells"]],
		                 [(str(fx.d(6, 9)), 0, 1), (str(fx.d(6, 10)), 1, 0), (str(fx.d(6, 11)), 0, 1),
		                  (str(fx.d(6, 12)), 0, 1)])
		out = crs_api.extras_bulk_update(fx.PROPERTY, ["SPA"], str(fx.d(6, 10)), str(fx.d(6, 11)), capacity=3)
		self.assertEqual((out["updated"], out["over_capacity"]), (2, []))
		crs_api.extras_bulk_update(fx.PROPERTY, ["SPA"], str(fx.d(6, 12)), str(fx.d(6, 12)), closed=1)
		cells = {c["date"]: c for c in next(x for x in crs_api.extras_grid(fx.PROPERTY, str(fx.d(6, 10)), 3)["extras"]
		                                    if x["code"] == "SPA")["cells"]}
		self.assertEqual((cells[str(fx.d(6, 10))]["remaining"], cells[str(fx.d(6, 12))]["closed"]), (2, True))
		closed = self.extra(self.quotes("g19-g2", [{"code": "SPA", "service_dates": [str(fx.d(6, 12))]}])[0], "SPA")
		self.assertEqual((closed["ok"], closed["reason"]), (False, f"closed on {fx.d(6, 12)}"))
		frappe.set_user("Administrator")  # nosemgrep: frappe-setuser -- revenue manager
		held = crs_api.extras_allocations(fx.PROPERTY, "SPA", str(fx.d(6, 10)))
		self.assertEqual([(a["units"], a["status"]) for a in held], [(1, "Confirmed")])
		# never below what is sold without saying so
		out = crs_api.extras_bulk_update(fx.PROPERTY, ["SPA"], str(fx.d(6, 10)), str(fx.d(6, 10)), capacity=0)
		self.assertEqual(out["over_capacity"], [])                        # 0 = back to the default of 1
		with self.assertRaises(frappe.ValidationError):                   # an extra without a limit
			crs_api.extras_bulk_update(fx.PROPERTY, ["TRF"], str(fx.d(6, 10)), str(fx.d(6, 10)), capacity=2)

	def test_a_day_note_is_set_and_removed(self):
		frappe.set_user("Administrator")  # nosemgrep: frappe-setuser -- revenue manager
		day = str(fx.d(6, 10))
		note = lambda: next(c for c in next(x for x in crs_api.extras_grid(fx.PROPERTY, day, 1)["extras"]  # noqa: E731
		                                   if x["code"] == "SPA")["cells"])["note"]
		crs_api.extras_bulk_update(fx.PROPERTY, ["SPA"], day, day, closed=1, note="therapist away")
		self.assertEqual(note(), "therapist away")
		crs_api.extras_bulk_update(fx.PROPERTY, ["SPA"], day, day, closed=0, note="")   # with another change
		self.assertFalse(note())
		crs_api.extras_bulk_update(fx.PROPERTY, ["SPA"], day, day, note="back at noon")
		crs_api.extras_bulk_update(fx.PROPERTY, ["SPA"], day, day, note="")              # the only change
		self.assertFalse(note())

	def test_only_inventory_editors_change_capacity(self):
		agent = fx.ensure_user("g19-agent@example.com", ["Call Center Agent"])
		fx.ensure("TEX Access Grant", {"user": agent, "property": fx.PROPERTY},
		          {"user": agent, "scope_level": "Hotel", "property": fx.PROPERTY,
		           "permission_profile": "Reservations Agent"})
		scope.clear_cache()
		frappe.set_user(agent)  # nosemgrep: frappe-setuser -- an agent: sees, does not edit
		self.assertTrue(crs_api.extras_availability(fx.PROPERTY, str(fx.d(6, 10)), str(fx.d(6, 13)))["SPA"])
		with self.assertRaises(frappe.PermissionError):
			crs_api.extras_bulk_update(fx.PROPERTY, ["SPA"], str(fx.d(6, 10)), str(fx.d(6, 10)), capacity=5)
		with self.assertRaises(frappe.PermissionError):
			crs_api.extras_reconcile(fx.PROPERTY)

	def test_guests_see_availability_never_counts(self):
		limited("BACKSTAGE", bookable_online=0)                          # staff only
		self.book("g19-p1", self.quotes("g19-p1", [{"code": "SPA"}]))
		frappe.set_user("Guest")  # nosemgrep: frappe-setuser -- a visitor
		a = public.extras_availability(site=SLUG, hotel=fx.PROPERTY, check_in=str(fx.d(6, 10)),
		                               check_out=str(fx.d(6, 12)))
		self.assertEqual(sorted(a), ["SPA"])
		self.assertEqual(a["SPA"][str(fx.d(6, 10))], {"available": False, "low": False})
		self.assertEqual(a["SPA"][str(fx.d(6, 11))], {"available": True, "low": True})
		with self.assertRaises(frappe.ValidationError):
			public.extras_availability(site=SLUG, hotel="Some Other Hotel", check_in=str(fx.d(6, 10)),
			                           check_out=str(fx.d(6, 12)))

	def test_a_limited_extra_needs_a_capacity_and_is_never_mandatory(self):
		frappe.set_user("Administrator")  # nosemgrep: frappe-setuser -- revenue manager
		base = {"doctype": "TEX Extra", "property": fx.PROPERTY, "extra_name": "Yoga", "category": "Service",
		        "pricing_mode": "UNIT", "currency": "EUR", "amount": 10, "inventory_tracked": 1}
		for bad in ({"extra_code": "YOGA1", "daily_capacity": 0},
		            {"extra_code": "YOGA2", "daily_capacity": 5, "is_mandatory": 1}):
			with self.assertRaises(frappe.ValidationError, msg=bad):
				frappe.get_doc({**base, **bad}).insert(ignore_permissions=True)

	def test_a_new_revision_keeps_the_count(self):
		from kamra.tex.commercial import revisions

		self.book("g19-r1", self.quotes("g19-r1", [{"code": "SPA"}]))
		frappe.set_user("Administrator")  # nosemgrep: frappe-setuser -- revenue manager changes the price
		draft = frappe.get_doc("TEX Extra", revisions.revise("TEX Extra", self.spa))
		draft.amount = 35
		draft.save(ignore_permissions=True)
		revisions.activate("TEX Extra", draft.name)
		late = self.extra(self.quotes("g19-r2", [{"code": "SPA"}])[0], "SPA")
		self.assertEqual((late["ok"], late["reason"]), (False, f"sold out on {fx.d(6, 10)}"))

	def test_reconcile_repairs_the_counters(self):
		b = self.book("g19-k1", self.quotes("g19-k1", [{"code": "SPA"}]))
		res = b["rooms"][0]["reservation"]
		frappe.set_user("Administrator")  # nosemgrep: frappe-setuser -- inventory manager
		day = frappe.db.get_value("TEX Extra Inventory Day", {"property": fx.PROPERTY, "extra_code": "SPA",
		                                                      "service_date": fx.d(6, 10)})
		doc = frappe.get_doc("TEX Extra Inventory Day", day)             # a Desk edit never moves the counter
		doc.sold = 9
		doc.note = "checked"
		doc.save(ignore_permissions=True)
		self.assertEqual(self.sold("SPA", fx.d(6, 10)), 1)
		frappe.db.sql("UPDATE `tabTEX Extra Inventory Day` SET sold=5 WHERE name=%s", day)
		self.assertEqual(crs_api.extras_reconcile(fx.PROPERTY)["drift"],
		                 [{"extra_code": "SPA", "date": str(fx.d(6, 10)), "was": 5, "now": 1}])
		frappe.db.set_value("Reservation", res, "status", "Cancelled")   # behind the hooks' back
		crs_api.extras_reconcile(fx.PROPERTY, "SPA")
		self.assertEqual((self.sold("SPA", fx.d(6, 10)), self.allocations(res)[0][3]), (0, "Released"))

	def test_stays_sold_before_a_limit_hold_their_units(self):
		from kamra.tex.commercial import revisions

		fx.ensure_live("TEX Extra", {"property": fx.PROPERTY, "extra_code": "MASSAGE"}, {
			"property": fx.PROPERTY, "extra_code": "MASSAGE", "extra_name": "Massage", "category": "Service",
			"pricing_mode": "UNIT", "currency": "EUR", "amount": 50, "bookable_online": 1})
		b = self.book("g19-b1", self.quotes("g19-b1", [{"code": "MASSAGE"}]))      # not limited yet
		frappe.set_user("Administrator")  # nosemgrep: frappe-setuser -- revenue manager limits it
		live = frappe.db.get_value("TEX Extra", {"property": fx.PROPERTY, "extra_code": "MASSAGE",
		                                         "tex_status": "Active"})
		draft = frappe.get_doc("TEX Extra", revisions.revise("TEX Extra", live))
		draft.inventory_tracked, draft.daily_capacity = 1, 1
		draft.save(ignore_permissions=True)
		revisions.activate("TEX Extra", draft.name)
		self.assertEqual(self.allocations(b["rooms"][0]["reservation"]),
		                 [("MASSAGE", str(fx.d(6, 10)), 1, "Confirmed")])
		late = self.extra(self.quotes("g19-b2", [{"code": "MASSAGE"}])[0], "MASSAGE")
		self.assertFalse(late["ok"])
		self.assertEqual(D(xinv.availability(fx.PROPERTY, ["MASSAGE"], fx.d(6, 10),
		                                     fx.d(6, 10))["MASSAGE"][fx.d(6, 10)].remaining), 0)

	def test_a_stay_whose_old_snapshot_has_no_whole_quantity_is_left_out_of_the_backfill(self):
		"""LO-48 (2K-4): a snapshot from before G-19 carries no ``usage``: its units are its quantity, read as a whole
		number, never cut to one. A stay whose quantity is not whole is left out of the backfill and logged; the other
		stays still hold their units and the extra is still limited."""
		import json

		from kamra.tex.commercial import revisions

		fx.ensure_live("TEX Extra", {"property": fx.PROPERTY, "extra_code": "MASSAGE"}, {
			"property": fx.PROPERTY, "extra_code": "MASSAGE", "extra_name": "Massage", "category": "Service",
			"pricing_mode": "UNIT", "currency": "EUR", "amount": 50, "bookable_online": 1})
		odd, fine = (self.book(f"lo48-{n}", self.quotes(f"lo48-{n}", [{"code": "MASSAGE"}]))["rooms"][0]["reservation"]
		             for n in ("odd", "fine"))
		frappe.set_user("Administrator")  # nosemgrep: frappe-setuser -- revenue manager limits it
		for res, quantity in ((odd, "2.5"), (fine, "1.000000")):              # as stored before G-19
			snap = json.loads(frappe.db.get_value("Reservation", res, "tex_pricing_snapshot"))
			for e in snap["extras"]:
				if e["code"] == "MASSAGE":
					e.pop("usage", None)
					e["quantity"] = quantity
			frappe.db.set_value("Reservation", res, "tex_pricing_snapshot", json.dumps(snap), update_modified=False)
		before = set(frappe.get_all("Error Log", pluck="name"))
		live = frappe.db.get_value("TEX Extra", {"property": fx.PROPERTY, "extra_code": "MASSAGE",
		                                         "tex_status": "Active"})
		draft = frappe.get_doc("TEX Extra", revisions.revise("TEX Extra", live))
		draft.inventory_tracked, draft.daily_capacity = 1, 5
		draft.save(ignore_permissions=True)
		revisions.activate("TEX Extra", draft.name)
		self.assertEqual(self.allocations(fine), [("MASSAGE", str(fx.d(6, 10)), 1, "Confirmed")])
		self.assertEqual(self.allocations(odd), [])
		logged = frappe.get_all("Error Log", filters={"name": ("not in", list(before) or ["-"])}, pluck="method")
		self.assertIn(f"TEX job extras backfill {odd}", logged)
		self.assertTrue(frappe.db.get_value("TEX Extra", {"property": fx.PROPERTY, "extra_code": "MASSAGE",
		                                                  "tex_status": "Active"}, "inventory_tracked"))
