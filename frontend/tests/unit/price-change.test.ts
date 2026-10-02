// LO-32 (Part 2K-5): a quote made again (O-30) is compared with the last quote the guest saw of the room, not with the
// search; the server's own flag compares with the search, so it decides only when the guest saw no quote yet
// (booking/lib/priceChange.ts). Run with `npm run test:unit` (node --test).
import { test } from "node:test"
import assert from "node:assert/strict"
import { priceChange } from "../../src/booking/lib/priceChange.ts"
import type { ExtraOutcome, QuoteResponse, RoomQuote } from "../../src/booking/types.ts"

const extra = (code: string, amount: string, ok = true): ExtraOutcome => ({
  code,
  name: code,
  ok,
  quantity: "1",
  amount: ok ? amount : "0.00",
  currency: "EUR",
  pricing_mode: "PER_STAY",
  ...(ok ? {} : { reason: "sold out on 2027-06-10" }),
})
const quote = (accommodation: string, total: string, extras: ExtraOutcome[] = []): RoomQuote =>
  ({ sellable: true, currency: "EUR", lines: [], promotions: [], extras, taxes: [], totals: { accommodation, total }, nights: [] }) as RoomQuote
const made = (q: RoomQuote, server: { price_changed?: boolean; previous_total?: string } = {}): QuoteResponse => ({ ok: true, quote_id: "Q-1", quote: q, ...server })
// the room as the search priced it
const offer = quote("200.00", "200.00")

test("the price the guest accepted is not announced again, though the server marks it changed against the search", () => {
  const shown = quote("210.00", "210.00")
  assert.equal(priceChange(0, made(quote("210.00", "210.00"), { price_changed: true, previous_total: "200.00" }), shown, offer), null)
})

test("a new price after an accepted one is announced from the price the guest saw", () => {
  const shown = quote("210.00", "210.00")
  const change = priceChange(0, made(quote("220.00", "220.00"), { price_changed: true, previous_total: "200.00" }), shown, offer)
  assert.deepEqual(change, { room: 0, from: "210.00", to: "220.00", currency: "EUR" })
})

test("an extra the new quote cannot add is not a price change: it has its own notice and is not charged", () => {
  const shown = quote("200.00", "230.00", [extra("TRANSFER", "30.00")])
  assert.equal(priceChange(0, made(quote("200.00", "200.00", [extra("TRANSFER", "30.00", false)])), shown, offer), null)
  // the room's own price is still compared then
  const dearer = priceChange(0, made(quote("210.00", "210.00", [extra("TRANSFER", "30.00", false)])), shown, offer)
  assert.deepEqual(dearer, { room: 0, from: "200.00", to: "210.00", currency: "EUR" })
})

test("an extra the guest added since is their own choice, not a price change; the room's price is still compared", () => {
  const shown = quote("210.00", "210.00")
  assert.equal(priceChange(0, made(quote("210.00", "240.00", [extra("TRANSFER", "30.00")])), shown, offer), null)
  const dearer = priceChange(0, made(quote("220.00", "250.00", [extra("TRANSFER", "30.00")])), shown, offer)
  assert.deepEqual(dearer, { room: 0, from: "210.00", to: "220.00", currency: "EUR" })
})

test("the same extras at a new price are announced, extras included", () => {
  const shown = quote("200.00", "230.00", [extra("TRANSFER", "30.00")])
  const change = priceChange(0, made(quote("200.00", "240.00", [extra("TRANSFER", "40.00")])), shown, offer)
  assert.deepEqual(change, { room: 0, from: "230.00", to: "240.00", currency: "EUR" })
})

test("before the guest saw a quote, the search's offer and the server's flag decide, as before", () => {
  assert.equal(priceChange(1, made(quote("200.00", "200.00")), null, offer), null)
  assert.deepEqual(priceChange(1, made(quote("210.00", "210.00")), null, offer), { room: 1, from: "200.00", to: "210.00", currency: "EUR" })
  assert.deepEqual(priceChange(1, made(quote("200.00", "204.00"), { price_changed: true, previous_total: "200.00" }), null, offer), {
    room: 1,
    from: "200.00",
    to: "204.00",
    currency: "EUR",
  })
})
