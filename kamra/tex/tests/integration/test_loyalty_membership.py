"""C-04 (owner, 2026-10-03; ADR-077): a loyalty member is a guest who joined the hotel's program (through staff
now, on the web next) or who stayed and earned points in it (a matured earning); a guest who left is not one,
whatever they earned. Members get the program's members-only prices."""

import threading
from unittest import mock

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import add_to_date, now_datetime

from kamra.tex.api import crm as crm_api
from kamra.tex.api import crs as crs_api
from kamra.tex.api import loyalty as loyalty_api
from kamra.tex.api import policies as policy_api
from kamra.tex.api import ui_crs
from kamra.tex.crm import loyalty
from kamra.tex.crm import service as crm
from kamra.tex.money import D
from kamra.tex.tests.integration import fixtures as fx
from kamra.tex.tests.integration.test_crm_segments import OTHER, agent
from kamra.tex.tests.integration.test_loyalty_admin import CLUB, LoyaltyCase


class MembershipCase(LoyaltyCase):
	def setUp(self):
		super().setUp()
		self.club = self.create()
		self.viewer = agent("c04-viewer@example.com", fx.PROPERTY, "Viewer")
		self.guest = self.profile("mia")
		frappe.set_user("Administrator")  # nosemgrep: frappe-setuser -- fixtures

	def profile(self, tag: str) -> str:
		ent = frappe.db.get_value("Property", fx.PROPERTY, "tex_enterprise")
		return frappe.get_doc({"doctype": "Guest", "first_name": tag.title(), "last_name": "Member",
		                       "email": f"c04-{tag}-{frappe.generate_hash(length=6)}@example.com",
		                       "tex_enterprise": ent}).insert(ignore_permissions=True).name

	def earn(self, guest: str, status: str, program: str | None = None) -> str:
		return frappe.get_doc({"doctype": "TEX Loyalty Ledger", "program": program or self.club, "guest": guest,
		                       "entry_type": "Earn", "points": 100, "status": status, "property": fx.PROPERTY,
		                       "reason": "a stay"}).insert(ignore_permissions=True).name

	def join(self, guest: str, user: str | None = None, program: str | None = None) -> dict:
		frappe.set_user(user or self.desk)  # nosemgrep: frappe-setuser -- staff join the guest
		try:
			return crm_api.loyalty_join(guest=guest, program=program or self.club)
		finally:
			frappe.set_user("Administrator")  # nosemgrep: frappe-setuser -- back


