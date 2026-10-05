// LO-35 (Part 2K-5): a fixed deposit is taken once per booking and policy (the server's `deposit_shares`, ADR-067),
// so the checkout names it once: on the first room that carries the policy, for the whole booking; the other rooms
// of that policy say it is taken with that room. Run with `npm run test:unit` (node --test).
import { test } from "node:test"
import assert from "node:assert/strict"
import type { I18n } from "../../src/booking/i18n"
import { bookingPaymentTerms } from "../../src/booking/lib/policy.ts"
import type { RatePlanInfo } from "../../src/booking/types.ts"

const i18n = {
  t: (key: string, params?: Record<string, unknown>) => `${key} ${JSON.stringify(params ?? {})}`,
  money: (value: string, currency: string) => `${value} ${currency}`,
} as unknown as I18n

const plan = (payment: RatePlanInfo["payment_policy"]): RatePlanInfo => ({
  code: "FLEX",
  name: "Flexible",
  refundable: true,
  payment_policy: payment,
})
const deposit100 = plan({ id: "PP-100", deposit_type: "FIXED", deposit_value: "100", currency: "EUR" })
const room = (info: RatePlanInfo) => ({ info, currency: "EUR" })
const naming = (lines: ({ text: string } | null)[]) => lines.filter((l) => l?.text.includes("100 EUR")).length

test("three rooms of one fixed-deposit policy name the deposit once, for the booking", () => {
  const lines = bookingPaymentTerms(i18n, [room(deposit100), room(deposit100), room(deposit100)])
  assert.equal(naming(lines), 1)
  assert.match(lines[0]!.text, /policy\.depositFixedBooking/)
  for (const l of lines.slice(1)) assert.match(l!.text, /policy\.depositWithRoom \{"n":1\}/)
})

test("each fixed-deposit policy is named once, on its own first room", () => {
  const other = plan({ id: "PP-50", deposit_type: "FIXED", deposit_value: "50", currency: "EUR" })
  const lines = bookingPaymentTerms(i18n, [room(other), room(deposit100), room(other), room(deposit100)])
  assert.match(lines[0]!.text, /policy\.depositFixedBooking.*50 EUR/)
  assert.match(lines[1]!.text, /policy\.depositFixedBooking.*100 EUR/)
  assert.match(lines[2]!.text, /policy\.depositWithRoom \{"n":1\}/)
  assert.match(lines[3]!.text, /policy\.depositWithRoom \{"n":2\}/)
})

test("one room, or another kind of deposit, reads as before", () => {
  assert.match(bookingPaymentTerms(i18n, [room(deposit100)])[0]!.text, /^policy\.depositFixed \{/)
  const pct = plan({ id: "PP-30", deposit_type: "PERCENT", deposit_value: "30.00" })
  const lines = bookingPaymentTerms(i18n, [room(pct), room(pct)])
  for (const l of lines) assert.match(l!.text, /policy\.depositPercent/)
  // a room not chosen yet stays empty
  assert.deepEqual(bookingPaymentTerms(i18n, [room(deposit100), null, room(deposit100)])[1], null)
})

// 2K-5 review: "for the whole booking" only where the booking has two rooms or more of that policy; a fixed deposit
// one room alone carries is that room's (the other rooms pay their own policy's deposit as well)
test("a fixed deposit only one room carries reads as that room's own, also in a booking of several rooms", () => {
  const pct = plan({ id: "PP-30", deposit_type: "PERCENT", deposit_value: "30.00" })
  const other = plan({ id: "PP-50", deposit_type: "FIXED", deposit_value: "50", currency: "EUR" })
  const lines = bookingPaymentTerms(i18n, [room(deposit100), room(pct), room(other)])
  assert.match(lines[0]!.text, /^policy\.depositFixed \{.*100 EUR/)
  assert.match(lines[1]!.text, /policy\.depositPercent/)
  assert.match(lines[2]!.text, /^policy\.depositFixed \{.*50 EUR/)
  // a second room of the policy makes it the booking's again
  const four = bookingPaymentTerms(i18n, [room(deposit100), room(pct), room(other), room(deposit100)])
  assert.match(four[0]!.text, /policy\.depositFixedBooking.*100 EUR/)
  assert.match(four[2]!.text, /^policy\.depositFixed \{.*50 EUR/)
  assert.match(four[3]!.text, /policy\.depositWithRoom \{"n":1\}/)
})

// §6K5 (batch 2Q): a room takes at most its own total of the booking's fixed deposit, the rest goes with the next room
// (the server's `deposit_shares`): with a first room of 60 EUR and a deposit of 100 EUR, the second room pays 40 EUR
// of it, which "taken once for the booking, with room 1" did not say. The basket gives each room's share (`due_now`)
test("a later room that pays part of the booking's deposit names its share", () => {
  const lines = bookingPaymentTerms(i18n, [
    { ...room(deposit100), share: "60.00" },
    { ...room(deposit100), share: "40.00" },
    { ...room(deposit100), share: "0.00" },
  ])
  assert.match(lines[0]!.text, /policy\.depositFixedBooking.*100 EUR/)
  assert.match(lines[1]!.text, /^policy\.depositShare \{"amount":"40\.00 EUR"\}/)
  assert.match(lines[2]!.text, /policy\.depositWithRoom \{"n":1\}/)
  // without the basket (still loading, or refused) the lines read as before
  const before = bookingPaymentTerms(i18n, [room(deposit100), { ...room(deposit100), share: null }])
  assert.match(before[1]!.text, /policy\.depositWithRoom \{"n":1\}/)
})
