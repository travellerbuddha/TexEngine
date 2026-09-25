// The Price test's pure helpers (PRICING_WORKSPACE_UX.md §3.13, §3.13.2; slice S14): the prefill
// from the matrix's active cell, a child's age as the server takes it (whole years, exact months
// or a date of birth; GAP-6), and "Show in grid": the row of the draft a rule id of a quote names
// (`~<_key>` for a row priced unsaved, GAP-1; the saved row's name otherwise) and the grid cell or
// card that shows it. The only numbers computed are integers: date offsets and months (§3.14 (f)).
// Pure: no runtime imports.
import type { Tables } from "../lib/tables.ts"
import type { PreviewChild, Row } from "../lib/types.ts"
import type { PricingRegion } from "./sections.ts"

const ISO = /^(\d{4})-(\d{2})-(\d{2})$/

/** `iso` + `days` (calendar days, UTC; integers only). */
export function addDaysIso(iso: string, days: number): string {
  const m = ISO.exec(iso)
  if (!m) return iso
  const d = new Date(Date.UTC(Number(m[1]), Number(m[2]) - 1, Number(m[3]) + days))
  return d.toISOString().slice(0, 10)
}

export interface PrefillPeriod {
  code: string
  start: string
  end: string
}

export interface PrefillInput {
  /** the contract rooms, in table order */
  rooms: readonly string[]
  /** the base room (is_base), if any */
  baseRoom?: string | null
  /** the periods with their dates, in table order */
  periods: readonly PrefillPeriod[]
  /** the version's stay window (selling terms), inclusive */
  stayFrom?: string | null
  stayTo?: string | null
  /** the matrix cell the Price test is asked from (a cell's "Test this price"), or the one that
   * last had the focus (the header's Price test); period "" is All periods */
  active?: { room?: string | null; period?: string | null } | null
  /** the site's today */
  today: string
}

export interface Prefill {
  room: string
  /** the period the dates come from (null: none, the default dates) */
  period: string | null
  checkIn: string
  checkOut: string
}

/** The stay a Price test starts with (§3.13): the active matrix row's room (else the base room,
 * else the first), 3 nights from the active period's start (All periods or no active cell: the
 * first period that has not ended), clamped to the stay window so the 3 nights fit in it. Without
 * periods: two weeks after today, or the first stay day when later. */
export function prefillOf(i: PrefillInput): Prefill {
  const room =
    i.active?.room && i.rooms.includes(i.active.room) ? i.active.room : i.baseRoom && i.rooms.includes(i.baseRoom) ? i.baseRoom : (i.rooms[0] ?? "")
  const dated = i.periods.filter((p) => ISO.test(p.start) && ISO.test(p.end))
  const period = (i.active?.period ? dated.find((p) => p.code === i.active?.period) : undefined) ?? dated.find((p) => p.end >= i.today) ?? dated[0]
  let checkIn: string
  if (period) {
    checkIn = period.start
    if (i.stayTo && ISO.test(i.stayTo) && checkIn > addDaysIso(i.stayTo, -2)) checkIn = addDaysIso(i.stayTo, -2)
    if (i.stayFrom && ISO.test(i.stayFrom) && checkIn < i.stayFrom) checkIn = i.stayFrom
  } else {
    checkIn = addDaysIso(i.today, 14)
    if (i.stayFrom && ISO.test(i.stayFrom) && i.stayFrom > checkIn) checkIn = i.stayFrom
  }
  return { room, period: period?.code ?? null, checkIn, checkOut: addDaysIso(checkIn, 3) }
}

/** How a child's age is given: whole years (the default), or exactly in months or by date of birth. */
export type ChildMode = "years" | "months" | "dob"

export interface ChildEntry {
  mode: ChildMode
  /** the text typed: digits (years, months) or an ISO date (dob) */
  value: string
}

/** The most months the server takes (17 years and 11 months; GAP-6). */
export const CHILD_MONTHS_MAX = 215
export const CHILD_YEARS_MAX = 17

/** A child as preview_price takes it (GAP-6): years as a number, `{age_months}` or `{dob}`; null
 * when the entry is not one (the Calculate button then stays off and the field is invalid). */
