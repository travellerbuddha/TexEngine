// Unit tests for the Pricing Workspace occupancy ladder and special combinations
// (PRICING_WORKSPACE_UX.md §3.6, §3.7, D8, D12, §5.1). Run with `npm run test:unit` (node --test).
import { test } from "node:test"
import assert from "node:assert/strict"
import { parseShorthand } from "../../src/tex/screens/rates/lib/shorthand.ts"
import {
  applyOccEntry,
  applyOccRule,
  applyOccRuleAs,
  builderCanEdit,
  builderFromCard,
  builderValueText,
  canonCombination,
  cardOfRow,
  childQualifier,
  combinationChips,
  combinationNotes,
  ensureChildLines,
  isSingleUseCard,
  newBuilderDraft,
  planCombination,
  readBuilderValue,
  shownChildPositions,
  defaultParty,
  fromInheritedRule,
  groupCombinations,
  ladderModel,
  ladderSummary,
  occEditText,
  occReadingOf,
  PARTY_ADULTS_MAX,
  PARTY_CHILDREN_MAX,
  PARTY_OPTIONS_MAX,
  partyOptions,
  persistCombination,
  planOccEntries,
  policySource,
  removeCombination,
  scopesWithRules,
  singleWriteRefusal,
  validCombinations,
  type BuilderDraft,
  type BuilderLine,
  type LadderOptions,
  type OccIdentity,
} from "../../src/tex/screens/rates/workspace/occupancy.ts"
import type { Row } from "../../src/tex/screens/rates/lib/types.ts"
import type { Tables } from "../../src/tex/screens/rates/lib/tables.ts"

let seq = 0
const r = (fields: Record<string, string | number | null>): Row => ({ _key: `o${++seq}`, ...fields })

function occ(fields: Record<string, string | number | null>): Row {
  return r({ target: "ADULT", position: 0, age_band: "", combination: "", room_type: "", period_code: "", op: "MULTIPLY", value: "", is_override: 0, note: "", ...fields })
}

function tablesOf(p: Partial<Tables>): Tables {
  return { rooms: [], periods: [], period_rates: [], age_bands: [], occupancy_rules: [], boards: [], rate_plans: [], offers: [], ...p }
}

const BANDS = [
  { code: "INF", label: "Infant 0–2.99", is_infant: 1 },
  { code: "CHA", label: "Child 3–6.99", is_infant: 0 },
  { code: "CHB", label: "Child 7–11.99", is_infant: 0 },
]
const DEFAULTS: LadderOptions["defaults"] = {
  adult: { rule_id: "GLOBAL:ADULT", target: "ADULT", op: "MULTIPLY", value: "1", source: "global-default", note: "every adult pays the full unit" },
  child: null,
}
const OPTS: LadderOptions = { maxAdults: 4, includedAdults: 2, bands: BANDS, defaults: DEFAULTS }

function example(extra: Row[] = []): Tables {
  return tablesOf({
    rooms: [r({ room_type: "STD", is_base: 1 }), r({ room_type: "SUP", is_base: 0 }), r({ room_type: "DLX", is_base: 0 })],
    periods: ["P1", "P2", "P3", "P4"].map((code) => r({ period_code: code })),
    occupancy_rules: [
      occ({ target: "COMBINATION", combination: "1+0", op: "MULTIPLY", value: "1.5" }),
      occ({ target: "ADULT", position: 3, op: "MULTIPLY", value: "0.7" }),
      occ({ target: "ADULT", position: 3, period_code: "P4", op: "MULTIPLY", value: "0.8" }),
      occ({ target: "CHILD", age_band: "INF", op: "MULTIPLY", value: "0" }),
      occ({ target: "CHILD", age_band: "CHA", op: "MULTIPLY", value: "0.25" }),
      ...extra,
    ],
  })
}

const kinds = (m: ReturnType<typeof ladderModel>) => m.rows.map((row) => (row.position ? `${row.kind}${row.position}` : row.band ? `${row.kind}:${row.band}` : row.kind))

// ─── the ladder (§3.6.2, D12) ────────────────────────────────────────────

test("PERSON ladder: single use, the BASE pair with the engine default, adult positions and bands", () => {
  const m = ladderModel(example(), null, "PERSON", OPTS)
  assert.deepEqual(kinds(m), ["single", "adults_base", "adult3", "adult4", "band:INF", "band:CHA", "band:CHB"])
  assert.deepEqual(m.periods, ["", "P1", "P2", "P3", "P4"])
  const [single, pair] = m.rows
  assert.deepEqual(single.identity, { target: "COMBINATION", position: 0, age_band: "", combination: "1+0", room_type: "" })
  assert.equal(single.cells[""].state, "rule")
  assert.deepEqual(single.cells[""].value, { op: "MULTIPLY", value: "1.5" })
  assert.equal(single.cells.P2.state, "inherited")
  assert.equal(pair.editable, false, "the BASE pair is read-only")
  assert.equal(pair.identity, null)
  for (const p of m.periods) {
    assert.equal(pair.cells[p].state, "default", p)
    assert.deepEqual(pair.cells[p].value, { op: "MULTIPLY", value: "1" })
  }
})

test("a 4th adult position with no rule shows the server default ×1", () => {
  const m = ladderModel(example(), null, "PERSON", OPTS)
  const fourth = m.rows.find((row) => row.kind === "adult" && row.position === 4)
  assert.ok(fourth)
  assert.equal(fourth.editable, true)
  assert.deepEqual(fourth.identity, { target: "ADULT", position: 4, age_band: "", combination: "", room_type: "" })
  assert.equal(fourth.cells[""].state, "default")
  assert.deepEqual(fourth.cells[""].value, { op: "MULTIPLY", value: "1" })
  assert.equal(fourth.cells[""].rule, null)
  // the single-use row falls back to the same default when it has no rule
  const bare = ladderModel(tablesOf({ periods: [r({ period_code: "P1" })] }), null, "PERSON", OPTS)
  assert.equal(bare.rows[0].kind, "single")
  assert.equal(bare.rows[0].cells.P1.state, "default")
  // without server defaults (an older server) the state stays, with no value
  const noDefaults = ladderModel(example(), null, "PERSON", { ...OPTS, defaults: undefined })
  assert.equal(noDefaults.rows.find((row) => row.position === 4)?.cells[""].value, null)
})

test("the 3rd adult: All periods ×0.70, P4 ×0.80 OVERRIDE", () => {
  const m = ladderModel(example(), null, "PERSON", OPTS)
  const third = m.rows.find((row) => row.kind === "adult" && row.position === 3)
  assert.ok(third)
  assert.equal(third.cells[""].state, "rule")
  assert.equal(third.cells.P1.state, "inherited")
  assert.deepEqual(third.cells.P1.value, { op: "MULTIPLY", value: "0.7" })
  assert.equal(third.cells.P1.rule, null)
  assert.equal(third.cells.P4.state, "period-override")
  assert.deepEqual(third.cells.P4.value, { op: "MULTIPLY", value: "0.8" })
  assert.equal(third.cells.P4.rule?.period_code, "P4")
  assert.equal(m.counts.periodOverrides, 1)
})

test("a band without a rule is 'missing' (no child default, ADR-007)", () => {
  const m = ladderModel(example(), null, "PERSON", OPTS)
  const chb = m.rows.find((row) => row.band === "CHB")
  assert.ok(chb)
  assert.deepEqual(chb.identity, { target: "CHILD", position: 0, age_band: "CHB", combination: "", room_type: "" })
  for (const p of m.periods) {
    assert.equal(chb.cells[p].state, "missing", p)
    assert.equal(chb.cells[p].value, null)
  }
  assert.equal(m.rows.find((row) => row.band === "INF")?.cells.P3.state, "inherited")
  // a band-less child rule prices every band that has no rule of its own
  const general = ladderModel(example([occ({ target: "CHILD", op: "PERCENT_OF", value: "50" })]), null, "PERSON", OPTS)
  assert.deepEqual(kinds(general).slice(-4), ["band:INF", "band:CHA", "band:CHB", "child_any"])
  const chbGeneral = general.rows.find((row) => row.band === "CHB")
  assert.equal(chbGeneral?.cells.P1.state, "general")
  assert.deepEqual(chbGeneral?.cells.P1.value, { op: "PERCENT_OF", value: "50" })
})

test("the BASE pair splits into Adult 1 / Adult 2 when a position-1 rule exists", () => {
  const m = ladderModel(example([occ({ target: "ADULT", position: 1, op: "MULTIPLY", value: "1.1" })]), null, "PERSON", OPTS)
  assert.deepEqual(kinds(m), ["single", "adult1", "adult2", "adult3", "adult4", "band:INF", "band:CHA", "band:CHB"])
  assert.equal(m.rows[1].cells[""].state, "rule")
  assert.equal(m.rows[2].cells[""].state, "default")
  assert.equal(m.rows[2].editable, true)
})

test("ROOM basis: positions up to the included adults are included in the room price", () => {
  const m = ladderModel(example(), null, "ROOM", OPTS)
  assert.deepEqual(kinds(m), ["single", "adult1", "adult2", "adult3", "adult4", "band:INF", "band:CHA", "band:CHB"])
  for (const pos of [1, 2]) {
    const row = m.rows.find((x) => x.kind === "adult" && x.position === pos)
    for (const p of m.periods) assert.equal(row?.cells[p].state, "included", `${pos} ${p}`)
  }
  const third = m.rows.find((x) => x.kind === "adult" && x.position === 3)
  assert.equal(third?.cells.P4.state, "period-override")
  assert.equal(m.rows.find((x) => x.kind === "adult" && x.position === 4)?.cells[""].state, "default")
  const one = ladderModel(example(), null, "ROOM", { ...OPTS, includedAdults: 1 })
  assert.equal(one.rows.find((x) => x.kind === "adult" && x.position === 2)?.cells[""].state, "default")
})

test("a room scope shows that room's rules; inherited policy rules show their source", () => {
  const extra = [occ({ target: "CHILD", age_band: "CHB", room_type: "SUP", op: "MULTIPLY", value: "0.5" })]
  const sup = ladderModel(example(extra), "SUP", "PERSON", OPTS)
  assert.equal(sup.rows.find((row) => row.band === "CHB")?.cells[""].state, "rule")
  assert.equal(sup.rows.find((row) => row.band === "CHB")?.identity?.room_type, "SUP")
  // (S11 review) an All-rooms rule prices every room with no rule of its own, so the room scope
  // shows it as coming from All rooms, never as the engine default
  const third = sup.rows.find((row) => row.kind === "adult" && row.position === 3)?.cells[""]
  assert.equal(third?.state, "all-rooms", "the all-rooms rule applies to SUP")
  assert.deepEqual(third?.value, { op: "MULTIPLY", value: "0.7" })
  assert.equal(third?.rule, null, "SUP holds no row of its own for it")
  const inherited = [{ target: "CHILD", position: 0, age_band: "CHB", combination: "", room_type: "", period_code: "", op: "MULTIPLY", value: "0.4", source: "Hotel policy" }]
  const pol = ladderModel(example(), null, "PERSON", { ...OPTS, inherited })
  const cell = pol.rows.find((row) => row.band === "CHB")?.cells.P2
  assert.equal(cell?.state, "policy")
  assert.equal(cell?.source?.source, "Hotel policy")
  assert.deepEqual(cell?.value, { op: "MULTIPLY", value: "0.4" })
})

test("rules for positions beyond max adults and for unknown bands still get a row", () => {
  const m = ladderModel(
    example([occ({ target: "ADULT", position: 6, op: "MULTIPLY", value: "0.5" }), occ({ target: "CHILD", age_band: "ZZZ", op: "MULTIPLY", value: "0.1" })]),
    null,
    "PERSON",
    OPTS,
  )
  assert.deepEqual(kinds(m), ["single", "adults_base", "adult3", "adult4", "adult5", "adult6", "band:INF", "band:CHA", "band:CHB", "band:ZZZ"])
  assert.equal(m.rows.find((row) => row.band === "ZZZ")?.unknownBand, true)
})

