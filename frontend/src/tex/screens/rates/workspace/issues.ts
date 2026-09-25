// Validation issues anchored in the Pricing Workspace (PRICING_WORKSPACE_UX.md §3.15, §4 GAP-4, D9,
// D13; slice S15). An issue of validate_version carries an optional `ref` (the rule(s), room,
// period, band(s), party and board it is about). This decides where it is shown:
// - `ref.rule_id(s)` names rows of the draft: `~<_key>` (a row priced unsaved; `~<table>-<n>` for
//   one sent without a key) or a saved row's name. A room price row marks its matrix cell, an
//   occupancy rule its ladder cell (in the rule's rooms scope) or its special combination card, a
//   board rule its board cell;
// - otherwise the ref's fields: a board (+ room, period) → the board cell; a party (adults +
//   children) → the combination card for it; an age band (± period) → the band's ladder row; a
//   room + period → the matrix cell; a period alone → the period's column header.
// An issue whose place is not on screen (a room or period the contract does not have, a room
// alone, the header, the selling terms, offers) stays in the lists only. Anchors are the grids'
// `data-cellid` values, so a click on an issue can find and focus its cell. Messages keep the
// server's text; band codes in them are shown as labels (`issueMessage`, the bracket rule for the
// publish sweep's "STD 2A+2C [CHB]: …").
// Pure: no runtime imports except each other.
import type { Tables } from "../lib/tables.ts"
import type { Issue, IssueRef, Row } from "../lib/types.ts"
import { bandCode, type BandLike } from "./bands.ts"
import { ALL_PERIODS } from "./model.ts"
import { canonCombination, groupCombinations, isSingleUseCard, type CombinationCard } from "./occupancy.ts"
import type { ShowTarget } from "./priceTest.ts"
import { int, str } from "./rows.ts"
import { issueSection, issueTable, SECTIONS, type RuleTableId, type SectionId } from "./sections.ts"

/** Where an issue is shown in Pricing. */
export type IssueAnchor =
  | { kind: "matrix"; room: string; period: string }
  | { kind: "ladder"; scope: string; row: string; period: string }
  | { kind: "card"; card: string }
  | { kind: "board"; board: string; room: string; period: string }
  | { kind: "period"; period: string }

// ─── the grids' cell ids (data-cellid) ────────────────────────────────────

/** A room price cell of the matrix (period "" = All periods). */
export const matrixCellId = (room: string, period: string) => `${room}|${period}`
/** A ladder cell: its row (`${kind}:${position}:${band}`, occupancy.ladderModel) and period, in
 * the rooms scope shown ("" = All rooms; a room scope adds `@{room}`, so a room's cell is never
 * taken for the All-rooms one). */
export const ladderCellId = (row: string, period: string, scope = "") => `occ:${row}|${period}${scope ? `@${scope}` : ""}`
/** A boards cell (room "" = All rooms, period "" = All periods). */
export const boardCellId = (board: string, room: string, period: string) => `board:${board}|${room}|${period}`
/** A period column's header in the matrix. */
export const periodHeaderId = (period: string) => `period:${period}`
/** A special combination card (its id is groupCombinations' JSON: compared, never put in a selector). */
export const cardAnchorId = (card: string) => `card:${card}`

export function anchorId(a: IssueAnchor): string {
  switch (a.kind) {
    case "matrix":
      return matrixCellId(a.room, a.period)
    case "ladder":
      return ladderCellId(a.row, a.period, a.scope)
    case "card":
      return cardAnchorId(a.card)
    case "board":
      return boardCellId(a.board, a.room, a.period)
    case "period":
      return periodHeaderId(a.period)
  }
}

/** The ladder row (occupancy.ladderModel's row id) that shows a plain occupancy rule in its rooms
 * scope: `adult:{n}:`, `adult_any:0:`, `band:0:{BAND}`, `child:{n}:{BAND}`, `child_any:0:`, or the
 * single-use row `single:0:` (1+0 for the whole party, adult 1 of 1+*); null for a rule no ladder
 * row shows (a special combination, an adult rule with a band, a combination rule without a party). */
export function ladderRowIdOf(rule: Row): string | null {
  const target = str(rule.target).toUpperCase()
  const position = int(rule.position)
  const band = str(rule.age_band).toUpperCase()
  const combination = canonCombination(rule.combination)
  if ((target === "COMBINATION" && combination === "1+0") || (target === "ADULT" && position === 1 && combination === "1+*")) return "single:0:"
  if (combination) return null
  if (target === "ADULT") {
    if (band) return null
    return position > 0 ? `adult:${position}:` : "adult_any:0:"
  }
  if (target === "CHILD") {
    if (position > 0) return `child:${position}:${band}`
    return band ? `band:0:${band}` : "child_any:0:"
  }
  return null
}

