// Unit tests for anchored validation issues (PRICING_WORKSPACE_UX.md §3.15, §4 GAP-4, D9, D13;
// slice S15): which grid cell, ladder row, combination card, board cell or period header an issue
// of validate_version points at, and its message with band labels instead of codes. Run with
// `npm run test:unit` (node --test).
import { test } from "node:test"
import assert from "node:assert/strict"
import { bandLabel, displayBandCodes, generatedLabel, type BandLike } from "../../src/tex/screens/rates/workspace/bands.ts"
import { groupCombinations } from "../../src/tex/screens/rates/workspace/occupancy.ts"
import {
  anchorId,
  anchorIssues,
  boardCellId,
  cardAnchorId,
  issueBandCodes,
  issueMessage,
  issuePlace,
  issuesBySection,
  ladderCellId,
  ladderRowIdOf,
  matrixCellId,
  periodHeaderId,
} from "../../src/tex/screens/rates/workspace/issues.ts"
import type { Issue, Row } from "../../src/tex/screens/rates/lib/types.ts"
import type { Tables } from "../../src/tex/screens/rates/lib/tables.ts"

const r = (key: string, fields: Record<string, string | number | null>): Row => ({ _key: key, ...fields })

function occ(key: string, fields: Record<string, string | number | null>): Row {
  return r(key, { target: "CHILD", position: 0, age_band: "", combination: "", room_type: "", period_code: "", op: "MULTIPLY", value: "0.5", is_override: 0, note: "", ...fields })
}

/** The owner example: Standard (base), Superior, Deluxe; P1–P4; three child bands; a 2+2 card. */
function owner(): Tables {
  return {
    rooms: [r("rm1", { room_type: "STD", is_base: 1 }), r("rm2", { room_type: "SUP", is_base: 0 }), r("rm3", { room_type: "DLX", is_base: 0 })],
    periods: ["P1", "P2", "P3", "P4"].map((code, i) => r(`pe${i}`, { period_code: code, start_date: `2027-0${4 + i}-01`, end_date: `2027-0${4 + i}-28` })),
    period_rates: [
      r("pr1", { room_type: "STD", period_code: "", op: "ABSOLUTE", value: "70", base_room_type: "" }),
      r("pr2", { room_type: "SUP", period_code: "", op: "MULTIPLY", value: "1.15", base_room_type: "STD" }),
      r("pr3", { room_type: "SUP", period_code: "P4", op: "MULTIPLY", value: "1.2", base_room_type: "STD", _name: "tpr-0003" }),
      r("pr4", { room_type: "SUP", period_code: "P4", op: "MULTIPLY", value: "1.25", base_room_type: "STD" }),
      r("pr5", { room_type: "GHOST", period_code: "P1", op: "ABSOLUTE", value: "10", base_room_type: "" }),
      r("pr6", { room_type: "STD", period_code: "P9", op: "ABSOLUTE", value: "10", base_room_type: "" }),
    ],
    age_bands: [
      r("ab1", { band_code: "INF", label: "", from_age: "0", to_age: "2.99", is_infant: 1 }),
      r("ab2", { band_code: "CHA", label: "", from_age: "3", to_age: "6.99", is_infant: 0 }),
      r("ab3", { band_code: "CHB", label: "School age", from_age: "7", to_age: "11.99", is_infant: 0 }),
    ],
    occupancy_rules: [
      occ("oa3", { target: "ADULT", position: 3, value: "0.7" }),
      occ("oa3p4", { target: "ADULT", position: 3, period_code: "P4", value: "0.8" }),
      occ("oinf", { age_band: "INF", value: "0" }),
      occ("ocha", { age_band: "CHA", value: "0.25", room_type: "DLX" }),
      occ("ocany", { value: "0.5" }),
      occ("oc1", { position: 1, age_band: "CHB", combination: "2+2", value: "0.5" }),
      occ("oc2", { position: 2, age_band: "CHA", combination: "2+2", value: "0.25" }),
      occ("osingle", { target: "COMBINATION", combination: "1+0", op: "MULTIPLY", value: "1.5" }),
      occ("oany", { target: "ADULT", position: 0, value: "1" }),
      occ("obadroom", { age_band: "CHB", room_type: "GHOST" }),
    ],
    boards: [
      r("bb", { board: "BB", is_base: 1, op: "ADD", adult_amount: "", room_type: "", period_code: "" }),
      r("hb", { board: "HB", is_base: 0, op: "ADD", adult_amount: "20", room_type: "", period_code: "" }),
      r("hbsup", { board: "HB", is_base: 0, op: "ADD", adult_amount: "25", room_type: "SUP", period_code: "P2" }),
      r("hbsup2", { board: "HB", is_base: 0, op: "ADD", adult_amount: "26", room_type: "SUP", period_code: "P2" }),
    ],
    rate_plans: [],
    offers: [],
  }
}

