// Rate edits and selections of the rates & availability grid (UX revision 2026-10).
//
// Pure and deterministic, no runtime imports (tested with `node --test`,
// tests/unit/inventory-edits.test.ts). Nothing here computes money: an entry stays the decimal
// text the user typed, and the server works out every new price (crs.ari_rate_changes). What this
// module does is read an entry, keep the grid's unsaved edits, and turn edits and selections into
// the ranges the server takes (runs of consecutive nights per room).
import { parseShorthand, type ShErrorCode } from "../rates/lib/shorthand.ts"

/** The rate operations of a grid edit (the same as the bulk editor's). */
export type RateOp = "ABSOLUTE" | "ADJUST_PERCENT" | "ADD" | "SUBTRACT"

/** One entry: a new price ("120"), a percentage ("+10%", "-5%", "+%10") or an amount ("+20", "-20"). */
export interface RateEdit {
  op: RateOp
  /** decimal text; ADJUST_PERCENT keeps its sign ("-5") */
  value: string
}

/** An unsaved edit of one cell (room type × night). */
export interface PendingRate extends RateEdit {
  room: string
  date: string
}

export type RateEntryError = ShErrorCode | "PERCENT_SHARE" | "NOT_A_RATE"

export type RateEntry = { ok: true; edit: RateEdit } | { ok: true; clear: true } | { ok: false; code: RateEntryError }

/**
 * What a typed or pasted entry means for a night's price. The workspace's shorthand, read in the
 * room context, limited to what a date edit can do:
 * - "120" (or "=120") is the new price; "+10%" / "-10%" (also "+%10") change it by a percentage;
 *   "+20" / "-20" by an amount;
 * - a bare "10%" is refused (PERCENT_SHARE): raise or lower? never guessed;
 * - "x1.1" and other formulas are refused (NOT_A_RATE): a formula belongs to the contract;
 * - an empty entry clears the cell's unsaved edit.
 */
export function parseRateEntry(text: string, minorUnits?: number): RateEntry {
  const r = parseShorthand(text, "room", { minorUnits })
  if (!r.ok) return { ok: false, code: r.code === "OP_NOT_ALLOWED" ? "NOT_A_RATE" : r.code }
  if (r.kind === "clear") return { ok: true, clear: true }
  if (r.kind === "base") return { ok: false, code: "NOT_A_RATE" }
  switch (r.op) {
    case "ABSOLUTE":
    case "ADD":
    case "SUBTRACT":
    case "ADJUST_PERCENT":
      return { ok: true, edit: { op: r.op, value: r.value } }
    case "PERCENT_OF":
      return { ok: false, code: "PERCENT_SHARE" }
    default:
      return { ok: false, code: "NOT_A_RATE" }
  }
}

/** The text an edit is shown and edited as ("120", "+10%", "-5%", "+20", "-20"). */
export function rateEditText(e: RateEdit): string {
  switch (e.op) {
    case "ABSOLUTE":
      return e.value
    case "ADJUST_PERCENT":
      return `${e.value.startsWith("-") ? "" : "+"}${e.value}%`
    case "ADD":
      return `+${e.value}`
    case "SUBTRACT":
      return `-${e.value}`
  }
}

/** The key of a cell: a room type and a night. */
export function cellKey(room: string, date: string): string {
  return `${room}\u0000${date}`
}

/** The calendar day after an ISO date (UTC arithmetic on the date only). */
export function nextDay(iso: string): string {
  const d = new Date(`${iso}T00:00:00Z`)
  d.setUTCDate(d.getUTCDate() + 1)
  return d.toISOString().slice(0, 10)
}

/** Sorted unique ISO dates as runs of consecutive days: [[first, last], …]. */
export function dateRuns(dates: readonly string[]): [string, string][] {
  const sorted = [...new Set(dates)].sort()
  const out: [string, string][] = []
  for (const d of sorted) {
    const last = out[out.length - 1]
    if (last && nextDay(last[1]) === d) last[1] = d
    else out.push([d, d])
  }
  return out
}

/** A change the server takes (crs.ari_rate_changes): rooms × a run of nights, one operation. */
export interface RateChange {
  room_types: string[]
  start: string
  end: string
  op: RateOp
  value: string
}

/** The grid's unsaved edits as the server's changes: per room and operation, runs of consecutive
 * nights; rooms with the same run and operation share one change. Every cell is in exactly one
 * change. Ordered by first night, then by the order the rooms were first edited. */
