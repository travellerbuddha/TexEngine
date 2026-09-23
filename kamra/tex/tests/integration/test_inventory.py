"""TEX inventory governs a TEX hotel (G-49, R-17, ADR-048).

- A stay TEX sold is never refused afterwards by the legacy physical-room check: explicit
  oversell, shared (pooled) and configured inventory are TEX's to sell.
- A reservation written outside TEX (Desk form, REST, legacy import, legacy PMS actions) for a
  TEX hotel takes TEX's inventory lock and is counted against TEX's inventory, closures,
  manual adjustments and withheld allotments: it never bypasses them.
- A hotel outside TEX keeps the legacy overbooking check.
- Allotments: consumption, release (rooms back to general sale) and the separate cutoff (the
  contract's booking deadline); oversell limit and manual adjustment.
"""

from datetime import timedelta

import frappe
from frappe.utils import add_days, getdate

from kamra.tex.api import policies as policy_api
from kamra.tex.availability import repository as avail
from kamra.tex.commercial import grid
from kamra.tex.security import scope
from kamra.tex.services import booking, quoting
from kamra.tex.tests.integration import fixtures as fx
from kamra.tex.tests.integration.test_critical_journey import TexTestCase

LEGACY_HOTEL = "G49 Legacy Hotel"
TEX_REFUSAL = "TEX inventory"


class InventoryCase(TexTestCase):
	def setUp(self):
		super().setUp()
		self.c = fx.create_contract(self.f)
		self.std, self.dlx = self.f["room_types"]["STD"], self.f["room_types"]["DLX"]
		self.ci, self.co = fx.d(7, 10), fx.d(7, 12)
		self.nights = [self.ci, add_days(self.ci, 1)]
		from kamra.api import _find_or_create_guest

		self.guest = _find_or_create_guest("Desk Guest", "+49 30 5550149")

	def rt(self, code: str) -> str:
		return self.f["room_types"][code]

	def entry(self, code: str = "DLX") -> dict | None:
		"""The staff search's FLEX all-inclusive entry for a room type (bookable or not)."""
		res = quoting.search(properties=[fx.PROPERTY], check_in=self.ci, check_out=self.co, rooms=[{"adults": 2}],
		                     market="DE", channel="CALL_CENTER", currency="EUR")["properties"][0]
		flex = self.f["rate_plans"]["FLEX"]
		for e in res["offers"] + res["unavailable"]:
			if e["room_type"] == self.rt(code) and e["board"] == "AI" and e["rate_plan"] == flex:
				return e
		return None

	def available(self, code: str = "DLX") -> int:
		e = self.entry(code)
		return int(e["available"]) if e else 0

	def quote(self, code: str = "DLX") -> str:
		e = self.entry(code)
		self.assertTrue(e and e["rooms"], f"no bookable {code} offer: {e}")
		q = quoting.create_quote(e["rooms"][0]["offer_key"])
		self.assertTrue(q["ok"], q)
		return q["quote_id"]

	def tex_book(self, code: str = "DLX", who: str = "guest", quote_id: str | None = None) -> str:
		"""A call-centre booking through TEX (confirmed, pay at hotel)."""
		b = booking.create_booking(quote_ids=[quote_id or self.quote(code)],
		                           guest={"first_name": who, "last_name": "Inventory",
		                                  "email": f"{who}.g49@example.com"},
		                           payment_method="Pay at Hotel", confirm_without_payment=True)
		return b["rooms"][0]["reservation"]

	def desk(self, code: str = "DLX", check_in=None, check_out=None, **kw):
		"""A reservation written outside TEX: what the Desk form, REST or an import insert."""
		return frappe.get_doc({"doctype": "Reservation", "property": fx.PROPERTY, "guest": self.guest,
		                       "room_type": self.rt(code), "check_in_date": check_in or self.ci,
		                       "check_out_date": check_out or self.co, "adults": 2, "status": "Confirmed",
		                       **kw}).insert()

	def set_inventory(self, code: str, **values):
		"""The staff grid (inventory.edit) over every night of the stay."""
		grid.bulk_update(fx.PROPERTY, self.nights[0], self.nights[-1], room_types=[self.rt(code)], inventory=values)

	def live(self, code: str = "DLX") -> int:
		return frappe.db.count("Reservation", {"property": fx.PROPERTY, "room_type": self.rt(code),
		                                       "status": ("in", ["Confirmed", "Checked In", "Held",
		                                                          "Pending Payment"])})


