"""G-51 (R-21, R-22): modification and simulator determinism (ADR-054).

- A sale time is never silently ignored: a change carries none of its own, a historical sale
  date is used only by its basis and is checked on the server (given, valid, not in the
  future), and so is the simulator's.
- HISTORICAL_SALE_DATE and a manual override go end to end (propose → apply → revision →
  audit) and need ``price.override`` at the hotel when applied, not only when proposed.
- The simulator for a past sale time reads the contract status and the coupon uses of that
  time: a contract archived since is simulated for a time it was Active, one suspended then
  is not; a coupon use given back since still counts, one made since does not. Repricing on
  the original sale date selects among the contracts Active then too.
- A proposal token is applied only by whoever proposed it: a staff user's by that user, a
  guest's through the manage page of its booking. Guest self-service keeps working.
"""

import json
from datetime import timedelta, timezone
from zoneinfo import ZoneInfo

import frappe
from frappe.utils import add_to_date, get_datetime, get_system_timezone, now_datetime

from kamra.tex.api import crs as crs_api
from kamra.tex.api import policies as policy_api
from kamra.tex.api import public
from kamra.tex.commercial import contracts
from kamra.tex.money import D
from kamra.tex.security import scope
from kamra.tex.services import booking, modification, quoting
from kamra.tex.tests.integration import fixtures as fx
from kamra.tex.tests.integration.test_channel_binding import as_user, grant, profile
from kamra.tex.tests.integration.test_commercial_flows import guest_books, setup_site_and_payments
from kamra.tex.tests.integration.test_critical_journey import TexTestCase, pick, search_std
from kamra.tex.tests.integration.test_self_service_money import paid

MODIFY = "G51 Modify"               # an agent: sees prices and reservations, modifies them
OVERRIDE = "G51 Override"           # held beside MODIFY by a revenue manager
PRICES = "G51 Prices only"
DT = "TEX Guest Change Request"


def sell(code: str | None = None, email: str = "g51@example.com") -> str:
	"""A guest books STD / AI / Flexible for 2 adults, 6/10–6/12 (400.00 on a 100 base), with
	``code`` if given. → the reservation."""
	frappe.set_user("Guest")  # nosemgrep: frappe-setuser -- anonymous booking-engine visitor
	codes = [code] if code else []
	offer = pick(search_std(fx.d(6, 10), fx.d(6, 12), [{"adults": 2}], promo_codes=codes))
	q = quoting.create_quote(offer["rooms"][0]["offer_key"], promo_codes=codes or None)
	assert q["ok"], q
	b = booking.create_booking(quote_ids=[q["quote_id"]], guest={"first_name": "Gee", "last_name": "Fiftyone",
	                                                             "email": email}, payment_method="Card")
	as_user("Administrator")
	return b["rooms"][0]["reservation"]


def raise_low_rate(contract: str, value: int) -> str:
	"""Publish a new version whose LOW base is ``value`` (now)."""
	as_user("Administrator")
	v2 = contracts.new_draft(contract)
	doc = frappe.get_doc("TEX Contract Version", v2)
	for r in doc.period_rates:
		if r.period_code == "LOW":
			r.value = value
	doc.save()
	contracts.publish(v2)
	return v2


def last_audit(action: str, name: str) -> dict:
	rows = frappe.get_all("TEX Audit Event", filters={"action": action, "reference_name": name},
	                      fields=["new_value", "old_value"], order_by="creation desc, name desc", limit=1)
	assert rows, f"no {action} audit for {name}"
	return json.loads(rows[0].new_value or "{}")


def revision(name: str):
	return frappe.get_doc("TEX Reservation Revision", name)


class DeterminismCase(TexTestCase):
	def setUp(self):
		super().setUp()
		try:
			self.c = fx.create_contract(self.f, code="G51")
			profile(MODIFY, ("price.view", "reservation.view", "reservation.modify"))
			profile(OVERRIDE, ("price.override",))
			profile(PRICES, ("price.view",))
			self.agent = fx.ensure_user("g51-agent@example.com", ["Call Center Agent"])
			self.agent2 = fx.ensure_user("g51-agent2@example.com", ["Call Center Agent"])
			self.rm = fx.ensure_user("g51-rm@example.com", ["Call Center Agent"])
			for u in (self.agent, self.agent2, self.rm):
				grant(u, fx.PROPERTY, MODIFY)
			grant(self.rm, fx.PROPERTY, OVERRIDE)
			scope.clear_cache()
		except Exception:
			self.tearDown()
			raise

	def revoke_override(self) -> None:
		as_user("Administrator")
		frappe.db.set_value("TEX Access Grant", {"user": self.rm, "permission_profile": OVERRIDE}, "disabled", 1)
		scope.clear_cache()


