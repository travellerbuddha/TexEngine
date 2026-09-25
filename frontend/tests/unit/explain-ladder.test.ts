// Unit tests for the Price test's Explain ladder and its helpers (PRICING_WORKSPACE_UX.md §3.13,
// §5.1; slice S14), on quotes recorded from preview_price on this tree's bench (the S5 backend,
// GAP-12 subtotals), trimmed to the keys the ladder reads. Run with `npm run test:unit`.
import { test } from "node:test"
import assert from "node:assert/strict"
import { readFileSync } from "node:fs"
import { explainLadder, sameAmount, type LadderStage, type NightBlock } from "../../src/tex/screens/rates/workspace/explainLadder.ts"
import { bareBandCodes, parseChildLabel, parseOpText, withRoomNames } from "../../src/tex/screens/rates/workspace/explainText.ts"
import { addDaysIso, childPayload, prefillOf, ruleRowOf, showTargetOf, withChildMode } from "../../src/tex/screens/rates/workspace/priceTest.ts"
import type { ExplainStep, PreviewResult, Row } from "../../src/tex/screens/rates/lib/types.ts"
import type { Tables } from "../../src/tex/screens/rates/lib/tables.ts"

const fixture = (name: string): PreviewResult => JSON.parse(readFileSync(new URL(`../fixtures/${name}.json`, import.meta.url), "utf8"))
const ids = (stages: LadderStage[]) => stages.map((s) => s.id)
const of = (b: NightBlock, id: string) => {
  const s = b.stages.find((x) => x.id === id)
  assert.ok(s, `stage ${id}`)
  return s
}
const ba = (s: LadderStage) => [s.before, s.after]
const codes = (s: LadderStage) => s.lines.map((l) => l.step.code)

// ─── (a) Deluxe, 2 adults + a child of 8, 3 nights in P2, BB base ──────────────

test("(a) Deluxe 2A + child 8: the stages in engine order, every value served", () => {
  const q = fixture("quote-deluxe-2a1c")
  const L = explainLadder(q)
  assert.equal(L.nights.length, 1, "the three nights are one block")
  const b = L.nights[0]
  assert.deepEqual([b.first, b.last, b.dates.length, b.period], [1, 3, 3, "P2"])
  assert.deepEqual(ids(b.stages), ["base", "period", "room", "occupancy", "child", "board", "night_cost", "markup", "fx", "promotion"])
  // the stay: the promotion not applied (a line, no amounts), tax, the final price
  assert.deepEqual(ids(L.stay), ["promotion", "tax", "final"])
  assert.deepEqual([...ba(L.stay[0]), ...codes(L.stay[0])], [null, null, "PROMO_REJECTED"])
  assert.deepEqual(ba(of(b, "base")), [null, "80.000000"])
  const period = of(b, "period")
  assert.equal(period.amount, false)
  assert.deepEqual(ba(period), [null, null])
  assert.deepEqual(period.period, { code: "P2", name: "May" })
  assert.deepEqual(ba(of(b, "room")), ["80.000000", "108.000000"])
  assert.equal(of(b, "room").derived, true)
  assert.deepEqual(ba(of(b, "occupancy")), ["108.000000", "216.000000"])
  assert.deepEqual(codes(of(b, "occupancy")), ["ADULT_SLOT", "ADULT_SLOT"])
  const child = of(b, "child")
  assert.deepEqual(ba(child), ["216.000000", "270.000000"])
  const slot = child.lines.find((l) => l.step.code === "CHILD_SLOT")
  assert.equal(slot?.step.after, "54.000000")
  assert.deepEqual(codes(child), ["CHILD_SLOT", "OCCUPANCY_TOTAL"], "the occupancy total closes the child stage")
  const board = of(b, "board")
  assert.deepEqual(ba(board), ["270.000000", "270.000000"])
  assert.equal(board.included, true)
  assert.equal(board.supplement, "0.000000")
  assert.deepEqual(ba(of(b, "night_cost")), [null, "270.000000"])
  assert.deepEqual(ba(of(b, "markup")), ["270.000000", "291.600000"])
  const fx = of(b, "fx")
  assert.deepEqual([...ba(fx), fx.rate, fx.beforeCurrency, fx.afterCurrency], ["291.600000", "291.600000", "1.000000", "contract", "sell"])
  assert.deepEqual(ba(of(b, "promotion")), ["291.600000", "291.600000"])
  assert.deepEqual(ba(L.stay[1]), ["874.80", "874.80"])
  assert.deepEqual([L.stay[1].tax, L.stay[1].included], ["0", false])
  assert.deepEqual(ba(L.stay[2]), [null, "874.80"])
  assert.deepEqual(codes(L.stay[2]), ["TOTAL"])
  assert.deepEqual(L.chainBreaks, [])
  // every value is a string the server sent: the night's fields or a step's before/after
  const served = new Set<string>()
  for (const n of q.nights ?? []) for (const v of Object.values(n)) served.add(String(v))
  for (const s of q.explanation ?? []) for (const v of [s.before, s.after]) if (v !== null) served.add(v)
  for (const v of Object.values(q.totals ?? {})) served.add(v)
  for (const s of [...b.stages, ...L.stay]) for (const v of [s.before, s.after]) if (v !== null) assert.ok(served.has(v), `${s.id}: ${v} is served`)
})

