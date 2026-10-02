// Period management in the matrix columns (PRICING_WORKSPACE_UX.md §3.9): add, rename, duplicate,
// copy the previous period's prices, reorder and delete, as pure functions over the version tables.
// Periods are referenced by code (no foreign key) from period_rates, occupancy_rules and boards, so
// a rename or a delete rewrites or removes those rows too. Dates are ISO strings handled with integer
// day numbers only (no Date objects, no time zones). No runtime imports except rows.ts.
import type { Tables } from "../lib/tables.ts"
import type { Row } from "../lib/types.ts"
import { copyRow, newRow, str } from "./rows.ts"

/** The tables whose rows name a period (`period_code`). */
export const PERIOD_TABLES = ["period_rates", "occupancy_rules", "boards"] as const

export interface PeriodCounts {
  prices: number
  occupancy: number
  boards: number
}

// ─── ISO dates as day numbers (proleptic Gregorian; H. Hinnant's days_from_civil) ─────────────

function daysFromCivil(y: number, m: number, d: number): number {
  const yy = m <= 2 ? y - 1 : y
  const era = Math.floor(yy / 400)
  const yoe = yy - era * 400
  const doy = Math.floor((153 * (m > 2 ? m - 3 : m + 9) + 2) / 5) + d - 1
  const doe = yoe * 365 + Math.floor(yoe / 4) - Math.floor(yoe / 100) + doy
  return era * 146097 + doe - 719468
}

function civilFromDays(n: number): [number, number, number] {
  const z = n + 719468
  const era = Math.floor(z / 146097)
  const doe = z - era * 146097
  const yoe = Math.floor((doe - Math.floor(doe / 1460) + Math.floor(doe / 36524) - Math.floor(doe / 146096)) / 365)
  const doy = doe - (365 * yoe + Math.floor(yoe / 4) - Math.floor(yoe / 100))
  const mp = Math.floor((5 * doy + 2) / 153)
  const d = doy - Math.floor((153 * mp + 2) / 5) + 1
  const m = mp < 10 ? mp + 3 : mp - 9
  return [yoe + era * 400 + (m <= 2 ? 1 : 0), m, d]
}

const pad = (n: number, w: number) => String(n).padStart(w, "0")

/** "YYYY-MM-DD" → day number, or null when it is not a real calendar date. */
export function isoDay(iso: unknown): number | null {
  const m = /^([0-9]{4})-([0-9]{2})-([0-9]{2})$/.exec(str(iso))
  if (!m) return null
  const [y, mo, d] = [parseInt(m[1], 10), parseInt(m[2], 10), parseInt(m[3], 10)]
  if (mo < 1 || mo > 12 || d < 1 || d > 31) return null
  const n = daysFromCivil(y, mo, d)
  const back = civilFromDays(n)
  return back[0] === y && back[1] === mo && back[2] === d ? n : null
}

/** Day number → "YYYY-MM-DD". */
export function isoOfDay(n: number): string {
  const [y, m, d] = civilFromDays(n)
  return `${pad(y, 4)}-${pad(m, 2)}-${pad(d, 2)}`
}

/** `iso` plus `days` (negative: minus), or "" when `iso` is not a date. */
export function isoAddDays(iso: unknown, days: number): string {
  const n = isoDay(iso)
  return n === null ? "" : isoOfDay(n + days)
}

/** The period's length in days (end − start + 1), or null without two valid dates in order. */
function lengthOf(p: Row): number | null {
  const a = isoDay(p.start_date)
  const b = isoDay(p.end_date)
  return a === null || b === null || b < a ? null : b - a + 1
}

/** The range right after `p` with the same length. */
function nextRange(p: Row | undefined): { start_date: string; end_date: string } {
  const len = p ? lengthOf(p) : null
  if (!p || len === null) return { start_date: "", end_date: "" }
  const start = isoAddDays(p.end_date, 1)
  return { start_date: start, end_date: isoAddDays(start, len - 1) }
}

// ─── periods ─────────────────────────────────────────────────────────────

const codeOf = (r: Row) => str(r.period_code)

/** The next free code P{n+1} (n = the number of periods), counting up past codes in use. */
export function nextPeriodCode(tables: Pick<Tables, "periods">): string {
  const used = new Set(tables.periods.map(codeOf))
  for (let i = tables.periods.length + 1; ; i++) if (!used.has(`P${i}`)) return `P${i}`
}

/** Adds a period column: the next free code, starting the day after the last period (in table
 * order) ends and as long as it. The dates stay blank when there is no dated period to follow. */
