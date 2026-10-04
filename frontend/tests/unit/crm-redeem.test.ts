// §6K2 "Not done" (batch 2O): the CRM offered "Redeem" on a channel's booking, which the server refuses (LO-02: its
// price and payment are the channel's). The bookings points can be redeemed on: a TEX booking, not cancelled, not a
// channel's, at a hotel where the user may take payments. Run with `npm run test:unit`.
import { test } from "node:test"
import assert from "node:assert/strict"
import { redeemableBookings } from "../../src/tex/screens/crm/profile/redeem.ts"

const stay = (over: Record<string, unknown>) => ({
  name: "RES-1", property: "Aurora", status: "Confirmed", tex_booking: "TB-1", channel_booking: false, ...over,
})

test("a channel's booking, a cancelled one and one without the right are left out; each booking once", () => {
  const can = (cap: string, property?: string | null) => cap === "payment.link" && property === "Aurora"
  const stays = [
    stay({ name: "RES-1", tex_booking: "TB-1" }),
    stay({ name: "RES-2", tex_booking: "TB-1" }),
    stay({ name: "RES-3", tex_booking: "TB-2", channel_booking: true }),
    stay({ name: "RES-4", tex_booking: "TB-3", status: "Cancelled" }),
    stay({ name: "RES-5", tex_booking: "TB-4", property: "Elsewhere" }),
    stay({ name: "RES-6", tex_booking: null }),
  ]
  assert.deepEqual(redeemableBookings(stays, can).map((s) => s.tex_booking), ["TB-1"])
  assert.deepEqual(redeemableBookings([stays[2]], can), [])
})
