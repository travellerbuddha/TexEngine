// Harness page for tests/dom/history.spec.ts: the workspace undo history's React binding
// (PRICING_WORKSPACE_UX.md §3.10; slices S9, S10) with the real useWorkspaceHistory, useUndoToast
// and the toast's view. "Fill" is a bulk entry of the matrix (it shows the toast), "Edit" another
// matrix entry, and the "Family price" field a Rule table: every keystroke writes the whole
// period_rates table through `record`, as the Advanced rule tables do in the version editor.
// Open /tests/dom/history.html under `npx vite --config tests/dom/vite.config.ts` to try it by hand.
import { StrictMode, useCallback, useMemo, useRef, useState } from "react"
import { createRoot } from "react-dom/client"
import "./harness.css"
import type { EditorState, Tables } from "../../src/tex/screens/rates/lib/tables"
import type { Row, VersionTable } from "../../src/tex/screens/rates/lib/types"
import { UndoToastView } from "../../src/tex/screens/rates/workspace/BulkToolbar"
import { useUndoToast, useWorkspaceHistory } from "../../src/tex/screens/rates/workspace/useWorkspaceHistory"

declare global {
  interface Window {
    /** undo / redo labels, in order ("undo:Fill", "toast:Fill", "undo:null") */
    __log: string[]
  }
}
window.__log = []

const empty = (): Tables => ({ rooms: [], periods: [], period_rates: [], age_bands: [], occupancy_rules: [], boards: [], rate_plans: [], offers: [] })
let seq = 0
const rate = (room: string, period: string, value: string): Row => ({ _key: `h${++seq}`, room_type: room, period_code: period, op: "ABSOLUTE", value })

function Harness() {
  const [state, setState] = useState<EditorState>(() => ({ settings: { child_ordering: "OLDEST_FIRST" } as EditorState["settings"], tables: empty() }))
  const setTable = useCallback((k: VersionTable, rows: Row[]) => setState((s) => ({ ...s, tables: { ...s.tables, [k]: rows } })), [])
  // the settings are recorded too (S16 review): the editor's writers put them back
  const writers = useMemo(() => ({ settings: (settings: EditorState["settings"]) => setState((s) => ({ ...s, settings })) }), [])
  const history = useWorkspaceHistory(state, setTable, writers)
  const toast = useUndoToast(history)
  const cell = useRef<HTMLDivElement | null>(null)
  const rates = state.tables.period_rates
  const family = String(rates.find((r) => r.room_type === "FAM")?.value ?? "")

  const add = (label: string, room: string) => {
    const now = history.current() ?? state.tables
    const next = [...now.period_rates, rate(room, `P${now.period_rates.filter((r) => r.room_type === room).length + 1}`, "70")]
    return history.commit(label, now, { ...now, period_rates: next })
  }
  const log = (what: string, label: string | null) => window.__log.push(`${what}:${label}`)

  return (
    <main className="space-y-3 p-4 text-sm">
      <div role="group" aria-label="Toolbar" className="flex gap-2">
        <button type="button" className="rounded border px-2 py-1" onClick={() => add("Fill", "STD") && toast.show("Applied to 1 cell")}>
          Fill
        </button>
        <button type="button" className="rounded border px-2 py-1" onClick={() => add("Edit", "DLX")}>
          Edit
        </button>
        <button type="button" className="rounded border px-2 py-1" disabled={!history.canUndo} onClick={() => log("undo", history.undo())}>
          Undo
        </button>
        <button type="button" className="rounded border px-2 py-1" disabled={!history.canRedo} onClick={() => log("redo", history.redo())}>
          Redo
        </button>
      </div>
      <label className="block">
        Family price
        <input
          className="ml-2 rounded border px-2 py-1"
          value={family}
          onChange={(e) => {
            // a Rule table writes its whole table per keystroke (VersionEditor's recordTable)
            const rows = rates.filter((r) => r.room_type !== "FAM")
            if (e.target.value) rows.push(rate("FAM", "", e.target.value))
            history.record("period_rates", rows, "Rule table: Room prices")
          }}
        />
      </label>
      <label className="block">
        Child order
        <select
          className="ml-2 rounded border px-2 py-1"
          value={String(state.settings.child_ordering)}
          onChange={(e) => history.setting("Child order", { child_ordering: e.target.value }, "setting:child_ordering")}
        >
          <option value="OLDEST_FIRST">oldest</option>
          <option value="YOUNGEST_FIRST">youngest</option>
        </select>
      </label>
      <output data-testid="rates" className="block">
        {rates.map((r) => `${r.room_type}:${r.period_code || "*"}:${r.value}`).join(",")}
      </output>
      <output data-testid="size" className="block">
        {history.size}
      </output>
      {/* the matrix's active cell: where the toast puts the focus back when it goes while holding it */}
      <div role="gridcell" tabIndex={-1} ref={cell} aria-label="Active cell" className="inline-block rounded border px-2 py-1">
        70
      </div>
      <UndoToastView toast={toast.toast} onUndo={() => log("toast", toast.undo())} onDismiss={toast.dismiss} onHold={toast.hold} onFocusBack={() => cell.current?.focus()} />
    </main>
  )
}

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <Harness />
  </StrictMode>,
)
