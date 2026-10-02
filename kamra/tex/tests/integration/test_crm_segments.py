"""CRM segments (G-23, R-37): the named segments work end to end, a guest's facts come
only from the viewer's hotels, and a segment belongs to its enterprise (G-26)."""

import json
from datetime import timedelta
from unittest import mock

import frappe
from frappe.utils import add_days, getdate, nowdate

from kamra.tex.api import crm as crm_api
from kamra.tex.crm import service as crm
from kamra.tex.security import scope
from kamra.tex.services import booking
from kamra.tex.tests.integration import fixtures as fx
from kamra.tex.tests.integration.test_commercial_flows import GUEST, guest_books, setup_site_and_payments
from kamra.tex.tests.integration.test_critical_journey import TexTestCase

OTHER = "TEX Other Hotel"
OTHER_ENT = "TEX Other Enterprise"


def other_tenant() -> str:
	ent = fx.ensure("TEX Enterprise", {"enterprise_name": OTHER_ENT}, {"enterprise_name": OTHER_ENT})
	grp = fx.ensure("TEX Hotel Group", {"group_name": "TEX Other Group"}, {"group_name": "TEX Other Group",
	                                                                       "enterprise": ent})
	if not frappe.db.exists("Property", OTHER):
		frappe.get_doc({"doctype": "Property", "property_name": OTHER, "city": "Kemer", "country": "Turkey",
		                "currency": "EUR"}).insert(ignore_permissions=True)
	frappe.db.set_value("Property", OTHER, {"tex_hotel_group": grp, "tex_enterprise": ent})
	return ent


def agent(email: str, prop: str, profile: str = "Reservations Agent") -> str:
	frappe.set_user("Administrator")  # nosemgrep: frappe-setuser -- grants are set up by the admin
	user = fx.ensure_user(email, ["Call Center Agent"])
	fx.ensure("TEX Access Grant", {"user": user, "property": prop},
	          {"user": user, "scope_level": "Hotel", "property": prop, "permission_profile": profile})
	scope.clear_cache()
	return user


class SegmentCase(TexTestCase):
	def setUp(self):
		super().setUp()
		setup_site_and_payments(self.f)
		crm.ensure_system_segments()
		self.other_ent = other_tenant()
		self.here = agent("g23-here@example.com", fx.PROPERTY)
		self.there = agent("g23-there@example.com", OTHER)
		frappe.set_user("Administrator")  # nosemgrep: frappe-setuser -- fixtures

	def stay(self, session: str, *, where=fx.PROPERTY, days_ago=30, amount=800, status="Checked Out", **values):
		b = guest_books(session=session, guest={**GUEST, "email": "g23@example.com"})
		frappe.set_user("Administrator")  # nosemgrep: frappe-setuser -- fixtures
		res = b["rooms"][0]["reservation"]
		frappe.db.set_value("Reservation", res, {"property": where, "status": status, "tex_total_amount": amount,
		                                         "check_in_date": add_days(nowdate(), -days_ago - 3),
		                                         "check_out_date": add_days(nowdate(), -days_ago),
		                                         "tex_sale_at": add_days(nowdate(), -days_ago - 63),   # booked early
		                                         **values})
		return res, frappe.db.get_value("Reservation", res, "guest")

	def members(self, key: str, user: str) -> set[str]:
		frappe.set_user(user)  # nosemgrep: frappe-setuser -- the viewer decides the facts
		name = frappe.db.get_value("TEX Guest Segment", {"system_key": key})
		out = {r["name"] for r in crm_api.guests(segment=name, limit=200)["rows"]}
		frappe.set_user("Administrator")  # nosemgrep: frappe-setuser -- back
		return out


