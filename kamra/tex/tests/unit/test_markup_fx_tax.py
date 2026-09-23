"""Markup (R-14), currency engine (R-15) and tax resolver tests."""

import unittest
from datetime import date, datetime
from decimal import Decimal

from kamra.tex.pricing import engine, fx, markup, tax
from kamra.tex.pricing.enums import ExtraPricingMode, FxMode, Level, MarkupCombine, Op, TaxKind
from kamra.tex.pricing.explain import Explanation
from kamra.tex.pricing.model import ExtraDef, ExtraRequest, FxSnapshot, MarkupRule, TaxRule, Unsellable
from kamra.tex.tests.unit import fixtures

D = Decimal
NIGHT = date(2027, 7, 10)
SCOPE = markup.MarkupScope("HOTEL-A", "DE", "C1", "DLX", "CALL_CENTER", "EUR")


class TestMarkup(unittest.TestCase):
	def apply(self, rules, cost=None, scope=SCOPE, night=NIGHT):
		return markup.apply_markup(tuple(rules), scope, night, D("1000") if cost is None else cost)

	def test_types(self):
		self.assertEqual(self.apply([MarkupRule("m", Op.ADJUST_PERCENT, D("8"), property="HOTEL-A")]), D("1080"))
		self.assertEqual(self.apply([MarkupRule("m", Op.MULTIPLY, D("1.1"), property="HOTEL-A")]), D("1100.0"))
		self.assertEqual(self.apply([MarkupRule("m", Op.ADD, D("25"), property="HOTEL-A")]), D("1025"))

	def test_no_rule_means_contract_price(self):
		ex = Explanation()
		self.assertEqual(markup.apply_markup((), SCOPE, NIGHT, D("99"), explain=ex), D("99"))
		self.assertEqual(ex.steps[0].code, "NO_MARKUP")

	def test_most_specific_wins(self):
		rules = [
			MarkupRule("global", Op.ADJUST_PERCENT, D("5")),
			MarkupRule("hotel", Op.ADJUST_PERCENT, D("6"), property="HOTEL-A"),
			MarkupRule("market", Op.ADJUST_PERCENT, D("7"), property="HOTEL-A", market="DE"),
			MarkupRule("room", Op.ADJUST_PERCENT, D("9"), property="HOTEL-A", room_type="DLX"),
			MarkupRule("other-market", Op.ADJUST_PERCENT, D("50"), property="HOTEL-A", market="UK"),
		]
		self.assertEqual(self.apply(rules), D("1090"))
		winner, _, overridden = markup.resolve(tuple(rules), SCOPE, NIGHT)
		self.assertEqual(winner.rule_id, "room")
		self.assertEqual([r.rule_id for r in overridden], ["market", "hotel", "global"])

	def test_channel_and_period_specificity(self):
		rules = [
			MarkupRule("room", Op.ADJUST_PERCENT, D("9"), property="HOTEL-A", room_type="DLX"),
			MarkupRule("summer", Op.ADJUST_PERCENT, D("10"), property="HOTEL-A", stay_from=date(2027, 7, 1),
			           stay_to=date(2027, 7, 31)),
			MarkupRule("cc", Op.ADJUST_PERCENT, D("3"), property="HOTEL-A", channel="CALL_CENTER"),
		]
		self.assertEqual(self.apply(rules), D("1030"))                           # channel most specific
		self.assertEqual(self.apply(rules[:2]), D("1100"))                       # period beats room
		self.assertEqual(self.apply(rules[:2], night=date(2027, 8, 1)), D("1090"))

	def test_stack_is_explicit(self):
		rules = [
			MarkupRule("market", Op.ADJUST_PERCENT, D("7"), property="HOTEL-A", market="DE"),
			MarkupRule("cc-extra", Op.ADD, D("5"), property="HOTEL-A", channel="CALL_CENTER",
			           combine=MarkupCombine.STACK),
		]
		ex = Explanation()
		self.assertEqual(markup.apply_markup(tuple(rules), SCOPE, NIGHT, D("100"), explain=ex), D("112"))
		self.assertEqual([s.code for s in ex.steps], ["MARKUP", "MARKUP_STACK"])

	def test_add_in_other_currency_refused(self):
		with self.assertRaises(Unsellable):
			self.apply([MarkupRule("m", Op.ADD, D("5"), property="HOTEL-A", currency="TRY")])