class TestSaleTimeInputs(DeterminismCase):
	"""A sale time given is used or refused, never ignored."""

	def test_a_change_carries_no_sale_time_of_its_own(self):
		res = sell()
		sold_at = now_datetime()
		as_user(self.rm)
		with self.assertRaisesRegex(frappe.ValidationError, "historical sale date basis"):
			modification.propose(res, {"check_out": str(fx.d(6, 13)), "sale_at": str(sold_at)})
		with self.assertRaisesRegex(frappe.ValidationError, "historical sale date basis"):
			crs_api.propose_modification(reservation=res, changes=json.dumps({"sale_at": str(sold_at)}))
		self.assertNotIn("sale_at", modification.EDITABLE)

	def test_a_sale_date_with_another_basis_is_refused(self):
		res = sell()
		sold_at = now_datetime()
		as_user(self.rm)
		for basis in ("CURRENT", "ORIGINAL_VERSION", "ORIGINAL_SALE_DATE"):
			with self.subTest(basis=basis), self.assertRaisesRegex(frappe.ValidationError, "only with the historical"):
				crs_api.propose_modification(reservation=res, changes=json.dumps({"check_out": str(fx.d(6, 13))}),
				                             basis=basis, basis_sale_at=str(sold_at))

	def test_a_historical_sale_date_is_checked_on_the_server(self):
		res = sell()
		as_user(self.rm)
		change = {"check_out": str(fx.d(6, 13))}
		for value, why in ((None, "Choose the historical sale date"), ("", "Choose the historical sale date"),
		                   ("not a date", "not a valid date"),
		                   (str(add_to_date(now_datetime(), hours=1)), "cannot be in the future")):
			with self.subTest(value=value), self.assertRaisesRegex(frappe.ValidationError, why):
				modification.propose(res, change, basis="HISTORICAL_SALE_DATE", basis_sale_at=value)

	def test_the_simulated_sale_time_is_checked_on_the_server(self):
		res = sell()
		for value, why in (("", "Choose the sale time"), ("31 Febtember", "not a valid date"),
		                   (str(add_to_date(now_datetime(), days=1)), "cannot be in the future")):
			with self.subTest(value=value), self.assertRaisesRegex(frappe.ValidationError, why):
				crs_api.simulate(reservation=res, sale_at=value)

	def test_the_simulator_needs_to_see_the_reservation(self):
		res = sell()
		sold_at = now_datetime()
		viewer = fx.ensure_user("g51-prices@example.com", ["Call Center Agent"])
		grant(viewer, fx.PROPERTY, PRICES)
		as_user(viewer)
		with self.assertRaises(frappe.PermissionError):
			crs_api.simulate(reservation=res, sale_at=str(sold_at))
		as_user(self.agent)
		self.assertEqual(crs_api.simulate(reservation=res, sale_at=str(sold_at))["simulated"]["totals"]["total"],
		                 "400.00")


	def test_a_sale_time_with_a_utc_offset_is_read_in_the_hotels_time_zone(self):
		# review L1: an ISO time with an offset ("Z", "+03:00") is the same moment in the site's
		# time zone, never an HTTP 500 (an aware time compared with the site's naive clock)
		res = sell()
		sold_at = now_datetime()
		site = sold_at.replace(tzinfo=ZoneInfo(get_system_timezone()))
		in_utc = site.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
		in_istanbul = site.astimezone(timezone(timedelta(hours=3))).isoformat()
		for value in (in_utc, in_istanbul):
			with self.subTest(value=value):
				sim = crs_api.simulate(reservation=res, sale_at=value)
				self.assertEqual((get_datetime(sim["simulated_sale_at"]), sim["difference"]), (sold_at, "0.00"))
		as_user(self.rm)
		p = crs_api.propose_modification(reservation=res, changes=json.dumps({"check_out": str(fx.d(6, 13))}),
		                                 basis="HISTORICAL_SALE_DATE", basis_sale_at=in_istanbul)
		self.assertEqual(get_datetime(p["pricing_sale_at"]), sold_at)
		later = add_to_date(site, hours=2).astimezone(timezone.utc).isoformat()
		with self.assertRaisesRegex(frappe.ValidationError, "cannot be in the future"):
			crs_api.simulate(reservation=res, sale_at=later)
		with self.assertRaisesRegex(frappe.ValidationError, "cannot be in the future"):
			crs_api.propose_modification(reservation=res, changes=json.dumps({"check_out": str(fx.d(6, 13))}),
			                             basis="HISTORICAL_SALE_DATE", basis_sale_at=later)


