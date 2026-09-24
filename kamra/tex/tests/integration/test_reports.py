"""Commercial reports (G-46, R-14, R-48, ADR-059).

- Contract vs selling: the margin is measured on the accommodation selling price the
  contract cost was marked up to (never on gross revenue), and every row reconciles:
  cost + margin = accommodation; accommodation + extras + taxes on top + stays without a
  contract cost = revenue; the totals are the sums of the rows, per currency.
- Filters: hotel / group / enterprise scope, market, channel, room, rate, currency, and a
  stay window together with a sale window.
- Views: production and contract vs selling by hotel and group, promotion, extras,
  cancellation, payment and conversion.
- Tenancy: only the hotels the viewer may report on; cost and margin only with
  ``price.view_cost`` at every hotel of the report, enforced on the server.
- Performance: aggregated in SQL, a fixed number of queries whatever the number of stays.
"""

import json
from contextlib import contextmanager
from unittest.mock import patch

import frappe
from frappe.utils import add_days, add_to_date, getdate, now_datetime, nowdate

from kamra.tex.api import policies as policy_api
from kamra.tex.api import public
from kamra.tex.api import reports as rep_api
from kamra.tex.money import D
from kamra.tex.reports import service as rep
from kamra.tex.security import scope
from kamra.tex.services import booking
from kamra.tex.tests.integration import fixtures as fx
from kamra.tex.tests.integration.test_commercial_flows import GUEST, SLUG, setup_site_and_payments
from kamra.tex.tests.integration.test_critical_journey import TexTestCase
from kamra.tex.tests.integration.test_crm_segments import OTHER, agent, other_tenant

SIBLING = "TEX Test Resort B"          # a second hotel of the test hotel's group
COST_KEYS = {"cost", "margin", "margin_pct", "accommodation", "extras", "taxes", "not_from_contract"}
MONEY = ("revenue", "accommodation", "extras", "taxes", "not_from_contract", "cost", "margin")


def sell(session: str, *, room: str = "STD", rate: str = "FLEX", check_in=None, check_out=None, extras: bool = True,
         code: str | None = None, guest: dict | None = None) -> dict:
	"""search → quote → book through the booking engine, as an anonymous visitor (Card)."""
	frappe.set_user("Guest")  # nosemgrep: frappe-setuser -- anonymous booking-engine visitor
	res = public.search(site=SLUG, check_in=str(check_in or fx.d(6, 10)), check_out=str(check_out or fx.d(6, 13)),
	                    rooms=[{"adults": 2, "children": [8]}], market="DE", session_id=session)
	rt = frappe.db.get_value("Room Type", {"property": fx.PROPERTY, "room_type_code": room})
	rp = frappe.db.get_value("Rate Plan", {"property": fx.PROPERTY, "code": rate})
	offer = next(o for o in res["properties"][0]["offers"]
	             if o["room_type"] == rt and o["board"] == "AI" and o["rate_plan"] == rp)
	q = public.quote(site=SLUG, offer_key=offer["rooms"][0]["offer_key"],
	                 extras=[{"code": "TRF", "quantity": 1}] if extras else [], promo_code=code, session_id=session)
	assert q["ok"], q
	b = public.book(site=SLUG, quote_ids=[q["quote_id"]], guest=guest or {**GUEST, "email": f"{session}@example.com"},
	                payment_method="Card", session_id=session, idempotency_key=f"idem-{session}")
	frappe.set_user("Administrator")  # nosemgrep: frappe-setuser -- back to the test's staff context
	b["reservation"] = b["rooms"][0]["reservation"]
	return b


def pay(b: dict) -> None:
	p = b["payment"]
	frappe.set_user("Guest")  # nosemgrep: frappe-setuser -- the sandbox gateway's page
	public.mock_pay(transaction=p["transaction"], outcome="success", sig=p["fields"]["success_sig"])
	frappe.set_user("Administrator")  # nosemgrep: frappe-setuser -- back


