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
