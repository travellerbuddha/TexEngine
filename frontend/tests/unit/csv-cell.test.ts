// A CSV cell is made safe for a spreadsheet (a text starting like a formula gets a leading '), but an
// international phone number is not a formula and is exported as it is (O-33, audit Part 2H-1): the CRM's
// SMS / WhatsApp export gave "'+905321234567". Run with `npm run test:unit` (node --test).
import { test } from "node:test"
import assert from "node:assert/strict"
import { csvCell } from "../../src/tex/lib/csv.ts"

test("an international phone number stays as it is", () => {
  for (const phone of ["+905321234567", "+49 170 1234567", "+1 (800) 555-0100", "+90 532 123 45 67", "+44.20.7946.0958"]) {
    assert.equal(csvCell(phone), phone)
    assert.equal(csvCell(phone, false), phone)
  }
})

test("a text that starts like a formula gets a leading quote, quoted as CSV where it must be", () => {
  assert.equal(csvCell('=HYPERLINK("x")'), `"'=HYPERLINK(""x"")"`)
  assert.equal(csvCell("=1+1"), "'=1+1")
  assert.equal(csvCell("-2+3"), "'-2+3")
  assert.equal(csvCell("@SUM(A1)"), "'@SUM(A1)")
  assert.equal(csvCell("+"), "'+")
  assert.equal(csvCell("\t=1"), "'\t=1")
  assert.equal(csvCell("\r=1"), '"\'\r=1"') // a carriage return is quoted as CSV too
})

test("a phone with anything a formula could use is not taken for a phone", () => {
  for (const text of ["+cmd|' /C calc'!A0", "+49\t=1", "+49 30 1234!A1", "+49 30 1234|x", "+49 30 12a4", "+ 49 30", "+49 30 1234\n"]) {
    assert.ok(csvCell(text).replace(/^"/, "").startsWith("'"), text)
  }
})

test("a number that starts with a digit, text and empty values are untouched; a plain cell is quoted only when it must be", () => {
  assert.equal(csvCell("05321234567"), "05321234567")
  assert.equal(csvCell("Ada"), "Ada")
  assert.equal(csvCell(null), "")
  assert.equal(csvCell(undefined), "")
  assert.equal(csvCell(12.5), "12.5")
  assert.equal(csvCell("a,b"), '"a,b"')
  assert.equal(csvCell('say "hi"'), '"say ""hi"""')
  assert.equal(csvCell("x;y"), '"x;y"')
})

test("a column that is not free text is not guarded", () => {
  assert.equal(csvCell("=1+1", false), "=1+1")
  assert.equal(csvCell("-5", false), "-5")
})