class TestTexSalesAreTexInventory(InventoryCase):
	"""A stay TEX allowed is never refused by the legacy physical-room check (G-49)."""

	def test_explicit_oversell_is_sold_and_stays_saveable(self):
		self.tex_book(who="one")
		self.tex_book(who="two")                         # both Deluxe rooms sold
		self.assertEqual(self.available(), 0)
		self.set_inventory("DLX", oversell_limit=1)      # the revenue manager allows one more
		self.assertEqual(self.available(), 1)
		first, second = self.quote(), self.quote()       # two agents quote the last oversold room
		oversold = self.tex_book(who="three", quote_id=first)
		self.assertEqual(self.live(), 3)
		# the oversold stay is an ordinary stay afterwards: saving it is never refused
		res = frappe.get_doc("Reservation", oversold)
		res.special_requests = "quiet room"
		res.save()
		# the oversell limit is a limit: the other agent's quote is refused, and so is a desk stay
		with self.assertRaisesRegex(frappe.ValidationError, "sold out"):
			self.tex_book(who="four", quote_id=second)
		with self.assertRaisesRegex(frappe.ValidationError, TEX_REFUSAL):
			self.desk()
		self.assertEqual(self.live(), 3)

	def test_pooled_inventory_is_sold_by_tex(self):
		for code in ("STD", "DLX"):
			frappe.db.set_value("Room Type", self.rt(code), "tex_inventory_pool", "G49-POOL")
		self.tex_book(who="one")
		self.tex_book(who="two")
		self.assertEqual(self.available("DLX"), 6)       # 6 Standard + 2 Deluxe rooms, shared
		self.tex_book(who="three")                       # a third Deluxe from the shared pool
		self.assertEqual(self.live("DLX"), 3)
		self.assertEqual(self.available("STD"), 5)       # the pool is shared both ways

	def test_configured_inventory_is_sold_by_tex(self):
		frappe.db.set_value("Property", fx.PROPERTY, "tex_inventory_mode", "Configured")
		frappe.db.set_value("Room Type", self.rt("DLX"), "tex_sellable_inventory", 3)
		frappe.db.set_value("Room Type", self.rt("STD"), "tex_sellable_inventory", 6)
		self.tex_book(who="one")
		self.tex_book(who="two")
		self.assertEqual(self.available(), 1)            # 3 configured, 2 physical rooms
		self.tex_book(who="three")
		self.assertEqual(self.live(), 3)
		with self.assertRaisesRegex(frappe.ValidationError, TEX_REFUSAL):
			self.desk()


