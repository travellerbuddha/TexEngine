// Guest refusal codes in the booking app (G-70a, audit 2G-2; booking/lib/api.ts): the server's stable code and its
// params reach ApiError, and a code decides the kind before any wording. Run with `npm run test:unit`.
import { test } from "node:test"
import assert from "node:assert/strict"
import { parseError } from "../../src/booking/lib/api.ts"

const body = (extra: Record<string, unknown>, message = "") =>
  JSON.stringify({
    exc_type: "ValidationError",
    _server_messages: JSON.stringify([JSON.stringify({ message })]),
    ...extra,
  })

test("the error body's code and params reach the ApiError", () => {
  const e = parseError(body({ tex_code: "MARKET_RESIDENCY", tex_params: { countries: ["TR"] } }, "Residents only."), 417)
  assert.equal(e.code, "MARKET_RESIDENCY")
  assert.deepEqual(e.params, { countries: ["TR"] })
  assert.equal(e.message, "Residents only.")
})

test("no code, or one that is not a code, gives code null and no params", () => {
  const plain = parseError(body({}, "Check-out must be after check-in."), 417)
  assert.equal(plain.code, null)
  assert.deepEqual(plain.params, {})
  for (const odd of ["sold out", "<b>X</b>", 404, "", "a".repeat(70), "lower_case"]) {
    const e = parseError(body({ tex_code: odd, tex_params: "not an object" }), 417)
    assert.equal(e.code, null, String(odd))
    assert.deepEqual(e.params, {}, String(odd))
  }
  assert.deepEqual(parseError(body({ tex_code: "SOLD_OUT", tex_params: ["a"] }), 417).params, {})
})

test("a code decides the kind, whatever the language of the message", () => {
  // a Turkish sold-out text is classified by its code, not by English wording
  assert.equal(parseError(body({ tex_code: "SOLD_OUT" }, "Üzgünüz — oda az önce tükendi."), 417).kind, "sold_out")
  assert.equal(parseError(body({ tex_code: "EXTRA_SOLD_OUT" }, "Spa: tükendi."), 417).kind, "extra_sold_out")
  assert.equal(parseError(body({ tex_code: "CONTRACT_SUSPENDED" }, "Bu fiyat artık satışta değil."), 417).kind, "expired")
  assert.equal(parseError(body({ tex_code: "NOT_FOUND" }, ""), 404).kind, "not_found")
  assert.equal(parseError(body({ tex_code: "RATE_LIMITED" }, ""), 429).kind, "rate_limit")
})

test("a market code is a refusal the guest can act on, never read as sold out or expired", () => {
  // "not available" wording must not turn a market refusal into a sold-out room
  const e = parseError(body({ tex_code: "MARKET_UNKNOWN", tex_params: { market: "XX" } }, "market XX is not available"), 417)
  assert.equal(e.kind, "invalid")
  assert.equal(e.code, "MARKET_UNKNOWN")
})

test("without a code the existing classification still applies (until every refusal is coded, G-70b)", () => {
  assert.equal(parseError(body({}, "Sorry — Deluxe has just sold out for 2026-12-01."), 417).kind, "sold_out")
  assert.equal(parseError(body({}, "This quote has expired — please search again."), 417).kind, "expired")
  assert.equal(parseError(JSON.stringify({ exc_type: "ExtraSoldOut" }), 417).kind, "extra_sold_out")
  assert.equal(parseError("", 429).kind, "rate_limit")
})
