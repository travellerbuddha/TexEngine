// The room price matrix's clipboard (PRICING_WORKSPACE_UX.md §3.10; slice S10): TSV encode and
// decode, the block Ctrl/Cmd+C copies, where a pasted block is anchored, and paste planning.
//
// Pure and deterministic, with no runtime imports (tested with `node --test`). Cells are grid
// positions (row, column of the rendered grid); what a cell holds, whether it takes entries and
// how a text is parsed are the caller's (PriceMatrix passes the shorthand parser with the contract
// currency's minor units). Paste is all or nothing: one cell that cannot be read refuses the whole
// block, and nothing is applied.

/** A cell of the rendered grid (the same shape as tex/ui GridCell). */
export interface GridPos {
  r: number
  c: number
}

/** An inclusive rectangle of cells (the same shape as tex/ui GridRange). */
export interface GridRect {
  r0: number
  c0: number
  r1: number
  c1: number
}

// ─── TSV ────────────────────────────────────────────────────────────────────

/** Cells joined by tabs, every row ended by a line break, as spreadsheets exchange them (decodeTSV
 * trims exactly that last one, so a last row of one empty cell survives the round trip). A tab or
 * line break inside a cell (never in shorthand or an amount) becomes a space, so it cannot split
 * the block. No rows is an empty text. */
export function encodeTSV(cells: readonly (readonly string[])[]): string {
  return cells.map((row) => `${row.map((v) => v.replace(/[\t\r\n]+/g, " ")).join("\t")}\n`).join("")
}

/** The block of a TSV text: one trailing line break (spreadsheets end with one) is trimmed, lines
 * are split on CRLF, LF or CR and cells on tabs; empty cells are kept (they clear). An empty text
 * is no block at all. */
export function decodeTSV(text: string): string[][] {
  if (!text) return []
  const body = text.replace(/(?:\r\n|\n|\r)$/, "")
  return body.split(/\r\n|\n|\r/).map((line) => line.split("\t"))
}

// ─── copy ───────────────────────────────────────────────────────────────────

/**
 * The block Ctrl/Cmd+C copies: the rows and the columns that hold a selected cell, in grid order,
 * with each selected cell's text and "" for the others. One range is its rectangle; ranges that
 * skip rows (a column selected by its header passes over the resolved rows) give only the rows
 * they hold, so the block pastes back onto the same rows.
 *
 * `entryRow` (the rows that take entries; the matrix's resolved rows do not): a selection that
 * holds entry rows copies those only. A paste writes entry rows only and passes over the resolved
 * ones (planPaste), so a Shift+Arrow or Shift+Click rectangle across a resolved row would
 * otherwise shift every row below it onto the next room (S10 review). The columns are then the
 * ones that hold a selected cell of a row kept. A selection of resolved rows alone copies them
 * (their server amounts, §3.10).
 */
export function copyBlock(ranges: readonly GridRect[], textAt: (r: number, c: number) => string, entryRow?: (r: number) => boolean): string[][] {
  if (!ranges.length) return []
  const inside = (r: number, c: number) => ranges.some((g) => r >= g.r0 && r <= g.r1 && c >= g.c0 && c <= g.c1)
  const held = new Set<number>()
  for (const g of ranges) for (let r = g.r0; r <= g.r1; r++) held.add(r)
  let rs = [...held].sort((a, b) => a - b)
  if (entryRow && rs.some(entryRow)) rs = rs.filter(entryRow)
  const cols = new Set<number>()
  for (const g of ranges) {
    if (!rs.some((r) => r >= g.r0 && r <= g.r1)) continue
    for (let c = g.c0; c <= g.c1; c++) cols.add(c)
  }
  const cs = [...cols].sort((a, b) => a - b)
  return rs.map((r) => cs.map((c) => (inside(r, c) ? textAt(r, c) : "")))
}

// ─── paste ──────────────────────────────────────────────────────────────────

/** Where a pasted block is anchored: the top-left cell of the range that holds the active cell
 * (Shift+Arrow moves the active cell to a corner; the block still starts where the selection
 * does), else the active cell. */
export function pasteOrigin(sel: { active: GridPos; ranges: readonly GridRect[] }): GridPos {
  const { active, ranges } = sel
  for (let i = ranges.length - 1; i >= 0; i--) {
    const g = ranges[i]
    if (active.r >= g.r0 && active.r <= g.r1 && active.c >= g.c0 && active.c <= g.c1) return { r: g.r0, c: g.c0 }
  }
  return { r: active.r, c: active.c }
}

