"""Loyalty administration (G-24, R-39): programs are managed in TEX with every rule
validated, by the hotels they belong to only; earnings are never rewritten by a rule
change; redemption honours its cap and blackouts; a guest's summary shows the viewer's
programs only."""

import threading
import time
from types import MappingProxyType
from unittest import mock

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import add_days, add_months, add_to_date, now_datetime, nowdate

from kamra.tex.api import crm as crm_api
from kamra.tex.api import loyalty as loyalty_api
from kamra.tex.api import public
from kamra.tex.crm import loyalty
from kamra.tex.money import D, from_db
from kamra.tex.payments import service as pay
from kamra.tex.security import scope
from kamra.tex.services import booking as booking_svc
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

	def test_points_pay_at_most_the_programs_share_and_what_the_booking_owes(self):
		"""O-19 (audit 2B, ADR-065): points pay at most the program's share of a booking, the points already
		on it counted, and never more than it still owes: a second 50 % is refused, and so is any on a booking
		paid in full. The refusal says the most it may still take, in money and points."""
		name = self.create(pending_days=0)                                # 50 %, a point is 0.10
		at_hotel = guest_books(session="o19-hotel", method="Pay at Hotel")      # 842.50, nothing paid yet
		frappe.set_user("Administrator")  # nosemgrep: frappe-setuser -- staff redeem
		guest = frappe.db.get_value("TEX Booking", at_hotel["booking"], "booker_guest")
		frappe.get_doc({"doctype": "TEX Loyalty Ledger", "program": name, "guest": guest, "entry_type": "Adjust",
		                "points": 20000, "status": "Available", "reason": "welcome"}).insert(ignore_permissions=True)
		self.assertEqual(loyalty.redeem(guest, at_hotel["booking"], 4212, idempotency_key="o19-1")["value"], "421.20")
		with self.assertRaisesRegex(frappe.ValidationError, r"at most 0\.05 EUR .*\(0 points\)"):
			loyalty.redeem(guest, at_hotel["booking"], 50, idempotency_key="o19-2")
		full, _guest = self.paid_stay("o19-full")                          # the deposit, then the rest
		frappe.set_user("Guest")  # nosemgrep: frappe-setuser -- the guest pays the rest online
		rest = public.pay_booking(token=full["manage_token"])
		public.mock_pay(transaction=rest["transaction"], outcome="success", sig=rest["fields"]["success_sig"])
		frappe.set_user("Administrator")  # nosemgrep: frappe-setuser -- staff redeem
		with self.assertRaisesRegex(frappe.ValidationError, r"at most 0\.00 EUR"):
			loyalty.redeem(guest, full["booking"], 50, idempotency_key="o19-3")

	def test_the_points_on_a_booking_are_read_by_its_indexes(self):
		"""O-19 review: the locking reads of the points already on a booking go by an index (its booking, or
		the charges' names), so their shared locks hold this booking's rows only, never every payment of every
		hotel until the redemption commits."""
		for sql, values in ((loyalty.LOYALTY_ON_BOOKING, {"b": "BK-O19"}), (loyalty.ALLOCATED_TO_BOOKING, {"b": "BK-O19"}),
		                    (loyalty.LOYALTY_NAMED, {"names": ("TXN-O19-1", "TXN-O19-2")})):
			for row in frappe.db.sql("EXPLAIN " + sql, values, as_dict=True):
				self.assertNotIn(row.type, ("ALL", "index"), (sql, row))
				self.assertTrue(row.key, (sql, row))

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


class TestExpiry(LoyaltyCase):
	"""Y-11 and O-22 (audit Part 2H-1, ADR-071): points are used first-to-expire first, and an expiry takes
	only what is left of its lot. The job used to take ``min(lot, balance)`` whenever it ran: a spent lot
	took a later lot's points, or the points of a lot that expires years later."""

	def setUp(self):
		super().setUp()
		self.club = self.create()
		self.guest = frappe.get_doc({"doctype": "Guest", "first_name": "Lots", "last_name": "Test",
		                             "email": "h1-lots@example.com"}).insert(ignore_permissions=True).name

	def row(self, entry_type, points, status="Available", expires_on=None, available_on=None, reason="h1") -> str:
		return frappe.get_doc({"doctype": "TEX Loyalty Ledger", "program": self.club, "guest": self.guest,
		                       "entry_type": entry_type, "points": points, "status": status, "property": fx.PROPERTY,
		                       "expires_on": expires_on, "available_on": available_on, "reason": reason}
		                      ).insert(ignore_permissions=True).name

	def available(self) -> int:
		return loyalty.balances(self.guest, self.club)["available"]

	def expire_rows(self) -> list[int]:
		return frappe.get_all("TEX Loyalty Ledger", filters={"guest": self.guest, "entry_type": "Expire"},
		                      pluck="points", order_by="creation asc, name asc")

	def test_y11_a_lot_spent_in_full_takes_nothing_from_a_later_lot(self):
		past, later = add_days(nowdate(), -30), add_days(nowdate(), 400)
		a = self.row("Earn", 100, expires_on=past, available_on=add_days(nowdate(), -60))
		self.row("Burn", -100, "Used")
		loyalty.mature_and_expire()                                       # A is spent: nothing to take
		self.row("Earn", 80, "Pending", expires_on=later, available_on=add_days(nowdate(), -1))
		loyalty.mature_and_expire()                                       # B matures
		self.assertEqual(self.available(), 80)
		self.assertEqual(self.expire_rows(), [])
		self.assertEqual(frappe.db.get_value("TEX Loyalty Ledger", a, "status"), "Expired")

	def test_o22_spent_points_come_from_the_lot_that_expires_first(self):
		self.row("Earn", 100, expires_on=add_days(nowdate(), -30), available_on=add_days(nowdate(), -60))
		self.row("Earn", 100, expires_on=add_days(nowdate(), 400), available_on=add_days(nowdate(), -50))
		self.row("Burn", -100, "Used")
		loyalty.mature_and_expire()
		self.assertEqual(self.available(), 100)
		self.assertEqual(self.expire_rows(), [])

	def test_a_partly_spent_lot_expires_what_is_left_and_only_once(self):
		a = self.row("Earn", 100, expires_on=add_days(nowdate(), -30), available_on=add_days(nowdate(), -60))
		self.row("Earn", 100, expires_on=add_days(nowdate(), 400), available_on=add_days(nowdate(), -50))
		self.row("Burn", -60, "Used")
		out = loyalty.mature_and_expire()
		self.assertEqual((self.available(), self.expire_rows(), out["expired_points"]), (100, [-40], 40))
		self.assertEqual(frappe.db.get_value("TEX Loyalty Ledger", a, "status"), "Expired")
		self.assertEqual(frappe.db.get_value("Guest", self.guest, "tex_loyalty_points"), 100)
		again = loyalty.mature_and_expire()                               # a closed lot is not looked at again
		self.assertEqual((self.available(), self.expire_rows(), again["expired_points"]), (100, [-40], 0))

	def test_points_past_their_expiry_cannot_be_spent_before_the_daily_job_runs(self):
		at_hotel = guest_books(session="h1-expired", method="Pay at Hotel")
		frappe.set_user("Administrator")  # nosemgrep: frappe-setuser -- staff redeem
		self.guest = frappe.db.get_value("TEX Booking", at_hotel["booking"], "booker_guest")
		self.row("Earn", 100, expires_on=add_days(nowdate(), -1), available_on=add_days(nowdate(), -60))
		self.row("Earn", 20, expires_on=add_days(nowdate(), 400), available_on=add_days(nowdate(), -50))
		with self.assertRaisesRegex(frappe.ValidationError, "Not enough points"):
			loyalty.redeem(self.guest, at_hotel["booking"], 50, idempotency_key="h1-exp-1")
		self.assertEqual((self.available(), self.expire_rows()), (20, [-100]))

	def test_a_negative_adjustment_cannot_take_points_that_expired(self):
		self.row("Earn", 100, expires_on=add_days(nowdate(), -1), available_on=add_days(nowdate(), -60))
		self.row("Earn", 20, expires_on=add_days(nowdate(), 400), available_on=add_days(nowdate(), -50))
		frappe.set_user(self.desk)  # nosemgrep: frappe-setuser -- an agent with crm.edit
		with self.assertRaisesRegex(frappe.ValidationError, "cannot go negative"):
			loyalty.adjust(self.guest, self.club, -50, "correction", property=fx.PROPERTY)
		frappe.set_user("Administrator")  # nosemgrep: frappe-setuser -- back
		self.assertEqual((self.available(), self.expire_rows()), (20, [-100]))

	def test_a_guest_whose_transaction_was_lost_is_logged_and_the_job_goes_on(self):
		"""Part 2H-2 item 0: the victim of a deadlock has no savepoint left, rolling back to it fails (MariaDB
		1305): the job rolls back whole (as the payments job does, 2E-2), logs it and settles the next guest."""
		other = frappe.get_doc({"doctype": "Guest", "first_name": "Lots", "last_name": "Other",
		                        "email": "h2-lots-other@example.com"}).insert(ignore_permissions=True).name
		past = add_days(nowdate(), -30)
		self.row("Earn", 100, expires_on=past, available_on=add_days(nowdate(), -60))
		mine, self.guest = self.guest, other
		self.row("Earn", 100, expires_on=past, available_on=add_days(nowdate(), -60))
		first, second = sorted((mine, other))
		real_settle, real_rollback, wholly = loyalty.settle, frappe.db.rollback, []
		frappe.db.savepoint("h2")

		def settle(guest, program, today=None):
			if guest == first:
				raise frappe.QueryDeadlockError("Deadlock found when trying to get lock")
			return real_settle(guest, program, today)

		def rollback(*args, **kw):                    # the test's own transaction stands for the job's
			if kw.get("save_point") and kw["save_point"] != "h2":
				raise frappe.db.OperationalError(1305, f"SAVEPOINT {kw['save_point']} does not exist")
			wholly.append(1)
			return real_rollback(save_point="h2")

		with mock.patch.object(loyalty, "settle", side_effect=settle), \
				mock.patch.object(frappe.db, "rollback", side_effect=rollback), \
				mock.patch.object(frappe, "log_error") as log:
			out = loyalty.mature_and_expire()
		self.assertEqual(wholly, [1])
		self.assertEqual(log.call_count, 1)
		self.assertIn(first, log.call_args.kwargs["title"])
		self.assertEqual(out["expired_points"], 100)
		rows = {g: frappe.get_all("TEX Loyalty Ledger", filters={"guest": g, "entry_type": "Expire"}, pluck="points")
		        for g in (first, second)}
		self.assertEqual(rows, {first: [], second: [-100]})


