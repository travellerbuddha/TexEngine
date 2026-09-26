// The "Boards" region of Pricing (PRICING_WORKSPACE_UX.md §3.12, §3.4.4 O1–O3, §3.19; slice S13): a
// collapsible section under Occupancy & child pricing. Collapsed, it reads as chips ("UAI BASE ·
// AI −5 % · HB −20.00 per adult"); expanded, it is a keyboard grid "Board supplements by period" on
// the matrix's column template: one row per board (in `boards` order) and an indented row for each
// room-scoped rule ("HB · Deluxe only"), All periods and the period columns.
//
// Cells take the `board` shorthand with the matrix's editing model (type, F2 / Enter, Enter moves
// down, Tab sideways, Escape reverts, an invalid entry stays as an error draft, Ctrl/Cmd+Enter writes
// every selected cell, Delete clears): a bare 20 is ABSOLUTE per room per night (O1), +20 ADD per
// adult, -20 ADD -20 per adult (O2), 5% / ±5% ADJUST_PERCENT (O3), BASE the base board (exclusive,
// in a board's own All periods cell only). The reading line always names the unit. Clearing a
// period or room cell removes that row; clearing a board's own All periods cell removes the board
// after an inline confirmation. The row popover (Alt+Enter, or the row's terms button) edits child
// %, infants free, the label and the rooms; "Add board" adds a board (the first is the base board).
// Every change is one workspace history entry (S9). The column of the matrix's active period is
// highlighted here, and #boards opens the section. Cells carry data-cellid
// "board:{board}|{room}|{period}" for anchoring (S15) and "Show in grid" (S14).
import { useCallback, useEffect, useId, useMemo, useRef, useState, useSyncExternalStore, type KeyboardEvent, type ReactNode, type RefObject } from "react"
import { AlertTriangle, ChevronDown, ChevronRight, SlidersHorizontal, X } from "lucide-react"
import { useMatrixOnlyBulk } from "./useMatrixOnlyBulk"
import { AddMenu } from "./AddMenu"
import { cn } from "../../../../lib/utils"
import { minorUnits as currencyMinorUnits } from "../../../lib/format"
import { useTexT } from "../../../i18n"
import {
  Badge,
  Button,
  Checkbox,
  DecimalInput,
  editorKeyAction,
  editShortcut,
  Field,
  focusHeaderLane,
  headerLaneKeyDown,
  refocusIfLost,
  focusCellNow,
  IconButton,
  Input,
  Notice,
  Popover,
  revealElement,
  Select,
  useGridNavigation,
  useGridSelection,
  useScrollSyncRef,
  useToast,
  type GridCell,
  type GridEditRequest,
} from "../../../ui"
import type { TabProps } from "../contracts/tabs/shared"
import { BOARDS, enumLabel } from "../lib/options"
import { normaliseDecimal, parseShorthand } from "../lib/shorthand"
import type { Row } from "../lib/types"
import { decText } from "../lib/util"
import { UndoToastView } from "./BulkToolbar"
import { CellEditor, MatrixRowCells, type CellTone, type CellView } from "./MatrixCell"
import { KEPT } from "./keptState.ts"
import { useKeptState } from "./useKeptState"
import { columnTemplate, decimalMarkOf } from "./matrixView.ts"
import {
  addBoard,
  ALL_PERIODS,
  boardEditText,
  boardModel,
  boardReadingOf,
  boardSummary,
  boardTermsOf,
  moveBoardRows,
  planBoardEntries,
  removeBoard,
  removeBoardRow,
  setBoardTerms,
  type BoardCell,
  type BoardEntryItem,
  type BoardIdentity,
  type BoardRow,
  type BoardTerms,
} from "./model.ts"
import { boardCellId } from "./issues.ts"
import { isSet, str } from "./rows.ts"
import type { PricingRegion } from "./sections.ts"
import { useCellIssues } from "./useCellIssues"
import { useUndoToast, type WorkspaceHistory } from "./useWorkspaceHistory"
import type { BoardCellStateKey } from "./stateKeys.ts"

const OPEN_KEY = "tex.rates.ws.boards_open"

function readOpen(fallback: boolean): boolean {
  try {
    const s = window.localStorage.getItem(OPEN_KEY)
    return s === null ? fallback : s === "1"
  } catch {
    return fallback
  }
}

function storeOpen(open: boolean) {
  try {
    window.localStorage.setItem(OPEN_KEY, open ? "1" : "0")
  } catch {
    /* storage blocked: the choice lasts until reload */
  }
}

/** The matrix's active period, shared with the boards grid without re-rendering the rest of
 * Pricing: the matrix sets it when one of its cells gets the focus, the boards grid subscribes. */
export interface PeriodChannel {
  get: () => string | null
  set: (period: string | null) => void
  subscribe: (listener: () => void) => () => void
}

export function usePeriodChannel(): PeriodChannel {
  const [channel] = useState<PeriodChannel>(() => {
    let value: string | null = null
    const listeners = new Set<() => void>()
    return {
      get: () => value,
      set: (period) => {
        if (period === value) return
        value = period
        for (const l of listeners) l()
      },
      subscribe: (listener) => {
        listeners.add(listener)
        return () => {
          listeners.delete(listener)
        }
      },
    }
  })
  return channel
}

const noSubscribe = () => () => {}
const noPeriod = () => null

/** A boards grid cell: a row of the model (by its id, "board|room") and a period ("" = All periods). */
interface BoardRef {
  row: string
  period: string
}

interface Editing {
  cell: BoardRef
  text: string
  selectAll: boolean
}

interface Draft {
  text: string
  code: string
}

/** A gesture that removes boards, waiting for "Remove {board}?" */
interface Confirming {
  cells: BoardRef[]
  text: string
  label: string
  boards: string[]
  rows: number
}

const keyOf = (c: BoardRef) => `${c.row}\u0000${c.period}`
const rowIdOf = (id: BoardIdentity) => `${id.board}|${id.room_type}`
/** The DOM id of a boards cell (data-cellid, issues.boardCellId): S15 anchors issues on it, S14
 * "Show in grid" finds it. */
