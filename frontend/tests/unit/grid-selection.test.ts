// Unit tests for the keyboard grid's pure selection reducer and fill planning
// (PRICING_WORKSPACE_UX.md §3.10, §5.1). Run with `npm run test:unit` (node --test).
import { test } from "node:test"
import assert from "node:assert/strict"
import {
  editableCells,
  fillDownPlan,
  fillRightPlan,
  gridSelectionInit,
  gridSelectionReducer as reduce,
  isCellSelected,
  isSingleCell,
  selectedCells,
  type GridAction,
  type GridCell,
  type GridSelection,
} from "../../src/tex/ui/grid-model.ts"

const all = () => true

function run(s: GridSelection, ...actions: GridAction[]): GridSelection {
  return actions.reduce(reduce, s)
}

function cells(...pairs: Array<[number, number]>): GridCell[] {
  return pairs.map(([r, c]) => ({ r, c }))
}

test("init: the active cell is the only selected cell", () => {
  const s = gridSelectionInit(3, 4)
  assert.deepEqual(s.active, { r: 0, c: 0 })
  assert.deepEqual(s.anchor, { r: 0, c: 0 })
  assert.deepEqual(s.ranges, [{ r0: 0, c0: 0, r1: 0, c1: 0 }])
  assert.equal(isSingleCell(s), true)
  assert.deepEqual(selectedCells(s, all), cells([0, 0]))
  assert.deepEqual(gridSelectionInit(0, 4).ranges, [])
})

test("moves clamp to the bounds", () => {
  const s = gridSelectionInit(3, 4)
  assert.deepEqual(reduce(s, { type: "move", dr: -1, dc: 0 }).active, { r: 0, c: 0 })
  assert.deepEqual(reduce(s, { type: "move", dr: 0, dc: -1 }).active, { r: 0, c: 0 })
  assert.deepEqual(reduce(s, { type: "move", dr: 0, dc: 9 }).active, { r: 0, c: 3 })
  assert.deepEqual(reduce(s, { type: "move", dr: 9, dc: 9 }).active, { r: 2, c: 3 })
  const end = run(s, { type: "move", dr: 5, dc: 5 }, { type: "move", dr: 1, dc: 1 })
  assert.deepEqual(end.active, { r: 2, c: 3 })
  // a plain move collapses the selection onto the new active cell
  assert.deepEqual(end.anchor, { r: 2, c: 3 })
  assert.deepEqual(end.ranges, [{ r0: 2, c0: 3, r1: 2, c1: 3 }])
  // moveTo clamps too (Home/End/PageUp/PageDown)
  assert.deepEqual(reduce(s, { type: "moveTo", r: 40, c: -3 }).active, { r: 2, c: 0 })
  // an empty grid ignores moves
  const empty = gridSelectionInit(0, 0)
  assert.equal(reduce(empty, { type: "move", dr: 1, dc: 1 }), empty)
})

test("Shift+move extends from the anchor", () => {
  const s = run(gridSelectionInit(4, 5), { type: "moveTo", r: 1, c: 1 })
  const a = run(s, { type: "move", dr: 0, dc: 1, extend: true }, { type: "move", dr: 1, dc: 0, extend: true })
  assert.deepEqual(a.anchor, { r: 1, c: 1 })
  assert.deepEqual(a.active, { r: 2, c: 2 })
  assert.deepEqual(a.ranges, [{ r0: 1, c0: 1, r1: 2, c1: 2 }])
  // extending back past the anchor normalises the rectangle
  const b = run(a, { type: "move", dr: -2, dc: -2, extend: true })
  assert.deepEqual(b.anchor, { r: 1, c: 1 })
  assert.deepEqual(b.active, { r: 0, c: 0 })
  assert.deepEqual(b.ranges, [{ r0: 0, c0: 0, r1: 1, c1: 1 }])
  // Shift+Ctrl+End extends to the last cell
  const c = reduce(a, { type: "moveTo", r: 3, c: 4, extend: true })
  assert.deepEqual(c.ranges, [{ r0: 1, c0: 1, r1: 3, c1: 4 }])
  // Shift+Click extends from the same anchor
  const d = reduce(a, { type: "click", r: 0, c: 3, shift: true })
  assert.deepEqual(d.anchor, { r: 1, c: 1 })
  assert.deepEqual(d.active, { r: 0, c: 3 })
  assert.deepEqual(d.ranges, [{ r0: 0, c0: 1, r1: 1, c1: 3 }])
  assert.equal(isSingleCell(d), false)
})