class TestExpiryLockOrder(IntegrationTestCase):
	"""Part 2H-2 item 0 (ADR-071, ADR-066): the daily job locked the Pending rows it matured (an UPDATE, no
	commit) and only then, in ``settle``, the guest: the reverse of the order everywhere else (the guest, then
	its ledger rows). Against an adjustment or a redemption of the same guest it deadlocked. Two connections:
	the committed fixtures are removed again in tearDownClass."""

	@classmethod
	def drop(cls):
		frappe.set_user("Administrator")  # nosemgrep: frappe-setuser -- test cleanup
		guests = frappe.get_all("Guest", filters={"email": ("like", "h2-lock-%")}, pluck="name")
		if guests:
			rows = frappe.get_all("TEX Loyalty Ledger", filters={"guest": ("in", guests)}, pluck="name")
			if rows:
				frappe.db.delete("TEX Audit Event", {"reference_name": ("in", rows)})
			for g in guests:
				frappe.db.delete("Error Log", {"method": ("like", f"Loyalty expiry failed: {g} /%")})
			frappe.db.delete("TEX Loyalty Ledger", {"guest": ("in", guests)})
			frappe.db.delete("Guest", {"name": ("in", guests)})
		frappe.db.delete("TEX Loyalty Program", {"program_name": "H2 Lock Club"})
		frappe.db.commit()  # nosemgrep: frappe-manual-commit -- test fixture cleanup across connections

	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		frappe.set_user("Administrator")  # nosemgrep: frappe-setuser -- test setup
		fx.base_setup()
		frappe.db.commit()  # nosemgrep: frappe-manual-commit -- threads need committed fixtures
		cls.drop()
		cls.club = frappe.get_doc({"doctype": "TEX Loyalty Program", "program_name": "H2 Lock Club",
		                           "property": fx.PROPERTY, "enabled": 1, "currency": "EUR", "point_value": "0.1",
		                           "min_redeem_points": 1, "max_redeem_percent": 100, "pending_days": 0,
		                           "expiry_months": 24}).insert(ignore_permissions=True).name
		cls.held, cls.after = sorted(
			frappe.get_doc({"doctype": "Guest", "first_name": "Lock", "last_name": n, "email": f"h2-lock-{n}@example.com"}
			               ).insert(ignore_permissions=True).name for n in ("A", "B"))
		past, today = add_days(nowdate(), -30), nowdate()
		for guest, entry_type, points, status, expires_on, available_on in (
				(cls.held, "Earn", 100, "Available", past, add_days(today, -60)),     # past its expiry
				(cls.held, "Earn", 50, "Pending", add_days(today, 400), add_days(today, -1)),     # matures today
				(cls.after, "Earn", 40, "Available", past, add_days(today, -60))):
			frappe.get_doc({"doctype": "TEX Loyalty Ledger", "program": cls.club, "guest": guest,
			                "entry_type": entry_type, "points": points, "status": status, "property": fx.PROPERTY,
			                "expires_on": expires_on, "available_on": available_on, "reason": "h2"}
			               ).insert(ignore_permissions=True)
		frappe.db.commit()  # nosemgrep: frappe-manual-commit -- threads need committed fixtures

	@classmethod
	def tearDownClass(cls):
		cls.drop()
		super().tearDownClass()

	def test_the_job_holds_no_ledger_lock_while_it_waits_for_a_guest(self):
		"""An adjustment holds the guest and waits for the ledger rows while the job, which matured one of
		them, waits for the guest: now the job has committed that row before it asks for the guest."""
		site, sites_path = frappe.local.site, frappe.local.sites_path
		held, entered = threading.Event(), threading.Event()
		out: dict[str, tuple] = {}
		job_thread: list[threading.Thread] = []
		real_settle = loyalty.settle

		def settle(guest, program, today=None):
			if guest == self.held and threading.current_thread() is job_thread[0]:
				entered.set()                    # from here the job waits for the guest
			return real_settle(guest, program, today)

		def adjustment():
			frappe.init(site=site, sites_path=sites_path)
			frappe.connect()
			try:
				frappe.set_user("Administrator")  # nosemgrep: frappe-setuser -- staff adjustment
				from kamra.tex.crm.service import require_live_guest

				require_live_guest(self.held)
				held.set()
				entered.wait(timeout=30)
				time.sleep(1)                    # the job is waiting: the ledger rows are asked for now
				out["adjust"] = ("ok", loyalty.adjust(self.held, self.club, -10, "lock order", property=fx.PROPERTY))
				frappe.db.commit()  # nosemgrep: frappe-manual-commit -- each side is its own request
			except Exception as e:
				frappe.db.rollback()
				out["adjust"] = ("error", f"{type(e).__name__}: {e}")
			finally:
				held.set()
				frappe.destroy()

		def job():
			frappe.init(site=site, sites_path=sites_path)
			frappe.connect()
			try:
				frappe.set_user("Administrator")  # nosemgrep: frappe-setuser -- the scheduler
				held.wait(timeout=30)
				frappe.flags.in_test = False         # the scheduler's batches commit (``loyalty._commit``)
				out["job"] = ("ok", loyalty.mature_and_expire())
			except Exception as e:
				frappe.db.rollback()
				out["job"] = ("error", f"{type(e).__name__}: {e}")
			finally:
				frappe.destroy()

		threads = [threading.Thread(target=adjustment), threading.Thread(target=job)]
		job_thread.append(threads[1])
		with mock.patch.object(loyalty, "settle", side_effect=settle):
			for t in threads:
				t.start()
			for t in threads:
				t.join(timeout=90)
		frappe.db.rollback()                         # a fresh snapshot of what the threads committed
		self.assertEqual(frappe.get_all("Error Log", filters={"method": ("like", f"Loyalty expiry failed: {self.held} /%")},
		                                pluck="name"), [], "the job lost a deadlock with the adjustment")
		self.assertEqual({k: v[0] for k, v in out.items()}, {"adjust": "ok", "job": "ok"}, out)
		self.assertEqual(out["job"][1]["matured"], 1)
		self.assertEqual(loyalty.balances(self.held, self.club)["available"], 40)         # 100 expired, 50 less 10
		self.assertEqual(loyalty.balances(self.after, self.club)["available"], 0)         # the next guest was settled
		self.assertEqual(frappe.get_all("TEX Loyalty Ledger", filters={"guest": self.after, "entry_type": "Expire"},
		                                pluck="points"), [-40])


