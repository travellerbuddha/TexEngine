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


class TestContractSelection(TexTestCase):
	"""G-17: a room is sold by the highest-priority contract that can sell this stay at
	this sale time; a contract closed for the sale date or the stay hides nothing."""

	def _contract(self, code: str, base: int, priority: int, **window) -> str:
		c = fx.create_contract(self.f, code=code, base=base, publish=False)
		frappe.db.set_value("TEX Contract", c["contract"], {"priority": priority, **window})
		contracts.publish(c["version"])
		return c["contract"]

	def test_a_contract_that_cannot_sell_the_stay_hides_nothing(self):
		main = self._contract("DE-MAIN", 100, 0)
		early = self._contract("DE-EARLY", 60, 10, stay_to=fx.d(6, 30))     # stays until the end of June
		self._contract("DE-CLOSED", 50, 20, sale_to=frappe.utils.add_days(frappe.utils.nowdate(), -1))
		july = search_std(fx.d(7, 10), fx.d(7, 13), [{"adults": 2}])
		self.assertEqual({o["contract"] for o in july["offers"]}, {main})
		june = search_std(fx.d(6, 10), fx.d(6, 13), [{"adults": 2}])
		self.assertEqual({o["contract"] for o in june["offers"]}, {early})  # the early contract wins where it sells


LOCK_OTHER_HOTEL = "TEX Header Lock Other Hotel"


