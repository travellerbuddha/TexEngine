// The room price matrix's bulk tools (PRICING_WORKSPACE_UX.md §3.10, D2, D11, O4, O5; slice S10):
// Fill right / Fill down, the Adjust… popover's targets, preview and commit, and the
// apply_op_values calls an entry over many cells makes.
//
// Same rules as model.ts: runtime imports only among the workspace modules and lib/shorthand.ts;
// inputs are never changed; an edit that changes nothing returns the same tables object (no
// history entry); values stay decimal strings, compared canonically and never computed. Every
// adjusted amount is the server's (apply_op_values: ops.apply_op + money.quantize).
import { normaliseDecimal, type ShErrorCode, type ShOp } from "../lib/shorthand.ts"
import type { Tables } from "../lib/tables.ts"
import type { Row } from "../lib/types.ts"
import { canonValue, defaultBase, isRelativeOp, matrixModel, upsertRoomRule, type MatrixModel, type NeedsServer, type RoomCell } from "./model.ts"
import { clearCells, type AdjustAnswer, type CellRef } from "./matrixView.ts"
import { str } from "./rows.ts"

const keyOf = (c: CellRef) => `${c.room}\u0000${c.period}`
const isEntered = (op: unknown) => str(op) === "ABSOLUTE" || str(op) === "FIXED"

/** The model's cell (one pass over the rates for the whole gesture, not one per cell). */
function cellOf(model: MatrixModel, cell: CellRef): RoomCell | undefined {
  return model.rooms.find((x) => x.room_type === cell.room)?.cells[cell.period]
}

// ─── Fill right / Fill down ────────────────────────────────────────────────

/** One copy of a fill: the source cell's rule is written into the target cell. */
export interface FillStep {
  from: CellRef
  to: CellRef
}

export type FillPlan =
  /** `fixed`: targets in formula rows that get a price (a fixed price override): the screen asks
   * "Set a fixed price override?" before it commits; `cleared`: targets whose rule was removed
   * because their source shows no rule (the toast names them); `count`: the target cells */
  | { tables: Tables; count: number; fixed: CellRef[]; cleared: CellRef[] }
  /** a formula copied into a price row (the base room or a manual room): refused as a whole */
  | { error: "FILL_FORMULA" | "NO_BASE_ROOM"; cell: CellRef }

/**
 * Fill right ("copy across periods") and Fill down ("copy down rooms"), from the steps of
 * fillRightPlan / fillDownPlan, all or nothing (§3.10). What is copied is the rule the source
 * shows (S10 review):
 * - within a room (Fill →) the source's own rule is copied as it is (op and value): a price stays
 *   a price, INHERIT stays INHERIT; a source without a rule of its own follows All periods, so the
 *   target's own rule is removed and the target follows the same All-periods rule;
 * - into another room (Fill ↓) a source that follows All periods (no rule of its own, or its own
 *   INHERIT row, which the engine skips) copies the All-periods rule it follows as if it were its
 *   own, so the target shows what the source shows;
 * - a source that shows no rule at all removes the target's rule: those targets are `cleared`;
 * - a formula keeps the room it derives from, unless that is the target room itself (then the
 *   target's default base), and goes into formula rows only: into a price row (the base room, where
 *   a relative entry would change the price once (O4), or a manual room) it is refused;
 * - a price in a formula row is a fixed price override: allowed, and listed in `fixed` for the
 *   confirmation;
 * - a period copy equal to the target room's All-periods rule is not stored (the period follows it:
 *   the same price, upsertRoomRule).
 * Sources are read from the tables before the fill. The row kinds are the matrix's (roomRole).
 */
export function planFill(tables: Tables, steps: readonly FillStep[]): FillPlan {
  const model = matrixModel(tables, "PERSON")
  const role = new Map(model.rooms.map((x) => [x.room_type, x.role]))
  let acc = tables
  const fixed: CellRef[] = []
  const cleared: CellRef[] = []
  for (const { from, to } of steps) {
    const target = { room: to.room, period: to.period }
    const source = cellOf(model, from)
    const own: Row | null = source?.rule ?? null
    // the rule the source shows: its own, or the All-periods rule it follows
    const shown: Row | null = own && str(own.op) !== "INHERIT" ? own : (source?.defaultRule ?? null)
    const src: Row | null = from.room === to.room ? own : shown
    const formulaRow = role.get(to.room) === "derived"
    let next: Tables
    if (!src) {
      next = clearCells(acc, [target])
      if (!shown && next !== acc) cleared.push(target)
    } else if (str(src.op) === "INHERIT") next = upsertRoomRule(acc, to.room, to.period, { op: "INHERIT", value: "", base_room_type: "" })
    else if (isRelativeOp(src.op)) {
      if (!formulaRow) return { error: "FILL_FORMULA", cell: target }
      let base = str(src.base_room_type)
      if (!base || base === to.room) base = str(defaultBase(acc, to.room))
      if (!base || base === to.room) return { error: "NO_BASE_ROOM", cell: target }
      next = upsertRoomRule(acc, to.room, to.period, { op: str(src.op), value: str(src.value), base_room_type: base })
    } else {
      next = upsertRoomRule(acc, to.room, to.period, { op: str(src.op), value: str(src.value), base_room_type: "" })
      if (formulaRow && next !== acc) fixed.push(target)
    }
    acc = next
  }
  return { tables: acc, count: steps.length, fixed, cleared }
}

