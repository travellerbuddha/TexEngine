"""G-92 review follow-up (ADR-052 review section) and G-96.

- H1: migration amounts are read strictly (one parser for both importers), shown in the preview
  before anything is written, and an imported amount can be corrected with ``price.override``, a
  reason, a revision and an audit event.
- H2 / G-96: the legacy check-out never bills a TEX-sold or imported stay at the legacy Room Type
  rate. A stay TEX sold is billed on its TEX booking: the legacy folio posts none of its nights. A
  stay imported without a TEX booking posts its locked amount, split over its nights.
- M1: an ``import_bookings`` row that fails leaves nothing behind; Cancelled and Checked In rows
  are stamped like ``run_import``'s history rows.
- M2: an imported stay's cancellation fee is taken from its locked amount (legacy and TEX cancel).
- M3: a hotel joining TEX keeps selling at the Desk until an administrator sets it live in TEX.
- L1: the TEX modification flag covers one save; there is no request-wide bypass.
- L3: an import at a TEX hotel says which currency its amounts are in.
"""

from unittest import mock

import frappe
from frappe.utils import add_days, getdate, now_datetime, nowdate

from kamra.tex.money import D, from_db
from kamra.tex.security import scope
from kamra.tex.tests.integration import fixtures as fx
from kamra.tex.tests.integration.test_legacy_pricing import REFUSED, LegacyPricingCase

ONBOARDING = "G92 Onboarding Hotel"


def charges(reservation: str, types=("Room", "Meal Plan", "Discount", "Cleaning Fee", "Misc")) -> list[dict]:
	folios = frappe.get_all("Folio", filters={"reservation": reservation}, pluck="name")
	return frappe.get_all("Folio Charge", filters={"parent": ("in", folios or [""]), "charge_type": ("in", types)},
	                      fields=["charge_type", "amount", "gst_rate", "posting_date", "description"],
	                      order_by="posting_date asc, idx asc")


class ReviewCase(LegacyPricingCase):
	def imported(self, amount="312.40", currency="EUR", **kw) -> str:
		from kamra.api import import_bookings

		out = import_bookings(fx.PROPERTY, [self.import_row(amount_after_tax=amount, **kw)], currency=currency)
		self.assertEqual(out["created"], 1, out)
		return out["reservations"][0]

	def room(self, room_type: str) -> str:
		return frappe.db.get_value("Room", {"property": fx.PROPERTY, "room_type": room_type}, "name")

	def csv(self, *rows: str, header="Guest Name,Mobile No,Room Type,Arrival Date,Departure Date,Adult,Total Amount,"
	                                  "Reservation Status") -> str:
		return header + "\n" + "\n".join(rows) + "\n"

	def dates(self, offset=0) -> tuple[str, str]:
		return (add_days(self.ci, offset).strftime("%d/%m/%Y"), add_days(self.co, offset).strftime("%d/%m/%Y"))


# ─── H1 · amounts read strictly, previewed, correctable ─────────────────


