// The checkout's payment methods when the server basket cannot be read (O-15, audit 2F-2;
// booking/lib/methods.ts). Run with `npm run test:unit`.
import { test } from "node:test"
import assert from "node:assert/strict"
import { fallbackChoices } from "../../src/booking/lib/methods.ts"

test("the fallback offers the card only: the hotel's payment method rules are the server's to apply", () => {
  // a hotel that sells no transfer or pay-at-the-hotel booking must not be offered them by a failed basket call;
  // the server refuses a method the hotel's rules do not offer (create_booking)
  assert.deepEqual(
    fallbackChoices().map((c) => c.method),
    ["Card"],
  )
})

test("the fallback carries no account and no amount: the server decides both", () => {
  const [card] = fallbackChoices()
  assert.deepEqual(card, { method: "Card", account: null, via: null, dueNow: null, later: null, sandbox: false })
})
