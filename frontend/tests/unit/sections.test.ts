// Unit tests for the version editor's four sections, their hashes and the section of each
// validation issue (PRICING_WORKSPACE_UX.md §2, slice S8). Run with `npm run test:unit`.
import { test } from "node:test"
import assert from "node:assert/strict"
import {
  DEFAULT_RULE_TABLE,
  editorHash,
  issueSection,
  issueTable,
  parseEditorHash,
  RULE_TABLES,
  SECTIONS,
  type EditorPlace,
} from "../../src/tex/screens/rates/workspace/sections.ts"

test("the four sections, in order, and the Rule tables in the order of the spec", () => {
  assert.deepEqual([...SECTIONS], ["pricing", "rules", "offers", "preview"])
  assert.deepEqual([...RULE_TABLES], ["plans", "settings", "rooms", "periods", "rates", "ages", "occupancy", "boards"])
  assert.equal(DEFAULT_RULE_TABLE, "plans")
})

test("the new hashes open their section", () => {
  assert.deepEqual(parseEditorHash("#pricing"), { section: "pricing" })
  assert.deepEqual(parseEditorHash("#offers"), { section: "offers" })
  assert.deepEqual(parseEditorHash("#preview"), { section: "preview" })
  assert.deepEqual(parseEditorHash("#rules"), { section: "rules", table: "plans" })
  assert.deepEqual(parseEditorHash("rules"), { section: "rules", table: "plans" }, "the leading # is optional")
})

test("#rules/<table> opens an Advanced rule table; an unknown table opens the first", () => {
  for (const table of RULE_TABLES) assert.deepEqual(parseEditorHash(`#rules/${table}`), { section: "rules", table })
  assert.deepEqual(parseEditorHash("#rules/offers"), { section: "rules", table: "plans" })
  assert.deepEqual(parseEditorHash("#rules/"), { section: "rules", table: "plans" })
})

test("old hashes are aliases (§2): tables of the price model open Pricing, plans and settings open Commercial rules", () => {
  assert.deepEqual(parseEditorHash("#rooms"), { section: "pricing" })
  assert.deepEqual(parseEditorHash("#periods"), { section: "pricing" })
  assert.deepEqual(parseEditorHash("#rates"), { section: "pricing" })
  // the child ages drawer, the occupancy and boards regions (S11, S13) are named, so they can open once they exist
  assert.deepEqual(parseEditorHash("#ages"), { section: "pricing", region: "ages" })
  assert.deepEqual(parseEditorHash("#occupancy"), { section: "pricing", region: "occupancy" })
  assert.deepEqual(parseEditorHash("#boards"), { section: "pricing", region: "boards" })
  assert.deepEqual(parseEditorHash("#plans"), { section: "rules", table: "plans" })
  assert.deepEqual(parseEditorHash("#settings"), { section: "rules", table: "settings" })
})

test("no hash, or a hash that names nothing, is not a place (the editor keeps its default)", () => {
  for (const h of ["", "#", "#nope", "#Pricing", "#pricing/rooms", "#rates/x", "#rules/rooms/1"]) assert.equal(parseEditorHash(h), null, h)
})

test("the canonical hash of every place parses back to it", () => {
  const places: EditorPlace[] = [
    { section: "pricing" },
    { section: "offers" },
    { section: "preview" },
    ...RULE_TABLES.map((table) => ({ section: "rules" as const, table })),
    { section: "pricing", region: "ages" },
    { section: "pricing", region: "occupancy" },
    { section: "pricing", region: "boards" },
  ]
  for (const p of places) assert.deepEqual(parseEditorHash(`#${editorHash(p)}`), p, JSON.stringify(p))
  assert.equal(editorHash({ section: "pricing" }), "pricing")
  assert.equal(editorHash({ section: "rules", table: "rooms" }), "rules/rooms")
  assert.equal(editorHash({ section: "rules" }), "rules/plans", "Commercial rules always names its inner tab")
})