class TestOutsideTexReservations(InventoryCase):
	"""Desk, REST and imports never bypass a TEX hotel's inventory (G-49)."""

	def test_a_desk_stay_is_counted_by_tex(self):
		self.desk()
		self.assertEqual(self.available(), 1)

	def test_a_desk_insert_locks_the_nights_before_it_takes_a_name(self):
		"""The lock order of a TEX booking: inventory days first, then the reservation's naming
		series row. A desk insert in the opposite order could deadlock with a TEX booking."""
		from unittest import mock

		from frappe.model.document import Document

		order = []
		real_lock, real_name = avail.lock_nights, Document.set_new_name

		def lock(*a, **kw):
			order.append("inventory")
			return real_lock(*a, **kw)

		def name(doc, *a, **kw):
			order.append(f"name {doc.doctype}")
			return real_name(doc, *a, **kw)

		with mock.patch.object(avail, "lock_nights", lock), mock.patch.object(Document, "set_new_name", name):
			self.desk()
		self.assertEqual(order[:2], ["inventory", "name Reservation"])

	def test_an_unknown_room_type_is_refused_cleanly(self):
		doc = frappe.get_doc({"doctype": "Reservation", "property": fx.PROPERTY, "guest": self.guest,
		                      "room_type": "G49 No Such Room Type", "check_in_date": self.ci,
		                      "check_out_date": self.co, "adults": 2, "status": "Confirmed"})
		doc.flags.ignore_links = True                    # a write that skipped link validation
		with self.assertRaisesRegex(frappe.ValidationError, TEX_REFUSAL):
			doc.insert()

	def test_a_closed_night_refuses_desk_and_rest(self):
		self.set_inventory("DLX", closed=1)
		with self.assertRaisesRegex(frappe.ValidationError, TEX_REFUSAL):
			self.desk()
		with self.assertRaisesRegex(frappe.ValidationError, TEX_REFUSAL):
			frappe.client.insert({"doctype": "Reservation", "property": fx.PROPERTY, "guest": self.guest,
			                      "room_type": self.dlx, "check_in_date": str(self.ci),
			                      "check_out_date": str(self.co), "adults": 2, "status": "Confirmed"})
		self.assertEqual(self.live(), 0)

	def test_manual_adjustment_moves_what_everyone_may_sell(self):
		self.set_inventory("DLX", manual_adjustment=-1)  # one Deluxe room out of order
		self.desk()
		with self.assertRaisesRegex(frappe.ValidationError, TEX_REFUSAL):
			self.desk()
		self.assertEqual(self.available(), 0)
		self.set_inventory("DLX", manual_adjustment=1)   # a connecting room sold as Deluxe
		self.assertEqual(self.available(), 2)
		self.tex_book(who="one")
		self.tex_book(who="two")                         # 3 of 2 physical rooms: TEX's decision
		self.assertEqual(self.live(), 3)
		audit = frappe.get_all("TEX Audit Event", filters={"action": "grid.bulk_update", "property": fx.PROPERTY},
		                       pluck="new_value", order_by="creation desc", limit=1)
		self.assertIn('"manual_adjustment": 1', audit[0] if audit else "")      # inventory edits are audited

	def test_a_guaranteed_allotment_is_withheld_from_desk_stays(self):
		frappe.get_doc({"doctype": "TEX Allotment", "property": fx.PROPERTY, "room_type": self.dlx,
		                "contract": self.c["contract"], "date_from": fx.d(7, 1), "date_to": fx.d(7, 31), "rooms": 1,
		                "release_days": 7, "guaranteed": 1}).insert()
		self.desk()
		with self.assertRaisesRegex(frappe.ValidationError, TEX_REFUSAL):
			self.desk()                                  # the last room is held for the contract
		self.tex_book(who="partner")                     # and the contract still gets it
		self.assertEqual(self.live(), 2)

	def test_moving_a_desk_stay_takes_tex_inventory(self):
		res = self.desk(check_in=fx.d(7, 20), check_out=fx.d(7, 22))
		self.set_inventory("DLX", closed=1)
		res.check_in_date, res.check_out_date = self.ci, self.co
		with self.assertRaisesRegex(frappe.ValidationError, TEX_REFUSAL):
			res.save()
		wait = self.desk(check_in=fx.d(7, 20), check_out=fx.d(7, 22), status="Waitlist")
		wait.reload()
		wait.update({"check_in_date": self.ci, "check_out_date": self.co})
		wait.save()                                      # a waitlisted stay holds no room
		wait.status = "Confirmed"
		with self.assertRaisesRegex(frappe.ValidationError, TEX_REFUSAL):
			wait.save()

	def test_the_legacy_import_takes_tex_inventory(self):
		from kamra.api import import_bookings

		self.set_inventory("DLX", closed=1)
		row = {"guest_name": "Imported Guest", "phone": "+49 30 5550150", "room_type_code": "DLX",
		       "check_in": str(self.ci), "check_out": str(self.co), "amount_after_tax": 300}
		out = import_bookings(fx.PROPERTY, [row])
		self.assertEqual(out["created"], 0)
		self.assertIn(TEX_REFUSAL, out["errors"][0]["error"])
		self.set_inventory("DLX", closed=0)
		self.assertEqual(import_bookings(fx.PROPERTY, [row])["created"], 1)
		self.assertEqual(self.available(), 1)

	def test_a_stay_that_takes_no_room_is_never_refused(self):
		res = self.desk()
		self.set_inventory("DLX", closed=1)              # closed after it was sold
		res.special_requests = "late arrival"
		res.save()
		res.reload()
		self.assertEqual(res.special_requests, "late arrival")


