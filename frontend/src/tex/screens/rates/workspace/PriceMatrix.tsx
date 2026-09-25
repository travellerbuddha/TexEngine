// The room price matrix of the Pricing Workspace (PRICING_WORKSPACE_UX.md §3.3–§3.5, §3.9, §3.11,
// §3.19; slice S9): a keyboard grid (role="grid" "Room prices by period") of the contract rooms ×
// All periods and the period columns, edited inline with the shorthand (§3.4). The row decides how
// a relative entry is stored (D11): on the base room the server adjusts the entered price once and
// it is stored as ABSOLUTE (O4, apply_op_values); on every other room it writes a formula from the
// room's default base. Resolved rows show the server's prices for what is on screen (the live
// preview, S8); the client computes no amount. Every change is one workspace history entry.
//
// Bulk tools (§3.10, slice S10): header clicks select a row's or column's cells; Fill → / Fill ↓
// (Ctrl/Cmd+R, Ctrl/Cmd+D) copy the rule the first cell shows, a price into a formula row only after an
// inline confirmation; Ctrl/Cmd+C / V copy and paste TSV (the browser's clipboard events while a
// cell has focus: no clipboard permission is asked); Adjust… changes entered prices by the
// server's apply_op_values with a preview; Ctrl/Cmd+Z, Ctrl/Cmd+Shift+Z / Ctrl+Y and the toolbar
// undo and redo. A bulk operation shows "Applied to N cells · Undo" for 10 s.
import { useCallback, useEffect, useId, useMemo, useRef, useState, type KeyboardEvent, type MouseEvent, type ReactNode } from "react"
import { AlertTriangle, Calculator, Loader2, Pencil, Pin } from "lucide-react"
import { tex, TexApiError } from "../../../lib/api"
import { minorUnits as currencyMinorUnits } from "../../../lib/format"
import { useTexT } from "../../../i18n"
import {
  Badge,
  Checkbox,
  ContextMenu,
  editorKeyAction,
  editShortcut,
  fillDownPlan,
  fillRightPlan,
  MenuItem,
  Money,
  Notice,
  revealElement,
  Tooltip,
  focusHeaderLane,
  headerLaneKeyDown,
  useGridNavigation,
  useGridSelection,
  useScrollSyncRef,
  useToast,
  type EditShortcut,
  type GridCell,
  type GridEditRequest,
} from "../../../ui"
import type { TabProps } from "../contracts/tabs/shared"
import { displayText, editText, parseShorthand, type ShOp, type ShResult } from "../lib/shorthand"
import type { Tables } from "../lib/tables"
import type { ApplyOpResult, Row } from "../lib/types"
import { decText } from "../lib/util"
import { AddMenu } from "./AddMenu"
import { AdjustPopover } from "./AdjustPopover"
import { applyAdjust, answersInOrder, planFill, serverCalls, type AdjustTarget, type FillStep } from "./bulk.ts"
import { BulkToolbar, FillConfirm, UndoToastView } from "./BulkToolbar"
import { copyBlock, decodeTSV, encodeTSV, pasteOrigin, planPaste } from "./clipboard.ts"
import { CellEditor, MatrixRowCells, type CellTone, type CellView } from "./MatrixCell"
import { KEPT } from "./keptState.ts"
import { useKeptState } from "./useKeptState"
import { ALL_PERIODS, isRelativeOp, matrixModel, type MatrixRoom, type NeedsServer, type RoomCell } from "./model.ts"
import {
  addRoom,
  applyPopover,
  cellCopyText,
  cellEditText,
  cellPosition,
  clearCells,
  columnTemplate,
  decimalMarkOf,
  finishItems,
  gestureCells,
  gridRows,
  planItems,
  readingOf,
  type AdjustAnswer,
  type CellRef,
  type EntryError,
  type GridRow,
  type PopoverRule,
  type Reading,
} from "./matrixView.ts"
import { matrixCellId, periodHeaderId } from "./issues.ts"
import { AddPeriodHeader, PeriodHeader, PeriodStrip } from "./PeriodHeader"
import { headerPick, RoomRowHeader } from "./RoomRowHeader"
import { RuleEditorPopover } from "./RuleEditorPopover"
import { int, str } from "./rows.ts"
import { useCellIssues } from "./useCellIssues"
import { useUndoToast, type WorkspaceHistory } from "./useWorkspaceHistory"
import type { MatrixCellStateKey } from "./stateKeys.ts"
import { resolvedStatus } from "./draftPreview.ts"
import { STALE_STATE } from "./cellTone.ts"

const SHOW_RESOLVED_KEY = "tex.rates.ws.show_resolved"

/** A per-viewer on/off preference in localStorage (the "Show resolved" toggle, §3.3.1). */
function useStoredFlag(key: string, initial: boolean): [boolean, (v: boolean) => void] {
  const [value, setValue] = useState(() => {
    try {
      const s = window.localStorage.getItem(key)
      return s === null ? initial : s === "1"
    } catch {
      return initial
    }
  })
  const set = useCallback(
    (v: boolean) => {
      setValue(v)
      try {
        window.localStorage.setItem(key, v ? "1" : "0")
      } catch {
        /* storage blocked: the choice lasts until reload */
      }
    },
    [key],
  )
  return [value, set]
}

/** The cell being edited and the text the edit starts from (the editor keeps what is typed, so
 * typing re-renders the editor only, not the grid). Kept by its cell, not by a row index: rows
 * that come and go above it (a room that gains a resolved row) never move the edit. */
interface Editing {
  cell: CellRef
  text: string
  selectAll: boolean
}

/** An entry that could not be stored: kept in its cell, never lost (§3.4.1). */
interface Draft {
  text: string
  code?: EntryError
  message?: string
}

/** One cell of a gesture with what was typed or pasted for it (the error draft keeps the text). */
interface TextItem {
  cell: CellRef
  parsed: ShResult
  text: string
}

/** A fill waiting for "Set a fixed price override?" (§3.10). */
interface PendingFill {
  dir: "right" | "down"
  steps: FillStep[]
  fixed: number
}

const keyOf = (c: CellRef) => `${c.room}\u0000${c.period}`
/** The DOM id of an entry cell (data-cellid), stable while rows come and go; issues anchor on it (S15). */
const cellIdOf = (c: CellRef) => matrixCellId(c.room, c.period)

