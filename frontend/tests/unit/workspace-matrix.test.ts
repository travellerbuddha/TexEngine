// Unit tests for the Pricing Workspace matrix screen logic (PRICING_WORKSPACE_UX.md §3.3–§3.5,
// §3.9, §3.3.5, D11, O4; slice S9): the shared column template, the rows the keyboard grid walks,
// entries over one or many cells (the base room's cells adjusted by the server in one call, the
// other cells as formulas, one result), the reading line, the advanced popover, rooms and periods.
// Run with `npm run test:unit` (node --test).
import { test } from "node:test"
import assert from "node:assert/strict"
import { parseShorthand, type ShContext } from "../../src/tex/screens/rates/lib/shorthand.ts"
import { matrixModel, setBaseRoom } from "../../src/tex/screens/rates/workspace/model.ts"
import {
  addRoom,
  applyPopover,
  cellEditText,
  clearCells,
  columnTemplate,
  decimalMarkOf,
  finishEntry,
  gridRows,
  moveRoom,
  planEntry,
  readingOf,
  setPeriodAdjustment,
  setPeriodFields,
  setRoomCapacity,
  MATRIX_WIDTHS,
} from "../../src/tex/screens/rates/workspace/matrixView.ts"
import type { Row } from "../../src/tex/screens/rates/lib/types.ts"
import type { Tables } from "../../src/tex/screens/rates/lib/tables.ts"

let seq = 0
const r = (fields: Record<string, string | number | null>): Row => ({ _key: `m${++seq}`, ...fields })
const rate = (room: string, period: string, op: string, value: string, base = "") => r({ room_type: room, period_code: period, op, value, base_room_type: base })

function tablesOf(p: Partial<Tables>): Tables {
  return { rooms: [], periods: [], period_rates: [], age_bands: [], occupancy_rules: [], boards: [], rate_plans: [], offers: [], ...p }
}

const sh = (text: string, ctx: ShContext = "room", minorUnits?: number) => parseShorthand(text, ctx, { minorUnits })

/** The owner's example (§3.1) as entered in steps 4–5: Standard 70/80/100/130, Superior ×1.15
 * (P4 ×1.20), Deluxe ×1.35, and a fixed Superior price in P2 for the "restores a formula" case. */
function owner(): Tables {
  return tablesOf({
    rooms: [r({ room_type: "STD", is_base: 1 }), r({ room_type: "SUP", is_base: 0 }), r({ room_type: "DLX", is_base: 0 })],
    periods: [
      r({ period_code: "P1", period_name: "Apr", start_date: "2027-04-01", end_date: "2027-04-30", weekdays: "", priority: 0, adjustment_op: "", adjustment_value: "" }),
      r({ period_code: "P2", period_name: "May", start_date: "2027-05-01", end_date: "2027-05-31", weekdays: "", priority: 0, adjustment_op: "", adjustment_value: "" }),
      r({ period_code: "P3", period_name: "Jun", start_date: "2027-06-01", end_date: "2027-06-30", weekdays: "", priority: 0, adjustment_op: "", adjustment_value: "" }),
      r({ period_code: "P4", period_name: "Jul", start_date: "2027-07-01", end_date: "2027-07-31", weekdays: "", priority: 0, adjustment_op: "", adjustment_value: "" }),
    ],
    period_rates: [
      rate("STD", "P1", "ABSOLUTE", "70"),
      rate("STD", "P2", "ABSOLUTE", "80"),
      rate("STD", "P3", "ABSOLUTE", "100"),
      rate("STD", "P4", "ABSOLUTE", "130"),
      rate("SUP", "", "MULTIPLY", "1.15", "STD"),
      rate("SUP", "P2", "ABSOLUTE", "245"),
      rate("SUP", "P4", "MULTIPLY", "1.2", "STD"),
      rate("DLX", "", "MULTIPLY", "1.35", "STD"),
    ],
  })
}

const ratesOf = (t: Tables, room: string) =>
  t.period_rates.filter((x) => x.room_type === room).map((x) => `${x.period_code || "*"}:${x.op}:${x.value}:${x.base_room_type || "-"}`)

function planned(res: ReturnType<typeof planEntry>) {
  assert.ok("tables" in res, `expected a plan, got ${JSON.stringify(res)}`)
  return res
}

// ─── layout ───────────────────────────────────────────────────────────────

