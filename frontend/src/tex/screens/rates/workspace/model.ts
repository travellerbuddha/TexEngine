// The Pricing Workspace model (PRICING_WORKSPACE_UX.md §3.3, §3.4.5, §3.12; D1, D6, D7, D11): pure
// projections of the version editor's tables into the room price matrix and the boards grid, and
// the functions that turn a cell entry into ordinary `period_rates` / `boards` rows.
//
// Rules of this module (and of every workspace/*.ts module):
// - no runtime imports except each other and lib/shorthand.ts / lib/keys.ts (tested with node --test);
// - pure: inputs are never changed; a table that does not change is returned as the same array, and
//   an edit that changes nothing returns the same tables object (so no history entry is recorded);
// - values stay decimal strings: they are parsed, canonicalised and compared as strings, never
//   computed. Adjusting an entered price is done by the server (apply_op_values, §3.4.5).
import { normaliseDecimal, type ShErrorCode, type ShOp, type ShResult } from "../lib/shorthand.ts"
import type { Tables } from "../lib/tables.ts"
import type { Row } from "../lib/types.ts"
import { isSet, newRow, str } from "./rows.ts"

/** The All-periods column: `period_code` blank. */
export const ALL_PERIODS = ""

export type Basis = "PERSON" | "ROOM"

/** Ops that derive a price from a reference (a base room, the slot unit, the occupancy amount). */
export const RELATIVE_OPS: readonly string[] = Object.freeze(["MULTIPLY", "PERCENT_OF", "ADJUST_PERCENT", "ADD", "SUBTRACT"])

export function isRelativeOp(op: unknown): boolean {
  return RELATIVE_OPS.includes(str(op))
}

/** An entered price: the engine reads ABSOLUTE and FIXED alike (rooms.room_unit). */
function isEntered(op: unknown): boolean {
  const o = str(op)
  return o === "ABSOLUTE" || o === "FIXED"
}

/** Canonical decimal text for comparisons ("1.150" = "1.15"); unreadable text compares as typed. */
export function canonValue(v: unknown): string {
  const s = str(v)
  const n = normaliseDecimal(s)
  return n.ok ? n.value : s
}

// ─── room matrix (§3.3) ─────────────────────────────────────────────────

export type RoomRole = "base" | "derived" | "manual"

export type RoomCellState = "manual" | "formula-default" | "inherited" | "period-override" | "fixed-override" | "inherit-rule" | "empty"

export interface RoomCell {
  state: RoomCellState
  /** The cell's own row (`room_type`, `period_code`), if any. */
  rule: Row | null
  /** The room's All-periods rule (its first non-INHERIT generic row), if any. */
  defaultRule: Row | null
}

export type MatrixRowKind = "base" | "formula" | "manual" | "resolved"

export interface MatrixRow {
  kind: MatrixRowKind
  editable: boolean
  /** Which label the row header shows (§3.3.1, §3.11); the screen maps it to an i18n key. */
  label: "base_person" | "base_room" | "formula" | "manual" | "resolved_person" | "resolved_room"
}

export interface MatrixRoom {
  room_type: string
  /** `_key` of the `rooms` row. */
  key: string
  role: RoomRole
  /** The base room a formula typed into this room derives from (§3.3.2). */
  defaultBase: string | null
  defaultRule: Row | null
  rows: MatrixRow[]
}

export interface MatrixPeriod {
  code: string
  name: string
  start: string
  end: string
  weekdays: string
  /** The period has a night adjustment (◆ in its header). */
  adjusted: boolean
  key: string
}

export interface MatrixModel {
  basis: Basis
  baseRoom: string | null
  rooms: MatrixRoom[]
  periods: MatrixPeriod[]
}

const roomOf = (r: Row) => str(r.room_type)
const periodOf = (r: Row) => str(r.period_code)

/** The base room: the first `rooms` row with is_base set (D6: a UI concept, made exclusive here). */
export function baseRoomOf(tables: Pick<Tables, "rooms">): string | null {
  const row = tables.rooms.find((r) => isSet(r.is_base) && roomOf(r))
  return row ? roomOf(row) : null
}

