// A promotion code typed in the CRS is keyed as the server keys it (O-31, `promotions.code_key`):
// the Turkish dotted İ and dotless ı are I, Ş, Ğ, Ü, Ö, Ç are S, G, U, O, C (C-12), other letters are kept.
// Run with `npm run test:unit` (node --test).
import { test } from "node:test"
import assert from "node:assert/strict"
import { normalisePromoCode } from "../../src/tex/screens/crs/lib/promoCode.ts"

test("a Turkish dotted or dotless i is I", () => {
  for (const typed of ["wİnter", "WİNTER", "winter", "wınter", "wi̇nter", " win ter "]) assert.equal(normalisePromoCode(typed), "WINTER")
})

test("letters of any alphabet, digits, _ and - are kept; anything else goes", () => {
  assert.equal(normalisePromoCode("şeker-24"), "SEKER-24")
  assert.equal(normalisePromoCode("dağ_üçgöz"), "DAG_UCGOZ")
  assert.equal(normalisePromoCode("año-été"), "AÑO-ÉTÉ")
  assert.equal(normalisePromoCode("yaz!%24"), "YAZ24")
  assert.equal(normalisePromoCode(normalisePromoCode("wİnter")), "WINTER") // idempotent
})

test("stacked dots above an I are all dropped, and it is idempotent (2D-1 0d)", () => {
  for (const typed of ["İ\u0307\u0307i", "i\u0307\u0307\u0307", "ı\u0307", "wİ\u0307nter"]) {
    const key = normalisePromoCode(typed)
    assert.equal(normalisePromoCode(key), key)
  }
  assert.equal(normalisePromoCode("İ\u0307\u0307i"), "II")
})

test("the Turkish letters are their Latin base, as the server keys them (C-12)", () => {
  const cases: [string, string][] = [["ŞĞÜÖÇ", "SGUOC"], ["şğüöç", "SGUOC"], ["çağ", "CAG"], ["c\u0327ag\u0306", "CAG"],
    ["u\u0308c\u0327go\u0308z", "UCGOZ"], ["S\u0327\u0323", "\u1E62"], ["kış-24", "KIS-24"], ["bär", "BÄR"]]
  for (const [typed, key] of cases) {
    assert.equal(normalisePromoCode(typed), key, typed)
    assert.equal(normalisePromoCode(key), key, `${typed} idempotent`)
  }
})

test("the promotion editor shows the key as typed, its spaces and signs kept: the server keeps them (§6M, batch 2P)", async () => {
  const { promoCodeKey } = await import("../../src/tex/screens/crs/lib/promoCode.ts")
  const cases: [string, string][] = [["şeker 24", "SEKER 24"], ["wİnter!", "WINTER!"], ["dağ_üçgöz", "DAG_UCGOZ"], ["año-été", "AÑO-ÉTÉ"],
    ["yaz ", "YAZ "]]
  for (const [typed, key] of cases) {
    assert.equal(promoCodeKey(typed), key, typed)
    assert.equal(promoCodeKey(key), key, `${typed} idempotent`)
    // the CRS input is that key with anything but letters, digits, "_" and "-" left out
    assert.equal(normalisePromoCode(typed), key.replace(/[^\p{Lu}0-9_-]/gu, ""), `${typed} CRS`)
  }
})
