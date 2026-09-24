import type { LucideIcon } from "lucide-react"
import {
  BarChart3,
  BedDouble,
  CalendarRange,
  CreditCard,
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
}

const PRICE = ["price.view"]
// contract cost: the periods and occupancy rules of versions (G-11, contracts.get_version)
const COST = ["price.view_cost", "contract.edit"]

/** R-35: Dashboard, CRS, Reservations, Rates & Contracts, Inventory, Booking Engine,
 * CRM, Payments, Reports, Connect, Settings. The Call Center is part of CRS. */
export const NAV: NavItem[] = [
  { id: "dashboard", to: "/tex", label: "core.nav.dashboard", icon: LayoutDashboard, anyOf: ["report.view", "reservation.view"], group: "sell" },
  { id: "crs", to: "/tex/crs", label: "core.nav.crs", icon: Search, anyOf: ["reservation.create"], group: "sell", keywords: "book search availability" },
  { id: "call-center", to: "/tex/crs/call-center", label: "core.nav.call_center", icon: Headphones, anyOf: ["reservation.create"], group: "sell", keywords: "phone agent" },
  { id: "reservations", to: "/tex/reservations", label: "core.nav.reservations", icon: BedDouble, anyOf: ["reservation.view"], group: "sell" },
  {
    id: "rates",
    to: "/tex/rates",
    label: "core.nav.rates",
    icon: Tags,
    anyOf: ["price.view", "contract.edit"],
    group: "commercial",
    keywords: "contracts prices markup promotions",
    // R-35: Contracts, Contract Versions, Price Periods, Occupancy Rules, Rate Plans, Markets,
    // Promotions, Restrictions, Currency, Bulk Editor
    children: [
      { id: "rates-contracts", to: "/tex/rates", label: "core.nav.sub.contracts", anyOf: PRICE, match: ["/tex/rates/contracts"] },
      { id: "rates-versions", to: "/tex/rates/versions", label: "core.nav.sub.versions", anyOf: PRICE, keywords: "published draft superseded" },
      { id: "rates-periods", to: "/tex/rates/periods", label: "core.nav.sub.periods", anyOf: COST, allOf: PRICE, keywords: "seasons dates" },
      { id: "rates-occupancy", to: "/tex/rates/occupancy", label: "core.nav.sub.occupancy", anyOf: COST, allOf: PRICE, keywords: "child adult extra bed" },
      { id: "rates-plans", to: "/tex/rates/rate-plans", label: "core.nav.sub.rate_plans", anyOf: PRICE, keywords: "refundable non-refundable" },
      { id: "rates-markets", to: "/tex/settings/markets", label: "core.nav.sub.markets", anyOf: PRICE, keywords: "countries" },
      { id: "rates-promotions", to: "/tex/rates/policies/promotions", label: "core.nav.sub.promotions", anyOf: PRICE, keywords: "coupons discounts" },
      { id: "rates-restrictions", to: "/tex/rates/restrictions", label: "core.nav.sub.restrictions", anyOf: PRICE, keywords: "stop sell min stay cta ctd" },
      { id: "rates-currency", to: "/tex/rates/fx-rates", label: "core.nav.sub.currency", anyOf: PRICE, keywords: "fx exchange rates" },
      // the bulk editor of the rates & availability grid: the grid needs price.view, the editor
      // an edit right (a rate change also needs a contract chosen in the grid)
      { id: "rates-bulk", to: "/tex/inventory?bulk=1", label: "core.nav.sub.bulk", anyOf: ["restriction.edit", "inventory.edit"], allOf: PRICE, keywords: "grid mass update" },
    ],
  },
  { id: "inventory", to: "/tex/inventory", label: "core.nav.inventory", icon: CalendarRange, anyOf: ["inventory.edit", "restriction.edit", "price.view"], group: "commercial", keywords: "grid availability stop sell" },
  {
    id: "booking-engine",
    to: "/tex/booking-engine",
    label: "core.nav.booking_engine",
    icon: Globe,
    anyOf: ["booking_site.edit"],
    group: "commercial",
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
  { id: "reports", to: "/tex/reports", label: "core.nav.reports", icon: BarChart3, anyOf: ["report.view"], group: "insights", keywords: "production pace" },
  { id: "connect", to: "/tex/connect", label: "core.nav.connect", icon: PlugZap, anyOf: ["connect.admin", "channel.view"], group: "system", keywords: "integrations pms channel manager distribution ari ota" },
  { id: "settings", to: "/tex/settings", label: "core.nav.settings", icon: Settings, anyOf: ["settings.admin", "user.admin", "system.monitor"], group: "system", keywords: "users access audit system status monitoring" },
]

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

/** Whether `pathname` belongs to this area: its own pages, or one of its sub-sections that
 * lives elsewhere (Rates & Contracts › Markets is a Settings page). */
export function inArea(n: NavItem, children: NavChild[], pathname: string): boolean {
  if (n.to === "/tex" || !children.length) return false
  return under(pathname, n.to) || children.some((c) => childActive(c, n, pathname))
}
