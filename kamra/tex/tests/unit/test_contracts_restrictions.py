"""Contract payloads/versions, market resolution, validation, restrictions, inventory."""

import ast
import pathlib
import subprocess
import sys
import unittest
from dataclasses import replace
from datetime import date, datetime
from decimal import Decimal

from kamra.tex.availability import inventory_math as inv
from kamra.tex.availability import restrictions as rs
from kamra.tex.pricing import engine, serialize, validate, versions
from kamra.tex.pricing.enums import OccTarget, Op
from kamra.tex.pricing.model import OccupancyRule, Period, RoomRule, Unsellable
from kamra.tex.tests.unit import fixtures as fx
from kamra.tex.tests.unit.test_engine import DE_MARKUP, EB, spec_request, spec_terms

D = Decimal


class TestPayload(unittest.TestCase):
	def test_roundtrip_is_lossless(self):
		t = replace(spec_terms(), payload_hash="x")
		payload = serialize.normalise_payload(serialize.terms_to_payload(t))
		back = serialize.terms_from_payload(payload, "x")
		self.assertEqual(back, t)

	def test_hash_is_canonical_and_detects_change(self):
		p = serialize.normalise_payload(serialize.terms_to_payload(fx.terms()))
		shuffled = dict(reversed(list(p.items())))
		self.assertEqual(serialize.payload_hash(p), serialize.payload_hash(shuffled))
		changed = serialize.normalise_payload(serialize.terms_to_payload(
			fx.terms(room_rules=tuple(replace(r, value=D("101")) if r.rule_id == "R-STD-P1" else r
			                          for r in fx.room_rules()))))
		self.assertNotEqual(serialize.payload_hash(p), serialize.payload_hash(changed))

	def test_decimal_canonical_form(self):
		self.assertEqual(serialize.dec_str(D("100.00")), "100")
		self.assertEqual(serialize.dec_str(D("1.150")), "1.15")
		self.assertEqual(serialize.dec_str(D("1E+2")), "100")

	def test_quote_from_payload_equals_quote_from_terms(self):
		t = spec_terms()
		payload = serialize.normalise_payload(serialize.terms_to_payload(t))
		t2 = serialize.terms_from_payload(payload, t.payload_hash)
		a = engine.price_stay(fx.ctx(t, markups=(DE_MARKUP,)), spec_request()).to_dict()
		b = engine.price_stay(fx.ctx(t2, markups=(DE_MARKUP,)), spec_request()).to_dict()
		self.assertEqual(a, b)

	def test_request_roundtrip(self):
		r = spec_request(promo_codes=("A",))
		self.assertEqual(serialize.request_from_dict(serialize.request_to_dict(r)), r)

	def test_unknown_schema_refused(self):
		from kamra.tex.pricing.model import PricingError

		with self.assertRaises(PricingError):
			serialize.terms_from_payload({"schema": "other"})


class TestVersions(unittest.TestCase):
	def setUp(self):
		H = versions.VersionHeader
		self.h = [
			H("V1", 1, "Superseded", datetime(2026, 10, 1), datetime(2027, 1, 10)),
			H("V2", 2, "Superseded", datetime(2027, 1, 10), datetime(2027, 2, 1)),
			H("V3", 3, "Published", datetime(2027, 2, 1), None),
			H("V4", 4, "Draft", None, None),
			H("V5", 5, "Published", datetime(2027, 6, 1), None),   # scheduled
		]

	def at(self, *a):
		v = versions.active_version(self.h, datetime(*a))
		return v.version_id if v else None

	def test_resolution_by_sale_time(self):
		self.assertIsNone(self.at(2026, 9, 1))
		self.assertEqual(self.at(2026, 12, 1), "V1")
		self.assertEqual(self.at(2027, 1, 10), "V2")
		self.assertEqual(self.at(2027, 1, 15), "V2")
		self.assertEqual(self.at(2027, 3, 1), "V3")
		self.assertEqual(self.at(2027, 6, 2), "V5")   # scheduled version takes over, drafts never sell

	def test_withdrawn_sold_until_withdrawn(self):
		h = [versions.VersionHeader("V1", 1, "Withdrawn", datetime(2027, 1, 1), datetime(2027, 2, 1))]
		self.assertEqual(versions.active_version(h, datetime(2027, 1, 15)).version_id, "V1")
		self.assertIsNone(versions.active_version(h, datetime(2027, 2, 2)))