class TestImportAmounts(ReviewCase):
	def test_run_import_reads_amounts_strictly(self):
		from kamra import migrate

		ci, co = self.dates()
		rows = [f"Comma decimal,+49 30 5550201,DLX,{ci},{co},2,\"150,00\",Confirmed",
		        f"Dot thousands,+49 30 5550202,STD,{ci},{co},2,\"1.250,50\",Confirmed",
		        f"Ambiguous,+49 30 5550203,STD,{ci},{co},2,TL 1.500,Confirmed",
		        f"Rupees,+49 30 5550204,STD,{ci},{co},2,\"Rs. 1,500\",Confirmed",
		        f"Negative,+49 30 5550205,STD,{ci},{co},2,-120,Confirmed",
		        f"Garbage,+49 30 5550206,STD,{ci},{co},2,12a,Confirmed"]
		out = migrate.run_import(fx.PROPERTY, self.csv(*rows), "auto", currency="EUR")
		amounts = {r.guest_name: from_db(r.amount_after_tax, "EUR") for r in frappe.get_all(
			"Reservation", filters={"name": ("in", out["reservations"])}, fields=["guest_name", "amount_after_tax"])}
		self.assertEqual(amounts, {"Comma decimal": D("150.00"), "Dot thousands": D("1250.50")}, out)
		errors = {e["guest"]: e["error"] for e in out["errors"]}
		self.assertIn("ambiguous", errors["Ambiguous"])
		self.assertIn("ambiguous", errors["Rupees"])
		self.assertIn("negative", errors["Negative"])
		self.assertIn("not an amount", errors["Garbage"])

	def test_the_import_says_which_decimal_mark_it_uses(self):
		from kamra import migrate

		ci, co = self.dates()
		out = migrate.run_import(fx.PROPERTY, self.csv(f"Lira,+49 30 5550207,STD,{ci},{co},2,TL 1.500,Confirmed"),
		                         "auto", decimal=",", currency="TRY")
		self.assertEqual(out["created"], 1, out)
		res = frappe.get_doc("Reservation", out["reservations"][0])
		self.assertEqual((from_db(res.amount_after_tax, "TRY"), res.tex_currency), (D("1500.00"), "TRY"))

	def test_the_preview_shows_each_rows_amount_and_currency(self):
		from kamra import migrate

		ci, co = self.dates()
		p = migrate.preview_import(fx.PROPERTY, self.csv(f"Shown,+49 30 5550208,STD,{ci},{co},2,\"€ 1.250,50\",Confirmed",
		                                                 f"Refused,+49 30 5550209,STD,{ci},{co},2,\"1,500\",Confirmed"),
		                           "auto", currency="EUR")
		self.assertEqual((p["ok"], p["skipped"]), (1, 1), p)
		self.assertEqual((p["sample"][0]["amount"], p["sample"][0]["currency"]), ("1250.50", "EUR"))
		self.assertIn("ambiguous", p["issues"][0]["error"])
		self.assertEqual(frappe.db.count("Reservation", {"guest_name": "Shown"}), 0)      # nothing written

	def test_both_importers_read_the_same_way(self):
		"""L2: "10,500.50" is 10500.50 in import_bookings too, at a hotel outside TEX as before."""
		from kamra.api import import_bookings

		other = self.legacy_hotel()
		code = frappe.db.get_value("Room Type", other["room_type"], "room_type_code")
		out = import_bookings(other["hotel"], [self.import_row(room_type_code=code, amount_after_tax="10,500.50")])
		self.assertEqual(out["created"], 1, out)
		self.assertEqual(from_db(frappe.db.get_value("Reservation", out["reservations"][0], "amount_after_tax"),
		                         "EUR"), D("10500.50"))
		out = import_bookings(other["hotel"], [self.import_row(room_type_code=code, amount_after_tax="1,500",
		                                                       check_in=str(add_days(self.co, 5)),
		                                                       check_out=str(add_days(self.co, 6)))])
		self.assertIn("ambiguous", out["errors"][0]["error"])

	def test_an_imported_amount_is_corrected_with_a_reason(self):
		from kamra.tex.api import crs

		name = self.imported("15000.00")                   # the file said "150,00"
		agent = self.user("g92r-agent@example.com", "Front Desk")      # sells, no price.override
		frappe.set_user(agent)  # nosemgrep: frappe-setuser -- a sales agent
		with self.assertRaises(frappe.PermissionError):
			crs.correct_imported_amount(reservation=name, amount="150.00", reason="file used a decimal comma")
		frappe.set_user("Administrator")  # nosemgrep: frappe-setuser -- the revenue manager
		with self.assertRaisesRegex(frappe.ValidationError, "reason"):
			crs.correct_imported_amount(reservation=name, amount="150.00", reason=" ")
		with self.assertRaisesRegex(frappe.ValidationError, "negative"):
			crs.correct_imported_amount(reservation=name, amount="-1", reason="typo")
		out = crs.correct_imported_amount(reservation=name, amount="150.00", reason="file used a decimal comma")
		self.assertEqual((out["old_amount"], out["new_amount"], out["currency"]), ("15000.00", "150.00", "EUR"))
		res = frappe.get_doc("Reservation", name)
		self.assertEqual((from_db(res.amount_after_tax, "EUR"), from_db(res.tex_total_amount, "EUR")),
		                 (D("150.00"), D("150.00")))
		self.assertEqual((res.tex_pricing_source, res.tex_price_locked), ("Imported", 1))
		rev = frappe.get_all("TEX Reservation Revision", filters={"reservation": name},
		                     fields=["change_type", "old_amount", "new_amount", "reason"])
		self.assertEqual(len(rev), 1)
		self.assertEqual((rev[0].change_type, rev[0].reason), ("Price Override", "file used a decimal comma"))
		self.assertEqual((from_db(rev[0].old_amount, "EUR"), from_db(rev[0].new_amount, "EUR")),
		                 (D("15000.00"), D("150.00")))
		self.assertTrue(frappe.db.exists("TEX Audit Event", {"action": "reservation.import_correct",
		                                                     "reference_name": name}))
		# only an imported stay is corrected this way: a TEX sale changes through Modify reservation
		tex = self.tex_book(who="corr")
		with self.assertRaisesRegex(frappe.ValidationError, "imported"):
			crs.correct_imported_amount(reservation=tex, amount="1.00", reason="no")


