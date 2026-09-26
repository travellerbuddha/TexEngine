// The room price matrix screen's logic (PRICING_WORKSPACE_UX.md §3.3–§3.5, §3.3.5, §3.9; slice S9),
// kept pure so it runs under `node --test`: the column template the matrix shares with the
// occupancy ladder and the boards grid, the rows the keyboard grid walks, one entry over one or
// many cells (base-room cells adjusted once by the server, every other cell a formula, D11/O4),
// the reading line under an edited cell, the advanced popover's rows, and the room and period
// edits of the row and column menus.
//
// Same rules as model.ts: runtime imports only among the workspace modules and lib/shorthand.ts;
// inputs are never changed; an edit that changes nothing returns the same tables object (so the
// workspace history records nothing); values stay decimal strings, compared canonically, never
// computed. The server computes every amount (apply_op_values, price_matrix).
import { editText, parseShorthand, type ShFormatOptions, type ShOp, type ShParseOptions, type ShResult } from "../lib/shorthand.ts"
import type { Tables } from "../lib/tables.ts"
import type { Row } from "../lib/types.ts"
import {
  ALL_PERIODS,
  applyAdjustResults,
  applyRoomEntry,
  baseRoomOf,
  canonValue,
  defaultBase,
  defaultRuleOf,
  isRelativeOp,
  resolvingRule,
  upsertRoomRule,
  type MatrixModel,
  type MatrixRowKind,
  type NeedsServer,
  type RoomCell,
  type RoomEntryError,
} from "./model.ts"
import { isSet, newRow, str } from "./rows.ts"

// ─── layout: one column template (§3.1) ────────────────────────────────────

/** Column widths of the matrix, the occupancy ladder and the boards grid. Fixed widths (the row
 * header's depends on the viewport only, and on a side panel open beside the page: tex.css sets
 * --tex-row-header then), so the separate CSS grids of the rows and of the three regions line their
 * period columns up exactly. */
export const MATRIX_WIDTHS = Object.freeze({ header: "var(--tex-row-header, clamp(9rem, 38vw, 16rem))", all: "7.5rem", period: "7.5rem", add: "7rem" })

/** `grid-template-columns` for a row: row header | All periods | one column per period | "+ Period"
 * (left out with `add: false`). */
export function columnTemplate(periods: number, opts?: { add?: boolean }): string {
  const w = MATRIX_WIDTHS
  const n = periods > 0 ? Math.trunc(periods) : 0
  const cols: string[] = [w.header, w.all]
  if (n > 0) cols.push(`repeat(${n}, ${w.period})`)
  if (opts?.add !== false) cols.push(w.add)
  return cols.join(" ")
}

// ─── the rows the keyboard grid walks ─────────────────────────────────────

export interface GridRow {
  room: string
  /** index of the room in the model (and in `rooms` order) */
  roomIndex: number
  kind: MatrixRowKind
  /** the row takes entries (resolved rows never do; read-only mode is the caller's) */
  editable: boolean
  /** the room's first / last row (room block separators) */
  first: boolean
  last: boolean
}

/** Every matrix row, room by room, in the order they are rendered. */
export function gridRows(model: MatrixModel): GridRow[] {
  const out: GridRow[] = []
  model.rooms.forEach((room, roomIndex) => {
    room.rows.forEach((row, i) => {
      out.push({ room: room.room_type, roomIndex, kind: row.kind, editable: row.editable, first: i === 0, last: i === room.rows.length - 1 })
    })
  })
  return out
}

// ─── entries over one or many cells (§3.4.1, §3.4.5) ──────────────────────

/** A matrix cell: a room and a period code ("" = All periods). */
export interface CellRef {
  room: string
  period: string
}

/** Where a cell is in the grid: its room's entry row (a resolved row takes no entry) and its
 * period's column; null when the room or the period is gone. An edit is kept by its cell, not by a
 * row index, so a room above it that gains or loses a resolved row (a late server answer, an undo)
 * never moves the edit, or its commit, to another room. */
export function cellPosition(rows: readonly GridRow[], cols: readonly string[], cell: CellRef): { r: number; c: number } | null {
  const c = cols.indexOf(cell.period)
  if (c < 0) return null
  const r = rows.findIndex((x) => x.room === cell.room && x.editable)
  return r < 0 ? null : { r, c }
}

/** Why an entry cannot be stored in a cell: the parser's code, the model's (BASE_NO_PRICE,
 * NO_BASE_ROOM), BASE_FORMULA (a base-room cell priced by a formula has no entered price to
 * adjust), and the server's per-price answers NEGATIVE / NO_VALUE, or CHANGED (a cell of the
 * entry was edited, or its room or period removed, while the server computed the adjustment),
 * PENDING (a cell is still waiting for such an answer). */
