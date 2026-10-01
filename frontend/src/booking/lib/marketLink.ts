// A campaign link's market the server refused (G-55b, ADR-070): the search runs again without the link, the guest
// is told why, and the funnel counts it. Only a market refusal does this: any other error (bad dates, an unknown
// hotel) is the search's own error and is shown as one. Pure: no DOM, no React.
import { ApiError } from "./api.ts"

export const MARKET_REFUSALS = ["MARKET_UNKNOWN", "MARKET_AMBIGUOUS", "MARKET_REQUIRED", "MARKET_NOT_ALLOWED", "MARKET_RESIDENCY"] as const
export type MarketRefusalCode = (typeof MARKET_REFUSALS)[number]

export interface MarketRefusal {
  reason: MarketRefusalCode
  /** a residents-only market's countries (MARKET_RESIDENCY) */
  countries?: string[]
}

/** The market refusal `e` is (by its code, G-70a), or null for anything else. */
export function marketRefusal(e: unknown): MarketRefusal | null {
  if (!(e instanceof ApiError) || !e.code || !(MARKET_REFUSALS as readonly string[]).includes(e.code)) return null
  const reason = e.code as MarketRefusalCode
  const countries = Array.isArray(e.params.countries) ? e.params.countries.filter((c): c is string => typeof c === "string") : null
  return countries && reason === "MARKET_RESIDENCY" ? { reason, countries } : { reason }
}

/** The notice the results page shows for a refused link. */
export function marketNotice(reason: MarketRefusalCode): "market.refused.unavailable" | "market.refused.residency" | "market.refused.other" {
  if (reason === "MARKET_NOT_ALLOWED" || reason === "MARKET_UNKNOWN") return "market.refused.unavailable"
  if (reason === "MARKET_RESIDENCY") return "market.refused.residency"
  return "market.refused.other"
}

/** The funnel event's payload (`public.track` keeps these three only, ADR-056): the refusal, the link's market and its
 * two-letter country. Never the guest's details or the manage token (O-27). */
export function refusedLinkPayload(reason: MarketRefusalCode, market: string | null, country: string | null) {
  const out: { reason: MarketRefusalCode; market?: string; country?: string } = { reason }
  if (market) out.market = market.toUpperCase()
  if (country && /^[A-Za-z]{2}$/.test(country)) out.country = country.toUpperCase()
  return out
}
