// Unit tests for shortcutLetter: the letter a Ctrl/Cmd shortcut means on any keyboard layout
// (slice S7 review follow-up). Run with `npm run test:unit`.
import { test } from "node:test"
import assert from "node:assert/strict"
import { shortcutLetter } from "../../src/tex/ui/keys.ts"

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