def rate(pid, base, quote, r, d=date(2027, 1, 14), provider="TCMB"):
	return fx.ProviderRate(pid, provider, base, quote, D(r), d)


AS_OF = datetime(2027, 1, 15, 12, 0)
RATES = (rate("t1", "EUR", "TRY", "50"), rate("t2", "USD", "TRY", "40"), rate("t3", "GBP", "TRY", "60"),
         rate("t0", "EUR", "TRY", "45", date(2027, 1, 1)))


class TestFx(unittest.TestCase):
	def pol(self, mode, **kw):
		return fx.FxPolicy("pol", "EUR", "TRY", mode, provider=kw.pop("provider", "TCMB"), **kw)

	def test_identity(self):
		s = fx.resolve_fx("EUR", "EUR", None, (), AS_OF)
		self.assertEqual(s.sell_rate, D(1))
		self.assertEqual(s.mode, FxMode.IDENTITY)

	def test_provider_modes(self):
		self.assertEqual(fx.resolve_fx("EUR", "TRY", self.pol(FxMode.PROVIDER), RATES, AS_OF).sell_rate, D("50"))
		p = fx.resolve_fx("EUR", "TRY", self.pol(FxMode.PROVIDER_PERCENT, adjustment=D("2")), RATES, AS_OF)
		self.assertEqual(p.sell_rate, D("51.000000"))
		self.assertEqual(p.provider_rate, D("50.000000"))
		self.assertEqual(p.provider_rate_id, "t1")
		f = fx.resolve_fx("EUR", "TRY", self.pol(FxMode.PROVIDER_FIXED, adjustment=D("1.50")), RATES, AS_OF)
		self.assertEqual(f.sell_rate, D("51.500000"))

	def test_as_of_picks_rate_known_then(self):
		s = fx.resolve_fx("EUR", "TRY", self.pol(FxMode.PROVIDER), RATES, datetime(2027, 1, 5))
		self.assertEqual(s.sell_rate, D("45"))

	def test_manual(self):
		s = fx.resolve_fx("EUR", "TRY", fx.FxPolicy("m", "EUR", "TRY", FxMode.MANUAL, manual_rate=D("49.5")),
		                  (), AS_OF)
		self.assertEqual(s.sell_rate, D("49.500000"))

	def test_inverse_and_cross(self):
		inv = fx.resolve_fx("TRY", "EUR", fx.FxPolicy("p", "TRY", "EUR", FxMode.PROVIDER, provider="TCMB"),
		                    RATES, AS_OF)
		self.assertEqual(inv.sell_rate, D("0.020000"))
		cross = fx.resolve_fx("GBP", "EUR", fx.FxPolicy("p", "GBP", "EUR", FxMode.PROVIDER, provider="TCMB"),
		                      RATES, AS_OF)
		self.assertEqual(cross.sell_rate, D("1.200000"))       # 60 / 50 via TRY
		self.assertEqual(cross.provider_rate_id, "t3/t1")
		ecb = (rate("e1", "EUR", "USD", "1.10", provider="ECB"), rate("e2", "EUR", "GBP", "0.85", provider="ECB"))
		c2 = fx.resolve_fx("GBP", "USD", fx.FxPolicy("p", "GBP", "USD", FxMode.PROVIDER, provider="ECB"), ecb, AS_OF)
		self.assertEqual(c2.sell_rate, D("1.294118"))          # 1.10 / 0.85 via EUR

	def test_refusals(self):
		with self.assertRaises(Unsellable) as cm:
			fx.resolve_fx("EUR", "TRY", None, RATES, AS_OF)
		self.assertEqual(cm.exception.code, "NO_FX_POLICY")
		with self.assertRaises(Unsellable) as cm:
			fx.resolve_fx("EUR", "TRY", self.pol(FxMode.PROVIDER, max_age_days=2), RATES, datetime(2027, 1, 20))
		self.assertEqual(cm.exception.code, "FX_RATE_STALE")
		with self.assertRaises(Unsellable) as cm:
			fx.resolve_fx("EUR", "TRY", self.pol(FxMode.PROVIDER, provider="ECB"), RATES, AS_OF)
		self.assertEqual(cm.exception.code, "FX_RATE_MISSING")

	def test_convert_full_precision(self):
		s = fx.resolve_fx("EUR", "TRY", self.pol(FxMode.PROVIDER_PERCENT, adjustment=D("2")), RATES, AS_OF)
		self.assertEqual(fx.convert(D("1080"), s), D("55080"))


