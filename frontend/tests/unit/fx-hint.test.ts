// LO-38 (Part 2K-6): the hint on a reservation's exchange rate names the provider a manual rate stood in for
// (`bridged_from`, ADR-069 "manual rate bridge": the provider's rate was stale or missing). Run with `npm run test:unit`.
import { test } from "node:test"
import assert from "node:assert/strict"
import { fxRateHint } from "../../src/tex/screens/reservations/lib/fxHint.ts"
import type { FxRate } from "../../src/tex/screens/crs/lib/types.ts"

const t = (key: string, params?: Record<string, string>) => `${key} ${JSON.stringify(params ?? {})}`
const rate = (over: Partial<FxRate> = {}): FxRate => ({
  from: "EUR",
  to: "TRY",
  mode: "PROVIDER",
  sell_rate: "51.510000",
  provider: "TCMB",
  provider_rate: "50.000000",
  rate_date: "2026-10-01",
  policy_id: "FXP-0001",
  as_of: null,
  used_for: ["accommodation"],
  ...over,
})

test("a manual rate standing in for a provider says which", () => {
  const hint = fxRateHint(rate({ provider: "MANUAL", provider_rate: null, bridged_from: "TCMB" }), t)
  assert.match(hint, /res\.snap\.fx_bridging \{"provider":"TCMB"\}/)
  assert.match(hint.split(" · ")[0], /^MANUAL\b/)
})

test("a provider's own rate reads as before", () => {
  assert.equal(fxRateHint(rate(), t), "TCMB 50.000000 2026-10-01 · FXP-0001 · accommodation")
  assert.equal(fxRateHint(rate({ provider: null, policy_id: null, used_for: ["cost", "extra:SPA"] }), t), "cost, extra:SPA")
})
