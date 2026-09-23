"""Double-selling protection under real concurrency (R-17).

Two threads, each with its own database connection, try to book the last
Deluxe room at the same instant. Exactly one must win; the other must be told the
room sold out. Fixture data is committed (threads cannot see an uncommitted
transaction) and removed again in tearDownClass.
"""

import threading

import frappe
from frappe.tests import IntegrationTestCase

from kamra.tex.money import D
from kamra.tex.services import booking, quoting
from kamra.tex.tests.integration import fixtures as fx

PROPERTY_TABLES = ("TEX Booking", "Reservation", "TEX Quote", "TEX Reservation Revision", "TEX Contract",
                   "TEX Inventory Day", "TEX Promotion Redemption", "TEX Audit Event", "TEX Markup Rule")


def _cleanup():
	frappe.set_user("Administrator")  # nosemgrep: frappe-setuser -- test cleanup
	codes = frappe.get_all("TEX Contract", filters={"property": fx.PROPERTY, "contract_code": "CONC"}, pluck="name")
	for c in codes:
		frappe.db.sql("DELETE FROM `tabTEX Contract Version` WHERE contract=%s", c)
	bookings = frappe.get_all("TEX Booking", filters={"property": fx.PROPERTY}, pluck="name")
	for b in bookings:
		frappe.db.sql("DELETE FROM `tabTEX Booking Room` WHERE parent=%s", b)
	res = frappe.get_all("Reservation", filters={"property": fx.PROPERTY}, pluck="name")
	for r in res:
		frappe.db.sql("DELETE FROM `tabTEX Reservation Revision` WHERE reservation=%s", r)
	for dt in PROPERTY_TABLES:
		if dt == "TEX Reservation Revision":
			continue
		frappe.db.sql(f"DELETE FROM `tab{dt}` WHERE property=%s", fx.PROPERTY)  # constant table list
	frappe.db.commit()  # nosemgrep: frappe-manual-commit -- test fixture cleanup across connections