// ─── anchoring ────────────────────────────────────────────────────────────

export interface AnchorOptions {
  /** The bands the ladder shows a row for (the version's, or the inherited ones: effectiveBands).
   * Defaults to the version's own. */
  bands?: readonly BandLike[]
}

export interface AnchoredIssues {
  /** anchor id (anchorId) → the issues shown there, in list order */
  byCell: Map<string, Issue[]>
  /** each issue's anchors, by its index in the list (empty: not shown in a cell) */
  anchors: IssueAnchor[][]
  /** the issues shown in the lists only */
  unanchored: Issue[]
}

type ShownTable = "period_rates" | "occupancy_rules" | "boards"
const SHOWN: readonly ShownTable[] = ["period_rates", "occupancy_rules", "boards"]

/** The draft's rows by rule id, the contract's rooms, periods and bands, the combination cards: built
 * once per call, and only what the issues need. */
interface Index {
  rooms: Set<string>
  periods: Set<string>
  /** `${board}|${room}` of every boards grid row */
  boardRows: Set<string>
  /** whether the ladder has a row for a band in a rooms scope */
  hasBand: (band: string, scope: string) => boolean
  cards: () => CombinationCard[]
  /** the card that holds a rule row (by its key) */
  cardOfKey: (key: string) => CombinationCard | undefined
  /** the row a rule id names (priceTest.ruleRowOf's reading, looked up in maps) */
  row: (ruleId: string) => { table: ShownTable; row: Row } | null
  periodOk: (period: string) => boolean
}

function indexOf(tables: Tables, opts: AnchorOptions): Index {
  const rooms = new Set(tables.rooms.map((r) => str(r.room_type)).filter(Boolean))
  const periods = new Set(tables.periods.map((p) => str(p.period_code)).filter(Boolean))
  const boardRows = new Set<string>()
  for (const b of tables.boards) {
    const board = str(b.board)
    if (!board) continue
    boardRows.add(`${board}|`)
    boardRows.add(`${board}|${str(b.room_type)}`)
  }
  // the ladder has a row for each band it shows, and one for a band a plain rule that reaches the
  // scope names (a rule of All rooms reaches every scope)
  const bands = new Set((opts.bands ?? tables.age_bands).map(bandCode).filter(Boolean))
  const named = new Set<string>()
  for (const r of tables.occupancy_rules) {
    const id = ladderRowIdOf(r)
    if (id?.startsWith("band:")) named.add(`${str(r.room_type)}|${id.slice("band:0:".length)}`)
  }
  let cardList: CombinationCard[] | undefined
  let byKey: Map<string, CombinationCard> | undefined
  const cards = () => (cardList ??= groupCombinations(tables))
  let keys: Map<string, { table: ShownTable; row: Row }> | undefined
  let names: Map<string, { table: ShownTable; row: Row }> | undefined
  const row = (ruleId: string): { table: ShownTable; row: Row } | null => {
    const id = str(ruleId)
    if (!id) return null
    if (!keys || !names) {
      keys = new Map()
      names = new Map()
      for (const table of SHOWN)
        for (const r of tables[table]) {
          if (!keys.has(r._key)) keys.set(r._key, { table, row: r })
          const name = str(r._name)
          if (name && !names.has(name)) names.set(name, { table, row: r })
        }
    }
    if (!id.startsWith("~")) return names.get(id) ?? null
    const key = id.slice(1)
    const hit = keys.get(key)
    if (hit) return hit
    const m = /^([a-z_]+)-(\d+)$/.exec(key)
    if (m && (SHOWN as readonly string[]).includes(m[1])) {
      const table = m[1] as ShownTable
      const r = tables[table][parseInt(m[2], 10) - 1]
      return r ? { table, row: r } : null
    }
    return null
  }
  return {
    rooms,
    periods,
    boardRows,
    hasBand: (band, scope) => bands.has(band) || named.has(`|${band}`) || (scope !== "" && named.has(`${scope}|${band}`)),
    cards,
    cardOfKey: (key) => {
      if (!byKey) {
        byKey = new Map()
        for (const c of cards()) for (const k of c.keys) if (!byKey.has(k)) byKey.set(k, c)
      }
      return byKey.get(key)
    },
    row,
    periodOk: (period) => period === ALL_PERIODS || periods.has(period),
  }
}