class TestMembership(MembershipCase):
	def test_c04_a_guest_who_joined_is_a_member_until_they_leave(self):
		self.assertFalse(loyalty.is_member(self.guest, fx.PROPERTY))
		out = self.join(self.guest)
		self.assertTrue(loyalty.is_member(self.guest, fx.PROPERTY))
		row = frappe.db.get_value("TEX Loyalty Member", out["name"], ["program", "guest", "status", "source",
		                                                               "joined_by", "property", "joined_at"],
		                          as_dict=True)
		self.assertEqual((row.program, row.guest, row.status, row.source, row.joined_by, row.property),
		                 (self.club, self.guest, "Active", "Staff", self.desk, fx.PROPERTY))
		self.assertTrue(row.joined_at)
		self.assertTrue(frappe.db.exists("TEX Audit Event", {"action": "loyalty.member_join",
		                                                     "reference_name": out["name"]}))
		frappe.set_user(self.desk)  # nosemgrep: frappe-setuser -- staff
		crm_api.loyalty_leave(guest=self.guest, program=self.club, reason="asked to leave")
		frappe.set_user("Administrator")  # nosemgrep: frappe-setuser -- back
		self.assertFalse(loyalty.is_member(self.guest, fx.PROPERTY))
		left = frappe.db.get_value("TEX Loyalty Member", out["name"], ["status", "left_reason", "left_at"], as_dict=True)
		self.assertEqual((left.status, left.left_reason), ("Left", "asked to leave"))
		self.assertTrue(left.left_at)
		self.assertTrue(frappe.db.exists("TEX Audit Event", {"action": "loyalty.member_leave",
		                                                     "reference_name": out["name"]}))
		# joining again makes the same record active: one membership per guest and program
		again = self.join(self.guest)
		self.assertEqual(again["name"], out["name"])
		self.assertTrue(loyalty.is_member(self.guest, fx.PROPERTY))
		self.assertEqual(frappe.db.count("TEX Loyalty Member", {"guest": self.guest}), 1)
		self.assertEqual(self.join(self.guest)["name"], out["name"])                  # a second join changes nothing

	def test_c04_a_guest_who_stayed_and_earned_is_a_member_without_joining(self):
		pending = self.earn(self.guest, "Pending")
		self.assertFalse(loyalty.is_member(self.guest, fx.PROPERTY))             # not stayed yet
		frappe.db.set_value("TEX Loyalty Ledger", pending, "status", "Reversed")
		self.assertFalse(loyalty.is_member(self.guest, fx.PROPERTY))             # cancelled
		self.earn(self.guest, "Available")
		self.assertTrue(loyalty.is_member(self.guest, fx.PROPERTY))              # stayed and earned
		other = self.profile("used")
		self.earn(other, "Used")
		self.assertTrue(loyalty.is_member(other, fx.PROPERTY))                   # earned and spent
		# a guest who left is not a member, whatever they earned
		frappe.set_user(self.desk)  # nosemgrep: frappe-setuser -- staff
		crm_api.loyalty_leave(guest=self.guest, program=self.club, reason="no more mail")
		frappe.set_user("Administrator")  # nosemgrep: frappe-setuser -- back
		self.assertFalse(loyalty.is_member(self.guest, fx.PROPERTY))

	def test_c04_no_program_no_members(self):
		self.join(self.guest)
		frappe.db.set_value("TEX Loyalty Program", self.club, "enabled", 0)
		self.assertFalse(loyalty.is_member(self.guest, fx.PROPERTY))
		self.assertFalse(loyalty.is_member(None, fx.PROPERTY))

	def test_c04_joining_and_leaving_need_crm_edit_at_a_hotel_of_the_program(self):
		for user in (self.viewer, self.there):
			with self.assertRaises(frappe.PermissionError, msg=user):
				self.join(self.guest, user=user)
		self.assertFalse(frappe.db.exists("TEX Loyalty Member", {"guest": self.guest}))
		self.join(self.guest)
		frappe.set_user(self.viewer)  # nosemgrep: frappe-setuser -- a viewer may not end it either
		with self.assertRaises(frappe.PermissionError):
			crm_api.loyalty_leave(guest=self.guest, program=self.club, reason="x")
		frappe.set_user(self.desk)  # nosemgrep: frappe-setuser -- a reason is required
		with self.assertRaises(frappe.ValidationError):
			crm_api.loyalty_leave(guest=self.guest, program=self.club, reason="  ")
		frappe.set_user("Administrator")  # nosemgrep: frappe-setuser -- back
		self.assertTrue(loyalty.is_member(self.guest, fx.PROPERTY))

	def test_c04_a_group_programs_member_is_a_member_at_each_of_its_hotels(self):
		group = frappe.db.get_value("Property", fx.PROPERTY, "tex_hotel_group")
		frappe.db.set_value("TEX Loyalty Program", self.club, "enabled", 0)
		shared = loyalty_api.save_program({**CLUB, "program_name": "Group Club", "hotel_group": group})["name"]
		sister = fx.ensure("Property", {"property_name": "TEX C04 Sister"},
		                   {"property_name": "TEX C04 Sister", "city": "Kemer", "country": "Turkey",
		                    "currency": "EUR"})
		frappe.db.set_value("Property", sister, {"tex_hotel_group": group,
		                                         "tex_enterprise": frappe.db.get_value("Property", fx.PROPERTY,
		                                                                               "tex_enterprise")})
		self.join(self.guest, program=shared)
		self.assertTrue(loyalty.is_member(self.guest, fx.PROPERTY))
		self.assertTrue(loyalty.is_member(self.guest, sister))
		self.assertFalse(loyalty.is_member(self.guest, OTHER))                   # another enterprise's hotel
		# the sister hotel's staff see the member, and when they joined by month only, as the other hotels' entries
		frappe.set_user(agent("c04-sister@example.com", sister))  # nosemgrep: frappe-setuser -- the sister's staff
		[account] = crm_api.loyalty_summary(self.guest)
		frappe.set_user("Administrator")  # nosemgrep: frappe-setuser -- back
		self.assertTrue(account["member"])
		self.assertEqual((account["membership"]["status"], account["membership"]["other_hotel"]), ("Active", True))
		self.assertRegex(account["membership"]["joined_at"], r"^\d{4}-\d{2}$")
		# review round 1: the program's own hotel (none: a group's) and its hotels the user sees the guest through,
		# so the CRM makes a membership for one of them, never the first hotel the user sees the guest at
		from kamra.tex.api import ui_backoffice_crm_payments as ui_crm

		frappe.set_user("c04-sister@example.com")  # nosemgrep: frappe-setuser -- the sister's staff
		[info] = ui_crm.loyalty_programs(self.guest)
		frappe.set_user("Administrator")  # nosemgrep: frappe-setuser -- back
		self.assertEqual((info["program"], info["program_property"], info["hotels"]), (shared, None, [sister]))

	def test_c04_the_guests_summary_shows_the_membership(self):
		self.join(self.guest)
		frappe.set_user(self.desk)  # nosemgrep: frappe-setuser -- the hotel's staff read the profile
		[account] = crm_api.loyalty_summary(self.guest)
		frappe.set_user("Administrator")  # nosemgrep: frappe-setuser -- back
		self.assertEqual(account["program"], self.club)                         # listed without any points yet
		self.assertTrue(account["member"])
		self.assertEqual((account["membership"]["status"], account["membership"]["source"]), ("Active", "Staff"))
		self.assertTrue(account["membership"]["joined_at"])
		earned = self.profile("earned")
		self.earn(earned, "Available")
		frappe.set_user(self.desk)  # nosemgrep: frappe-setuser -- staff
		[acc] = crm_api.loyalty_summary(earned)
		frappe.set_user("Administrator")  # nosemgrep: frappe-setuser -- back
		self.assertEqual((acc["member"], acc["membership"]), (True, None))         # a member by their stay

	def test_c04_memberships_follow_the_tenancy_in_desk_and_rest(self):
		name = self.join(self.guest)["name"]
		admin = fx.ensure_user("c04-there-admin@example.com", ["Hotel Admin"])
		fx.ensure("TEX Access Grant", {"user": admin, "property": OTHER},
		          {"user": admin, "scope_level": "Hotel", "property": OTHER, "permission_profile": "Hotel Admin"})
		frappe.set_user(admin)  # nosemgrep: frappe-setuser -- another enterprise's hotel admin, in Desk
		try:
			self.assertNotIn(name, frappe.get_list("TEX Loyalty Member", pluck="name"))
			with self.assertRaises(frappe.PermissionError):
				frappe.get_doc("TEX Loyalty Member", name).check_permission("read")
		finally:
			frappe.set_user("Administrator")  # nosemgrep: frappe-setuser -- back
		mine = fx.ensure_user("c04-here-admin@example.com", ["Hotel Admin"])
		fx.ensure("TEX Access Grant", {"user": mine, "property": fx.PROPERTY},
		          {"user": mine, "scope_level": "Hotel", "property": fx.PROPERTY, "permission_profile": "Hotel Admin"})
		frappe.set_user(mine)  # nosemgrep: frappe-setuser -- the hotel's own admin reads it
		try:
			self.assertIn(name, frappe.get_list("TEX Loyalty Member", pluck="name"))
		finally:
			frappe.set_user("Administrator")  # nosemgrep: frappe-setuser -- back

	def test_c04_a_merge_keeps_one_membership_per_program(self):
		kept, dup = self.guest, self.profile("dup")
		frappe.db.set_value("Guest", dup, "email", frappe.db.get_value("Guest", kept, "email"))
		mine = self.join(kept)["name"]
		self.join(dup)
		frappe.set_user(self.desk)  # nosemgrep: frappe-setuser -- staff merge the duplicate
		crm_api.merge_guests(source=dup, target=kept)
		frappe.set_user("Administrator")  # nosemgrep: frappe-setuser -- back
		self.assertEqual(frappe.get_all("TEX Loyalty Member", filters={"guest": kept}, pluck="name"), [mine])
		self.assertTrue(loyalty.is_member(kept, fx.PROPERTY))
		# a duplicate's own membership moves with it when the profile that stays has none
		other, dup2 = self.profile("other"), self.profile("dup2")
		moved = self.join(dup2)["name"]
		frappe.set_user(self.desk)  # nosemgrep: frappe-setuser -- staff
		crm_api.merge_guests(source=dup2, target=other)
		frappe.set_user("Administrator")  # nosemgrep: frappe-setuser -- back
		self.assertEqual(frappe.get_all("TEX Loyalty Member", filters={"guest": other}, pluck="name"), [moved])

	def test_c04_r1_a_merge_keeps_the_membership_changed_last(self):
		"""Review round 1: where both profiles have a membership of the program, the person's last word decides:
		a newer Left on the duplicate ends the older Active of the profile that stays, and the other way round."""
		for last in ("Left", "Active"):
			with self.subTest(last=last):
				kept, dup = self.profile(f"k{last}"), self.profile(f"d{last}")
				mine, theirs = self.join(kept)["name"], self.join(dup)["name"]
				older, newer = (mine, theirs) if last == "Left" else (theirs, mine)
				frappe.db.set_value("TEX Loyalty Member", theirs, {"status": "Left", "left_reason": "moved away"})
				frappe.db.set_value("TEX Loyalty Member", older, "modified", "2026-01-01 10:00:00", update_modified=False)
				frappe.db.set_value("TEX Loyalty Member", newer, "modified", "2026-06-01 10:00:00", update_modified=False)
				frappe.set_user(self.desk)  # nosemgrep: frappe-setuser -- staff merge the duplicate
				out = crm_api.merge_guests(source=dup, target=kept)
				frappe.set_user("Administrator")  # nosemgrep: frappe-setuser -- back
				self.assertEqual(frappe.get_all("TEX Loyalty Member", filters={"guest": kept}, pluck="status"), [last])
				self.assertEqual(loyalty.is_member(kept, fx.PROPERTY), last == "Active")
				self.assertEqual(frappe.get_all("TEX Loyalty Member", filters={"guest": dup}), [])
				self.assertEqual(out["memberships_dropped"], [theirs])                    # named in the audit

	def test_c04_an_erased_guest_is_no_member(self):
		name = self.join(self.guest)["name"]
		crm.erase_traces(self.guest, "Erased guest", emails=(), audit_event=False)
		row = frappe.db.get_value("TEX Loyalty Member", name, ["status", "left_reason"], as_dict=True)
		self.assertEqual((row.status, row.left_reason), ("Left", "erased"))
		self.assertFalse(loyalty.is_member(self.guest, fx.PROPERTY))

	def test_c04_r1_an_erased_guest_is_no_member_by_their_stays_either(self):
		"""Review round 1: erasure ended Active memberships only; a member by their stays stayed one."""
		self.earn(self.guest, "Available")
		self.assertTrue(loyalty.is_member(self.guest, fx.PROPERTY))
		frappe.db.set_value("Guest", self.guest, "tex_erased_at", now_datetime())
		crm.erase_traces(self.guest, "Erased guest", emails=(), audit_event=False)
		self.assertFalse(loyalty.is_member(self.guest, fx.PROPERTY))
		with self.assertRaises(frappe.ValidationError):
			self.join(self.guest)                                                     # nor joined again

	def test_c04_r1_staff_join_only_to_a_program_of_the_guests_hotels(self):
		"""Review round 1: staff who may edit guests in two enterprises never join one's guest to the other's program
		(nor adjust its points there)."""
		ent = frappe.db.get_value("Property", OTHER, "tex_enterprise")
		theirs = frappe.get_doc({"doctype": "Guest", "first_name": "Far", "last_name": "Away",
		                         "email": f"c04-far-{frappe.generate_hash(length=6)}@example.com",
		                         "tex_enterprise": ent}).insert(ignore_permissions=True).name
		both = agent("c04-both@example.com", fx.PROPERTY)
		fx.ensure("TEX Access Grant", {"user": both, "property": OTHER},
		          {"user": both, "scope_level": "Hotel", "property": OTHER, "permission_profile": "Reservations Agent"})
		from kamra.tex.security import scope

		scope.clear_cache()
		for call in (lambda: self.join(theirs, user=both),
		             lambda: crm_api.loyalty_adjust(guest=theirs, program=self.club, points=10, reason="goodwill")):
			frappe.set_user(both)  # nosemgrep: frappe-setuser -- an agent of both enterprises
			try:
				with self.assertRaises((frappe.PermissionError, frappe.DoesNotExistError)):
					call()
			finally:
				frappe.set_user("Administrator")  # nosemgrep: frappe-setuser -- back
		self.assertFalse(frappe.db.exists("TEX Loyalty Member", {"guest": theirs}))
		self.assertFalse(frappe.db.exists("TEX Loyalty Ledger", {"guest": theirs}))

	def test_c04_now_is_recorded_when_staff_join(self):
		before = now_datetime()
		name = self.join(self.guest)["name"]
		self.assertGreaterEqual(frappe.db.get_value("TEX Loyalty Member", name, "joined_at"), before.replace(microsecond=0))

	def test_c04_a_program_with_members_does_not_move(self):
		"""Its memberships would make the guests members at another hotel: as a program with points (G-24)."""
		self.join(self.guest)
		sister = fx.ensure("Property", {"property_name": "TEX C04 Sister"},
		                   {"property_name": "TEX C04 Sister", "city": "Kemer", "country": "Turkey", "currency": "EUR"})
		doc = frappe.get_doc("TEX Loyalty Program", self.club)
		doc.property = sister
		with self.assertRaisesRegex(frappe.ValidationError, "cannot move"):
			doc.save(ignore_permissions=True)
		self.assertEqual(frappe.db.get_value("TEX Loyalty Program", self.club, "property"), fx.PROPERTY)


