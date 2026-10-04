"""A TEX hotel is never priced by the legacy engine (G-92, ADR-052).

- A new reservation at a TEX hotel is created only by TEX: its booking service (CRS, Call
  Center, booking engine) or a channel's sale. The Desk form, REST (``POST
  /api/resource/Reservation``, ``frappe.client.insert``) and data import are refused, whoever
  writes and whatever the status, and nothing a payload carries (flags, pricing source, price
  lock) changes that.
- Migration imports (``import_bookings``, ``migrate.run_import`` with its history rows) keep
  working: the row is recorded as "Imported" at the amount the file carries (Decimal), never
  auto-priced, price-locked and audited.
- The legacy ``Reservation.apply_pricing`` never runs for a TEX hotel.
- An existing reservation at a TEX hotel changes its dates, room type, party, board, rate plan
  or price only through the TEX modification service: the Desk form, REST, ``set_value`` and
  the legacy PMS actions (``amend_stay``, ``move_reservation``) are refused, for a TEX-priced
  stay (price lock) and for a stay the legacy engine sold before the hotel joined TEX alike.
  Other edits (notes, a status) still work.
- A hotel outside TEX keeps the legacy auto-price.
"""

from unittest import mock

import frappe
from frappe.utils import add_days

from kamra.tex.money import D, from_db
from kamra.tex.security import scope
from kamra.tex.services import modification
from kamra.tex.tests.integration import fixtures as fx
from kamra.tex.tests.integration.test_inventory import InventoryCase

LEGACY_HOTEL = "G92 Legacy Hotel"
REFUSED = "sold through TEX"
LOCKED = "price-locked"


class LegacyPricingCase(InventoryCase):
	def setUp(self):
		super().setUp()
		self.desk_user = self.user("g92-desk@example.com", "Front Desk")

	def user(self, email: str, role: str) -> str:
		fx.ensure_user(email, [role])
		fx.ensure("TEX Access Grant", {"user": email, "property": fx.PROPERTY},
		          {"user": email, "scope_level": "Hotel", "property": fx.PROPERTY,
		           "permission_profile": "Reservations Agent"})
		scope.clear_cache()
		return email

	def values(self, **kw) -> dict:
		return {"doctype": "Reservation", "property": fx.PROPERTY, "guest": self.guest, "room_type": self.dlx,
		        "check_in_date": str(self.ci), "check_out_date": str(self.co), "adults": 2, "status": "Confirmed",
		        **kw}

	def count(self) -> int:
		return frappe.db.count("Reservation", {"property": fx.PROPERTY, "guest": self.guest})

	def legacy_stay(self, **kw):
		"""A stay the legacy engine sold before the hotel joined TEX: auto-priced, no TEX lock."""
		with mock.patch("kamra.tex.legacy.is_tex_hotel", return_value=False):
			doc = frappe.get_doc(self.values(**kw)).insert()
		self.assertFalse(doc.tex_price_locked)
		self.assertTrue(doc.amount_after_tax)                # priced by the legacy engine then
		return frappe.get_doc("Reservation", doc.name)

	def legacy_hotel(self) -> dict:
		if not frappe.db.exists("Property", LEGACY_HOTEL):
			frappe.get_doc({"doctype": "Property", "property_name": LEGACY_HOTEL, "city": "Izmir", "country": "Turkey",
			                "currency": "EUR"}).insert(ignore_permissions=True)
		rt = fx.ensure("Room Type", {"property": LEGACY_HOTEL, "room_type_code": "G92"},
		               {"property": LEGACY_HOTEL, "room_type_code": "G92", "room_type_name": "G92 Double",
		                "base_price": 80, "adults_capacity": 2, "children_capacity": 1, "max_total_occupants": 3,
		                "base_occupancy": 2})
		fx.ensure("Room", {"property": LEGACY_HOTEL, "room_number": "G92-1"},
		          {"property": LEGACY_HOTEL, "room_number": "G92-1", "room_type": rt})
		return {"hotel": LEGACY_HOTEL, "room_type": rt}

	def import_row(self, **kw) -> dict:
		return {"guest_name": "Imported Guest", "phone": "+49 30 5550192", "room_type_code": "DLX",
		        "check_in": str(self.ci), "check_out": str(self.co), **kw}


