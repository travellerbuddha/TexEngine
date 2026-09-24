"""TEX inventory governs a TEX hotel (G-49, R-17, ADR-048).

- A stay TEX sold is never refused afterwards by the legacy physical-room check: explicit
  oversell, shared (pooled) and configured inventory are TEX's to sell.
- A reservation written outside TEX for a TEX hotel takes TEX's inventory lock and is counted
  against TEX's inventory, closures, manual adjustments and withheld allotments: it never
  bypasses them. Since G-92 (ADR-052) the Desk form and REST cannot create one at all; what is
  left outside TEX is a migration import and a status move into a live status (a stay waitlisted
  before the hotel joined TEX).
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
from kamra.tex.services import booking, modification, quoting
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
		"""A reservation written outside TEX. The Desk form and REST cannot create one at a TEX
		hotel since G-92 (ADR-052): what is left is a migration import, at its own amount."""
		from kamra.tex.legacy import flag_import

		doc = frappe.get_doc({"doctype": "Reservation", "property": fx.PROPERTY, "guest": self.guest,
		                      "room_type": self.rt(code), "check_in_date": check_in or self.ci,
		                      "check_out_date": check_out or self.co, "adults": 2, "status": "Confirmed",
		                      "amount_after_tax": 240, **kw})
		flag_import(doc)
		return doc.insert()

	def set_inventory(self, code: str, start=None, end=None, **values):
		"""The staff grid (inventory.edit), by default over every night of the stay."""
		grid.bulk_update(fx.PROPERTY, start or self.nights[0], end or self.nights[-1], room_types=[self.rt(code)],
		                 inventory=values)

	def allot(self, contract: str | None = None, **kw) -> str:
		return frappe.get_doc({"doctype": "TEX Allotment", "property": fx.PROPERTY, "room_type": self.dlx,
		                       "contract": contract or self.c["contract"], "date_from": fx.d(7, 1), "date_to": fx.d(7, 31),
		                       "rooms": 1, "release_days": 7, **kw}).insert().name

	def stay(self, contract, sale_date) -> tuple[int, str]:
		count, per = avail.stay_availability(fx.PROPERTY, self.dlx, contract, self.ci, self.co, sale_date)
		return count, next((d.reason for d in per if d.available < 1), "")

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
	"""Writes outside TEX never bypass a TEX hotel's inventory (G-49). Since G-92 these are
	migration imports and status moves; the Desk form and REST are refused before (ADR-052)."""

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
		from kamra.tex.legacy import flag_import

		doc = frappe.get_doc({"doctype": "Reservation", "property": fx.PROPERTY, "guest": self.guest,
		                      "room_type": "G49 No Such Room Type", "check_in_date": self.ci,
		                      "check_out_date": self.co, "adults": 2, "status": "Confirmed", "amount_after_tax": 240})
		doc.flags.ignore_links = True                    # a write that skipped link validation
		flag_import(doc)
		with self.assertRaisesRegex(frappe.ValidationError, TEX_REFUSAL):
			doc.insert()

	def test_a_closed_night_refuses_an_import(self):
		self.set_inventory("DLX", closed=1)
		with self.assertRaisesRegex(frappe.ValidationError, TEX_REFUSAL):
			self.desk()
		# a Desk or REST insert does not get this far: TEX hotels are booked in TEX (G-92)
		with self.assertRaisesRegex(frappe.ValidationError, "sold through TEX"):
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

	def test_a_stay_moving_into_a_live_status_takes_tex_inventory(self):
		res = self.desk(check_in=fx.d(7, 20), check_out=fx.d(7, 22))
		self.set_inventory("DLX", closed=1)
		res.check_in_date, res.check_out_date = self.ci, self.co
		with self.assertRaisesRegex(frappe.ValidationError, "sold through TEX"):
			res.save()                                   # its nights change only through TEX (G-92)
		wait = self.desk(status="Waitlist")              # a waitlisted stay holds no room
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


# ─── review follow-up (G-49 review) ──────────────────────────────────────


class TestChangesKeepHeldNights(InventoryCase):
	"""H1: a change never loses the nights the stay already holds — a cutoff, a closure or a
	full house on those nights refuses only the nights it would newly take."""

	def pool(self):
		for code in ("STD", "DLX"):
			frappe.db.set_value("Room Type", self.rt(code), "tex_inventory_pool", "G49-POOL")

	def test_a_staff_change_keeps_the_nights_already_held(self):
		res = self.tex_book(who="held")
		# the contract's allotment for the booked nights is now inside its cutoff
		self.allot(date_from=self.ci, date_to=add_days(self.ci, 1), cutoff_days=365)
		longer = modification.propose(res, {"check_out": add_days(self.co, 1)})
		self.assertTrue(longer["sellable"], longer["warnings"])
		modification.apply(longer["proposal_token"], reason="one more night")
		shorter = modification.propose(res, {"check_out": add_days(self.ci, 1)})
		self.assertTrue(shorter["sellable"], shorter["warnings"])
		self.pool()
		other_type = modification.propose(res, {"room_type": self.std})
		self.assertTrue(other_type["sellable"], other_type["warnings"])
		# a night it does not hold yet is still checked: inside the cutoff it is refused
		self.allot(date_from=add_days(self.co, 1), date_to=add_days(self.co, 3), cutoff_days=365)
		cut = modification.propose(res, {"check_out": add_days(self.co, 3)})
		self.assertFalse(cut["sellable"])
		self.assertIn("SOLD_OUT", [w["code"] for w in cut["warnings"]])

	def test_leaving_early_over_closed_nights_is_accepted(self):
		"""M1: a stay covering closed or oversold nights may still be shortened, or moved to
		another room type of the same pool; it takes no new night. Since G-92 (ADR-052) only TEX
		changes a TEX hotel's stay: this is a staff modification."""
		res = self.tex_book(who="early")
		self.set_inventory("DLX", closed=1)                                # every night, after it was sold
		shorter = modification.propose(res, {"check_out": add_days(self.ci, 1)})   # leaves after night 1
		self.assertTrue(shorter["sellable"], shorter["warnings"])
		modification.apply(shorter["proposal_token"], reason="leaves early")
		self.pool()
		self.set_inventory("DLX", self.ci, self.ci, closed=1)               # the pool's row: both types
		other = modification.propose(res, {"room_type": self.std})
		self.assertTrue(other["sellable"], other["warnings"])
		modification.apply(other["proposal_token"], reason="moved to Standard")
		self.assertEqual(frappe.db.get_value("Reservation", res, "room_type"), self.std)