test("applyOccEntry stores what is typed as a rule on the row's identity", () => {
  const t = example()
  const fourth: OccIdentity = { target: "ADULT", position: 4, age_band: "", combination: "", room_type: "" }
  const res = applyOccEntry(t, fourth, "", parseShorthand("x0.6", "occupancy"))
  assert.ok("tables" in res)
  const row = res.tables.occupancy_rules.at(-1)
  assert.deepEqual(
    [row?.target, row?.position, row?.age_band, row?.combination, row?.room_type, row?.period_code, row?.op, row?.value, row?.is_override],
    ["ADULT", 4, "", "", "", "", "MULTIPLY", "0.6", 0],
  )
  // relative ops are always stored as rules here, and an override replaces the period cell in place
  const third: OccIdentity = { target: "ADULT", position: 3, age_band: "", combination: "", room_type: "" }
  const key = t.occupancy_rules[2]._key
  const p4 = applyOccEntry(t, third, "P4", parseShorthand("+10%", "occupancy"))
  assert.ok("tables" in p4)
  const p4row = p4.tables.occupancy_rules.find((x) => x._key === key)
  assert.deepEqual([p4row?.op, p4row?.value, p4row?.period_code], ["ADJUST_PERCENT", "10", "P4"])
  // a period entry equal to All periods is stored, not dropped (occupancy precedence ranks it)
  const same = applyOccEntry(t, third, "P2", parseShorthand("x0.7", "occupancy"))
  assert.ok("tables" in same)
  assert.equal(same.tables.occupancy_rules.filter((x) => x.position === 3).length, 3)
  // clear removes the cell's row; the All-periods row stays
  const cleared = applyOccEntry(t, third, "P4", parseShorthand("", "occupancy"))
  assert.ok("tables" in cleared)
  assert.deepEqual(
    cleared.tables.occupancy_rules.filter((x) => x.position === 3).map((x) => x.period_code),
    [""],
  )
  const band: OccIdentity = { target: "CHILD", position: 0, age_band: "CHB", combination: "", room_type: "SUP" }
  const b = applyOccEntry(t, band, "", parseShorthand("50%", "occupancy"))
  assert.ok("tables" in b)
  const brow = b.tables.occupancy_rules.at(-1)
  assert.deepEqual([brow?.target, brow?.age_band, brow?.room_type, brow?.op, brow?.value], ["CHILD", "CHB", "SUP", "PERCENT_OF", "50"])
  assert.deepEqual(applyOccEntry(t, band, "", parseShorthand("abc", "occupancy")), { error: "SYNTAX" })
})

// ─── special combinations (§3.7) ─────────────────────────────────────────

test("validCombinations follows the publish sweep", () => {
  const got = validCombinations([{ max_adults: 3, max_children: 2, max_occupants: 4, min_adults: 1 }])
  assert.deepEqual(
    got.map((c) => (c.children ? `${c.adults}A+${c.children}C` : `${c.adults}A`)),
    ["1A", "2A", "3A", "1A+1C", "1A+2C", "2A+1C", "2A+2C", "3A+1C"],
  )
  // min_adults 0 still starts at one adult; the union across rooms names the rooms that can host
  const union = validCombinations([
    { room_type: "STD", max_adults: 2, max_children: 1, max_occupants: 3, min_adults: 0 },
    { room_type: "FAM", max_adults: 2, max_children: 2, max_occupants: 4, min_adults: 2 },
  ])
  assert.deepEqual(
    union.map((c) => `${c.adults}+${c.children}:${c.rooms.join(",")}`),
    ["1+0:STD", "2+0:STD,FAM", "1+1:STD", "2+1:STD,FAM", "2+2:FAM"],
  )
})

test("persistCombination writes ordinary occupancy rules (2A+2C: Child 1 CHB ×0.5, Child 2 CHA ×0.25)", () => {
  const t = example()
  const { tables: out, counts } = persistCombination(t, {
    adults: 2,
    children: 2,
    rooms: [],
    periods: [],
    childRules: [
      { position: 1, age_band: "CHB", op: "MULTIPLY", value: "0.5" },
      { position: 2, age_band: "CHA", op: "MULTIPLY", value: "0.25" },
    ],
  })
  assert.deepEqual(counts, { removed: 0, added: 2 })
  const added = out.occupancy_rules.slice(-2)
  assert.deepEqual(
    added.map((x) => [x.target, x.position, x.age_band, x.combination, x.room_type, x.period_code, x.op, x.value, x.is_override, x.note]),
    [
      ["CHILD", 1, "CHB", "2+2", "", "", "MULTIPLY", "0.5", 0, ""],
      ["CHILD", 2, "CHA", "2+2", "", "", "MULTIPLY", "0.25", 0, ""],
    ],
  )
})

test("persistCombination: rooms × periods, adult and whole-stay rules, any children, and replacing a card", () => {
  const t = example()
  const res = persistCombination(t, {
    adults: 2,
    children: "*",
    rooms: ["STD", "DLX"],
    periods: ["P1", "P2"],
    childRules: [{ position: 1, age_band: "", op: "MULTIPLY", value: "0.5" }],
    adultRules: [{ position: 3, op: "MULTIPLY", value: "0.6" }],
    whole: { op: "ADJUST_PERCENT", value: "-5" },
  })
  assert.deepEqual(res.counts, { removed: 0, added: 12 })
  const added = res.tables.occupancy_rules.slice(-12)
  assert.ok(added.every((x) => x.combination === "2+*"))
  assert.deepEqual(
    added.filter((x) => x.target === "CHILD").map((x) => `${x.room_type}@${x.period_code}`),
    ["STD@P1", "STD@P2", "DLX@P1", "DLX@P2"],
  )
  const cards = groupCombinations(res.tables).filter((c) => c.combination === "2+*")
  assert.equal(cards.length, 1, "4 rows per rule group back into one card")
  assert.deepEqual(cards[0].rooms, ["STD", "DLX"])
  assert.deepEqual(cards[0].periods, ["P1", "P2"])
  assert.equal(cards[0].adults, 2)
  assert.equal(cards[0].children, null)
  assert.equal(cards[0].periodScoped, true)
  assert.equal(cards[0].rules.length, 3)
  // editing the card replaces exactly its rows
  const edited = persistCombination(res.tables, {
    adults: 2,
    children: "*",
    rooms: [],
    periods: [],
    childRules: [{ position: 1, age_band: "", op: "MULTIPLY", value: "0.4" }],
    replace: cards[0].keys,
  })
  assert.deepEqual(edited.counts, { removed: 12, added: 1 })
  assert.deepEqual(
    edited.tables.occupancy_rules.slice(0, t.occupancy_rules.length),
    t.occupancy_rules,
    "other rows are untouched",
  )
  assert.equal(edited.tables.occupancy_rules.length, t.occupancy_rules.length + 1)
  const removed = removeCombination(res.tables, cards[0])
  assert.deepEqual(removed.counts, { removed: 12 })
  assert.deepEqual(removed.tables.occupancy_rules, t.occupancy_rules)
})

test("groupCombinations merges a cross product into one card and splits one that is not", () => {
  const child = (room: string, period: string, value = "0.5") =>
    occ({ target: "CHILD", position: 1, age_band: "CHB", combination: "2+1", room_type: room, period_code: period, op: "MULTIPLY", value })
  const merged = groupCombinations(example([child("SUP", ""), child("STD", "")]))
  const two = merged.filter((c) => c.combination === "2+1")
  assert.equal(two.length, 1)
  assert.deepEqual(two[0].rooms, ["STD", "SUP"], "rooms in table order")
  assert.deepEqual(two[0].periods, [""])
  assert.equal(two[0].periodScoped, false)
  // STD × {P1, P2} and SUP × {P1} is not a cross product: one card per room
  const split = groupCombinations(example([child("STD", "P1"), child("STD", "P2"), child("SUP", "P1")])).filter((c) => c.combination === "2+1")
  assert.deepEqual(
    split.map((c) => `${c.rooms.join(",")}:${c.periods.join(",")}`),
    ["STD:P1,P2", "SUP:P1"],
  )
  // a different value is a different card
  const diff = groupCombinations(example([child("STD", ""), child("SUP", "", "0.6")])).filter((c) => c.combination === "2+1")
  assert.equal(diff.length, 2)
})

test("groupCombinations orders cards by adults, then children, and keeps rules the builder cannot express", () => {
  const cards = groupCombinations(
    example([
      occ({ target: "CHILD", position: 1, age_band: "CHA", combination: "2+2", op: "MULTIPLY", value: "0.25" }),
      occ({ target: "COMBINATION", combination: "3+0", op: "MULTIPLY", value: "2.5", note: "promo" }),
      occ({ target: "CHILD", position: 1, combination: "2A+1C", op: "MULTIPLY", value: "0.5" }),
    ]),
  )
  assert.deepEqual(
    cards.map((c) => c.combination),
    ["1+0", "2+1", "2+2", "3+0"],
  )
  assert.equal(cards.find((c) => c.combination === "3+0")?.expressible, false)
  assert.equal(cards.find((c) => c.combination === "2+2")?.expressible, true)
  assert.equal(canonCombination(" 2a + 1c "), "2+1")
  assert.equal(canonCombination("2+"), "2+*")
  assert.equal(canonCombination("*+1"), "*+1")
  assert.equal(canonCombination(""), "")
})

// ─── S11: the ladder on screen (§3.6, §3.11, D12) ─────────────────────────

test("ROOM basis: included positions, and extra adults priced from the header's extra unit", () => {
  const share = ladderModel(example(), null, "ROOM", { ...OPTS, includedAdults: 2, extraUnit: "PER_PERSON_SHARE" })
  assert.equal(share.basis, "ROOM")
  assert.equal(share.includedAdults, 2)
  assert.deepEqual(kinds(share), ["single", "adult1", "adult2", "adult3", "adult4", "band:INF", "band:CHA", "band:CHB"])
  for (const pos of [1, 2]) {
    const row = share.rows.find((x) => x.kind === "adult" && x.position === pos)
    assert.equal(row?.editable, false, `adult ${pos} is included`)
    assert.equal(row?.cells[""].state, "included")
  }
  const fourth = share.rows.find((x) => x.kind === "adult" && x.position === 4)
  assert.equal(fourth?.editable, true)
  assert.equal(fourth?.unit, "person_share", "the per-person share (room ÷ included adults)")
  assert.equal(fourth?.cells[""].state, "default")
  assert.deepEqual(fourth?.cells[""].value, { op: "MULTIPLY", value: "1" }, "the server's default, as served")
  assert.equal(share.rows.find((x) => x.band === "CHB")?.unit, "person_share", "children are priced from the slot unit too")
  assert.equal(share.rows[0].unit, "room", "single use replaces the room price")
  const room = ladderModel(example(), null, "ROOM", { ...OPTS, includedAdults: 2, extraUnit: "ROOM_PRICE" })
  assert.equal(room.rows.find((x) => x.kind === "adult" && x.position === 3)?.unit, "room")
  assert.equal(room.rows.find((x) => x.band === "INF")?.unit, "room")
  // an unknown or missing unit reads as the per-person share (the engine's default)
  assert.equal(ladderModel(example(), null, "ROOM", OPTS).rows.find((x) => x.position === 3)?.unit, "person_share")
  // PERSON: every row is priced from the base person price, nothing is included
  const person = ladderModel(example(), null, "PERSON", { ...OPTS, extraUnit: "ROOM_PRICE" })
  assert.equal(person.basis, "PERSON")
  assert.equal(person.includedAdults, 0)
  assert.ok(person.rows.every((x) => x.unit === "person"))
})

test("default cells carry the server's default value string, never a client constant (D12)", () => {
  const served = { adult: { rule_id: "GLOBAL:ADULT", target: "ADULT", op: "MULTIPLY", value: "1.000000000", source: "global-default", note: "" }, child: null }
  const m = ladderModel(example(), null, "PERSON", { ...OPTS, defaults: served })
  assert.deepEqual(m.rows.find((x) => x.position === 4)?.cells.P2.value, { op: "MULTIPLY", value: "1.000000000" })
  assert.deepEqual(m.rows.find((x) => x.kind === "adults_base")?.cells[""].value, { op: "MULTIPLY", value: "1.000000000" })
  const other = { adult: { ...served.adult, value: "0.9" }, child: null }
  assert.deepEqual(ladderModel(example(), null, "PERSON", { ...OPTS, defaults: other }).rows.find((x) => x.position === 4)?.cells[""].value, { op: "MULTIPLY", value: "0.9" })
  // a child default, should a server ever send one, is shown as a default too (not "missing")
  const withChild = ladderModel(example(), null, "PERSON", { ...OPTS, defaults: { adult: served.adult, child: { op: "PERCENT_OF", value: "50" } } })
  assert.deepEqual(withChild.rows.find((x) => x.band === "CHB")?.cells[""], { state: "default", rule: null, source: null, value: { op: "PERCENT_OF", value: "50" } })
})