class TestTax(unittest.TestCase):
	TR = (TaxRule("KDV", "KDV", rate=D("10"), applies_to=frozenset({"ACCOMMODATION"}), order=2),
	      TaxRule("KV", "Konaklama Vergisi", rate=D("2"), applies_to=frozenset({"ACCOMMODATION"}), order=1),
	      TaxRule("KDV20", "KDV 20", rate=D("20"), applies_to=frozenset({"EXTRA:SERVICE"}), order=3))

	def test_inclusive_lines_add_up_exactly(self):
		lines, nets = tax.compute_taxes(self.TR, {"ACCOMMODATION": D("1000.00")}, inclusive=True,
		                                currency="TRY", persons=2, nights=3)
		total_tax = sum(t.amount for t in lines)
		self.assertEqual(nets["ACCOMMODATION"] + total_tax, D("1000.00"))
		self.assertEqual([t.code for t in lines], ["KV", "KDV"])
		# each tax is rounded on the exact net (892.857…): KV 17.86, KDV 89.29; net = gross − Σ taxes
		self.assertEqual([t.amount for t in lines], [D("17.86"), D("89.29")])
		self.assertEqual(nets["ACCOMMODATION"], D("892.85"))
		self.assertTrue(all(t.included for t in lines))

	def test_exclusive_and_compound(self):
		rules = (TaxRule("A", "A", rate=D("10"), order=1),
		         TaxRule("B", "B", rate=D("5"), compound=True, order=2))
		lines, nets = tax.compute_taxes(rules, {"ACCOMMODATION": D("100")}, inclusive=False, currency="EUR",
		                                persons=2, nights=1)
		self.assertEqual([t.amount for t in lines], [D("10.00"), D("5.50")])
		self.assertEqual(nets["ACCOMMODATION"], D("100"))

	def test_extras_categories_and_fixed_levies(self):
		rules = (*self.TR, TaxRule("CITY", "City tax", kind=TaxKind.PER_PERSON_NIGHT, amount=D("2.50")))
		lines, _ = tax.compute_taxes(rules, {"ACCOMMODATION": D("500"), "EXTRA:SERVICE": D("120")},
		                             inclusive=False, currency="EUR", persons=2, nights=3)
		by = {t.code: t.amount for t in lines}
		self.assertEqual(by["KDV20"], D("24.00"))
		self.assertEqual(by["CITY"], D("15.00"))
		self.assertFalse(next(t for t in lines if t.code == "CITY").included)

	def test_slab_rate_by_nightly_tariff(self):
		gst = (TaxRule("GST", "GST", rate=D("5"), slabs=((D("7500"), D("5")), (None, D("18")))),)
		low, _ = tax.compute_taxes(gst, {"ACCOMMODATION": D("21000")}, inclusive=False, currency="INR",
		                           persons=2, nights=3)                      # 7000 / night
		high, _ = tax.compute_taxes(gst, {"ACCOMMODATION": D("24000")}, inclusive=False, currency="INR",
		                            persons=2, nights=3)                     # 8000 / night
		self.assertEqual((low[0].rate, low[0].amount), (D("5"), D("1050.00")))
		self.assertEqual((high[0].rate, high[0].amount), (D("18"), D("4320.00")))

	def test_turkish_compound_kdv_on_accommodation_tax(self):
		rules = (TaxRule("KV", "Konaklama Vergisi", rate=D("2"), order=1),
		         TaxRule("KDV", "KDV", rate=D("10"), compound=True, order=2))
		lines, nets = tax.compute_taxes(rules, {"ACCOMMODATION": D("1122.00")}, inclusive=True, currency="TRY",
		                                persons=2, nights=1)
		self.assertEqual(nets["ACCOMMODATION"], D("1000.00"))
		self.assertEqual([t.amount for t in lines], [D("20.00"), D("102.00")])

	def test_no_rules_no_tax(self):
		lines, nets = tax.compute_taxes((), {"ACCOMMODATION": D("10")}, inclusive=True, currency="EUR",
		                                persons=1, nights=1)
		self.assertEqual(lines, [])
		self.assertEqual(nets["ACCOMMODATION"], D("10"))


