import type { LucideIcon } from "lucide-react"
import {
  BadgePercent,
  BarChart3,
  BedDouble,
  CalendarRange,
  CreditCard,
  FileText,
  Globe,
  Headphones,
  LayoutDashboard,
  PlugZap,
  Search,
  Settings,
  Tags,
  Users,
} from "lucide-react"

/** A sub-section of an area (R-35, G-64). Every entry opens a working screen, or a real tab or
 * deep link of one; each is shown only with the capabilities that screen's endpoints require
 * (the server checks them again: hiding an entry is never the control). */
export interface NavChild {
  id: string
  /** Route, optionally with a query that opens part of the screen (e.g. `?bulk=1`). */
  to: string
  /** i18n key */
  label: string
  /** Shown when the user holds any of these capabilities at the selected hotel… */
  anyOf: string[]
  /** …and every one of these. */
  allOf?: string[]
  keywords?: string
  /** Deeper pages that belong to this entry when its route is the area's home (e.g. a
   * contract's page under Contracts). */
  match?: string[]
  /** A section the spec names that TEX does not have yet: listed plainly as not available,
   * never a link, never in the command palette. */
  unavailable?: boolean
}

export interface NavItem {
  id: string
  to: string
  /** i18n key */
  label: string
  icon: LucideIcon
  /** Shown when the user holds any of these capabilities at the selected hotel. */
  anyOf: string[]
  group: "sell" | "commercial" | "guests" | "insights" | "system"
  /** Extra entries for the command palette only. */
  keywords?: string
  children?: NavChild[]
  /** The area's own page is `to` exactly (its deeper pages are other areas' or listed in `match`). */
  end?: boolean
  /** Other paths that are this area's own pages (e.g. a contract's page under Contracts). */
  match?: string[]
}

const PRICE = ["price.view"]
// contract cost: the periods and occupancy rules of versions (G-11, contracts.get_version)
const COST = ["price.view_cost", "contract.edit"]

/** The selling rules (policy kinds) a revenue manager sets once and rarely changes, in the order
 * staff look for them; promotions are daily work and have their own entry. */
export const RULE_SLUGS = ["markup", "cancellation", "payment", "pricing-policies", "taxes", "extras", "allotments", "fx-policies"] as const
const RULE_LABELS: Record<(typeof RULE_SLUGS)[number], string> = {
  markup: "rates.nav.markup",
  cancellation: "rates.nav.cancellation",
  payment: "rates.nav.payment",
  "pricing-policies": "rates.nav.pricing",
  taxes: "rates.nav.taxes",
  extras: "rates.nav.extras",
  allotments: "rates.nav.allotments",
  "fx-policies": "rates.nav.fx",
}
/** Rules read with more than price.view: markups and contract formulas are cost (G-11; the server's
 * `policies.READ_CAP`), so neither the side navigation nor the rules' tabs offer them without it. */
const RULE_READ: Partial<Record<(typeof RULE_SLUGS)[number], string[]>> = {
  markup: ["price.view_cost"],
  "pricing-policies": ["price.view_cost"],
}

/** Whether someone with `can` may open this selling rule's list. */
export function ruleVisible(slug: (typeof RULE_SLUGS)[number], can: (cap: string) => boolean): boolean {
  return PRICE.some(can) && (RULE_READ[slug] ?? []).every(can)
}

/** R-35's areas, grouped by the work staff come to do (UX revision 2026-10): daily selling and
 * price/availability work first; contract set-up and selling rules next; guests and money;
 * reports; set-up and system last. Routes are unchanged: only the grouping and labels moved, so
 * every deep link and bookmark keeps working. The Call Center is part of CRS. */
