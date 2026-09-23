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
}

/** R-35: Dashboard, CRS, Reservations, Rates & Contracts, Inventory, Booking Engine,
 * CRM, Payments, Reports, Connect, Settings. The Call Center is part of CRS. */
export const NAV: NavItem[] = [
  { id: "dashboard", to: "/tex", label: "core.nav.dashboard", icon: LayoutDashboard, anyOf: ["report.view", "reservation.view"], group: "sell" },
  { id: "crs", to: "/tex/crs", label: "core.nav.crs", icon: Search, anyOf: ["reservation.create"], group: "sell", keywords: "book search availability" },
  { id: "call-center", to: "/tex/crs/call-center", label: "core.nav.call_center", icon: Headphones, anyOf: ["reservation.create"], group: "sell", keywords: "phone agent" },
  { id: "reservations", to: "/tex/reservations", label: "core.nav.reservations", icon: BedDouble, anyOf: ["reservation.view"], group: "sell" },
  { id: "rates", to: "/tex/rates", label: "core.nav.rates", icon: Tags, anyOf: ["price.view", "contract.edit"], group: "commercial", keywords: "contracts prices markup promotions" },
  { id: "inventory", to: "/tex/inventory", label: "core.nav.inventory", icon: CalendarRange, anyOf: ["inventory.edit", "restriction.edit", "price.view"], group: "commercial", keywords: "grid availability stop sell" },
  { id: "booking-engine", to: "/tex/booking-engine", label: "core.nav.booking_engine", icon: Globe, anyOf: ["booking_site.edit"], group: "commercial", keywords: "website widget domain" },
  { id: "crm", to: "/tex/crm", label: "core.nav.crm", icon: Users, anyOf: ["crm.view"], group: "guests", keywords: "guests segments loyalty abandoned" },
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
