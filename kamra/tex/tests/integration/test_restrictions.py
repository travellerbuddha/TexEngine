"""Restriction enforcement (G-48, ADR-057).

A new booking — booking engine, CRS / Call Center — is refused by a stop sell, CTA/CTD, a
length of stay, an advance rule or a booking window of its scope. A change of a booked stay
(staff modification, guest self-service) is checked the same way for what it newly takes:
new nights, a new arrival or departure, the new length, a new product. Staff who may edit
restrictions override with a reason, audited. A channel's booking is accepted with a warning
(ADR-039). Cells can be hotel- or market-level and scoped to the Booking Engine, the Call
Center or both; the channels' ARI hears the booking window and the advance rules."""

import hashlib
import json

import frappe
from frappe.utils import add_days, getdate, now_datetime

from kamra.tex.api import crs as crs_api
from kamra.tex.api import public
from kamra.tex.commercial import grid as grid_svc
from kamra.tex.services import booking, modification, quoting
from kamra.tex.tests.integration import fixtures as fx
from kamra.tex.tests.integration.test_commercial_flows import (
	GUEST,
	SLUG,
	guest_books,
	setup_site_and_payments,
)
from kamra.tex.tests.integration.test_critical_journey import TexTestCase, pick, search_std
from kamra.tex.tests.integration.test_crm_segments import agent
from kamra.tex.tests.integration.test_distribution import DistributionCase, message

BOTH = "Booking Engine + Call Center"


def codes(items) -> list[str]:
	return sorted({(x.get("code") or "") for x in items or []})


class RestrictionCase(TexTestCase):
	def setUp(self):
		super().setUp()
		setup_site_and_payments(self.f)
		self.std = frappe.db.get_value("Room Type", {"property": fx.PROPERTY, "room_type_code": "STD"})
		self.dlx = frappe.db.get_value("Room Type", {"property": fx.PROPERTY, "room_type_code": "DLX"})
		self.ci, self.co = fx.d(6, 10), fx.d(6, 13)
		self.today = getdate(now_datetime())

	def cell(self, day, **kw) -> str:
		frappe.set_user("Administrator")  # nosemgrep: frappe-setuser -- the revenue manager sets a restriction
		return frappe.get_doc({"doctype": "TEX ARI Restriction", "property": fx.PROPERTY, "restriction_date": day,
		                       **kw}).insert(ignore_permissions=True).name

	def staff_books(self, *, room="STD", channel="CALL_CENTER") -> str:
		frappe.set_user("Administrator")  # nosemgrep: frappe-setuser -- a call-centre booking
		offer = pick(search_std(self.ci, self.co, [{"adults": 2}], channel=channel), room_code=room)
		q = quoting.create_quote(offer["rooms"][0]["offer_key"])
		self.assertTrue(q["ok"], q)
		b = booking.create_booking(quote_ids=[q["quote_id"]], guest=dict(GUEST), payment_method="Pay at Hotel")
		return b["rooms"][0]["reservation"]

	def std_entry(self, prop, board="AI"):
		rp = frappe.db.get_value("Rate Plan", {"property": fx.PROPERTY, "code": "FLEX"})
		return next(o for o in prop["offers"] + prop["unavailable"]
		            if o["room_type"] == self.std and o["board"] == board and o["rate_plan"] == rp)