// ─── Adjust… ────────────────────────────────────────────────────────────────

/** The Adjust… ops, in the popover's order: +%, −%, +amount, −amount, ×. */
export const ADJUST_KINDS = ["up_pct", "down_pct", "up_amount", "down_amount", "times"] as const
export type AdjustKind = (typeof ADJUST_KINDS)[number]

/** Amount kinds get the currency-aware AMBIGUOUS guard (O5); percentages and factors do not. */
export function isAmountKind(kind: AdjustKind): boolean {
  return kind === "up_amount" || kind === "down_amount"
}

/**
 * The op and value apply_op_values is asked for (§3.10): +% → ADJUST_PERCENT v, −% →
 * ADJUST_PERCENT −v, +amount → ADD v, −amount → SUBTRACT v, × → MULTIPLY v. The value is a
 * decimal string without a sign (the sign is the op's), either decimal mark, canonicalised; an
 * amount written like "1.500" is AMBIGUOUS below 3 decimals (O5). BLANK: nothing typed yet.
 */
export function adjustRule(kind: AdjustKind, text: string, minorUnits?: number): { ok: true; op: ShOp; value: string } | { ok: false; code: ShErrorCode | "BLANK" } {
  if (!text.trim()) return { ok: false, code: "BLANK" }
  if (/^\s*[+-]/.test(text)) return { ok: false, code: "SYNTAX" }
  const n = normaliseDecimal(text, { amount: isAmountKind(kind), minorUnits })
  if (!n.ok) return { ok: false, code: n.code }
  const v = n.value
  switch (kind) {
    case "up_pct":
      return { ok: true, op: "ADJUST_PERCENT", value: v }
    case "down_pct":
      return { ok: true, op: "ADJUST_PERCENT", value: v === "0" ? "0" : `-${v}` }
    case "up_amount":
      return { ok: true, op: "ADD", value: v }
    case "down_amount":
      return { ok: true, op: "SUBTRACT", value: v }
    case "times":
      return { ok: true, op: "MULTIPLY", value: v }
  }
}

/** An entered price Adjust… changes, and the price it has now. */
export interface AdjustTarget {
  cell: CellRef
  current: string
}

/**
 * What Adjust… changes in the selected cells (§3.10): the entered prices (`manual` and
 * `fixed-override`, in any row: an ABSOLUTE or FIXED row of the cell's own, with a value).
 * `formulas`: selected cells priced by a formula (their own, or the All-periods formula they
 * follow), skipped and counted; `others`: the rest (no price, INHERIT, or a period that follows the
 * All-periods price: adjust that cell instead), skipped and counted.
 */
export function adjustTargets(tables: Tables, cells: readonly CellRef[]): { targets: AdjustTarget[]; formulas: number; others: number } {
  const model = matrixModel(tables, "PERSON")
  const targets: AdjustTarget[] = []
  let formulas = 0
  let others = 0
  const seen = new Set<string>()
  for (const cell of cells) {
    const k = keyOf(cell)
    if (seen.has(k)) continue
    seen.add(k)
    const mc = cellOf(model, cell)
    const rule = mc?.rule
    if (rule && isEntered(rule.op) && str(rule.value).trim()) targets.push({ cell: { room: cell.room, period: cell.period }, current: str(rule.value) })
    else if ((rule && isRelativeOp(rule.op)) || (!rule && mc?.defaultRule && isRelativeOp(mc.defaultRule.op))) formulas += 1
    else others += 1
  }
  return { targets, formulas, others }
}

/** The preview lists at most this many changes ("+N more" for the rest). */
export const ADJUST_PREVIEW_LINES = 8