function cellRows(tables: Pick<Tables, "period_rates">, room: string, period: string): Row[] {
  return tables.period_rates.filter((r) => roomOf(r) === room && periodOf(r) === period)
}

/** The row that counts for a cell: the first non-INHERIT row (the engine's winner), else an INHERIT row. */
function ownRule(rows: Row[]): Row | null {
  return rows.find((r) => str(r.op) !== "INHERIT") ?? rows[0] ?? null
}

/** The room's All-periods rule: its first non-INHERIT generic row. */
export function defaultRuleOf(tables: Pick<Tables, "period_rates">, room: string): Row | null {
  return cellRows(tables, room, ALL_PERIODS).find((r) => str(r.op) !== "INHERIT") ?? null
}

/** The rule the engine prices a cell with (rooms._candidates: the period's rows, then the generic
 * ones; INHERIT rows are skipped). */
export function resolvingRule(tables: Pick<Tables, "period_rates">, room: string, period: string): Row | null {
  const candidates = period === ALL_PERIODS ? cellRows(tables, room, ALL_PERIODS) : [...cellRows(tables, room, period), ...cellRows(tables, room, ALL_PERIODS)]
  return candidates.find((r) => str(r.op) !== "INHERIT") ?? null
}

/** The default base of a room: the base_room_type of its All-periods rule, else the base room,
 * else null (§3.3.2). */
export function defaultBase(tables: Pick<Tables, "rooms" | "period_rates">, room: string): string | null {
  const own = str(defaultRuleOf(tables, room)?.base_room_type)
  if (own) return own
  return baseRoomOf(tables)
}

/** base: the is_base room; derived: it has any rule with a derived op; manual: entered prices only. */
export function roomRole(tables: Pick<Tables, "rooms" | "period_rates">, room: string): RoomRole {
  if (room === baseRoomOf(tables)) return "base"
  return tables.period_rates.some((r) => roomOf(r) === room && isRelativeOp(r.op)) ? "derived" : "manual"
}

/** The state of a matrix cell (§3.3.3). The cell's state never changes how an entry is stored. */
export function cellState(tables: Pick<Tables, "rooms" | "period_rates">, room: string, period: string): RoomCell {
  const defaultRule = defaultRuleOf(tables, room)
  const own = ownRule(cellRows(tables, room, period))
  if (period === ALL_PERIODS) {
    if (!own) return { state: "empty", rule: null, defaultRule }
    if (str(own.op) === "INHERIT") return { state: "inherit-rule", rule: own, defaultRule }
    return { state: isEntered(own.op) ? "manual" : "formula-default", rule: own, defaultRule }
  }
  if (own) {
    if (str(own.op) === "INHERIT") return { state: "inherit-rule", rule: own, defaultRule }
    if (isEntered(own.op)) return { state: roomRole(tables, room) === "derived" ? "fixed-override" : "manual", rule: own, defaultRule }
    return { state: "period-override", rule: own, defaultRule }
  }
  return { state: defaultRule ? "inherited" : "empty", rule: null, defaultRule }
}

/** The matrix projection: one entry per contract room (in `rooms` order) with its role and rows,
 * and the period columns (in `periods` order; the All-periods column is implicit). */
export function matrixModel(tables: Pick<Tables, "rooms" | "periods" | "period_rates">, basis: Basis): MatrixModel {
  const seen = new Set<string>()
  const rooms: MatrixRoom[] = []
  for (const r of tables.rooms) {
    const room = roomOf(r)
    if (!room || seen.has(room)) continue
    seen.add(room)
    const role = roomRole(tables, room)
    const defaultRule = defaultRuleOf(tables, room)
    const resolved: MatrixRow = { kind: "resolved", editable: false, label: basis === "ROOM" ? "resolved_room" : "resolved_person" }
    const rows: MatrixRow[] =
      role === "base"
        ? [{ kind: "base", editable: true, label: basis === "ROOM" ? "base_room" : "base_person" }]
        : role === "derived"
          ? [{ kind: "formula", editable: true, label: "formula" }, resolved]
          : [{ kind: "manual", editable: true, label: "manual" }, ...(defaultRule && isEntered(defaultRule.op) ? [resolved] : [])]
    rooms.push({ room_type: room, key: r._key, role, defaultBase: defaultBase(tables, room), defaultRule, rows })
  }
  const periods = tables.periods
    .filter((p) => periodOf(p))
    .map((p) => ({
      code: periodOf(p),
      name: str(p.period_name),
      start: str(p.start_date),
      end: str(p.end_date),
      weekdays: str(p.weekdays),
      adjusted: Boolean(str(p.adjustment_op)),
      key: p._key,
    }))
  return { basis, baseRoom: baseRoomOf(tables), rooms, periods }
}

