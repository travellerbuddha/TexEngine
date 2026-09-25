// Unit tests for the matrix's bulk tools (PRICING_WORKSPACE_UX.md §3.10, D2, D11, O4; slice S10):
// Fill right / Fill down (copy across periods, copy down rooms, a price into a formula row only
// after confirmation, never a formula into a price row), the Adjust… targets, preview lines and
// commit (the server's amounts written as ABSOLUTE; the client computes none), one entry over
// cells with different entries (paste) and the server calls it makes.
// Run with `npm run test:unit` (node --test).
import { test } from "node:test"
import assert from "node:assert/strict"
import { parseShorthand } from "../../src/tex/screens/rates/lib/shorthand.ts"
import type { Row } from "../../src/tex/screens/rates/lib/types.ts"
import type { Tables } from "../../src/tex/screens/rates/lib/tables.ts"
import {
  ADJUST_KINDS,
  ADJUST_PREVIEW_LINES,
  adjustPreview,
  adjustRule,
  adjustTargets,
  applyAdjust,
  planFill,
  serverCalls,
} from "../../src/tex/screens/rates/workspace/bulk.ts"
import { finishItems, planItems } from "../../src/tex/screens/rates/workspace/matrixView.ts"

let seq = 0
const r = (fields: Record<string, string | number | null>): Row => ({ _key: `b${++seq}`, ...fields })
const rate = (room: string, period: string, op: string, value: string, base = "") => r({ room_type: room, period_code: period, op, value, base_room_type: base })
const tablesOf = (p: Partial<Tables>): Tables => ({ rooms: [], periods: [], period_rates: [], age_bands: [], occupancy_rules: [], boards: [], rate_plans: [], offers: [], ...p })
const sh = (text: string, minorUnits?: number) => parseShorthand(text, "room", { minorUnits })
const at = (room: string, period: string) => ({ room, period })

/** The owner's example: Standard 70/80/100/130 (base), Superior ×1.15 with a fixed 245 in P2 and
 * ×1.2 in P4, Deluxe ×1.35, and a manual Family room with 90 for all periods. */
function owner(): Tables {
  return tablesOf({
    rooms: [r({ room_type: "STD", is_base: 1 }), r({ room_type: "SUP", is_base: 0 }), r({ room_type: "DLX", is_base: 0 }), r({ room_type: "FAM", is_base: 0 })],
    periods: ["P1", "P2", "P3", "P4"].map((p) => r({ period_code: p })),
    period_rates: [
      rate("STD", "P1", "ABSOLUTE", "70"),
      rate("STD", "P2", "ABSOLUTE", "80"),
      rate("STD", "P3", "ABSOLUTE", "100"),
      rate("STD", "P4", "ABSOLUTE", "130"),
      rate("SUP", "", "MULTIPLY", "1.15", "STD"),
      rate("SUP", "P2", "ABSOLUTE", "245"),
      rate("SUP", "P4", "MULTIPLY", "1.2", "STD"),
      rate("DLX", "", "MULTIPLY", "1.35", "STD"),
      rate("FAM", "", "ABSOLUTE", "90"),
    ],
  })
}
const ratesOf = (t: Tables, room: string) =>
  t.period_rates.filter((x) => x.room_type === room).map((x) => `${x.period_code || "*"}:${x.op}:${x.value}:${x.base_room_type || "-"}`)

// ─── Fill right / Fill down ────────────────────────────────────────────────

test("Fill right copies each row's leftmost cell across the selected periods", () => {
  const t = owner()
  const res = planFill(t, [
    { from: at("STD", "P1"), to: at("STD", "P2") },
    { from: at("STD", "P1"), to: at("STD", "P3") },
  ])
  assert.ok("tables" in res, JSON.stringify(res))
  assert.deepEqual(res.fixed, [])
  assert.equal(res.count, 2)
  assert.deepEqual(ratesOf(res.tables, "STD"), ["P1:ABSOLUTE:70:-", "P2:ABSOLUTE:70:-", "P3:ABSOLUTE:70:-", "P4:ABSOLUTE:130:-"])
  // the source keeps its row (and its key); the targets keep theirs, updated in place
  assert.equal(res.tables.period_rates[0], t.period_rates[0])
  assert.equal(res.tables.period_rates[1]._key, t.period_rates[1]._key)
})

test("Fill down copies a formula to the formula rows below, keeping the base it derives from", () => {
  const res = planFill(owner(), [{ from: at("SUP", "P4"), to: at("DLX", "P4") }])
  assert.ok("tables" in res)
  assert.deepEqual(ratesOf(res.tables, "DLX"), ["*:MULTIPLY:1.35:STD", "P4:MULTIPLY:1.2:STD"])
  assert.deepEqual(res.fixed, [])
})