class TestModification(LoyaltyCase):
	"""O-21 (audit Part 2H-1, ADR-071): changing a stay whose points were spent minted them again. The change
	reversed the earning and topped the balance up to zero with an Adjust (the points that were spent were
	"not clawed back"), then earned the whole new amount: 842 spent, a +1 change: 843 points. The stay's own
	points also counted for its tier. Now the change is exact: the old earning goes, the new one comes, the
	difference is the balance's; and the tier is read without the stay's own points."""

	CLUB_1 = MappingProxyType({"earn_rules": [{"basis": "MONEY", "rate": "1"}]})      # 842.50 earns 842

	def available(self, guest: str, club: str) -> int:
		return loyalty.balances(guest, club)["available"]

	def set_total(self, res: str, amount) -> None:
		"""The stay's total changes (its fingerprint), then the daily job runs, as it does the next night."""
		frappe.db.set_value("Reservation", res, "tex_total_amount", D(amount))
		doc = frappe.get_doc("Reservation", res)
		doc.save(ignore_permissions=True)
		loyalty.mature_and_expire(today=fx.d(6, 13))

	def spent_stay(self, club: str, session: str) -> tuple[dict, str, str, dict]:
		"""A stay that earned 842 (matured), all of it spent on another booking of the guest (84.20 of 842.50)."""
		b, guest = self.paid_stay(session)
		res = b["rooms"][0]["reservation"]
		loyalty.mature_and_expire(today=fx.d(6, 13))
		self.assertEqual(self.available(guest, club), 842)
		at_hotel = guest_books(session=f"{session}-hotel", method="Pay at Hotel")
		frappe.set_user("Administrator")  # nosemgrep: frappe-setuser -- staff redeem
		# the booking the points are spent on earns points of its own: not part of this scenario
		own = frappe.db.get_value("TEX Loyalty Ledger", {"booking": at_hotel["booking"], "entry_type": "Earn"})
		frappe.db.set_value("TEX Loyalty Ledger", own, "status", "Reversed")
		self.assertEqual(loyalty.redeem(guest, at_hotel["booking"], 842, idempotency_key=f"{session}-1")["value"], "84.20")
		self.assertEqual(self.available(guest, club), 0)
		return b, guest, res, at_hotel

	def test_changing_a_spent_stay_does_not_mint_its_points_again(self):
		club = self.create(**self.CLUB_1)
		_b, guest, res, _hotel = self.spent_stay(club, "o21-a")
		self.set_total(res, "843.50")                                             # +1
		self.assertEqual(self.available(guest, club), 1)                          # 843 earned now, 842 were spent
		self.assertFalse(frappe.db.exists("TEX Loyalty Ledger", {"guest": guest, "entry_type": "Adjust"}))
		lot = frappe.get_all("TEX Loyalty Ledger", filters={"reservation": res, "entry_type": "Earn",
		                                                    "status": ("!=", "Reversed")}, fields=["points", "status"])
		self.assertEqual([(r.points, r.status) for r in lot], [(843, "Available")])    # a matured stay's new lot is mature

	def test_repeated_changes_never_add_up_to_more_than_the_stay_is_worth(self):
		club = self.create(**self.CLUB_1)
		_b, guest, res, hotel = self.spent_stay(club, "o21-b")
		for total, left in (("843.50", 1), ("844.50", 2), ("845.50", 3), ("846.50", 4)):
			self.set_total(res, total)
			self.assertEqual(self.available(guest, club), left, total)
		with self.assertRaisesRegex(frappe.ValidationError, "Not enough points"):
			loyalty.redeem(guest, hotel["booking"], 50, idempotency_key="o21-b-2")

	def test_changing_a_stay_whose_points_expired_never_brings_them_back(self):
		"""LO-26 (audit 2K-2, ADR-071 §5): a stay whose points expired, changed afterwards (its dates moved: TEX is
		not the PMS, a stay that ended may still read Confirmed), earns again with the old lot's expiry, never a
		fresh one: the points that had expired expire again (before: 842 came back, valid for a new month)."""
		club = self.create(**self.CLUB_1, expiry_months=1)
		b, guest = self.paid_stay("lo26")
		res = b["rooms"][0]["reservation"]
		loyalty.mature_and_expire(today=fx.d(6, 13))
		self.assertEqual(self.available(guest, club), 842)
		loyalty.mature_and_expire(today=fx.d(8, 1))                               # a month after: expired
		self.assertEqual(self.available(guest, club), 0)
		frappe.db.set_value("Reservation", res, "check_out_date", fx.d(7, 20))      # the stay is changed afterwards
		frappe.get_doc("Reservation", res).save(ignore_permissions=True)
		loyalty.mature_and_expire(today=fx.d(8, 1))
		self.assertEqual(self.available(guest, club), 0)
		lot = frappe.get_all("TEX Loyalty Ledger", filters={"reservation": res, "entry_type": "Earn",
		                                                    "status": ("!=", "Reversed")}, pluck="expires_on")
		self.assertEqual([str(d) for d in lot], [str(add_months(fx.d(6, 13), 1))])

	def test_a_stay_changed_down_and_up_again_is_worth_what_it_is_now(self):
		club = self.create(**self.CLUB_1)
		_b, guest, res, _hotel = self.spent_stay(club, "o21-c")
		self.set_total(res, "843.50")
		self.assertEqual(self.available(guest, club), 1)
		self.set_total(res, "800.00")                                             # 800 earned, 842 spent: a debt
		self.assertEqual(self.available(guest, club), -42)
		self.assertEqual(frappe.db.get_value("Guest", guest, "tex_loyalty_points"), -42)
		self.set_total(res, "843.50")
		self.assertEqual(self.available(guest, club), 1)

	def test_a_stay_does_not_raise_its_own_tier(self):
		club = self.create(earn_rules=[{"basis": "MONEY", "rate": "1"}],
		                   tiers=[{"tier_name": "Silver", "min_points": 0, "earn_multiplier": "1"},
		                          {"tier_name": "Gold", "min_points": 800, "earn_multiplier": "2"}])
		b, guest = self.paid_stay("o21-d")
		res = b["rooms"][0]["reservation"]
		loyalty.mature_and_expire(today=fx.d(6, 13))
		self.assertEqual(self.available(guest, club), 842)                        # earned as Silver (0 before it)
		self.set_total(res, "843.50")                                             # its own 842 made the guest Gold
		self.assertEqual(self.available(guest, club), 843)                        # still Silver: 1687 as Gold

	def test_changing_a_stay_whose_points_expired_takes_the_expiry_with_the_earning(self):
		club = self.create(**self.CLUB_1)
		b, guest = self.paid_stay("o21-e")
		res = b["rooms"][0]["reservation"]
		loyalty.mature_and_expire(today=fx.d(6, 13))
		earn = frappe.db.get_value("TEX Loyalty Ledger", {"reservation": res, "entry_type": "Earn"})
		frappe.db.set_value("TEX Loyalty Ledger", earn, "expires_on", add_days(nowdate(), -1))
		loyalty.mature_and_expire()
		self.assertEqual((self.available(guest, club), frappe.db.get_value("TEX Loyalty Ledger", earn, "status")),
		                 (0, "Expired"))
		self.set_total(res, "843.50")
		self.assertEqual(frappe.db.get_value("TEX Loyalty Ledger", earn, "status"), "Reversed")
		expiry = frappe.get_all("TEX Loyalty Ledger", filters={"guest": guest, "entry_type": "Expire"},
		                        fields=["points", "status"])
		# taken away with its lot; the new lot keeps the expiry, so its points expire again at once (LO-26: before,
		# 843 came back with a fresh expiry)
		self.assertEqual(sorted((r.points, r.status) for r in expiry), [(-843, "Expired"), (-842, "Reversed")])
		self.assertEqual(self.available(guest, club), 0)


