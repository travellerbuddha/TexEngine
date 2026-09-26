// Unit tests for the Popover/Menu/Tooltip placement math: fixed positioning that flips and
// clamps inside the viewport (PRICING_WORKSPACE_UX.md §3.19; slice S7). Run with `npm run test:unit`.
import { test } from "node:test"
import assert from "node:assert/strict"
import { placeFloating, type FloatingRect } from "../../src/tex/ui/placement.ts"

const VIEW = { width: 1000, height: 800 }

function rect(left: number, top: number, width: number, height: number): FloatingRect {
  return { left, top, right: left + width, bottom: top + height }
}

test("bottom-start sits under the anchor, aligned to its left edge", () => {
  const p = placeFloating(rect(100, 100, 80, 30), { width: 200, height: 150 }, VIEW)
  assert.deepEqual(p, { top: 134, left: 100, maxHeight: 658, maxWidth: 984, placement: "bottom-start" })
})

test("bottom-end and centred placements align to the anchor's right edge and centre", () => {
  const a = rect(400, 100, 80, 30)
  assert.equal(placeFloating(a, { width: 200, height: 100 }, VIEW, "bottom-end").left, 280)
  assert.equal(placeFloating(a, { width: 200, height: 100 }, VIEW, "bottom").left, 340)
  const top = placeFloating(a, { width: 120, height: 40 }, VIEW, "top")
  assert.deepEqual(top, { top: 56, left: 380, maxHeight: 88, maxWidth: 984, placement: "top" })
})

test("flips to the top when the bottom lacks room and the top has more", () => {
  const p = placeFloating(rect(100, 700, 80, 30), { width: 200, height: 150 }, VIEW, "bottom-start")
  assert.equal(p.placement, "top-start")
  assert.equal(p.top, 700 - 4 - 150)
  // and back: top requested near the top edge
  const q = placeFloating(rect(100, 20, 80, 30), { width: 200, height: 150 }, VIEW, "top-end")
  assert.equal(q.placement, "bottom-end")
  assert.equal(q.top, 54)
})

test("keeps the requested side when neither side fits but it has more room, and scrolls inside", () => {
  const p = placeFloating(rect(100, 300, 80, 30), { width: 200, height: 600 }, VIEW, "bottom-start")
  assert.equal(p.placement, "bottom-start")
  assert.equal(p.top, 334)
  assert.equal(p.maxHeight, 800 - 8 - 334)
})

test("clamps horizontally inside the viewport margins", () => {
  const right = placeFloating(rect(950, 100, 40, 30), { width: 300, height: 100 }, VIEW, "bottom-start")
  assert.equal(right.left, 1000 - 8 - 300)
  const left = placeFloating(rect(5, 100, 40, 30), { width: 300, height: 100 }, VIEW, "bottom-end")
  assert.equal(left.left, 8)
  // wider than the viewport: pinned to the margin and limited to the viewport width
  const wide = placeFloating(rect(5, 100, 40, 30), { width: 1200, height: 100 }, VIEW)
  assert.equal(wide.left, 8)
  assert.equal(wide.maxWidth, 984)
})

test("overlaps the anchor rather than shrinking to nothing in a short viewport", () => {
  const small = { width: 400, height: 200 }
  // 78 px below and 78 px above: a 400 px panel fits neither side, so it overlaps the anchor
  // and uses the whole viewport height (minus the margins) instead of a 78 px sliver
  const p = placeFloating(rect(10, 90, 80, 20), { width: 200, height: 400 }, small, "bottom-start")
  assert.equal(p.top, 8)
  assert.equal(p.maxHeight, 200 - 16)
  // with at least 120 px on one side it stays attached and scrolls inside
  const q = placeFloating(rect(10, 240, 80, 40), { width: 200, height: 400 }, { width: 400, height: 300 }, "bottom-start")
  assert.equal(q.placement, "top-start")
  assert.equal(q.maxHeight, 240 - 4 - 8)
  assert.equal(q.top, 8)
})

test("an anchor scrolled out of view keeps the panel on screen", () => {
  const below = placeFloating(rect(100, 900, 80, 30), { width: 200, height: 100 }, VIEW, "bottom-start")
  assert.equal(below.placement, "top-start")
  assert.equal(below.top, 800 - 8 - 100)
  const above = placeFloating(rect(100, -200, 80, 30), { width: 200, height: 100 }, VIEW, "top-start")
  assert.equal(above.placement, "bottom-start")
  assert.equal(above.top, 8)
})