def snapshot(reservation: str) -> dict:
	return json.loads(frappe.db.get_value("Reservation", reservation, "tex_pricing_snapshot"))


def with_vat(rate=10) -> None:
	"""VAT on accommodation at the test hotel from now on (a new revision of its live tax
	policy; rolled back with the test). The test contract's prices exclude tax, so VAT is
	added on top of the accommodation price."""
	from kamra.tex.commercial import revisions

	rule = {"code": "VAT", "tax_name": "VAT", "kind": "PERCENT", "rate": rate, "applies_to": "ACCOMMODATION"}
	live = frappe.db.get_value("TEX Tax Policy", {"property": fx.PROPERTY, "tex_status": "Active"})
	if live:
		draft = frappe.get_doc("TEX Tax Policy", revisions.revise("TEX Tax Policy", live))
		draft.set("rules", [rule])
		draft.save(ignore_permissions=True)
		revisions.activate("TEX Tax Policy", draft.name)
	else:
		doc = frappe.get_doc({"doctype": "TEX Tax Policy", "policy_name": "G-46 taxes", "property": fx.PROPERTY,
		                      "rules": [rule]}).insert(ignore_permissions=True)
		revisions.activate("TEX Tax Policy", doc.name, at="2020-01-01 00:00:00", backdate=True)


def promo_code(code: str, percent=10) -> str:
	doc = policy_api.save_record("TEX Promotion", {
		"promotion_name": f"Code {code}", "property": fx.PROPERTY, "trigger": "Code", "code": code,
		"value_type": "PERCENT", "value": percent, "applies_to": "ACCOMMODATION"})
	policy_api.activate("TEX Promotion", doc["name"], at=str(add_to_date(now_datetime(), minutes=-1)))
	return doc["name"]


def sibling_hotel() -> str:
	"""A second hotel in the test hotel's group (rolled back with the test)."""
	if not frappe.db.exists("Property", SIBLING):
		frappe.get_doc({"doctype": "Property", "property_name": SIBLING, "city": "Antalya", "country": "Turkey",
		                "currency": "EUR"}).insert(ignore_permissions=True)
	grp = frappe.db.get_value("Property", fx.PROPERTY, "tex_hotel_group")
	ent = frappe.db.get_value("Property", fx.PROPERTY, "tex_enterprise")
	frappe.db.set_value("Property", SIBLING, {"tex_hotel_group": grp, "tex_enterprise": ent})
	return SIBLING


@contextmanager
def queries():
	"""Counts ``frappe.db.sql`` calls (every Frappe read and write goes through it)."""
	real = frappe.db.sql
	seen = []

	def spy(*args, **kwargs):
		seen.append(args[0] if args else kwargs.get("query"))
		return real(*args, **kwargs)

	with patch.object(frappe.db, "sql", side_effect=spy):
		yield seen


def row_of(report: dict, key: str, currency: str = "EUR") -> dict:
	rows = [r for r in report["rows"] if r["key"] == key and r["currency"] == currency]
	assert len(rows) == 1, (key, currency, report["rows"])
	return rows[0]


class ReportCase(TexTestCase):
	def setUp(self):
		super().setUp()
		setup_site_and_payments(self.f)
		self.rm = agent("g46-rm@example.com", fx.PROPERTY, "Revenue Manager")
		frappe.set_user("Administrator")  # nosemgrep: frappe-setuser -- fixtures

	def report(self, view: str, user: str | None = None, **kw) -> dict:
		frappe.set_user(user or self.rm)  # nosemgrep: frappe-setuser -- the viewer decides hotels and cost
		scope.clear_cache()
		try:
			return rep_api.report(view=view, **kw)
		finally:
			frappe.set_user("Administrator")  # nosemgrep: frappe-setuser -- back
			scope.clear_cache()

	def june(self, **kw) -> dict:
		return {"property": fx.PROPERTY, "stay_from": str(fx.d(6, 1)), "stay_to": str(fx.d(6, 30)), **kw}

	def assertReconciles(self, report: dict):
		"""Every row and total adds up to the cent, per currency."""
		for row in [*report["rows"], *[{**t, "currency": c} for c, t in report["totals"].items()]]:
			m = {k: D(row[k]) for k in MONEY}
			self.assertEqual(m["cost"] + m["margin"], m["accommodation"], row)
			self.assertEqual(m["accommodation"] + m["extras"] + m["taxes"] + m["not_from_contract"], m["revenue"], row)
			if m["accommodation"]:
				self.assertEqual(D(row["margin_pct"]), (m["margin"] / m["accommodation"] * 100).quantize(D("0.01")), row)
		for ccy, total in report["totals"].items():
			rows = [r for r in report["rows"] if r["currency"] == ccy]
			for k in MONEY:
				self.assertEqual(sum((D(r[k]) for r in rows), D(0)), D(total[k]), (ccy, k))
			self.assertEqual(sum(r["room_nights"] for r in rows), total["room_nights"])
			self.assertEqual(sum(r["bookings"] for r in rows), total["bookings"])


