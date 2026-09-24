// Occupancy & child pricing in the workspace (PRICING_WORKSPACE_UX.md §3.6, §3.7; D8, D12): the
// slot ladder projection over `occupancy_rules`, cell entries, valid party combinations and the
// special-combination cards. Every gesture writes ordinary TEX Occupancy Rule rows; nothing here
// prices anything (resolved totals come from the server's price_matrix parties, GAP-2b).
//
// The ladder is a per-scope rule editor: the "All rooms" scope shows the rules with room_type blank,
// a room scope the rules naming that room. A cell shows its own rule, the All-periods rule of the
// same slot it inherits, a general rule of the scope (every adult / a band-less child rule), an
// inherited pricing-policy rule, or the engine default (adults ×1; no child default, ADR-007). It
// does not re-rank rules across scopes or levels (occupancy precedence v2): where that matters, the
// server's resolved line and the precedence note are the truth (§3.6.2). No runtime imports except
// each other and lib/shorthand.ts.
import type { ShErrorCode, ShResult } from "../lib/shorthand.ts"
import type { Tables } from "../lib/tables.ts"
import type { Row } from "../lib/types.ts"
import { bandCode, type BandLike } from "./bands.ts"
import { ALL_PERIODS, canonValue, type Basis } from "./model.ts"
import { int, isSet, newRow, str } from "./rows.ts"

export type OccTarget = "ADULT" | "CHILD" | "COMBINATION"

/** A ladder row's slot: which rule rows it reads and writes (plus `period_code` = the column). */
export interface OccIdentity {
  target: OccTarget
  /** 0 = any position. */
  position: number
  /** "" = any band. */
  age_band: string
  /** Canonical "a+c" ("" = none). */
  combination: string
  /** "" = all rooms. */
  room_type: string
}

/** An occupancy rule as the server reports an inherited one (price_matrix inherited_rules, GAP-3):
 * the TEX Occupancy Rule fields plus its `source` ("Hotel policy", …). */
export type OccRuleLike = Readonly<Record<string, string | number | boolean | null | undefined>>

/** The engine default the server reports (price_matrix occupancy_defaults, GAP-3). */
export interface OccDefault {
  rule_id?: string
  target?: string
  op: string
  value: string
  source?: string
  note?: string
}

export interface LadderOptions {
  /** The largest effective max_adults of the rooms in scope (server capacity, GAP-3). */
  maxAdults: number
  /** ROOM basis: the effective included adults of the scoped room (positions up to it are included). */
  includedAdults?: number
  /** The version's bands, or the inherited ones when it has none. */
  bands: readonly BandLike[]
  /** Inherited pricing-policy rules (non-version origin). */
  inherited?: readonly OccRuleLike[]
  defaults?: { adult: OccDefault | null; child: OccDefault | null } | null
}

export type LadderCellState =
  | "rule" // the slot's own All-periods rule
  | "period-override" // the slot's own rule for this period (◆ OVERRIDE)
  | "inherited" // no own period rule: the slot's All-periods rule applies (↳)
  | "inherit-rule" // an own INHERIT row (the engine skips it; `source`/`value` say what applies)
  | "general" // a general rule of the scope (every adult, any child band)
  | "policy" // an inherited pricing-policy rule (shown with its source)
  | "default" // no rule: the engine's adult default (×1.00 default)
  | "missing" // no rule for a child band: not sellable (NO_CHILD_RULE)
  | "included" // ROOM basis: an adult included in the room price

export interface LadderCell {
  state: LadderCellState
  /** The cell's own row, if any. */
  rule: Row | null
  /** The rule that prices the slot (own, inherited, general or policy), if any. */
  source: Row | OccRuleLike | null
  /** Its op and value as served/stored strings (the default's for "default"); null when none. */
  value: { op: string; value: string } | null
}

export type LadderRowKind = "single" | "adults_base" | "adult" | "adult_any" | "band" | "child" | "child_any"

export interface LadderRow {
  id: string
  kind: LadderRowKind
  /** Adult or child position (0 for rows without one). */
  position: number
  /** The band code (band and child rows; "" otherwise). */
  band: string
  /** The rows it edits; null for the read-only BASE pair. */
  identity: OccIdentity | null
  editable: boolean
  /** A band code no band defines (OCC_UNKNOWN_BAND). */
  unknownBand: boolean
  cells: Record<string, LadderCell>
}