class TestMarket(unittest.TestCase):
	M = (versions.MarketDef("DE", frozenset({"DE"})), versions.MarketDef("DACH", frozenset({"DE", "AT", "CH"})),
	     versions.MarketDef("EU", frozenset({"DE", "AT", "FR", "RO", "PL"})),
	     versions.MarketDef("RO", frozenset({"RO"})), versions.MarketDef("RO2", frozenset({"RO"})),
	     versions.MarketDef("GLOBAL", frozenset(), is_global=True), versions.MarketDef("OLD", frozenset({"FR"}),
	                                                                                    disabled=True))

	def r(self, **kw):
		return versions.resolve_market(markets=self.M, explicit=kw.get("explicit"), country=kw.get("country"),
		                               allowed=kw.get("allowed"), default=kw.get("default"))

	def test_explicit(self):
		self.assertEqual(self.r(explicit="dach"), ("DACH", "explicit"))
		with self.assertRaises(Unsellable):
			self.r(explicit="OLD")

	def test_country_most_specific(self):
		self.assertEqual(self.r(country="de"), ("DE", "country:DE"))
		self.assertEqual(self.r(country="AT"), ("DACH", "country:AT"))
		self.assertEqual(self.r(country="DE", allowed={"DACH", "EU", "GLOBAL"}), ("DACH", "country:DE"))

	def test_ambiguity_is_never_silent(self):
		with self.assertRaises(Unsellable) as cm:
			self.r(country="RO")
		self.assertEqual(cm.exception.code, "MARKET_AMBIGUOUS")
		with self.assertRaises(Unsellable) as cm:
			self.r(country="JP")
		self.assertEqual(cm.exception.code, "MARKET_REQUIRED")
		self.assertEqual(self.r(country="JP", default="GLOBAL"), ("GLOBAL", "default"))


class TestValidation(unittest.TestCase):
	def codes(self, t, level="ERROR"):
		return [i.code for i in validate.validate_terms(t) if i.level == level]

	def test_reference_contract_is_clean(self):
		self.assertEqual(validate.validate_terms(fx.terms()), [])

	def test_errors(self):
		t = fx.terms()
		self.assertIn("PERIOD_OVERLAP", self.codes(replace(t, periods=(*t.periods,
		                                                     Period("PX", "x", date(2027, 6, 10), date(2027, 6, 20))))))
		self.assertIn("NO_ROOM_PRICE", self.codes(replace(t, room_rules=t.room_rules[1:])))
		self.assertIn("ROOM_RULE_DUPLICATE", self.codes(replace(t, room_rules=(*t.room_rules,
		                                                          RoomRule("dup", "STD", "P1", Op.ABSOLUTE, D(1))))))
		self.assertIn("OCC_DUPLICATE", self.codes(replace(t, occupancy_rules=(
			*t.occupancy_rules, OccupancyRule("dup", OccTarget.CHILD, Op.PERCENT_OF, D(5), age_band="CHB")))))
		self.assertIn("OCC_UNKNOWN_BAND", self.codes(replace(t, occupancy_rules=(
			*t.occupancy_rules, OccupancyRule("x", OccTarget.CHILD, Op.PERCENT_OF, D(5), age_band="ZZ")))))
		self.assertIn("NO_BASE_BOARD", self.codes(replace(t, boards=t.boards[1:])))
		self.assertIn("OFFER_VALUE", self.codes(replace(t, offers=(replace(EB, value=D("150")),))))

	def test_sweep_warns_about_unpriceable_combinations(self):
		t = fx.terms(occupancy_rules=tuple(r for r in fx.occ_rules() if r.rule_id != "O-TEEN"))
		warnings = [i for i in validate.validate_terms(t) if i.level == "WARNING"]
		self.assertTrue(warnings)
		self.assertTrue(all(w.code == "NO_CHILD_RULE" and "TEEN" in w.message for w in warnings))


