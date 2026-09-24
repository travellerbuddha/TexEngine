// Unit tests for the Pricing Workspace room matrix, board and period projections
// (PRICING_WORKSPACE_UX.md §3.3, §3.4.5, §3.9, §3.12, D6, D7, D11, §5.1).
// Run with `npm run test:unit` (node --test).
import { test } from "node:test"
import assert from "node:assert/strict"
import { parseShorthand, type ShContext } from "../../src/tex/screens/rates/lib/shorthand.ts"
import {
  applyAdjustResults,
  applyBoardEntry,
  applyRoomEntry,
  boardModel,
  cellState,
  defaultBase,
  matrixModel,
  removeBoard,
  removeRoom,
  setBaseRoom,
  setDerivation,
  upsertRoomRule,
} from "../../src/tex/screens/rates/workspace/model.ts"
import {
  addPeriod,
  copyPreviousPeriod,
  deletePeriod,
  duplicatePeriod,
  isoAddDays,
  movePeriod,
  nextPeriodCode,
  periodDependents,
  renamePeriod,
} from "../../src/tex/screens/rates/workspace/periods.ts"
import type { Row } from "../../src/tex/screens/rates/lib/types.ts"
import type { Tables } from "../../src/tex/screens/rates/lib/tables.ts"

let seq = 0
const r = (fields: Record<string, string | number | null>): Row => ({ _key: `t${++seq}`, ...fields })
const rate = (room: string, period: string, op: string, value: string, base = "") => r({ room_type: room, period_code: period, op, value, base_room_type: base })

function tablesOf(p: Partial<Tables>): Tables {
  return { rooms: [], periods: [], period_rates: [], age_bands: [], occupancy_rules: [], boards: [], rate_plans: [], offers: [], ...p }
}

const sh = (text: string, ctx: ShContext = "room") => parseShorthand(text, ctx)

/** The owner's example (§3.1): Standard is the base room with entered prices per period;
 * Superior = Standard ×1.15 (P4 ×1.20); Deluxe = Standard ×1.35 (P3–P4 ×1.40). */
function owner(): Tables {
  return tablesOf({
    rooms: [r({ room_type: "STD", is_base: 1 }), r({ room_type: "SUP", is_base: 0 }), r({ room_type: "DLX", is_base: 0 })],
    periods: [
      r({ period_code: "P1", period_name: "Apr", start_date: "2027-04-01", end_date: "2027-04-30" }),
      r({ period_code: "P2", period_name: "May", start_date: "2027-05-01", end_date: "2027-05-31" }),
      r({ period_code: "P3", period_name: "Jun", start_date: "2027-06-01", end_date: "2027-06-30" }),
      r({ period_code: "P4", period_name: "Jul", start_date: "2027-07-01", end_date: "2027-07-31" }),
    ],
    period_rates: [
      rate("STD", "P1", "ABSOLUTE", "70"),
      rate("STD", "P2", "ABSOLUTE", "80"),
      rate("STD", "P3", "ABSOLUTE", "100"),
      rate("STD", "P4", "ABSOLUTE", "130"),
      rate("SUP", "", "MULTIPLY", "1.15", "STD"),
      rate("SUP", "P4", "MULTIPLY", "1.2", "STD"),
      rate("DLX", "", "MULTIPLY", "1.35", "STD"),
      rate("DLX", "P3", "MULTIPLY", "1.4", "STD"),
      rate("DLX", "P4", "MULTIPLY", "1.40", "STD"),
    ],
    occupancy_rules: [
      r({ target: "ADULT", position: 3, age_band: "", combination: "", room_type: "", period_code: "", op: "MULTIPLY", value: "0.7", is_override: 0, note: "" }),
      r({ target: "ADULT", position: 3, age_band: "", combination: "", room_type: "", period_code: "P4", op: "MULTIPLY", value: "0.8", is_override: 0, note: "" }),
      r({ target: "CHILD", position: 0, age_band: "CHB", combination: "", room_type: "SUP", period_code: "", op: "MULTIPLY", value: "0.5", is_override: 0, note: "" }),
    ],
    boards: [
      r({ board: "UAI", is_base: 1, op: "ADD", adult_amount: "", child_percent: "50", infant_free: 1, room_type: "", period_code: "", label: "" }),
      r({ board: "AI", is_base: 0, op: "ADJUST_PERCENT", adult_amount: "-5", child_percent: "50", infant_free: 1, room_type: "", period_code: "", label: "" }),
      r({ board: "HB", is_base: 0, op: "ADD", adult_amount: "-20", child_percent: "30", infant_free: 1, room_type: "", period_code: "", label: "" }),
      r({ board: "HB", is_base: 0, op: "ADD", adult_amount: "-25", child_percent: "30", infant_free: 1, room_type: "", period_code: "P2", label: "" }),
      r({ board: "HB", is_base: 0, op: "ADD", adult_amount: "-10", child_percent: "40", infant_free: 0, room_type: "DLX", period_code: "", label: "" }),
    ],
  })
}

const ratesOf = (t: Tables, room: string) =>
  t.period_rates.filter((x) => x.room_type === room).map((x) => `${x.period_code || "*"}:${x.op}:${x.value}:${x.base_room_type || "-"}`)

