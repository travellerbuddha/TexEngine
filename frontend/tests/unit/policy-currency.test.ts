// Unit tests for the currency a rate plan's fixed deposit is written in on the guest's offer
// (Y-3 B, ADR-067). Run with `npm run test:unit` (node --test).
import { test } from "node:test"
import assert from "node:assert/strict"
import type { I18n } from "../../src/booking/i18n"
import { paymentTerms } from "../../src/booking/lib/policy.ts"
import type { RatePlanInfo } from "../../src/booking/types.ts"

// records the currency each amount is written in
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

test("a fixed deposit is written in its policy's own currency, not the quote's", () => {
  const { text } = paymentTerms(i18n, plan({ deposit_type: "FIXED", deposit_value: "100", currency: "EUR" }), "TRY")
  assert.match(text, /policy\.depositFixed/)
  assert.match(text, /100 EUR/)
  assert.doesNotMatch(text, /TRY/)
})

test("a fixed deposit of a policy frozen without a currency keeps the quote's (sold before ADR-067)", () => {
  const { text } = paymentTerms(i18n, plan({ deposit_type: "FIXED", deposit_value: "100" }), "TRY")
  assert.match(text, /100 TRY/)
})

test("other deposits name no amount", () => {
  const { text } = paymentTerms(i18n, plan({ deposit_type: "PERCENT", deposit_value: "30.00", currency: "EUR" }), "TRY")
  assert.match(text, /policy\.depositPercent/)
  assert.doesNotMatch(text, /EUR|TRY/)
})