class TestHistoricalSaleDate(DeterminismCase):
	"""HISTORICAL_SALE_DATE end to end: priced on the version live then, applied, recorded."""

	def test_a_change_priced_as_if_sold_earlier_is_applied_and_recorded(self):
		res = sell()
		sold_at = now_datetime()
		v1 = self.c["version"]
		raise_low_rate(self.c["contract"], 150)               # today: 300 a night for two
		as_user(self.rm)
		change = {"check_out": str(fx.d(6, 13))}
		now = modification.propose(res, change, basis="CURRENT")
		self.assertEqual(now["proposed"]["totals"]["total"], "900.00")
		p = modification.propose(res, change, basis="HISTORICAL_SALE_DATE", basis_sale_at=str(sold_at))
		self.assertEqual((p["proposed"]["totals"]["total"], p["proposed"]["contract"]["version"]), ("600.00", v1))
		self.assertEqual(get_datetime(p["pricing_sale_at"]), sold_at)
		self.assertEqual(p["difference"], "200.00")
		out = modification.apply(p["proposal_token"], reason="Honour the price of the first sale")
		self.assertEqual((out["old_total"], out["new_total"], out["difference"]), ("400.00", "600.00", "200.00"))
		r = frappe.db.get_value("Reservation", res, ["tex_total_amount", "tex_contract_version", "check_out_date"],
		                        as_dict=True)
		self.assertEqual((D(r.tex_total_amount), r.tex_contract_version, str(r.check_out_date)),
		                 (D("600.00"), v1, str(fx.d(6, 13))))
		rev = revision(out["revision"])
		self.assertEqual((rev.pricing_basis, get_datetime(rev.basis_sale_at), rev.change_type, rev.actor),
		                 ("HISTORICAL_SALE_DATE", sold_at, "Multiple", self.rm))       # dates + sale date
		self.assertEqual((D(rev.old_amount), D(rev.new_amount)), (D("400"), D("600")))
		self.assertFalse(rev.override_amount)
		self.assertEqual(json.loads(rev.snapshot_after)["basis"], "HISTORICAL_SALE_DATE")
		as_user("Administrator")
		audit = last_audit("reservation.modify", res)
		self.assertEqual((audit["basis"], get_datetime(audit["pricing_sale_at"]), audit["total"], audit["revision"]),
		                 ("HISTORICAL_SALE_DATE", sold_at, "600.00", out["revision"]))
		self.assertNotIn("computed_total", audit)

	def test_repricing_only_the_sale_date_is_a_sale_date_change(self):
		res = sell()
		sold_at = now_datetime()
		raise_low_rate(self.c["contract"], 150)
		as_user(self.rm)
		current = modification.propose(res, {"adults": 2}, basis="CURRENT")
		modification.apply(current["proposal_token"], reason="repriced today")
		self.assertEqual(D(frappe.db.get_value("Reservation", res, "tex_total_amount")), D("600.00"))
		back = modification.propose(res, {}, basis="HISTORICAL_SALE_DATE", basis_sale_at=str(sold_at))
		out = modification.apply(back["proposal_token"], reason="price of the day it was sold")
		self.assertEqual((out["new_total"], revision(out["revision"]).change_type), ("400.00", "Sale Date"))

	def test_proposing_on_a_historical_sale_date_needs_price_override(self):
		res = sell()
		as_user(self.agent)
		with self.assertRaises(frappe.PermissionError):
			modification.propose(res, {"check_out": str(fx.d(6, 13))}, basis="HISTORICAL_SALE_DATE",
			                     basis_sale_at=str(now_datetime()))

	def test_applying_a_historical_proposal_needs_price_override_again(self):
		res = sell()
		sold_at = now_datetime()
		as_user(self.rm)
		p = modification.propose(res, {"check_out": str(fx.d(6, 13))}, basis="HISTORICAL_SALE_DATE",
		                         basis_sale_at=str(sold_at))
		self.revoke_override()                                 # the right is gone before the apply
		as_user(self.rm)
		with self.assertRaisesRegex(frappe.PermissionError, "price.override"):
			modification.apply(p["proposal_token"], reason="honour the old price")
		self.assertEqual(str(frappe.db.get_value("Reservation", res, "check_out_date")), str(fx.d(6, 12)))


