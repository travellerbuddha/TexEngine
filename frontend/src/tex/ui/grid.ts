// Keyboard grid hooks (PRICING_WORKSPACE_UX.md §3.10, §3.19): a roving tabindex with the AriGrid
// key map, and an optional multi-range selection backed by the pure reducer in grid-model.ts.
//
//   const selection = useGridSelection({ rows, cols, isEditable })
//   const nav = useGridNavigation({ rows, cols, selection, onEdit, onKey })
//   <table role="grid" aria-multiselectable ref={nav.gridRef}> … <td role="gridcell" {...nav.cellProps(r, c)}>
//
// Only the active cell has tabIndex 0, so the grid is one tab stop. Focus moves in
// requestAnimationFrame to the active cell's element (data-cell="r:c") inside `gridRef`.
import {
  useCallback,
  useEffect,
  useMemo,
  useReducer,
  useRef,
  useState,
  type FocusEvent,
  type KeyboardEvent,
  type MouseEvent,
} from "react"
import {
  editableCells,
  gridSelectionInit,
  gridSelectionReducer,
  isCellSelected,
  isSingleCell,
  selectedCells,
  type GridAction,
  type GridCell,
  type GridEditable,
  type GridSelection,
} from "./grid-model"
import { shortcutLetter } from "./keys"

export interface GridSelectionOptions {
  rows: number
  cols: number
  /** Cells that accept edits; header selection, Ctrl/Cmd+A and `selected` use only these. */
  isEditable?: GridEditable
}

export interface GridSelectionApi {
  state: GridSelection
  /** Dispatch a reducer action (the grid's current bounds are applied first). */
  dispatch: (action: GridAction) => void
  /** Selected and editable (drives aria-selected and the selection tint). */
  isSelected: (r: number, c: number) => boolean
  /** The selected editable cells, unique and in reading order. */
  selected: GridCell[]
  /** More than the active cell is selected. */
  multiple: boolean
  click: (r: number, c: number, mods?: { shift?: boolean; meta?: boolean }) => void
  selectRow: (r: number, opts?: { add?: boolean }) => void
  selectCol: (c: number, opts?: { add?: boolean }) => void
  selectAll: () => void
  clear: () => void
}

/** Multi-range selection over a rows × cols grid (§3.10 gestures). */
export function useGridSelection({ rows, cols, isEditable }: GridSelectionOptions): GridSelectionApi {
  const [raw, send] = useReducer(gridSelectionReducer, undefined, () => gridSelectionInit(rows, cols))
  // the grid can change size between renders (a room or period added or removed): clamp at once
  // for this render and persist it after
  const state = raw.rows === rows && raw.cols === cols ? raw : gridSelectionReducer(raw, { type: "clamp", rows, cols })
  useEffect(() => {
    if (raw.rows !== rows || raw.cols !== cols) send({ type: "clamp", rows, cols })
  }, [raw.rows, raw.cols, rows, cols])

  const latest = useRef({ rows, cols, isEditable })
  latest.current = { rows, cols, isEditable }
  const dispatch = useCallback((action: GridAction) => {
    const { rows: r, cols: c } = latest.current
    send({ type: "clamp", rows: r, cols: c })
    send(action)
  }, [])

  const selected = useMemo(() => selectedCells(state, isEditable), [state, isEditable])
  const isSelected = useCallback(
    (r: number, c: number) => isCellSelected(state, r, c) && (!isEditable || isEditable(r, c)),
    [state, isEditable],
  )
  const click = useCallback(
    (r: number, c: number, mods: { shift?: boolean; meta?: boolean } = {}) => dispatch({ type: "click", r, c, ...mods }),
    [dispatch],
  )
  const selectRow = useCallback(
    (r: number, opts: { add?: boolean } = {}) => dispatch({ type: "selectRow", r, isEditable: latest.current.isEditable, add: opts.add }),
    [dispatch],
  )
  const selectCol = useCallback(
    (c: number, opts: { add?: boolean } = {}) => dispatch({ type: "selectCol", c, isEditable: latest.current.isEditable, add: opts.add }),
    [dispatch],
  )
  const selectAll = useCallback(() => {
    const { rows: r, cols: c, isEditable: ed } = latest.current
    dispatch({ type: "selectAll", cells: editableCells(r, c, ed) })
  }, [dispatch])
  const clear = useCallback(() => dispatch({ type: "clear" }), [dispatch])

  return { state, dispatch, isSelected, selected, multiple: !isSingleCell(state), click, selectRow, selectCol, selectAll, clear }
}

