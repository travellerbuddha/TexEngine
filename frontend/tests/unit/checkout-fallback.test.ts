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

// LO-14 (Part 2K-5): a basket that could not be read offers no guessed method. The card alone was offered, also at
// a hotel that sells no card: the server refused it and the guest had no way on. They are told, and may try again.
test("a basket that could not be read offers no method and asks to try again", async () => {
  const { checkoutChoices } = await import("../../src/booking/lib/methods.ts")
  assert.deepEqual(checkoutChoices({ status: "error", data: null }), { choices: [], failed: true })
})

test("a basket read offers its available methods; one not read yet offers the card, as before", async () => {
  const { checkoutChoices } = await import("../../src/booking/lib/methods.ts")
  const method = (m: string, available = true, account: string | null = null) =>
    ({ method: m, provider_account: account, label: m, provider: null, sandbox: false, available, due_now: "0.00",
       balance_after: "100.00" }) as never
  const data = { methods: [method("Bank Transfer"), method("Card", false), method("Voucher")] } as never
  assert.deepEqual(checkoutChoices({ status: "done", data }).choices.map((c) => c.method), ["Bank Transfer"])
  assert.deepEqual(checkoutChoices({ status: "done", data }).failed, false)
  assert.deepEqual(checkoutChoices({ status: "idle", data: null }), { choices: fallbackChoices(), failed: false })
})

// 2K-5 review: a basket refused by a rate limit or a coded refusal says so; trying again would fail the same way
test("a basket that could not be read says why: a rate limit, a refusal in its own words, else the connection", async () => {
  const { basketFailureText } = await import("../../src/booking/lib/methods.ts")
  const i18n = { t: (key: string) => (key === "refusal.QUOTE_INVALID" ? "Your selection is no longer valid." : key), locale: "en", day: (v: string) => v, money: (a: string | null | undefined) => a ?? "" } as unknown as Parameters<typeof basketFailureText>[0]
  assert.deepEqual(basketFailureText(i18n, { kind: "rate_limit", code: "RATE_LIMITED" }), { title: "errors.rateLimitTitle", body: "errors.rateLimitBody" })
  assert.deepEqual(basketFailureText(i18n, { kind: "expired", code: "QUOTE_INVALID" }), { title: "payment.optionsFailedTitle", body: "Your selection is no longer valid." })
  assert.deepEqual(basketFailureText(i18n, { kind: "network", message: "" }), { title: "payment.optionsFailedTitle", body: "payment.optionsFailedBody" })
  assert.deepEqual(basketFailureText(i18n, null), { title: "payment.optionsFailedTitle", body: "payment.optionsFailedBody" })
})

// §5b, §6G3 (batch 2P): a basket read but no longer usable sent the guest to "Refresh prices" whatever its rooms'
// problem; for a price already booked (another tab, the browser's history) a refresh leads to a second booking
test("a basket read but not usable asks for a refresh with its problem's code, a booked price first", async () => {
  const { basketExpiry } = await import("../../src/booking/lib/methods.ts")
  const data = (usable: boolean, ...codes: (string | null)[]) =>
    ({ usable, methods: [], rooms: codes.map((c) => ({ problem: c && "…", problem_code: c })) }) as never
  assert.equal(basketExpiry({ status: "done", data: data(true, null) }), null)
  assert.deepEqual(basketExpiry({ status: "done", data: data(false, null, "QUOTE_EXPIRED") }), { code: "QUOTE_EXPIRED", message: "" })
  assert.deepEqual(basketExpiry({ status: "done", data: data(false, "QUOTE_EXPIRED", "QUOTE_USED") }), { code: "QUOTE_USED", message: "" })
  assert.deepEqual(basketExpiry({ status: "done", data: data(false, null) }), { code: null, message: "" })   // an older server
  assert.equal(basketExpiry({ status: "idle", data: null }), null)
})

// §6K5 (batch 2P): a basket the server refuses as gone (QUOTE_INVALID, SEARCH_AGAIN…) showed "Try again", which fails
// the same way; it takes the refresh path, the refusal's code with it. A connection or a rate limit still asks to retry
test("a basket refused as gone asks for a refresh; any other failure still asks to try again", async () => {
  const { basketExpiry } = await import("../../src/booking/lib/methods.ts")
  const gone = { kind: "expired", code: "QUOTE_INVALID", message: "Your selection is no longer valid." }
  assert.deepEqual(basketExpiry({ status: "error", data: null, error: gone }), { code: "QUOTE_INVALID", message: gone.message })
  assert.deepEqual(basketExpiry({ status: "error", data: null, error: { kind: "expired", code: "SEARCH_AGAIN" } }), { code: "SEARCH_AGAIN", message: "" })
  assert.equal(basketExpiry({ status: "error", data: null, error: { kind: "network", message: "" } }), null)
  assert.equal(basketExpiry({ status: "error", data: null, error: { kind: "rate_limit", code: "RATE_LIMITED" } }), null)
  assert.equal(basketExpiry({ status: "error", data: null }), null)
})