# ─── L3 · the currency of the amounts ───────────────────────────────────


class TestImportCurrency(ReviewCase):
	def test_a_tex_hotel_import_names_its_currency(self):
		from kamra import migrate
		from kamra.api import import_bookings

		ci, co = self.dates()
		out = migrate.run_import(fx.PROPERTY, self.csv(f"No currency,+49 30 5550210,STD,{ci},{co},2,200.00,Confirmed"))
		self.assertEqual(out["created"], 0, out)
		self.assertIn("currency", out["errors"][0]["error"])
		out = import_bookings(fx.PROPERTY, [self.import_row(amount_after_tax="200")])
		self.assertEqual(out["created"], 0, out)
		self.assertIn("currency", out["errors"][0]["error"])
		# a currency column, per row
		header = "Guest Name,Mobile No,Room Type,Arrival Date,Departure Date,Adult,Total Amount,Currency,Reservation Status"
		out = migrate.run_import(fx.PROPERTY, self.csv(f"Dollars,+49 30 5550211,STD,{ci},{co},2,200.00,USD,Confirmed",
		                                               f"Unknown,+49 30 5550212,STD,{ci},{co},2,200.00,XQZ,Confirmed",
		                                               f"Mismatch,+49 30 5550213,STD,{ci},{co},2,€ 200.00,USD,Confirmed",
		                                               header=header))
		self.assertEqual(out["created"], 1, out)
		self.assertEqual(frappe.db.get_value("Reservation", out["reservations"][0], ["tex_currency", "guest_name"]),
		                 ("USD", "Dollars"))
		errors = {e["guest"]: e["error"] for e in out["errors"]}
		self.assertIn("XQZ", errors["Unknown"])
		self.assertIn("EUR, not USD", errors["Mismatch"])
		# or one currency chosen for the whole import
		out = import_bookings(fx.PROPERTY, [self.import_row(amount_after_tax="200")], currency="GBP")
		self.assertEqual(frappe.db.get_value("Reservation", out["reservations"][0], "tex_currency"), "GBP")


# ─── M1 · one row, all or nothing ───────────────────────────────────────


