"""Double-selling protection under real concurrency (R-17).

Two threads, each with its own database connection, try to book the last
Deluxe room at the same instant. Exactly one must win; the other must be told the
room sold out. Fixture data is committed (threads cannot see an uncommitted
transaction) and removed again in tearDownClass.
"""

import threading
import traceback

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import add_days

from kamra.tex.money import D
from kamra.tex.services import booking, quoting
from kamra.tex.tests.integration import fixtures as fx

PROPERTY_TABLES = ("TEX Booking", "Reservation", "TEX Quote", "TEX Reservation Revision", "TEX Contract",
                   "TEX Inventory Day", "TEX Promotion Redemption", "TEX Audit Event", "TEX Markup Rule",
                   "TEX Extra Allocation", "TEX Extra Inventory Day")


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


class TestConcurrentDeskAndTexBooking(IntegrationTestCase):
	"""G-49: a TEX booking of the last Deluxe room is in flight (its nights locked, not yet
	committed) when a reservation for the same nights is written outside TEX (a migration import:
	since G-92 the Desk form and REST cannot create one at a TEX hotel, ADR-052). The outside write
	waits for TEX's inventory lock, then sees the room is gone: the hotel is never oversold.
	(Before G-49 the outside write took no lock and was checked only against its own snapshot, so
	both were kept.)"""

	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		frappe.set_user("Administrator")  # nosemgrep: frappe-setuser -- test setup
		_cleanup()
		cls.f = fx.base_setup()
		fx.create_contract(cls.f, code="CONC")
		frappe.set_user("Guest")  # nosemgrep: frappe-setuser -- guest booking path
		cls.ci, cls.co = fx.d(8, 20), fx.d(8, 22)
		prop = quoting.search(properties=[fx.PROPERTY], check_in=cls.ci, check_out=cls.co, rooms=[{"adults": 2}],
		                      market="DE", channel="DIRECT_WEB", currency="EUR")["properties"][0]
		cls.dlx = frappe.db.get_value("Room Type", {"property": fx.PROPERTY, "room_type_code": "DLX"})
		offer = next(o for o in prop["offers"] if o["room_type"] == cls.dlx and o["board"] == "AI")
		quotes = [quoting.create_quote(offer["rooms"][0]["offer_key"])["quote_id"] for _ in range(2)]
		booking.create_booking(quote_ids=[quotes[0]], guest={"first_name": "Pre", "last_name": "Booked",
		                                                     "email": "pre.desk@example.com"}, payment_method="Card")
		cls.racer = quotes[1]
		frappe.set_user("Administrator")  # nosemgrep: frappe-setuser -- test setup
		from kamra.api import _find_or_create_guest

		cls.guest = _find_or_create_guest("Desk Racer", "+49 30 5550151")
		frappe.db.commit()  # nosemgrep: frappe-manual-commit -- threads need committed fixtures

	@classmethod
	def tearDownClass(cls):
		frappe.db.sql("DELETE FROM `tabGuest` WHERE phone=%s", "+49 30 5550151")
		_cleanup()
		super().tearDownClass()

	def test_a_desk_reservation_waits_for_the_tex_booking_and_is_refused(self):
		site, sites_path = frappe.local.site, frappe.local.sites_path
		tex_holds, desk_done = threading.Event(), threading.Event()
		results: dict[str, str] = {}

		def tex():
			frappe.init(site=site, sites_path=sites_path)
			frappe.connect()
			try:
				frappe.set_user("Guest")  # nosemgrep: frappe-setuser -- guest booking path
				booking.create_booking(quote_ids=[self.racer], guest={"first_name": "Tex", "last_name": "Racer",
				                                                      "email": "tex.racer@example.com"},
				                       payment_method="Card")
				tex_holds.set()
				desk_done.wait(timeout=5)     # the desk write runs while this booking holds the nights
				frappe.db.commit()  # nosemgrep: frappe-manual-commit -- each racer is its own request
				results["tex"] = "booked"
			except Exception as e:
				frappe.db.rollback()
				results["tex"] = f"{type(e).__name__}: {e}"
			finally:
				tex_holds.set()
				frappe.destroy()

		def desk():
			frappe.init(site=site, sites_path=sites_path)
			frappe.connect()
			try:
				frappe.set_user("Administrator")  # nosemgrep: frappe-setuser -- an admin importing bookings
				tex_holds.wait(timeout=30)
				from kamra.tex.legacy import flag_import

				doc = frappe.get_doc({"doctype": "Reservation", "property": fx.PROPERTY, "guest": self.guest,
				                      "room_type": self.dlx, "check_in_date": self.ci, "check_out_date": self.co,
				                      "adults": 2, "status": "Confirmed", "amount_after_tax": 240})
				flag_import(doc, currency="EUR")
				doc.insert()
				frappe.db.commit()  # nosemgrep: frappe-manual-commit -- each racer is its own request
				results["desk"] = "booked"
			except Exception as e:
				frappe.db.rollback()
				results["desk"] = f"{type(e).__name__}: {e}"
			finally:
				desk_done.set()
				frappe.destroy()

		threads = [threading.Thread(target=tex), threading.Thread(target=desk)]
		for t in threads:
			t.start()
		for t in threads:
			t.join(timeout=90)
		self.assertEqual(results.get("tex"), "booked", results)
		self.assertIn("TEX inventory", results.get("desk", ""), results)
		frappe.db.rollback()
		live = frappe.db.count("Reservation", {"property": fx.PROPERTY, "room_type": self.dlx,
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
	for dt in ("TEX Payment Allocation", "TEX Payment Transaction", "TEX Payment Link"):
		frappe.db.sql(f"DELETE FROM `tab{dt}` WHERE property=%s", fx.PROPERTY)  # constant table list
	frappe.db.commit()  # nosemgrep: frappe-manual-commit -- test fixture cleanup across connections


def _cleanup_codes():
	frappe.set_user("Administrator")  # nosemgrep: frappe-setuser -- test cleanup
	frappe.db.sql("DELETE FROM `tabTEX Promotion` WHERE property=%s AND code='CONCONE'", fx.PROPERTY)
	frappe.db.commit()  # nosemgrep: frappe-manual-commit -- test fixture cleanup across connections


class TestConcurrentCouponLimit(IntegrationTestCase):
	"""G-07 under real concurrency: a code that may be used once, two guests book with it at
	the same instant. Exactly one booking gets it; the other is told it is used up."""

	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		frappe.set_user("Administrator")  # nosemgrep: frappe-setuser -- test setup
		_cleanup()
		_cleanup_codes()
		cls.f = fx.base_setup()
		fx.create_contract(cls.f, code="CONC")
		from kamra.tex.commercial import revisions

		promo = frappe.get_doc({"doctype": "TEX Promotion", "promotion_name": "Once only", "property": fx.PROPERTY,
		                        "trigger": "Code", "code": "CONCONE", "value_type": "PERCENT", "value": 10,
		                        "applies_to": "ACCOMMODATION", "usage_limit": 1}).insert(ignore_permissions=True)
		revisions.activate("TEX Promotion", promo.name, at="2020-01-01 00:00:00", backdate=True)
		cls.promo = promo.name
		frappe.set_user("Guest")  # nosemgrep: frappe-setuser -- guest booking path
		ci, co = fx.d(8, 20), fx.d(8, 22)
		prop = quoting.search(properties=[fx.PROPERTY], check_in=ci, check_out=co, rooms=[{"adults": 2}],
		                      market="DE", channel="DIRECT_WEB", currency="EUR", promo_codes=["CONCONE"])
		offers = prop["properties"][0]["offers"]
		cls.racers = []
		rt = frappe.db.get_value("Room Type", {"property": fx.PROPERTY, "room_type_code": "STD"})
		offer = next(o for o in offers if o["room_type"] == rt and o["board"] == "AI")
		for _ in range(2):              # plenty of Standard rooms: only the code is contended
			q = quoting.create_quote(offer["rooms"][0]["offer_key"])
			assert any(p["promo_id"] == promo.name and p["applied"] for p in q["quote"]["promotions"]), q
			cls.racers.append(q["quote_id"])
		frappe.set_user("Administrator")  # nosemgrep: frappe-setuser -- test setup
		frappe.db.commit()  # nosemgrep: frappe-manual-commit -- threads need committed fixtures

	@classmethod
	def tearDownClass(cls):
		_cleanup()
		_cleanup_codes()
		super().tearDownClass()

	def test_a_code_used_once_is_used_once(self):
		site, sites_path = frappe.local.site, frappe.local.sites_path
		barrier = threading.Barrier(2)
		results: dict[str, str] = {}

		def race(quote_id: str, who: str):
			frappe.init(site=site, sites_path=sites_path)
			frappe.connect()
			try:
				frappe.set_user("Guest")  # nosemgrep: frappe-setuser -- guest booking path
				barrier.wait(timeout=10)
				booking.create_booking(quote_ids=[quote_id], guest={"first_name": who, "last_name": "Coupon",
				                                                    "email": f"{who}.coupon@example.com"},
				                       payment_method="Card")
				frappe.db.commit()  # nosemgrep: frappe-manual-commit -- each racer is its own request
				results[who] = "booked"
			except frappe.ValidationError as e:
				frappe.db.rollback()
				results[who] = f"refused: {e}"
			finally:
				frappe.destroy()

		threads = [threading.Thread(target=race, args=(q, w)) for q, w in zip(self.racers, ("carol", "dave"),
		                                                                        strict=True)]
		for t in threads:
			t.start()
		for t in threads:
			t.join(timeout=60)
		self.assertEqual(sorted(v.split(":")[0] for v in results.values()), ["booked", "refused"], results)
		self.assertTrue(any("fully redeemed" in v for v in results.values()), results)
		frappe.db.rollback()
		self.assertEqual(frappe.db.count("TEX Promotion Redemption", {
			"promotion": self.promo, "status": ("in", ["Reserved", "Committed"])}), 1)


class TestConcurrentRoomTypes(IntegrationTestCase):
	"""Two agents book two different room types of one hotel at the same instant. Nothing is
	contended, so both bookings go through: neither guest sees a database deadlock."""

	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		frappe.set_user("Administrator")  # nosemgrep: frappe-setuser -- test setup
		_cleanup()
		cls.f = fx.base_setup()
		fx.create_contract(cls.f, code="CONC")
		ci, co = fx.d(8, 20), fx.d(8, 22)
		offers = quoting.search(properties=[fx.PROPERTY], check_in=ci, check_out=co, rooms=[{"adults": 2}],
		                        market="DE", channel="CALL_CENTER", currency="EUR")["properties"][0]["offers"]
		flex = frappe.db.get_value("Rate Plan", {"property": fx.PROPERTY, "code": "FLEX"})
		cls.offer_keys = []
		for code in ("STD", "DLX"):
			rt = frappe.db.get_value("Room Type", {"property": fx.PROPERTY, "room_type_code": code})
			offer = next(o for o in offers if o["room_type"] == rt and o["board"] == "AI" and o["rate_plan"] == flex)
			cls.offer_keys.append(offer["rooms"][0]["offer_key"])
		frappe.db.commit()  # nosemgrep: frappe-manual-commit -- threads need committed fixtures

	@classmethod
	def tearDownClass(cls):
		_cleanup()
		super().tearDownClass()

	def test_different_room_types_book_side_by_side(self):
		from kamra.tex.api import crs as crs_api

		site, sites_path = frappe.local.site, frappe.local.sites_path
		results: dict[str, str] = {}
		for attempt in range(6):          # a deadlock depends on timing: race several times
			frappe.set_user("Administrator")  # nosemgrep: frappe-setuser -- the agents' quotes
			# free the rooms of the previous race (2 Deluxe rooms only)
			frappe.db.sql("UPDATE `tabReservation` SET status='Cancelled' WHERE property=%s", fx.PROPERTY)
			racers = [quoting.create_quote(k)["quote_id"] for k in self.offer_keys]
			frappe.db.commit()  # nosemgrep: frappe-manual-commit -- threads need committed fixtures
			barrier = threading.Barrier(2)

			def race(quote_id: str, who: str, barrier=barrier):
				frappe.init(site=site, sites_path=sites_path)
				frappe.connect()
				try:
					frappe.set_user("Administrator")  # nosemgrep: frappe-setuser -- a call-centre agent
					barrier.wait(timeout=10)
					crs_api.book(quote_ids=[quote_id], guest={"first_name": who, "last_name": "Side",
					                                          "email": f"{who}.side@example.com"},
					             payment_method="Pay at Hotel", confirm_without_payment=1)
					frappe.db.commit()  # nosemgrep: frappe-manual-commit -- each agent is its own request
					results[who] = "booked"
				except Exception as e:
					traceback.print_exc()           # shown with the failure
					frappe.db.rollback()
					results[who] = f"{type(e).__name__}: {e}"
				finally:
					frappe.destroy()

			threads = [threading.Thread(target=race, args=(q, f"{w}{attempt}"))
			           for q, w in zip(racers, ("erin", "frank"), strict=True)]
			for t in threads:
				t.start()
			for t in threads:
				t.join(timeout=60)
			self.assertEqual([results.get(f"{w}{attempt}") for w in ("erin", "frank")], ["booked", "booked"],
			                 results)
			frappe.db.rollback()

	def test_a_deadlock_victim_is_booked_on_the_retry(self):
		from unittest import mock

		from kamra.tex.api import crs as crs_api

		frappe.set_user("Administrator")  # nosemgrep: frappe-setuser -- a call-centre agent
		frappe.db.sql("UPDATE `tabReservation` SET status='Cancelled' WHERE property=%s", fx.PROPERTY)
		quote = quoting.create_quote(self.offer_keys[0])["quote_id"]
		frappe.db.commit()  # nosemgrep: frappe-manual-commit -- the quote outlives the rolled-back attempt
		real, calls = booking.create_booking, []

		def victim_once(**kw):
			out = real(**kw)
			calls.append(out["booking"])
			if len(calls) == 1:           # chosen as the victim after writing: all of it is undone
				raise frappe.QueryDeadlockError("Deadlock found when trying to get lock (simulated)")
			return out

		with mock.patch.object(booking, "create_booking", side_effect=victim_once):
			out = crs_api.book(quote_ids=[quote], guest={"first_name": "Grace", "last_name": "Retry",
			                                             "email": "grace.retry@example.com"},
			                   payment_method="Pay at Hotel", confirm_without_payment=1)
		self.assertEqual(len(calls), 2)               # the rolled-back attempt left nothing behind:
		self.assertEqual(frappe.db.count("TEX Booking", {"booker_email": "grace.retry@example.com"}), 1)
		self.assertEqual(frappe.db.count("Reservation", {"tex_booking": out["booking"]}), 1)
		frappe.db.rollback()


def _cleanup_extras():
	frappe.set_user("Administrator")  # nosemgrep: frappe-setuser -- test cleanup
	frappe.db.sql("DELETE FROM `tabTEX Extra` WHERE property=%s AND extra_code='CONCSPA'", fx.PROPERTY)
	frappe.db.commit()  # nosemgrep: frappe-manual-commit -- test fixture cleanup across connections


class TestConcurrentLastExtra(IntegrationTestCase):
	"""G-19: a spa slot with one unit left, two guests book it at the same instant: exactly one
	gets it. The same slot on two different days: both are booked, without a deadlock."""

	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		frappe.set_user("Administrator")  # nosemgrep: frappe-setuser -- test setup
		_cleanup()
		_cleanup_extras()
		cls.f = fx.base_setup()
		fx.create_contract(cls.f, code="CONC")
		fx.ensure_live("TEX Extra", {"property": fx.PROPERTY, "extra_code": "CONCSPA"}, {
			"property": fx.PROPERTY, "extra_code": "CONCSPA", "extra_name": "Spa slot", "category": "Service",
			"pricing_mode": "UNIT", "currency": "EUR", "amount": 30, "bookable_online": 1, "inventory_tracked": 1,
			"daily_capacity": 1})
		frappe.set_user("Guest")  # nosemgrep: frappe-setuser -- guest booking path
		cls.ci, cls.co = fx.d(8, 20), fx.d(8, 23)
		offers = quoting.search(properties=[fx.PROPERTY], check_in=cls.ci, check_out=cls.co, rooms=[{"adults": 2}],
		                        market="DE", channel="DIRECT_WEB", currency="EUR")["properties"][0]["offers"]
		rt = frappe.db.get_value("Room Type", {"property": fx.PROPERTY, "room_type_code": "STD"})
		cls.key = next(o for o in offers if o["room_type"] == rt and o["board"] == "AI")["rooms"][0]["offer_key"]
		frappe.set_user("Administrator")  # nosemgrep: frappe-setuser -- test setup
		frappe.db.commit()  # nosemgrep: frappe-manual-commit -- threads need committed fixtures

	@classmethod
	def tearDownClass(cls):
		_cleanup()
		_cleanup_extras()
		super().tearDownClass()

	def _race(self, days) -> dict[str, str]:
		frappe.set_user("Guest")  # nosemgrep: frappe-setuser -- the racers' quotes
		quotes = [quoting.create_quote(self.key, extras=[{"code": "CONCSPA", "service_dates": [str(d)]}])
		          for d in days]
		assert all(next(e for e in q["quote"]["extras"] if e["code"] == "CONCSPA")["ok"] for q in quotes), quotes
		frappe.set_user("Administrator")  # nosemgrep: frappe-setuser -- test setup
		frappe.db.commit()  # nosemgrep: frappe-manual-commit -- threads need committed fixtures
		site, sites_path = frappe.local.site, frappe.local.sites_path
		barrier = threading.Barrier(len(quotes))
		results: dict[str, str] = {}

		def race(quote_id: str, who: str):
			frappe.init(site=site, sites_path=sites_path)
			frappe.connect()
			try:
				frappe.set_user("Guest")  # nosemgrep: frappe-setuser -- guest booking path
				barrier.wait(timeout=10)
				booking.create_booking(quote_ids=[quote_id], guest={"first_name": who, "last_name": "Spa",
				                                                    "email": f"{who}.spa@example.com"},
				                       payment_method="Card")
				frappe.db.commit()  # nosemgrep: frappe-manual-commit -- each racer is its own request
				results[who] = "booked"
			except Exception as e:
				frappe.db.rollback()
				results[who] = f"{type(e).__name__}: {e}"
			finally:
				frappe.destroy()

		threads = [threading.Thread(target=race, args=(q["quote_id"], w))
		           for q, w in zip(quotes, ("gina", "hugo"), strict=True)]
		for t in threads:
			t.start()
		for t in threads:
			t.join(timeout=60)
		frappe.db.rollback()
		return results

	def test_one_of_two_simultaneous_bookings_gets_the_last_unit(self):
		results = self._race([self.ci, self.ci])
		self.assertEqual(sorted(v.split(":")[0] for v in results.values()), ["ExtraSoldOut", "booked"], results)
		self.assertEqual(frappe.db.get_value("TEX Extra Inventory Day", {"property": fx.PROPERTY,
		                                                                 "extra_code": "CONCSPA",
		                                                                 "service_date": self.ci}, "sold"), 1)
		self.assertEqual(frappe.db.count("TEX Extra Allocation", {"extra_code": "CONCSPA", "service_date": self.ci,
		                                                          "status": ("!=", "Released")}), 1)

	def test_different_days_book_side_by_side(self):
		d1, d2 = add_days(self.ci, 1), add_days(self.ci, 2)
		self.assertEqual(sorted(self._race([d1, d2]).values()), ["booked", "booked"])


class TestConcurrentPaymentLink(IntegrationTestCase):
	"""O-38 (audit 2B, ADR-065): two ``create_link`` calls with the same idempotency key at the same
	instant (a double click, a retried request) make one link and send one e-mail; the other call is
	answered with that link (``replay``). The database holds one link per key (unique, p57)."""

	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		frappe.set_user("Administrator")  # nosemgrep: frappe-setuser -- test setup
		_cleanup()
		_cleanup_payments()
		cls.f = fx.base_setup()
		fx.create_contract(cls.f, code="CONC")
		frappe.set_user("Guest")  # nosemgrep: frappe-setuser -- guest booking path
		prop = quoting.search(properties=[fx.PROPERTY], check_in=fx.d(8, 20), check_out=fx.d(8, 22),
		                      rooms=[{"adults": 2}], market="DE", channel="DIRECT_WEB", currency="EUR")["properties"][0]
		flex = frappe.db.get_value("Rate Plan", {"property": fx.PROPERTY, "code": "FLEX"})
		offer = next(o for o in prop["offers"] if o["board"] == "AI" and o["rate_plan"] == flex)
		q = quoting.create_quote(offer["rooms"][0]["offer_key"])["quote_id"]
		cls.booking = booking.create_booking(quote_ids=[q], guest={"first_name": "Link", "last_name": "Twice",
		                                                           "email": "link.twice@example.com"},
		                                     payment_method="Pay at Hotel")["booking"]
		frappe.db.commit()  # nosemgrep: frappe-manual-commit -- threads need committed fixtures

	@classmethod
	def tearDownClass(cls):
		_cleanup_payments()
		_cleanup()
		super().tearDownClass()

	def race(self, key: str, **link) -> tuple[list[dict], list[str], int]:
		"""Two staff requests create a link with ``key`` at the same instant; each passes the check for
		an existing link before either inserts. → (their answers, errors, e-mails sent)."""
		from unittest import mock

		from kamra.tex.services import holds

		site, sites_path = frappe.local.site, frappe.local.sites_path
		start, checked = threading.Barrier(2), threading.Barrier(2)
		real = holds.hold_for_link
		answers: list[dict] = []
		errors: list[str] = []

		def after_the_check(*args, **kw):
			checked.wait(timeout=10)                   # both found no link with the key
			return real(*args, **kw)

		def run():
			frappe.init(site=site, sites_path=sites_path)
			frappe.connect()
			try:
				from kamra.tex.payments import service as pay

				frappe.set_user("Administrator")  # nosemgrep: frappe-setuser -- a finance user
				start.wait(timeout=10)
				answers.append(pay.create_link(property=fx.PROPERTY, amount="80", currency="EUR", description="Deposit",
				                               idempotency_key=key, send_email=True, guest_email="o38@example.com",
				                               **link))
				frappe.db.commit()  # nosemgrep: frappe-manual-commit -- each request is its own transaction
			except Exception:
				frappe.db.rollback()
				errors.append(traceback.format_exc())
			finally:
				frappe.destroy()

		with mock.patch("kamra.tex.services.holds.hold_for_link", side_effect=after_the_check), \
				mock.patch("kamra.tex.services.notify.payment_link", return_value=True) as mailed:
			threads = [threading.Thread(target=run) for _ in range(2)]
			for t in threads:
				t.start()
			for t in threads:
				t.join(timeout=60)
		frappe.db.rollback()
		return answers, errors, mailed.call_count

	def assert_one_link(self, key: str, answers: list[dict], errors: list[str], mails: int) -> None:
		from kamra.tex.payments import service as pay

		self.assertEqual(errors, [])
		self.assertEqual(frappe.db.count("TEX Payment Link", {"idempotency_key": pay.ns_key(fx.PROPERTY, key, "link")}), 1)
		self.assertEqual(sorted(bool(a.get("replay")) for a in answers), [False, True])
		self.assertEqual(len({a["link"] for a in answers}), 1)
		self.assertEqual(mails, 1)

	def test_one_standalone_link_per_key(self):
		self.assert_one_link("o38-standalone", *self.race("o38-standalone"))

	def test_one_booking_link_per_key(self):
		self.assert_one_link("o38-booking", *self.race("o38-booking", booking=self.booking))
