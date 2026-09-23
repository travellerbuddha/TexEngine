# Design: G-30 + G-31 — "occupancy precedence v2" (one change, ADR-041 → renumber if taken)

Publish-time validation lives in the PURE module kamra/tex/pricing/validate.py (called from contracts.validate_version / publish). There is no kamra/tex/commercial/validate.py.

## G-30 Pricing-policy cascade
Root cause: kamra/tex/commercial/contracts.py `_policy_for` (~99-118) keeps ONE live policy, ranked (2 if property)+(1 if market): hotel+market 3 > hotel 2 > market 1 > global 0, so a hotel-only policy beats a market one, and nothing cascades. build_terms (~202-208) uses its bands only when the version has none and appends its rules once.
Found while tracing:
- chosen policy without bands + version without bands → bands=() → ages.classify_party top=0 → every child priced as an adult (children_over_max_as_adults default True).
- occupancy.rule_level ignores origin: a policy COMBINATION rule and a version COMBINATION rule with the same qualifiers tie → AMBIGUOUS_OCCUPANCY_RULES at runtime; publish only warns.
- no one-live-policy-per-scope guard (loader picks the first by name).
- i18n rates.policy.pricing.scope_help states the wrong order ("hotel + market, hotel, market, global").
As-of-sale-time is already right: policies are resolved with as_of(..., eff) at publish and frozen in the payload (ADR-004); pricing, simulator, ORIGINAL_* use the payload. Risk: resolver changes alter old payloads → versioned precedence below.

Decision:
1. Load ALL applicable live policies (global, hotel, market, hotel+market) as of eff. Each rule keeps its origin: new OccupancyRule.scope_weight (property=1, market=2, like markup.weight): global GLOBAL/0, hotel HOTEL/1, market MARKET/2, hotel+market MARKET/3 (spec: MARKET above HOTEL; matches markup.level()). Explanation source e.g. `policy:POL-00004/r2/hotel+market`.
2. Origin ranks before qualifiers: VERSION rule > hotel+market > market > hotel > global; then OVERRIDE > COMBINATION > PERIOD > ROOM; then slot qualifiers. (Product copy rates.policy.pricing.occ_help: "Default adult/child rules, overridden by any rule in a contract version".) Removes cross-level ties.
3. Age bands are REPLACED, not merged: version bands if any, else the band set of the most specific policy defining one (H+M > M > H > G). Rules cascade by band code; an inherited rule whose band/room/period doesn't exist in this contract never applies → WARNING OCC_INHERITED_*_UNUSED (not ERROR).
4. Ties refused: activating a second live policy with the same (property, market) is refused (tex_pricing_policy controller, on Draft→Active like TEXTaxPolicy); if it still happens build_terms fails PRICING_POLICY_AMBIGUOUS (BUILD issue; publish refuses). OCC_DUPLICATE signature gains scope_weight.
5. Old payloads keep sold semantics: new payloads carry settings.occupancy_precedence = 2; a payload without it reads as 1 and uses exactly today's tuple. Policy changes reach a contract only on republish (ADR-004).

Ranking (occupancy.py):
```python
LEGACY, CASCADE = 1, 2   # ContractTerms.occupancy_precedence; payload without the key -> LEGACY
def specificity(rule, *, precedence=CASCADE, infant_slot=False) -> tuple:
	qual = (int(rule_level(rule)), rule.period is not None, rule.room_type is not None,
	        rule.adults is not None and rule.children is not None)
	slot = (rule.position is not None, rule.age_band is not None)
	if precedence == LEGACY:
		return (*qual, *slot)                                  # exactly today's tuple
	return (infant_slot and rule.age_band is not None,         # G-31
	        int(rule.base_level), rule.scope_weight,           # G-30: VERSION > H+M > M > H > GLOBAL
	        *qual, *slot)
```
_pick(candidates, what, key) sorts by key; ambiguity guard compares key(other) != key(r). price_occupancy: adults/COMBINATION use key=specificity(r, precedence=terms.occupancy_precedence); child slots add infant_slot=child.band.is_infant. Rewrite module docstring.

