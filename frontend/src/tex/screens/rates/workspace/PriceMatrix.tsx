// The room price matrix of the Pricing Workspace (PRICING_WORKSPACE_UX.md §3.3–§3.5, §3.9, §3.11,
// §3.19; slice S9): a keyboard grid (role="grid" "Room prices by period") of the contract rooms ×
// All periods and the period columns, edited inline with the shorthand (§3.4). The row decides how
// a relative entry is stored (D11): on the base room the server adjusts the entered price once and
// it is stored as ABSOLUTE (O4, apply_op_values); on every other room it writes a formula from the
// room's default base. Resolved rows show the server's prices for what is on screen (the live
// preview, S8); the client computes no amount. Every change is one workspace history entry.
import { useCallback, useMemo, useRef, useState, type KeyboardEvent, type MouseEvent, type ReactNode } from "react"
import { AlertTriangle, Loader2, Pin } from "lucide-react"
import { tex, TexApiError } from "../../../lib/api"
import { minorUnits as currencyMinorUnits } from "../../../lib/format"
import { useTexT } from "../../../i18n"
import { Badge, Checkbox, Money, Notice, Select, Tooltip, useGridNavigation, useGridSelection, type GridCell, type GridEditRequest } from "../../../ui"
import type { TabProps } from "../contracts/tabs/shared"
import { displayText, parseShorthand, type ShOp, type ShResult } from "../lib/shorthand"
import type { Tables } from "../lib/tables"
import type { ApplyOpResult, Row } from "../lib/types"
import { decText } from "../lib/util"
import { CellEditor, MatrixRowCells, type CellTone, type CellView } from "./MatrixCell"
import { ALL_PERIODS, isRelativeOp, matrixModel, type MatrixRoom, type NeedsServer, type RoomCell } from "./model.ts"
import {
  addRoom,
  applyPopover,
  cellEditText,
  cellPosition,
  clearCells,
  columnTemplate,
  decimalMarkOf,
  finishEntry,
  gestureCells,
  gridRows,
  planEntry,
  readingOf,
  type CellRef,
  type EntryError,
  type GridRow,
  type PopoverRule,
  type Reading,
} from "./matrixView.ts"
import { AddPeriodHeader, PeriodHeader, PeriodStrip } from "./PeriodHeader"
import { RoomRowHeader } from "./RoomRowHeader"
import { RuleEditorPopover } from "./RuleEditorPopover"
import { int, str } from "./rows.ts"
import type { WorkspaceHistory } from "./useWorkspaceHistory"

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

const keyOf = (c: CellRef) => `${c.room}\u0000${c.period}`
/** The DOM id of an entry cell (data-cellid), stable while rows come and go. */
const cellIdOf = (c: CellRef) => `${c.room}|${c.period}`