test("(a) the unit's derivation: one step from the base room, the base's entered price as Base", () => {
  const b = explainLadder(fixture("quote-deluxe-2a1c")).nights[0]
  assert.deepEqual(codes(of(b, "base")), ["ROOM_ABSOLUTE"])
  assert.deepEqual(codes(of(b, "room")), ["ROOM_DERIVED"])
  assert.deepEqual(codes(of(b, "board")), ["BOARD_BASE"])
  assert.deepEqual(codes(of(b, "night_cost")), ["NIGHT_COST"])
  assert.deepEqual(codes(of(b, "markup")), ["MARKUP"])
})

// ─── (b) a whole-combination rule ────────────────────────────────────────────

test("(b) 2A+2C with a combination rule: Special combination starts from subtotal_children", () => {
  const q = fixture("quote-combination-2a2c")
  const L = explainLadder(q)
  const b = L.nights[0]
  assert.deepEqual(ids(b.stages), ["base", "period", "room", "occupancy", "child", "combination", "board", "night_cost", "markup", "fx", "promotion"])
  const combo = of(b, "combination")
  assert.equal(combo.before, q.nights![0].subtotal_children)
  assert.equal(combo.after, q.nights![0].occupancy)
  assert.deepEqual(ba(combo), ["429.000000", "386.100000"])
  assert.deepEqual(codes(of(b, "child")), ["CHILD_SLOT", "CHILD_SLOT"])
  assert.deepEqual(L.chainBreaks, [])
})

// ─── (c) a night adjustment and a rate plan ──────────────────────────────────

test("(c) Period adjustment comes after Board and before Rate plan and Night cost", () => {
  const q = fixture("quote-period-adjust")
  const L = explainLadder(q)
  const b = L.nights[0]
  assert.deepEqual(ids(b.stages), ["base", "period", "room", "occupancy", "board", "period_adjustment", "rate_plan", "night_cost", "markup", "fx", "promotion"])
  const adj = of(b, "period_adjustment")
  assert.equal(adj.before, q.nights![0].subtotal_board)
  assert.deepEqual([...ba(adj), adj.period?.code], ["160.000000", "176.000000", "P2"])
  assert.deepEqual(ba(of(b, "rate_plan")), ["176.000000", "167.200000"])
  assert.deepEqual(ba(of(b, "night_cost")), [null, "167.200000"])
  assert.equal(of(b, "room").derived, false, "Standard is priced by its own entered price")
  assert.deepEqual(ba(of(b, "room")), [null, "80.000000"])
  assert.deepEqual(L.chainBreaks, [])
})

// ─── (d) ROOM basis ─────────────────────────────────────────────────────────

