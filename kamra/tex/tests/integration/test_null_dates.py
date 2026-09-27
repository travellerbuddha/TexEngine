"""NEW-1 (audit Part 2A, ADR-064): a scheduled job never reads a missing date as a past one.

``frappe.get_all`` compares a nullable Date/Datetime as ``IFNULL(field, '0001-01-01')`` for ``<``
and ``<=``, so a row without the date looked "long past" to four jobs:

* the contract roll (every 15 min) superseded every published version without an end: the live
  one and every scheduled one. Withdraw and resume were then refused, the "current" lists were
  empty, and a publish never withdrew a scheduled version it replaced, which went back on sale at
  its start (``SELLABLE_HISTORY``);
* the loyalty job (daily) expired earnings that never expire;
* the grant job (daily) audited a grant without an end date as ``grant.expired`` every night;
* the payment-link job (every 5 min) expired a link without an expiry time.
"""

import frappe
from frappe.utils import add_days, add_to_date, get_datetime, now_datetime, nowdate

from kamra.tex.api import lists
from kamra.tex.commercial import contracts
from kamra.tex.crm import loyalty
from kamra.tex.payments import service as pay
from kamra.tex.security import grants, scope
from kamra.tex.services import booking, quoting
from kamra.tex.tests.integration import fixtures as fx
from kamra.tex.tests.integration.test_critical_journey import TexTestCase, pick, search_std

CLUB = {"doctype": "TEX Loyalty Program", "program_name": "NEW-1 Club", "property": fx.PROPERTY, "enabled": 1,
        "currency": "EUR", "point_value": 0.1, "min_redeem_points": 50, "max_redeem_percent": 50,
        "pending_days": 0, "earn_rules": [{"basis": "STAY", "rate": 25}]}


def status(version: str) -> str:
	return frappe.db.get_value("TEX Contract Version", version, "status")


def schedule(contract: str, at) -> str:
	"""A new version of ``contract`` published to start at ``at``."""
	version = contracts.new_draft(contract)
	contracts.publish(version, effective_from=at)
	return version


def window(version: str) -> tuple:
	row = frappe.db.get_value("TEX Contract Version", version, ["effective_from", "active_to"], as_dict=True)
	return (get_datetime(row.effective_from) if row.effective_from else None,
	        get_datetime(row.active_to) if row.active_to else None)


class TestContractRoll(TexTestCase):
	def schedule(self, contract: str, at) -> str:
		return schedule(contract, at)

	def test_a_live_version_without_an_end_and_a_scheduled_one_stay_published(self):
		c = fx.create_contract(self.f, code="NEW1-ROLL")
		v1 = c["version"]
		self.assertIsNone(frappe.db.get_value("TEX Contract Version", v1, "active_to"))
		contracts.roll_version_statuses()
		self.assertEqual(status(v1), "Published")                            # live, no end
		v2 = self.schedule(c["contract"], add_to_date(now_datetime(), days=30))
		self.assertIsNone(frappe.db.get_value("TEX Contract Version", v2, "active_to"))
		contracts.roll_version_statuses()
		self.assertEqual((status(v1), status(v2)), ("Published", "Published"))
		self.assertEqual(frappe.db.get_value("TEX Contract", c["contract"], "active_version"), v1)
		# the "current" list still has them (the entry-branding case of b0522d92)
		rows = {r["name"] for r in lists.versions(property=fx.PROPERTY, status="Published")["rows"]}
		self.assertTrue({v1, v2} <= rows)
		# and the live one can still be withdrawn
		contracts.withdraw(v1, reason="wrong price")
		self.assertEqual(status(v1), "Withdrawn")

	def test_a_version_published_before_a_scheduled_one_withdraws_it(self):
		c = fx.create_contract(self.f, code="NEW1-FIX")
		t2 = add_to_date(now_datetime(), days=30)
		v2 = self.schedule(c["contract"], t2)
		contracts.roll_version_statuses()                                    # the job ran in between
		v3 = self.schedule(c["contract"], add_to_date(now_datetime(), days=10))  # corrects V2 before its start
		self.assertEqual(status(v2), "Withdrawn")
		self.assertEqual(contracts.active_version_header(c["contract"], t2).version_id, v3)