class TestNewReservationsAtATexHotel(LegacyPricingCase):
	"""A reservation for a TEX hotel is created by TEX only."""

	def test_a_desk_insert_is_refused_for_every_role_that_may_create(self):
		for email, role in (("g92-desk@example.com", "Front Desk"), ("g92-admin@example.com", "Hotel Admin"),
		                    ("g92-agent@example.com", "Kamra Agent")):
			user = self.user(email, role)
			self.assertTrue(frappe.has_permission("Reservation", "create", user=user), role)
			frappe.set_user(user)  # nosemgrep: frappe-setuser -- a Desk user who may create reservations
			with self.assertRaisesRegex(frappe.ValidationError, REFUSED, msg=role):
				frappe.get_doc(self.values()).insert()
			frappe.set_user("Administrator")  # nosemgrep: frappe-setuser -- back to the test's user
		# a platform administrator is refused too: the rule is the hotel's, not the user's
		with self.assertRaisesRegex(frappe.ValidationError, REFUSED):
			frappe.get_doc(self.values()).insert()
		self.assertEqual(self.count(), 0)

	def test_every_status_is_refused(self):
		"""A quote or waitlist entry would become a sale later; a history record would count in
		reports and guest stats: none of them is written outside TEX."""
		for status in ("Inquiry", "Quoted", "Requested", "Waitlist", "Held", "Pending Payment", "Checked In",
		               "Checked Out", "Cancelled", "No Show"):
			with self.assertRaisesRegex(frappe.ValidationError, REFUSED, msg=status):
				frappe.get_doc(self.values(status=status)).insert()
		self.assertEqual(self.count(), 0)

	def test_a_rest_insert_is_refused_and_cannot_be_forged(self):
		frappe.set_user(self.desk_user)  # nosemgrep: frappe-setuser -- REST as a Front Desk user
		with self.assertRaisesRegex(frappe.ValidationError, REFUSED):
			frappe.client.insert(self.values())
		# nothing in a payload makes it a TEX sale or an import: flags are not fields
		forged = self.values(auto_price=0, amount_after_tax=1, tex_pricing_source="TEX", tex_price_locked=1,
		                     flags={"tex_sale": True, "tex_import": {"status": "Confirmed"},
		                            "tex_inventory_checked": True})
		with self.assertRaisesRegex(frappe.ValidationError, REFUSED):
			frappe.client.insert(forged)
		with self.assertRaisesRegex(frappe.ValidationError, REFUSED):
			frappe.client.insert(self.values(tex_pricing_source="Imported", tex_price_locked=1, amount_after_tax=1))
		frappe.set_user("Administrator")  # nosemgrep: frappe-setuser -- back to the test's user
		self.assertEqual(self.count(), 0)

	def test_the_legacy_auto_price_never_prices_a_tex_hotel(self):
		doc = frappe.get_doc(self.values(auto_price=1, amount_after_tax=0))
		with mock.patch("kamra.pricing.quote", side_effect=AssertionError("legacy pricing ran")) as legacy:
			doc.apply_pricing()
		legacy.assert_not_called()
		self.assertFalse(doc.amount_after_tax)

	def test_a_tex_crs_booking_is_unaffected(self):
		name = self.tex_book(who="crs")
		res = frappe.get_doc("Reservation", name)
		self.assertEqual((res.tex_pricing_source, res.tex_price_locked, res.auto_price), ("TEX", 1, 0))
		quote_total = frappe.db.get_value("TEX Quote", res.tex_quote, "total_amount")
		self.assertEqual(from_db(res.amount_after_tax, "EUR"), from_db(quote_total, "EUR"))
		# and it changes through the TEX modification service
		p = modification.propose(name, {"check_out": str(add_days(self.co, 1))})
		self.assertTrue(p["sellable"], p["warnings"])
		modification.apply(p["proposal_token"], reason="one more night")
		self.assertEqual(str(frappe.db.get_value("Reservation", name, "check_out_date")), str(add_days(self.co, 1)))


