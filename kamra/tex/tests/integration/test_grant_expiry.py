"""G-94: an expired access grant still granted (found by the G-41 review; ADR-011, ADR-050).

A grant is mirrored into ``tex_managed`` Frappe User Permission rows, re-synced only when the
grant is saved or deleted. ``scope._grants`` dropped an expired grant, but ``scope._scope``
still read its mirrored row, so the hotel stayed in scope without a profile and the user's
Frappe role defaults applied there: a Hotel Admin kept every capability, an agent kept selling.
Grants are now the only authority for TEX-managed rows (live grants decide; manual User
Permissions stay the legacy scope), and a job just after the site's midnight removes the rows
of expired grants and audits it.
"""

import frappe
from frappe.utils import add_days, nowdate

from kamra.tex.api import crs
from kamra.tex.security import grants, perm, scope
from kamra.tex.tests.integration import fixtures as fx
from kamra.tex.tests.integration.test_critical_journey import TexTestCase

OTHER = "TEX Grant Expiry Other Hotel"


def as_user(user: str) -> None:
	frappe.set_user(user)  # nosemgrep: frappe-setuser -- the test acts as each user in turn
	scope.clear_cache()


def mirrored(user: str) -> set[str]:
	return set(frappe.get_all("User Permission", filters={"user": user, "allow": "Property", "tex_managed": 1},
	                          pluck="for_value"))


class ExpiryCase(TexTestCase):
	def setUp(self):
		super().setUp()
		try:
			self.contract = fx.create_contract(self.f, code="G94")["contract"]
			if not frappe.db.exists("Property", OTHER):
				frappe.get_doc({"doctype": "Property", "property_name": OTHER, "city": "Kas", "country": "Turkey",
				                "currency": "EUR", "tex_hotel_group": self.f["group"]}).insert(ignore_permissions=True)
			self.gm = fx.ensure_user("g94-gm@example.com", ["Hotel Admin"])
			self.agent = fx.ensure_user("g94-agent@example.com", ["Call Center Agent"])
			self.gm_grant = self._grant(self.gm, fx.PROPERTY, "Hotel Admin")
			self.agent_grant = self._grant(self.agent, fx.PROPERTY, "Reservations Agent")
			self._grant(self.agent, OTHER, "Reservations Agent", valid_until=add_days(nowdate(), 30))
			for user in (self.gm, self.agent):
				self.assertIn(fx.PROPERTY, mirrored(user))            # the grant was mirrored while live
			# a day passes: both grants at the test hotel ended yesterday; nothing re-synced them
			for g in (self.gm_grant, self.agent_grant):
				frappe.db.set_value("TEX Access Grant", g, "valid_until", add_days(nowdate(), -1))
			scope.clear_cache()
		except Exception:
			self.tearDown()
			raise

	def _grant(self, user: str, prop: str, profile: str, valid_until=None) -> str:
		as_user("Administrator")
		doc = frappe.get_doc({"doctype": "TEX Access Grant", "user": user, "scope_level": "Hotel", "property": prop,
		                      "permission_profile": profile, "valid_until": valid_until or nowdate()})
		doc.insert(ignore_permissions=True)
		return doc.name