test("inherited policy rules as served (period, adults/children) read as ladder rules", () => {
  const served = [
    { rule_id: "OR-1", target: "CHILD" as const, position: null, age_band: "CHB", adults: null, children: null, room_type: null, period: null, op: "MULTIPLY", value: "0.4", is_override: false, source: "policy:PP-1/r2/hotel" },
    { rule_id: "OR-2", target: "ADULT" as const, position: 3, age_band: null, adults: null, children: null, room_type: "SUP", period: "P2", op: "MULTIPLY", value: "0.6", is_override: true, source: "policy:PP-1/r2/hotel" },
    { rule_id: "OR-3", target: "CHILD" as const, position: 1, age_band: null, adults: 2, children: null, room_type: null, period: null, op: "MULTIPLY", value: "0.3", is_override: false, source: "policy:PP-2/r1/global" },
  ]
  const rows = served.map(fromInheritedRule)
  assert.deepEqual(
    rows.map((x) => [x.target, x.position, x.age_band, x.combination, x.room_type, x.period_code, x.op, x.value, x.is_override, x.source]),
    [
      ["CHILD", 0, "CHB", "", "", "", "MULTIPLY", "0.4", 0, "policy:PP-1/r2/hotel"],
      ["ADULT", 3, "", "", "SUP", "P2", "MULTIPLY", "0.6", 1, "policy:PP-1/r2/hotel"],
      ["CHILD", 1, "", "2+*", "", "", "MULTIPLY", "0.3", 0, "policy:PP-2/r1/global"],
    ],
  )
  const m = ladderModel(example(), null, "PERSON", { ...OPTS, inherited: rows })
  assert.equal(m.rows.find((x) => x.band === "CHB")?.cells.P1.state, "policy")
  assert.deepEqual(policySource("policy:PP-1/r2/hotel+market"), { policy: "PP-1", revision: 2, scope: "hotel+market" })
  assert.equal(policySource("version"), null)
})

test("the ladder summary: own All-periods rules of adults and children, special combinations, period overrides", () => {
  const t = example([occ({ target: "CHILD", position: 1, age_band: "CHB", combination: "2+2", op: "MULTIPLY", value: "0.5" })])
  const m = ladderModel(t, null, "PERSON", OPTS)
  const s = ladderSummary(m, groupCombinations(t))
  assert.deepEqual(
    s.adults.map((x) => `${x.kind}${x.position || ""}:${x.op}:${x.value}`),
    ["single:MULTIPLY:1.5", "adult3:MULTIPLY:0.7"],
  )
  assert.deepEqual(
    s.children.map((x) => `${x.band}:${x.value}`),
    ["INF:0", "CHA:0.25"],
  )
  assert.equal(s.combinations, 1, "the single-use row is a ladder row, not a special combination")
  assert.equal(s.periodOverrides, 1)
  const empty = ladderSummary(ladderModel(tablesOf({ periods: [r({ period_code: "P1" })] }), null, "PERSON", OPTS), [])
  assert.deepEqual(empty, { adults: [], children: [], combinations: 0, periodOverrides: 0 })
})

test("rooms scopes with rules of their own (the dot on the scope select)", () => {
  const t = example([occ({ target: "CHILD", age_band: "CHB", room_type: "SUP", op: "MULTIPLY", value: "0.5" })])
  assert.deepEqual([...scopesWithRules(t)].sort(), ["", "SUP"])
  assert.deepEqual([...scopesWithRules(tablesOf({}))], [])
})

test("applyOccRule (the ladder's rule popover): rooms × periods, Always wins and note; Remove clears the cell", () => {
  const t = example()
  const third = { target: "ADULT" as const, position: 3, age_band: "", combination: "" }
  const out = applyOccRule(t, third, ["STD", "DLX"], ["P1", "P2"], { op: "MULTIPLY", value: "0.75", is_override: true, note: "family promo" })
  const added = out.occupancy_rules.filter((x) => x.position === 3 && x.room_type)
  assert.deepEqual(
    added.map((x) => `${x.room_type}@${x.period_code}:${x.op}:${x.value}:${x.is_override}:${x.note}`),
    ["STD@P1:MULTIPLY:0.75:1:family promo", "STD@P2:MULTIPLY:0.75:1:family promo", "DLX@P1:MULTIPLY:0.75:1:family promo", "DLX@P2:MULTIPLY:0.75:1:family promo"],
  )
  // an existing cell is updated in place (its key kept), its twins removed
  const key = t.occupancy_rules[2]._key
  const twin = occ({ target: "ADULT", position: 3, period_code: "P4", op: "MULTIPLY", value: "0.9" })
  const upd = applyOccRule({ ...t, occupancy_rules: [...t.occupancy_rules, twin] }, third, [""], ["P4"], { op: "INHERIT", value: "", is_override: false, note: "" })
  const p4 = upd.occupancy_rules.filter((x) => x.position === 3 && x.period_code === "P4")
  assert.deepEqual(p4.map((x) => [x._key, x.op, x.value]), [[key, "INHERIT", ""]])
  // the same rule again changes nothing (no history entry)
  assert.equal(applyOccRule(t, third, [""], ["P4"], { op: "MULTIPLY", value: "0.80", is_override: false, note: "" }), t)
  // Remove: the cell's rows only
  const removed = applyOccRule(t, third, [""], ["P4"], null)
  assert.deepEqual(
    removed.occupancy_rules.filter((x) => x.position === 3).map((x) => x.period_code),
    [""],
  )
  assert.equal(applyOccRule(t, third, ["SUP"], ["P4"], null), t, "nothing to remove")
})

test("planOccEntries: one gesture over many ladder cells, all or nothing", () => {
  const t = example()
  const band = (code: string) => ({ target: "CHILD" as const, position: 0, age_band: code, combination: "", room_type: "" })
  const ok = planOccEntries(t, [
    { id: band("INF"), period: "", parsed: parseShorthand("x0", "occupancy") },
    { id: band("CHA"), period: "", parsed: parseShorthand("x0.25", "occupancy") },
    { id: band("CHB"), period: "", parsed: parseShorthand("x0.5", "occupancy") },
  ])
  assert.ok("tables" in ok)
  assert.deepEqual(
    ok.tables.occupancy_rules.filter((x) => x.target === "CHILD" && !x.combination).map((x) => `${x.age_band}:${x.value}`),
    ["INF:0", "CHA:0.25", "CHB:0.5"],
  )
  const bad = planOccEntries(t, [
    { id: band("CHA"), period: "", parsed: parseShorthand("x0.3", "occupancy") },
    { id: band("CHB"), period: "", parsed: parseShorthand("1.500", "occupancy") },
  ])
  assert.deepEqual(bad, { error: "AMBIGUOUS", index: 1 })
  // the same entry twice changes nothing
  const same = planOccEntries(t, [{ id: band("CHA"), period: "", parsed: parseShorthand("x0.25", "occupancy") }])
  assert.ok("tables" in same)
  assert.equal(same.tables, t)
})

test("occReadingOf: what a ladder entry stores, for the reading line", () => {
  const t = example()
  const third = { target: "ADULT" as const, position: 3, age_band: "", combination: "", room_type: "" }
  assert.deepEqual(occReadingOf(t, third, "", parseShorthand("x0.7", "occupancy")), { kind: "unchanged" })
  assert.deepEqual(occReadingOf(t, third, "P1", parseShorthand("x0.75", "occupancy")), { kind: "rule", op: "MULTIPLY", value: "0.75" })
  assert.deepEqual(occReadingOf(t, third, "P4", parseShorthand("", "occupancy")), { kind: "clear", follows: { op: "MULTIPLY", value: "0.7" } })
  assert.deepEqual(occReadingOf(t, third, "", parseShorthand("", "occupancy")), { kind: "clear", follows: null })
  assert.deepEqual(occReadingOf(t, third, "", parseShorthand("abc", "occupancy")), { kind: "error", code: "SYNTAX" })
  assert.deepEqual(occReadingOf(t, third, "", parseShorthand("1.500", "occupancy", { minorUnits: 3 })), { kind: "rule", op: "ABSOLUTE", value: "1.5" })
  assert.deepEqual(occReadingOf(t, third, "P2", parseShorthand("", "occupancy")), { kind: "unchanged" }, "nothing to clear")
})

test("occEditText: the cell's own rule as occupancy shorthand; empty without one", () => {
  const m = ladderModel(example(), null, "PERSON", OPTS)
  const third = m.rows.find((x) => x.position === 3)
  assert.equal(occEditText(third?.cells[""], { decimalMark: "," }), "x0,7")
  assert.equal(occEditText(third?.cells.P1), "", "a period that follows all periods")
  assert.equal(occEditText(m.rows.find((x) => x.position === 4)?.cells[""]), "", "a default")
  const fixed = ladderModel(example([occ({ target: "ADULT", position: 4, op: "FIXED", value: "25" })]), null, "PERSON", OPTS)
  assert.equal(occEditText(fixed.rows.find((x) => x.position === 4)?.cells[""]), "=25")
})

test("the precedence note: a special combination prices the same slot as a ladder cell", () => {
  const t = example([
    occ({ target: "CHILD", position: 1, age_band: "CHB", combination: "2+2", op: "MULTIPLY", value: "0.5" }),
    occ({ target: "CHILD", position: 2, age_band: "CHA", combination: "2+2", room_type: "DLX", period_code: "P2", op: "MULTIPLY", value: "0.25" }),
    occ({ target: "ADULT", position: 3, period_code: "P3", op: "MULTIPLY", value: "0.6", is_override: 1 }),
  ])
  const cards = groupCombinations(t)
  const all = ladderModel(t, null, "PERSON", OPTS)
  const notes = combinationNotes(all, cards, null)
  const chb = all.rows.find((x) => x.band === "CHB")
  const cha = all.rows.find((x) => x.band === "CHA")
  assert.ok(chb && cha)
  assert.equal(notes.get(`${chb.id}|P1`)?.length, 1)
  assert.equal(notes.get(`${cha.id}|P1`), undefined, "the CHA card is scoped to P2")
  assert.equal(notes.get(`${cha.id}|P2`)?.length, 1)
  assert.equal(notes.get(`${cha.id}|`)?.length, 1, "the All-periods column holds for every period")
  assert.equal(notes.get(`${all.rows.find((x) => x.position === 3)?.id}|P3`), undefined, "no card prices adult 3")
  assert.equal(notes.get(`${all.rows[0].id}|`), undefined, "the single-use row is itself a combination")
  // a room scope: the DLX-only card does not reach the SUP scope
  const sup = ladderModel(t, "SUP", "PERSON", OPTS)
  const supNotes = combinationNotes(sup, cards, "SUP")
  assert.equal(supNotes.get(`${sup.rows.find((x) => x.band === "CHA")?.id}|P2`), undefined)
  assert.equal(supNotes.get(`${sup.rows.find((x) => x.band === "CHB")?.id}|P2`)?.length, 1)
  // "Always wins" beats special combinations: no note on such a cell
  const always = example([
    occ({ target: "ADULT", position: 3, combination: "3+0", op: "MULTIPLY", value: "0.5" }),
    occ({ target: "ADULT", position: 3, period_code: "P3", op: "MULTIPLY", value: "0.6", is_override: 1 }),
  ])
  const am = ladderModel(always, null, "PERSON", OPTS)
  const an = combinationNotes(am, groupCombinations(always), null)
  const third = am.rows.find((x) => x.position === 3)
  assert.equal(an.get(`${third?.id}|P3`), undefined)
  assert.equal(an.get(`${third?.id}|P2`)?.length, 1)
})

test("sample parties: the valid combinations of the room, children at their bands", () => {
  const cap = { room_type: "STD", max_adults: 2, max_children: 2, max_occupants: 3, min_adults: 1 }
  const opts = partyOptions(cap, BANDS)
  assert.deepEqual(
    opts.map((p) => `${p.adults}+${p.children.join(",")}`),
    ["1+", "2+", "1+INF", "1+CHA", "1+CHB", "1+INF,INF", "1+INF,CHA", "1+INF,CHB", "1+CHA,CHA", "1+CHA,CHB", "1+CHB,CHB", "2+INF", "2+CHA", "2+CHB"],
  )
  assert.equal(opts[1].id, "2+")
  assert.equal(defaultParty(opts)?.id, "2+", "two adults when the room takes them")
  assert.equal(defaultParty(partyOptions({ ...cap, max_adults: 1 }, BANDS))?.id, "1+")
  assert.deepEqual(partyOptions({ ...cap, max_children: 1 }, []).map((p) => p.id), ["1+", "2+"], "no bands: adults only")
  assert.ok(partyOptions({ max_adults: 4, max_children: 4, max_occupants: 8, min_adults: 1 }, BANDS).length <= PARTY_OPTIONS_MAX)
})

// ─── S11 review: what prices a slot in a room scope (the engine's ranking, D12) ──────────

const cellOf = (m: ReturnType<typeof ladderModel>, pick: (row: ReturnType<typeof ladderModel>["rows"][number]) => boolean, period: string) => {
  const row = m.rows.find(pick)
  assert.ok(row, "row")
  return row.cells[period]
}
const summary = (c: { state: string; value: { op: string; value: string } | null } | undefined) => (c ? `${c.state}${c.value ? ` ${c.value.op} ${c.value.value}` : ""}` : "none")