function tablesAfter(res: ReturnType<typeof applyRoomEntry>): Tables {
  assert.ok("tables" in res, `expected tables, got ${JSON.stringify(res)}`)
  return res.tables
}

// ─── matrix projection and cell states ──────────────────────────────────

test("the owner's example: roles, default bases, row kinds and period columns", () => {
  const m = matrixModel(owner(), "PERSON")
  assert.deepEqual(
    m.rooms.map((x) => [x.room_type, x.role, x.defaultBase]),
    [
      ["STD", "base", "STD"],
      ["SUP", "derived", "STD"],
      ["DLX", "derived", "STD"],
    ],
  )
  assert.deepEqual(
    m.rooms.map((x) => x.rows.map((row) => row.kind)),
    [["base"], ["formula", "resolved"], ["formula", "resolved"]],
  )
  assert.equal(m.rooms[0].rows[0].label, "base_person")
  assert.equal(matrixModel(owner(), "ROOM").rooms[0].rows[0].label, "base_room")
  assert.equal(m.rooms[1].defaultRule?.value, "1.15")
  assert.deepEqual(
    m.periods.map((p) => [p.code, p.start, p.end]),
    [
      ["P1", "2027-04-01", "2027-04-30"],
      ["P2", "2027-05-01", "2027-05-31"],
      ["P3", "2027-06-01", "2027-06-30"],
      ["P4", "2027-07-01", "2027-07-31"],
    ],
  )
})

test("the owner's example: cell states", () => {
  const t = owner()
  assert.equal(cellState(t, "STD", "").state, "empty")
  assert.equal(cellState(t, "STD", "P1").state, "manual")
  assert.equal(cellState(t, "SUP", "").state, "formula-default")
  for (const p of ["P1", "P2", "P3"]) {
    const c = cellState(t, "SUP", p)
    assert.equal(c.state, "inherited", p)
    assert.equal(c.rule, null)
    assert.equal(c.defaultRule?.value, "1.15")
  }
  const p4 = cellState(t, "SUP", "P4")
  assert.equal(p4.state, "period-override")
  assert.equal(p4.rule?.value, "1.2")
  assert.equal(p4.defaultRule?.value, "1.15")
  assert.equal(cellState(t, "DLX", "P3").state, "period-override")
  assert.equal(cellState(t, "DLX", "P1").state, "inherited")
})

test("cell states: manual room, fixed override, inherit rule and a missing default", () => {
  const t = tablesOf({
    rooms: [r({ room_type: "STD", is_base: 1 }), r({ room_type: "FAM", is_base: 0 }), r({ room_type: "SUP", is_base: 0 })],
    periods: [r({ period_code: "P1" }), r({ period_code: "P2" })],
    period_rates: [
      rate("FAM", "", "ABSOLUTE", "200"),
      rate("SUP", "", "MULTIPLY", "1.15", "STD"),
      rate("SUP", "P1", "ABSOLUTE", "245"),
      rate("SUP", "P2", "INHERIT", ""),
    ],
  })
  const m = matrixModel(t, "PERSON")
  assert.deepEqual(
    m.rooms.map((x) => [x.room_type, x.role]),
    [
      ["STD", "base"],
      ["FAM", "manual"],
      ["SUP", "derived"],
    ],
  )
  assert.deepEqual(
    m.rooms[1].rows.map((row) => row.kind),
    ["manual", "resolved"],
    "a manual room with an All-periods price shows a resolved row",
  )
  assert.equal(cellState(t, "FAM", "").state, "manual")
  assert.equal(cellState(t, "FAM", "P1").state, "inherited")
  assert.equal(cellState(t, "SUP", "P1").state, "fixed-override")
  assert.equal(cellState(t, "SUP", "P2").state, "inherit-rule")
  assert.equal(cellState(t, "STD", "P1").state, "empty")
})

test("defaultBase: the All-periods rule's base, else the base room, else null", () => {
  const t = owner()
  assert.equal(defaultBase(t, "SUP"), "STD")
  const chained = { ...t, period_rates: [...t.period_rates.filter((x) => x.room_type !== "DLX"), rate("DLX", "", "MULTIPLY", "1.1", "SUP")] }
  assert.equal(defaultBase(chained, "DLX"), "SUP")
  const noBase = tablesOf({ rooms: [r({ room_type: "STD", is_base: 0 }), r({ room_type: "SUP", is_base: 0 })] })
  assert.equal(defaultBase(noBase, "SUP"), null)
})

// ─── entries (§3.3.2, D11) ──────────────────────────────────────────────

test("x1.15 typed into a period cell equal to the default removes the period row", () => {
  const t = owner()
  const out = tablesAfter(applyRoomEntry(t, "SUP", "P4", sh("x1.15")))
  assert.deepEqual(ratesOf(out, "SUP"), ["*:MULTIPLY:1.15:STD"])
  assert.equal(cellState(out, "SUP", "P4").state, "inherited")
  // the comparison is on canonical strings: 1.150 is 1.15
  const again = tablesAfter(applyRoomEntry(t, "SUP", "P4", sh("x1,150")))
  assert.deepEqual(ratesOf(again, "SUP"), ["*:MULTIPLY:1.15:STD"])
  // an entry equal to the default in a period without its own row adds nothing
  const noop = applyRoomEntry(t, "SUP", "P2", sh("x1.15"))
  assert.ok("tables" in noop)
  assert.equal(noop.tables.period_rates, t.period_rates, "nothing changed: the same array comes back")
})