export const NAV: NavItem[] = [
  // ── daily work ──
  { id: "dashboard", to: "/tex", label: "core.nav.dashboard", icon: LayoutDashboard, anyOf: ["report.view", "reservation.view"], group: "sell", end: true },
  { id: "reservations", to: "/tex/reservations", label: "core.nav.reservations", icon: BedDouble, anyOf: ["reservation.view"], group: "sell", keywords: "find booking guest number ota" },
  { id: "crs", to: "/tex/crs", label: "core.nav.crs", icon: Search, anyOf: ["reservation.create"], group: "sell", keywords: "crs book search availability new booking", end: true },
  { id: "call-center", to: "/tex/crs/call-center", label: "core.nav.call_center", icon: Headphones, anyOf: ["reservation.create"], group: "sell", keywords: "phone agent" },
  {
    id: "inventory",
    to: "/tex/inventory",
    label: "core.nav.inventory",
    icon: CalendarRange,
    anyOf: ["inventory.edit", "restriction.edit", "price.view"],
    group: "sell",
    keywords: "inventory grid availability stop sell close open rates prices calendar",
    children: [
      { id: "inv-calendar", to: "/tex/inventory", label: "core.nav.sub.calendar", anyOf: ["inventory.edit", "restriction.edit", "price.view"], keywords: "grid prices availability stop sell" },
      // the restrictions list needs price.view, as the grid
      { id: "rates-restrictions", to: "/tex/rates/restrictions", label: "core.nav.sub.restrictions", anyOf: PRICE, keywords: "stop sell min stay cta ctd" },
      { id: "inv-extras", to: "/tex/inventory/extras", label: "core.nav.sub.extras", anyOf: PRICE, keywords: "spa capacity limited extras" },
      // the bulk editor of the grid: the grid needs price.view, the editor an edit right (a rate
      // change also needs a contract chosen in the grid)
      { id: "rates-bulk", to: "/tex/inventory?bulk=1", label: "core.nav.sub.bulk", anyOf: ["restriction.edit", "inventory.edit"], allOf: PRICE, keywords: "grid mass update" },
    ],
  },
  { id: "promotions", to: "/tex/rates/policies/promotions", label: "core.nav.promotions", icon: BadgePercent, anyOf: PRICE, group: "sell", keywords: "promotions discounts campaigns coupons early booking offers" },
  // ── contracts and pricing set-up ──
  {
    id: "rates",
    to: "/tex/rates",
    label: "core.nav.rates",
    icon: FileText,
    anyOf: ["price.view", "contract.edit"],
    group: "commercial",
    keywords: "contracts seasons prices children occupancy",
    end: true,
    match: ["/tex/rates/contracts"],
    // R-35: Contracts, Contract Versions, Price Periods, Occupancy Rules, Rate Plans
    children: [
      { id: "rates-contracts", to: "/tex/rates", label: "core.nav.sub.contracts", anyOf: PRICE, match: ["/tex/rates/contracts"] },
      { id: "rates-versions", to: "/tex/rates/versions", label: "core.nav.sub.versions", anyOf: PRICE, keywords: "published draft superseded" },
      { id: "rates-periods", to: "/tex/rates/periods", label: "core.nav.sub.periods", anyOf: COST, allOf: PRICE, keywords: "seasons dates" },
      { id: "rates-occupancy", to: "/tex/rates/occupancy", label: "core.nav.sub.occupancy", anyOf: COST, allOf: PRICE, keywords: "child adult extra bed" },
      { id: "rates-plans", to: "/tex/rates/rate-plans", label: "core.nav.sub.rate_plans", anyOf: PRICE, keywords: "refundable non-refundable" },
    ],
  },
  {
    id: "rules",
    to: "/tex/rates/policies/markup",
    label: "core.nav.selling_rules",
    icon: Tags,
    anyOf: PRICE,
    group: "commercial",
    keywords: "policies markup cancellation payment taxes currency",
    // R-35: Markets, Currency and the selling policies
    children: [
      ...RULE_SLUGS.map((s) => ({ id: `rules-${s}`, to: `/tex/rates/policies/${s}`, label: RULE_LABELS[s], anyOf: PRICE, allOf: RULE_READ[s] })),
      { id: "rates-currency", to: "/tex/rates/fx-rates", label: "core.nav.sub.currency", anyOf: PRICE, keywords: "fx exchange rates" },
      { id: "rates-markets", to: "/tex/settings/markets", label: "core.nav.sub.markets", anyOf: PRICE, keywords: "countries" },
    ],
  },
  // ── guests and money ──
  {
    id: "crm",
    to: "/tex/crm",
    label: "core.nav.crm",
    icon: Users,
    anyOf: ["crm.view"],
    group: "guests",
    keywords: "guests segments loyalty abandoned",
    // R-35: Guests, Segments, Campaigns, Loyalty, Abandoned Bookings, Communications
    children: [
      { id: "crm-guests", to: "/tex/crm", label: "core.nav.sub.guests", anyOf: ["crm.view"], match: ["/tex/crm/guests"] },
      { id: "crm-segments", to: "/tex/crm/segments", label: "core.nav.sub.segments", anyOf: ["crm.view"] },
      { id: "crm-campaigns", to: "/tex/crm/campaigns", label: "core.nav.sub.campaigns", anyOf: ["crm.view"], unavailable: true },
      { id: "crm-loyalty", to: "/tex/crm/loyalty", label: "core.nav.sub.loyalty", anyOf: ["crm.view"], keywords: "points tiers" },
      { id: "crm-abandoned", to: "/tex/crm/abandoned", label: "core.nav.sub.abandoned", anyOf: ["crm.view"] },
      { id: "crm-communications", to: "/tex/crm/communications", label: "core.nav.sub.communications", anyOf: ["crm.view"], keywords: "emails calls notes messages" },
    ],
  },
  { id: "payments", to: "/tex/payments", label: "core.nav.payments", icon: CreditCard, anyOf: ["payment.view"], group: "guests", keywords: "links refunds transactions" },
  // ── reports ──
  { id: "reports", to: "/tex/reports", label: "core.nav.reports", icon: BarChart3, anyOf: ["report.view"], group: "insights", keywords: "production pace" },
  // ── set-up and system ──
  {
    id: "booking-engine",
    to: "/tex/booking-engine",
    label: "core.nav.booking_engine",
    icon: Globe,
    anyOf: ["booking_site.edit"],
    group: "system",
    keywords: "website widget domain",
    // R-35: Configuration, Rooms, Content, Branding, Widgets, Domains, Policies, Analytics
    // (a site's branding, widgets, domains and policies are tabs of the site)
    children: [
      { id: "be-sites", to: "/tex/booking-engine", label: "core.nav.sub.sites", anyOf: ["booking_site.edit"], allOf: PRICE, match: ["/tex/booking-engine/sites", "/tex/booking-engine/new"], keywords: "configuration branding widgets domains policies" },
      { id: "be-rooms", to: "/tex/booking-engine/rooms", label: "core.nav.sub.rooms", anyOf: ["booking_site.edit"], keywords: "room types photos" },
      { id: "be-content", to: "/tex/booking-engine/content", label: "core.nav.sub.content", anyOf: ["booking_site.edit"], keywords: "translations languages" },
      { id: "be-analytics", to: "/tex/booking-engine/analytics", label: "core.nav.sub.analytics", anyOf: ["report.view"], allOf: ["booking_site.edit"], keywords: "funnel conversion" },
    ],
  },
  { id: "connect", to: "/tex/connect", label: "core.nav.connect", icon: PlugZap, anyOf: ["connect.admin", "channel.view"], group: "system", keywords: "integrations pms channel manager distribution ari ota" },
  { id: "settings", to: "/tex/settings", label: "core.nav.settings", icon: Settings, anyOf: ["settings.admin", "user.admin", "system.monitor"], group: "system", keywords: "users access audit system status monitoring" },
]