const issue = (level: "ERROR" | "WARNING", code: string, message: string, ref?: Issue["ref"]): Issue => (ref ? { level, code, message, ref } : { level, code, message })

test("anchor ids: the grids' data-cellid values", () => {
  assert.equal(matrixCellId("SUP", "P4"), "SUP|P4")
  assert.equal(matrixCellId("SUP", ""), "SUP|")
  assert.equal(ladderCellId("band:0:CHB", "P1"), "occ:band:0:CHB|P1")
  assert.equal(ladderCellId("band:0:CHB", "P1", ""), "occ:band:0:CHB|P1")
  assert.equal(ladderCellId("band:0:CHB", "P1", "STD"), "occ:band:0:CHB|P1@STD")
  assert.equal(boardCellId("HB", "", "P2"), "board:HB||P2")
  assert.equal(periodHeaderId("P4"), "period:P4")
  assert.equal(cardAnchorId('["2+2"]'), 'card:["2+2"]')
  assert.equal(anchorId({ kind: "matrix", room: "SUP", period: "P4" }), "SUP|P4")
  assert.equal(anchorId({ kind: "ladder", scope: "DLX", row: "adult:3:", period: "" }), "occ:adult:3:|@DLX")
  assert.equal(anchorId({ kind: "board", board: "HB", room: "SUP", period: "P2" }), "board:HB|SUP|P2")
  assert.equal(anchorId({ kind: "period", period: "P1" }), "period:P1")
  assert.equal(anchorId({ kind: "card", card: "x" }), "card:x")
})

test("ladderRowIdOf: the ladder row a plain occupancy rule is shown in", () => {
  assert.equal(ladderRowIdOf(occ("a", { target: "ADULT", position: 3 })), "adult:3:")
  assert.equal(ladderRowIdOf(occ("a", { target: "ADULT", position: 0 })), "adult_any:0:")
  assert.equal(ladderRowIdOf(occ("a", { target: "adult", position: "1" })), "adult:1:")
  assert.equal(ladderRowIdOf(occ("a", { age_band: "chb" })), "band:0:CHB")
  assert.equal(ladderRowIdOf(occ("a", { position: 2, age_band: "CHA" })), "child:2:CHA")
  assert.equal(ladderRowIdOf(occ("a", { position: 2 })), "child:2:")
  assert.equal(ladderRowIdOf(occ("a", {})), "child_any:0:")
  assert.equal(ladderRowIdOf(occ("a", { target: "COMBINATION", combination: "1+0" })), "single:0:")
  assert.equal(ladderRowIdOf(occ("a", { target: "ADULT", position: 1, combination: "1+*" })), "single:0:")
  // an adult rule with a band (OCC_ADULT_BAND), a combination rule without a party, a special
  // combination (a card), an unknown target: no ladder row
  assert.equal(ladderRowIdOf(occ("a", { target: "ADULT", position: 3, age_band: "CHB" })), null)
  assert.equal(ladderRowIdOf(occ("a", { target: "COMBINATION" })), null)
  assert.equal(ladderRowIdOf(occ("a", { position: 1, combination: "2+2" })), null)
  assert.equal(ladderRowIdOf(occ("a", { target: "ROOM" })), null)
})