class TestContractHeaderLock(TexTestCase):
	"""G-50 (ADR-045): once a contract has a published version, what selection and pricing read
	(hotel, market, currency, pricing basis, sale/stay windows, channels, priority, sell currency)
	is fixed; windows, channels, priority and sell currency change only with a new version. The
	header mirrors the live version, selection reads the frozen version, and the status moves
	only through audited actions."""

	def setUp(self):
		super().setUp()
		self.c = fx.create_contract(self.f, code="LOCK")
		self.name = self.c["contract"]
		contracts.clear_terms_cache()

	def _audit(self, action: str, name: str | None = None) -> dict:
		rows = frappe.get_all("TEX Audit Event", filters={"action": action, "reference_name": name or self.name},
		                      fields=["old_value", "new_value", "reason"], order_by="creation desc, name desc",
		                      limit=1)
		self.assertTrue(rows, f"no {action} audit for {name or self.name}")
		r = rows[0]
		return {"old": json.loads(r.old_value) if r.old_value else None,
		        "new": json.loads(r.new_value) if r.new_value else None, "reason": r.reason}

	def _published(self, code: str, base: int, priority: int) -> str:
		c = fx.create_contract(self.f, code=code, base=base, publish=False)
		frappe.db.set_value("TEX Contract", c["contract"], "priority", priority)  # before the first publish
		contracts.publish(c["version"])
		return c["contract"]

	def _other_hotel(self) -> str:
		if not frappe.db.exists("Property", LOCK_OTHER_HOTEL):
			frappe.get_doc({"doctype": "Property", "property_name": LOCK_OTHER_HOTEL, "city": "Side",
			                "country": "Turkey", "currency": "EUR", "tex_hotel_group": self.f["group"]}
			               ).insert(ignore_permissions=True)
		return LOCK_OTHER_HOTEL

	def test_published_header_refuses_commercial_edits_through_the_api(self):
		from kamra.tex.api import contracts as api

		before = frappe.get_doc("TEX Contract", self.name).as_dict()
		changes = {"market": "UK", "channels": ["OTA"], "sale_from": str(fx.d(1, 15)), "sale_to": str(fx.d(6, 1)),
		           "stay_from": str(fx.d(6, 1)), "stay_to": str(fx.d(9, 30)), "priority": 50,
		           "sell_currency": "GBP", "contract_currency": "GBP", "pricing_basis": "ROOM", "status": "Suspended"}
		for field, value in changes.items():
			with self.subTest(field=field), self.assertRaises(frappe.ValidationError):
				api.save_contract(data={"name": self.name, field: value})
		after = frappe.get_doc("TEX Contract", self.name)
		for field in changes:
			if field != "channels":
				self.assertEqual(str(after.get(field) or ""), str(before.get(field) or ""), field)
		self.assertEqual([c.sales_channel for c in after.channels], [])

	def test_published_header_refuses_commercial_edits_through_desk_and_rest(self):
		other = self._other_hotel()
		for field, value in (("market", "UK"), ("sale_to", fx.d(6, 1)), ("stay_from", fx.d(6, 1)), ("priority", 50),
		                     ("sell_currency", "GBP"), ("status", "Suspended"), ("property", other),
		                     ("active_version", None)):
			doc = frappe.get_doc("TEX Contract", self.name)
			doc.set(field, value)
			with self.subTest(field=field), self.assertRaises(frappe.ValidationError):
				doc.save()
		doc = frappe.get_doc("TEX Contract", self.name)
		doc.append("channels", {"sales_channel": "OTA"})
		with self.assertRaises(frappe.ValidationError):
			doc.save()
		from frappe.client import set_value

		with self.assertRaises(frappe.ValidationError):              # REST: PUT /api/resource runs the same save
			set_value("TEX Contract", self.name, "market", "UK")
		self.assertEqual(frappe.db.get_value("TEX Contract", self.name, "market"), "DE")
		# a new contract always starts as a draft, whatever the request says
		new = frappe.get_doc({"doctype": "TEX Contract", "property": fx.PROPERTY, "contract_code": "LOCK-INS",
		                      "contract_name": "Inserted", "market": "DE", "contract_currency": "EUR",
		                      "pricing_basis": "PERSON", "status": "Active"}).insert(ignore_permissions=True)
		self.assertEqual(new.status, "Draft")

	def test_name_notes_and_code_stay_editable_and_are_audited(self):
		from kamra.tex.api import contracts as api

		api.save_contract(data={"name": self.name, "contract_name": "Renamed", "notes": "memo", "is_bar": 1})
		doc = frappe.get_doc("TEX Contract", self.name)
		self.assertEqual((doc.contract_name, doc.notes, doc.is_bar), ("Renamed", "memo", 1))
		ev = self._audit("contract.save")
		self.assertEqual(ev["old"]["contract_name"], "LOCK contract")
		self.assertEqual(ev["new"]["contract_name"], "Renamed")
		self.assertEqual(ev["new"]["notes"], "memo")
		# a Desk / REST save of the header is audited too
		doc.contract_name = "Renamed in Desk"
		doc.save()
		self.assertEqual(self._audit("contract.save")["new"]["contract_name"], "Renamed in Desk")

	def test_save_contract_audit_records_channels_and_every_changed_field(self):
		from kamra.tex.api import contracts as api

		draft = fx.create_contract(self.f, code="LOCK-D", publish=False)["contract"]
		api.save_contract(data={"name": draft, "channels": ["OTA", "B2B"], "sale_to": str(fx.d(9, 30)),
		                        "priority": 4})
		ev = self._audit("contract.save", draft)
		self.assertEqual(ev["old"]["channels"], [])
		self.assertEqual(ev["new"]["channels"], ["B2B", "OTA"])
		self.assertEqual((ev["old"]["sale_to"], ev["new"]["sale_to"]), (str(fx.STAY_TO), str(fx.d(9, 30))))
		self.assertEqual((ev["old"]["priority"], ev["new"]["priority"]), (0, 4))
		api.save_contract(data={"name": draft, "channels": ["OTA"]})
		ev = self._audit("contract.save", draft)
		self.assertEqual((ev["old"]["channels"], ev["new"]["channels"]), (["B2B", "OTA"], ["OTA"]))

	def test_status_moves_only_through_audited_actions(self):
		from kamra.tex.api import contracts as api

		july = (fx.d(7, 10), fx.d(7, 13), [{"adults": 2}])
		self.assertTrue(search_std(*july)["offers"])
		with self.assertRaises(frappe.ValidationError):              # a reason is required
			api.set_contract_status(name=self.name, action="suspend", reason=" ")
		api.set_contract_status(name=self.name, action="suspend", reason="Hotel overbooked")
		self.assertEqual(frappe.db.get_value("TEX Contract", self.name, "status"), "Suspended")
		self.assertEqual(search_std(*july)["offers"], [])            # stop sale takes effect at once
		ev = self._audit("contract.status")
		self.assertEqual((ev["old"], ev["new"], ev["reason"]),
		                 ({"status": "Active"}, {"status": "Suspended"}, "Hotel overbooked"))
		with self.assertRaises(frappe.ValidationError):              # only an active contract is suspended
			api.set_contract_status(name=self.name, action="suspend", reason="again")
		api.set_contract_status(name=self.name, action="resume", reason="Rooms back")
		self.assertTrue(search_std(*july)["offers"])
		api.set_contract_status(name=self.name, action="archive", reason="Season over")
		self.assertEqual(frappe.db.get_value("TEX Contract", self.name, "status"), "Archived")
		api.set_contract_status(name=self.name, action="restore", reason="Archived by mistake")
		self.assertEqual(frappe.db.get_value("TEX Contract", self.name, "status"), "Suspended")
		draft = fx.create_contract(self.f, code="LOCK-NP", publish=False)["contract"]
		with self.assertRaises(frappe.ValidationError):              # nothing published: nothing to resume
			api.set_contract_status(name=draft, action="resume", reason="x")

	def test_selection_reads_the_frozen_version_not_the_header(self):
		now = frappe.utils.now_datetime()
		# the header is changed behind the controller's back (DB / data import)
		frappe.db.set_value("TEX Contract", self.name, {"market": "UK", "sell_currency": "GBP",
		                                                "sale_to": add_days(frappe.utils.nowdate(), -1)})
		frappe.get_doc({"doctype": "TEX Contract Channel", "parent": self.name, "parenttype": "TEX Contract",
		                "parentfield": "channels", "idx": 1, "sales_channel": "OTA"}).db_insert()
		cands = contracts.candidate_contracts(fx.PROPERTY, "DE", "DIRECT_WEB", now)
		self.assertEqual([c[0].name for c in cands], [self.name])
		row = cands[0][0]
		self.assertEqual((row.market, str(row.sale_to), row.sell_currency), ("DE", str(fx.STAY_TO), "EUR"))
		self.assertEqual(contracts.candidate_contracts(fx.PROPERTY, "UK", "OTA", now), [])
		offers = search_std(fx.d(7, 10), fx.d(7, 13), [{"adults": 2}])["offers"]
		self.assertEqual({(o["contract"], o["currency"]) for o in offers}, {(self.name, "EUR")})

	def test_a_tampered_priority_does_not_change_the_winner(self):
		early = self._published("LOCK-EARLY", 60, 10)
		july = (fx.d(7, 10), fx.d(7, 13), [{"adults": 2}])
		self.assertEqual({o["contract"] for o in search_std(*july)["offers"]}, {early})
		frappe.db.set_value("TEX Contract", self.name, "priority", 99)
		self.assertEqual({o["contract"] for o in search_std(*july)["offers"]}, {early})

	def test_a_version_frozen_before_g50_still_selects_by_its_header(self):
		from kamra.tex.pricing import serialize

		early = self._published("LOCK-EARLY", 60, 10)
		# payloads frozen before ADR-045 carry no priority or sell currency
		v = self.c["version"]
		payload = json.loads(frappe.db.get_value("TEX Contract Version", v, "payload"))
		payload["contract"].pop("priority", None)
		payload["contract"].pop("sell_currency", None)
		frappe.db.set_value("TEX Contract Version", v, {"payload": json.dumps(payload),
		                                                "payload_hash": serialize.payload_hash(payload)},
		                    update_modified=False)
		frappe.db.set_value("TEX Contract", self.name, {"priority": 30, "sell_currency": "GBP"})
		contracts.clear_terms_cache()
		cands = contracts.candidate_contracts(fx.PROPERTY, "DE", "DIRECT_WEB", frappe.utils.now_datetime())
		self.assertEqual([c[0].name for c in cands], [self.name, early])
		self.assertEqual((cands[0][0].priority, cands[0][0].sell_currency), (30, "GBP"))

	def test_selling_terms_change_with_a_new_version(self):
		from kamra.tex.api import contracts as api

		v1 = self.c["version"]
		v2 = contracts.new_draft(self.name)
		d = api.get_version(v2)
		self.assertTrue(d["selling_editable"])
		self.assertEqual(d["selling"]["sale_to"], str(fx.STAY_TO))
		self.assertEqual(d["selling"]["channels"], [])
		api.save_version(v2, {"selling": {"sale_to": str(fx.d(8, 31)), "stay_to": str(fx.d(8, 31)),
		                                  "channels": ["OTA"], "priority": 7}})
		contracts.publish(v2, change_note="OTA only, summer")
		header = frappe.get_doc("TEX Contract", self.name)         # the header mirrors the live version
		self.assertEqual((str(header.sale_to), str(header.stay_to), header.priority),
		                 (str(fx.d(8, 31)), str(fx.d(8, 31)), 7))
		self.assertEqual([c.sales_channel for c in header.channels], ["OTA"])
		self.assertIsNone(contracts.load_terms(v1).channels)       # V1 keeps what it sold with
		self.assertEqual(api.get_version(v1)["selling"]["channels"], [])
		now = frappe.utils.now_datetime()
		self.assertEqual(contracts.candidate_contracts(fx.PROPERTY, "DE", "DIRECT_WEB", now), [])
		self.assertEqual([c[0].name for c in contracts.candidate_contracts(fx.PROPERTY, "DE", "OTA", now)],
		                 [self.name])
		ev = self._audit("contract.publish", v2)
		self.assertEqual(ev["new"]["selling"]["channels"], ["OTA"])
		self.assertEqual(ev["old"]["selling"]["channels"], [])
		with self.assertRaises(frappe.ValidationError):              # published versions stay frozen
			api.save_version(v2, {"selling": {"priority": 1}})

	def test_a_version_made_outside_new_draft_starts_from_the_published_terms(self):
		# Desk / REST insert of a version, without selling terms: not "everywhere, always"
		v = frappe.get_doc({"doctype": "TEX Contract Version", "contract": self.name}).insert(ignore_permissions=True)
		self.assertEqual((str(v.sale_to), str(v.stay_from), v.sell_currency), (str(fx.STAY_TO), str(fx.STAY_FROM), "EUR"))

	def test_p21_gives_drafts_of_published_contracts_their_header_terms(self):
		from kamra.patches.tex import p21_contract_header_lock

		v2 = contracts.new_draft(self.name)
		# a draft made before G-50 has no selling terms of its own; its header had a channel
		frappe.db.set_value("TEX Contract Version", v2, {f: 0 if f == "priority" else None
		                                                 for f in contracts.SELLING_FIELDS})
		frappe.get_doc({"doctype": "TEX Contract Channel", "parent": self.name, "parenttype": "TEX Contract",
		                "parentfield": "channels", "idx": 1, "sales_channel": "B2B"}).db_insert()
		from unittest import mock

		with mock.patch("frappe.reload_doc"):                         # no schema sync (DDL commits) in a test
			p21_contract_header_lock.execute()
		d = frappe.get_doc("TEX Contract Version", v2)
		self.assertEqual((str(d.sale_to), str(d.stay_from), [c.sales_channel for c in d.channels]),
		                 (str(fx.STAY_TO), str(fx.STAY_FROM), ["B2B"]))
		self.assertEqual(frappe.db.get_value("TEX Contract Version", self.c["version"], "payload_hash"),
		                 self.c["payload_hash"])                     # published payloads are not touched

	def test_before_the_first_publish_the_header_holds_the_selling_terms(self):
		from kamra.tex.api import contracts as api

		c = fx.create_contract(self.f, code="LOCK-NEW", publish=False)
		api.save_contract(data={"name": c["contract"], "market": "UK", "priority": 5, "channels": ["CALL_CENTER"]})
		d = api.get_version(c["version"])
		self.assertFalse(d["selling_editable"])
		self.assertEqual((d["selling"]["priority"], d["selling"]["channels"]), (5, ["CALL_CENTER"]))
		with self.assertRaises(frappe.ValidationError):
			api.save_version(c["version"], {"selling": {"priority": 9}})
		contracts.publish(c["version"])
		t = contracts.load_terms(c["version"])
		self.assertEqual((t.market, t.channels, t.priority, t.sell_currency), ("UK", frozenset({"CALL_CENTER"}), 5, "EUR"))
		self.assertTrue(api.get_contract(c["contract"])["published"])

	def test_only_contract_managers_of_the_hotel_change_a_contract(self):
		from kamra.tex.api import contracts as api
		from kamra.tex.security import scope

		other = self._other_hotel()
		fx.ensure("TEX Permission Profile", {"profile_name": "G50 Contract Editor"},
		          {"profile_name": "G50 Contract Editor",
		           "capabilities": [{"capability": "price.view"}, {"capability": "contract.edit"}]})
		agent = fx.ensure_user("g50-agent@example.com", ["Call Center Agent"])
		editor = fx.ensure_user("g50-editor@example.com", ["Revenue Manager"])
		foreign = fx.ensure_user("g50-foreign@example.com", ["Hotel Admin"])
		for user, prop, profile in ((agent, fx.PROPERTY, "Reservations Agent"),
		                            (editor, fx.PROPERTY, "G50 Contract Editor"), (foreign, other, "Hotel Admin")):
			fx.ensure("TEX Access Grant", {"user": user, "property": prop},
			          {"user": user, "scope_level": "Hotel", "property": prop, "permission_profile": profile})
		for user in (agent, foreign):
			frappe.set_user(user)  # nosemgrep: frappe-setuser -- no contract.edit at this hotel
			scope.clear_cache()
			with self.assertRaises(frappe.PermissionError):
				api.save_contract(data={"name": self.name, "contract_name": "hijacked"})
			with self.assertRaises(frappe.PermissionError):
				api.set_contract_status(name=self.name, action="suspend", reason="probe")
		frappe.set_user(editor)  # nosemgrep: frappe-setuser -- contract.edit without contract.publish
		scope.clear_cache()
		api.save_contract(data={"name": self.name, "contract_name": "Edited by editor"})
		with self.assertRaises(frappe.PermissionError):
			api.set_contract_status(name=self.name, action="suspend", reason="probe")
		self.assertFalse(api.get_contract(self.name)["status_actions"])
		frappe.set_user("Administrator")  # nosemgrep: frappe-setuser -- verify
		self.assertEqual(frappe.db.get_value("TEX Contract", self.name, ["contract_name", "status"]),
		                 ("Edited by editor", "Active"))