test("one column template for the matrix, the ladder and the boards: row header, All periods, periods, + Period", () => {
  const w = MATRIX_WIDTHS
  assert.equal(columnTemplate(4), `${w.header} ${w.all} repeat(4, ${w.period}) ${w.add}`)
  assert.equal(columnTemplate(0), `${w.header} ${w.all} ${w.add}`)
  assert.equal(columnTemplate(2, { add: false }), `${w.header} ${w.all} repeat(2, ${w.period})`)
  assert.equal(columnTemplate(-3), columnTemplate(0), "a negative count is no period")
})

test("grid rows: the rows the keyboard grid walks, in rooms order, with what is editable", () => {
  const rows = gridRows(matrixModel(owner(), "PERSON"))
  assert.deepEqual(
    rows.map((x) => [x.room, x.kind, x.editable, x.first, x.last]),
    [
      ["STD", "base", true, true, true],
      ["SUP", "formula", true, true, false],
      ["SUP", "resolved", false, false, true],
      ["DLX", "formula", true, true, false],
      ["DLX", "resolved", false, false, true],
    ],
  )
  assert.deepEqual(
    rows.map((x) => x.roomIndex),
    [0, 1, 1, 2, 2],
  )
})

// ─── entries over one or many cells (§3.4.1, §3.4.5, D11) ────────────────

test("a price typed into a base cell is stored at once, nothing is asked of the server", () => {
  const p = planned(planEntry(owner(), [{ room: "STD", period: "P1" }], sh("75")))
  assert.deepEqual(p.server, [])
  assert.deepEqual(ratesOf(p.tables, "STD")[0], "P1:ABSOLUTE:75:-")
})

test("Ctrl+Enter over a selection: base cells go to the server in one list, other cells get the formula", () => {
  const t = owner()
  const cells = [
    { room: "STD", period: "P1" },
    { room: "STD", period: "P2" },
    { room: "DLX", period: "P3" },
    { room: "DLX", period: "P4" },
  ]
  const p = planned(planEntry(t, cells, sh("x1.4")))
  assert.deepEqual(
    p.server.map((s) => [s.room, s.targetPeriod, s.op, s.value, s.current]),
    [
      ["STD", "P1", "MULTIPLY", "1.4", "70"],
      ["STD", "P2", "MULTIPLY", "1.4", "80"],
    ],
  )
  // the planned tables hold the formulas only; the base cells wait for the server
  assert.deepEqual(ratesOf(p.tables, "DLX"), ["*:MULTIPLY:1.35:STD", "P3:MULTIPLY:1.4:STD", "P4:MULTIPLY:1.4:STD"])
  assert.deepEqual(ratesOf(p.tables, "STD"), ratesOf(t, "STD"))
  // the server's answer completes the same gesture: one result, so one history entry
  const done = finishEntry(t, cells, sh("x1.4"), p.server, [
    { value: "98.00", error: null },
    { value: "112.00", error: null },
  ])
  assert.ok("tables" in done, JSON.stringify(done))
  assert.deepEqual(ratesOf(done.tables, "STD"), ["P1:ABSOLUTE:98.00:-", "P2:ABSOLUTE:112.00:-", "P3:ABSOLUTE:100:-", "P4:ABSOLUTE:130:-"])
  assert.deepEqual(ratesOf(done.tables, "DLX"), ["*:MULTIPLY:1.35:STD", "P3:MULTIPLY:1.4:STD", "P4:MULTIPLY:1.4:STD"])
})

test("+10% on the base room's P1 is adjusted by the server and stored as ABSOLUTE (O4)", () => {
  const t = owner()
  const cells = [{ room: "STD", period: "P1" }]
  const p = planned(planEntry(t, cells, sh("+10%")))
  assert.deepEqual(p.server, [{ room: "STD", targetPeriod: "P1", op: "ADJUST_PERCENT", value: "10", current: "70" }])
  assert.equal(p.tables, t, "nothing is written before the server answers")
  const done = finishEntry(t, cells, sh("+10%"), p.server, [{ value: "77.00", error: null }])
  assert.ok("tables" in done)
  assert.deepEqual(ratesOf(done.tables, "STD")[0], "P1:ABSOLUTE:77.00:-")
})

