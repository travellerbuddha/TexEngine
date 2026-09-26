"""Loyalty administration (G-24, R-39): programs are managed in TEX with every rule
validated, by the hotels they belong to only; earnings are never rewritten by a rule
change; redemption honours its cap and blackouts; a guest's summary shows the viewer's
programs only."""

from unittest import mock

import frappe
from frappe.utils import add_days

from kamra.tex.api import crm as crm_api
from kamra.tex.api import loyalty as loyalty_api
from kamra.tex.api import public
from kamra.tex.crm import loyalty
from kamra.tex.money import D
from kamra.tex.security import scope
from kamra.tex.tests.integration import fixtures as fx
from kamra.tex.tests.integration.test_commercial_flows import guest_books, setup_site_and_payments
from kamra.tex.tests.integration.test_critical_journey import TexTestCase
from kamra.tex.tests.integration.test_crm_segments import OTHER, agent, other_tenant

CLUB = {"program_name": "Resort Club", "enabled": 1, "currency": "EUR", "point_value": "0.1",
        "min_redeem_points": 50, "max_redeem_percent": "50", "pending_days": 0, "expiry_months": 24,
        "earn_rules": [{"basis": "MONEY", "rate": "1"}, {"basis": "STAY", "rate": "25"}],
        "tiers": [{"tier_name": "Silver", "min_points": 0, "earn_multiplier": "1"}], "blackouts": []}


class LoyaltyCase(TexTestCase):
	def setUp(self):
		super().setUp()
		setup_site_and_payments(self.f)
		other_tenant()
		self.rm = agent("g24-rm@example.com", fx.PROPERTY, "Revenue Manager")
		self.desk = agent("g24-desk@example.com", fx.PROPERTY)                  # crm.edit, no loyalty.edit
		self.there = agent("g24-there@example.com", OTHER, "Hotel Admin")
		frappe.set_user("Administrator")  # nosemgrep: frappe-setuser -- fixtures

	def create(self, **kw) -> str:
		frappe.set_user(self.rm)  # nosemgrep: frappe-setuser -- the revenue manager creates the club
		name = loyalty_api.save_program({**CLUB, "property": fx.PROPERTY, **kw})["name"]
		frappe.set_user("Administrator")  # nosemgrep: frappe-setuser -- back
		return name

	def paid_stay(self, session: str) -> tuple[dict, str]:
		b = guest_books(session=session)
		p = b["payment"]
		public.mock_pay(transaction=p["transaction"], outcome="success", sig=p["fields"]["success_sig"])
		frappe.set_user("Administrator")  # nosemgrep: frappe-setuser -- staff
		return b, frappe.db.get_value("TEX Booking", b["booking"], "booker_guest")