class TestContractHeaderLockReview(TexTestCase):
	"""G-50 review follow-up (ADR-045). Before G-50 selection read the header and pricing the
	payload, so a header narrowed after publish (a channel removed, the sale window closed, the
	market changed) stopped sales. Such narrowings survive the upgrade: a version frozen before
	G-50 sells only where both its payload and the header (as snapshotted at the upgrade, p25)
	let it, and p25 reports every such contract. A suspend stops quotes and bookings in flight;
	the scheduler survives a broken header; Desk-made versions and p21 re-runs never lose terms."""

	def setUp(self):
		super().setUp()
		self.c = fx.create_contract(self.f, code="LOCKR")
		self.name = self.c["contract"]
		contracts.clear_terms_cache()

	_audit = TestContractHeaderLock._audit

	def _pre_g50(self, version: str) -> None:
		"""Make a published version look frozen before G-50: no priority or sell currency in its
		payload (re-hashed) and no selling terms of its own."""
		from kamra.tex.pricing import serialize

		payload = json.loads(frappe.db.get_value("TEX Contract Version", version, "payload"))
		payload["contract"].pop("priority", None)
		payload["contract"].pop("sell_currency", None)
		frappe.db.set_value("TEX Contract Version", version, {
			"payload": json.dumps(payload), "payload_hash": serialize.payload_hash(payload), "priority": 0,
			"sale_from": None, "sale_to": None, "stay_from": None, "stay_to": None, "sell_currency": None},
			update_modified=False)
		frappe.db.delete("TEX Contract Channel", {"parent": version, "parenttype": "TEX Contract Version"})
		contracts.clear_terms_cache()

	def _header_channels(self, contract: str, *channels: str) -> None:
		frappe.db.delete("TEX Contract Channel", {"parent": contract, "parenttype": "TEX Contract"})
		for idx, ch in enumerate(channels, 1):
			frappe.get_doc({"doctype": "TEX Contract Channel", "parent": contract, "parenttype": "TEX Contract",
			                "parentfield": "channels", "idx": idx, "sales_channel": ch}).db_insert()

	def _narrowed_legacy_contracts(self) -> dict:
		"""Three contracts published before G-50 whose headers staff narrowed after publishing."""
		ota = self.name
		self._pre_g50(self.c["version"])
		self._header_channels(ota, "OTA")                                     # DIRECT_WEB removed
		closed = fx.create_contract(self.f, code="LOCKR-CLOSED")
		self._pre_g50(closed["version"])
		frappe.db.set_value("TEX Contract", closed["contract"], "sale_to", add_days(frappe.utils.nowdate(), -1))
		de = fx.create_contract(self.f, code="LOCKR-GLOBAL", market="GLOBAL")
		self._pre_g50(de["version"])
		frappe.db.set_value("TEX Contract", de["contract"], "market", "DE")    # GLOBAL payload, DE header
		return {"ota": ota, "closed": closed["contract"], "de": de["contract"], "versions": {
			ota: self.c["version"], closed["contract"]: closed["version"], de["contract"]: de["version"]}}

	def _candidates(self, market: str, channel: str) -> list[str]:
		return [c[0].name for c in contracts.candidate_contracts(fx.PROPERTY, market, channel,
		                                                         frappe.utils.now_datetime())]

	def _upgrade(self) -> None:
		from unittest import mock

		from kamra.patches.tex import p21_contract_header_lock as p21
		from kamra.patches.tex import p25_contract_header_snapshot as p25

		with mock.patch("frappe.reload_doc"):                         # no schema sync (DDL commits) in a test
			p21.execute()
			p25.execute()

	def test_a_pre_g50_version_still_honours_its_narrowed_header(self):
		# finding 1: selection of a version frozen before G-50 = payload ∩ header, as before G-50
		k = self._narrowed_legacy_contracts()
		self.assertEqual(self._candidates("DE", "DIRECT_WEB"), [k["de"]])
		self.assertEqual(sorted(self._candidates("DE", "OTA")), sorted([k["ota"], k["de"]]))
		self.assertEqual(self._candidates("UK", "DIRECT_WEB"), [])       # the GLOBAL payload sells DE only
		self.assertEqual({o["contract"] for o in search_std(fx.d(7, 10), fx.d(7, 13), [{"adults": 2}])["offers"]},
		                 {k["de"]})

	def test_the_upgrade_keeps_header_narrowings_fixed_and_reports_them(self):
		k = self._narrowed_legacy_contracts()
		hashes = {v: frappe.db.get_value("TEX Contract Version", v, "payload_hash") for v in k["versions"].values()}
		self._upgrade()
		self.assertEqual(self._candidates("DE", "DIRECT_WEB"), [k["de"]])
		# finding 3: the snapshot is fixed; later header changes (DB) no longer move selection
		self._header_channels(k["ota"])
		frappe.db.set_value("TEX Contract", k["closed"], {"sale_to": fx.STAY_TO, "priority": 50})
		frappe.db.set_value("TEX Contract", k["de"], "market", "UK")
		self.assertEqual(self._candidates("DE", "DIRECT_WEB"), [k["de"]])
		self.assertEqual(self._candidates("UK", "DIRECT_WEB"), [])
		v = frappe.get_doc("TEX Contract Version", k["versions"][k["ota"]])
		self.assertEqual(([c.sales_channel for c in v.channels], v.header_market), (["OTA"], "DE"))
		self.assertTrue(v.header_snapshot_at)
		for version, digest in hashes.items():                          # payloads and hashes untouched
			self.assertEqual(frappe.db.get_value("TEX Contract Version", version, "payload_hash"), digest)
		# every contract whose header differs from its live payload is reported
		self.assertEqual(self._audit("contract.header_differs", k["ota"])["new"]["channels"], ["OTA"])
		self.assertEqual(self._audit("contract.header_differs", k["ota"])["old"]["channels"], [])
		self.assertIn("sale_to", self._audit("contract.header_differs", k["closed"])["new"])
		ev = self._audit("contract.header_differs", k["de"])
		self.assertEqual((ev["old"]["market"], ev["new"]["market"]), ("GLOBAL", "DE"))
		# a re-run changes nothing and reports nothing new
		before = frappe.db.count("TEX Audit Event", {"action": "contract.header_differs"})
		self._upgrade()
		self.assertEqual(frappe.db.count("TEX Audit Event", {"action": "contract.header_differs"}), before)

	def test_a_draft_from_a_pre_g50_version_starts_from_what_it_sold(self):
		k = self._narrowed_legacy_contracts()
		self._upgrade()
		d = frappe.get_doc("TEX Contract Version", contracts.new_draft(k["ota"]))
		self.assertEqual(([c.sales_channel for c in d.channels], str(d.sale_to)), (["OTA"], str(fx.STAY_TO)))

	def test_suspend_stops_quotes_and_bookings_already_in_flight(self):
		# finding 2: an offer (20 min) or a quote (30 min) taken before a suspend no longer sells
		from kamra.tex.api import contracts as api

		offer = pick(search_std(fx.d(7, 10), fx.d(7, 13), [{"adults": 2}]))
		key = offer["rooms"][0]["offer_key"]
		quoted = quoting.create_quote(key)
		self.assertTrue(quoted["ok"])
		api.set_contract_status(name=self.name, action="suspend", reason="Overbooked")
		late = quoting.create_quote(key)
		self.assertFalse(late["ok"])
		self.assertEqual(late["reasons"][0]["code"], "CONTRACT_SUSPENDED")
		guest = {"first_name": "Sus", "last_name": "Pended", "email": "suspended@example.com"}
		with self.assertRaises(contracts.ContractNotOnSale) as caught:
			booking.create_booking(quote_ids=[quoted["quote_id"]], guest=guest, payment_method="Card")
		self.assertEqual(caught.exception.code, "CONTRACT_SUSPENDED")
		api.set_contract_status(name=self.name, action="resume", reason="Rooms back")
		self.assertTrue(booking.create_booking(quote_ids=[quoted["quote_id"]], guest=guest,
		                                       payment_method="Card")["booking"])

	def test_the_scheduler_mirrors_a_version_going_live_and_survives_a_broken_header(self):
		# findings 4 and 7: one contract whose header no longer validates stops nothing else
		from frappe.utils import add_to_date

		from kamra.tex.api import contracts as api

		now = frappe.utils.now_datetime()
		past, later = add_to_date(now, minutes=-1), add_to_date(now, minutes=30)

		def schedule(contract, version, selling=None):
			v2 = contracts.new_draft(contract)
			if selling:
				api.save_version(v2, {"selling": selling})
			contracts.publish(v2, effective_from=later)
			frappe.db.set_value("TEX Contract Version", v2, "effective_from", past)   # it is due now
			frappe.db.set_value("TEX Contract Version", version, "active_to", past)
			return v2

		broken = fx.create_contract(self.f, code="LOCKR-BROKEN")
		b2 = schedule(broken["contract"], broken["version"])
		v2 = schedule(self.name, self.c["version"], {"channels": ["OTA"], "priority": 4})
		# legacy data: two contracts of the hotel share a code, so this header no longer saves
		fx.create_contract(self.f, code="LOCKR-TWIN", publish=False)
		frappe.db.set_value("TEX Contract", broken["contract"], "contract_code", "LOCKR-TWIN")
		contracts.roll_version_statuses()                               # does not raise
		header = frappe.get_doc("TEX Contract", self.name)
		self.assertEqual((header.active_version, header.priority, [c.sales_channel for c in header.channels]),
		                 (v2, 4, ["OTA"]))
		ev = self._audit("contract.version_live")
		self.assertEqual((ev["new"]["version"], ev["new"]["selling"]["channels"]), (v2, ["OTA"]))
		self.assertEqual(frappe.db.get_value("TEX Contract Version", self.c["version"], "status"), "Superseded")
		# the broken contract is skipped and logged; its version flip is kept
		self.assertEqual(frappe.db.get_value("TEX Contract", broken["contract"], "active_version"),
		                 broken["version"])
		self.assertEqual(frappe.db.get_value("TEX Contract Version", broken["version"], "status"), "Superseded")
		self.assertTrue(frappe.db.exists("Error Log", {"method": ("like", f"%{broken['contract']}%")}))
		self.assertTrue(b2)

	def test_a_desk_copy_of_a_pre_g50_version_keeps_selling_terms(self):
		# finding 5: a version made in Desk from a published one (based_on set) without terms
		self._pre_g50(self.c["version"])
		self._header_channels(self.name, "OTA")
		v = frappe.get_doc({"doctype": "TEX Contract Version", "contract": self.name,
		                    "based_on": self.c["version"]}).insert(ignore_permissions=True)
		self.assertEqual(([c.sales_channel for c in v.channels], str(v.sale_to)), (["OTA"], str(fx.STAY_TO)))

	def test_p21_rerun_keeps_a_drafts_own_terms(self):
		# finding 6: p21 fills only drafts without selling terms of their own
		from kamra.tex.api import contracts as api

		v2 = contracts.new_draft(self.name)
		api.save_version(v2, {"selling": {"channels": ["OTA"], "priority": 9}})
		self._upgrade()
		d = frappe.get_doc("TEX Contract Version", v2)
		self.assertEqual((d.priority, [c.sales_channel for c in d.channels]), (9, ["OTA"]))

	def test_original_sale_date_pricing_uses_the_terms_on_sale_then(self):
		# finding 7: V2 stops selling on DIRECT_WEB; a stay sold on V1 is re-priced on V1's terms
		from kamra.tex.api import contracts as api

		offer = pick(search_std(fx.d(7, 10), fx.d(7, 13), [{"adults": 2}]))
		q = quoting.create_quote(offer["rooms"][0]["offer_key"])
		b = booking.create_booking(quote_ids=[q["quote_id"]], guest={
			"first_name": "Ori", "last_name": "Ginal", "email": "original@example.com"}, payment_method="Card")
		res = b["rooms"][0]["reservation"]
		v2 = contracts.new_draft(self.name)
		api.save_version(v2, {"selling": {"channels": ["OTA"]}})
		contracts.publish(v2)
		p = modification.propose(res, {"check_out": fx.d(7, 14)}, basis="ORIGINAL_SALE_DATE")
		self.assertEqual(p["proposed"]["contract"]["version"], self.c["version"])
		with self.assertRaises(frappe.ValidationError):                # on sale now: V2, not on DIRECT_WEB
			modification.propose(res, {"check_out": fx.d(7, 14)}, basis="CURRENT")
