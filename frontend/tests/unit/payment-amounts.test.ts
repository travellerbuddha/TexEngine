// LO-45 (Part 2K-6): the payments screen's amount helpers in every currency's own decimals (VND 0, EUR 2, KWD 3);
// `minusAmount` had no test, and the bank-transfer dialog assumed two decimals. Run with `npm run test:unit`.
import { test } from "node:test"
import assert from "node:assert/strict"
import { isPositiveAmount, minusAmount } from "../../src/tex/screens/payments/amounts.ts"

test("minusAmount subtracts exactly, in two decimals by default", () => {
  assert.equal(minusAmount("192.60", "187.6"), "5.00")
  assert.equal(minusAmount("100", "100.00"), "0.00")
  assert.equal(minusAmount("10.5", "12"), "-1.50")
  assert.equal(minusAmount("0.1", "0.2"), "-0.10")
})

test("minusAmount in a currency without decimals (VND) and with three (KWD)", () => {
  assert.equal(minusAmount("500000", "499000", 0), "1000")
  assert.equal(minusAmount("499000", "500000", 0), "-1000")
  assert.equal(minusAmount("12.345", "2.3", 3), "10.045")
  assert.equal(minusAmount("1", "1.001", 3), "-0.001")
})

test("isPositiveAmount takes the currency's decimals: none for VND, three for KWD", () => {
  assert.equal(isPositiveAmount("500000", 0), true)
  assert.equal(isPositiveAmount("500000.5", 0), false)
  assert.equal(isPositiveAmount("12.345", 3), true)
  assert.equal(isPositiveAmount("12.3456", 3), false)
  assert.equal(isPositiveAmount("12.34"), true)
  assert.equal(isPositiveAmount("12.345"), false)
  assert.equal(isPositiveAmount("0", 0), false)
})