export type EntryError = RoomEntryError | "BASE_FORMULA" | "NEGATIVE" | "NO_VALUE" | "CHANGED" | "PENDING"

export type EntryPlan = { tables: Tables; server: NeedsServer[] } | { error: EntryError; cell: CellRef }

/** The refusal of a relative entry on a base-room cell, made precise: a formula (the base room
 * kept one after "Set as base") is BASE_FORMULA, no entered price BASE_NO_PRICE. */
function baseError(tables: Tables, cell: CellRef): EntryError {
  const rule = resolvingRule(tables, cell.room, cell.period)
  return rule && isRelativeOp(rule.op) ? "BASE_FORMULA" : "BASE_NO_PRICE"
}

/** One cell of an entry and what was typed (or pasted) for it, parsed in the room context. */
export interface EntryItem {
  cell: CellRef
  parsed: ShResult
}

/**
 * One entry over the given cells, each by its own row's rule (§3.3.2, D11): a relative entry on
 * a base-room cell becomes a server adjustment (`server`, sent to apply_op_values), every other
 * cell is written into `tables` (in the order given). All or nothing: the first cell that cannot
 * take its entry refuses the whole gesture. Each cell has its own entry (a paste, S10).
 */
export function planItems(tables: Tables, items: readonly EntryItem[]): EntryPlan {
  let acc = tables
  const server: NeedsServer[] = []
  for (const { cell, parsed } of items) {
    const r = applyRoomEntry(acc, cell.room, cell.period, parsed)
    if ("error" in r) return { error: r.error === "BASE_NO_PRICE" ? baseError(acc, cell) : r.error, cell: { room: cell.room, period: cell.period } }
    if ("needsServer" in r) server.push(r.needsServer)
    else acc = r.tables
  }
  return { tables: acc, server }
}

/** The same entry in every cell (a typed entry, Ctrl/Cmd+Enter over a selection). */
export function planEntry(tables: Tables, cells: readonly CellRef[], parsed: ShResult): EntryPlan {
  return planItems(
    tables,
    cells.map((cell) => ({ cell, parsed })),
  )
}

/** Every cell of an entry while the server adjusts its base-room prices, in the order given: all
 * of them are pending (none takes another entry until the answer), the base-room ones with the
 * price sent, the others with null. */
export function gestureCells(cells: readonly CellRef[], server: readonly NeedsServer[]): { cell: CellRef; current: string | null }[] {
  const sent = new Map(server.map((s) => [`${s.room}\u0000${s.targetPeriod}`, s.current]))
  return cells.map((c) => ({ cell: { room: c.room, period: c.period }, current: sent.get(`${c.room}\u0000${c.period}`) ?? null }))
}

/** One apply_op_values answer per value sent (types.ts ApplyOpResult). */
export interface AdjustAnswer {
  value: string | null
  error: string | null
}

/** The rows stored for a cell (its own rule; more than one only in hand-made data). */
const ownRows = (tables: Tables, cell: CellRef) => tables.period_rates.filter((r) => str(r.room_type) === cell.room && str(r.period_code) === cell.period)

/** A cell's own rows as a comparable text (op, canonical value, base room): no arithmetic. */
function ownSignature(tables: Tables, cell: CellRef): string {
  return ownRows(tables, cell)
    .map((r) => `${str(r.op)}\u0001${canonValue(r.value)}\u0001${str(r.base_room_type)}`)
    .join("\u0002")
}

/** The cell's room is in the contract and its period is All periods or one of the periods. */
function cellExists(tables: Tables, cell: CellRef): boolean {
  if (!tables.rooms.some((r) => str(r.room_type) === cell.room)) return false
  return cell.period === ALL_PERIODS || tables.periods.some((p) => str(p.period_code) === cell.period)
}

/**
 * Completes an entry once the server has adjusted its base-room prices: the entry is planned again
 * on the tables as they are now (edits of other cells may have landed meanwhile and are kept), and
 * the answers are written as ABSOLUTE into their cells, in one result (one history entry). Refused
 * as a whole with CHANGED when a cell of the gesture was changed since the entry was sent
 * (`sentFrom`: its own rows differ, or its room or period is gone) or a price sent has changed,
 * so a late answer never overwrites what the user typed meanwhile; and when the server refused a
 * price (NEGATIVE, NO_VALUE).
 */
