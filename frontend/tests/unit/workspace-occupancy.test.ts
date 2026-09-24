// Unit tests for the Pricing Workspace occupancy ladder and special combinations
// (PRICING_WORKSPACE_UX.md §3.6, §3.7, D8, D12, §5.1). Run with `npm run test:unit` (node --test).
import { test } from "node:test"
import assert from "node:assert/strict"
import { parseShorthand } from "../../src/tex/screens/rates/lib/shorthand.ts"
import {
  applyOccEntry,
  canonCombination,
  groupCombinations,
  ladderModel,
  persistCombination,
  removeCombination,
  validCombinations,
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
  assert.equal(sup.rows.find((row) => row.kind === "adult" && row.position === 3)?.cells[""].state, "default", "the all-rooms rule belongs to the All rooms scope")
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