class TestProgramRules(LoyaltyCase):
	def test_every_rule_is_checked(self):
		name = self.create()
		frappe.set_user(self.rm)  # nosemgrep: frappe-setuser -- bad edits are refused
		room_elsewhere = frappe.db.get_value("Room Type", {"property": ("!=", fx.PROPERTY)})
		for bad in ({"property": None, "hotel_group": None}, {"point_value": "-1"}, {"max_redeem_percent": "120"},
		            {"currency": None}, {"earn_rules": [{"basis": "NIGHTS", "rate": "0"}]},
		            {"earn_rules": [{"basis": "ROOM", "rate": "5", "room_type": room_elsewhere}]},
		            {"earn_rules": [{"basis": "EXTRA", "rate": "5"}]},
		            {"tiers": [{"tier_name": "Gold", "min_points": 0}, {"tier_name": "gold", "min_points": 10}]},
		            {"tiers": [{"tier_name": "A", "min_points": 0}, {"tier_name": "B", "min_points": 0}]},
		            {"blackouts": [{"date_from": "2027-08-10", "date_to": "2027-08-01"}]}):
			with self.assertRaises(frappe.ValidationError, msg=str(bad)):
				loyalty_api.save_program({**CLUB, "name": name, "property": fx.PROPERTY, **bad})
		with self.assertRaises(frappe.ValidationError):                    # one enabled club per hotel
			loyalty_api.save_program({**CLUB, "property": fx.PROPERTY, "program_name": "Second club"})
		self.assertTrue(loyalty_api.save_program({**CLUB, "property": fx.PROPERTY, "program_name": "Second club",
		                                          "enabled": 0})["name"])

	def test_only_the_hotels_loyalty_editors_manage_it(self):
		name = self.create()
		self.assertTrue(frappe.db.exists("TEX Audit Event", {"action": "loyalty.program_save", "reference_name": name}))
		frappe.set_user(self.desk)  # nosemgrep: frappe-setuser -- an agent sees it but cannot change it
		self.assertEqual(loyalty_api.program(name)["can_edit"], False)
		for call in (lambda: loyalty_api.save_program({**CLUB, "name": name, "property": fx.PROPERTY}),
		             lambda: loyalty_api.set_enabled(name, 0), lambda: loyalty_api.delete_program(name)):
			with self.assertRaises(frappe.PermissionError):
				call()
		frappe.set_user(self.there)  # nosemgrep: frappe-setuser -- another tenant's admin
		self.assertNotIn(name, {p["name"] for p in loyalty_api.programs()["programs"]})
		for call in (lambda: loyalty_api.program(name), lambda: loyalty_api.ledger(name),
		             lambda: loyalty_api.set_enabled(name, 0),
		             lambda: loyalty_api.save_program({**CLUB, "property": fx.PROPERTY, "program_name": "Mine"})):
			with self.assertRaises((frappe.DoesNotExistError, frappe.PermissionError)):
				call()
		frappe.set_user(self.rm)  # nosemgrep: frappe-setuser -- its editor deletes it (no members yet)
		loyalty_api.delete_program(name)
		self.assertFalse(frappe.db.exists("TEX Loyalty Program", name))
		self.assertTrue(frappe.db.exists("TEX Audit Event", {"action": "loyalty.program_delete",
		                                                     "reference_name": name}))

	def test_a_program_with_points_neither_moves_nor_disappears(self):
		name = self.create()
		_b, guest = self.paid_stay("g24-keep")
		self.assertGreater(loyalty.balances(guest, name)["pending"], 0)
		frappe.set_user(self.rm)  # nosemgrep: frappe-setuser -- tries to delete it
		with self.assertRaises(frappe.ValidationError):
			loyalty_api.delete_program(name)
		frappe.set_user("Administrator")  # nosemgrep: frappe-setuser -- even the platform cannot move it
		doc = frappe.get_doc("TEX Loyalty Program", name)
		doc.property = OTHER
		with self.assertRaises(frappe.ValidationError):
			doc.save(ignore_permissions=True)
		stats = loyalty_api.programs()["programs"]
		club = next(p for p in stats if p["name"] == name)
		self.assertEqual((club["members"], club["pending_points"]), (1, loyalty.balances(guest, name)["pending"]))