export function addPeriod(tables: Tables, opts?: { code?: string; name?: string }): { tables: Tables; code: string } {
  const code = str(opts?.code) || nextPeriodCode(tables)
  const last = [...tables.periods].reverse().find((p) => lengthOf(p) !== null)
  const row = newRow("periods", { period_code: code, period_name: opts?.name ?? "", ...nextRange(last) })
  return { tables: { ...tables, periods: [...tables.periods, row] }, code }
}

/** The rows of the three period tables that name `code`, counted. */
export function periodDependents(tables: Pick<Tables, "period_rates" | "occupancy_rules" | "boards">, code: string): PeriodCounts {
  const c = str(code)
  const n = (rows: Row[]) => rows.filter((r) => codeOf(r) === c).length
  return { prices: n(tables.period_rates), occupancy: n(tables.occupancy_rules), boards: n(tables.boards) }
}

export type PeriodError = "BLANK_CODE" | "DUPLICATE_CODE" | "UNKNOWN_PERIOD" | "NO_PREVIOUS_PERIOD"

/** Renames a period's code (and name, when given) and rewrites `period_code` in period_rates,
 * occupancy_rules and boards. Codes must stay unique (compared exactly, as the engine does). */
export function renamePeriod(tables: Tables, oldCode: string, newCode: string, name?: string): { tables: Tables; counts: PeriodCounts } | { error: PeriodError } {
  const from = str(oldCode)
  const to = str(newCode)
  if (!to) return { error: "BLANK_CODE" }
  if (!tables.periods.some((p) => codeOf(p) === from)) return { error: "UNKNOWN_PERIOD" }
  if (to !== from && tables.periods.some((p) => codeOf(p) === to)) return { error: "DUPLICATE_CODE" }
  const zero = { prices: 0, occupancy: 0, boards: 0 }
  if (to === from && name === undefined) return { tables, counts: zero }
  const periods = tables.periods.map((p) => (codeOf(p) === from ? { ...p, period_code: to, ...(name !== undefined ? { period_name: name } : {}) } : p))
  if (to === from) return { tables: { ...tables, periods }, counts: zero }
  const counts = periodDependents(tables, from)
  const out: Tables = { ...tables, periods }
  for (const t of PERIOD_TABLES) {
    if (tables[t].some((r) => codeOf(r) === from)) out[t] = tables[t].map((r) => (codeOf(r) === from ? { ...r, period_code: to } : r))
  }
  return { tables: out, counts }
}

/** Duplicates a period: the next free code, the dates right after the source with the same length,
 * placed right after the source, and copies (new rows) of the source's period-scoped rows in all
 * three tables. The copy has no name: the source's ("Jul") would name a column of other dates (S16
 * review); the workspace opens Rename… on it. */
export function duplicatePeriod(tables: Tables, code: string): { tables: Tables; code: string; counts: PeriodCounts } | { error: PeriodError } {
  const c = str(code)
  const idx = tables.periods.findIndex((p) => codeOf(p) === c)
  if (idx < 0) return { error: "UNKNOWN_PERIOD" }
  const src = tables.periods[idx]
  const next = nextPeriodCode(tables)
  const copy = copyRow(src, { period_code: next, period_name: "", ...nextRange(src) })
  const out: Tables = { ...tables, periods: [...tables.periods.slice(0, idx + 1), copy, ...tables.periods.slice(idx + 1)] }
  for (const t of PERIOD_TABLES) {
    const copies = tables[t].filter((r) => codeOf(r) === c).map((r) => copyRow(r, { period_code: next }))
    if (copies.length) out[t] = [...tables[t], ...copies]
  }
  return { tables: out, code: next, counts: periodDependents(tables, c) }
}

/** "Copy prices from…" (UX revision 2026-10): replaces this column's rows in the three tables
 * (room prices, occupancy and child rules, boards) with copies of the rows of period `from`. */
export function copyPeriodFrom(tables: Tables, from: string, code: string): { tables: Tables; counts: { removed: number; copied: number } } | { error: PeriodError } {
  const c = str(code)
  const src = str(from)
  if (!tables.periods.some((p) => codeOf(p) === c) || !tables.periods.some((p) => codeOf(p) === src)) return { error: "UNKNOWN_PERIOD" }
  if (src === c) return { error: "NO_PREVIOUS_PERIOD" }
  const out: Tables = { ...tables }
  let removed = 0
  let copied = 0
  for (const t of PERIOD_TABLES) {
    const rest = tables[t].filter((r) => codeOf(r) !== c)
    const copies = tables[t].filter((r) => codeOf(r) === src).map((r) => copyRow(r, { period_code: c }))
    removed += tables[t].length - rest.length
    copied += copies.length
    if (rest.length !== tables[t].length || copies.length) out[t] = [...rest, ...copies]
  }
  return { tables: out, counts: { removed, copied } }
}

