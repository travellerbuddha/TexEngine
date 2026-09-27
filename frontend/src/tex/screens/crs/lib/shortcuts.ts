// The Call Center's global keyboard shortcuts (R-25; O-32). Pure, no React; unit tested with
// `node --test` (tests/unit/callcenter-shortcuts.test.ts).
//
// Alt+letter shortcuts collide with typing: on a Mac, Option alone also types characters (Turkish-Q:
// ⌥Q is "@", US: ⌥Q is "œ", ⌥N starts a tilde). So on a Mac ⌃⌥+letter is always the shortcut, and
// ⌥ alone is one except in a field where it types something of its own (a dead key, or a character
// other than the key's letter). Elsewhere Alt without Ctrl, Meta or AltGr is the shortcut, in fields
// too (Ctrl+Alt is AltGr on Windows and types). The letter follows ui/keys.ts shortcutLetter.
import { shortcutLetter } from "../../../ui/keys.ts"

export type ShortcutPlatform = "mac" | "windows" | "linux"

export type CallCenterAction =
  | "book"
  | "new_call"
  | "caller"
  | "search"
  | "results"
  | "requote"
  | "copy"
  | "guest"
  | "payment"
  | "notes"
  | "help"

/** What the page needs of a keydown. `altGraph` is getModifierState("AltGraph"); `editable` whether
 * the target takes typed text (input, textarea, select, contenteditable). */
export interface ShortcutEvent {
  key: string
  code: string
  altKey: boolean
  ctrlKey: boolean
  metaKey: boolean
  altGraph: boolean
  editable: boolean
}

/** Alt (Mac: ⌃⌥ or ⌥) + letter. */
export const LETTER_ACTIONS: Record<string, CallCenterAction> = {
  n: "new_call",
  c: "caller",
  s: "search",
  r: "results",
  u: "requote",
  q: "copy",
  g: "guest",
  p: "payment",
  m: "notes",
}

export function shortcutPlatform(navigatorPlatform: string | null | undefined): ShortcutPlatform {
  const p = navigatorPlatform ?? ""
  if (/Mac|iPhone|iPad/.test(p)) return "mac"
  return /^Win/.test(p) ? "windows" : "linux"
}

/** The key types something of its own: a dead key, or one character other than its key's letter. */
function typesCharacter(ev: ShortcutEvent): boolean {
  if (ev.key === "Dead") return true
  const own = /^Key([A-Z])$/.exec(ev.code)?.[1].toLowerCase()
  return [...ev.key].length === 1 && ev.key.toLowerCase() !== own
}

/** The Call Center action a keydown asks for, or null (the key is left to the page / field). */
export function callCenterShortcut(ev: ShortcutEvent, platform: ShortcutPlatform): CallCenterAction | null {
  if ((ev.ctrlKey || ev.metaKey) && !ev.altKey && ev.key === "Enter") return "book"
  if (ev.altKey) {
    const action = LETTER_ACTIONS[shortcutLetter(ev) ?? ""] ?? null
    if (!action) return null
    if (platform === "mac") {
      if (ev.metaKey) return null
      if (ev.ctrlKey) return action
      return ev.editable && typesCharacter(ev) ? null : action
    }
    return ev.ctrlKey || ev.metaKey || ev.altGraph ? null : action
  }
  if (ev.key === "?" && !ev.editable && !ev.ctrlKey && !ev.metaKey) return "help"
  return null
}