test("a room scope: slots priced only by All-rooms rules show them, not the default or 'not sellable'", () => {
  // the verifier's probe: All-rooms rules for adult 3 (×0.7), INF (×0) and CHA (×0.5), seen from SUP
  const t = tablesOf({
    rooms: [r({ room_type: "STD", is_base: 1 }), r({ room_type: "SUP", is_base: 0 })],
    periods: [r({ period_code: "P1" })],
    occupancy_rules: [
      occ({ target: "ADULT", position: 3, op: "MULTIPLY", value: "0.7" }),
      occ({ target: "CHILD", age_band: "INF", op: "MULTIPLY", value: "0" }),
      occ({ target: "CHILD", age_band: "CHA", op: "MULTIPLY", value: "0.5" }),
    ],
  })
  const sup = ladderModel(t, "SUP", "PERSON", OPTS)
  for (const p of ["", "P1"]) {
    assert.equal(summary(cellOf(sup, (x) => x.kind === "adult" && x.position === 3, p)), "all-rooms MULTIPLY 0.7", p)
    assert.equal(summary(cellOf(sup, (x) => x.band === "INF", p)), "all-rooms MULTIPLY 0", p)
    assert.equal(summary(cellOf(sup, (x) => x.band === "CHA", p)), "all-rooms MULTIPLY 0.5", p)
    // no rule of any scope prices these
    assert.equal(summary(cellOf(sup, (x) => x.band === "CHB", p)), "missing", p)
    assert.equal(summary(cellOf(sup, (x) => x.kind === "adult" && x.position === 4, p)), "default MULTIPLY 1", p)
    assert.equal(summary(cellOf(sup, (x) => x.kind === "single", p)), "default MULTIPLY 1", p)
  }
  const inf = cellOf(sup, (x) => x.band === "INF", "")
  assert.equal(inf.rule, null)
  assert.equal(inf.source?.room_type, "", "the source is the All-rooms row")
  // the rows still write the room's own rules
  assert.equal(sup.rows.find((x) => x.band === "INF")?.identity?.room_type, "SUP")
  // the All rooms scope is unchanged
  const all = ladderModel(t, null, "PERSON", OPTS)
  assert.equal(summary(cellOf(all, (x) => x.band === "INF", "P1")), "inherited MULTIPLY 0")
  assert.equal(summary(cellOf(all, (x) => x.band === "CHB", "P1")), "missing")
})

test("a room scope: the owner's example seen from Superior (single use, adult 3 with its P4 override, the bands)", () => {
  const sup = ladderModel(example(), "SUP", "PERSON", OPTS)
  assert.deepEqual(kinds(sup), ["single", "adults_base", "adult3", "adult4", "band:INF", "band:CHA", "band:CHB"])
  assert.equal(summary(cellOf(sup, (x) => x.kind === "single", "P2")), "all-rooms MULTIPLY 1.5")
  assert.equal(summary(cellOf(sup, (x) => x.position === 3, "P1")), "all-rooms MULTIPLY 0.7")
  assert.equal(summary(cellOf(sup, (x) => x.position === 3, "P4")), "all-rooms MULTIPLY 0.8", "the All-rooms P4 rule")
  assert.equal(summary(cellOf(sup, (x) => x.band === "CHA", "P3")), "all-rooms MULTIPLY 0.25")
  assert.equal(summary(cellOf(sup, (x) => x.kind === "adults_base", "")), "default MULTIPLY 1")
  assert.equal(sup.counts.periodOverrides, 0, "SUP has no period rule of its own")
  // All-rooms rules shape the room scope's rows too: a position-1 rule splits the BASE pair, an
  // every-adult rule and a child position rule get their rows
  const more = ladderModel(
    example([
      occ({ target: "ADULT", position: 1, op: "MULTIPLY", value: "1.1" }),
      occ({ target: "ADULT", op: "MULTIPLY", value: "0.95" }),
      occ({ target: "CHILD", position: 2, age_band: "CHB", op: "MULTIPLY", value: "0.4" }),
    ]),
    "SUP",
    "PERSON",
    OPTS,
  )
  assert.deepEqual(kinds(more), ["single", "adult1", "adult2", "adult3", "adult4", "adult_any", "band:INF", "band:CHA", "band:CHB", "child2"])
  assert.equal(summary(cellOf(more, (x) => x.kind === "adult" && x.position === 1, "")), "all-rooms MULTIPLY 1.1")
  assert.equal(summary(cellOf(more, (x) => x.kind === "adult" && x.position === 2, "")), "all-rooms MULTIPLY 0.95", "the every-adult rule of All rooms")
  assert.equal(more.rows.find((x) => x.kind === "child")?.identity?.room_type, "SUP")
  // the "also with children" single-use variant of All rooms is the room's single-use row too
  const alt = tablesOf({ periods: [r({ period_code: "P1" })], occupancy_rules: [occ({ target: "ADULT", position: 1, combination: "1+*", op: "MULTIPLY", value: "1.4" })] })
  const altSup = ladderModel(alt, "SUP", "PERSON", OPTS)
  assert.deepEqual(altSup.rows[0].identity, { target: "ADULT", position: 1, age_band: "", combination: "1+*", room_type: "SUP" })
  assert.equal(summary(altSup.rows[0].cells.P1), "all-rooms MULTIPLY 1.4")
})

test("a room scope ranks like the engine: own rule, then period before room before All rooms (occupancy precedence v2)", () => {
  const sup = ladderModel(
    example([
      occ({ target: "ADULT", position: 3, room_type: "SUP", op: "MULTIPLY", value: "0.9" }),
      occ({ target: "CHILD", age_band: "CHB", room_type: "SUP", op: "MULTIPLY", value: "0.5" }),
      occ({ target: "ADULT", room_type: "SUP", op: "MULTIPLY", value: "0.95" }),
      occ({ target: "ADULT", position: 4, period_code: "P2", op: "MULTIPLY", value: "0.85" }),
    ]),
    "SUP",
    "PERSON",
    OPTS,
  )
  assert.equal(summary(cellOf(sup, (x) => x.position === 3, "")), "rule MULTIPLY 0.9")
  assert.equal(summary(cellOf(sup, (x) => x.position === 3, "P1")), "inherited MULTIPLY 0.9")
  // a period rule (All rooms, P4) outranks the room's all-periods rule (level PERIOD > ROOM)
  assert.equal(summary(cellOf(sup, (x) => x.position === 3, "P4")), "all-rooms MULTIPLY 0.8")
  assert.equal(summary(cellOf(sup, (x) => x.band === "CHB", "P1")), "inherited MULTIPLY 0.5")
  // the room's every-adult rule beats the engine default and All rooms' all-periods rules…
  assert.equal(summary(cellOf(sup, (x) => x.position === 4, "P1")), "general MULTIPLY 0.95")
  // …but not an All-rooms period rule of the slot
  assert.equal(summary(cellOf(sup, (x) => x.position === 4, "P2")), "all-rooms MULTIPLY 0.85")
  // an own INHERIT row says what applies instead
  const inh = ladderModel(example([occ({ target: "CHILD", age_band: "CHA", room_type: "SUP", op: "INHERIT", value: "" })]), "SUP", "PERSON", OPTS)
  const cha = cellOf(inh, (x) => x.band === "CHA", "")
  assert.equal(summary(cha), "inherit-rule MULTIPLY 0.25")
  assert.equal(cha.rule?.op, "INHERIT")
  // "Always wins" of All rooms beats the room's all-periods rule in a period
  const wins = ladderModel(
    example([occ({ target: "ADULT", position: 3, room_type: "SUP", op: "MULTIPLY", value: "0.9" }), occ({ target: "ADULT", position: 3, period_code: "P2", op: "MULTIPLY", value: "0.6", is_override: 1 })]),
    "SUP",
    "PERSON",
    OPTS,
  )
  assert.equal(summary(cellOf(wins, (x) => x.position === 3, "P2")), "all-rooms MULTIPLY 0.6")
})

test("policy rules: a version rule of All rooms beats a room's policy rule (origin first), and All-rooms policy rules reach a room", () => {
  const inherited = [
    fromInheritedRule({ rule_id: "OR-1", target: "CHILD", position: null, age_band: "CHB", adults: null, children: null, room_type: null, period: null, op: "MULTIPLY", value: "0.4", is_override: false, source: "policy:PP-1/r2/hotel" }),
    fromInheritedRule({ rule_id: "OR-2", target: "CHILD", position: null, age_band: "CHA", adults: null, children: null, room_type: "SUP", period: null, op: "MULTIPLY", value: "0.3", is_override: false, source: "policy:PP-1/r2/hotel" }),
    fromInheritedRule({ rule_id: "OR-3", target: "ADULT", position: 4, age_band: null, adults: null, children: null, room_type: null, period: null, op: "MULTIPLY", value: "0.8", is_override: false, source: "policy:PP-2/r1/global" }),
    fromInheritedRule({ rule_id: "OR-4", target: "ADULT", position: 4, age_band: null, adults: null, children: null, room_type: null, period: null, op: "MULTIPLY", value: "0.75", is_override: false, source: "policy:PP-3/r1/market" }),
  ]
  const sup = ladderModel(example(), "SUP", "PERSON", { ...OPTS, inherited })
  const chb = cellOf(sup, (x) => x.band === "CHB", "P1")
  assert.equal(summary(chb), "policy MULTIPLY 0.4")
  assert.equal(chb.source?.room_type, "")
  assert.equal(summary(cellOf(sup, (x) => x.band === "CHA", "P1")), "all-rooms MULTIPLY 0.25", "a version rule beats any policy rule")
  assert.equal(summary(cellOf(sup, (x) => x.position === 4, "")), "policy MULTIPLY 0.75", "a market policy outranks a global one")
  // the All rooms scope does not see the SUP policy rule
  const all = ladderModel(example(), null, "PERSON", { ...OPTS, inherited })
  assert.equal(summary(cellOf(all, (x) => x.band === "CHA", "P1")), "inherited MULTIPLY 0.25")
  assert.equal(summary(cellOf(all, (x) => x.band === "CHB", "P1")), "policy MULTIPLY 0.4")
})

test("a policy rule served without its formula (a viewer without cost, S16 review) still ranks and names its source, without a value", () => {
  const hidden = { adults: null, children: null, room_type: null, period: null, op: null, value: null, is_override: false, hidden: true }
  const inherited = [
    fromInheritedRule({ ...hidden, rule_id: "OR-1", target: "CHILD", position: null, age_band: "CHB", source: "policy:PP-1/r2/hotel" }),
    fromInheritedRule({ ...hidden, rule_id: "OR-3", target: "ADULT", position: 4, age_band: null, source: "policy:PP-2/r1/global" }),
  ]
  assert.deepEqual([inherited[0].op, inherited[0].value, inherited[0].hidden], ["", "", 1])
  const m = ladderModel(example(), null, "PERSON", { ...OPTS, inherited })
  const chb = cellOf(m, (x) => x.band === "CHB", "P1")
  assert.equal(chb.state, "policy")
  assert.equal(chb.value, null, "no op or value to show")
  assert.equal(chb.source?.source, "policy:PP-1/r2/hotel")
  const fourth = cellOf(m, (x) => x.position === 4, "")
  assert.deepEqual([fourth.state, fourth.value], ["policy", null])
  // a version rule still wins over it, as over any policy rule
  const cha = [fromInheritedRule({ ...hidden, rule_id: "OR-2", target: "CHILD", position: null, age_band: "CHA", source: "policy:PP-1/r2/hotel" })]
  assert.equal(summary(cellOf(ladderModel(example(), null, "PERSON", { ...OPTS, inherited: cha }), (x) => x.band === "CHA", "P1")), "inherited MULTIPLY 0.25")
})

