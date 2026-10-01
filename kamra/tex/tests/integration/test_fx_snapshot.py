"""G-56 (R-15): a cross-currency booking records every FX rate it was priced with.

A EUR contract sold in TRY, with a EUR extra, a USD extra and a fixed EUR promotion: the
reservation's price-locked snapshot holds each rate (pair, exact rate, provider, rate
date, policy, sale time) and what it converted. The FX tables changing afterwards changes
neither the snapshot nor its re-explanation; the ORIGINAL_* bases reprice with the
recorded rates, CURRENT with today's (ADR-051)."""

import json

import frappe
from frappe.utils import add_days, add_to_date, getdate, now_datetime

from kamra.tex.commercial import revisions
from kamra.tex.money import D
from kamra.tex.security import scope
from kamra.tex.services import booking, modification, quoting
from kamra.tex.tests.integration import fixtures as fx
from kamra.tex.tests.integration.test_critical_journey import TexTestCase, pick


def _rate(provider: str, base: str, quote: str, rate, day, fetched_at) -> str:
	doc = frappe.get_doc({"doctype": "TEX FX Rate", "provider": provider, "base_currency": base,
	                      "quote_currency": quote, "rate_type": "FOREX_SELLING", "rate": rate, "rate_date": day,
	                      "fetched_at": fetched_at, "source_ref": "test"})
	doc.insert(ignore_permissions=True)
	return doc.name


def _live(doctype: str, payload: dict) -> str:
	doc = frappe.get_doc({"doctype": doctype, **payload}).insert(ignore_permissions=True)
	revisions.activate(doctype, doc.name, at="2020-01-01 00:00:00", backdate=True)   # on sale at the sale time
	return doc.name


def _rates(snap: dict) -> dict:
	return {(r["from"], r["to"]): r for r in snap.get("fx_rates") or []}


def _fixed(r: dict) -> dict:
	"""What a recorded rate says, without where the record came from."""
	return {k: v for k, v in r.items() if k != "origin"}