class TestLegacyHotel(InventoryCase):
	"""A hotel outside TEX keeps the legacy check; TEX inventory rows do not change it."""

	def setUp(self):
		super().setUp()
		if not frappe.db.exists("Property", LEGACY_HOTEL):
			frappe.get_doc({"doctype": "Property", "property_name": LEGACY_HOTEL, "city": "Izmir", "country": "Turkey",
			                "currency": "EUR"}).insert(ignore_permissions=True)
		frappe.db.set_value("Property", LEGACY_HOTEL, "overbooking_pct", 0)
		self.legacy_rt = fx.ensure("Room Type", {"property": LEGACY_HOTEL, "room_type_code": "G49"},
		                           {"property": LEGACY_HOTEL, "room_type_code": "G49", "room_type_name": "G49 Double",
		                            "base_price": 80, "adults_capacity": 2, "children_capacity": 1,
		                            "max_total_occupants": 3, "base_occupancy": 2})
		fx.ensure("Room", {"property": LEGACY_HOTEL, "room_number": "G49-1"},
		          {"property": LEGACY_HOTEL, "room_number": "G49-1", "room_type": self.legacy_rt})

	def legacy_stay(self):
		return frappe.get_doc({"doctype": "Reservation", "property": LEGACY_HOTEL, "guest": self.guest,
		                       "room_type": self.legacy_rt, "check_in_date": self.ci, "check_out_date": self.co,
		                       "adults": 2, "status": "Confirmed"}).insert()

	def test_the_legacy_overbooking_check_still_applies(self):
		from kamra.tex.legacy import is_tex_hotel

		self.assertFalse(is_tex_hotel(LEGACY_HOTEL))
		from kamra.tex_commercial.doctype.tex_inventory_day.tex_inventory_day import inventory_day_name

		for night in self.nights:                        # a TEX row means nothing outside TEX
			frappe.get_doc({"doctype": "TEX Inventory Day", "name": inventory_day_name(self.legacy_rt, night),
			                "property": LEGACY_HOTEL, "room_type": self.legacy_rt, "inventory_date": night,
			                "oversell_limit": 5}).insert(ignore_permissions=True)
		self.legacy_stay()
		with self.assertRaisesRegex(frappe.ValidationError, "overbooking allowance"):
			self.legacy_stay()