/** What an edit request carries: `text` = the typed character that replaces the content;
 * absent = edit the current text with all of it selected (Enter, F2, double-click). */
export interface GridEditRequest {
  text?: string
}

export interface GridNavigationOptions {
  rows: number
  cols: number
  /** Enter / F2 / double-click / typing a printable character. Omit for a read-only grid. */
  onEdit?: (cell: GridCell, request: GridEditRequest) => void
  /** Runs first for every key on a cell; return true (or preventDefault) to stop the default map. */
  onKey?: (e: KeyboardEvent<HTMLElement>, cell: GridCell) => boolean | void
  /** Shift+Arrow / Shift+Click extend, Ctrl/Cmd+Click adds, Ctrl/Cmd+A selects all, Escape clears. */
  selection?: GridSelectionApi
  /** Rows moved by PageUp / PageDown (default 10). */
  pageSize?: number
}

export interface GridCellProps {
  "data-cell": string
  tabIndex: number
  "aria-selected"?: boolean
  onKeyDown: (e: KeyboardEvent<HTMLElement>) => void
  onFocus: (e: FocusEvent<HTMLElement>) => void
  onMouseDown?: (e: MouseEvent<HTMLElement>) => void
  onDoubleClick?: (e: MouseEvent<HTMLElement>) => void
}

export interface GridNavigationApi {
  active: GridCell
  /** Ref for the grid element; cells are looked up inside it. */
  gridRef: (el: HTMLElement | null) => void
  /** Props for the cell at (r, c): data-cell, the roving tabIndex and the handlers. */
  cellProps: (r: number, c: number) => GridCellProps
  /** Make (r, c) the active cell (collapsing any selection) and focus it. */
  focusCell: (r: number, c: number) => void
}

const CONTROLS = "input,textarea,select,button,a[href],[contenteditable]"

function clampTo(v: number, n: number): number {
  return v < 0 ? 0 : v > n - 1 ? n - 1 : v
}

/** A key that types a character (not Space): starts edit mode with it (§3.4.1). */
function isPrintable(e: KeyboardEvent<HTMLElement>): boolean {
  if (e.key.length !== 1 || e.key === " " || e.nativeEvent.isComposing) return false
  if (e.metaKey) return false
  // AltGr reports Ctrl+Alt on Windows and types characters such as "@" or "€"
  return !(e.ctrlKey || e.altKey) || e.getModifierState("AltGraph")
}

