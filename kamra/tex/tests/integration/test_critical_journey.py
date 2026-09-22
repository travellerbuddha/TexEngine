"""PRODUCT_SPEC R-58 critical journey, exercised through the TEX services.

1 hotel exists · 2 market · 3 contract · 4 price period · 5 base-person rate ·
6 adult/child formulas · 7 publish · 8 guest searches · 9 availability ·
10 correct price · 11 selects room · 12 adds extra · 13 pays · 14 confirms ·
15 admin changes the contract · 16 existing reservation unchanged ·
17 dates/occupancy modified · 18 correct difference proposed · 19 revision recorded.
"""

import json

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import add_days

from kamra.tex.commercial import contracts
from kamra.tex.money import D
from kamra.tex.services import booking, modification, quoting
from kamra.tex.tests.integration import fixtures as fx


class TexTestCase(IntegrationTestCase):
	def setUp(self):
		frappe.set_user("Administrator")  # nosemgrep: frappe-setuser -- test context switch
		self.f = fx.base_setup()

	def tearDown(self):
		frappe.set_user("Administrator")  # nosemgrep: frappe-setuser -- test context switch
		frappe.db.rollback()          # every test starts from the same fixtures
		contracts.clear_terms_cache()
		from kamra.tex.security import scope

		scope.clear_cache()


def search_std(check_in, check_out, rooms, **kw):
	res = quoting.search(properties=[fx.PROPERTY], check_in=check_in, check_out=check_out, rooms=rooms,
	                     market=kw.pop("market", "DE"), channel=kw.pop("channel", "DIRECT_WEB"), currency="EUR", **kw)
	prop = res["properties"][0]
	return prop


def pick(prop, room_code="STD", board="AI", rate_plan_code="FLEX"):
	rt = fx.frappe.db.get_value("Room Type", {"property": fx.PROPERTY, "room_type_code": room_code})
	rp = fx.frappe.db.get_value("Rate Plan", {"property": fx.PROPERTY, "code": rate_plan_code})
	for o in prop["offers"]:
		if o["room_type"] == rt and o["board"] == board and o["rate_plan"] == rp:
			return o
	raise AssertionError(f"no offer {room_code}/{board}/{rate_plan_code}: {json.dumps(prop, default=str)[:2000]}")