class TestContractVsSelling(ReportCase):
	def test_margin_is_over_the_accommodation_selling_price_and_reconciles(self):
		"""The defect: revenue (842.50 + VAT) was set against a margin that only covers the
		accommodation, and margin % was divided by gross revenue."""
		with_vat(10)
		b = sell("g46-margin")
		snap = snapshot(b["reservation"])["totals"]
		accom, cost = D(snap["accommodation"]), D(snap["cost"])
		self.assertEqual((accom, cost, D(snap["tax_added"])), (D("802.50"), D("750.00"), D("80.25")))
		out = rep.production(fx.PROPERTY, fx.d(6, 1), fx.d(6, 30), group_by="channel", basis="stay")
		row = out["rows"][0]
		self.assertEqual((row["revenue"], row["cost"], row["margin"]), ("922.75", "750.00", "52.50"))
		# margin % of the accommodation selling price (52.50 / 802.50), not of gross revenue (52.50 / 922.75)
		self.assertEqual(row["margin_pct"], "6.54")
		# the selling price the margin is measured on, next to what else the guest paid
		self.assertEqual({k: row.get(k) for k in ("accommodation", "extras", "taxes", "not_from_contract")},
		                 {"accommodation": "802.50", "extras": "40.00", "taxes": "80.25", "not_from_contract": "0.00"})
		self.assertReconciles(out)
		self.assertEqual(out["totals"]["EUR"]["margin_pct"], "6.54")

	def test_rows_and_totals_reconcile_when_prorated_and_with_stays_without_contract_cost(self):
		with_vat(10)
		sell("g46-rec-web")
		cc = sell("g46-rec-cc", room="DLX", check_in=fx.d(6, 12), check_out=fx.d(6, 16))
		imp = sell("g46-rec-imp", check_in=fx.d(6, 20), check_out=fx.d(6, 22))
		frappe.db.set_value("Reservation", cc["reservation"], "tex_sales_channel", "CALL_CENTER")
		# a stay TEX did not price (imported): it has no contract cost, so it is kept out of the margin
		frappe.db.set_value("Reservation", imp["reservation"], {"tex_pricing_source": "Imported",
		                                                        "tex_cost_amount": 0, "tex_margin_amount": 0})
		# 11–20 June: 2 of the web stay's 3 nights, all 4 of the call-centre stay's, 1 of the imported stay's 2
		out = self.report("margin", **self.june(stay_from=str(fx.d(6, 11)), stay_to=str(fx.d(6, 20))))
		self.assertTrue(out["cost_visible"])
		self.assertReconciles(out)
		web_row = row_of(out, "DIRECT_WEB")
		imp_total = D(frappe.db.get_value("Reservation", imp["reservation"], "tex_total_amount"))
		self.assertEqual(D(web_row["not_from_contract"]), (imp_total / 2).quantize(D("0.01")))
		self.assertEqual(row_of(out, "CALL_CENTER")["room_nights"], 4)
		self.assertEqual(web_row["room_nights"], 2 + 1)

	def test_multi_currency_is_never_added(self):
		b1, b2 = sell("g46-eur"), sell("g46-gbp")
		frappe.db.set_value("Reservation", b2["reservation"], "tex_currency", "GBP")
		frappe.db.set_value("TEX Booking", b2["booking"], "currency", "GBP")
		out = self.report("margin", **self.june())
		self.assertEqual(set(out["totals"]), {"EUR", "GBP"})
		one = D(frappe.db.get_value("Reservation", b1["reservation"], "tex_total_amount"))
		self.assertEqual((D(out["totals"]["EUR"]["revenue"]), D(out["totals"]["GBP"]["revenue"])), (one, one))
		self.assertReconciles(out)
		self.assertEqual(set(self.report("production", **self.june(currency="GBP"))["totals"]), {"GBP"})


