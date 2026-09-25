// The occupancy ladder of the Pricing Workspace (PRICING_WORKSPACE_UX.md §3.6.2, §3.11, D12, D13;
// slice S11): a keyboard grid "Occupancy and child pricing by period" on the matrix's column
// template, one row per guest slot of occupancy.ladderModel (single use, the adults, the child
// bands by their labels) and a resolved line. Cells take the `occupancy` shorthand with the
// matrix's editing model (type, F2 / Enter, Enter moves down, Tab sideways, Escape reverts, an
// invalid entry stays as an error draft, Alt+Enter or ▾ opens the rule popover, Ctrl/Cmd+Enter
// writes every selected cell, Delete clears): a relative entry is always stored as a rule of the
// row's slot. Every change is one workspace history entry (S9). A cell without a rule of its own
// shows the rule the engine would use (in a room scope, possibly one of All rooms or of a pricing
// policy, with its source); only when none applies does it show the engine default: "×1.00
// default" is the server's value (occupancy_defaults), a band without a rule is "No rule · not
// sellable". The resolved line shows the server's occupancy total of a sample party per period
// (price_matrix parties, GAP-2b), from an answer that priced that very party; the client adds
// nothing up.
import { useCallback, useEffect, useId, useMemo, useRef, useState, type KeyboardEvent, type MouseEvent, type ReactNode } from "react"
import { AlertTriangle, Info, Loader2 } from "lucide-react"
import { minorUnits as currencyMinorUnits } from "../../../lib/format"
import { useTexT } from "../../../i18n"
import {
  Badge,
  editorKeyAction,
  editShortcut,
  focusHeaderLane,
  headerLaneKeyDown,
  refocusIfLost,
  Money,
  revealElement,
  Select,
  useGridNavigation,
  useGridSelection,
  useScrollSyncRef,
  useToast,
  type GridCell,
  type GridEditRequest,
} from "../../../ui"
import { useMatrixOnlyBulk } from "./useMatrixOnlyBulk"
import { resolvedStatus, sampleKey } from "./draftPreview.ts"
import type { DraftPreview } from "./useDraftPreview"
import { parseShorthand } from "../lib/shorthand"
import type { Tables } from "../lib/tables"
import type { Issue, VersionDoc } from "../lib/types"
import { decText } from "../lib/util"
import { UndoToastView } from "./BulkToolbar"
import { CellEditor, MatrixRowCells, type CellTone, type CellView } from "./MatrixCell"
import { KEPT } from "./keptState.ts"
import { useKeptState } from "./useKeptState"
import { columnTemplate, decimalMarkOf } from "./matrixView.ts"
import { ALL_PERIODS, type Basis } from "./model.ts"
import {
  applyOccRuleAs,
  occEditText,
  occReadingOf,
  planOccEntries,
  policySource,
  singleWriteRefusal,
  switchedSlot,
  type CombinationCard,
  type LadderCell,
  type LadderModel,
  type LadderRow,
  type OccEntryItem,
  type OccRule,
  type PartyOption,
  type SlotSwitch,
} from "./occupancy.ts"
import { ladderCellId, type AnchoredIssues } from "./issues.ts"
import { OccRulePopover } from "./RuleEditorPopover"
import { isSet, str } from "./rows.ts"
import type { BandLabels } from "./useBandLabels"
import { useCellIssues } from "./useCellIssues"
import { useUndoToast, type WorkspaceHistory } from "./useWorkspaceHistory"
import type { LadderCellStateKey } from "./stateKeys.ts"
import { STALE_STATE } from "./cellTone.ts"

/** A ladder cell: a row of the model (by its id) and a period ("" = All periods). */
interface LadderRef {
  row: string
  period: string
}

interface Editing {
  cell: LadderRef
  text: string
  selectAll: boolean
}

interface Draft {
  text: string
  code: string
}

const keyOf = (c: LadderRef) => `${c.row}\u0000${c.period}`
/** The DOM id of a ladder cell (data-cellid, `occ:{row}|{period}`, `@{room}` in a room scope):
 * "Show in grid" (S14) and issue anchoring (S15) find it. */
export { ladderCellId }

/** A rule as a ladder cell and the section summary show it (display only, from the stored
 * strings): ×0.70, 50%, +10%, +25.00, −25.00, 25.00. */
export function occRuleText(op: string, value: string, minorUnits: number): string {
  switch (op) {
    case "MULTIPLY":
      return `×${decText(value, 2)}`
    case "PERCENT_OF":
      return `${decText(value, 0)}%`
    case "ADJUST_PERCENT":
      return `${value.trim().startsWith("-") ? "" : "+"}${decText(value, 0)}%`
    case "ADD":
      return `+${decText(value, minorUnits)}`
    case "SUBTRACT":
      return `−${decText(value, minorUnits)}`
    case "INHERIT":
      return "↳"
    default:
      return decText(value, minorUnits)
  }
}

export interface OccupancyLadderProps {
  doc: VersionDoc
  tables: Tables
  readOnly: boolean
  history: WorkspaceHistory
  preview?: DraftPreview
  model: LadderModel
  cards: readonly CombinationCard[]
  /** ⓘ notes: `${row.id}|${period}` → the ids of the cards that outrank the cell (combinationNotes) */
  notes: Map<string, string[]>
  /** the rooms scope ("" = all rooms) */
  scope: string
  basis: Basis
  labels: BandLabels
  roomName: (rt: string) => string
  /** the room the resolved line prices ("" = none) and its sample parties */
  partyRoom: string
  party: PartyOption | null
  parties: readonly PartyOption[]
  onParty: (id: string) => void
  /** the card names for the ⓘ notes ("2 Adults + 2 Children") */
  cardName: (card: CombinationCard) => string
  /** the ⓘ note's link: brings that combination card into view and focuses it (S12) */
  onShowCard?: (id: string) => void
  /** the party's name ("2 adults + 1 child 7–11.99") */
  partyName: (party: PartyOption) => string
  /** a cell to bring into view and focus (ladderCellId; "Show in grid", S14); `n` repeats a request */
  focus?: { cellId: string; n: number } | null
  /** the validation issues anchored on ladder cells (S15), their messages as shown, and whether
   * they are older than the state on screen */
  anchored?: AnchoredIssues
  issueText?: (issue: Issue) => string
  issuesStale?: boolean
  /** the most children a room in scope holds: the child positions a band row's popover offers */
  maxChildren?: number
}