test("the server's per-price refusal, or a price changed meanwhile, completes nothing", () => {
  const t = owner()
  const cells = [{ room: "STD", period: "P1" }, { room: "SUP", period: "P3" }]
  const p = planned(planEntry(t, cells, sh("-100")))
  assert.deepEqual(finishEntry(t, cells, sh("-100"), p.server, [{ value: null, error: "NEGATIVE" }]), { error: "NEGATIVE", cell: { room: "STD", period: "P1" } })
  assert.deepEqual(finishEntry(t, cells, sh("-100"), p.server, []), { error: "NO_VALUE", cell: { room: "STD", period: "P1" } })
  // the user typed another P1 price while the call was out: the answer is for the old price
  const moved = { ...t, period_rates: t.period_rates.map((x) => (x.room_type === "STD" && x.period_code === "P1" ? { ...x, value: "72" } : x)) }
  assert.deepEqual(finishEntry(moved, cells, sh("-100"), p.server, [{ value: "0.00", error: null }]), { error: "CHANGED", cell: { room: "STD", period: "P1" } })
})

test("a selection with a cell that cannot take the entry applies nothing (all or nothing)", () => {
  const noBase = tablesOf({
    rooms: [r({ room_type: "STD", is_base: 0 }), r({ room_type: "SUP", is_base: 0 })],
    periods: [r({ period_code: "P1" })],
    period_rates: [rate("STD", "P1", "ABSOLUTE", "70")],
  })
  assert.deepEqual(planEntry(noBase, [{ room: "STD", period: "P1" }, { room: "SUP", period: "P1" }], sh("x1.2")), { error: "NO_BASE_ROOM", cell: { room: "STD", period: "P1" } })
  assert.deepEqual(planEntry(owner(), [{ room: "SUP", period: "P1" }], sh("abc")), { error: "SYNTAX", cell: { room: "SUP", period: "P1" } })
  assert.deepEqual(planEntry(owner(), [{ room: "SUP", period: "P1" }], sh("1.500")), { error: "AMBIGUOUS", cell: { room: "SUP", period: "P1" } })
})

test("a base cell priced by a formula or by a blank price cannot be adjusted (S6 review)", () => {
  // after "Set as base" on Deluxe, Deluxe keeps its own ×1.35 formula
  const t = setBaseRoom(owner(), "DLX", { repoint: true }).tables
  assert.deepEqual(planEntry(t, [{ room: "DLX", period: "P1" }], sh("+10%")), { error: "BASE_FORMULA", cell: { room: "DLX", period: "P1" } })
  const blank = { ...owner(), period_rates: [rate("STD", "P1", "ABSOLUTE", "")] }
  assert.deepEqual(planEntry(blank, [{ room: "STD", period: "P1" }], sh("+10%")), { error: "BASE_NO_PRICE", cell: { room: "STD", period: "P1" } })
  assert.deepEqual(planEntry(blank, [{ room: "STD", period: "P2" }], sh("x2")), { error: "BASE_NO_PRICE", cell: { room: "STD", period: "P2" } })
})

test("x1.20 typed into a Superior cell holding =245 restores a formula from the default base", () => {
  const p = planned(planEntry(owner(), [{ room: "SUP", period: "P2" }], sh("x1.20")))
  assert.deepEqual(ratesOf(p.tables, "SUP"), ["*:MULTIPLY:1.15:STD", "P2:MULTIPLY:1.2:STD", "P4:MULTIPLY:1.2:STD"])
})

test("Delete clears the selected cells; nothing to clear gives the same tables back", () => {
  const t = owner()
  const out = clearCells(t, [{ room: "STD", period: "P1" }, { room: "SUP", period: "P4" }])
  assert.deepEqual(ratesOf(out, "STD"), ["P2:ABSOLUTE:80:-", "P3:ABSOLUTE:100:-", "P4:ABSOLUTE:130:-"])
  assert.deepEqual(ratesOf(out, "SUP"), ["*:MULTIPLY:1.15:STD", "P2:ABSOLUTE:245:-"])
  assert.equal(clearCells(t, [{ room: "DLX", period: "P1" }]), t)
})

// ─── the reading line (§3.4.1) ────────────────────────────────────────────