class TestFilters(ReportCase):
	def test_market_channel_room_and_rate_filters(self):
		std = sell("g46-f-std")
		dlx = sell("g46-f-dlx", room="DLX")
		nrf = sell("g46-f-nrf", rate="NRF")
		frappe.db.set_value("Reservation", dlx["reservation"], "tex_sales_channel", "CALL_CENTER")
		frappe.db.set_value("Reservation", nrf["reservation"], "tex_market", "UK")

		def stays(**kw):
			return self.report("production", **self.june(**kw))["totals"].get("EUR", {}).get("bookings", 0)

		dlx_rt = frappe.db.get_value("Room Type", {"property": fx.PROPERTY, "room_type_code": "DLX"})
		nrf_rp = frappe.db.get_value("Rate Plan", {"property": fx.PROPERTY, "code": "NRF"})
		self.assertEqual(stays(), 3)
		self.assertEqual(stays(market="DE"), 2)
		self.assertEqual(stays(market="UK"), 1)
		self.assertEqual(stays(channel="CALL_CENTER"), 1)
		self.assertEqual(stays(channel=json.dumps(["CALL_CENTER", "DIRECT_WEB"])), 3)
		self.assertEqual(stays(room_type=dlx_rt), 1)
		self.assertEqual(stays(rate_plan=nrf_rp), 1)
		self.assertEqual(stays(rate_plan=nrf_rp, market="DE"), 0)
		self.assertEqual(stays(currency="GBP"), 0)
		# a value is a value: never SQL
		self.assertEqual(stays(market="DE' OR '1'='1"), 0)
		self.assertTrue(std)

	def test_sale_window_and_stay_window_together(self):
		early, late = sell("g46-sale-early"), sell("g46-sale-late", check_in=fx.d(7, 10), check_out=fx.d(7, 13))
		sold_then = add_days(nowdate(), -60)
		frappe.db.set_value("Reservation", early["reservation"], "tex_sale_at", f"{sold_then} 10:00:00")
		today = nowdate()
		both = self.report("production", property=fx.PROPERTY, stay_from=str(fx.d(6, 1)), stay_to=str(fx.d(7, 31)),
		                   sale_from=str(add_days(today, -7)), sale_to=str(today))
		self.assertEqual(both["totals"]["EUR"]["bookings"], 1)                    # sold this week, stays in July
		self.assertEqual((both["stay"], both["sale"]), ({"from": str(fx.d(6, 1)), "to": str(fx.d(7, 31))},
		                                                {"from": str(add_days(today, -7)), "to": str(today)}))
		sold_early = self.report("production", property=fx.PROPERTY, group_by="month", basis="booking",
		                         sale_from=str(add_days(sold_then, -1)), sale_to=str(add_days(sold_then, 1)))
		self.assertEqual([r["key"] for r in sold_early["rows"]], [str(sold_then)[:7]])
		self.assertTrue(late)

	def test_stay_date_rows_are_the_nights_of_that_day_or_month(self):
		b = sell("g46-months", check_in=fx.d(6, 29), check_out=fx.d(7, 2))
		total = D(frappe.db.get_value("Reservation", b["reservation"], "tex_total_amount"))
		out = self.report("production", property=fx.PROPERTY, stay_from=str(fx.d(6, 1)), stay_to=str(fx.d(7, 31)),
		                  group_by="month")
		june, july = row_of(out, f"{fx.YEAR}-06"), row_of(out, f"{fx.YEAR}-07")
		self.assertEqual((june["room_nights"], july["room_nights"]), (2, 1))
		self.assertEqual(D(june["revenue"]) + D(july["revenue"]), total)
		self.assertEqual((june["bookings"], july["bookings"]), (1, 0))          # a stay counts once, where it starts