STAY = {"check_in": str(fx.d(6, 10)), "check_out": str(fx.d(6, 13)), "rooms": [{"adults": 2, "children": []}],
        "market": "DE", "channel": "CALL_CENTER"}


class TestMemberPrices(MembershipCase):
	"""C-04: a members-only promotion is saved and goes live; the call centre prices the caller it names at the
	members' price when they are a member of the hotel's program, and such a price books only for a member."""

	def setUp(self):
		super().setUp()
		frappe.db.set_value("Guest", self.guest, {"first_name": "Mia", "last_name": "Member"})
		self.members_ten = self.promotion()

	def promotion(self, **kw) -> str:
		doc = policy_api.save_record("TEX Promotion", {"promotion_name": "Members 10", "property": fx.PROPERTY,
		                                               "trigger": "Automatic", "value_type": "PERCENT", "value": 10,
		                                               "applies_to": "ACCOMMODATION", "member_only": 1, **kw})
		policy_api.activate("TEX Promotion", doc["name"], at=str(add_to_date(now_datetime(), minutes=-1)))
		return doc["name"]

	def search(self, guest: str | None = None, user: str | None = None, **kw) -> dict:
		frappe.set_user(user or self.desk)  # nosemgrep: frappe-setuser -- the agent on the phone
		try:
			return ui_crs.search(**STAY, properties=[fx.PROPERTY], guest=guest, **kw)
		finally:
			frappe.set_user("Administrator")  # nosemgrep: frappe-setuser -- back

	def flex(self, res: dict) -> dict:
		return next(o for o in res["properties"][0]["offers"] if o["room_type"] == self.f["room_types"]["STD"]
		            and o["board"] == "AI" and o["rate_plan"] == self.f["rate_plans"]["FLEX"])

	def contact(self, guest: str) -> dict:
		g = frappe.db.get_value("Guest", guest, ["first_name", "last_name", "email"], as_dict=True)
		return {"first_name": g.first_name, "last_name": g.last_name, "email": g.email, "country": "Germany"}

	def book(self, offer: dict, guest: dict) -> dict:
		frappe.set_user(self.desk)  # nosemgrep: frappe-setuser -- the agent books
		try:
			q = crs_api.quote(offer_key=offer["rooms"][0]["offer_key"])
			return crs_api.book(quote_ids=[q["quote_id"]], guest=guest, payment_method="Pay at Hotel")
		finally:
			frappe.set_user("Administrator")  # nosemgrep: frappe-setuser -- back

	def test_c04_a_members_only_promotion_is_saved_and_goes_live(self):
		self.assertEqual(frappe.db.get_value("TEX Promotion", self.members_ten, ["member_only", "tex_status"]),
		                 (1, "Active"))

	def test_c04_the_call_centre_prices_a_member_at_the_members_price(self):
		anyone = self.flex(self.search())
		stranger = self.search(self.guest)                                     # named, not a member yet
		self.assertEqual((stranger["properties"][0]["member"], self.flex(stranger)["total"]),
		                 (False, anyone["total"]))
		self.assertFalse(self.flex(stranger).get("member_price"))
		self.join(self.guest)
		member = self.search(self.guest)
		offer = self.flex(member)
		self.assertTrue(member["properties"][0]["member"])
		self.assertTrue(offer["member_price"])
		self.assertLess(D(offer["total"]), D(anyone["total"]))
		applied = [p for p in offer["rooms"][0]["quote"]["promotions"] if p["applied"]]
		self.assertIn((self.members_ten, True), [(p["promo_id"], p.get("member_only")) for p in applied])
		self.assertFalse(anyone["member_price"])                                # nobody named: nobody's price

	def test_c04_a_members_price_books_for_the_member_only(self):
		self.join(self.guest)
		offer = self.flex(self.search(self.guest))
		done = self.book(offer, self.contact(self.guest))
		self.assertEqual(frappe.db.get_value("TEX Booking", done["booking"], "booker_guest"), self.guest)
		self.assertEqual(D(done["total"]), D(offer["total"]))
		# another caller on the same quote's price: refused, and nothing is booked
		again = self.flex(self.search(self.guest))
		with self.assertRaisesRegex(frappe.ValidationError, "member"):
			self.book(again, {"first_name": "Otto", "last_name": "Other", "email": "c04-otto@example.com",
			                  "country": "Germany"})
		self.assertFalse(frappe.db.exists("Guest", {"email": "c04-otto@example.com"}))

	def test_c04_a_member_who_left_is_refused_the_members_price(self):
		self.join(self.guest)
		offer = self.flex(self.search(self.guest))
		frappe.set_user(self.desk)  # nosemgrep: frappe-setuser -- staff
		crm_api.loyalty_leave(guest=self.guest, program=self.club, reason="asked to leave")
		frappe.set_user("Administrator")  # nosemgrep: frappe-setuser -- back
		with self.assertRaisesRegex(frappe.ValidationError, "member"):
			self.book(offer, self.contact(self.guest))

	def test_c04_a_price_without_a_members_promotion_books_for_anyone(self):
		policy_api.archive("TEX Promotion", self.members_ten, reason="members price over")
		self.join(self.guest)
		offer = self.flex(self.search(self.guest))
		self.assertFalse(offer.get("member_price"))
		done = self.book(offer, {"first_name": "Otto", "last_name": "Other", "email": "c04-otto2@example.com",
		                         "country": "Germany"})
		self.assertTrue(done["booking"])

	def test_c04_the_caller_named_must_be_one_the_agent_sees(self):
		ent = frappe.db.get_value("Property", OTHER, "tex_enterprise")
		theirs = frappe.get_doc({"doctype": "Guest", "first_name": "Far", "last_name": "Away",
		                         "email": "c04-far@example.com", "tex_enterprise": ent}).insert(ignore_permissions=True)
		with self.assertRaises(frappe.PermissionError):
			self.search(theirs.name)
		frappe.set_user("Administrator")  # nosemgrep: frappe-setuser -- a member at the other hotel's program
		self.assertFalse(loyalty.is_member(theirs.name, fx.PROPERTY))

	def test_c04_a_member_is_priced_as_one_at_their_programs_hotels_only(self):
		"""A hotel of the same enterprise without the program (the agent sees the guest there) is no member's."""
		self.join(self.guest)
		sister = fx.ensure("Property", {"property_name": "TEX C04 Sister"},
		                   {"property_name": "TEX C04 Sister", "city": "Kemer", "country": "Turkey", "currency": "EUR"})
		frappe.db.set_value("Property", sister, {"tex_hotel_group": None, "tex_enterprise": frappe.db.get_value(
			"Property", fx.PROPERTY, "tex_enterprise")})
		frappe.set_user("Administrator")  # nosemgrep: frappe-setuser -- a group search across hotels
		res = crs_api.search(**STAY, properties=[fx.PROPERTY, sister, OTHER], guest=self.guest)
		member = {p["property"]: p["member"] for p in res["properties"]}
		self.assertEqual(member, {fx.PROPERTY: True, sister: False, OTHER: False})

	def test_2q_the_callers_membership_is_read_once_per_program(self):
		"""Batch 2Q (§6N1): the call centre's search read the caller's erasure mark, and the membership, once per hotel
		searched (``loyalty.is_member`` each time): a group search of many hotels sharing one program read the same
		rows each time. The mark is read once, each program once; who is a member where is unchanged."""
		self.join(self.guest)
		sister = fx.ensure("Property", {"property_name": "TEX C04 Sister"},
		                   {"property_name": "TEX C04 Sister", "city": "Kemer", "country": "Turkey", "currency": "EUR"})
		frappe.db.set_value("Property", sister, {"tex_hotel_group": None, "tex_enterprise": frappe.db.get_value(
			"Property", fx.PROPERTY, "tex_enterprise")})
		frappe.get_doc({"doctype": "TEX Loyalty Program", "program_name": "Sister Club 2Q", "enabled": 1,
		                "currency": "EUR", "property": sister}).insert(ignore_permissions=True)
		frappe.set_user("Administrator")  # nosemgrep: frappe-setuser -- a group search across hotels
		real, marks = frappe.db.get_value, []

		def counted(doctype, filters=None, fieldname="name", *a, **kw):
			if doctype == "Guest" and filters == self.guest and fieldname == "tex_erased_at":
				marks.append(1)
			return real(doctype, filters, fieldname, *a, **kw)

		with mock.patch.object(frappe.db, "get_value", side_effect=counted):
			res = crs_api.search(**STAY, properties=[fx.PROPERTY, sister, OTHER], guest=self.guest)
		self.assertEqual({p["property"]: p["member"] for p in res["properties"]},
		                 {fx.PROPERTY: True, sister: False, OTHER: False})
		self.assertEqual(len(marks), 1)

	def change(self, reservation: str, nights: int = 5) -> dict:
		from kamra.tex.services import modification

		frappe.set_user("Administrator")  # nosemgrep: frappe-setuser -- a revenue manager prices the change
		return modification.propose(reservation, {"check_out": str(fx.d(6, 10 + nights))}, basis="CURRENT")

	def members_price_in(self, proposal: dict) -> bool:
		return any(p.get("applied") and p.get("member_only") for p in proposal["proposed"]["promotions"])

	def test_c04_r1_a_change_prices_a_member_only_for_a_member(self):
		"""Review round 1 (BLOCKER): a member's search signs every offer as a member's; an offer that no members-only
		promotion priced books for anyone. Its stay kept the member's flag, and a change gave a non-member the
		member's price. A change prices the stay as a member's when it was sold at a member's price, or for a
		booker who is a member now."""
		policy_api.archive("TEX Promotion", self.members_ten, reason="a long-stay one instead")
		self.promotion(promotion_name="Members long stay", min_nights=5)           # not on a 3-night stay
		self.join(self.guest)
		offer = self.flex(self.search(self.guest))
		self.assertFalse(offer["member_price"])
		stranger = self.book(offer, {"first_name": "Otto", "last_name": "Other", "email": "c04-otto3@example.com",
		                             "country": "Germany"})
		mine = self.book(self.flex(self.search(self.guest)), self.contact(self.guest))
		theirs_res = frappe.db.get_value("Reservation", {"tex_booking": stranger["booking"]}, "name")
		mine_res = frappe.db.get_value("Reservation", {"tex_booking": mine["booking"]}, "name")
		self.assertFalse(self.members_price_in(self.change(theirs_res)))           # five nights, no member's price
		self.assertTrue(self.members_price_in(self.change(mine_res)))              # the member gets it
		# review round 2: the stay records whether its booker was a member, so the historical simulation of the
		# non-member's stay never applies a members-only promotion either (it reads the stay as sold)
		from kamra.tex.services import modification

		self.assertEqual([frappe.parse_json(frappe.db.get_value("Reservation", r, "tex_pricing_snapshot"))["request"]
		                  ["member"] for r in (theirs_res, mine_res)], [False, True])
		self.promotion(promotion_name="Members any stay")
		at = str(now_datetime())
		simulated = {r: modification.simulate(r, at)["simulated"]["promotions"] for r in (theirs_res, mine_res)}
		self.assertEqual([any(p["applied"] and p.get("member_only") for p in simulated[r])
		                  for r in (theirs_res, mine_res)], [False, True])

	def test_c04_r1_the_booking_checks_the_membership_again_with_a_locking_read(self):
		"""Review round 1: the second check runs once the profile is locked, with a locking read (a plain read sees
		this request's old view, not a leave committed meanwhile)."""
		self.join(self.guest)
		offer = self.flex(self.search(self.guest))
		calls = []
		real = loyalty.is_member

		def spy(guest, property, **kw):
			calls.append(kw.get("lock", False))
			return real(guest, property, **kw)

		with mock.patch.object(loyalty, "is_member", side_effect=spy):
			self.book(offer, self.contact(self.guest))
		self.assertEqual(calls, [False, True])                                      # before any lock; then locked