/** Group headings, in the sidebar's order (labels: daily work, contracts and pricing, guests and
 * money, reports, set-up and system). */
export const NAV_GROUPS: { id: NavItem["group"]; label: string }[] = [
  { id: "sell", label: "core.navgroup.sell" },
  { id: "commercial", label: "core.navgroup.commercial" },
  { id: "guests", label: "core.navgroup.guests" },
  { id: "insights", label: "core.navgroup.insights" },
  { id: "system", label: "core.navgroup.system" },
]

/** Whether a sub-section is shown to someone with `can`. */
export function childVisible(c: NavChild, can: (cap: string) => boolean): boolean {
  return c.anyOf.some(can) && (c.allOf ?? []).every(can)
}

/** Where an area's own link goes for someone shown `sub`: the area's page, or, when that page is a
 * sub-section they may not open, their first one (a call-centre agent's Selling rules open on the
 * cancellation rules, not on the markups they may not read). */
export function areaEntry(n: NavItem, sub: NavChild[]): string {
  const own = (n.children ?? []).find((c) => c.to === n.to)
  if (!own || sub.includes(own)) return n.to
  return sub.find((c) => !c.unavailable)?.to ?? n.to
}

/** The path part of a sub-section's route (a query only opens part of that screen). */
export function childPath(c: NavChild): string {
  return c.to.split("?", 1)[0]
}

const under = (pathname: string, path: string) => pathname === path || pathname.startsWith(`${path}/`)

/** Whether `pathname` is this sub-section's page. An entry that opens part of a screen (a
 * query) is never shown as the current page. */
export function childActive(c: NavChild, parent: NavItem, pathname: string): boolean {
  if (c.unavailable || c.to.includes("?")) return false
  const path = childPath(c)
  if (pathname === path) return true
  if (path === parent.to) return (c.match ?? []).some((m) => under(pathname, m))
  return under(pathname, path)
}

/** Whether `pathname` is one of the area's own pages: its route (exactly, for an `end` area) or a
 * path it `match`es. Drives the area link's current state. */
export function areaHome(n: NavItem, pathname: string): boolean {
  const path = pathname.length > 1 ? pathname.replace(/\/+$/, "") : pathname
  if (n.end ? path === n.to : under(path, n.to)) return true
  return (n.match ?? []).some((m) => under(path, m))
}

/** Whether `pathname` belongs to this area: its own pages, or one of its sub-sections that
 * lives elsewhere (Fiyat ve müsaitlik › Kısıtlama listesi is a Rates page). */
export function inArea(n: NavItem, children: NavChild[], pathname: string): boolean {
  if (n.to === "/tex" || !children.length) return false
  return areaHome(n, pathname) || children.some((c) => childActive(c, n, pathname))
}
