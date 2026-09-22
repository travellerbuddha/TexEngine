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
}

export interface GridCell {
  date: string
  available: number
  capacity: number
  sold: number
  closed: boolean
  manual_adjustment: number
  stop_sell: boolean
  min_los: number | null
  max_los: number | null
  cta: boolean
  ctd: boolean
  release_days: number | null
  own: OwnRestriction | null
  promo: boolean
  rate?: string | null
  draft_rate?: string | null
}

export interface GridRow {
  room_type: string
  name: string
  cells: GridCell[]
}

export interface Grid {
  property: string
  start: string
  days: number
  dates: string[]
  contract: string | null
  version: string | null
  draft: string | null
  basis: "PERSON" | "ROOM" | null
  currency: string | null
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

export type Metric = "rate" | "avail" | "stop" | "los" | "arrdep" | "release"
export const METRICS: Metric[] = ["rate", "avail", "stop", "los", "arrdep", "release"]

export interface Scope {
  contract: string
  market: string
  channel: string
  rate_plan: string
}