test("'~key' and _name anchoring: a duplicate SUP P4 room rule marks the SUP · P4 cell (once)", () => {
  const tb = owner()
  const dup = issue("ERROR", "ROOM_RULE_DUPLICATE", "room SUP has two rules for period P4", { rule_id: "tpr-0003", rule_ids: ["tpr-0003", "~pr4"], room_type: "SUP", period: "P4" })
  const byKey = issue("ERROR", "ROOM_RULE_NO_BASE", "rule ~pr2 derives a price but names no base room", { rule_id: "~pr2", room_type: "SUP", period: "" })
  const a = anchorIssues([dup, byKey], tb)
  assert.deepEqual(a.anchors[0], [{ kind: "matrix", room: "SUP", period: "P4" }])
  assert.deepEqual(a.anchors[1], [{ kind: "matrix", room: "SUP", period: "" }])
  assert.deepEqual(a.byCell.get("SUP|P4"), [dup])
  assert.deepEqual(a.byCell.get("SUP|"), [byKey])
  assert.deepEqual(a.unanchored, [])
  // a row sent without a key: ~<table>-<n> (1-based)
  const byPos = issue("ERROR", "ROOM_RULE_NO_BASE", "…", { rule_id: "~period_rates-2" })
  assert.deepEqual(anchorIssues([byPos], tb).anchors[0], [{ kind: "matrix", room: "SUP", period: "" }])
})

test("room + period: an issue without a rule of the draft marks the matrix cell", () => {
  const tb = owner()
  const noPrice = issue("ERROR", "NO_ROOM_PRICE", "DLX / P1: no price for DLX", { room_type: "DLX", period: "P1" })
  const negative = issue("ERROR", "ROOM_NEGATIVE", "SUP prices below zero in P2", { room_type: "SUP", period: "P2", rule_id: "POLICY-RULE-9" })
  const a = anchorIssues([noPrice, negative], tb)
  assert.deepEqual(a.anchors[0], [{ kind: "matrix", room: "DLX", period: "P1" }])
  // a rule id the draft does not hold falls back to the ref's fields
  assert.deepEqual(a.anchors[1], [{ kind: "matrix", room: "SUP", period: "P2" }])
  assert.deepEqual([...a.byCell.keys()], ["DLX|P1", "SUP|P2"])
})

test("a rule for an unknown room or period, and a room alone, stay unanchored", () => {
  const tb = owner()
  const ghost = issue("ERROR", "ROOM_RULE_UNKNOWN_ROOM", "rule ~pr5 prices unknown room GHOST", { rule_id: "~pr5", room_type: "GHOST", period: "P1" })
  const p9 = issue("ERROR", "ROOM_RULE_UNKNOWN_PERIOD", "rule ~pr6 names unknown period P9", { rule_id: "~pr6", room_type: "STD", period: "P9" })
  const cap = issue("ERROR", "ROOM_CAPACITY", "SUP: max occupants below max adults", { room_type: "SUP" })
  const occRoom = issue("ERROR", "OCC_UNKNOWN_ROOM", "rule ~obadroom names unknown room GHOST", { rule_id: "~obadroom", room_type: "GHOST", age_band: "CHB" })
  const a = anchorIssues([ghost, p9, cap, occRoom], tb)
  assert.deepEqual(a.anchors, [[], [], [], []])
  assert.deepEqual(a.unanchored, [ghost, p9, cap, occRoom])
  assert.equal(a.byCell.size, 0)
})