test("=245 on a derived room gives a fixed override with no base room", () => {
  const out = tablesAfter(applyRoomEntry(owner(), "SUP", "P2", sh("=245")))
  const row = out.period_rates.find((x) => x.room_type === "SUP" && x.period_code === "P2")
  assert.deepEqual([row?.op, row?.value, row?.base_room_type], ["ABSOLUTE", "245", ""])
  assert.equal(cellState(out, "SUP", "P2").state, "fixed-override")
})

test("x1.20 typed into that fixed-override cell stores MULTIPLY 1.2 from STD", () => {
  const fixed = tablesAfter(applyRoomEntry(owner(), "SUP", "P2", sh("=245")))
  const key = fixed.period_rates.find((x) => x.room_type === "SUP" && x.period_code === "P2")?._key
  const out = tablesAfter(applyRoomEntry(fixed, "SUP", "P2", sh("x1.20")))
  const row = out.period_rates.find((x) => x.room_type === "SUP" && x.period_code === "P2")
  assert.deepEqual([row?.op, row?.value, row?.base_room_type], ["MULTIPLY", "1.2", "STD"])
  assert.equal(row?._key, key, "the row keeps its key (selection and anchoring survive)")
  assert.equal(cellState(out, "SUP", "P2").state, "period-override")
})

test("a manual non-base room receiving x1.35 in All periods becomes a formula from the base room", () => {
  const t = tablesOf({
    rooms: [r({ room_type: "STD", is_base: 1 }), r({ room_type: "DLX", is_base: 0 })],
    periods: [r({ period_code: "P1" })],
    period_rates: [rate("STD", "", "ABSOLUTE", "70"), rate("DLX", "", "ABSOLUTE", "120"), rate("DLX", "P1", "ABSOLUTE", "130")],
  })
  assert.equal(matrixModel(t, "PERSON").rooms[1].role, "manual")
  const out = tablesAfter(applyRoomEntry(t, "DLX", "", sh("x1.35")))
  assert.deepEqual(ratesOf(out, "DLX"), ["*:MULTIPLY:1.35:STD", "P1:ABSOLUTE:130:-"])
  assert.equal(matrixModel(out, "PERSON").rooms[1].role, "derived")
  assert.equal(cellState(out, "DLX", "P1").state, "fixed-override")
})

test("every relative op on a non-base room is stored as a formula, whatever the cell held", () => {
  const t = tablesAfter(applyRoomEntry(owner(), "SUP", "P3", sh("=245")))
  const cases: [string, string, string][] = [
    ["50%", "PERCENT_OF", "50"],
    ["+10%", "ADJUST_PERCENT", "10"],
    ["-10%", "ADJUST_PERCENT", "-10"],
    ["+25", "ADD", "25"],
    ["-25", "SUBTRACT", "25"],
  ]
  for (const [text, op, value] of cases) {
    const out = tablesAfter(applyRoomEntry(t, "SUP", "P3", sh(text)))
    const row = out.period_rates.find((x) => x.room_type === "SUP" && x.period_code === "P3")
    assert.deepEqual([row?.op, row?.value, row?.base_room_type], [op, value, "STD"], text)
  }
  // an INHERIT row is replaced too
  const inh = { ...t, period_rates: [...t.period_rates.filter((x) => !(x.room_type === "SUP" && x.period_code === "P3")), rate("SUP", "P3", "INHERIT", "")] }
  const out = tablesAfter(applyRoomEntry(inh, "SUP", "P3", sh("x1.3")))
  assert.deepEqual(ratesOf(out, "SUP").filter((x) => x.startsWith("P3")), ["P3:MULTIPLY:1.3:STD"])
})

test("a formula follows the room's default base (chained derivation)", () => {
  const t = owner()
  const chained = tablesAfter(applyRoomEntry({ ...t, period_rates: t.period_rates.filter((x) => x.room_type !== "DLX") }, "DLX", "", sh("x1.35")))
  assert.deepEqual(ratesOf(chained, "DLX"), ["*:MULTIPLY:1.35:STD"])
  const viaSup = setDerivation(chained, "DLX", "SUP", { allPeriods: true }).tables
  const out = tablesAfter(applyRoomEntry(viaSup, "DLX", "P2", sh("x1.2")))
  assert.deepEqual(ratesOf(out, "DLX"), ["*:MULTIPLY:1.35:SUP", "P2:MULTIPLY:1.2:SUP"])
})