class TestImportRows(ReviewCase):
	def live(self) -> int:
		return frappe.db.count("Reservation", {"property": fx.PROPERTY, "status": ("in", ["Confirmed", "Checked In",
		                                                                                   "Held", "Pending Payment"])})

	def test_a_cancelled_row_leaves_no_live_stay(self):
		from kamra.api import import_bookings

		before = self.live()
		out = import_bookings(fx.PROPERTY, [self.import_row(amount_after_tax="80.00", status="Cancelled")],
		                      currency="EUR")
		self.assertEqual(out["created"], 1, out)
		res = frappe.get_doc("Reservation", out["reservations"][0])
		self.assertEqual((res.status, res.tex_pricing_source), ("Cancelled", "Imported"))
		self.assertEqual(self.live(), before)
		audit = frappe.get_all("TEX Audit Event", filters={"action": "reservation.import", "reference_name": res.name},
		                       pluck="new_value")
		self.assertIn('"status": "Cancelled"', audit[0])

	def test_an_in_house_row_is_stamped_checked_in(self):
		from kamra.api import import_bookings

		row = self.import_row(amount_after_tax="200.00", status="Checked In", check_in=str(add_days(nowdate(), -1)),
		                      check_out=str(add_days(nowdate(), 1)))
		out = import_bookings(fx.PROPERTY, [row], currency="EUR")
		self.assertEqual(out["created"], 1, out)
		self.assertEqual(frappe.db.get_value("Reservation", out["reservations"][0], "status"), "Checked In")

	def test_a_row_that_fails_leaves_nothing_behind(self):
		from kamra.api import import_bookings

		before = frappe.db.count("Reservation", {"property": fx.PROPERTY})
		with mock.patch("kamra.tex.legacy.record_import", side_effect=frappe.ValidationError("audit down")):
			out = import_bookings(fx.PROPERTY, [self.import_row(amount_after_tax="80.00")], currency="EUR")
		self.assertEqual(out["created"], 0, out)
		self.assertEqual(frappe.db.count("Reservation", {"property": fx.PROPERTY}), before)
		# the next row still imports
		self.assertEqual(import_bookings(fx.PROPERTY, [self.import_row(amount_after_tax="80.00")],
		                                 currency="EUR")["created"], 1)


# ─── H2 / G-96 · the legacy check-out bills no TEX price ────────────────


class TestLegacyCheckOut(ReviewCase):
	def setUp(self):
		super().setUp()
		frappe.db.set_value("Property", fx.PROPERTY, "cleaning_fee", 25)

	def stay_in_house(self, name: str, room_type: str):
		from kamra import api

		api.check_in(name, room=self.room(room_type))
		return api

	def test_a_tex_sold_stay_is_billed_in_tex_not_on_the_folio(self):
		from kamra import api
		from kamra.ledger import force_advance_bill

		name = self.tex_book(who="checkout")
		self.stay_in_house(name, self.dlx)
		with self.assertRaisesRegex(frappe.ValidationError, "billed on its TEX booking"):
			force_advance_bill(name, "entire")
		api.check_out(name)
		self.assertEqual(frappe.db.get_value("Reservation", name, "status"), "Checked Out")
		self.assertEqual(charges(name), [])                 # no legacy room, board, discount or cleaning line

	def test_an_imported_stay_posts_its_locked_amount(self):
		from kamra import api

		name = self.imported("100.00", check_out=str(add_days(self.ci, 3)))    # 3 nights
		self.stay_in_house(name, self.dlx)
		api.check_out(name)
		lines = charges(name)
		self.assertEqual([(c.charge_type, from_db(c.amount, "EUR"), float(c.gst_rate or 0)) for c in lines],
		                 [("Room", D("33.33"), 0.0), ("Room", D("33.33"), 0.0), ("Room", D("33.34"), 0.0)])
		self.assertEqual([getdate(c.posting_date) for c in lines], [getdate(add_days(self.ci, i)) for i in range(3)])
		folio = frappe.db.get_value("Folio", {"reservation": name, "folio_type": "Guest"}, "grand_total")
		self.assertEqual(from_db(folio, "EUR"), D("100.00"))

	def test_an_imported_stay_advance_bills_its_locked_amount(self):
		from kamra.ledger import force_advance_bill

		name = self.imported("312.40")
		out = force_advance_bill(name, "entire")
		self.assertEqual(len(out["nights_posted"]), 2)
		self.assertEqual([from_db(c.amount, "EUR") for c in charges(name, ("Room",))], [D("156.20"), D("156.20")])

	def test_an_imported_stay_in_another_currency_is_not_billed_in_the_hotels(self):
		from kamra import api

		name = self.imported("250.00", currency="USD")
		self.stay_in_house(name, self.dlx)
		api.check_out(name)
		lines = charges(name)
		self.assertTrue(lines and all(from_db(c.amount, "EUR") == 0 for c in lines), lines)
		self.assertIn("USD", lines[0].description)

	def test_a_hotel_outside_tex_bills_as_before(self):
		from kamra import api
		from kamra.folio import _nightly_room_rate

		other = self.legacy_hotel()
		res = frappe.get_doc(self.values(property=other["hotel"], room_type=other["room_type"])).insert()
		room = frappe.db.get_value("Room", {"property": other["hotel"]}, "name")
		api.check_in(res.name, room=room)
		api.check_out(res.name)
		lines = charges(res.name, ("Room",))
		self.assertEqual(len(lines), 2)
		self.assertEqual(float(lines[0].amount), _nightly_room_rate(res, self.ci))


