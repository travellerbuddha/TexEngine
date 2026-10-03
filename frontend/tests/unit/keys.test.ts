// Unit tests for shortcutLetter: the letter a Ctrl/Cmd shortcut means on any keyboard layout
// (slice S7 review follow-up). Run with `npm run test:unit`.
import { test } from "node:test"
import assert from "node:assert/strict"
import { editorSwallowsShortcut, editShortcut, shortcutLetter, editorKeyAction, isSaveShortcut } from "../../src/tex/ui/keys.ts"

test("a Latin letter is the letter, in lower case", () => {
  assert.equal(shortcutLetter({ key: "a", code: "KeyA" }), "a")
  assert.equal(shortcutLetter({ key: "A", code: "KeyA" }), "a")
  assert.equal(shortcutLetter({ key: "z", code: "KeyY" }), "z") // German QWERTZ
})

test("a non-Latin layout falls back to the physical key", () => {
  assert.equal(shortcutLetter({ key: "ф", code: "KeyA" }), "a") // Russian ЙЦУКЕН
  assert.equal(shortcutLetter({ key: "Ф", code: "KeyA" }), "a")
  assert.equal(shortcutLetter({ key: "к", code: "KeyR" }), "r")
  assert.equal(shortcutLetter({ key: "ı", code: "KeyI" }), "i") // Turkish dotless i
  assert.equal(shortcutLetter({ key: "Dead", code: "KeyU" }), "u")
})

test("a Latin layout keeps its own letter, not the physical key (AZERTY)", () => {
  assert.equal(shortcutLetter({ key: "q", code: "KeyA" }), "q")
  assert.equal(shortcutLetter({ key: "a", code: "KeyQ" }), "a")
})

test("anything else is not a letter shortcut", () => {
  assert.equal(shortcutLetter({ key: "Enter", code: "Enter" }), null)
  assert.equal(shortcutLetter({ key: "1", code: "Digit1" }), null)
  assert.equal(shortcutLetter({ key: "ф" }), null)
  assert.equal(shortcutLetter({ key: "ф", code: "" }), null)
  assert.equal(shortcutLetter({ key: "ß", code: "Minus" }), null)
})

// ─── editing shortcuts of the keyboard grids (slice S10) ───────────────────

const k = (key: string, mods: { ctrl?: boolean; meta?: boolean; shift?: boolean; alt?: boolean } = {}, code?: string) => ({
  key,
  code: code ?? (/^[a-z]$/i.test(key) ? `Key${key.toUpperCase()}` : ""),
  ctrlKey: Boolean(mods.ctrl),
  metaKey: Boolean(mods.meta),
  shiftKey: Boolean(mods.shift),
  altKey: Boolean(mods.alt),
})

test("undo, redo, fill right and fill down by Ctrl or Cmd, on every layout", () => {
  assert.equal(editShortcut(k("z", { ctrl: true })), "undo")
  assert.equal(editShortcut(k("z", { meta: true })), "undo")
  assert.equal(editShortcut(k("Z", { ctrl: true, shift: true })), "redo")
  assert.equal(editShortcut(k("Z", { meta: true, shift: true })), "redo")
  assert.equal(editShortcut(k("y", { ctrl: true })), "redo")
  assert.equal(editShortcut(k("r", { ctrl: true })), "fill_right")
  assert.equal(editShortcut(k("d", { ctrl: true })), "fill_down")
  // Russian ЙЦУКЕН: the keys marked Z, R, D type я, к, в
  assert.equal(editShortcut(k("я", { ctrl: true }, "KeyZ")), "undo")
  assert.equal(editShortcut(k("Я", { ctrl: true, shift: true }, "KeyZ")), "redo")
  assert.equal(editShortcut(k("к", { ctrl: true }, "KeyR")), "fill_right")
  assert.equal(editShortcut(k("в", { ctrl: true }, "KeyD")), "fill_down")
  // German QWERTZ: Ctrl + the key labelled Z (physical KeyY) is undo, the one labelled Y redo
  assert.equal(editShortcut(k("z", { ctrl: true }, "KeyY")), "undo")
  assert.equal(editShortcut(k("y", { ctrl: true }, "KeyZ")), "redo")
})

test("no editing shortcut without Ctrl/Cmd, with Alt (AltGr), or with Shift on R, D, Y", () => {
  assert.equal(editShortcut(k("z")), null)
  assert.equal(editShortcut(k("r", { shift: true })), null)
  assert.equal(editShortcut(k("z", { ctrl: true, alt: true })), null)
  assert.equal(editShortcut(k("R", { ctrl: true, shift: true })), null)
  assert.equal(editShortcut(k("D", { ctrl: true, shift: true })), null)
  assert.equal(editShortcut(k("Y", { ctrl: true, shift: true })), null)
  assert.equal(editShortcut(k("c", { ctrl: true })), null, "copy and paste are the browser's clipboard events")
  assert.equal(editShortcut(k("v", { ctrl: true })), null)
  assert.equal(editShortcut(k("Enter", { ctrl: true })), null)
})

