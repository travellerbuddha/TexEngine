// Keyboard shortcut matching that works on every supported layout (en, tr, de, ru, ro, pl).
// Pure, no imports; unit tested with `node --test` (tests/unit/keys.test.ts).

/**
 * The letter (a–z) a Ctrl/Cmd shortcut means for this key event, or null.
 *
 * `e.key` when it is a Latin letter, so a Latin layout keeps its own letters (AZERTY's Ctrl+A is
 * the key labelled A, not the one at the QWERTY A position). On a non-Latin layout `e.key` is
 * another script (Russian: "ф" at the A key), so the physical key (`e.code` "KeyA") decides, as
 * browsers and desktop apps do.
 *
 * Every Ctrl/Cmd+letter shortcut (select all, fill right/down, copy, paste, undo, …) must use
 * this instead of comparing `e.key`, which misses them on the Russian layout.
 */
export function shortcutLetter(e: { key: string; code?: string }): string | null {
  if (/^[a-z]$/i.test(e.key)) return e.key.toLowerCase()
  // Turkish ı and İ are the I key, on Turkish-Q and on Turkish-F (where it sits at the QWERTY R / S position)
  if (e.key === "ı" || e.key === "İ") return "i"
  const m = /^Key([A-Z])$/.exec(e.code ?? "")
  const own = m ? m[1].toLowerCase() : null
  // a letter with a diacritic (ü, ç, ğ, å …) is its base letter's key only where it is that key (Mac ⌥C types ç on
  // the C key); elsewhere a key of its own, never another letter's: on Turkish-F ü sits at the QWERTY G position
  // (LO-49). Letters without a base letter (œ, ø, ß) and other scripts fall back to the physical key, as before
  const base = [...e.key].length === 1 ? e.key.normalize("NFD")[0].toLowerCase() : ""
  if (base !== e.key.toLowerCase() && /^[a-z]$/.test(base)) return base === own ? base : null
  return own
}

/** The editing shortcuts of the keyboard grids (PRICING_WORKSPACE_UX.md §3.10). */
export type EditShortcut = "undo" | "redo" | "fill_right" | "fill_down"

/**
 * The editing shortcut a key event means, on any layout (via shortcutLetter), or null:
 * Ctrl/Cmd+Z undo, Ctrl/Cmd+Shift+Z and Ctrl/Cmd+Y redo, Ctrl/Cmd+R fill right, Ctrl/Cmd+D fill
 * down. With Alt (AltGr types characters on Windows) it is none. Copy and paste are not here: the
 * browser's clipboard events carry them, on every layout.
 */
export function editShortcut(e: { key: string; code?: string; ctrlKey?: boolean; metaKey?: boolean; shiftKey?: boolean; altKey?: boolean }): EditShortcut | null {
  if (!(e.ctrlKey || e.metaKey) || e.altKey) return null
  const letter = shortcutLetter(e)
  if (letter === "z") return e.shiftKey ? "redo" : "undo"
  if (e.shiftKey) return null
  if (letter === "y") return "redo"
  if (letter === "r") return "fill_right"
  if (letter === "d") return "fill_down"
  return null
}

/**
 * True for the grid shortcuts a cell editor (an input inside a keyboard grid) must keep from the
 * browser: Ctrl/Cmd+R (reload) and Ctrl/Cmd+D (bookmark), on any layout. No fill runs while a
 * cell is being edited; Ctrl/Cmd+Z and Ctrl/Cmd+Y stay the field's own undo and redo.
 */
export function editorSwallowsShortcut(e: { key: string; code?: string; ctrlKey?: boolean; metaKey?: boolean; shiftKey?: boolean; altKey?: boolean }): boolean {
  const which = editShortcut(e)
  return which === "fill_right" || which === "fill_down"
}

type KeyLike = { key: string; code?: string; ctrlKey?: boolean; metaKey?: boolean; shiftKey?: boolean; altKey?: boolean }

/** Ctrl/Cmd+S (save), on any layout (Russian: the key marked S types "ы"). */
export function isSaveShortcut(e: KeyLike): boolean {
  return Boolean((e.ctrlKey || e.metaKey) && !e.altKey && shortcutLetter(e) === "s")
}

/** What a key typed in a grid's cell editor asks for (PRICING_WORKSPACE_UX.md §3.4.1, §3.10): one
 * routing for the matrix, the occupancy ladder and the boards grid, which each carry it out. */
export type EditorKeyAction =
  /** Ctrl/Cmd+R, Ctrl/Cmd+D: kept from the browser (reload, bookmark); no fill while editing */
  | { kind: "swallow" }
  /** Ctrl/Cmd+S: commit the entry and stay on the cell; the version editor then saves what it
   * wrote, so the save never leaves the typed value behind (S16 review) */
  | { kind: "save" }
  /** Escape: drop the entry */
  | { kind: "cancel" }
  /** Alt+Enter: the entry in the advanced rule popover */
  | { kind: "popover" }
  /** Ctrl/Cmd+Enter: the entry into every selected editable cell */
  | { kind: "bulk" }
  /** Enter / Shift+Enter / Tab / Shift+Tab: commit, then move */
  | { kind: "commit"; move: "down" | "up" | "left" | "right" }

export function editorKeyAction(e: KeyLike): EditorKeyAction | null {
  if (editorSwallowsShortcut(e)) return { kind: "swallow" }
  if (isSaveShortcut(e)) return { kind: "save" }
  if (e.key === "Escape") return { kind: "cancel" }
  if (e.key === "Enter" && e.altKey) return { kind: "popover" }
  if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) return { kind: "bulk" }
  if (e.key === "Enter") return { kind: "commit", move: e.shiftKey ? "up" : "down" }
  if (e.key === "Tab") return { kind: "commit", move: e.shiftKey ? "left" : "right" }
  return null
}