// ─── entries (§3.3.2, D11) ──────────────────────────────────────────────

export interface RoomRule {
  op: string
  value: string
  base_room_type: string
}

/** The same rule, compared as canonical strings (op, value and base). */
function sameRule(a: Row | RoomRule, b: RoomRule): boolean {
  return str(a.op) === str(b.op) && canonValue(a.value) === canonValue(b.value) && str(a.base_room_type) === str(b.base_room_type)
}

function removeCell(tables: Tables, room: string, period: string): Tables {
  const rest = tables.period_rates.filter((r) => !(roomOf(r) === room && periodOf(r) === period))
  return rest.length === tables.period_rates.length ? tables : { ...tables, period_rates: rest }
}

/** Writes one cell as exactly this rule: the cell's first row is updated in place (it keeps its key),
 * other rows of the same cell are removed (a cell holds one rule; ROOM_RULE_DUPLICATE stays the
 * server's backstop), and a new row is appended when the cell had none. A period rule equal to the
 * room's All-periods rule (op, value and base as canonical strings) is removed instead, because the
 * period then inherits exactly that rule (rooms._candidates falls back to it). Used by shorthand
 * entries and, with the op chosen as chosen, by the advanced popover. */
export function upsertRoomRule(tables: Tables, room: string, period: string, rule: RoomRule): Tables {
  if (period !== ALL_PERIODS) {
    const def = defaultRuleOf(tables, room)
    if (def && sameRule(def, rule)) return removeCell(tables, room, period)
  }
  const rates = tables.period_rates
  const same = rates.filter((r) => roomOf(r) === room && periodOf(r) === period)
  if (same.length === 1 && sameRule(same[0], rule)) return tables
  const patch = { room_type: room, period_code: period, op: rule.op, value: rule.value, base_room_type: rule.base_room_type }
  if (same.length === 0) return { ...tables, period_rates: [...rates, newRow("period_rates", patch)] }
  const first = same[0]
  const next: Row[] = []
  for (const r of rates) {
    if (r === first) next.push({ ...r, ...patch })
    else if (!same.includes(r)) next.push(r)
  }
  return { ...tables, period_rates: next }
}

/** A relative entry on the base room: the server adjusts the entered price once (O4, §3.4.5). */
export interface NeedsServer {
  room: string
  /** The cell that receives the result (as ABSOLUTE). */
  targetPeriod: string
  op: ShOp
  value: string
  /** The entered price the cell resolves to (its own, or the All-periods one it inherits). */
  current: string
}

export type RoomEntryError = ShErrorCode | "BASE_NO_PRICE" | "NO_BASE_ROOM"

export type RoomEntryResult = { tables: Tables } | { needsServer: NeedsServer } | { error: RoomEntryError }

/** Applies a parsed shorthand entry to a matrix cell (§3.3.2). The ROW decides how a relative
 * entry is stored, never the cell's current state (D11):
 * - on the base room, a relative op (MULTIPLY, PERCENT_OF, ADJUST_PERCENT, ADD, SUBTRACT) adjusts
 *   the entered price the cell resolves to, on the server: {needsServer}; without an entered price
 *   it is refused (BASE_NO_PRICE);
 * - on every other room a relative op always writes a formula from the room's default base,
 *   replacing whatever the cell held (a fixed price, a manual price, INHERIT); NO_BASE_ROOM when
 *   the room has no default base;
 * - ABSOLUTE writes an entered price (base_room_type blank); clear removes the cell's row.
 * A period row equal to the All-periods rule is removed (see upsertRoomRule). */
