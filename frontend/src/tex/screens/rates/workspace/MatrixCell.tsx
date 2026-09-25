// One cell of the room price matrix (PRICING_WORKSPACE_UX.md §3.3.3, §3.4.1, §3.19; slice S9): a
// role="gridcell" wired to the keyboard grid (useGridNavigation's cellProps), its tooltip, the
// state glyphs (never colour alone), the ▾ trigger of the advanced popover, and the inline editor
// with its reading line. What the cell shows is computed by PriceMatrix; this renders it.
import { memo, useEffect, useId, useRef, useState, type KeyboardEvent, type MouseEvent, type ReactNode } from "react"
import { ChevronDown } from "lucide-react"
import { cn } from "../../../../lib/utils"
import { useTooltip, type GridCellProps, type GridNavigationApi } from "../../../ui"

export type CellTone = "plain" | "muted" | "override" | "fixed" | "missing" | "resolved" | "error" | "pending"

const TONE: Record<CellTone, string> = {
  plain: "text-zinc-900",
  muted: "text-zinc-500",
  // period override: amber tint with a corner triangle (the glyph ◆ says it without colour)
  override:
    "bg-amber-50 text-amber-950 before:absolute before:top-0 before:right-0 before:border-t-[7px] before:border-l-[7px] before:border-t-amber-500 before:border-l-transparent before:content-['']",
  fixed: "bg-amber-50 text-amber-950",
  missing: "text-rose-700 outline-1 -outline-offset-2 outline-dashed outline-rose-400",
  resolved: "bg-zinc-50 text-zinc-800",
  error: "text-rose-800 underline decoration-rose-500 decoration-wavy underline-offset-2",
  pending: "text-zinc-600",
}

/** What a cell shows (computed by PriceMatrix, memoised apart from the selection). */
export interface CellView {
  /** a stable id of an entry cell (data-cellid), to find it again after an edit */
  cellId?: string
  /** the cell's full accessible name (§3.19) */
  label: string
  tone: CellTone
  content: ReactNode
  /** read-only reason, override explanation or exact server value; hover/keyboard focus only */
  tooltip?: string
  /** aria-readonly (resolved rows, read-only versions) */
  readOnly: boolean
  /** the resolved value belongs to an older state than the one on screen (§3.14) */
  stale?: boolean
  /** an error message, referenced by aria-describedby (aria-invalid) */
  error?: string
  /** the ▾ trigger of the advanced popover (editable cells only) */
  trigger?: { label: string; onOpen: (anchor: HTMLElement) => void }
  onContextMenu?: (e: MouseEvent<HTMLElement>) => void
}

export interface MatrixCellProps {
  nav: GridCellProps
  view: CellView
  /** tint the cell when selected (a selection of more than the active cell) */
  tint?: boolean
  /** the inline editor while this cell is being edited */
  editor?: ReactNode
  /** the first row of a room block (a 2 px separator above it) */
  blockStart?: boolean
  /** the active cell (the grid's tab stop) and whether it is selected: what its nav props say */
  active?: boolean
  selected?: boolean
  /** the selection state, for the active cell only: it re-renders with every new selection, so
   * its keyboard handlers (the only ones that receive keys) always see the current one */
  selState?: unknown
}

export interface MatrixRowCellsProps {
  r: number
  /** the row's cell views (PriceMatrix's memoised cellViews[r]) */
  views: CellView[]
  nav: GridNavigationApi
  /** the active cell's column when it is in this row, else -1 */
  activeC: number
  /** which of the row's cells are selected ("0110…") */
  selected: string
  /** the selection state, passed to the active cell's row only (see below) */
  selState?: unknown
  tint: boolean
  blockStart: boolean
  /** the column being edited in this row, else -1, and its editor */
  editC: number
  editor?: ReactNode
}

/**
 * The cells of one matrix row. Moving the active cell or the selection re-renders only the rows
 * whose active cell, selection or editor changed, and in them only the cells that changed, so the
 * keyboard stays fast on large contracts. Cell handlers can therefore be older than the grid's
 * latest render, which is safe: a cell receives keys only while it is focused and focusing it makes
 * it the active cell; the active cell's row gets every new selection state (`selState`), so its
 * handlers always see the current selection; and a change of the draft, of the server's answers
 * or of the entries in flight gives every cell a new view.
 */
export const MatrixRowCells = memo(
  function MatrixRowCells({ r, views, nav, activeC, selected, selState, tint, blockStart, editC, editor }: MatrixRowCellsProps) {
    return (
      <>
        {views.map((view, c) => (
          <MatrixCell
            key={c}
            nav={nav.cellProps(r, c)}
            view={view}
            tint={tint}
            blockStart={blockStart}
            editor={c === editC ? editor : undefined}
            active={c === activeC}
            selected={selected[c] === "1"}
            selState={c === activeC ? selState : undefined}
          />
        ))}
      </>
    )
  },
  (a, b) =>
    a.r === b.r &&
    a.views === b.views &&
    a.activeC === b.activeC &&
    a.selected === b.selected &&
    a.selState === b.selState &&
    a.tint === b.tint &&
    a.blockStart === b.blockStart &&
    a.editC === b.editC &&
    a.editor === b.editor,
)

/**
 * A cell re-renders when its view, its tab stop, its selection or its editor changes (the same
 * reasoning as MatrixRowCells for its handlers).
 */
export const MatrixCell = memo(
  MatrixCellImpl,
  (a, b) =>
    a.view === b.view &&
    a.editor === b.editor &&
    a.tint === b.tint &&
    a.blockStart === b.blockStart &&
    a.active === b.active &&
    a.selected === b.selected &&
    a.selState === b.selState &&
    a.nav["data-cell"] === b.nav["data-cell"],
)

