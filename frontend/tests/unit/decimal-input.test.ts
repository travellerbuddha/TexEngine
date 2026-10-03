// 2K-6 review N4: since LO-45 a payments dialog's input takes its currency's decimals. With none (VND, JPY) it
// took "500000." (a point that can never be followed by a digit), which the dialog's check refuses: Save stayed
// off with nothing said. A currency without decimals takes no point. Run with `npm run test:unit`.
import { test } from "node:test"
import assert from "node:assert/strict"
import { decimalPattern } from "../../src/tex/ui/decimal.ts"

test("a currency without decimals takes no point", () => {
  const re = decimalPattern(0)
  assert.ok(re.test("500000"))
  assert.equal(re.test("500000."), false)
  assert.equal(re.test("500000.5"), false)
})

test("with decimals, a point is taken while typing and the fraction is bounded, as before", () => {
  assert.ok(decimalPattern(2).test("12."))
  assert.ok(decimalPattern(2).test("12.34"))
  assert.equal(decimalPattern(2).test("12.345"), false)
  assert.ok(decimalPattern(3).test("12.345"))
  assert.equal(decimalPattern(2).test("-1"), false)
  assert.ok(decimalPattern(2, true).test("-1.5"))
})