export interface LadderModel {
  rows: LadderRow[]
  /** "" (All periods) then the period codes in table order. */
  periods: string[]
  counts: { periodOverrides: number }
}

/** "2+1" from "2A+1C", " 2 + 1 ", …; "*" for any ("2+" → "2+*"), as contracts.parse_combination
 * reads it; "" for blank. Unreadable text comes back upper-cased and without spaces. */
export function canonCombination(text: unknown): string {
  const t = str(text).replace(/\s+/g, "").toUpperCase().replace(/[AC]/g, "")
  if (!t) return ""
  const m = /^([0-9]+|\*)?\+([0-9]+|\*)?$/.exec(t)
  if (!m) return t
  const part = (x: string | undefined) => (x === undefined || x === "*" ? "*" : String(int(x)))
  return `${part(m[1])}+${part(m[2])}`
}

interface Norm {
  target: string
  position: number
  age_band: string
  combination: string
  room_type: string
  period: string
  op: string
  is_override: boolean
  src: Row | OccRuleLike
}

function norm(r: Row | OccRuleLike): Norm {
  return {
    target: str(r.target).toUpperCase(),
    position: int(r.position),
    age_band: str(r.age_band).toUpperCase(),
    combination: canonCombination(r.combination),
    room_type: str(r.room_type),
    period: str(r.period_code),
    op: str(r.op),
    is_override: isSet(r.is_override),
    src: r,
  }
}

function sameSlot(n: Norm, id: OccIdentity): boolean {
  return n.target === id.target && n.position === id.position && n.age_band === id.age_band && n.combination === id.combination && n.room_type === id.room_type
}

/** The row a cell shows: a non-INHERIT "Always wins" row, else a non-INHERIT row, else an INHERIT row. */
function pick(rows: Norm[], allowInherit = true): Norm | null {
  return rows.find((n) => n.op !== "INHERIT" && n.is_override) ?? rows.find((n) => n.op !== "INHERIT") ?? (allowInherit ? (rows[0] ?? null) : null)
}

const valueOf = (r: Row | OccRuleLike): { op: string; value: string } => ({ op: str(r.op), value: str(r.value) })

type SlotKind = "adult" | "child"

interface Ctx {
  version: Norm[]
  inherited: Norm[]
  defaults: LadderOptions["defaults"]
}

function at(rows: Norm[], id: OccIdentity, period: string): Norm[] {
  return rows.filter((n) => n.period === period && sameSlot(n, id))
}

/** What prices a slot when it has no own (non-INHERIT) rule in this column. */
function fallback(ctx: Ctx, id: OccIdentity, general: readonly OccIdentity[], period: string, slot: SlotKind): Omit<LadderCell, "rule"> {
  const periods = period === ALL_PERIODS ? [ALL_PERIODS] : [period, ALL_PERIODS]
  if (period !== ALL_PERIODS) {
    const all = pick(at(ctx.version, id, ALL_PERIODS), false)
    if (all) return { state: "inherited", source: all.src, value: valueOf(all.src) }
  }
  for (const g of general)
    for (const p of periods) {
      const hit = pick(at(ctx.version, g, p), false)
      if (hit) return { state: "general", source: hit.src, value: valueOf(hit.src) }
    }
  for (const cand of [id, ...general])
    for (const p of periods) {
      const hit = pick(at(ctx.inherited, cand, p), false)
      if (hit) return { state: "policy", source: hit.src, value: valueOf(hit.src) }
    }
  if (slot === "child") {
    const child = ctx.defaults?.child
    return child ? { state: "default", source: null, value: { op: child.op, value: child.value } } : { state: "missing", source: null, value: null }
  }
  const adult = ctx.defaults?.adult
  return { state: "default", source: null, value: adult ? { op: adult.op, value: adult.value } : null }
}

function cellOf(ctx: Ctx, id: OccIdentity, general: readonly OccIdentity[], period: string, slot: SlotKind, included: boolean): LadderCell {
  const own = pick(at(ctx.version, id, period))
  if (included) return { state: "included", rule: own ? (own.src as Row) : null, source: null, value: null }
  if (own && own.op !== "INHERIT") return { state: period === ALL_PERIODS ? "rule" : "period-override", rule: own.src as Row, source: own.src, value: valueOf(own.src) }
  const fb = fallback(ctx, id, general, period, slot)
  return own ? { ...fb, state: "inherit-rule", rule: own.src as Row } : { ...fb, rule: null }
}

const identity = (target: OccTarget, position: number, age_band: string, combination: string, room_type: string): OccIdentity => ({ target, position, age_band, combination, room_type })

