// Shapes of kamra/tex/api/lists.py (G-64).

export type VersionState = "live" | "scheduled" | "published" | "draft" | "superseded" | "withdrawn"

export interface VersionListRow {
  name: string
  contract: string
  contract_code: string
  contract_name: string
  market: string
  property: string
  contract_status: string
  version_no: number
  status: string
  state: VersionState
  effective_from: string | null
  active_to: string | null
  published_at: string | null
  published_by: string | null
  change_note: string | null
  based_on: string | null
  modified: string | null
}

export interface ListOf<T> {
  rows: T[]
  truncated: boolean
}

/** A row of a version's table with its contract and version. */
export interface VersionRowBase {
  version: string
  version_no: number
  version_status: string
  state: VersionState
  contract: string
  contract_code: string
  contract_name: string
  market: string
  property: string
  idx: number
}

export interface PeriodRow extends VersionRowBase {
  period_code: string
  period_name: string | null
  start_date: string | null
  end_date: string | null
  weekdays: string | null
  adjustment_op: string | null
  adjustment_value: string | null
  priority: number | null
}

export interface OccupancyRow extends VersionRowBase {
  target: string
  position: number | null
  age_band: string | null
  combination: string | null
  room_type: string | null
  room_type_name: string | null
  period_code: string | null
  op: string
  value: string | null
  is_override: number
  note: string | null
}

export interface RatePlanRow extends VersionRowBase {
  rate_plan: string
  rate_plan_name: string
  rate_plan_code: string | null
  /** Only where the user sees cost (G-11). */
  op?: string | null
  value?: string | null
  refundable: number
  boards: string | null
  cancellation_policy: string | null
  cancellation_policy_name: string | null
  payment_policy: string | null
  payment_policy_name: string | null
}

export interface RestrictionRange {
  property: string
  room_type: string | null
  room_type_name: string | null
  contract: string | null
  contract_code: string | null
  market: string | null
  rate_plan: string | null
  rate_plan_name: string | null
  sales_channel: string | null
  channel_scope?: string | null
  stop_sell: "STOP" | "OPEN" | null
  stop_sell_mode: string | null
  min_los: number | null
  max_los: number | null
  cta: "Yes" | "No" | null
  ctd: "Yes" | "No" | null
  release_days: number | null
  min_advance: number | null
  max_advance: number | null
  book_from?: string | null
  book_to?: string | null
  note: string | null
  date_from: string
  date_to: string
  days: number
}

export interface RestrictionList {
  from: string
  to: string
  rows: RestrictionRange[]
  optional_fields: string[]
  truncated: boolean
}
