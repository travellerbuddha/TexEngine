// Occupancy & child pricing in the workspace (PRICING_WORKSPACE_UX.md §3.6, §3.7; D8, D12): the
// slot ladder projection over `occupancy_rules`, cell entries, valid party combinations and the
// special-combination cards. Every gesture writes ordinary TEX Occupancy Rule rows; nothing here
// prices anything (resolved totals come from the server's price_matrix parties, GAP-2b).
//
// The ladder is a per-scope rule editor: the "All rooms" scope edits the rules with room_type blank,
// a room scope the rules naming that room. A cell shows its own rule; without one, the rule the
// engine would use for the slot among the plain rules that reach the scope. For a room these are its
// own rules and the All-rooms rules (a blank room_type matches every room), version and inherited
// pricing-policy rules alike, ranked as occupancy.specificity ranks them (CASCADE, `engineRank`).
// That rule is the slot's All-periods rule (↳), a general rule of the scope (every adult, a band-less
// child rule), a rule of All rooms, or a policy rule; only when none applies does the cell show the
// engine default (adults ×1; no child default, ADR-007: "not sellable"). Special combinations are
// not ranked into the cells: the precedence note marks them, and the server's resolved line is the
// truth for a party (§3.6.2). No runtime imports except each other and lib/shorthand.ts.
import {
  editText,
  isAmountOp,
  normaliseDecimal,
  OPS_BY_CONTEXT,
  parseShorthand,
  type ShErrorCode,
  type ShFormatOptions,
  type ShOp,
  type ShResult,
} from "../lib/shorthand.ts"
import type { Tables } from "../lib/tables.ts"
import type { InheritedOccupancyRule, Row } from "../lib/types.ts"
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
  /** ROOM basis: what extra adults and children are priced from (the version's
   * room_basis_extra_unit: PER_PERSON_SHARE, the default, or ROOM_PRICE). */
  extraUnit?: string
}

/** What a row's relative rules are applied to (§3.11), for its reading line and default text:
 * the base person price (PERSON), the per-person share of the room price (ROOM, room ÷ included
 * adults) or the room price (ROOM: a single-use combination, or ROOM_PRICE extra units). */
export type LadderUnit = "person" | "person_share" | "room"

export type LadderCellState =
  | "rule" // the slot's own All-periods rule
  | "period-override" // the slot's own rule for this period (◆ OVERRIDE)
  | "inherited" // no own period rule: the slot's All-periods rule applies (↳)
  | "inherit-rule" // an own INHERIT row (the engine skips it; `source`/`value` say what applies)
  | "general" // a general rule of the scope (every adult, any child band)
  | "all-rooms" // a room scope: a version rule of All rooms (the slot's or a general one) applies
  | "policy" // an inherited pricing-policy rule (shown with its source; its room_type says the scope)
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
  /** A child row of an infant band: a rule naming the band prices it before any band-less rule (G-31). */
  infant: boolean
  /** What the row's relative rules (and the adult default) are applied to. */
  unit: LadderUnit
  /** The single-use row: a rule of its form that reaches the scope is not the scope's own (a rule of
   * All rooms seen from a room, or a pricing policy's), so switching the row's form would leave that
   * rule applying (S16 re-review 3). False on every other row. */
  foreign: boolean
  cells: Record<string, LadderCell>
}

export interface LadderModel {
  rows: LadderRow[]
  /** "" (All periods) then the period codes in table order. */
  periods: string[]
  counts: { periodOverrides: number }
  basis: Basis
  /** ROOM basis: the adults the room price covers (positions up to it are included); 0 for PERSON. */
  includedAdults: number
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
  /** An inherited pricing-policy rule (price_matrix inherited_rules), not a row of the version. */
  policy: boolean
  src: Row | OccRuleLike
}

function norm(r: Row | OccRuleLike, policy = false): Norm {
  return {
    target: str(r.target).toUpperCase(),
    position: int(r.position),
    age_band: str(r.age_band).toUpperCase(),
    combination: canonCombination(r.combination),
    room_type: str(r.room_type),
    period: str(r.period_code),
    op: str(r.op),
    is_override: isSet(r.is_override),
    policy,
    src: r,
  }
}

function sameSlot(n: Norm, id: OccIdentity): boolean {
  return n.target === id.target && n.position === id.position && n.age_band === id.age_band && n.combination === id.combination && n.room_type === id.room_type
}

/** The same guest slot, in any rooms scope. */
function sameGuest(n: Norm, id: OccIdentity): boolean {
  return n.target === id.target && n.position === id.position && n.age_band === id.age_band && n.combination === id.combination
}

/** The row a cell shows: a non-INHERIT "Always wins" row, else a non-INHERIT row, else an INHERIT row. */
function pick(rows: Norm[], allowInherit = true): Norm | null {
  return rows.find((n) => n.op !== "INHERIT" && n.is_override) ?? rows.find((n) => n.op !== "INHERIT") ?? (allowInherit ? (rows[0] ?? null) : null)
}

const valueOf = (r: Row | OccRuleLike): { op: string; value: string } => ({ op: str(r.op), value: str(r.value) })

type SlotKind = "adult" | "child"

interface Ctx {
  /** the rooms scope ("" = All rooms) */
  scope: string
  /** the version's rules that reach the scope: its own and, for a room, All rooms' */
  version: Norm[]
  /** the inherited pricing-policy rules that reach the scope, likewise */
  inherited: Norm[]
  defaults: LadderOptions["defaults"]
}

function at(rows: Norm[], id: OccIdentity, period: string): Norm[] {
  return rows.filter((n) => n.period === period && sameSlot(n, id))
}

// Rule levels and policy weights as kamra/tex/pricing/enums.Level and inherit.weight_of number them.
const LEVEL = { GLOBAL: 0, HOTEL: 1, MARKET: 2, VERSION: 4, ROOM: 5, PERIOD: 6, COMBINATION: 7, OVERRIDE: 8 } as const
const POLICY_WEIGHT: Record<string, number> = { global: 0, hotel: 1, market: 2, "hotel+market": 3 }

/** A rule's origin (base_level, scope_weight): a version rule, or the policy scope its source names
 * (inherit.level_for; an unreadable source ranks as a global policy). */
function originOf(n: Norm): [number, number] {
  if (!n.policy) return [LEVEL.VERSION, 0]
  const w = POLICY_WEIGHT[policySource(n.src.source)?.scope ?? ""] ?? 0
  return [w & 2 ? LEVEL.MARKET : w & 1 ? LEVEL.HOTEL : LEVEL.GLOBAL, w]
}

/** occupancy.specificity (CASCADE) of a rule that matches a slot; the higher wins: an infant's band
 * first (G-31), then origin (G-30: version > hotel + market > market > hotel > global), level
 * (override > combination > period > room > none), qualifiers (period, room, exact combination)
 * and the slot (position, band). Integers only. */
function engineRank(n: Norm, infant: boolean): number[] {
  const [base, weight] = originOf(n)
  const [a, c] = n.combination.split("+")
  const combo = n.combination !== ""
  const level = n.is_override ? LEVEL.OVERRIDE : combo ? LEVEL.COMBINATION : n.period ? LEVEL.PERIOD : n.room_type ? LEVEL.ROOM : base
  return [infant && n.age_band ? 1 : 0, base, weight, level, n.period ? 1 : 0, n.room_type ? 1 : 0, combo && a !== "*" && c !== "*" ? 1 : 0, n.position ? 1 : 0, n.age_band ? 1 : 0]
}