test("reading: a formula over a fixed price says it replaces it; the base room reads 'adjust … on commit'", () => {
  const t = owner()
  assert.deepEqual(readingOf(t, "SUP", "P2", sh("x1.20")), { kind: "formula", op: "MULTIPLY", value: "1.2", base: "STD", replacesFixed: "245" })
  assert.deepEqual(readingOf(t, "SUP", "P3", sh("x1.25")), { kind: "formula", op: "MULTIPLY", value: "1.25", base: "STD", replacesFixed: null })
  assert.deepEqual(readingOf(t, "STD", "P1", sh("+10%")), { kind: "adjust", op: "ADJUST_PERCENT", value: "10", current: "70" })
  assert.deepEqual(readingOf(t, "SUP", "P3", sh("=250")), { kind: "price", value: "250", fixed: true })
  assert.deepEqual(readingOf(t, "STD", "P1", sh("75")), { kind: "price", value: "75", fixed: false })
})

test("reading: same as the default, clear, unchanged and refusals", () => {
  const t = owner()
  const same = readingOf(t, "SUP", "P4", sh("x1.15"))
  assert.equal(same.kind, "same")
  assert.equal(same.kind === "same" && same.rule.value, "1.15")
  assert.deepEqual(readingOf(t, "STD", "P1", sh("")), { kind: "clear", follows: null })
  const clear = readingOf(t, "SUP", "P4", sh(""))
  assert.equal(clear.kind === "clear" && clear.follows?.value, "1.15")
  assert.deepEqual(readingOf(t, "STD", "P1", sh("70.00")), { kind: "unchanged" })
  assert.deepEqual(readingOf(t, "SUP", "P3", sh("")), { kind: "unchanged" })
  assert.deepEqual(readingOf(t, "SUP", "P3", sh("abc")), { kind: "error", code: "SYNTAX" })
  assert.deepEqual(readingOf(t, "SUP", "P3", sh("1.500")), { kind: "error", code: "AMBIGUOUS" })
  assert.deepEqual(readingOf(t, "SUP", "P3", sh("1.500", "room", 3)), { kind: "price", value: "1.5", fixed: true })
})

// ─── edit text (§3.4.6) ───────────────────────────────────────────────────

test("edit text: the cell's own rule in the viewer's decimal mark; inherited and INHERIT cells start empty", () => {
  const m = matrixModel({ ...owner(), period_rates: [...owner().period_rates, rate("DLX", "P2", "INHERIT", ""), rate("DLX", "P3", "ADD", "-5", "STD")] }, "PERSON")
  const cells = (room: string) => m.rooms.find((x) => x.room_type === room)?.cells ?? {}
  assert.equal(cellEditText(cells("SUP")[""], { decimalMark: "," }), "x1,15")
  assert.equal(cellEditText(cells("SUP")["P1"]), "", "inherited: no own rule")
  assert.equal(cellEditText(cells("STD")["P1"]), "70")
  assert.equal(cellEditText(cells("DLX")["P2"]), "", "INHERIT has no text")
  assert.equal(cellEditText(cells("DLX")["P3"]), "-5", "ADD -5 reads back as SUBTRACT 5 (same arithmetic): the caller never re-commits unchanged text")
  assert.equal(cellEditText(matrixModel(tablesOf({ rooms: [r({ room_type: "STD", is_base: 1 })], period_rates: [rate("STD", "", "ABSOLUTE", "12.345")] }), "PERSON").rooms[0].cells[""], { minorUnits: 2 }), "12.3450")
  assert.equal(decimalMarkOf("de-DE"), ",")
  assert.equal(decimalMarkOf("en-GB"), ".")
  assert.equal(decimalMarkOf("tr-TR"), ",")
})

// ─── the advanced popover (§3.5): the op chosen is the op stored ─────────

test("popover: one row per period applied to, the op as chosen, INHERIT without a value, Remove", () => {
  const t = owner()
  const two = applyPopover(t, "SUP", ["P1", "P3"], { op: "PERCENT_OF", value: "120", base: "DLX" })
  assert.deepEqual(ratesOf(two, "SUP"), ["*:MULTIPLY:1.15:STD", "P2:ABSOLUTE:245:-", "P4:MULTIPLY:1.2:STD", "P1:PERCENT_OF:120:DLX", "P3:PERCENT_OF:120:DLX"])
  // on the base room a relative op chosen in the popover is stored as chosen (no adjust-once)
  const base = applyPopover(t, "STD", ["P1"], { op: "MULTIPLY", value: "1.1", base: "SUP" })
  assert.deepEqual(ratesOf(base, "STD")[0], "P1:MULTIPLY:1.1:SUP")
  const inherit = applyPopover(t, "SUP", ["P4"], { op: "INHERIT", value: "9", base: "STD" })
  assert.deepEqual(ratesOf(inherit, "SUP")[2], "P4:INHERIT::-")
  const absolute = applyPopover(t, "SUP", [""], { op: "ABSOLUTE", value: "150", base: "STD" })
  assert.deepEqual(ratesOf(absolute, "SUP")[0], "*:ABSOLUTE:150:-")
  const removed = applyPopover(t, "SUP", ["P2", "P4"], null)
  assert.deepEqual(ratesOf(removed, "SUP"), ["*:MULTIPLY:1.15:STD"])
  assert.equal(applyPopover(t, "SUP", ["P4"], { op: "MULTIPLY", value: "1.20", base: "STD" }), t, "unchanged: the same tables")
})

