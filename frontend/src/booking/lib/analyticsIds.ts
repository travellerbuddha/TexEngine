// The analytics ids a booking site may carry (G-62): one rule for the booking engine
// (lib/analytics.ts), the admin form (tex/screens/booking-engine/site.ts) and the server
// (TEXBookingSite.validate, the same patterns). A value is trimmed, then must match, so a
// misconfigured id never becomes script. Pure, no imports; unit tested with `node --test`
// (tests/unit/analytics-ids.test.ts).

export const ANALYTICS_ID_PATTERNS = {
  ga4: /^G-[A-Z0-9]{4,20}$/,
  gtm: /^GTM-[A-Z0-9]{4,12}$/,
  pixel: /^\d{6,20}$/,
} as const

export type AnalyticsIdKind = keyof typeof ANALYTICS_ID_PATTERNS

/** The id as the engine uses it (trimmed), or null when it is blank or not valid. */
export function analyticsId(kind: AnalyticsIdKind, raw: string | null | undefined): string | null {
  const v = (raw ?? "").trim()
  return v && ANALYTICS_ID_PATTERNS[kind].test(v) ? v : null
}
