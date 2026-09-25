// The React binding of the workspace undo history (PRICING_WORKSPACE_UX.md §3.10; slice S9; the
// pure log is history.ts). Every workspace mutation goes through `commit(label, before, after)`
// or `apply(label, edit)`: the tables that changed are recorded (their before and after arrays)
// and written with the editor's setTable. An edit that changes nothing records nothing. Undo puts
// the recorded arrays back; nothing is recomputed and nothing calls the server. The log is cleared
// by Discard and by loading a version (`clear`). The undo/redo buttons, keys and toast are S10's.
import { useCallback, useMemo, useRef, useState } from "react"
import type { EditorState, Tables } from "../lib/tables"
import type { Row, VersionTable } from "../lib/types"
import { createHistory, diffTables } from "./history.ts"

export interface WorkspaceHistory {
  /** Records `before` → `after` (the tables whose arrays differ) and writes the changed tables.
   * Returns false when nothing changed (no entry). */
  commit: (label: string, before: Tables, after: Tables) => boolean
  /** The same, from the tables as they are now (including edits not rendered yet): for
   * answers that arrive later, such as a server adjustment. `edit` must be pure. */
  apply: (label: string, edit: (tables: Tables) => Tables) => boolean
  /** Undo / redo the last entry; the label of the entry, or null when there was none. */
  undo: () => string | null
  redo: () => string | null
  canUndo: boolean
  canRedo: boolean
  /** Entries that can be undone. */
  size: number
  /** Empties the log (Discard, loading another version). */
  clear: () => void
  /** The tables as last written (what `apply` edits). */
  current: () => Tables | undefined
  /** Bumped by every `clear`: an answer that arrives later (a server adjustment) is dropped when
   * the version was reloaded or discarded since it was asked for. */
  generation: () => number
}

export function useWorkspaceHistory(state: EditorState | undefined, setTable: (t: VersionTable, rows: Row[]) => void): WorkspaceHistory {
  const log = useMemo(() => createHistory<Tables>(), [])
  // re-render when the log changes (canUndo / canRedo / size)
  const [, setVersion] = useState(0)
  const bump = useCallback(() => setVersion((n) => n + 1), [])
  // the tables as last written: a commit updates it at once, so a second commit in the same
  // event (before React renders) starts from the first one's result
  const latest = useRef<Tables | undefined>(state?.tables)
  const rendered = useRef<Tables | undefined>(state?.tables)
  if (state?.tables !== rendered.current) {
    rendered.current = state?.tables
    latest.current = state?.tables
  }

  const write = useCallback(
    (patch: Partial<Tables>) => {
      const base = latest.current
      if (base) latest.current = { ...base, ...patch }
      for (const k of Object.keys(patch) as VersionTable[]) setTable(k, patch[k] as Row[])
    },
    [setTable],
  )

  const commit = useCallback(
    (label: string, before: Tables, after: Tables) => {
      const d = diffTables(before, after)
      if (!d) return false
      log.commit(label, d.before, d.after)
      write(d.after)
      bump()
      return true
    },
    [log, write, bump],
  )

  const apply = useCallback(
    (label: string, edit: (tables: Tables) => Tables) => {
      const now = latest.current
      if (!now) return false
      return commit(label, now, edit(now))
    },
    [commit],
  )

  const step = useCallback(
    (which: "undo" | "redo") => {
      const now = latest.current
      if (!now) return null
      const s = which === "undo" ? log.undo(now) : log.redo(now)
      if (!s) return null
      const patch = diffTables(now, s.state)
      if (patch) write(patch.after)
      bump()
      return s.label
    },
    [log, write, bump],
  )
  const undo = useCallback(() => step("undo"), [step])
  const redo = useCallback(() => step("redo"), [step])
  const gen = useRef(0)
  const clear = useCallback(() => {
    gen.current += 1
    log.clear()
    bump()
  }, [log, bump])
  const current = useCallback(() => latest.current, [])
  const generation = useCallback(() => gen.current, [])

  return { commit, apply, undo, redo, canUndo: log.canUndo(), canRedo: log.canRedo(), size: log.size(), clear, current, generation }
}
