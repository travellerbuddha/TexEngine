// The version editor's four sections and their hashes (PRICING_WORKSPACE_UX.md §2, slice S8):
// Pricing · Commercial rules (with the Advanced rule tables) · Offers & promotions · Preview &
// audit. Old tab hashes stay links: they open the section that now holds their content. Also the
// section (and the Advanced rule table) each validation issue belongs to, for the badges.
// Pure: no runtime imports.
import type { IssueRef } from "../lib/types.ts"

export const SECTIONS = ["pricing", "rules", "offers", "preview"] as const
export type SectionId = (typeof SECTIONS)[number]

/** The inner "Rule tables" of Commercial rules, in tab order: the editors of the ten-tab editor. */
export const RULE_TABLES = ["plans", "settings", "rooms", "periods", "rates", "ages", "occupancy", "boards"] as const
export type RuleTableId = (typeof RULE_TABLES)[number]
export const DEFAULT_RULE_TABLE: RuleTableId = "plans"

/** A part of Pricing an old hash asks for: the child ages drawer, the occupancy and the boards
 * regions (S11, S13): the hash opens that region and scrolls to it. */
export type PricingRegion = "ages" | "occupancy" | "boards"
const REGIONS: readonly string[] = ["ages", "occupancy", "boards"]

export interface EditorPlace {
  section: SectionId
  /** the inner Rule tables tab (Commercial rules only; always set there) */
  table?: RuleTableId
  /** the Pricing region an old link asked for */
  region?: PricingRegion
}

const isSection = (s: string): s is SectionId => (SECTIONS as readonly string[]).includes(s)
const isTable = (s: string): s is RuleTableId => (RULE_TABLES as readonly string[]).includes(s)

/**
 * The place a location hash names, or null when it names none (the editor keeps its default,
 * Pricing). New hashes: `#pricing`, `#rules`, `#rules/<table>`, `#offers`, `#preview`. Aliases
 * (§2): `#rooms`, `#periods`, `#rates` → Pricing; `#ages`, `#occupancy`, `#boards` → Pricing with
 * that region; `#plans`, `#settings` → Commercial rules with that inner tab.
 */
export function parseEditorHash(hash: string): EditorPlace | null {
  const h = hash.startsWith("#") ? hash.slice(1) : hash
  if (!h) return null
  const slash = h.indexOf("/")
  if (slash >= 0) {
    if (h.slice(0, slash) !== "rules") return null
    const rest = h.slice(slash + 1)
    if (rest.includes("/")) return null
    return { section: "rules", table: isTable(rest) ? rest : DEFAULT_RULE_TABLE }
  }
  if (h === "rules") return { section: "rules", table: DEFAULT_RULE_TABLE }
  if (isSection(h)) return { section: h }
  if (h === "rooms" || h === "periods" || h === "rates") return { section: "pricing" }
  if (REGIONS.includes(h)) return { section: "pricing", region: h as PricingRegion }
  if (h === "plans" || h === "settings") return { section: "rules", table: h }
  return null
}

/** The canonical hash (without "#") of a place; parseEditorHash reads it back to the same place. */
export function editorHash(place: EditorPlace): string {
  if (place.section === "rules") return `rules/${place.table ?? DEFAULT_RULE_TABLE}`
  if (place.section === "pricing" && place.region) return place.region
  return place.section
}

const PRICING_CODES: readonly string[] = ["NO_PERIODS", "NO_ROOMS", "INCLUDED_ADULTS", "NO_BASE_BOARD", "NO_AGE_BANDS"]

/** The publish sweep reports a party it cannot price under the engine's own code (e.g.
 * NO_CHILD_RULE, AMBIGUOUS_OCCUPANCY_RULES); its ref names the party (GAP-4). */
const namesParty = (ref: IssueRef | undefined) => ref?.adults !== undefined

/**
 * The section a validation issue belongs to (§2): Pricing for rooms, periods, room prices, child
 * ages, occupancy and boards (ROOM_*, PERIOD_*, NO_PERIODS, NO_ROOMS, INCLUDED_ADULTS, AGE_BANDS*,
 * NO_AGE_BANDS, OCC_*, NO_BASE_BOARD, BOARD_*, and a party of the publish sweep); Offers for
 * OFFER_*; Commercial rules for the rest (RATE_PLAN_*, SALE_WINDOW, STAY_WINDOW, CURRENCY,
 * BUILD, and any code not known here).
 */
export function issueSection(code: string, ref?: IssueRef): SectionId {
  if (code.startsWith("OFFER_")) return "offers"
  if (
    code.startsWith("ROOM_") ||
    code.startsWith("PERIOD_") ||
    code.startsWith("OCC_") ||
    code.startsWith("BOARD_") ||
    code.startsWith("AGE_BANDS") ||
    PRICING_CODES.includes(code) ||
    namesParty(ref)
  )
    return "pricing"
  return "rules"
}

/** The Advanced rule table (or Offers) whose editor lists an issue, as the ten-tab editor did;
 * BOARD_* and NO_AGE_BANDS now go to their own table, a sweep party to Occupancy. */
export function issueTable(code: string, ref?: IssueRef): RuleTableId | "offers" {
  if (code.startsWith("OCC_")) return "occupancy"
  if (code.startsWith("OFFER_")) return "offers"
  if (code.startsWith("PERIOD_") || code === "NO_PERIODS") return "periods"
  if (code.startsWith("ROOM_RULE") || code === "ROOM_NEGATIVE") return "rates"
  if (code === "ROOM_CAPACITY" || code === "INCLUDED_ADULTS" || code === "NO_ROOMS") return "rooms"
  if (code.startsWith("AGE_BANDS") || code === "NO_AGE_BANDS") return "ages" // AGE_BANDS, AGE_BANDS_MIN_AGE (G-52)
  if (code === "NO_BASE_BOARD" || code.startsWith("BOARD_")) return "boards"
  if (code === "RATE_PLAN_BOARD" || code === "RATE_PLAN_REFUNDABLE") return "plans"
  if (namesParty(ref)) return "occupancy"
  return "settings"
}