/** The ladder (§3.6.2) for one rooms scope (null = All rooms) and basis, with a cell per column. */
export function ladderModel(tables: Pick<Tables, "periods" | "occupancy_rules">, scopeRoom: string | null, basis: Basis, opts: LadderOptions): LadderModel {
  const scope = str(scopeRoom)
  const periods = [ALL_PERIODS, ...tables.periods.map((p) => str(p.period_code)).filter(Boolean)]
  const inScope = (n: Norm) => n.room_type === scope
  const ctx: Ctx = { version: tables.occupancy_rules.map(norm).filter(inScope), inherited: (opts.inherited ?? []).map(norm).filter(inScope), defaults: opts.defaults }
  const plain = [...ctx.version, ...ctx.inherited].filter((n) => !n.combination)
  const rows: LadderRow[] = []
  const add = (kind: LadderRowKind, position: number, band: string, id: OccIdentity | null, general: readonly OccIdentity[], slot: SlotKind, flags: { editable?: boolean; included?: boolean; unknownBand?: boolean } = {}) => {
    const probe = id ?? identity("ADULT", 1, "", "", scope)
    const cells: Record<string, LadderCell> = {}
    for (const p of periods) {
      const c = cellOf(ctx, probe, general, p, slot, Boolean(flags.included))
      cells[p] = id ? c : { ...c, rule: null }
    }
    rows.push({ id: `${kind}:${position}:${band}`, kind, position, band, identity: id, editable: flags.editable ?? id !== null, unknownBand: Boolean(flags.unknownBand), cells })
  }

  const anyAdult = identity("ADULT", 0, "", "", scope)
  const anyChild = identity("CHILD", 0, "", "", scope)

  // 1 Adult (single use): the whole combination 1+0, or the "also when children travel" variant
  const single = identity("COMBINATION", 0, "", "1+0", scope)
  const singleAlt = identity("ADULT", 1, "", "1+*", scope)
  const all = [...ctx.version, ...ctx.inherited]
  const singleId = !all.some((n) => sameSlot(n, single)) && all.some((n) => sameSlot(n, singleAlt)) ? singleAlt : single
  add("single", 0, "", singleId, [], "adult")

  // adults: PERSON shows the BASE pair (positions 1–2, read-only, default) until a rule names one of them
  const included = basis === "ROOM" ? Math.max(1, opts.includedAdults ?? 1) : 0
  const adultPositions = plain.filter((n) => n.target === "ADULT" && !n.age_band).map((n) => n.position)
  const splitPair = basis === "ROOM" || adultPositions.some((p) => p === 1 || p === 2)
  if (!splitPair) add("adults_base", 0, "", null, [anyAdult], "adult", { editable: false })
  const maxPos = Math.max(opts.maxAdults, ...adultPositions, splitPair ? 2 : 0)
  for (let pos = splitPair ? 1 : 3; pos <= maxPos; pos++) {
    const inc = pos <= included
    add("adult", pos, "", identity("ADULT", pos, "", "", scope), [anyAdult], "adult", { included: inc, editable: !inc })
  }
  if (plain.some((n) => n.target === "ADULT" && n.position === 0 && !n.age_band)) add("adult_any", 0, "", anyAdult, [], "adult")

  // children: one row per band (labels come from the band), then position rows, then band-less rules
  const known = opts.bands.map(bandCode).filter(Boolean)
  const bandCodes = [...new Set(known)]
  for (const n of plain) if (n.target === "CHILD" && n.position === 0 && n.age_band && !bandCodes.includes(n.age_band)) bandCodes.push(n.age_band)
  for (const code of bandCodes) add("band", 0, code, identity("CHILD", 0, code, "", scope), [anyChild], "child", { unknownBand: !known.includes(code) })
  const bandRank = (b: string) => (b ? (bandCodes.includes(b) ? bandCodes.indexOf(b) : bandCodes.length) : bandCodes.length + 1)
  const childPos = new Map<string, { position: number; band: string }>()
  for (const n of plain) if (n.target === "CHILD" && n.position > 0) childPos.set(`${n.position}|${n.age_band}`, { position: n.position, band: n.age_band })
  const ordered = [...childPos.values()].sort((a, b) => a.position - b.position || bandRank(a.band) - bandRank(b.band) || (a.band < b.band ? -1 : a.band > b.band ? 1 : 0))
  for (const c of ordered) {
    const general = c.band ? [identity("CHILD", c.position, "", "", scope), identity("CHILD", 0, c.band, "", scope), anyChild] : [anyChild]
    add("child", c.position, c.band, identity("CHILD", c.position, c.band, "", scope), general, "child", { unknownBand: Boolean(c.band) && !known.includes(c.band) })
  }
  if (plain.some((n) => n.target === "CHILD" && n.position === 0 && !n.age_band)) add("child_any", 0, "", anyChild, [], "child")

  let periodOverrides = 0
  for (const row of rows) for (const p of periods) if (row.cells[p].state === "period-override") periodOverrides += 1
  return { rows, periods, counts: { periodOverrides } }
}