test("a relative op on the base room asks the server to adjust the entered price once (O4)", () => {
  const t = owner()
  const res = applyRoomEntry(t, "STD", "P1", sh("+10%"))
  assert.deepEqual(res, { needsServer: { room: "STD", targetPeriod: "P1", op: "ADJUST_PERCENT", value: "10", current: "70" } })
  // a cell that inherits an All-periods price adjusts that price into its own period row
  const withDefault = { ...t, period_rates: [rate("STD", "", "ABSOLUTE", "70"), ...t.period_rates.filter((x) => !(x.room_type === "STD" && x.period_code === "P1"))] }
  assert.deepEqual(applyRoomEntry(withDefault, "STD", "P1", sh("x1.1")), {
    needsServer: { room: "STD", targetPeriod: "P1", op: "MULTIPLY", value: "1.1", current: "70" },
  })
  // the server's result is stored as ABSOLUTE in the target cell
  const adjusted = applyAdjustResults(t, [{ room: "STD", targetPeriod: "P1" }], ["77.00"])
  assert.deepEqual(ratesOf(adjusted, "STD")[0], "P1:ABSOLUTE:77.00:-")
  // absolute entries on the base room are stored directly
  const abs = tablesAfter(applyRoomEntry(t, "STD", "P1", sh("75")))
  assert.deepEqual(ratesOf(abs, "STD")[0], "P1:ABSOLUTE:75:-")
})

test("a relative op on the base room without an entered price is refused (BASE_NO_PRICE)", () => {
  const t = owner()
  assert.deepEqual(applyRoomEntry(t, "STD", "", sh("x1.1")), { error: "BASE_NO_PRICE" })
  const noP1 = { ...t, period_rates: t.period_rates.filter((x) => !(x.room_type === "STD" && x.period_code === "P1")) }
  assert.deepEqual(applyRoomEntry(noP1, "STD", "P1", sh("-5")), { error: "BASE_NO_PRICE" })
})

test("with no base room a relative op on SUP is refused (NO_BASE_ROOM)", () => {
  const t = tablesOf({
    rooms: [r({ room_type: "STD", is_base: 0 }), r({ room_type: "SUP", is_base: 0 })],
    periods: [r({ period_code: "P1" })],
    period_rates: [rate("STD", "", "ABSOLUTE", "70")],
  })
  assert.deepEqual(applyRoomEntry(t, "SUP", "P1", sh("x1.15")), { error: "NO_BASE_ROOM" })
  assert.deepEqual(applyRoomEntry(t, "SUP", "", sh("+10%")), { error: "NO_BASE_ROOM" })
  // an absolute price needs no base
  assert.ok("tables" in applyRoomEntry(t, "SUP", "P1", sh("90")))
})

test("clear on All periods removes the generic row; clear on a period falls back to the default", () => {
  const t = owner()
  const noDefault = tablesAfter(applyRoomEntry(t, "SUP", "", sh("")))
  assert.deepEqual(ratesOf(noDefault, "SUP"), ["P4:MULTIPLY:1.2:STD"])
  assert.equal(cellState(noDefault, "SUP", "P1").state, "empty")
  assert.equal(cellState(noDefault, "SUP", "P4").state, "period-override")
  const back = tablesAfter(applyRoomEntry(t, "SUP", "P4", sh("  ")))
  assert.deepEqual(ratesOf(back, "SUP"), ["*:MULTIPLY:1.15:STD"])
  assert.equal(cellState(back, "SUP", "P4").state, "inherited")
  // clearing an empty cell changes nothing
  const noop = applyRoomEntry(t, "STD", "", sh(""))
  assert.ok("tables" in noop)
  assert.equal(noop.tables, t)
})

test("an entry replaces duplicate rows of the same cell with one row", () => {
  const t = owner()
  const dup = { ...t, period_rates: [...t.period_rates, rate("SUP", "P4", "ABSOLUTE", "300")] }
  const out = tablesAfter(applyRoomEntry(dup, "SUP", "P4", sh("x1.25")))
  assert.deepEqual(ratesOf(out, "SUP"), ["*:MULTIPLY:1.15:STD", "P4:MULTIPLY:1.25:STD"])
})

test("parser errors and the board-only keyword are passed back as errors", () => {
  assert.deepEqual(applyRoomEntry(owner(), "SUP", "P1", sh("abc")), { error: "SYNTAX" })
  assert.deepEqual(applyRoomEntry(owner(), "SUP", "P1", parseShorthand("1.500", "room")), { error: "AMBIGUOUS" })
  assert.deepEqual(applyRoomEntry(owner(), "SUP", "P1", { ok: true, kind: "base" }), { error: "SYNTAX" })
})

test("upsertRoomRule stores the chosen op as chosen (advanced popover)", () => {
  const out = upsertRoomRule(owner(), "SUP", "P2", { op: "INHERIT", value: "", base_room_type: "" })
  assert.deepEqual(ratesOf(out, "SUP"), ["*:MULTIPLY:1.15:STD", "P4:MULTIPLY:1.2:STD", "P2:INHERIT::-"])
  assert.equal(cellState(out, "SUP", "P2").state, "inherit-rule")
})

test("entries never change the input tables", () => {
  const t = owner()
  const snap = JSON.stringify(t)
  applyRoomEntry(t, "SUP", "P2", sh("=245"))
  applyRoomEntry(t, "SUP", "", sh(""))
  setBaseRoom(t, "DLX", { repoint: true })
  removeRoom(t, "SUP")
  assert.equal(JSON.stringify(t), snap)
})

// ─── rooms (§3.3.5) ─────────────────────────────────────────────────────