// ─── rooms (§3.3.5) ───────────────────────────────────────────────────────

test("rooms: the first room added is the base, a room is added once, move up and down", () => {
  const empty = tablesOf({})
  const one = addRoom(empty, "STD")
  assert.deepEqual(one.rooms.map((x) => [x.room_type, x.is_base]), [["STD", 1]])
  const two = addRoom(one, "SUP")
  assert.deepEqual(two.rooms.map((x) => [x.room_type, x.is_base]), [["STD", 1], ["SUP", 0]])
  assert.equal(addRoom(two, "SUP"), two)
  assert.equal(addRoom(two, " "), two)
  const moved = moveRoom(owner(), "DLX", -1)
  assert.deepEqual(moved.rooms.map((x) => x.room_type), ["STD", "DLX", "SUP"])
  assert.equal(moveRoom(owner(), "STD", -1).rooms.map((x) => x.room_type).join(), "STD,SUP,DLX")
  const same = owner()
  assert.equal(moveRoom(same, "STD", -1), same)
  assert.equal(moveRoom(same, "NOPE", 1), same)
})

test("rooms: capacity is written as whole numbers on the room's row; unchanged gives the same tables", () => {
  const t = owner()
  const out = setRoomCapacity(t, "SUP", { max_adults: 3, included_adults: 2 })
  const row = out.rooms.find((x) => x.room_type === "SUP")
  assert.deepEqual([row?.max_adults, row?.included_adults], [3, 2])
  assert.equal(out.rooms[0], t.rooms[0], "other rooms are untouched")
  assert.equal(setRoomCapacity(out, "SUP", { max_adults: 3 }), out)
  assert.equal(setRoomCapacity(t, "NOPE", { max_adults: 3 }), t)
})

// ─── periods (§3.9) ───────────────────────────────────────────────────────

test("periods: dates, weekdays and priority on the period's row; unchanged gives the same tables", () => {
  const t = owner()
  const out = setPeriodFields(t, "P2", { end_date: "2027-05-30", weekdays: "Fri,Sat", priority: 5 })
  const p2 = out.periods.find((x) => x.period_code === "P2")
  assert.deepEqual([p2?.start_date, p2?.end_date, p2?.weekdays, p2?.priority], ["2027-05-01", "2027-05-30", "Fri,Sat", 5])
  assert.equal(setPeriodFields(out, "P2", { end_date: "2027-05-30" }), out)
  assert.equal(setPeriodFields(t, "P9", { end_date: "2027-05-30" }), t)
})

test("periods: the night adjustment takes the period_adjust shorthand", () => {
  const t = owner()
  const x = setPeriodAdjustment(t, "P3", sh("x1.1", "period_adjust"))
  assert.ok("tables" in x)
  const p3 = x.tables.periods.find((p) => p.period_code === "P3")
  assert.deepEqual([p3?.adjustment_op, p3?.adjustment_value], ["MULTIPLY", "1.1"])
  const minus = setPeriodAdjustment(x.tables, "P3", sh("-10%", "period_adjust"))
  assert.ok("tables" in minus)
  assert.deepEqual([minus.tables.periods[2].adjustment_op, minus.tables.periods[2].adjustment_value], ["ADJUST_PERCENT", "-10"])
  const cleared = setPeriodAdjustment(minus.tables, "P3", sh("", "period_adjust"))
  assert.ok("tables" in cleared)
  assert.deepEqual([cleared.tables.periods[2].adjustment_op, cleared.tables.periods[2].adjustment_value], ["", ""])
  assert.deepEqual(setPeriodAdjustment(t, "P3", sh("100", "period_adjust")), { error: "OP_NOT_ALLOWED" })
  assert.equal((setPeriodAdjustment(t, "P3", sh("", "period_adjust")) as { tables: Tables }).tables, t)
})