test("(d) ROOM basis: Occupancy starts from the room price, with the ROOM_BASIS line", () => {
  const L = explainLadder(fixture("quote-room-basis"))
  const occ = of(L.nights[0], "occupancy")
  assert.deepEqual(ba(occ), ["200.000000", "270.000000"])
  assert.deepEqual(codes(occ), ["ROOM_BASIS", "ADULT_SLOT", "OCCUPANCY_TOTAL"])
  assert.equal(L.nights[0].stages.some((s) => s.id === "child"), false, "no children, no Child stage")
  assert.deepEqual(L.chainBreaks, [])
})

// ─── (e) a quote without the GAP-12 subtotals ─────────────────────────────────

test("(e) without subtotal_*: Occupancy, Child and Board are blank and computed from nothing", () => {
  const q = fixture("quote-deluxe-2a1c")
  for (const n of q.nights!) {
    delete n.subtotal_adults
    delete n.subtotal_children
    delete n.subtotal_board
  }
  const L = explainLadder(q)
  const b = L.nights[0]
  for (const id of ["occupancy", "child", "board"]) {
    const s = of(b, id)
    assert.deepEqual([...ba(s), s.missing], [null, null, true], id)
    assert.ok(s.lines.length > 0, `${id} keeps its detail lines`)
  }
  assert.deepEqual(ba(of(b, "room")), ["80.000000", "108.000000"])
  assert.deepEqual(ba(of(b, "night_cost")), [null, "270.000000"])
  assert.deepEqual(L.chainBreaks, [], "a missing value is not a break")
})

// ─── (f) a synthetic break ────────────────────────────────────────────────────

test("(f) Room after ≠ Occupancy before is reported, per night, and nothing is corrected", () => {
  const q = fixture("quote-deluxe-2a1c")
  q.nights![1].unit = "109.000000"
  const L = explainLadder(q)
  assert.deepEqual(
    L.chainBreaks.map((x) => [x.scope, x.night, x.stage, x.value, x.previous, x.previousAfter]),
    [["night", q.nights![1].date, "occupancy", "109.000000", "room", "108.000000"]],
  )
  assert.deepEqual(
    L.nights.map((b) => [b.first, b.last]),
    [
      [1, 1],
      [2, 2],
      [3, 3],
    ],
    "the changed night is a block of its own",
  )
  assert.equal(of(L.nights[1], "occupancy").before, "109.000000")
  // a stay-level break: the final price is not the tax stage's after
  const t = fixture("quote-deluxe-2a1c")
  t.totals = { ...t.totals, total: "874.81" }
  assert.deepEqual(explainLadder(t).chainBreaks, [], "tax and final both read totals.total")
})

test("(f) canonical comparison: trailing zeros and 6-dp strings are the same amount", () => {
  assert.equal(sameAmount("216.000000", "216"), true)
  assert.equal(sameAmount("874.80", "874.800000"), true)
  assert.equal(sameAmount("-0.000000", "0"), true)
  assert.equal(sameAmount("108.000001", "108"), false)
  assert.equal(sameAmount("1e3", "1000"), null, "unreadable: not reported as a mismatch")
  assert.equal(sameAmount(null, "1"), null)
})

// ─── (g) a step the ladder does not know ──────────────────────────────────────