export type OccEntryResult = { tables: Tables } | { error: ShErrorCode }

/** Applies a parsed `occupancy` entry to a ladder cell: the op and value are stored as a rule on
 * the row's identity and the column's period (relative ops are always rules here); clear removes
 * the cell's rows. The cell keeps one row: the one it showed is updated in place (keeping its key,
 * "Always wins" flag and note), other rows of the same slot and period are removed. A period entry
 * equal to the All-periods rule is stored, not dropped: occupancy precedence ranks a period rule
 * above rules of other scopes, so dropping it could change a price. */
export function applyOccEntry(tables: Tables, id: OccIdentity, period: string, parsed: ShResult): OccEntryResult {
  if (!parsed.ok) return { error: parsed.code }
  if (parsed.kind === "base") return { error: "SYNTAX" }
  const same = tables.occupancy_rules.map(norm).filter((n) => n.period === period && sameSlot(n, id))
  const rows = same.map((n) => n.src as Row)
  if (parsed.kind === "clear") {
    if (!rows.length) return { tables }
    return { tables: { ...tables, occupancy_rules: tables.occupancy_rules.filter((r) => !rows.includes(r)) } }
  }
  const { op, value } = parsed
  if (!rows.length) {
    const row = newRow("occupancy_rules", {
      target: id.target,
      position: id.position,
      age_band: id.age_band,
      combination: id.combination,
      room_type: id.room_type,
      period_code: period,
      op,
      value,
      is_override: 0,
      note: "",
    })
    return { tables: { ...tables, occupancy_rules: [...tables.occupancy_rules, row] } }
  }
  const keep = (pick(same) as Norm).src as Row
  if (rows.length === 1 && str(keep.op) === op && canonValue(keep.value) === canonValue(value)) return { tables }
  const out: Row[] = []
  for (const r of tables.occupancy_rules) {
    if (r === keep) out.push({ ...r, op, value })
    else if (!rows.includes(r)) out.push(r)
  }
  return { tables: { ...tables, occupancy_rules: out } }
}

// ─── special combinations (§3.7) ─────────────────────────────────────────

/** A room's effective capacity (price_matrix rooms[].capacity, GAP-3). */
export interface CapacityLike {
  room_type?: string
  max_adults: number
  max_children: number
  max_occupants: number
  min_adults: number
}

export interface ValidCombination {
  adults: number
  children: number
  /** The rooms (with a room_type) that can host it. */
  rooms: string[]
}

/** The party combinations the rooms can host, exactly like the publish sweep (validate._sweep):
 * adults from max(1, min_adults) to max_adults, children from 0 to max_children, a + c ≤
 * max_occupants; the union over the rooms, adults-only first, then by adults and children. */
export function validCombinations(capacities: readonly CapacityLike[]): ValidCombination[] {
  const found = new Map<string, ValidCombination>()
  for (const cap of capacities) {
    for (let a = Math.max(1, int(cap.min_adults)); a <= int(cap.max_adults); a++) {
      for (let c = 0; c <= int(cap.max_children); c++) {
        if (a + c > int(cap.max_occupants)) continue
        const key = `${a}+${c}`
        const entry = found.get(key) ?? { adults: a, children: c, rooms: [] }
        const room = str(cap.room_type)
        if (room && !entry.rooms.includes(room)) entry.rooms.push(room)
        found.set(key, entry)
      }
    }
  }
  return [...found.values()].sort((x, y) => Number(x.children > 0) - Number(y.children > 0) || x.adults - y.adults || x.children - y.children)
}

