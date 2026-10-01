// A campaign link's market the server refused (G-55b, audit 2G-2; booking/lib/marketLink.ts): only a market refusal
// sends the search on without the link, with a notice and a funnel event. Run with `npm run test:unit`.
import { test } from "node:test"
import assert from "node:assert/strict"
import { ApiError } from "../../src/booking/lib/api.ts"
import { marketNotice, marketRefusal, refusedLinkPayload } from "../../src/booking/lib/marketLink.ts"

const refused = (code: string | null, params: Record<string, unknown> = {}) => new ApiError("x", 417, "MarketRefused", "invalid", code, params)

test("a market code is a refused link; any other refusal is not", () => {
  for (const code of ["MARKET_UNKNOWN", "MARKET_AMBIGUOUS", "MARKET_REQUIRED", "MARKET_NOT_ALLOWED", "MARKET_RESIDENCY"])
    assert.deepEqual(marketRefusal(refused(code))?.reason, code, code)
  // bad dates, an unknown hotel, a code-less validation error: the search error is shown, never hidden by a fallback
  for (const code of ["DATES_INVALID", "HOTEL_NOT_FOUND", null]) assert.equal(marketRefusal(refused(code)), null, String(code))
  assert.equal(marketRefusal(new Error("boom")), null)
  assert.equal(marketRefusal(new ApiError("", 0, "NetworkError", "network")), null)
})

test("a residents-only refusal carries the market's countries", () => {
  assert.deepEqual(marketRefusal(refused("MARKET_RESIDENCY", { market: "TR", countries: ["TR", 7, "CY"] })), {
    reason: "MARKET_RESIDENCY",
    countries: ["TR", "CY"],
  })
})

test("each refusal has its notice", () => {
  assert.equal(marketNotice("MARKET_NOT_ALLOWED"), "market.refused.unavailable")
  assert.equal(marketNotice("MARKET_UNKNOWN"), "market.refused.unavailable")
  assert.equal(marketNotice("MARKET_RESIDENCY"), "market.refused.residency")
  assert.equal(marketNotice("MARKET_AMBIGUOUS"), "market.refused.other")
  assert.equal(marketNotice("MARKET_REQUIRED"), "market.refused.other")
})

test("the funnel event says the refusal, the link's market and its two-letter country, nothing else", () => {
  assert.deepEqual(refusedLinkPayload("MARKET_NOT_ALLOWED", "tr", "de"), { reason: "MARKET_NOT_ALLOWED", market: "TR", country: "DE" })
  assert.deepEqual(refusedLinkPayload("MARKET_RESIDENCY", "TR", null), { reason: "MARKET_RESIDENCY", market: "TR" })
  assert.deepEqual(refusedLinkPayload("MARKET_UNKNOWN", null, "Germany"), { reason: "MARKET_UNKNOWN" })
})
