// A promotion code typed in the CRS is keyed as the server keys it (O-31, `promotions.code_key`):
// the Turkish dotted İ and dotless ı are I, other letters (Ş, Ğ, Ü) are kept. Run with
// `npm run test:unit` (node --test).
import { test } from "node:test"
import assert from "node:assert/strict"
import { normalisePromoCode } from "../../src/tex/screens/crs/lib/promoCode.ts"

test("a Turkish dotted or dotless i is I", () => {
  for (const typed of ["wİnter", "WİNTER", "winter", "wınter", "wi̇nter", " win ter "]) assert.equal(normalisePromoCode(typed), "WINTER")
})

test("letters of any alphabet, digits, _ and - are kept; anything else goes", () => {
  assert.equal(normalisePromoCode("şeker-24"), "ŞEKER-24")
  assert.equal(normalisePromoCode("dağ_üçgöz"), "DAĞ_ÜÇGÖZ")
  assert.equal(normalisePromoCode("yaz!%24"), "YAZ24")
  assert.equal(normalisePromoCode(normalisePromoCode("wİnter")), "WINTER") // idempotent
})