export interface CombinationSpec {
  adults: number | "*"
  children: number | "*"
  /** Rooms in scope ([] = all rooms, room_type blank). */
  rooms: readonly string[]
  /** Periods in scope ([] = all periods, period_code blank). */
  periods: readonly string[]
  childRules?: readonly { position: number; age_band: string; op: string; value: string }[]
  adultRules?: readonly { position: number; op: string; value: string }[]
  /** A whole-stay price for the combination (target COMBINATION). */
  whole?: { op: string; value: string } | null
  isOverride?: boolean
  /** `_key`s of the rows the edited card held; they are replaced. */
  replace?: readonly string[]
}

/** Writes a special combination as ordinary TEX Occupancy Rule rows (§3.7.3): for each room ×
 * period in scope, one CHILD row per child rule, one ADULT row per adult rule and one COMBINATION
 * row for a whole-stay price, all with combination "a+c" ("*" = any). Editing a card replaces
 * exactly its rows (one history entry). */
export function persistCombination(tables: Tables, spec: CombinationSpec): { tables: Tables; counts: { removed: number; added: number } } {
  const combination = `${spec.adults}+${spec.children}`
  const replace = new Set(spec.replace ?? [])
  const kept = tables.occupancy_rules.filter((r) => !replace.has(r._key))
  const rooms = spec.rooms.length ? spec.rooms : [""]
  const periods = spec.periods.length ? spec.periods : [ALL_PERIODS]
  const is_override = spec.isOverride ? 1 : 0
  const added: Row[] = []
  for (const room_type of rooms)
    for (const period_code of periods) {
      const base = { combination, room_type, period_code, is_override, note: "" }
      for (const c of spec.childRules ?? []) added.push(newRow("occupancy_rules", { ...base, target: "CHILD", position: c.position, age_band: c.age_band, op: c.op, value: c.value }))
      for (const a of spec.adultRules ?? []) added.push(newRow("occupancy_rules", { ...base, target: "ADULT", position: a.position, age_band: "", op: a.op, value: a.value }))
      if (spec.whole) added.push(newRow("occupancy_rules", { ...base, target: "COMBINATION", position: 0, age_band: "", op: spec.whole.op, value: spec.whole.value }))
    }
  return { tables: { ...tables, occupancy_rules: [...kept, ...added] }, counts: { removed: tables.occupancy_rules.length - kept.length, added: added.length } }
}

/** Removes a card's rows. */
export function removeCombination(tables: Tables, card: Pick<CombinationCard, "keys">): { tables: Tables; counts: { removed: number } } {
  const keys = new Set(card.keys)
  const rest = tables.occupancy_rules.filter((r) => !keys.has(r._key))
  const removed = tables.occupancy_rules.length - rest.length
  return { tables: removed ? { ...tables, occupancy_rules: rest } : tables, counts: { removed } }
}

export interface CardRule {
  target: string
  position: number
  age_band: string
  op: string
  value: string
  note: string
}

export interface CombinationCard {
  id: string
  combination: string
  /** null = any ("*"). */
  adults: number | null
  children: number | null
  isOverride: boolean
  /** "" = all rooms; rooms in `rooms` table order. */
  rooms: string[]
  /** "" = all periods; periods in `periods` table order. */
  periods: string[]
  rules: CardRule[]
  /** `_key`s of every row of the card. */
  keys: string[]
  /** Scoped to specific periods (◆). */
  periodScoped: boolean
  /** The structured builder can edit it (no rule carries a note). */
  expressible: boolean
}

/** A single-use row the ladder shows ("1 Adult (single use)"), so a screen can leave it out of the cards. */
export function isSingleUseRow(row: Row): boolean {
  const n = norm(row)
  return (n.target === "COMBINATION" && n.combination === "1+0") || (n.target === "ADULT" && n.position === 1 && n.combination === "1+*")
}

const TARGET_ORDER: Record<string, number> = { ADULT: 0, CHILD: 1, COMBINATION: 2 }

function countOf(part: string): number | null {
  return part === "*" || part === "" ? null : int(part)
}

/** Groups the rows with a combination into cards (§3.7.4): rows of the same combination, room,
 * period and override flag form a cell; cells with the same combination, flag and rules (target,
 * position, band, op, value, note; values canonical) form a card over rooms R × periods P, which
 * is split by room when its cells are not exactly R × P. Cards are ordered by adults, children,
 * then room and period table order (any "*" after numbers). */
