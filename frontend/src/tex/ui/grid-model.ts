// Keyboard grid selection model (PRICING_WORKSPACE_UX.md §3.10): the pure reducer behind
// useGridSelection, plus fill planning for "Fill →" and "Fill ↓".
//
// Pure and deterministic: no runtime imports and erasable TypeScript only, so it is unit tested
// with `node --test` (tests/unit/grid-selection.test.ts). It knows cell coordinates only; what a
// cell holds, whether it can be edited and what a fill writes are the caller's business.

/** A cell by row and column index (0-based, rows × cols of the rendered grid). */
export type GridCell = { r: number; c: number }

/** An inclusive rectangle, always normalised: r0 ≤ r1 and c0 ≤ c1. */
export type GridRange = { r0: number; c0: number; r1: number; c1: number }

/**
 * The selection of one grid.
 * - `active` is the focused cell (the roving tab stop) and the moving corner of the last range;
 * - `anchor` is where the last range started (Shift+Arrow / Shift+Click extend from it);
 * - `ranges` are the selected rectangles; the last one is the one being extended. They may
 *   overlap and may cover read-only cells: `selectedCells` dedupes and filters them;
 * - `rows` × `cols` are the bounds every action clamps to (updated by `clamp`).
 */
export type GridSelection = { active: GridCell; anchor: GridCell; ranges: GridRange[]; rows: number; cols: number }

/** Whether a cell accepts edits (resolved rows and published versions do not). */
export type GridEditable = (r: number, c: number) => boolean

export type GridAction =
  /** Arrow keys: move the active cell by (dr, dc); `extend` (Shift) grows the last range. */
  | { type: "move"; dr: number; dc: number; extend?: boolean }
  /** Home / End / Ctrl+Home / Ctrl+End / PageUp / PageDown: move to a cell. */
  | { type: "moveTo"; r: number; c: number; extend?: boolean }
  /** Focus reached a cell by other means: no-op on the active cell, otherwise collapse onto it. */
  | { type: "focus"; r: number; c: number }
  /** Pointer: plain = collapse, `shift` = extend from the anchor, `meta` (Ctrl/Cmd) = add a range. */
  | { type: "click"; r: number; c: number; shift?: boolean; meta?: boolean }
  /** Row header click: the row's editable cells (`add` keeps the current selection). */
  | { type: "selectRow"; r: number; isEditable?: GridEditable; add?: boolean }
  /** Column header click: the column's editable cells, skipping read-only rows. */
  | { type: "selectCol"; c: number; isEditable?: GridEditable; add?: boolean }
  /** Ctrl/Cmd+A: every editable cell of the grid (see `editableCells`). */
  | { type: "selectAll"; cells: readonly GridCell[] }
  /** Escape: collapse the selection onto the active cell. */
  | { type: "clear" }
  /** The grid changed size (a room or period added or removed). */
  | { type: "clamp"; rows: number; cols: number }

/** One cell copy of a fill: the value of `from` is written to `to`. */
export type GridFillStep = { from: GridCell; to: GridCell }

function clampTo(v: number, n: number): number {
  return v < 0 ? 0 : v > n - 1 ? n - 1 : v
}

function hasCells(s: GridSelection): boolean {
  return s.rows > 0 && s.cols > 0
}

function clampCell(s: GridSelection, r: number, c: number): GridCell {
  return { r: clampTo(r, s.rows), c: clampTo(c, s.cols) }
}

function single(p: GridCell): GridRange {
  return { r0: p.r, c0: p.c, r1: p.r, c1: p.c }
}

function span(a: GridCell, b: GridCell): GridRange {
  return { r0: Math.min(a.r, b.r), c0: Math.min(a.c, b.c), r1: Math.max(a.r, b.r), c1: Math.max(a.c, b.c) }
}

function sameCell(a: GridCell, b: GridCell): boolean {
  return a.r === b.r && a.c === b.c
}

function readingOrder(a: GridCell, b: GridCell): number {
  return a.r - b.r || a.c - b.c
}

/** Collapse the selection onto one cell (it becomes active and the anchor). */
function collapse(s: GridSelection, p: GridCell): GridSelection {
  return { ...s, active: p, anchor: p, ranges: [single(p)] }
}