class TestMigrationImports(LegacyPricingCase):
	"""Imports are migrations, not sales: kept, at the amount the file carries."""

	def test_import_bookings_records_the_amount_as_imported(self):
		from kamra.api import import_bookings

		with mock.patch("kamra.pricing.quote", side_effect=AssertionError("legacy pricing ran")):
			out = import_bookings(fx.PROPERTY, [self.import_row(amount_after_tax="312.40")], currency="EUR")
		self.assertEqual(out["created"], 1, out)
		res = frappe.get_doc("Reservation", out["reservations"][0])
		self.assertEqual((res.tex_pricing_source, res.tex_price_locked, res.auto_price), ("Imported", 1, 0))
		self.assertEqual(from_db(res.amount_after_tax, "EUR"), D("312.40"))
		self.assertEqual(from_db(res.tex_total_amount, "EUR"), D("312.40"))
		self.assertEqual(res.tex_currency, "EUR")
		self.assertTrue(res.tex_locked_at)
		audit = frappe.get_all("TEX Audit Event", filters={"action": "reservation.import", "reference_name": res.name},
		                       fields=["new_value", "property"])
		self.assertEqual(len(audit), 1)
		self.assertEqual(audit[0].property, fx.PROPERTY)
		self.assertIn('"amount": "312.40"', audit[0].new_value)
		# an imported stay is price-locked: its dates change only through TEX
		res.check_out_date = add_days(self.co, 1)
		with self.assertRaises(frappe.ValidationError):
			res.save()

	def test_a_live_import_needs_its_amount(self):
		from kamra.api import import_bookings

		with mock.patch("kamra.pricing.quote", side_effect=AssertionError("legacy pricing ran")):
			out = import_bookings(fx.PROPERTY, [self.import_row()], currency="EUR")
		self.assertEqual(out["created"], 0, out)
		self.assertIn("amount", out["errors"][0]["error"])

	def test_run_import_with_history(self):
		from kamra import migrate

		ci, co = self.ci.strftime("%d/%m/%Y"), self.co.strftime("%d/%m/%Y")
		past_ci, past_co = fx.d(5, 20).replace(year=fx.YEAR - 2), fx.d(5, 22).replace(year=fx.YEAR - 2)
		csv_text = ("Guest Name,Mobile No,Room Type,Arrival Date,Departure Date,Adult,Child,Total Amount,"
		            "Reservation Status\n"
		            f"Import Live,+49 30 5550193,DLX,{ci},{co},2,0,\"1,250.50\",Confirmed\n"
		            f"Import Past,+49 30 5550194,DLX,{past_ci:%d/%m/%Y},{past_co:%d/%m/%Y},2,0,480.00,Checked Out\n"
		            f"Import Cancelled,+49 30 5550195,DLX,{ci},{co},2,0,,Cancelled\n")
		with mock.patch("kamra.pricing.quote", side_effect=AssertionError("legacy pricing ran")):
			out = migrate.run_import(fx.PROPERTY, csv_text, "auto", currency="EUR")
		self.assertEqual((out["created"], out["history"]), (3, 2), out)
		rows = {r.guest_name: r for r in frappe.get_all(
			"Reservation", filters={"name": ("in", out["reservations"])},
			fields=["guest_name", "status", "amount_after_tax", "tex_pricing_source", "tex_price_locked", "auto_price"])}
		self.assertEqual(rows["Import Live"].status, "Confirmed")
		self.assertEqual(from_db(rows["Import Live"].amount_after_tax, "EUR"), D("1250.50"))
		self.assertEqual(rows["Import Past"].status, "Checked Out")
		self.assertEqual(from_db(rows["Import Past"].amount_after_tax, "EUR"), D("480.00"))
		self.assertEqual(rows["Import Cancelled"].status, "Cancelled")
		self.assertFalse(rows["Import Cancelled"].amount_after_tax)        # a history record without an amount
		for r in rows.values():
			self.assertEqual((r.tex_pricing_source, r.tex_price_locked, r.auto_price), ("Imported", 1, 0), r)
		self.assertEqual(frappe.db.count("TEX Audit Event", {"action": "reservation.import",
		                                                     "reference_name": ("in", out["reservations"])}), 3)

	def test_an_import_needs_the_right_to_set_a_price_at_the_hotel(self):
		from kamra.api import import_bookings

		# a Hotel Admin whose grant at this hotel only lets them sell (no price.override)
		admin = self.user("g92-hoteladmin@example.com", "Hotel Admin")
		frappe.set_user(admin)  # nosemgrep: frappe-setuser -- a Hotel Admin with a sales profile here
		self.assertFalse(scope.has_capability("price.override", fx.PROPERTY))
		out = import_bookings(fx.PROPERTY, [self.import_row(amount_after_tax="200")], currency="EUR")
		frappe.set_user("Administrator")  # nosemgrep: frappe-setuser -- back to the test's user
		self.assertEqual(out["created"], 0, out)