class TestVersionLifecycle(TexTestCase):
	"""Y-2 + O-13 (2D-1, ADR-069): withdrawing a version that has not started gives the version before
	it back the window it was to take over (it never shortens another); withdrawing the version on sale
	still stops it now. A withdrawn version's open quotes are expired: none is booked."""

	def test_a_withdrawn_scheduled_version_leaves_the_one_before_on_sale(self):
		c = fx.create_contract(self.f, code="Y2-A")
		v1, t2 = c["version"], add_to_date(now_datetime(), days=1)
		v2 = schedule(c["contract"], t2)
		self.assertEqual(window(v1)[1], window(v2)[0])                        # V1 was to end at V2's start
		from kamra.tex.api import contracts as api

		shown = {v.name: v.scheduled for v in api.get_contract(c["contract"])["versions"]}
		self.assertEqual((shown[v1], shown[v2]), (False, True))              # the dialog says what withdraw does
		contracts.withdraw(v2, reason="wrong prices")
		self.assertEqual(status(v2), "Withdrawn")
		self.assertEqual(window(v2), (window(v2)[0], window(v2)[0]))          # a cancelled schedule
		self.assertIsNone(window(v1)[1])
		later = add_to_date(now_datetime(), days=2)
		self.assertEqual(contracts.active_version_header(c["contract"], later).version_id, v1)
		with self.freeze_time(later):
			contracts.roll_version_statuses()
		self.assertEqual(status(v1), "Published")
		self.assertEqual(frappe.db.get_value("TEX Contract", c["contract"], "active_version"), v1)

	def test_the_version_before_takes_the_withdrawn_ones_window_to_the_next(self):
		c = fx.create_contract(self.f, code="Y2-B")
		v1 = c["version"]
		v2 = schedule(c["contract"], add_to_date(now_datetime(), days=1))
		v3 = schedule(c["contract"], add_to_date(now_datetime(), days=5))
		contracts.withdraw(v2, reason="wrong prices")
		self.assertEqual(window(v1)[1], window(v3)[0])                        # V1 hands over to V3 at T3
		self.assertIsNone(window(v3)[1])
		d = fx.create_contract(self.f, code="Y2-B2")
		w2 = schedule(d["contract"], add_to_date(now_datetime(), days=1))
		w3 = schedule(d["contract"], add_to_date(now_datetime(), days=5))
		contracts.withdraw(w3, reason="not needed")
		self.assertIsNone(window(w2)[1])                                      # V2 stays open-ended
		self.assertEqual(window(d["version"])[1], window(w2)[0])              # V1 still ends at T2

	def test_withdrawing_the_version_on_sale_still_stops_it_now(self):
		c = fx.create_contract(self.f, code="Y2-C")
		v1 = c["version"]
		# None: "now" as publish reads it, never a time taken before new_draft ran (a second may pass)
		v2 = schedule(c["contract"], None)
		self.assertEqual(status(v1), "Superseded")
		contracts.withdraw(v2, reason="wrong prices")
		self.assertEqual(status(v2), "Withdrawn")
		self.assertEqual(status(v1), "Superseded")                            # an older version never comes back
		self.assertIsNone(contracts.active_version_header(c["contract"], add_to_date(now_datetime(), seconds=1)))
		self.assertIsNone(frappe.db.get_value("TEX Contract", c["contract"], "active_version"))

	def test_a_withdrawn_versions_quote_is_not_booked(self):
		c = fx.create_contract(self.f, code="Y2-D")
		offer = pick(search_std(fx.d(6, 10), fx.d(6, 13), [{"adults": 2}]))
		q = quoting.create_quote(offer["rooms"][0]["offer_key"])
		self.assertTrue(q["ok"], q)
		contracts.withdraw(c["version"], reason="wrong prices")
		with self.assertRaisesRegex(frappe.ValidationError, "no longer on sale"):
			booking.create_booking(quote_ids=[q["quote_id"]], guest={"first_name": "Ada", "last_name": "Y2",
			                                                         "email": "ada.y2@example.com"},
			                       payment_method="Pay at Hotel")
		self.assertEqual(frappe.db.get_value("TEX Quote", q["quote_id"], "status"), "Expired")


class TestOpenEndedRows(TexTestCase):
	def test_points_without_an_expiry_never_expire(self):
		club = frappe.get_doc(CLUB).insert(ignore_permissions=True).name
		guest = frappe.get_doc({"doctype": "Guest", "first_name": "Open", "last_name": "Ended",
		                        "email": "new1-points@example.com"}).insert(ignore_permissions=True).name
		frappe.get_doc({"doctype": "TEX Loyalty Ledger", "program": club, "guest": guest, "entry_type": "Earn",
		                "points": 100, "status": "Available", "property": fx.PROPERTY,
		                "reason": "no expiry"}).insert(ignore_permissions=True)
		out = loyalty.mature_and_expire()
		self.assertEqual(out["expired_points"], 0)
		self.assertEqual(loyalty.balances(guest, club)["available"], 100)
		self.assertFalse(frappe.db.exists("TEX Loyalty Ledger", {"guest": guest, "entry_type": "Expire"}))

	def test_a_grant_without_an_end_date_is_not_expired(self):
		user = fx.ensure_user("new1-open-grant@example.com", ["Call Center Agent"])
		grant = frappe.get_doc({"doctype": "TEX Access Grant", "user": user, "scope_level": "Hotel",
		                        "property": fx.PROPERTY, "permission_profile": "Reservations Agent"}
		                       ).insert(ignore_permissions=True).name
		self.assertIsNone(frappe.db.get_value("TEX Access Grant", grant, "valid_until"))
		out = grants.remove_expired_grants()
		self.assertNotIn(grant, out["grants"])
		self.assertFalse(frappe.db.exists("TEX Audit Event", {"action": "grant.expired", "reference_name": grant}))
		self.assertTrue(frappe.db.exists("User Permission", {"user": user, "allow": "Property",
		                                                     "for_value": fx.PROPERTY, "tex_managed": 1}))
		scope.clear_cache()
		# a grant that ended yesterday still is
		frappe.db.set_value("TEX Access Grant", grant, "valid_until", add_days(nowdate(), -1))
		self.assertIn(grant, grants.remove_expired_grants()["grants"])

	def test_a_payment_link_without_an_expiry_is_not_expired(self):
		from kamra.tex.tests.integration.test_commercial_flows import setup_site_and_payments

		p = setup_site_and_payments(self.f)
		link = pay.create_link(property=fx.PROPERTY, amount="50", currency="EUR", description="NEW-1",
		                       provider_account=p["account"], guest_name="Open Link")["link"]
		frappe.db.set_value("TEX Payment Link", link, "expires_at", None)
		pay.expire_links()
		self.assertEqual(frappe.db.get_value("TEX Payment Link", link, "status"), "Active")
		# one past its expiry still expires
		frappe.db.set_value("TEX Payment Link", link, "expires_at", add_days(now_datetime(), -1))
		self.assertEqual(pay.expire_links(), 1)
		self.assertEqual(frappe.db.get_value("TEX Payment Link", link, "status"), "Expired")