class TestMembershipReadsAreCurrent(IntegrationTestCase):
	"""Review round 1: a locking read of the membership sees a leave another request committed after this one's
	read view opened; a plain read does not. The booking's second check reads so (above). Commits its fixtures
	(another connection must see them) and removes them."""

	def test_c04_r1_a_locking_read_sees_a_leave_committed_meanwhile(self):
		frappe.set_user("Administrator")  # nosemgrep: frappe-setuser -- fixtures
		fx.base_setup()
		program = guest = None
		try:
			program = loyalty_api.save_program({**CLUB, "enabled": 0, "property": fx.PROPERTY,
			                                    "program_name": f"C04 race {frappe.generate_hash(length=6)}"})["name"]
			guest = frappe.get_doc({"doctype": "Guest", "first_name": "Race", "last_name": "Member",
			                        "email": f"c04-race-{frappe.generate_hash(length=6)}@example.com"}
			                       ).insert(ignore_permissions=True).name
			frappe.get_doc({"doctype": "TEX Loyalty Member", "program": program, "guest": guest, "status": "Active",
			                "source": "Staff", "property": fx.PROPERTY}).insert(ignore_permissions=True)
			frappe.db.commit()  # nosemgrep: frappe-manual-commit -- the other connection reads them
			self.assertTrue(loyalty.member_of(guest, program))                     # this request's read view opens
			site, sites_path = frappe.local.site, frappe.local.sites_path

			def staff_end_it():                                                    # another request, its own connection
				frappe.init(site=site, sites_path=sites_path)
				frappe.connect()
				try:
					frappe.db.set_value("TEX Loyalty Member", {"guest": guest, "program": program}, "status", "Left")
					frappe.db.commit()  # nosemgrep: frappe-manual-commit -- its own request
				finally:
					frappe.destroy()

			other = threading.Thread(target=staff_end_it)
			other.start()
			other.join(timeout=30)
			self.assertTrue(loyalty.member_of(guest, program))                     # a plain read: the old view
			self.assertFalse(loyalty.member_of(guest, program, lock=True))         # a locking read: as committed now
		finally:
			frappe.db.rollback()
			if guest:
				frappe.db.delete("TEX Loyalty Member", {"guest": guest})
				frappe.db.delete("Guest", {"name": guest})
			if program:
				frappe.db.delete("TEX Loyalty Program", {"name": program})
				for child in ("TEX Loyalty Earn Rule", "TEX Loyalty Tier", "TEX Loyalty Blackout"):
					if frappe.db.table_exists(child):
						frappe.db.delete(child, {"parent": program})
			frappe.db.commit()  # nosemgrep: frappe-manual-commit -- test fixture cleanup across connections
