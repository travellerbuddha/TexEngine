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

/** What the server strips around an id (Python ``str.strip()``: its whitespace; ``String.trim`` also strips a
 * byte-order mark and keeps the separators U+001C–U+001F and U+0085). The same set: the admin form, the engine and
 * the server judge one value alike (LO-49). */
const EDGE = /^[\t\n\v\f\r\x1c-\x1f \x85\xa0\u1680\u2000-\u200a\u2028\u2029\u202f\u205f\u3000]+|[\t\n\v\f\r\x1c-\x1f \x85\xa0\u1680\u2000-\u200a\u2028\u2029\u202f\u205f\u3000]+$/g

/** The id as the engine uses it (stripped as the server strips it), or null when it is blank or not valid. */
export function analyticsId(kind: AnalyticsIdKind, raw: string | null | undefined): string | null {
  const v = (raw ?? "").replace(EDGE, "")
  return v && ANALYTICS_ID_PATTERNS[kind].test(v) ? v : null
}