class TestRestrictions(unittest.TestCase):
	CI, CO = date(2027, 7, 10), date(2027, 7, 14)
	SALE = date(2027, 7, 1)
	SCOPE = rs.RestrictionScope("DLX", contract="C1", market="DE", channel="DIRECT_WEB")

	def check(self, cells, **kw):
		v, _ = rs.evaluate(cells, self.SCOPE, kw.get("ci", self.CI), kw.get("co", self.CO), kw.get("sale", self.SALE),
		                   min_los_basis=kw.get("basis", rs.ARRIVAL))
		return [x.code for x in v]

	def cell(self, cid, day, **kw):
		return rs.RestrictionCell(cid, day, **kw)

	def test_clean(self):
		self.assertEqual(self.check([]), [])

	def test_stop_sell_modes(self):
		self.assertEqual(self.check([self.cell("a", date(2027, 7, 12), stop_sell="STOP")]), ["STOP_SELL"])
		self.assertEqual(self.check([self.cell("a", self.CO, stop_sell="STOP")]), [])      # checkout day not a night
		self.assertEqual(self.check([self.cell("a", self.CI, stop_sell="STOP", stop_sell_mode=rs.ARRIVAL)]),
		                 ["STOP_SELL", "STOP_SELL_ARRIVAL"][1:])
		self.assertEqual(self.check([self.cell("a", date(2027, 7, 12), stop_sell="STOP",
		                                       stop_sell_mode=rs.ARRIVAL)]), [])
		self.assertEqual(self.check([self.cell("a", self.CO, stop_sell="STOP", stop_sell_mode=rs.DEPARTURE)]),
		                 ["STOP_SELL_DEPARTURE"])

	def test_open_sale_beats_broader_stop(self):
		cells = [self.cell("hotel", date(2027, 7, 11), stop_sell="STOP"),
		         self.cell("room", date(2027, 7, 11), room_type="DLX", stop_sell="OPEN")]
		self.assertEqual(self.check(cells), [])
		cells.append(self.cell("contract", date(2027, 7, 11), contract="C1", stop_sell="STOP"))
		self.assertEqual(self.check(cells), ["STOP_SELL"])

	def test_scope_mismatch_ignored(self):
		cells = [self.cell("uk", date(2027, 7, 11), market="UK", stop_sell="STOP"),
		         self.cell("cc", date(2027, 7, 11), channel="CALL_CENTER", stop_sell="STOP"),
		         self.cell("std", date(2027, 7, 11), room_type="STD", stop_sell="STOP")]
		self.assertEqual(self.check(cells), [])

	def test_los_cta_ctd(self):
		self.assertEqual(self.check([self.cell("a", self.CI, min_los=5)]), ["MIN_LOS"])
		self.assertEqual(self.check([self.cell("a", self.CI, min_los=4)]), [])
		self.assertEqual(self.check([self.cell("a", self.CI, max_los=3)]), ["MAX_LOS"])
		self.assertEqual(self.check([self.cell("a", self.CI, cta=True)]), ["CTA"])
		self.assertEqual(self.check([self.cell("a", self.CO, ctd=True)]), ["CTD"])
		self.assertEqual(self.check([self.cell("a", date(2027, 7, 11), cta=True)]), [])
		stay_through = [self.cell("a", date(2027, 7, 12), min_los=7)]
		self.assertEqual(self.check(stay_through), [])
		self.assertEqual(self.check(stay_through, basis=rs.STAY_THROUGH), ["MIN_LOS"])

	def test_release_and_booking_window(self):
		self.assertEqual(self.check([self.cell("a", self.CI, release_days=14)]), ["RELEASE"])
		self.assertEqual(self.check([self.cell("a", self.CI, release_days=7)]), [])
		self.assertEqual(self.check([self.cell("a", self.CI, min_advance=10)]), ["MIN_ADVANCE"])
		self.assertEqual(self.check([self.cell("a", self.CI, max_advance=5)]), ["MAX_ADVANCE"])

	def test_most_specific_min_los_wins(self):
		cells = [self.cell("hotel", self.CI, min_los=7), self.cell("mkt", self.CI, market="DE", min_los=3)]
		_, eff = rs.evaluate(cells, self.SCOPE, self.CI, self.CO, self.SALE)
		self.assertEqual(eff[self.CI].min_los, 3)
		self.assertEqual(eff[self.CI].sources["min_los"], "mkt")