export function PriceMatrix({ doc, state, readOnly, preview, history }: TabProps & { history: WorkspaceHistory }) {
  const { t, locale } = useTexT()
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

  // ─── the server's resolved prices (live preview) ─────────────────────
  const matrix = preview?.matrix
  const resolvedRooms = useMemo(() => new Map((matrix?.rooms ?? []).map((r) => [r.room_type, r])), [matrix])
  const stale = Boolean(preview && (preview.stale || preview.forKey !== preview.key))
  const includedAdults = (rt: string): number => {
    const fromServer = resolvedRooms.get(rt)?.capacity?.included_adults
    if (fromServer) return fromServer
    const row = tables.rooms.find((r) => str(r.room_type) === rt)
    return int(row?.included_adults) || doc.room_types.find((r) => r.name === rt)?.base_occupancy || 0
  }

  // ─── the keyboard grid ──────────────────────────────────────────────
  const isEditable = useCallback((r: number, c: number) => canEdit && c >= 0 && Boolean(rows[r]?.editable), [canEdit, rows])
  const selection = useGridSelection({ rows: rows.length, cols: cols.length, isEditable })
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
  const [drafts, setDrafts] = useState<Record<string, Draft>>({})
  // the cells of an entry waiting for the server's adjustment: the base-room price sent, or null
  const [pending, setPending] = useState<Record<string, string | null>>({})
  const [pop, setPop] = useState<{ cell: CellRef; initial: PopoverRule } | null>(null)
  const popAnchor = useRef<HTMLElement | null>(null)
  const [freshPeriod, setFreshPeriod] = useState<string | null>(null)
  const freshDone = useCallback(() => setFreshPeriod(null), [])
  const [announce, setAnnounce] = useState("")

  const historyApply = history.apply
  const edit = useCallback((label: string, fn: (tb: Tables) => Tables) => historyApply(label, fn), [historyApply])
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
   * apply_op_values call for all of them; the whole gesture is then one history entry. Every cell
   * of the gesture is pending until the answer, and the answer completes nothing when one of them
   * was changed meanwhile (`sentFrom`, CHANGED). */
  const adjust = async (cells: CellRef[], parsed: ShResult, sent: NeedsServer[], label: string, text: string, sentFrom: Tables) => {
    const waiting = gestureCells(cells, sent)
    const keys = waiting.map((w) => keyOf(w.cell))
    setPending((p) => {
      const n = { ...p }
      waiting.forEach((w, i) => (n[keys[i]] = w.current))
      return n
    })
    const first = { room: sent[0].room, period: sent[0].targetPeriod }
    const gen = history.generation()
    try {
      const answers = await tex<ApplyOpResult[]>("contracts", "apply_op_values", { version: doc.name, values: sent.map((s) => s.current), op: sent[0].op, value: sent[0].value }, { post: true })
      // the version was reloaded or discarded meanwhile: the answer is for a draft that is gone
      if (history.generation() !== gen) return
      let failed: { error: EntryError; cell: CellRef } | null = null
      history.apply(label, (tb) => {
        const done = finishEntry(tb, cells, parsed, sent, answers, sentFrom)
        if ("error" in done) {
          failed = done
          return tb
        }
        return done.tables
      })
      const f = failed as { error: EntryError; cell: CellRef } | null
      if (f) setDrafts((d) => ({ ...d, [keyOf(f.cell)]: { text, code: f.error } }))
      else setAnnounce(t("rates.ws.adjusted", { count: sent.length }))
    } catch (e) {
      setDrafts((d) => ({ ...d, [keyOf(first)]: { text, message: e instanceof TexApiError || e instanceof Error ? e.message : String(e) } }))
    } finally {
      setPending((p) => {
        const n = { ...p }
        for (const k of keys) delete n[k]
        return n
      })
    }
  }

  /** Commits `text` into `cells` as one gesture: stored at once, or (base-room relative entries)
   * after the server's adjustment. Refused as a whole when one cell cannot take it. */
  const commitText = (cells: CellRef[], text: string): { ok: true } | { ok: false; code: EntryError; cell: CellRef } => {
    // a cell still waiting for the server takes no other entry; a cell whose row or column is gone
    // (or no longer editable) takes none either
    const busy = cells.find((x) => pending[keyOf(x)] !== undefined)
    if (busy) return { ok: false, code: "PENDING", cell: busy }
    const gone = cells.find((x) => {
      const at = cellPosition(rows, cols, x)
      return !at || !isEditable(at.r, at.c)
    })
    if (gone) return { ok: false, code: "CHANGED", cell: gone }
    const parsed = parseShorthand(text, "room", { minorUnits })
    const now = history.current() ?? tables
    const plan = planEntry(now, cells, parsed)
    if ("error" in plan) return { ok: false, code: plan.error, cell: plan.cell }
    const label = cells.length === 1 ? t("rates.ws.h.price", { cell: cellName(cells[0]) }) : t("rates.ws.h.prices", { count: cells.length })
    dropDrafts(cells)
    if (plan.server.length) void adjust(cells, parsed, plan.server, label, text, now)
    else history.commit(label, now, plan.tables)
    return { ok: true }
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
    if (e.key === "Escape") {
      e.preventDefault()
      e.stopPropagation()
      dropDrafts([cell])
      finish(cell, null)
      return
    }
    if (e.key === "Enter" && e.altKey) {
      e.preventDefault()
      const anchor = e.currentTarget.closest<HTMLElement>('[role="gridcell"]')
      closing.current = true
      setEditing(null)
      if (anchor) openPopover(cell, anchor, parseShorthand(text, "room", { minorUnits }))
      return
    }
    if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) {
      // Ctrl/Cmd+Enter: every selected editable cell, each by its row's rule, as one entry
      e.preventDefault()
      const cells = selectedRefs()
      if (!cells.some((x) => x.room === cell.room && x.period === cell.period)) cells.push(cell)
      return commitEditor(ed, text, cells, null)
    }
    if (e.key === "Enter") {
      e.preventDefault()
      return commitEditor(ed, text, [cell], e.shiftKey ? "up" : "down")
    }
    if (e.key === "Tab") {
      e.preventDefault()
      return commitEditor(ed, text, [cell], e.shiftKey ? "left" : "right")
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

  const onKey = (e: KeyboardEvent<HTMLElement>, at: GridCell): boolean | void => {
    if (!canEdit) return
    const cell = cellAt(at.r, at.c)
    if ((e.key === "Enter" && e.altKey) || (e.key === "F10" && e.shiftKey) || e.key === "ContextMenu") {
      e.preventDefault()
      if (cell && isEditable(at.r, at.c)) openPopover(cell, e.currentTarget)
      return true
    }
    if ((e.key === "Delete" || e.key === "Backspace") && !e.ctrlKey && !e.metaKey && !e.altKey) {
      const cells = selectedRefs().filter((x) => pending[keyOf(x)] === undefined)
      if (!cells.length) return
      e.preventDefault()
      dropDrafts(cells)
      edit(cells.length === 1 ? t("rates.ws.h.clear", { cell: cellName(cells[0]) }) : t("rates.ws.h.clear_many", { count: cells.length }), (tb) => clearCells(tb, cells))
      return true
    }
    if (e.key === "Escape" && cell && drafts[keyOf(cell)] && !selection.multiple) {
      e.preventDefault()
      dropDrafts([cell])
      return true
    }
  }

  const nav = useGridNavigation({ rows: rows.length, cols: cols.length, selection, onEdit: canEdit ? onEdit : undefined, onKey })
  const setGrid = useCallback(
    (el: HTMLDivElement | null) => {
      gridEl.current = el
      nav.gridRef(el)
    },
    [nav],
  )

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

  type View = { tone: CellTone; content: ReactNode; state: string; value?: string; tooltip?: string; error?: string }

  const entryView = (cell: CellRef, mc: RoomCell | undefined): View => {
    const rule = mc?.rule
    const def = mc?.defaultRule
    switch (mc?.state) {
      case "manual":
        return { tone: "plain", content: shortText(rule as Row), state: "manual", value: amount(rule?.value) }
      case "formula-default":
        return { tone: "plain", content: <span className="text-slate-700">{shortText(rule as Row)}</span>, state: "formula-default", value: ruleText(rule as Row) }
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
              <Pin className="mr-1 inline size-3 -translate-y-px text-amber-700" aria-hidden />= {amount(rule?.value)}
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
    const stateText = resolved && stale ? t("rates.ws.cell.stale_state", { state }) : state
    return {
      cellId: resolved ? undefined : cellIdOf(cell),
      label: view.value ? t("rates.ws.cell.label", { cell: cellName(cell), state: stateText, value: view.value }) : t("rates.ws.cell.label_bare", { cell: cellName(cell), state: stateText }),
      tone: view.tone,
      content: view.content,
      tooltip: view.tooltip ?? (!editable ? (resolved ? t("rates.ws.cell.ro_resolved") : roTip) : undefined),
      readOnly: !editable,
      stale: resolved && stale,
      error: view.error,
      trigger: editable && waiting === undefined ? { label: t("rates.rates.edit_cell", { cell: cellName(cell) }), onOpen: (el) => openPopover(cell, el) } : undefined,
      onContextMenu: editable
        ? (e: MouseEvent<HTMLElement>) => {
            e.preventDefault()
            openPopover(cell, e.currentTarget)
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
    [rows, cols, model, tables, resolvedRooms, matrix, stale, drafts, pending, canEdit, t, decimalMark, minorUnits, doc.status, ccy, names],
  )
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
    <section aria-labelledby="pm-title" className="space-y-2">
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
        <span role="status" aria-live="polite" className="inline-flex min-h-5 items-center gap-1 text-xs text-zinc-500">
          {preview && (preview.loading || stale) && (
            <>
              <Loader2 className="size-3.5 animate-spin" aria-hidden />
              {t("rates.ws.updating")}
            </>
          )}
          <span className="sr-only">{announce}</span>
        </span>
        <span className="ml-auto">
          <Checkbox label={t("rates.ws.show_resolved")} checked={showResolved} onChange={(e) => setShowResolved(e.target.checked)} />
        </span>
      </div>
      {canEdit && <p className="text-xs text-zinc-500">{t("rates.ws.matrix_hint")}</p>}
      {preview?.buildError && (
        <Notice tone="warning" title={t("rates.ws.build_error")}>
          {preview.buildError}
        </Notice>
      )}
      {preview?.error && <Notice tone="danger">{preview.error.message}</Notice>}
      {orphans > 0 && <Notice tone="warning">{t("rates.ws.orphans", { count: orphans })}</Notice>}
      {model.rooms.length === 0 && <Notice tone="info">{canEdit ? t("rates.ws.room.none") : t("rates.rooms.empty")}</Notice>}

      <PeriodStrip tables={tables} stayFrom={stay?.stay_from} stayTo={stay?.stay_to} />
      <div className="max-h-[70vh] overflow-auto rounded-lg border border-zinc-200 pb-12">
        <div
          role="grid"
          aria-label={t("rates.rates.caption")}
          aria-rowcount={rows.length + 1}
          aria-colcount={cols.length + 2}
          aria-readonly={readOnly || undefined}
          aria-multiselectable={canEdit || undefined}
          ref={setGrid}
          className="w-max min-w-full text-sm"
        >
          <div role="row" className="sticky top-0 z-[2] grid bg-white" style={{ gridTemplateColumns: template }}>
            <div role="columnheader" className="sticky left-0 z-[4] flex items-end gap-1.5 border-r border-b border-zinc-200 bg-white px-3 py-1.5 text-xs font-semibold text-zinc-600">
              {t("rates.f.room_type")}
              {stale && <Loader2 className="size-3 animate-spin text-zinc-400" aria-hidden />}
            </div>
            <div role="columnheader" className="flex flex-col justify-end border-r border-b border-zinc-200 bg-white px-2 py-1.5 text-left">
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
              />
            ))}
            <AddPeriodHeader readOnly={readOnly} edit={edit} onAdded={setFreshPeriod} />
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
          <Select
            aria-label={t("rates.ws.room.add")}
            value=""
            className="h-8! w-72! text-xs!"
            placeholder={available.length ? t("rates.ws.room.add_placeholder") : t("rates.ws.room.all_added")}
            disabled={!available.length}
            options={available.map((r) => ({ value: r.name, label: r.room_type_name || r.name }))}
            onChange={(e) => {
              const rt = e.target.value
              if (rt) edit(t("rates.ws.h.add_room", { room: roomName(rt) }), (tb) => addRoom(tb, rt))
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
    </section>
  )
}