class TestViews(ReportCase):
	def test_hotel_and_group_views_over_a_group(self):
		sibling = sibling_hotel()
		here, there = sell("g46-grp-here"), sell("g46-grp-there")
		frappe.db.set_value("Reservation", there["reservation"], "property", sibling)
		grp = frappe.db.get_value("Property", fx.PROPERTY, "tex_hotel_group")
		boss = fx.ensure_user("g46-group@example.com", ["Call Center Agent"])
		fx.ensure("TEX Access Grant", {"user": boss, "hotel_group": grp},
		          {"user": boss, "scope_level": "Hotel Group", "hotel_group": grp, "permission_profile": "Revenue Manager"})
		kw = {"level": "Group", "name": grp, "stay_from": str(fx.d(6, 1)), "stay_to": str(fx.d(6, 30))}
		by_hotel = self.report("margin", boss, group_by="hotel", **kw)
		self.assertEqual({r["key"] for r in by_hotel["rows"]}, {fx.PROPERTY, sibling})
		self.assertEqual(sorted(by_hotel["scope"]["hotels"]), sorted([fx.PROPERTY, sibling]))
		self.assertReconciles(by_hotel)
		by_group = self.report("production", boss, group_by="group", **kw)
		self.assertEqual([(r["key"], r["bookings"]) for r in by_group["rows"]], [(grp, 2)])
		self.assertEqual(by_group["labels"][grp], frappe.db.get_value("TEX Hotel Group", grp, "group_name"))
		self.assertTrue(here)

	def test_promotion_view(self):
		promo = promo_code("G46TEN", 10)
		sell("g46-promo", code="G46TEN")
		sell("g46-nopromo")
		out = self.report("promotion", **self.june())
		self.assertEqual(len(out["rows"]), 1)
		row = out["rows"][0]
		self.assertEqual((row["key"], row["currency"], row["applications"], row["room_nights"]), (promo, "EUR", 1, 3))
		self.assertEqual(row["discount"], "80.25")                                # 10 % of 802.50
		self.assertEqual(out["totals"]["EUR"], {"applications": 1, "discount": "80.25"})

	def test_extras_view(self):
		sell("g46-x1")
		sell("g46-x2")
		sell("g46-x3", extras=False)
		out = self.report("extras", **self.june())
		row = row_of(out, "TRF")
		self.assertEqual((row["stays"], D(row["quantity"]), row["amount"]), (2, D(2), "80.00"))
		self.assertEqual(out["totals"]["EUR"], {"amount": "80.00"})

	def test_cancellation_view(self):
		kept, free, fee = sell("g46-c-kept"), sell("g46-c-free"), sell("g46-c-fee", rate="NRF")
		booking.cancel_reservation(free["reservation"], reason="plans changed")
		booking.cancel_reservation(fee["reservation"], reason="plans changed")
		values = {k: D(frappe.db.get_value("Reservation", b["reservation"], "tex_total_amount"))
		          for k, b in (("free", free), ("fee", fee))}
		retained = D(frappe.db.get_value("Reservation", fee["reservation"], "cancellation_fee"))
		self.assertGreater(retained, 0)                                            # non-refundable
		out = self.report("cancellation", **self.june())
		t = out["totals"]["EUR"]
		self.assertEqual((t["stays"], t["cancelled"], t["no_shows"], t["cancelled_nights"]), (3, 2, 0, 6))
		self.assertEqual((D(t["cancelled_value"]), D(t["fees"])), (values["free"] + values["fee"], retained))
		self.assertEqual(t["cancelled_pct"], "66.67")
		self.assertEqual(sum(r["cancelled"] for r in out["rows"]), 2)
		self.assertTrue(kept)

	def test_payment_view(self):
		paid, unpaid = sell("g46-p-paid"), sell("g46-p-open")
		pay(paid)
		out = self.report("payment", **self.june(group_by="payment_status"))
		t = out["totals"]["EUR"]
		value = sum((D(frappe.db.get_value("TEX Booking", b["booking"], "total_amount")) for b in (paid, unpaid)), D(0))
		charged = D(frappe.db.get_value("TEX Booking", paid["booking"], "paid_amount"))
		self.assertTrue(charged > 0)
		self.assertEqual((t["bookings"], D(t["value"]), D(t["paid"]), D(t["charged"])), (2, value, charged, charged))
		self.assertEqual(D(t["paid"]) + D(t["balance"]), D(t["value"]))
		for r in out["rows"]:
			self.assertEqual(D(r["paid"]) + D(r["balance"]), D(r["value"]), r)
		method = out["methods"][0]
		self.assertEqual((method["method"], method["currency"], D(method["charged"]), D(method["net"])),
		                 ("Card", "EUR", charged, charged))
		self.assertTrue(unpaid)

	def test_conversion_view(self):
		today = nowdate()
		kw = {"property": fx.PROPERTY, "sale_from": today, "sale_to": today, "group_by": "site"}
		before = self.report("conversion", **kw)["totals"]
		b = sell("g46-conv-1")
		pay(b)
		sell("g46-conv-2")
		frappe.set_user("Guest")  # nosemgrep: frappe-setuser -- a visitor who only searched
		public.search(site=SLUG, check_in=str(fx.d(6, 10)), check_out=str(fx.d(6, 13)), rooms=[{"adults": 2}],
		              market="DE", session_id="g46-conv-3")
		frappe.set_user("Administrator")  # nosemgrep: frappe-setuser -- back
		after = self.report("conversion", **kw)
		delta = {k: after["totals"][k] - before.get(k, 0) for k in ("searched", "quoted", "booked", "confirmed")}
		self.assertEqual(delta, {"searched": 3, "quoted": 2, "booked": 2, "confirmed": 1})
		self.assertEqual(sum(r["searched"] for r in after["rows"]), after["totals"]["searched"])
		with self.assertRaises(frappe.ValidationError):                         # sessions happen on sale dates
			self.report("conversion", **self.june())


