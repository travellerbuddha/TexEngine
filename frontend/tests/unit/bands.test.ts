// Unit tests for band labels and band codes (PRICING_WORKSPACE_UX.md §3.8, D13, §5.1).
// Run with `npm run test:unit` (node --test).
import { test } from "node:test"
import assert from "node:assert/strict"
import {
  addBand,
  ageMonths,
  bandCoverage,
  bandLabel,
  bandRuleCount,
  bandsFromMatrix,
  customiseBands,
  defaultInfant,
  displayBandCodes,
  effectiveBands,
  generatedLabel,
  monthsToYears,
  nameBands,
  nextBandCode,
  nextBandFrom,
  removeBand,
  renameBandCode,
  unnamedBands,
  updateBand,
  type BandLike,
} from "../../src/tex/screens/rates/workspace/bands.ts"

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

// ─── S11: the child ages drawer and inherited bands (§3.8) ─────────────────

test("ages in years ↔ whole months, integer maths only, as the engine rounds (years_to_months)", () => {
  assert.equal(ageMonths("2.99"), 36)
  assert.equal(ageMonths("3"), 36)
  assert.equal(ageMonths("11.99"), 144)
  assert.equal(ageMonths("2,5"), 30)
  assert.equal(ageMonths("0"), 0)
  assert.equal(ageMonths(7), 84)
  assert.equal(ageMonths("7.000000000"), 84)
  assert.equal(ageMonths(""), null)
  assert.equal(ageMonths("abc"), null)
  assert.equal(monthsToYears(36), "3")
  assert.equal(monthsToYears(35), "2.92")
  assert.equal(monthsToYears(30), "2.5")
  assert.equal(monthsToYears(0), "0")
  for (let m = 0; m <= 216; m++) assert.equal(ageMonths(monthsToYears(m)), m, `round trip ${m}`)
})

test("a new band starts where the previous one ends (2.99 → 3), and a first band from 0 up to 3 is an infant band", () => {
  assert.equal(nextBandFrom("2.99"), "3")
  assert.equal(nextBandFrom("6.99"), "7")
  assert.equal(nextBandFrom("3"), "3")
  assert.equal(nextBandFrom("2.5"), "3")
  assert.equal(nextBandFrom(""), "0")
  assert.equal(defaultInfant(true, "0", "2.99"), true)
  assert.equal(defaultInfant(true, "0", "3"), true)
  assert.equal(defaultInfant(true, "0", "3.5"), false)
  assert.equal(defaultInfant(true, "1", "2"), false)
  assert.equal(defaultInfant(false, "0", "2"), false)
  assert.equal(defaultInfant(true, "0", ""), false)
})

test("inherited bands as served (months) are shown with years and labels, never the code as a label", () => {
  const served = [
    { code: "INF", label: "INF", from_months: 0, to_months: 36, is_infant: true, source: "policy:PP-1/r2/hotel" },
    { code: "CHD", label: "Kids", from_months: 36, to_months: 144, is_infant: false, source: "policy:PP-1/r2/hotel" },
  ]
  const bands = bandsFromMatrix(served)
  assert.deepEqual(
    bands.map((b) => [b.code, b.label, b.from_age, b.to_age, b.is_infant, b.source]),
    [
      ["INF", "INF", "0", "3", 1, "policy:PP-1/r2/hotel"],
      ["CHD", "Kids", "3", "12", 0, "policy:PP-1/r2/hotel"],
    ],
  )
  assert.deepEqual(
    bands.map((b) => bandLabel(b, gen)),
    ["Infant 0–3", "Kids"],
  )
  // the version's own bands win; the served ones only when it has none
  const own = { age_bands: [r("a", { band_code: "CHA", label: "", from_age: "3", to_age: "6.99", is_infant: 0 })] }
  assert.equal(effectiveBands(own, served), own.age_bands)
  assert.deepEqual(effectiveBands({ age_bands: [] }, served), bands)
  assert.deepEqual(effectiveBands({ age_bands: [] }, undefined), [])
  // "Customise for this contract": the same codes; a label equal to its code becomes the generated label
  const tables = { age_bands: [] as R[], occupancy_rules: [r("o", { age_band: "CHD" })] }
  const out = customiseBands(tables, served, gen)
  assert.deepEqual(
    out.age_bands.map((b) => [b.band_code, b.label, b.from_age, b.to_age, b.is_infant]),
    [
      ["INF", "Infant 0–3", "0", "3", 1],
      ["CHD", "Kids", "3", "12", 0],
    ],
  )
  assert.equal(out.occupancy_rules, tables.occupancy_rules, "inherited rules keep matching by code")
  assert.equal(customiseBands(tables, [], gen), tables)
})

