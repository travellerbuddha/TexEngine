// Workspace input that is not in the version yet, kept above the section switch (S16 review;
// PRICING_WORKSPACE_UX.md §3.4.1 "an invalid entry is never lost"): the grids' error drafts and an
// open combination builder lived in component state, so switching to Commercial rules, following
// an issue to another section or collapsing Occupancy dropped them without a word. They now live
// in a store the version editor owns (one per loaded version: Discard and loading another version
// start a new one), and a grid or builder mounted again takes them back. The editor also asks the
// store (and the page's open cell editors) before the tab closes.
export type KeptStore = Map<string, unknown>

// The store's context and useKeptState are in useKeptState.ts (React); this module stays pure.

/** Keys of the store (kept here so a reader of the store knows what each one holds). */
export const KEPT = {
  /** a grid's error drafts: Record<cell key, draft> (the ladder's per rooms scope) */
  drafts: (grid: "matrix" | "ladder" | "boards", scope = "") => `${grid}.drafts:${scope}`,
  /** the open combination builder (CombinationCards' `open`), and its draft and "More" state */
  comboOpen: "combos.open",
  comboDraft: "combos.builder",
  comboMore: "combos.builder.more",
} as const

/** Whether the store holds input the user typed that is not in the version: an error draft in a
 * grid, or an open combination builder. */
export function keptInput(store: KeptStore | null | undefined): boolean {
  if (!store) return false
  for (const [key, value] of store) {
    if (key === KEPT.comboOpen && value) return true
    if (/^(matrix|ladder|boards)\.drafts:/.test(key) && value && typeof value === "object" && Object.keys(value).length) return true
  }
  return false
}
