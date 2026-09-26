// The single-use row's form switch paired with the engine (Pricing Workspace final follow-up; ADR-061).
//
// The popover's "Also when children travel" moves the row's rules between the whole 1+0 combination
// and Adult 1 of 1+*. That must never change what one adult without children pays: either the
// engine prices the switched version as it prices the same rule written without the switch, or the
// switch is refused (singleWriteRefusal). The frontend cannot run the engine, so this test writes
// each scenario's rows - before, the rule written without the switch ("stay"), the switch as the
// popover applies it ("after") and, for a refused one, the switch written anyway ("unchecked") - and
// compares them with kamra/tex/tests/unit/parity_data/single_use_switch.json. The Python test
// kamra/tex/tests/unit/test_single_use_switch.py prices every one of those row sets with the engine
// (price_occupancy, 1 adult and no child, every room and period) and asserts: allowed ⇒ the same
// price as "stay" (and as before, for a pure switch); refused ⇒ "unchecked" would have changed it.
//
// After a change to the switch, write the file again and run both tests:
//   UPDATE_SWITCH_PAIRS=1 npm run test:unit
//   python -m unittest kamra.tex.tests.unit.test_single_use_switch
import { test } from "node:test"
import assert from "node:assert/strict"
import { readFileSync, writeFileSync } from "node:fs"
import { fileURLToPath } from "node:url"
import {
  applyOccRule,
  applyOccRuleAs,
  fromInheritedRule,
  persistCombination,
  SINGLE_CHILDREN,
  SINGLE_WHOLE,
  singleWriteRefusal,
  switchSingleUnchecked,
  type OccRule,
} from "../../src/tex/screens/rates/workspace/occupancy.ts"
import type { InheritedOccupancyRule, Row } from "../../src/tex/screens/rates/lib/types.ts"
import type { Tables } from "../../src/tex/screens/rates/lib/tables.ts"

const FIXTURE = fileURLToPath(new URL("../../../kamra/tex/tests/unit/parity_data/single_use_switch.json", import.meta.url))
const ROOMS = ["STD", "SUP", "DLX"]
const PERIODS = ["P1", "P2", "P3", "P4"]
const FIELDS = ["target", "position", "age_band", "combination", "room_type", "period_code", "op", "value", "is_override"] as const

let seq = 0
function occ(fields: Record<string, string | number | null>): Row {
  return { _key: `o${++seq}`, target: "ADULT", position: 0, age_band: "", combination: "", room_type: "", period_code: "", op: "MULTIPLY", value: "", is_override: 0, note: "", ...fields }
}

/** Children are priced in every party the engine could be asked for (the bands of the terms). */
const CHILDREN = () => [occ({ target: "CHILD", age_band: "INF", op: "MULTIPLY", value: "0" }), occ({ target: "CHILD", age_band: "CHD", op: "PERCENT_OF", value: "50" })]

function tablesOf(rules: Row[]): Tables {
  return {
    rooms: ROOMS.map((room_type, i) => ({ _key: `r${i}`, room_type, is_base: i === 0 ? 1 : 0 })),
    periods: PERIODS.map((period_code, i) => ({ _key: `p${i}`, period_code })),
    period_rates: [],
    age_bands: [],
    occupancy_rules: [...rules, ...CHILDREN()],
    boards: [],
    rate_plans: [],
    offers: [],
  }
}

const A1_ALWAYS = () => occ({ target: "ADULT", position: 1, op: "MULTIPLY", value: "1", is_override: 1 })
const WHOLE = (value: string, f: Record<string, string | number> = {}) => occ({ target: "COMBINATION", combination: "1+0", op: "MULTIPLY", value, ...f })
const ALT = (value: string, f: Record<string, string | number> = {}) => occ({ target: "ADULT", position: 1, combination: "1+*", op: "MULTIPLY", value, ...f })
const RULE = (value: string, f: Partial<OccRule> = {}): OccRule => ({ op: "MULTIPLY", value, is_override: false, note: "", ...f })

/** A pricing policy's rule as price_matrix serves it (the engine side reads `value`; a viewer
 * without cost is served no op or value: `hidden`). */
function policy(f: Partial<InheritedOccupancyRule>): InheritedOccupancyRule {
  return { rule_id: "G-1", target: "COMBINATION", position: null, age_band: null, adults: null, children: null, room_type: null, period: null, op: "MULTIPLY", value: "1", is_override: false, source: "policy:POL-G/r1/global", ...f }
}

interface Scenario {
  name: string
  before: Tables
  /** the row's form: the whole 1+0 ("whole") or Adult 1 of 1+* ("children") */
  from: "whole" | "children"
  rooms: string[]
  periods: string[]
  rule: OccRule
  /** the value written is the row's own in every cell written: a switch of form only */
  pure: boolean
  inherited?: InheritedOccupancyRule[]
  expect: "outranked" | "relative" | null
}

