// Unit tests for the Pricing Workspace undo history (PRICING_WORKSPACE_UX.md §3.10, §5.1).
// Run with `npm run test:unit` (node --test).
import { test } from "node:test"
import assert from "node:assert/strict"
import { createHistory, diffTables } from "../../src/tex/screens/rates/workspace/history.ts"

type R = { _key: string; [k: string]: string | number | null }
type T = { rooms: R[]; periods: R[]; period_rates: R[] }

const r = (key: string, fields: Record<string, string | number | null> = {}): R => ({ _key: key, ...fields })

function base(): T {
  return { rooms: [r("a", { room_type: "STD" })], periods: [r("p", { period_code: "P1" })], period_rates: [] }
}

test("commit, undo and redo restore the recorded tables only", () => {
  const h = createHistory<T>()
  assert.equal(h.canUndo(), false)
  assert.equal(h.canRedo(), false)
  const s0 = base()
  const rates1 = [r("x", { room_type: "STD", period_code: "P1", op: "ABSOLUTE", value: "70" })]
  const s1: T = { ...s0, period_rates: rates1 }
  h.commit("Set STD P1", { period_rates: s0.period_rates }, { period_rates: rates1 })
  assert.equal(h.canUndo(), true)
  assert.equal(h.canRedo(), false)

  // a later unrelated change to rooms is not touched by undoing the rate entry
  const rooms2 = [...s1.rooms, r("b", { room_type: "SUP" })]
  const cur: T = { ...s1, rooms: rooms2 }
  const u = h.undo(cur)
  assert.ok(u)
  assert.equal(u.label, "Set STD P1")
  assert.equal(u.state.period_rates, s0.period_rates)
  assert.equal(u.state.rooms, rooms2, "tables the entry did not record stay as they are")
  assert.equal(h.canUndo(), false)
  assert.equal(h.canRedo(), true)

  const re = h.redo(u.state)
  assert.ok(re)
  assert.equal(re.label, "Set STD P1")
  assert.equal(re.state.period_rates, rates1)
  assert.equal(h.canRedo(), false)
  assert.equal(h.undo(re.state)?.state.period_rates, s0.period_rates)
})

test("undo restores recorded rows: 'no rule' comes back as no row, never as 0", () => {
  const h = createHistory<T>()
  const before: R[] = []
  const after = [r("x", { room_type: "SUP", period_code: "P4", op: "MULTIPLY", value: "1.2", base_room_type: "STD" })]
  h.commit("SUP P4", { period_rates: before }, { period_rates: after })
  const u = h.undo({ ...base(), period_rates: after })
  assert.deepEqual(u?.state.period_rates, [])
})

test("a new commit clears the redo stack", () => {
  const h = createHistory<T>()
  const s = base()
  h.commit("one", { rooms: s.rooms }, { rooms: [] })
  h.undo({ ...s, rooms: [] })
  assert.equal(h.canRedo(), true)
  h.commit("two", { periods: s.periods }, { periods: [] })
  assert.equal(h.canRedo(), false)
  assert.equal(h.redo(s), null)
})

test("the log keeps at most 100 entries (the oldest is dropped)", () => {
  const h = createHistory<T>()
  let cur = base()
  for (let i = 0; i < 101; i++) {
    const next = [r(`k${i}`, { period_code: `P${i}` })]
    h.commit(`step ${i}`, { periods: cur.periods }, { periods: next })
    cur = { ...cur, periods: next }
  }
  assert.equal(h.size(), 100)
  let undone = 0
  let last = ""
  for (;;) {
    const u = h.undo(cur)
    if (!u) break
    cur = u.state
    last = u.label
    undone += 1
  }
  assert.equal(undone, 100)
  assert.equal(last, "step 1", "step 0 fell off the log")
  assert.equal(cur.periods[0]._key, "k0")
})

test("a smaller cap is honoured", () => {
  const h = createHistory<T>(2)
  const s = base()
  h.commit("a", { rooms: s.rooms }, { rooms: [] })
  h.commit("b", { rooms: [] }, { rooms: s.rooms })
  h.commit("c", { rooms: s.rooms }, { rooms: [] })
  assert.equal(h.size(), 2)
})

test("clear (Discard, loading another version) empties undo and redo", () => {
  const h = createHistory<T>()
  const s = base()
  h.commit("a", { rooms: s.rooms }, { rooms: [] })
  h.commit("b", { periods: s.periods }, { periods: [] })
  h.undo({ ...s, rooms: [], periods: [] })
  h.clear()
  assert.equal(h.canUndo(), false)
  assert.equal(h.canRedo(), false)
  assert.equal(h.undo(s), null)
  assert.equal(h.size(), 0)
})

test("undo on an empty log returns null and does not call anything", () => {
  const h = createHistory<T>()
  assert.equal(h.undo(base()), null)
  assert.equal(h.redo(base()), null)
})

test("diffTables records only the tables whose arrays changed", () => {
  const s0 = base()
  const s1 = { ...s0, period_rates: [r("x")] }
  const d = diffTables(s0, s1)
  assert.ok(d)
  assert.deepEqual(Object.keys(d.before), ["period_rates"])
  assert.equal(d.before.period_rates, s0.period_rates)
  assert.equal(d.after.period_rates, s1.period_rates)
  assert.equal(diffTables(s0, { ...s0 }), null, "no change → nothing to record")
})