/** "Copy previous period's prices": `copyPeriodFrom` the period to its left (table order). */
export function copyPreviousPeriod(tables: Tables, code: string): { tables: Tables; counts: { removed: number; copied: number } } | { error: PeriodError } {
  const c = str(code)
  const idx = tables.periods.findIndex((p) => codeOf(p) === c)
  if (idx < 0) return { error: "UNKNOWN_PERIOD" }
  const prev = idx > 0 ? codeOf(tables.periods[idx - 1]) : ""
  if (!prev || prev === c) return { error: "NO_PREVIOUS_PERIOD" }
  return copyPeriodFrom(tables, prev, c)
}

// ─── a new season: every date a year later ───────────────────────────────

const lastOfFebruary = (y: number) => (isoDay(`${pad(y, 4)}-02-29`) === null ? 28 : 29)

/**
 * The same calendar day `years` years later (negative: earlier), or "" when `iso` is not a date.
 * February is kept seamless for back-to-back periods: an end on the last day of February stays the
 * last day of February (28 ↔ 29), and a 29 February that the target year lacks becomes 1 March for
 * a start (28 February for an end).
 */
export function shiftIsoYears(iso: unknown, years: number, edge: "start" | "end"): string {
  if (isoDay(iso) === null) return ""
  const [y0, m, d] = str(iso).split("-").map((x) => parseInt(x, 10))
  const y = y0 + years
  if (m === 2 && d >= 28) {
    if (edge === "end" && d === lastOfFebruary(y0)) return `${pad(y, 4)}-02-${lastOfFebruary(y)}`
    if (d === 29 && lastOfFebruary(y) === 28) return edge === "start" ? `${pad(y, 4)}-03-01` : `${pad(y, 4)}-02-28`
  }
  return `${pad(y, 4)}-${pad(m, 2)}-${pad(d, 2)}`
}

export interface SeasonShift {
  tables: Tables
  /** each period moved: code, old and new dates */
  periods: { code: string; from: [string, string]; to: [string, string] }[]
  /** offers whose sale or stay dates moved */
  offers: number
}

/** Every date of the version's periods and offers moved by `years` years (a new season from the
 * last one: prices and rules stay as they are, attached to the same period codes). Blank dates
 * stay blank. */
export function shiftSeasonYears(tables: Tables, years: number): SeasonShift {
  const moved: SeasonShift["periods"] = []
  const periods = tables.periods.map((p) => {
    const a = str(p.start_date)
    const b = str(p.end_date)
    const na = a ? shiftIsoYears(a, years, "start") || a : a
    const nb = b ? shiftIsoYears(b, years, "end") || b : b
    if (na === a && nb === b) return p
    moved.push({ code: codeOf(p), from: [a, b], to: [na, nb] })
    return { ...p, start_date: na, end_date: nb }
  })
  let offers = 0
  const offerRows = tables.offers.map((o) => {
    const next = { ...o }
    let changed = false
    for (const [k, edge] of [["sale_from", "start"], ["sale_to", "end"], ["stay_from", "start"], ["stay_to", "end"]] as const) {
      const v = str(o[k])
      const nv = v ? shiftIsoYears(v, years, edge) || v : v
      if (nv !== v) {
        next[k] = nv
        changed = true
      }
    }
    if (changed) offers++
    return changed ? next : o
  })
  return { tables: { ...tables, periods, offers: offerRows }, periods: moved, offers }
}

/** Moves a period one column left (-1) or right (+1). Column order has no pricing effect
 * (rooms.period_for picks by dates, weekdays and priority), so this only changes table order. */
export function movePeriod(tables: Tables, code: string, delta: -1 | 1): Tables {
  const idx = tables.periods.findIndex((p) => codeOf(p) === str(code))
  const to = idx + delta
  if (idx < 0 || to < 0 || to >= tables.periods.length) return tables
  const periods = [...tables.periods]
  ;[periods[idx], periods[to]] = [periods[to], periods[idx]]
  return { ...tables, periods }
}

/** Deletes a period and every row naming it, with the counts for the inline confirmation. */
export function deletePeriod(tables: Tables, code: string): { tables: Tables; counts: PeriodCounts } {
  const c = str(code)
  const counts = periodDependents(tables, c)
  const out: Tables = { ...tables, periods: tables.periods.filter((p) => codeOf(p) !== c) }
  for (const t of PERIOD_TABLES) if (tables[t].some((r) => codeOf(r) === c)) out[t] = tables[t].filter((r) => codeOf(r) !== c)
  return { tables: out, counts }
}
