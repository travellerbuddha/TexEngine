// The Pricing Workspace undo history (PRICING_WORKSPACE_UX.md §3.10): a client-side linear command
// log. Every workspace mutation is recorded as the before and after arrays of the tables it
// changed; undo puts the recorded "before" arrays back and redo the "after" ones. Nothing is ever
// inverted or recomputed (restoring "no rule" restores the absence of the row, never a 0), and
// nothing calls the server. Pure and framework-free: the React binding (useWorkspaceHistory) is
// built on it in S9. No runtime imports.
import type { Tables } from "../lib/tables.ts"

export const HISTORY_CAP = 100

export interface HistoryEntry<T extends object = Tables> {
  label: string
  before: Partial<T>
  after: Partial<T>
}

export interface HistoryStep<T extends object = Tables> {
  /** The state to show: the current state with the entry's recorded tables put back. */
  state: T
  /** The label of the entry that was undone or redone (for the toast / live region). */
  label: string
}

export interface History<T extends object = Tables> {
  /** Records one mutation: the affected tables before and after it. Clears the redo stack. */
  commit(label: string, before: Partial<T>, after: Partial<T>): void
  /** The current state with the last entry's "before" tables, or null when there is nothing to undo. */
  undo(current: T): HistoryStep<T> | null
  /** The current state with the next entry's "after" tables, or null when there is nothing to redo. */
  redo(current: T): HistoryStep<T> | null
  canUndo(): boolean
  canRedo(): boolean
  /** Number of entries that can be undone. */
  size(): number
  /** Empties the log (Discard, loading another version). */
  clear(): void
}

/** A linear undo log that keeps at most `cap` entries (the oldest is dropped). It survives Save:
 * undoing after a save makes the draft dirty again. */
export function createHistory<T extends object = Tables>(cap: number = HISTORY_CAP): History<T> {
  const limit = Math.max(1, Math.trunc(cap))
  let done: HistoryEntry<T>[] = []
  let undone: HistoryEntry<T>[] = []
  return {
    commit(label, before, after) {
      done = [...done, { label, before, after }]
      if (done.length > limit) done = done.slice(done.length - limit)
      undone = []
    },
    undo(current) {
      const entry = done.at(-1)
      if (!entry) return null
      done = done.slice(0, -1)
      undone = [...undone, entry]
      return { state: { ...current, ...entry.before }, label: entry.label }
    },
    redo(current) {
      const entry = undone.at(-1)
      if (!entry) return null
      undone = undone.slice(0, -1)
      done = [...done, entry]
      return { state: { ...current, ...entry.after }, label: entry.label }
    },
    canUndo: () => done.length > 0,
    canRedo: () => undone.length > 0,
    size: () => done.length,
    clear() {
      done = []
      undone = []
    },
  }
}

/** The tables whose arrays differ between two states (by reference: every workspace function
 * returns the same array for a table it did not change), as the before/after patch of a commit;
 * null when nothing changed, so an unchanged edit records no entry. */
export function diffTables<T extends object>(before: T, after: T): { before: Partial<T>; after: Partial<T> } | null {
  const b: Partial<T> = {}
  const a: Partial<T> = {}
  let changed = false
  for (const k of Object.keys(after) as (keyof T)[]) {
    if (before[k] === after[k]) continue
    b[k] = before[k]
    a[k] = after[k]
    changed = true
  }
  return changed ? { before: b, after: a } : null
}