class TestInventoryMath(unittest.TestCase):
	DAY = date(2027, 7, 10)

	def pool(self, **kw):
		base = dict(day=self.DAY, base_inventory=10)
		base.update(kw)
		return inv.PoolDay(**base)

	def test_capacity(self):
		self.assertEqual(inv.capacity(self.pool(manual_adjustment=-2, oversell_limit=1)), 9)
		self.assertEqual(inv.capacity(self.pool(closed=True)), 0)

	def test_free_pool_and_sold_out(self):
		d = inv.day_availability(self.pool(sold=10), [], None, date(2027, 7, 1))
		self.assertEqual((d.available, d.reason), (0, "sold out"))
		self.assertEqual(inv.day_availability(self.pool(sold=7), [], None, date(2027, 7, 1)).available, 3)

	def test_guaranteed_allotment_withheld_until_release(self):
		tui = inv.Allotment("A1", "TUI", self.DAY, rooms=4, release_days=7, guaranteed=True)
		p = self.pool(sold=3, sold_by_contract=(("TUI", 1),))
		early = inv.day_availability(p, [tui], "DIRECT", date(2027, 6, 1))
		self.assertEqual(early.withheld, 3)
		self.assertEqual(early.available, 4)                 # 10 − 3 sold − 3 withheld
		late = inv.day_availability(p, [tui], "DIRECT", date(2027, 7, 5))
		self.assertEqual(late.available, 7)                  # released
		own = inv.day_availability(p, [tui], "TUI", date(2027, 6, 1))
		self.assertEqual(own.allotment_remaining, 3)
		self.assertEqual(own.available, 3)

	def test_stay_minimum(self):
		days = [self.pool(sold=2), inv.PoolDay(date(2027, 7, 11), 10, sold=9)]
		self.assertEqual(inv.stay_availability(days, [], None, date(2027, 7, 1))[0], 1)


class TestPurity(unittest.TestCase):
	"""ADR-002: the pricing and availability cores must never import frappe."""

	def test_no_frappe_imports_in_source(self):
		root = pathlib.Path(__file__).resolve().parents[2]
		for pkg in ("pricing", "availability"):
			for f in (root / pkg).glob("*.py"):
				if f.name in ("repository.py", "loader.py"):
					continue
				tree = ast.parse(f.read_text())
				for node in ast.walk(tree):
					names = []
					if isinstance(node, ast.Import):
						names = [a.name for a in node.names]
					elif isinstance(node, ast.ImportFrom):
						names = [node.module or ""]
					self.assertFalse(any(n == "frappe" or n.startswith("frappe.") for n in names),
					                 f"{f.name} imports frappe")
		tree = ast.parse((root / "money.py").read_text())
		mods = [a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names]
		mods += [n.module or "" for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)]
		self.assertFalse(any(m.startswith("frappe") for m in mods))

	def test_modules_import_without_frappe_installed(self):
		code = ("import sys; sys.modules['frappe'] = None\n"
		        "import kamra.tex.pricing.engine, kamra.tex.pricing.validate, kamra.tex.pricing.versions\n"
		        "import kamra.tex.availability.restrictions, kamra.tex.availability.inventory_math\n"
		        "print('ok')")
		root = pathlib.Path(__file__).resolve().parents[4]
		out = subprocess.run([sys.executable, "-c", code], cwd=root, capture_output=True, text=True)
		self.assertEqual(out.stdout.strip(), "ok", out.stderr)