test("setBaseRoom is exclusive and re-points formulas that used the previous base", () => {
  const t = owner()
  const { tables: out, counts } = setBaseRoom(t, "DLX", { repoint: true })
  assert.deepEqual(
    out.rooms.map((x) => [x.room_type, x.is_base]),
    [
      ["STD", 0],
      ["SUP", 0],
      ["DLX", 1],
    ],
  )
  assert.deepEqual(ratesOf(out, "SUP"), ["*:MULTIPLY:1.15:DLX", "P4:MULTIPLY:1.2:DLX"])
  assert.deepEqual(ratesOf(out, "DLX"), ["*:MULTIPLY:1.35:STD", "P3:MULTIPLY:1.4:STD", "P4:MULTIPLY:1.40:STD"], "the new base never derives from itself")
  assert.deepEqual(ratesOf(out, "STD"), ratesOf(t, "STD"), "the previous base keeps its entered prices")
  assert.deepEqual(counts, { repointed: 2 })
  const kept = setBaseRoom(t, "DLX", { repoint: false })
  assert.deepEqual(ratesOf(kept.tables, "SUP"), ratesOf(t, "SUP"))
  assert.deepEqual(kept.counts, { repointed: 0 })
  assert.equal(matrixModel(kept.tables, "PERSON").rooms[0].role, "manual", "the previous base becomes a manual room")
})

test("setBaseRoom on the base room changes nothing; a second is_base flag is cleared", () => {
  const t = owner()
  assert.equal(setBaseRoom(t, "STD", { repoint: true }).tables, t)
  const two = { ...t, rooms: t.rooms.map((x) => (x.room_type === "SUP" ? { ...x, is_base: 1 } : x)) }
  const out = setBaseRoom(two, "STD", { repoint: false }).tables
  assert.deepEqual(
    out.rooms.map((x) => x.is_base),
    [1, 0, 0],
  )
})

test("setDerivation changes the base of the All-periods formula and, optionally, the period formulas", () => {
  const t = owner()
  const generic = setDerivation(t, "DLX", "SUP", { allPeriods: false })
  assert.deepEqual(ratesOf(generic.tables, "DLX"), ["*:MULTIPLY:1.35:SUP", "P3:MULTIPLY:1.4:STD", "P4:MULTIPLY:1.40:STD"])
  assert.deepEqual(generic.counts, { changed: 1 })
  const all = setDerivation(t, "DLX", "SUP", { allPeriods: true })
  assert.deepEqual(ratesOf(all.tables, "DLX"), ["*:MULTIPLY:1.35:SUP", "P3:MULTIPLY:1.4:SUP", "P4:MULTIPLY:1.40:SUP"])
  assert.deepEqual(all.counts, { changed: 3 })
  assert.deepEqual(setDerivation(t, "DLX", "DLX", { allPeriods: true }).counts, { changed: 0 }, "never derives from itself")
})

test("removeRoom removes the room and its rows and counts them and the formulas deriving from it", () => {
  const t = owner()
  const sup = removeRoom(t, "SUP")
  assert.deepEqual(sup.counts, { prices: 2, occupancy: 1, boards: 0, derivedFrom: 0 })
  assert.deepEqual(
    sup.tables.rooms.map((x) => x.room_type),
    ["STD", "DLX"],
  )
  assert.deepEqual(ratesOf(sup.tables, "SUP"), [])
  assert.equal(sup.tables.occupancy_rules.length, 2)
  const dlx = removeRoom(t, "DLX")
  assert.deepEqual(dlx.counts, { prices: 3, occupancy: 0, boards: 1, derivedFrom: 0 })
  const std = removeRoom(t, "STD")
  assert.deepEqual(std.counts, { prices: 4, occupancy: 0, boards: 0, derivedFrom: 5 })
  assert.deepEqual(ratesOf(std.tables, "SUP"), ratesOf(t, "SUP"), "dependent formulas are counted, not removed")
})

// ─── boards (§3.12, O1–O3) ──────────────────────────────────────────────

const HB = { board: "HB", room_type: "" }
const boardRows = (t: Tables, board: string) =>
  t.boards.filter((b) => b.board === board).map((b) => `${b.room_type || "*"}/${b.period_code || "*"}:${b.is_base ? "BASE" : `${b.op}:${b.adult_amount}`}`)

function boardsAfter(res: ReturnType<typeof applyBoardEntry>): Tables {
  assert.ok("tables" in res, `expected tables, got ${JSON.stringify(res)}`)
  return res.tables
}

test("board entries follow the owner's table: 20 ABSOLUTE, +20 ADD, -20 ADD -20, n% ADJUST_PERCENT", () => {
  const t = owner()
  assert.deepEqual(boardRows(boardsAfter(applyBoardEntry(t, HB, "", sh("20", "board"))), "HB"), ["*/*:ABSOLUTE:20", "*/P2:ADD:-25", "DLX/*:ADD:-10"])
  assert.deepEqual(boardRows(boardsAfter(applyBoardEntry(t, HB, "", sh("=20", "board"))), "HB")[0], "*/*:ABSOLUTE:20")
  assert.deepEqual(boardRows(boardsAfter(applyBoardEntry(t, HB, "", sh("+20", "board"))), "HB")[0], "*/*:ADD:20")
  assert.deepEqual(boardRows(boardsAfter(applyBoardEntry(t, HB, "", sh("-20", "board"))), "HB")[0], "*/*:ADD:-20")
  const ai = { board: "AI", room_type: "" }
  assert.deepEqual(boardRows(boardsAfter(applyBoardEntry(t, ai, "", sh("-5%", "board"))), "AI"), ["*/*:ADJUST_PERCENT:-5"])
  assert.deepEqual(boardRows(boardsAfter(applyBoardEntry(t, ai, "", sh("5%", "board"))), "AI"), ["*/*:ADJUST_PERCENT:5"])
  assert.deepEqual(boardRows(boardsAfter(applyBoardEntry(t, ai, "", sh("+5%", "board"))), "AI"), ["*/*:ADJUST_PERCENT:5"])
})