class TestCrossCurrencySnapshot(TexTestCase):
	def setUp(self):
		super().setUp()
		now = now_datetime()
		today = getdate(now)
		# nothing left over from elsewhere decides these rates
		frappe.db.delete("TEX FX Rate", {"provider": "TCMB", "base_currency": "EUR", "quote_currency": "TRY"})
		for pair in (("EUR", "TRY"), ("USD", "TRY")):
			frappe.db.delete("TEX FX Policy", {"property": fx.PROPERTY, "from_currency": pair[0],
			                                   "to_currency": pair[1]})
		fx.create_contract(self.f, code="FXC")
		self.yesterday = add_days(today, -1)
		self.eur_rate = _rate("TCMB", "EUR", "TRY", 50, self.yesterday, add_to_date(now, days=-1))
		self.eur_policy = _live("TEX FX Policy", {"property": fx.PROPERTY, "from_currency": "EUR",
		                                          "to_currency": "TRY", "mode": "PROVIDER_PERCENT",
		                                          "provider": "TCMB", "rate_type": "FOREX_SELLING",
		                                          "adjustment": 2, "max_age_days": 4})
		self.usd_policy = _live("TEX FX Policy", {"property": fx.PROPERTY, "from_currency": "USD",
		                                          "to_currency": "TRY", "mode": "MANUAL", "manual_rate": 40})
		_live("TEX Extra", {"property": fx.PROPERTY, "extra_code": "SPA", "extra_name": "Spa ritual",
		                    "category": "Spa", "pricing_mode": "RESERVATION", "currency": "USD", "amount": 30,
		                    "tax_category": "SERVICE"})
		self.promo = _live("TEX Promotion", {"promotion_name": "20 EUR off", "property": fx.PROPERTY,
		                                     "trigger": "Automatic", "kind": "MARKET", "value_type": "FIXED_STAY",
		                                     "value": 20, "currency": "EUR", "applies_to": "ACCOMMODATION",
		                                     "stackable": 1})
		self.ci, self.co = fx.d(6, 10), fx.d(6, 13)
		res = quoting.search(properties=[fx.PROPERTY], check_in=self.ci, check_out=self.co, rooms=[{"adults": 2}],
		                     market="DE", channel="DIRECT_WEB", currency="TRY")
		offer = pick(res["properties"][0])
		q = quoting.create_quote(offer["rooms"][0]["offer_key"], extras=[{"code": "TRF"}, {"code": "SPA"}])
		self.assertTrue(q["ok"], q)
		b = booking.create_booking(quote_ids=[q["quote_id"]], guest={
			"first_name": "Deniz", "last_name": "Kaya", "email": "deniz@example.com"}, payment_method="Card",
			confirm_without_payment=True, idempotency_key="g56-fx")
		self.res = b["rooms"][0]["reservation"]
		self.sold = json.loads(frappe.db.get_value("Reservation", self.res, "tex_pricing_snapshot"))
		self.sold_at = modification.original_priced_at(frappe.get_doc("Reservation", self.res), self.sold)

	def _tables_change(self):
		"""After the sale: the manual USD rate is revised, and a TCMB EUR rate of today is
		imported stamped with its publication time, before the sale (a late import)."""
		draft = revisions.revise("TEX FX Policy", self.usd_policy)
		frappe.db.set_value("TEX FX Policy", draft, "manual_rate", 45)
		revisions.activate("TEX FX Policy", draft)
		_rate("TCMB", "EUR", "TRY", 55, getdate(self.sold_at), add_to_date(self.sold_at, minutes=-1))

	def test_the_snapshot_records_every_rate_it_was_priced_with(self):
		rates = _rates(self.sold)
		self.assertEqual(set(rates), {("EUR", "TRY"), ("USD", "TRY")})
		eur, usd = rates[("EUR", "TRY")], rates[("USD", "TRY")]
		self.assertEqual({k: eur[k] for k in ("mode", "sell_rate", "provider", "provider_rate", "provider_rate_id",
		                                     "rate_date", "adjustment", "policy_id")},
		                 {"mode": "PROVIDER_PERCENT", "sell_rate": "51.000000", "provider": "TCMB",
		                  "provider_rate": "50.000000", "provider_rate_id": self.eur_rate,
		                  "rate_date": str(self.yesterday), "adjustment": "2.000000", "policy_id": self.eur_policy})
		self.assertEqual(eur["as_of"], self.sold["request"]["sale_at"])
		self.assertEqual(set(eur["used_for"]), {"accommodation", "cost", "extra:TRF", f"promotion:{self.promo}"})
		self.assertEqual((usd["mode"], usd["sell_rate"], usd["policy_id"], usd["used_for"]),
		                 ("MANUAL", "40.000000", self.usd_policy, ["extra:SPA"]))
		extras = {e["code"]: e for e in self.sold["extras"]}
		self.assertEqual((D(extras["TRF"]["amount"]), D(extras["SPA"]["amount"])), (D("2040"), D("1200")))
		promo = next(p for p in self.sold["promotions"] if p["promo_id"] == self.promo)
		self.assertTrue(promo["applied"])
		self.assertEqual(D(promo["discount"]), D("1020"))                  # 20 EUR × 51
		uses = {s["params"]["use"]: s for s in self.sold["explanation"] if s["code"] == "FX"}
		self.assertEqual(set(uses), {"accommodation", "cost", "extra:TRF", "extra:SPA", f"promotion:{self.promo}"})
		self.assertIn(f"TCMB 50.000000 of {self.yesterday}", uses[f"promotion:{self.promo}"]["text"])
		self.assertEqual(uses["extra:SPA"]["params"]["policy"], self.usd_policy)
		# the Original revision keeps the same record
		first = frappe.db.get_value("TEX Reservation Revision", {"reservation": self.res, "change_type": "Original"},
		                            "snapshot_after")
		self.assertEqual(json.loads(first)["fx_rates"], self.sold["fx_rates"])

	def test_new_rates_change_neither_the_snapshot_nor_its_reexplanation(self):
		self._tables_change()
		now = json.loads(frappe.db.get_value("Reservation", self.res, "tex_pricing_snapshot"))
		self.assertEqual(now, self.sold)
		for basis in ("ORIGINAL_VERSION", "ORIGINAL_SALE_DATE"):
			p = modification.propose(self.res, {}, basis=basis)
			new = p["proposed"]
			self.assertEqual(new["totals"]["total"], self.sold["totals"]["total"], basis)
			self.assertEqual(p["difference"], "0.00", basis)
			self.assertEqual([_fixed(r) for r in new["fx_rates"]], self.sold["fx_rates"], basis)
			self.assertEqual({r.get("origin") for r in new["fx_rates"]}, {f"reservation:{self.res}"}, basis)
			self.assertEqual([s["params"]["rate"] for s in new["explanation"] if s["code"] == "FX"],
			                 [s["params"]["rate"] for s in self.sold["explanation"] if s["code"] == "FX"], basis)
		# today's terms convert at today's rates
		cur = modification.propose(self.res, {}, basis="CURRENT")["proposed"]
		self.assertEqual((_rates(cur)[("EUR", "TRY")]["sell_rate"], _rates(cur)[("USD", "TRY")]["sell_rate"]),
		                 ("56.100000", "45.000000"))
		self.assertNotEqual(cur["totals"]["total"], self.sold["totals"]["total"])

	def test_a_modification_on_the_original_sale_date_keeps_the_recorded_rates(self):
		self._tables_change()
		p = modification.propose(self.res, {"check_out": add_days(self.co, 1)}, basis="ORIGINAL_SALE_DATE")
		self.assertTrue(p["sellable"], p)
		self.assertEqual({k: r["sell_rate"] for k, r in _rates(p["proposed"]).items()},
		                 {("EUR", "TRY"): "51.000000", ("USD", "TRY"): "40.000000"})
		modification.apply(p["proposal_token"], reason="one more night")
		after = json.loads(frappe.db.get_value("Reservation", self.res, "tex_pricing_snapshot"))
		self.assertEqual(after["original_fx_rates"], self.sold["fx_rates"])
		self.assertEqual({k: r["sell_rate"] for k, r in _rates(after).items()},
		                 {("EUR", "TRY"): "51.000000", ("USD", "TRY"): "40.000000"})
		# a later change on today's terms, then one on the original sale date again: still the sale's rates
		cur = modification.propose(self.res, {"adults": 2}, basis="CURRENT")
		modification.apply(cur["proposal_token"], reason="repriced today")
		again = modification.propose(self.res, {"adults": 2}, basis="ORIGINAL_SALE_DATE")["proposed"]
		self.assertEqual({k: r["sell_rate"] for k, r in _rates(again).items()},
		                 {("EUR", "TRY"): "51.000000", ("USD", "TRY"): "40.000000"})

	def test_a_modification_on_a_historical_sale_date_reads_the_rates_of_then(self):
		# HISTORICAL_SALE_DATE is "as if sold then": the tables as of then, not the sale's record
		self._tables_change()
		p = modification.propose(self.res, {}, basis="HISTORICAL_SALE_DATE", basis_sale_at=str(self.sold_at))
		self.assertEqual(_rates(p["proposed"])[("EUR", "TRY")]["sell_rate"], "56.100000")   # the late import
		self.assertEqual(_rates(p["proposed"])[("USD", "TRY")]["sell_rate"], "40.000000")   # revised later
		self.assertNotIn("origin", _rates(p["proposed"])[("EUR", "TRY")])

	def test_a_snapshot_sold_before_g56_pins_its_line_rates(self):
		# a pre-G-56 snapshot recorded the room rate (``fx``) and each converted line's rate
		# (``extras[].fx_rate`` with the extra revision); the tables then say something else about
		# the sale time (the USD rate live then is corrected in place)
		legacy = {k: v for k, v in self.sold.items() if k != "fx_rates"}
		frappe.db.set_value("Reservation", self.res, "tex_pricing_snapshot", json.dumps(legacy),
		                    update_modified=False)
		frappe.db.set_value("TEX Reservation Revision", {"reservation": self.res, "change_type": "Original"},
		                    "snapshot_after", json.dumps(legacy))
		frappe.db.set_value("TEX FX Policy", self.usd_policy, "manual_rate", 45)
		_rate("TCMB", "EUR", "TRY", 55, getdate(self.sold_at), add_to_date(self.sold_at, minutes=-1))
		p = modification.propose(self.res, {}, basis="ORIGINAL_VERSION")
		self.assertEqual(p["proposed"]["totals"]["total"], self.sold["totals"]["total"])
		rates = _rates(p["proposed"])
		self.assertEqual((rates[("EUR", "TRY")]["sell_rate"], rates[("USD", "TRY")]["sell_rate"]),
		                 ("51.000000", "40.000000"))
		self.assertEqual(rates[("USD", "TRY")]["mode"], "RECORDED")