export function childPayload(c: ChildEntry): PreviewChild | null {
  const v = c.value.trim()
  if (c.mode === "dob") return ISO.test(v) ? { dob: v } : null
  if (!/^\d{1,3}$/.test(v)) return null
  const n = parseInt(v, 10)
  if (c.mode === "months") return n <= CHILD_MONTHS_MAX ? { age_months: n } : null
  return n <= CHILD_YEARS_MAX ? n : null
}

/** The entry after its mode changes: years ↔ months carry the age over in whole months (×12, or
 * the completed years); a date of birth starts empty, and from one a child starts again empty. */
export function withChildMode(c: ChildEntry, mode: ChildMode): ChildEntry {
  if (mode === c.mode) return c
  const v = c.value.trim()
  const digits = /^\d{1,3}$/.test(v) ? parseInt(v, 10) : null
  if (mode === "dob") return { mode, value: "" }
  if (c.mode === "dob" || digits === null) return { mode, value: "" }
  if (mode === "months") return { mode, value: String(Math.min(digits * 12, CHILD_MONTHS_MAX)) }
  return { mode, value: String(Math.min(Math.floor(digits / 12), CHILD_YEARS_MAX)) }
}

/** Where "Show in grid" goes for a rule of a quote: a room price cell (room × period, "" = All
 * periods), an occupancy rule (the ladder cell or the combination card that shows it; the
 * occupancy section decides) or a board cell. A validation issue (S15, issues.issuePlace) can also
 * lead to a ladder cell in a rooms scope, a combination card, a period's column header, or a
 * region of Pricing (the matrix, Occupancy, the child ages drawer, Boards). */
export type ShowTarget =
  | { kind: "matrix"; room: string; period: string }
  | { kind: "occupancy"; key: string }
  | { kind: "board"; board: string; room: string; period: string }
  | { kind: "ladder"; scope: string; row: string; period: string }
  | { kind: "card"; id: string }
  | { kind: "period"; period: string }
  | { kind: "region"; region: PricingRegion | "matrix" }

/** A "Show in grid" request; `n` tells a repeated request from the last one. */
export interface ShowRequest {
  target: ShowTarget
  n: number
}

const SHOWN_TABLES = ["period_rates", "occupancy_rules", "boards"] as const
type ShownTable = (typeof SHOWN_TABLES)[number]

const text = (v: unknown) => (v === null || v === undefined ? "" : String(v).trim())

/** The row of the draft a rule id names: `~<_key>` (a row priced unsaved; `~<table>-<n>` for one
 * sent without a key) or the saved row's name. Only the tables the grids show. */
export function ruleRowOf(tables: Pick<Tables, ShownTable>, ruleId: string | null | undefined): { table: ShownTable; row: Row } | null {
  const id = text(ruleId)
  if (!id) return null
  if (id.startsWith("~")) {
    const key = id.slice(1)
    for (const table of SHOWN_TABLES) {
      const row = tables[table].find((r) => r._key === key)
      if (row) return { table, row }
    }
    const m = /^([a-z_]+)-(\d+)$/.exec(key)
    if (m && (SHOWN_TABLES as readonly string[]).includes(m[1])) {
      const row = tables[m[1] as ShownTable][parseInt(m[2], 10) - 1]
      return row ? { table: m[1] as ShownTable, row } : null
    }
    return null
  }
  for (const table of SHOWN_TABLES) {
    const row = tables[table].find((r) => text(r._name) === id)
    if (row) return { table, row }
  }
  return null
}

/** The grid place of a rule id (ruleRowOf), or null: a rule the draft does not hold (a pricing
 * policy's, the engine's default, a markup, a row removed since) has no "Show in grid". */
export function showTargetOf(tables: Pick<Tables, ShownTable>, ruleId: string | null | undefined): ShowTarget | null {
  const hit = ruleRowOf(tables, ruleId)
  if (!hit) return null
  const { table, row } = hit
  if (table === "period_rates") return { kind: "matrix", room: text(row.room_type), period: text(row.period_code) }
  if (table === "occupancy_rules") return { kind: "occupancy", key: row._key }
  return { kind: "board", board: text(row.board), room: text(row.room_type), period: text(row.period_code) }
}