const card = (base: Row[], spec: Parameters<typeof persistCombination>[1]) => persistCombination(tablesOf(base), spec).tables

const SCENARIOS: Scenario[] = [
  // refused: another rule would decide what one adult pays in the other form
  { name: "an Always-wins Adult 1 and single use as the whole 1+0", before: tablesOf([A1_ALWAYS(), WHOLE("0.8")]), from: "whole", rooms: [""], periods: [""], rule: RULE("0.8"), pure: true, expect: "outranked" },
  { name: "an Always-wins Adult 1 and single use as Adult 1 of 1+* (switched back to the whole 1+0)", before: tablesOf([A1_ALWAYS(), ALT("0.8")]), from: "children", rooms: [""], periods: [""], rule: RULE("0.8"), pure: true, expect: "outranked" },
  { name: "an Always-wins Adult 1 of one room reaches the All-rooms rule that moves", before: tablesOf([{ ...A1_ALWAYS(), room_type: "SUP" }, WHOLE("0.8")]), from: "whole", rooms: [""], periods: [""], rule: RULE("0.8"), pure: true, expect: "outranked" },
  { name: "Always wins on both Adult 1 and the single-use rule (they would tie: the engine refuses the party)", before: tablesOf([A1_ALWAYS(), WHOLE("0.8", { is_override: 1 })]), from: "whole", rooms: [""], periods: [""], rule: RULE("0.8", { is_override: true }), pure: true, expect: "outranked" },
  { name: "a special combination '1 adult' with an Adult 1 rule for P1 (its exact 1+0 outranks Adult 1 of 1+*)", before: card([WHOLE("0.8")], { adults: 1, children: 0, rooms: [], periods: ["P1"], adultRules: [{ position: 1, op: "MULTIPLY", value: "0.9" }] }), from: "whole", rooms: [""], periods: [""], rule: RULE("0.8"), pure: true, expect: "outranked" },
  { name: "a whole-stay rule for any adults without children (*+0) takes 1A+0C once the whole 1+0 has gone", before: tablesOf([WHOLE("0.8"), occ({ target: "COMBINATION", combination: "*+0", op: "MULTIPLY", value: "0.95" })]), from: "whole", rooms: [""], periods: [""], rule: RULE("0.8"), pure: true, expect: "outranked" },
  { name: "a pricing policy's whole-stay rule for one adult and any children", before: tablesOf([WHOLE("0.8")]), inherited: [policy({ rule_id: "G-1A", adults: 1, value: "0.9" })], from: "whole", rooms: [""], periods: [""], rule: RULE("0.8"), pure: true, expect: "outranked" },
  { name: "the same policy rule served without its formula (a viewer without cost)", before: tablesOf([WHOLE("0.8")]), inherited: [policy({ rule_id: "G-1A", adults: 1, value: "0.9", hidden: true })], from: "whole", rooms: [""], periods: [""], rule: RULE("0.8"), pure: true, expect: "outranked" },
  { name: "one room switched while an All-rooms whole 1+0 would take its single use", before: tablesOf([WHOLE("1.5"), WHOLE("1.3", { room_type: "SUP" })]), from: "whole", rooms: ["SUP"], periods: [""], rule: RULE("1.3"), pure: true, expect: "outranked" },
  { name: "a relative period rule over an Adult 1 rule (S16 re-review 3's refusal)", before: tablesOf([occ({ target: "ADULT", position: 1, op: "MULTIPLY", value: "1.2" }), WHOLE("1.5"), WHOLE("10", { period_code: "P2", op: "ADJUST_PERCENT" })]), from: "whole", rooms: [""], periods: ["P1"], rule: RULE("1.5"), pure: false, expect: "relative" },
  // allowed: the engine prices one adult as before
  { name: "single use ×0.8 alone", before: tablesOf([WHOLE("0.8")]), from: "whole", rooms: [""], periods: [""], rule: RULE("0.8"), pure: true, expect: null },
  { name: "single use ×0.8 as Adult 1 of 1+*, back to the whole 1+0", before: tablesOf([ALT("0.8")]), from: "children", rooms: [""], periods: [""], rule: RULE("0.8"), pure: true, expect: null },
  { name: "All periods ×1.5 with P2 ×1.2 and a P4 price of 95 (period overrides move along)", before: tablesOf([WHOLE("1.5"), WHOLE("1.2", { period_code: "P2" }), WHOLE("95", { period_code: "P4", op: "ABSOLUTE" })]), from: "whole", rooms: [""], periods: [""], rule: RULE("1.5"), pure: true, expect: null },
  { name: "an Adult 1 rule that is not Always wins (Adult 1 of 1+* outranks it)", before: tablesOf([occ({ target: "ADULT", position: 1, op: "MULTIPLY", value: "1.1" }), WHOLE("0.8")]), from: "whole", rooms: [""], periods: [""], rule: RULE("0.8"), pure: true, expect: null },
  { name: "an Always-wins Adult 1 that defers (Inherit)", before: tablesOf([{ ...A1_ALWAYS(), op: "INHERIT", value: "" }, WHOLE("0.8")]), from: "whole", rooms: [""], periods: [""], rule: RULE("0.8"), pure: true, expect: null },
  { name: "a new value typed while switching", before: tablesOf([WHOLE("0.8")]), from: "whole", rooms: [""], periods: [""], rule: RULE("0.9"), pure: false, expect: null },
  { name: "the rule written marked Always wins, no other Adult 1 rule", before: tablesOf([WHOLE("0.8")]), from: "whole", rooms: [""], periods: [""], rule: RULE("0.8", { is_override: true }), pure: false, expect: null },
  { name: "a pricing policy's Adult 1 rule (the version's Adult 1 of 1+* outranks it by origin)", before: tablesOf([WHOLE("0.8")]), inherited: [policy({ rule_id: "G-A1", target: "ADULT", position: 1, value: "1.2" })], from: "whole", rooms: [""], periods: [""], rule: RULE("0.8"), pure: true, expect: null },
  { name: "one room's own rule switched, no All-rooms rule", before: tablesOf([WHOLE("1.3", { room_type: "SUP" })]), from: "whole", rooms: ["SUP"], periods: [""], rule: RULE("1.3"), pure: true, expect: null },
  { name: "a card for one adult in another period than the rules switched", before: card([WHOLE("0.8", { period_code: "P2" })], { adults: 1, children: 0, rooms: [], periods: ["P1"], adultRules: [{ position: 1, op: "MULTIPLY", value: "0.9" }] }), from: "whole", rooms: [""], periods: ["P2"], rule: RULE("0.8"), pure: true, expect: null },
]