class TestManualOverride(DeterminismCase):
	"""A manual price: the proposal is priced, staff set the amount with a reason."""

	def test_an_override_is_applied_and_recorded_next_to_the_computed_price(self):
		res = sell()
		as_user(self.rm)
		p = modification.propose(res, {"check_out": str(fx.d(6, 13))})
		self.assertEqual(p["proposed"]["totals"]["total"], "600.00")
		out = crs_api.apply_modification(proposal_token=p["proposal_token"], reason="Goodwill for the delay",
		                                 override_amount="550")
		self.assertEqual((out["new_total"], out["difference"]), ("550.00", "150.00"))
		r = frappe.db.get_value("Reservation", res, ["tex_total_amount", "amount_after_tax", "tex_booking"],
		                        as_dict=True)
		self.assertEqual((D(r.tex_total_amount), D(r.amount_after_tax)), (D("550.00"), D("550.00")))
		self.assertEqual(D(frappe.db.get_value("TEX Booking", r.tex_booking, "total_amount")), D("550.00"))
		rev = revision(out["revision"])
		self.assertEqual((rev.pricing_basis, D(rev.override_amount), D(rev.new_amount), rev.change_type),
		                 ("MANUAL", D("550"), D("550"), "Multiple"))                 # dates + override
		self.assertEqual(rev.reason, "Goodwill for the delay")
		self.assertEqual(json.loads(rev.snapshot_after)["override_amount"], "550.00")
		as_user("Administrator")
		audit = last_audit("reservation.modify", res)
		self.assertEqual((audit["total"], audit["computed_total"], audit["override"], audit["basis"]),
		                 ("550.00", "600.00", True, "CURRENT"))

	def test_an_override_alone_is_a_price_override(self):
		res = sell()
		as_user(self.rm)
		p = modification.propose(res, {})
		out = modification.apply(p["proposal_token"], reason="Corporate rate agreed by phone", override_amount="380")
		self.assertEqual((out["new_total"], revision(out["revision"]).change_type), ("380.00", "Price Override"))

	def priced_by_hand(self) -> str:
		"""Staff price the stay by hand at 380 (the engine's 400). → the reservation."""
		res = sell()
		as_user(self.rm)
		p = modification.propose(res, {})
		modification.apply(p["proposal_token"], reason="Corporate rate agreed by phone", override_amount="380")
		return res

	def test_a_change_of_a_stay_priced_by_hand_needs_a_choice(self):
		"""Y-7b (D-9, ADR-065): a later change shows the price set by hand and the change's price; it is
		refused until staff choose one, never silently repriced."""
		res = self.priced_by_hand()
		p = modification.propose(res, {"check_out": str(fx.d(6, 13))})
		self.assertEqual(p["manual_price"], {"amount": "380.00", "engine_total": "600.00"})
		with self.assertRaisesRegex(frappe.ValidationError, r"380\.00.*600\.00"):
			modification.apply(p["proposal_token"], reason="one more night")
		self.assertEqual(D(frappe.db.get_value("Reservation", res, "tex_total_amount")), D("380.00"))

	def test_the_price_set_by_hand_is_kept_when_staff_keep_it(self):
		res = self.priced_by_hand()
		p = modification.propose(res, {"check_out": str(fx.d(6, 13))})
		out = crs_api.apply_modification(proposal_token=p["proposal_token"], reason="one more night, same price",
		                                 override_amount=p["manual_price"]["amount"])
		self.assertEqual(out["new_total"], "380.00")
		rev = revision(out["revision"])
		self.assertEqual((rev.pricing_basis, json.loads(rev.changes_json)["priced"]["total"]), ("MANUAL", "600.00"))

	def test_staff_without_price_override_take_the_changes_price_and_it_is_audited(self):
		res = self.priced_by_hand()
		as_user(self.agent)
		p = modification.propose(res, {"check_out": str(fx.d(6, 13))})
		out = crs_api.apply_modification(proposal_token=p["proposal_token"], reason="one more night", reprice=1)
		self.assertEqual(out["new_total"], "600.00")
		self.assertEqual(D(frappe.db.get_value("Reservation", res, "tex_total_amount")), D("600.00"))
		dropped = {"amount": "380.00", "engine_total": "600.00"}
		self.assertEqual(json.loads(revision(out["revision"]).changes_json)["manual_price_dropped"], dropped)
		as_user("Administrator")
		self.assertEqual({k: last_audit("reservation.manual_price_dropped", res)[k] for k in dropped}, dropped)

	def test_an_override_on_a_historical_sale_date(self):
		res = sell()
		sold_at = now_datetime()
		raise_low_rate(self.c["contract"], 150)
		as_user(self.rm)
		p = modification.propose(res, {"check_out": str(fx.d(6, 13))}, basis="HISTORICAL_SALE_DATE",
		                         basis_sale_at=str(sold_at))
		out = modification.apply(p["proposal_token"], reason="old price, rounded down", override_amount="590")
		rev = revision(out["revision"])
		self.assertEqual((rev.pricing_basis, D(rev.override_amount), get_datetime(rev.basis_sale_at)),
		                 ("MANUAL", D("590"), sold_at))
		# the revision also says what the engine computed, and on which basis (review, minor)
		self.assertEqual(json.loads(rev.changes_json)["priced"], {"basis": "HISTORICAL_SALE_DATE", "total": "600.00"})
		listed = next(r for r in modification.revisions(res) if r["name"] == out["revision"])
		self.assertEqual(listed["changes"]["priced"]["basis"], "HISTORICAL_SALE_DATE")
		as_user("Administrator")
		audit = last_audit("reservation.modify", res)
		self.assertEqual((audit["basis"], audit["computed_total"], audit["total"]),
		                 ("HISTORICAL_SALE_DATE", "600.00", "590.00"))

	def test_an_override_needs_price_override_when_applied(self):
		res = sell()
		as_user(self.agent)
		p = modification.propose(res, {"check_out": str(fx.d(6, 13))})
		with self.assertRaisesRegex(frappe.PermissionError, "price.override"):
			modification.apply(p["proposal_token"], reason="discount", override_amount="500")
		as_user(self.rm)
		p = modification.propose(res, {"check_out": str(fx.d(6, 13))})
		self.revoke_override()
		as_user(self.rm)
		with self.assertRaisesRegex(frappe.PermissionError, "price.override"):
			modification.apply(p["proposal_token"], reason="discount", override_amount="500")
		self.assertEqual(D(frappe.db.get_value("Reservation", res, "tex_total_amount")), D("400.00"))


