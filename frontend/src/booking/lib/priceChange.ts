// What a new quote of a room changes in the price the guest was shown (O-30, LO-32). Pure, no React; unit tested
// with `node --test` (tests/unit/price-change.test.ts).
import type { QuoteResponse, RoomQuote } from "../types"

export interface PriceChange {
  room: number
  from: string
  to: string
  currency: string
}

/** The extras a quote adds (code, quantity and days), as one comparable string. */
function added(q: RoomQuote): string {
  return (q.extras ?? [])
    .filter((e) => e.ok)
    .map((e) => [(e.code ?? "").toUpperCase(), e.quantity, (e.service_dates ?? []).join(" ")].join("|"))
    .sort()
    .join(",")
}

/**
 * The change the new quote `res` of room `room` makes, or null.
 *
 * Against the last quote the guest saw of the room (`shown`), when there is one: the totals, extras included, so a
 * new price of an extra is told too. When the two add other extras (the guest changed them since, or the new quote
 * cannot add one, which has its own notice and is not charged), the room's own price is compared. The server's flag
 * is not used then: it compares with the search, so a price the guest accepted would be told again, from the
 * search's price.
 *
 * Without one, the search's offer (`offer`, the room as the results priced it) and the server's flag decide.
 */
export function priceChange(room: number, res: QuoteResponse, shown: RoomQuote | null, offer: RoomQuote): PriceChange | null {
  const q = res.quote
  if (!q) return null
  if (shown) {
    const k = added(shown) === added(q) ? "total" : "accommodation"
    const from = shown.totals[k]
    const to = q.totals[k]
    return from && to && from !== to ? { room, from, to, currency: q.currency } : null
  }
  const before = offer.totals.accommodation
  const after = q.totals.accommodation
  if (res.price_changed || (before && after && before !== after))
    return { room, from: res.price_changed && res.previous_total ? res.previous_total : before, to: res.price_changed ? q.totals.total : after, currency: q.currency }
  return null
}