test("a price copied into a formula row is a fixed price override: the plan names those cells for the confirmation", () => {
  const res = planFill(owner(), [
    { from: at("STD", "P3"), to: at("SUP", "P3") },
    { from: at("STD", "P3"), to: at("DLX", "P3") },
    { from: at("STD", "P3"), to: at("FAM", "P3") },
  ])
  assert.ok("tables" in res)
  assert.deepEqual(res.fixed, [at("SUP", "P3"), at("DLX", "P3")])
  assert.deepEqual(ratesOf(res.tables, "SUP"), ["*:MULTIPLY:1.15:STD", "P2:ABSOLUTE:245:-", "P4:MULTIPLY:1.2:STD", "P3:ABSOLUTE:100:-"])
  assert.deepEqual(ratesOf(res.tables, "FAM"), ["*:ABSOLUTE:90:-", "P3:ABSOLUTE:100:-"])
  // a price copied within a formula room (Superior's fixed P2 across P3) is one too
  const across = planFill(owner(), [{ from: at("SUP", "P2"), to: at("SUP", "P3") }])
  assert.ok("tables" in across)
  assert.deepEqual(across.fixed, [at("SUP", "P3")])
})

test("a formula is never copied into a price row: the whole fill is refused at that cell", () => {
  const t = owner()
  assert.deepEqual(
    planFill(t, [
      { from: at("SUP", "P4"), to: at("DLX", "P4") },
      { from: at("SUP", "P4"), to: at("FAM", "P4") },
    ]),
    { error: "FILL_FORMULA", cell: at("FAM", "P4") },
  )
  // nor into the base room (there a relative entry would change its price once, O4: not a copy)
  assert.deepEqual(planFill(t, [{ from: at("SUP", "P4"), to: at("STD", "P4") }]), { error: "FILL_FORMULA", cell: at("STD", "P4") })
})

test("an empty or inherited source clears its targets; an INHERIT row is copied as INHERIT", () => {
  const t = owner()
  // Superior P1 follows all periods: copied over P4's own ×1.2, P4 follows all periods too
  const res = planFill(t, [{ from: at("SUP", "P1"), to: at("SUP", "P4") }])
  assert.ok("tables" in res)
  assert.deepEqual(ratesOf(res.tables, "SUP"), ["*:MULTIPLY:1.15:STD", "P2:ABSOLUTE:245:-"])
  const inh = { ...t, period_rates: [...t.period_rates, rate("DLX", "P1", "INHERIT", "")] }
  const res2 = planFill(inh, [{ from: at("DLX", "P1"), to: at("DLX", "P2") }])
  assert.ok("tables" in res2)
  assert.deepEqual(ratesOf(res2.tables, "DLX"), ["*:MULTIPLY:1.35:STD", "P1:INHERIT::-", "P2:INHERIT::-"])
})

test("a copied formula never derives a room from itself: it takes the target's default base", () => {
  // Deluxe P4 derives from Superior; copied up into Superior it derives from Superior's default base
  const t = { ...owner(), period_rates: [...owner().period_rates, rate("DLX", "P4", "MULTIPLY", "1.1", "SUP")] }
  const res = planFill(t, [{ from: at("DLX", "P4"), to: at("SUP", "P4") }])
  assert.ok("tables" in res)
  assert.deepEqual(ratesOf(res.tables, "SUP").at(-1), "P4:MULTIPLY:1.1:STD")
})

test("a fill that changes nothing returns the same tables (no history entry); a copy equal to the default drops the period row", () => {
  const t = owner()
  const same = planFill(t, [{ from: at("STD", "P1"), to: at("STD", "P1") }])
  assert.ok("tables" in same)
  assert.equal(same.tables, t)
  // Superior All periods ×1.15 copied across P4: P4 then follows all periods (the same price)
  const res = planFill(t, [{ from: at("SUP", ""), to: at("SUP", "P4") }])
  assert.ok("tables" in res)
  assert.deepEqual(ratesOf(res.tables, "SUP"), ["*:MULTIPLY:1.15:STD", "P2:ABSOLUTE:245:-"])
})

// ─── Adjust… ────────────────────────────────────────────────────────────────