class TestGuestChangeKeepsHeldNights(TexTestCase):
	"""H1 on the guest's manage page: an extension is priced, not refused as sold out, because
	the booked nights fell inside the contract's cutoff."""

	def test_a_guest_extension_keeps_the_nights_already_held(self):
		from kamra.tex.api import public
		from kamra.tex.tests.integration.test_commercial_flows import guest_books, setup_site_and_payments

		setup_site_and_payments(self.f)
		b = guest_books(session="g49-h1", method="Pay at Hotel")
		frappe.set_user("Administrator")  # nosemgrep: frappe-setuser -- the revenue manager sets the cutoff
		res = b["rooms"][0]["reservation"]
		contract, rt = frappe.db.get_value("Reservation", res, ["tex_contract", "room_type"])
		frappe.get_doc({"doctype": "TEX Allotment", "property": fx.PROPERTY, "room_type": rt, "contract": contract,
		                "date_from": fx.d(6, 10), "date_to": fx.d(6, 12), "rooms": 1, "release_days": 7,
		                "cutoff_days": 365}).insert()
		frappe.set_user("Guest")  # nosemgrep: frappe-setuser -- the guest on the manage page
		up = public.manage_propose(token=b["manage_token"], reservation=res, changes={"check_out": str(fx.d(6, 14))})
		self.assertTrue(up["sellable"], up["warnings"])
		self.assertNotIn("SOLD_OUT", [w["code"] for w in up["warnings"]])