test("addBand: the next free code, the generated label when none is typed, the key of the draft row", () => {
  const empty = { age_bands: [] as R[], occupancy_rules: [] as R[] }
  const one = addBand(empty, { key: "k1", label: "", from: "0", to: "2.99", infant: true }, gen)
  assert.deepEqual(
    one.age_bands.map((b) => [b._key, b.band_code, b.label, b.from_age, b.to_age, b.is_infant]),
    [["k1", "INF", "Infant 0–2.99", "0", "2.99", 1]],
  )
  const two = addBand(one, { key: "k2", label: "  ", from: "3", to: "6.99", infant: false }, gen)
  const three = addBand(two, { key: "k3", label: "School age", from: "7", to: "11.99", infant: false }, gen)
  assert.deepEqual(
    three.age_bands.map((b) => `${b.band_code}:${b.label}`),
    ["INF:Infant 0–2.99", "CHA:Child 3–6.99", "CHB:School age"],
  )
  // a first band that is not an infant band starts at CHA
  assert.equal(addBand(empty, { key: "k", label: "", from: "0", to: "5", infant: false }, gen).age_bands[0].band_code, "CHA")
})

test("updateBand: a generated label follows the ages; a typed label stays; a blank label is written on commit", () => {
  const tables = {
    age_bands: [
      r("a", { band_code: "CHA", label: "Child 3–6.99", from_age: "3", to_age: "6.99", is_infant: 0 }),
      r("b", { band_code: "CHB", label: "Teens", from_age: "7", to_age: "11.99", is_infant: 0 }),
      r("c", { band_code: "CHC", label: "", from_age: "12", to_age: "15.99", is_infant: 0 }),
    ],
    occupancy_rules: [] as R[],
  }
  const a = updateBand(tables, "a", { to_age: "7.99" }, gen)
  assert.deepEqual([a.age_bands[0].to_age, a.age_bands[0].label], ["7.99", "Child 3–7.99"])
  const b = updateBand(tables, "b", { to_age: "12.99" }, gen)
  assert.deepEqual([b.age_bands[1].to_age, b.age_bands[1].label], ["12.99", "Teens"], "a typed label is the user's")
  const c = updateBand(tables, "c", { is_infant: 1 }, gen)
  assert.deepEqual([c.age_bands[2].is_infant, c.age_bands[2].label], [1, "Infant 12–15.99"], "a band committed with a blank label gets the generated one")
  const cleared = updateBand(tables, "b", { label: " " }, gen)
  assert.equal(cleared.age_bands[1].label, "Child 7–11.99")
  assert.equal(updateBand(tables, "a", { to_age: "6.99" }, gen), tables, "no change, no history entry")
  assert.equal(updateBand(tables, "zz", { to_age: "1" }, gen), tables)
  assert.equal(a.age_bands[0]._key, "a")
})

test("nameBands names the bands without a name in one edit; removeBand removes the rules that name the band", () => {
  const tables = {
    age_bands: [
      r("a", { band_code: "INF", label: "", from_age: "0", to_age: "2.99", is_infant: 1 }),
      r("b", { band_code: "CHA", label: "CHA", from_age: "3", to_age: "6.99", is_infant: 0 }),
      r("c", { band_code: "CHB", label: "Teens", from_age: "7", to_age: "11.99", is_infant: 0 }),
    ],
    occupancy_rules: [r("o1", { age_band: "CHA" }), r("o2", { age_band: "cha" }), r("o3", { age_band: "CHB" })],
  }
  assert.equal(unnamedBands(tables), 2)
  const named = nameBands(tables, gen)
  assert.deepEqual(
    named.age_bands.map((b) => b.label),
    ["Infant 0–2.99", "Child 3–6.99", "Teens"],
  )
  assert.equal(unnamedBands(named), 0)
  assert.equal(nameBands(named, gen), named)
  assert.equal(bandRuleCount(tables, "CHA"), 2)
  const removed = removeBand(tables, "b")
  assert.deepEqual(removed.counts, { rules: 2 })
  assert.deepEqual(
    removed.tables.age_bands.map((b) => b.band_code),
    ["INF", "CHB"],
  )
  assert.deepEqual(
    removed.tables.occupancy_rules.map((o) => o._key),
    ["o3"],
  )
  assert.equal(removeBand(tables, "zz").tables, tables)
})

test("bandCoverage: segments on the month scale, gaps and overlaps as the server check reads them", () => {
  const ok = bandCoverage([
    { band_code: "INF", from_age: "0", to_age: "2.99" },
    { band_code: "CHA", from_age: "3", to_age: "6.99" },
    { band_code: "CHB", from_age: "7", to_age: "11.99" },
  ])
  assert.deepEqual(
    ok.segments.map((s) => `${s.code}:${s.from}-${s.to}`),
    ["INF:0-36", "CHA:36-84", "CHB:84-144"],
  )
  assert.deepEqual([ok.gaps, ok.overlaps, ok.invalid, ok.end], [[], [], [], 144])
  const bad = bandCoverage([
    { band_code: "CHB", from_age: "8", to_age: "12" },
    { band_code: "CHA", from_age: "2", to_age: "6.99" },
    { band_code: "INF", from_age: "0", to_age: "2.5" },
    { band_code: "X", from_age: "5", to_age: "4" },
  ])
  assert.deepEqual(bad.overlaps, [{ from: 24, to: 30, codes: ["INF", "CHA"] }])
  assert.deepEqual(bad.gaps, [{ from: 84, to: 96, codes: ["CHA", "CHB"] }])
  assert.deepEqual(bad.invalid, ["X"])
  assert.equal(bad.start, 0)
  assert.equal(bandCoverage([{ band_code: "CHA", from_age: "2", to_age: "5" }]).start, 24, "a minimum child age")
})
