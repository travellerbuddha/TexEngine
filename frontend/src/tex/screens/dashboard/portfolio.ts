// Portfolio dashboard (R-47, ADR-038): the shapes of kamra.tex.api.reports.portfolio
// and portfolio_scopes, plus display helpers. Amounts stay the server's decimal
// strings, grouped per currency; nothing here adds money or mixes currencies.
import { useCallback, type MouseEvent } from "react"
import { nightsBetween } from "../../lib/format"
import { useSession } from "../../lib/session"
import { cmpDecimal } from "../crs/lib/party"
import { rangeProblem } from "../reports/lib"

/** Money per currency code, e.g. { EUR: "1250.00", TRY: "48000.00" }. */
export type Amounts = Record<string, string>

export type ScopeLevel = "All" | "Enterprise" | "Group" | "Hotel"

export interface PortfolioScopes {
  hotels: { name: string; label: string; group: string | null; enterprise: string | null }[]
  groups: { name: string; label: string }[]
  enterprises: { name: string; label: string }[]
}

export interface HotelFigures {
  hotel: string
  hotel_name: string
  sold: number
  sold_today: number
  booking_value: Amounts
  direct_value: Amounts
  call_centre_value: Amounts
  cancellations: number
  cancelled_value: Amounts
  pending_payment: number
  pending_payment_value: Amounts
  open_balances: number
  open_balance_value: Amounts
  abandoned: number
  abandoned_value: Amounts
  inventory_alerts: number
  restriction_alerts: number
}

export const INVENTORY_KINDS = ["oversold", "sold_out", "few_left", "closed"] as const
export const RESTRICTION_KINDS = ["stop_sell", "closed_to_arrival", "closed_to_departure"] as const
export type InventoryKind = (typeof INVENTORY_KINDS)[number]
export type RestrictionKind = (typeof RESTRICTION_KINDS)[number]

interface AlertBase {
  hotel: string
  hotel_name: string
  date: string
  room_type: string | null
  room_type_name: string | null
}

export interface InventoryAlert extends AlertBase {
  kind: InventoryKind
  /** Rooms left in the pool that day; negative when oversold. */
  free: number
  capacity: number
}

export interface RestrictionAlert extends AlertBase {
  kind: RestrictionKind
  market: string | null
  channel: string | null
  /** the Booking Engine, the Call Center or both (G-48) */
  channel_scope?: string | null
}

export type PortfolioAlert = InventoryAlert | RestrictionAlert

export interface PortfolioTotals {
  sold: number
  sold_today: number
  cancellations: number
  pending_payment: number
  open_balances: number
  abandoned: number
  booking_value: Amounts
  direct_value: Amounts
  call_centre_value: Amounts
  cancelled_value: Amounts
  pending_payment_value: Amounts
  open_balance_value: Amounts
  abandoned_value: Amounts
  today_value: Amounts
}

export interface MarketRow {
  market: string
  count: number
  value: Amounts
}

export interface RoomRow {
  room_type: string
  room_type_name: string
  hotel: string | null
  hotel_name: string | null
  count: number
  nights: number
  value: Amounts
}

export interface PortfolioData {
  scope: { level: ScopeLevel; name: string | null; hotels: number }
  from: string
  to: string
  today: string
  totals: PortfolioTotals
  hotels: HotelFigures[]
  markets: MarketRow[]
  rooms: RoomRow[]
  alerts: PortfolioAlert[]
  alerts_total: number
}

export function isInventoryAlert(a: PortfolioAlert): a is InventoryAlert {
  return (INVENTORY_KINDS as readonly string[]).includes(a.kind)
}

// ---- scope and period -------------------------------------------------------

export interface Scope {
  level: ScopeLevel
  name?: string
}

/** "All" | "Enterprise:ENT-1" | "Group:GRP-1" | "Hotel:HTL-1" (URL and <select> value). */
export function encodeScope(s: Scope): string {
  return s.level === "All" || !s.name ? "All" : `${s.level}:${s.name}`
}

export function decodeScope(raw: string | null | undefined): Scope {
  if (!raw) return { level: "All" }
  const i = raw.indexOf(":")
  const level = (i > 0 ? raw.slice(0, i) : raw) as ScopeLevel
  const name = i > 0 ? raw.slice(i + 1) : ""
  if ((level === "Enterprise" || level === "Group" || level === "Hotel") && name) return { level, name }
  return { level: "All" }
}

/** True when the picker offers this scope (a stale URL falls back to all hotels). */
export function scopeOffered(s: Scope, scopes: PortfolioScopes | undefined): boolean {
  if (s.level === "All" || !scopes) return true
  const list = s.level === "Enterprise" ? scopes.enterprises : s.level === "Group" ? scopes.groups : scopes.hotels
  return list.some((x) => x.name === s.name)
}