class TestNewBookings(RestrictionCase):
	"""Enforcement on a new booking, from the booking engine and the CRS."""

	def test_the_booking_engine_refuses_restricted_stays(self):
		self.cell(fx.d(6, 11), room_type=self.std, stop_sell="STOP")
		frappe.set_user("Guest")  # nosemgrep: frappe-setuser -- a visitor searches
		res = public.search(site=SLUG, check_in=str(self.ci), check_out=str(self.co), rooms=[{"adults": 2}],
		                    market="DE", session_id="g48-web")
		prop = res["properties"][0]
		entry = self.std_entry(prop)
		self.assertFalse(entry["bookable"])
		self.assertIn("STOP_SELL", codes(entry["reasons"]))
		q = public.quote(site=SLUG, offer_key=entry["rooms"][0]["offer_key"], session_id="g48-web")
		self.assertFalse(q["ok"])
		self.assertIn("STOP_SELL", codes(q["reasons"]))
		dlx = next(o for o in prop["offers"] if o["room_type"] == self.dlx)
		self.assertTrue(dlx["bookable"])                                          # another room is not closed

	def test_a_booking_made_after_a_restriction_was_set_is_refused(self):
		with self.assertRaisesRegex(frappe.ValidationError, "no longer bookable"):
			guest_books(session="g48-late", method="Pay at Hotel",
			            before_book=lambda: self.cell(self.ci, room_type=self.std, cta="Yes"))

	def test_each_rule_refuses_a_new_booking(self):
		for kw, code in (({"restriction_date": self.co, "ctd": "Yes"}, "CTD"),
		                 ({"restriction_date": self.ci, "min_los": 4}, "MIN_LOS"),
		                 ({"restriction_date": self.ci, "max_los": 2}, "MAX_LOS"),
		                 ({"restriction_date": self.ci, "min_advance": 400}, "MIN_ADVANCE"),
		                 ({"restriction_date": self.ci, "max_advance": 10}, "MAX_ADVANCE"),
		                 ({"restriction_date": self.ci, "stop_sell": "STOP", "stop_sell_mode": "ARRIVAL"},
		                  "STOP_SELL_ARRIVAL")):
			with self.subTest(code):
				day = kw.pop("restriction_date")
				name = self.cell(day, room_type=self.std, **kw)
				entry = self.std_entry(search_std(self.ci, self.co, [{"adults": 2}]))
				self.assertFalse(entry["bookable"])
				self.assertIn(code, codes(entry["restrictions"]))
				frappe.delete_doc("TEX ARI Restriction", name, ignore_permissions=True)

	def test_the_booking_window_limits_the_sale_dates_of_a_night(self):
		self.cell(fx.d(6, 12), book_from=add_days(self.today, 5))
		entry = self.std_entry(search_std(self.ci, self.co, [{"adults": 2}]))
		self.assertFalse(entry["bookable"])
		self.assertIn("BOOKING_WINDOW", codes(entry["restrictions"]))
		# a stay that does not sleep that night is not affected
		self.assertTrue(self.std_entry(search_std(self.ci, fx.d(6, 12), [{"adults": 2}]))["bookable"])
		frappe.db.delete("TEX ARI Restriction", {"property": fx.PROPERTY})
		self.cell(fx.d(6, 12), book_to=add_days(self.today, -1))                  # the window has closed
		self.assertIn("BOOKING_WINDOW", codes(self.std_entry(search_std(self.ci, self.co, [{"adults": 2}]))[
			"restrictions"]))
		self.cell(fx.d(6, 12), room_type=self.std, book_to=add_days(self.today, 30))   # the room's own window
		self.assertTrue(self.std_entry(search_std(self.ci, self.co, [{"adults": 2}]))["bookable"])

	def test_booking_engine_and_call_center_scopes(self):
		cc_cell = self.cell(fx.d(6, 11), channel_scope="Call Center", stop_sell="STOP")
		frappe.set_user("Administrator")  # nosemgrep: frappe-setuser -- a call-centre agent searches
		cc = crs_api.search(check_in=str(self.ci), check_out=str(self.co), rooms=[{"adults": 2}], market="DE",
		                    channel="CALL_CENTER", properties=[fx.PROPERTY])
		self.assertFalse(self.std_entry(cc["properties"][0])["bookable"])
		self.assertTrue(self.std_entry(search_std(self.ci, self.co, [{"adults": 2}]))["bookable"])   # the web sells
		frappe.delete_doc("TEX ARI Restriction", cc_cell, ignore_permissions=True)
		self.cell(fx.d(6, 11), channel_scope=BOTH, stop_sell="STOP")
		for channel in ("DIRECT_WEB", "CALL_CENTER"):
			self.assertFalse(self.std_entry(search_std(self.ci, self.co, [{"adults": 2}], channel=channel))[
				"bookable"], channel)
		# another channel (B2B, a channel manager) is not the booking engine or the call centre
		self.assertTrue(self.std_entry(search_std(self.ci, self.co, [{"adults": 2}], channel="B2B"))["bookable"])
		# a sales channel's own cell outranks the surface scope: it re-opens the web
		self.cell(fx.d(6, 11), sales_channel="DIRECT_WEB", stop_sell="OPEN")
		self.assertTrue(self.std_entry(search_std(self.ci, self.co, [{"adults": 2}]))["bookable"])