function outranks(x: readonly number[], y: readonly number[]): boolean {
  for (let i = 0; i < x.length; i++) if (x[i] !== y[i]) return x[i] > y[i]
  return false
}

/** What prices a slot when it has no own (non-INHERIT) rule in this column: the rule the engine
 * would pick (engineRank; the first of equal ones) among the version and policy rules of the slot
 * (`id`) or of its general slots (`general`: every adult, a band-less child, …) that reach the scope
 * in this period. It is the slot's All-periods rule (inherited), a general rule of the scope, a
 * rule of All rooms (a room scope) or a policy rule; with none, the engine default. */
function fallback(ctx: Ctx, id: OccIdentity, general: readonly OccIdentity[], period: string, slot: SlotKind, infant: boolean): Omit<LadderCell, "rule"> {
  const guests = [id, ...general]
  let best: Norm | null = null
  let bestRank: number[] = []
  for (const n of [...ctx.version, ...ctx.inherited]) {
    if (n.op === "INHERIT" || (n.period && n.period !== period) || !guests.some((g) => sameGuest(n, g))) continue
    const rank = engineRank(n, infant)
    if (best && !outranks(rank, bestRank)) continue
    best = n
    bestRank = rank
  }
  if (best) {
    const state: LadderCellState = best.policy ? "policy" : best.room_type !== ctx.scope ? "all-rooms" : sameGuest(best, id) ? "inherited" : "general"
    // a policy rule whose formula the viewer may not read has no value (price_matrix `hidden`)
    return { state, source: best.src, value: best.policy && isSet(best.src.hidden) ? null : valueOf(best.src) }
  }
  if (slot === "child") {
    const child = ctx.defaults?.child
    return child ? { state: "default", source: null, value: { op: child.op, value: child.value } } : { state: "missing", source: null, value: null }
  }
  const adult = ctx.defaults?.adult
  return { state: "default", source: null, value: adult ? { op: adult.op, value: adult.value } : null }
}

function cellOf(ctx: Ctx, id: OccIdentity, general: readonly OccIdentity[], period: string, slot: SlotKind, included: boolean, infant: boolean): LadderCell {
  const own = pick(at(ctx.version, id, period))
  if (included) return { state: "included", rule: own ? (own.src as Row) : null, source: null, value: null }
  if (own && own.op !== "INHERIT") return { state: period === ALL_PERIODS ? "rule" : "period-override", rule: own.src as Row, source: own.src, value: valueOf(own.src) }
  const fb = fallback(ctx, id, general, period, slot, infant)
  return own ? { ...fb, state: "inherit-rule", rule: own.src as Row } : { ...fb, rule: null }
}

const identity = (target: OccTarget, position: number, age_band: string, combination: string, room_type: string): OccIdentity => ({ target, position, age_band, combination, room_type })

/** The ladder (§3.6.2) for one rooms scope (null = All rooms) and basis, with a cell per column. A
 * room scope's rows also follow the All-rooms rules that reach it (a rule for adult 1 splits the
 * BASE pair, a child position rule gets its row), and its cells show them (`all-rooms`). */
export function ladderModel(tables: Pick<Tables, "periods" | "occupancy_rules">, scopeRoom: string | null, basis: Basis, opts: LadderOptions): LadderModel {
  const scope = str(scopeRoom)
  const periods = [ALL_PERIODS, ...tables.periods.map((p) => str(p.period_code)).filter(Boolean)]
  // a blank room_type matches every room (occupancy.qualifiers_match)
  const reaches = (n: Norm) => n.room_type === scope || n.room_type === ""
  // a special combination's rules are the card's (§3.7.4, D8): the single-use row, the only row that
  // reads rules with a combination, neither shows nor counts them (S16 re-review 3)
  const version = tables.occupancy_rules.map((r) => norm(r))
  const inherited = (opts.inherited ?? []).map((r) => norm(r, true))
  const cards = new Set([...cardRows(version), ...cardRows(inherited)])
  const ctx: Ctx = {
    scope,
    version: version.filter((n) => reaches(n) && !cards.has(n.src)),
    inherited: inherited.filter((n) => reaches(n) && !cards.has(n.src)),
    defaults: opts.defaults,
  }
  const all = [...ctx.version, ...ctx.inherited]
  const plain = all.filter((n) => !n.combination)
  const infantBands = new Set(opts.bands.filter((b) => isSet(b.is_infant)).map(bandCode).filter(Boolean))
  const rows: LadderRow[] = []
  const slotUnit: LadderUnit = basis === "PERSON" ? "person" : str(opts.extraUnit) === "ROOM_PRICE" ? "room" : "person_share"
  const add = (
    kind: LadderRowKind,
    position: number,
    band: string,
    id: OccIdentity | null,
    general: readonly OccIdentity[],
    slot: SlotKind,
    flags: { editable?: boolean; included?: boolean; unknownBand?: boolean; infant?: boolean } = {},
  ) => {
    const probe = id ?? identity("ADULT", 1, "", "", scope)
    const cells: Record<string, LadderCell> = {}
    for (const p of periods) {
      const c = cellOf(ctx, probe, general, p, slot, Boolean(flags.included), Boolean(flags.infant))
      cells[p] = id ? c : { ...c, rule: null }
    }
    // a whole-combination rule replaces (or adjusts) the unit itself: the room price under ROOM
    const unit = basis === "ROOM" && id?.target === "COMBINATION" ? "room" : slotUnit
    const foreign = kind === "single" && id !== null && all.some((n) => sameGuest(n, id) && (n.policy || n.room_type !== scope))
    rows.push({
      id: `${kind}:${position}:${band}`,
      kind,
      position,
      band,
      identity: id,
      editable: flags.editable ?? id !== null,
      unknownBand: Boolean(flags.unknownBand),
      infant: Boolean(flags.infant),
      unit,
      foreign,
      cells,
    })
  }

  const anyAdult = identity("ADULT", 0, "", "", scope)
  const anyChild = identity("CHILD", 0, "", "", scope)

  // 1 Adult (single use): the whole combination 1+0 (`single:0:`) and the "also when children
  // travel" form, Adult 1 of 1+* (`single:1:`): a row for each form that a rule reaching the scope
  // has (both when both do: the engine applies both, and no rule is left unshown, S16 re-review 2),
  // else the whole combination
  const single = identity("COMBINATION", 0, "", "1+0", scope)
  const singleAlt = identity("ADULT", 1, "", "1+*", scope)
  const hasWhole = all.some((n) => sameGuest(n, single))
  const hasAlt = all.some((n) => sameGuest(n, singleAlt))
  if (hasWhole || !hasAlt) add("single", 0, "", single, [], "adult")
  if (hasAlt) add("single", 1, "", singleAlt, [], "adult")

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
  for (const code of bandCodes) add("band", 0, code, identity("CHILD", 0, code, "", scope), [anyChild], "child", { unknownBand: !known.includes(code), infant: infantBands.has(code) })
  const bandRank = (b: string) => (b ? (bandCodes.includes(b) ? bandCodes.indexOf(b) : bandCodes.length) : bandCodes.length + 1)
  const childPos = new Map<string, { position: number; band: string }>()
  for (const n of plain) if (n.target === "CHILD" && n.position > 0) childPos.set(`${n.position}|${n.age_band}`, { position: n.position, band: n.age_band })
  const ordered = [...childPos.values()].sort((a, b) => a.position - b.position || bandRank(a.band) - bandRank(b.band) || (a.band < b.band ? -1 : a.band > b.band ? 1 : 0))
  for (const c of ordered) {
    const general = c.band ? [identity("CHILD", c.position, "", "", scope), identity("CHILD", 0, c.band, "", scope), anyChild] : [anyChild]
    add("child", c.position, c.band, identity("CHILD", c.position, c.band, "", scope), general, "child", {
      unknownBand: Boolean(c.band) && !known.includes(c.band),
      infant: Boolean(c.band) && infantBands.has(c.band),
    })
  }
  if (plain.some((n) => n.target === "CHILD" && n.position === 0 && !n.age_band)) add("child_any", 0, "", anyChild, [], "child")

  let periodOverrides = 0
  for (const row of rows) for (const p of periods) if (row.cells[p].state === "period-override") periodOverrides += 1
  return { rows, periods, counts: { periodOverrides }, basis, includedAdults: included }
}