# ─── M2 · the fee of an imported stay comes from its locked amount ──────


class TestImportedCancellationFee(ReviewCase):
	def policy(self, basis: str):
		frappe.db.set_value("Property", fx.PROPERTY, {"free_cancel_days": 9999, "cancellation_fee": basis})

	def test_the_legacy_cancel_takes_the_fee_from_the_locked_amount(self):
		from kamra import api

		self.policy("Full Stay")
		name = self.imported("312.40")
		out = api.cancel_reservation(name, reason="Change of plans")
		self.assertEqual(D(str(out["fee"])), D("312.40"))
		self.assertEqual(from_db(frappe.db.get_value("Reservation", name, "cancellation_fee"), "EUR"), D("312.40"))
		self.policy("First Night")
		name = self.imported("312.40", guest_name="Second", phone="+49 30 5550214")
		out = api.cancel_reservation(name, reason="Change of plans")
		self.assertEqual(D(str(out["fee"])), D("156.20"))
		fee = charges(name, ("Misc",))
		self.assertEqual([(from_db(c.amount, "EUR"), float(c.gst_rate or 0)) for c in fee], [(D("156.20"), 0.0)])

	def test_the_tex_cancel_applies_the_hotels_policy_to_the_locked_amount(self):
		from kamra.tex.services import booking

		self.policy("Full Stay")
		name = self.imported("312.40")
		out = booking.cancel_reservation(name, reason="guest request")
		self.assertEqual((out["penalty"], out["currency"]), ("312.40", "EUR"))
		self.policy("None")
		name = self.imported("312.40", guest_name="Third", phone="+49 30 5550215")
		self.assertEqual(booking.cancel_reservation(name, reason="guest request")["penalty"], "0.00")

	def test_a_tex_sale_is_cancelled_in_tex_only(self):
		from kamra import api

		self.policy("None")
		name = self.tex_book(who="cxl")
		with self.assertRaisesRegex(frappe.ValidationError, "Cancel it in TEX"):
			api.cancel_reservation(name, reason="Change of plans")
		self.assertEqual(frappe.db.get_value("Reservation", name, "status"), "Confirmed")


# ─── M3 · a hotel goes live in TEX when an administrator says so ────────