test("board 'base' sets is_base on that board exclusively", () => {
  const t = owner()
  const out = boardsAfter(applyBoardEntry(t, { board: "AI", room_type: "" }, "", sh("base", "board")))
  assert.deepEqual(
    out.boards.map((b) => `${b.board}/${b.room_type || "*"}/${b.period_code || "*"}:${b.is_base}`),
    ["UAI/*/*:0", "AI/*/*:1", "HB/*/*:0", "HB/*/P2:0", "HB/DLX/*:0"],
  )
  // a board with no row yet gets one
  const bb = boardsAfter(applyBoardEntry(t, { board: "BB", room_type: "" }, "", sh("BASE", "board")))
  assert.deepEqual(boardRows(bb, "BB"), ["*/*:BASE"])
  assert.deepEqual(
    bb.boards.filter((b) => b.is_base).map((b) => b.board),
    ["BB"],
  )
  // a rule typed into the base board makes it an ordinary board again
  const priced = boardsAfter(applyBoardEntry(t, { board: "UAI", room_type: "" }, "", sh("+30", "board")))
  assert.deepEqual(boardRows(priced, "UAI"), ["*/*:ADD:30"])
})

test("period- and room-scoped board cells: own rows, inherited child terms, clear", () => {
  const t = owner()
  const p4 = boardsAfter(applyBoardEntry(t, HB, "P4", sh("-30", "board")))
  const row = p4.boards.find((b) => b.board === "HB" && b.period_code === "P4")
  assert.deepEqual([row?.op, row?.adult_amount, row?.room_type, row?.child_percent, row?.infant_free, row?.is_base], ["ADD", "-30", "", "30", 1, 0])
  const dlxP4 = boardsAfter(applyBoardEntry(t, { board: "HB", room_type: "DLX" }, "P4", sh("-15", "board")))
  const drow = dlxP4.boards.find((b) => b.board === "HB" && b.room_type === "DLX" && b.period_code === "P4")
  assert.deepEqual([drow?.adult_amount, drow?.child_percent, drow?.infant_free], ["-15", "40", 0], "a new row starts from the terms of the row it overrides")
  const cleared = boardsAfter(applyBoardEntry(t, HB, "P2", sh("", "board")))
  assert.deepEqual(boardRows(cleared, "HB"), ["*/*:ADD:-20", "DLX/*:ADD:-10"])
  assert.deepEqual(applyBoardEntry(t, HB, "P2", sh("x2", "board")), { error: "OP_NOT_ALLOWED" })
})

test("boardModel: one row per board plus room-scoped rows; cells show own and inherited rules", () => {
  const m = boardModel(owner())
  assert.deepEqual(
    m.rows.map((x) => [x.board, x.room_type, x.isBase, x.depth]),
    [
      ["UAI", "", true, 0],
      ["AI", "", false, 0],
      ["HB", "", false, 0],
      ["HB", "DLX", false, 1],
    ],
  )
  const hb = m.rows[2]
  assert.equal(hb.cells[""].state, "rule")
  assert.equal(hb.cells.P1.state, "inherited")
  assert.equal(hb.cells.P1.source?.adult_amount, "-20")
  assert.equal(hb.cells.P2.state, "period-override")
  const hbDlx = m.rows[3]
  assert.equal(hbDlx.cells[""].state, "rule")
  // the engine ranks a period-scoped rule above a room-scoped one (boards.board_rule)
  assert.equal(hbDlx.cells.P2.state, "inherited")
  assert.equal(hbDlx.cells.P2.source?.adult_amount, "-25")
  assert.equal(hbDlx.cells.P1.source?.adult_amount, "-10")
  assert.deepEqual(m.periods, ["", "P1", "P2", "P3", "P4"])
})

test("removeBoard removes every row of a board", () => {
  const out = removeBoard(owner(), "HB")
  assert.deepEqual(out.counts, { rows: 3 })
  assert.deepEqual(
    out.tables.boards.map((b) => b.board),
    ["UAI", "AI"],
  )
})

// ─── periods (§3.9) ─────────────────────────────────────────────────────

test("ISO date integer maths", () => {
  assert.equal(isoAddDays("2027-07-31", 1), "2027-08-01")
  assert.equal(isoAddDays("2028-02-28", 1), "2028-02-29")
  assert.equal(isoAddDays("2027-02-28", 1), "2027-03-01")
  assert.equal(isoAddDays("2027-12-31", 1), "2028-01-01")
  assert.equal(isoAddDays("2027-03-01", -1), "2027-02-28")
  assert.equal(isoAddDays("2000-02-29", 366), "2001-03-01")
  assert.equal(isoAddDays("not a date", 1), "")
})