test("meta+click adds a separate range", () => {
  const s = run(gridSelectionInit(4, 5), { type: "click", r: 0, c: 0 }, { type: "click", r: 1, c: 1, shift: true })
  const t = reduce(s, { type: "click", r: 3, c: 4, meta: true })
  assert.deepEqual(t.active, { r: 3, c: 4 })
  assert.deepEqual(t.anchor, { r: 3, c: 4 })
  assert.deepEqual(t.ranges, [
    { r0: 0, c0: 0, r1: 1, c1: 1 },
    { r0: 3, c0: 4, r1: 3, c1: 4 },
  ])
  // Ctrl+Shift+Click grows the added range from its own anchor; the first range stays
  const u = reduce(t, { type: "click", r: 2, c: 3, shift: true, meta: true })
  assert.deepEqual(u.ranges, [
    { r0: 0, c0: 0, r1: 1, c1: 1 },
    { r0: 2, c0: 3, r1: 3, c1: 4 },
  ])
  assert.equal(isCellSelected(u, 2, 3), true)
  assert.equal(isCellSelected(u, 2, 2), false)
  // a plain click collapses everything again
  const v = reduce(u, { type: "click", r: 2, c: 2 })
  assert.deepEqual(v.ranges, [{ r0: 2, c0: 2, r1: 2, c1: 2 }])
})

test("selectCol skips non-editable rows", () => {
  // row 1 is a resolved (read-only) row; row 3 is editable only in column 0
  const editable = (r: number, c: number) => r !== 1 && !(r === 3 && c !== 0)
  const s = reduce(gridSelectionInit(5, 3), { type: "selectCol", c: 2, isEditable: editable })
  assert.deepEqual(s.active, { r: 0, c: 2 })
  assert.deepEqual(s.anchor, { r: 0, c: 2 })
  assert.deepEqual(s.ranges, [
    { r0: 0, c0: 2, r1: 0, c1: 2 },
    { r0: 2, c0: 2, r1: 2, c1: 2 },
    { r0: 4, c0: 2, r1: 4, c1: 2 },
  ])
  assert.deepEqual(selectedCells(s, editable), cells([0, 2], [2, 2], [4, 2]))
  // with add (Ctrl/Cmd+header click) a second column joins the first
  const t = reduce(s, { type: "selectCol", c: 0, isEditable: editable, add: true })
  assert.deepEqual(selectedCells(t, editable), cells([0, 0], [0, 2], [2, 0], [2, 2], [3, 0], [4, 0], [4, 2]))
  assert.deepEqual(t.active, { r: 0, c: 0 })
  // a column with no editable cell leaves the selection as it was
  const none = reduce(t, { type: "selectCol", c: 1, isEditable: () => false })
  assert.equal(none, t)
})

test("selectRow selects the row's editable cells", () => {
  const editable = (_r: number, c: number) => c !== 1
  const s = reduce(gridSelectionInit(3, 4), { type: "selectRow", r: 2, isEditable: editable })
  assert.deepEqual(s.active, { r: 2, c: 0 })
  assert.deepEqual(s.ranges, [
    { r0: 2, c0: 0, r1: 2, c1: 0 },
    { r0: 2, c0: 2, r1: 2, c1: 3 },
  ])
  assert.deepEqual(selectedCells(s, editable), cells([2, 0], [2, 2], [2, 3]))
})

test("selectAll takes the editable list, keeps an editable active cell, and compresses ranges", () => {
  const editable = (r: number, c: number) => r !== 1 && c < 3
  const list = editableCells(4, 4, editable)
  assert.deepEqual(list, cells([0, 0], [0, 1], [0, 2], [2, 0], [2, 1], [2, 2], [3, 0], [3, 1], [3, 2]))
  const s = run(gridSelectionInit(4, 4), { type: "moveTo", r: 2, c: 1 }, { type: "selectAll", cells: list })
  assert.deepEqual(s.active, { r: 2, c: 1 })
  assert.deepEqual(s.anchor, { r: 2, c: 1 })
  assert.deepEqual(s.ranges, [
    { r0: 0, c0: 0, r1: 0, c1: 2 },
    { r0: 2, c0: 0, r1: 3, c1: 2 },
  ])
  assert.deepEqual(selectedCells(s, editable), list)
  // a non-editable active cell moves to the first editable cell
  const t = run(gridSelectionInit(4, 4), { type: "moveTo", r: 1, c: 3 }, { type: "selectAll", cells: list })
  assert.deepEqual(t.active, { r: 0, c: 0 })
  // an empty list changes nothing; out-of-bounds cells are ignored
  assert.equal(reduce(t, { type: "selectAll", cells: [] }), t)
  const u = reduce(gridSelectionInit(2, 2), { type: "selectAll", cells: cells([0, 1], [5, 5], [0, 1]) })
  assert.deepEqual(u.ranges, [{ r0: 0, c0: 1, r1: 0, c1: 1 }])
})

test("selectedCells has no duplicates and keeps reading order", () => {
  // overlapping ranges added in a jumbled order
  let s = run(gridSelectionInit(4, 4), { type: "click", r: 2, c: 2 }, { type: "click", r: 3, c: 3, shift: true })
  s = run(s, { type: "click", r: 0, c: 1, meta: true }, { type: "click", r: 2, c: 3, shift: true, meta: true })
  s = run(s, { type: "click", r: 2, c: 2, meta: true }, { type: "click", r: 0, c: 0, meta: true })
  const got = selectedCells(s, all)
  assert.deepEqual(got, cells([0, 0], [0, 1], [0, 2], [0, 3], [1, 1], [1, 2], [1, 3], [2, 1], [2, 2], [2, 3], [3, 2], [3, 3]))
  const keys = got.map((x) => `${x.r}:${x.c}`)
  assert.equal(new Set(keys).size, keys.length)
  // the editable filter drops read-only cells without reordering the rest
  assert.deepEqual(
    selectedCells(s, (r) => r !== 2),
    cells([0, 0], [0, 1], [0, 2], [0, 3], [1, 1], [1, 2], [1, 3], [3, 2], [3, 3]),
  )
  // without a predicate every selected cell counts
  assert.deepEqual(selectedCells(s), got)
})

