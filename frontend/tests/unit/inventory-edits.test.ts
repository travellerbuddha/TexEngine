// The rates & availability grid's entries, unsaved edits and selections (UX revision 2026-10;
// screens/inventory/rateEdits.ts). Run with `npm run test:unit`.
import { test } from "node:test"
import assert from "node:assert/strict"
import { cellKey, dateRuns, nextDay, parseRateEntry, planRatePaste, rateEditText, targetBatches, toChanges, type PendingRate } from "../../src/tex/screens/inventory/rateEdits.ts"

test("an entry is a new price, a percentage or an amount; never a guess", () => {
  assert.deepEqual(parseRateEntry("120"), { ok: true, edit: { op: "ABSOLUTE", value: "120" } })
  assert.deepEqual(parseRateEntry("=120,50"), { ok: true, edit: { op: "ABSOLUTE", value: "120.5" } })
  assert.deepEqual(parseRateEntry("+10%"), { ok: true, edit: { op: "ADJUST_PERCENT", value: "10" } })
  assert.deepEqual(parseRateEntry("+%10"), { ok: true, edit: { op: "ADJUST_PERCENT", value: "10" } })
  assert.deepEqual(parseRateEntry("-%5"), { ok: true, edit: { op: "ADJUST_PERCENT", value: "-5" } })
  assert.deepEqual(parseRateEntry("+20"), { ok: true, edit: { op: "ADD", value: "20" } })
  assert.deepEqual(parseRateEntry("−20"), { ok: true, edit: { op: "SUBTRACT", value: "20" } })
  assert.deepEqual(parseRateEntry(""), { ok: true, clear: true })
  // a bare share: raise or lower? refused, never read as one of them
  assert.deepEqual(parseRateEntry("10%"), { ok: false, code: "PERCENT_SHARE" })
  assert.deepEqual(parseRateEntry("%10"), { ok: false, code: "PERCENT_SHARE" })
  // a formula belongs to the contract
  assert.deepEqual(parseRateEntry("x1.1"), { ok: false, code: "NOT_A_RATE" })
  assert.deepEqual(parseRateEntry("base"), { ok: false, code: "SYNTAX" })
  // "1.500" in a 2-decimal currency: 1500 or 1.5? refused (O5)
  assert.deepEqual(parseRateEntry("1.500"), { ok: false, code: "AMBIGUOUS" })
  assert.deepEqual(parseRateEntry("abc"), { ok: false, code: "SYNTAX" })
})

test("an edit reads back as it was typed", () => {
  for (const text of ["120", "+10%", "-5%", "+20", "-20"]) {
    const r = parseRateEntry(text)
    assert.ok(r.ok && "edit" in r, text)
    assert.equal(rateEditText(r.edit), text)
  }
})

test("dates: the next day across months and leap years; runs of consecutive nights", () => {
  assert.equal(nextDay("2027-02-28"), "2027-03-01")
  assert.equal(nextDay("2028-02-28"), "2028-02-29")
  assert.equal(nextDay("2026-12-31"), "2027-01-01")
  assert.deepEqual(dateRuns(["2026-10-05", "2026-10-03", "2026-10-04", "2026-10-07", "2026-10-04"]), [
    ["2026-10-03", "2026-10-05"],
    ["2026-10-07", "2026-10-07"],
  ])
  assert.deepEqual(dateRuns([]), [])
})

const p = (room: string, date: string, op: PendingRate["op"], value: string): PendingRate => ({ room, date, op, value })

test("unsaved edits become the server's changes: one per run and operation, rooms that share it together", () => {
  const changes = toChanges([
    p("STD", "2026-10-03", "ADJUST_PERCENT", "10"),
    p("STD", "2026-10-04", "ADJUST_PERCENT", "10"),
    p("DLX", "2026-10-04", "ADJUST_PERCENT", "10"),
    p("DLX", "2026-10-03", "ADJUST_PERCENT", "10"),
    p("STD", "2026-10-06", "ADJUST_PERCENT", "10"),
    p("DLX", "2026-10-06", "ABSOLUTE", "150"),
  ])
  assert.deepEqual(changes, [
    { room_types: ["STD", "DLX"], start: "2026-10-03", end: "2026-10-04", op: "ADJUST_PERCENT", value: "10" },
    { room_types: ["STD"], start: "2026-10-06", end: "2026-10-06", op: "ADJUST_PERCENT", value: "10" },
    { room_types: ["DLX"], start: "2026-10-06", end: "2026-10-06", op: "ABSOLUTE", value: "150" },
  ])
  // every edited night exactly once
  const nights = changes.flatMap((c) => c.room_types.flatMap((r) => dateRuns([c.start, c.end]).flatMap(([a, b]) => (a === b ? [cellKey(r, a)] : [cellKey(r, a), cellKey(r, b)]))))
  assert.equal(new Set(nights).size, nights.length)
  assert.deepEqual(toChanges([]), [])
})

test("typed prices that differ night by night stay one change per night", () => {
  const changes = toChanges([p("STD", "2026-10-03", "ABSOLUTE", "120"), p("STD", "2026-10-04", "ABSOLUTE", "125"), p("STD", "2026-10-05", "ABSOLUTE", "120")])
  assert.deepEqual(
    changes.map((c) => [c.start, c.end, c.value]),
    [
      ["2026-10-03", "2026-10-03", "120"],
      ["2026-10-04", "2026-10-04", "125"],
      ["2026-10-05", "2026-10-05", "120"],
    ],
  )
})

test("a selection becomes rectangles: rooms that share a run of nights together, the hotel row as null", () => {
  const batches = targetBatches([
    { room: "STD", date: "2026-10-03" },
    { room: "STD", date: "2026-10-04" },
    { room: "DLX", date: "2026-10-03" },
    { room: "DLX", date: "2026-10-04" },
    { room: null, date: "2026-10-04" },
    { room: "DLX", date: "2026-10-09" },
  ])
  assert.deepEqual(batches, [
    { rooms: ["STD", "DLX"], start: "2026-10-03", end: "2026-10-04" },
    { rooms: [null], start: "2026-10-04", end: "2026-10-04" },
    { rooms: ["DLX"], start: "2026-10-09", end: "2026-10-09" },
  ])
})

test("a pasted block lands rooms down and nights across, all or nothing", () => {
  const rooms = ["STD", "DLX", "FAM"]
  const dates = ["2026-10-03", "2026-10-04", "2026-10-05"]
  const ok = planRatePaste(
    [
      ["120", "125"],
      ["", "+10%"],
    ],
    rooms,
    dates,
    { row: 1, col: 1 },
  )
  assert.deepEqual(ok, {
    ok: true,
    edits: [
      { room: "DLX", date: "2026-10-04", op: "ABSOLUTE", value: "120" },
      { room: "DLX", date: "2026-10-05", op: "ABSOLUTE", value: "125" },
      { room: "FAM", date: "2026-10-05", op: "ADJUST_PERCENT", value: "10" },
    ],
    clears: [{ room: "FAM", date: "2026-10-04" }],
  })
  const bad = planRatePaste([["120", "x2", "130"]], rooms, dates, { row: 0, col: 1 })
  assert.deepEqual(bad, {
    ok: false,
    failures: [
      { row: 0, col: 1, text: "x2", code: "NOT_A_RATE" },
      { row: 0, col: 2, text: "130", code: "OUTSIDE" },
    ],
  })
})