test("Adjust… ops: +%, −%, +amount, −amount, × map onto the ops apply_op_values takes", () => {
  assert.deepEqual(ADJUST_KINDS, ["up_pct", "down_pct", "up_amount", "down_amount", "times"])
  assert.deepEqual(adjustRule("up_pct", "10"), { ok: true, op: "ADJUST_PERCENT", value: "10" })
  assert.deepEqual(adjustRule("down_pct", "7,5"), { ok: true, op: "ADJUST_PERCENT", value: "-7.5" })
  assert.deepEqual(adjustRule("down_pct", "0"), { ok: true, op: "ADJUST_PERCENT", value: "0" })
  assert.deepEqual(adjustRule("up_amount", "5"), { ok: true, op: "ADD", value: "5" })
  assert.deepEqual(adjustRule("down_amount", "5.50"), { ok: true, op: "SUBTRACT", value: "5.5" })
  assert.deepEqual(adjustRule("times", "1.100"), { ok: true, op: "MULTIPLY", value: "1.1" })
  assert.deepEqual(adjustRule("times", ""), { ok: false, code: "BLANK" })
  assert.deepEqual(adjustRule("up_pct", "1 0"), { ok: false, code: "SYNTAX" })
  assert.deepEqual(adjustRule("up_pct", "-5"), { ok: false, code: "SYNTAX" }, "the sign is the op's")
})

test("Adjust… amounts are currency-aware (O5); factors and percentages are exempt", () => {
  assert.deepEqual(adjustRule("up_amount", "1.500", 2), { ok: false, code: "AMBIGUOUS" })
  assert.deepEqual(adjustRule("down_amount", "1,500", 0), { ok: false, code: "AMBIGUOUS" })
  assert.deepEqual(adjustRule("up_amount", "1.500", 3), { ok: true, op: "ADD", value: "1.5" })
  assert.deepEqual(adjustRule("up_pct", "1.500", 2), { ok: true, op: "ADJUST_PERCENT", value: "1.5" })
  assert.deepEqual(adjustRule("times", "1.125", 2), { ok: true, op: "MULTIPLY", value: "1.125" })
})

test("Adjust… targets the selected entered prices in any row; formula cells are counted as skipped", () => {
  const t = owner()
  const res = adjustTargets(t, [at("STD", ""), at("STD", "P1"), at("STD", "P2"), at("SUP", ""), at("SUP", "P1"), at("SUP", "P2"), at("SUP", "P4"), at("FAM", ""), at("FAM", "P1"), at("DLX", "P3")])
  assert.deepEqual(res.targets, [
    { cell: at("STD", "P1"), current: "70" },
    { cell: at("STD", "P2"), current: "80" },
    { cell: at("SUP", "P2"), current: "245" }, // Superior's fixed price (fixed-override)
    { cell: at("FAM", ""), current: "90" }, // a manual room's All-periods price
  ])
  // Superior All periods, P1 (follows the formula), P4 (its own formula); Deluxe P3 (follows its formula)
  assert.equal(res.formulas, 4)
  // Standard All periods (empty) and Family P1 (follows the All-periods price: adjust that cell)
  assert.equal(res.others, 2)
  assert.deepEqual(adjustTargets(t, []), { targets: [], formulas: 0, others: 0 })
})

test("the Adjust… preview lists the cells that change, their errors, and counts the unchanged ones", () => {
  const targets = [
    { cell: at("STD", "P1"), current: "70" },
    { cell: at("STD", "P2"), current: "80" },
    { cell: at("STD", "P3"), current: "100" },
    { cell: at("STD", "P4"), current: "130" },
  ]
  const p = adjustPreview(targets, [
    { value: "77.00", error: null },
    { value: "80.00", error: null },
    { value: null, error: "NEGATIVE" },
    { value: "143.00", error: null },
  ])
  assert.deepEqual(p.changes, [
    { cell: at("STD", "P1"), before: "70", after: "77.00" },
    { cell: at("STD", "P4"), before: "130", after: "143.00" },
  ])
  assert.deepEqual(p.errors, [{ cell: at("STD", "P3"), code: "NEGATIVE" }])
  assert.equal(p.unchanged, 1)
  assert.equal(ADJUST_PREVIEW_LINES, 8)
  // an answer missing for a price is an error, never a silent skip
  assert.deepEqual(adjustPreview(targets.slice(0, 1), []).errors, [{ cell: at("STD", "P1"), code: "NO_VALUE" }])
})