export function toChanges(pending: Iterable<PendingRate>): RateChange[] {
  const byRoomOp = new Map<string, { room: string; op: RateOp; value: string; dates: string[] }>()
  const roomOrder: string[] = []
  for (const p of pending) {
    if (!roomOrder.includes(p.room)) roomOrder.push(p.room)
    const k = `${p.room}\u0000${p.op}\u0000${p.value}`
    const g = byRoomOp.get(k) ?? { room: p.room, op: p.op, value: p.value, dates: [] }
    g.dates.push(p.date)
    byRoomOp.set(k, g)
  }
  const merged = new Map<string, RateChange>()
  for (const g of byRoomOp.values()) {
    for (const [start, end] of dateRuns(g.dates)) {
      const k = `${start}\u0000${end}\u0000${g.op}\u0000${g.value}`
      const c = merged.get(k)
      if (c) c.room_types.push(g.room)
      else merged.set(k, { room_types: [g.room], start, end, op: g.op, value: g.value })
    }
  }
  const rank = (r: string) => roomOrder.indexOf(r)
  return [...merged.values()]
    .map((c) => ({ ...c, room_types: [...c.room_types].sort((a, b) => rank(a) - rank(b)) }))
    .sort((a, b) => (a.start < b.start ? -1 : a.start > b.start ? 1 : rank(a.room_types[0]) - rank(b.room_types[0])))
}

/** A selected cell of the grid: a room type (null = the hotel-level row) and a night. */
export interface GridTarget {
  room: string | null
  date: string
}

/** A rectangle of a selection: rooms (null = the hotel-level row) × a run of nights. */
export interface TargetBatch {
  rooms: (string | null)[]
  start: string
  end: string
}

/** Selected cells as rectangles the bulk endpoint takes (one call each): per room, runs of
 * consecutive nights; rooms with the same run share one rectangle. Every cell is in exactly one. */
export function targetBatches(targets: Iterable<GridTarget>): TargetBatch[] {
  const byRoom = new Map<string | null, string[]>()
  for (const t of targets) byRoom.set(t.room, [...(byRoom.get(t.room) ?? []), t.date])
  const merged = new Map<string, TargetBatch>()
  for (const [room, dates] of byRoom) {
    for (const [start, end] of dateRuns(dates)) {
      const k = `${start}\u0000${end}`
      const b = merged.get(k)
      if (b) b.rooms.push(room)
      else merged.set(k, { rooms: [room], start, end })
    }
  }
  return [...merged.values()].sort((a, b) => (a.start < b.start ? -1 : a.start > b.start ? 1 : 0))
}

export interface PasteFail {
  /** 0-based row and column inside the pasted block */
  row: number
  col: number
  text: string
  code: RateEntryError | "OUTSIDE"
}

export type RatePaste = { ok: true; edits: PendingRate[]; clears: { room: string; date: string }[] } | { ok: false; failures: PasteFail[] }

/**
 * A block copied from a spreadsheet, pasted with its top-left cell on room `rooms[row]` and night
 * `dates[col]`: block row i is the i-th room from there, block column j the j-th night. All or
 * nothing: a cell that cannot be read, or that falls outside the grid, refuses the whole block
 * (the first three failures are reported). An empty cell clears that cell's unsaved edit.
 */
export function planRatePaste(block: readonly (readonly string[])[], rooms: readonly string[], dates: readonly string[], at: { row: number; col: number }, minorUnits?: number): RatePaste {
  const edits: PendingRate[] = []
  const clears: { room: string; date: string }[] = []
  const failures: PasteFail[] = []
  for (let i = 0; i < block.length; i++) {
    for (let j = 0; j < block[i].length; j++) {
      const text = block[i][j]
      const room = rooms[at.row + i]
      const date = dates[at.col + j]
      if (room === undefined || date === undefined) {
        failures.push({ row: i, col: j, text, code: "OUTSIDE" })
        continue
      }
      const r = parseRateEntry(text, minorUnits)
      if (!r.ok) failures.push({ row: i, col: j, text, code: r.code })
      else if ("clear" in r) clears.push({ room, date })
      else edits.push({ room, date, ...r.edit })
    }
  }
  return failures.length ? { ok: false, failures: failures.slice(0, 3) } : { ok: true, edits, clears }
}
