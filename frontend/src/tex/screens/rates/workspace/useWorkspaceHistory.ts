// The React binding of the workspace undo history (PRICING_WORKSPACE_UX.md §3.10; slices S9, S10; the
// pure log is history.ts). Every workspace mutation goes through `commit(label, before, after)`
// or `apply(label, edit)`: the tables that changed are recorded (their before and after arrays)
// and written with the editor's setTable. An edit that changes nothing records nothing. Undo puts
// the recorded arrays back; nothing is recomputed and nothing calls the server. The log is cleared
// by Discard and by loading a version (`clear`).
//
// S10: the Advanced rule tables and Offers write through `record` (merged per table while the user
// types), so undoing a matrix entry never puts back a table array older than an edit made there.
// `useUndoToast` is the "Applied to N cells · Undo" toast of a bulk operation (10 s, the old
// RateGrid's undo toast): its Undo undoes that entry only while it is still the last one.
//
// S16 review: the version's settings and its selling terms are recorded too (`setting`,
// `selling`), so the workspace's own controls (child ordering, the ROOM-basis extra unit and
// children-fill, the header's selling popover) and the Advanced settings fields are undone like any
// other edit (§3.10: every workspace mutation; the pricing basis, a contract header field, stays
// outside the log).
import { useCallback, useEffect, useMemo, useRef, useState } from "react"
import type { EditorState, SellingForm, Settings, Tables } from "../lib/tables"
import type { Row, VersionTable } from "../lib/types"
import { createHistory, diffTables } from "./history.ts"

/** What the log records: the tables, and the settings and selling terms as two more "tables". */
type Recorded = Tables & { settings?: Settings; selling?: SellingForm }

/** How the log writes the settings and the selling terms back (the editor's state setters). */
export interface HistoryWriters {
  settings?: (settings: Settings) => void
  selling?: (selling: SellingForm) => void
}

export interface WorkspaceHistory {
  /** Records `before` → `after` (the tables whose arrays differ) and writes the changed tables.
   * Returns false when nothing changed (no entry). */
  commit: (label: string, before: Tables, after: Tables) => boolean
  /** A whole table written by an Advanced rule table or Offers (their setTable): recorded like any
   * other edit, one entry per table while the user types (merged within MERGE_WINDOW_MS). */
  record: (table: VersionTable, rows: Row[], label: string) => boolean
  /** The same, from the tables as they are now (including edits not rendered yet): for
   * answers that arrive later, such as a server adjustment. `edit` must be pure. */
  apply: (label: string, edit: (tables: Tables) => Tables) => boolean
  /** Settings changed (merged per `merge` key while the user types, as `record`); false when
   * nothing changed. */
  setting: (label: string, patch: Partial<Settings>, merge?: string) => boolean
  /** The draft's own selling terms changed (likewise). */
  selling: (label: string, patch: Partial<SellingForm>, merge?: string) => boolean
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
  /** Changes with every commit, undo, redo and clear (rendered); `seq()` is the same number, at
   * once (read right after a commit, before React renders). */
  version: number
  seq: () => number
}