class TestSimulatorAsOfTheSaleTime(DeterminismCase):
	"""The simulator for a past moment reads the contract status and coupon uses of then."""

	def test_an_archived_contract_is_simulated_for_a_time_it_was_on_sale(self):
		res = sell()
		sold_at = now_datetime()
		contracts.set_status(self.c["contract"], "archive", "Season over")
		then = modification.simulate(res, sold_at)
		self.assertIn("simulated", then, then)
		self.assertEqual((then["simulated"]["totals"]["total"], then["difference"]), ("400.00", "0.00"))
		self.assertEqual(then["contract"], {"contract": self.c["contract"], "code": "G51", "status_now": "Archived"})
		now = modification.simulate(res, now_datetime())
		self.assertEqual((now["sellable"], now["reasons"][0]["code"]), (False, "NO_CONTRACT"))

	def test_a_contract_suspended_at_the_time_is_not_simulated_then(self):
		res = sell()
		contracts.set_status(self.c["contract"], "suspend", "Overbooked")
		stopped = now_datetime()
		contracts.set_status(self.c["contract"], "resume", "Rooms back")
		then = modification.simulate(res, stopped)
		self.assertEqual((then["sellable"], then["reasons"][0]["code"]), (False, "NO_CONTRACT"))
		self.assertEqual(modification.simulate(res, now_datetime())["simulated"]["totals"]["total"], "400.00")

	def _code(self, code: str, **kw) -> str:
		as_user("Administrator")
		doc = policy_api.save_record("TEX Promotion", {
			"promotion_name": f"Code {code}", "property": fx.PROPERTY, "trigger": "Code", "code": code,
			"value_type": "PERCENT", "value": 10, "applies_to": "ACCOMMODATION", **kw})
		policy_api.activate("TEX Promotion", doc["name"], at=str(add_to_date(now_datetime(), minutes=-1)))
		return doc["name"]

	def _code_applied(self, quote: dict, promo: str) -> bool:
		return any(x["promo_id"] == promo and x["applied"] for x in quote.get("promotions") or [])

	def test_coupon_uses_are_counted_as_held_at_the_sale_time(self):
		promo = self._code("G51ONE", usage_limit=1)
		first = sell("G51ONE", email="first@example.com")          # takes the only use
		res = sell("G51ONE", email="second@example.com")           # the code no longer applies
		snap = json.loads(frappe.db.get_value("Reservation", res, "tex_pricing_snapshot"))
		self.assertEqual(snap["request"]["promo_codes"], ["G51ONE"])
		self.assertFalse(self._code_applied(snap, promo))
		self.assertEqual(D(snap["totals"]["total"]), D("400.00"))
		sold_at = now_datetime()
		booking.cancel_reservation(first, reason="plans changed")   # the use is given back
		self.assertEqual(frappe.db.get_value("TEX Promotion Redemption", {"reservation": first}, "status"),
		                 "Released")
		freed = now_datetime()
		# at the sale time the use was held: the simulation reproduces the price sold
		then = modification.simulate(res, sold_at)
		self.assertFalse(self._code_applied(then["simulated"], promo))
		self.assertEqual((then["simulated"]["totals"]["total"], then["difference"]), ("400.00", "0.00"))
		# once it was given back, the code applied; a use made later does not count before it was made
		later = sell("G51ONE", email="third@example.com")
		self.assertEqual(frappe.db.get_value("TEX Promotion Redemption", {"reservation": later}, "status"), "Reserved")
		between = modification.simulate(res, freed)
		self.assertTrue(self._code_applied(between["simulated"], promo))
		self.assertEqual(between["simulated"]["totals"]["total"], "360.00")
		self.assertFalse(self._code_applied(modification.simulate(res, now_datetime())["simulated"], promo))

	def test_a_released_use_keeps_when_it_was_released(self):
		self._code("G51REL", usage_limit=5)
		res = sell("G51REL", email="rel@example.com")
		booking.cancel_reservation(res, reason="plans changed")
		red = frappe.get_doc("TEX Promotion Redemption", {"reservation": res})
		self.assertEqual(red.status, "Released")
		self.assertTrue(red.released_at)
		released_at = get_datetime(red.released_at)
		red.status = "Committed"
		with self.assertRaises(frappe.ValidationError):
			red.save(ignore_permissions=True)                   # a use given back stays given back
		red.reload()
		red.released_at = add_to_date(released_at, days=1)
		red.save(ignore_permissions=True)
		self.assertEqual(get_datetime(frappe.db.get_value("TEX Promotion Redemption", red.name, "released_at")),
		                 released_at)                            # written once


