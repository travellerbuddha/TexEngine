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
  const m = /^Key([A-Z])$/.exec(e.code ?? "")
  return m ? m[1].toLowerCase() : null
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
