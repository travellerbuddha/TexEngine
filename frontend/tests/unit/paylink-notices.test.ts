// The payment-link page's notices (K2, audit 1c-son; booking/lib/paylink.ts). Run with `npm run test:unit`.
import { test } from "node:test"
import assert from "node:assert/strict"
import { payLinkNotices } from "../../src/booking/lib/paylink.ts"

const shown = (n: ReturnType<typeof payLinkNotices>) =>
  (["failed", "verifying", "late", "closed"] as const).filter((k) => n[k])

test("a link whose booking could not take its money shows only the late-payment notice", () => {
  for (const late of ["contact", "refund"] as const) {
    for (const status of ["Cancelled", "Expired", "Partially Paid", "Paid"]) {
      // the guest came back from the gateway: its money was parked for the hotel, or refunded
      assert.deepEqual(shown(payLinkNotices({ status, late_payment: late }, "succeeded")), ["late"], `${status} ${late}`)
      assert.deepEqual(shown(payLinkNotices({ status, late_payment: late }, null)), ["late"], `${status} ${late}`)
    }
  }
})

test("a link paid a moment ago is being confirmed; a closed one asks for a new link", () => {
  assert.deepEqual(shown(payLinkNotices({ status: "Active" }, "succeeded")), ["verifying"])
  assert.deepEqual(shown(payLinkNotices({ status: "Paid" }, "succeeded")), [])
  assert.deepEqual(shown(payLinkNotices({ status: "Active" }, "failed")), ["failed"])
  assert.deepEqual(shown(payLinkNotices({ status: "Expired" }, null)), ["closed"])
  assert.deepEqual(shown(payLinkNotices({ status: "Cancelled", late_payment: null }, null)), ["closed"])
})