/** Sale-date presets: the portfolio counts bookings on the day they were sold. */
export const SALE_PRESETS = ["this_month", "last_30"] as const
/** The server refuses longer windows (kamra/tex/reports/portfolio.py). */
export const MAX_PORTFOLIO_DAYS = 400

/** i18n key of the problem with a sale window, or null when it can be asked for. */
export function saleRangeProblem(from: string, to: string): string | null {
  const p = rangeProblem(from, to)
  if (p) return p
  return nightsBetween(from, to) > MAX_PORTFOLIO_DAYS ? "reports.err.too_long" : null
}

// ---- currencies -------------------------------------------------------------

const TOTAL_AMOUNTS = [
  "booking_value",
  "direct_value",
  "call_centre_value",
  "cancelled_value",
  "pending_payment_value",
  "open_balance_value",
  "abandoned_value",
  "today_value",
] as const

/** Every currency that appears anywhere in the answer, alphabetically. */
export function currenciesOf(d: PortfolioData): string[] {
  const seen = new Set<string>()
  for (const k of TOTAL_AMOUNTS) for (const c of Object.keys(d.totals[k] ?? {})) seen.add(c)
  for (const m of d.markets) for (const c of Object.keys(m.value)) seen.add(c)
  for (const r of d.rooms) for (const c of Object.keys(r.value)) seen.add(c)
  return [...seen].filter(Boolean).sort()
}

/** The currency most hotels sold in (ties: alphabetical) — the default for rankings. */
export function mainCurrency(d: PortfolioData, currencies: string[]): string | undefined {
  let best: string | undefined
  let bestN = -1
  for (const c of currencies) {
    const n = d.hotels.filter((h) => h.booking_value[c] !== undefined).length
    if (n > bestN) {
      best = c
      bestN = n
    }
  }
  return best
}

/**
 * Position of each row when ordered by its amount in one currency, compared exactly
 * as decimals (rows without that currency count as zero). DataTable sorts by the
 * returned number; equal amounts share a position so the table keeps its order.
 */
export function rankBy<T>(rows: T[], id: (r: T) => string, amount: (r: T) => string | undefined): Map<string, number> {
  const val = (r: T) => amount(r) ?? "0"
  const ordered = [...rows].sort((a, b) => cmpDecimal(val(a), val(b)))
  const out = new Map<string, number>()
  let pos = 0
  ordered.forEach((r, i) => {
    if (i > 0 && cmpDecimal(val(ordered[i - 1]), val(r)) !== 0) pos = i
    out.set(id(r), pos)
  })
  return out
}

// ---- alerts -----------------------------------------------------------------

export interface HotelAlerts {
  hotel: string
  hotel_name: string
  inventory: number
  restrictions: number
  days: { date: string; alerts: PortfolioAlert[] }[]
}

const KIND_ORDER: string[] = [...INVENTORY_KINDS, ...RESTRICTION_KINDS]

/** Alerts grouped by hotel (by name), then by day; the most severe kind first. */
export function groupAlerts(alerts: PortfolioAlert[]): HotelAlerts[] {
  const byHotel = new Map<string, HotelAlerts>()
  for (const a of alerts) {
    let h = byHotel.get(a.hotel)
    if (!h) {
      h = { hotel: a.hotel, hotel_name: a.hotel_name || a.hotel, inventory: 0, restrictions: 0, days: [] }
      byHotel.set(a.hotel, h)
    }
    if (isInventoryAlert(a)) h.inventory++
    else h.restrictions++
    let day = h.days.find((d) => d.date === a.date)
    if (!day) {
      day = { date: a.date, alerts: [] }
      h.days.push(day)
    }
    day.alerts.push(a)
  }
  const out = [...byHotel.values()]
  for (const h of out) {
    h.days.sort((x, y) => (x.date < y.date ? -1 : x.date > y.date ? 1 : 0))
    for (const d of h.days) d.alerts.sort((x, y) => KIND_ORDER.indexOf(x.kind) - KIND_ORDER.indexOf(y.kind))
  }
  return out.sort((x, y) => x.hotel_name.localeCompare(y.hotel_name))
}

// ---- drill-down -------------------------------------------------------------

/** The single-hotel dashboard (explicit view, so a remembered portfolio view does not win). */
export const HOTEL_DASHBOARD = "/tex?view=hotel"

/**
 * onClick for a link into one hotel's screens: makes it the selected hotel before the
 * route changes (a new tab opened with Ctrl/⌘ reads the same stored choice).
 */
export function useSelectHotel() {
  const { setProperty } = useSession()
  return useCallback(
    (hotel: string) => (e: MouseEvent) => {
      setProperty(hotel)
      if (e.button === 0 && !e.metaKey && !e.ctrlKey && !e.shiftKey && !e.altKey) window.scrollTo(0, 0)
    },
    [setProperty],
  )
}