export interface AdjustPreview {
  /** the prices that change: before (as stored) → after (the server's) */
  changes: { cell: CellRef; before: string; after: string }[]
  /** the prices the server refused (NEGATIVE, NO_VALUE) */
  errors: { cell: CellRef; code: "NEGATIVE" | "NO_VALUE" }[]
  /** the prices that stay the same */
  unchanged: number
}

/** The preview of the server's answers, one per target in order (compared canonically). */
export function adjustPreview(targets: readonly AdjustTarget[], answers: readonly AdjustAnswer[]): AdjustPreview {
  const out: AdjustPreview = { changes: [], errors: [], unchanged: 0 }
  targets.forEach((t, i) => {
    const a = answers[i]
    if (!a || a.error || typeof a.value !== "string" || !a.value.trim()) out.errors.push({ cell: t.cell, code: a?.error === "NEGATIVE" ? "NEGATIVE" : "NO_VALUE" })
    else if (canonValue(a.value) === canonValue(t.current)) out.unchanged += 1
    else out.changes.push({ cell: t.cell, before: t.current, after: a.value.trim() })
  })
  return out
}

/**
 * Apply: the server's amounts are written as ABSOLUTE into the cells whose price changes, in one
 * result (one history entry); the others keep their rows as they are. Refused as a whole with
 * CHANGED when a target no longer holds the price that was sent (edited, cleared or turned into a
 * formula since the preview), or with the server's refusal of a price.
 */
export function applyAdjust(tables: Tables, targets: readonly AdjustTarget[], answers: readonly AdjustAnswer[]): { tables: Tables } | { error: "CHANGED" | "NEGATIVE" | "NO_VALUE"; cell: CellRef } {
  const model = matrixModel(tables, "PERSON")
  for (const t of targets) {
    const rule = cellOf(model, t.cell)?.rule
    if (!rule || !isEntered(rule.op) || canonValue(rule.value) !== canonValue(t.current)) return { error: "CHANGED", cell: t.cell }
  }
  let acc = tables
  for (let i = 0; i < targets.length; i++) {
    const t = targets[i]
    const a = answers[i]
    if (!a || a.error || typeof a.value !== "string" || !a.value.trim()) return { error: a?.error === "NEGATIVE" ? "NEGATIVE" : "NO_VALUE", cell: t.cell }
    if (canonValue(a.value) === canonValue(t.current)) continue
    acc = upsertRoomRule(acc, t.cell.room, t.cell.period, { op: "ABSOLUTE", value: a.value.trim(), base_room_type: "" })
  }
  return { tables: acc }
}

// ─── the server calls of an entry ───────────────────────────────────────────

/** apply_op_values takes at most this many prices per call (contracts.ADJUST_VALUES_MAX). */
export const APPLY_OP_VALUES_MAX = 500

export interface ServerCall {
  op: ShOp
  value: string
  /** the prices sent */
  values: string[]
  /** where each answer goes in the entry's `server` list */
  indexes: number[]
}

/** The apply_op_values calls for the base-room adjustments of an entry (O4): one per op and
 * (canonical) value, at most APPLY_OP_VALUES_MAX prices each, in first-seen order. A typed entry
 * or Ctrl/Cmd+Enter makes one call; a paste may make several. */
export function serverCalls(server: readonly NeedsServer[]): ServerCall[] {
  const out: ServerCall[] = []
  const open = new Map<string, ServerCall>()
  server.forEach((s, i) => {
    const k = `${s.op}\u0000${canonValue(s.value)}`
    let call = open.get(k)
    if (!call || call.values.length >= APPLY_OP_VALUES_MAX) {
      call = { op: s.op, value: s.value, values: [], indexes: [] }
      open.set(k, call)
      out.push(call)
    }
    call.values.push(s.current)
    call.indexes.push(i)
  })
  return out
}

/** The answers of the calls put back in the order of the entry's `server` list. */
export function answersInOrder(calls: readonly ServerCall[], results: readonly (readonly AdjustAnswer[])[], count: number): AdjustAnswer[] {
  const out: AdjustAnswer[] = Array.from({ length: count }, () => ({ value: null, error: "NO_VALUE" }))
  calls.forEach((call, j) => {
    call.indexes.forEach((idx, k) => {
      const a = results[j]?.[k]
      if (a) out[idx] = a
    })
  })
  return out
}

/** The same calls for the Adjust… targets: one op and value, at most APPLY_OP_VALUES_MAX each. */
export function adjustCalls(targets: readonly AdjustTarget[], op: ShOp, value: string): ServerCall[] {
  return serverCalls(targets.map((t) => ({ room: t.cell.room, targetPeriod: t.cell.period, op, value, current: t.current })))
}
