// Shapes of crs.reservations / ui_crs.reservation / crs.propose_modification /
// crs.apply_modification / crs.simulate / crs.cancellation_preview / crs.cancel.
import type { CancellationRule, ChildSpec, ContractRef, QuoteDict, QuoteLine, Reason, StayRequest } from "../../crs/lib/types"

export interface ReservationRow {
  name: string
  property: string
  status: string
  guest: string | null
  guest_name: string | null
  room_type: string
  room_type_name: string | null
  room: string | null
  check_in_date: string
  check_out_date: string
  nights: number
  adults: number
  children: number
  tex_booking: string | null
  tex_market: string | null
  tex_sales_channel: string | null
  tex_board: string | null
  tex_currency: string | null
  tex_guest_change_pending: number
  tex_revision_no: number | null
  creation: string
  total: string
}

export interface Revision {
  name: string
  revision_no: number
  change_type: string
  actor: string
  creation: string
  old_amount: string | null
  new_amount: string | null
  difference: string | null
  currency: string | null
  pricing_basis: string | null
  reason: string | null
  approval_status: string | null
  source: string | null
  override_amount: string | null
  changes: Record<string, unknown>
}

export type Snapshot = QuoteDict & {
  accepted_at?: string
  quote_id?: string
  basis?: string
  override_amount?: string | null
}

export interface ReservationDetail {
  name: string
  status: string
  property: string
  booking: string | null
  room_type: string
  room_type_name: string | null
  room: string | null
  check_in: string
  check_out: string
  nights: number
  adults: number
  children: number
  child_ages: ChildSpec[]
  board: string | null
  rate_plan: string | null
  market: string | null
  channel: string | null
  currency: string
  total: string
  cancellation_fee: string | null
  price_locked: boolean
  pricing_source: string | null
  contract: string | null
  contract_version: string | null
  sale_at: string | null
  revision_no: number | null
  guest_change_pending: boolean
  guest_change_note: string | null
  special_requests: string | null
  guest: {
    name: string
    full_name: string
    email: string | null
    phone: string | null
    tex_language: string | null
    tex_country: string | null
    vip: number
    tex_tags: string | null
  } | null
  pricing: Snapshot
  revisions: Revision[]
  capabilities: string[]
  /** ui_crs: guest-facing nightly prices of the locked snapshot. */
  nightly?: { date: string; amount: string }[]
}

export interface Proposal {
  reservation: string
  basis: string
  basis_detail: string
  pricing_sale_at: string
  old: {
    total: string
    currency: string
    request: StayRequest
    contract: ContractRef | null
    lines: QuoteLine[] | null
    totals: Record<string, string> | null
  }
  proposed: QuoteDict
  sellable: boolean
  difference: string | null
  currency_changed: boolean
  warnings: Reason[]
  proposal_token: string
}

export interface ApplyResult {
  reservation: string
  revision: string
  old_total: string
  new_total: string
  difference: string
  currency: string
}

export interface Simulation {
  reservation?: string
  simulated_sale_at?: string
  contract_version?: string
  actual?: { total: string; currency: string; sale_at: string; version: string }
  simulated?: QuoteDict
  difference?: string | null
  sellable?: false
  reasons?: Reason[]
}

export interface CancelPreview {
  penalty: string
  currency: string
  basis: { rule: string | CancellationRule; days_before: number }
}

export interface CancelResult {
  reservation: string
  penalty: string
  currency: string
}

export interface ContractVersionInfo {
  name: string
  rooms: { room_type: string }[]
  boards: { board: string }[]
  rate_plans: { rate_plan: string; refundable: number }[]
  room_types: { name: string; room_type_name: string; adults_capacity: number; children_capacity: number }[]
  rate_plan_options: { name: string; rate_plan_name: string; code: string; tex_refundable: number }[]
}