test("nextPeriodCode and addPeriod", () => {
  const t = owner()
  assert.equal(nextPeriodCode(t), "P5")
  assert.equal(nextPeriodCode({ ...t, periods: [...t.periods, r({ period_code: "P5" })] }), "P6")
  assert.equal(nextPeriodCode(tablesOf({})), "P1")
  const { tables: out, code } = addPeriod(t)
  assert.equal(code, "P5")
  const p5 = out.periods[4]
  assert.deepEqual([p5.period_code, p5.start_date, p5.end_date], ["P5", "2027-08-01", "2027-08-31"])
  const first = addPeriod(tablesOf({}))
  assert.deepEqual([first.tables.periods[0].period_code, first.tables.periods[0].start_date, first.tables.periods[0].end_date], ["P1", "", ""])
})

test("renamePeriod rewrites all three tables and refuses a duplicate code", () => {
  const t = owner()
  const res = renamePeriod(t, "P2", "MAY", "May 2027")
  assert.ok("tables" in res)
  const out = res.tables
  assert.deepEqual(
    out.periods.map((p) => p.period_code),
    ["P1", "MAY", "P3", "P4"],
  )
  assert.equal(out.periods[1].period_name, "May 2027")
  assert.equal(out.periods[1]._key, t.periods[1]._key)
  assert.equal(out.boards.find((b) => b.adult_amount === "-25")?.period_code, "MAY")
  assert.equal(
    out.period_rates.filter((x) => x.period_code === "P2").length,
    0,
  )
  assert.equal(
    out.period_rates.filter((x) => x.period_code === "MAY").length,
    1,
  )
  assert.deepEqual(res.counts, { prices: 1, occupancy: 0, boards: 1 })
  const occ = renamePeriod(t, "P4", "JUL")
  assert.ok("tables" in occ)
  assert.equal(occ.tables.occupancy_rules[1].period_code, "JUL")
  assert.deepEqual(renamePeriod(t, "P2", "P3"), { error: "DUPLICATE_CODE" })
  assert.deepEqual(renamePeriod(t, "P2", " "), { error: "BLANK_CODE" })
  assert.deepEqual(renamePeriod(t, "P9", "X"), { error: "UNKNOWN_PERIOD" })
})

test("duplicatePeriod copies the period rows with the next date range", () => {
  const t = owner()
  const res = duplicatePeriod(t, "P4")
  assert.ok("tables" in res)
  assert.equal(res.code, "P5")
  const p5 = res.tables.periods.find((p) => p.period_code === "P5")
  assert.deepEqual([p5?.start_date, p5?.end_date, p5?.period_name], ["2027-08-01", "2027-08-31", "Jul"])
  assert.deepEqual(
    res.tables.periods.map((p) => p.period_code),
    ["P1", "P2", "P3", "P4", "P5"],
  )
  assert.deepEqual(ratesOf(res.tables, "SUP"), ["*:MULTIPLY:1.15:STD", "P4:MULTIPLY:1.2:STD", "P5:MULTIPLY:1.2:STD"])
  assert.deepEqual(res.counts, { prices: 3, occupancy: 1, boards: 0 })
  const copy = res.tables.period_rates.find((x) => x.room_type === "SUP" && x.period_code === "P5")
  const src = res.tables.period_rates.find((x) => x.room_type === "SUP" && x.period_code === "P4")
  assert.notEqual(copy?._key, src?._key, "copies are new rows")
  assert.equal(res.tables.occupancy_rules.filter((o) => o.period_code === "P5").length, 1)
  // P2 is 31 days: the copy is 01.06–01.07 (and overlaps P3; PERIOD_OVERLAP stays the server check)
  const p2 = duplicatePeriod(t, "P2")
  assert.ok("tables" in p2)
  const c = p2.tables.periods.find((p) => p.period_code === p2.code)
  assert.deepEqual([c?.start_date, c?.end_date], ["2027-06-01", "2027-07-01"])
  assert.deepEqual(
    p2.tables.periods.map((p) => p.period_code),
    ["P1", "P2", "P5", "P3", "P4"],
    "the copy sits right after its source",
  )
})

test("copyPreviousPeriod replaces a column's rows with copies of the left neighbour's", () => {
  const t = owner()
  const res = copyPreviousPeriod(t, "P4")
  assert.ok("tables" in res)
  assert.deepEqual(ratesOf(res.tables, "STD"), ["P1:ABSOLUTE:70:-", "P2:ABSOLUTE:80:-", "P3:ABSOLUTE:100:-", "P4:ABSOLUTE:100:-"])
  assert.deepEqual(ratesOf(res.tables, "SUP"), ["*:MULTIPLY:1.15:STD"])
  assert.deepEqual(ratesOf(res.tables, "DLX"), ["*:MULTIPLY:1.35:STD", "P3:MULTIPLY:1.4:STD", "P4:MULTIPLY:1.4:STD"])
  assert.equal(res.tables.occupancy_rules.filter((o) => o.period_code === "P4").length, 0)
  assert.deepEqual(res.counts, { removed: 4, copied: 2 })
  assert.deepEqual(copyPreviousPeriod(t, "P1"), { error: "NO_PREVIOUS_PERIOD" })
})