test("an infant is priced by a rule naming its band before any band-less rule (G-31)", () => {
  const t = example([occ({ target: "CHILD", room_type: "SUP", op: "MULTIPLY", value: "0.5" })])
  const sup = ladderModel(t, "SUP", "PERSON", OPTS)
  assert.equal(sup.rows.find((x) => x.band === "INF")?.infant, true)
  assert.equal(sup.rows.find((x) => x.band === "CHA")?.infant, false)
  assert.equal(summary(cellOf(sup, (x) => x.band === "INF", "P1")), "all-rooms MULTIPLY 0", "the INF rule of All rooms, not the room's band-less rule")
  assert.equal(summary(cellOf(sup, (x) => x.band === "CHA", "P1")), "general MULTIPLY 0.5", "a room rule outranks All rooms for a child who is not an infant")
  assert.equal(summary(cellOf(sup, (x) => x.band === "CHB", "P1")), "general MULTIPLY 0.5")
  // a policy rule naming the infant's band beats the version's band-less rule
  const noInf = { ...example(), occupancy_rules: example().occupancy_rules.filter((x) => x.age_band !== "INF") }
  const pol = [fromInheritedRule({ rule_id: "OR-9", target: "CHILD", position: null, age_band: "INF", adults: null, children: null, room_type: null, period: null, op: "MULTIPLY", value: "0.1", is_override: false, source: "policy:PP-1/r2/hotel" })]
  const all = ladderModel({ ...noInf, occupancy_rules: [...noInf.occupancy_rules, occ({ target: "CHILD", op: "MULTIPLY", value: "0.5" })] }, null, "PERSON", { ...OPTS, inherited: pol })
  assert.equal(summary(cellOf(all, (x) => x.band === "INF", "P1")), "policy MULTIPLY 0.1")
  assert.equal(summary(cellOf(all, (x) => x.band === "CHA", "P1")), "inherited MULTIPLY 0.25")
})

test("the precedence note: a band-less combination rule does not outrank an infant's band rule (G-31)", () => {
  const t = example([occ({ target: "CHILD", position: 1, combination: "2+1", op: "MULTIPLY", value: "0.2" })])
  const m = ladderModel(t, null, "PERSON", OPTS)
  const notes = combinationNotes(m, groupCombinations(t), null)
  const id = (band: string) => m.rows.find((x) => x.band === band)?.id
  assert.equal(notes.get(`${id("INF")}|P1`), undefined, "the infant is priced by its INF rule")
  assert.equal(notes.get(`${id("CHA")}|P1`)?.length, 1)
  assert.equal(notes.get(`${id("CHB")}|P1`)?.length, 1, "a band without a rule: the combination prices it")
  // an infant band without a rule of its own: the band-less combination rule does price it
  const bare = example([occ({ target: "CHILD", position: 1, combination: "2+1", op: "MULTIPLY", value: "0.2" })])
  bare.occupancy_rules = bare.occupancy_rules.filter((x) => x.age_band !== "INF")
  const bm = ladderModel(bare, null, "PERSON", OPTS)
  assert.equal(combinationNotes(bm, groupCombinations(bare), null).get(`${bm.rows.find((x) => x.band === "INF")?.id}|P1`)?.length, 1)
  // a combination rule naming the infant's band still outranks it
  const named = example([occ({ target: "CHILD", position: 1, age_band: "INF", combination: "2+1", op: "MULTIPLY", value: "0" })])
  const nm = ladderModel(named, null, "PERSON", OPTS)
  assert.equal(combinationNotes(nm, groupCombinations(named), null).get(`${nm.rows.find((x) => x.band === "INF")?.id}|P1`)?.length, 1)
})

test("sample parties stay within the server's limits and keep the common ones when the list is capped", () => {
  const big = { room_type: "VIL", max_adults: 14, max_children: 10, max_occupants: 24, min_adults: 1 }
  const opts = partyOptions(big, BANDS)
  assert.ok(opts.length <= PARTY_OPTIONS_MAX)
  assert.ok(opts.every((p) => p.adults <= PARTY_ADULTS_MAX && p.children.length <= PARTY_CHILDREN_MAX), "price_matrix refuses more")
  assert.equal(PARTY_ADULTS_MAX, 12)
  assert.equal(PARTY_CHILDREN_MAX, 8)
  const ids = opts.map((p) => p.id)
  for (const id of ["1+", "2+", "12+", "2+INF", "2+CHB", "1+CHA", "2+INF,CHB", "2+CHA,CHB", "2+CHB,CHB", "3+CHB"]) assert.ok(ids.includes(id), id)
  // shown in the usual order: adults only, then by adults and children
  const order = (p: { adults: number; children: string[] }) => [p.children.length > 0 ? 1 : 0, p.adults, p.children.length]
  for (let i = 1; i < opts.length; i++) {
    const [a, b] = [order(opts[i - 1]), order(opts[i])]
    assert.ok(a[0] < b[0] || (a[0] === b[0] && (a[1] < b[1] || (a[1] === b[1] && a[2] <= b[2]))), `${opts[i - 1].id} before ${opts[i].id}`)
  }
  assert.equal(defaultParty(opts)?.id, "2+")
  // a room within the limits and the cap keeps every party
  assert.equal(partyOptions({ max_adults: 2, max_children: 2, max_occupants: 4, min_adults: 1 }, BANDS).length, 2 + 3 + 6 + 3 + 6)
})

// ─── S12: the special combination builder and its cards (§3.7) ────────────

const MU = { minorUnits: 2 }
const line = (patch: Partial<BuilderLine>): BuilderLine => ({ id: `t${++seq}`, position: 1, age_band: "", op: "MULTIPLY", text: "", ...patch })

test("builder values: a form sets the rule, a number alone takes the rule chosen, FIXED stays FIXED", () => {
  // occupancy shorthand chooses the rule (§3.4.4)
  assert.deepEqual(readBuilderValue("x0.5", "PERCENT_OF", 2), { kind: "rule", op: "MULTIPLY", value: "0.5" })
  assert.deepEqual(readBuilderValue("50%", "MULTIPLY", 2), { kind: "rule", op: "PERCENT_OF", value: "50" })
  assert.deepEqual(readBuilderValue("-10%", "MULTIPLY", 2), { kind: "rule", op: "ADJUST_PERCENT", value: "-10" })
  assert.deepEqual(readBuilderValue("+25", "MULTIPLY", 2), { kind: "rule", op: "ADD", value: "25" })
  assert.deepEqual(readBuilderValue("-25", "MULTIPLY", 2), { kind: "rule", op: "SUBTRACT", value: "25" })
  assert.deepEqual(readBuilderValue("=25", "MULTIPLY", 2), { kind: "rule", op: "ABSOLUTE", value: "25" })
  assert.deepEqual(readBuilderValue("=25", "FIXED", 2), { kind: "rule", op: "FIXED", value: "25" }, "FIXED has no shorthand of its own")
  // a number alone is the value of the rule chosen (the mock's "Rule [Multiply] Value [0.50]")
  assert.deepEqual(readBuilderValue("0,50", "MULTIPLY", 2), { kind: "rule", op: "MULTIPLY", value: "0.5" })
  assert.deepEqual(readBuilderValue(" 25 ", "FIXED", 2), { kind: "rule", op: "FIXED", value: "25" })
  assert.deepEqual(readBuilderValue("10", "ADJUST_PERCENT", 2), { kind: "rule", op: "ADJUST_PERCENT", value: "10" })
  // amounts keep the AMBIGUOUS guard (O5); factors do not
  assert.deepEqual(readBuilderValue("1.500", "ABSOLUTE", 2), { kind: "error", code: "AMBIGUOUS" })
  assert.deepEqual(readBuilderValue("1.500", "ABSOLUTE", 3), { kind: "rule", op: "ABSOLUTE", value: "1.5" })
  assert.deepEqual(readBuilderValue("1.500", "MULTIPLY", 2), { kind: "rule", op: "MULTIPLY", value: "1.5" })
  assert.deepEqual(readBuilderValue("", "MULTIPLY", 2), { kind: "empty" })
  assert.deepEqual(readBuilderValue("2+2", "MULTIPLY", 2), { kind: "error", code: "SYNTAX" })
  assert.deepEqual(readBuilderValue("", "INHERIT", 2), { kind: "rule", op: "INHERIT", value: "" })
  // what a field shows for a stored rule reads back to that rule
  const cases: [string, string][] = [
    ["MULTIPLY", "0.5"],
    ["PERCENT_OF", "50"],
    ["ADJUST_PERCENT", "10"],
    ["ADJUST_PERCENT", "-5"],
    ["ADD", "25"],
    ["SUBTRACT", "25"],
    ["ABSOLUTE", "12.345"],
    ["FIXED", "245"],
  ]
  for (const [op, value] of cases) {
    const text = builderValueText(op, value, { minorUnits: 2 })
    assert.deepEqual(readBuilderValue(text, op, 2), { kind: "rule", op, value }, `${op} ${value} → ${text}`)
  }
  assert.equal(builderValueText("MULTIPLY", "0.500000000", { minorUnits: 2 }), "0.5")
  assert.equal(builderValueText("MULTIPLY", "0.5", { minorUnits: 2, decimalMark: "," }), "0,5")
  assert.equal(builderValueText("ADJUST_PERCENT", "-5", { minorUnits: 2 }), "-5", "signed, beside the Rule's % sign")
  assert.equal(builderValueText("ADD", "-5", { minorUnits: 2 }), "-5", "in its shorthand, which reads as SUBTRACT 5: builderCanEdit keeps such a card out of the builder")
  assert.equal(builderValueText("ABSOLUTE", "12.345", { minorUnits: 2 }), "12.3450", "not refused as AMBIGUOUS when read back")
  assert.equal(builderValueText("INHERIT", "", { minorUnits: 2 }), "")
})

test("the builder writes 2A+2C (Child 1 7–11.99 ×0.50, Child 2 3–6.99 ×0.25) as ordinary occupancy rules", () => {
  const t = example()
  const draft = ensureChildLines({ ...newBuilderDraft(), adults: 2, children: 2 })
  assert.deepEqual(shownChildPositions(draft), [1, 2])
  assert.deepEqual(draft.childLines.map((x) => [x.position, x.age_band, x.op, x.text]), [
    [1, "", "MULTIPLY", ""],
    [2, "", "MULTIPLY", ""],
  ])
  const empty = planCombination(t, draft, MU)
  assert.deepEqual(empty.issues, [{ code: "NO_RULES" }])
  assert.equal(empty.spec, null)
  const filled: BuilderDraft = {
    ...draft,
    childLines: [
      { ...draft.childLines[0], age_band: "CHB", text: "x0.5" },
      { ...draft.childLines[1], age_band: "cha", text: "0.25" },
    ],
  }
  const plan = planCombination(t, filled, MU)
  assert.deepEqual(plan.issues, [])
  assert.equal(plan.combination, "2+2")
  assert.deepEqual(plan.rules.map((x) => [x.target, x.position, x.age_band, x.op, x.value]), [
    ["CHILD", 1, "CHB", "MULTIPLY", "0.5"],
    ["CHILD", 2, "CHA", "MULTIPLY", "0.25"],
  ])
  assert.ok(plan.spec)
  const out = persistCombination(t, plan.spec).tables
  assert.deepEqual(
    out.occupancy_rules.slice(t.occupancy_rules.length).map((x) => [x.target, x.position, x.age_band, x.combination, x.room_type, x.period_code, x.op, x.value, x.is_override, x.note]),
    [
      ["CHILD", 1, "CHB", "2+2", "", "", "MULTIPLY", "0.5", 0, ""],
      ["CHILD", 2, "CHA", "2+2", "", "", "MULTIPLY", "0.25", 0, ""],
    ],
  )
  const card = groupCombinations(out).find((c) => c.combination === "2+2")
  assert.ok(card)
  assert.equal(card.expressible, true)
  assert.equal(isSingleUseCard(card), false)
})

test("editing a card replaces exactly its rows; saving it unchanged gives the same card back", () => {
  const t = example([
    occ({ target: "CHILD", position: 1, age_band: "CHB", combination: "2+2", op: "MULTIPLY", value: "0.5" }),
    occ({ target: "CHILD", position: 2, age_band: "CHA", combination: "2+2", op: "MULTIPLY", value: "0.25" }),
    occ({ target: "CHILD", position: 1, combination: "2+1", room_type: "DLX", op: "PERCENT_OF", value: "40" }),
  ])
  const card = groupCombinations(t).find((c) => c.combination === "2+2")
  assert.ok(card)
  const draft = builderFromCard(card, MU)
  assert.ok(draft)
  assert.deepEqual([draft.adults, draft.children, draft.roomsAll, draft.periodsAll, draft.isOverride], [2, 2, true, true, false])
  assert.deepEqual(draft.replace, card.keys)
  assert.deepEqual(draft.childLines.map((x) => [x.position, x.age_band, x.op, x.text]), [
    [1, "CHB", "MULTIPLY", "0.5"],
    [2, "CHA", "MULTIPLY", "0.25"],
  ])
  // unchanged: the same card (content), other rows untouched
  const same = planCombination(t, draft, MU)
  assert.deepEqual(same.issues, [], "a card never conflicts with its own rows")
  assert.ok(same.spec)
  const again = persistCombination(t, same.spec).tables
  assert.deepEqual(groupCombinations(again).map((c) => c.id), groupCombinations(t).map((c) => c.id))
  // child 2 becomes ×0.30: exactly the card's two rows go, two new ones come
  const edited = planCombination(t, { ...draft, childLines: draft.childLines.map((x) => (x.position === 2 ? { ...x, text: "x0.3" } : x)) }, MU)
  assert.ok(edited.spec)
  const res = persistCombination(t, edited.spec)
  assert.deepEqual(res.counts, { removed: 2, added: 2 })
  const others = (rows: Row[]) => rows.filter((x) => !card.keys.includes(x._key))
  assert.deepEqual(res.tables.occupancy_rules.slice(0, -res.counts.added), others(t.occupancy_rules), "every other row is untouched, in order")
  assert.ok(res.tables.occupancy_rules.every((x) => !card.keys.includes(x._key)))
  const now = groupCombinations(res.tables).find((c) => c.combination === "2+2")
  assert.deepEqual(now?.rules.map((x) => [x.position, x.age_band, x.value]), [
    [1, "CHB", "0.5"],
    [2, "CHA", "0.3"],
  ])
  assert.equal(cardOfRow(groupCombinations(res.tables), res.tables.occupancy_rules.at(-1)?._key ?? ""), now?.id, "the card that holds a row (Show in grid)")
  assert.equal(cardOfRow(groupCombinations(res.tables), "nope"), null)
})

