// Shapes of kamra/tex/commercial/grid.py (grid / bulk_update).

export interface OwnRestriction {
  stop_sell: "STOP" | "OPEN" | null
  stop_sell_mode: string | null
  min_los: number | null
  max_los: number | null
  cta: boolean | null
  ctd: boolean | null
  release_days: number | null
  min_advance: number | null
  max_advance: number | null
  /** Booking window: the sale dates on which the night is sold (G-48). */
  book_from: string | null
  book_to: string | null
}

export interface GridCell {
  date: string
  /** null on the hotel-level row (restrictions only). */
  available: number | null
  capacity: number | null
  sold: number | null
  closed: boolean
  manual_adjustment: number
  stop_sell: boolean
  min_los: number | null
  max_los: number | null
  cta: boolean
  ctd: boolean
  release_days: number | null
  min_advance: number | null
  max_advance: number | null
  book_from: string | null
  book_to: string | null
  own: OwnRestriction | null
  promo: boolean
  rate?: string | null
  draft_rate?: string | null
}

export interface GridRow {
  /** null: the hotel-level row — cells without a room type (hotel- or market-wide). */
  room_type: string | null
  name: string
  level: "hotel" | "room"
  cells: GridCell[]
}

export interface Grid {
  property: string
  start: string
  days: number
  dates: string[]
  contract: string | null
  channel_scope: string | null
  version: string | null
  draft: string | null
  basis: "PERSON" | "ROOM" | null
  currency: string | null
  /** decimals of the currency (a typed "1.500" is read by it) */
  minor_units?: number
  /** the viewer may not see cost: no rate is sent */
  rates_hidden?: boolean
  rows: GridRow[]
}

export interface BulkResult {
  dates: number
  rooms: number
  restriction_cells?: number
  restrictions?: Record<string, string | number>
  inventory?: Record<string, number>
  rate?: { draft: string; periods: string[]; note: string }
}

export type Metric = "rate" | "sell" | "avail" | "stop" | "los" | "arrdep" | "release" | "window"
export const METRICS: Metric[] = ["rate", "sell", "avail", "stop", "los", "arrdep", "release", "window"]
/** What the hotel-level row shows: restrictions only (no pool, no rate). */
export const HOTEL_METRICS: Metric[] = ["stop", "los", "arrdep", "release", "window"]

/** Channel scopes of a restriction (G-48): a product surface instead of one sales channel. */
export const CHANNEL_SCOPES = ["Booking Engine + Call Center", "Booking Engine", "Call Center"] as const
export const SCOPE_PREFIX = "scope:"

export interface Scope {
  contract: string
  market: string
  /** a sales channel, or `scope:<channel scope>` */
  channel: string
  rate_plan: string
}

/** The API's channel / channel_scope for a grid scope. */
export function channelArgs(scope: Scope): { channel: string | null; channel_scope: string | null } {
  if (scope.channel.startsWith(SCOPE_PREFIX)) return { channel: null, channel_scope: scope.channel.slice(SCOPE_PREFIX.length) }
  return { channel: scope.channel || null, channel_scope: null }
}

// Shapes of kamra/tex/availability/extras.py (limited extras, G-19).

export interface ExtraGridCell {
  date: string
  capacity: number
  /** Capacity set for this day (null = the extra's default daily capacity). */
  override: number | null
  closed: boolean
  sold: number
  held: number
  confirmed: number
  remaining: number
  /** More units sold than the capacity (e.g. after lowering it). */
  over: boolean
  note: string | null
}

export interface ExtraGridRow {
  code: string
  name: string
  pricing_mode: string
  daily_capacity: number
  cells: ExtraGridCell[]
}

export interface ExtrasGrid {
  property: string
  start: string
  days: number
  dates: string[]
  extras: ExtraGridRow[]
}

export interface ExtrasBulkResult {
  updated: number
  over_capacity: { extra_code: string; date: string; sold: number; capacity: number }[]
}

export interface ExtraAllocation {
  booking: string | null
  reservation: string | null
  units: number
  status: "Held" | "Confirmed" | string
  booker_name: string | null
}

export interface ExtrasDrift {
  drift: { extra_code: string; date: string; was: number; now: number }[]
}

/** What a guest pays for one night beside the contract price (UX revision 2026-10,
 * crs.ari_sell_prices): a reference stay priced by the engine with the markups and promotions in force. */
export interface SellCell {
  room_type: string
  date: string
  /** the decimal string the guest pays, or null when the night is not sold at this reference */
  total: string | null
  reason?: string | null
  message?: string | null
  promotions?: string[]
}

export interface SellPrices {
  contract: string
  on_sale: boolean
  start: string
  days: number
  adults: number
  version?: string
  currency?: string
  market?: string
  channel?: string
  board?: string | null
  rate_plan?: string | null
  rate_plans?: { code: string; name: string }[]
  cells: SellCell[]
}