class TestEarnMatrix(LoyaltyCase):
	"""G-66 (audit Part 2H-1): every earn basis, with and without a tier multiplier, on one stay (842.50 EUR,
	3 nights, DBL, SPA x2), and the flows around it: tier progression, the pending period, expiry, the
	minimum, the currency, a lack of points. They fix today's behaviour; none is a fix."""

	def setUp(self):
		super().setUp()
		self.spa = fx.ensure_live("TEX Extra", {"property": fx.PROPERTY, "extra_code": "SPA"},
		                          {"property": fx.PROPERTY, "extra_code": "SPA", "extra_name": "Spa treatment",
		                           "category": "Spa", "pricing_mode": "UNIT", "currency": "EUR", "amount": 50,
		                           "tax_category": "SERVICE"})

	def stay(self) -> frappe._dict:
		return frappe._dict(check_in_date=fx.d(6, 10), check_out_date=fx.d(6, 13), tex_currency="EUR", room_type="DBL",
		                    tex_total_amount=D("842.50"), tex_pricing_snapshot=frappe.as_json(
			                    {"extras": [{"code": "SPA", "quantity": "2.000000", "ok": True}]}))

	def program(self, *rules, currency="EUR", blackouts=()) -> frappe._dict:
		bare = {"date_from": None, "date_to": None, "room_type": None, "extra": None}
		return frappe._dict(currency=currency, blackouts=list(blackouts),
		                    earn_rules=[frappe._dict({**bare, **r}) for r in rules])

	def test_each_basis_with_and_without_a_multiplier(self):
		for rules, plain, boosted in (
			([{"basis": "MONEY", "rate": "1"}], 842, 1263),
			([{"basis": "NIGHTS", "rate": "10"}], 30, 45),
			([{"basis": "STAY", "rate": "25"}], 25, 37),
			([{"basis": "ROOM", "rate": "5", "room_type": "DBL"}], 15, 22),
			([{"basis": "ROOM", "rate": "5", "room_type": "SGL"}], 0, 0),
			([{"basis": "EXTRA", "rate": "5", "extra": self.spa}], 10, 15),
			([{"basis": "MONEY", "rate": "0.5"}], 421, None),
			([{"basis": "MONEY", "rate": "1"}, {"basis": "STAY", "rate": "25"}], 867, 1301),
		):
			for multiplier, expected in (("1", plain), ("1.5", boosted)):
				if expected is None:
					continue
				with self.subTest(rules=[(r["basis"], r["rate"]) for r in rules], multiplier=multiplier):
					self.assertEqual(loyalty.points_for(self.program(*rules), self.stay(), multiplier)[0], expected)

	def test_a_stay_in_another_currency_than_the_program_earns_nothing_on_its_amount(self):
		points, lines = loyalty.points_for(self.program({"basis": "MONEY", "rate": "1"}, currency="TRY"), self.stay(), 1)
		self.assertEqual(points, 0)
		self.assertIn("currency EUR ≠ program TRY", lines[0]["note"])

	def test_a_rule_that_starts_after_check_in_earns_nothing(self):
		prog = self.program({"basis": "MONEY", "rate": "1"})
		prog.earn_rules[0].date_from = fx.d(6, 11)
		self.assertEqual(loyalty.points_for(prog, self.stay(), 1)[0], 0)
		prog.earn_rules[0].date_from, prog.earn_rules[0].date_to = fx.d(6, 1), fx.d(6, 10)       # up to check-in: counts
		self.assertEqual(loyalty.points_for(prog, self.stay(), 1)[0], 842)

	def test_an_earning_blackout_on_the_check_in_day_earns_nothing_and_a_redemption_one_does_not_matter(self):
		day = frappe._dict(date_from=fx.d(6, 10), date_to=fx.d(6, 10))
		stay_rule = {"basis": "STAY", "rate": "25"}
		points, lines = loyalty.points_for(self.program(stay_rule, blackouts=[frappe._dict(**day, applies_to="Earning")]),
		                                   self.stay(), 1)
		self.assertEqual((points, lines), (0, [{"rule": "BLACKOUT", "points": 0}]))
		self.assertEqual(loyalty.points_for(self.program(stay_rule, blackouts=[frappe._dict(**day, applies_to="Redemption")]),
		                                    self.stay(), 1)[0], 25)

	def test_the_tier_is_the_highest_one_reached(self):
		prog = frappe._dict(tiers=[frappe._dict(tier_name="Gold", min_points=1000),
		                           frappe._dict(tier_name="Silver", min_points=0)])
		self.assertEqual((loyalty.tier_of(prog, 999).tier_name, loyalty.tier_of(prog, 1000).tier_name), ("Silver", "Gold"))

	def test_the_second_stay_earns_at_the_tier_the_first_made(self):
		club = self.create(tiers=[{"tier_name": "Silver", "min_points": 0, "earn_multiplier": "1"},
		                          {"tier_name": "Gold", "min_points": 800, "earn_multiplier": "1.5"}])
		first, guest = self.paid_stay("g66-tier-1")
		loyalty.mature_and_expire(today=fx.d(6, 13))                       # 867 earned: Gold from here
		second, _same = self.paid_stay("g66-tier-2")                        # the same guest books and pays again
		earned = {r: frappe.db.get_value("TEX Loyalty Ledger", {"reservation": r, "entry_type": "Earn"}, "points")
		          for r in (first["rooms"][0]["reservation"], second["rooms"][0]["reservation"])}
		self.assertEqual(list(earned.values()), [867, 1301])
		self.assertEqual(loyalty.balances(guest, club)["lifetime_earned"], 867)

	def test_points_wait_for_the_pending_period_and_expire_after_their_months(self):
		club = self.create(pending_days=2, expiry_months=24)
		b, guest = self.paid_stay("g66-wait")
		earn = frappe.db.get_value("TEX Loyalty Ledger", {"guest": guest, "entry_type": "Earn"}, "name")
		loyalty.mature_and_expire(today=add_days(fx.d(6, 13), 1))
		self.assertEqual(frappe.db.get_value("TEX Loyalty Ledger", earn, "status"), "Pending")      # check-out + 1
		loyalty.mature_and_expire(today=add_days(fx.d(6, 13), 2))
		self.assertEqual(frappe.db.get_value("TEX Loyalty Ledger", earn, "status"), "Available")    # check-out + 2
		available_on, expires_on = frappe.db.get_value("TEX Loyalty Ledger", earn, ["available_on", "expires_on"])
		self.assertEqual(available_on, add_days(fx.d(6, 13), 2))
		self.assertEqual(expires_on, add_months(available_on, 24))
		self.assertEqual(loyalty.balances(guest, club)["available"], 867)
		self.assertTrue(b["booking"])

	def test_a_program_without_expiry_months_gives_points_no_expiry_date(self):
		self.create(expiry_months=0)
		_b, guest = self.paid_stay("g66-never")
		earn = frappe.db.get_value("TEX Loyalty Ledger", {"guest": guest, "entry_type": "Earn"}, "name")
		self.assertIsNone(frappe.db.get_value("TEX Loyalty Ledger", earn, "expires_on"))

	def test_redemption_asks_for_the_minimum_the_currency_and_the_points(self):
		club = self.create()
		b, guest = self.paid_stay("g66-redeem")
		loyalty.mature_and_expire(today=fx.d(6, 13))
		with self.assertRaisesRegex(frappe.ValidationError, "At least 50 points"):
			loyalty.redeem(guest, b["booking"], 49, idempotency_key="g66-1")
		self.assertEqual(loyalty.balances(guest, club)["available"], 867)
		frappe.get_doc({"doctype": "TEX Loyalty Ledger", "program": club, "guest": guest, "entry_type": "Burn",
		                "points": -850, "status": "Used", "reason": "spent"}).insert(ignore_permissions=True)
		with self.assertRaisesRegex(frappe.ValidationError, "Not enough points"):    # 17 left
			loyalty.redeem(guest, b["booking"], 50, idempotency_key="g66-2")
		frappe.db.set_value("TEX Loyalty Program", club, "enabled", 0)
		self.create(program_name="TRY club", currency="TRY")
		with self.assertRaisesRegex(frappe.ValidationError, "can only be redeemed on TRY bookings"):
			loyalty.redeem(guest, b["booking"], 50, idempotency_key="g66-3")