class TestTenancyAndCost(ReportCase):
	def test_another_hotels_grant_sees_nothing_of_this_hotel(self):
		sell("g46-t-here")
		other_tenant()
		there = agent("g46-there@example.com", OTHER, "Revenue Manager")
		frappe.set_user("Administrator")  # nosemgrep: frappe-setuser -- fixtures
		ent = frappe.db.get_value("Property", fx.PROPERTY, "tex_enterprise")
		grp = frappe.db.get_value("Property", fx.PROPERTY, "tex_hotel_group")
		for view in rep.VIEWS:
			dates = {"sale_from": nowdate(), "sale_to": nowdate()}
			if view != "conversion":                   # shopping sessions have no stay dates
				dates.update(stay_from=str(fx.d(6, 1)), stay_to=str(fx.d(6, 30)))
			for kw in ({"property": fx.PROPERTY}, {"level": "Hotel", "name": fx.PROPERTY},
			           {"level": "Group", "name": grp}, {"level": "Enterprise", "name": ent}):
				with self.assertRaises(frappe.PermissionError, msg=(view, kw)):
					self.report(view, there, **dates, **kw)
			mine = self.report(view, there, level="All", **dates)
			self.assertEqual(mine["scope"]["hotels"], [OTHER])
			self.assertEqual((mine["rows"], mine["totals"] if view != "conversion" else {}), ([], {}), view)

	def test_a_group_filter_never_widens_the_scope(self):
		sibling = sibling_hotel()
		sell("g46-w-here")
		there = sell("g46-w-there")
		frappe.db.set_value("Reservation", there["reservation"], "property", sibling)
		grp = frappe.db.get_value("Property", fx.PROPERTY, "tex_hotel_group")
		for view in ("production", "margin", "cancellation", "payment"):
			out = self.report(view, level="Group", name=grp, stay_from=str(fx.d(6, 1)), stay_to=str(fx.d(6, 30)),
			                  group_by="hotel")
			self.assertEqual(out["scope"]["hotels"], [fx.PROPERTY], view)          # the group has two, I see one
			self.assertEqual({r["key"] for r in out["rows"]}, {fx.PROPERTY}, view)
		for kw in ({"level": "Hotel", "name": sibling}, {"property": sibling}):
			with self.assertRaises(frappe.PermissionError):
				self.report("production", stay_from=str(fx.d(6, 1)), stay_to=str(fx.d(6, 30)), **kw)

	def test_a_profile_without_cost_gets_selling_figures_only(self):
		sell("g46-v")
		viewer = agent("g46-viewer@example.com", fx.PROPERTY, "Viewer")
		for view in ("production", "promotion", "extras", "cancellation", "payment"):
			out = self.report(view, viewer, **self.june())
			self.assertFalse(out["cost_visible"], view)
			keys = set().union(*(set(r) for r in out["rows"]), *(set(t) for t in out["totals"].values()))
			self.assertFalse(keys & COST_KEYS, (view, keys & COST_KEYS))
		self.assertEqual(self.report("production", viewer, **self.june())["totals"]["EUR"]["revenue"],
		                 self.report("production", **self.june())["totals"]["EUR"]["revenue"])
		with self.assertRaises(frappe.PermissionError):
			self.report("margin", viewer, **self.june())
		# the compatibility endpoint too
		frappe.set_user(viewer)  # nosemgrep: frappe-setuser -- the viewer
		scope.clear_cache()
		old = rep_api.production(property=fx.PROPERTY, date_from=str(fx.d(6, 1)), date_to=str(fx.d(6, 30)))
		frappe.set_user("Administrator")  # nosemgrep: frappe-setuser -- back
		self.assertFalse(set().union(*(set(r) for r in old["rows"])) & COST_KEYS)

	def test_cost_needs_the_capability_at_every_hotel_of_the_report(self):
		sibling = sibling_hotel()
		there = sell("g46-mix")
		frappe.db.set_value("Reservation", there["reservation"], "property", sibling)
		fx.ensure("TEX Access Grant", {"user": self.rm, "property": sibling},
		          {"user": self.rm, "scope_level": "Hotel", "property": sibling, "permission_profile": "Viewer"})
		grp = frappe.db.get_value("Property", fx.PROPERTY, "tex_hotel_group")
		out = self.report("production", level="Group", name=grp, **{k: v for k, v in self.june().items()
		                                                              if k != "property"})
		self.assertFalse(out["cost_visible"])
		self.assertFalse(set().union(*(set(r) for r in out["rows"])) & COST_KEYS)
		self.assertTrue(self.report("production", **self.june())["cost_visible"])  # at its own hotel: yes

	def test_every_report_endpoint_declares_its_capability(self):
		fns = [fn for name, fn in vars(rep_api).items()
		       if callable(fn) and getattr(fn, "__module__", None) == rep_api.__name__ and fn in frappe.whitelisted]
		self.assertGreaterEqual(len(fns), 6)
		self.assertEqual([fn.__name__ for fn in fns if not getattr(fn, "_tex_capability", None)], [])