class TestNamedSegments(SegmentCase):
	def test_a_guests_facts_come_from_the_viewers_hotels_only(self):
		_r1, guest = self.stay("g23-a", amount=800)
		self.stay("g23-b", where=OTHER, amount=5000)
		frappe.set_user(self.here)  # nosemgrep: frappe-setuser -- tenant A
		row = next(r for r in crm_api.guests(q="g23@example.com")["rows"] if r["name"] == guest)
		self.assertEqual((row["tex_stays"], row["tex_lifetime_value"], row["tex_lifetime_currency"]), (1, "800.00", "EUR"))
		prof = crm_api.guest(guest)["guest"]
		self.assertEqual((prof["tex_stays"], prof["tex_lifetime_value"]), (1, "800.00"))
		frappe.set_user("Administrator")  # nosemgrep: frappe-setuser -- a high-value rule of tenant A
		frappe.set_user(self.here)  # nosemgrep: frappe-setuser -- tenant A saves it
		name = crm_api.save_segment({"segment_name": "Big spenders", "rules": {"match": "all", "conditions": [
			{"field": "lifetime_value", "op": "gte", "value": "2000", "currency": "EUR"}]}})["name"]
		self.assertNotIn(guest, {r["name"] for r in crm_api.guests(segment=name)["rows"]})   # 5000 was elsewhere

	def test_a_booking_of_several_rooms_is_one_stay(self):
		"""O-23 (audit Part 2H-1): the CRM counted a reservation, which is a room: a two-room booking was two
		stays and a repeat guest. A stay is a visit: the reservations of one booking."""
		r1, guest = self.stay("g23-rooms-a")
		r2, same = self.stay("g23-rooms-b")
		self.assertEqual(guest, same)
		frappe.db.set_value("Reservation", r2, "tex_booking", frappe.db.get_value("Reservation", r1, "tex_booking"))
		frappe.set_user(self.here)  # nosemgrep: frappe-setuser -- tenant A
		row = next(r for r in crm_api.guests(q="g23@example.com")["rows"] if r["name"] == guest)
		self.assertEqual((row["tex_stays"], row["tex_lifetime_value"]), (1, "1600.00"))     # one visit, both rooms' value
		self.assertNotIn(guest, self.members("REPEAT", self.here))
		frappe.set_user("Administrator")  # nosemgrep: frappe-setuser -- the stored statistics
		crm.refresh_guest_stats(guest)
		self.assertEqual(frappe.db.get_value("Guest", guest, ["tex_stays", "tex_lifetime_value"]), (1, 1600))
		third, _g = self.stay("g23-rooms-c")                                                 # a booking of its own
		self.assertIn(guest, self.members("REPEAT", self.here))
		crm.refresh_guest_stats(guest)
		self.assertEqual(frappe.db.get_value("Guest", guest, "tex_stays"), 2)
		self.assertTrue(third)

	def test_an_expired_hold_is_not_a_cancellation_of_the_guest(self):
		"""O-24 (audit Part 2H-2): a hold that ran out of time was the guest's cancellation (the CANCELLED
		segment, the profile's count) and their last sale (the lead time)."""
		_res, guest = self.stay("g23-held-a")
		hold = guest_books(session="g23-held-b", guest={**GUEST, "email": "g23@example.com"})
		frappe.set_user("Administrator")  # nosemgrep: frappe-setuser -- the scheduler
		self.assertTrue(booking.expire_booking(hold["booking"], force=True))
		self.assertNotIn(guest, self.members("CANCELLED", self.here))
		frappe.set_user(self.here)  # nosemgrep: frappe-setuser -- tenant A
		self.assertEqual(crm_api.guest(guest)["cancellations"]["count"], 0)
		row = next(r for r in crm_api.guests(q="g23@example.com")["rows"] if r["name"] == guest)
		self.assertEqual(row["tex_stays"], 1)
		frappe.set_user("Administrator")  # nosemgrep: frappe-setuser -- back

	def test_families_last_minute_cancelled_abandoned_birthday(self):
		res, guest = self.stay("g23-fam")                                   # guest_books has a child of 8
		self.assertIn(guest, self.members("FAMILY", self.here))
		self.assertNotIn(guest, self.members("LAST_MINUTE", self.here))
		frappe.db.set_value("Reservation", res, "tex_sale_at", add_days(nowdate(), -34))   # 1 day before arrival
		self.assertIn(guest, self.members("LAST_MINUTE", self.here))
		self.assertNotIn(guest, self.members("CANCELLED", self.here))
		up = guest_books(session="g23-cxl", guest={**GUEST, "email": "g23@example.com"})
		frappe.set_user("Administrator")  # nosemgrep: frappe-setuser -- the stay is cancelled
		booking.cancel_reservation(up["rooms"][0]["reservation"], reason="changed plans", waive_penalty=True)
		self.assertIn(guest, self.members("CANCELLED", self.here))
		self.assertNotIn(guest, self.members("CANCELLED", self.there))     # another tenant sees none of it
		self.assertNotIn(guest, self.members("ABANDONED", self.here))
		# a case names its guest only while the guest consents to marketing e-mail (ADR-046, ADR-056)
		frappe.db.set_value("Guest", guest, "tex_consent_email", 1)
		frappe.get_doc({"doctype": "TEX Abandoned Booking", "property": fx.PROPERTY, "session_id": "g23-ab",
		                "stage_reached": "quote", "status": "Open", "guest": guest, "consent_marketing": 1,
		                "last_event_at": add_days(nowdate(), -2)}).insert(ignore_permissions=True)
		self.assertIn(guest, self.members("ABANDONED", self.here))
		self.assertNotIn(guest, self.members("BIRTHDAY", self.here))
		soon = getdate(nowdate()) + timedelta(days=10)
		frappe.db.set_value("Guest", guest, "date_of_birth", soon.replace(year=1992))      # a leap year
		self.assertIn(guest, self.members("BIRTHDAY", self.here))

	def test_rules_are_typed_and_money_needs_its_currency(self):
		frappe.set_user(self.here)  # nosemgrep: frappe-setuser -- tenant A
		for bad in ({"field": "lifetime_value", "op": "gte", "value": "500"},
		            {"field": "stays", "op": "gte", "value": "many"}):
			with self.assertRaises(frappe.ValidationError):
				crm_api.save_segment({"segment_name": "Bad", "rules": {"conditions": [bad]}})