test("the any-children card '2+*' and the any-adults card '*+1' (under More)", () => {
  const t = example()
  const d = ensureChildLines({ ...newBuilderDraft(), adults: 2, children: "*" as const, anyChildren: 1 })
  assert.deepEqual(shownChildPositions(d), [1], "any children: the child positions the user asked for")
  const plan = planCombination(t, { ...d, childLines: [{ ...d.childLines[0], text: "x0.5" }] }, MU)
  assert.deepEqual(plan.issues, [])
  assert.equal(plan.combination, "2+*")
  const out = persistCombination(t, plan.spec as NonNullable<typeof plan.spec>).tables
  const card = groupCombinations(out).find((c) => c.combination === "2+*")
  assert.ok(card)
  assert.equal(card.children, null)
  const back = builderFromCard(card, MU)
  assert.equal(back?.children, "*")
  assert.equal(back?.anyChildren, 1)
  // two child positions of any children
  const two = ensureChildLines({ ...d, anyChildren: 2 })
  assert.deepEqual(shownChildPositions(two), [1, 2])
  // any adults with one child
  const anyA = planCombination(t, ensureChildLines({ ...newBuilderDraft(), adults: "*" as const, children: 1, whole: line({ position: 0, op: "ADJUST_PERCENT", text: "-10%" }) }), MU)
  assert.deepEqual(anyA.issues, [])
  assert.equal(anyA.combination, "*+1")
  assert.deepEqual(anyA.spec?.whole, { op: "ADJUST_PERCENT", value: "-10" })
  // "any adults + any children" is no combination at all (OCC_COMBINATION_QUALIFIER)
  const both = planCombination(t, { ...newBuilderDraft(), adults: "*", children: "*", whole: line({ position: 0, text: "x2" }) }, MU)
  assert.deepEqual(both.issues, [{ code: "ANY_BOTH" }])
})

test("rooms {STD, DLX} × periods {P1, P2}: 4 rows per rule that group back into one card", () => {
  const t = example()
  const d = ensureChildLines({ ...newBuilderDraft(), adults: 3, children: 1, roomsAll: false, rooms: ["DLX", "STD"], periodsAll: false, periods: ["P2", "P1"] })
  const plan = planCombination(
    t,
    {
      ...d,
      childLines: [{ ...d.childLines[0], age_band: "CHB", text: "50%" }],
      adultLines: [line({ position: 3, text: "0.6" })],
      whole: line({ position: 0, op: "ADJUST_PERCENT", text: "-5" }),
    },
    MU,
  )
  assert.deepEqual(plan.issues, [])
  assert.deepEqual(plan.spec?.rooms, ["STD", "DLX"], "in table order")
  assert.deepEqual(plan.spec?.periods, ["P1", "P2"])
  const res = persistCombination(t, plan.spec as NonNullable<typeof plan.spec>)
  assert.deepEqual(res.counts, { removed: 0, added: 12 })
  const added = res.tables.occupancy_rules.slice(t.occupancy_rules.length)
  for (const target of ["CHILD", "ADULT", "COMBINATION"]) {
    assert.deepEqual(
      added.filter((x) => x.target === target).map((x) => `${x.room_type}@${x.period_code}`),
      ["STD@P1", "STD@P2", "DLX@P1", "DLX@P2"],
      target,
    )
  }
  const cards = groupCombinations(res.tables).filter((c) => c.combination === "3+1")
  assert.equal(cards.length, 1)
  assert.deepEqual([cards[0].rooms, cards[0].periods, cards[0].periodScoped], [["STD", "DLX"], ["P1", "P2"], true])
  assert.deepEqual(cards[0].rules.map((x) => [x.target, x.position, x.age_band, x.op, x.value]), [
    ["ADULT", 3, "", "MULTIPLY", "0.6"],
    ["CHILD", 1, "CHB", "PERCENT_OF", "50"],
    ["COMBINATION", 0, "", "ADJUST_PERCENT", "-5"],
  ])
  // the card opens in the builder as it was saved
  const back = builderFromCard(cards[0], MU)
  assert.ok(back)
  assert.deepEqual([back.roomsAll, back.rooms, back.periodsAll, back.periods], [false, ["STD", "DLX"], false, ["P1", "P2"]])
  assert.deepEqual(back.adultLines.map((x) => [x.position, x.op, x.text]), [[3, "MULTIPLY", "0.6"]])
  assert.deepEqual([back.whole?.op, back.whole?.text], ["ADJUST_PERCENT", "-5"])
})

test("the builder refuses what the server would refuse or ignore, and never a free-text combination", () => {
  const t = example([occ({ target: "CHILD", position: 1, age_band: "CHB", combination: "2+2", op: "MULTIPLY", value: "0.5" })])
  const base = ensureChildLines({ ...newBuilderDraft(), adults: 2, children: 2 })
  const [c1, c2] = base.childLines
  // a value the parser refuses stays on its line
  const bad = planCombination(t, { ...base, childLines: [{ ...c1, text: "abc" }, c2] }, MU)
  assert.deepEqual(bad.issues, [{ code: "VALUE", line: c1.id, value: "SYNTAX" }], "not also 'give a rule a value'")
  // two rules of one child for one band; each child's band condition is independent otherwise
  const dup = planCombination(t, { ...base, childLines: [{ ...c1, age_band: "CHA", text: "x0.3" }, { ...c1, id: "c1b", age_band: "CHA", text: "x0.4" }, c2] }, MU)
  assert.deepEqual(dup.issues, [{ code: "DUPLICATE", line: "c1b" }])
  const bands = planCombination(t, { ...base, childLines: [{ ...c1, age_band: "CHA", text: "x0.3" }, { ...c1, id: "c1b", age_band: "", text: "x0.4" }, c2] }, MU)
  assert.deepEqual(bands.issues, [], "child 1: a CHA rule and a rule for any other age")
  // an adult the combination does not have
  const adult = planCombination(t, { ...base, adultLines: [line({ id: "a3", position: 3, text: "x0.6" })] }, MU)
  assert.deepEqual(adult.issues, [{ code: "POSITION", line: "a3" }])
  const twoAdults = planCombination(t, { ...base, adultLines: [line({ position: 2, text: "x0.9" }), line({ id: "a2b", position: 2, text: "x0.8" })] }, MU)
  assert.deepEqual(twoAdults.issues, [{ code: "DUPLICATE", line: "a2b" }])
  // chosen rooms / periods, none chosen
  const scope = planCombination(t, { ...base, roomsAll: false, rooms: [], periodsAll: false, periods: [], whole: line({ position: 0, text: "x3" }) }, MU)
  assert.deepEqual(scope.issues, [{ code: "NO_ROOMS" }, { code: "NO_PERIODS" }])
  // the twin of another card's row (OCC_DUPLICATE): refused, naming its rows
  const twin = planCombination(t, { ...base, childLines: [{ ...c1, age_band: "CHB", text: "x0.4" }, c2] }, MU)
  const existing = t.occupancy_rules.at(-1)?._key
  assert.deepEqual(twin.issues, [{ code: "TWIN", line: c1.id, keys: [existing] }])
  // an Always-wins twin is another rule
  assert.deepEqual(planCombination(t, { ...base, isOverride: true, childLines: [{ ...c1, age_band: "CHB", text: "x0.4" }, c2] }, MU).issues, [])
  // hidden child lines (the count went down) are not saved
  const fewer = planCombination(t, { ...base, children: 1, childLines: [{ ...c1, text: "x0.3" }, { ...c2, text: "x0.2" }] }, MU)
  assert.deepEqual(fewer.rules.map((x) => x.position), [1])
})

test("cards the builder cannot express are edited in the rule tables; single-use cards stay in the ladder", () => {
  const cards = groupCombinations(
    example([
      occ({ target: "COMBINATION", combination: "3+0", op: "MULTIPLY", value: "2.5", note: "promo" }),
      occ({ target: "CHILD", position: 0, age_band: "CHA", combination: "2+1", op: "MULTIPLY", value: "0.5" }),
      occ({ target: "ADULT", position: 3, combination: "2+2", op: "MULTIPLY", value: "0.5" }),
      occ({ target: "ADULT", position: 2, combination: "2+3", op: "MULTIPLY", value: "0.9" }),
      occ({ target: "ADULT", position: 1, combination: "1+*", op: "MULTIPLY", value: "1.2" }),
    ]),
  )
  const by = (c: string) => cards.find((x) => x.combination === c)
  assert.equal(by("3+0")?.expressible, false, "a note")
  assert.equal(by("2+1")?.expressible, false, "a rule for every child of the combination")
  assert.equal(by("2+2")?.expressible, false, "a 3rd adult in 2 adults")
  assert.equal(by("2+3")?.expressible, true)
  for (const c of ["3+0", "2+1", "2+2"]) assert.equal(builderFromCard(by(c) as NonNullable<ReturnType<typeof by>>, MU), null, c)
  // the single-use row's cards are the ladder's first row, not special combinations
  assert.equal(isSingleUseCard(by("1+0") as NonNullable<ReturnType<typeof by>>), true)
  assert.equal(isSingleUseCard(by("1+*") as NonNullable<ReturnType<typeof by>>), true)
  assert.equal(isSingleUseCard(by("2+3") as NonNullable<ReturnType<typeof by>>), false)
})

test("quick chips: the union of the rooms' valid combinations, greyed out where no room in scope can host them", () => {
  const caps = [
    { room_type: "STD", max_adults: 2, max_children: 1, max_occupants: 3, min_adults: 1 },
    { room_type: "FAM", max_adults: 2, max_children: 2, max_occupants: 4, min_adults: 1 },
  ]
  const all = combinationChips(caps, null)
  assert.deepEqual(
    all.map((c) => `${c.adults}+${c.children}:${c.enabled ? "on" : "off"}:${c.rooms.join(",")}`),
    ["1+0:on:STD,FAM", "2+0:on:STD,FAM", "1+1:on:STD,FAM", "1+2:on:FAM", "2+1:on:STD,FAM", "2+2:on:FAM"],
  )
  // Rooms = Standard (max_children 1): 2A+2C greys out and names the room that can
  const std = combinationChips(caps, ["STD"])
  const twoTwo = std.find((c) => c.adults === 2 && c.children === 2)
  assert.deepEqual([twoTwo?.enabled, twoTwo?.rooms], [false, ["FAM"]])
  assert.equal(std.find((c) => c.adults === 2 && c.children === 1)?.enabled, true)
})

test("child positions are named by the contract's child ordering", () => {
  assert.equal(childQualifier("OLDEST_FIRST", 1, 2), "oldest")
  assert.equal(childQualifier("OLDEST_FIRST", 2, 2), "youngest")
  assert.equal(childQualifier("OLDEST_FIRST", 2, 3), null)
  assert.equal(childQualifier("", 1, 1), "oldest", "the server's default is OLDEST_FIRST")
  assert.equal(childQualifier("OLDEST_FIRST", 1, "*"), "oldest")
  assert.equal(childQualifier("OLDEST_FIRST", 2, "*"), null)
  assert.equal(childQualifier("YOUNGEST_FIRST", 1, 2), "youngest")
  assert.equal(childQualifier("YOUNGEST_FIRST", 2, 2), "oldest")
  assert.equal(childQualifier("AS_ENTERED", 1, 2), "first")
  assert.equal(childQualifier("AS_ENTERED", 2, 2), null)
})

// ─── S12 review follow-up ─────────────────────────────────────────────────

/** Every occupancy row as its fields (no `_key`), sorted: what a save wrote, whatever the keys. */
const rowsOf = (t: Tables) =>
  t.occupancy_rules.map((x) => JSON.stringify([x.target, x.position, x.age_band, x.combination, x.room_type, x.period_code, x.op, x.value, x.is_override, x.note])).sort()