class TestExpiredGrantGivesNothing(ExpiryCase):
	def test_no_scope_capability_or_channel_is_left(self):
		for user in (self.gm, self.agent):
			as_user(user)
			self.assertNotIn(fx.PROPERTY, scope.permitted_properties(), user)
			self.assertEqual(scope.capabilities(fx.PROPERTY), frozenset(), user)      # not the role defaults
			self.assertEqual(scope.pricing_channels(fx.PROPERTY), frozenset(), user)
			self.assertEqual(scope.booking_channels(fx.PROPERTY), frozenset(), user)
		as_user(self.agent)                                        # the live grant elsewhere still works
		self.assertEqual(scope.permitted_properties(), {OTHER})
		self.assertIn("reservation.create", scope.capabilities(OTHER))

	def test_tex_endpoints_refuse_the_hotel(self):
		as_user(self.agent)
		with self.assertRaises(frappe.PermissionError):
			crs.search(check_in=str(fx.d(6, 10)), check_out=str(fx.d(6, 13)), rooms=[{"adults": 2}], market="DE",
			           channel="CALL_CENTER", properties=[fx.PROPERTY])
		with self.assertRaises(frappe.PermissionError):
			crs.extras_for(property=fx.PROPERTY)
		self.assertEqual(crs.reservations(), [])
		as_user(self.gm)
		from kamra.tex.api import contracts

		with self.assertRaises(frappe.PermissionError):
			contracts.save_contract(data={"name": self.contract, "contract_name": "taken over"})

	def test_desk_and_rest_reads_are_scoped_away(self):
		as_user(self.gm)
		self.assertEqual(perm.query_conditions(self.gm, "TEX Contract"), "1=0")
		self.assertNotIn(self.contract, frappe.get_list("TEX Contract", pluck="name"))
		self.assertFalse(frappe.has_permission("TEX Contract", "read", doc=self.contract, user=self.gm))
		self.assertNotIn(fx.PROPERTY, frappe.get_list("Property", pluck="name"))

	def test_legacy_endpoints_refuse_the_hotel(self):
		from kamra import assistant, authz
		from kamra import crs as legacy_crs

		frappe.db.set_single_value("TEX Settings", "show_legacy_pms", 1)  # a site that runs the PMS
		as_user(self.gm)
		with self.assertRaises(frappe.PermissionError):
			legacy_crs.assert_property_access(fx.PROPERTY)
		self.assertEqual(authz.property_scope(), [""])
		with self.assertRaises(frappe.PermissionError):
			assistant.assistant_status(property=fx.PROPERTY)

	def test_legacy_mode_does_not_reopen_every_hotel(self):
		# with strict tenancy off, a user TEX never granted anything sees every hotel (legacy mode);
		# a user whose grants ended does not
		frappe.db.set_single_value("TEX Settings", "strict_tenancy", 0)
		as_user(self.gm)
		self.assertEqual(scope.permitted_properties(), set())
		never = fx.ensure_user("g94-never@example.com", ["Hotel Admin"])
		as_user(never)
		self.assertIn(fx.PROPERTY, scope.permitted_properties())

	def test_a_manual_user_permission_is_still_the_legacy_scope(self):
		# a User Permission an administrator made by hand (not mirrored from a grant) still scopes
		# the user, with their Frappe role defaults there, as before
		as_user("Administrator")
		frappe.get_doc({"doctype": "User Permission", "user": self.gm, "allow": "Property",
		                "for_value": OTHER, "apply_to_all_doctypes": 1}).insert(ignore_permissions=True)
		as_user(self.gm)
		self.assertEqual(scope.permitted_properties(), {OTHER})
		self.assertIn("reservation.create", scope.capabilities(OTHER))


class TestExpiredGrantsAreRemoved(ExpiryCase):
	def test_the_midnight_job_removes_mirrored_rows_and_audits(self):
		as_user("Administrator")
		manual = frappe.get_doc({"doctype": "User Permission", "user": self.gm, "allow": "Property",
		                         "for_value": OTHER, "apply_to_all_doctypes": 1}).insert(ignore_permissions=True).name
		mine = [self.gm_grant, self.agent_grant]
		out = grants.remove_expired_grants()
		self.assertTrue({self.gm, self.agent} <= set(out["users"]))
		self.assertTrue(set(mine) <= set(out["grants"]))
		self.assertEqual(mirrored(self.gm), set())
		self.assertEqual(mirrored(self.agent), {OTHER})                             # live grant kept
		self.assertTrue(frappe.db.exists("User Permission", manual))               # manual rows untouched
		events = frappe.get_all("TEX Audit Event", filters={"action": "grant.expired", "reference_name": ("in", mine)},
		                        fields=["reference_name", "property"])
		self.assertEqual(sorted(e.reference_name for e in events), sorted(mine))
		self.assertEqual({e.property for e in events}, {fx.PROPERTY})
		# re-runnable: nothing left to remove, nothing audited twice
		self.assertEqual(grants.remove_expired_grants()["users"], [])
		self.assertEqual(frappe.db.count("TEX Audit Event", {"action": "grant.expired", "reference_name": ("in", mine)}), 2)

	def test_a_user_left_without_rows_is_not_opened_to_every_hotel(self):
		# legacy hotel-bound DocTypes were isolated only by Frappe's User Permission filter, which a
		# user without rows escapes: they now follow the TEX scope too
		as_user("Administrator")
		outlet = fx.ensure("POS Outlet", {"property": fx.PROPERTY, "outlet_name": "G94 Bar"},
		                   {"property": fx.PROPERTY, "outlet_name": "G94 Bar"})
		order = frappe.get_doc({"doctype": "POS Order", "property": fx.PROPERTY, "outlet": outlet}).insert(
			ignore_permissions=True).name
		grants.remove_expired_grants()
		self.assertEqual(mirrored(self.gm), set())
		as_user(self.gm)                               # Hotel Admin role, no grant left, no row left
		for dt, name in (("POS Order", order), ("POS Outlet", outlet)):
			self.assertNotIn(name, frappe.get_list(dt, pluck="name"), dt)
			self.assertFalse(frappe.has_permission(dt, "read", doc=name, user=self.gm), dt)
		as_user("Administrator")
		self.assertIn(order, frappe.get_list("POS Order", pluck="name"))

	def test_the_job_runs_at_the_sites_midnight(self):
		from kamra.tex import scheduler

		self.assertIn("kamra.tex.security.grants.remove_expired_grants", scheduler.SITE_MIDNIGHT)