/** Roving tabindex + keyboard map for a rows × cols grid (the AriGrid pattern). */
export function useGridNavigation({ rows, cols, onEdit, onKey, selection, pageSize = 10 }: GridNavigationOptions): GridNavigationApi {
  const [own, setOwn] = useState<GridCell>({ r: 0, c: 0 })
  const root = useRef<HTMLElement | null>(null)
  const gridRef = useCallback((el: HTMLElement | null) => {
    root.current = el
  }, [])
  const raw = selection ? selection.state.active : own
  const active = { r: clampTo(raw.r, rows), c: clampTo(raw.c, cols) }
  const activeRef = useRef(active)
  activeRef.current = active

  // Focus the active cell of the latest render, not the target of the key that asked for it:
  // with fast key repeat a frame can come after the next key, and focusing that key's stale target
  // would collapse the selection (the cell's onFocus).
  const focusActive = useCallback(() => {
    requestAnimationFrame(() => {
      const { r, c } = activeRef.current
      root.current?.querySelector<HTMLElement>(`[data-cell="${r}:${c}"]`)?.focus()
    })
  }, [])

  const moveTo = (target: GridCell, extend: boolean) => {
    const t = { r: clampTo(target.r, rows), c: clampTo(target.c, cols) }
    if (selection) selection.dispatch({ type: "moveTo", r: t.r, c: t.c, extend })
    else setOwn(t)
    focusActive()
  }

  const focusCell = (r: number, c: number) => moveTo({ r, c }, false)

  const onKeyDown = (e: KeyboardEvent<HTMLElement>) => {
    // keys typed into an editor inside the cell belong to that editor
    if (e.target !== e.currentTarget || rows <= 0 || cols <= 0) return
    if (onKey?.(e, active) === true || e.defaultPrevented) return
    const { r, c } = active
    const mod = e.ctrlKey || e.metaKey
    let target: GridCell | null = null
    switch (e.key) {
      case "ArrowRight":
      case "ArrowLeft":
      case "ArrowDown":
      case "ArrowUp": {
        const dr = e.key === "ArrowDown" ? 1 : e.key === "ArrowUp" ? -1 : 0
        const dc = e.key === "ArrowRight" ? 1 : e.key === "ArrowLeft" ? -1 : 0
        e.preventDefault()
        if (selection) selection.dispatch({ type: "move", dr, dc, extend: e.shiftKey })
        else setOwn({ r: clampTo(r + dr, rows), c: clampTo(c + dc, cols) })
        focusActive()
        return
      }
      case "Home":
        target = mod ? { r: 0, c: 0 } : { r, c: 0 }
        break
      case "End":
        target = mod ? { r: rows - 1, c: cols - 1 } : { r, c: cols - 1 }
        break
      case "PageDown":
        target = { r: r + pageSize, c }
        break
      case "PageUp":
        target = { r: r - pageSize, c }
        break
      case "Enter":
      case "F2":
        if (!onEdit || e.altKey || mod || e.shiftKey) return
        e.preventDefault()
        onEdit(active, {})
        return
      case "Escape":
        if (!selection?.multiple) return
        e.preventDefault()
        selection.clear()
        return
      default:
        // by letter on any layout (Russian: key "ф", code "KeyA"); later Ctrl/Cmd+letter
        // shortcuts use shortcutLetter too
        if (selection && mod && !e.altKey && shortcutLetter(e) === "a") {
          e.preventDefault()
          selection.selectAll()
          return
        }
        if (onEdit && isPrintable(e)) {
          e.preventDefault()
          onEdit(active, { text: e.key })
        }
        return
    }
    e.preventDefault()
    moveTo(target, e.shiftKey)
  }

  const cellProps = (r: number, c: number): GridCellProps => ({
    "data-cell": `${r}:${c}`,
    tabIndex: r === active.r && c === active.c ? 0 : -1,
    "aria-selected": selection ? selection.isSelected(r, c) : undefined,
    onKeyDown,
    onFocus: (e) => {
      if (e.target !== e.currentTarget) return
      if (selection) selection.dispatch({ type: "focus", r, c })
      else if (r !== own.r || c !== own.c) setOwn({ r, c })
    },
    onMouseDown: selection
      ? (e) => {
          if (e.button !== 0) return
          const t = e.target as HTMLElement
          if (t !== e.currentTarget && t.closest(CONTROLS)) return
          const shift = e.shiftKey
          // Shift+Click would otherwise select text across cells; focus the cell by hand
          if (shift) e.preventDefault()
          selection.click(r, c, { shift, meta: e.metaKey || e.ctrlKey })
          if (shift) e.currentTarget.focus()
        }
      : undefined,
    onDoubleClick: onEdit
      ? (e) => {
          const t = e.target as HTMLElement
          if (t !== e.currentTarget && t.closest(CONTROLS)) return
          onEdit({ r, c }, {})
        }
      : undefined,
  })

  return { active, gridRef, cellProps, focusCell }
}