class TestPerformanceAndBounds(ReportCase):
	def count(self, call) -> int:
		call()                                         # warm the per-request caches (scope, meta)
		with queries() as seen:
			call()
		return len(seen)

	def test_country_grouping_is_not_n_plus_one(self):
		frappe.set_user("Administrator")  # nosemgrep: frappe-setuser -- revenue manager view
		sell("g46-n1-a", guest={**GUEST, "email": "n1a@example.com", "country": "Germany"})

		def run():
			return rep.production(fx.PROPERTY, fx.d(6, 1), fx.d(6, 30), group_by="country", basis="stay")

		one = self.count(run)
		sell("g46-n1-b", guest={**GUEST, "email": "n1b@example.com", "country": "Austria"})
		sell("g46-n1-c", guest={**GUEST, "email": "n1c@example.com", "country": "Poland"})
		frappe.set_user("Administrator")  # nosemgrep: frappe-setuser -- same viewer
		three = self.count(run)
		self.assertEqual(three, one, "one query per reservation")
		self.assertEqual({r["key"] for r in run()["rows"]}, {"Germany", "Austria", "Poland"})

	def test_every_view_runs_a_fixed_number_of_queries(self):
		b = sell("g46-q1", code=None)
		pay(b)
		today = nowdate()
		kw = {"property": fx.PROPERTY, "stay_from": str(fx.d(6, 1)), "stay_to": str(fx.d(6, 30))}

		def runs():
			for view in rep.VIEWS:
				args = {"property": fx.PROPERTY, "sale_from": today, "sale_to": today} if view == "conversion" else kw
				yield view, lambda v=view, a=args: self.report(v, **a)

		first = {v: self.count(call) for v, call in runs()}
		for s in ("g46-q2", "g46-q3"):
			pay(sell(s))
		self.assertEqual({v: self.count(call) for v, call in runs()}, first)

	def test_bounds(self):
		with self.assertRaisesRegex(frappe.ValidationError, "at most 800 days"):
			self.report("production", property=fx.PROPERTY, stay_from=str(fx.d(1, 1)),
			            stay_to=str(add_days(fx.d(1, 1), 801)))
		with self.assertRaises(frappe.ValidationError):                          # a period is required
			self.report("production", property=fx.PROPERTY)
		with self.assertRaises(frappe.ValidationError):
			self.report("production", **self.june(group_by="password"))
		with self.assertRaises(frappe.ValidationError):
			self.report("nonsense", **self.june())
		with self.assertRaises(frappe.ValidationError):
			self.report("production", **self.june(market=json.dumps([f"M{i}" for i in range(rep.MAX_VALUES + 1)])))
		with self.assertRaises(frappe.ValidationError):
			self.report("production", **self.june(currency="EURO"))
		with self.assertRaises(frappe.ValidationError):                          # not a booking dimension
			self.report("payment", **self.june(group_by="room_type"))

	def test_long_results_fold_into_one_row_and_still_reconcile(self):
		for i, day in enumerate((3, 6, 9, 12)):
			sell(f"g46-fold-{i}", check_in=fx.d(6, day), check_out=fx.d(6, day + 2))
		full = self.report("margin", **self.june(group_by="day"))
		with patch.object(rep, "MAX_ROWS", 3):
			folded = self.report("margin", **self.june(group_by="day"))
		self.assertEqual(len(folded["rows"]), 3)
		self.assertEqual(folded["truncated"], len(full["rows"]) - 2)
		self.assertEqual(folded["rows"][-1]["key"], rep.OTHER)
		self.assertEqual(folded["totals"], full["totals"])
		self.assertReconciles(folded)

	def test_the_old_production_endpoint_still_answers(self):
		sell("g46-compat")
		frappe.set_user(self.rm)  # nosemgrep: frappe-setuser -- the revenue manager
		scope.clear_cache()
		old = rep_api.production(property=fx.PROPERTY, date_from=str(fx.d(6, 11)), date_to=str(fx.d(6, 30)))
		frappe.set_user("Administrator")  # nosemgrep: frappe-setuser -- back
		self.assertEqual((old["totals"]["EUR"]["room_nights"], old["totals"]["EUR"]["revenue"]), (2, "561.67"))
		self.assertEqual((old["property"], old["from"], old["to"]), (fx.PROPERTY, str(fx.d(6, 11)), str(fx.d(6, 30))))
		self.assertTrue(getdate(old["to"]))