const rowOut = (r: Row) => Object.fromEntries(FIELDS.map((f) => [f, r[f] ?? (f === "position" || f === "is_override" ? 0 : "")]))
const rows = (t: Tables) => t.occupancy_rules.map(rowOut)

function outcome(s: Scenario) {
  const slot = s.from === "whole" ? SINGLE_WHOLE : SINGLE_CHILDREN
  const to = { single: s.from === "whole" ? "children" : "whole" } as const
  const inherited = (s.inherited ?? []).map((r) => fromInheritedRule(r.hidden ? { ...r, op: null, value: null } : r))
  const refusal = singleWriteRefusal(s.before, slot, s.rooms, s.periods, to, { rule: s.rule, inherited })
  const after = applyOccRuleAs(s.before, slot, s.rooms, s.periods, s.rule, to, { inherited })
  return {
    name: s.name,
    from: s.from,
    rooms: s.rooms,
    periods: s.periods,
    rule: { op: s.rule.op, value: s.rule.value, is_override: s.rule.is_override },
    pure: s.pure,
    inherited: s.inherited ?? [],
    refusal,
    before: rows(s.before),
    stay: rows(applyOccRule(s.before, slot, s.rooms, s.periods, s.rule)),
    after: rows(after),
    unchecked: refusal ? rows(switchSingleUnchecked(s.before, slot, to, s.rooms, s.periods, s.rule)) : null,
  }
}

test("the single-use switch: each scenario is refused as expected, and nothing is written when it is", () => {
  for (const s of SCENARIOS) {
    const o = outcome(s)
    assert.equal(o.refusal, s.expect, s.name)
    if (o.refusal) assert.deepEqual(o.after, o.before, s.name)
    else assert.notDeepEqual(o.after, o.before, s.name)
  }
})

test("the scenarios' rows are the ones the engine test prices (parity_data/single_use_switch.json)", () => {
  const now = {
    about: "Written by frontend/tests/unit/single-use-switch.test.ts (UPDATE_SWITCH_PAIRS=1); priced by kamra/tex/tests/unit/test_single_use_switch.py.",
    rooms: ROOMS,
    periods: PERIODS,
    scenarios: SCENARIOS.map(outcome),
  }
  if (process.env.UPDATE_SWITCH_PAIRS) writeFileSync(FIXTURE, `${JSON.stringify(now, null, 1)}\n`)
  const kept = JSON.parse(readFileSync(FIXTURE, "utf8"))
  assert.deepEqual(kept, now, "the switch changed: write the file again (UPDATE_SWITCH_PAIRS=1) and run the engine test")
})