test("(g) an unknown code goes under the stage its `stage` field names, as a detail line", () => {
  const q = fixture("quote-deluxe-2a1c")
  const night = q.nights![0].date
  const extra = (p: Partial<ExplainStep>): ExplainStep => ({ stage: "board", text: "new", code: "BOARD_NEW", night, before: null, after: null, currency: null, rule: null, overridden: [], message: "new", params: {}, ...p })
  q.explanation = [
    ...q.explanation!,
    extra({ code: "BOARD_EXTRA_FEE", text: "board BB fee" }),
    extra({ code: "PLAN_NOTE", stage: "rate_plan", text: "rate plan note" }),
    extra({ code: "TAX_NOTE", stage: "tax", night: null, text: "tourist tax note" }),
    extra({ code: "CONTRACT_NOTE", stage: "contract", night: null, text: "not a stage" }),
  ]
  const L = explainLadder(q)
  const b = L.nights[0]
  assert.deepEqual(codes(of(b, "board")), ["BOARD_BASE", "BOARD_EXTRA_FEE"])
  const plan = of(b, "rate_plan")
  assert.deepEqual([...ba(plan), ...codes(plan)], [null, null, "PLAN_NOTE"], "an optional stage shown for its line, without amounts")
  assert.deepEqual(ids(b.stages).slice(5, 8), ["board", "rate_plan", "night_cost"])
  assert.deepEqual(codes(L.stay.find((s) => s.id === "tax")!), ["TAX_NOTE"])
  assert.ok(!JSON.stringify(L).includes("CONTRACT_NOTE"), "a stage the ladder has not stays in the Why list only")
  assert.deepEqual(L.chainBreaks, [])
  assert.deepEqual(
    L.nights.map((x) => [x.first, x.last]),
    [
      [1, 1],
      [2, 3],
    ],
  )
})

test("stay-level promotions: applied offers before → after, rejected ones as lines, the chain inside", () => {
  const q = fixture("quote-deluxe-2a1c")
  const promo = (p: Partial<ExplainStep>): ExplainStep => ({ stage: "promotion", text: "", code: "PROMO_APPLIED", night: null, before: null, after: null, currency: "EUR", rule: null, overridden: [], ...p })
  q.explanation = [
    ...q.explanation!.filter((s) => s.code !== "TOTAL"),
    promo({ before: "874.800000", after: "787.320000", text: "Early 10%" }),
    promo({ before: "787.320000", after: "747.954000", text: "Long stay 5%" }),
    promo({ stage: "cost_offer", before: "810.000000", after: "770.000000", text: "Net offer" }),
    ...q.explanation!.filter((s) => s.code === "TOTAL"),
  ]
  const L = explainLadder(q)
  assert.deepEqual(ids(L.stay), ["cost_offers", "promotion", "tax", "final"])
  const p = L.stay[1]
  assert.deepEqual(ba(p), ["874.800000", "747.954000"])
  assert.deepEqual(codes(p), ["PROMO_REJECTED", "PROMO_APPLIED", "PROMO_APPLIED"])
  assert.deepEqual(ba(L.stay[0]), ["810.000000", "770.000000"])
  assert.ok(L.nights[0].stages.some((s) => s.id === "cost_offers"), "cost offers show per night when the stay has any")
  assert.deepEqual(L.chainBreaks, [])
  const broken = fixture("quote-deluxe-2a1c")
  broken.explanation = [...broken.explanation!, promo({ before: "874.8", after: "800" }), promo({ before: "790", after: "700" })]
  assert.deepEqual(
    explainLadder(broken).chainBreaks.map((x) => [x.scope, x.stage, x.value, x.previousAfter]),
    [["stay", "promotion", "790", "800"]],
  )
})

test("an unsellable quote has no ladder", () => {
  const L = explainLadder({ sellable: false, reasons: [{ code: "NO_ROOM_PRICE", message: "no price" }], explanation: [] })
  assert.deepEqual([L.nights, L.stay, L.chainBreaks], [[], [], []])
})

// ─── localisation helpers ─────────────────────────────────────────────────────