test("occupancy rules: a plain rule marks its ladder cell in its rooms scope; a special combination its card; single use the ladder's first row", () => {
  const tb = owner()
  const cards = groupCombinations(tb)
  const twoTwo = cards.find((c) => c.combination === "2+2")
  assert.ok(twoTwo)
  const issues = [
    issue("ERROR", "OCC_NO_VALUE", "rule ~oa3p4 has no value", { rule_id: "~oa3p4", period: "P4" }),
    issue("ERROR", "OCC_DUPLICATE", "rules ~ocha, ~x share the same scope …", { rule_id: "~ocha", rule_ids: ["~ocha"], room_type: "DLX", age_band: "CHA" }),
    issue("ERROR", "OCC_NO_VALUE", "rule ~oc1 has no value", { rule_id: "~oc1", adults: 2, children: 2, age_band: "CHB" }),
    issue("ERROR", "OCC_NO_VALUE", "rule ~osingle has no value", { rule_id: "~osingle", adults: 1, children: 0 }),
  ]
  const a = anchorIssues(issues, tb)
  assert.deepEqual(a.anchors[0], [{ kind: "ladder", scope: "", row: "adult:3:", period: "P4" }])
  assert.deepEqual(a.anchors[1], [{ kind: "ladder", scope: "DLX", row: "band:0:CHA", period: "" }])
  assert.deepEqual(a.anchors[2], [{ kind: "card", card: twoTwo.id }])
  assert.deepEqual(a.anchors[3], [{ kind: "ladder", scope: "", row: "single:0:", period: "" }])
  assert.deepEqual(a.byCell.get(ladderCellId("band:0:CHA", "", "DLX")), [issues[1]])
  assert.deepEqual(a.byCell.get(cardAnchorId(twoTwo.id)), [issues[2]])
})

test("age_band (± period) → a ladder row: a band's own issue, and a sweep party in its room", () => {
  const tb = owner()
  const range = issue("ERROR", "AGE_BANDS", "age band CHB has an invalid range (84–84 months)", { age_bands: ["INF", "CHA", "CHB"], age_band: "CHB" })
  const sweep = issue("WARNING", "NO_CHILD_RULE", "STD 2A+1C [CHB]: no child rule for child 1 (CHB)", { room_type: "STD", period: "P1", adults: 2, children: 1, age_band: "CHB" })
  const unknownBand = issue("WARNING", "NO_CHILD_RULE", "STD 2A+1C [CHZ]: …", { room_type: "STD", period: "P1", adults: 2, children: 1, age_band: "CHZ" })
  const a = anchorIssues([range, sweep, unknownBand], tb)
  assert.deepEqual(a.anchors[0], [{ kind: "ladder", scope: "", row: "band:0:CHB", period: "" }])
  assert.deepEqual(a.anchors[1], [{ kind: "ladder", scope: "STD", row: "band:0:CHB", period: "P1" }])
  // a party issue never lands on a room price cell: no card and no band row → the list only
  assert.deepEqual(a.anchors[2], [])
  // the bands the ladder shows can be the inherited ones (the version has none)
  const inherited = anchorIssues([range], { ...tb, age_bands: [] }, { bands: [{ code: "CHB", label: "" }] })
  assert.deepEqual(inherited.anchors[0], [{ kind: "ladder", scope: "", row: "band:0:CHB", period: "" }])
  assert.deepEqual(anchorIssues([range], { ...tb, age_bands: [] }).anchors[0], [])
})