/** Move the active cell to `p` and replace the last range with anchor → p. */
function extendTo(s: GridSelection, p: GridCell): GridSelection {
  const ranges = s.ranges.length ? s.ranges.slice(0, -1) : []
  return { ...s, active: p, ranges: [...ranges, span(s.anchor, p)] }
}

/**
 * Compress cells into rectangles: contiguous runs per row, then identical runs on consecutive
 * rows merge. Deterministic (ordered by first row, then first column).
 */
function rangesOf(list: readonly GridCell[]): GridRange[] {
  const sorted = [...list].sort(readingOrder)
  const out: GridRange[] = []
  let i = 0
  while (i < sorted.length) {
    const r = sorted[i].r
    const c0 = sorted[i].c
    let c1 = c0
    i++
    while (i < sorted.length && sorted[i].r === r && sorted[i].c === c1 + 1) {
      c1 = sorted[i].c
      i++
    }
    // skip duplicates of the run's last cell
    while (i < sorted.length && sorted[i].r === r && sorted[i].c <= c1) i++
    const open = out.find((g) => g.r1 === r - 1 && g.c0 === c0 && g.c1 === c1)
    if (open) open.r1 = r
    else out.push({ r0: r, c0, r1: r, c1 })
  }
  return out
}

/** Replace (or, with `add`, extend) the selection with `list`; the first cell becomes active. */
function selectList(s: GridSelection, list: GridCell[], add: boolean | undefined): GridSelection {
  if (!list.length) return s
  const first = list[0]
  const ranges = rangesOf(list)
  return { ...s, active: first, anchor: first, ranges: add ? [...s.ranges, ...ranges] : ranges }
}

export function gridSelectionInit(rows: number, cols: number): GridSelection {
  const origin = { r: 0, c: 0 }
  return { active: origin, anchor: origin, ranges: rows > 0 && cols > 0 ? [single(origin)] : [], rows, cols }
}

/** The editable cells of a rows × cols grid in reading order (the list `selectAll` takes). */
export function editableCells(rows: number, cols: number, isEditable?: GridEditable): GridCell[] {
  const out: GridCell[] = []
  for (let r = 0; r < rows; r++) for (let c = 0; c < cols; c++) if (!isEditable || isEditable(r, c)) out.push({ r, c })
  return out
}

/** The reducer. It returns the same object when an action changes nothing. */
export function gridSelectionReducer(s: GridSelection, a: GridAction): GridSelection {
  if (a.type === "clamp") return clampSelection(s, a.rows, a.cols)
  if (!hasCells(s)) return s
  switch (a.type) {
    case "move": {
      const p = clampCell(s, s.active.r + a.dr, s.active.c + a.dc)
      return a.extend ? extendTo(s, p) : collapse(s, p)
    }
    case "moveTo": {
      const p = clampCell(s, a.r, a.c)
      return a.extend ? extendTo(s, p) : collapse(s, p)
    }
    case "focus": {
      const p = clampCell(s, a.r, a.c)
      return sameCell(p, s.active) ? s : collapse(s, p)
    }
    case "click": {
      const p = clampCell(s, a.r, a.c)
      if (a.shift) return extendTo(s, p)
      if (a.meta) return { ...s, active: p, anchor: p, ranges: [...s.ranges, single(p)] }
      return collapse(s, p)
    }
    case "selectRow": {
      if (a.r < 0 || a.r >= s.rows) return s
      const list: GridCell[] = []
      for (let c = 0; c < s.cols; c++) if (!a.isEditable || a.isEditable(a.r, c)) list.push({ r: a.r, c })
      return selectList(s, list, a.add)
    }
    case "selectCol": {
      if (a.c < 0 || a.c >= s.cols) return s
      const list: GridCell[] = []
      for (let r = 0; r < s.rows; r++) if (!a.isEditable || a.isEditable(r, a.c)) list.push({ r, c: a.c })
      return selectList(s, list, a.add)
    }
    case "selectAll": {
      const seen = new Set<number>()
      const list: GridCell[] = []
      for (const p of a.cells) {
        if (p.r < 0 || p.c < 0 || p.r >= s.rows || p.c >= s.cols) continue
        const key = p.r * s.cols + p.c
        if (seen.has(key)) continue
        seen.add(key)
        list.push({ r: p.r, c: p.c })
      }
      if (!list.length) return s
      list.sort(readingOrder)
      const keep = seen.has(s.active.r * s.cols + s.active.c)
      const active = keep ? s.active : list[0]
      return { ...s, active, anchor: active, ranges: rangesOf(list) }
    }
    case "clear":
      return collapse(s, s.active)
  }
}