test("movePeriod changes table order only", () => {
  const t = owner()
  assert.deepEqual(
    movePeriod(t, "P3", -1).periods.map((p) => p.period_code),
    ["P1", "P3", "P2", "P4"],
  )
  assert.deepEqual(
    movePeriod(t, "P3", 1).periods.map((p) => p.period_code),
    ["P1", "P2", "P4", "P3"],
  )
  assert.equal(movePeriod(t, "P1", -1), t)
  assert.equal(movePeriod(t, "P4", 1), t)
  assert.equal(movePeriod(t, "P3", 1).period_rates, t.period_rates)
})

test("periodDependents and deletePeriod count and remove the dependent rows", () => {
  const t = owner()
  assert.deepEqual(periodDependents(t, "P4"), { prices: 3, occupancy: 1, boards: 0 })
  assert.deepEqual(periodDependents(t, "P2"), { prices: 1, occupancy: 0, boards: 1 })
  const { tables: out, counts } = deletePeriod(t, "P4")
  assert.deepEqual(counts, { prices: 3, occupancy: 1, boards: 0 })
  assert.deepEqual(
    out.periods.map((p) => p.period_code),
    ["P1", "P2", "P3"],
  )
  assert.equal(
    out.period_rates.filter((x) => x.period_code === "P4").length,
    0,
  )
  assert.equal(out.occupancy_rules.length, 2)
})

// ─── module rules (S6) ──────────────────────────────────────────────────

test("workspace modules and lib/keys.ts import at runtime only each other and shorthand.ts", async () => {
  const { readFileSync, readdirSync } = await import("node:fs")
  const root = new URL("../../src/tex/screens/rates/", import.meta.url)
  const files = [...readdirSync(new URL("workspace/", root)).filter((f) => f.endsWith(".ts")).map((f) => `workspace/${f}`), "lib/keys.ts"]
  const allowed = new Set([...files, "lib/shorthand.ts"])
  for (const file of files) {
    const src = readFileSync(new URL(file, root), "utf8")
    for (const m of src.matchAll(/^import\s+(type\s+)?[^;]*?from\s+"([^"]+)"/gm)) {
      if (m[1]) continue // `import type` is erased
      const spec = m[2]
      assert.ok(spec.startsWith("."), `${file}: runtime import of package ${spec}`)
      assert.ok(spec.endsWith(".ts"), `${file}: ${spec} needs an explicit .ts extension`)
      const target = new URL(spec, new URL(file, root)).pathname.split("/screens/rates/")[1]
      assert.ok(allowed.has(target), `${file}: runtime import of ${target}`)
    }
  }
})

test("server decimal strings (9 places) compare canonically with typed entries", () => {
  const t = tablesOf({
    rooms: [r({ room_type: "STD", is_base: 1 }), r({ room_type: "SUP", is_base: 0 })],
    periods: [r({ period_code: "P1" })],
    period_rates: [rate("STD", "", "ABSOLUTE", "70.000000000"), rate("SUP", "", "MULTIPLY", "1.150000000", "STD"), rate("SUP", "P1", "MULTIPLY", "1.200000000", "STD")],
    boards: [r({ board: "HB", is_base: 0, op: "ADD", adult_amount: "-20.000000000", child_percent: "50.000000000", infant_free: 1, room_type: "", period_code: "", label: "" })],
  })
  // typing the stored value again changes nothing (no history entry)
  const same = applyRoomEntry(t, "SUP", "", sh("x1.15"))
  assert.ok("tables" in same)
  assert.equal(same.tables, t)
  // a period entry equal to the server's default string is dropped
  const drop = tablesAfter(applyRoomEntry(t, "SUP", "P1", sh("x1.15")))
  assert.deepEqual(ratesOf(drop, "SUP"), ["*:MULTIPLY:1.150000000:STD"])
  assert.deepEqual(applyRoomEntry(t, "STD", "P1", sh("+10%")), {
    needsServer: { room: "STD", targetPeriod: "P1", op: "ADJUST_PERCENT", value: "10", current: "70.000000000" },
  })
  const board = applyBoardEntry(t, { board: "HB", room_type: "" }, "", sh("-20", "board"))
  assert.ok("tables" in board)
  assert.equal(board.tables, t)
})

test("matrixModel's cells equal cellState for every cell (one pass over the rates)", () => {
  const variants: Tables[] = [
    owner(),
    tablesAfter(applyRoomEntry(owner(), "SUP", "P2", sh("=245"))),
    tablesAfter(applyRoomEntry(owner(), "SUP", "", sh(""))),
    upsertRoomRule(owner(), "DLX", "P1", { op: "INHERIT", value: "", base_room_type: "" }),
    setBaseRoom(owner(), "DLX", { repoint: true }).tables,
    { ...owner(), rooms: owner().rooms.map((x) => ({ ...x, is_base: 0 })) },
  ]
  for (const t of variants) {
    const m = matrixModel(t, "PERSON")
    for (const room of m.rooms) {
      assert.deepEqual(room.defaultBase, defaultBase(t, room.room_type))
      for (const code of ["", ...m.periods.map((p) => p.code)]) assert.deepEqual(room.cells[code], cellState(t, room.room_type, code), `${room.room_type} ${code}`)
    }
  }
})