/** An occupancy entry's refusal: the shorthand's, or "CARD" (a special combination holds the cell
 * of a single-use rule, S16 re-review 3). */
export type OccErrorCode = ShErrorCode | "CARD"

export type OccEntryResult = { tables: Tables } | { error: OccErrorCode }

/** Applies a parsed `occupancy` entry to a ladder cell: the op and value are stored as a rule on
 * the row's identity and the column's period (relative ops are always rules here); clear removes
 * the cell's rows. The cell keeps one row: the one it showed is updated in place (keeping its key,
 * "Always wins" flag and note), other rows of the same slot and period are removed. A period entry
 * equal to the All-periods rule is stored, not dropped: occupancy precedence ranks a period rule
 * above rules of other scopes, so dropping it could change a price. */
export function applyOccEntry(tables: Tables, id: OccIdentity, period: string, parsed: ShResult): OccEntryResult {
  if (!parsed.ok) return { error: parsed.code }
  if (parsed.kind === "base") return { error: "SYNTAX" }
  const same = slotRows(tables, id, period)
  const rows = same.map((n) => n.src as Row)
  if (parsed.kind !== "clear" && cardHeld(tables, id.combination, id.room_type, period)) return { error: "CARD" }
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

// ─── the ladder on screen (slice S11) ──────────────────────────────────────

/** An occupancy rule inherited from a pricing policy, as price_matrix serves it (GAP-3: `period`,
 * `adults` / `children` instead of the row fields), read as the ladder reads rules. */
export function fromInheritedRule(r: InheritedOccupancyRule): OccRuleLike {
  const any = (n: number | null | undefined) => (n === null || n === undefined ? "*" : String(n))
  const combination = (r.adults === null || r.adults === undefined) && (r.children === null || r.children === undefined) ? "" : `${any(r.adults)}+${any(r.children)}`
  return {
    rule_id: str(r.rule_id),
    target: str(r.target),
    position: int(r.position),
    age_band: str(r.age_band),
    combination,
    room_type: str(r.room_type),
    period_code: str(r.period),
    op: str(r.op),
    value: str(r.value),
    is_override: r.is_override ? 1 : 0,
    note: "",
    source: str(r.source),
    hidden: r.hidden ? 1 : 0,
  }
}

/** The pricing policy a served rule or band comes from ("policy:<id>/r<rev>/<scope>"), or null. */
export function policySource(source: unknown): { policy: string; revision: number; scope: string } | null {
  const m = /^policy:(.+)\/r([0-9]+)\/([a-z+]+)$/.exec(str(source))
  return m ? { policy: m[1], revision: int(m[2]), scope: m[3] } : null
}

/** A rule a cell's popover stores: the op chosen, its value (none for INHERIT), "Always wins" and a note. */
export interface OccRule {
  op: string
  value: string
  is_override: boolean
  note: string
}

/** Rows of a slot in one room scope and period; never a special combination's (a card is edited
 * as a whole in the builder, D8; only the single-use row's slots have a combination). */
function slotRows(tables: Pick<Tables, "occupancy_rules">, id: OccIdentity, period: string): Norm[] {
  const norms = tables.occupancy_rules.map((r) => norm(r))
  const cards = id.combination ? cardRows(norms) : null
  return norms.filter((n) => n.period === period && sameSlot(n, id) && !cards?.has(n.src))
}

/** The rows of special combinations (§3.7.4): rows with a combination whose cell (combination,
 * room, period, "Always wins"; for a policy's rules also their source) is not a single-use card
 * (isSingleUseCard). A builder card such as "1 adult + any children" with an Adult 1 rule is one;
 * the single-use row neither shows, counts nor rewrites its rules (S16 re-review 3). */
function cardRows(norms: readonly Norm[]): Set<Row | OccRuleLike> {
  const cells = new Map<string, Norm[]>()
  for (const n of norms) {
    if (!n.combination) continue
    const key = JSON.stringify([n.combination, n.room_type, n.period, n.is_override, n.policy ? str(n.src.source) : ""])
    const list = cells.get(key)
    if (list) list.push(n)
    else cells.set(key, [n])
  }
  const out = new Set<Row | OccRuleLike>()
  for (const list of cells.values()) if (!isSingleUseCard({ combination: list[0].combination, rules: list })) for (const n of list) out.add(n.src)
  return out
}

/** A special combination holds the cell (combination, room, period) of the version. */
function cardHeld(tables: Pick<Tables, "occupancy_rules">, combination: string, room: string, period: string): boolean {
  if (!combination) return false
  const norms = tables.occupancy_rules.map((r) => norm(r))
  const cards = cardRows(norms)
  return norms.some((n) => cards.has(n.src) && n.combination === combination && n.room_type === room && n.period === period)
}

/** The ladder's rule popover (§3.5, "Edit rule: {slot} · {period}"): writes the rule for each
 * room (`[""]` = all rooms) × period of the slot, one row each; a cell that has rows keeps the one
 * it shows (its key) and loses its twins. `null` (Remove) deletes those cells' rows. The op chosen
 * is the op stored. The same tables when nothing changes. */
export function applyOccRule(tables: Tables, slot: Omit<OccIdentity, "room_type">, rooms: readonly string[], periods: readonly string[], rule: OccRule | null): Tables {
  // a rule written into a cell a special combination holds would join (or rewrite) the card: nothing
  // is written (singleWriteRefusal says why; S16 re-review 3)
  if (rule && singleWriteRefusal(tables, slot, rooms, periods)) return tables
  let rows = tables.occupancy_rules
  let changed = false
  for (const room_type of rooms.length ? rooms : [""])
    for (const period of periods) {
      const id: OccIdentity = { ...slot, room_type: str(room_type) }
      const same = slotRows({ occupancy_rules: rows }, id, period)
      const mine = same.map((n) => n.src as Row)
      if (!rule) {
        if (!mine.length) continue
        rows = rows.filter((r) => !mine.includes(r))
        changed = true
        continue
      }
      const fields = { op: rule.op, value: rule.op === "INHERIT" ? "" : rule.value, is_override: rule.is_override ? 1 : 0, note: str(rule.note) }
      if (!mine.length) {
        rows = [...rows, newRow("occupancy_rules", { target: id.target, position: id.position, age_band: id.age_band, combination: id.combination, room_type: id.room_type, period_code: period, ...fields })]
        changed = true
        continue
      }
      const keep = (pick(same) as Norm).src as Row
      const equal =
        mine.length === 1 && str(keep.op) === fields.op && canonValue(keep.value) === canonValue(fields.value) && isSet(keep.is_override) === rule.is_override && str(keep.note) === fields.note
      if (equal) continue
      rows = rows.flatMap((r) => (r === keep ? [{ ...r, ...fields }] : mine.includes(r) ? [] : [r]))
      changed = true
    }
  return changed ? { ...tables, occupancy_rules: rows } : tables
}

/** Where the ladder's rule popover writes instead of its row's own slot (§3.6.2, S16 re-review):
 * a band row's rule for one child position, or the single-use row in its other form. */
export type SlotSwitch = { position: number } | { single: "whole" | "children" }

type Slot = Omit<OccIdentity, "room_type">
/** "1 Adult (single use)": the whole 1+0 combination, or "also when children travel" (Adult 1 in 1+*). */
export const SINGLE_WHOLE: Slot = { target: "COMBINATION", position: 0, age_band: "", combination: "1+0" }
export const SINGLE_CHILDREN: Slot = { target: "ADULT", position: 1, age_band: "", combination: "1+*" }

/** The slot a popover's rule is written to: `slot` itself, a position of a band row's children
 * ({CHILD, position n, band}), or the other form of the single-use row. */
export function switchedSlot(slot: Slot, to?: SlotSwitch): Slot {
  if (!to) return slot
  if ("position" in to) return to.position > 0 && slot.target === "CHILD" && slot.position === 0 && slot.age_band ? { ...slot, position: to.position } : slot
  return to.single === "children" ? SINGLE_CHILDREN : SINGLE_WHOLE
}

const sameSlotOf = (a: Slot, b: Slot) => a.target === b.target && a.position === b.position && a.age_band === b.age_band && a.combination === b.combination

/** The rule popover with a slot switch (§3.6.2 "position rows added through the popover"; "the
 * popover can switch [single use] to also when children travel"): the rule is written to the
 * switched slot for each room × period (applyOccRule). A child position rule is a row of its own,
 * so the band's rule stays. The single-use row switches form as a whole (S16 re-review 2): every
 * row of the old form in the rooms written, of All periods and of each period, becomes a row of
 * the new form (its key, op, value, "Always wins" and note kept; dropped where that cell already
 * has a row of the new form), then the rule is written to the periods chosen; one history entry.
 * Remove (`rule` null) and no switch are applyOccRule on the row's slot. */
export function applyOccRuleAs(tables: Tables, slot: Slot, rooms: readonly string[], periods: readonly string[], rule: OccRule | null, to?: SlotSwitch): Tables {
  const target = switchedSlot(slot, to)
  if (!rule || !to || sameSlotOf(target, slot)) return applyOccRule(tables, slot, rooms, periods, rule)
  if (!("single" in to)) return applyOccRule(tables, target, rooms, periods, rule)
  // a card's cell reached, or a relative rule carried into the other form: nothing is written
  if (singleWriteRefusal(tables, slot, rooms, periods, to)) return tables
  const written = new Set((rooms.length ? rooms : [""]).map(str))
  const norms = tables.occupancy_rules.map((r) => norm(r))
  // a special combination's rules are the card's: they keep their form (S16 re-review 3)
  const cards = cardRows(norms)
  const mine = norms.filter((n) => written.has(n.room_type) && !cards.has(n.src))
  const taken = new Set(mine.filter((n) => sameGuest(n, { ...target, room_type: "" })).map((n) => `${n.room_type}|${n.period}`))
  const old = new Map(mine.filter((n) => sameGuest(n, { ...slot, room_type: "" })).map((n) => [n.src as Row, n]))
  const rows = tables.occupancy_rules.flatMap((r) => {
    const n = old.get(r)
    if (!n) return [r]
    const cell = `${n.room_type}|${n.period}`
    if (taken.has(cell)) return []
    taken.add(cell)
    return [{ ...r, target: target.target, position: target.position, age_band: target.age_band, combination: target.combination }]
  })
  return applyOccRule({ ...tables, occupancy_rules: rows }, target, rooms, periods, rule)
}

/** Why the single-use row may not write a rule (S16 re-review 3): a special combination holds a
 * cell the write reaches ("card": the rule would join the card or rewrite its rule, and a card is
 * edited as a whole in the builder, D8), or the whole-row switch would carry a relative rule (Plus
 * or minus %, Add, Subtract) of another period or room into the other form, where it applies to
 * another amount (a whole combination's relative rule to the party total, an adult's to the slot
 * unit: "relative"). Replacing rules and INHERIT keep their price in either form. */
export type SingleRefusal = "card" | "relative"

/** Rules whose meaning is the same as a whole 1+0 combination and as Adult 1 of 1+* (price_occupancy:
 * a replacing combination op prices from the unit, as an adult's does). */
const SWITCH_SAFE_OPS = new Set(["ABSOLUTE", "FIXED", "MULTIPLY", "PERCENT_OF", "INHERIT"])

const isSingleSlot = (slot: Slot) => sameSlotOf(slot, SINGLE_WHOLE) || sameSlotOf(slot, SINGLE_CHILDREN)

/** What refuses writing a rule to the single-use row's `slot` (or, with `to`, switching its form)
 * for `rooms` × `periods`; null when nothing does, and for any other row. */
export function singleWriteRefusal(tables: Pick<Tables, "occupancy_rules">, slot: Slot, rooms: readonly string[], periods: readonly string[], to?: SlotSwitch): SingleRefusal | null {
  const target = switchedSlot(slot, to)
  if (!isSingleSlot(slot) || !isSingleSlot(target)) return null
  const written = [...new Set((rooms.length ? rooms : [""]).map(str))]
  const norms = tables.occupancy_rules.map((r) => norm(r))
  const cards = cardRows(norms)
  const held = new Set(norms.filter((n) => cards.has(n.src) && n.combination === target.combination).map((n) => `${n.room_type}|${n.period}`))
  const writes = new Set(written.flatMap((room) => periods.map((p) => `${room}|${p}`)))
  if ([...writes].some((c) => held.has(c))) return "card"
  if (sameSlotOf(target, slot)) return null
  const moved = norms.filter((n) => !cards.has(n.src) && written.includes(n.room_type) && sameGuest(n, { ...slot, room_type: "" }))
  if (moved.some((n) => held.has(`${n.room_type}|${n.period}`))) return "card"
  if (moved.some((n) => !writes.has(`${n.room_type}|${n.period}`) && !SWITCH_SAFE_OPS.has(n.op))) return "relative"
  return null
}

/** One ladder cell of a gesture and what was typed for it. */
export interface OccEntryItem {
  id: OccIdentity
  period: string
  parsed: ShResult
}

/** One gesture over one or many ladder cells (a typed entry, Ctrl/Cmd+Enter over a selection,
 * Delete): every cell its own entry (applyOccEntry), all or nothing; `index` names the cell
 * that refused. The same tables when nothing changes. */
export function planOccEntries(tables: Tables, items: readonly OccEntryItem[]): { tables: Tables } | { error: OccErrorCode; index: number } {
  let out = tables
  for (let i = 0; i < items.length; i++) {
    const res = applyOccEntry(out, items[i].id, items[i].period, items[i].parsed)
    if ("error" in res) return { error: res.error, index: i }
    out = res.tables
  }
  return { tables: out }
}

/** What committing a parsed entry into a ladder cell would store, for its reading line (no arithmetic). */
export type OccReading =
  | { kind: "error"; code: OccErrorCode }
  | { kind: "unchanged" }
  /** the cell's rows are removed; a period cell then follows the slot's All-periods rule, if any */
  | { kind: "clear"; follows: { op: string; value: string } | null }
  | { kind: "rule"; op: string; value: string }

export function occReadingOf(tables: Tables, id: OccIdentity, period: string, parsed: ShResult): OccReading {
  const res = applyOccEntry(tables, id, period, parsed)
  if ("error" in res) return { kind: "error", code: res.error }
  if (!parsed.ok || parsed.kind === "base") return { kind: "error", code: "SYNTAX" }
  if (res.tables === tables) return { kind: "unchanged" }
  if (parsed.kind === "clear") {
    const all = period === ALL_PERIODS ? null : pick(slotRows(tables, id, ALL_PERIODS), false)
    return { kind: "clear", follows: all ? valueOf(all.src) : null }
  }
  return { kind: "rule", op: parsed.op, value: parsed.value }
}

/** The text an edit of a ladder cell starts from: its own rule as `occupancy` shorthand (FIXED as
 * "=v"); empty when it has none (it inherits, a default, or its own INHERIT row). */
export function occEditText(cell: LadderCell | undefined, opts?: ShFormatOptions): string {
  const rule = cell?.rule
  if (!rule || str(rule.op) === "INHERIT") return ""
  return editText(str(rule.op) as ShOp, str(rule.value), "occupancy", opts)
}

/** Rooms scopes ("" = All rooms) that have occupancy rules of their own: the dot on the scope select. */
export function scopesWithRules(tables: Pick<Tables, "occupancy_rules">): Set<string> {
  return new Set(tables.occupancy_rules.map((r) => str(r.room_type)))
}

/** A card that only holds the single-use rule the ladder shows as its first row ("1 Adult (single
 * use)", or its "also with children" variant): not a special combination, so the summary, the ⓘ
 * notes and the combination cards leave it out. */
export function isSingleUseCard(card: { combination: string; rules: readonly Pick<CardRule, "target" | "position">[] }): boolean {
  if (card.combination === "1+0") return card.rules.every((r) => r.target === "COMBINATION")
  if (card.combination === "1+*") return card.rules.every((r) => r.target === "ADULT" && r.position === 1)
  return false
}

export interface SummaryItem {
  rowId: string
  kind: LadderRowKind
  position: number
  band: string
  unknownBand: boolean
  op: string
  value: string
}

export interface LadderSummary {
  adults: SummaryItem[]
  children: SummaryItem[]
  /** special combinations (cards other than the single-use row) */
  combinations: number
  periodOverrides: number
}

/** The collapsed section's summary (§3.6.1): the scope's own All-periods rules of adults and of
 * children, the number of special combinations and of period overrides. */
export function ladderSummary(model: LadderModel, cards: readonly CombinationCard[]): LadderSummary {
  const adults: SummaryItem[] = []
  const children: SummaryItem[] = []
  for (const row of model.rows) {
    const cell = row.cells[ALL_PERIODS]
    if (!row.identity || cell?.state !== "rule" || !cell.value) continue
    const item = { rowId: row.id, kind: row.kind, position: row.position, band: row.band, unknownBand: row.unknownBand, op: cell.value.op, value: cell.value.value }
    if (row.kind === "band" || row.kind === "child" || row.kind === "child_any") children.push(item)
    else adults.push(item)
  }
  return { adults, children, combinations: cards.filter((c) => !isSingleUseCard(c)).length, periodOverrides: model.counts.periodOverrides }
}

/** The ⓘ precedence note (§3.6.2): the cells a special combination outranks for some party,
 * because a card prices the same slot (same target; positions and bands equal or "any") in a room
 * and period the cell covers. Not on "Always wins" rules (they beat combinations), included
 * places, the single-use row or the cards the single-use row shows, nor from a band-less card rule
 * on an infant row whose cell a rule naming the band prices (G-31: that rule wins for an infant).
 * Keyed `${row.id}|${period}`, the card ids as values. Computed from the grouping (§3.7.4). */
export function combinationNotes(model: LadderModel, cards: readonly CombinationCard[], scopeRoom: string | null): Map<string, string[]> {
  const scope = str(scopeRoom)
  const live = cards.filter((c) => !isSingleUseCard(c))
  const out = new Map<string, string[]>()
  if (!live.length) return out
  for (const row of model.rows) {
    const id = row.identity
    if (!id || row.kind === "single" || id.target === "COMBINATION") continue
    for (const p of model.periods) {
      const cell = row.cells[p]
      if (!cell || cell.state === "included" || (cell.source && isSet(cell.source.is_override))) continue
      // G-31: an infant priced by a rule naming its band is not priced by a band-less rule
      const bandPriced = row.infant && str(cell.source?.age_band) !== ""
      const hits = live.filter(
        (card) =>
          (!scope || card.rooms.includes("") || card.rooms.includes(scope)) &&
          (p === ALL_PERIODS || card.periods.includes(ALL_PERIODS) || card.periods.includes(p)) &&
          card.rules.some(
            (r) =>
              r.target === id.target &&
              (!id.position || !r.position || r.position === id.position) &&
              (!id.age_band || !r.age_band || r.age_band === id.age_band) &&
              !(bandPriced && !r.age_band),
          ),
      )
      if (hits.length) out.set(`${row.id}|${p}`, hits.map((c) => c.id))
    }
  }
  return out
}

/** A sample party of the resolved line (§3.6.2, GAP-2b): adults and each child's band code (the
 * server prices a child at its band's lower edge). */
export interface PartyOption {
  id: string
  adults: number
  children: string[]
}

/** At most this many sample parties are offered (the select stays usable on large rooms). */
export const PARTY_OPTIONS_MAX = 60

/** price_matrix refuses a sample party with more adults or children than this, and with it the
 * whole call (kamra/tex/api/contracts.py PARTY_ADULTS_MAX, PARTY_CHILDREN_MAX). */
export const PARTY_ADULTS_MAX = 12
export const PARTY_CHILDREN_MAX = 8

/** The sample parties a room can host (validCombinations, within the server's party limits), each
 * child in every band: the multisets of band codes in band order. Adults-only parties when there
 * are no bands. When there are more than PARTY_OPTIONS_MAX, the common ones are kept (adults only,
 * then the smallest parties, two adults first); they are listed in the usual order either way. */
export function partyOptions(capacity: CapacityLike, bands: readonly BandLike[]): PartyOption[] {
  const codes = [...new Set(bands.map(bandCode).filter(Boolean))]
  const cap = { ...capacity, max_adults: Math.min(int(capacity.max_adults), PARTY_ADULTS_MAX), max_children: Math.min(int(capacity.max_children), PARTY_CHILDREN_MAX) }
  const combos = validCombinations([cap]).filter((c) => c.children === 0 || codes.length > 0)
  // the band multisets of n children, lazily (a large room with many bands has very many)
  function* multisets(n: number, from: number): Generator<string[]> {
    if (n === 0) {
      yield []
      return
    }
    for (let i = from; i < codes.length; i++) for (const rest of multisets(n - 1, i)) yield [codes[i], ...rest]
  }
  const commonness = (c: ValidCombination) => [c.children > 0 ? 1 : 0, c.adults + c.children, Math.abs(c.adults - 2), c.children]
  const byCommon = combos.map((c, i) => ({ c, i })).sort((x, y) => {
    const [a, b] = [commonness(x.c), commonness(y.c)]
    for (let k = 0; k < a.length; k++) if (a[k] !== b[k]) return a[k] - b[k]
    return x.i - y.i
  })
  const kept: { party: PartyOption; combo: number; seq: number }[] = []
  fill: for (const { c, i } of byCommon) {
    let seq = 0
    for (const children of multisets(c.children, 0)) {
      if (kept.length >= PARTY_OPTIONS_MAX) break fill
      kept.push({ party: { id: `${c.adults}+${children.join(",")}`, adults: c.adults, children }, combo: i, seq: seq++ })
    }
  }
  return kept.sort((x, y) => x.combo - y.combo || x.seq - y.seq).map((k) => k.party)
}

/** The party the resolved line starts with: two adults when the room takes them, else the first. */
export function defaultParty(options: readonly PartyOption[]): PartyOption | null {
  return options.find((p) => p.adults === 2 && !p.children.length) ?? options[0] ?? null
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
  /** The structured builder can edit it (builderCanEdit: no note, one rule per guest and band,
   * guests the combination has, no negative value outside Plus/minus %, All or named rooms and
   * periods); the others are edited in the rule tables. */
  expressible: boolean
}

/** A single-use row the ladder shows ("1 Adult (single use)"), so a screen can leave it out of the cards. */
export function isSingleUseRow(row: Row): boolean {
  const n = norm(row)
  return (n.target === "COMBINATION" && n.combination === "1+0") || (n.target === "ADULT" && n.position === 1 && n.combination === "1+*")
}

const TARGET_ORDER: Record<string, number> = { ADULT: 0, CHILD: 1, COMBINATION: 2 }

/** A card's rules in display order: adults, children, the whole stay; then position and band. */
function cardRuleSort(a: CardRule, b: CardRule): number {
  const ja = JSON.stringify(a)
  const jb = JSON.stringify(b)
  return (
    (TARGET_ORDER[a.target] ?? 9) - (TARGET_ORDER[b.target] ?? 9) ||
    a.position - b.position ||
    (a.age_band < b.age_band ? -1 : a.age_band > b.age_band ? 1 : 0) ||
    (ja < jb ? -1 : ja > jb ? 1 : 0)
  )
}

function countOf(part: string): number | null {
  return part === "*" || part === "" ? null : int(part)
}

/** Groups the rows with a combination into cards (§3.7.4): rows of the same combination, room,
 * period and override flag form a cell; cells with the same combination, flag and rules (target,
 * position, band, op, value, note; values canonical) form a card over rooms R × periods P, which
 * is split by room when its cells are not exactly R × P. All rooms (room_type blank) and named
 * rooms are never one card, nor All periods and named periods: they are different scope choices
 * of the builder, and different rules to the engine (a named room or period outranks All). Cards
 * are ordered by adults, children, then room and period table order (any "*" after numbers). */
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
  // 2. merge cells with the same combination, flag and signature
  const groups = new Map<string, { combination: string; isOverride: boolean; rules: CardRule[]; cells: { room: string; period: string; rows: Row[] }[] }>()
  for (const cell of cells.values()) {
    const rules = [...cell.rules].sort(cardRuleSort)
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
    const adults = countOf(a ?? "")
    const children = countOf(c ?? "")
    return {
      id: JSON.stringify([g.combination, g.isOverride, rooms, periods, g.rules]),
      combination: g.combination,
      adults,
      children,
      isOverride: g.isOverride,
      rooms,
      periods,
      rules: g.rules,
      keys,
      periodScoped: periods.some((p) => p !== ALL_PERIODS),
      expressible: builderCanEdit({ combination: g.combination, adults, children, rules: g.rules, rooms, periods }),
    }
  }
  for (const g of groups.values()) {
    // All rooms / All periods apart from named ones, then the cross product or a split by room
    const scopes = new Map<string, typeof g.cells>()
    for (const c of g.cells) {
      const k = `${c.room === "" ? "all" : "named"}|${c.period === ALL_PERIODS ? "all" : "named"}`
      const list = scopes.get(k)
      if (list) list.push(c)
      else scopes.set(k, [c])
    }
    for (const cells of scopes.values()) {
      const rooms = new Set(cells.map((c) => c.room))
      const periods = new Set(cells.map((c) => c.period))
      if (cells.length === rooms.size * periods.size) cards.push(card(g, cells))
      else for (const room of rooms) cards.push(card(g, cells.filter((c) => c.room === room)))
    }
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

/** The card that holds a rule row (by its `_key`), or null: where "Show in grid" and an issue
 * about the row lead (the card's element carries `data-card` = its id). */
export function cardOfRow(cards: readonly CombinationCard[], key: string): string | null {
  return cards.find((c) => c.keys.includes(key))?.id ?? null
}

// ─── the special combination builder (§3.7.1, slice S12) ─────────────────

/** One rule line of the builder: a child (position, age band; several lines of one child name
 * different bands), an adult (position) or the whole stay (position 0). `text` is what its Value
 * field holds; `op` is its Rule select. */
export interface BuilderLine {
  id: string
  position: number
  /** "" = any age (child lines); always "" for adult and whole-stay lines */
  age_band: string
  op: string
  text: string
}

/** The builder's state: the combination (never free text: steppers, chips and the "any" options),
 * the rule lines, the rooms and periods it applies to, and the card it edits. */
export interface BuilderDraft {
  adults: number | "*"
  children: number | "*"
  /** any children ("a+*"): how many child positions have lines (1, 2, …) */
  anyChildren: number
  childLines: BuilderLine[]
  adultLines: BuilderLine[]
  whole: BuilderLine | null
  roomsAll: boolean
  rooms: string[]
  periodsAll: boolean
  periods: string[]
  isOverride: boolean
  /** the edited card's row keys ([] for a new combination): Save replaces exactly these */
  replace: string[]
}

export interface BuilderOptions {
  minorUnits: number
  decimalMark?: "." | ","
}

let lineSeq = 0
/** A new builder line (ids are only for the screen: React keys, focus, errors). */
export function builderLine(patch: Partial<BuilderLine> = {}): BuilderLine {
  lineSeq += 1
  return { id: `bl${lineSeq}`, position: 1, age_band: "", op: "MULTIPLY", text: "", ...patch }
}

/** A new combination: two adults and one child unless told otherwise, all rooms, all periods. */
export function newBuilderDraft(init: Partial<Pick<BuilderDraft, "adults" | "children" | "roomsAll" | "rooms">> = {}): BuilderDraft {
  return ensureChildLines({
    adults: 2,
    children: 1,
    anyChildren: 1,
    childLines: [],
    adultLines: [],
    whole: null,
    roomsAll: true,
    rooms: [],
    periodsAll: true,
    periods: [],
    isOverride: false,
    replace: [],
    ...init,
  })
}

/** The child positions the builder shows: 1…children, or 1…anyChildren for any children. */
export function shownChildPositions(draft: Pick<BuilderDraft, "children" | "anyChildren">): number[] {
  const n = draft.children === "*" ? Math.max(1, draft.anyChildren) : Math.max(0, draft.children)
  return Array.from({ length: n }, (_, i) => i + 1)
}

/** Every child position shown has at least one line (a blank line writes nothing). Lines of
 * positions no longer shown are kept, hidden, so a count put back shows them again; they are
 * never saved. The same draft when nothing is missing. */
export function ensureChildLines(draft: BuilderDraft): BuilderDraft {
  const missing = shownChildPositions(draft).filter((p) => !draft.childLines.some((l) => l.position === p))
  if (!missing.length) return draft
  const lines = [...draft.childLines, ...missing.map((position) => builderLine({ position }))]
  return { ...draft, childLines: lines.sort((a, b) => a.position - b.position) }
}

const RE_PLAIN = /^[0-9]+(?:[.,][0-9]+)?$/
const RE_SIGNED = /^[+-] *[0-9]+(?:[.,][0-9]+)?$/

/** What a builder Value field holds: nothing, a rule, or the parser's refusal. */
export type BuilderValue = { kind: "empty" } | { kind: "rule"; op: ShOp; value: string } | { kind: "error"; code: ShErrorCode }

/** Reads a builder Value field (§3.7.1). The `occupancy` shorthand chooses the rule itself (x0.5
 * Multiply, 50% Percentage of, +10% / -10% Plus/minus %, +25 Add, -25 Subtract, =25 Set price;
 * "=25" keeps FIXED when FIXED is chosen, as FIXED has no shorthand of its own). A number alone is
 * the value of the rule chosen in the Rule select (the design's "Rule [Multiply] Value [0.50]"),
 * signed under Plus/minus %. Amounts keep the AMBIGUOUS guard (O5). No arithmetic. */
export function readBuilderValue(text: string, op: string, minorUnits: number): BuilderValue {
  if (op === "INHERIT") return { kind: "rule", op: "INHERIT", value: "" }
  const s = text.replace(/[   ]/g, " ").replace(/^ +| +$/g, "")
  if (s === "") return { kind: "empty" }
  const chosen = (OPS_BY_CONTEXT.occupancy as readonly string[]).includes(op) ? (op as ShOp) : null
  if (chosen && (RE_PLAIN.test(s) || (chosen === "ADJUST_PERCENT" && RE_SIGNED.test(s)))) {
    const d = normaliseDecimal(s.replace(/^([+-]) +/, "$1"), { amount: isAmountOp("occupancy", chosen), minorUnits })
    return d.ok ? { kind: "rule", op: chosen, value: d.value } : { kind: "error", code: d.code }
  }
  const p = parseShorthand(text, "occupancy", { minorUnits })
  if (!p.ok) return { kind: "error", code: p.code }
  if (p.kind !== "rule") return p.kind === "clear" ? { kind: "empty" } : { kind: "error", code: "SYNTAX" }
  return { kind: "rule", op: chosen === "FIXED" && p.op === "ABSOLUTE" ? "FIXED" : p.op, value: p.value }
}

/** The text a Value field shows for a stored rule, read back to the same rule by readBuilderValue
 * with that rule chosen: the number alone ("0.5", "25", "-5" under Plus/minus %; an amount such as
 * 12.345 as "12.3450" so the AMBIGUOUS guard accepts it); "" for INHERIT. A negative value of any
 * other rule shows in its shorthand, which does not read back to that rule ("-5" for ADD -5 reads
 * as SUBTRACT 5, "x-1" is refused): builderCanEdit keeps such cards out of the builder. */
export function builderValueText(op: string, value: string, opts?: ShFormatOptions): string {
  if (op === "INHERIT") return ""
  const canon = normaliseDecimal(str(value))
  if (!canon.ok) return str(value)
  const mark = (v: string) => (opts?.decimalMark === "," ? v.replace(".", ",") : v)
  if (op === "ADJUST_PERCENT") return mark(canon.value)
  if (canon.value.startsWith("-")) return editText(op as ShOp, canon.value, "occupancy", opts)
  if (isAmountOp("occupancy", op as ShOp)) return editText("ABSOLUTE", canon.value, "occupancy", opts)
  return mark(canon.value)
}

const RE_COMBINATION = /^([0-9]+|\*)\+([0-9]+|\*)$/

/** The structured builder can show a card as it is, so saving it unchanged writes the same rows:
 * a readable combination (not "any + any", at least one adult), All rooms or named rooms (not
 * both; likewise periods), no note, occupancy ops only, no negative value except under Plus/minus
 * %, one rule per adult position (1…adults), per child position (1…children) and band, and at most
 * one whole-stay rule (position 0, no band). Others are edited in the rule tables (§3.7.4). */
export function builderCanEdit(card: Pick<CombinationCard, "combination" | "adults" | "children" | "rules" | "rooms" | "periods">): boolean {
  const m = RE_COMBINATION.exec(card.combination)
  if (!m || (m[1] === "*" && m[2] === "*")) return false
  if (card.adults !== null && card.adults < 1) return false
  // the builder's scope is All or named ones: Save would write All only and drop the named rows
  const mixed = (list: readonly string[], all: string) => list.includes(all) && list.some((x) => x !== all)
  if (mixed(card.rooms, "") || mixed(card.periods, ALL_PERIODS)) return false
  const seen = new Set<string>()
  for (const r of card.rules) {
    if (r.note || !(OPS_BY_CONTEXT.occupancy as readonly string[]).includes(r.op)) return false
    if (r.op !== "ADJUST_PERCENT" && r.op !== "INHERIT") {
      const d = normaliseDecimal(r.value)
      if (d.ok && d.value.startsWith("-")) return false
    }
    const slot = `${r.target}|${r.position}|${r.age_band}`
    if (seen.has(slot)) return false
    seen.add(slot)
    if (r.target === "ADULT") {
      if (r.position < 1 || r.age_band || (card.adults !== null && r.position > card.adults)) return false
    } else if (r.target === "CHILD") {
      if (r.position < 1 || (card.children !== null && r.position > card.children)) return false
    } else if (r.target === "COMBINATION") {
      if (r.position !== 0 || r.age_band || [...seen].filter((x) => x.startsWith("COMBINATION|")).length > 1) return false
    } else return false
  }
  return card.rules.length > 0
}

/** A card in the builder (Edit), or null when the builder cannot show it (builderCanEdit). */
export function builderFromCard(card: CombinationCard, opts: BuilderOptions): BuilderDraft | null {
  if (!builderCanEdit(card)) return null
  const text = (r: CardRule) => builderValueText(r.op, r.value, opts)
  const children = card.children === null ? ("*" as const) : card.children
  const childLines = card.rules.filter((r) => r.target === "CHILD").map((r) => builderLine({ position: r.position, age_band: r.age_band, op: r.op, text: text(r) }))
  const whole = card.rules.find((r) => r.target === "COMBINATION")
  return ensureChildLines({
    adults: card.adults === null ? "*" : card.adults,
    children,
    anyChildren: children === "*" ? Math.max(1, ...childLines.map((l) => l.position)) : 1,
    childLines,
    adultLines: card.rules.filter((r) => r.target === "ADULT").map((r) => builderLine({ position: r.position, op: r.op, text: text(r) })),
    whole: whole ? builderLine({ position: 0, op: whole.op, text: text(whole) }) : null,
    roomsAll: card.rooms.includes(""),
    rooms: card.rooms.filter(Boolean),
    periodsAll: card.periods.includes(ALL_PERIODS),
    periods: card.periods.filter(Boolean),
    isOverride: card.isOverride,
    replace: [...card.keys],
  })
}

/** Why the builder cannot save (yet). `line` names the line a message belongs to. */
export type BuilderIssue =
  | { code: "NO_RULES" | "NO_ROOMS" | "NO_PERIODS" | "ANY_BOTH" }
  | { code: "VALUE"; line: string; value: ShErrorCode }
  /** a second rule of one guest (and band) in this combination */
  | { code: "DUPLICATE" | "POSITION"; line: string }
  /** another card already has a rule for this guest and band in the same rooms and periods: the
   * server's OCC_DUPLICATE for two non-INHERIT rules. With an INHERIT on either side the server
   * accepts it, but the engine skips the INHERIT one and the two rows form one card the builder
   * cannot open, so it is refused too. `keys` are the other card's rows */
  | { code: "TWIN"; line: string; keys: string[] }

export interface CombinationPlan {
  /** "a+c", "*" for any */
  combination: string
  /** the rules the lines give, in card order (the reading line), even while issues remain */
  rules: CardRule[]
  issues: BuilderIssue[]
  /** what Save writes (persistCombination); null while issues remain */
  spec: CombinationSpec | null
}

/** What Save would write (§3.7.3): every shown line with a value becomes a rule for each chosen
 * room × period, replacing the edited card's rows; blank lines write nothing (that guest keeps the
 * ladder's rules). Refused: a value the parser refuses, a second rule for one guest and band, an
 * adult the combination does not have, no rule, no room or period chosen, "any adults + any
 * children", and the twin of a row of another card (the server's OCC_DUPLICATE; INHERIT twins
 * included, see TWIN). Pure. */
export function planCombination(tables: Pick<Tables, "rooms" | "periods" | "occupancy_rules">, draft: BuilderDraft, opts: BuilderOptions): CombinationPlan {
  const issues: BuilderIssue[] = []
  const combination = `${draft.adults}+${draft.children}`
  if (draft.adults === "*" && draft.children === "*") issues.push({ code: "ANY_BOTH" })
  const rules: (CardRule & { line: string })[] = []
  const seen = new Set<string>()
  const take = (target: OccTarget, l: BuilderLine) => {
    const v = readBuilderValue(l.text, l.op, opts.minorUnits)
    if (v.kind === "empty") return
    if (v.kind === "error") {
      issues.push({ code: "VALUE", line: l.id, value: v.code })
      return
    }
    const age_band = target === "CHILD" ? str(l.age_band).toUpperCase() : ""
    const slot = `${target}|${l.position}|${age_band}`
    if (seen.has(slot)) {
      issues.push({ code: "DUPLICATE", line: l.id })
      return
    }
    seen.add(slot)
    rules.push({ target, position: l.position, age_band, op: v.op, value: v.value, note: "", line: l.id })
  }
  const shown = new Set(shownChildPositions(draft))
  for (const l of draft.adultLines) {
    if (l.position < 1 || (draft.adults !== "*" && l.position > draft.adults)) issues.push({ code: "POSITION", line: l.id })
    else take("ADULT", l)
  }
  for (const l of draft.childLines) if (shown.has(l.position)) take("CHILD", l)
  if (draft.whole) take("COMBINATION", { ...draft.whole, position: 0 })
  if (!rules.length && !issues.some((i) => "line" in i)) issues.push({ code: "NO_RULES" })
  if (!draft.roomsAll && !draft.rooms.length) issues.push({ code: "NO_ROOMS" })
  if (!draft.periodsAll && !draft.periods.length) issues.push({ code: "NO_PERIODS" })

  const inOrder = (list: readonly string[], order: readonly string[]) =>
    [...new Set(list)].sort((a, b) => {
      const [i, j] = [order.indexOf(a), order.indexOf(b)]
      return (i < 0 ? 1e9 : i) - (j < 0 ? 1e9 : j) || (a < b ? -1 : a > b ? 1 : 0)
    })
  const rooms = draft.roomsAll ? [] : inOrder(draft.rooms, tables.rooms.map((r) => str(r.room_type)))
  const periods = draft.periodsAll ? [] : inOrder(draft.periods, tables.periods.map((p) => str(p.period_code)))

  // the twins of other rows: same guest, band, combination, room, period and Always wins (one pass
  // over the rows, then a lookup per rule, room and period: cheap enough for every keystroke)
  if (!issues.length) {
    const replace = new Set(draft.replace)
    const sig = (target: string, position: number, band: string, room: string, period: string) => JSON.stringify([target, position, band, room, period])
    const others = new Map<string, string[]>()
    for (const r of tables.occupancy_rules) {
      if (replace.has(r._key)) continue
      const n = norm(r)
      if (n.combination !== combination || n.is_override !== draft.isOverride) continue
      const k = sig(n.target, n.position, n.age_band, n.room_type, n.period)
      others.set(k, [...(others.get(k) ?? []), r._key])
    }
    if (others.size)
      for (const rule of rules) {
        const keys: string[] = []
        for (const room of rooms.length ? rooms : [""])
          for (const period of periods.length ? periods : [ALL_PERIODS]) keys.push(...(others.get(sig(rule.target, rule.position, rule.age_band, room, period)) ?? []))
        if (keys.length) issues.push({ code: "TWIN", line: rule.line, keys })
      }
  }

  const cardRules: CardRule[] = rules.map(({ line: _line, ...r }) => ({ ...r, value: canonValue(r.value) })).sort(cardRuleSort)
  const pick = (target: OccTarget) => rules.filter((r) => r.target === target)
  const whole = pick("COMBINATION")[0]
  return {
    combination,
    rules: cardRules,
    issues,
    spec: issues.length
      ? null
      : {
          adults: draft.adults,
          children: draft.children,
          rooms,
          periods,
          childRules: pick("CHILD").map((r) => ({ position: r.position, age_band: r.age_band, op: r.op, value: r.value })),
          adultRules: pick("ADULT").map((r) => ({ position: r.position, op: r.op, value: r.value })),
          whole: whole ? { op: whole.op, value: whole.value } : null,
          isOverride: draft.isOverride,
          replace: [...draft.replace],
        },
  }
}

/** A quick chip of the builder: a valid combination of some contract room, enabled when a room in
 * the builder's scope can host it; `rooms` are the rooms that can (the tooltip of a greyed chip). */
export interface ComboChip extends ValidCombination {
  enabled: boolean
}

/** The quick chips (§3.7.2): the union of the contract rooms' valid combinations (the publish
 * sweep's rule, validCombinations), each enabled when a room of `scoped` hosts it (null = all
 * rooms). Nothing is hard-coded. */
export function combinationChips(capacities: readonly CapacityLike[], scoped: readonly string[] | null): ComboChip[] {
  const inScope = scoped === null ? null : new Set(scoped)
  return validCombinations(capacities).map((c) => ({ ...c, enabled: inScope === null || c.rooms.some((r) => inScope.has(r)) }))
}

/** How a child position is named under the contract's child ordering (child 1 is the oldest by
 * default, OLDEST_FIRST): "Child 1 (oldest)", the last of a known count "(youngest)"; under
 * AS_ENTERED child 1 is the first in the booking. */
export function childQualifier(ordering: string, position: number, children: number | "*"): "oldest" | "youngest" | "first" | null {
  const order = str(ordering) || "OLDEST_FIRST"
  const last = children !== "*" && children > 1 && position === children
  if (order === "AS_ENTERED") return position === 1 ? "first" : null
  const [first, end] = order === "YOUNGEST_FIRST" ? (["youngest", "oldest"] as const) : (["oldest", "youngest"] as const)
  return position === 1 ? first : last ? end : null
}