test("describe_op strings and child labels are split for the localised sentences", () => {
  assert.deepEqual(parseOpText("× 1.35"), { kind: "mul", value: "1.35" })
  assert.deepEqual(parseOpText("50% of"), { kind: "pct_of", value: "50" })
  assert.deepEqual(parseOpText("+10%"), { kind: "pct", value: "+10" })
  assert.deepEqual(parseOpText("-7.5%"), { kind: "pct", value: "-7.5" })
  assert.deepEqual(parseOpText("= 245.00"), { kind: "abs", value: "245.00" })
  assert.deepEqual(parseOpText("+ 10.00"), { kind: "add", value: "10.00" })
  assert.deepEqual(parseOpText("− 5.00"), { kind: "sub", value: "5.00" })
  assert.deepEqual(parseOpText("inherit"), { kind: "inherit", value: "" })
  assert.equal(parseOpText("times 2"), null)
  assert.deepEqual(parseChildLabel("Child 1 (8y, Child 7–11.99)"), { n: 1, years: 8, months: 0, band: "Child 7–11.99" })
  assert.deepEqual(parseChildLabel("Child 2 (11y11m, CHB)"), { n: 2, years: 11, months: 11, band: "CHB" })
  assert.equal(parseChildLabel("Adult 1"), null)
  const known = new Set(["INF", "CHB"])
  assert.deepEqual(bareBandCodes("CHILD_SLOT", { label: "Child 2 (11y11m, CHB)" }, known), ["CHB"])
  assert.deepEqual(bareBandCodes("CHILD_SLOT", { label: "Child 1 (8y, Child 7–11.99)" }, known), [])
  assert.deepEqual(bareBandCodes("ADULT_SLOT", { label: "CHB" }, known), [])
})

// ─── the Price test's prefill, children and Show in grid ──────────────────────

const PERIODS = [
  { code: "P1", start: "2027-04-01", end: "2027-04-30" },
  { code: "P2", start: "2027-05-01", end: "2027-05-31" },
  { code: "P3", start: "2027-06-01", end: "2027-06-30" },
]

test("prefill: the active row and period's start for 3 nights, clamped to the stay window", () => {
  const base = { rooms: ["STD", "SUP", "DLX"], baseRoom: "STD", periods: PERIODS, today: "2026-09-25" }
  assert.deepEqual(prefillOf({ ...base, active: { room: "DLX", period: "P2" } }), { room: "DLX", period: "P2", checkIn: "2027-05-01", checkOut: "2027-05-04" })
  assert.deepEqual(prefillOf({ ...base, active: { room: "SUP", period: "" } }), { room: "SUP", period: "P1", checkIn: "2027-04-01", checkOut: "2027-04-04" }, "All periods: the first period")
  assert.deepEqual(prefillOf({ ...base, active: null }), { room: "STD", period: "P1", checkIn: "2027-04-01", checkOut: "2027-04-04" }, "no active cell: the base room")
  assert.deepEqual(prefillOf({ ...base, active: { room: "GONE", period: "P9" } }).room, "STD")
  assert.equal(prefillOf({ ...base, active: { room: "STD", period: "P1" }, stayFrom: "2027-04-10" }).checkIn, "2027-04-10")
  assert.deepEqual(prefillOf({ ...base, active: { room: "STD", period: "P3" }, stayTo: "2027-06-01" }).checkIn, "2027-05-30", "3 nights end on the last stay day")
  assert.equal(prefillOf({ ...base, today: "2027-05-15", active: null }).period, "P2", "the first period that has not ended")
  assert.deepEqual(prefillOf({ ...base, periods: [], stayFrom: null }), { room: "STD", period: null, checkIn: "2026-10-09", checkOut: "2026-10-12" })
  assert.equal(addDaysIso("2027-02-27", 3), "2027-03-02")
  assert.equal(addDaysIso("2028-02-28", 1), "2028-02-29")
})

test("children: whole years by default, exactly in months or by date of birth", () => {
  assert.equal(childPayload({ mode: "years", value: "8" }), 8)
  assert.equal(childPayload({ mode: "years", value: "18" }), null)
  assert.equal(childPayload({ mode: "years", value: "7.5" }), null)
  assert.deepEqual(childPayload({ mode: "months", value: "143" }), { age_months: 143 })
  assert.deepEqual(childPayload({ mode: "months", value: "0" }), { age_months: 0 })
  assert.equal(childPayload({ mode: "months", value: "216" }), null)
  assert.deepEqual(childPayload({ mode: "dob", value: "2019-03-02" }), { dob: "2019-03-02" })
  assert.equal(childPayload({ mode: "dob", value: "02.03.2019" }), null)
  assert.deepEqual(withChildMode({ mode: "years", value: "11" }, "months"), { mode: "months", value: "132" })
  assert.deepEqual(withChildMode({ mode: "months", value: "143" }, "years"), { mode: "years", value: "11" })
  assert.deepEqual(withChildMode({ mode: "years", value: "17" }, "months"), { mode: "months", value: "204" })
  assert.deepEqual(withChildMode({ mode: "years", value: "8" }, "dob"), { mode: "dob", value: "" })
  assert.deepEqual(withChildMode({ mode: "dob", value: "2019-03-02" }, "years"), { mode: "years", value: "" })
})