class TestRoomTypeBelongsToTheHotel(TestLegacyHotel):
	"""M3: a reservation books its own hotel's room types, in both directions."""

	def test_another_hotels_room_type_is_refused(self):
		with self.assertRaisesRegex(frappe.ValidationError, "does not belong to"):
			frappe.get_doc({"doctype": "Reservation", "property": LEGACY_HOTEL, "guest": self.guest,
			                "room_type": self.dlx, "check_in_date": self.ci, "check_out_date": self.co,
			                "adults": 2, "status": "Confirmed"}).insert()
		from kamra.tex.legacy import flag_import

		doc = frappe.get_doc({"doctype": "Reservation", "property": fx.PROPERTY, "guest": self.guest,
		                      "room_type": self.legacy_rt, "check_in_date": self.ci, "check_out_date": self.co,
		                      "adults": 2, "status": "Confirmed", "amount_after_tax": 240})
		flag_import(doc)                                 # a Desk insert is refused before (G-92)
		with self.assertRaisesRegex(frappe.ValidationError, "does not belong to"):
			doc.insert()
		# nothing of the other hotel's inventory was created under this one
		self.assertFalse(frappe.db.exists("TEX Inventory Day", {"property": fx.PROPERTY,
		                                                        "room_type": self.legacy_rt}))


class TestReviewFollowUps(InventoryCase):
	def test_a_cutoff_before_the_release_gives_the_rooms_back(self):
		"""L2: from the contract's cutoff it can no longer book its rooms, so they go back to
		general sale then, even when its release is later."""
		self.allot(rooms=1, guaranteed=1, release_days=3, cutoff_days=10)
		sale = self.ci - timedelta(days=6)
		self.assertEqual(self.stay(self.c["contract"], sale), (0, "cutoff"))
		self.assertEqual(self.stay(None, sale)[0], 2)                     # not withheld from anyone
		self.assertEqual(self.stay(None, self.ci - timedelta(days=20))[0], 1)   # before the cutoff: withheld

	def test_the_service_flag_is_used_once(self):
		"""L3: a document a TEX service marked as checked is checked again on its next save (here
		a status move into a live status: its nights change only through TEX, G-92)."""
		res = frappe.get_doc({"doctype": "Reservation", "property": fx.PROPERTY, "guest": self.guest,
		                      "room_type": self.dlx, "check_in_date": self.ci, "check_out_date": self.co,
		                      "adults": 2, "status": "Waitlist"})
		res.flags.tex_sale = True                        # as the booking service marks it
		res.flags.tex_inventory_checked = True
		res.insert()
		self.assertNotIn("tex_sale", res.flags)            # each flag covers one save
		self.assertNotIn("tex_inventory_checked", res.flags)
		self.set_inventory("DLX", closed=1)
		res.status = "Confirmed"
		with self.assertRaisesRegex(frappe.ValidationError, TEX_REFUSAL):
			res.save()

	def test_a_deadlock_asks_the_desk_to_try_again(self):
		"""M2: a write outside TEX chosen as a deadlock victim is told to try again (it cannot be
		re-run for it, unlike the TEX endpoints)."""
		from unittest import mock

		with mock.patch.object(avail, "lock_nights", side_effect=frappe.QueryDeadlockError("1213 Deadlock")):
			with self.assertRaisesRegex(frappe.ValidationError, "try again") as caught:
				self.desk()
		self.assertIsInstance(caught.exception, frappe.QueryDeadlockError)   # TEX endpoints still retry it

	def test_every_endpoint_into_a_booking_or_a_change_retries_a_deadlock(self):
		"""M2: a TEX endpoint whose request books or changes a stay (directly, or through the guest
		change service) runs again when it is a deadlock victim: the lock orders of a booking, a
		change and a desk write can still meet (ADR-032, ADR-048)."""
		import ast
		import pathlib

		entry = {("booking_svc", "create_booking"), ("modification", "apply"), ("guest_changes", "submit"),
		         ("guest_changes", "resolve"), ("guest_changes", "pay_again")}
		root = pathlib.Path(frappe.get_app_path("kamra", "tex", "api"))
		checked = []
		for f in sorted(root.glob("*.py")):
			for fn in ast.walk(ast.parse(f.read_text())):
				if not isinstance(fn, ast.FunctionDef):
					continue
				decorators = [ast.unparse(d) for d in fn.decorator_list]
				if not any("whitelist" in d for d in decorators):
					continue
				calls = {(c.func.value.id, c.func.attr) for c in ast.walk(fn) if isinstance(c, ast.Call)
				         and isinstance(c.func, ast.Attribute) and isinstance(c.func.value, ast.Name)}
				if calls & entry:
					checked.append(f"{f.stem}.{fn.name}")
					self.assertIn("retry_on_deadlock", decorators, f"{f.stem}.{fn.name}")
		self.assertGreaterEqual(len(checked), 7, checked)

	def test_a_deadlock_stops_an_import(self):
		"""L1: after a deadlock InnoDB has undone the earlier rows too; the import stops instead of
		reporting them as created."""
		from unittest import mock

		from kamra import api

		rows = [{"guest_name": f"Import {i}", "phone": f"+49 30 55502{i}", "room_type_code": "STD",
		         "check_in": str(self.ci), "check_out": str(self.co), "amount_after_tax": 300} for i in (1, 2)]
		real = api._find_or_create_guest
		calls = []

		def guest(name, phone):
			calls.append(name)
			if len(calls) == 2:
				raise frappe.QueryDeadlockError("1213 Deadlock found when trying to get lock")
			return real(name, phone)

		with mock.patch.object(api, "_find_or_create_guest", side_effect=guest):
			with self.assertRaises(frappe.QueryDeadlockError):
				api.import_bookings(fx.PROPERTY, rows)

	def test_a_disabled_allotment_saves_whatever_its_release(self):
		name = self.allot()
		frappe.db.set_value("TEX Allotment", name, "release_days", 400, update_modified=False)
		doc = frappe.get_doc("TEX Allotment", name)
		with self.assertRaises(frappe.ValidationError):
			doc.save()                                    # a live allotment is brought into range first
		doc.reload()
		doc.disabled = 1
		doc.save()                                        # but it can always be switched off
		self.assertEqual(frappe.db.get_value("TEX Allotment", name, "disabled"), 1)

	def test_boundaries_crossing_today_queue_the_channels(self):
		"""L4: the nights whose release or cutoff starts today are queued for the channels at the
		site's midnight, not only at the daily resync."""
		from unittest import mock

		from kamra.tex.distribution import repository as dist

		self.allot(release_days=7, cutoff_days=3)
		today = fx.d(7, 14)
		with mock.patch.object(dist, "channel_properties", return_value=[fx.PROPERTY]), \
				mock.patch.object(dist, "mark_dirty", return_value=1) as dirty:
			dist.allotment_boundaries(today)
		marked = sorted((c.args[1][0], c.args[2], c.args[3]) for c in dirty.call_args_list)
		self.assertEqual(marked, [(self.dlx, fx.d(7, 16), fx.d(7, 16)), (self.dlx, fx.d(7, 20), fx.d(7, 20))])