Code changes:
- NEW pure kamra/tex/pricing/inherit.py: PolicyLayer(policy_id, revision, property, market, bands, rules) with .weight; level_for(weight) (MARKET if weight&2 else HOTEL if weight&1 else GLOBAL); scope_label(weight); cascade(version_bands, version_rules, layers) -> (bands, rules) (raises PricingError on duplicate weights; bands by replace rule; returns version rules + every layer's rules, most specific first).
- pricing/model.py: OccupancyRule.scope_weight: int = 0; ContractTerms.occupancy_precedence: int = 2 (both at the END of the dataclasses).
- pricing/serialize.py: terms_to_payload writes scope_weight per occupancy rule and settings.occupancy_precedence (test_roundtrip_is_lossless); terms_from_payload reads int(r.get("scope_weight") or 0) and int(s.get("occupancy_precedence") or 1). Schema string stays tex.contract.v1.
- pricing/occupancy.py: specificity, _pick, price_occupancy, docstring; rule_ref may add the policy scope.
- commercial/contracts.py: replace _policy_for with _policy_layers(property, market, at) (as_of fields name, property, market, revision_no; existing applicability filter; one PolicyLayer per policy; PricingError → frappe.throw); _occ_rules(..., scope_weight=0); build_terms calls inherit.cascade and sets occupancy_precedence=2.
- pricing/validate.py: OCC_UNKNOWN_BAND/ROOM/PERIOD stay ERROR only for version rules (base_level >= CONTRACT); inherited → WARNING OCC_INHERITED_*_UNUSED; scope_weight in duplicate signature; WARNING NO_AGE_BANDS when no bands but a room allows children.
- commercial/revisions.py live_or_scheduled_roots (~236-249): None filter values as IFNULL(col,'')='' (as as_of does) — today a blank global scope never matches.
- tex_pricing_policy controller validate: upper-case band codes + ages.validate_bands; refuse period_code in policy rules; room type must belong to the policy's hotel; on activation lock + refuse a second live/scheduled policy with the same (property, market).
- Frontend: rates.policy.pricing.scope_help and rates.occ.precedence in 6 languages (frontend/src/tex/i18n/locales/rates/*.json).
- tests/integration/fixtures.create_contract gains age_bands=None, occupancy_rules=None kwargs.
No DocType change; payload keys optional (no patch).

Tests failing today (unit, test_occupancy_and_rooms.py with fx.terms(); STD P1 = 100, DLX P1 = 135):
- test_version_combination_rule_beats_same_policy_rule: TestRoomBasis (ROOM basis, room 200) + POL-1A (COMBINATION PERCENT_OF 90, adults=1, children=0, base_level=HOTEL) → 1A = 160 (today AMBIGUOUS).
- test_contract_rule_beats_policy_room_rule: + POL-A3-DLX (ADULT pos 3 MULTIPLY 0.90 room DLX base HOTEL) → DLX 3A = 364.5 (today 391.5).
- test_hotel_market_policy_beats_market_policy: remove O-CHB; add M-CHB (PERCENT_OF 40, MARKET, w2), HM-CHB (PERCENT_OF 45, MARKET, w3) → 2A+1C(8) = 245.
- test_inherit_in_hotel_market_policy_defers_to_market_policy: HM-CHB INHERIT w3, M-CHB 40 w2, H-CHB 30 HOTEL w1 → 240.
New unit test_policy_cascade.py (layers): GLOBAL w0 bands INF 0–36m (infant), CHD 36–144; rules G-INF ×0, G-CHD 50%, G-A3 ×0.70. HOTEL-A w1 no bands; H-A3 ×0.80, H-CHB 30%. DE w2 bands INF 0–36, CHA 36–84, CHB 84–144; M-CHA 25%, M-CHB 40%. HOTEL-A+DE w3 no bands; HM-CHB INHERIT, HM-1A0C COMBINATION 1+0 ×0.90. Version no bands/rules. Expected STD P1: bands = DE's; 3A = 280; 2A+1C(8) = 240; 2A+1C(4) = 225; 2A+1C(1) = 200; 1A = 90; CHILD_SLOT step names M-CHB level MARKET, overridden contains HM-CHB and H-CHB; validate_terms → WARNING OCC_INHERITED_BAND_UNUSED for G-CHD, no ERROR; two layers same weight → PricingError.
Payload: round trip keeps scope_weight + occupancy_precedence; payload without key loads as precedence 1.
Integration (new test_pricing_policies.py): activate the four policies for fx.PROPERTY / DE with fx.ensure_live, publish create_contract(age_bands=[], occupancy_rules=[]), price LOW STD 1 night via quoting.price_request: 2A+[8] nights[0].occupancy = 240.00 (today 300.00); 3A 280.00 (today 300.00); 2A+[1] 200.00 (today 300.00); payload 9 rules (GLOBAL/0 ×3, HOTEL/1 ×2, MARKET/2 ×2, MARKET/3 ×2). test_market_policy_beats_hotel_policy: only H (own bands, CHB 30%) and DE (CHB 40%) → 240.00 (today 230.00). test_two_live_policies_of_one_scope_are_refused. test_policy_change_reaches_contract_only_on_republish: revise DE CHB to 45%: existing version still 240, republished 245, simulate at earlier sale time 240. Archive stray live policies inside the test transaction first.
Risks: sites with two live policies in one scope cannot publish until one is archived (list them at deploy); parent_market chains not walked.

## G-31 Band-less rules outrank band rules
Root cause: kamra/tex/tests/unit/fixtures.py:90 O-2A2C-C2 (CHILD PERCENT_OF 25, position 2, 2A+2C, no band) level COMBINATION; line 84 O-INF (INF ×0) level VERSION. For 2A+(8,1) (oldest first) the infant is child 2 → O-2A2C-C2 wins → infant pays 25 (275 instead of 250). Cross-level, not only inside a level. Same inside one level: version "Child 1 ×0.5" beats "[INF] ×0" (position above band, occupancy.py:52-60). validate._sweep (142-172) only catches unsellable cases; an ambiguous tie is only a WARNING. No existing test asserts the buggy infant price. Constraints: test_reference_contract_is_clean (zero issues on fx.terms()) and test_sweep_warns_about_unpriceable_combinations (only TEEN NO_CHILD_RULE warnings).
Decision B′: for a child in an infant band (is_infant), a rule naming that band beats every band-less rule, at any level/origin; band-less rules still price infants when no infant-band rule matches; for non-infant children today's order holds (position rules are exceptions to band defaults). Among infant-band rules, INHERIT falls back to less specific infant-band rules first.
Final order for one slot (v2): (1) infant slot only: rules naming the infant's band; (2) origin VERSION > H+M > M > H > G; (3) OVERRIDE > COMBINATION > PERIOD > ROOM > none; (4) period > room > exact combination; (5) position+band > position > band > neither. Equal keys with different values → AMBIGUOUS at runtime → publish ERROR.
Validation (pricing/validate.py): NEW ERROR OCC_AMBIGUOUS (static): for each target any pair of non-INHERIT rules with equal v2 keys that can match the same slot (room & period equal; adults/children compatible within some room capacity, e.g. (2,*) and (*,2) meet at 2+2; positions and bands equal or both empty) and different (op, value). In _sweep map AMBIGUOUS_OCCUPANCY_RULES to ERROR; NO_CHILD_RULE stays WARNING. NEW WARNING OCC_INFANT_GENERIC: an infant band no rule names while band-less rules exist. Reference fixture must stay clean.
Unit tests failing today: test_infant_is_priced_by_its_band_rule_not_a_band_less_combination_rule: occ(fx.terms(), "STD","P1",2,8,1) total 250 (today 275), slots [100,100,50,0], slots[3].rule.rule_id == "O-INF", CHILD_SLOT overridden contains O-2A2C-C2. test_engine_family_with_infant: engine.price_stay(fx.ctx(), fx.req(children=(8,1))).totals["total"] == D("250.00") (today 275.00). test_band_less_position_rule_never_prices_an_infant: add O-C1 (CHILD MULTIPLY 0.5 position 1): 2A+[1] = 200 (today 250); guard 2A+[4] = 250 both. test_policy_infant_rule_beats_version_band_less_rule: version without O-INF but with O-C1, plus G-INF (GLOBAL INF ×0): 2A+[1] = 200 (today 250). Guards (pass both): without O-INF + O-ANY 50%: 2A+[1] = 250; explicit @2A+2C Child 2 [INF] FIXED 10: 2A+[8,1] = 260. test_legacy_payload_keeps_its_sold_price: replace(fx.terms(), occupancy_precedence=1) → 2A+[8,1] = 275. Validation (test_contracts_restrictions.py): test_overlapping_partial_combinations_are_an_error: P-2A (pos 1, adults=2, 60%) + P-2C (pos 1, children=2, 40%) → ERROR OCC_AMBIGUOUS; test_infants_priced_only_by_band_less_rules_warn → WARNING OCC_INFANT_GENERIC; test_reference_contract_is_clean stays [].
Integration failing today: test_infant_in_a_family_room_is_free: create_contract + rule {"target":"CHILD","position":2,"combination":"2+2","op":"PERCENT_OF","value":25}; search 2A+[8,1] 3 LOW nights → offer total "802.50" ((100+100+50+0)×1.07×3), today "882.75". test_ambiguous_rules_block_publish: combinations "2+*" and "*+2" both position 1 → publish raises "Cannot publish" (today publishes with a warning).
Risks: live versions keep v1 until republished → a dev-tool report listing live versions whose v1/v2 results differ. Infants still count toward the child count and take a position (YOUNGEST_FIRST pushes the older child to position 2) — separate product decision.