export function finishItems(
  tables: Tables,
  items: readonly EntryItem[],
  sent: readonly NeedsServer[],
  answers: readonly AdjustAnswer[],
  sentFrom: Tables,
): { tables: Tables } | { error: EntryError; cell: CellRef } {
  for (const { cell } of items) {
    if (!cellExists(tables, cell) || ownSignature(sentFrom, cell) !== ownSignature(tables, cell)) return { error: "CHANGED", cell: { room: cell.room, period: cell.period } }
  }
  const plan = planItems(tables, items)
  if ("error" in plan) return plan
  const at = (s: NeedsServer): CellRef => ({ room: s.room, period: s.targetPeriod })
  for (let i = 0; i < sent.length; i++) {
    const now = plan.server[i]
    const was = sent[i]
    if (
      !now ||
      now.room !== was.room ||
      now.targetPeriod !== was.targetPeriod ||
      now.op !== was.op ||
      canonValue(now.value) !== canonValue(was.value) ||
      canonValue(now.current) !== canonValue(was.current)
    )
      return { error: "CHANGED", cell: at(was) }
    const a = answers[i]
    if (!a || a.error || typeof a.value !== "string" || !a.value.trim()) return { error: a?.error === "NEGATIVE" ? "NEGATIVE" : "NO_VALUE", cell: at(was) }
  }
  if (plan.server.length !== sent.length) return { error: "CHANGED", cell: at(plan.server[sent.length] ?? sent[0]) }
  return { tables: applyAdjustResults(plan.tables, plan.server, answers.map((a) => a.value)) }
}

/** finishItems for the same entry in every cell. */
export function finishEntry(
  tables: Tables,
  cells: readonly CellRef[],
  parsed: ShResult,
  sent: readonly NeedsServer[],
  answers: readonly AdjustAnswer[],
  sentFrom: Tables,
): { tables: Tables } | { error: EntryError; cell: CellRef } {
  return finishItems(
    tables,
    cells.map((cell) => ({ cell, parsed })),
    sent,
    answers,
    sentFrom,
  )
}

/** Delete / Backspace: removes the rows of the given cells (CLEAR semantics). */
export function clearCells(tables: Tables, cells: readonly CellRef[]): Tables {
  const drop = new Set(cells.map((c) => `${c.room}\u0000${c.period}`))
  const rest = tables.period_rates.filter((r) => !drop.has(`${str(r.room_type)}\u0000${str(r.period_code)}`))
  return rest.length === tables.period_rates.length ? tables : { ...tables, period_rates: rest }
}

// ─── the reading line (§3.4.1) ────────────────────────────────────────────

/** What committing a parsed entry into one cell would do, for the reading line. No arithmetic:
 * the amounts are the strings typed or stored. */
export type Reading =
  | { kind: "error"; code: EntryError }
  /** the cell's own price or rule is removed; a period cell then follows `follows` (or nothing) */
  | { kind: "clear"; follows: Row | null }
  /** a period entry equal to the All-periods rule: the period follows the default (no own row) */
  | { kind: "same"; rule: Row }
  /** an entered price; `fixed`: on a room priced by a formula, it replaces the formula here */
  | { kind: "price"; value: string; fixed: boolean }
  /** a formula from `base`; `replacesFixed`: the entered price the cell held */
  | { kind: "formula"; op: ShOp; value: string; base: string; replacesFixed: string | null }
  /** a base-room cell: the server adjusts `current` once, on commit (O4) */
  | { kind: "adjust"; op: ShOp; value: string; current: string }
  /** nothing would change */
  | { kind: "unchanged" }

export function readingOf(tables: Tables, room: string, period: string, parsed: ShResult): Reading {
  const cell = { room, period }
  const plan = planEntry(tables, [cell], parsed)
  if ("error" in plan) return { kind: "error", code: plan.error }
  if (!parsed.ok || parsed.kind === "base") return { kind: "error", code: "SYNTAX" }
  const s = plan.server[0]
  if (s) return { kind: "adjust", op: s.op, value: s.value, current: s.current }
  if (plan.tables === tables) return { kind: "unchanged" }
  const before = ownRows(tables, cell)
  const after = ownRows(plan.tables, cell)
  const def = period === ALL_PERIODS ? null : defaultRuleOf(tables, room)
  if (parsed.kind === "clear") return { kind: "clear", follows: def }
  if (!after.length && def) return { kind: "same", rule: def }
  const own = before.find((r) => str(r.op) !== "INHERIT") ?? null
  if (!isRelativeOp(parsed.op)) {
    const formula = room !== baseRoomOf(tables) && Boolean((own && isRelativeOp(own.op)) || (def && isRelativeOp(def.op)))
    return { kind: "price", value: parsed.value, fixed: formula }
  }
  const entered = own && (str(own.op) === "ABSOLUTE" || str(own.op) === "FIXED") ? str(own.value) : ""
  return { kind: "formula", op: parsed.op, value: parsed.value, base: str(after[0]?.base_room_type) || str(defaultBase(tables, room)), replacesFixed: entered || null }
}

