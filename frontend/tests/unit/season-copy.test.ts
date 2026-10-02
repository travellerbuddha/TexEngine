// A new season from the last one, and a season's prices copied from any other (UX revision
// 2026-10; screens/rates/workspace/periods.ts). Run with `npm run test:unit`.
import { test } from "node:test"
import assert from "node:assert/strict"
import { copyPeriodFrom, copyPreviousPeriod, shiftIsoYears, shiftSeasonYears } from "../../src/tex/screens/rates/workspace/periods.ts"
import type { Row } from "../../src/tex/screens/rates/lib/types.ts"
import type { Tables } from "../../src/tex/screens/rates/lib/tables.ts"

let seq = 0
const r = (fields: Record<string, string | number | null>): Row => ({ _key: `s${++seq}`, ...fields })
const tablesOf = (p: Partial<Tables>): Tables => ({ rooms: [], periods: [], period_rates: [], age_bands: [], occupancy_rules: [], boards: [], rate_plans: [], offers: [], ...p })

function season(): Tables {
  return tablesOf({
    periods: [
      r({ period_code: "P1", period_name: "Winter", start_date: "2027-01-01", end_date: "2027-02-28" }),
      r({ period_code: "P2", period_name: "Spring", start_date: "2027-03-01", end_date: "2027-05-31" }),
      r({ period_code: "P3", period_name: "Summer", start_date: "2027-06-01", end_date: "2027-09-30" }),
      r({ period_code: "WE", period_name: "Weekends", start_date: "", end_date: "", weekdays: "Sat,Sun" }),
    ],
    period_rates: [
      r({ room_type: "STD", period_code: "P1", op: "ABSOLUTE", value: "70" }),
      r({ room_type: "STD", period_code: "P2", op: "ABSOLUTE", value: "80" }),
      r({ room_type: "STD", period_code: "P3", op: "ABSOLUTE", value: "130" }),
      r({ room_type: "DLX", period_code: "P3", op: "MULTIPLY", value: "1.4", base_room_type: "STD" }),
    ],
    occupancy_rules: [r({ target: "ADULT", position: 3, period_code: "P3", op: "ADJUST_PERCENT", value: "-30" })],
    boards: [r({ board: "HB", period_code: "P1", op: "ADD", adult_amount: "15" })],
    offers: [r({ offer_code: "EB", sale_from: "2026-10-01", sale_to: "2027-02-28", stay_from: "2027-04-01", stay_to: "" })],
  })
}

test("a date a year on: the same day; February stays seamless for back-to-back periods", () => {
  assert.equal(shiftIsoYears("2027-06-01", 1, "start"), "2028-06-01")
  // into a leap year: an end on the last day of February follows it to the 29th
  assert.equal(shiftIsoYears("2027-02-28", 1, "end"), "2028-02-29")
  assert.equal(shiftIsoYears("2027-02-28", 1, "start"), "2028-02-28")
  // out of a leap year: 29 February is 28 February for an end, 1 March for a start
  assert.equal(shiftIsoYears("2028-02-29", 1, "end"), "2029-02-28")
  assert.equal(shiftIsoYears("2028-02-29", 1, "start"), "2029-03-01")
  assert.equal(shiftIsoYears("2028-02-28", 1, "end"), "2029-02-28")
  assert.equal(shiftIsoYears("2027-03-01", -1, "start"), "2026-03-01")
  assert.equal(shiftIsoYears("", 1, "start"), "")
  assert.equal(shiftIsoYears("2027-02-30", 1, "start"), "")
})

test("a new season: every period and offer date a year on, prices and rules untouched", () => {
  const t = season()
  const s = shiftSeasonYears(t, 1)
  assert.deepEqual(
    s.tables.periods.map((p) => [p.period_code, p.start_date, p.end_date]),
    [
      ["P1", "2028-01-01", "2028-02-29"],
      ["P2", "2028-03-01", "2028-05-31"],
      ["P3", "2028-06-01", "2028-09-30"],
      ["WE", "", ""],
    ],
  )
  assert.deepEqual(s.periods.map((p) => p.code), ["P1", "P2", "P3"])
  assert.deepEqual(s.periods[0], { code: "P1", from: ["2027-01-01", "2027-02-28"], to: ["2028-01-01", "2028-02-29"] })
  assert.equal(s.offers, 1)
  assert.deepEqual([s.tables.offers[0].sale_from, s.tables.offers[0].sale_to, s.tables.offers[0].stay_from, s.tables.offers[0].stay_to], ["2027-10-01", "2028-02-29", "2028-04-01", ""])
  // the same rows, by reference: nothing priced changes
  assert.equal(s.tables.period_rates, t.period_rates)
  assert.equal(s.tables.occupancy_rules, t.occupancy_rules)
  assert.equal(s.tables.boards, t.boards)
  // and back again
  const back = shiftSeasonYears(s.tables, -1)
  assert.deepEqual(back.tables.periods.map((p) => [p.start_date, p.end_date]), t.periods.map((p) => [p.start_date, p.end_date]))
})

test("a season's prices copied from any period, its occupancy and board rules with them", () => {
  const t = season()
  const res = copyPeriodFrom(t, "P3", "P1")
  assert.ok("tables" in res)
  const of = (tb: Tables, code: string) => tb.period_rates.filter((x) => x.period_code === code).map((x) => `${x.room_type}:${x.op}:${x.value}`)
  assert.deepEqual(of(res.tables, "P1"), ["STD:ABSOLUTE:130", "DLX:MULTIPLY:1.4"])
  assert.deepEqual(of(res.tables, "P3"), ["STD:ABSOLUTE:130", "DLX:MULTIPLY:1.4"])
  assert.equal(res.tables.occupancy_rules.filter((x) => x.period_code === "P1").length, 1)
  // P1's own board rule is replaced (P3 has none)
  assert.equal(res.tables.boards.filter((x) => x.period_code === "P1").length, 0)
  assert.deepEqual(res.counts, { removed: 2, copied: 3 })
  assert.deepEqual(copyPeriodFrom(t, "P1", "P1"), { error: "NO_PREVIOUS_PERIOD" })
  assert.deepEqual(copyPeriodFrom(t, "XX", "P1"), { error: "UNKNOWN_PERIOD" })
  // the previous-period copy is the same operation from the left neighbour
  const prev = copyPreviousPeriod(t, "P2")
  const from = copyPeriodFrom(t, "P1", "P2")
  assert.ok("tables" in prev && "tables" in from)
  assert.deepEqual(of(prev.tables, "P2"), of(from.tables, "P2"))
})