class TestStaffModifications(RestrictionCase):
	"""A change is checked like a new booking for what it newly takes; staff who may edit
	restrictions (``restriction.edit``) override with a reason, audited."""

	def test_a_new_night_under_a_stop_sell_refuses_the_change(self):
		res = self.staff_books()
		self.cell(self.co, room_type=self.std, stop_sell="STOP")                # the night an extension adds
		p = modification.propose(res, {"check_out": str(fx.d(6, 14))})
		self.assertFalse(p["sellable"])
		self.assertIn("STOP_SELL", codes(p["restrictions"]))
		with self.assertRaisesRegex(frappe.ValidationError, "cannot be sold"):
			modification.apply(p["proposal_token"], reason="one more night")

	def test_nights_already_held_are_not_checked_again(self):
		res = self.staff_books()
		self.cell(fx.d(6, 11), room_type=self.std, stop_sell="STOP")            # a night the stay holds
		self.cell(self.ci, room_type=self.std, cta="Yes", min_los=3)             # its arrival, already sold
		for change in ({"check_out": str(fx.d(6, 14))}, {"adults": 3}):
			p = modification.propose(res, change)
			self.assertTrue(p["sellable"], p["warnings"])
			self.assertEqual(p["restrictions"], [])
		modification.apply(modification.propose(res, {"check_out": str(fx.d(6, 14))})["proposal_token"],
		                   reason="one more night")
		self.assertEqual(frappe.db.get_value("Reservation", res, "check_out_date"), fx.d(6, 14))

	def test_arrival_departure_and_length_rules_follow_what_changes(self):
		res = self.staff_books()
		self.cell(fx.d(6, 11), room_type=self.std, cta="Yes")
		p = modification.propose(res, {"check_in": str(fx.d(6, 11))})           # arrives a day later
		self.assertFalse(p["sellable"])
		self.assertIn("CTA", codes(p["restrictions"]))
		self.cell(fx.d(6, 12), room_type=self.std, ctd="Yes")
		self.assertIn("CTD", codes(modification.propose(res, {"check_out": str(fx.d(6, 12))})["restrictions"]))
		self.cell(self.ci, room_type=self.std, min_los=3)
		shorter = modification.propose(res, {"check_out": str(fx.d(6, 12))})     # 2 nights now
		self.assertIn("MIN_LOS", codes(shorter["restrictions"]))
		self.assertFalse(shorter["sellable"])

	def test_the_booking_window_applies_to_the_new_nights(self):
		res = self.staff_books()
		self.cell(self.co, book_to=add_days(self.today, -1))
		p = modification.propose(res, {"check_out": str(fx.d(6, 14))})
		self.assertIn("BOOKING_WINDOW", codes(p["restrictions"]))
		self.assertFalse(p["sellable"])

	def test_another_room_type_is_checked_in_full(self):
		res = self.staff_books()
		self.cell(fx.d(6, 11), room_type=self.dlx, stop_sell="STOP")
		p = modification.propose(res, {"room_type": self.dlx})
		self.assertFalse(p["sellable"])
		self.assertIn("STOP_SELL", codes(p["restrictions"]))

	def test_an_override_needs_restriction_edit_a_reason_and_is_audited(self):
		res = self.staff_books()
		self.cell(self.co, room_type=self.std, stop_sell="STOP")
		p = modification.propose(res, {"check_out": str(fx.d(6, 14))})
		self.assertTrue(p["restriction_override"])                             # the admin may override
		out = modification.apply(p["proposal_token"], reason="VIP stays on", override_restrictions=True)
		self.assertEqual(frappe.db.get_value("Reservation", res, "check_out_date"), fx.d(6, 14))
		ev = frappe.get_all("TEX Audit Event", filters={"action": "reservation.restriction_override",
		                                                "reference_name": res}, fields=["new_value", "reason"])
		self.assertEqual(len(ev), 1)
		self.assertIn("STOP_SELL", ev[0].new_value)
		self.assertEqual(ev[0].reason, "VIP stays on")
		changes = json.loads(frappe.db.get_value("TEX Reservation Revision", out["revision"], "changes_json"))
		self.assertEqual(codes(changes["restrictions_overridden"]), ["STOP_SELL"])

	def test_an_agent_without_restriction_edit_cannot_override(self):
		res = self.staff_books()
		self.cell(self.co, room_type=self.std, stop_sell="STOP")
		user = agent("g48-agent@example.com", fx.PROPERTY)
		frappe.set_user(user)  # nosemgrep: frappe-setuser -- a call-centre agent tries to override
		p = modification.propose(res, {"check_out": str(fx.d(6, 14))})
		self.assertFalse(p["restriction_override"])
		with self.assertRaises(frappe.PermissionError):
			modification.apply(p["proposal_token"], reason="please", override_restrictions=True)
		self.assertEqual(frappe.db.get_value("Reservation", res, "check_out_date"), self.co)