class TestConcurrentLastRoom(IntegrationTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		frappe.set_user("Administrator")  # nosemgrep: frappe-setuser -- test setup
		_cleanup()
		cls.f = fx.base_setup()
		fx.create_contract(cls.f, code="CONC")
		frappe.set_user("Guest")  # nosemgrep: frappe-setuser -- guest booking path
		ci, co = fx.d(8, 20), fx.d(8, 22)
		prop = quoting.search(properties=[fx.PROPERTY], check_in=ci, check_out=co, rooms=[{"adults": 2}],
		                      market="DE", channel="DIRECT_WEB", currency="EUR")["properties"][0]
		rt = frappe.db.get_value("Room Type", {"property": fx.PROPERTY, "room_type_code": "DLX"})
		offer = next(o for o in prop["offers"] if o["room_type"] == rt and o["board"] == "AI")
		quotes = [quoting.create_quote(offer["rooms"][0]["offer_key"])["quote_id"] for _ in range(3)]
		# one of the two Deluxe rooms is already sold
		booking.create_booking(quote_ids=[quotes[0]], guest={"first_name": "Pre", "last_name": "Booked",
		                                                     "email": "pre@example.com"}, payment_method="Card")
		cls.racers = quotes[1:]
		frappe.set_user("Administrator")  # nosemgrep: frappe-setuser -- test setup
		frappe.db.commit()  # nosemgrep: frappe-manual-commit -- threads need committed fixtures

	@classmethod
	def tearDownClass(cls):
		_cleanup()
		super().tearDownClass()

	def test_exactly_one_of_two_simultaneous_bookings_wins(self):
		site, sites_path = frappe.local.site, frappe.local.sites_path
		barrier = threading.Barrier(2)
		results: dict[str, str] = {}

		def race(quote_id: str, who: str):
			frappe.init(site=site, sites_path=sites_path)
			frappe.connect()
			try:
				frappe.set_user("Guest")  # nosemgrep: frappe-setuser -- guest booking path
				barrier.wait(timeout=10)
				booking.create_booking(quote_ids=[quote_id], guest={"first_name": who, "last_name": "Racer",
				                                                    "email": f"{who}@example.com"},
				                       payment_method="Card")
				frappe.db.commit()  # nosemgrep: frappe-manual-commit -- each racer is its own request
				results[who] = "booked"
			except frappe.ValidationError as e:
				frappe.db.rollback()
				results[who] = f"refused: {e}"
			finally:
				frappe.destroy()

		threads = [threading.Thread(target=race, args=(q, w)) for q, w in zip(self.racers, ("alice", "bob"),
		                                                                        strict=True)]
		for t in threads:
			t.start()
		for t in threads:
			t.join(timeout=60)
		outcomes = sorted(v.split(":")[0] for v in results.values())
		self.assertEqual(outcomes, ["booked", "refused"], results)
		self.assertTrue(any("sold out" in v for v in results.values()), results)
		frappe.db.rollback()
		live = frappe.db.count("Reservation", {"property": fx.PROPERTY, "room_type": ("like", "%DLX"),
		                                       "status": ("in", ["Confirmed", "Pending Payment"])})
		self.assertEqual(live, 2)


class TestConcurrentAllocation(IntegrationTestCase):
	"""G-14: two finance users allocate the same unallocated payment to two bookings at the
	same instant. The payment is allocated once; the other is told nothing is left."""

	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		frappe.set_user("Administrator")  # nosemgrep: frappe-setuser -- test setup
		_cleanup()
		_cleanup_payments()
		cls.f = fx.base_setup()
		fx.create_contract(cls.f, code="CONC")
		frappe.set_user("Guest")  # nosemgrep: frappe-setuser -- guest booking path
		ci, co = fx.d(8, 20), fx.d(8, 22)
		prop = quoting.search(properties=[fx.PROPERTY], check_in=ci, check_out=co, rooms=[{"adults": 2}],
		                      market="DE", channel="DIRECT_WEB", currency="EUR")["properties"][0]
		flex = frappe.db.get_value("Rate Plan", {"property": fx.PROPERTY, "code": "FLEX"})
		offer = next(o for o in prop["offers"] if o["board"] == "AI" and o["rate_plan"] == flex)
		cls.bookings = []
		for who in ("one", "two"):
			q = quoting.create_quote(offer["rooms"][0]["offer_key"])["quote_id"]
			cls.bookings.append(booking.create_booking(quote_ids=[q], guest={
				"first_name": who, "last_name": "Payer", "email": f"{who}.payer@example.com"},
				payment_method="Pay at Hotel")["booking"])
		frappe.set_user("Administrator")  # nosemgrep: frappe-setuser -- finance records a desk payment
		from kamra.tex.payments import service as pay

		cls.txn = pay.record_manual(booking=cls.bookings[0], amount="100", method="Cash", reference="till 7",
		                            idempotency_key="conc-cash")["transaction"]
		pay.release(cls.txn, booking=cls.bookings[0], amount="100", reason="to be allocated")
		frappe.db.commit()  # nosemgrep: frappe-manual-commit -- threads need committed fixtures

	@classmethod
	def tearDownClass(cls):
		_cleanup_payments()
		_cleanup()
		super().tearDownClass()

	def test_one_payment_is_allocated_once(self):
		site, sites_path = frappe.local.site, frappe.local.sites_path
		barrier = threading.Barrier(2)
		results: dict[str, str] = {}

		def race(target: str):
			frappe.init(site=site, sites_path=sites_path)
			frappe.connect()
			try:
				from kamra.tex.payments import service as pay

				frappe.set_user("Administrator")  # nosemgrep: frappe-setuser -- a finance user
				barrier.wait(timeout=10)
				pay.allocate(self.txn, booking=target, amount="100", reason="race")
				frappe.db.commit()  # nosemgrep: frappe-manual-commit -- each submit is its own request
				results[target] = "allocated"
			except frappe.ValidationError as e:
				frappe.db.rollback()
				results[target] = f"refused: {e}"
			finally:
				frappe.destroy()

		threads = [threading.Thread(target=race, args=(b,)) for b in self.bookings]
		for t in threads:
			t.start()
		for t in threads:
			t.join(timeout=60)
		self.assertEqual(sorted(v.split(":")[0] for v in results.values()), ["allocated", "refused"], results)
		frappe.db.rollback()
		from kamra.tex.payments import service as pay

		self.assertEqual(pay.allocated_of(self.txn), D("100"))


def _cleanup_payments():
	frappe.set_user("Administrator")  # nosemgrep: frappe-setuser -- test cleanup
	for dt in ("TEX Payment Allocation", "TEX Payment Transaction"):
		frappe.db.sql(f"DELETE FROM `tab{dt}` WHERE property=%s", fx.PROPERTY)  # constant table list
	frappe.db.commit()  # nosemgrep: frappe-manual-commit -- test fixture cleanup across connections
