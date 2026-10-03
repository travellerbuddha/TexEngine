// Harness page for tests/dom/keyboard.spec.ts: the S7 keyboard check (PRICING_WORKSPACE_UX.md
// §3.10, §3.19) of Popover, Menu, Tooltip and the grid hooks, with the app's styles.
// Open /tests/dom/keyboard.html under `npx vite --config tests/dom/vite.config.ts` to try it by hand.
import { StrictMode, useRef, useState } from "react"
import { createRoot } from "react-dom/client"
import "./harness.css"
import {
  ContextMenu,
  Drawer,
  Menu,
  MenuItem,
  MenuSeparator,
  Popover,
  Tooltip,
  fillDownPlan,
  fillRightPlan,
  focusHeaderLane,
  headerLaneKeyDown,
  useGridNavigation,
  useGridSelection,
  useTooltip,
  type GridNavigationApi,
} from "../../src/tex/ui"

declare global {
  interface Window {
    /** Menu items and other actions that ran, in order. */
    __log: string[]
    /** performance.now() of the last focus / pointer entry on a [data-probe] element. */
    __probe: { focus?: number; pointer?: number }
    /** performance.now() when a tooltip with this text first appeared since the last reset. */
    __tips: Record<string, number>
  }
}

window.__log = []
window.__probe = {}
window.__tips = {}
const log = (what: string) => () => {
  window.__log.push(what)
}

document.addEventListener(
  "focusin",
  (e) => {
    if (e.target instanceof HTMLElement && e.target.dataset.probe) window.__probe.focus = performance.now()
  },
  true,
)
document.addEventListener(
  "pointerover",
  (e) => {
    if (e.target instanceof HTMLElement && e.target.closest("[data-probe]")) window.__probe.pointer ??= performance.now()
  },
  true,
)
new MutationObserver((records) => {
  for (const rec of records)
    for (const n of rec.addedNodes) {
      if (!(n instanceof HTMLElement)) continue
      const tip = n.getAttribute("role") === "tooltip" ? n : n.querySelector<HTMLElement>('[role="tooltip"]')
      const text = tip?.textContent ?? ""
      if (tip && !(text in window.__tips)) window.__tips[text] = performance.now()
    }
}).observe(document.body, { childList: true, subtree: true })

const button = "rounded border border-zinc-300 bg-white px-2 py-1"

function PopoverCase() {
  const [open, setOpen] = useState(false)
  const anchor = useRef<HTMLButtonElement>(null)
  const value = useRef<HTMLInputElement>(null)
  return (
    <>
      <button ref={anchor} type="button" data-testid="pop-trigger" className={button} onClick={() => setOpen((o) => !o)}>
        Edit price
      </button>
      <Popover open={open} onClose={() => setOpen(false)} anchorRef={anchor} label="Edit price: Superior · P4" initialFocusRef={value}>
        <div className="flex flex-col gap-2">
          {/* the first focusable element: initialFocusRef wins over it */}
          <input aria-label="Note" className={button} />
          <input ref={value} aria-label="Value" className={button} />
          <Menu label="More" text="More" variant="secondary">
            <MenuItem onSelect={log("pop:set-base")}>Set as base</MenuItem>
            <MenuItem onSelect={log("pop:move-up")}>Move up</MenuItem>
            <MenuItem onSelect={log("pop:move-down")}>Move down</MenuItem>
          </Menu>
        </div>
      </Popover>
    </>
  )
}

function CornerPopover() {
  const [open, setOpen] = useState(false)
  const anchor = useRef<HTMLButtonElement>(null)
  return (
    <>
      <button ref={anchor} type="button" className={button} style={{ position: "fixed", right: 8, bottom: 8 }} onClick={() => setOpen((o) => !o)}>
        Corner
      </button>
      <Popover open={open} onClose={() => setOpen(false)} anchorRef={anchor} label="Corner popover" width="sm">
        <input aria-label="Corner value" className={button} />
      </Popover>
    </>
  )
}

function RowMenu() {
  return (
    <Menu label="Row actions: Superior" icon={<span aria-hidden>⋯</span>}>
      <MenuItem onSelect={log("set-base")}>Set as base</MenuItem>
      <MenuItem onSelect={log("derive")}>Derive from…</MenuItem>
      <MenuItem disabled onSelect={log("capacity")}>
        Capacity…
      </MenuItem>
      <MenuSeparator />
      <MenuItem onSelect={log("move-up")}>Move up</MenuItem>
      <MenuItem onSelect={log("move-down")} shortcut="Alt+↓" keyshortcuts="Alt+ArrowDown">
        Move down
      </MenuItem>
      {/* typeahead by textValue: the visible text starts with a glyph */}
      <MenuItem onSelect={log("test")} textValue="Test this price">
        ▶ Test this price
      </MenuItem>
      <MenuItem tone="danger" onSelect={log("remove")}>
        Remove room
      </MenuItem>
    </Menu>
  )
}

/** A cell's context menu (S14): opened by a right-click, Shift+F10 or the ContextMenu key. */
function ContextMenuCase() {
  const [open, setOpen] = useState(false)
  const cell = useRef<HTMLDivElement>(null)
  return (
    <>
      <div
        ref={cell}
        tabIndex={0}
        data-testid="ctx-cell"
        className={button}
        onContextMenu={(e) => {
          e.preventDefault()
          setOpen(true)
        }}
        onKeyDown={(e) => {
          if ((e.key === "F10" && e.shiftKey) || e.key === "ContextMenu") {
            e.preventDefault()
            setOpen(true)
          }
        }}
      >
        Superior · P2
      </div>
      <ContextMenu open={open} onClose={() => setOpen(false)} anchorRef={cell} label="Cell actions: Superior · P2">
        <MenuItem onSelect={log("ctx:edit")} shortcut="Alt+↵" keyshortcuts="Alt+Enter">
          Edit rule…
        </MenuItem>
        <MenuItem onSelect={log("ctx:test")}>Test this price</MenuItem>
      </ContextMenu>
    </>
  )
}