class TestCriticalJourney(TexTestCase):
	def test_full_journey(self):
		# 1-7: contract with periods, base-person rates, formulas; published (+ DE markup 7 %)
		c = fx.create_contract(self.f)
		fx.create_markup("DE", 7)
		self.assertTrue(c["payload_hash"])
		v1 = c["version"]
		self.assertEqual(frappe.db.get_value("TEX Contract Version", v1, "status"), "Published")
		self.assertEqual(frappe.db.get_value("TEX Contract", c["contract"], "active_version"), v1)

		# 8-10: guest search — 2 adults + child 8, 3 nights in LOW
		ci, co = fx.d(6, 10), fx.d(6, 13)
		frappe.set_user("Guest")  # nosemgrep: frappe-setuser -- guest booking path
		prop = search_std(ci, co, [{"adults": 2, "children": [8]}])
		offer = pick(prop)
		self.assertEqual(offer["available"], 6)
		# per night 100 + 100 + 50 = 250 → +7 % = 267.50 → 3 nights
		self.assertEqual(offer["total"], "802.50")
		self.assertNotIn("explanation", offer["rooms"][0]["quote"])        # guest view hides internals
		self.assertNotIn("margin", offer["rooms"][0]["quote"]["totals"])
		nrf = pick(prop, rate_plan_code="NRF")
		self.assertEqual(nrf["total"], "722.25")                           # −10 % before markup

		# 11-12: select + add the airport transfer
		q = quoting.create_quote(offer["rooms"][0]["offer_key"], extras=[{"code": "TRF", "quantity": 1}])
		self.assertTrue(q["ok"], q)
		self.assertEqual(q["quote"]["totals"]["total"], "842.50")

		# 13-14: book; 30 % deposit due; payment confirms
		b = booking.create_booking(quote_ids=[q["quote_id"]], guest={
			"first_name": "Anna", "last_name": "Muster", "email": "anna@example.com", "country": "Germany"},
			payment_method="Card", idempotency_key="journey-1", language="de")
		self.assertEqual(b["status"], "Pending Payment")
		self.assertEqual(b["due_now"], "252.75")
		self.assertTrue(b["manage_token"])
		replay = booking.create_booking(quote_ids=[q["quote_id"]], guest={"first_name": "x", "last_name": "y",
		                                                                  "email": "x@y.z"},
		                                idempotency_key="journey-1")
		self.assertTrue(replay["idempotent_replay"])
		frappe.set_user("Administrator")  # nosemgrep: frappe-setuser -- staff side
		booking.apply_payment(b["booking"], D("252.75"), reference="MOCK-1")
		res_name = b["rooms"][0]["reservation"]
		res = frappe.get_doc("Reservation", res_name)
		self.assertEqual(res.status, "Confirmed")
		self.assertEqual(res.tex_price_locked, 1)
		self.assertEqual(D(res.tex_total_amount), D("842.50"))
		self.assertEqual(res.tex_contract_version, v1)

		# 15: the revenue manager raises the base rate in a new version
		v2 = contracts.new_draft(c["contract"])
		doc = frappe.get_doc("TEX Contract Version", v2)
		for r in doc.period_rates:
			if r.period_code == "LOW":
				r.value = 110
		doc.save()
		contracts.publish(v2)
		self.assertEqual(frappe.db.get_value("TEX Contract Version", v1, "status"), "Superseded")

		# 16: the sold reservation is untouched, even when saved again
		res.reload()
		res.special_requests = "late arrival"
		res.save()
		res.reload()
		self.assertEqual(D(res.tex_total_amount), D("842.50"))
		self.assertEqual(res.tex_contract_version, v1)
		res.check_out_date = add_days(co, 1)
		with self.assertRaises(frappe.ValidationError):
			res.save()                                   # price-locked: no silent change
		res.reload()

		# 17-18: add a night and a second child (4 y) — on current rules (V2 + markup)
		p = modification.propose(res_name, {"check_out": add_days(co, 1), "children": [8, 4]}, basis="CURRENT")
		# new night = 110 + 110 + 55 + 27.50 = 302.50 → ×1.07 = 323.675 ; 4 nights + transfer
		self.assertEqual(p["proposed"]["totals"]["total"], "1334.70")
		self.assertEqual(p["difference"], "492.20")
		self.assertEqual(p["old"]["total"], "842.50")
		orig = modification.propose(res_name, {"check_out": add_days(co, 1), "children": [8, 4]},
		                            basis="ORIGINAL_VERSION")
		self.assertEqual(orig["proposed"]["contract"]["version"], v1)
		self.assertEqual(orig["proposed"]["totals"]["total"], "1217.00")   # 4 × 275 × 1.07 + 40
		# 19: apply → revision history
		out = modification.apply(p["proposal_token"], reason="Guest asked for an extra night")
		self.assertEqual(out["difference"], "492.20")
		revs = modification.revisions(res_name)
		self.assertEqual([r["change_type"] for r in revs], ["Original", "Multiple"])
		self.assertEqual(revs[1]["old_amount"], "842.50")
		self.assertEqual(revs[1]["new_amount"], "1334.70")
		self.assertEqual(D(frappe.get_doc("TEX Booking", b["booking"]).total_amount), D("1334.70"))
		self.assertTrue(frappe.db.exists("TEX Audit Event", {"action": "reservation.modify",
		                                                     "reference_name": res_name}))


class TestContractImmutability(TexTestCase):
	def test_published_version_cannot_be_edited(self):
		c = fx.create_contract(self.f, code="IMM")
		v = frappe.get_doc("TEX Contract Version", c["version"])
		v.period_rates[0].value = 999
		with self.assertRaises(frappe.ValidationError):
			v.save()

	def test_payload_integrity_is_checked(self):
		c = fx.create_contract(self.f, code="INT")
		payload = json.loads(frappe.db.get_value("TEX Contract Version", c["version"], "payload"))
		payload["room_rules"][0]["value"] = "1"          # tamper with a sold price
		frappe.db.set_value("TEX Contract Version", c["version"], "payload", json.dumps(payload),
		                    update_modified=False)
		contracts.clear_terms_cache()
		with self.assertRaises(frappe.ValidationError):
			contracts.load_terms(c["version"])

	def test_publish_rejects_invalid_contract(self):
		c = fx.create_contract(self.f, code="BAD", publish=False)
		v = frappe.get_doc("TEX Contract Version", c["version"])
		v.period_rates = [r for r in v.period_rates if r.period_code != "HIGH"]
		v.save()
		with self.assertRaises(frappe.ValidationError):
			contracts.publish(v.name)

	def test_scheduled_version_takes_over_at_its_time(self):
		c = fx.create_contract(self.f, code="SCH")
		v2 = contracts.new_draft(c["contract"])
		future = add_days(frappe.utils.now_datetime(), 10)
		contracts.publish(v2, effective_from=future)
		now = frappe.utils.now_datetime()
		self.assertEqual(contracts.active_version_header(c["contract"], now).version_id, c["version"])
		self.assertEqual(contracts.active_version_header(c["contract"], add_days(future, 1)).version_id, v2)


