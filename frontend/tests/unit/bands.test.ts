// Unit tests for band labels and band codes (PRICING_WORKSPACE_UX.md §3.8, D13, §5.1).
// Run with `npm run test:unit` (node --test).
import { test } from "node:test"
import assert from "node:assert/strict"
import { bandLabel, displayBandCodes, generatedLabel, nextBandCode, renameBandCode, type BandLike } from "../../src/tex/screens/rates/workspace/bands.ts"

type R = { _key: string; [k: string]: string | number | null }
const r = (key: string, fields: Record<string, string | number | null>): R => ({ _key: key, ...fields })

// the generated label as S11 renders it (en), from the i18n descriptor
const gen = (b: BandLike) => {
  const g = generatedLabel(b)
  return `${g.key === "rates.bands.label_infant" ? "Infant" : "Child"} ${g.params.from}–${g.params.to}`
}

const BANDS: BandLike[] = [
  { band_code: "INF", label: "Infant 0–2.99", from_age: "0", to_age: "2.99", is_infant: 1 },
  { band_code: "CHA", label: "", from_age: "3", to_age: "6.99", is_infant: 0 },
  { band_code: "CHB", label: "CHB", from_age: "7.00", to_age: "11.99", is_infant: 0 },
]
const labelOf = (_code: string, b: BandLike) => bandLabel(b, gen)

test("bandLabel: the saved label; the generated one when the label is blank or equals the code", () => {
  assert.equal(bandLabel(BANDS[0], gen), "Infant 0–2.99")
  assert.equal(bandLabel(BANDS[1], gen), "Child 3–6.99")
  assert.equal(bandLabel(BANDS[2], gen), "Child 7–11.99", "label == code is the server fallback")
  assert.equal(bandLabel({ code: "chb", label: " CHB " }, () => "gen"), "gen", "compared trimmed, ignoring case")
  assert.equal(bandLabel({ code: "CHB", label: null }, () => "gen"), "gen")
})

test("generatedLabel: an i18n key and the ages as typed strings (no maths)", () => {
  assert.deepEqual(generatedLabel(BANDS[0]), { key: "rates.bands.label_infant", params: { from: "0", to: "2.99" } })
  assert.deepEqual(generatedLabel(BANDS[2]), { key: "rates.bands.label_child", params: { from: "7", to: "11.99" } })
  assert.deepEqual(generatedLabel({ band_code: "X", from_age: "", to_age: "5", is_infant: false }), {
    key: "rates.bands.label_child",
    params: { from: "", to: "5" },
  })
})

test("displayBandCodes replaces [CODE] with [label] for known bands", () => {
  assert.equal(displayBandCodes("Child 1 [CHB] @2A+2C × 0.5", BANDS, { labelOf }), "Child 1 [Child 7–11.99] @2A+2C × 0.5")
  assert.equal(displayBandCodes("STD 2A+2C [CHB]: no occupancy rule", BANDS, { labelOf }), "STD 2A+2C [Child 7–11.99]: no occupancy rule")
  assert.equal(displayBandCodes("Child 2 [INF] @*A+2C", BANDS, { labelOf }), "Child 2 [Infant 0–2.99] @*A+2C")
})

test("displayBandCodes with codes replaces whole tokens of those codes", () => {
  assert.equal(
    displayBandCodes("age bands CHA and CHB overlap at 36 months", BANDS, { labelOf, codes: ["CHA", "CHB"] }),
    "age bands Child 3–6.99 and Child 7–11.99 overlap at 36 months",
  )
  // without codes the bare tokens stay (only the bracket rule applies)
  assert.equal(displayBandCodes("age bands CHA and CHB overlap", BANDS, { labelOf }), "age bands CHA and CHB overlap")
  // only the codes given are replaced
  assert.equal(displayBandCodes("CHA, CHB", BANDS, { labelOf, codes: ["CHB"] }), "CHA, Child 7–11.99")
})

test("displayBandCodes leaves substrings and unknown codes untouched", () => {
  assert.equal(displayBandCodes("CHBX and XCHB and CHB_1 and 1CHB", BANDS, { labelOf, codes: ["CHB"] }), "CHBX and XCHB and CHB_1 and 1CHB")
  assert.equal(displayBandCodes("rule names unknown band [ZZZ]", BANDS, { labelOf, codes: ["ZZZ"] }), "rule names unknown band [ZZZ]")
  assert.equal(displayBandCodes("[CHBX] [chb]", BANDS, { labelOf }), "[CHBX] [chb]", "codes are matched as the server prints them")
  assert.equal(displayBandCodes("", BANDS, { labelOf, codes: ["CHB"] }), "")
})

