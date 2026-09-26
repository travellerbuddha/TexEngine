// Unit tests for the save-settling helpers of the version editor (PRICING_WORKSPACE_UX.md §3.16,
// §5.1): keepKeys keeps the client row keys across a save, overSaved keeps in-flight edits.
// Run with `npm run test:unit` (node --test).
import { test } from "node:test"
import assert from "node:assert/strict"
import { keepKeys, overSaved } from "../../src/tex/lib/edits.ts"

type R = { _key: string; [k: string]: string | number | null }

const row = (key: string, fields: Record<string, string | number | null> = {}): R => ({ _key: key, ...fields })

test("keepKeys copies the sent row keys onto the saved rows of every table of equal length", () => {
  const sent = { rooms: [row("a", { room_type: "STD" }), row("b", { room_type: "SUP" })], periods: [row("p", { period_code: "P1" })] }
  const saved = {
    rooms: [row("x", { room_type: "STD", _name: "srv-1" }), row("y", { room_type: "SUP", _name: "srv-2" })],
    periods: [row("z", { period_code: "P1" })],
  }
  const out = keepKeys(saved, sent)
  assert.deepEqual(
    out.rooms.map((r) => r._key),
    ["a", "b"],
  )
  assert.deepEqual(
    out.periods.map((r) => r._key),
    ["p"],
  )
  // everything else comes from the saved copy (server names and normalised values)
  assert.deepEqual(
    out.rooms.map((r) => r._name),
    ["srv-1", "srv-2"],
  )
  assert.equal(out.rooms[0].room_type, "STD")
})

test("keepKeys leaves a table alone when the saved and sent lengths differ", () => {
  const sent = { rooms: [row("a"), row("b")], periods: [row("p")] }
  const saved = { rooms: [row("x")], periods: [row("z")] }
  const out = keepKeys(saved, sent)
  assert.equal(out.rooms, saved.rooms, "a table of another length is returned as it was saved")
  assert.deepEqual(
    out.periods.map((r) => r._key),
    ["p"],
  )
})

test("keepKeys is pure: neither input is changed", () => {
  const sent = { rooms: [row("a")] }
  const saved = { rooms: [row("x", { room_type: "STD" })] }
  const snapSent = JSON.stringify(sent)
  const snapSaved = JSON.stringify(saved)
  const out = keepKeys(saved, sent)
  assert.equal(JSON.stringify(sent), snapSent)
  assert.equal(JSON.stringify(saved), snapSaved)
  assert.notEqual(out.rooms[0], saved.rooms[0])
  assert.equal(out.rooms[0]._key, "a")
})

test("keepKeys ignores tables missing from the sent state", () => {
  const saved = { rooms: [row("x")], offers: [row("o")] } as Record<string, R[]>
  const sent = { rooms: [row("a")] } as Record<string, R[]>
  const out = keepKeys(saved, sent)
  assert.equal(out.offers, saved.offers)
  assert.equal(out.rooms[0]._key, "a")
})

test("keepKeys then overSaved: an untouched table keeps its keys; a table edited in flight keeps the edit", () => {
  const sent = { rooms: [row("a", { room_type: "STD" })], periods: [row("p", { period_code: "P1" })] }
  const cur = { rooms: sent.rooms, periods: [row("p", { period_code: "P1" }), row("q", { period_code: "P2" })] }
  const saved = { rooms: [row("x", { room_type: "STD" })], periods: [row("z", { period_code: "P1" })] }
  const out = overSaved(keepKeys(saved, sent), sent, cur)
  assert.equal(out.rooms[0]._key, "a", "the saved rooms keep the client key")
  assert.equal(out.periods, cur.periods, "the in-flight edit survives")
})