class TestEarningsAndRedemption(LoyaltyCase):
	def test_a_rule_change_never_rewrites_an_earning(self):
		name = self.create()
		b, guest = self.paid_stay("g24-freeze")
		first = loyalty.balances(guest, name)["pending"]
		entry = frappe.get_all("TEX Loyalty Ledger", filters={"guest": guest, "program": name, "entry_type": "Earn"},
		                       fields=["name", "stay_fingerprint", "explanation"])
		self.assertEqual(len(entry), 1)
		self.assertTrue(entry[0].stay_fingerprint and "MONEY" in entry[0].explanation)
		frappe.set_user(self.rm)  # nosemgrep: frappe-setuser -- the club doubles its rate
		loyalty_api.save_program({**CLUB, "name": name, "property": fx.PROPERTY,
		                          "earn_rules": [{"basis": "MONEY", "rate": "2"}]})
		frappe.set_user("Administrator")  # nosemgrep: frappe-setuser -- an unrelated save of the stay
		res = frappe.get_doc("Reservation", b["rooms"][0]["reservation"])
		res.special_requests = "late arrival"
		res.save(ignore_permissions=True)
		self.assertEqual(loyalty.balances(guest, name)["pending"], first)
		res.reload()                                                     # the stay itself changes: earns again
		frappe.db.set_value("Reservation", res.name, "tex_total_amount", D(res.tex_total_amount) + 100)
		res.reload()
		res.save(ignore_permissions=True)
		self.assertNotEqual(loyalty.balances(guest, name)["pending"], first)

	def test_redemption_honours_its_cap_and_blackouts(self):
		name = self.create(pending_days=0)
		b, guest = self.paid_stay("g24-burn")
		loyalty.mature_and_expire(today=fx.d(6, 13))
		night = str(fx.d(6, 11))
		frappe.set_user(self.rm)  # nosemgrep: frappe-setuser -- an earning blackout does not block redemption
		loyalty_api.save_program({**CLUB, "name": name, "property": fx.PROPERTY,
		                          "blackouts": [{"date_from": night, "date_to": night, "applies_to": "Earning"}]})
		frappe.set_user("Administrator")  # nosemgrep: frappe-setuser -- staff redeem
		self.assertEqual(loyalty.redeem(guest, b["booking"], 50, idempotency_key="g24-1")["value"], "5.00")
		frappe.set_user(self.rm)  # nosemgrep: frappe-setuser -- a redemption blackout on a night of the stay
		loyalty_api.save_program({**CLUB, "name": name, "property": fx.PROPERTY,
		                          "blackouts": [{"date_from": night, "date_to": night, "applies_to": "Redemption"}]})
		frappe.set_user("Administrator")  # nosemgrep: frappe-setuser -- staff redeem
		with self.assertRaisesRegex(frappe.ValidationError, "cannot be redeemed for stays"):
			loyalty.redeem(guest, b["booking"], 50, idempotency_key="g24-2")
		frappe.set_user(self.rm)  # nosemgrep: frappe-setuser -- 0 % means no redemption, not 100 %
		loyalty_api.save_program({**CLUB, "name": name, "property": fx.PROPERTY, "max_redeem_percent": "0"})
		frappe.set_user("Administrator")  # nosemgrep: frappe-setuser -- staff redeem
		with self.assertRaisesRegex(frappe.ValidationError, "cannot be redeemed in this program"):
			loyalty.redeem(guest, b["booking"], 50, idempotency_key="g24-3")

	def test_a_guests_summary_shows_the_viewers_programs_only(self):
		name = self.create()
		_b, guest = self.paid_stay("g24-sum")
		frappe.set_user("Administrator")  # nosemgrep: frappe-setuser -- another tenant's club gave points too
		theirs = frappe.get_doc({"doctype": "TEX Loyalty Program", "program_name": "Other club", "property": OTHER,
		                         "enabled": 1, "currency": "EUR", "point_value": 0.1}).insert(ignore_permissions=True)
		frappe.get_doc({"doctype": "TEX Loyalty Ledger", "program": theirs.name, "guest": guest, "entry_type": "Adjust",
		                "points": 999, "status": "Available", "reason": "welcome"}).insert(ignore_permissions=True)
		frappe.set_user(self.desk)  # nosemgrep: frappe-setuser -- this tenant's agent
		self.assertEqual([s["program"] for s in crm_api.loyalty_summary(guest)], [name])


