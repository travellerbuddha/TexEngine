// Promotions as staff read them (UX revision 2026-10; screens/rates/policies/promotions.ts).
// Run with `npm run test:unit`.
import { test } from "node:test"
import assert from "node:assert/strict"
import { backToFront, copyOf, coversEverything, csv, promoState } from "../../src/tex/screens/rates/policies/promotions.ts"

const today = "2026-10-02"
const now = "2026-10-02 10:00:00"

test("where a promotion stands today", () => {
  assert.equal(promoState({ tex_status: "Draft" }, today, now), "draft")
  assert.equal(promoState({}, today, now), "draft")
  assert.equal(promoState({ tex_status: "Active", active_from: "2026-09-01 00:00:00" }, today, now), "live")
  assert.equal(promoState({ tex_status: "Active", active_from: "2026-11-01 00:00:00" }, today, now), "scheduled")
  assert.equal(promoState({ tex_status: "Active", active_from: "2026-10-02T11:00:00" }, today, now), "scheduled")
  // still "Active" in its lifecycle, but its windows are over
  assert.equal(promoState({ tex_status: "Active", sale_to: "2026-09-30" }, today, now), "ended")
  assert.equal(promoState({ tex_status: "Active", stay_to: "2026-10-01" }, today, now), "ended")
  assert.equal(promoState({ tex_status: "Active", stay_to: "2026-10-02" }, today, now), "live")
  assert.equal(promoState({ tex_status: "Superseded" }, today, now), "superseded")
  assert.equal(promoState({ tex_status: "Archived" }, today, now), "archived")
})

test("back-to-front date ranges and an open scope", () => {
  assert.deepEqual(backToFront({ sale_from: "2026-10-01", sale_to: "2026-05-31", stay_from: "2027-07-01", stay_to: "2027-07-31" }), ["sale_to"])
  assert.deepEqual(backToFront({ sale_from: "", sale_to: "2026-05-31" }), [])
  assert.equal(coversEverything({ markets: "", channels: null, room_types: " " }), true)
  assert.equal(coversEverything({ markets: "DE" }), false)
  assert.deepEqual(csv("DE, UK,,"), ["DE", "UK"])
})

test("a similar promotion starts from the terms, never from the identity, the lifecycle or the code", () => {
  const src = {
    name: "PRM-00012",
    promotion_name: "Summer DE 15",
    tex_status: "Active",
    revision_no: 3,
    revision_of: "PRM-00007",
    active_from: "2026-09-01 00:00:00",
    times_redeemed: 41,
    code: "SUMMER15",
    trigger: "Code",
    value_type: "PERCENT",
    value: "15",
    markets: "DE",
    stay_from: "2027-07-01",
  }
  assert.deepEqual(copyOf(src, "promotion_name", (t) => `${t} (copy)`), {
    promotion_name: "Summer DE 15 (copy)",
    trigger: "Code",
    value_type: "PERCENT",
    value: "15",
    markets: "DE",
    stay_from: "2027-07-01",
  })
})