export function applyRoomEntry(tables: Tables, room: string, period: string, parsed: ShResult): RoomEntryResult {
  if (!parsed.ok) return { error: parsed.code }
  if (parsed.kind === "base") return { error: "SYNTAX" }
  if (parsed.kind === "clear") return { tables: removeCell(tables, room, period) }
  const { op, value } = parsed
  if (isRelativeOp(op)) {
    if (room === baseRoomOf(tables)) {
      const current = resolvingRule(tables, room, period)
      if (!current || !isEntered(current.op) || !str(current.value)) return { error: "BASE_NO_PRICE" }
      return { needsServer: { room, targetPeriod: period, op, value, current: str(current.value) } }
    }
    const base = defaultBase(tables, room)
    if (!base || base === room) return { error: "NO_BASE_ROOM" }
    return { tables: upsertRoomRule(tables, room, period, { op, value, base_room_type: base }) }
  }
  return { tables: upsertRoomRule(tables, room, period, { op, value, base_room_type: "" }) }
}

/** Writes the server's adjusted amounts (apply_op_values) as ABSOLUTE into their cells, in order.
 * A missing result (the server's per-item error) leaves its cell as it is. */
export function applyAdjustResults(
  tables: Tables,
  targets: readonly Pick<NeedsServer, "room" | "targetPeriod">[],
  results: readonly (string | null | undefined)[],
): Tables {
  let out = tables
  targets.forEach((t, i) => {
    const v = results[i]
    if (typeof v === "string" && v.trim()) out = upsertRoomRule(out, t.room, t.targetPeriod, { op: "ABSOLUTE", value: v.trim(), base_room_type: "" })
  })
  return out
}

// ─── rooms (§3.3.5) ─────────────────────────────────────────────────────

/** Makes `room` the only base room (radio behaviour, D6). The previous base keeps its entered
 * prices and becomes a manual room. With `repoint`, formulas of other rooms that derive from the
 * previous base derive from the new one (the new base's own formulas are left alone: a room never
 * derives from itself). */
export function setBaseRoom(tables: Tables, room: string, opts: { repoint: boolean }): { tables: Tables; counts: { repointed: number } } {
  const target = tables.rooms.find((r) => roomOf(r) === room)
  if (!target) return { tables, counts: { repointed: 0 } }
  const previous = new Set(tables.rooms.filter((r) => isSet(r.is_base) && roomOf(r) !== room).map(roomOf))
  let roomsChanged = false
  const rooms = tables.rooms.map((r) => {
    const want = r === target ? 1 : 0
    if (r.is_base === want) return r
    roomsChanged = true
    return { ...r, is_base: want }
  })
  let repointed = 0
  let rates = tables.period_rates
  if (opts.repoint && previous.size) {
    rates = tables.period_rates.map((r) => {
      if (roomOf(r) === room || !isRelativeOp(r.op) || !previous.has(str(r.base_room_type))) return r
      repointed += 1
      return { ...r, base_room_type: room }
    })
  }
  if (!roomsChanged && !repointed) return { tables, counts: { repointed: 0 } }
  return { tables: { ...tables, rooms: roomsChanged ? rooms : tables.rooms, period_rates: repointed ? rates : tables.period_rates }, counts: { repointed } }
}

/** "Derive from…": sets the base room of the room's All-periods formula and, with `allPeriods`,
 * of its period formulas. Entered prices and INHERIT rows are not touched; a room never derives
 * from itself. */
export function setDerivation(tables: Tables, room: string, base: string, opts: { allPeriods: boolean }): { tables: Tables; counts: { changed: number } } {
  if (!base || base === room) return { tables, counts: { changed: 0 } }
  let changed = 0
  const rates = tables.period_rates.map((r) => {
    if (roomOf(r) !== room || !isRelativeOp(r.op)) return r
    if (periodOf(r) !== ALL_PERIODS && !opts.allPeriods) return r
    if (str(r.base_room_type) === base) return r
    changed += 1
    return { ...r, base_room_type: base }
  })
  return changed ? { tables: { ...tables, period_rates: rates }, counts: { changed } } : { tables, counts: { changed: 0 } }
}

