"""C-04 (owner, 2026-10-03; ADR-077): a loyalty member is a guest who joined the hotel's program (through staff
now, on the web next) or who stayed and earned points in it (a matured earning); a guest who left is not one,
whatever they earned. Members get the program's members-only prices."""

import frappe
from frappe.utils import now_datetime

from kamra.tex.api import crm as crm_api
from kamra.tex.api import loyalty as loyalty_api
from kamra.tex.crm import loyalty
from kamra.tex.crm import service as crm
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

	def test_c04_an_erased_guest_is_no_member(self):
		name = self.join(self.guest)["name"]
		crm.erase_traces(self.guest, "Erased guest", emails=(), audit_event=False)
		row = frappe.db.get_value("TEX Loyalty Member", name, ["status", "left_reason"], as_dict=True)
		self.assertEqual((row.status, row.left_reason), ("Left", "erased"))
		self.assertFalse(loyalty.is_member(self.guest, fx.PROPERTY))

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