export function OccupancyLadder(p: OccupancyLadderProps) {
  const { doc, tables, readOnly, history, preview, model, labels, basis } = p
  const { t, tOrdinal, locale } = useTexT()
  // the header lane, said to a screen reader on the grid (S16 re-review 2)
  const laneNoteId = useId()
  const ccy = doc.contract_doc.contract_currency
  const minorUnits = doc.contract_doc.minor_units ?? currencyMinorUnits(ccy)
  const decimalMark = useMemo(() => decimalMarkOf(locale), [locale])
  const canEdit = !readOnly
  const rows = model.rows
  const cols = model.periods
  const periodRows = useMemo(() => new Map(tables.periods.map((x) => [str(x.period_code), x])), [tables.periods])
  const showResolved = Boolean(p.partyRoom && p.party && preview && preview.mode !== "catalogue")
  // the grid's only header lane control is the resolved line's sample party select
  const laneNote = showResolved ? t("rates.kbd.lane_note_ladder") : ""
  const navRows = rows.length + (showResolved ? 1 : 0)
  const template = columnTemplate(cols.length - 1)
  const rowIndex = useMemo(() => new Map(rows.map((x, i) => [x.id, i])), [rows])
  const singleRows = rows.filter((x) => x.kind === "single").length

  // ─── words ─────────────────────────────────────────────────────────────
  const periodName = (code: string) => code || t("rates.rates.all_periods")
  const amount = (v: string) => decText(v, minorUnits)
  const ruleShort = (op: string, value: string) => occRuleText(op, value, minorUnits)
  const unitWord = (row: LadderRow) => t(`rates.occ.unit.${row.unit}`, { count: model.includedAdults })
  const slotName = (row: LadderRow): string => {
    switch (row.kind) {
      case "single":
        if (row.identity?.target === "ADULT") return t("rates.occ.ladder.row.single_any")
        return t(basis === "ROOM" ? "rates.occ.ladder.row.single_room" : "rates.occ.ladder.row.single_person")
      case "adults_base":
        return t("rates.occ.ladder.row.adults_base")
      case "adult":
        return basis === "ROOM" && row.position > model.includedAdults
          ? tOrdinal("rates.occ.ladder.row.extra_adult", row.position)
          : tOrdinal("rates.occ.ladder.row.adult", row.position)
      case "adult_any":
        return t("rates.occ.ladder.row.adult_any")
      case "band":
        return row.unknownBand ? t("rates.occ.ladder.row.unknown_band", { code: row.band }) : labels.labelOf(row.band)
      case "child":
        return row.band
          ? t("rates.occ.ladder.row.child_n", { n: row.position, band: row.unknownBand ? row.band : labels.labelOf(row.band) })
          : t("rates.occ.ladder.row.child_n_any", { n: row.position })
      case "child_any":
        return t("rates.occ.ladder.row.child_any")
    }
  }
  const isIncludedRow = (row: LadderRow) => row.kind === "adult" && basis === "ROOM" && row.position <= model.includedAdults
  const subLabel = (row: LadderRow): string => {
    if (row.kind === "adults_base") {
      const all = row.cells[ALL_PERIODS]
      const rule = all.value ? ruleShort(all.value.op, all.value.value) : all.state === "policy" ? t("rates.occ.ladder.cell.policy_hidden") : "×1"
      return all.state === "default" ? t("rates.occ.ladder.base_pair", { rule, count: 2 }) : t("rates.occ.ladder.base_pair_general", { rule })
    }
    if (isIncludedRow(row)) return t("rates.occ.ladder.included_sub", { count: model.includedAdults })
    if (row.kind === "single" && row.identity?.target === "COMBINATION") return t("rates.occ.ladder.single_sub", { unit: unitWord(row) })
    return t("rates.occ.ladder.unit_sub", { unit: unitWord(row) })
  }
  /** The row as the popover's switched slot names it (a child position, the other single-use form). */
  const rowAs = (row: LadderRow, to?: SlotSwitch): LadderRow => {
    if (!to || !row.identity) return row
    const identity = { ...switchedSlot(row.identity, to), room_type: row.identity.room_type }
    return "position" in to ? { ...row, kind: "child", position: identity.position, identity } : { ...row, identity }
  }
  /** The reading sentence of a rule in this row (§3.4.1, §3.11): no arithmetic. */
  const ruleReading = (row: LadderRow, op: string, value: string, cell: string) => {
    const single = row.kind === "single" && row.identity?.target === "COMBINATION"
    return t(`rates.occ.read.${single ? "single." : ""}${op}`, { cell, rule: op === "INHERIT" ? "" : ruleShort(op, value), unit: unitWord(row) })
  }
  const errorText = (code: string) => t(`rates.sh.err.${code}`)
  // the validation issues anchored on this scope's cells (§3.15, S15)
  const issueAt = useCellIssues(p.anchored, p.issueText, p.issuesStale)

  // ─── the keyboard grid ─────────────────────────────────────────────────
  const isEditable = useCallback((r: number, c: number) => canEdit && c >= 0 && r < rows.length && Boolean(rows[r]?.editable), [canEdit, rows])
  const selection = useGridSelection({ rows: navRows, cols: cols.length, isEditable })
  // sideways in step with the other grids of the Pricing section (§3.1)
  const syncScroll = useScrollSyncRef()
  const gridEl = useRef<HTMLDivElement | null>(null)
  // copy, paste and the fills are the matrix's: here they say so (S16 re-review)
  const matrixOnly = useMatrixOnlyBulk(gridEl, canEdit)
  const toast = useToast()
  // only requests made while mounted (a remount after Discard or a scope change does not replay one)
  const focused = useRef(p.focus?.n ?? 0)
  useEffect(() => {
    if (!p.focus || p.focus.n === focused.current) return
    focused.current = p.focus.n
    const id = p.focus.cellId
    const el = Array.from(gridEl.current?.querySelectorAll<HTMLElement>("[data-cellid]") ?? []).find((x) => x.dataset.cellid === id)
    if (el) revealElement(el)
  }, [p.focus])
  const cellAt = (r: number, c: number): LadderRef | null => {
    const row = rows[r]
    const period = cols[c]
    return row && period !== undefined ? { row: row.id, period } : null
  }
  const positionOf = (c: LadderRef): { r: number; c: number } | null => {
    const r = rowIndex.get(c.row)
    const ci = cols.indexOf(c.period)
    return r === undefined || ci < 0 ? null : { r, c: ci }
  }
  const rowOf = (c: LadderRef) => rows[rowIndex.get(c.row) ?? -1]
  const cellName = (c: LadderRef) => {
    const row = rowOf(c)
    return `${row ? slotName(row) : c.row} · ${periodName(c.period)}`
  }

  const [editing, setEditing] = useState<Editing | null>(null)
  const editingRef = useRef<Editing | null>(null)
  editingRef.current = editing
  const editPos = editing ? positionOf(editing.cell) : null
  const closing = useRef(false)
  // error drafts outlive the grid (a section switch, a collapsed section): the editor keeps them
  const [drafts, setDrafts] = useKeptState<Record<string, Draft>>(KEPT.drafts("ladder", p.scope), {})
  const [pop, setPop] = useState<{ cell: LadderRef; initial: OccRule } | null>(null)
  const popAnchor = useRef<HTMLElement | null>(null)
  const [announce, setAnnounce] = useState("")
  const say = useCallback((text: string) => setAnnounce((prev) => (prev === text ? `${text}​` : text)), [])
  const undoToast = useUndoToast(history)

  const dropDrafts = (cells: LadderRef[]) =>
    setDrafts((d) => {
      if (!cells.some((c) => d[keyOf(c)])) return d
      const n = { ...d }
      for (const c of cells) delete n[keyOf(c)]
      return n
    })
  const focusAt = (r: number, c: number) =>
    requestAnimationFrame(() => {
      if (editingRef.current) return
      gridEl.current?.querySelector<HTMLElement>(`[data-cell="${r}:${c}"]`)?.focus()
    })
  const refocus = (cell: LadderRef) =>
    requestAnimationFrame(() => {
      const now = document.activeElement
      if (now && now !== document.body && now.isConnected) return
      const at = positionOf(cell)
      if (at) gridEl.current?.querySelector<HTMLElement>(`[data-cell="${at.r}:${at.c}"]`)?.focus()
    })
  /** Focus a cell by its id once the change is rendered, when nothing else holds the focus: the
   * single-use row that switched form is a row of another id (S16 re-review 2). */
  const refocusId = (cell: LadderRef) =>
    requestAnimationFrame(() => {
      const now = document.activeElement
      if (now && now !== document.body && now.isConnected) return
      const id = ladderCellId(cell.row, cell.period, p.scope)
      Array.from(gridEl.current?.querySelectorAll<HTMLElement>("[data-cellid]") ?? [])
        .find((x) => x.dataset.cellid === id)
        ?.focus()
    })
  const bulkDone = (count: number) => {
    const message = t("rates.ws.bulk.applied", { count })
    undoToast.show(message)
    say(message)
  }

  /** One gesture (a typed entry, Ctrl/Cmd+Enter, Delete): each cell by its row's slot, all or nothing, one history entry. */
  const commitItems = (cells: LadderRef[], text: string, label: string): { ok: true } | { ok: false; code: string; cell: LadderRef } => {
    const parsed = parseShorthand(text, "occupancy", { minorUnits })
    const items: OccEntryItem[] = []
    for (const cell of cells) {
      const row = rowOf(cell)
      const at = positionOf(cell)
      if (!row?.identity || !at || !isEditable(at.r, at.c)) return { ok: false, code: "CHANGED", cell }
      items.push({ id: row.identity, period: cell.period, parsed })
    }
    const now = history.current() ?? tables
    const plan = planOccEntries(now, items)
    if ("error" in plan) return { ok: false, code: plan.error, cell: cells[plan.index] }
    dropDrafts(cells)
    if (history.commit(label, now, plan.tables) && cells.length > 1) bulkDone(cells.length)
    return { ok: true }
  }

  const commitText = (cells: LadderRef[], text: string) =>
    commitItems(cells, text, cells.length === 1 ? t("rates.occ.h.rule", { cell: cellName(cells[0]) }) : t("rates.occ.h.rules", { count: cells.length }))

  const editTextOf = (c: LadderRef) => occEditText(rowOf(c)?.cells[c.period], { decimalMark, minorUnits })

  const onEdit = (at: GridCell, req: GridEditRequest) => {
    if (!isEditable(at.r, at.c)) return
    const cell = cellAt(at.r, at.c)
    if (!cell) return
    closing.current = false
    setEditing({ cell, text: req.text ?? drafts[keyOf(cell)]?.text ?? editTextOf(cell), selectAll: req.text === undefined })
  }

  const openPopover = (cell: LadderRef, anchor: HTMLElement, typedText?: string) => {
    const row = rowOf(cell)
    if (!row?.identity) return
    popAnchor.current = anchor
    const lc = row.cells[cell.period]
    const own = lc?.rule
    const typed = typedText === undefined ? null : parseShorthand(typedText, "occupancy", { minorUnits })
    let initial: OccRule
    if (typed?.ok && typed.kind === "rule") initial = { op: typed.op, value: typed.value, is_override: own ? isSet(own.is_override) : false, note: str(own?.note) }
    else if (own) initial = { op: str(own.op), value: str(own.value), is_override: isSet(own.is_override), note: str(own.note) }
    else if (lc?.value && lc.state !== "default") initial = { op: lc.value.op, value: lc.value.value, is_override: false, note: "" }
    else initial = { op: "MULTIPLY", value: "", is_override: false, note: "" }
    setPop({ cell, initial })
  }

  const nextEditableRow = (r: number, c: number, dir: 1 | -1) => {
    for (let i = r + dir; i >= 0 && i < rows.length; i += dir) if (isEditable(i, c)) return i
    return r
  }

  const finish = (cell: LadderRef, move: "down" | "up" | "left" | "right" | null) => {
    closing.current = true
    setEditing(null)
    const at = positionOf(cell)
    if (!at) return
    if (move === "down" || move === "up") nav.focusCell(nextEditableRow(at.r, at.c, move === "down" ? 1 : -1), at.c)
    else if (move === "left" || move === "right") nav.focusCell(at.r, Math.max(0, Math.min(cols.length - 1, at.c + (move === "right" ? 1 : -1))))
    else focusAt(at.r, at.c)
  }

  const commitEditor = (ed: Editing, text: string, cells: LadderRef[], move: "down" | "up" | "left" | "right" | null): string | void => {
    const cell = cells[0]
    if (cells.length === 1 && !drafts[keyOf(cell)] && text === editTextOf(cell)) return finish(ed.cell, move)
    const res = commitText(cells, text)
    if (res.ok) return finish(ed.cell, move)
    const own = res.cell.row === ed.cell.row && res.cell.period === ed.cell.period
    return own ? errorText(res.code) : t("rates.ws.bulk_error", { cell: cellName(res.cell), error: errorText(res.code) })
  }

  const selectedRefs = (): LadderRef[] => {
    const cells = selection.selected.map((x) => cellAt(x.r, x.c)).filter((x): x is LadderRef => x !== null)
    if (cells.length) return cells
    const a = nav.active
    const own = isEditable(a.r, a.c) ? cellAt(a.r, a.c) : null
    return own ? [own] : []
  }

  const onEditorKey = (e: KeyboardEvent<HTMLInputElement>, text: string): string | void => {
    const ed = editingRef.current
    if (!ed) return
    const cell = ed.cell
    // one routing for the three grids (ui/keys.ts); Ctrl/Cmd+S commits the entry first and the
    // version editor saves it
    const act = editorKeyAction(e)
    if (!act) return
    switch (act.kind) {
      case "swallow":
        e.preventDefault()
        return
      case "save":
        return commitEditor(ed, text, [cell], null)
      case "cancel":
        e.preventDefault()
        e.stopPropagation()
        dropDrafts([cell])
        finish(cell, null)
        return
      case "popover": {
        e.preventDefault()
        const anchor = e.currentTarget.closest<HTMLElement>('[role="gridcell"]')
        closing.current = true
        setEditing(null)
        if (anchor) openPopover(cell, anchor, text)
        return
      }
      case "bulk": {
        e.preventDefault()
        const cells = selectedRefs()
        if (!cells.some((x) => x.row === cell.row && x.period === cell.period)) cells.push(cell)
        return commitEditor(ed, text, cells, null)
      }
      case "commit":
        e.preventDefault()
        return commitEditor(ed, text, [cell], act.move)
    }
  }

  const onEditorBlur = (text: string) => {
    if (closing.current) return
    const ed = editingRef.current
    if (!ed) return
    const cell = ed.cell
    closing.current = true
    setEditing(null)
    if (!drafts[keyOf(cell)] && text === editTextOf(cell)) return
    const res = commitText([cell], text)
    if (!res.ok) setDrafts((d) => ({ ...d, [keyOf(res.cell)]: { text, code: res.code } }))
  }

  const stepHistory = (which: "undo" | "redo", fromToast = false) => {
    const label = fromToast ? undoToast.undo() : which === "undo" ? history.undo() : history.redo()
    if (label) say(t(which === "undo" ? "rates.ws.bulk.undone" : "rates.ws.bulk.redone", { label }))
    // a keyboard undo or redo that removed the focused cell's row: the active cell takes the focus
    // back (the toast's Undo has its own way back, onToastFocusBack)
    if (!fromToast) refocusIfLost(() => latest.current.focusActive())
  }
  const latest = useRef<{ stepHistory: typeof stepHistory; focusActive: () => void }>({ stepHistory, focusActive: () => {} })
  latest.current = { stepHistory, focusActive: () => void focusAt(nav.active.r, nav.active.c) }
  const onToastUndo = useCallback(() => latest.current.stepHistory("undo", true), [])
  const onToastFocusBack = useCallback(() => latest.current.focusActive(), [])

  const onKey = (e: KeyboardEvent<HTMLElement>, at: GridCell): boolean | void => {
    if (!canEdit) return
    const shortcut = editShortcut(e)
    if (shortcut) {
      // undo / redo work here as in the matrix; Ctrl+R / Ctrl+D (the matrix's fills) must not
      // reload or bookmark the page while a ladder cell has the focus
      e.preventDefault()
      if (shortcut === "undo" || shortcut === "redo") stepHistory(shortcut)
      else matrixOnly()
      return true
    }
    const cell = cellAt(at.r, at.c)
    if ((e.key === "Enter" && e.altKey) || (e.key === "F10" && e.shiftKey) || e.key === "ContextMenu") {
      e.preventDefault()
      if (cell && isEditable(at.r, at.c)) openPopover(cell, e.currentTarget)
      return true
    }
    if ((e.key === "Delete" || e.key === "Backspace") && !e.ctrlKey && !e.metaKey && !e.altKey) {
      const cells = selectedRefs()
      if (!cells.length) return
      e.preventDefault()
      const label = cells.length === 1 ? t("rates.occ.h.clear", { cell: cellName(cells[0]) }) : t("rates.occ.h.clear_many", { count: cells.length })
      const res = commitItems(cells, "", label)
      // a refusal is shown as the matrix shows it (a toast, announced), not only to screen readers
      if (!res.ok) toast.error(t("rates.ws.bulk_error", { cell: cellName(res.cell), error: errorText(res.code) }))
      return true
    }
    if (e.key === "Escape" && cell && drafts[keyOf(cell)] && !selection.multiple) {
      e.preventDefault()
      dropDrafts([cell])
      return true
    }
  }

  // one tab stop (§3.19): the sample party select is reached with ArrowLeft from the resolved line
  const nav = useGridNavigation({ rows: navRows, cols: cols.length, selection, onEdit: canEdit ? onEdit : undefined, onKey, onEdge: (edge, cell) => focusHeaderLane(gridEl.current, edge, cell) })
  const setGrid = useCallback(
    (el: HTMLDivElement | null) => {
      gridEl.current = el
      nav.gridRef(el)
    },
    [nav],
  )

  // ─── what each cell shows ──────────────────────────────────────────────
  type View = { tone: CellTone; content: ReactNode; state: LadderCellStateKey; value?: string; tooltip?: string; error?: string; wrap?: boolean; stack?: boolean }
  const tag = (text: string) => <span className="ml-1 rounded bg-white/70 px-0.5 align-middle text-[9px] font-semibold tracking-wide uppercase">{text}</span>

  const ladderView = (row: LadderRow, period: string, cell: LadderCell): View => {
    const val = cell.value
    const short = val ? ruleShort(val.op, val.value) : ""
    const own = cell.rule
    const wins = own && isSet(own.is_override) ? tag(t("rates.occ.ladder.cell.always_tag")) : null
    const fixed = own && str(own.op) === "FIXED" ? tag(t("rates.occ.ladder.cell.fixed_tag")) : null
    switch (cell.state) {
      case "included":
        return {
          tone: "muted",
          content: t("rates.occ.ladder.cell.included"),
          wrap: true,
          state: "included",
          tooltip: own ? t("rates.occ.ladder.cell.ignored_tip", { rule: ruleShort(str(own.op), str(own.value)), count: model.includedAdults }) : t("rates.occ.ladder.cell.included_tip", { count: model.includedAdults }),
        }
      case "rule":
        return { tone: "plain", content: <>{short}{fixed}{wins}</>, state: "rule", value: short }
      case "period-override": {
        const all = row.cells[ALL_PERIODS]
        const def = all?.value && all.state !== "default" && all.state !== "missing" ? ruleShort(all.value.op, all.value.value) : ""
        return {
          tone: "override",
          content: (
            <>
              <span>
                ◆ {short}
                {fixed}
                {wins}
              </span>
              <span className="text-[9px] font-semibold tracking-wide">{t("rates.occ.ladder.cell.override")}</span>
            </>
          ),
          stack: true,
          state: "period-override",
          value: short,
          tooltip: def ? t("rates.occ.ladder.cell.override_tip", { period, default: def, rule: short }) : t("rates.ws.cell.own_rule_tip", { period, rule: short }),
        }
      }
      case "inherited":
        return { tone: "muted", content: `↳ ${short}`, state: "inherited", value: short }
      case "inherit-rule":
        return {
          tone: "muted",
          content: (
            <>
              ↳ <span className="ml-1 rounded bg-zinc-100 px-1 text-[10px] text-zinc-600">{t("rates.ws.state.inherit_tag")}</span>
            </>
          ),
          state: "inherit-rule",
          value: short || undefined,
          tooltip: t("rates.occ.ladder.cell.inherit_tip", { rule: short || "—" }),
        }
      case "general":
        return { tone: "muted", content: `↳ ${short}`, state: "general", value: short, tooltip: t("rates.occ.ladder.cell.general_tip", { rule: short }) }
      case "all-rooms": {
        // a room scope without a rule of its own for the slot: an All-rooms rule prices it
        const allRooms = t("rates.occ.ladder.all_rooms")
        const room = p.roomName(p.scope)
        return {
          tone: "muted",
          content: (
            <>
              <span>↳ {short}</span>
              <span className="max-w-full truncate text-[10px]">{allRooms}</span>
            </>
          ),
          stack: true,
          state: "all-rooms",
          value: `${short} (${allRooms})`,
          tooltip: t("rates.occ.ladder.cell.all_rooms_tip", { room, rule: short }),
        }
      }
      case "policy": {
        const src = policySource(cell.source?.source)
        const scope = src ? t(`rates.occ.ladder.source.${src.scope.replace("+", "_")}`) : t("rates.occ.ladder.source.policy")
        const from = t("rates.occ.ladder.cell.policy_from", { source: scope })
        // in a room scope, a policy rule without a room applies as the All-rooms rule of the policy
        const allRooms = p.scope !== "" && str(cell.source?.room_type) === "" ? t("rates.occ.ladder.all_rooms") : ""
        const source = [src ? `${scope} · ${src.policy} r${src.revision}` : str(cell.source?.source), allRooms].filter(Boolean).join(" · ")
        if (!val) {
          // its formula is cost the viewer does not see (price_matrix `hidden`): which rule applies, not how
          const hidden = t("rates.occ.ladder.cell.policy_hidden")
          return {
            tone: "muted",
            content: (
              <>
                <i>{hidden}</i>
                <span className="max-w-full truncate text-[10px]">{from}</span>
              </>
            ),
            stack: true,
            state: "policy",
            value: `${hidden} (${[from, allRooms].filter(Boolean).join(" · ")})`,
            tooltip: t("rates.occ.ladder.cell.policy_hidden_tip", { source }),
          }
        }
        return {
          tone: "muted",
          content: (
            <>
              <i>{short}</i>
              <span className="max-w-full truncate text-[10px]">{from}</span>
            </>
          ),
          stack: true,
          state: "policy",
          value: `${short} (${[from, allRooms].filter(Boolean).join(" · ")})`,
          tooltip: t("rates.occ.ladder.cell.policy_tip", { source, rule: short }),
        }
      }
      case "default": {
        const each = row.kind === "adults_base"
        const text = short ? t(each ? "rates.occ.ladder.cell.default_each" : "rates.occ.ladder.cell.default", { rule: short }) : t("rates.occ.ladder.cell.default_bare")
        if (row.kind === "single") {
          // "×1.00 default (no single-use rule)" (§3.6.2)
          const sub = t("rates.occ.ladder.cell.default_single_sub")
          return {
            tone: "muted",
            content: (
              <>
                <i>{text}</i>
                <span className="max-w-full truncate text-[10px]">{sub}</span>
              </>
            ),
            stack: true,
            state: "default",
            value: `${text} ${sub}`,
            tooltip: t("rates.occ.ladder.cell.default_single_tip"),
          }
        }
        const tip =
          row.identity?.target === "CHILD"
              ? t("rates.occ.ladder.cell.default_child_tip", { rule: short })
              : basis === "ROOM"
                ? t("rates.occ.ladder.cell.default_extra_tip", { rule: short, unit: unitWord(row) })
                : t("rates.occ.ladder.cell.default_tip")
        return { tone: "muted", content: <i>{text}</i>, state: "default", value: text, tooltip: tip }
      }
      case "missing":
        return { tone: "missing", content: t("rates.occ.ladder.cell.missing"), state: "missing", tooltip: t("rates.occ.ladder.cell.missing_tip"), wrap: true }
    }
  }

  // the resolved line: the server's total for the chosen party, from an answer that priced this
  // very party (partiesFor, as sent); another party's totals are never shown for it ("…" until
  // its answer comes, "—" when that call failed). An answer for this party about an older state
  // stays, dimmed, while the new one is on its way.
  const matrix = preview?.matrix
  // what the resolved line is against the state on screen (S16 re-review; as in the matrix)
  const status = preview ? resolvedStatus(preview) : "current"
  const stale = status !== "current"
  const wanted = p.party && p.partyRoom ? sampleKey([{ adults: p.party.adults, children: p.party.children }], p.partyRoom) : ""
  const partyCell = wanted && preview?.partiesFor === wanted ? matrix?.party_cells?.[0] : undefined
  const matrixState = preview?.matrixState
  // a spinner only while a call is in flight: for other prices, or for this party
  const partyPending = showResolved && Boolean(preview?.loading) && (status === "updating" || !partyCell)
  const allCodes = useMemo(() => labels.bands.map((b) => str(b.band_code ?? b.code).toUpperCase()).filter(Boolean), [labels.bands])

  const resolvedView = (period: string): View => {
    if (period === ALL_PERIODS) return { tone: "resolved", content: "", state: "resolved_all" }
    const err = partyCell?.errors?.[period]
    if (err) {
      const msg = labels.display(err, allCodes)
      return {
        tone: "error",
        content: (
          <>
            <AlertTriangle className="mr-0.5 inline size-3 -translate-y-px" aria-hidden />
            {t("rates.rates.unsellable")}
          </>
        ),
        state: "unsellable",
        value: msg,
        tooltip: msg,
        error: msg,
      }
    }
    if (!partyCell) {
      // the call that asked for this party failed
      if (matrixState === "failed") return { tone: "resolved", content: "—", state: "failed", tooltip: t("rates.occ.ladder.party_failed") }
      // the answer for the state on screen priced no party: it is about the saved draft (a clean
      // draft, above the overlay's cap, a published version), which does not hold this room
      if (matrix && matrixState === "ready" && status !== "updating") return { tone: "resolved", content: "—", state: "no_party", tooltip: t("rates.occ.ladder.party_unsaved") }
      return { tone: "resolved", content: "…", state: "loading" }
    }
    const v = partyCell.cells?.[period]
    if (partyCell.hidden?.includes(period)) return { tone: "resolved", content: "—", state: "cost_hidden", value: t("rates.occ.ladder.party_hidden"), tooltip: t("rates.occ.ladder.party_hidden") }
    if (v === undefined || v === null) return { tone: "resolved", content: "—", state: "no_price" }
    return { tone: "resolved", content: <Money amount={v} currency={ccy} />, state: "occ_resolved", value: `${ccy} ${amount(v)}`, tooltip: t("rates.occ.ladder.resolved_tip") }
  }

  const draftView = (draft: Draft): View => {
    const message = errorText(draft.code)
    return {
      tone: "error",
      content: (
        <>
          <AlertTriangle className="mr-1 inline size-3 -translate-y-px" aria-hidden />
          {draft.text}
        </>
      ),
      state: "draft",
      value: draft.text,
      tooltip: message,
      error: message,
    }
  }

  const roTip = doc.status !== "Draft" ? t("rates.ws.cell.ro_published") : t("rates.ws.cell.ro_permission")

  const cellView = (r: number, period: string, c: number): CellView => {
    const resolved = r >= rows.length
    const ref: LadderRef | null = resolved ? null : { row: rows[r].id, period }
    const name = resolved ? `${t("rates.occ.ladder.resolved", { room: p.roomName(p.partyRoom) })} · ${periodName(period)}` : cellName(ref as LadderRef)
    const editable = isEditable(r, c)
    const row = resolved ? null : rows[r]
    let view = resolved || !row ? resolvedView(period) : ladderView(row, period, row.cells[period])
    const draft = ref ? drafts[keyOf(ref)] : undefined
    if (draft) view = draftView(draft)
    // ⓘ a special combination outranks this cell for some party (§3.6.2)
    const hit = row ? p.notes.get(`${row.id}|${period}`) : undefined
    let note = ""
    if (hit && !draft) {
      const names = p.cards.filter((x) => hit.includes(x.id)).map(p.cardName)
      note = t("rates.occ.ladder.cell.combo_note", { combos: names.join(", ") })
      view = {
        ...view,
        content: (
          <>
            {view.content}
            <Info className="ml-1 inline size-3 -translate-y-px text-sky-700" aria-hidden />
          </>
        ),
        tooltip: view.tooltip ? `${view.tooltip} ${note}` : note,
      }
    }
    const state = t(`rates.occ.state.${view.state}`)
    const stateText = resolved && stale ? t(STALE_STATE[status], { state }) : state
    const value = [view.value, note].filter(Boolean).join(" · ")
    const cellId = ref ? ladderCellId(ref.row, ref.period, p.scope) : undefined
    return {
      cellId,
      issue: cellId ? issueAt(cellId) : undefined,
      label: value ? t("rates.ws.cell.label", { cell: name, state: stateText, value }) : t("rates.ws.cell.label_bare", { cell: name, state: stateText }),
      tone: view.tone,
      content: view.content,
      tooltip: view.tooltip ?? (!editable ? (resolved ? t("rates.occ.ladder.cell.ro_resolved") : row && !row.editable ? undefined : roTip) : undefined),
      readOnly: !editable,
      stale: resolved && stale,
      error: view.error,
      wrap: view.wrap,
      stack: view.stack,
      trigger: editable && ref ? { label: t("rates.occ.pop.title", { cell: name }), onOpen: (el) => openPopover(ref, el) } : undefined,
      onContextMenu:
        editable && ref
          ? (e: MouseEvent<HTMLElement>) => {
              e.preventDefault()
              openPopover(ref, e.currentTarget)
            }
          : undefined,
    }
  }
  const cellViews = useMemo(
    () => Array.from({ length: navRows }, (_, r) => cols.map((period, c) => cellView(r, period, c))),
    // everything cellView reads
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [rows, cols, navRows, model, tables, drafts, canEdit, t, tOrdinal, decimalMark, minorUnits, doc.status, ccy, labels, p.notes, p.cards, partyCell, stale, status, matrix, matrixState, p.partyRoom, p.scope, basis, issueAt],
  )
  const selectedKey = (r: number) => {
    let out = ""
    for (let c = 0; c < cols.length; c++) out += selection.isSelected(r, c) ? "1" : "0"
    return out
  }

  const editorFor = (ed: Editing) => {
    const cell = ed.cell
    const row = rowOf(cell)
    return (
      <CellEditor
        label={t("rates.occ.ladder.cell.input", { cell: cellName(cell) })}
        initialText={ed.text}
        selectAll={ed.selectAll}
        readingFor={(text) => {
          if (!row?.identity) return { text: "", invalid: true }
          const reading = occReadingOf(history.current() ?? tables, row.identity, cell.period, parseShorthand(text, "occupancy", { minorUnits }))
          const name = cellName(cell)
          switch (reading.kind) {
            case "error":
              return { text: errorText(reading.code), invalid: true }
            case "unchanged":
              return { text: t("rates.sh.read.unchanged"), invalid: false }
            case "clear":
              return {
                text: reading.follows ? t("rates.occ.read.clear_follows", { cell: name, rule: ruleShort(reading.follows.op, reading.follows.value) }) : t("rates.occ.read.clear", { cell: name }),
                invalid: false,
              }
            case "rule":
              return { text: ruleReading(row, reading.op, reading.value, name), invalid: false }
          }
        }}
        onKey={onEditorKey}
        onBlur={onEditorBlur}
      />
    )
  }

  const periodsForPopover = tables.periods
    .map((x) => ({ code: str(x.period_code), label: str(x.period_name) ? `${str(x.period_code)} · ${str(x.period_name)}` : str(x.period_code) }))
    .filter((x) => x.code)
  const roomOptions = tables.rooms.map((x) => str(x.room_type)).filter(Boolean).map((rt) => ({ value: rt, label: p.roomName(rt) }))

  // the active cell's ⓘ note, with links to the cards that outrank it (§3.6.2)
  const activeRow = rows[nav.active.r]
  const activePeriod = cols[nav.active.c]
  const noteIds = activeRow && activePeriod !== undefined ? p.notes.get(`${activeRow.id}|${activePeriod}`) : undefined
  const noteCards = noteIds && p.onShowCard ? p.cards.filter((x) => noteIds.includes(x.id)) : []

  const headerCell = "border-r border-b border-zinc-200 bg-white px-2 py-1 text-left"
  return (
    <div className="space-y-1.5">
      {/* the header lane as this grid has it: the resolved line's sample party (S16 re-review 3) */}
      {(canEdit || laneNote) && (
        <p className="text-xs text-zinc-500">
          {canEdit && t("rates.occ.ladder.hint")}
          {canEdit && laneNote && " "}
          {laneNote && <span id={laneNoteId}>{laneNote}</span>}
        </p>
      )}
      <span role="status" aria-live="polite" className="sr-only">
        {announce}
      </span>
      <div ref={syncScroll} data-scroll-sync className="max-h-[70vh] overflow-auto rounded-lg border border-zinc-200 bg-white pb-10">
        <div
          role="grid"
          aria-label={t("rates.occ.ladder.caption")}
          aria-describedby={laneNote ? laneNoteId : undefined}
          aria-rowcount={navRows + 1}
          aria-colcount={cols.length + 1}
          aria-readonly={readOnly || undefined}
          aria-multiselectable
          ref={setGrid}
          onKeyDownCapture={(e) => void headerLaneKeyDown(e, gridEl.current, nav.focusCell, { rows: navRows, cols: cols.length })}
          className="w-max min-w-full text-sm"
        >
          <div role="row" className="sticky top-0 z-[2] grid bg-white" style={{ gridTemplateColumns: template }}>
            <div role="columnheader" className={`sticky left-0 z-[4] flex items-end gap-1.5 ${headerCell} text-xs font-semibold text-zinc-600`}>
              {t("rates.occ.ladder.guest")}
              {partyPending && <Loader2 className="size-3 animate-spin text-zinc-400" aria-hidden />}
            </div>
            {cols.map((code) => {
              const per = periodRows.get(code)
              return (
                <div role="columnheader" key={code || "all"} className={headerCell}>
                  <span className="block truncate text-xs font-semibold text-zinc-800">{code ? code : t("rates.rates.all_periods")}</span>
                  <span className="block truncate text-[11px] text-zinc-500">{code ? str(per?.period_name) || " " : t("rates.ws.default")}</span>
                </div>
              )
            })}
            <div aria-hidden className="border-b border-zinc-200" />
          </div>

          {rows.map((row, r) => (
            <div role="row" key={row.id} className="grid" style={{ gridTemplateColumns: template }}>
              <div role="rowheader" className="sticky left-0 z-[1] flex min-w-0 flex-col justify-center border-r border-b border-zinc-100 bg-white px-3 py-1">
                <span className="flex min-w-0 items-center gap-1.5">
                  <span className="truncate text-[13px] font-medium text-zinc-900">{slotName(row)}</span>
                  {row.kind === "adults_base" && <Badge tone="brand">{t("rates.ws.room.base")}</Badge>}
                  {row.unknownBand && <AlertTriangle className="size-3.5 shrink-0 text-amber-600" aria-label={t("rates.occ.ladder.unknown_band_tip")} />}
                </span>
                <span className="text-[11px] leading-tight text-zinc-500">{subLabel(row)}</span>
              </div>
              <MatrixRowCells
                r={r}
                views={cellViews[r]}
                nav={nav}
                activeC={nav.active.r === r ? nav.active.c : -1}
                selected={selectedKey(r)}
                selState={nav.active.r === r ? selection.state : undefined}
                tint={selection.multiple}
                blockStart={false}
                editC={editing && editPos && editPos.r === r ? editPos.c : -1}
                editor={editing && editPos && editPos.r === r ? editorFor(editing) : undefined}
              />
              <div aria-hidden className="border-b border-zinc-100" />
            </div>
          ))}

          {showResolved && p.party && (
            <div role="row" className="grid" style={{ gridTemplateColumns: template }}>
              <div role="rowheader" className="sticky left-0 z-[1] flex min-w-0 flex-col justify-center gap-0.5 border-t-2 border-r border-b border-t-zinc-200 border-r-zinc-100 border-b-zinc-100 bg-zinc-50 px-3 py-1">
                <span className="truncate text-[12px] font-medium text-zinc-700">{t("rates.occ.ladder.resolved", { room: p.roomName(p.partyRoom) })}</span>
                <Select
                  aria-label={t("rates.occ.ladder.party")}
                  tabIndex={navRows > 0 && cols.length > 0 ? -1 : 0}
                  data-lane-rows={String(rows.length)}
                  value={p.party.id}
                  className="h-7! py-0! text-xs!"
                  options={p.parties.map((x) => ({ value: x.id, label: p.partyName(x) }))}
                  onChange={(e) => p.onParty(e.target.value)}
                />
              </div>
              <MatrixRowCells
                r={rows.length}
                views={cellViews[rows.length]}
                nav={nav}
                activeC={nav.active.r === rows.length ? nav.active.c : -1}
                selected={selectedKey(rows.length)}
                selState={nav.active.r === rows.length ? selection.state : undefined}
                tint={selection.multiple}
                blockStart
                editC={-1}
              />
              <div aria-hidden className="border-t-2 border-b border-t-zinc-200 border-b-zinc-100" />
            </div>
          )}
        </div>
      </div>

      {noteCards.length > 0 && activeRow && (
        <p className="flex flex-wrap items-center gap-x-1.5 gap-y-0.5 text-xs text-sky-900">
          <Info className="size-3.5 shrink-0 text-sky-700" aria-hidden />
          <span>{t("rates.occ.ladder.note_line", { cell: cellName({ row: activeRow.id, period: activePeriod }) })}</span>
          {noteCards.map((card) => (
            <button
              key={card.id}
              type="button"
              aria-label={t("rates.occ.ladder.note_show", { name: p.cardName(card) })}
              onClick={() => p.onShowCard?.(card.id)}
              className="rounded px-0.5 font-medium text-sky-800 underline underline-offset-2 hover:text-sky-900 focus-visible:ring-2 focus-visible:ring-tex-500 focus-visible:outline-none"
            >
              {p.cardName(card)}
            </button>
          ))}
        </p>
      )}

      {pop &&
        (() => {
          const row = rowOf(pop.cell)
          if (!row?.identity) return null
          const slot = { target: row.identity.target, position: row.identity.position, age_band: row.identity.age_band, combination: row.identity.combination }
          const cell = pop.cell
          return (
            <OccRulePopover
              key={keyOf(cell)}
              anchorRef={popAnchor}
              onClose={() => setPop(null)}
              slotName={slotName(row)}
              periodName={periodName(cell.period)}
              period={cell.period}
              periods={periodsForPopover}
              rooms={roomOptions}
              scope={p.scope}
              initial={pop.initial}
              hasRule={Boolean(row.cells[cell.period]?.rule)}
              reading={(op, value, where, to) => ruleReading(rowAs(row, to), op, value, where)}
              // §3.6.2: a band row's rule for one child position (a position row of its own), and the
              // single-use row's "also when children travel" form (PERSON basis: under ROOM the
              // included adult 1 takes no rule). The form switches for the whole row; with both
              // forms shown (a row each) each row keeps its own (S16 re-review 2). Only a row of the
              // scope's own rules switches: a rule of All rooms or of a pricing policy would still
              // apply, which the popover says instead (S16 re-review 3).
              positions={row.kind === "band" ? p.maxChildren : 0}
              single={row.kind === "single" && basis === "PERSON" && singleRows === 1 && !row.foreign ? (row.identity.target === "ADULT" ? "children" : "whole") : undefined}
              singleForeign={row.kind === "single" && basis === "PERSON" && singleRows === 1 && row.foreign}
              // a write the single-use row refuses: a special combination's cell, a relative rule
              // carried into the other form (S16 re-review 3)
              refusal={(rooms, periods, to) => singleWriteRefusal(history.current() ?? tables, slot, rooms, periods, to)}
              slotNameAs={(to) => slotName(rowAs(row, to))}
              minorUnits={minorUnits}
              ccy={ccy}
              onApply={(rooms, periods, rule, to) => {
                dropDrafts(periods.map((period) => ({ row: cell.row, period })))
                const label = rule ? t("rates.occ.h.rule", { cell: to ? `${slotName(rowAs(row, to))} · ${periodName(cell.period)}` : cellName(cell) }) : t("rates.occ.h.clear", { cell: cellName(cell) })
                history.apply(label, (tb) => applyOccRuleAs(tb, slot, rooms, periods, rule, to))
                setPop(null)
                if (rule && to && "single" in to) refocusId({ row: to.single === "children" ? "single:1:" : "single:0:", period: cell.period })
                else refocus(cell)
              }}
            />
          )
        })()}
      <UndoToastView toast={undoToast.toast} onUndo={onToastUndo} onDismiss={undoToast.dismiss} onHold={undoToast.hold} onFocusBack={onToastFocusBack} />
    </div>
  )
}