class TestPointsBack(LoyaltyCase):
	"""O-20 (audit Part 2H-2, D-16, ADR-071 §4): a booking that is cancelled or expires gives back as points,
	never as money, what its Loyalty charges hold beyond what it now costs. Before: nothing gave a burn back
	(867 earned, 300 spent, the booking cancelled: 567), and the points' money stayed on the cancelled booking,
	where staff with payment.refund could record it as "refunded in cash"."""

	def setUp(self):
		super().setUp()
		self.club = self.create(pending_days=0)                                  # 50 %, a point is 0.10 EUR

	def available(self, guest: str) -> int:
		return loyalty.balances(guest, self.club)["available"]

	def give(self, guest: str, points: int, *, entry_type="Adjust", **kw) -> str:
		return frappe.get_doc({"doctype": "TEX Loyalty Ledger", "program": self.club, "guest": guest,
		                       "entry_type": entry_type, "points": points, "status": "Available", "reason": "o20", **kw}
		                      ).insert(ignore_permissions=True).name

	def spend(self, session: str, points: int = 300, *, method: str = "Pay at Hotel", gift: int = 1000):
		"""A booking of a guest who holds ``gift`` points, and ``points`` of them spent on it."""
		booking = guest_books(session=session, method=method)
		frappe.set_user("Administrator")  # nosemgrep: frappe-setuser -- staff redeem
		guest = frappe.db.get_value("TEX Booking", booking["booking"], "booker_guest")
		own = frappe.db.get_value("TEX Loyalty Ledger", {"booking": booking["booking"], "entry_type": "Earn"})
		if own:                                                  # the booking's own earning is not part of this scenario
			frappe.db.set_value("TEX Loyalty Ledger", own, "status", "Reversed")
		if gift:
			self.give(guest, gift)
		red = loyalty.redeem(guest, booking["booking"], points, idempotency_key=f"{session}-pts")
		return booking, guest, red

	def test_points_are_never_paid_back_as_money(self):
		hotel, _guest, red = self.spend("o20-cash")
		for call in (lambda: pay.refund_outside(red["transaction"], amount="10.00", reason="cash back", reference="R-1",
		                                        idempotency_key="o20-cash-1", booking=hotel["booking"]),
		             lambda: pay.refund(red["transaction"], amount="10.00", reason="back", idempotency_key="o20-cash-2",
		                                booking=hotel["booking"]),
		             lambda: pay.refund(red["transaction"], amount="10.00", reason="back", idempotency_key="o20-cash-3",
		                                booking=hotel["booking"], _system=True)):
			with self.assertRaisesRegex(frappe.ValidationError, "never as money"):
				call()
		self.assertEqual(frappe.db.count("TEX Payment Transaction", {"parent_transaction": red["transaction"]}), 0)

	def refunds_of(self, charge: str) -> list[tuple]:
		return [(from_db(r.amount, "EUR"), r.status, r.raw_status, r.provider) for r in frappe.get_all(
			"TEX Payment Transaction", filters={"parent_transaction": charge, "txn_type": "Refund"},
			fields=["amount", "status", "raw_status", "provider"], order_by="creation asc, name asc")]

	def reverse_rows(self, guest: str) -> list[tuple]:
		return [(r.points, r.status, r.booking) for r in frappe.get_all(
			"TEX Loyalty Ledger", filters={"guest": guest, "entry_type": "Reverse"},
			fields=["points", "status", "booking"], order_by="creation asc, name asc")]

	def test_cancelling_gives_back_the_points_it_was_paid_with(self):
		"""867 earned, 300 spent on another booking, that booking cancelled: 867 (it was 567)."""
		_stay, guest = self.paid_stay("o20-a")
		loyalty.mature_and_expire(today=fx.d(6, 13))
		self.assertEqual(self.available(guest), 867)
		hotel, who, red = self.spend("o20-a-hotel", 300, gift=0)
		self.assertEqual((who, self.available(guest)), (guest, 567))
		booking_svc.cancel_reservation(hotel["rooms"][0]["reservation"], reason="o20", waive_penalty=True)
		self.assertEqual(self.available(guest), 867)
		paid, status = frappe.db.get_value("TEX Booking", hotel["booking"], ["paid_amount", "payment_status"])
		self.assertEqual((from_db(paid, "EUR"), status), (D("0.00"), "Refunded"))
		self.assertEqual(self.refunds_of(red["transaction"]), [(D("30.00"), "Succeeded", "POINTS RETURNED", "Loyalty")])
		self.assertEqual(self.reverse_rows(guest), [(300, "Available", hotel["booking"])])
		self.assertEqual(pay.booking_charges(hotel["booking"]), [])
		self.assertEqual(loyalty.return_points(hotel["booking"], reason="again"), 0)           # by state: nothing more
		self.assertEqual(frappe.db.get_value("Guest", guest, "tex_loyalty_points"), 867)
		self.assertTrue(frappe.db.exists("TEX Audit Event", {"action": "loyalty.return", "reference_name": hotel["booking"]}))
		self.assertTrue(frappe.db.exists("TEX Audit Event", {"action": "payment.points_returned"}))

	def test_points_spent_on_the_stays_own_booking_are_given_back_before_its_earning_is(self):
		"""The stay earned 867 and 300 of them paid for it: the points go back first, so reversing the earning
		takes 867 of 867 and never tops up (an Adjust of +300 made them out of nothing)."""
		stay, guest = self.paid_stay("o20-b")
		loyalty.mature_and_expire(today=fx.d(6, 13))
		red = loyalty.redeem(guest, stay["booking"], 300, idempotency_key="o20-b-pts")
		self.assertEqual(self.available(guest), 567)
		booking_svc.cancel_reservation(stay["rooms"][0]["reservation"], reason="o20", waive_penalty=True)
		self.assertEqual(self.available(guest), 0)
		self.assertEqual(frappe.get_all("TEX Loyalty Ledger", filters={"guest": guest, "entry_type": "Adjust"}), [])
		self.assertEqual(self.reverse_rows(guest), [(300, "Available", stay["booking"])])
		self.assertEqual(self.refunds_of(red["transaction"]), [(D("30.00"), "Succeeded", "POINTS RETURNED", "Loyalty")])
		paid = frappe.db.get_value("TEX Booking", stay["booking"], "paid_amount")
		self.assertEqual(from_db(paid, "EUR"), D("252.75"))             # the card deposit stays: staff refund it

	def test_a_hold_that_ends_gives_the_points_back_and_asks_staff_for_nothing(self):
		held = guest_books(session="o20-d")                              # a card hold waiting for its payment
		frappe.set_user("Administrator")  # nosemgrep: frappe-setuser -- staff redeem
		guest = frappe.db.get_value("TEX Booking", held["booking"], "booker_guest")
		self.give(guest, 1000)
		red = loyalty.redeem(guest, held["booking"], 500, idempotency_key="o20-d-pts")
		self.assertEqual(self.available(guest), 500)
		self.assertTrue(booking_svc.expire_booking(held["booking"], now=add_to_date(now_datetime(), hours=2)))
		self.assertEqual(self.available(guest), 1000)
		self.assertFalse(frappe.db.get_value("TEX Payment Transaction", red["transaction"], "reconciliation"))
		self.assertFalse(frappe.db.exists("TEX Audit Event", {"action": "payment.reconciliation_required",
		                                                      "reference_name": red["transaction"]}))
		self.assertEqual(from_db(frappe.db.get_value("TEX Booking", held["booking"], "paid_amount"), "EUR"), D("0.00"))
		self.assertEqual(self.refunds_of(red["transaction"]), [(D("50.00"), "Succeeded", "POINTS RETURNED", "Loyalty")])

	def test_points_that_come_back_after_their_lot_expired_expire_at_once(self):
		"""D-16a: the lot the spent points came from has expired meanwhile: nothing reopens it."""
		hotel = guest_books(session="o20-e", method="Pay at Hotel")
		frappe.set_user("Administrator")  # nosemgrep: frappe-setuser -- staff redeem
		guest = frappe.db.get_value("TEX Booking", hotel["booking"], "booker_guest")
		own = frappe.db.get_value("TEX Loyalty Ledger", {"booking": hotel["booking"], "entry_type": "Earn"})
		frappe.db.set_value("TEX Loyalty Ledger", own, "status", "Reversed")        # not part of this scenario
		lot = self.give(guest, 500, entry_type="Earn", expires_on=add_days(nowdate(), 5),
		                available_on=add_days(nowdate(), -30))
		loyalty.redeem(guest, hotel["booking"], 300, idempotency_key="o20-e-pts")      # 200 of the lot are left
		frappe.db.set_value("TEX Loyalty Ledger", lot, "expires_on", add_days(nowdate(), -1))
		loyalty.mature_and_expire()                                                    # 200 expire, the lot closes
		self.assertEqual(self.available(guest), 0)
		booking_svc.cancel_reservation(hotel["rooms"][0]["reservation"], reason="o20", waive_penalty=True)
		rows = frappe.get_all("TEX Loyalty Ledger", filters={"guest": guest, "entry_type": ("in", ["Reverse", "Expire"])},
		                      fields=["entry_type", "points"], order_by="creation asc, name asc")
		self.assertEqual([(r.entry_type, r.points) for r in rows], [("Expire", -200), ("Reverse", 300), ("Expire", -300)])
		self.assertEqual(self.available(guest), 0)

	def test_a_return_is_shared_pro_rata_by_the_newest_payment_first(self):
		"""Two redemptions of one booking, the booking now costs less than it holds: the newest payment gives
		back first, and only what the booking holds beyond its new cost."""
		hotel, guest, first = self.spend("o20-f", 300)                                 # 30.00
		second = loyalty.redeem(guest, hotel["booking"], 200, idempotency_key="o20-f-2")   # 20.00
		self.assertEqual(self.available(guest), 500)
		frappe.db.set_value("TEX Booking", hotel["booking"], "total_amount", D("50.00"))      # it costs what it holds
		self.assertEqual(loyalty.return_points(hotel["booking"], reason="a fee kept"), 0)      # a fee keeps its points
		frappe.db.set_value("TEX Booking", hotel["booking"], "total_amount", D("45.00"))      # 5.00 over
		self.assertEqual(loyalty.return_points(hotel["booking"], reason="the price came down"), 50)
		self.assertEqual(self.refunds_of(second["transaction"]), [(D("5.00"), "Succeeded", "POINTS RETURNED", "Loyalty")])
		self.assertEqual(self.refunds_of(first["transaction"]), [])
		self.assertEqual(self.available(guest), 550)

	def test_the_points_of_a_return_are_read_by_their_indexes(self):
		params = {"guests": ("G-O20-1", "G-O20-2"), "b": "BK-O20", "bookings": ("BK-O20", "BK-O20-2"),
		          "reasons": ("redeemed as TXN-O20-1",)}
		for sql in (loyalty.BURNS_OF, loyalty.BURNERS_OF, loyalty.PENDING_REFUNDS_OF):
			for row in frappe.db.sql("EXPLAIN " + sql, params, as_dict=True):
				self.assertNotIn(row.type, ("ALL", "index"), (sql, row))
				self.assertTrue(row.key, (sql, row))

	# LO-01 (O-19b, audit 2K-1): a lower price of a booking paid partly with points gives the points' share back as
	# points, before any cash, and asks staff for nothing; points are never recorded as money given back outside TEX.
	# Before: the points' share went to staff, whose "Refunded outside TEX" refused (the Loyalty charge newest) or
	# recorded it as cash off the card.

	def lowered(self, session: str, *, points_last: bool) -> dict:
		"""842.50 paid as 300.00 of points (3000) and card or desk money; the guest shortens the stay (575.00, 267.50
		less) and finance approves it as a refund. → what the test reads."""
		from kamra.tex.api import crs as crs_api

		b = guest_books(session=session, method="Card")
		p = b["payment"]
		public.mock_pay(transaction=p["transaction"], outcome="success", sig=p["fields"]["success_sig"])   # 252.75
		frappe.set_user("Administrator")  # nosemgrep: frappe-setuser -- staff
		booking = b["booking"]
		guest = frappe.db.get_value("TEX Booking", booking, "booker_guest")
		own = frappe.db.get_value("TEX Loyalty Ledger", {"booking": booking, "entry_type": "Earn"})
		if own:                                                  # the booking's own earning is not part of this scenario
			frappe.db.set_value("TEX Loyalty Ledger", own, "status", "Reversed")
		self.give(guest, 5000)
		if points_last:
			pay.record_manual(booking=booking, amount="289.75", method="Cash", reference="desk",
			                  idempotency_key=f"{session}-cash")
			red = loyalty.redeem(guest, booking, 3000, idempotency_key=f"{session}-pts")
		else:
			red = loyalty.redeem(guest, booking, 3000, idempotency_key=f"{session}-pts")
			rest = public.pay_booking(token=b["manage_token"])
			public.mock_pay(transaction=rest["transaction"], outcome="success", sig=rest["fields"]["success_sig"])
			frappe.set_user("Administrator")  # nosemgrep: frappe-setuser -- staff
		self.assertEqual(from_db(frappe.db.get_value("TEX Booking", booking, "paid_amount"), "EUR"), D("842.50"))
		frappe.set_user("Guest")  # nosemgrep: frappe-setuser -- the guest shortens the stay on the manage page
		down = public.manage_propose(token=b["manage_token"], reservation=b["rooms"][0]["reservation"],
		                             changes={"check_out": str(fx.d(6, 12))})
		out = public.manage_apply(token=b["manage_token"], proposal_token=down["proposal_token"])
		self.assertEqual(out["status"], "requested")
		frappe.set_user("Administrator")  # nosemgrep: frappe-setuser -- finance approves it as a refund
		return {"booking": booking, "guest": guest, "points": red["transaction"], "request": out["request"],
		        "approve": lambda: crs_api.resolve_guest_change(request=out["request"], action="approve", reason="shorter",
		                                                        settlement="Refund")}

	def assert_points_came_back(self, case: dict, done: dict) -> None:
		req = frappe.get_doc("TEX Guest Change Request", case["request"])
		self.assertEqual((done["status"], done["refunded_amount"], req.staff_open, D(req.staff_amount or 0)),
		                 ("Approved", "267.50", 0, D(0)))
		self.assertEqual(self.refunds_of(case["points"]), [(D("267.50"), "Succeeded", "POINTS RETURNED", "Loyalty")])
		self.assertEqual(self.reverse_rows(case["guest"]), [(2675, "Available", case["booking"])])
		cash = frappe.get_all("TEX Payment Transaction", filters={"txn_type": "Refund", "booking": case["booking"],
		                                                          "provider": ("!=", "Loyalty")}, pluck="name")
		self.assertEqual(cash, [])                               # nothing went back as money
		total, paid = frappe.db.get_value("TEX Booking", case["booking"], ["total_amount", "paid_amount"])
		self.assertEqual((from_db(total, "EUR"), from_db(paid, "EUR")), (D("575.00"), D("575.00")))

	def test_the_points_paid_last_come_back_as_points(self):
		case = self.lowered("lo01-points-last", points_last=True)
		self.assert_points_came_back(case, case["approve"]())

	def test_the_points_come_back_first_even_when_the_card_paid_last(self):
		case = self.lowered("lo01-card-last", points_last=False)
		self.assert_points_came_back(case, case["approve"]())

	def test_points_left_to_staff_are_never_recorded_as_money_given_back(self):
		"""LO-01: points that could not come back by themselves (no burn row found) are left to staff; their
		"Refunded outside TEX" is refused with the reason, never closed as if refunded (before: 267.50 recorded off the
		card paid last; then, review round 1: closed silently with nothing recorded, so the booking stayed over and its
		points could come back again later). Kept on the booking, it closes and records no money given back."""
		from kamra.tex.api import crs as crs_api

		case = self.lowered("lo01-staff", points_last=False)
		frappe.db.set_value("TEX Loyalty Ledger", {"reason": f"redeemed as {case['points']}"}, "reason", "unknown burn")
		self.assertEqual(case["approve"]()["refunded_amount"], "0.00")
		self.assertEqual(frappe.db.get_value("TEX Guest Change Request", case["request"], "staff_open"), 1)
		with self.assertRaisesRegex(frappe.ValidationError, "267.50 EUR of this money was paid with loyalty points"):
			crs_api.resolve_guest_change(request=case["request"], action="close", reason="given back by hand",
			                             staff_money="Refunded outside TEX")
		self.assertEqual(frappe.db.get_value("TEX Guest Change Request", case["request"], "staff_open"), 1)
		crs_api.resolve_guest_change(request=case["request"], action="close", reason="kept, points corrected in the CRM",
		                             staff_money="Kept on the booking")
		self.assertEqual(frappe.db.get_value("TEX Guest Change Request", case["request"], "staff_open"), 0)
		cash = frappe.get_all("TEX Payment Transaction", filters={"txn_type": "Refund", "booking": case["booking"]},
		                      pluck="name")
		self.assertEqual(cash, [])

	# LO-06 (audit 2K-2): the burn row of a Loyalty charge is found by the charge, wherever the charge or its burner
	# is now. Before: only among the booking's current guests and on this booking, so a charge staff moved to
	# another booking, or a burner no longer on the room, gave no points back (an Error Log, the money left to staff).

	def test_points_moved_to_another_booking_come_back_when_it_is_cancelled(self):
		hotel, guest, red = self.spend("lo06-moved", 300)
		other = guest_books(session="lo06-other", method="Pay at Hotel",
		                    guest={"first_name": "Otto", "last_name": "Other", "email": "otto.lo06@example.com"})
		frappe.set_user("Administrator")  # nosemgrep: frappe-setuser -- staff move the points' money
		pay.transfer(red["transaction"], from_booking=hotel["booking"], to_booking=other["booking"], amount="30.00",
		             reason="the guest asked to pay the other stay")
		self.assertEqual(self.available(guest), 700)
		since = now_datetime()
		booking_svc.cancel_reservation(other["rooms"][0]["reservation"], reason="lo06", waive_penalty=True)
		self.assertEqual(self.available(guest), 1000)
		self.assertEqual(self.reverse_rows(guest), [(300, "Available", other["booking"])])
		self.assertFalse(frappe.db.exists("Error Log", {"method": f"Loyalty points not returned: {red['transaction']}",
		                                                "creation": (">=", since)}))

	def test_points_come_back_to_their_burner_after_the_guest_changed(self):
		hotel, guest, red = self.spend("lo06-burner", 300)
		newcomer = frappe.get_doc({"doctype": "Guest", "first_name": "Nina", "last_name": "New",
		                           "email": "nina.lo06@example.com"}).insert(ignore_permissions=True).name
		res = hotel["rooms"][0]["reservation"]
		frappe.db.set_value("Reservation", res, "guest", newcomer, update_modified=False)
		frappe.db.set_value("TEX Booking", hotel["booking"], "booker_guest", newcomer, update_modified=False)
		booking_svc.cancel_reservation(res, reason="lo06", waive_penalty=True)
		self.assertEqual(self.available(guest), 1000)
		self.assertEqual(self.reverse_rows(guest), [(300, "Available", hotel["booking"])])
		self.assertEqual(self.refunds_of(red["transaction"]), [(D("30.00"), "Succeeded", "POINTS RETURNED", "Loyalty")])

	def test_a_revival_short_of_the_points_given_back_says_so_to_staff(self):
		"""LO-23 (audit 2K-2): a hold paid partly with points expires (the points come back), then its card money,
		paid in time, comes late: the card alone no longer pays what it owes, so it is not taken back (points are
		never burned again, 2H-2). The note for staff says the points were given back (before: a generic note)."""
		held = guest_books(session="lo23")                                   # a card hold waiting for its payment
		frappe.set_user("Administrator")  # nosemgrep: frappe-setuser -- staff redeem
		guest = frappe.db.get_value("TEX Booking", held["booking"], "booker_guest")
		self.give(guest, 1000)
		loyalty.redeem(guest, held["booking"], 500, idempotency_key="lo23-pts")
		rest = public.pay_booking(token=held["manage_token"])                # the rest of the deposit, by card
		frappe.set_user("Administrator")  # nosemgrep: frappe-setuser -- the expiry job
		self.assertTrue(booking_svc.expire_booking(held["booking"], now=add_to_date(now_datetime(), hours=2)))
		self.assertEqual(self.available(guest), 1000)
		public.mock_pay(transaction=rest["transaction"], outcome="success", sig=rest["fields"]["success_sig"])
		frappe.set_user("Administrator")  # nosemgrep: frappe-setuser -- staff read what is on record
		row = frappe.db.get_value("TEX Payment Transaction", rest["transaction"],
		                          ["status", "reconciliation", "reconciliation_note"], as_dict=True)
		self.assertEqual((row.status, row.reconciliation), ("Succeeded", "Action Required"))
		self.assertIn("points that paid part of it were given back", row.reconciliation_note)

	def test_a_balance_below_zero_is_shown_as_points_owed(self):
		"""LO-25 (audit 2K-2): points spent before a stay changed and earned less leave a balance below zero; the
		profile's summary says how many points are owed (``debt``) and puts no negative money value on them."""
		b = guest_books(session="lo25", method="Pay at Hotel")
		frappe.set_user("Administrator")  # nosemgrep: frappe-setuser -- staff read the profile
		guest = frappe.db.get_value("TEX Booking", b["booking"], "booker_guest")
		frappe.db.set_value("TEX Loyalty Ledger", {"guest": guest, "program": self.club}, "status", "Reversed")
		self.give(guest, 100)
		self.give(guest, -300, entry_type="Reverse")                  # a changed stay took back more than was left
		[account] = loyalty.summary(guest, {self.club})
		self.assertEqual((account["available"], account["debt"], account["value"]), (-200, 200, "0.00"))
		self.give(guest, 500)
		[account] = loyalty.summary(guest, {self.club})
		self.assertEqual((account["available"], account["debt"], account["value"]), (300, 0, "30.00"))