test("a combination ref → its card: the sweep's 2A+2C party in a room the All-rooms 2+2 card covers", () => {
  const tb = owner()
  const card = groupCombinations(tb).find((c) => c.combination === "2+2")
  assert.ok(card)
  const sweep = issue("WARNING", "NO_CHILD_RULE", "SUP 2A+2C [INF]: no child rule for child 1 (INF)", { room_type: "SUP", period: "P3", adults: 2, children: 2, age_band: "INF" })
  const ambiguous = issue("ERROR", "OCC_AMBIGUOUS", "rules A and B both price …", { rule_id: "POLICY-1", rule_ids: ["POLICY-1", "POLICY-2"], adults: 2, children: 2 })
  const a = anchorIssues([sweep, ambiguous], tb)
  assert.deepEqual(a.anchors[0], [{ kind: "card", card: card.id }])
  assert.deepEqual(a.anchors[1], [{ kind: "card", card: card.id }])
  assert.deepEqual(a.byCell.get(cardAnchorId(card.id)), [sweep, ambiguous])
  // a 3A+1C party has no card: its band row
  const three = issue("WARNING", "NO_CHILD_RULE", "SUP 3A+1C [INF]: …", { room_type: "SUP", period: "P3", adults: 3, children: 1, age_band: "INF" })
  assert.deepEqual(anchorIssues([three], tb).anchors[0], [{ kind: "ladder", scope: "SUP", row: "band:0:INF", period: "P3" }])
  // the card of the party's room wins over the All-rooms one; any children matches too
  const named = { ...tb, occupancy_rules: [...tb.occupancy_rules, occ("ocsup", { position: 1, age_band: "INF", combination: "2+2", room_type: "SUP", value: "0" }), occ("any", { position: 1, combination: "2+*", value: "0.1" })] }
  const cards = groupCombinations(named)
  const sup = cards.find((c) => c.combination === "2+2" && c.rooms.includes("SUP"))
  const any = cards.find((c) => c.combination === "2+*")
  assert.ok(sup && any)
  assert.deepEqual(anchorIssues([sweep], named).anchors[0], [{ kind: "card", card: sup.id }])
  const twoThree = issue("WARNING", "NO_CHILD_RULE", "SUP 2A+3C [INF]: …", { room_type: "SUP", period: "P3", adults: 2, children: 3, age_band: "INF" })
  assert.deepEqual(anchorIssues([twoThree], named).anchors[0], [{ kind: "card", card: any.id }])
})

test("board refs → board cells; period alone → the period headers", () => {
  const tb = owner()
  const dup = issue("ERROR", "BOARD_DUPLICATE", "board HB has 2 rules for the same room and period", { rule_id: "~hbsup", rule_ids: ["~hbsup", "~hbsup2"], board: "HB", room_type: "SUP", period: "P2" })
  const byRef = issue("ERROR", "BOARD_DUPLICATE", "board HB has 2 rules …", { rule_id: "saved-x", board: "HB", room_type: "SUP", period: "P2" })
  const unknownPeriod = issue("ERROR", "BOARD_UNKNOWN_PERIOD", "board rule X (HB) names unknown period P9", { rule_id: "X", board: "HB", room_type: "", period: "P9" })
  const range = issue("ERROR", "PERIOD_RANGE", "period P2 ends before it starts", { period: "P2" })
  const overlap = issue("ERROR", "PERIOD_OVERLAP", "periods P1 and P3 overlap with equal priority", { period: "P1", other_period: "P3" })
  const a = anchorIssues([dup, byRef, unknownPeriod, range, overlap], tb)
  assert.deepEqual(a.anchors[0], [{ kind: "board", board: "HB", room: "SUP", period: "P2" }])
  assert.deepEqual(a.anchors[1], [{ kind: "board", board: "HB", room: "SUP", period: "P2" }])
  assert.deepEqual(a.anchors[2], [])
  assert.deepEqual(a.anchors[3], [{ kind: "period", period: "P2" }])
  assert.deepEqual(a.anchors[4], [
    { kind: "period", period: "P1" },
    { kind: "period", period: "P3" },
  ])
  assert.deepEqual(a.byCell.get("board:HB|SUP|P2"), [dup, byRef])
  assert.deepEqual(a.byCell.get("period:P3"), [overlap])
})