def _channel_case():
	from kamra.tex.tests.integration.test_distribution import DistributionCase

	return DistributionCase


class TestChannelLockOrder(_channel_case()):
	"""L1: a channel booking takes every room's nights before it names its booking or rooms —
	the order of a TEX booking and of a desk write — so none of them waits on the others in a
	cycle."""

	def test_a_channel_booking_locks_all_nights_before_any_name(self):
		from unittest import mock

		from frappe.model.document import Document

		from kamra.tex.tests.integration.test_distribution import message

		events = []
		real_lock, real_name = avail.lock_nights, Document.set_new_name

		def lock(prop, requests):
			events.append(("inventory", sorted((str(a), str(b)) for _rt, a, b in requests)))
			return real_lock(prop, requests)

		def name(doc, *a, **kw):
			if doc.doctype in ("TEX Booking", "Reservation"):
				events.append(("name", doc.doctype))
			return real_name(doc, *a, **kw)

		rooms = [{"room_code": "DBL", "rate_code": "BAR", "check_in": str(fx.d(6, 10)), "check_out": str(fx.d(6, 12)),
		          "adults": 2, "total": "300.00", "currency": "EUR", "line_ref": "L1"},
		         {"room_code": "DBL", "rate_code": "BAR", "check_in": str(fx.d(6, 11)), "check_out": str(fx.d(6, 13)),
		          "adults": 2, "total": "300.00", "currency": "EUR", "line_ref": "L2"}]
		self.send(message("OTA-G49", rooms=rooms))
		with mock.patch.object(avail, "lock_nights", lock), mock.patch.object(Document, "set_new_name", name):
			self.apply_all()
		first_name = next(i for i, e in enumerate(events) if e[0] == "name")
		self.assertEqual(events[0][0], "inventory", events)
		self.assertLess(0, first_name)
		self.assertEqual(events[0][1], [(str(fx.d(6, 10)), str(fx.d(6, 12))), (str(fx.d(6, 11)), str(fx.d(6, 13)))],
		                 events)