class TestRepricingOnThePastSaleDate(DeterminismCase):
	"""ORIGINAL_SALE_DATE selects among the contracts that were on sale at the original sale."""

	def test_the_original_sale_date_reprices_on_a_contract_archived_since(self):
		res = sell()
		v1 = self.c["version"]
		contracts.set_status(self.c["contract"], "archive", "Season over")
		as_user(self.rm)
		change = {"check_out": str(fx.d(6, 13))}
		with self.assertRaisesRegex(frappe.ValidationError, "No contract sold this stay"):
			modification.propose(res, change, basis="CURRENT")      # nothing is on sale today
		p = modification.propose(res, change, basis="ORIGINAL_SALE_DATE")
		self.assertEqual((p["proposed"]["totals"]["total"], p["proposed"]["contract"]["version"]), ("600.00", v1))
		out = modification.apply(p["proposal_token"], reason="one more night at the price sold")
		self.assertEqual(revision(out["revision"]).pricing_basis, "ORIGINAL_SALE_DATE")


class TestProposalBinding(DeterminismCase):
	"""A staff proposal is applied only by the user who proposed it, at its hotel."""

	def test_only_the_proposer_applies_a_proposal(self):
		res = sell()
		as_user(self.agent)
		p = crs_api.propose_modification(reservation=res, changes=json.dumps({"check_out": str(fx.d(6, 13))}))
		for other in (self.agent2, self.rm, "Administrator"):
			as_user(other)
			with self.subTest(user=other), self.assertRaisesRegex(frappe.PermissionError, "another user"):
				crs_api.apply_modification(proposal_token=p["proposal_token"], reason="not mine")
		self.assertEqual(str(frappe.db.get_value("Reservation", res, "check_out_date")), str(fx.d(6, 12)))
		as_user(self.agent)
		out = crs_api.apply_modification(proposal_token=p["proposal_token"], reason="one more night")
		self.assertEqual((out["new_total"], revision(out["revision"]).actor), ("600.00", self.agent))

	def test_a_proposal_names_its_proposer_hotel_and_booking(self):
		res = sell()
		as_user(self.agent)
		p = modification.propose(res, {"check_out": str(fx.d(6, 13))})
		body = quoting.verify(p["proposal_token"], kind="proposal")
		self.assertEqual((body["origin"], body["by"], body["property"]), ("staff", self.agent, fx.PROPERTY))
		self.assertEqual(body["booking"], frappe.db.get_value("Reservation", res, "tex_booking"))
		# a token re-pointed at another reservation (a signing key known) still names this one's booking
		other = sell(email="other@example.com")
		as_user(self.agent)
		moved = quoting.sign({**body, "reservation": other,
		                      "modified": str(frappe.db.get_value("Reservation", other, "modified"))})
		with self.assertRaisesRegex(frappe.PermissionError, "another reservation"):
			modification.apply(moved, reason="moved")