test("unanchored header issues stay in the list", () => {
  const tb = owner()
  const header = [
    issue("ERROR", "SALE_WINDOW", "sale window ends before it starts"),
    issue("ERROR", "CURRENCY", "currency 'EURO' is not an ISO code"),
    issue("ERROR", "NO_BASE_BOARD", "no base board is included in the room price"),
    issue("ERROR", "RATE_PLAN_BOARD", "rate plan NRF sells unknown board FB"),
    issue("WARNING", "AGE_BANDS", "age bands CHA and CHB overlap at 6y–7y", { age_bands: ["INF", "CHA", "CHB"] }),
    issue("ERROR", "OFFER_VALUE", "offer EB: percent must be in (0, 100]"),
  ]
  const a = anchorIssues(header, tb)
  assert.deepEqual(a.unanchored, header)
  assert.equal(a.byCell.size, 0)
  // nothing to anchor: no work, the same shape
  const none = anchorIssues([], tb)
  assert.deepEqual(none.unanchored, [])
  assert.equal(none.byCell.size, 0)
})

test("issuePlace: an anchored issue shows its cell; the others open their section, rule table or Pricing region", () => {
  const tb = owner()
  const list = [
    issue("ERROR", "ROOM_RULE_DUPLICATE", "…", { rule_id: "~pr4", room_type: "SUP", period: "P4" }),
    issue("ERROR", "OCC_NO_VALUE", "…", { rule_id: "~oa3p4" }),
    issue("ERROR", "PERIOD_RANGE", "…", { period: "P2" }),
    issue("ERROR", "RATE_PLAN_BOARD", "rate plan NRF sells unknown board FB"),
    issue("ERROR", "OFFER_VALUE", "…"),
    issue("WARNING", "AGE_BANDS", "age bands CHA and CHB overlap at …", { age_bands: ["CHA", "CHB"] }),
    issue("ERROR", "NO_BASE_BOARD", "no base board …"),
    issue("ERROR", "OCC_UNKNOWN_ROOM", "…", { rule_id: "~obadroom", room_type: "GHOST" }),
    issue("ERROR", "ROOM_CAPACITY", "…", { room_type: "SUP" }),
    issue("ERROR", "SALE_WINDOW", "…"),
  ]
  const a = anchorIssues(list, tb)
  const places = list.map((x, i) => issuePlace(x, a.anchors[i]))
  assert.deepEqual(places[0], { section: "pricing", target: { kind: "matrix", room: "SUP", period: "P4" } })
  assert.deepEqual(places[1], { section: "pricing", target: { kind: "ladder", scope: "", row: "adult:3:", period: "P4" } })
  assert.deepEqual(places[2], { section: "pricing", target: { kind: "period", period: "P2" } })
  assert.deepEqual(places[3], { section: "rules", table: "plans" })
  assert.deepEqual(places[4], { section: "offers" })
  assert.deepEqual(places[5], { section: "pricing", target: { kind: "region", region: "ages" } })
  assert.deepEqual(places[6], { section: "pricing", target: { kind: "region", region: "boards" } })
  assert.deepEqual(places[7], { section: "pricing", target: { kind: "region", region: "occupancy" } })
  assert.deepEqual(places[8], { section: "pricing", target: { kind: "region", region: "matrix" } })
  assert.deepEqual(places[9], { section: "rules", table: "settings" })
  const card = groupCombinations(tb).find((c) => c.combination === "2+2")
  assert.deepEqual(issuePlace(list[0], [{ kind: "card", card: card?.id ?? "" }]), { section: "pricing", target: { kind: "card", id: card?.id } })
  assert.deepEqual(issuePlace(list[0], [{ kind: "board", board: "HB", room: "", period: "P1" }]), { section: "pricing", target: { kind: "board", board: "HB", room: "", period: "P1" } })
})