// ─── edit text (§3.4.6) ────────────────────────────────────────────────────

/** The text an edit starts from (F2 / Enter / double-click): the cell's own rule as ASCII
 * shorthand in the viewer's decimal mark; empty for an inherited cell and an INHERIT row. */
export function cellEditText(cell: RoomCell | undefined, opts?: { decimalMark?: "." | ","; minorUnits?: number }): string {
  const rule = cell?.rule
  if (!rule || str(rule.op) === "INHERIT") return ""
  return editText(str(rule.op) as ShOp, str(rule.value), "room", opts)
}

/** The text Ctrl/Cmd+C copies for an entry cell (§3.10, S10 review): the canonical edit text of
 * the rule the cell shows, which is its own rule, or (no rule of its own, or its own INHERIT row,
 * which the engine skips) its room's All-periods rule; empty when it shows no rule. What a cell
 * shows is what a spreadsheet gets, and the text pasted back into the same cell stores nothing
 * new (a period rule equal to the All-periods rule is not stored). */
export function cellCopyText(cell: RoomCell | undefined, opts?: { decimalMark?: "." | ","; minorUnits?: number }): string {
  const own = cell?.rule
  const rule = own && str(own.op) !== "INHERIT" ? own : cell?.defaultRule
  if (!rule || str(rule.op) === "INHERIT") return ""
  return editText(str(rule.op) as ShOp, str(rule.value), "room", opts)
}

/** The decimal mark of a locale ("," for de-DE, tr-TR …). The parser accepts both marks. */
export function decimalMarkOf(locale: string): "." | "," {
  try {
    const mark = new Intl.NumberFormat(locale).formatToParts(1.5).find((p) => p.type === "decimal")?.value
    return mark === "," ? "," : "."
  } catch {
    return "."
  }
}

// ─── the advanced popover (§3.5) ───────────────────────────────────────────

export interface PopoverRule {
  op: string
  value: string
  /** the room a derived op derives from (ignored for ABSOLUTE and INHERIT) */
  base: string
}

/** Writes the popover's rule into each period applied to ("" = All periods), one row per period;
 * the op chosen is the op stored (never re-interpreted, never adjusted once). INHERIT carries no
 * value; entered prices and INHERIT no base room. `null` removes the cells' rows (Remove). */
export function applyPopover(tables: Tables, room: string, periods: readonly string[], rule: PopoverRule | null): Tables {
  if (!rule) return clearCells(tables, periods.map((period) => ({ room, period })))
  const inherit = rule.op === "INHERIT"
  const derived = isRelativeOp(rule.op)
  let out = tables
  for (const period of periods) {
    out = upsertRoomRule(out, room, period, { op: rule.op, value: inherit ? "" : rule.value, base_room_type: derived ? rule.base : "" })
  }
  return out
}

// ─── rooms (§3.3.5) ─────────────────────────────────────────────────────────

/** "+ Add room": appends the room type; the first room of the contract becomes the base room. */
export function addRoom(tables: Tables, roomType: string): Tables {
  const rt = str(roomType)
  if (!rt || tables.rooms.some((r) => str(r.room_type) === rt)) return tables
  const first = !tables.rooms.some((r) => str(r.room_type))
  return { ...tables, rooms: [...tables.rooms, newRow("rooms", { room_type: rt, is_base: first ? 1 : 0 })] }
}

/** Move up (-1) / down (+1) in `rooms` order (the matrix's row order; no pricing effect). */
export function moveRoom(tables: Tables, room: string, delta: -1 | 1): Tables {
  const idx = tables.rooms.findIndex((r) => str(r.room_type) === room)
  const to = idx + delta
  if (idx < 0 || to < 0 || to >= tables.rooms.length) return tables
  const rooms = [...tables.rooms]
  ;[rooms[idx], rooms[to]] = [rooms[to], rooms[idx]]
  return { ...tables, rooms }
}

export const CAPACITY_FIELDS = ["max_adults", "max_children", "max_occupants", "min_adults", "included_adults"] as const
export type CapacityField = (typeof CAPACITY_FIELDS)[number]