let seq = 0
const row = (f: Record<string, string | number | null>): Row => ({ _key: `k${++seq}`, ...f })
const tables = (): Pick<Tables, "period_rates" | "occupancy_rules" | "boards"> => ({
  period_rates: [row({ room_type: "STD", period_code: "P2", op: "ABSOLUTE", value: "80", _name: "abc123" }), row({ room_type: "SUP", period_code: "P4", op: "MULTIPLY", value: "1.2" })],
  occupancy_rules: [row({ target: "CHILD", position: 1, age_band: "CHB", combination: "2+2" })],
  boards: [row({ board: "HB", room_type: "", period_code: "P2" })],
})

test("Show in grid: a rule id names a row of the draft (~key unsaved, the row's name saved)", () => {
  const t = tables()
  const [std, sup] = t.period_rates
  assert.deepEqual(showTargetOf(t, `~${sup._key}`), { kind: "matrix", room: "SUP", period: "P4" })
  assert.deepEqual(showTargetOf(t, "abc123"), { kind: "matrix", room: "STD", period: "P2" })
  assert.equal(ruleRowOf(t, "abc123")?.row, std)
  assert.deepEqual(showTargetOf(t, `~${t.occupancy_rules[0]._key}`), { kind: "occupancy", key: t.occupancy_rules[0]._key })
  assert.deepEqual(showTargetOf(t, `~${t.boards[0]._key}`), { kind: "board", board: "HB", room: "", period: "P2" })
  assert.deepEqual(showTargetOf(t, "~boards-1"), { kind: "board", board: "HB", room: "", period: "P2" }, "a row sent without a key")
  assert.equal(showTargetOf(t, "~boards-9"), null)
  assert.equal(showTargetOf(t, "GLOBAL:ADULT"), null, "the engine's default is not a row")
  assert.equal(showTargetOf(t, "MKP-00001"), null)
  assert.equal(showTargetOf(t, "~gone"), null)
  assert.equal(showTargetOf(t, ""), null)
  assert.equal(showTargetOf(t, null), null)
})

test("an English step sentence names rooms, not room type ids (S16 review)", () => {
  const names: Record<string, string> = { "Aurora Beach Resort-VIL": "Garden Villa", "Aurora Beach Resort-STD": "Standard Sea View", "H-STD2": "Superior" }
  const roomName = (rt: string) => names[rt] ?? rt
  assert.equal(
    withRoomNames("Aurora Beach Resort-VIL = Aurora Beach Resort-STD × 1.35 → 108.00", { room: "Aurora Beach Resort-VIL", base: "Aurora Beach Resort-STD", op: "× 1.35" }, roomName),
    "Garden Villa = Standard Sea View × 1.35 → 108.00",
  )
  assert.equal(withRoomNames("Aurora Beach Resort-STD in P2: price 80.00", { room: "Aurora Beach Resort-STD", period: "P2" }, roomName), "Standard Sea View in P2: price 80.00")
  // an id inside a longer one is left alone; an unknown room and a step without rooms are unchanged
  assert.equal(withRoomNames("H-STD2 = H-STD × 1.10", { room: "H-STD2", base: "H-STD" }, roomName), "Superior = H-STD × 1.10")
  assert.equal(withRoomNames("period P2 (May)", { period: "P2" }, roomName), "period P2 (May)")
  assert.equal(withRoomNames("X in P1: price 1.00", null, roomName), "X in P1: price 1.00")
})