test("issuesBySection: the chip's groups in section order, errors first, each item with its index", () => {
  const list = [
    issue("WARNING", "NO_CHILD_RULE", "…", { room_type: "STD", adults: 2, children: 1 }),
    issue("ERROR", "RATE_PLAN_BOARD", "…"),
    issue("ERROR", "ROOM_RULE_DUPLICATE", "…", { room_type: "SUP", period: "P4" }),
    issue("WARNING", "OFFER_OVERLAP", "…"),
    issue("ERROR", "OFFER_VALUE", "…"),
  ]
  const groups = issuesBySection(list)
  assert.deepEqual(
    groups.map((g) => [g.section, g.items.map((x) => x.index), g.errors, g.warnings]),
    [
      ["pricing", [2, 0], 1, 1],
      ["rules", [1], 1, 0],
      ["offers", [4, 3], 1, 1],
    ],
  )
  assert.deepEqual(issuesBySection([]), [])
})

// ─── messages with band labels (D13) ────────────────────────────────────────

const BANDS: BandLike[] = [
  { band_code: "INF", label: "", from_age: "0", to_age: "2.99", is_infant: 1 },
  { band_code: "CHA", label: "", from_age: "3", to_age: "6.99", is_infant: 0 },
  { band_code: "CHB", label: "School age", from_age: "7", to_age: "11.99", is_infant: 0 },
]
// the generated label as useBandLabels renders it in English
const gen = (b: BandLike) => {
  const g = generatedLabel(b)
  return `${g.key === "rates.bands.label_infant" ? "Infant" : "Child"} ${g.params.from}–${g.params.to}`
}
const display = (text: string, codes?: readonly string[]) => displayBandCodes(text, BANDS, { codes, labelOf: (_c, band) => bandLabel(band, gen) })

test("issueBandCodes: the codes a message may print bare", () => {
  assert.deepEqual(issueBandCodes(issue("ERROR", "AGE_BANDS", "…", { age_bands: ["INF", "CHA"], age_band: "CHA" })), ["INF", "CHA"])
  assert.deepEqual(issueBandCodes(issue("ERROR", "OCC_UNKNOWN_BAND", "…", { age_band: "CHZ" })), ["CHZ"])
  assert.equal(issueBandCodes(issue("ERROR", "SALE_WINDOW", "…")), undefined)
  assert.equal(issueBandCodes(issue("ERROR", "PERIOD_RANGE", "…", { period: "P1" })), undefined)
})

test("an AGE_BANDS message reads band labels, not codes", () => {
  const overlap = issue("ERROR", "AGE_BANDS", "age bands CHA and CHB overlap at 6y 6m–7y", { age_bands: ["INF", "CHA", "CHB"] })
  assert.equal(issueMessage(overlap, display), "age bands Child 3–6.99 and School age overlap at 6y 6m–7y")
  const range = issue("ERROR", "AGE_BANDS", "age band INF has an invalid range (36–36 months)", { age_bands: ["INF", "CHA", "CHB"], age_band: "INF" })
  assert.equal(issueMessage(range, display), "age band Infant 0–2.99 has an invalid range (36–36 months)")
  // a code the contract does not have, and a word that only contains a code, stay as they are
  const unknown = issue("ERROR", "OCC_UNKNOWN_BAND", "rule ~x names unknown age band CHZ; CHAX", { age_band: "CHZ" })
  assert.equal(issueMessage(unknown, display), "rule ~x names unknown age band CHZ; CHAX")
})

test("a sweep message 'STD 2A+2C [CHB]: …' reads the band's label (the bracket rule)", () => {
  const sweep = issue("WARNING", "NO_CHILD_RULE", "STD 2A+2C [CHB]: no child rule for child 2 (CHB)", { room_type: "STD", period: "P1", adults: 2, children: 2, age_band: "CHB" })
  assert.equal(issueMessage(sweep, display), "STD 2A+2C [School age]: no child rule for child 2 (School age)")
  // without a ref naming the band, only the bracketed code is replaced
  const bare = issue("WARNING", "NO_CHILD_RULE", "STD 2A+2C [CHA]: no child rule for child 2 (CHA)")
  assert.equal(issueMessage(bare, display), "STD 2A+2C [Child 3–6.99]: no child rule for child 2 (CHA)")
})