/** "Capacity…": whole numbers on the room's row (0 = from the room type). */
export function setRoomCapacity(tables: Tables, room: string, patch: Partial<Record<CapacityField, number>>): Tables {
  const idx = tables.rooms.findIndex((r) => str(r.room_type) === room)
  if (idx < 0) return tables
  const row = tables.rooms[idx]
  const changes: Record<string, number> = {}
  for (const f of CAPACITY_FIELDS) {
    const v = patch[f]
    if (v === undefined || !Number.isInteger(v) || v < 0) continue
    if (row[f] !== v) changes[f] = v
  }
  if (!Object.keys(changes).length) return tables
  const rooms = [...tables.rooms]
  rooms[idx] = { ...row, ...changes }
  return { ...tables, rooms }
}

/** Whether a room holds formulas of its own (the "Set as base" warning: they stay, S6). */
export function roomHasFormulas(tables: Pick<Tables, "period_rates">, room: string): boolean {
  return tables.period_rates.some((r) => str(r.room_type) === room && isRelativeOp(r.op))
}

/** Whether the room is the contract's base room. */
export function isBaseRoom(tables: Pick<Tables, "rooms">, room: string): boolean {
  return tables.rooms.some((r) => str(r.room_type) === room && isSet(r.is_base))
}

// ─── periods (§3.9) ────────────────────────────────────────────────────────

export interface PeriodFields {
  period_name?: string
  start_date?: string
  end_date?: string
  weekdays?: string
  priority?: number
}

/** "Dates…" (and the "+ Period" end date): writes the given fields on the period's row. */
export function setPeriodFields(tables: Tables, code: string, patch: PeriodFields): Tables {
  const idx = tables.periods.findIndex((p) => str(p.period_code) === code)
  if (idx < 0) return tables
  const row = tables.periods[idx]
  const changes: Record<string, string | number> = {}
  for (const [k, v] of Object.entries(patch) as [keyof PeriodFields, string | number | undefined][]) {
    if (v === undefined) continue
    if (k === "priority" ? row[k] !== v : str(row[k]) !== str(v)) changes[k] = v
  }
  if (!Object.keys(changes).length) return tables
  const periods = [...tables.periods]
  periods[idx] = { ...row, ...changes }
  return { ...tables, periods }
}

/** "Night adjustment…": parses the popover's text in the `period_adjust` context with the
 * contract currency's minor units. O5 counts the adjustment's ADD / SUBTRACT as amounts, so
 * "+12.345" is AMBIGUOUS below 3 decimals and ADD 12.345 in KWD, BHD, OMR, JOD or TND; factors and
 * percentages are exempt. */
export function parsePeriodAdjust(text: string, opts?: ShParseOptions): ShResult {
  return parseShorthand(text, "period_adjust", { minorUnits: opts?.minorUnits })
}

/** The text "Night adjustment…" starts from: the period's adjustment as ASCII shorthand in the
 * viewer's decimal mark, which parsePeriodAdjust with the same minor units reads back to the
 * same adjustment ("+12.345" in a 3-decimal currency, "+12.3450" below); "" without one. */
export function periodAdjustEditText(tables: Pick<Tables, "periods">, code: string, opts?: ShFormatOptions): string {
  const row = tables.periods.find((p) => str(p.period_code) === code)
  const op = str(row?.adjustment_op)
  if (!row || !op) return ""
  return editText(op as ShOp, str(row.adjustment_value), "period_adjust", opts)
}

/** "Night adjustment…": the `period_adjust` shorthand (§3.4.4) on the period's adjustment_op /
 * adjustment_value; an empty entry removes the adjustment. */
export function setPeriodAdjustment(tables: Tables, code: string, parsed: ShResult): { tables: Tables } | { error: EntryError } {
  if (!parsed.ok) return { error: parsed.code }
  if (parsed.kind === "base") return { error: "SYNTAX" }
  const idx = tables.periods.findIndex((p) => str(p.period_code) === code)
  if (idx < 0) return { tables }
  const row = tables.periods[idx]
  const next = parsed.kind === "clear" ? { adjustment_op: "", adjustment_value: "" } : { adjustment_op: parsed.op, adjustment_value: parsed.value }
  if (str(row.adjustment_op) === next.adjustment_op && canonValue(row.adjustment_value) === canonValue(next.adjustment_value)) return { tables }
  const periods = [...tables.periods]
  periods[idx] = { ...row, ...next }
  return { tables: { ...tables, periods } }
}