export interface RoomDependents {
  prices: number
  occupancy: number
  boards: number
  /** Formulas of other rooms deriving from this room (kept; they no longer price after removal). */
  derivedFrom: number
}

/** Removes a room and its prices, occupancy rules and board rules (§3.3.5), with the counts for
 * the inline confirmation. Formulas of other rooms that derive from it are counted, not removed. */
export function removeRoom(tables: Tables, room: string): { tables: Tables; counts: RoomDependents } {
  const drop = (rows: Row[]) => rows.filter((r) => roomOf(r) !== room)
  const period_rates = drop(tables.period_rates)
  const occupancy_rules = drop(tables.occupancy_rules)
  const boards = drop(tables.boards)
  const counts: RoomDependents = {
    prices: tables.period_rates.length - period_rates.length,
    occupancy: tables.occupancy_rules.length - occupancy_rules.length,
    boards: tables.boards.length - boards.length,
    derivedFrom: period_rates.filter((r) => str(r.base_room_type) === room && isRelativeOp(r.op)).length,
  }
  return { tables: { ...tables, rooms: drop(tables.rooms), period_rates, occupancy_rules, boards }, counts }
}

// ─── boards (§3.12, O1–O3) ──────────────────────────────────────────────

/** A board grid row: a board (room_type blank) or one of its room-scoped rules. */
export interface BoardIdentity {
  board: string
  room_type: string
}

export type BoardCellState = "base" | "rule" | "period-override" | "inherited" | "empty"

export interface BoardCell {
  state: BoardCellState
  /** The cell's own row (board, room_type, period_code). */
  rule: Row | null
  /** The row that prices this cell (its own, or the one it inherits by boards.board_rule's order). */
  source: Row | null
}

export interface BoardRow {
  id: string
  board: string
  room_type: string
  /** 0 for the board, 1 for a room-scoped row under it. */
  depth: 0 | 1
  /** Its All-periods row is the base board. */
  isBase: boolean
  identity: BoardIdentity
  cells: Record<string, BoardCell>
}

const boardOf = (r: Row) => str(r.board)

function boardRowsAt(tables: Pick<Tables, "boards">, id: BoardIdentity, period: string): Row[] {
  return tables.boards.filter((r) => boardOf(r) === id.board && roomOf(r) === id.room_type && periodOf(r) === period)
}

/** The row the engine uses for this board, room scope and period, other than the cell's own:
 * boards.board_rule ranks a period-scoped rule above a room-scoped one, then the generic rule. */
function boardSource(tables: Pick<Tables, "boards">, id: BoardIdentity, period: string): Row | null {
  let best: Row | null = null
  let bestRank = -1
  for (const r of tables.boards) {
    if (boardOf(r) !== id.board) continue
    const rr = roomOf(r)
    const rp = periodOf(r)
    if (rr && rr !== id.room_type) continue
    if (rp && rp !== period) continue
    if (rr === id.room_type && rp === period) continue // the cell's own row
    const rank = (rp ? 2 : 0) + (rr ? 1 : 0)
    if (rank > bestRank) {
      best = r
      bestRank = rank
    }
  }
  return best
}

/** The boards grid (§3.12): one row per board in `boards` order, each followed by its room-scoped
 * rows; cells for All periods ("") and every period. */