class TestAllotments(InventoryCase):
	"""Allotment consumption, release and cutoff (G-49)."""

	def allot(self, **kw) -> str:
		return frappe.get_doc({"doctype": "TEX Allotment", "property": fx.PROPERTY, "room_type": self.dlx,
		                       "contract": self.c["contract"], "date_from": fx.d(7, 1), "date_to": fx.d(7, 31),
		                       "rooms": 1, "release_days": 7, **kw}).insert().name

	def stay(self, contract, sale_date) -> tuple[int, str]:
		count, per = avail.stay_availability(fx.PROPERTY, self.dlx, contract, self.ci, self.co, sale_date)
		return count, next((d.reason for d in per if d.available < 1), "")

	def test_an_allotment_caps_its_contract_and_is_consumed(self):
		self.allot()
		self.assertEqual(self.available(), 1)            # 2 rooms, the contract's allotment is 1
		res = self.tex_book(who="partner")
		self.assertEqual(frappe.db.get_value("Reservation", res, "tex_contract"), self.c["contract"])
		self.assertEqual(self.stay(self.c["contract"], getdate()), (0, "allotment used"))
		self.assertEqual(self.stay(None, getdate())[0], 1)          # the hotel still has a room
		self.assertEqual(self.available(), 0)
		# at the release the cap ends: the contract sells what general sale has left
		self.assertEqual(self.stay(self.c["contract"], self.ci - timedelta(days=5))[0], 1)

	def test_a_guaranteed_allotment_is_withheld_until_release(self):
		self.allot(rooms=2, guaranteed=1)
		self.assertEqual(self.stay(None, getdate()), (0, "sold out"))  # both Deluxe rooms held for the partner
		self.assertEqual(self.stay(self.c["contract"], getdate())[0], 2)
		self.assertEqual(self.stay(None, self.ci - timedelta(days=5))[0], 2)   # both nights released

	def test_release_and_cutoff_are_separate(self):
		self.allot(rooms=1, guaranteed=1, release_days=7, cutoff_days=3)
		contract = self.c["contract"]
		self.assertEqual(self.stay(contract, self.ci - timedelta(days=10))[0], 1)   # its allotment
		self.assertEqual(self.stay(None, self.ci - timedelta(days=10))[0], 1)       # 1 withheld of 2
		self.assertEqual(self.stay(contract, self.ci - timedelta(days=5))[0], 2)    # released, until the cutoff
		self.assertEqual(self.stay(contract, self.ci - timedelta(days=2)), (0, "cutoff"))
		self.assertEqual(self.stay(None, self.ci - timedelta(days=2))[0], 2)        # others still sell

	def test_allotments_are_edited_with_inventory_edit_only(self):
		rm = fx.ensure_user("g49-revenue@example.com", ["Revenue Manager"])
		agent = fx.ensure_user("g49-agent@example.com", ["Call Center Agent"])
		for user, profile in ((rm, "Revenue Manager"), (agent, "Reservations Agent")):
			fx.ensure("TEX Access Grant", {"user": user, "property": fx.PROPERTY},
			          {"user": user, "scope_level": "Hotel", "property": fx.PROPERTY, "permission_profile": profile})
		scope.clear_cache()
		data = {"property": fx.PROPERTY, "room_type": self.dlx, "contract": self.c["contract"],
		        "date_from": str(fx.d(7, 1)), "date_to": str(fx.d(7, 31)), "rooms": 1, "release_days": 7,
		        "cutoff_days": 2}
		frappe.set_user(agent)  # nosemgrep: frappe-setuser -- sells, does not manage inventory
		with self.assertRaises(frappe.PermissionError):
			policy_api.save_record("TEX Allotment", data)
		frappe.set_user(rm)  # nosemgrep: frappe-setuser -- the revenue manager
		saved = policy_api.save_record("TEX Allotment", data)
		self.assertEqual((saved["release_days"], saved["cutoff_days"]), (7, 2))
		for bad in ({"cutoff_days": -1}, {"release_days": -3}, {"cutoff_days": 400}):
			with self.assertRaises(frappe.ValidationError, msg=bad):
				policy_api.save_record("TEX Allotment", {**data, **bad})
		self.assertTrue(frappe.db.exists("TEX Audit Event", {"action": "tex_allotment.save",
		                                                     "reference_name": saved["name"]}))

	def test_the_upgrade_keeps_allotments_selling_as_before(self):
		from unittest import mock

		from kamra.patches.tex import p27_inventory_cutoff_release as p27

		kept = self.allot(release_days=7)
		broken = self.allot(release_days=7)
		# written below the controller, as a pre-G-49 row could be
		frappe.db.set_value("TEX Allotment", broken, {"release_days": -2, "cutoff_days": -1}, update_modified=False)
		with mock.patch("frappe.reload_doc"):              # no schema sync (DDL commits) in a test
			p27.execute()
			p27.execute()                                  # runs again safely
		self.assertEqual(frappe.db.get_value("TEX Allotment", kept, ["release_days", "cutoff_days"]), (7, 0))
		self.assertEqual(frappe.db.get_value("TEX Allotment", broken, ["release_days", "cutoff_days"]), (0, 0))