function DrawerCase() {
  const [open, setOpen] = useState(false)
  return (
    <>
      <button type="button" data-testid="drawer-btn" className={button} onClick={() => setOpen(true)}>
        Open drawer
      </button>
      <Drawer open={open} onClose={() => setOpen(false)} title="Bands">
        <Menu label="Band actions" text="Band actions" variant="secondary">
          <MenuItem onSelect={log("band:rename")}>Rename</MenuItem>
          <MenuItem onSelect={log("band:delete")}>Delete</MenuItem>
        </Menu>
      </Drawer>
    </>
  )
}

const ROWS = 4
const COLS = 5
// row 1 is a resolved (read-only) row
const isEditable = (r: number) => r !== 1

function GridCellView({ r, c, nav }: { r: number; c: number; nav: GridNavigationApi }) {
  const tip = useTooltip(r === 0 && c === 0 ? "Cell 0:0 tooltip" : null)
  const p = nav.cellProps(r, c)
  const tp = tip.triggerProps
  return (
    <td
      role="gridcell"
      aria-readonly={!isEditable(r) || undefined}
      className="border border-zinc-200 px-3 py-1 tabular-nums aria-selected:bg-sky-100"
      {...p}
      ref={tp.ref}
      aria-describedby={tp["aria-describedby"]}
      onKeyDown={(e) => {
        tp.onKeyDown(e)
        p.onKeyDown(e)
      }}
      onFocus={(e) => {
        p.onFocus(e)
        tp.onFocus(e)
      }}
      onBlur={tp.onBlur}
      onPointerEnter={tp.onPointerEnter}
      onPointerLeave={tp.onPointerLeave}
      onPointerDown={tp.onPointerDown}
    >
      {`${r}:${c}`}
      {tip.tooltip}
    </td>
  )
}

function GridCase() {
  const [edit, setEdit] = useState("")
  const selection = useGridSelection({ rows: ROWS, cols: COLS, isEditable })
  const root = useRef<HTMLTableElement | null>(null)
  const nav = useGridNavigation({
    rows: ROWS,
    cols: COLS,
    selection,
    // the header buttons are the header lane (one tab stop per grid, S16 re-review)
    onEdge: (edge, cell) => focusHeaderLane(root.current, edge, cell),
    onEdit: (cell, req) => setEdit(`${cell.r}:${cell.c}:${req.text ?? "<select-all>"}`),
    // the caller's keys run first: Delete clears (CLEAR semantics in the workspace)
    onKey: (e) => {
      if (e.key !== "Delete") return
      e.preventDefault()
      setEdit("delete")
      return true
    },
  })
  const state = {
    selected: selection.selected,
    edit,
    right: fillRightPlan(selection.selected).length,
    down: fillDownPlan(selection.selected).length,
  }
  const rows = Array.from({ length: ROWS }, (_, i) => i)
  const cols = Array.from({ length: COLS }, (_, i) => i)
  return (
    <div className="flex flex-wrap items-start gap-4">
      <table
        role="grid"
        aria-label="Prices"
        aria-multiselectable
        data-testid="grid"
        ref={(el) => {
          root.current = el
          nav.gridRef(el)
        }}
        onKeyDownCapture={(e) => void headerLaneKeyDown(e, root.current, nav.focusCell, { rows: ROWS, cols: COLS })}
        className="border-collapse"
      >
        <thead>
          <tr>
            <td />
            {cols.map((c) => (
              <th key={c} role="columnheader">
                <button type="button" data-testid={`col${c}`} tabIndex={-1} data-lane-col={String(c)} className="px-2" onClick={(e) => selection.selectCol(c, { add: e.ctrlKey || e.metaKey })}>
                  {`P${c + 1}`}
                </button>
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r}>
              <th role="rowheader">
                <button type="button" data-testid={`row${r}`} tabIndex={-1} data-lane-rows={String(r)} className="px-2" onClick={(e) => selection.selectRow(r, { add: e.ctrlKey || e.metaKey })}>
                  {`R${r}`}
                </button>
              </th>
              {cols.map((c) => (
                <GridCellView key={c} r={r} c={c} nav={nav} />
              ))}
            </tr>
          ))}
        </tbody>
      </table>
      <output data-testid="grid-state" className="block min-w-0 max-w-full break-all font-mono text-xs">
        {JSON.stringify(state)}
      </output>
    </div>
  )
}

function Harness() {
  return (
    <div className="tex-root p-4 text-sm">
      <div className="flex flex-wrap items-center gap-2">
        <button type="button" className={button}>
          Before
        </button>
        <PopoverCase />
        <RowMenu />
        <Tooltip content="Published versions are immutable">
          <button type="button" data-testid="tip-btn" data-probe="tip" className={button}>
            Published
          </button>
        </Tooltip>
        <button type="button" data-testid="after" className={button}>
          After
        </button>
        <DrawerCase />
        <ContextMenuCase />
      </div>
      <div className="mt-6">
        <GridCase />
      </div>
      <CornerPopover />
      {/* the page scrolls, so a key that is not prevented would scroll it */}
      <div style={{ height: 2000 }} />
    </div>
  )
}

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <Harness />
  </StrictMode>,
)