export function useWorkspaceHistory(state: EditorState | undefined, setTable: (t: VersionTable, rows: Row[]) => void, writers: HistoryWriters = {}): WorkspaceHistory {
  const log = useMemo(() => createHistory<Recorded>(), [])
  const writersRef = useRef(writers)
  writersRef.current = writers
  // re-render when the log changes (canUndo / canRedo / size)
  const counter = useRef(0)
  const [version, setVersion] = useState(0)
  const bump = useCallback(() => {
    counter.current += 1
    setVersion(counter.current)
  }, [])
  // the tables as last written: a commit updates it at once, so a second commit in the same
  // event (before React renders) starts from the first one's result
  const latest = useRef<Tables | undefined>(state?.tables)
  const rendered = useRef<Tables | undefined>(state?.tables)
  if (state?.tables !== rendered.current) {
    rendered.current = state?.tables
    latest.current = state?.tables
  }
  // the settings and selling terms as last written, likewise
  const extras = useRef<{ settings?: Settings; selling?: SellingForm }>({ settings: state?.settings, selling: state?.selling })
  const renderedExtras = useRef({ settings: state?.settings, selling: state?.selling })
  if (state?.settings !== renderedExtras.current.settings || state?.selling !== renderedExtras.current.selling) {
    renderedExtras.current = { settings: state?.settings, selling: state?.selling }
    extras.current = { settings: state?.settings, selling: state?.selling }
  }

  const write = useCallback(
    (patch: Partial<Recorded>) => {
      const { settings, selling, ...tables } = patch
      const base = latest.current
      if (base) latest.current = { ...base, ...(tables as Partial<Tables>) }
      for (const k of Object.keys(tables) as VersionTable[]) setTable(k, tables[k] as Row[])
      if (settings) {
        extras.current = { ...extras.current, settings }
        writersRef.current.settings?.(settings)
      }
      if (selling) {
        extras.current = { ...extras.current, selling }
        writersRef.current.selling?.(selling)
      }
    },
    [setTable],
  )
  /** The tables with the settings and selling terms, as the log undoes and redoes them. */
  const recorded = useCallback((): Recorded | undefined => (latest.current ? { ...latest.current, ...extras.current } : undefined), [])

  const commitWith = useCallback(
    (label: string, before: Tables, after: Tables, merge?: string) => {
      const d = diffTables(before, after)
      if (!d) return false
      log.commit(label, d.before, d.after, merge ? { merge, at: Date.now() } : undefined)
      write(d.after)
      bump()
      return true
    },
    [log, write, bump],
  )
  const commit = useCallback((label: string, before: Tables, after: Tables) => commitWith(label, before, after), [commitWith])
  const record = useCallback(
    (table: VersionTable, rows: Row[], label: string) => {
      const now = latest.current
      if (!now) return false
      return commitWith(label, now, { ...now, [table]: rows }, `table:${table}`)
    },
    [commitWith],
  )

  const apply = useCallback(
    (label: string, edit: (tables: Tables) => Tables) => {
      const now = latest.current
      if (!now) return false
      return commit(label, now, edit(now))
    },
    [commit],
  )

  /** A settings or selling patch as one entry (merged per key while the user types). */
  const commitExtra = useCallback(
    <K extends "settings" | "selling">(which: K, label: string, patch: Partial<NonNullable<Recorded[K]>>, merge?: string) => {
      const now = extras.current[which] as Record<string, unknown> | undefined
      if (!now) return false
      if (Object.entries(patch).every(([k, v]) => now[k] === v)) return false
      const next = { ...now, ...patch }
      log.commit(label, { [which]: now } as Partial<Recorded>, { [which]: next } as Partial<Recorded>, merge ? { merge, at: Date.now() } : undefined)
      write({ [which]: next } as Partial<Recorded>)
      bump()
      return true
    },
    [log, write, bump],
  )
  const setting = useCallback((label: string, patch: Partial<Settings>, merge?: string) => commitExtra("settings", label, patch, merge), [commitExtra])
  const selling = useCallback((label: string, patch: Partial<SellingForm>, merge?: string) => commitExtra("selling", label, patch, merge), [commitExtra])

  const step = useCallback(
    (which: "undo" | "redo") => {
      const now = recorded()
      if (!now) return null
      const s = which === "undo" ? log.undo(now) : log.redo(now)
      if (!s) return null
      const patch = diffTables(now, s.state)
      if (patch) write(patch.after)
      bump()
      return s.label
    },
    [log, write, bump, recorded],
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
  const seq = useCallback(() => counter.current, [])

  return { commit, record, apply, setting, selling, undo, redo, canUndo: log.canUndo(), canRedo: log.canRedo(), size: log.size(), clear, current, generation, version, seq }
}

/** How long the undo toast of a bulk operation stays (the old RateGrid's, §1.4). */
export const UNDO_TOAST_MS = 10_000

export interface UndoToastState {
  /** "Applied to 8 cells" */
  message: string
  /** the history's seq right after the bulk entry was committed */
  seq: number
  id: number
}

export interface UndoToast {
  /** the toast on screen, or null (it goes when anything else is committed, undone or redone) */
  toast: UndoToastState | null
  /** Shows the toast for the entry just committed. */
  show: (message: string) => void
  /** Undoes the toast's entry (only while it is the last one); the entry's label, or null. */
  undo: () => string | null
  dismiss: () => void
  /** Holds the countdown while the pointer or the focus is on the toast. */
  hold: (on: boolean) => void
}

/** The "Applied to N cells · Undo" toast (§3.10): visible for UNDO_TOAST_MS, held while hovered
 * or focused, gone as soon as the log changes again. Its Undo restores recorded rows like Ctrl/Cmd+Z;
 * it never computes an inverse. */
export function useUndoToast(history: Pick<WorkspaceHistory, "undo" | "seq" | "version">, ms: number = UNDO_TOAST_MS): UndoToast {
  const [toast, setToast] = useState<UndoToastState | null>(null)
  const [held, setHeld] = useState(false)
  const ids = useRef(0)
  // a toast that goes while hovered or focused (its Undo clicked) never gets its pointerleave or
  // blur: every new toast and every dismissal starts unheld
  const show = useCallback(
    (message: string) => {
      ids.current += 1
      setHeld(false)
      setToast({ message, seq: history.seq(), id: ids.current })
    },
    [history],
  )
  const dismiss = useCallback(() => {
    setHeld(false)
    setToast(null)
  }, [])
  // a new countdown for every toast; none while it is held
  useEffect(() => {
    if (!toast || held) return
    const timer = window.setTimeout(() => setToast((t) => (t?.id === toast.id ? null : t)), ms)
    return () => window.clearTimeout(timer)
  }, [toast, held, ms])
  const live = toast && toast.seq === history.version ? toast : null
  const undo = useCallback(() => {
    if (!toast || toast.seq !== history.seq()) return null
    setHeld(false)
    setToast(null)
    return history.undo()
  }, [toast, history])
  const hold = useCallback((on: boolean) => setHeld(on), [])
  return { toast: live, show, undo, dismiss, hold }
}
