// Residents-only markets (O-8, audit 2G-2, ADR-070; lib/residency.ts): what the booking engine's checkout and the
// Call Center ask before the server decides. Run with `npm run test:unit`.
import { test } from "node:test"
import assert from "node:assert/strict"
import { countryNames, isoCountry, marketCountries, qualifies, residencyProblem } from "../../src/lib/residency.ts"

const NAMES = { TR: "Türkiye", DE: "Germany", GB: "United Kingdom" }

test("a country given as a code or by its name is its ISO code; anything else is none", () => {
  assert.equal(isoCountry("tr", NAMES), "TR")
  assert.equal(isoCountry(" DE ", NAMES), "DE")
  assert.equal(isoCountry("Türkiye", NAMES), "TR")
  assert.equal(isoCountry("united kingdom", NAMES), "GB")
  // a CRM profile's nationality defaults to "Indian": never a country
  for (const odd of ["Indian", "Turkish", "", null, undefined, "T", "TUR"]) assert.equal(isoCountry(odd, NAMES), null, String(odd))
})

test("a market's countries come from its list, upper case and sorted", () => {
  assert.deepEqual(marketCountries("tr, cy"), ["CY", "TR"])
  assert.deepEqual(marketCountries(""), [])
  assert.deepEqual(marketCountries(undefined), [])
})

test("residence or nationality among the market's countries qualifies", () => {
  assert.equal(qualifies(["TR"], "TR", null), true)
  assert.equal(qualifies(["TR"], "de", "tr"), true)
  assert.equal(qualifies(["TR"], "DE", "GB"), false)
  assert.equal(qualifies(["TR"], "", ""), false)
})

test("checkout asks for the country of residence, and says when the guest does not qualify", () => {
  const tr = { countries: ["TR"] }
  assert.equal(residencyProblem(null, "", ""), null)                  // not a residents-only market: optional
  assert.equal(residencyProblem(undefined, "DE", ""), null)
  assert.equal(residencyProblem(tr, "", ""), "required")
  assert.equal(residencyProblem(tr, "", "TR"), "required")            // the residence itself is still asked
  assert.equal(residencyProblem(tr, "DE", ""), "not_eligible")
  assert.equal(residencyProblem(tr, "DE", "TR"), null)                // a Turkish national living abroad
  assert.equal(residencyProblem(tr, "TR", ""), null)
})

test("the market's countries are named in the guest's language", () => {
  const display = (code: string) => ({ TR: "Türkei", CY: "Zypern" })[code]
  assert.equal(countryNames(["TR"], display), "Türkei")
  assert.equal(countryNames(["CY", "TR"], display), "Zypern, Türkei")
  assert.equal(countryNames(["XX"], display), "XX")                     // no name: the code
})