/** At most this many failing cells are named (all of them are counted). */
export const PASTE_MAX_ERRORS = 3

/** What a parser gives back: ok, or a failure with its code (the shorthand parser's ShResult). */
export type Parsed = { ok: true } | { ok: false; code: string }

export interface PasteItem<P> {
  cell: GridPos
  /** the text pasted into the cell */
  text: string
  parsed: P
}

export interface PasteFailure {
  cell: GridPos
  /** the cell's name for the message ("P3 · Superior"), when the caller gives a label */
  where?: string
  text: string
  code: string
}

export type PasteResult<P extends Parsed = Parsed> =
  | { ok: true; items: PasteItem<P>[] }
  /** nothing to paste (an empty clipboard) */
  | { ok: false; code: "EMPTY" }
  /** no editable cell to paste into (the active cell is on a resolved row, or read-only) */
  | { ok: false; code: "NO_TARGET" }
  /** the block does not fit the editable cells from its anchor */
  | { ok: false; code: "SHAPE"; rows: number; cols: number; availableRows: number; availableCols: number }
  /** a cell cannot be read: at most PASTE_MAX_ERRORS named, `count` in all */
  | { ok: false; code: "INVALID"; errors: PasteFailure[]; count: number }

export interface PasteOptions {
  /** the grid's size */
  rows: number
  cols: number
  /** a cell's name for the failure messages */
  label?: (cell: GridPos) => string
}

/**
 * Plans a paste (§3.10), all or nothing:
 * - one value fills every selected editable cell (`selection`: useGridSelection's `selected`), or
 *   the active cell when nothing else is selected;
 * - a block is anchored at `active` (pass pasteOrigin) and must fit the editable cells from there:
 *   its rows go to the editable rows downwards (a resolved row in between is passed over, never
 *   written), its columns to the columns rightwards; otherwise SHAPE, with what is available;
 * - every cell is parsed in its context (`parse`, with the contract's minor units); any failure
 *   refuses the whole paste (INVALID), naming at most PASTE_MAX_ERRORS cells in reading order.
 * A cell that a ragged row does not have is not written.
 */
export function planPaste<P extends Parsed>(
  block: readonly (readonly string[])[],
  active: GridPos,
  selection: readonly GridPos[],
  editable: (r: number, c: number) => boolean,
  parse: (text: string, cell: GridPos) => P,
  opts: PasteOptions,
): PasteResult<P> {
  const width = block.reduce((w, row) => Math.max(w, row.length), 0)
  if (!block.length || width === 0) return { ok: false, code: "EMPTY" }
  const inGrid = (r: number, c: number) => r >= 0 && c >= 0 && r < opts.rows && c < opts.cols && editable(r, c)
  let targets: { cell: GridPos; text: string }[]
  if (block.length === 1 && width === 1) {
    const text = block[0][0]
    const cells = selection.filter((p) => inGrid(p.r, p.c))
    if (!cells.length && inGrid(active.r, active.c)) cells.push(active)
    if (!cells.length) return { ok: false, code: "NO_TARGET" }
    targets = cells.map((p) => ({ cell: { r: p.r, c: p.c }, text }))
  } else {
    if (!inGrid(active.r, active.c)) return { ok: false, code: "NO_TARGET" }
    const rows: number[] = []
    for (let r = active.r; r < opts.rows; r++) if (inGrid(r, active.c)) rows.push(r)
    const cols: number[] = []
    for (let c = active.c; c < opts.cols; c++) if (inGrid(active.r, c)) cols.push(c)
    const shape = { ok: false as const, code: "SHAPE" as const, rows: block.length, cols: width, availableRows: rows.length, availableCols: cols.length }
    if (block.length > rows.length || width > cols.length) return shape
    targets = []
    for (let i = 0; i < block.length; i++) {
      for (let j = 0; j < block[i].length; j++) {
        const cell = { r: rows[i], c: cols[j] }
        if (!inGrid(cell.r, cell.c)) return shape
        targets.push({ cell, text: block[i][j] })
      }
    }
  }
  const items: PasteItem<P>[] = []
  const errors: PasteFailure[] = []
  let count = 0
  for (const { cell, text } of targets) {
    const parsed = parse(text, cell)
    if (parsed.ok) {
      items.push({ cell, text, parsed })
      continue
    }
    count += 1
    if (errors.length < PASTE_MAX_ERRORS) errors.push(opts.label ? { cell, where: opts.label(cell), text, code: parsed.code } : { cell, text, code: parsed.code })
  }
  if (count) return { ok: false, code: "INVALID", errors, count }
  return { ok: true, items }
}