export { boardCellId }
const hasRows = (boards: readonly Row[], id: BoardIdentity) => boards.some((r) => str(r.board) === id.board && str(r.room_type) === id.room_type)
/** Entry errors with a board-specific message; the others read as in every grid (rates.sh.err.*). */
const BOARD_ERRORS = ["SYNTAX", "OP_NOT_ALLOWED", "BASE_SCOPE"]

export function BoardsSection(props: TabProps & { history: WorkspaceHistory; region?: PricingRegion; matrixPeriod?: PeriodChannel }) {
  const { doc, state, readOnly, history, region, matrixPeriod } = props
  const { t, locale } = useTexT()
  const tables = state.tables
  const ccy = doc.contract_doc.contract_currency
  const minorUnits = doc.contract_doc.minor_units ?? currencyMinorUnits(ccy)
  const decimalMark = useMemo(() => decimalMarkOf(locale), [locale])
  const canEdit = !readOnly
  const titleId = useId()
  const bodyId = useId()
  // the header lane, said to a screen reader on the grid (S16 re-review 2)
  const laneNoteId = useId()
  const sectionRef = useRef<HTMLElement>(null)
  const addRef = useRef<HTMLSpanElement>(null)
  const focusAdd = () => addRef.current?.querySelector<HTMLElement>("button")?.focus()

  // ─── open / closed, #boards ─────────────────────────────────────────────
  const [open, setOpenState] = useState(() => readOpen(tables.boards.length === 0))
  const setOpen = useCallback((v: boolean) => {
    setOpenState(v)
    storeOpen(v)
  }, [])
  useEffect(() => {
    if (region !== "boards") return
    setOpen(true)
    requestAnimationFrame(() => sectionRef.current?.scrollIntoView({ block: "start" }))
  }, [region, setOpen])

  // ─── rows, columns, names ─────────────────────────────────────────────
  const [pending, setPending] = useState<BoardIdentity[]>([])
  const model = useMemo(() => boardModel(tables, pending), [tables, pending])
  const rows = model.rows
  const cols = model.periods
  const template = columnTemplate(cols.length - 1)
  const rowIndex = useMemo(() => new Map(rows.map((x, i) => [x.id, i])), [rows])
  const periodRows = useMemo(() => new Map(tables.periods.map((x) => [str(x.period_code), x])), [tables.periods])
  const names = useMemo(() => new Map(doc.room_types.map((r) => [r.name, r.room_type_name || r.name])), [doc.room_types])
  const roomName = useCallback((rt: string) => names.get(rt) ?? rt, [names])
  const contractRooms = useMemo(() => tables.rooms.map((r) => str(r.room_type)).filter(Boolean), [tables.rooms])
  const hlPeriod = useSyncExternalStore(matrixPeriod?.subscribe ?? noSubscribe, matrixPeriod?.get ?? noPeriod)
  const hlC = hlPeriod === null ? -1 : cols.indexOf(hlPeriod)

  const allRooms = t("rates.occ.ladder.all_rooms")
  const periodName = (code: string) => code || t("rates.rates.all_periods")
  const boardName = (code: string) => enumLabel(t, "board", code)
  const rowLabel = (row: Pick<BoardRow, "board" | "room_type">) => (row.room_type ? t("rates.brd.row.room", { board: boardName(row.board), room: roomName(row.room_type) }) : boardName(row.board))
  const amount = (v: string) => decText(v, minorUnits)
  /** A stored supplement as a cell shows it: 100.00 (per room), +20.00 / −20.00 (per adult), −5% (display only). */
  const ruleShort = (op: string, value: string) => {
    const neg = value.trim().startsWith("-")
    if (op === "ADJUST_PERCENT") return `${neg ? "" : "+"}${decText(value, 0)}%`
    if (op === "ADD") return `${neg ? "" : "+"}${amount(value)}`
    return amount(value)
  }
  /** The unit in words (§3.12: the reading line always names it). */
  const unitFull = (op: string, child: string, infantFree: boolean) =>
    op === "ADD" ? t(infantFree ? "rates.brd.unit_full.ADD_infants" : "rates.brd.unit_full.ADD", { child: decText(child || "50", 0) }) : t(`rates.brd.unit_full.${op === "ABSOLUTE" ? "ABSOLUTE" : "ADJUST_PERCENT"}`)
  const ruleWords = (r: Row) => {
    if (isSet(r.is_base)) return t("rates.brd.unit_full.base")
    const v = str(r.adult_amount)
    if (!v) return t("rates.brd.cell.no_value")
    const op = str(r.op)
    return `${ruleShort(op, v)} ${unitFull(op, str(r.child_percent), isSet(r.infant_free))}`
  }
  const sourceName = (r: Row) => `${rowLabel({ board: str(r.board), room_type: str(r.room_type) })} · ${periodName(str(r.period_code))}`
  const errorText = (code: string) => (BOARD_ERRORS.includes(code) ? t(`rates.brd.err.${code}`) : t(`rates.sh.err.${code}`))
  // the validation issues anchored on board cells (§3.15, S15)
  const issueAt = useCellIssues(props.anchored, props.issueText, props.issuesStale)

  // ─── the keyboard grid ─────────────────────────────────────────────────
  const isEditable = useCallback((r: number, c: number) => canEdit && c >= 0 && r >= 0 && r < rows.length, [canEdit, rows])
  const selection = useGridSelection({ rows: rows.length, cols: cols.length, isEditable })
  // sideways in step with the other grids of the Pricing section (§3.1)
  const syncScroll = useScrollSyncRef()
  const gridEl = useRef<HTMLDivElement | null>(null)
  // copy, paste and the fills are the matrix's: here they say so (S16 re-review)
  const matrixOnly = useMatrixOnlyBulk(gridEl, canEdit)
  const toast = useToast()
  // "Show in grid" (S14): the section opens, then the board cell of the rule is focused
  const { show, onShown } = props
  const [reveal, setReveal] = useState<string | null>(null)
  useEffect(() => {
    if (!show) return
    const target = show.target
    if (target.kind === "board") {
      onShown?.(show.n)
      setOpen(true)
      setReveal(boardCellId(target.board, target.room, target.period))
    } else if (target.kind === "region" && target.region === "boards") {
      // an issue about the boards as a whole (NO_BASE_BOARD, S15): the section, open
      onShown?.(show.n)
      setOpen(true)
      setReveal("")
    }
  }, [show, onShown, setOpen])
  useEffect(() => {
    if (reveal === null || !open) return
    setReveal(null)
    const el = reveal ? Array.from(gridEl.current?.querySelectorAll<HTMLElement>("[data-cellid]") ?? []).find((x) => x.dataset.cellid === reveal) : undefined
    if (el) revealElement(el)
    else sectionRef.current?.scrollIntoView({ block: "start" })
  }, [reveal, open])
  const cellAt = (r: number, c: number): BoardRef | null => {
    const row = rows[r]
    const period = cols[c]
    return row && period !== undefined ? { row: row.id, period } : null
  }
  const positionOf = (c: BoardRef): { r: number; c: number } | null => {
    const r = rowIndex.get(c.row)
    const ci = cols.indexOf(c.period)
    return r === undefined || ci < 0 ? null : { r, c: ci }
  }
  const rowOf = (c: BoardRef): BoardRow | undefined => rows[rowIndex.get(c.row) ?? -1]
  const cellName = (c: BoardRef) => {
    const row = rowOf(c)
    return `${row ? rowLabel(row) : c.row} · ${periodName(c.period)}`
  }

  const [editing, setEditing] = useState<Editing | null>(null)
  const editingRef = useRef<Editing | null>(null)
  editingRef.current = editing
  const editPos = editing ? positionOf(editing.cell) : null
  const closing = useRef(false)
  // error drafts outlive the grid (a section switch, a collapsed section): the editor keeps them
  const [drafts, setDrafts] = useKeptState<Record<string, Draft>>(KEPT.drafts("boards"), {})
  const [confirm, setConfirm] = useState<Confirming | null>(null)
  const [pop, setPop] = useState<{ row: string } | null>(null)
  const popAnchor = useRef<HTMLElement | null>(null)
  const [startEdit, setStartEdit] = useState<BoardRef | null>(null)
  const [focusNext, setFocusNext] = useState<BoardRef | "active" | null>(null)
  const [announce, setAnnounce] = useState("")
  const say = useCallback((text: string) => setAnnounce((prev) => (prev === text ? `${text}​` : text)), [])
  const undoToast = useUndoToast(history)

  const dropDrafts = (cells: BoardRef[]) =>
    setDrafts((d) => {
      if (!cells.some((c) => d[keyOf(c)])) return d
      const n = { ...d }
      for (const c of cells) delete n[keyOf(c)]
      return n
    })
  // at once (the closing editor had the focus: a key typed straight after Escape or Enter reaches the
  // cell, not the page); a frame later only if the focus was lost, and never from an edit that a key
  // typed at once began (taking it would commit that edit's first keys on blur)
  const focusAt = (r: number, c: number) =>
    focusCellNow(
      () => gridEl.current?.querySelector<HTMLElement>(`[data-cell="${r}:${c}"]`),
      () => editingRef.current !== null,
    )
  /** Rows written: the pending rows that got a rule are rows of the table now. */
  const settlePending = (boards: readonly Row[]) => setPending((p) => (p.some((id) => hasRows(boards, id)) ? p.filter((id) => !hasRows(boards, id)) : p))
  const toastDone = (message: string) => {
    undoToast.show(message)
    say(message)
  }

  /** One gesture (a typed entry, Ctrl/Cmd+Enter, Delete): all or nothing, one history entry; a
   * gesture that removes a board waits for the inline confirmation. */
  const commitItems = (cells: BoardRef[], text: string, label: string): { ok: true; asked?: boolean } | { ok: false; code: string; cell: BoardRef } => {
    const parsed = parseShorthand(text, "board", { minorUnits })
    const items: BoardEntryItem[] = []
    for (const cell of cells) {
      const row = rowOf(cell)
      const at = positionOf(cell)
      if (!row || !at || !isEditable(at.r, at.c)) return { ok: false, code: "CHANGED", cell }
      items.push({ id: row.identity, period: cell.period, parsed })
    }
    const now = history.current() ?? tables
    const plan = planBoardEntries(now, items)
    if ("error" in plan) return { ok: false, code: plan.error, cell: cells[plan.index] }
    dropDrafts(cells)
    if (plan.removes.length) {
      const count = plan.removes.reduce((n, b) => n + removeBoard(now, b).counts.rows, 0)
      setConfirm({ cells, text, label, boards: plan.removes, rows: count })
      return { ok: true, asked: true }
    }
    if (history.commit(label, now, plan.tables)) {
      settlePending(plan.tables.boards)
      if (cells.length > 1) toastDone(t("rates.ws.bulk.applied", { count: cells.length }))
    }
    return { ok: true }
  }

  const commitText = (cells: BoardRef[], text: string) =>
    commitItems(cells, text, cells.length === 1 ? t("rates.brd.h.rule", { cell: cellName(cells[0]) }) : t("rates.brd.h.rules", { count: cells.length }))

  /** "Remove": the gesture again, from the tables as they are now. */
  const confirmRemove = () => {
    const c = confirm
    setConfirm(null)
    if (!c) return
    const parsed = parseShorthand(c.text, "board", { minorUnits })
    const items: BoardEntryItem[] = []
    for (const cell of c.cells) {
      const row = rowOf(cell)
      if (row) items.push({ id: row.identity, period: cell.period, parsed })
    }
    const now = history.current() ?? tables
    const plan = planBoardEntries(now, items)
    if (!("error" in plan) && history.commit(c.label, now, plan.tables)) {
      settlePending(plan.tables.boards)
      toastDone(t("rates.brd.removed", { boards: plan.removes.map(boardName).join(", ") }))
    }
    setFocusNext("active")
  }
  const cancelRemove = () => {
    const c = confirm
    setConfirm(null)
    if (c) setFocusNext(c.cells[0])
  }

  const editTextOf = (c: BoardRef) => boardEditText(rowOf(c)?.cells[c.period], { decimalMark, minorUnits })

  const onEdit = (at: GridCell, req: GridEditRequest) => {
    if (!isEditable(at.r, at.c)) return
    const cell = cellAt(at.r, at.c)
    if (!cell) return
    closing.current = false
    setEditing({ cell, text: req.text ?? drafts[keyOf(cell)]?.text ?? editTextOf(cell), selectAll: req.text === undefined })
  }

  const openTerms = (row: BoardRow, anchor: HTMLElement) => {
    if (row.pending || !canEdit) return
    popAnchor.current = anchor
    setPop({ row: row.id })
  }

  const nextEditableRow = (r: number, c: number, dir: 1 | -1) => {
    for (let i = r + dir; i >= 0 && i < rows.length; i += dir) if (isEditable(i, c)) return i
    return r
  }

  const finish = (cell: BoardRef, move: "down" | "up" | "left" | "right" | null) => {
    closing.current = true
    setEditing(null)
    const at = positionOf(cell)
    if (!at) return
    if (move === "down" || move === "up") nav.focusCell(nextEditableRow(at.r, at.c, move === "down" ? 1 : -1), at.c)
    else if (move === "left" || move === "right") nav.focusCell(at.r, Math.max(0, Math.min(cols.length - 1, at.c + (move === "right" ? 1 : -1))))
    else focusAt(at.r, at.c)
  }

  const commitEditor = (ed: Editing, text: string, cells: BoardRef[], move: "down" | "up" | "left" | "right" | null): string | void => {
    const cell = cells[0]
    if (cells.length === 1 && !drafts[keyOf(cell)] && text === editTextOf(cell)) return finish(ed.cell, move)
    const res = commitText(cells, text)
    if (res.ok && res.asked) {
      // the confirmation takes the focus; Cancel gives it back to the cell
      closing.current = true
      setEditing(null)
      return
    }
    if (res.ok) return finish(ed.cell, move)
    const own = res.cell.row === ed.cell.row && res.cell.period === ed.cell.period
    return own ? errorText(res.code) : t("rates.ws.bulk_error", { cell: cellName(res.cell), error: errorText(res.code) })
  }

  const selectedRefs = (): BoardRef[] => {
    const cells = selection.selected.map((x) => cellAt(x.r, x.c)).filter((x): x is BoardRef => x !== null)
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
        const row = rowOf(cell)
        const anchor = e.currentTarget.closest<HTMLElement>('[role="gridcell"]')
        if (!row || row.pending || !anchor) return
        closing.current = true
        setEditing(null)
        // what is typed is committed first, as Enter commits it (or kept as the cell's error draft,
        // as a blur keeps it): the terms popover is about the row, not this entry (S16 re-review)
        if (drafts[keyOf(cell)] || text !== editTextOf(cell)) {
          const res = commitText([cell], text)
          if (res.ok && res.asked) return // the removal's confirmation takes the focus
          if (!res.ok) setDrafts((d) => ({ ...d, [keyOf(res.cell)]: { text, code: res.code } }))
        }
        openTerms(row, anchor)
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
      // undo / redo as in the matrix; Ctrl+R / Ctrl+D (the matrix's fills) must not reload or
      // bookmark the page while a boards cell has the focus
      e.preventDefault()
      if (shortcut === "undo" || shortcut === "redo") stepHistory(shortcut)
      else matrixOnly()
      return true
    }
    const cell = cellAt(at.r, at.c)
    if ((e.key === "Enter" && e.altKey) || (e.key === "F10" && e.shiftKey) || e.key === "ContextMenu") {
      e.preventDefault()
      const row = cell ? rowOf(cell) : undefined
      if (row) openTerms(row, e.currentTarget)
      return true
    }
    if ((e.key === "Delete" || e.key === "Backspace") && !e.ctrlKey && !e.metaKey && !e.altKey) {
      const cells = selectedRefs()
      if (!cells.length) return
      e.preventDefault()
      const label = cells.length === 1 ? t("rates.brd.h.clear", { cell: cellName(cells[0]) }) : t("rates.brd.h.clear_many", { count: cells.length })
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

  // one tab stop (§3.19): a row's terms (or discard) button is reached with ArrowLeft from its first cell
  const nav = useGridNavigation({ rows: rows.length, cols: cols.length, selection, onEdit: canEdit ? onEdit : undefined, onKey, onEdge: (edge, cell) => focusHeaderLane(gridEl.current, edge, cell) })
  const setGrid = useCallback(
    (el: HTMLDivElement | null) => {
      gridEl.current = el
      nav.gridRef(el)
    },
    [nav],
  )

  // a new row waits for its first value: its All periods cell is edited at once; a board added as
  // the base board, a confirmation answered, the popover's changes: the focus goes back to the grid
  const { dispatch } = selection
  useEffect(() => {
    if (!startEdit) return
    const at = positionOf(startEdit)
    if (!at) return
    setStartEdit(null)
    dispatch({ type: "moveTo", r: at.r, c: at.c, extend: false })
    closing.current = false
    setEditing({ cell: startEdit, text: "", selectAll: false })
    // the new row's position is known once it is rendered
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [startEdit, rows, dispatch])
  useEffect(() => {
    if (!focusNext) return
    setFocusNext(null)
    if (!rows.length) {
      focusAdd()
      return
    }
    const at = focusNext === "active" ? nav.active : positionOf(focusNext)
    if (at) nav.focusCell(at.r, at.c)
    // after the render that shows the change
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [focusNext, rows])

  // ─── what each cell shows ──────────────────────────────────────────────
  type View = { tone: CellTone; content: ReactNode; state: BoardCellStateKey; value?: string; tooltip?: string; error?: string; stack?: boolean }
  const unitLine = (text: string) => <span className="max-w-full truncate text-[10px] leading-tight opacity-80">{text}</span>

  const boardView = (row: BoardRow, period: string, cell: BoardCell): View => {
    const rooms = row.room_type ? roomName(row.room_type) : allRooms
    const applies = t("rates.brd.cell.applies", { rooms, period: periodName(period) })
    const own = cell.rule
    if (own) {
      const override = period !== ALL_PERIODS
      const mark = override ? "◆ " : ""
      const tone: CellTone = override ? "override" : "plain"
      if (isSet(own.is_base)) {
        return {
          tone,
          content: (
            <>
              <span className="font-semibold tracking-wide">{mark}BASE</span>
              {unitLine(t("rates.brd.unit.base"))}
            </>
          ),
          stack: true,
          state: "base",
          value: t("rates.brd.unit_full.base"),
          tooltip: `${applies} ${t("rates.brd.cell.base_tip")}`,
        }
      }
      const v = str(own.adult_amount)
      if (!v) return { tone: "missing", content: "—", state: "no_value", value: t("rates.brd.cell.no_value"), tooltip: `${applies} ${t("rates.brd.cell.no_value_tip", { board: boardName(row.board) })}` }
      const op = str(own.op)
      const short = ruleShort(op, v)
      return {
        tone,
        content: (
          <>
            <span>
              {mark}
              {short}
            </span>
            {unitLine(t(`rates.brd.unit.${op === "ABSOLUTE" || op === "ADD" ? op : "ADJUST_PERCENT"}`))}
          </>
        ),
        stack: true,
        state: override ? "period-override" : "rule",
        value: ruleWords(own),
        tooltip: override ? `${applies} ${t("rates.brd.cell.override_tip", { period })}` : applies,
      }
    }
    const src = cell.source
    if (src) {
      const text = isSet(src.is_base) ? "BASE" : str(src.adult_amount) ? ruleShort(str(src.op), str(src.adult_amount)) : "—"
      return { tone: "muted", content: `↳ ${text}`, state: "inherited", value: `${ruleWords(src)} (${sourceName(src)})`, tooltip: `${applies} ${t("rates.brd.cell.follows", { source: sourceName(src) })}` }
    }
    if (row.pending) return { tone: "muted", content: "—", state: "pending", tooltip: t("rates.brd.cell.pending_tip") }
    return { tone: "muted", content: "—", state: "empty", tooltip: t("rates.brd.cell.none_tip", { board: boardName(row.board), rooms, period: periodName(period) }) }
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
    const row = rows[r]
    const ref: BoardRef = { row: row.id, period }
    const editable = isEditable(r, c)
    let view = boardView(row, period, row.cells[period])
    const draft = drafts[keyOf(ref)]
    if (draft) view = draftView(draft)
    const stateText = t(`rates.brd.state.${view.state}`)
    const name = cellName(ref)
    const cellId = boardCellId(row.board, row.room_type, period)
    return {
      cellId,
      issue: issueAt(cellId),
      label: view.value ? t("rates.ws.cell.label", { cell: name, state: stateText, value: view.value }) : t("rates.ws.cell.label_bare", { cell: name, state: stateText }),
      tone: view.tone,
      content: view.content,
      tooltip: view.tooltip ?? (!editable ? roTip : undefined),
      readOnly: !editable,
      error: view.error,
      stack: view.stack,
      // the context menu opens the row's terms, as Shift+F10 and the ContextMenu key do
      onContextMenu:
        editable && !row.pending
          ? (e) => {
              e.preventDefault()
              openTerms(row, e.currentTarget)
            }
          : undefined,
    }
  }
  const cellViews = useMemo(
    () => rows.map((_, r) => cols.map((period, c) => cellView(r, period, c))),
    // everything cellView reads
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [rows, cols, drafts, canEdit, t, minorUnits, doc.status, roomName, issueAt],
  )
  const selectedKey = (r: number) => {
    let out = ""
    for (let c = 0; c < cols.length; c++) out += selection.isSelected(r, c) ? "1" : "0"
    return out
  }

  const readingFor = (cell: BoardRef) => (text: string) => {
    const row = rowOf(cell)
    if (!row) return { text: "", invalid: true }
    if (row.pending && !text.trim()) return { text: t("rates.brd.read.pending"), invalid: false }
    const now = history.current() ?? tables
    const reading = boardReadingOf(now, row.identity, cell.period, parseShorthand(text, "board", { minorUnits }))
    const name = cellName(cell)
    switch (reading.kind) {
      case "error":
        return { text: errorText(reading.code), invalid: true }
      case "unchanged":
        return { text: t("rates.sh.read.unchanged"), invalid: false }
      case "remove-board":
        return { text: t("rates.brd.read.remove_board", { board: boardName(row.board), count: reading.rows }), invalid: false }
      case "clear":
        return {
          text: reading.follows ? t("rates.brd.read.clear_follows", { cell: name, source: `${ruleWords(reading.follows)} (${sourceName(reading.follows)})` }) : t("rates.brd.read.clear_none", { cell: name, board: boardName(row.board) }),
          invalid: false,
        }
      case "base":
        return {
          text: reading.previous.length
            ? t("rates.brd.read.base_moves", { cell: name, board: boardName(row.board), previous: reading.previous.map(boardName).join(", ") })
            : t("rates.brd.read.base", { cell: name, board: boardName(row.board) }),
          invalid: false,
        }
      case "rule": {
        const text = t("rates.brd.read.rule", { cell: name, rule: ruleShort(reading.op, reading.value), unit: unitFull(reading.op, reading.child_percent, reading.infant_free) })
        return { text: reading.wasBase ? t("rates.brd.read.was_base", { reading: text, board: boardName(row.board) }) : text, invalid: false }
      }
    }
  }

  const editorFor = (ed: Editing) => (
    <CellEditor
      label={t("rates.brd.cell.input", { cell: cellName(ed.cell) })}
      initialText={ed.text}
      selectAll={ed.selectAll}
      readingFor={readingFor(ed.cell)}
      onKey={onEditorKey}
      onBlur={onEditorBlur}
    />
  )

  // ─── Add board, the summary, the row header ────────────────────────────
  const present = new Set([...tables.boards.map((r) => str(r.board)), ...pending.filter((p) => !p.room_type).map((p) => p.board)])
  const available = BOARDS.filter((b) => !present.has(b))
  const onAdd = (code: string) => {
    if (!code) return
    const now = history.current() ?? tables
    const res = addBoard(now, code)
    if ("exists" in res) return
    setOpen(true)
    if ("tables" in res) {
      if (history.commit(t("rates.brd.h.add", { board: boardName(code) }), now, res.tables)) {
        say(t("rates.brd.added_base", { board: boardName(code) }))
        setFocusNext({ row: `${code}|`, period: ALL_PERIODS })
      }
      return
    }
    setPending((p) => [...p, res.pending])
    setStartEdit({ row: rowIdOf(res.pending), period: ALL_PERIODS })
    say(t("rates.brd.added", { board: boardName(code) }))
  }
  const discardPending = (row: BoardRow) => {
    setPending((p) => p.filter((x) => rowIdOf(x) !== row.id))
    dropDrafts(cols.map((period) => ({ row: row.id, period })))
    requestAnimationFrame(focusAdd)
  }

  const summary = useMemo(() => boardSummary(tables), [tables])
  const chipText = (item: (typeof summary.items)[number]) => {
    const r = item.rule
    if (!r) return t("rates.brd.sum.scoped_only", { board: item.board })
    if (item.base) return t("rates.brd.sum.base", { board: item.board })
    const v = str(r.adult_amount)
    if (!v) return t("rates.brd.sum.no_value", { board: item.board })
    const op = str(r.op)
    return t(`rates.brd.sum.${op === "ABSOLUTE" || op === "ADD" ? op : "ADJUST_PERCENT"}`, { board: item.board, value: op === "ADJUST_PERCENT" ? ruleShort(op, v).replace(/%$/, "") : ruleShort(op, v) })
  }
  const hasBase = tables.boards.some((r) => isSet(r.is_base))

  const subLine = (row: BoardRow): string => {
    if (row.pending) return t("rates.brd.row.pending_sub")
    const own = row.cells[ALL_PERIODS]?.rule
    const label = own ? str(own.label) : ""
    if (!own) return t("rates.brd.row.periods_only")
    const words = isSet(own.is_base) ? t("rates.brd.row.base_sub") : str(own.adult_amount) ? unitFull(str(own.op), str(own.child_percent), isSet(own.infant_free)) : t("rates.brd.cell.no_value")
    return label ? `${label} · ${words}` : words
  }

  const popRow = pop ? rows[rowIndex.get(pop.row) ?? -1] : undefined
  const headerCell = "border-r border-b border-zinc-200 bg-white px-2 py-1 text-left"

  return (
    <section ref={sectionRef} id="boards" aria-labelledby={titleId} className="scroll-mt-44 space-y-2 border-t border-zinc-200 pt-4">
      <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
        <h2 id={titleId} className="text-base font-semibold text-zinc-900">
          <button
            type="button"
            aria-expanded={open}
            aria-controls={bodyId}
            onClick={() => setOpen(!open)}
            className="-ml-1 inline-flex items-center gap-1 rounded-md px-1 py-0.5 hover:bg-zinc-100 focus-visible:ring-2 focus-visible:ring-tex-500 focus-visible:outline-none"
          >
            {open ? <ChevronDown className="size-4" aria-hidden /> : <ChevronRight className="size-4" aria-hidden />}
            {t("rates.brd.title")}
          </button>
        </h2>
        {!open &&
          (summary.items.length ? (
            <ul aria-label={t("rates.brd.sum.label")} className="flex min-w-0 flex-wrap items-center gap-1.5">
              {summary.items.map((item) => (
                <li key={item.board} className={cn("rounded-full px-2 py-0.5 text-xs ring-1 ring-inset", item.base ? "bg-tex-50 text-tex-800 ring-tex-200" : "bg-zinc-50 text-zinc-700 ring-zinc-200")}>
                  {chipText(item)}
                </li>
              ))}
              {summary.scoped > 0 && <li className="text-xs text-zinc-500">{t("rates.brd.sum.scoped", { count: summary.scoped })}</li>}
            </ul>
          ) : (
            <p className="text-xs text-zinc-600">{t("rates.brd.sum.none")}</p>
          ))}
        {canEdit && (
          <AddMenu
            ref={addRef}
            label={t("rates.brd.add")}
            className="ml-auto inline-flex flex-wrap items-center gap-2"
            emptyText={t("rates.brd.all_added")}
            items={available.map((b) => ({ value: b, label: `${boardName(b)} (${b})` }))}
            onAdd={onAdd}
          />
        )}
      </div>

      <div id={bodyId}>
        {open && (
          <div className="space-y-1.5">
            {/* the header lane as this grid has it: a row's terms button, for an editor (S16 re-review 3) */}
            {canEdit && rows.length > 0 && (
              <p className="text-xs text-zinc-500">
                {t("rates.brd.hint")} <span id={laneNoteId}>{t("rates.kbd.lane_note_boards")}</span>
              </p>
            )}
            {tables.boards.length > 0 && !hasBase && <Notice tone="warning">{t("rates.boards.no_base")}</Notice>}
            {!rows.length && <Notice tone="info">{canEdit ? t("rates.brd.none") : t("rates.brd.none_ro")}</Notice>}
            {confirm && (
              <RemoveConfirm
                message={t("rates.brd.confirm.body", { boards: confirm.boards.map(boardName).join(", "), count: confirm.rows })}
                onConfirm={confirmRemove}
                onCancel={cancelRemove}
              />
            )}
            <span role="status" aria-live="polite" className="sr-only">
              {announce}
            </span>
            {rows.length > 0 && (
              <div ref={syncScroll} data-scroll-sync className="max-h-[70vh] overflow-auto rounded-lg border border-zinc-200 bg-white pb-10">
                <div
                  role="grid"
                  aria-label={t("rates.brd.caption")}
                  aria-describedby={canEdit ? laneNoteId : undefined}
                  aria-rowcount={rows.length + 1}
                  aria-colcount={cols.length + 1}
                  aria-readonly={readOnly || undefined}
                  aria-multiselectable
                  ref={setGrid}
                  onKeyDownCapture={(e) => void headerLaneKeyDown(e, gridEl.current, nav.focusCell, { rows: rows.length, cols: cols.length })}
                  className="w-max min-w-full text-sm"
                >
                  <div role="row" className="sticky top-0 z-[2] grid bg-white" style={{ gridTemplateColumns: template }}>
                    <div role="columnheader" className={`sticky left-0 z-[4] flex items-end ${headerCell} text-xs font-semibold text-zinc-600`}>
                      {t("rates.f.board")}
                    </div>
                    {cols.map((code, c) => {
                      const per = periodRows.get(code)
                      return (
                        <div
                          role="columnheader"
                          key={code || "all"}
                          data-matrix-period={c === hlC || undefined}
                          className={cn(headerCell, c === hlC && "shadow-[inset_0_-3px_0_var(--color-tex-400)]")}
                        >
                          <span className="block truncate text-xs font-semibold text-zinc-800">{code ? code : t("rates.rates.all_periods")}</span>
                          <span className="block truncate text-[11px] text-zinc-500">{code ? str(per?.period_name) || " " : t("rates.ws.default")}</span>
                        </div>
                      )
                    })}
                    <div aria-hidden className="border-b border-zinc-200" />
                  </div>

                  {rows.map((row, r) => (
                    <div role="row" key={row.id} data-board-row={row.id} className="grid" style={{ gridTemplateColumns: template }}>
                      <div
                        role="rowheader"
                        className={cn(
                          "sticky left-0 z-[1] flex min-w-0 items-center gap-1 border-r border-b border-zinc-100 bg-white py-1 pr-1",
                          row.depth ? "pl-7" : "pl-3",
                          row.depth === 0 && r > 0 && "border-t-2 border-t-zinc-200",
                        )}
                      >
                        <span className="flex min-w-0 flex-1 flex-col">
                          {/* the name wraps rather than being cut on phones (the row header is 9rem there) */}
                          <span className="flex min-w-0 flex-wrap items-center gap-x-1.5 gap-y-0.5">
                            {row.depth ? (
                              <span className="min-w-0 text-[13px] leading-tight break-words text-zinc-800">{t("rates.brd.row.room", { board: boardName(row.board), room: roomName(row.room_type) })}</span>
                            ) : (
                              <>
                                <span className="min-w-0 text-[13px] leading-tight font-medium break-words text-zinc-900">{boardName(row.board)}</span>
                                <span className="font-mono text-[11px] text-zinc-500">{row.board}</span>
                              </>
                            )}
                            {row.isBase && <Badge tone="brand">{t("rates.ws.room.base")}</Badge>}
                            {row.pending && <Badge tone="info">{t("rates.brd.row.new")}</Badge>}
                          </span>
                          <span className="truncate text-[11px] leading-tight text-zinc-500">{subLine(row)}</span>
                        </span>
                        {canEdit && !row.pending && (
                          <IconButton
                            size="sm"
                            className="size-7!"
                            label={t("rates.brd.row.terms", { row: rowLabel(row) })}
                            tabIndex={-1}
                            data-lane-rows={String(r)}
                            aria-haspopup="dialog"
                            aria-expanded={pop?.row === row.id}
                            icon={<SlidersHorizontal className="size-3.5" aria-hidden />}
                            onClick={(e) => openTerms(row, e.currentTarget)}
                          />
                        )}
                        {canEdit && row.pending && (
                          <IconButton
                            size="sm"
                            className="size-7!"
                            label={t("rates.brd.row.discard", { row: rowLabel(row) })}
                            tabIndex={-1}
                            data-lane-rows={String(r)}
                            icon={<X className="size-3.5" aria-hidden />}
                            onClick={() => discardPending(row)}
                          />
                        )}
                      </div>
                      <MatrixRowCells
                        r={r}
                        views={cellViews[r]}
                        nav={nav}
                        activeC={nav.active.r === r ? nav.active.c : -1}
                        selected={selectedKey(r)}
                        selState={nav.active.r === r ? selection.state : undefined}
                        tint={selection.multiple}
                        blockStart={row.depth === 0 && r > 0}
                        editC={editing && editPos && editPos.r === r ? editPos.c : -1}
                        editor={editing && editPos && editPos.r === r ? editorFor(editing) : undefined}
                        hlC={hlC}
                      />
                      <div aria-hidden className={row.depth === 0 && r > 0 ? "border-t-2 border-b border-t-zinc-200 border-b-zinc-100" : "border-b border-zinc-100"} />
                    </div>
                  ))}
                </div>
              </div>
            )}
          </div>
        )}
      </div>

      {pop && popRow && (
        <BoardTermsPopover
          key={popRow.id}
          anchorRef={popAnchor}
          onClose={() => setPop(null)}
          rowLabel={rowLabel(popRow)}
          row={popRow}
          terms={boardTermsOf(history.current() ?? tables, popRow.identity)}
          rooms={[{ value: "", label: allRooms }, ...contractRooms.map((rt) => ({ value: rt, label: roomName(rt) }))]}
          addRooms={
            popRow.depth === 0
              ? contractRooms.filter((rt) => !rows.some((x) => x.board === popRow.board && x.room_type === rt)).map((rt) => ({ value: rt, label: roomName(rt) }))
              : []
          }
          removeCount={popRow.depth === 0 ? removeBoard(tables, popRow.board).counts.rows : removeBoardRow(tables, popRow.identity).counts.rows}
          periodName={periodName}
          onApply={(v) => {
            const now = history.current() ?? tables
            let next = setBoardTerms(now, popRow.identity, { child_percent: v.child_percent, infant_free: v.infant_free ? 1 : 0, label: v.label })
            if (v.room !== popRow.room_type) {
              const moved = moveBoardRows(next, popRow.identity, v.room)
              if ("error" in moved) return t("rates.brd.pop.rooms_taken", { board: boardName(popRow.board), room: v.room ? roomName(v.room) : allRooms })
              next = moved.tables
            }
            history.commit(t("rates.brd.h.terms", { row: rowLabel(popRow) }), now, next)
            setPop(null)
            // the popover gives the focus back to its trigger; a row moved to other rooms has a new one
            if (v.room !== popRow.room_type) setFocusNext({ row: rowIdOf({ board: popRow.board, room_type: v.room }), period: ALL_PERIODS })
          }}
          onAddRoom={(room) => {
            const id = { board: popRow.board, room_type: room }
            setPop(null)
            setPending((p) => [...p, id])
            setStartEdit({ row: rowIdOf(id), period: ALL_PERIODS })
            say(t("rates.brd.added_room", { row: rowLabel(id) }))
          }}
          onRemove={() => {
            const now = history.current() ?? tables
            const next = popRow.depth === 0 ? removeBoard(now, popRow.board).tables : removeBoardRow(now, popRow.identity).tables
            const label = popRow.depth === 0 ? t("rates.brd.h.remove", { board: boardName(popRow.board) }) : t("rates.brd.h.remove_row", { row: rowLabel(popRow) })
            setPop(null)
            if (history.commit(label, now, next)) toastDone(t("rates.brd.removed", { boards: rowLabel(popRow) }))
            setFocusNext("active")
          }}
        />
      )}
      <UndoToastView toast={undoToast.toast} onUndo={onToastUndo} onDismiss={undoToast.dismiss} onHold={undoToast.hold} onFocusBack={onToastFocusBack} />
    </section>
  )
}

/** "Remove {board}?" under the section header: the gesture that clears a board's own All periods
 * cell waits here (the focus is on Remove; Escape or Cancel keeps the board). */
function RemoveConfirm({ message, onConfirm, onCancel }: { message: string; onConfirm: () => void; onCancel: () => void }) {
  const { t } = useTexT()
  const ref = useRef<HTMLButtonElement>(null)
  useEffect(() => {
    ref.current?.focus()
  }, [])
  return (
    <div
      role="group"
      aria-label={t("rates.brd.confirm.title")}
      className="flex flex-wrap items-center gap-2 rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-sm text-amber-900"
      onKeyDown={(e) => {
        if (e.key !== "Escape") return
        e.preventDefault()
        e.stopPropagation()
        onCancel()
      }}
    >
      <span className="min-w-0 flex-1">{message}</span>
      <Button ref={ref} size="sm" variant="danger" onClick={onConfirm}>
        {t("rates.brd.confirm.remove")}
      </Button>
      <Button variant="secondary" size="sm" onClick={onCancel}>
        {t("core.action.cancel")}
      </Button>
    </div>
  )
}

interface TermsValues {
  child_percent: string
  infant_free: boolean
  label: string
  room: string
}

/** The row popover (§3.12): child %, infants free, the label and the rooms of one grid row's rules
 * (all its periods); for a board's row also "Add a rule for one room" and Remove board. Non-modal;
 * the focus returns to the trigger on close. */
function BoardTermsPopover(p: {
  anchorRef: RefObject<HTMLElement | null>
  onClose: () => void
  rowLabel: string
  row: BoardRow
  terms: BoardTerms
  rooms: { value: string; label: string }[]
  addRooms: { value: string; label: string }[]
  removeCount: number
  periodName: (code: string) => string
  /** a refusal comes back as its message */
  onApply: (v: TermsValues) => string | void
  onAddRoom: (room: string) => void
  onRemove: () => void
}) {
  const { t } = useTexT()
  const addRoomHelpId = useId()
  const [child, setChild] = useState(() => {
    const n = normaliseDecimal(p.terms.child_percent)
    return n.ok ? n.value : p.terms.child_percent
  })
  const [infant, setInfant] = useState(p.terms.infant_free)
  const [label, setLabel] = useState(p.terms.label)
  const [room, setRoom] = useState(p.row.room_type)
  const [error, setError] = useState<string>()
  const [removing, setRemoving] = useState(false)
  const checked = normaliseDecimal(child)
  const childError = child.trim() === "" ? t("rates.brd.pop.child_required") : !checked.ok ? t(`rates.sh.err.${checked.code}`) : undefined
  const ready = !childError
  const board = p.row.depth === 0

  const apply = () => {
    if (!ready || !checked.ok) return
    const refused = p.onApply({ child_percent: checked.value, infant_free: infant, label: label.trim(), room })
    if (refused) setError(refused)
  }

  return (
    <Popover open onClose={p.onClose} anchorRef={p.anchorRef} label={t("rates.brd.pop.title", { row: p.rowLabel })} width="md">
      <form
        className="space-y-3"
        onSubmit={(e) => {
          e.preventDefault()
          apply()
        }}
      >
        <Field label={t("rates.brd.pop.child")} required error={childError} hint={t("rates.brd.pop.child_help")}>
          <DecimalInput value={child} onValueChange={setChild} decimals={9} suffix="%" data-autofocus />
        </Field>
        <Checkbox label={t("rates.f.infant_free")} checked={infant} onChange={(e) => setInfant(e.target.checked)} />
        <Field label={t("rates.f.board_label")}>
          <Input value={label} onChange={(e) => setLabel(e.target.value)} maxLength={140} />
        </Field>
        <Field label={t("rates.brd.pop.rooms")} hint={t("rates.brd.pop.rooms_help")} error={error}>
          <Select
            value={room}
            options={p.rooms}
            onChange={(e) => {
              setRoom(e.target.value)
              setError(undefined)
            }}
          />
        </Field>
        <p className="text-xs text-zinc-500">
          {t("rates.brd.pop.applies", { count: p.terms.count, periods: p.terms.periods.map(p.periodName).join(", ") })}
          {p.terms.mixed ? ` ${t("rates.brd.pop.mixed")}` : ""}
        </p>
        {board && p.addRooms.length > 0 && (
          <div className="space-y-1">
            <AddMenu label={t("rates.brd.pop.add_room")} items={p.addRooms} onAdd={p.onAddRoom} describedBy={addRoomHelpId} />
            <p id={addRoomHelpId} className="text-xs text-zinc-500">
              {t("rates.brd.pop.add_room_help", { board: p.rowLabel })}
            </p>
          </div>
        )}
        {removing ? (
          <div role="group" aria-label={t("rates.brd.confirm.title")} className="flex flex-wrap items-center gap-2 rounded-md bg-amber-50 px-2.5 py-1.5 text-sm text-amber-900">
            <span className="min-w-0 flex-1">
              {board ? t("rates.brd.confirm.body", { boards: p.rowLabel, count: p.removeCount }) : t("rates.brd.pop.remove_row_body", { row: p.rowLabel, count: p.removeCount })}
            </span>
            <Button size="sm" variant="danger" onClick={p.onRemove} autoFocus>
              {t("rates.brd.confirm.remove")}
            </Button>
            <Button size="sm" variant="secondary" onClick={() => setRemoving(false)}>
              {t("core.action.cancel")}
            </Button>
          </div>
        ) : (
          <div className="flex flex-wrap items-center justify-end gap-2 pt-1">
            <Button variant="ghost" size="sm" className="mr-auto text-rose-700! hover:bg-rose-50!" onClick={() => setRemoving(true)}>
              {board ? t("rates.brd.pop.remove_board") : t("rates.brd.pop.remove_row")}
            </Button>
            <Button variant="secondary" size="sm" onClick={p.onClose}>
              {t("core.action.cancel")}
            </Button>
            <Button size="sm" type="submit" disabled={!ready}>
              {t("core.action.apply")}
            </Button>
          </div>
        )}
      </form>
    </Popover>
  )
}