class TestGuestSelfService(RestrictionCase):
	"""The manage page refuses a change the restrictions refuse, and never overrides."""

	def test_a_guest_cannot_extend_into_a_stop_sell(self):
		b = guest_books(session="g48-guest", method="Pay at Hotel")
		res = b["rooms"][0]["reservation"]
		frappe.set_user("Guest")  # nosemgrep: frappe-setuser -- the guest proposes a change first
		before = public.manage_propose(token=b["manage_token"], reservation=res,
		                               changes={"check_out": str(fx.d(6, 14))})
		self.assertTrue(before["sellable"], before["warnings"])
		self.cell(self.co, room_type=self.std, stop_sell="STOP")                 # then the hotel closes the night
		frappe.set_user("Guest")  # nosemgrep: frappe-setuser -- the guest on the manage page
		up = public.manage_propose(token=b["manage_token"], reservation=res, changes={"check_out": str(fx.d(6, 14))})
		self.assertFalse(up["sellable"])
		self.assertIn("STOP_SELL", codes(up["warnings"]))
		for token in (up["proposal_token"], before["proposal_token"]):   # neither applies
			with self.assertRaisesRegex(frappe.ValidationError, "cannot be sold"):
				public.manage_apply(token=b["manage_token"], proposal_token=token)
		self.assertEqual(frappe.db.get_value("Reservation", res, "check_out_date"), self.co)

	def test_a_guest_cannot_shorten_below_the_minimum_stay(self):
		b = guest_books(session="g48-guest-los", method="Pay at Hotel")
		res = b["rooms"][0]["reservation"]
		self.cell(self.ci, min_los=3)
		frappe.set_user("Guest")  # nosemgrep: frappe-setuser -- the guest on the manage page
		up = public.manage_propose(token=b["manage_token"], reservation=res, changes={"check_out": str(fx.d(6, 12))})
		self.assertFalse(up["sellable"])
		self.assertIn("MIN_LOS", codes(up["warnings"]))


