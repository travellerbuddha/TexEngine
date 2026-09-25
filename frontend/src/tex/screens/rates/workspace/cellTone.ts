// The tones of a workspace grid cell (PRICING_WORKSPACE_UX.md §3.3.3, §3.18): the classes each
// state draws with, apart from MatrixCell so a unit test can check their contrast in both themes
// (tests/unit/contrast.test.ts, S16 review). Only shades that index.css / tex.css remap for the
// dark theme are used for text and backgrounds: an unmapped shade (amber-950, slate-700, …) keeps
// its light value on the dark theme's backgrounds and becomes unreadable.

export type CellTone = "plain" | "muted" | "override" | "fixed" | "missing" | "resolved" | "error" | "pending"

export const TONE: Record<CellTone, string> = {
  plain: "text-zinc-900",
  muted: "text-zinc-500",
  // period override: amber tint with a corner triangle (the glyph ◆ says it without colour)
  override:
    "bg-amber-50 text-amber-900 before:absolute before:top-0 before:right-0 before:border-t-[7px] before:border-l-[7px] before:border-t-amber-500 before:border-l-transparent before:content-['']",
  fixed: "bg-amber-50 text-amber-900",
  missing: "text-rose-700 outline-1 -outline-offset-2 outline-dashed outline-rose-400",
  resolved: "bg-zinc-50 text-zinc-800",
  error: "text-rose-800 underline decoration-rose-500 decoration-wavy underline-offset-2",
  pending: "text-zinc-600",
}

/** A selected cell of a range (aria-selected, §3.3.3, §3.19): an inset outline of the TEX accent
 * besides the tint, so the range reads without colour alone (the tint alone is about 1.07:1 on
 * white) and survives forced-colors, which drops backgrounds but keeps outlines (in a system
 * colour). */
// outline-solid: the cell's outline-none sets the outline style Tailwind's outline-2 reads
export const SELECTED = "aria-selected:bg-sky-50 aria-selected:outline-2 aria-selected:outline-solid aria-selected:-outline-offset-2 aria-selected:outline-tex-400"
