// §6K6 (batch 2Q): the occupancy ladder's sample parties (`partyOptions`) walked every band combination of a party
// size that does not fit, for each number of adults: about 20 ms for five bands, 400 ms for ten, seconds for more (in a
// memo, on each room). The fit depends on the number of children and of infants only, and more infants never hurts:
// the walk leaves out what cannot fit, and lists exactly the parties it listed before. Run with `npm run test:unit`.
import { test } from "node:test"
import assert from "node:assert/strict"
import { PARTY_ADULTS_MAX, PARTY_CHILDREN_MAX, PARTY_OPTIONS_MAX, partyOptions, type InfantRules } from "../../src/tex/screens/rates/workspace/occupancy.ts"

type Band = { code: string; is_infant: number }
type Cap = { max_adults: number; max_children: number; max_occupants: number; min_adults: number }

/** The walk as it was before batch 2Q (every multiset of every size), the reference the pruned walk must equal. */
function fullWalk(capacity: Cap, bands: readonly Band[], rules: InfantRules = {}) {
  const asChildren = rules.infantsAsChildren ?? true
  const asOccupants = rules.infantsAsOccupants ?? true
  const codes = [...new Set(bands.map((b) => b.code))]
  const infantCodes = new Set(bands.filter((b) => b.is_infant).map((b) => b.code))
  const fits = (adults: number, children: readonly string[]) => {
    const infants = children.filter((c) => infantCodes.has(c)).length
    return children.length - (asChildren ? 0 : infants) <= capacity.max_children && adults + children.length - (asOccupants ? 0 : infants) <= capacity.max_occupants
  }
  function* multisets(n: number, from: number): Generator<string[]> {
    if (n === 0) {
      yield []
      return
    }
    for (let i = from; i < codes.length; i++) for (const rest of multisets(n - 1, i)) yield [codes[i], ...rest]
  }
  const some = (n: number, adults: number) => {
    for (const children of multisets(n, 0)) if (fits(adults, children)) return true
    return false
  }
  const combos: { adults: number; children: number }[] = []
  for (let a = Math.max(1, capacity.min_adults); a <= Math.min(capacity.max_adults, PARTY_ADULTS_MAX); a++)
    for (let c = 0; c <= (codes.length ? PARTY_CHILDREN_MAX : 0); c++) if (some(c, a)) combos.push({ adults: a, children: c })
  combos.sort((x, y) => Number(x.children > 0) - Number(y.children > 0) || x.adults - y.adults || x.children - y.children)
  const commonness = (c: { adults: number; children: number }) => [c.children > 0 ? 1 : 0, c.adults + c.children, Math.abs(c.adults - 2), c.children]
  const byCommon = combos.map((c, i) => ({ c, i })).sort((x, y) => {
    const [a, b] = [commonness(x.c), commonness(y.c)]
    for (let k = 0; k < a.length; k++) if (a[k] !== b[k]) return a[k] - b[k]
    return x.i - y.i
  })
  const kept: { id: string; combo: number; seq: number }[] = []
  fill: for (const { c, i } of byCommon) {
    let seq = 0
    for (const children of multisets(c.children, 0)) {
      if (!fits(c.adults, children)) continue
      if (kept.length >= PARTY_OPTIONS_MAX) break fill
      kept.push({ id: `${c.adults}+${children.join(",")}`, combo: i, seq: seq++ })
    }
  }
  return kept.sort((x, y) => x.combo - y.combo || x.seq - y.seq).map((k) => k.id)
}

const bands = (n: number, infants: number[] = [0]): Band[] =>
  Array.from({ length: n }, (_, i) => ({ code: `B${String(i).padStart(2, "0")}`, is_infant: infants.includes(i) ? 1 : 0 }))

test("a room with many bands lists its sample parties at once", () => {
  // no children at all, infants only as neither children nor occupants: the full walk tried every combination (15 s)
  const many = bands(20, [3])
  const adults = { max_adults: 4, max_children: 0, max_occupants: 4, min_adults: 1 }
  const started = performance.now()
  assert.deepEqual(partyOptions(adults, many).map((p) => p.id), ["1+", "2+", "3+", "4+"])
  const ids = partyOptions(adults, many, { infantsAsChildren: false, infantsAsOccupants: false }).map((p) => p.id)
  const ms = performance.now() - started
  assert.ok(ms < 1000, `${Math.round(ms)} ms`)
  assert.ok(ids.includes("2+B03,B03,B03,B03,B03,B03,B03,B03"), ids.join(" "))
  assert.ok(ids.every((id) => !id.split("+")[1] || id.split("+")[1].split(",").every((c) => c === "B03")), ids.join(" "))
})

test("the pruned walk lists exactly the parties of the full walk", () => {
  let seed = 7
  const rnd = (n: number) => ((seed = (seed * 1103515245 + 12345) % 2 ** 31), seed % n)
  const ruleSets: InfantRules[] = [{}, { infantsAsChildren: false }, { infantsAsOccupants: false }, { infantsAsChildren: false, infantsAsOccupants: false }]
  for (let k = 0; k < 300; k++) {
    const n = rnd(6)
    const infants = Array.from({ length: n }, (_, i) => i).filter(() => rnd(3) === 0)
    const cap = { max_adults: 1 + rnd(5), max_children: rnd(5), max_occupants: 1 + rnd(8), min_adults: 1 + rnd(2) }
    const rules = ruleSets[rnd(4)]
    const got = partyOptions(cap, bands(n, infants), rules).map((p) => p.id)
    assert.deepEqual(got, fullWalk(cap, bands(n, infants), rules), JSON.stringify({ n, infants, cap, rules }))
  }
})