/** Where a row of the draft is shown, or null when it is not (a room or period the contract lacks). */
function anchorOfRow(ix: Index, table: ShownTable, row: Row): IssueAnchor | null {
  const room = str(row.room_type)
  const period = str(row.period_code)
  if (!ix.periodOk(period)) return null
  if (table === "period_rates") return ix.rooms.has(room) ? { kind: "matrix", room, period } : null
  if (table === "boards") {
    const board = str(row.board)
    return board ? { kind: "board", board, room, period } : null
  }
  if (room && !ix.rooms.has(room)) return null
  if (canonCombination(row.combination)) {
    const card = ix.cardOfKey(row._key)
    if (card && !isSingleUseCard(card)) return { kind: "card", card: card.id }
  }
  const rowId = ladderRowIdOf(row)
  return rowId ? { kind: "ladder", scope: room, row: rowId, period } : null
}

const known = (v: unknown) => v !== undefined && v !== null

/** The card a party is about: the combination (or a "*" one that takes it) in the party's room and
 * period; the most specific first (exact counts, then a named room, then a named period). */
function cardOfParty(ix: Index, adults: number, children: number, room: string, period: string): CombinationCard | null {
  let best: CombinationCard | null = null
  let bestScore = -1
  for (const c of ix.cards()) {
    if ((c.adults !== null && c.adults !== adults) || (c.children !== null && c.children !== children)) continue
    if (room && !c.rooms.includes(room) && !c.rooms.includes("")) continue
    if (period && !c.periods.includes(period) && !c.periods.includes(ALL_PERIODS)) continue
    const score = (c.adults !== null ? 8 : 0) + (c.children !== null ? 4 : 0) + (room && c.rooms.includes(room) ? 2 : 0) + (period && c.periods.includes(period) ? 1 : 0)
    if (score > bestScore) {
      best = c
      bestScore = score
    }
  }
  return best
}

/** The anchors of an issue by its ref's fields (no row of the draft named). */
function anchorsOfRef(ix: Index, code: string, ref: IssueRef): IssueAnchor[] {
  const room = str(ref.room_type)
  const period = str(ref.period)
  const board = str(ref.board)
  if (board) return ix.boardRows.has(`${board}|${room}`) && ix.periodOk(period) ? [{ kind: "board", board, room, period }] : []
  if ((room && !ix.rooms.has(room)) || !ix.periodOk(period)) return []
  const party = known(ref.adults) && known(ref.children)
  if (party) {
    const card = cardOfParty(ix, int(ref.adults), int(ref.children), room, period)
    if (card) return [isSingleUseCard(card) ? { kind: "ladder", scope: room, row: "single:0:", period } : { kind: "card", card: card.id }]
  }
  const band = str(ref.age_band).toUpperCase()
  if (band && ix.hasBand(band, room)) return [{ kind: "ladder", scope: room, row: `band:0:${band}`, period }]
  // an issue about guests is never shown on a room price
  if (party || band || known(ref.adults) || known(ref.children) || code.startsWith("OCC_")) return []
  if (room && period) return [{ kind: "matrix", room, period }]
  if (!room && period) {
    const other = str(ref.other_period)
    const out: IssueAnchor[] = [{ kind: "period", period }]
    if (other && other !== period && ix.periods.has(other)) out.push({ kind: "period", period: other })
    return out
  }
  return []
}

/**
 * Where each issue is shown (§3.15): its anchors in the grids (see the header comment), the cells
 * with the issues they show, and the issues that stay in the lists only. Rows are found by their
 * client key (`~<_key>`, which survives a save: keepKeys) or their saved name, so a stored report
 * (Checked when published) anchors too.
 */