class TestInventory(TexTestCase):
	def test_last_room_cannot_be_sold_twice(self):
		fx.create_contract(self.f, code="INV")
		ci, co = fx.d(7, 10), fx.d(7, 12)
		frappe.set_user("Guest")  # nosemgrep: frappe-setuser -- guest booking path
		prop = search_std(ci, co, [{"adults": 2}])
		dlx = pick(prop, room_code="DLX")
		self.assertEqual(dlx["available"], 2)
		quotes = [quoting.create_quote(dlx["rooms"][0]["offer_key"])["quote_id"] for _ in range(3)]
		guest = {"first_name": "A", "last_name": "B", "email": "ab@example.com"}
		booking.create_booking(quote_ids=[quotes[0]], guest=guest, payment_method="Card")
		booking.create_booking(quote_ids=[quotes[1]], guest=guest, payment_method="Card")
		with self.assertRaises(frappe.ValidationError):
			booking.create_booking(quote_ids=[quotes[2]], guest=guest, payment_method="Card")

	def test_multi_room_overlapping_dates_count_together(self):
		fx.create_contract(self.f, code="OVL")
		frappe.set_user("Guest")  # nosemgrep: frappe-setuser -- guest booking path
		a = pick(search_std(fx.d(7, 10), fx.d(7, 12), [{"adults": 2}]), room_code="DLX")
		b = pick(search_std(fx.d(7, 11), fx.d(7, 13), [{"adults": 2}]), room_code="DLX")
		c = pick(search_std(fx.d(7, 11), fx.d(7, 12), [{"adults": 1}]), room_code="DLX")
		qa, qb, qc = (quoting.create_quote(x["rooms"][0]["offer_key"])["quote_id"] for x in (a, b, c))
		guest = {"first_name": "A", "last_name": "B", "email": "ab@example.com"}
		with self.assertRaises(frappe.ValidationError):   # 3 rooms want DLX on the 11th, only 2 exist
			booking.create_booking(quote_ids=[qa, qb, qc], guest=guest, payment_method="Card")


class TestMultiRoom(TexTestCase):
	def test_rooms_priced_independently_under_one_booking(self):
		fx.create_contract(self.f, code="MR")
		frappe.set_user("Guest")  # nosemgrep: frappe-setuser -- guest booking path
		prop = search_std(fx.d(6, 1), fx.d(6, 3), [{"adults": 2, "children": [5]},
		                                           {"adults": 1, "children": [3, 8]}])
		offer = pick(prop)
		self.assertEqual(len(offer["rooms"]), 2)
		# room 1: 100+100+25 = 225 ; room 2: 1A+2C → CHB child 1 50 %, CHA child 2 25 % = 175 (no 1+1 rule)
		self.assertEqual([r["quote"]["totals"]["total"] for r in offer["rooms"]], ["450.00", "350.00"])
		qids = [quoting.create_quote(r["offer_key"])["quote_id"] for r in offer["rooms"]]
		b = booking.create_booking(quote_ids=qids, guest={"first_name": "M", "last_name": "R",
		                                                  "email": "mr@example.com"}, payment_method="Card")
		self.assertEqual(len(b["rooms"]), 2)
		self.assertEqual(b["total"], "800.00")
		for r in b["rooms"]:
			self.assertEqual(frappe.db.get_value("Reservation", r["reservation"], "tex_booking"), b["booking"])


class TestHistoricalSimulator(TexTestCase):
	def test_simulation_uses_rules_on_sale_at_that_time(self):
		c = fx.create_contract(self.f, code="SIM")
		ci, co = fx.d(6, 10), fx.d(6, 12)
		frappe.set_user("Guest")  # nosemgrep: frappe-setuser -- guest booking path
		offer = pick(search_std(ci, co, [{"adults": 2}]))
		q = quoting.create_quote(offer["rooms"][0]["offer_key"])
		b = booking.create_booking(quote_ids=[q["quote_id"]], guest={"first_name": "S", "last_name": "T",
		                                                             "email": "st@example.com"},
		                           payment_method="Card")
		frappe.set_user("Administrator")  # nosemgrep: frappe-setuser -- staff side
		sold_at = frappe.utils.now_datetime()
		v2 = contracts.new_draft(c["contract"])
		doc = frappe.get_doc("TEX Contract Version", v2)
		for r in doc.period_rates:
			if r.period_code == "LOW":
				r.value = 150
		doc.save()
		contracts.publish(v2)
		res = b["rooms"][0]["reservation"]
		then = modification.simulate(res, sold_at)
		now = modification.simulate(res, frappe.utils.now_datetime())
		self.assertEqual(then["simulated"]["totals"]["total"], "400.00")
		self.assertEqual(now["simulated"]["totals"]["total"], "600.00")
		self.assertEqual(then["difference"], "0.00")