function MatrixCellImpl({ nav, view, tint, editor, blockStart }: MatrixCellProps) {
  const { cellId, label, tone, tooltip, readOnly, stale, error, trigger, onContextMenu } = view
  const tip = useTooltip(editor ? null : tooltip)
  const errId = useId()
  const tp = tip.triggerProps
  const describedBy = [tp["aria-describedby"], error ? errId : undefined].filter(Boolean).join(" ") || undefined
  return (
    <div
      role="gridcell"
      data-cellid={cellId}
      aria-label={editor ? undefined : label}
      aria-readonly={readOnly || undefined}
      aria-invalid={error ? true : undefined}
      aria-describedby={describedBy}
      {...nav}
      ref={tp.ref}
      onKeyDown={(e) => {
        tp.onKeyDown(e)
        nav.onKeyDown(e)
      }}
      onFocus={(e) => {
        nav.onFocus(e)
        tp.onFocus(e)
      }}
      onBlur={tp.onBlur}
      onPointerEnter={tp.onPointerEnter}
      onPointerLeave={tp.onPointerLeave}
      onPointerDown={tp.onPointerDown}
      onContextMenu={onContextMenu}
      className={cn(
        "group relative flex h-full min-h-7 items-center justify-end border-r border-b border-zinc-100 px-2 text-[13px] tabular-nums outline-none select-none",
        "focus-visible:z-[1] focus-visible:ring-2 focus-visible:ring-tex-500 focus-visible:ring-inset",
        tint && "aria-selected:bg-sky-50",
        blockStart && "border-t-2 border-t-zinc-200",
        TONE[tone],
        stale && "opacity-55",
        editor ? "z-[3] p-0" : undefined,
      )}
    >
      {editor ?? (
        <>
          <span className="min-w-0 truncate">{view.content}</span>
          {trigger && (
            <button
              type="button"
              tabIndex={-1}
              aria-label={trigger.label}
              onMouseDown={(e) => e.preventDefault()}
              onClick={(e) => {
                e.stopPropagation()
                const cell = (e.currentTarget as HTMLElement).closest<HTMLElement>('[role="gridcell"]')
                if (cell) trigger.onOpen(cell)
              }}
              className="absolute top-0.5 left-0.5 hidden size-4 items-center justify-center rounded text-zinc-500 group-focus-within:flex group-hover:flex hover:bg-zinc-200"
            >
              <ChevronDown className="size-3" aria-hidden />
            </button>
          )}
          {error && (
            <span id={errId} hidden>
              {error}
            </span>
          )}
        </>
      )}
      {tip.tooltip}
    </div>
  )
}

export interface CellEditorProps {
  /** "Price: {room} · {period}" */
  label: string
  /** the text the edit starts from; what is typed stays here (typing re-renders the editor only) */
  initialText: string
  /** edit the current text with all of it selected (Enter, F2, double-click); else the caret goes last */
  selectAll: boolean
  /** the reading line under the cell for a text (§3.4.1), and whether the text is refused */
  readingFor: (text: string) => { text: string; invalid: boolean }
  /** every key: the grid acts on Enter, Tab, Escape, Alt+Enter and Ctrl/Cmd+Enter; a refusal comes
   * back as the message the reading line shows until the text changes */
  onKey: (e: KeyboardEvent<HTMLInputElement>, text: string) => string | void
  onBlur: (text: string) => void
}

export function CellEditor({ label, initialText, selectAll, readingFor, onKey, onBlur }: CellEditorProps) {
  const ref = useRef<HTMLInputElement>(null)
  const readingId = useId()
  const [text, setText] = useState(initialText)
  const [refusal, setRefusal] = useState<string>()
  useEffect(() => {
    const el = ref.current
    if (!el) return
    el.focus({ preventScroll: true })
    if (selectAll) el.select()
    else el.setSelectionRange(el.value.length, el.value.length)
    // only when the editor opens
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])
  const reading = readingFor(text)
  const invalid = Boolean(refusal) || reading.invalid
  return (
    <>
      <input
        ref={ref}
        type="text"
        // the full keyboard: a phone's decimal keypad has no x, %, + or =, so a formula could not be
        // typed into a cell there (§3.21 keeps single-cell editing on phones)
        inputMode="text"
        autoCapitalize="off"
        autoCorrect="off"
        autoComplete="off"
        spellCheck={false}
        aria-label={label}
        aria-invalid={invalid || undefined}
        aria-describedby={readingId}
        value={text}
        onChange={(e) => {
          setText(e.target.value)
          setRefusal(undefined)
        }}
        onKeyDown={(e) => {
          const r = onKey(e, text)
          if (r) setRefusal(r)
        }}
        onBlur={() => onBlur(text)}
        className={cn(
          "h-full min-h-7 w-full bg-white px-2 text-right text-[13px] tabular-nums outline-none ring-2 ring-tex-500 ring-inset",
          invalid && "ring-rose-500",
        )}
      />
      <div
        id={readingId}
        role="status"
        aria-live="polite"
        className={cn(
          // a hint over the cells below: clicks go through to them
          "pointer-events-none absolute top-full right-0 z-[4] mt-px w-max max-w-[22rem] rounded-md border px-2 py-1 text-left text-xs leading-snug whitespace-normal shadow-tex-pop",
          invalid ? "border-rose-200 bg-rose-50 text-rose-800" : "border-zinc-200 bg-white text-zinc-700",
        )}
      >
        {refusal ?? reading.text}
      </div>
    </>
  )
}