export function anchorIssues(issues: readonly Issue[], tables: Tables, opts: AnchorOptions = {}): AnchoredIssues {
  const byCell = new Map<string, Issue[]>()
  const anchors: IssueAnchor[][] = []
  const unanchored: Issue[] = []
  if (!issues.length) return { byCell, anchors, unanchored }
  const ix = indexOf(tables, opts)
  for (const issue of issues) {
    const ref = issue.ref ?? {}
    const ids = [...(ref.rule_ids ?? []), ...(ref.rule_id ? [ref.rule_id] : [])]
    let found: IssueAnchor[] = []
    for (const id of ids) {
      const hit = ix.row(id)
      const a = hit ? anchorOfRow(ix, hit.table, hit.row) : null
      if (a) found.push(a)
    }
    // a rule the draft does not hold (a pricing policy's, a row removed since): the ref's fields
    if (!found.length && !ids.some((id) => ix.row(id))) found = anchorsOfRef(ix, issue.code, ref)
    const seen = new Set<string>()
    const mine: IssueAnchor[] = []
    for (const a of found) {
      const id = anchorId(a)
      if (seen.has(id)) continue
      seen.add(id)
      mine.push(a)
      const list = byCell.get(id)
      if (list) list.push(issue)
      else byCell.set(id, [issue])
    }
    anchors.push(mine)
    if (!mine.length) unanchored.push(issue)
  }
  return { byCell, anchors, unanchored }
}

// ─── where a click on an issue leads ────────────────────────────────────

export type IssuePlace = { section: "pricing"; target: ShowTarget } | { section: Exclude<SectionId, "pricing">; table?: RuleTableId }

/** Where the live check's list takes the viewer for an issue: its first cell; else the Pricing
 * region that holds its subject (the child ages drawer, Occupancy, Boards, the matrix), the rule
 * table that lists it (Commercial rules), or Offers. */
export function issuePlace(issue: Issue, anchors: readonly IssueAnchor[]): IssuePlace {
  const a = anchors[0]
  if (a) {
    switch (a.kind) {
      case "matrix":
        return { section: "pricing", target: { kind: "matrix", room: a.room, period: a.period } }
      case "ladder":
        return { section: "pricing", target: { kind: "ladder", scope: a.scope, row: a.row, period: a.period } }
      case "card":
        return { section: "pricing", target: { kind: "card", id: a.card } }
      case "board":
        return { section: "pricing", target: { kind: "board", board: a.board, room: a.room, period: a.period } }
      case "period":
        return { section: "pricing", target: { kind: "period", period: a.period } }
    }
  }
  const { code, ref } = issue
  const section = issueSection(code, ref)
  if (section === "pricing") {
    if (code.startsWith("AGE_BANDS") || code === "NO_AGE_BANDS") return { section, target: { kind: "region", region: "ages" } }
    if (code.startsWith("BOARD_") || code === "NO_BASE_BOARD") return { section, target: { kind: "region", region: "boards" } }
    if (code.startsWith("OCC_") || known(ref?.adults)) return { section, target: { kind: "region", region: "occupancy" } }
    return { section, target: { kind: "region", region: "matrix" } }
  }
  if (section === "rules") {
    const table = issueTable(code, ref)
    return table === "offers" ? { section: "offers" } : { section, table }
  }
  return { section }
}

// ─── the live check's list ────────────────────────────────────────────────

export interface IssueGroup {
  section: SectionId
  /** the section's issues, errors first, each with its index in the list */
  items: { issue: Issue; index: number }[]
  errors: number
  warnings: number
}

/** The issues grouped by the section that holds them (§2), in section order; errors first. */
export function issuesBySection(issues: readonly Issue[]): IssueGroup[] {
  const groups = new Map<SectionId, IssueGroup>()
  issues.forEach((issue, index) => {
    const section = issueSection(issue.code, issue.ref)
    let g = groups.get(section)
    if (!g) {
      g = { section, items: [], errors: 0, warnings: 0 }
      groups.set(section, g)
    }
    g.items.push({ issue, index })
    if (issue.level === "ERROR") g.errors += 1
    else g.warnings += 1
  })
  const out: IssueGroup[] = []
  for (const s of SECTIONS) {
    const g = groups.get(s)
    if (!g) continue
    // a stable order: errors, then warnings, each in the server's order
    g.items = [...g.items.filter((x) => x.issue.level === "ERROR"), ...g.items.filter((x) => x.issue.level !== "ERROR")]
    out.push(g)
  }
  return out
}

// ─── messages ─────────────────────────────────────────────────────────────

/** The band codes an issue's message may print bare (every code for AGE_BANDS, the slot's band). */
export function issueBandCodes(issue: Issue): string[] | undefined {
  const ref = issue.ref
  if (ref?.age_bands) return ref.age_bands
  return ref?.age_band ? [ref.age_band] : undefined
}

/** An issue's message as shown (D13): the server's text with its band codes as labels, through
 * `display` (useBandLabels().display: `[CODE]` always, bare codes the ref names). */
export function issueMessage(issue: Issue, display: (text: string, codes?: readonly string[]) => string): string {
  return display(issue.message, issueBandCodes(issue))
}