export function PriceMatrix({
  doc,
  state,
  readOnly,
  preview,
  history,
  onActivePeriod,
  onActiveCell,
  onPriceTest,
  show,
  onShown,
  anchored,
  issueText,
  issuesStale,
}: TabProps & {
  history: WorkspaceHistory
  /** the period ("" = All periods) of the cell that gets the focus: the boards grid highlights
   * the same column (§3.12, S13) */
  onActivePeriod?: (period: string) => void
  /** the cell (room, period) that gets the focus: the header's Price test starts from it (S14) */
  onActiveCell?: (cell: CellRef) => void
}) {
  const { t, locale } = useTexT()
  // the header lane, said to a screen reader on the grid (S16 re-review 2)
  const laneNoteId = useId()
  const tables = state.tables
  const cd = doc.contract_doc
  const ccy = cd.contract_currency
  const minorUnits = cd.minor_units ?? currencyMinorUnits(ccy)
  const decimalMark = useMemo(() => decimalMarkOf(locale), [locale])
  const basis = cd.pricing_basis
  const canEdit = !readOnly
  const model = useMemo(() => matrixModel(tables, basis), [tables, basis])
  const [showResolved, setShowResolved] = useStoredFlag(SHOW_RESOLVED_KEY, true)
  const rows = useMemo(() => gridRows(model).filter((x) => showResolved || x.kind !== "resolved"), [model, showResolved])
  const cols = useMemo(() => [ALL_PERIODS, ...model.periods.map((p) => p.code)], [model])
  const template = columnTemplate(model.periods.length)
  const roomsByType = useMemo(() => new Map(model.rooms.map((x) => [x.room_type, x])), [model])

  // ─── names and texts ─────────────────────────────────────────────────
  const names = useMemo(() => new Map(doc.room_types.map((r) => [r.name, r.room_type_name || r.name])), [doc.room_types])
  const roomName = useCallback((rt: string) => names.get(rt) ?? rt, [names])
  const periodName = (code: string) => code || t("rates.rates.all_periods")
  const cellName = (c: CellRef) => `${roomName(c.room)} · ${periodName(c.period)}`
  const amount = (v: unknown) => decText(str(v), minorUnits)
  const opText = (op: string, value: string) => displayText(op as ShOp, value, "room", { decimalMark })
  const formulaText = (op: string, value: string, base: string) =>
    op === "PERCENT_OF" ? t("rates.ws.formula_pct", { base: roomName(base), rule: opText(op, value) }) : t("rates.ws.formula", { base: roomName(base), rule: opText(op, value) })
  /** A stored rule in words: an amount, a formula from its base room, or "inherits". */
  const ruleText = (rule: Row) => {
    const op = str(rule.op)
    if (op === "INHERIT") return t("rates.ws.state.inherit_tag")
    if (isRelativeOp(op)) return formulaText(op, str(rule.value), str(rule.base_room_type))
    return amount(rule.value)
  }
  /** A stored rule as the cell shows it: 70.00, ×1.15, +10%. */
  const shortText = (rule: Row) => {
    const op = str(rule.op)
    if (op === "INHERIT") return "↳"
    return isRelativeOp(op) ? opText(op, str(rule.value)) : amount(rule.value)
  }
  const errorText = (code: EntryError | string) => t(`rates.sh.err.${code}`)
  // the validation issues anchored on entry cells and period headers (§3.15, S15)
  const issueAt = useCellIssues(anchored, issueText, issuesStale)

  // ─── the server's resolved prices (live preview) ─────────────────────
  const matrix = preview?.matrix
  const resolvedRooms = useMemo(() => new Map((matrix?.rooms ?? []).map((r) => [r.room_type, r])), [matrix])
  // what the resolved prices on screen are (S16 re-review): only "updating" while this state's answer
  // is on its way; a failed call or the saved draft's prices above the overlay cap say so instead
  const status = preview ? resolvedStatus(preview) : "current"
  const stale = status !== "current"
  const includedAdults = (rt: string): number => {
    const fromServer = resolvedRooms.get(rt)?.capacity?.included_adults
    if (fromServer) return fromServer
    const row = tables.rooms.find((r) => str(r.room_type) === rt)
    return int(row?.included_adults) || doc.room_types.find((r) => r.name === rt)?.base_occupancy || 0
  }

  // ─── the keyboard grid ──────────────────────────────────────────────
  const isEditable = useCallback((r: number, c: number) => canEdit && c >= 0 && Boolean(rows[r]?.editable), [canEdit, rows])
  const selection = useGridSelection({ rows: rows.length, cols: cols.length, isEditable })
  // sideways in step with the other grids of the Pricing section (§3.1)
  const syncScroll = useScrollSyncRef()
  const gridEl = useRef<HTMLDivElement | null>(null)
  const cellAt = (r: number, c: number): CellRef | null => {
    const row = rows[r]
    const period = cols[c]
    return row && period !== undefined ? { room: row.room, period } : null
  }
  const modelCell = (c: CellRef): RoomCell | undefined => roomsByType.get(c.room)?.cells[c.period]
  const editTextOf = (c: CellRef) => cellEditText(modelCell(c), { decimalMark, minorUnits })

  const [editing, setEditing] = useState<Editing | null>(null)
  const editingRef = useRef<Editing | null>(null)
  editingRef.current = editing
  const editPos = editing ? cellPosition(rows, cols, editing.cell) : null
  // set when the editor is closed on purpose (commit, Escape): the blur that follows is not a commit
  const closing = useRef(false)
  // error drafts outlive the grid (a section switch, a collapsed section): the editor keeps them
  const [drafts, setDrafts] = useKeptState<Record<string, Draft>>(KEPT.drafts("matrix"), {})
  // the cells of an entry waiting for the server's adjustment: the base-room price sent, or null
  const [pending, setPending] = useState<Record<string, string | null>>({})
  const [pop, setPop] = useState<{ cell: CellRef; initial: PopoverRule } | null>(null)
  const popAnchor = useRef<HTMLElement | null>(null)
  // the cell's context menu (S14): "Edit rule…" and "Test this price"
  const [cellMenu, setCellMenu] = useState<{ cell: CellRef; editable: boolean } | null>(null)
  const cellMenuAnchor = useRef<HTMLElement | null>(null)
  const [freshPeriod, setFreshPeriod] = useState<string | null>(null)
  const freshDone = useCallback(() => setFreshPeriod(null), [])
  // the period Duplicate just made (unnamed): its header opens Rename… (S16 review)
  const [renamePeriodCode, setRenamePeriodCode] = useState<string | null>(null)
  const renameOpened = useCallback(() => setRenamePeriodCode(null), [])
  // the polite live region: bulk results, undo and redo (§3.19). The same text twice is announced
  // twice (a zero-width space tells them apart).
  const [announce, setAnnounce] = useState("")
  const say = useCallback((text: string) => setAnnounce((prev) => (prev === text ? `${text}\u200b` : text)), [])
  const toast = useToast()
  const undoToast = useUndoToast(history)
  const [fillAsk, setFillAsk] = useState<PendingFill | null>(null)
  const [adjusting, setAdjusting] = useState<CellRef[] | null>(null)
  const adjustRef = useRef<HTMLButtonElement | null>(null)

  const historyApply = history.apply
  const edit = useCallback((label: string, fn: (tb: Tables) => Tables) => historyApply(label, fn), [historyApply])
  /** The toast and the announcement of a bulk operation that was committed (`note`: what else the
   * user must know, e.g. the cells a fill cleared). */
  const bulkDone = (count: number, note?: string) => {
    const applied = t("rates.ws.bulk.applied", { count })
    const message = note ? `${applied} · ${note}` : applied
    undoToast.show(message)
    say(message)
  }
  const dropDrafts = (cells: CellRef[]) =>
    setDrafts((d) => {
      if (!cells.some((c) => d[keyOf(c)])) return d
      const n = { ...d }
      for (const c of cells) delete n[keyOf(c)]
      return n
    })

  /** Focus returns to a cell when the element that had it went away (the popover's anchor was
   * re-rendered by the edit it applied). */
  const refocus = (cell: CellRef) =>
    requestAnimationFrame(() => {
      const now = document.activeElement
      if (now && now !== document.body && now.isConnected) return
      gridEl.current?.querySelector<HTMLElement>(`[data-cellid="${CSS.escape(cellIdOf(cell))}"]`)?.focus()
    })
  const focusAt = (r: number, c: number) =>
    requestAnimationFrame(() => {
      // an edit started before this frame (a key typed at once after Escape) keeps the focus: taking
      // it would commit that edit's first keys on blur
      if (editingRef.current) return
      gridEl.current?.querySelector<HTMLElement>(`[data-cell="${r}:${c}"]`)?.focus()
    })

  /** The base-room cells of an entry are adjusted once by the server (O4, §3.4.5): one
   * apply_op_values call per op and value (a typed entry or Ctrl/Cmd+Enter makes one; a paste may
   * make several); the whole gesture is then one history entry. Every cell of the gesture is
   * pending until the answers, and they complete nothing when one of the cells was changed
   * meanwhile (`sentFrom`, CHANGED). */
  const adjust = async (items: TextItem[], sent: NeedsServer[], label: string, sentFrom: Tables, bulk: boolean) => {
    const cells = items.map((x) => x.cell)
    const waiting = gestureCells(cells, sent)
    const keys = waiting.map((w) => keyOf(w.cell))
    setPending((p) => {
      const n = { ...p }
      waiting.forEach((w, i) => (n[keys[i]] = w.current))
      return n
    })
    const first = { room: sent[0].room, period: sent[0].targetPeriod }
    const textOf = (c: CellRef) => items.find((x) => x.cell.room === c.room && x.cell.period === c.period)?.text ?? ""
    const gen = history.generation()
    try {
      const calls = serverCalls(sent)
      const results = await Promise.all(
        calls.map((c) => tex<ApplyOpResult[]>("contracts", "apply_op_values", { version: doc.name, values: c.values, op: c.op, value: c.value }, { post: true })),
      )
      const answers = answersInOrder(calls, results, sent.length)
      // the version was reloaded or discarded meanwhile: the answer is for a draft that is gone
      if (history.generation() !== gen) return
      let failed: { error: EntryError; cell: CellRef } | null = null
      const committed = history.apply(label, (tb) => {
        const done = finishItems(tb, items, sent, answers, sentFrom)
        if ("error" in done) {
          failed = done
          return tb
        }
        return done.tables
      })
      const f = failed as { error: EntryError; cell: CellRef } | null
      if (f) setDrafts((d) => ({ ...d, [keyOf(f.cell)]: { text: textOf(f.cell), code: f.error } }))
      else if (committed && bulk) bulkDone(items.length)
      else say(t("rates.ws.adjusted", { count: sent.length }))
    } catch (e) {
      setDrafts((d) => ({ ...d, [keyOf(first)]: { text: textOf(first), message: e instanceof TexApiError || e instanceof Error ? e.message : String(e) } }))
    } finally {
      setPending((p) => {
        const n = { ...p }
        for (const k of keys) delete n[k]
        return n
      })
    }
  }

  /** Commits one gesture (each cell its own entry: typed, Ctrl/Cmd+Enter, paste): stored at once,
   * or (base-room relative entries) after the server's adjustment. Refused as a whole when one
   * cell cannot take its entry. `bulk`: a toast with Undo follows (§3.10). */
  const commitItems = (items: TextItem[], label: string, bulk: boolean): { ok: true } | { ok: false; code: EntryError; cell: CellRef } => {
    const cells = items.map((x) => x.cell)
    // a cell still waiting for the server takes no other entry; a cell whose row or column is gone
    // (or no longer editable) takes none either
    const busy = cells.find((x) => pending[keyOf(x)] !== undefined)
    if (busy) return { ok: false, code: "PENDING", cell: busy }
    const gone = cells.find((x) => {
      const at = cellPosition(rows, cols, x)
      return !at || !isEditable(at.r, at.c)
    })
    if (gone) return { ok: false, code: "CHANGED", cell: gone }
    const now = history.current() ?? tables
    const plan = planItems(now, items)
    if ("error" in plan) return { ok: false, code: plan.error, cell: plan.cell }
    dropDrafts(cells)
    if (plan.server.length) void adjust(items, plan.server, label, now, bulk)
    else if (history.commit(label, now, plan.tables) && bulk) bulkDone(items.length)
    return { ok: true }
  }

  /** Commits `text` into `cells` as one gesture (a typed entry; Ctrl/Cmd+Enter over a selection). */
  const commitText = (cells: CellRef[], text: string) => {
    const parsed = parseShorthand(text, "room", { minorUnits })
    const label = cells.length === 1 ? t("rates.ws.h.price", { cell: cellName(cells[0]) }) : t("rates.ws.h.prices", { count: cells.length })
    return commitItems(
      cells.map((cell) => ({ cell, parsed, text })),
      label,
      cells.length > 1,
    )
  }

  const onEdit = (at: GridCell, req: GridEditRequest) => {
    if (!isEditable(at.r, at.c)) return
    const cell = cellAt(at.r, at.c)
    if (!cell || pending[keyOf(cell)] !== undefined) return
    const draft = drafts[keyOf(cell)]
    closing.current = false
    setEditing({ cell, text: req.text ?? draft?.text ?? editTextOf(cell), selectAll: req.text === undefined })
  }

  const openPopover = (cell: CellRef, anchor: HTMLElement, typed?: ShResult) => {
    if (pending[keyOf(cell)] !== undefined) return
    popAnchor.current = anchor
    const room = roomsByType.get(cell.room)
    const own = modelCell(cell)?.rule
    const others = tables.rooms.map((r) => str(r.room_type)).filter((rt) => rt && rt !== cell.room)
    const base = room?.defaultBase && room.defaultBase !== cell.room ? room.defaultBase : (others[0] ?? "")
    let initial: PopoverRule
    if (typed?.ok && typed.kind === "rule" && !(room?.role === "base" && isRelativeOp(typed.op))) initial = { op: typed.op, value: typed.value, base }
    else if (own) initial = { op: str(own.op), value: str(own.value), base: str(own.base_room_type) || base }
    else if (room?.defaultRule && cell.period !== ALL_PERIODS)
      initial = { op: str(room.defaultRule.op), value: str(room.defaultRule.value), base: str(room.defaultRule.base_room_type) || base }
    else initial = { op: room?.role === "derived" ? "MULTIPLY" : "ABSOLUTE", value: "", base }
    setPop({ cell, initial })
  }

  /** The context menu of a cell (a right-click or long press, Shift+F10, the ContextMenu key):
   * "Edit rule…" on an editable cell and "Test this price" when the viewer may use the Price test;
   * without the second, an editable cell opens its rule popover at once, as before (S9). */
  const openCellMenu = (cell: CellRef, anchor: HTMLElement, editable: boolean) => {
    if (!onPriceTest) {
      if (editable) openPopover(cell, anchor)
      return
    }
    cellMenuAnchor.current = anchor
    setCellMenu({ cell, editable: editable && pending[keyOf(cell)] === undefined })
  }
  const cellMenuRef = useRef(openCellMenu)
  cellMenuRef.current = openCellMenu

  // "Show in grid" (S14): the cell of a room price rule is brought into view and focused; an issue
  // (S15) can also lead to a period's column header, or to the matrix as a whole
  const sectionRef = useRef<HTMLElement | null>(null)
  useEffect(() => {
    if (!show) return
    const target = show.target
    if (target.kind === "matrix" || target.kind === "period") {
      const id = target.kind === "matrix" ? cellIdOf({ room: target.room, period: target.period }) : periodHeaderId(target.period)
      requestAnimationFrame(() => {
        const el = Array.from(gridEl.current?.querySelectorAll<HTMLElement>("[data-cellid]") ?? []).find((x) => x.dataset.cellid === id)
        if (el) revealElement(el)
        else sectionRef.current?.scrollIntoView({ block: "start" })
      })
    } else if (target.kind === "region" && target.region === "matrix") requestAnimationFrame(() => sectionRef.current?.scrollIntoView({ block: "start" }))
    else return
    onShown?.(show.n)
  }, [show, onShown])

  const nextEditableRow = (r: number, c: number, dir: 1 | -1) => {
    for (let i = r + dir; i >= 0 && i < rows.length; i += dir) if (isEditable(i, c)) return i
    return r
  }

  /** Ends the edit: `move` the active cell (Enter / Tab) or stay on it. */
  const finish = (cell: CellRef, move: "down" | "up" | "left" | "right" | null) => {
    closing.current = true
    setEditing(null)
    const at = cellPosition(rows, cols, cell)
    if (!at) return
    const { r, c } = at
    if (move === "down" || move === "up") nav.focusCell(nextEditableRow(r, c, move === "down" ? 1 : -1), c)
    else if (move === "left" || move === "right") nav.focusCell(r, Math.max(0, Math.min(cols.length - 1, c + (move === "right" ? 1 : -1))))
    else focusAt(r, c)
  }

  /** Commits the editor's text; a refusal keeps the editor open and returns what its reading line
   * shows (which cell of a selection refused, and why). */
  const commitEditor = (ed: Editing, text: string, cells: CellRef[], move: "down" | "up" | "left" | "right" | null): string | void => {
    const single = cells.length === 1
    const cell = cells[0]
    // an unchanged edit text is not committed again: ADD -5 edits as "-5", which reads back as
    // SUBTRACT 5 (the same arithmetic, another op; ADR-061 S1)
    if (single && !drafts[keyOf(cell)] && text === editTextOf(cell)) return finish(ed.cell, move)
    const res = commitText(cells, text)
    if (res.ok) return finish(ed.cell, move)
    const own = res.cell.room === ed.cell.room && res.cell.period === ed.cell.period
    return own ? errorText(res.code) : t("rates.ws.bulk_error", { cell: cellName(res.cell), error: errorText(res.code) })
  }

  const selectedRefs = (): CellRef[] => {
    const cells = selection.selected.map((x) => cellAt(x.r, x.c)).filter((x): x is CellRef => x !== null)
    if (cells.length) return cells
    const a = nav.active
    const own = isEditable(a.r, a.c) ? cellAt(a.r, a.c) : null
    return own ? [own] : []
  }

  const onEditorKey = (e: KeyboardEvent<HTMLInputElement>, text: string): string | void => {
    const ed = editingRef.current
    if (!ed) return
    const cell = ed.cell
    // one routing for the three grids (ui/keys.ts): Ctrl/Cmd+R and Ctrl/Cmd+D never reach the
    // browser (reload, bookmark) and run no fill while a cell is being edited; Ctrl/Cmd+Z stays the
    // field's own undo; Ctrl/Cmd+S commits the entry first and the version editor saves it
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
        if (anchor) openPopover(cell, anchor, parseShorthand(text, "room", { minorUnits }))
        return
      }
      case "bulk": {
        // Ctrl/Cmd+Enter: every selected editable cell, each by its row's rule, as one entry
        e.preventDefault()
        const cells = selectedRefs()
        if (!cells.some((x) => x.room === cell.room && x.period === cell.period)) cells.push(cell)
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
    // leaving the cell commits a valid entry; an invalid one stays as an error draft (§3.4.1)
    const res = commitText([cell], text)
    if (!res.ok) setDrafts((d) => ({ ...d, [keyOf(res.cell)]: { text, code: res.code } }))
  }

  // ─── bulk tools (§3.10, S10) ─────────────────────────────────────────
  const refOf = (p: GridCell): CellRef | null => cellAt(p.r, p.c)

  /** Undo / redo (keys, toolbar, toast): recorded rows are put back, nothing calls the server. */
  const stepHistory = (which: "undo" | "redo", fromToast = false) => {
    const label = fromToast ? undoToast.undo() : which === "undo" ? history.undo() : history.redo()
    if (label) say(t(which === "undo" ? "rates.ws.bulk.undone" : "rates.ws.bulk.redone", { label }))
  }

  /** Fill → / Fill ↓ over the selection (fillRightPlan / fillDownPlan). A price into a formula row
   * waits for the inline "Set a fixed price override?"; a formula into a price row is refused. */
  const fill = (dir: "right" | "down", confirmed?: FillStep[]) => {
    if (!canEdit) return
    const steps: FillStep[] =
      confirmed ??
      (dir === "right" ? fillRightPlan(selection.selected) : fillDownPlan(selection.selected)).flatMap((x) => {
        const from = refOf(x.from)
        const to = refOf(x.to)
        return from && to ? [{ from, to }] : []
      })
    if (!steps.length) return say(t("rates.ws.fill.nothing"))
    const busy = steps.find((x) => pending[keyOf(x.to)] !== undefined || pending[keyOf(x.from)] !== undefined)
    if (busy) return void toast.error(t("rates.ws.bulk_error", { cell: cellName(busy.to), error: errorText("PENDING") }))
    const now = history.current() ?? tables
    const plan = planFill(now, steps)
    if ("error" in plan) return void toast.error(t("rates.ws.bulk_error", { cell: cellName(plan.cell), error: t(plan.error === "FILL_FORMULA" ? "rates.ws.fill.err_formula" : "rates.sh.err.NO_BASE_ROOM") }))
    if (plan.fixed.length && !confirmed) {
      setFillAsk({ dir, steps, fixed: plan.fixed.length })
      return
    }
    setFillAsk(null)
    dropDrafts(steps.map((x) => x.to))
    const label = t(dir === "right" ? "rates.ws.h.fill_right" : "rates.ws.h.fill_down", { count: plan.count })
    // a source that shows no rule clears its targets: the toast says how many (S10 review)
    if (history.commit(label, now, plan.tables)) bulkDone(plan.count, plan.cleared.length ? t("rates.ws.fill.cleared", { count: plan.cleared.length }) : undefined)
    else say(t("rates.ws.bulk.unchanged"))
  }

  /** The text Ctrl/Cmd+C copies for a cell: the canonical edit text of the rule it shows (its own,
   * else the All-periods rule it follows; "." as the decimal mark, §1.4 stable codes), a resolved
   * row's exact server amount (with the trailing zero edit text gives an amount that would read as
   * AMBIGUOUS), "" for nothing. */
  const copyText = (r: number, c: number): string => {
    const row = rows[r]
    const period = cols[c]
    if (!row || period === undefined) return ""
    if (row.kind !== "resolved") return cellCopyText(modelCell({ room: row.room, period }), { minorUnits })
    const v = period === ALL_PERIODS ? undefined : resolvedRooms.get(row.room)?.cells[period]
    return typeof v === "string" && v ? editText("ABSOLUTE", v, "room", { minorUnits }) : ""
  }

  const onCopy = (e: ClipboardEvent) => {
    // the entry rows of a selection that holds some (a paste writes entry rows only, so the block
    // pastes back onto the same rooms); resolved rows only when they are all that is selected
    const block = copyBlock(selection.state.ranges, copyText, (r) => Boolean(rows[r]?.editable))
    if (!block.length || !e.clipboardData) return
    e.clipboardData.setData("text/plain", encodeTSV(block))
    e.preventDefault()
    const count = block.reduce((n, row) => n + row.length, 0)
    say(t("rates.ws.bulk.copied", { count }))
  }

  const onPaste = (e: ClipboardEvent) => {
    if (!canEdit || !e.clipboardData) return
    e.preventDefault()
    const block = decodeTSV(e.clipboardData.getData("text/plain"))
    const origin = pasteOrigin(selection.state)
    const res = planPaste(block, origin, selection.selected, isEditable, (text) => parseShorthand(text, "room", { minorUnits }), {
      rows: rows.length,
      cols: cols.length,
      label: ({ r, c }) => `${periodName(cols[c] ?? "")} · ${roomName(rows[r]?.room ?? "")}`,
    })
    if (!res.ok) {
      if (res.code === "EMPTY") return say(t("rates.ws.paste.empty"))
      if (res.code === "NO_TARGET") return void toast.error(t("rates.ws.paste.no_target"))
      if (res.code === "SHAPE") return void toast.error(t("rates.ws.paste.shape", { rows: res.rows, cols: res.cols, available_rows: res.availableRows, available_cols: res.availableCols }))
      const lines = res.errors.map((x) => t("rates.ws.paste.cell_error", { cell: x.where ?? "", text: x.text, error: errorText(x.code) }))
      if (res.count > res.errors.length) lines.push(t("rates.ws.paste.more", { count: res.count - res.errors.length }))
      return void toast.error(
        <span className="block">
          <span className="block font-medium">{t("rates.ws.paste.refused")}</span>
          {lines.map((l, i) => (
            <span key={i} className="block">
              {l}
            </span>
          ))}
        </span>,
      )
    }
    const items: TextItem[] = res.items.flatMap((x) => {
      const cell = refOf(x.cell)
      return cell ? [{ cell, parsed: x.parsed, text: x.text }] : []
    })
    const label = items.length === 1 ? t("rates.ws.h.price", { cell: cellName(items[0].cell) }) : t("rates.ws.h.paste", { count: items.length })
    const done = commitItems(items, label, items.length > 1)
    if (!done.ok) toast.error(t("rates.ws.bulk_error", { cell: cellName(done.cell), error: errorText(done.code) }))
  }

  /** The Adjust… popover's Apply: the server's amounts, as ABSOLUTE, in one history entry. */
  const applyAdjusted = (targets: AdjustTarget[], answers: AdjustAnswer[], count: number): string | void => {
    const busy = targets.find((x) => pending[keyOf(x.cell)] !== undefined)
    if (busy) return t("rates.ws.bulk_error", { cell: cellName(busy.cell), error: errorText("PENDING") })
    let refused: { error: string; cell: CellRef } | null = null
    const committed = history.apply(t("rates.ws.h.adjust", { count }), (tb) => {
      const r = applyAdjust(tb, targets, answers)
      if ("error" in r) {
        refused = r
        return tb
      }
      return r.tables
    })
    const f = refused as { error: string; cell: CellRef } | null
    if (f) return t("rates.ws.bulk_error", { cell: cellName(f.cell), error: errorText(f.error) })
    dropDrafts(targets.map((x) => x.cell))
    setAdjusting(null)
    if (committed) bulkDone(count)
  }

  const openAdjust = () => {
    const cells = selectedRefs()
    if (cells.length) setAdjusting(cells)
  }

  // stable callbacks for the memoised toolbar and toast (the latest handlers through a ref)
  const focusActive = () => focusAt(nav.active.r, nav.active.c)
  const bulk = useRef({ fill, openAdjust, stepHistory, focusActive })
  bulk.current = { fill, openAdjust, stepHistory, focusActive }
  const onToolbarFill = useCallback((dir: "right" | "down") => bulk.current.fill(dir), [])
  const onToolbarAdjust = useCallback(() => bulk.current.openAdjust(), [])
  const onToolbarUndo = useCallback(() => bulk.current.stepHistory("undo"), [])
  const onToolbarRedo = useCallback(() => bulk.current.stepHistory("redo"), [])
  const onToastUndo = useCallback(() => bulk.current.stepHistory("undo", true), [])
  // the toast goes with its Undo or close button: when it held the focus, the focus goes back to
  // the grid's active cell (as after the fill confirmation), not to the page
  const onToastFocusBack = useCallback(() => bulk.current.focusActive(), [])

  /** The editing shortcuts of a focused cell: undo, redo, fill right, fill down (layout-free). */
  const onShortcut = (which: EditShortcut) => {
    if (which === "undo" || which === "redo") stepHistory(which)
    else fill(which === "fill_right" ? "right" : "down")
  }

  // the clipboard events reach the document while a cell (a focusable element that is not
  // editable) has the focus, not always the cell itself: they are taken there, for this grid's
  // cells only, and the latest handlers are read through a ref
  const clip = useRef({ onCopy, onPaste })
  clip.current = { onCopy, onPaste }
  useEffect(() => {
    const mine = () => {
      const a = document.activeElement
      return a instanceof HTMLElement && a.getAttribute("role") === "gridcell" && Boolean(gridEl.current?.contains(a))
    }
    const copy = (e: ClipboardEvent) => {
      if (mine()) clip.current.onCopy(e)
    }
    const paste = (e: ClipboardEvent) => {
      if (mine()) clip.current.onPaste(e)
    }
    document.addEventListener("copy", copy)
    document.addEventListener("paste", paste)
    return () => {
      document.removeEventListener("copy", copy)
      document.removeEventListener("paste", paste)
    }
  }, [])

  const onKey = (e: KeyboardEvent<HTMLElement>, at: GridCell): boolean | void => {
    const cell = cellAt(at.r, at.c)
    // the keyboard's context menu, on every cell (read-only and resolved ones too: Test this price)
    if ((e.key === "F10" && e.shiftKey) || e.key === "ContextMenu") {
      e.preventDefault()
      if (cell) openCellMenu(cell, e.currentTarget, isEditable(at.r, at.c))
      return true
    }
    if (!canEdit) return
    const shortcut = editShortcut(e)
    if (shortcut) {
      // only while the grid has focus: Ctrl+R / Ctrl+D would reload / bookmark the page
      e.preventDefault()
      onShortcut(shortcut)
      return true
    }
    if (e.key === "Enter" && e.altKey) {
      e.preventDefault()
      if (cell && isEditable(at.r, at.c)) openPopover(cell, e.currentTarget)
      return true
    }
    if ((e.key === "Delete" || e.key === "Backspace") && !e.ctrlKey && !e.metaKey && !e.altKey) {
      const cells = selectedRefs().filter((x) => pending[keyOf(x)] === undefined)
      if (!cells.length) return
      e.preventDefault()
      dropDrafts(cells)
      const done = edit(cells.length === 1 ? t("rates.ws.h.clear", { cell: cellName(cells[0]) }) : t("rates.ws.h.clear_many", { count: cells.length }), (tb) => clearCells(tb, cells))
      if (done && cells.length > 1) bulkDone(cells.length)
      return true
    }
    if (e.key === "Escape" && cell && drafts[keyOf(cell)] && !selection.multiple) {
      e.preventDefault()
      dropDrafts([cell])
      return true
    }
  }

  // one tab stop (§3.19): the headers' controls are reached with the arrows from the first row or column
  const nav = useGridNavigation({ rows: rows.length, cols: cols.length, selection, onEdit: canEdit ? onEdit : undefined, onKey, onEdge: (edge, cell) => focusHeaderLane(gridEl.current, edge, cell) })
  // with no cell (no room yet) the grid has no tab stop: its header controls stay Tab stops
  const laneTab = rows.length > 0 && cols.length > 0 ? -1 : 0
  const laneRowsOf = (roomIndex: number) => rows.flatMap((x, i) => (x.roomIndex === roomIndex ? [String(i)] : [])).join(" ")
  const setGrid = useCallback(
    (el: HTMLDivElement | null) => {
      gridEl.current = el
      nav.gridRef(el)
    },
    [nav],
  )

  // header clicks (and the headers' "Select prices" menu items) select a row's or a column's
  // editable cells and focus the first of them, so the keys (Ctrl+R, Ctrl+C …) act on them at
  // once. Stable callbacks: the headers are memoised.
  const shape = useRef({ rows, cols, isEditable, nav })
  shape.current = { rows, cols, isEditable, nav }

  // a room added from the Add room menu takes the focus on its first cell, after the render that
  // shows it: the menu's button that the focus returned to is disabled once nothing is left to add
  // (S16 re-review 2)
  const [focusRoom, setFocusRoom] = useState<string | null>(null)
  useEffect(() => {
    if (!focusRoom) return
    setFocusRoom(null)
    const r = rows.findIndex((x) => model.rooms[x.roomIndex]?.room_type === focusRoom)
    if (r >= 0) nav.focusCell(r, 0)
    // after the render that shows the room
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [focusRoom, rows])
  const { selectRow, selectCol } = selection
  const focusCellEl = (r: number, c: number) => gridEl.current?.querySelector<HTMLElement>(`[data-cell="${r}:${c}"]`)?.focus()
  const pickRow = useCallback(
    (r: number, add: boolean, extend = false) => {
      const { cols: cs, isEditable: ed } = shape.current
      const c = cs.findIndex((_, i) => ed(r, i))
      if (c < 0) return
      selectRow(r, { add, extend })
      focusCellEl(r, c)
    },
    [selectRow],
  )
  const pickCol = useCallback(
    (c: number, add: boolean, extend = false) => {
      const { rows: rs, isEditable: ed } = shape.current
      const r = rs.findIndex((_, i) => ed(i, c))
      if (r < 0) return
      selectCol(c, { add, extend })
      focusCellEl(r, c)
    },
    [selectCol],
  )

  // "Remove room" and "Delete period" take away the header, its menu and the confirmation that had
  // the focus: it goes to the nearest cell left (the same column for a room, the same row for a
  // period), so the keys (Ctrl/Cmd+Z) keep working where the user was; with no cell left, to "Add
  // room" or "+ Period" (S16 review). After the render without the room or period.
  const focusAfterRemoval = useCallback((what: { room: number } | { period: number }) => {
    requestAnimationFrame(() => {
      const { rows: rs, cols: cs, nav: n } = shape.current
      if (!rs.length || !cs.length) {
        sectionRef.current?.querySelector<HTMLElement>("[data-add-room] button, [data-add-period]")?.focus()
        return
      }
      if ("room" in what) {
        const last = rs[rs.length - 1].roomIndex
        const room = Math.min(what.room, last)
        const r = rs.findIndex((x) => x.roomIndex === room)
        n.focusCell(r < 0 ? rs.length - 1 : r, Math.min(n.active.c, cs.length - 1))
      } else {
        // the period's column was `index + 1` (All periods is column 0): the next period, else the previous
        n.focusCell(Math.min(n.active.r, rs.length - 1), Math.min(what.period + 1, cs.length - 1))
      }
    })
  }, [])
  const onRoomRemoved = useCallback((room: number) => focusAfterRemoval({ room }), [focusAfterRemoval])
  const onPeriodRemoved = useCallback((period: number) => focusAfterRemoval({ period }), [focusAfterRemoval])

  // ─── what each cell shows ────────────────────────────────────────────
  const readingText = (cell: CellRef, reading: Reading): string => {
    const name = cellName(cell)
    switch (reading.kind) {
      case "error":
        return errorText(reading.code)
      case "unchanged":
        return t("rates.sh.read.unchanged")
      case "clear":
        return reading.follows ? t("rates.sh.read.clear_follows", { cell: name, rule: ruleText(reading.follows) }) : t("rates.sh.read.clear", { cell: name })
      case "same":
        return t("rates.sh.read.same", { cell: name, rule: ruleText(reading.rule) })
      case "price":
        return t(reading.fixed ? "rates.sh.read.fixed" : "rates.sh.read.price", { cell: name, amount: amount(reading.value) })
      case "formula": {
        const s = t("rates.sh.read.formula", { cell: name, formula: formulaText(reading.op, reading.value, reading.base) })
        return reading.replacesFixed ? t("rates.sh.read.replaces_fixed", { reading: s, amount: amount(reading.replacesFixed) }) : s
      }
      case "adjust":
        // "50%" (PERCENT_OF: 35.00 from 70.00) must not read like "+50%" (ADJUST_PERCENT: 105.00)
        return t(reading.op === "PERCENT_OF" ? "rates.sh.read.adjust_pct" : "rates.sh.read.adjust", { cell: name, current: amount(reading.current), rule: opText(reading.op, reading.value) })
    }
  }

  type View = { tone: CellTone; content: ReactNode; state: MatrixCellStateKey; value?: string; tooltip?: string; error?: string }

  const entryView = (cell: CellRef, mc: RoomCell | undefined): View => {
    const rule = mc?.rule
    const def = mc?.defaultRule
    switch (mc?.state) {
      case "manual":
        return { tone: "plain", content: shortText(rule as Row), state: "manual", value: amount(rule?.value) }
      case "formula-default":
        return { tone: "plain", content: <span className="text-zinc-700">{shortText(rule as Row)}</span>, state: "formula-default", value: ruleText(rule as Row) }
      case "inherited":
        return { tone: "muted", content: `↳ ${shortText(def as Row)}`, state: "inherited", value: ruleText(def as Row) }
      case "period-override":
        return {
          tone: "override",
          content: `◆ ${shortText(rule as Row)}`,
          state: "period-override",
          value: ruleText(rule as Row),
          tooltip: def
            ? t("rates.ws.cell.override_tip", { period: cell.period, default: shortText(def), rule: ruleText(rule as Row) })
            : t("rates.ws.cell.own_rule_tip", { period: cell.period, rule: ruleText(rule as Row) }),
        }
      case "fixed-override":
        return {
          tone: "fixed",
          content: (
            <>
              <Pin className="mr-1 inline size-3 -translate-y-px text-amber-800" aria-hidden />= {amount(rule?.value)}
            </>
          ),
          state: "fixed-override",
          value: amount(rule?.value),
          tooltip: def ? t("rates.ws.cell.fixed_tip", { amount: amount(rule?.value), rule: ruleText(def) }) : undefined,
        }
      case "inherit-rule":
        return {
          tone: "muted",
          content: (
            <>
              ↳ <span className="ml-1 rounded bg-zinc-100 px-1 text-[10px] text-zinc-600">{t("rates.ws.state.inherit_tag")}</span>
            </>
          ),
          state: "inherit-rule",
          value: def ? ruleText(def) : undefined,
        }
      default:
        return cell.period === ALL_PERIODS ? { tone: "muted", content: "—", state: "empty" } : { tone: "missing", content: "—", state: "missing" }
    }
  }

  const resolvedView = (cell: CellRef): View => {
    if (cell.period === ALL_PERIODS) return { tone: "resolved", content: "", state: "resolved_all" }
    const res = resolvedRooms.get(cell.room)
    const err = res?.errors?.[cell.period]
    if (err)
      return {
        tone: "error",
        content: (
          <>
            <AlertTriangle className="mr-0.5 inline size-3 -translate-y-px" aria-hidden />
            {t("rates.rates.unsellable")}
          </>
        ),
        state: "unsellable",
        value: err,
        tooltip: err,
        error: err,
      }
    const v = res?.cells[cell.period]
    if (v === undefined || v === null) return { tone: "resolved", content: matrix ? "—" : "…", state: matrix ? "no_price" : "loading" }
    const frac = v.split(".")[1]?.replace(/0+$/, "") ?? ""
    return {
      tone: "resolved",
      content: <Money amount={v} currency={ccy} />,
      state: "resolved",
      value: `${ccy} ${amount(v)}`,
      tooltip: frac.length > minorUnits ? t("rates.ws.cell.exact", { value: decText(v, minorUnits) }) : undefined,
    }
  }

  /** The selected cells of a row as a signature ("0110…"): a row re-renders when it changes. */
  const selectedKey = (r: number) => {
    let out = ""
    for (let c = 0; c < cols.length; c++) out += selection.isSelected(r, c) ? "1" : "0"
    return out
  }
  const editorFor = (ed: Editing) => {
    const cell = ed.cell
    return (
      <CellEditor
        label={t("rates.ws.cell.input", { cell: cellName(cell) })}
        initialText={ed.text}
        selectAll={ed.selectAll}
        readingFor={(text) => {
          const reading = readingOf(history.current() ?? tables, cell.room, cell.period, parseShorthand(text, "room", { minorUnits }))
          return { text: readingText(cell, reading), invalid: reading.kind === "error" }
        }}
        onKey={onEditorKey}
        onBlur={onEditorBlur}
      />
    )
  }

  const roTip = doc.status !== "Draft" ? t("rates.ws.cell.ro_published") : t("rates.ws.cell.ro_permission")

  /** What one cell shows, with its accessible name, tooltip and popover triggers. */
  const cellView = (row: GridRow, r: number, period: string, c: number): CellView => {
    const room = model.rooms[row.roomIndex]
    const cell = { room: room.room_type, period }
    const k = keyOf(cell)
    const resolved = row.kind === "resolved"
    const editable = isEditable(r, c)
    let view = resolved ? resolvedView(cell) : entryView(cell, room.cells[period])
    const draft = !resolved ? drafts[k] : undefined
    const waiting = !resolved ? pending[k] : undefined
    if (draft) {
      const message = draft.message ?? errorText(draft.code ?? "SYNTAX")
      view = {
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
    } else if (waiting !== undefined) {
      // a base-room cell shows the price sent; another cell of the same entry what it holds now
      view = {
        tone: "pending",
        content: (
          <>
            {waiting === null ? view.content : amount(waiting)} → <Loader2 className="ml-0.5 inline size-3 animate-spin" aria-hidden />
          </>
        ),
        state: "pending",
        value: waiting === null ? view.value : amount(waiting),
      }
    }
    const state = t(`rates.ws.state.${view.state}`)
    // a resolved value older than the state on screen says so to a screen reader too (§3.3.3)
    const stateText = resolved && stale ? t(STALE_STATE[status], { state }) : state
    const cellId = resolved ? undefined : cellIdOf(cell)
    return {
      cellId,
      label: view.value ? t("rates.ws.cell.label", { cell: cellName(cell), state: stateText, value: view.value }) : t("rates.ws.cell.label_bare", { cell: cellName(cell), state: stateText }),
      tone: view.tone,
      content: view.content,
      tooltip: view.tooltip ?? (!editable ? (resolved ? t("rates.ws.cell.ro_resolved") : roTip) : undefined),
      readOnly: !editable,
      stale: resolved && stale,
      error: view.error,
      issue: cellId ? issueAt(cellId) : undefined,
      trigger: editable && waiting === undefined ? { label: t("rates.rates.edit_cell", { cell: cellName(cell) }), onOpen: (el) => openPopover(cell, el) } : undefined,
      onContextMenu:
        editable || onPriceTest
          ? (e: MouseEvent<HTMLElement>) => {
              e.preventDefault()
              cellMenuRef.current(cell, e.currentTarget, editable)
            }
          : undefined,
    }
  }
  // computed when the draft, the server's answers, the entries in flight or the language change;
  // moving the active cell or the selection re-renders only the cells whose tab stop or selection
  // changed (MatrixCell is memoised on these views)
  const cellViews = useMemo(
    () => rows.map((row, r) => cols.map((period, c) => cellView(row, r, period, c))),
    // everything cellView reads
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [rows, cols, model, tables, resolvedRooms, matrix, stale, status, drafts, pending, canEdit, t, decimalMark, minorUnits, doc.status, ccy, names, issueAt],
  )
  // a period header's issues, as one stable object per header (the headers are memoised)
  const periodIssues = useMemo(() => new Map(model.periods.map((p) => [p.code, issueAt(periodHeaderId(p.code))])), [model.periods, issueAt])
  const periodsForPopover = model.periods.map((p) => ({ code: p.code, label: p.name ? `${p.code} · ${p.name}` : p.code }))
  const available = doc.room_types.filter((r) => !tables.rooms.some((x) => str(x.room_type) === r.name))
  const knownRooms = new Set(model.rooms.map((x) => x.room_type))
  const knownPeriods = new Set(model.periods.map((x) => x.code))
  const orphans = tables.period_rates.filter((r) => !knownRooms.has(str(r.room_type)) || (str(r.period_code) && !knownPeriods.has(str(r.period_code)))).length
  const stay = state.selling ?? doc.selling

  const rowLabel = (room: MatrixRoom, row: GridRow) => {
    const label = room.rows.find((x) => x.kind === row.kind)?.label
    const n = includedAdults(room.room_type)
    switch (label) {
      case "base_room":
        return n ? t("rates.ws.row.base_room_n", { count: n }) : t("rates.ws.row.base_room")
      case "resolved_room":
        return n ? t("rates.ws.row.resolved_room_n", { count: n }) : t("rates.ws.row.resolved_room")
      default:
        return t(`rates.ws.row.${label ?? "formula"}`)
    }
  }
  const derivationOf = (room: MatrixRoom) => {
    const def = room.defaultRule
    if (room.role === "manual") return t("rates.ws.room.manual")
    if (def && isRelativeOp(def.op)) return formulaText(str(def.op), str(def.value), str(def.base_room_type))
    return t("rates.ws.room.by_period")
  }

  return (
    <section ref={sectionRef} aria-labelledby="pm-title" className="scroll-mt-44 space-y-2">
      <div className="flex flex-wrap items-center gap-x-3 gap-y-2">
        <h2 id="pm-title" className="text-base font-semibold text-zinc-900">
          {t("rates.tab.rates")}
        </h2>
        <Badge tone="info">{t(`rates.rates.unit.${basis}`, { ccy })}</Badge>
        {preview?.savedOnly && (
          <Tooltip content={t("rates.ws.over_cap", { max: preview.maxRows ?? "" })}>
            <Badge tone="warning" tabIndex={0}>
              {t("rates.ws.saved_only")}
            </Badge>
          </Tooltip>
        )}
        {/* the prices' state is shown, not announced: the live region is for bulk and undo messages */}
        <span className="inline-flex min-h-5 items-center gap-1 text-xs text-zinc-500" data-resolved-status={status}>
          {preview?.pricesLoading ? (
            <>
              <Loader2 className="size-3.5 animate-spin" aria-hidden />
              {t("rates.ws.updating")}
            </>
          ) : status === "failed" ? (
            <>
              <AlertTriangle className="size-3.5 text-amber-600" aria-hidden />
              {t("rates.ws.not_updated")}
            </>
          ) : null}
        </span>
        <span role="status" aria-live="polite">
          <span className="sr-only">{announce}</span>
        </span>
        {/* a base-room entry waiting for the server's adjustment is typed input not in the version
            yet: the tab asks before it closes (keptState.UNCOMMITTED_INPUT, S16 re-review) */}
        {Object.keys(pending).length > 0 && <span hidden data-uncommitted="" data-changed="" data-pending-adjustment="" />}
        <span className="ml-auto">
          <Checkbox label={t("rates.ws.show_resolved")} checked={showResolved} onChange={(e) => setShowResolved(e.target.checked)} />
        </span>
      </div>
      {canEdit && (
        <p className="text-xs text-zinc-500">
          {t("rates.ws.matrix_hint")} {t("rates.kbd.lane_note")}
        </p>
      )}
      <span id={laneNoteId} className="sr-only">
        {t("rates.kbd.lane_note")}
      </span>
      {canEdit && (
        <BulkToolbar
          canFillRight={fillRightPlan(selection.selected).length > 0}
          canFillDown={fillDownPlan(selection.selected).length > 0}
          canAdjust={selectedRefs().length > 0}
          onFill={onToolbarFill}
          onAdjust={onToolbarAdjust}
          adjustRef={adjustRef}
          adjustOpen={adjusting !== null}
          canUndo={history.canUndo}
          canRedo={history.canRedo}
          onUndo={onToolbarUndo}
          onRedo={onToolbarRedo}
        />
      )}
      {fillAsk && (
        <FillConfirm
          message={t("rates.ws.fill.confirm_body", { count: fillAsk.fixed })}
          onConfirm={() => {
            const ask = fillAsk
            setFillAsk(null)
            fill(ask.dir, ask.steps)
            focusAt(nav.active.r, nav.active.c)
          }}
          onCancel={() => {
            setFillAsk(null)
            focusAt(nav.active.r, nav.active.c)
          }}
        />
      )}
      {preview?.buildError && (
        <Notice tone="warning" title={t("rates.ws.build_error")}>
          {preview.buildError}
        </Notice>
      )}
      {preview?.error && <Notice tone="danger">{preview.error.message}</Notice>}
      {orphans > 0 && <Notice tone="warning">{t("rates.ws.orphans", { count: orphans })}</Notice>}
      {model.rooms.length === 0 && <Notice tone="info">{canEdit ? t("rates.ws.room.none") : t("rates.rooms.empty")}</Notice>}

      <PeriodStrip tables={tables} stayFrom={stay?.stay_from} stayTo={stay?.stay_to} />
      <div ref={syncScroll} data-scroll-sync className="max-h-[70vh] overflow-auto rounded-lg border border-zinc-200 bg-white pb-12">
        <div
          role="grid"
          aria-label={t("rates.rates.caption")}
          aria-describedby={laneNoteId}
          aria-rowcount={rows.length + 1}
          aria-colcount={cols.length + 2}
          aria-readonly={readOnly || undefined}
          aria-multiselectable
          ref={setGrid}
          onKeyDownCapture={(e) => void headerLaneKeyDown(e, gridEl.current, nav.focusCell, { rows: rows.length, cols: cols.length })}
          onFocus={(e) => {
            // a cell (or its editor) got the focus: its column is the matrix's active period, and
            // its room and period are where the header's Price test starts
            const at = (e.target as HTMLElement).closest<HTMLElement>("[data-cell]")?.dataset.cell
            if (!at) return
            const [r, c] = at.split(":").map(Number)
            const period = cols[c]
            const room = rows[r]?.room
            if (period === undefined) return
            onActivePeriod?.(period)
            if (room) onActiveCell?.({ room, period })
          }}
          className="w-max min-w-full text-sm"
        >
          <div role="row" className="sticky top-0 z-[2] grid bg-white" style={{ gridTemplateColumns: template }}>
            <div role="columnheader" className="sticky left-0 z-[4] flex items-end gap-1.5 border-r border-b border-zinc-200 bg-white px-3 py-1.5 text-xs font-semibold text-zinc-600">
              {t("rates.f.room_type")}
              {preview?.pricesLoading && <Loader2 className="size-3 animate-spin text-zinc-400" aria-hidden />}
            </div>
            <div
              role="columnheader"
              onMouseDown={(e) => headerPick(e, canEdit ? (add, extend) => pickCol(0, add, extend) : undefined)}
              className="flex flex-col justify-end border-r border-b border-zinc-200 bg-white px-2 py-1.5 text-left"
            >
              <span className="text-xs font-semibold text-zinc-800">{t("rates.rates.all_periods")}</span>
              <span className="text-[11px] text-zinc-500">{t("rates.ws.default")}</span>
            </div>
            {model.periods.map((p, i) => (
              <PeriodHeader
                key={p.key}
                period={p}
                index={i}
                count={model.periods.length}
                tables={tables}
                readOnly={readOnly}
                edit={edit}
                fresh={freshPeriod === p.code}
                onFreshDone={freshDone}
                decimalMark={decimalMark}
                minorUnits={minorUnits}
                onSelect={canEdit ? pickCol : undefined}
                issue={periodIssues.get(p.code)}
                onRemoved={onPeriodRemoved}
                onDuplicated={setRenamePeriodCode}
                renameNow={renamePeriodCode === p.code}
                onRenameOpened={renameOpened}
                laneTab={laneTab}
              />
            ))}
            <AddPeriodHeader readOnly={readOnly} edit={edit} onAdded={setFreshPeriod} col={cols.length} laneTab={laneTab} />
          </div>

          {rows.map((row, r) => {
            const room = model.rooms[row.roomIndex]
            return (
              // keyed by the row's place in its room, not its kind: a manual room that gets a formula keeps
              // its cells (and an open popover its anchor)
              <div role="row" key={`${room.key}|${row.first ? 0 : 1}`} className="grid" style={{ gridTemplateColumns: template }}>
                <RoomRowHeader
                  room={room}
                  row={row}
                  rowLabel={rowLabel(room, row)}
                  roomName={roomName}
                  derivation={derivationOf(room)}
                  tables={tables}
                  readOnly={readOnly}
                  index={row.roomIndex}
                  count={model.rooms.length}
                  capacity={resolvedRooms.get(room.room_type)?.capacity}
                  edit={edit}
                  r={r}
                  onSelect={canEdit && row.editable ? pickRow : undefined}
                  onRemoved={onRoomRemoved}
                  laneRows={laneRowsOf(row.roomIndex)}
                  laneTab={laneTab}
                />
                <MatrixRowCells
                  r={r}
                  views={cellViews[r]}
                  nav={nav}
                  activeC={nav.active.r === r ? nav.active.c : -1}
                  selected={selectedKey(r)}
                  selState={nav.active.r === r ? selection.state : undefined}
                  tint={selection.multiple}
                  blockStart={row.first}
                  editC={editing && editPos && editPos.r === r ? editPos.c : -1}
                  editor={editing && editPos && editPos.r === r ? editorFor(editing) : undefined}
                />
                <div aria-hidden className={row.first ? "border-t-2 border-b border-t-zinc-200 border-b-zinc-100" : "border-b border-zinc-100"} />
              </div>
            )
          })}
        </div>
      </div>

      {canEdit && (
        <div className="flex flex-wrap items-center gap-2 pt-1">
          <AddMenu
            label={t("rates.ws.room.add")}
            marker="add-room"
            emptyText={t("rates.ws.room.all_added")}
            items={available.map((r) => ({ value: r.name, label: r.room_type_name || r.name }))}
            onAdd={(rt) => {
              edit(t("rates.ws.h.add_room", { room: roomName(rt) }), (tb) => addRoom(tb, rt))
              setFocusRoom(rt)
            }}
          />
          {model.rooms.length > 0 && !model.baseRoom && <span className="text-xs text-amber-800">{t("rates.ws.room.no_base")}</span>}
        </div>
      )}

      {pop && (
        <RuleEditorPopover
          key={keyOf(pop.cell)}
          anchorRef={popAnchor}
          onClose={() => setPop(null)}
          roomName={roomName(pop.cell.room)}
          periodName={periodName(pop.cell.period)}
          period={pop.cell.period}
          periods={periodsForPopover}
          baseOptions={tables.rooms
            .map((r) => str(r.room_type))
            .filter((rt) => rt && rt !== pop.cell.room)
            .map((rt) => ({ value: rt, label: roomName(rt) }))}
          initial={pop.initial}
          hasRule={Boolean(modelCell(pop.cell)?.rule)}
          minorUnits={minorUnits}
          ccy={ccy}
          decimalMark={decimalMark}
          onApply={(periods, rule) => {
            const cell = pop.cell
            dropDrafts(periods.map((period) => ({ room: cell.room, period })))
            edit(rule ? t("rates.ws.h.rule", { cell: cellName(cell) }) : t("rates.ws.h.clear", { cell: cellName(cell) }), (tb) => applyPopover(tb, cell.room, periods, rule))
            setPop(null)
            refocus(cell)
          }}
        />
      )}
      {cellMenu && (
        <ContextMenu open onClose={() => setCellMenu(null)} anchorRef={cellMenuAnchor} label={t("rates.ws.cell.menu", { cell: cellName(cellMenu.cell) })}>
          {cellMenu.editable && (
            <MenuItem
              icon={<Pencil className="size-4" />}
              shortcut="Alt+↵"
              keyshortcuts="Alt+Enter"
              onSelect={() => {
                const anchor = cellMenuAnchor.current
                if (anchor) openPopover(cellMenu.cell, anchor)
              }}
            >
              {t("rates.ws.cell.menu_edit")}
            </MenuItem>
          )}
          {onPriceTest && (
            <MenuItem icon={<Calculator className="size-4" />} onSelect={() => onPriceTest(cellMenu.cell)}>
              {t("rates.ws.cell.menu_test")}
            </MenuItem>
          )}
        </ContextMenu>
      )}
      {adjusting && (
        <AdjustPopover
          anchorRef={adjustRef}
          onClose={() => setAdjusting(null)}
          version={doc.name}
          tables={tables}
          cells={adjusting}
          minorUnits={minorUnits}
          ccy={ccy}
          cellName={cellName}
          amount={amount}
          onApply={applyAdjusted}
        />
      )}
      <UndoToastView toast={undoToast.toast} onUndo={onToastUndo} onDismiss={undoToast.dismiss} onHold={undoToast.hold} onFocusBack={onToastFocusBack} />
    </section>
  )
}