class TestAnEarningNeverUndoesTheStay(LoyaltyCase):
	"""LO-47 (audit 2K-2, owner's choice a): the loyalty earning runs in the reservation's save. A rule that fails
	must never roll back what the save does (a confirmation, a payment's callback, a cancellation): the earning is
	undone alone, logged, and the system status warns that a stay's points are missing."""

	def test_a_failing_earning_leaves_the_confirmation_and_is_reported(self):
		from kamra.tex.ops import status as ops_status

		self.create()
		b = guest_books(session="lo47")
		p = b["payment"]
		with mock.patch.object(loyalty, "points_for", side_effect=RuntimeError("a broken rule")):
			public.mock_pay(transaction=p["transaction"], outcome="success", sig=p["fields"]["success_sig"])
		frappe.set_user("Administrator")  # nosemgrep: frappe-setuser -- staff read what is on record
		res = b["rooms"][0]["reservation"]
		self.assertEqual(frappe.db.get_value("TEX Booking", b["booking"], "status"), "Confirmed")
		self.assertEqual(frappe.db.get_value("Reservation", res, "status"), "Confirmed")
		self.assertFalse(frappe.db.exists("TEX Loyalty Ledger", {"reservation": res, "entry_type": "Earn"}))
		self.assertTrue(frappe.db.exists("Error Log", {"method": f"TEX loyalty earning {res}"}))
		check = next(c for c in ops_status.collect(properties=[fx.PROPERTY]) if c["key"] == "loyalty.earnings")
		self.assertEqual(check["status"], "warn")
		self.assertEqual(check["issues"][0]["reason"], "loyalty_earning_failed")
		self.assertIn(fx.PROPERTY, check["properties"])

	def test_a_failing_reversal_leaves_the_cancellation_and_is_reported(self):
		"""The cancellation's reversal of the stay's points runs under the same guard: the cancellation is kept,
		the earned points stay for staff to correct, and the same check reports it (review round 1)."""
		from kamra.tex.ops import status as ops_status

		self.create()
		b = guest_books(session="lo47-rev")
		p = b["payment"]
		public.mock_pay(transaction=p["transaction"], outcome="success", sig=p["fields"]["success_sig"])
		frappe.set_user("Administrator")  # nosemgrep: frappe-setuser -- staff cancel
		res = b["rooms"][0]["reservation"]
		self.assertTrue(frappe.db.exists("TEX Loyalty Ledger", {"reservation": res, "entry_type": "Earn",
		                                                        "status": ("!=", "Reversed")}))
		since = now_datetime()
		with mock.patch.object(loyalty, "_reverse", side_effect=RuntimeError("a broken reversal")):
			booking_svc.cancel_reservation(res, reason="lo47", waive_penalty=True)
		self.assertEqual(frappe.db.get_value("Reservation", res, "status"), "Cancelled")
		self.assertTrue(frappe.db.exists("TEX Loyalty Ledger", {"reservation": res, "entry_type": "Earn",
		                                                        "status": ("!=", "Reversed")}))
		self.assertTrue(frappe.db.exists("Error Log", {"method": f"TEX loyalty earning {res}",
		                                               "creation": (">=", since)}))
		check = next(c for c in ops_status.collect(properties=[fx.PROPERTY]) if c["key"] == "loyalty.earnings")
		self.assertEqual((check["status"], check["issues"][0]["reason"]), ("warn", "loyalty_earning_failed"))
