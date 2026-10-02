// The Call Center's keyboard shortcuts (O-32; crs/lib/shortcuts.ts). On a Mac, Option alone also types
// characters (Turkish-Q: ⌥Q is "@"), so in a field it is a shortcut only when it types nothing of its
// own; ⌃⌥ always is. Elsewhere Alt without Ctrl, Meta or AltGr is. Run with `npm run test:unit`.
import { test } from "node:test"
import assert from "node:assert/strict"
import { callCenterShortcut, shortcutPlatform, type ShortcutEvent } from "../../src/tex/screens/crs/lib/shortcuts.ts"

const ev = (e: Partial<ShortcutEvent>): ShortcutEvent => ({
  key: "",
  code: "",
  altKey: false,
  ctrlKey: false,
  metaKey: false,
  altGraph: false,
  editable: false,
  ...e,
})

test("mac: Option typing a character in a field is the character", () => {
  assert.equal(callCenterShortcut(ev({ key: "@", code: "KeyQ", altKey: true, editable: true }), "mac"), null)
  assert.equal(callCenterShortcut(ev({ key: "œ", code: "KeyQ", altKey: true, editable: true }), "mac"), null)
})

test("mac: ⌃⌥ + letter is always the shortcut, in a field too", () => {
  assert.equal(callCenterShortcut(ev({ key: "@", code: "KeyQ", altKey: true, ctrlKey: true, editable: true }), "mac"), "copy")
})

test("mac: Option + letter outside a field is the shortcut", () => {
  assert.equal(callCenterShortcut(ev({ key: "œ", code: "KeyQ", altKey: true }), "mac"), "copy")
  assert.equal(callCenterShortcut(ev({ key: "Dead", code: "KeyU", altKey: true }), "mac"), "requote")
})

test("mac: a dead key (Option+N) in a field starts a character", () => {
  assert.equal(callCenterShortcut(ev({ key: "Dead", code: "KeyN", altKey: true, editable: true }), "mac"), null)
})

test("mac: Option + a key typing its own letter stays the shortcut in a field", () => {
  assert.equal(callCenterShortcut(ev({ key: "s", code: "KeyS", altKey: true, editable: true }), "mac"), "search")
})

test("linux / windows: Alt + letter is the shortcut, in a field too", () => {
  assert.equal(callCenterShortcut(ev({ key: "s", code: "KeyS", altKey: true, editable: true }), "linux"), "search")
  assert.equal(callCenterShortcut(ev({ key: "g", code: "KeyG", altKey: true }), "windows"), "guest")
})

test("windows: Ctrl+Alt is AltGr and types (Turkish-Q @)", () => {
  assert.equal(callCenterShortcut(ev({ key: "@", code: "KeyQ", altKey: true, ctrlKey: true, editable: true }), "windows"), null)
})

test("AltGraph types a character: never a shortcut", () => {
  assert.equal(callCenterShortcut(ev({ key: "@", code: "KeyQ", altKey: true, altGraph: true, editable: true }), "linux"), null)
  assert.equal(callCenterShortcut(ev({ key: "€", code: "KeyE", altKey: true, altGraph: true }), "windows"), null)
})

test("Ctrl/⌘+Enter books; with Alt it does not", () => {
  assert.equal(callCenterShortcut(ev({ key: "Enter", code: "Enter", ctrlKey: true, editable: true }), "linux"), "book")
  assert.equal(callCenterShortcut(ev({ key: "Enter", code: "Enter", metaKey: true }), "mac"), "book")
  assert.equal(callCenterShortcut(ev({ key: "Enter", code: "Enter", ctrlKey: true, altKey: true }), "linux"), null)
})

test("? opens the help outside a field only; other keys are no shortcut", () => {
  assert.equal(callCenterShortcut(ev({ key: "?", code: "Slash" }), "linux"), "help")
  assert.equal(callCenterShortcut(ev({ key: "?", code: "Slash", editable: true }), "linux"), null)
  assert.equal(callCenterShortcut(ev({ key: "x", code: "KeyX", altKey: true }), "linux"), null)
  assert.equal(callCenterShortcut(ev({ key: "q", code: "KeyQ" }), "mac"), null)
})

test("the platform comes from navigator.platform", () => {
  assert.equal(shortcutPlatform("MacIntel"), "mac")
  assert.equal(shortcutPlatform("iPhone"), "mac")
  assert.equal(shortcutPlatform("Win32"), "windows")
  assert.equal(shortcutPlatform("Linux x86_64"), "linux")
  assert.equal(shortcutPlatform(""), "linux")
})

test("? opens the help with Ctrl or AltGr too, never with ⌘, never in a field (LO-49)", () => {
  assert.equal(callCenterShortcut(ev({ key: "?", code: "Slash", ctrlKey: true }), "linux"), "help")
  // Windows reports AltGr as Ctrl+Alt: a layout that types ? with it
  assert.equal(callCenterShortcut(ev({ key: "?", code: "Minus", ctrlKey: true, altKey: true, altGraph: true }), "windows"), "help")
  assert.equal(callCenterShortcut(ev({ key: "?", code: "Slash", metaKey: true }), "mac"), null) // the Mac's own Help
  assert.equal(callCenterShortcut(ev({ key: "?", code: "Slash", ctrlKey: true, editable: true }), "linux"), null)
})

test("Turkish-F (LO-49): Alt with the key printed ı or ü runs no other letter's shortcut", () => {
  // ı sits where QWERTY has R (results), ü where it has G (guest)
  assert.equal(callCenterShortcut(ev({ key: "ı", code: "KeyR", altKey: true }), "windows"), null)
  assert.equal(callCenterShortcut(ev({ key: "ü", code: "KeyG", altKey: true }), "windows"), null)
  // the key printed R is still Alt+R
  assert.equal(callCenterShortcut(ev({ key: "r", code: "KeyU", altKey: true }), "windows"), "results")
})