export function boardModel(tables: Pick<Tables, "boards" | "periods">): { rows: BoardRow[]; periods: string[] } {
  const periods = [ALL_PERIODS, ...tables.periods.map(periodOf).filter(Boolean)]
  const order: string[] = []
  const roomsOf = new Map<string, string[]>()
  for (const r of tables.boards) {
    const b = boardOf(r)
    if (!b) continue
    if (!roomsOf.has(b)) {
      roomsOf.set(b, [])
      order.push(b)
    }
    const rr = roomOf(r)
    const list = roomsOf.get(b) as string[]
    if (rr && !list.includes(rr)) list.push(rr)
  }
  const rows: BoardRow[] = []
  const build = (id: BoardIdentity, depth: 0 | 1): BoardRow => {
    const cells: Record<string, BoardCell> = {}
    for (const p of periods) {
      const own = boardRowsAt(tables, id, p)[0] ?? null
      if (own) cells[p] = { state: isSet(own.is_base) ? "base" : p === ALL_PERIODS ? "rule" : "period-override", rule: own, source: own }
      else {
        const source = boardSource(tables, id, p)
        cells[p] = { state: source ? "inherited" : "empty", rule: null, source }
      }
    }
    const generic = boardRowsAt(tables, id, ALL_PERIODS)[0]
    return { id: `${id.board}|${id.room_type}`, board: id.board, room_type: id.room_type, depth, isBase: Boolean(generic && isSet(generic.is_base)), identity: id, cells }
  }
  for (const b of order) {
    rows.push(build({ board: b, room_type: "" }, 0))
    for (const rr of roomsOf.get(b) as string[]) rows.push(build({ board: b, room_type: rr }, 1))
  }
  return { rows, periods }
}

export type BoardEntryResult = { tables: Tables } | { error: ShErrorCode }

/** Applies a parsed `board` entry to a boards cell (§3.12): BASE makes this board the base board
 * (is_base on the cell's row; every row of every other board loses it); ABSOLUTE / ADD /
 * ADJUST_PERCENT are stored as parsed (O1–O3) in `adult_amount`, and a priced row is no longer a
 * base row; clear removes the cell's row. A new row takes child % and infants-free from the row it
 * overrides (the one that priced the cell), else the table defaults. */
export function applyBoardEntry(tables: Tables, id: BoardIdentity, period: string, parsed: ShResult): BoardEntryResult {
  if (!parsed.ok) return { error: parsed.code }
  const own = boardRowsAt(tables, id, period)
  if (parsed.kind === "clear") {
    if (!own.length) return { tables }
    return { tables: { ...tables, boards: tables.boards.filter((r) => !own.includes(r)) } }
  }
  const source = own[0] ?? boardSource(tables, id, period)
  const fresh = (patch: Record<string, string | number | null>) =>
    newRow("boards", {
      board: id.board,
      room_type: id.room_type,
      period_code: period,
      ...(source ? { child_percent: source.child_percent ?? "50", infant_free: source.infant_free ?? 1 } : {}),
      ...patch,
    })
  const write = (patch: Record<string, string | number | null>, unchanged: (r: Row) => boolean): Row[] => {
    if (own.length === 1 && unchanged(own[0])) return tables.boards
    if (!own.length) return [...tables.boards, fresh(patch)]
    const out: Row[] = []
    for (const r of tables.boards) {
      if (r === own[0]) out.push({ ...r, ...patch })
      else if (!own.includes(r)) out.push(r)
    }
    return out
  }
  if (parsed.kind === "base") {
    let boards = write({ is_base: 1 }, (r) => isSet(r.is_base))
    let changed = boards !== tables.boards
    boards = boards.map((r) => {
      if (boardOf(r) === id.board || !isSet(r.is_base)) return r
      changed = true
      return { ...r, is_base: 0 }
    })
    return { tables: changed ? { ...tables, boards } : tables }
  }
  const { op, value } = parsed
  const boards = write({ op, adult_amount: value, is_base: 0 }, (r) => !isSet(r.is_base) && str(r.op) === op && canonValue(r.adult_amount) === canonValue(value))
  return { tables: boards === tables.boards ? tables : { ...tables, boards } }
}

/** Removes every row of a board (the inline confirmation of clearing a board's generic cell). */
export function removeBoard(tables: Tables, board: string): { tables: Tables; counts: { rows: number } } {
  const boards = tables.boards.filter((r) => boardOf(r) !== board)
  const rows = tables.boards.length - boards.length
  return { tables: rows ? { ...tables, boards } : tables, counts: { rows } }
}