class TestChannelBookings(DistributionCase):
	"""A channel's booking breaking a TEX restriction is still accepted (the guest holds the
	channel's confirmation, ADR-039), with a warning and an audit event."""

	def test_a_restricted_channel_booking_is_accepted_with_a_warning(self):
		frappe.get_doc({"doctype": "TEX ARI Restriction", "property": fx.PROPERTY, "restriction_date": fx.d(6, 11),
		                "room_type": self.std, "stop_sell": "STOP"}).insert(ignore_permissions=True)
		self.send(message(ref="OTA-G48"))
		out = self.apply_all()
		self.assertTrue(out[0]["booking"])
		self.assertIn("restriction", (out[0]["warning"] or "").lower())
		self.assertIn("stop sale", out[0]["warning"])
		ev = frappe.db.get_value("TEX Audit Event", {"action": "channel.overbooking",
		                                            "reference_name": out[0]["booking"]}, "new_value")
		self.assertIn("stop sale", ev or "")

	def test_a_channel_change_is_checked_for_what_it_newly_takes(self):
		self.send(message(ref="OTA-G48B"))
		self.apply_all()
		frappe.get_doc({"doctype": "TEX ARI Restriction", "property": fx.PROPERTY, "restriction_date": fx.d(6, 11),
		                "room_type": self.std, "stop_sell": "STOP"}).insert(ignore_permissions=True)
		frappe.get_doc({"doctype": "TEX ARI Restriction", "property": fx.PROPERTY, "restriction_date": fx.d(6, 13),
		                "room_type": self.std, "stop_sell": "STOP"}).insert(ignore_permissions=True)
		self.send(message(ref="OTA-G48B", status="modified", co=fx.d(6, 14), total="600.00"))
		out = self.apply_all()
		warning = out[0]["warning"] or ""
		self.assertIn(str(fx.d(6, 13)), warning)                                 # the new night
		self.assertNotIn(str(fx.d(6, 11)), warning)                              # a night it already held

	def test_the_ari_closes_what_the_sale_date_rules_refuse(self):
		today = getdate(now_datetime())
		night = fx.d(6, 11)
		frappe.get_doc({"doctype": "TEX ARI Restriction", "property": fx.PROPERTY, "restriction_date": night,
		                "book_from": add_days(today, 10)}).insert(ignore_permissions=True)
		self.assertTrue(frappe.get_all("TEX Integration Outbox", filters={"connection": self.conn.name}))
		from kamra.tex.distribution import repository as dist

		self.assertTrue(dist.build_days(self.mapping, night, night)[0].closed)   # outside its booking window
		self.assertFalse(dist.build_days(self.mapping, fx.d(6, 12), fx.d(6, 12))[0].closed)
		arrival = fx.d(6, 12)
		frappe.get_doc({"doctype": "TEX ARI Restriction", "property": fx.PROPERTY, "restriction_date": arrival,
		                "room_type": self.std, "min_advance": 400}).insert(ignore_permissions=True)
		day = dist.build_days(self.mapping, arrival, arrival)[0]
		self.assertTrue(day.cta and not day.closed)                              # no arrival that day, stays through

	def test_a_booking_window_boundary_is_queued_at_the_sites_midnight(self):
		from kamra.tex.distribution import repository as dist

		today = getdate(now_datetime())
		frappe.get_doc({"doctype": "TEX ARI Restriction", "property": fx.PROPERTY, "restriction_date": fx.d(6, 11),
		                "book_from": today}).insert(ignore_permissions=True)
		frappe.db.delete("TEX Integration Outbox", {"connection": self.conn.name})
		self.assertEqual(dist.restriction_boundaries(today), 1)
		p = json.loads(frappe.db.get_value("TEX Integration Outbox", self.jobs()[0], "payload"))
		self.assertEqual((p["from"], p["to"]), (str(fx.d(6, 11)), str(fx.d(6, 11))))