class TestSegmentTenancy(SegmentCase):
	def test_a_segment_belongs_to_its_enterprise(self):
		frappe.set_user(self.here)  # nosemgrep: frappe-setuser -- tenant A
		name = crm_api.save_segment({"segment_name": "Golfers", "rules": {"conditions": [
			{"field": "tags", "op": "contains", "value": "golf"}]}})["name"]
		mine = frappe.db.get_value("Property", fx.PROPERTY, "tex_enterprise")
		self.assertEqual(frappe.db.get_value("TEX Guest Segment", name, "enterprise"), mine)
		with self.assertRaises(frappe.ValidationError):                   # unique within an enterprise
			crm_api.save_segment({"segment_name": "Golfers", "rules": {"conditions": []}})
		self.assertIn(name, {s["name"] for s in crm_api.segments()["segments"]})
		frappe.set_user(self.there)  # nosemgrep: frappe-setuser -- tenant B
		listed = crm_api.segments()["segments"]
		self.assertNotIn(name, {s["name"] for s in listed})
		self.assertTrue({"FAMILY", "BIRTHDAY", "ABANDONED"} <= {s["system_key"] for s in listed})
		for call in (lambda: crm_api.guests(segment=name), lambda: crm_api.evaluate_segment(name),
		             lambda: crm_api.save_segment({"name": name, "segment_name": "Mine now", "rules": {}}),
		             lambda: crm_api.delete_segment(name)):
			with self.assertRaises((frappe.DoesNotExistError, frappe.PermissionError)):
				call()
		frappe.set_user("Administrator")  # nosemgrep: frappe-setuser -- B may read segments in Desk (role)
		frappe.get_doc("User", self.there).add_roles("Hotel Admin")
		frappe.set_user(self.there)  # nosemgrep: frappe-setuser -- Desk / REST filter by tenant too
		listed_rest = frappe.get_list("TEX Guest Segment", pluck="name", limit=500)
		self.assertNotIn(name, listed_rest)
		self.assertTrue(frappe.db.get_value("TEX Guest Segment", {"system_key": "FAMILY"}) in listed_rest)
		with self.assertRaises(frappe.PermissionError):
			frappe.get_doc("TEX Guest Segment", name).check_permission("read")
		theirs = crm_api.save_segment({"segment_name": "Golfers", "rules": {"conditions": []}})["name"]
		self.assertEqual(frappe.db.get_value("TEX Guest Segment", theirs, "enterprise"), self.other_ent)
		frappe.set_user(self.here)  # nosemgrep: frappe-setuser -- its owner deletes it
		crm_api.delete_segment(name)
		self.assertFalse(frappe.db.exists("TEX Guest Segment", name))
		self.assertTrue(frappe.db.exists("TEX Audit Event", {"action": "guest_segment.delete", "reference_name": name}))

	def test_presets_are_shared_read_only_and_keep_no_tenant_count(self):
		preset = frappe.db.get_value("TEX Guest Segment", {"system_key": "FAMILY"})
		frappe.set_user(self.here)  # nosemgrep: frappe-setuser -- tenant A
		self.assertIsNotNone(crm_api.evaluate_segment(preset)["members"])
		self.assertFalse(frappe.db.get_value("TEX Guest Segment", preset, "last_evaluated"))
		for call in (lambda: crm_api.save_segment({"name": preset, "segment_name": "x", "rules": {}}),
		             lambda: crm_api.delete_segment(preset)):
			with self.assertRaises(frappe.ValidationError):
				call()

	def test_counting_needs_crm_view(self):
		nobody = fx.ensure_user("g23-nobody@example.com", ["Call Center Agent"])
		preset = frappe.db.get_value("TEX Guest Segment", {"system_key": "VIP"})
		frappe.set_user(nobody)  # nosemgrep: frappe-setuser -- no grant anywhere
		scope.clear_cache()
		with self.assertRaises(frappe.PermissionError):
			crm_api.evaluate_segment(preset)


