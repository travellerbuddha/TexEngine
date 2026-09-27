// The analytics ids a booking site loads (G-62): one rule (booking/lib/analyticsIds.ts) for the booking
// engine (trackers), the admin form (validateSite) and the server (TEXBookingSite.validate, same
// patterns, test_security_hygiene G-62). A value is trimmed, then must match. Run with `npm run test:unit`.
import { test } from "node:test"
import assert from "node:assert/strict"
import { trackers } from "../../src/booking/lib/analytics.ts"
import type { Site as BookingSite } from "../../src/booking/types.ts"
import { newSite, validateSite, type Site } from "../../src/tex/screens/booking-engine/site.ts"

type Kind = "ga4" | "gtm" | "pixel"
const FIELD = { ga4: "ga4_measurement_id", gtm: "gtm_container_id", pixel: "meta_pixel_id" } as const
const ERROR = { ga4: "be.err.ga4", gtm: "be.err.gtm", pixel: "be.err.pixel" } as const

// the server's matrix, plus the edges of each pattern
const BAD: [Kind, string][] = [
  ["gtm", "GTM-ABC'><script>"],
  ["ga4", "G-abc"],
  ["ga4", "UA-1234"],
  ["gtm", "GTM-ABCDEFGHIJKLM"], // 13 characters after GTM-
  ["pixel", "12345"],
  ["ga4", "G-" + "A".repeat(21)],
  ["gtm", "GTM-ABC"],
  ["pixel", "1".repeat(21)],
  ["pixel", "12345678a"],
]
const GOOD: [Kind, string, string][] = [
  ["ga4", "G-ABCD1234EF", "G-ABCD1234EF"],
  ["ga4", "  G-ABCD1234EF ", "G-ABCD1234EF"],
  ["ga4", "G-" + "A".repeat(20), "G-" + "A".repeat(20)], // the admin form stopped at 12
  ["gtm", "GTM-5XK2ABC", "GTM-5XK2ABC"],
  ["gtm", "GTM-" + "B".repeat(12), "GTM-" + "B".repeat(12)], // the admin form stopped at 10
  ["pixel", "123456", "123456"],
  ["pixel", " 123456789012345 ", "123456789012345"],
]

const bookingSite = (kind: Kind, value: string) =>
  ({ analytics: { ga4: kind === "ga4" ? value : null, gtm: kind === "gtm" ? value : null, meta_pixel: kind === "pixel" ? value : null, consent_banner: false } }) as unknown as BookingSite

const adminSite = (over: Partial<Site> = {}): Site => ({ ...newSite("Hotel"), site_name: "Hotel", site_slug: "hotel", ...over })

test("the booking engine loads only a valid id, trimmed", () => {
  for (const [kind, value] of BAD) assert.equal(trackers(bookingSite(kind, value))[kind], null, `${kind} ${value}`)
  for (const [kind, value, used] of GOOD) assert.equal(trackers(bookingSite(kind, value))[kind], used, `${kind} ${value}`)
})

test("the admin form refuses exactly what the engine ignores", () => {
  assert.deepEqual(validateSite(adminSite()), {})
  for (const [kind, value] of BAD) assert.equal(validateSite(adminSite({ [FIELD[kind]]: value }))[FIELD[kind]], ERROR[kind], `${kind} ${value}`)
  for (const [kind, value] of GOOD) assert.equal(validateSite(adminSite({ [FIELD[kind]]: value }))[FIELD[kind]], undefined, `${kind} ${value}`)
})

test("an unchanged older id keeps the site savable, as on the server", () => {
  const saved = adminSite({ gtm_container_id: "GTM-old'bad" })
  assert.equal(validateSite(adminSite({ gtm_container_id: "GTM-old'bad" }), saved).gtm_container_id, undefined)
  assert.equal(validateSite(adminSite({ gtm_container_id: "GTM-new'bad" }), saved).gtm_container_id, "be.err.gtm")
})