class TestGridCells(RestrictionCase):
	"""Hotel- and market-level cells, channel scopes and the booking window in the grid."""

	def test_hotel_and_market_level_cells(self):
		frappe.set_user("Administrator")  # nosemgrep: frappe-setuser -- the revenue manager edits the grid
		out = grid_svc.bulk_update(fx.PROPERTY, self.ci, self.ci, room_types=[], hotel_level=True, market="DE",
		                           restrictions={"min_los": 5})
		self.assertEqual(out["restriction_cells"], 1)
		row = frappe.get_all("TEX ARI Restriction", filters={"property": fx.PROPERTY}, fields=["room_type", "market",
		                                                                                     "min_los"])
		self.assertEqual([(r.room_type, r.market, r.min_los) for r in row], [(None, "DE", 5)])
		for rt in ("STD", "DLX"):
			entry = next(o for o in search_std(self.ci, self.co, [{"adults": 2}])["unavailable"]
			             if o["room_type"] == self.f["room_types"][rt])
			self.assertIn("MIN_LOS", codes(entry["restrictions"]))
		g = grid_svc.grid(fx.PROPERTY, self.ci, 3, market="DE")
		hotel = g["rows"][0]
		self.assertEqual((hotel["room_type"], hotel["level"]), (None, "hotel"))
		self.assertEqual(hotel["cells"][0]["own"]["min_los"], 5)
		self.assertEqual(g["rows"][1]["cells"][0]["min_los"], 5)                 # every room row inherits it
		with self.assertRaisesRegex(frappe.ValidationError, "room types"):
			grid_svc.bulk_update(fx.PROPERTY, self.ci, self.ci, room_types=[], hotel_level=True,
			                     inventory={"closed": 1})

	def test_channel_scopes_and_the_booking_window_round_trip(self):
		frappe.set_user("Administrator")  # nosemgrep: frappe-setuser -- the revenue manager edits the grid
		grid_svc.bulk_update(fx.PROPERTY, self.ci, self.ci, room_types=[self.std], channel_scope=BOTH,
		                     restrictions={"book_from": str(add_days(self.today, 3)), "book_to": str(fx.d(5, 1))})
		cell = frappe.get_all("TEX ARI Restriction", filters={"property": fx.PROPERTY},
		                      fields=["channel_scope", "book_from", "book_to", "sales_channel"])[0]
		self.assertEqual((cell.channel_scope, cell.book_from, cell.book_to, cell.sales_channel),
		                 (BOTH, add_days(self.today, 3), fx.d(5, 1), None))
		g = grid_svc.grid(fx.PROPERTY, self.ci, 1, channel_scope=BOTH)
		std = next(r for r in g["rows"] if r["room_type"] == self.std)
		self.assertEqual((std["cells"][0]["book_from"], std["cells"][0]["own"]["book_to"]),
		                 (str(add_days(self.today, 3)), str(fx.d(5, 1))))
		# the same scope without the channel scope is another cell
		grid_svc.bulk_update(fx.PROPERTY, self.ci, self.ci, room_types=[self.std], restrictions={"min_los": 2})
		self.assertEqual(frappe.db.count("TEX ARI Restriction", {"property": fx.PROPERTY}), 2)
		with self.assertRaisesRegex(frappe.ValidationError, "channel"):
			grid_svc.bulk_update(fx.PROPERTY, self.ci, self.ci, room_types=[self.std], channel="DIRECT_WEB",
			                     channel_scope=BOTH, restrictions={"min_los": 2})
		with self.assertRaisesRegex(frappe.ValidationError, "booking window"):
			grid_svc.bulk_update(fx.PROPERTY, self.ci, self.ci, room_types=[self.std],
			                     restrictions={"book_from": str(fx.d(5, 2)), "book_to": str(fx.d(5, 1))})

	def test_existing_cells_keep_their_scope_key(self):
		name = self.cell(self.ci, room_type=self.std, market="DE", min_los=2)
		raw = "|".join(str(v or "") for v in (fx.PROPERTY, self.std, "", "DE", "", "", self.ci))
		self.assertEqual(frappe.db.get_value("TEX ARI Restriction", name, "scope_key"),
		                 hashlib.sha1(raw.encode()).hexdigest())

	def test_restrictions_are_edited_only_with_restriction_edit(self):
		user = agent("g48-grid-agent@example.com", fx.PROPERTY)
		frappe.set_user(user)  # nosemgrep: frappe-setuser -- an agent tries to edit the grid
		with self.assertRaises(frappe.PermissionError):
			crs_api.ari_bulk_update(property=fx.PROPERTY, start=str(self.ci), end=str(self.ci), room_types=[],
			                        hotel_level=1, restrictions=json.dumps({"stop_sell": "STOP"}))
		self.assertEqual(frappe.db.count("TEX ARI Restriction", {"property": fx.PROPERTY}), 0)