test("focus keeps the selection when it lands on the active cell, collapses otherwise", () => {
  const s = run(gridSelectionInit(3, 3), { type: "click", r: 0, c: 0 }, { type: "click", r: 1, c: 1, shift: true })
  assert.equal(reduce(s, { type: "focus", r: 1, c: 1 }), s)
  const t = reduce(s, { type: "focus", r: 2, c: 0 })
  assert.deepEqual(t.ranges, [{ r0: 2, c0: 0, r1: 2, c1: 0 }])
  assert.deepEqual(t.anchor, { r: 2, c: 0 })
})

test("clear collapses onto the active cell", () => {
  const s = run(gridSelectionInit(3, 3), { type: "click", r: 0, c: 0 }, { type: "click", r: 2, c: 2, shift: true })
  const t = reduce(s, { type: "clear" })
  assert.deepEqual(t.active, { r: 2, c: 2 })
  assert.deepEqual(t.anchor, { r: 2, c: 2 })
  assert.deepEqual(t.ranges, [{ r0: 2, c0: 2, r1: 2, c1: 2 }])
  assert.equal(isSingleCell(t), true)
})

test("clamp follows a shrinking and growing grid", () => {
  const s = run(gridSelectionInit(4, 4), { type: "click", r: 1, c: 1 }, { type: "click", r: 3, c: 3, shift: true })
  assert.equal(reduce(s, { type: "clamp", rows: 4, cols: 4 }), s)
  // a deleted period column and room row: active, anchor and ranges are clipped
  const t = reduce(s, { type: "clamp", rows: 3, cols: 2 })
  assert.deepEqual(t.active, { r: 2, c: 1 })
  assert.deepEqual(t.anchor, { r: 1, c: 1 })
  assert.deepEqual(t.ranges, [{ r0: 1, c0: 1, r1: 2, c1: 1 }])
  // a range entirely outside the new bounds is dropped
  const u = run(gridSelectionInit(4, 4), { type: "click", r: 0, c: 0 }, { type: "click", r: 3, c: 3, meta: true })
  assert.deepEqual(reduce(u, { type: "clamp", rows: 2, cols: 2 }).ranges, [{ r0: 0, c0: 0, r1: 0, c1: 0 }])
  // an emptied grid has nothing selected; growing again selects the active cell
  const e = reduce(s, { type: "clamp", rows: 0, cols: 4 })
  assert.deepEqual(e.ranges, [])
  assert.deepEqual(selectedCells(e, all), [])
  const g = reduce(e, { type: "clamp", rows: 2, cols: 2 })
  assert.deepEqual(g.ranges, [{ r0: 0, c0: 0, r1: 0, c1: 0 }])
})

test("fillRightPlan and fillDownPlan for a 2×3 selection", () => {
  const s = run(gridSelectionInit(5, 6), { type: "click", r: 1, c: 2 }, { type: "click", r: 2, c: 4, shift: true })
  const sel = selectedCells(s, all)
  assert.deepEqual(sel, cells([1, 2], [1, 3], [1, 4], [2, 2], [2, 3], [2, 4]))
  assert.deepEqual(fillRightPlan(sel), [
    { from: { r: 1, c: 2 }, to: { r: 1, c: 3 } },
    { from: { r: 1, c: 2 }, to: { r: 1, c: 4 } },
    { from: { r: 2, c: 2 }, to: { r: 2, c: 3 } },
    { from: { r: 2, c: 2 }, to: { r: 2, c: 4 } },
  ])
  assert.deepEqual(fillDownPlan(sel), [
    { from: { r: 1, c: 2 }, to: { r: 2, c: 2 } },
    { from: { r: 1, c: 3 }, to: { r: 2, c: 3 } },
    { from: { r: 1, c: 4 }, to: { r: 2, c: 4 } },
  ])
})

test("fill plans use each row's leftmost / each column's topmost editable cell", () => {
  // unordered input with a gap: the plans sort and group, and single cells have nothing to fill
  const sel = cells([2, 3], [0, 1], [0, 3], [2, 1], [1, 2])
  assert.deepEqual(fillRightPlan(sel), [
    { from: { r: 0, c: 1 }, to: { r: 0, c: 3 } },
    { from: { r: 2, c: 1 }, to: { r: 2, c: 3 } },
  ])
  assert.deepEqual(fillDownPlan(sel), [
    { from: { r: 0, c: 1 }, to: { r: 2, c: 1 } },
    { from: { r: 0, c: 3 }, to: { r: 2, c: 3 } },
  ])
  assert.deepEqual(fillRightPlan(cells([0, 0])), [])
  assert.deepEqual(fillDownPlan([]), [])
})