test("issues map to sections per §2, including BOARD_* on Pricing", () => {
  const pricing = [
    "ROOM_RULE_DUPLICATE",
    "ROOM_RULE_UNKNOWN_ROOM",
    "ROOM_RULE_UNKNOWN_PERIOD",
    "ROOM_RULE_NO_BASE",
    "ROOM_NEGATIVE",
    "ROOM_CAPACITY",
    "PERIOD_DUPLICATE",
    "PERIOD_OVERLAP",
    "PERIOD_RANGE",
    "NO_PERIODS",
    "NO_ROOMS",
    "INCLUDED_ADULTS",
    "AGE_BANDS",
    "AGE_BANDS_MIN_AGE",
    "OCC_AMBIGUOUS",
    "OCC_UNKNOWN_BAND",
    "NO_BASE_BOARD",
    "BOARD_DUPLICATE",
    "BOARD_UNKNOWN_ROOM",
    "BOARD_UNKNOWN_PERIOD",
  ]
  for (const code of pricing) assert.equal(issueSection(code), "pricing", code)
  for (const code of ["RATE_PLAN_BOARD", "SALE_WINDOW", "STAY_WINDOW", "CURRENCY", "BUILD", "SOMETHING_NEW"]) assert.equal(issueSection(code), "rules", code)
  for (const code of ["OFFER_VALUE", "OFFER_FREE_NIGHTS"]) assert.equal(issueSection(code), "offers", code)
})

test("child age bands and the publish sweep's parties are Pricing issues", () => {
  // NO_AGE_BANDS is about the bands although it does not start with AGE_BANDS
  assert.equal(issueSection("NO_AGE_BANDS"), "pricing")
  // the sweep reports a party that cannot be priced under the engine's own code; its ref names the party
  const sweep = { room_type: "STD", period: "P1", adults: 2, children: 1, age_band: "CHB" }
  assert.equal(issueSection("AMBIGUOUS_OCCUPANCY_RULES", sweep), "pricing")
  assert.equal(issueSection("NO_CHILD_RULE", { ...sweep, children: 0 }), "pricing")
  assert.equal(issueSection("NO_CHILD_RULE"), "rules", "without a ref it is not known to be about a party")
})

test("issues still map to their Advanced rule table (the per-table lists), BOARD_* to Boards", () => {
  const cases: [string, string][] = [
    ["OCC_DUPLICATE", "occupancy"],
    ["OFFER_VALUE", "offers"],
    ["PERIOD_OVERLAP", "periods"],
    ["NO_PERIODS", "periods"],
    ["ROOM_RULE_DUPLICATE", "rates"],
    ["ROOM_NEGATIVE", "rates"],
    ["ROOM_CAPACITY", "rooms"],
    ["INCLUDED_ADULTS", "rooms"],
    ["NO_ROOMS", "rooms"],
    ["AGE_BANDS", "ages"],
    ["AGE_BANDS_MIN_AGE", "ages"],
    ["NO_AGE_BANDS", "ages"],
    ["NO_BASE_BOARD", "boards"],
    ["BOARD_DUPLICATE", "boards"],
    ["BOARD_UNKNOWN_ROOM", "boards"],
    ["BOARD_UNKNOWN_PERIOD", "boards"],
    ["RATE_PLAN_BOARD", "plans"],
    ["RATE_PLAN_REFUNDABLE", "plans"],
    ["POLICY_CURRENCY", "plans"],
    ["SALE_WINDOW", "settings"],
    ["STAY_WINDOW", "settings"],
    ["CURRENCY", "settings"],
    ["BUILD", "settings"],
  ]
  for (const [code, table] of cases) assert.equal(issueTable(code), table, code)
  assert.equal(issueTable("NO_CHILD_RULE", { room_type: "STD", adults: 2, children: 1 }), "occupancy")
})

test("every issue's table lies in the issue's section (the badges agree)", () => {
  const sectionOf: Record<string, string> = { plans: "rules", settings: "rules", offers: "offers" }
  const codes = ["OCC_DUPLICATE", "OFFER_VALUE", "PERIOD_OVERLAP", "ROOM_RULE_DUPLICATE", "ROOM_CAPACITY", "AGE_BANDS", "NO_AGE_BANDS", "BOARD_DUPLICATE", "NO_BASE_BOARD", "RATE_PLAN_BOARD", "SALE_WINDOW", "CURRENCY"]
  for (const code of codes) assert.equal(sectionOf[issueTable(code)] ?? "pricing", issueSection(code), code)
})