test("All rooms and a named room with the same rules are two cards, and each saved unchanged writes back exactly its rows", () => {
  const t = example()
  const base = ensureChildLines({ ...newBuilderDraft(), adults: 2, children: 2 })
  const chb = (d: BuilderDraft): BuilderDraft => ({ ...d, childLines: [{ ...d.childLines[0], age_band: "CHB", text: "x0.5" }, d.childLines[1]] })
  // the verifier's scenario: 2+2 Child 1 CHB ×0.5 for All rooms, then the same for Standard
  const all = planCombination(t, chb(base), MU)
  assert.ok(all.spec)
  const t1 = persistCombination(t, all.spec).tables
  const std = planCombination(t1, chb({ ...base, roomsAll: false, rooms: ["STD"] }), MU)
  assert.deepEqual(std.issues, [], "another room is no twin")
  assert.ok(std.spec)
  const t2 = persistCombination(t1, std.spec).tables
  const cards = groupCombinations(t2).filter((c) => c.combination === "2+2")
  assert.deepEqual(
    cards.map((c) => [c.rooms, c.periods, c.expressible]),
    [
      [[""], [""], true],
      [["STD"], [""], true],
    ],
    "the Standard card does not vanish into the All rooms card",
  )
  for (const card of cards) {
    const draft = builderFromCard(card, MU)
    assert.ok(draft)
    assert.deepEqual([draft.roomsAll, draft.rooms], card.rooms[0] === "" ? [true, []] : [false, ["STD"]])
    const plan = planCombination(t2, draft, MU)
    assert.deepEqual(plan.issues, [])
    assert.ok(plan.spec)
    const again = persistCombination(t2, plan.spec)
    assert.deepEqual(again.counts, { removed: 1, added: 1 })
    assert.deepEqual(rowsOf(again.tables), rowsOf(t2), `${card.rooms}: the same rows, the STD row kept`)
    assert.ok(groupCombinations(again.tables).some((c) => c.id === card.id && c.keys.length === card.keys.length), "saved unchanged: the same card (nothing to record)")
  }
})

test("All periods and named periods are never one card, also after a split by room", () => {
  const rule = { target: "CHILD", position: 1, age_band: "CHB", combination: "2+2", op: "MULTIPLY", value: "0.5" }
  const t = example([occ({ ...rule }), occ({ ...rule, period_code: "P1" })])
  const cards = groupCombinations(t).filter((c) => c.combination === "2+2")
  assert.deepEqual(
    cards.map((c) => [c.rooms, c.periods, c.periodScoped, c.expressible]),
    [
      [[""], [""], false, true],
      [[""], ["P1"], true, true],
    ],
  )
  for (const card of cards) {
    const draft = builderFromCard(card, MU)
    assert.ok(draft)
    const plan = planCombination(t, draft, MU)
    assert.ok(plan.spec)
    assert.deepEqual(rowsOf(persistCombination(t, plan.spec).tables), rowsOf(t), `${card.periods}: the P1 row kept`)
  }
  // STD × {All, P1} and DLX × All: not a cross product, and the split by room kept STD's All and P1 together
  const mixed = groupCombinations(example([occ({ ...rule, room_type: "STD" }), occ({ ...rule, room_type: "STD", period_code: "P1" }), occ({ ...rule, room_type: "DLX" })]))
  assert.deepEqual(
    mixed.filter((c) => c.combination === "2+2").map((c) => [c.rooms, c.periods]),
    [
      [["STD", "DLX"], [""]],
      [["STD"], ["P1"]],
    ],
  )
  // rooms {All, STD} × periods {All, P1}: four scopes, four cards, each one the builder can show
  const four = groupCombinations(example(["", "STD"].flatMap((room_type) => ["", "P1"].map((period_code) => occ({ ...rule, room_type, period_code })))))
  assert.deepEqual(
    four.filter((c) => c.combination === "2+2").map((c) => [c.rooms, c.periods, c.expressible]),
    [
      [[""], [""], true],
      [[""], ["P1"], true],
      [["STD"], [""], true],
      [["STD"], ["P1"], true],
    ],
  )
})

test("the builder does not open a card whose rooms or periods mix All with named ones", () => {
  const t = example([occ({ target: "CHILD", position: 1, age_band: "CHB", combination: "2+2", op: "MULTIPLY", value: "0.5" })])
  const card = groupCombinations(t).find((c) => c.combination === "2+2")
  assert.ok(card)
  assert.equal(builderCanEdit(card), true)
  for (const scope of [{ rooms: ["", "STD"] }, { periods: ["", "P1"] }]) {
    const mixed = { ...card, ...scope }
    assert.equal(builderCanEdit(mixed), false, JSON.stringify(scope))
    assert.equal(builderFromCard(mixed, MU), null, "Save would write All only and drop the named rows")
  }
})

test("a negative value of a rule other than Plus/minus % keeps its card out of the builder", () => {
  const cards = groupCombinations(
    example([
      occ({ target: "CHILD", position: 1, combination: "2+1", op: "ADD", value: "-5" }),
      occ({ target: "COMBINATION", combination: "3+0", op: "MULTIPLY", value: "-1" }),
      occ({ target: "ADULT", position: 2, combination: "2+2", op: "SUBTRACT", value: "-10" }),
      occ({ target: "CHILD", position: 1, combination: "2+3", op: "ADJUST_PERCENT", value: "-5" }),
      occ({ target: "CHILD", position: 1, combination: "1+1", op: "ADD", value: "-0" }),
    ]),
  )
  const by = (c: string) => cards.find((x) => x.combination === c)
  assert.equal(by("2+1")?.expressible, false, "ADD -5 would read back as SUBTRACT 5, another row")
  assert.equal(by("3+0")?.expressible, false, "MULTIPLY -1 would show as x-1, which the parser refuses")
  assert.equal(by("2+2")?.expressible, false, "SUBTRACT -10 would read back as ADD 10")
  assert.equal(by("2+3")?.expressible, true, "Plus/minus % keeps its sign")
  assert.equal(by("1+1")?.expressible, true, "-0 is 0")
  // every card the builder opens is saved unchanged as exactly its rows
  for (const c of ["2+3", "1+1"]) {
    const card = by(c)
    assert.ok(card)
    const draft = builderFromCard(card, MU)
    assert.ok(draft)
    const plan = planCombination(example(), { ...draft, replace: [] }, MU)
    assert.deepEqual(plan.rules, card.rules.map((x) => ({ ...x, value: x.value === "-0" ? "0" : x.value })), c)
  }
})

test("an INHERIT twin is refused too: the engine skips one of the two, and they would share one card the builder cannot open", () => {
  const t = example([occ({ target: "CHILD", position: 1, age_band: "CHB", combination: "2+2", op: "INHERIT", value: "" })])
  const base = ensureChildLines({ ...newBuilderDraft(), adults: 2, children: 2 })
  const [c1, c2] = base.childLines
  const existing = t.occupancy_rules.at(-1)?._key
  const draft = { ...base, childLines: [{ ...c1, age_band: "CHB", text: "x0.4" }, c2] }
  assert.deepEqual(planCombination(t, draft, MU).issues, [{ code: "TWIN", line: c1.id, keys: [existing] }])
  // written anyway, the two rows of one guest form one cell, so one card with two rules for Child 1 CHB
  const forced = persistCombination(t, { adults: 2, children: 2, rooms: [], periods: [], childRules: [{ position: 1, age_band: "CHB", op: "MULTIPLY", value: "0.4" }] }).tables
  const card = groupCombinations(forced).find((c) => c.combination === "2+2")
  assert.equal(card?.rules.length, 2)
  assert.equal(card?.expressible, false)
})

test("the rule popover adds a child position row, and switches single use to 'also when children travel' (§3.6.2, S16 re-review)", () => {
  const t = example()
  const cha = { target: "CHILD" as const, position: 0, age_band: "CHA", combination: "" }
  const rule = { op: "MULTIPLY", value: "0.5", is_override: false, note: "" }
  // "Child 2" on the CHA band row: a {CHILD, position 2, CHA} rule; the band's own rule stays
  const out = applyOccRuleAs(t, cha, [""], [""], rule, { position: 2 })
  const pos = out.occupancy_rules.filter((x) => x.target === "CHILD" && x.position === 2)
  assert.deepEqual(pos.map((x) => [x.age_band, x.combination, x.op, x.value, x.period_code]), [["CHA", "", "MULTIPLY", "0.5", ""]])
  assert.ok(out.occupancy_rules.some((x) => x.age_band === "CHA" && x.position === 0 && x.value === "0.25"))
  // the ladder shows it as a position row under the bands
  assert.deepEqual(kinds(ladderModel(out, null, "PERSON", OPTS)).slice(-1), ["child2"])
  // position 0 ("every child in this band") is the band row's own rule
  assert.deepEqual(applyOccRuleAs(t, cha, [""], [""], rule, { position: 0 }), applyOccRule(t, cha, [""], [""], rule))
  // single use: the whole 1+0 combination switched to Adult 1 in 1+* for the cell written
  const single = { target: "COMBINATION" as const, position: 0, age_band: "", combination: "1+0" }
  const sw = applyOccRuleAs(t, single, [""], [""], { op: "MULTIPLY", value: "1.5", is_override: false, note: "" }, { single: "children" })
  assert.deepEqual(sw.occupancy_rules.filter((x) => x.combination === "1+0"), [])
  assert.deepEqual(sw.occupancy_rules.filter((x) => x.combination === "1+*").map((x) => [x.target, x.position, x.op, x.value]), [["ADULT", 1, "MULTIPLY", "1.5"]])
  const m = ladderModel(sw, null, "PERSON", OPTS)
  assert.deepEqual(m.rows[0].identity, { target: "ADULT", position: 1, age_band: "", combination: "1+*", room_type: "" })
  // and back
  const back = applyOccRuleAs(sw, m.rows[0].identity!, [""], [""], { op: "MULTIPLY", value: "1.4", is_override: false, note: "" }, { single: "whole" })
  assert.deepEqual(back.occupancy_rules.filter((x) => x.combination === "1+*"), [])
  assert.deepEqual(back.occupancy_rules.filter((x) => x.combination === "1+0").map((x) => [x.target, x.value]), [["COMBINATION", "1.4"]])
  // the same form is the plain popover, and Remove never switches
  assert.equal(applyOccRuleAs(t, single, [""], [""], { op: "MULTIPLY", value: "1.5", is_override: false, note: "" }, { single: "whole" }), t)
  assert.deepEqual(applyOccRuleAs(t, single, [""], [""], null, { single: "children" }), applyOccRule(t, single, [""], [""], null))
})

// ─── the single-use row's two forms (S16 re-review 2) ─────────────────────

const RULE = (value: string) => ({ op: "MULTIPLY", value, is_override: false, note: "" })
const SINGLE = { target: "COMBINATION" as const, position: 0, age_band: "", combination: "1+0" }
const SINGLE_ANY = { target: "ADULT" as const, position: 1, age_band: "", combination: "1+*" }
const singleRules = (t: Tables) =>
  t.occupancy_rules
    .filter((x) => x.combination === "1+0" || x.combination === "1+*")
    .map((x) => `${x.target}:${x.combination}:${x.room_type}:${x.period_code || "ALL"}:${x.value}`)
    .sort()

test("switching one period's single-use form switches the whole row: every period keeps its value in the new form (S16 re-review 2)", () => {
  // All periods 1+0 ×1.5; P4 switched to "also when children travel" ×1.6, only P4
  const t = example()
  const kept = t.occupancy_rules.find((x) => x.combination === "1+0")!._key
  const out = applyOccRuleAs(t, SINGLE, [""], ["P4"], RULE("1.6"), { single: "children" })
  assert.deepEqual(singleRules(out), ["ADULT:1+*::ALL:1.5", "ADULT:1+*::P4:1.6"])
  assert.equal(out.occupancy_rules.find((x) => x.combination === "1+*" && !x.period_code)?._key, kept, "the row keeps its key")
  const m = ladderModel(out, null, "PERSON", OPTS)
  assert.deepEqual(kinds(m).slice(0, 2), ["single1", "adults_base"], "one single-use row, in the new form")
  assert.equal(summary(m.rows[0].cells[""]), "rule MULTIPLY 1.5")
  assert.equal(summary(m.rows[0].cells.P1), "inherited MULTIPLY 1.5")
  assert.equal(summary(m.rows[0].cells.P4), "period-override MULTIPLY 1.6")
  // and back from one period: All periods and P4 return to the whole 1+0 combination
  const back = applyOccRuleAs(out, SINGLE_ANY, [""], ["P2"], RULE("1.2"), { single: "whole" })
  assert.deepEqual(singleRules(back), ["COMBINATION:1+0::ALL:1.5", "COMBINATION:1+0::P2:1.2", "COMBINATION:1+0::P4:1.6"])
  const mb = ladderModel(back, null, "PERSON", OPTS)
  assert.deepEqual(kinds(mb).slice(0, 2), ["single", "adults_base"])
  assert.equal(summary(mb.rows[0].cells[""]), "rule MULTIPLY 1.5", "All periods keeps its rule")
  assert.equal(summary(mb.rows[0].cells.P1), "inherited MULTIPLY 1.5")
})