function clampSelection(s: GridSelection, rows: number, cols: number): GridSelection {
  if (rows === s.rows && cols === s.cols) return s
  if (rows <= 0 || cols <= 0) {
    const origin = { r: 0, c: 0 }
    return { active: origin, anchor: origin, ranges: [], rows, cols }
  }
  const next = { ...s, rows, cols }
  const active = clampCell(next, s.active.r, s.active.c)
  const anchor = clampCell(next, s.anchor.r, s.anchor.c)
  const ranges: GridRange[] = []
  for (const g of s.ranges) {
    if (g.r0 >= rows || g.c0 >= cols) continue
    ranges.push({ r0: g.r0, c0: g.c0, r1: Math.min(g.r1, rows - 1), c1: Math.min(g.c1, cols - 1) })
  }
  return { active, anchor, ranges: ranges.length ? ranges : [single(active)], rows, cols }
}

export function isCellSelected(s: GridSelection, r: number, c: number): boolean {
  for (const g of s.ranges) if (r >= g.r0 && r <= g.r1 && c >= g.c0 && c <= g.c1) return true
  return false
}

/** True when the selection is just the active cell (Escape then has nothing to clear). */
export function isSingleCell(s: GridSelection): boolean {
  if (s.ranges.length !== 1) return s.ranges.length === 0
  const g = s.ranges[0]
  return g.r0 === g.r1 && g.c0 === g.c1
}

/** The selected cells that accept edits: unique, within bounds, in reading order. */
export function selectedCells(s: GridSelection, isEditable?: GridEditable): GridCell[] {
  const seen = new Set<number>()
  const out: GridCell[] = []
  for (const g of s.ranges) {
    for (let r = Math.max(0, g.r0); r <= Math.min(g.r1, s.rows - 1); r++) {
      for (let c = Math.max(0, g.c0); c <= Math.min(g.c1, s.cols - 1); c++) {
        const key = r * s.cols + c
        if (seen.has(key)) continue
        seen.add(key)
        if (!isEditable || isEditable(r, c)) out.push({ r, c })
      }
    }
  }
  return out.sort(readingOrder)
}

/**
 * Fill right ("copy across periods"): in each row, the leftmost selected cell is copied to the
 * other selected cells of that row. Steps come in reading order of their targets.
 */
export function fillRightPlan(cells: readonly GridCell[]): GridFillStep[] {
  const sorted = [...cells].sort(readingOrder)
  const out: GridFillStep[] = []
  let from: GridCell | null = null
  for (const p of sorted) {
    if (!from || from.r !== p.r) from = p
    else if (from.c !== p.c) out.push({ from: { r: from.r, c: from.c }, to: { r: p.r, c: p.c } })
  }
  return dedupeSteps(out)
}

/**
 * Fill down ("copy down rooms"): in each column, the topmost selected cell is copied to the
 * other selected cells of that column. Steps come in reading order of their targets. Whether a
 * copy is allowed between two rows (formula ↔ formula, price ↔ price) is decided by the caller.
 */
export function fillDownPlan(cells: readonly GridCell[]): GridFillStep[] {
  const top = new Map<number, GridCell>()
  for (const p of cells) {
    const t = top.get(p.c)
    if (!t || p.r < t.r) top.set(p.c, p)
  }
  const out: GridFillStep[] = []
  for (const p of [...cells].sort(readingOrder)) {
    const t = top.get(p.c)
    if (t && t.r !== p.r) out.push({ from: { r: t.r, c: t.c }, to: { r: p.r, c: p.c } })
  }
  return dedupeSteps(out)
}

function dedupeSteps(steps: GridFillStep[]): GridFillStep[] {
  const seen = new Set<string>()
  return steps.filter((s) => {
    const k = `${s.to.r}:${s.to.c}`
    if (seen.has(k)) return false
    seen.add(k)
    return true
  })
}