test("a cell editor keeps Ctrl/Cmd+R and Ctrl/Cmd+D from the browser (reload, bookmark), on every layout; undo stays the field's (S10 review)", () => {
  assert.equal(editorSwallowsShortcut(k("r", { ctrl: true })), true)
  assert.equal(editorSwallowsShortcut(k("r", { meta: true })), true)
  assert.equal(editorSwallowsShortcut(k("d", { ctrl: true })), true)
  assert.equal(editorSwallowsShortcut(k("d", { meta: true })), true)
  assert.equal(editorSwallowsShortcut(k("к", { ctrl: true }, "KeyR")), true)
  assert.equal(editorSwallowsShortcut(k("в", { ctrl: true }, "KeyD")), true)
  // the field's own undo and redo, the clipboard and plain typing are left alone
  assert.equal(editorSwallowsShortcut(k("z", { ctrl: true })), false)
  assert.equal(editorSwallowsShortcut(k("Z", { ctrl: true, shift: true })), false)
  assert.equal(editorSwallowsShortcut(k("y", { ctrl: true })), false)
  assert.equal(editorSwallowsShortcut(k("c", { ctrl: true })), false)
  assert.equal(editorSwallowsShortcut(k("v", { meta: true })), false)
  assert.equal(editorSwallowsShortcut(k("r")), false)
  assert.equal(editorSwallowsShortcut(k("d", { shift: true })), false)
  // Ctrl+Shift+R (hard reload) and AltGr are not the grid's shortcuts
  assert.equal(editorSwallowsShortcut(k("R", { ctrl: true, shift: true })), false)
  assert.equal(editorSwallowsShortcut(k("d", { ctrl: true, alt: true })), false)
})

test("Ctrl/Cmd+S is the save shortcut on every layout; a cell editor routes it to commit-then-save (S16 review)", () => {
  assert.equal(isSaveShortcut(k("s", { ctrl: true })), true)
  assert.equal(isSaveShortcut(k("s", { meta: true })), true)
  assert.equal(isSaveShortcut(k("ы", { ctrl: true }, "KeyS")), true, "Russian: the key marked S")
  assert.equal(isSaveShortcut(k("s")), false)
  assert.equal(isSaveShortcut(k("s", { ctrl: true, alt: true })), false, "AltGr types characters")
  assert.deepEqual(editorKeyAction(k("s", { ctrl: true })), { kind: "save" })
  assert.deepEqual(editorKeyAction(k("ы", { meta: true }, "KeyS")), { kind: "save" })
})

test("a cell editor's keys: one routing for the matrix, the ladder and the boards grid (S16 review)", () => {
  assert.deepEqual(editorKeyAction(k("r", { ctrl: true })), { kind: "swallow" })
  assert.deepEqual(editorKeyAction(k("d", { meta: true })), { kind: "swallow" })
  assert.deepEqual(editorKeyAction(k("Escape")), { kind: "cancel" })
  assert.deepEqual(editorKeyAction(k("Enter", { alt: true })), { kind: "popover" })
  assert.deepEqual(editorKeyAction(k("Enter", { ctrl: true })), { kind: "bulk" })
  assert.deepEqual(editorKeyAction(k("Enter", { meta: true })), { kind: "bulk" })
  assert.deepEqual(editorKeyAction(k("Enter")), { kind: "commit", move: "down" })
  assert.deepEqual(editorKeyAction(k("Enter", { shift: true })), { kind: "commit", move: "up" })
  assert.deepEqual(editorKeyAction(k("Tab")), { kind: "commit", move: "right" })
  assert.deepEqual(editorKeyAction(k("Tab", { shift: true })), { kind: "commit", move: "left" })
  // typing, the field's own undo and the clipboard stay the field's
  for (const e of [k("a"), k("z", { ctrl: true }), k("c", { ctrl: true }), k("v", { meta: true }), k("ArrowLeft")]) assert.equal(editorKeyAction(e), null)
})

test("Turkish letters (LO-49): ı and İ are the I key on both Turkish layouts; ü and the others no other letter's key", () => {
  // Turkish-F: the key printed ı / I sits where QWERTY has R, İ / i where it has S, ü where it has G
  assert.equal(shortcutLetter({ key: "ı", code: "KeyR" }), "i")
  assert.equal(shortcutLetter({ key: "İ", code: "KeyS" }), "i")
  assert.equal(shortcutLetter({ key: "İ", code: "Quote" }), "i") // Turkish-Q
  for (const [key, code] of [["ü", "KeyG"], ["ö", "KeyX"], ["ç", "KeyB"], ["ş", "Semicolon"], ["ğ", "KeyE"], ["Ü", "KeyG"]])
    assert.equal(shortcutLetter({ key, code }), null, `${key} at ${code}`)
  // German QWERTZ keeps its ü key out of the letters, as before
  assert.equal(shortcutLetter({ key: "ü", code: "BracketLeft" }), null)
})
