// Guest refusal codes in the booking app (G-70, audits 2G-2 and 2G-3; booking/lib/api.ts, booking/lib/refusals.ts): the
// server's stable code and its params reach ApiError, a code decides the kind (never the wording), and the guest reads
// the code's text in their language. Run with `npm run test:unit`.
import { test } from "node:test"
import assert from "node:assert/strict"
import { readFileSync } from "node:fs"
import { parseError } from "../../src/booking/lib/api.ts"
import { KIND_BY_CODE, refusalMessage, type RefusalI18n } from "../../src/booking/lib/refusals.ts"

const catalog = (lang: string): Record<string, string> =>
  JSON.parse(readFileSync(new URL(`../../src/booking/i18n/${lang}.json`, import.meta.url), "utf8"))

/** The booking app's ``t`` over one catalog (English as its fallback), as ``i18n/index.tsx`` interpolates. */
function i18nFor(lang: string): RefusalI18n {
  const cat = catalog(lang)
  const en = catalog("en")
  return {
    t: ((key: string, vars?: Record<string, string | number>) => {
      const s = cat[key] ?? en[key]
      if (s === undefined) return key
      return s.replace(/\{(\w+)\}/g, (m, k: string) => (vars?.[k] !== undefined ? String(vars[k]) : m))
    }) as RefusalI18n["t"],
    locale: lang,
    day: (v) => `day(${v})`,
    money: (amount, ccy) => `${amount} ${ccy}`,
  }
}

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
  // a room type disabled since the search (LO-03): searched again, whatever the wording
  assert.equal(parseError(body({ tex_code: "ROOM_NOT_SOLD" }, "Bu oda artık satılmıyor."), 417).kind, "expired")
  assert.equal(parseError(body({ tex_code: "NOT_FOUND" }, ""), 404).kind, "not_found")
  assert.equal(parseError(body({ tex_code: "RATE_LIMITED" }, ""), 429).kind, "rate_limit")
})

test("a market code is a refusal the guest can act on, never read as sold out or expired", () => {
  // "not available" wording must not turn a market refusal into a sold-out room
  const e = parseError(body({ tex_code: "MARKET_UNKNOWN", tex_params: { market: "XX" } }, "market XX is not available"), 417)
  assert.equal(e.kind, "invalid")
  assert.equal(e.code, "MARKET_UNKNOWN")
})

test("the server's fallback codes classify as their HTTP status says", () => {
  // an expired manage link has its own code now (G-70b): a link the guest cannot use, whatever the wording
  assert.equal(parseError(body({ exc_type: "PermissionError", tex_code: "MANAGE_LINK_EXPIRED" }, "This link has expired."), 403).kind, "permission")
  assert.equal(parseError(body({ exc_type: "PermissionError", tex_code: "NOT_PERMITTED" }, "Invalid link."), 403).kind, "permission")
  // a quote of a market the site no longer sells: search again
  assert.equal(parseError(body({ tex_code: "MARKET_NOT_ALLOWED" }, "These prices are not sold on this site."), 417).kind, "expired")
})

test("without a code an error is classified by its status and type only, never by its wording (G-70b)", () => {
  // an English "sold out" text without a code is not a sold-out room: every guest refusal carries its code
  assert.equal(parseError(body({}, "Sorry — Deluxe has just sold out for 2026-12-01."), 417).kind, "invalid")
  assert.equal(parseError(body({}, "This quote has expired — please search again."), 417).kind, "invalid")
  assert.equal(parseError(body({ exc_type: "DoesNotExistError" }, "Booking site not found."), 404).kind, "not_found")
  assert.equal(parseError(JSON.stringify({ exc_type: "ExtraSoldOut" }), 417).kind, "extra_sold_out")
  assert.equal(parseError("", 429).kind, "rate_limit")
  assert.equal(parseError("<html>gateway</html>", 502).kind, "server")
})

test("the kinds G-70b adds: another payment method, the same step again, the time to pay is over", () => {
  assert.equal(parseError(body({ tex_code: "PAYMENT_METHOD_UNAVAILABLE" }, "Bu ödeme yöntemi kullanılamıyor."), 417).kind, "payment_method")
  assert.equal(parseError(body({ tex_code: "PAY_AT_HOTEL_NOT_ALLOWED" }, ""), 417).kind, "payment_method")
  assert.equal(parseError(body({ exc_type: "PaymentBusy", tex_code: "PAYMENT_BUSY" }, "A payment is being started."), 417).kind, "retry")
  assert.equal(parseError(body({ tex_code: "BUSY" }, "The hotel is very busy right now."), 417).kind, "retry")
  assert.equal(parseError(body({ exc_type: "HoldExpired", tex_code: "HOLD_EXPIRED" }, ""), 417).kind, "hold_expired")
  // the bank is reviewing the payment: never "try again" (review round 1)
  assert.notEqual(parseError(body({ exc_type: "PaymentBusy", tex_code: "PAYMENT_UNDER_REVIEW" }, ""), 417).kind, "retry")
  assert.equal(parseError(body({ tex_code: "PROPOSAL_EXPIRED" }, "This offer has expired."), 417).kind, "expired")
  assert.equal(parseError(body({ tex_code: "LINK_INVALID", exc_type: "DoesNotExistError" }, ""), 404).kind, "not_found")
})

test("the guest reads the code's text in their language, with its params", () => {
  const tr = i18nFor("tr")
  // a Turkish guest never sees the server's English text
  const soldOut = parseError(body({ tex_code: "SOLD_OUT", tex_params: { room: "Deluxe", date: "2026-12-01" } },
    "Sorry — Deluxe has just sold out for 2026-12-01."), 417)
  assert.equal(refusalMessage(tr, soldOut), "Üzgünüz — Deluxe day(2026-12-01) için az önce tükendi.")
  const over = parseError(body({ tex_code: "LINK_OVER_OWED", tex_params: { amount: "200.00", owed: "120.00", currency: "EUR" } }), 417)
  assert.match(refusalMessage(i18nFor("en"), over), /asks 200\.00 EUR, more than the booking still owes \(120\.00 EUR\)/)
  assert.equal(refusalMessage(tr, parseError(body({ tex_code: "ROOM_NOT_ACTIVE", tex_params: { status: "Cancelled" } }), 417)),
    "Bu oda iptal edilmiş veya artık değişikliğe açık değil.")
  // a placeholder without its value never reaches the screen: the server's message instead
  assert.equal(refusalMessage(tr, parseError(body({ tex_code: "CHANNEL_BOOKING" }, "Sold by X: cancel it on the channel."), 417)),
    "Sold by X: cancel it on the channel.")
  // a code without a text, or none: the server's message, else the generic text
  assert.equal(refusalMessage(tr, { code: "NOT_A_CODE", message: "server text" }), "server text")
  assert.equal(refusalMessage(tr, { code: null, message: "" }), catalog("tr")["errors.generic"])
})

test("every code the booking app acts on has a guest text in every language", () => {
  for (const lang of ["en", "tr", "de", "ru", "ro", "pl"]) {
    const cat = catalog(lang)
    const missing = Object.keys(KIND_BY_CODE).filter((code) => !(`refusal.${code}` in cat))
    assert.deepEqual(missing, [], lang)
  }
})
