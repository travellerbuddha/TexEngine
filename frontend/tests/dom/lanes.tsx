// Harness page for tests/dom/lanes.spec.ts: the header lane and the grid's focus timing
// (PRICING_WORKSPACE_UX.md §3.19; Pricing Workspace final follow-up) on a grid shaped as the room
// price matrix is: rooms as rows, "All periods" as the first column (a header with no control of
// its own), a menu button per period and "+ Period" after the last column. `?periods=n` starts it
// with n periods (default 0: a draft with rooms and no period yet). The Keyboard shortcuts popover
// is rendered too, in the language `?lang=` names (tests/dom/lanes.spec.ts measures its width).
// Open /tests/dom/lanes.html under `npx vite --config tests/dom/vite.config.ts` to try it by hand.
import { StrictMode, useRef, useState } from "react"
import { createRoot } from "react-dom/client"
import "./harness.css"
import { setTexLang, type TexLang } from "../../src/tex/i18n"
import { KeyboardShortcuts } from "../../src/tex/screens/rates/workspace/BulkToolbar"
import { focusHeaderLane, headerLaneKeyDown, useGridNavigation, useGridSelection, type GridNavigationApi } from "../../src/tex/ui"

declare global {
  interface Window {
    /** actions that ran, in order ("add-period:P1") */
    __log: string[]
  }
}
window.__log = []

const params = new URLSearchParams(location.search)
const ROOMS = ["Standard", "Family Suite", "Garden Villa"]
const button = "rounded border border-zinc-300 bg-white px-2 py-0.5"

function Cell({ r, c, nav }: { r: number; c: number; nav: GridNavigationApi }) {
  return (
    <td role="gridcell" className="border border-zinc-200 px-3 py-1 tabular-nums" {...nav.cellProps(r, c)}>
      {`${r}:${c}`}
    </td>
  )
}

function LaneGrid() {
  const [periods, setPeriods] = useState<string[]>(() => Array.from({ length: Number(params.get("periods") ?? 0) }, (_, i) => `P${i + 1}`))
  const cols = periods.length + 1
  const rows = ROOMS.length
  const selection = useGridSelection({ rows, cols })
  const root = useRef<HTMLTableElement | null>(null)
  const nav = useGridNavigation({ rows, cols, selection, onEdge: (edge, cell) => focusHeaderLane(root.current, edge, cell) })
  return (
    <table
      role="grid"
      aria-label="Room prices by period"
      data-testid="lane-grid"
      ref={(el) => {
        root.current = el
        nav.gridRef(el)
      }}
      onKeyDownCapture={(e) => void headerLaneKeyDown(e, root.current, nav.focusCell, { rows, cols })}
      className="border-collapse"
    >
      <thead>
        <tr>
          <th role="columnheader">Room</th>
          {/* All periods: no control of its own (as in the matrix) */}
          <th role="columnheader">All periods</th>
          {periods.map((p, i) => (
            <th key={p} role="columnheader">
              <button type="button" tabIndex={-1} data-lane-col={String(i + 1)} aria-label={`Period actions: ${p}`} className={button}>
                {p}
              </button>
            </th>
          ))}
          <th role="columnheader">
            <button
              type="button"
              tabIndex={-1}
              data-lane-col={String(cols)}
              aria-label="Add period"
              className={button}
              onClick={() => {
                const code = `P${periods.length + 1}`
                window.__log.push(`add-period:${code}`)
                setPeriods((ps) => [...ps, code])
              }}
            >
              + Period
            </button>
          </th>
        </tr>
      </thead>
      <tbody>
        {ROOMS.map((room, r) => (
          <tr key={room}>
            <th role="rowheader">
              <button type="button" tabIndex={-1} data-lane-rows={String(r)} aria-label={`Room actions: ${room}`} className={button}>
                {room}
              </button>
            </th>
            {Array.from({ length: cols }, (_, c) => (
              <Cell key={c} r={r} c={c} nav={nav} />
            ))}
          </tr>
        ))}
      </tbody>
    </table>
  )
}

function Harness() {
  return (
    <div className="tex-root space-y-4 p-4 text-sm">
      <button type="button" data-testid="before" className={button}>
        Before
      </button>
      <LaneGrid />
      <KeyboardShortcuts />
    </div>
  )
}

const lang = (params.get("lang") ?? "en") as TexLang
void setTexLang(lang).then(() =>
  createRoot(document.getElementById("root")!).render(
    <StrictMode>
      <Harness />
    </StrictMode>,
  ),
)