class TestChangesOutsideTex(LegacyPricingCase):
	"""An existing stay at a TEX hotel changes commercially only through TEX."""

	def tex_stay(self) -> str:
		return self.tex_book(who="locked")

	def assert_refused(self, name: str, pattern: str, **changes):
		doc = frappe.get_doc("Reservation", name)
		doc.update(changes)
		with self.assertRaisesRegex(frappe.ValidationError, pattern, msg=str(changes)):
			doc.save()

	def assert_unchanged(self, name: str, before: dict):
		now = frappe.db.get_value("Reservation", name, list(before), as_dict=True)
		self.assertEqual({k: str(v) for k, v in now.items()}, {k: str(v) for k, v in before.items()})

	def stay_fields(self, name: str) -> dict:
		return frappe.db.get_value("Reservation", name, ["check_in_date", "check_out_date", "room_type", "adults",
		                                                 "amount_after_tax", "property"], as_dict=True)

	def test_a_tex_priced_stay_is_changed_only_by_tex(self):
		name = self.tex_stay()
		before = self.stay_fields(name)
		frappe.set_user(self.desk_user)  # nosemgrep: frappe-setuser -- Desk and REST as a Front Desk user
		for changes in ({"check_out_date": str(add_days(self.co, 1))}, {"room_type": self.std}, {"adults": 1},
		                {"rate_plan": self.f["rate_plans"]["NRF"]}, {"tex_board": "BB"},
		                {"amount_after_tax": 1}):
			self.assert_refused(name, LOCKED, **changes)
		with self.assertRaisesRegex(frappe.ValidationError, LOCKED):
			frappe.client.set_value("Reservation", name, "check_in_date", str(add_days(self.ci, -1)))
		doc = frappe.get_doc("Reservation", name).as_dict()
		doc["room_type"] = self.std
		with self.assertRaisesRegex(frappe.ValidationError, LOCKED):
			frappe.client.save(doc)                          # REST PUT
		frappe.set_user("Administrator")  # nosemgrep: frappe-setuser -- the legacy PMS actions
		from kamra import api

		with self.assertRaisesRegex(frappe.ValidationError, LOCKED):
			api.amend_stay(name, str(self.ci), str(add_days(self.co, 2)))
		std_room = frappe.db.get_value("Room", {"property": fx.PROPERTY, "room_type": self.std})
		with self.assertRaisesRegex(frappe.ValidationError, LOCKED):
			api.move_reservation(name, std_room)
		self.assert_unchanged(name, before)

	def test_a_legacy_stay_at_a_tex_hotel_is_changed_only_by_tex(self):
		name = self.legacy_stay().name
		before = self.stay_fields(name)
		frappe.set_user(self.desk_user)  # nosemgrep: frappe-setuser -- Desk and REST as a Front Desk user
		for changes in ({"check_out_date": str(add_days(self.co, 1))}, {"check_in_date": str(add_days(self.ci, 1))},
		                {"room_type": self.std}, {"adults": 1}, {"children": 1},
		                {"rate_plan": self.f["rate_plans"]["NRF"]}, {"amount_after_tax": 1},
		                {"tex_pricing_source": "TEX"}, {"tex_price_locked": 1}):
			self.assert_refused(name, REFUSED, **changes)
		with self.assertRaisesRegex(frappe.ValidationError, REFUSED):
			frappe.client.set_value("Reservation", name, "check_out_date", str(add_days(self.co, 1)))
		doc = frappe.get_doc("Reservation", name).as_dict()
		doc["room_type"] = self.std
		with self.assertRaisesRegex(frappe.ValidationError, REFUSED):
			frappe.client.save(doc)                          # REST PUT
		frappe.set_user("Administrator")  # nosemgrep: frappe-setuser -- the legacy PMS actions
		from kamra import api

		with mock.patch("kamra.pricing.quote", side_effect=AssertionError("legacy pricing ran")):
			with self.assertRaisesRegex(frappe.ValidationError, REFUSED):
				api.amend_stay(name, str(self.ci), str(add_days(self.co, 2)))
			std_room = frappe.db.get_value("Room", {"property": fx.PROPERTY, "room_type": self.std})
			with self.assertRaisesRegex(frappe.ValidationError, REFUSED):
				api.move_reservation(name, std_room)
		self.assert_unchanged(name, before)

	def test_a_stay_does_not_move_into_or_out_of_a_tex_hotel(self):
		other = self.legacy_hotel()
		# a stay of the legacy hotel moved into the TEX hotel would be a sale outside TEX
		res = frappe.get_doc(self.values(property=other["hotel"], room_type=other["room_type"])).insert()
		res.update({"property": fx.PROPERTY, "room_type": self.dlx})
		with self.assertRaisesRegex(frappe.ValidationError, REFUSED):
			res.save()
		# and a TEX hotel's legacy stay does not leave it to be re-priced there
		name = self.legacy_stay().name
		doc = frappe.get_doc("Reservation", name)
		doc.update({"property": other["hotel"], "room_type": other["room_type"]})
		with mock.patch("kamra.pricing.quote", side_effect=AssertionError("legacy pricing ran")):
			with self.assertRaisesRegex(frappe.ValidationError, REFUSED):
				doc.save()

	def test_other_edits_still_work(self):
		tex, legacy = self.tex_stay(), self.legacy_stay().name
		frappe.set_user(self.desk_user)  # nosemgrep: frappe-setuser -- a Front Desk user
		for name in (tex, legacy):
			doc = frappe.get_doc("Reservation", name)
			doc.special_requests = "Late arrival, quiet room"
			doc.booked_by_name = "Assistant"
			doc.save()
			self.assertEqual(frappe.db.get_value("Reservation", name, "special_requests"), "Late arrival, quiet room")
			frappe.client.set_value("Reservation", name, "special_requests", "Feather-free pillows")
		frappe.set_user("Administrator")  # nosemgrep: frappe-setuser -- test setup
		# a stay waitlisted before the hotel joined TEX is still confirmed (TEX inventory permitting)
		wait = self.legacy_stay(status="Waitlist", room_type=self.std)
		wait.status = "Confirmed"
		wait.save()
		self.assertEqual(frappe.db.get_value("Reservation", wait.name, "status"), "Confirmed")