class TestSegmentMigration(SegmentCase):
	def setUp(self):
		super().setUp()
		# the schema is migrated already: DDL here would commit this test's rows (see p12's test)
		self.enterContext(mock.patch.object(frappe, "reload_doc"))
		self.enterContext(mock.patch("kamra.tex.setup.ensure_indexes"))

	def test_presets_are_seeded_and_renamed(self):
		from kamra.patches.tex import p16_crm_segments

		lapsed = frappe.db.get_value("TEX Guest Segment", {"system_key": "LAPSED"})
		frappe.db.set_value("TEX Guest Segment", lapsed, {"segment_name": "Lapsed (no stay in 18 months)",
		                                                  "rules_json": "{}"})
		frappe.db.delete("TEX Guest Segment", {"system_key": "BIRTHDAY"})
		p16_crm_segments.execute()
		self.assertEqual(frappe.db.get_value("TEX Guest Segment", lapsed, "segment_name"), "No stay in 12 months")
		self.assertIn('"value": 365', frappe.db.get_value("TEX Guest Segment", lapsed, "rules_json"))
		self.assertTrue(frappe.db.exists("TEX Guest Segment", {"system_key": "BIRTHDAY"}))
		self.assertEqual(json.loads(frappe.db.get_value("TEX Guest Segment", {"system_key": "FAMILY"},
		                                                "rules_json"))["conditions"][0]["field"], "has_children")


class TestProfileStays(SegmentCase):
	def test_an_expired_hold_is_marked_on_the_guests_stays(self):
		"""LO-24 (audit 2K-2): the profile's stays tab tells a hold that ran out of time (never a sale, O-24) from a
		cancellation (before: both just "Cancelled")."""
		gone = guest_books(session="lo24-gone", guest={**GUEST, "email": "lo24@example.com"})
		cut = guest_books(session="lo24-cut", guest={**GUEST, "email": "lo24@example.com"})
		frappe.set_user("Administrator")  # nosemgrep: frappe-setuser -- the expiry job, then staff
		self.assertTrue(booking.expire_booking(gone["booking"], force=True))
		booking.cancel_reservation(cut["rooms"][0]["reservation"], reason="plans changed", waive_penalty=True)
		guest = frappe.db.get_value("TEX Booking", gone["booking"], "booker_guest")
		stays = {s["name"]: (s["status"], s["hold_expired"]) for s in crm.profile(guest)["stays"]}
		self.assertEqual(stays[gone["rooms"][0]["reservation"]], ("Cancelled", True))
		self.assertEqual(stays[cut["rooms"][0]["reservation"]], ("Cancelled", False))