class TestGuestProposals(TexTestCase):
	"""Guest proposals are bound to the manage page of their booking; staff ones never reach it."""

	def setUp(self):
		super().setUp()
		setup_site_and_payments(self.f)

	def _booked(self, session: str) -> dict:
		b = guest_books(session=session)
		paid(b["payment"])
		return b

	def _guest_propose(self, b: dict, check_out) -> dict:
		frappe.set_user("Guest")  # nosemgrep: frappe-setuser -- the guest on the manage page
		return public.manage_propose(token=b["manage_token"], reservation=b["rooms"][0]["reservation"],
		                             changes={"check_out": str(check_out)})

	def test_guest_self_service_still_applies_the_guests_own_proposal(self):
		b = self._booked("g51-self")
		res = b["rooms"][0]["reservation"]
		up = self._guest_propose(b, fx.d(6, 14))
		self.assertEqual(quoting.verify(up["proposal_token"], kind="proposal")["origin"], "guest")
		frappe.set_user("Guest")  # nosemgrep: frappe-setuser -- the guest accepts
		out = public.manage_apply(token=b["manage_token"], proposal_token=up["proposal_token"])
		self.assertEqual(out["status"], "payment_required")
		paid(out["payment"])
		self.assertEqual(str(frappe.db.get_value("Reservation", res, "check_out_date")), str(fx.d(6, 14)))
		self.assertEqual(frappe.db.get_value(DT, out["request"], "status"), "Applied")

	def test_a_guests_proposal_is_not_applied_by_staff(self):
		b = self._booked("g51-guest-staff")
		up = self._guest_propose(b, fx.d(6, 14))
		as_user("Administrator")
		with self.assertRaisesRegex(frappe.PermissionError, "another user"):
			crs_api.apply_modification(proposal_token=up["proposal_token"], reason="applied for the guest")
		self.assertEqual(str(frappe.db.get_value("Reservation", b["rooms"][0]["reservation"], "check_out_date")),
		                 str(fx.d(6, 13)))

	def test_a_staff_proposal_is_not_accepted_on_the_manage_page(self):
		b = self._booked("g51-staff-guest")
		res = b["rooms"][0]["reservation"]
		sold_at = now_datetime()
		raise_low_rate(frappe.db.get_value("Reservation", res, "tex_contract"), 150)
		# staff price one more night as if sold before the rise: cheaper than today's price
		p = modification.propose(res, {"check_out": str(fx.d(6, 14))}, basis="HISTORICAL_SALE_DATE",
		                         basis_sale_at=str(sold_at))
		frappe.set_user("Guest")  # nosemgrep: frappe-setuser -- the token brought to the manage page
		with self.assertRaisesRegex(frappe.PermissionError, "not proposed on your booking page"):
			public.manage_apply(token=b["manage_token"], proposal_token=p["proposal_token"])
		as_user("Administrator")
		self.assertEqual(frappe.db.count(DT, {"booking": b["booking"]}), 0)
		self.assertEqual(str(frappe.db.get_value("Reservation", res, "check_out_date")), str(fx.d(6, 13)))

	def test_a_paid_change_applies_at_its_price_after_a_suspend(self):
		# the guest accepted the price and paid by the deadline: the change is re-derived as of the
		# moment it was priced, when the contract was on sale (a stop sale acts on new sales)
		b = self._booked("g51-paid-suspend")
		res = b["rooms"][0]["reservation"]
		up = self._guest_propose(b, fx.d(6, 14))
		frappe.set_user("Guest")  # nosemgrep: frappe-setuser -- the guest accepts
		out = public.manage_apply(token=b["manage_token"], proposal_token=up["proposal_token"])
		self.assertEqual(out["status"], "payment_required")
		as_user("Administrator")
		contract = frappe.db.get_value("Reservation", res, "tex_contract")
		contracts.set_status(contract, "suspend", "Overbooked")
		with self.assertRaisesRegex(frappe.ValidationError, "No contract sold this stay"):
			modification.propose(res, {"check_out": str(fx.d(6, 15))}, basis="CURRENT")   # staff, today: stopped
		paid(out["payment"])
		as_user("Administrator")
		self.assertEqual(frappe.db.get_value(DT, out["request"], "status"), "Applied")
		r = frappe.db.get_value("Reservation", res, ["check_out_date", "tex_total_amount"], as_dict=True)
		self.assertEqual((str(r.check_out_date), D(r.tex_total_amount)), (str(fx.d(6, 14)), D(up["new_total"])))

	def _requested_extension(self, session: str) -> tuple[dict, dict, str]:
		"""A paid-deposit booking whose guest extends by a night while the hotel takes no card
		online: the change waits for the hotel (Requested, settlement "staff")."""
		b = self._booked(session)
		as_user("Administrator")
		frappe.db.set_value("TEX Payment Method Rule", {"property": fx.PROPERTY, "method": "Card"}, "disabled", 1)
		up = self._guest_propose(b, fx.d(6, 14))
		frappe.set_user("Guest")  # nosemgrep: frappe-setuser -- the guest accepts
		out = public.manage_apply(token=b["manage_token"], proposal_token=up["proposal_token"])
		self.assertEqual((out["status"], out["settlement"]["kind"]), ("requested", "staff"))
		as_user("Administrator")
		return b, up, out["request"]

	def _listed(self, request: str) -> dict:
		return next(r for r in crs_api.guest_change_requests(property=fx.PROPERTY, needs_staff=1)
		            if r["name"] == request)

	def test_approving_a_request_on_a_contract_stopped_since_is_refused(self):
		# review M1: a request waits for the hotel without a time limit; approving it after a stop
		# sale must not sell the stopped contract (ADR-045); the approver sees why beforehand
		b, up, request = self._requested_extension("g51-approve-stopped")
		res = b["rooms"][0]["reservation"]
		contract = frappe.db.get_value("Reservation", res, "tex_contract")
		code = frappe.db.get_value("TEX Contract", contract, "contract_code")
		row = self._listed(request)
		self.assertEqual(row["contract"], {"contract": contract, "code": code, "status": "Active", "on_sale": True})
		self.assertIsNone(row["approve_blocked"])
		contracts.set_status(contract, "suspend", "Overbooked")
		row = self._listed(request)
		self.assertEqual((row["contract"]["status"], row["contract"]["on_sale"]), ("Suspended", False))
		self.assertIn("no longer sells", row["approve_blocked"])
		with self.assertRaisesRegex(contracts.ContractSuspended, f"{code} no longer sells"):
			crs_api.resolve_guest_change(request=request, action="approve", reason="collect at check-in")
		self.assertEqual(frappe.db.get_value(DT, request, "status"), "Requested")
		self.assertEqual(str(frappe.db.get_value("Reservation", res, "check_out_date")), str(fx.d(6, 13)))
		# rejecting it stays possible; once the contract sells again it is approved at the price shown
		contracts.set_status(contract, "resume", "Rooms back")
		done = crs_api.resolve_guest_change(request=request, action="approve", reason="collect at check-in")
		self.assertEqual(done["status"], "Approved")
		r = frappe.db.get_value("Reservation", res, ["check_out_date", "tex_total_amount"], as_dict=True)
		self.assertEqual((str(r.check_out_date), D(r.tex_total_amount)), (str(fx.d(6, 14)), D(up["new_total"])))

	def test_an_archived_contract_blocks_approval_but_not_rejection(self):
		b, _up, request = self._requested_extension("g51-approve-archived")
		contract = frappe.db.get_value("Reservation", b["rooms"][0]["reservation"], "tex_contract")
		contracts.set_status(contract, "archive", "Season over")
		with self.assertRaises(contracts.ContractNotOnSale):
			crs_api.resolve_guest_change(request=request, action="approve", reason="ok")
		self.assertEqual(crs_api.resolve_guest_change(request=request, action="reject", reason="no longer sold")[
			"status"], "Rejected")


class TestChangedPromotionCodes(TexTestCase):
	"""2D-1 0e: a change's promotion codes are keyed as a quote keys them (`code_key`, O-31), so the
	re-priced request and its snapshot say WINTER, never WİNTER."""

	def test_a_changed_code_is_stored_by_its_key(self):
		from kamra.tex.pricing import serialize
		from kamra.tex.pricing.model import StayRequest

		sold = StayRequest(property=fx.PROPERTY, room_type=self.f["room_types"]["STD"], board="AI",
		                   check_in=fx.d(6, 10), check_out=fx.d(6, 13), adults=2, sale_at=now_datetime(),
		                   market="DE", channel="DIRECT_WEB", sell_currency="EUR")
		res = frappe._dict(name="2D1-0E", tex_pricing_snapshot=json.dumps(
			{"request": serialize.request_to_dict(sold)}, default=str))
		req, _snap = modification.build_changed_request(res, {"promo_codes": [" wİnter ", "yaz", "  "]},
		                                                now_datetime())
		self.assertEqual(req.promo_codes, ("WINTER", "YAZ"))