export function groupCombinations(tables: Pick<Tables, "rooms" | "periods" | "occupancy_rules">): CombinationCard[] {
  const roomIdx = new Map<string, number>([["", -1]])
  tables.rooms.forEach((r, i) => roomIdx.has(str(r.room_type)) || roomIdx.set(str(r.room_type), i))
  const periodIdx = new Map<string, number>([["", -1]])
  tables.periods.forEach((p, i) => periodIdx.has(str(p.period_code)) || periodIdx.set(str(p.period_code), i))
  const byOrder = (idx: Map<string, number>) => (a: string, b: string) => (idx.get(a) ?? 1e9) - (idx.get(b) ?? 1e9) || (a < b ? -1 : a > b ? 1 : 0)
  const roomSort = byOrder(roomIdx)
  const periodSort = byOrder(periodIdx)

  // 1. cells
  const cells = new Map<string, { combination: string; room: string; period: string; isOverride: boolean; rows: Row[]; rules: CardRule[] }>()
  for (const r of tables.occupancy_rules) {
    const n = norm(r)
    if (!n.combination) continue
    const key = JSON.stringify([n.combination, n.room_type, n.period, n.is_override])
    const cell = cells.get(key) ?? { combination: n.combination, room: n.room_type, period: n.period, isOverride: n.is_override, rows: [], rules: [] }
    cell.rows.push(r)
    cell.rules.push({ target: n.target, position: n.position, age_band: n.age_band, op: n.op, value: canonValue(r.value), note: str(r.note) })
    cells.set(key, cell)
  }
  const ruleSort = (a: CardRule, b: CardRule) =>
    (TARGET_ORDER[a.target] ?? 9) - (TARGET_ORDER[b.target] ?? 9) ||
    a.position - b.position ||
    (a.age_band < b.age_band ? -1 : a.age_band > b.age_band ? 1 : 0) ||
    (JSON.stringify(a) < JSON.stringify(b) ? -1 : JSON.stringify(a) > JSON.stringify(b) ? 1 : 0)

  // 2. merge cells with the same combination, flag and signature
  const groups = new Map<string, { combination: string; isOverride: boolean; rules: CardRule[]; cells: { room: string; period: string; rows: Row[] }[] }>()
  for (const cell of cells.values()) {
    const rules = [...cell.rules].sort(ruleSort)
    const key = JSON.stringify([cell.combination, cell.isOverride, rules])
    const g = groups.get(key) ?? { combination: cell.combination, isOverride: cell.isOverride, rules, cells: [] }
    g.cells.push({ room: cell.room, period: cell.period, rows: cell.rows })
    groups.set(key, g)
  }

  // 3. one card per cross product, else one per room
  const cards: CombinationCard[] = []
  const card = (g: { combination: string; isOverride: boolean; rules: CardRule[] }, part: { room: string; period: string; rows: Row[] }[]): CombinationCard => {
    const rooms = [...new Set(part.map((c) => c.room))].sort(roomSort)
    const periods = [...new Set(part.map((c) => c.period))].sort(periodSort)
    const keySet = new Set(part.flatMap((c) => c.rows.map((r) => r._key)))
    const keys = tables.occupancy_rules.filter((r) => keySet.has(r._key)).map((r) => r._key)
    const [a, c] = g.combination.split("+")
    return {
      id: JSON.stringify([g.combination, g.isOverride, rooms, periods, g.rules]),
      combination: g.combination,
      adults: countOf(a ?? ""),
      children: countOf(c ?? ""),
      isOverride: g.isOverride,
      rooms,
      periods,
      rules: g.rules,
      keys,
      periodScoped: periods.some((p) => p !== ALL_PERIODS),
      expressible: g.rules.every((r) => !r.note),
    }
  }
  for (const g of groups.values()) {
    const rooms = new Set(g.cells.map((c) => c.room))
    const periods = new Set(g.cells.map((c) => c.period))
    if (g.cells.length === rooms.size * periods.size) cards.push(card(g, g.cells))
    else for (const room of rooms) cards.push(card(g, g.cells.filter((c) => c.room === room)))
  }

  // 4. order
  const count = (n: number | null) => (n === null ? Number.MAX_SAFE_INTEGER : n)
  const first = (list: string[], idx: Map<string, number>) => Math.min(...list.map((x) => idx.get(x) ?? 1e9))
  return cards.sort(
    (x, y) =>
      count(x.adults) - count(y.adults) ||
      count(x.children) - count(y.children) ||
      first(x.rooms, roomIdx) - first(y.rooms, roomIdx) ||
      first(x.periods, periodIdx) - first(y.periods, periodIdx) ||
      (x.id < y.id ? -1 : x.id > y.id ? 1 : 0),
  )
}
