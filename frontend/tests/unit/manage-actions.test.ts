// The manage page's room actions (O-16, audit Part 2A; booking/lib/manage.ts). Run with `npm run test:unit`.
import { test } from "node:test"
import assert from "node:assert/strict"
import { roomActions } from "../../src/booking/lib/manage.ts"

const open = { self_service: true, changes_blocked: null }

test("from the arrival day the page offers no cancellation, while a change still starts that day", () => {
  // the server's answer for a confirmed stay arriving today: changeable, not cancellable
  const today = roomActions({ status: "Confirmed", can_change: true, can_cancel: false }, open)
  assert.deepEqual(today, { change: true, extras: true, cancel: false })
  // arrived yesterday (still Confirmed: TEX never sets Checked In)
  assert.equal(roomActions({ status: "Confirmed", can_change: false, can_cancel: false }, open).cancel, false)
  // the day before the arrival
  assert.equal(roomActions({ status: "Confirmed", can_change: true, can_cancel: true }, open).cancel, true)
})

test("a room the server says nothing about offers no cancellation", () => {
  assert.equal(roomActions({ status: "Confirmed", can_change: true }, open).cancel, false)
})

test("a closed stay or a booking without self-service offers nothing", () => {
  const none = { change: false, extras: false, cancel: false }
  for (const status of ["Cancelled", "Checked In", "Checked Out", "No Show"])
    assert.deepEqual(roomActions({ status, can_change: true, can_cancel: true }, open), none, status)
  assert.deepEqual(roomActions({ status: "Confirmed", can_change: true, can_cancel: true }, { self_service: false }), none)
})

test("a blocked booking still cancels before the arrival day, but changes nothing", () => {
  const blocked = { self_service: true, changes_blocked: "PAYMENT_PENDING" }
  assert.deepEqual(roomActions({ status: "Pending Payment", can_change: false, can_cancel: true }, blocked),
    { change: false, extras: true, cancel: true })
})