class TestOnePolicyPerPair(TexTestCase):
	"""O-11 (2D-2, ADR-069): one live or scheduled FX policy per scope (a hotel, or every hotel) and pair.
	A second one used to activate and be ignored: the older name won, silently."""

	def setUp(self):
		super().setUp()
		frappe.db.delete("TEX FX Policy", {"from_currency": "EUR", "to_currency": "TRY"})
		self.first = _live("TEX FX Policy", self.payload())

	def payload(self, **kw) -> dict:
		return {"property": fx.PROPERTY, "from_currency": "EUR", "to_currency": "TRY", "mode": "PROVIDER_PERCENT",
		        "provider": "TCMB", "rate_type": "FOREX_SELLING", "adjustment": 0, "max_age_days": 4, **kw}

	def draft(self, **kw) -> str:
		return frappe.get_doc({"doctype": "TEX FX Policy", **self.payload(**kw)}).insert(ignore_permissions=True).name

	def test_a_second_policy_for_the_pair_is_refused(self):
		second = self.draft(adjustment=3)
		with self.assertRaisesRegex(frappe.ValidationError, f"already has a live FX policy for EUR→TRY \\({self.first}\\)"):
			revisions.activate("TEX FX Policy", second, at="2020-01-01 00:00:00", backdate=True)
		self.assertEqual(frappe.db.get_value("TEX FX Policy", second, "tex_status"), "Draft")

	def test_a_scheduled_policy_counts_both_ways(self):
		with self.assertRaisesRegex(frappe.ValidationError, "already has a live FX policy"):
			revisions.activate("TEX FX Policy", self.draft(adjustment=3), at=add_to_date(now_datetime(), days=10))
		frappe.db.delete("TEX FX Policy", {"from_currency": "EUR", "to_currency": "TRY"})
		later = self.draft()
		revisions.activate("TEX FX Policy", later, at=add_to_date(now_datetime(), days=10))      # scheduled
		with self.assertRaisesRegex(frappe.ValidationError, "already has a live FX policy"):
			revisions.activate("TEX FX Policy", self.draft(adjustment=3), at="2020-01-01 00:00:00", backdate=True)

	def test_a_revision_of_the_live_policy_activates(self):
		draft = revisions.revise("TEX FX Policy", self.first)
		frappe.db.set_value("TEX FX Policy", draft, "adjustment", 2)
		revisions.activate("TEX FX Policy", draft)
		self.assertEqual(frappe.db.get_value("TEX FX Policy", draft, "tex_status"), "Active")

	def test_a_global_policy_lives_next_to_a_hotels_own_and_the_hotels_wins(self):
		glob = _live("TEX FX Policy", self.payload(property=None, adjustment=5))
		from kamra.tex.commercial import context

		self.assertEqual(context.fx_policy("EUR", "TRY", fx.PROPERTY, now_datetime()).policy_id, self.first)
		self.assertEqual(context.fx_policy("EUR", "TRY", "Another Hotel", now_datetime()).policy_id, glob)

	def test_two_live_rows_are_never_ranked_by_name(self):
		"""Forced in past the check (Desk, an import, an older site): the pair is unsellable."""
		from kamra.tex.commercial import context
		from kamra.tex.pricing.model import Unsellable

		second = self.draft(adjustment=3)
		frappe.db.set_value("TEX FX Policy", second, {"tex_status": "Active", "active_from": "2020-01-01 00:00:00"})
		with self.assertRaises(Unsellable) as cm:
			context.fx_snapshot("EUR", "TRY", fx.PROPERTY, now_datetime())
		self.assertEqual(cm.exception.code, "FX_POLICY_AMBIGUOUS")
		self.assertIn(self.first, str(cm.exception))


