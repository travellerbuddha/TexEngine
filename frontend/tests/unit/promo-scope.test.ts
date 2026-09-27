// What a promotion can apply to (O-1, ADR-068): the promotion editor offers only what a room can use,
// as TEX Promotion's validate refuses the rest. Run with `npm run test:unit` (node --test).
import { test } from "node:test"
import assert from "node:assert/strict"
import { APPLIES_TO, promoAppliesTo } from "../../src/tex/screens/rates/lib/options.ts"

test("the whole booking or its extras take a percentage or a fixed amount for the stay, sold", () => {
  for (const value_type of ["PERCENT", "FIXED_STAY"]) {
    assert.deepEqual(promoAppliesTo({ stage: "SELL", value_type }), APPLIES_TO)
    assert.deepEqual(promoAppliesTo({ value_type }), APPLIES_TO) // a new record is SELL
  }
})

test("any other value type, or a cost-stage offer, applies to the accommodation only", () => {
  for (const value_type of ["FIXED_NIGHT", "MULTIPLIER", "FREE_NIGHTS", "VALUE_ADDED"])
    assert.deepEqual(promoAppliesTo({ stage: "SELL", value_type }), ["ACCOMMODATION"])
  for (const value_type of ["PERCENT", "FIXED_STAY"]) assert.deepEqual(promoAppliesTo({ stage: "COST", value_type }), ["ACCOMMODATION"])
})