test("Adjust… Apply writes the server's amounts as ABSOLUTE, in one result; a changed or refused price applies nothing", () => {
  const t = owner()
  const targets = adjustTargets(t, [at("STD", "P1"), at("STD", "P2"), at("SUP", "P2")]).targets
  const answers = [
    { value: "77.00", error: null },
    { value: "80", error: null },
    { value: "269.50", error: null },
  ]
  const res = applyAdjust(t, targets, answers)
  assert.ok("tables" in res, JSON.stringify(res))
  assert.deepEqual(ratesOf(res.tables, "STD"), ["P1:ABSOLUTE:77.00:-", "P2:ABSOLUTE:80:-", "P3:ABSOLUTE:100:-", "P4:ABSOLUTE:130:-"])
  assert.equal(res.tables.period_rates[1], t.period_rates[1], "an unchanged price keeps its row as it is")
  assert.deepEqual(ratesOf(res.tables, "SUP"), ["*:MULTIPLY:1.15:STD", "P2:ABSOLUTE:269.50:-", "P4:MULTIPLY:1.2:STD"])
  // the price was edited after the preview: nothing is applied
  const edited = { ...t, period_rates: t.period_rates.map((x) => (x.room_type === "STD" && x.period_code === "P2" ? { ...x, value: "85" } : x)) }
  assert.deepEqual(applyAdjust(edited, targets, answers), { error: "CHANGED", cell: at("STD", "P2") })
  const formula = { ...t, period_rates: t.period_rates.map((x) => (x.room_type === "SUP" && x.period_code === "P2" ? { ...x, op: "MULTIPLY", value: "1.3", base_room_type: "STD" } : x)) }
  assert.deepEqual(applyAdjust(formula, targets, answers), { error: "CHANGED", cell: at("SUP", "P2") })
  assert.deepEqual(applyAdjust(t, targets, [answers[0], { value: null, error: "NEGATIVE" }, answers[2]]), { error: "NEGATIVE", cell: at("STD", "P2") })
  assert.deepEqual(applyAdjust(t, targets, answers.slice(0, 2)), { error: "NO_VALUE", cell: at("SUP", "P2") })
  // same numbers as before (canonically): the same tables, so no history entry
  const same = applyAdjust(t, targets, [
    { value: "70.00", error: null },
    { value: "80", error: null },
    { value: "245.000000000", error: null },
  ])
  assert.ok("tables" in same)
  assert.equal(same.tables, t)
})

// ─── one entry over cells with different entries (paste) ────────────────────

test("a paste is one entry of different texts: formulas and prices at once, base-room relative entries for the server", () => {
  const t = owner()
  const plan = planItems(t, [
    { cell: at("STD", "P1"), parsed: sh("+10%") },
    { cell: at("STD", "P2"), parsed: sh("x1.1") },
    { cell: at("STD", "P3"), parsed: sh("+10%") },
    { cell: at("DLX", "P1"), parsed: sh("x1.4") },
    { cell: at("FAM", "P1"), parsed: sh("95") },
  ])
  assert.ok("tables" in plan, JSON.stringify(plan))
  assert.deepEqual(
    plan.server.map((s) => [s.targetPeriod, s.op, s.value, s.current]),
    [
      ["P1", "ADJUST_PERCENT", "10", "70"],
      ["P2", "MULTIPLY", "1.1", "80"],
      ["P3", "ADJUST_PERCENT", "10", "100"],
    ],
  )
  // one apply_op_values call per op and value (at most 500 prices each), answers put back in order
  const calls = serverCalls(plan.server)
  assert.deepEqual(
    calls.map((c) => [c.op, c.value, c.values, c.indexes]),
    [
      ["ADJUST_PERCENT", "10", ["70", "100"], [0, 2]],
      ["MULTIPLY", "1.1", ["80"], [1]],
    ],
  )
  assert.deepEqual(
    serverCalls(Array.from({ length: 1001 }, (_, i) => ({ room: "STD", targetPeriod: `P${i}`, op: "ADD" as const, value: "5", current: "1" }))).map((c) => c.values.length),
    [500, 500, 1],
  )
  const items = [
    { cell: at("STD", "P1"), parsed: sh("+10%") },
    { cell: at("STD", "P2"), parsed: sh("x1.1") },
    { cell: at("STD", "P3"), parsed: sh("+10%") },
    { cell: at("DLX", "P1"), parsed: sh("x1.4") },
    { cell: at("FAM", "P1"), parsed: sh("95") },
  ]
  const done = finishItems(
    t,
    items,
    plan.server,
    [
      { value: "77.00", error: null },
      { value: "88.00", error: null },
      { value: "110.00", error: null },
    ],
    t,
  )
  assert.ok("tables" in done, JSON.stringify(done))
  assert.deepEqual(ratesOf(done.tables, "STD"), ["P1:ABSOLUTE:77.00:-", "P2:ABSOLUTE:88.00:-", "P3:ABSOLUTE:110.00:-", "P4:ABSOLUTE:130:-"])
  assert.deepEqual(ratesOf(done.tables, "DLX"), ["*:MULTIPLY:1.35:STD", "P1:MULTIPLY:1.4:STD"])
  assert.deepEqual(ratesOf(done.tables, "FAM"), ["*:ABSOLUTE:90:-", "P1:ABSOLUTE:95:-"])
  // all or nothing: one refused cell refuses the paste
  assert.deepEqual(planItems(t, [...items, { cell: at("SUP", "P1"), parsed: sh("abc") }]), { error: "SYNTAX", cell: at("SUP", "P1") })
})