test("displayBandCodes is idempotent", () => {
  const texts = ["Child 1 [CHB] @2A+2C × 0.5", "STD 2A+2C [CHB]: no occupancy rule", "age bands CHA and CHB overlap at 36 months", "CHBX [ZZZ]"]
  for (const text of texts) {
    const once = displayBandCodes(text, BANDS, { labelOf, codes: ["CHA", "CHB"] })
    assert.equal(displayBandCodes(once, BANDS, { labelOf, codes: ["CHA", "CHB"] }), once, text)
  }
})

test("displayBandCodes escapes codes that contain regex characters", () => {
  const bands: BandLike[] = [{ band_code: "C.1", label: "Kid" }]
  assert.equal(displayBandCodes("[C.1] and C.1 but not CX1", bands, { labelOf: () => "Kid", codes: ["C.1"] }), "[Kid] and Kid but not CX1")
})

test("nextBandCode: INF, CHA, CHB, … skipping codes in use by bands or rules", () => {
  const empty = { age_bands: [] as R[], occupancy_rules: [] as R[] }
  assert.equal(nextBandCode(empty), "INF")
  const one = { age_bands: [r("a", { band_code: "INF" })], occupancy_rules: [] as R[] }
  assert.equal(nextBandCode(one), "CHA")
  const two = { age_bands: [r("a", { band_code: "inf" }), r("b", { band_code: "CHA" })], occupancy_rules: [] as R[] }
  assert.equal(nextBandCode(two), "CHB")
  // an orphan rule still naming CHB keeps the code from being reused
  const orphan = { age_bands: [r("a", { band_code: "INF" }), r("b", { band_code: "CHA" })], occupancy_rules: [r("o", { age_band: "CHB" })] }
  assert.equal(nextBandCode(orphan), "CHC")
  assert.equal(nextBandCode(empty, { infant: false }), "CHA", "a non-infant first band starts at CHA")
  const full = { age_bands: ["INF", ..."ABCDEFGHIJKLMNOPQRSTUVWXYZ".split("").map((c) => `CH${c}`)].map((c, i) => r(`k${i}`, { band_code: c })), occupancy_rules: [] as R[] }
  assert.equal(nextBandCode(full), "CH27")
})

test("renameBandCode rewrites the band and every occupancy rule naming it", () => {
  const tables = {
    age_bands: [r("a", { band_code: "CHA", label: "Child 3–6.99" }), r("b", { band_code: "CHB", label: "" })],
    occupancy_rules: [
      r("o1", { target: "CHILD", age_band: "CHB", op: "MULTIPLY", value: "0.5" }),
      r("o2", { target: "CHILD", age_band: "cha", op: "MULTIPLY", value: "0.25" }),
      r("o3", { target: "CHILD", age_band: "CHB", combination: "2+2", position: 1, op: "MULTIPLY", value: "0.5" }),
    ],
  }
  const out = renameBandCode(tables, "CHB", "kid")
  assert.ok("tables" in out)
  assert.deepEqual(
    out.tables.age_bands.map((b) => b.band_code),
    ["CHA", "KID"],
  )
  assert.deepEqual(
    out.tables.occupancy_rules.map((o) => o.age_band),
    ["KID", "cha", "KID"],
  )
  assert.equal(out.counts.rules, 2)
  assert.equal(out.tables.age_bands[1]._key, "b", "row keys stay stable")
  assert.equal(tables.age_bands[1].band_code, "CHB", "input unchanged")
})

test("renameBandCode refuses a code in use, a blank code and an unknown band", () => {
  const tables = { age_bands: [r("a", { band_code: "CHA" }), r("b", { band_code: "CHB" })], occupancy_rules: [] as R[] }
  assert.deepEqual(renameBandCode(tables, "CHB", "cha"), { error: "DUPLICATE_CODE" })
  assert.deepEqual(renameBandCode(tables, "CHB", "  "), { error: "BLANK_CODE" })
  assert.deepEqual(renameBandCode(tables, "ZZZ", "NEW"), { error: "UNKNOWN_BAND" })
  const same = renameBandCode(tables, "CHB", "chb")
  assert.ok("tables" in same)
  assert.equal(same.tables, tables, "renaming to the same code changes nothing")
})