test("switching All periods while a period override exists takes the override along (S16 re-review 2)", () => {
  const t = example([occ({ target: "COMBINATION", combination: "1+0", period_code: "P4", op: "MULTIPLY", value: "1.6" })])
  const out = applyOccRuleAs(t, SINGLE, [""], [""], RULE("1.5"), { single: "children" })
  assert.deepEqual(singleRules(out), ["ADULT:1+*::ALL:1.5", "ADULT:1+*::P4:1.6"])
  const m = ladderModel(out, null, "PERSON", OPTS)
  assert.equal(summary(m.rows[0].cells.P1), "inherited MULTIPLY 1.5")
  assert.equal(summary(m.rows[0].cells.P4), "period-override MULTIPLY 1.6")
  // a room's own rules of the old form switch with the rooms written, other rooms' stay
  const rooms = example([occ({ target: "COMBINATION", combination: "1+0", room_type: "SUP", op: "MULTIPLY", value: "1.3" })])
  assert.deepEqual(singleRules(applyOccRuleAs(rooms, SINGLE, ["SUP"], [""], RULE("1.4"), { single: "children" })), ["ADULT:1+*:SUP:ALL:1.4", "COMBINATION:1+0::ALL:1.5"])
  // a cell that already has a rule of the new form keeps it (one rule per cell)
  const both = example([occ({ target: "ADULT", position: 1, combination: "1+*", period_code: "P2", op: "MULTIPLY", value: "1.1" })])
  assert.deepEqual(singleRules(applyOccRuleAs(both, SINGLE, [""], [""], RULE("1.5"), { single: "children" })), ["ADULT:1+*::ALL:1.5", "ADULT:1+*::P2:1.1"])
})

test("both single-use forms reaching a scope are two rows, each showing its own rules (S16 re-review 2)", () => {
  // e.g. a draft saved before the switch rewrote whole rows: 1+0 for all periods, 1+* in P4
  const t = example([occ({ target: "ADULT", position: 1, combination: "1+*", period_code: "P4", op: "MULTIPLY", value: "1.6" })])
  const m = ladderModel(t, null, "PERSON", OPTS)
  assert.deepEqual(kinds(m).slice(0, 3), ["single", "single1", "adults_base"])
  const [whole, any] = m.rows
  assert.deepEqual([whole.id, any.id], ["single:0:", "single:1:"])
  assert.deepEqual(any.identity, { ...SINGLE_ANY, room_type: "" })
  assert.equal(summary(whole.cells.P4), "inherited MULTIPLY 1.5")
  assert.equal(summary(any.cells.P4), "period-override MULTIPLY 1.6")
  assert.equal(summary(any.cells[""]), "default MULTIPLY 1")
  // both are in the summary, neither is a special combination
  const s = ladderSummary(m, groupCombinations(t))
  assert.deepEqual(s.adults.map((x) => `${x.kind}${x.position}:${x.value}`), ["single0:1.5", "adult3:0.7"])
  assert.equal(s.combinations, 0)
  // a room scope: All rooms' whole form and the room's own "also with children" form
  const sup = ladderModel(example([occ({ target: "ADULT", position: 1, combination: "1+*", room_type: "SUP", op: "MULTIPLY", value: "1.4" })]), "SUP", "PERSON", OPTS)
  assert.deepEqual(kinds(sup).slice(0, 2), ["single", "single1"])
  assert.equal(summary(sup.rows[0].cells.P1), "all-rooms MULTIPLY 1.5")
  assert.equal(summary(sup.rows[1].cells.P1), "inherited MULTIPLY 1.4")
  // only the new form: one row
  const alt = tablesOf({ periods: [r({ period_code: "P1" })], occupancy_rules: [occ({ target: "ADULT", position: 1, combination: "1+*", op: "MULTIPLY", value: "1.3" })] })
  assert.deepEqual(kinds(ladderModel(alt, null, "PERSON", OPTS))[0], "single1")
})

// ─── the single-use row and special combinations (S16 re-review 3) ────────

/** The builder's "1 adult + any children" card (adults 1, any children under More, + Adult rule
 * position 1 and a Child 1 line): a special combination, not the single-use row's other form. */
const ANY_CHILDREN_CARD = { adults: 1, children: "*" as const, rooms: [], periods: [], adultRules: [{ position: 1, op: "MULTIPLY", value: "1.2" }], childRules: [{ position: 1, age_band: "", op: "MULTIPLY", value: "0.3" }] }
const cardRules = (t: Tables) =>
  groupCombinations(t)
    .filter((c) => c.combination === "1+*" && !isSingleUseCard(c))
    .map((c) => `${c.periods.join(",") || "ALL"}:${c.rules.map((x) => `${x.target}${x.position}:${x.value}`).join(" ")}`)

test("a special combination's Adult 1 rule is not the single-use row: the row neither shows nor switches it (S16 re-review 3)", () => {
  const t = persistCombination(tablesOf({ rooms: example().rooms, periods: example().periods }), ANY_CHILDREN_CARD).tables
  assert.deepEqual(cardRules(t), ["ALL:ADULT1:1.2 CHILD1:0.3"])
  const m = ladderModel(t, null, "PERSON", OPTS)
  assert.deepEqual(kinds(m).slice(0, 2), ["single", "adults_base"], "the whole-combination row alone, not 'also with children'")
  assert.equal(summary(m.rows[0].cells[""]), "default MULTIPLY 1")
  // "Also when children travel" on P2: a single-use rule of its own for P2, the card as it was
  const sw = applyOccRuleAs(t, SINGLE, [""], ["P2"], RULE("1.5"), { single: "children" })
  assert.deepEqual(cardRules(sw), ["ALL:ADULT1:1.2 CHILD1:0.3"])
  assert.deepEqual(singleRules(sw), ["ADULT:1+*::ALL:1.2", "ADULT:1+*::P2:1.5", "CHILD:1+*::ALL:0.3"])
  const ms = ladderModel(sw, null, "PERSON", OPTS)
  assert.deepEqual(kinds(ms).slice(0, 2), ["single1", "adults_base"])
  assert.equal(summary(ms.rows[0].cells.P2), "period-override MULTIPLY 1.5")
  assert.equal(summary(ms.rows[0].cells[""]), "default MULTIPLY 1", "the card's rule is the card's, not the row's")
  // and back from P2 (the reviewer's case): only the single-use rule switches, the card keeps its Adult 1
  const back = applyOccRuleAs(sw, SINGLE_ANY, [""], ["P2"], RULE("1.5"), { single: "whole" })
  assert.deepEqual(cardRules(back), ["ALL:ADULT1:1.2 CHILD1:0.3"])
  assert.deepEqual(singleRules(back), ["ADULT:1+*::ALL:1.2", "CHILD:1+*::ALL:0.3", "COMBINATION:1+0::P2:1.5"])
  // a write into a cell the card holds would change the card: refused, nothing written
  assert.equal(singleWriteRefusal(t, SINGLE, [""], [""], { single: "children" }), "card")
  assert.equal(applyOccRuleAs(t, SINGLE, [""], [""], RULE("1.5"), { single: "children" }), t)
  assert.equal(singleWriteRefusal(sw, SINGLE_ANY, [""], [""]), "card")
  assert.equal(applyOccRule(sw, SINGLE_ANY, [""], [""], RULE("1.3")), sw)
  assert.deepEqual(applyOccEntry(sw, { ...SINGLE_ANY, room_type: "" }, "", parseShorthand("1.3", "occupancy")), { error: "CARD" })
  assert.equal(singleWriteRefusal(t, SINGLE, [""], ["P2"], { single: "children" }), null)
  assert.equal(singleWriteRefusal(sw, SINGLE_ANY, [""], ["P3"]), null)
  // Remove on the row never removes the card's rule
  assert.deepEqual(cardRules(applyOccRule(sw, SINGLE_ANY, [""], ["", "P2"], null)), ["ALL:ADULT1:1.2 CHILD1:0.3"])
  assert.deepEqual(singleRules(applyOccRule(sw, SINGLE_ANY, [""], ["", "P2"], null)), ["ADULT:1+*::ALL:1.2", "CHILD:1+*::ALL:0.3"])
})

test("the single-use form switch is offered only for the scope's own rules (S16 re-review 3)", () => {
  // All rooms' 1+0 ×1.5 reaches Superior: the row there is not Superior's own
  const t = example()
  assert.equal(ladderModel(t, null, "PERSON", OPTS).rows[0].foreign, false)
  assert.equal(ladderModel(t, "SUP", "PERSON", OPTS).rows[0].foreign, true)
  // a room's own rule alone: its own
  const own = tablesOf({ rooms: t.rooms, periods: t.periods, occupancy_rules: [occ({ target: "COMBINATION", combination: "1+0", room_type: "SUP", op: "MULTIPLY", value: "1.3" })] })
  assert.equal(ladderModel(own, "SUP", "PERSON", OPTS).rows[0].foreign, false)
  // a room's own rule and All rooms' one both reach it: the All-rooms one would still apply
  assert.equal(ladderModel(example([occ({ target: "COMBINATION", combination: "1+0", room_type: "SUP", op: "MULTIPLY", value: "1.3" })]), "SUP", "PERSON", OPTS).rows[0].foreign, true)
  // a pricing policy's single-use rule, even outranked by the version's own
  const policy = { ...OPTS, inherited: [fromInheritedRule({ rule_id: "G-1A0C", target: "COMBINATION", position: 0, adults: 1, children: 0, op: "MULTIPLY", value: "1.4", source: "policy:POL-G/r1/global" } as never)] }
  assert.equal(ladderModel(t, null, "PERSON", policy).rows[0].foreign, true)
  assert.equal(ladderModel(tablesOf({ periods: t.periods }), null, "PERSON", policy).rows[0].foreign, true)
  // no rule at all: nothing to leave behind
  assert.equal(ladderModel(tablesOf({ periods: t.periods }), null, "PERSON", OPTS).rows[0].foreign, false)
  // other rows never carry the flag
  assert.equal(ladderModel(t, "SUP", "PERSON", OPTS).rows.slice(1).some((x) => x.foreign), false)
})

test("the whole-row switch refuses to carry a relative rule into the other form (S16 re-review 3)", () => {
  // 1+0 ADJUST_PERCENT −20 changes the party total; Adult 1 ADJUST_PERCENT −20 the slot unit
  const rel = example([occ({ target: "COMBINATION", combination: "1+0", period_code: "P4", op: "ADD", value: "30" })])
  assert.equal(singleWriteRefusal(rel, SINGLE, [""], ["P2"], { single: "children" }), "relative")
  assert.equal(applyOccRuleAs(rel, SINGLE, [""], ["P2"], RULE("1.6"), { single: "children" }), rel)
  // the relative row is the one written: it takes the new rule, nothing else is relative
  assert.equal(singleWriteRefusal(rel, SINGLE, [""], ["P4"], { single: "children" }), null)
  assert.deepEqual(singleRules(applyOccRuleAs(rel, SINGLE, [""], ["P4"], RULE("1.6"), { single: "children" })), ["ADULT:1+*::ALL:1.5", "ADULT:1+*::P4:1.6"])
  // replacing ops and INHERIT keep their price in either form
  for (const op of ["ABSOLUTE", "FIXED", "MULTIPLY", "PERCENT_OF", "INHERIT"]) {
    const x = example([occ({ target: "COMBINATION", combination: "1+0", period_code: "P4", op, value: op === "INHERIT" ? "" : "90" })])
    assert.equal(singleWriteRefusal(x, SINGLE, [""], ["P2"], { single: "children" }), null, op)
  }
  // back from "also with children": an Adult 1 ADJUST_PERCENT is relative too
  const alt = tablesOf({ periods: example().periods, occupancy_rules: [occ({ target: "ADULT", position: 1, combination: "1+*", op: "ADJUST_PERCENT", value: "-20" })] })
  assert.equal(singleWriteRefusal(alt, SINGLE_ANY, [""], ["P2"], { single: "whole" }), "relative")
  // no switch: a plain write is never refused for its op
  assert.equal(singleWriteRefusal(rel, SINGLE, [""], ["P2"]), null)
})