class TestHotelsOutsideTex(LegacyPricingCase):
	"""A hotel outside TEX keeps the legacy auto-price (the upstream suites rely on it)."""

	def test_2q_a_legacy_booking_and_an_import_take_one_plain_address(self):
		"""Batch 2Q (§6P): the legacy booking page (a hotel outside TEX) and the migration import stored their e-mail with
		a direct write, whatever it was (a display name, a Turkish dotted İ, a trailing dot): a profile no TEX booking
		joins (ADR-080). A guest typing one is refused, as the TEX booking refuses it."""
		from kamra import public_api

		other = self.legacy_hotel()
		stay = {"property": other["hotel"], "room_type": other["room_type"], "check_in_date": str(self.ci),
		        "check_out_date": str(self.co), "guest_name": "Ana Plain", "phone": "+49 30 5550291"}
		with self.assertRaisesRegex(frappe.ValidationError, "one plain e-mail address"):
			public_api.book(**stay, email="Ana <ana.2q@example.de>")
		frappe.clear_messages()
		frappe.set_user("Administrator")  # nosemgrep: frappe-setuser -- back to the test's user
		self.assertFalse(frappe.db.exists("Guest", {"phone": "+49 30 5550291"}))

	def test_2q_an_import_leaves_an_odd_address_out(self):
		"""Batch 2Q (§6P): see the test above; a migration's row is another system's data, so its address is left out."""
		from kamra import migrate

		other = self.legacy_hotel()
		ci, co = self.ci.strftime("%d/%m/%Y"), self.co.strftime("%d/%m/%Y")
		csv_text = ("Guest Name,Mobile No,Email,Room Type,Arrival Date,Departure Date,Adult,Child,Total Amount\n"
		            f"Odd Address,+49 30 5550292,İNFO.2Q@HOTEL.COM,G92,{ci},{co},2,0,180.00\n")
		out = migrate.run_import(other["hotel"], csv_text, "auto", currency="EUR")
		self.assertEqual(out["created"], 1, out)
		guest = frappe.db.get_value("Reservation", out["reservations"][0], "guest")
		self.assertFalse(frappe.db.get_value("Guest", guest, "email"))

	def test_a_legacy_hotel_is_still_auto_priced(self):
		from kamra.pricing import quote
		from kamra.tex.legacy import is_tex_hotel

		other = self.legacy_hotel()
		self.assertFalse(is_tex_hotel(other["hotel"]))
		res = frappe.get_doc(self.values(property=other["hotel"], room_type=other["room_type"])).insert()
		q = quote(property=other["hotel"], room_type=other["room_type"], check_in_date=str(self.ci),
		          check_out_date=str(self.co), adults=2, children=0, meal_plan=None, rate_plan=None, voucher_code=None)
		self.assertTrue(q["amount_after_tax"])
		self.assertEqual(from_db(res.amount_after_tax, "EUR"), from_db(q["amount_after_tax"], "EUR"))
		self.assertFalse(res.tex_pricing_source)
		# re-priced when its stay changes, as before
		res.check_out_date = add_days(self.co, 1)
		res.save()
		self.assertGreater(from_db(res.amount_after_tax, "EUR"), from_db(q["amount_after_tax"], "EUR"))

	def test_a_legacy_hotels_import_is_unchanged(self):
		from kamra.api import import_bookings

		other = self.legacy_hotel()
		code = frappe.db.get_value("Room Type", other["room_type"], "room_type_code")
		later = {"check_in": str(add_days(self.co, 5)), "check_out": str(add_days(self.co, 7))}   # one room
		out = import_bookings(other["hotel"], [self.import_row(room_type_code=code),
		                                       self.import_row(room_type_code=code, guest_name="Fixed Amount",
		                                                       amount_after_tax="99.90", **later)])
		self.assertEqual(out["created"], 2, out)
		auto, fixed = (frappe.get_doc("Reservation", n) for n in out["reservations"])
		self.assertEqual((auto.auto_price, fixed.auto_price), (1, 0))
		self.assertTrue(auto.amount_after_tax)                            # priced by the legacy engine
		self.assertEqual(from_db(fixed.amount_after_tax, "EUR"), D("99.90"))
		self.assertFalse(auto.tex_pricing_source or fixed.tex_pricing_source)