class TestEffectiveDatedSources(unittest.TestCase):
	"""G-20: every extra and tax step names the revision it came from, and a fixed levy
	is charged in its own currency, converted, never re-read as the sell currency."""

	EUR_TRY = FxSnapshot("EUR", "TRY", FxMode.PROVIDER_PERCENT, D("51"), provider="TCMB", provider_rate=D("50"),
	                     adjustment=D("2"))

	def test_the_extra_step_names_the_extra_revision(self):
		trf = ExtraDef("TRF", "Airport transfer", ExtraPricingMode.RESERVATION, "EUR", D("40"), revision="EXT-00007")
		q = engine.price_stay(fixtures.ctx(extras={"TRF": trf}), fixtures.req(extras=(ExtraRequest("TRF"),)))
		step = next(s for s in q.explanation.steps if s.code == "EXTRA")
		self.assertEqual(step.rule.to_dict(), {"kind": "extra", "rule_id": "TRF", "level": "HOTEL",
		                                       "source": "extra:EXT-00007", "label": "Airport transfer"})
		self.assertEqual(q.extras[0].revision, "EXT-00007")

	def test_the_tax_line_and_step_name_the_tax_policy(self):
		vat = TaxRule("VAT", "VAT", rate=D("10"), source="tax_policy:TXP-00002")
		q = engine.price_stay(fixtures.ctx(tax_rules=(vat,)), fixtures.req())
		self.assertEqual(q.taxes[0].source, "tax_policy:TXP-00002")
		step = next(s for s in q.explanation.steps if s.code == "TAX")
		self.assertEqual((step.rule.kind, step.rule.rule_id, step.rule.level, step.rule.source),
		                 ("tax", "VAT", Level.HOTEL, "tax_policy:TXP-00002"))

	def test_a_fixed_levy_in_another_currency_is_converted(self):
		city = TaxRule("CITY", "City tax", kind=TaxKind.PER_PERSON_NIGHT, amount=D("2"), currency="EUR")
		lines, _ = tax.compute_taxes((city,), {"ACCOMMODATION": D("9000")}, inclusive=False, currency="TRY",
		                             persons=2, nights=3, fx={"EUR": self.EUR_TRY})
		self.assertEqual((lines[0].amount, lines[0].fx_rate), (D("612.00"), D("51")))  # 2 × 6 person-nights × 51
		same, _ = tax.compute_taxes((city,), {"ACCOMMODATION": D("300")}, inclusive=False, currency="EUR",
		                            persons=2, nights=3)
		self.assertEqual((same[0].amount, same[0].fx_rate), (D("12.00"), None))

	def test_a_fixed_levy_without_fx_is_never_charged_as_the_sell_currency(self):
		city = TaxRule("CITY", "City tax", kind=TaxKind.PER_ROOM_NIGHT, amount=D("2"), currency="EUR")
		with self.assertRaises(Unsellable) as e:
			tax.compute_taxes((city,), {"ACCOMMODATION": D("9000")}, inclusive=False, currency="TRY", persons=2,
			                  nights=3)
		self.assertEqual(e.exception.code, "TAX_FX")
		q = engine.price_stay(fixtures.ctx(fx=self.EUR_TRY, tax_rules=(city,)), fixtures.req(sell_currency="TRY"))
		self.assertFalse(q.sellable)
		self.assertEqual(q.reasons[0]["code"], "TAX_FX")
		ok = engine.price_stay(fixtures.ctx(fx=self.EUR_TRY, tax_rules=(city,), tax_fx={"EUR": self.EUR_TRY}),
		                       fixtures.req(sell_currency="TRY"))
		self.assertTrue(ok.sellable, ok.reasons)
		self.assertEqual(next(t for t in ok.taxes if t.code == "CITY").amount, D("102.00"))  # 2 × 1 night × 51