class TestGoLive(ReviewCase):
	def setUp(self):
		super().setUp()
		if not frappe.db.exists("Property", ONBOARDING):
			frappe.get_doc({"doctype": "Property", "property_name": ONBOARDING, "city": "Kemer", "country": "Turkey",
			                "currency": "EUR"}).insert(ignore_permissions=True)
		frappe.db.set_value("Property", ONBOARDING, "tex_hotel_group", self.f["group"])   # joins TEX: onboarding
		self.hotel_rt = fx.ensure("Room Type", {"property": ONBOARDING, "room_type_code": "ONB"},
		                          {"property": ONBOARDING, "room_type_code": "ONB", "room_type_name": "Onboarding Double",
		                           "base_price": 90, "adults_capacity": 2, "children_capacity": 1,
		                           "max_total_occupants": 3, "base_occupancy": 2})
		for n in (1, 2):
			fx.ensure("Room", {"property": ONBOARDING, "room_number": f"ONB-{n}"},
			          {"property": ONBOARDING, "room_number": f"ONB-{n}", "room_type": self.hotel_rt})

	def desk_stay(self, **kw):
		return frappe.get_doc(self.values(property=ONBOARDING, room_type=self.hotel_rt, **kw)).insert()

	def test_the_desk_sells_until_the_hotel_goes_live(self):
		from kamra.tex.api import admin
		from kamra.tex.legacy import is_tex_hotel

		self.assertTrue(is_tex_hotel(ONBOARDING))
		stay = self.desk_stay()                              # onboarding: the Desk still sells, legacy-priced
		self.assertTrue(stay.amount_after_tax)
		admin.set_hotel_live(property=ONBOARDING, live=1, reason="contracts published, CRS trained")
		with self.assertRaisesRegex(frappe.ValidationError, REFUSED):
			self.desk_stay(check_in_date=str(add_days(self.co, 3)), check_out_date=str(add_days(self.co, 5)))
		self.assertTrue(frappe.db.exists("TEX Audit Event", {"action": "hotel.go_live", "reference_name": ONBOARDING}))
		# back to onboarding (a rollback), with a reason and audited
		admin.set_hotel_live(property=ONBOARDING, live=0, reason="cut-over postponed")
		self.desk_stay(check_in_date=str(add_days(self.co, 3)), check_out_date=str(add_days(self.co, 5)))
		self.assertTrue(frappe.db.exists("TEX Audit Event", {"action": "hotel.go_live_undo",
		                                                     "reference_name": ONBOARDING}))

	def test_going_live_needs_settings_admin_and_a_reason(self):
		from kamra.tex.api import admin

		agent = self.user("g92r-live@example.com", "Hotel Admin")      # a sales profile at the TEX hotel only
		fx.ensure("TEX Access Grant", {"user": agent, "property": ONBOARDING},
		          {"user": agent, "scope_level": "Hotel", "property": ONBOARDING,
		           "permission_profile": "Reservations Agent"})
		scope.clear_cache()
		frappe.set_user(agent)  # nosemgrep: frappe-setuser -- no settings.admin at the hotel
		with self.assertRaises(frappe.PermissionError):
			admin.set_hotel_live(property=ONBOARDING, live=1, reason="now")
		# nor through the Desk form or REST
		with self.assertRaisesRegex(frappe.ValidationError, "go live"):
			frappe.client.set_value("Property", ONBOARDING, "tex_live_from", str(now_datetime()))
		frappe.set_user("Administrator")  # nosemgrep: frappe-setuser -- back to the test's user
		with self.assertRaisesRegex(frappe.ValidationError, "reason"):
			admin.set_hotel_live(property=ONBOARDING, live=1, reason="")
		with self.assertRaisesRegex(frappe.ValidationError, "not in TEX"):
			admin.set_hotel_live(property=self.legacy_hotel()["hotel"], live=1, reason="no")
		self.assertFalse(frappe.db.get_value("Property", ONBOARDING, "tex_live_from"))

	def test_the_session_tells_the_shell_each_hotels_mode(self):
		from kamra.tex.api import admin, session

		modes = {p["name"]: p["tex_mode"] for p in session.bootstrap()["properties"]}
		self.assertEqual((modes[fx.PROPERTY], modes[ONBOARDING]), ("live", "onboarding"))
		admin.set_hotel_live(property=ONBOARDING, live=1, reason="go")
		modes = {p["name"]: p["tex_mode"] for p in session.bootstrap()["properties"]}
		self.assertEqual(modes[ONBOARDING], "live")
		from kamra.api import my_properties

		legacy = {p["name"]: p.get("tex_mode") for p in my_properties()}
		self.assertEqual(legacy[ONBOARDING], "live")
		# the Desk form asks for one hotel, in the caller's scope only
		self.assertEqual(session.hotel_mode(fx.PROPERTY)["tex_mode"], "live")
		self.assertIsNone(session.hotel_mode(self.legacy_hotel()["hotel"])["tex_mode"])
		frappe.set_user(self.desk_user)  # nosemgrep: frappe-setuser -- granted at the TEX hotel only
		with self.assertRaises(frappe.PermissionError):
			session.hotel_mode(ONBOARDING)

	def test_the_upgrade_keeps_todays_tex_hotels_live(self):
		from kamra.patches.tex import p36_g92_review as p36

		fx.create_contract(self.f, code="G92P36")                # TEX sells the test hotel
		# the site as before the upgrade: p36 sets hotels live on its first run only (ADR-058 review)
		frappe.db.delete("Patch Log", {"patch": "kamra.patches.tex.p36_g92_review"})
		frappe.db.set_value("Property", fx.PROPERTY, "tex_live_from", None)
		frappe.db.set_value("Property", ONBOARDING, "tex_live_from", None)
		p36.execute()
		p36.execute()                                        # runs again safely
		self.assertTrue(frappe.db.get_value("Property", fx.PROPERTY, "tex_live_from"))
		# in TEX, but TEX never sold it (no published contract, no TEX booking): onboarding, its Desk
		# sells it until an administrator sets it live (G-76, ADR-058)
		self.assertFalse(frappe.db.get_value("Property", ONBOARDING, "tex_live_from"))
		self.assertFalse(frappe.db.get_value("Property", self.legacy_hotel()["hotel"], "tex_live_from"))

	def test_an_in_house_legacy_stay_books_its_extra_nights_in_tex(self):
		# a stay the legacy engine sold before the hotel joined TEX, in house since yesterday
		with mock.patch("kamra.tex.legacy.is_tex_hotel", return_value=False):
			doc = frappe.get_doc(self.values(check_in_date=str(add_days(nowdate(), -1)), room_type=self.std,
			                                 check_out_date=str(add_days(nowdate(), 1)), room=self.room(self.std)))
			doc.flags.allow_past_check_in = True
			name = doc.insert().name
		frappe.db.set_value("Reservation", name, "status", "Checked In")
		doc = frappe.get_doc("Reservation", name)
		doc.check_out_date = add_days(nowdate(), 3)
		with self.assertRaisesRegex(frappe.ValidationError, "book the extra nights as a new TEX reservation"):
			doc.save()


# ─── L1 · the modification flag covers one save ─────────────────────────


class TestModificationFlag(ReviewCase):
	def test_the_flag_covers_one_save_and_nothing_request_wide(self):
		name = self.tex_book(who="flag")
		doc = frappe.get_doc("Reservation", name)
		doc.flags.tex_modification = True                  # as a TEX service marks its save
		doc.special_requests = "quiet"
		doc.save()
		self.assertNotIn("tex_modification", doc.flags)
		doc.check_out_date = add_days(self.co, 1)
		with self.assertRaisesRegex(frappe.ValidationError, "price-locked"):
			doc.save()
		frappe.flags.tex_modification = True               # no request-wide bypass
		try:
			doc = frappe.get_doc("Reservation", name)
			doc.check_out_date = add_days(self.co, 1)
			with self.assertRaisesRegex(frappe.ValidationError, "price-locked"):
				doc.save()
		finally:
			frappe.flags.tex_modification = False