class TestManualBridge(TexTestCase):
	"""O-12 (2D-2, ADR-069, D-4): over a bank holiday the provider's last rate is stale and pricing
	stopped. A dated manual rate entered by a Revenue Manager or Finance user stands in for the provider's
	reference rate, with the policy's margin on it, per hotel, audited, and recorded in the snapshot."""

	def setUp(self):
		super().setUp()
		now = now_datetime()
		self.today = getdate(now)
		frappe.db.delete("TEX FX Rate", {"base_currency": "EUR", "quote_currency": "TRY"})
		frappe.db.delete("TEX FX Policy", {"from_currency": "EUR", "to_currency": "TRY"})
		fx.create_contract(self.f, code="FXB")
		self.policy = _live("TEX FX Policy", {"property": fx.PROPERTY, "from_currency": "EUR", "to_currency": "TRY",
		                                      "mode": "PROVIDER_PERCENT", "provider": "TCMB",
		                                      "rate_type": "FOREX_SELLING", "adjustment": 2, "max_age_days": 4})
		self.tcmb = _rate("TCMB", "EUR", "TRY", 50, add_days(self.today, -6), add_to_date(now, days=-6))
		self.yesterday = add_days(self.today, -1)
		self.rm = self.hotel_user("fxb-rm@example.com", fx.PROPERTY, "Revenue Manager")

	def hotel_user(self, email: str, property: str, profile: str) -> str:
		fx.ensure_user(email, ["Revenue Manager"])            # the Desk role; the TEX profile decides
		fx.ensure("TEX Access Grant", {"user": email, "property": property},
		          {"user": email, "scope_level": "Hotel", "property": property, "permission_profile": profile})
		scope.clear_cache()
		return email

	def as_user(self, user: str) -> None:
		frappe.set_user(user)  # nosemgrep: frappe-setuser -- the test acts as each user in turn
		scope.clear_cache()

	def enter(self, rate="50.5", property=fx.PROPERTY, day=None) -> str:
		from kamra.tex.api import policies

		return policies.add_manual_rate("EUR", "TRY", rate, str(day or self.yesterday), property=property,
		                                reason="bank holiday")["name"]

	def sell(self) -> dict:
		res = quoting.search(properties=[fx.PROPERTY], check_in=fx.d(6, 10), check_out=fx.d(6, 13),
		                     rooms=[{"adults": 2}], market="DE", channel="DIRECT_WEB", currency="TRY")
		offer = pick(res["properties"][0])
		q = quoting.create_quote(offer["rooms"][0]["offer_key"])
		self.assertTrue(q["ok"], q)
		b = booking.create_booking(quote_ids=[q["quote_id"]], guest={
			"first_name": "Deniz", "last_name": "Kaya", "email": "deniz.fxb@example.com"}, payment_method="Card",
			confirm_without_payment=True, idempotency_key="o12-fx")
		return json.loads(frappe.db.get_value("Reservation", b["rooms"][0]["reservation"], "tex_pricing_snapshot")) \
			| {"_reservation": b["rooms"][0]["reservation"]}

	def test_without_a_manual_rate_the_stale_provider_rate_stops_the_pair(self):
		from kamra.tex.commercial import context
		from kamra.tex.pricing.model import Unsellable

		with self.assertRaises(Unsellable) as cm:
			context.fx_snapshot("EUR", "TRY", fx.PROPERTY, now_datetime())
		self.assertEqual(cm.exception.code, "FX_RATE_STALE")

	def test_a_revenue_manager_bridges_the_hotel_and_the_stay_is_sold_on_the_manual_rate(self):
		self.as_user(self.rm)
		name = self.enter()
		event = frappe.get_all("TEX Audit Event", filters={"action": "fx.manual_rate", "reference_name": name},
		                       fields=["property", "reason", "new_value"])[0]
		self.assertEqual((event.property, event.reason), (fx.PROPERTY, "bank holiday"))
		self.as_user("Administrator")
		sold = self.sell()
		rate = _rates(sold)[("EUR", "TRY")]
		self.assertEqual((rate["sell_rate"], rate["mode"], rate["provider"], rate["provider_rate"],
		                  rate["provider_rate_id"], rate["rate_date"], rate["adjustment"], rate["policy_id"],
		                  rate["bridged_from"]),
		                 ("51.510000", "PROVIDER_PERCENT", "MANUAL", "50.500000", name, str(self.yesterday),
		                  "2.000000", self.policy, "TCMB"))
		fx_step = next(s for s in sold["explanation"] if s["code"] == "FX")
		self.assertEqual(fx_step["params"]["bridged_from"], "TCMB")
		self.assertIn("(bridging TCMB)", fx_step["text"])

	def test_the_sale_keeps_its_recorded_rate_when_a_correction_is_entered_later(self):
		self.enter()
		sold = self.sell()
		self.enter(rate="60")                              # the same date entered again: the latest entry wins
		p = modification.propose(sold["_reservation"], {}, basis="ORIGINAL_SALE_DATE")["proposed"]
		self.assertEqual([_fixed(r) for r in p["fx_rates"]], sold["fx_rates"])
		self.assertEqual(_rates(p)[("EUR", "TRY")]["sell_rate"], "51.510000")
		self.assertEqual(_rates(p)[("EUR", "TRY")]["origin"], f"reservation:{sold['_reservation']}")
		from kamra.tex.commercial import context

		today = context.fx_snapshot("EUR", "TRY", fx.PROPERTY, now_datetime())
		self.assertEqual(today.sell_rate, D("61.200000"))                   # 60 × 1.02: today is the correction

	def test_another_hotels_rate_does_not_bridge_this_hotel_and_its_user_cannot_enter_one_here(self):
		from kamra.tex.commercial import context
		from kamra.tex.pricing.model import Unsellable
		from kamra.tex.tests.integration.test_security_regressions import OTHER, other_hotel_with_mock

		other_hotel_with_mock()
		self.enter(property=OTHER)                                           # platform administrator
		with self.assertRaises(Unsellable) as cm:
			context.fx_snapshot("EUR", "TRY", fx.PROPERTY, now_datetime())
		self.assertEqual(cm.exception.code, "FX_RATE_STALE")
		theirs = self.hotel_user("fxb-other@example.com", OTHER, "Revenue Manager")
		self.as_user(theirs)
		with self.assertRaises(frappe.PermissionError):
			self.enter(property=fx.PROPERTY)
		with self.assertRaises(frappe.PermissionError):
			self.enter(property=None)                                       # every hotel: platform administrators
		self.as_user(self.rm)
		from kamra.tex.api import policies

		self.assertNotIn(OTHER, {r.property for r in policies.fx_rates("MANUAL")})   # a hotel never sees another's rates

	def test_a_platform_administrator_enters_a_rate_for_every_hotel(self):
		from kamra.tex.commercial import context

		self.enter(property=None)
		snap = context.fx_snapshot("EUR", "TRY", fx.PROPERTY, now_datetime())
		self.assertEqual((snap.sell_rate, snap.bridged_from), (D("51.510000"), "TCMB"))

	def test_a_rate_older_than_the_policys_age_or_a_viewer_does_not_bridge_or_enter(self):
		from kamra.tex.commercial import context
		from kamra.tex.pricing.model import Unsellable

		self.enter(day=add_days(self.today, -5))                             # older than max_age 4
		with self.assertRaises(Unsellable):
			context.fx_snapshot("EUR", "TRY", fx.PROPERTY, now_datetime())
		viewer = self.hotel_user("fxb-viewer@example.com", fx.PROPERTY, "Viewer")
		self.as_user(viewer)
		with self.assertRaises(frappe.PermissionError):
			self.enter()
