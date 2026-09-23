"""G-83 security hygiene (R-53, ADR-046). Each test reproduced its defect before the fix.

- a CRM communication links only this guest's records at the caller's hotels;
- an anonymous booker cannot grant marketing consent on an existing profile;
- uploads are checked on the server (magic bytes, size, no public HTML/SVG);
- bearer tokens stay out of URL paths, query strings and Referer headers;
- a PMS webhook is never delivered unsigned;
- a payment provider's API key is a write-only encrypted secret.
"""


import frappe

from kamra.tex.api import crm as crm_api
from kamra.tex.security import scope
from kamra.tex.tests.integration import fixtures as fx
from kamra.tex.tests.integration.test_commercial_flows import (
	GUEST,
	guest_books,
	setup_site_and_payments,
)
from kamra.tex.tests.integration.test_critical_journey import TexTestCase
from kamra.tex.tests.integration.test_security_regressions import OTHER, other_hotel_with_mock


class TestSecurityHygieneG83(TexTestCase):
	def setUp(self):
		super().setUp()
		self.p = setup_site_and_payments(self.f)
		other_hotel_with_mock()
		self.agent = fx.ensure_user("g83-agent@example.com", ["Front Desk"])
		fx.ensure("TEX Access Grant", {"user": self.agent, "property": fx.PROPERTY},
		          {"user": self.agent, "scope_level": "Hotel", "property": fx.PROPERTY,
		           "permission_profile": "Reservations Agent"})
		self.editor = fx.ensure_user("g83-editor@example.com", ["Revenue Manager"])
		fx.ensure("TEX Access Grant", {"user": self.editor, "property": fx.PROPERTY},
		          {"user": self.editor, "scope_level": "Hotel", "property": fx.PROPERTY,
		           "permission_profile": "Revenue Manager"})
		self.outsider = fx.ensure_user("g83-outsider@example.com", ["Hotel Admin"])
		fx.ensure("TEX Access Grant", {"user": self.outsider, "property": OTHER},
		          {"user": self.outsider, "scope_level": "Hotel", "property": OTHER,
		           "permission_profile": "Hotel Admin"})
		scope.clear_cache()

	def as_user(self, user: str):
		frappe.set_user(user)  # nosemgrep: frappe-setuser -- test context switch
		scope.clear_cache()

	# ── 1. CRM communication links ────────────────────────────────────────

	def test_g83_a_communication_links_only_this_guests_records_at_my_hotels(self):
		mine = guest_books(session="g83-comm-a", guest={**GUEST, "email": "g83-comm@example.com"})
		theirs = guest_books(session="g83-comm-b", guest={**GUEST, "email": "g83-someone@example.com"})
		self.as_user("Administrator")
		guest = frappe.db.get_value("TEX Booking", mine["booking"], "booker_guest")
		foreign = frappe.get_doc({"doctype": "TEX Booking", "property": OTHER, "status": "Confirmed",
		                          "booker_guest": guest, "currency": "EUR"}).insert(ignore_permissions=True)
		self.as_user(self.agent)
		ok = crm_api.log_communication(guest=guest, channel="Phone", subject="Call about the transfer",
		                               booking=mine["booking"], reservation=mine["rooms"][0]["reservation"])
		row = frappe.db.get_value("TEX Communication", ok["name"], ["property", "booking", "reservation"],
		                          as_dict=True)
		self.assertEqual((row.property, row.booking), (fx.PROPERTY, mine["booking"]))
		for bad in ({"booking": foreign.name},                                   # another hotel's booking
		            {"booking": theirs["booking"]},                              # another guest's booking
		            {"reservation": theirs["rooms"][0]["reservation"]},          # another guest's stay
		            {"booking": "TEX-NOPE-00001"}, {"reservation": "RES-NOPE"},  # no such record
		            {"booking": theirs["booking"], "reservation": mine["rooms"][0]["reservation"]},
		            {"booking": mine["booking"], "property": OTHER},             # a hotel that is not mine
		            {"direction": "Sideways"}, {"consent_basis": "marketing"}):
			with self.assertRaises((frappe.PermissionError, frappe.ValidationError), msg=str(bad)):
				crm_api.log_communication(guest=guest, channel="Phone", **bad)
		self.as_user(self.outsider)                     # the other hotel's staff do not see this guest at all
		with self.assertRaises(frappe.PermissionError):
			crm_api.log_communication(guest=guest, channel="Phone", booking=foreign.name)