class TestLoyaltyMigration(LoyaltyCase):
	def setUp(self):
		super().setUp()
		# the schema is migrated already: DDL here would commit this test's rows (see p12's test)
		self.enterContext(mock.patch.object(frappe, "reload_doc"))

	def test_old_meanings_are_kept(self):
		from kamra.patches.tex import p17_loyalty_admin

		name = self.create()
		b, guest = self.paid_stay("g24-mig")
		earn = frappe.db.get_value("TEX Loyalty Ledger", {"guest": guest, "entry_type": "Earn"})
		frappe.db.set_value("TEX Loyalty Ledger", earn, "stay_fingerprint", None)
		frappe.db.set_value("TEX Loyalty Program", name, "max_redeem_percent", 0)
		prog = frappe.get_doc("TEX Loyalty Program", name)
		prog.append("blackouts", {"date_from": add_days(fx.d(6, 1), 0), "date_to": fx.d(6, 2)})
		prog.save(ignore_permissions=True)
		frappe.db.sql("UPDATE `tabTEX Loyalty Blackout` SET applies_to=NULL WHERE parent=%s", name)
		# the site as before the upgrade: the 0 → 100 conversion is the first run's only (G-76)
		frappe.db.delete("Patch Log", {"patch": "kamra.patches.tex.p17_loyalty_admin"})
		p17_loyalty_admin.execute()
		self.assertEqual(D(frappe.db.get_value("TEX Loyalty Program", name, "max_redeem_percent")), D(100))
		self.assertEqual(frappe.db.get_value("TEX Loyalty Blackout", {"parent": name}, "applies_to"), "Both")
		res = frappe.get_doc("Reservation", b["rooms"][0]["reservation"])
		self.assertEqual(frappe.db.get_value("TEX Loyalty Ledger", earn, "stay_fingerprint"),
		                 loyalty.stay_fingerprint(res))
		self.assertTrue(frappe.db.exists("TEX Profile Capability", {"parent": "Revenue Manager",
		                                                            "capability": "loyalty.edit"}))
		scope.clear_cache()


class TestExtraEarning(LoyaltyCase):
	"""Y-10 (audit Part 2A): a program earning per unit of an extra. The price snapshot stores a
	quantity as "2.000000" (``to_str6``); ``int("2.000000")`` raised in the reservation's update hook,
	so the confirmation (here: the payment's) was rolled back and the paid booking later expired."""

	def test_points_per_extra_unit_confirm_the_booking(self):
		spa = fx.ensure_live("TEX Extra", {"property": fx.PROPERTY, "extra_code": "SPA"},
		                     {"property": fx.PROPERTY, "extra_code": "SPA", "extra_name": "Spa treatment",
		                      "category": "Spa", "pricing_mode": "UNIT", "currency": "EUR", "amount": 50,
		                      "tax_category": "SERVICE"})
		club = self.create(earn_rules=[{"basis": "EXTRA", "rate": "5", "extra": spa}])
		b = guest_books(session="y10-spa", extras=[{"code": "SPA", "quantity": 2}])
		p = b["payment"]
		public.mock_pay(transaction=p["transaction"], outcome="success", sig=p["fields"]["success_sig"])
		frappe.set_user("Administrator")  # nosemgrep: frappe-setuser -- staff
		res = b["rooms"][0]["reservation"]
		self.assertEqual(frappe.db.get_value("Reservation", res, "status"), "Confirmed")
		guest = frappe.db.get_value("TEX Booking", b["booking"], "booker_guest")
		earned = frappe.get_all("TEX Loyalty Ledger", filters={"reservation": res, "entry_type": "Earn"},
		                        fields=["points", "status", "program"])
		self.assertEqual([(e.points, e.status, e.program) for e in earned], [(10, "Pending", club)])
		self.assertEqual(loyalty.balances(guest, club)["pending"], 10)

	def test_a_quantity_that_is_not_whole_earns_nothing_and_says_so(self):
		prog = frappe._dict(currency="EUR", blackouts=[], earn_rules=[frappe._dict(
			basis="EXTRA", rate="5", extra=None, date_from=None, date_to=None)])
		res = frappe._dict(check_in_date=fx.d(6, 10), check_out_date=fx.d(6, 13), tex_currency="EUR",
		                   tex_total_amount=100, tex_pricing_snapshot=frappe.as_json(
			                   {"extras": [{"code": None, "quantity": "1.500000", "ok": True}]}))
		points, lines = loyalty.points_for(prog, res, 1)
		self.assertEqual(points, 0)
		self.assertIn("not a whole number", lines[0]["note"])
