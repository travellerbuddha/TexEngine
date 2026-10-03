// LO-42 (a) (Part 2K-6): two texts of the rates screens said what the engine does not do. A markup's priority
// "only breaks ties between rules with exactly the same scope": it never said the higher one wins, that it also
// orders stacking rules, nor that an equal one in the same scope is refused (G-53; pricing/markup.py resolve). A
// promotion's kind "Member discount" read as members only, but a kind is only a label (the engine never reads
// it; member_only is refused, G-57). Run with `npm run test:unit`.
import { test } from "node:test"
import assert from "node:assert/strict"
import { readFileSync } from "node:fs"

const LANGS = ["en", "tr", "de", "ru", "ro", "pl"]
const catalog = (lang: string): Record<string, string> =>
  JSON.parse(readFileSync(new URL(`../../src/tex/i18n/locales/rates/${lang}.json`, import.meta.url), "utf8"))

test("a markup's priority: the higher wins in one scope, stacking rules apply lowest first, an equal one is refused", () => {
  const help = catalog("en")["rates.h.markup_priority"]
  assert.match(help, /higher priority wins/)
  assert.match(help, /lowest first/)
  assert.match(help, /cannot both be live/)
})

test("a promotion's kind is a label: Member never reads as members only", () => {
  const en = catalog("en")
  assert.match(en["rates.h.promo_kind"] ?? "", /never limits who/)
  assert.match(en["rates.promo_kind.MEMBER"], /label only/)
})

test("both texts are in the six catalogs, translated", () => {
  const en = catalog("en")
  for (const lang of LANGS.slice(1)) {
    const c = catalog(lang)
    for (const key of ["rates.h.markup_priority", "rates.h.promo_kind", "rates.promo_kind.MEMBER"]) {
      assert.ok(c[key], `${lang} ${key}`)
      assert.notEqual(c[key], en[key], `${lang} ${key} is translated`)
    }
  }
})
