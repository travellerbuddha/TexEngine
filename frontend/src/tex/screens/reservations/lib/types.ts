// Shapes of crs.reservations / ui_crs.reservation / crs.propose_modification /
// crs.apply_modification / crs.simulate / crs.cancellation_preview / crs.cancel /
// crs.addon_options / crs.addon_propose / crs.addon_apply.
import type {
  CancellationRule,
  ChildSpec,
  ContractRef,
  ExplanationStep,
  ExtraOutcome,
  QuoteDict,
  QuoteLine,
  Reason,
  StayRequest,
  TaxLine,
} from "../../crs/lib/types"

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
  /** Extras added after booking (G-22), each priced on its own; already in lines and totals. */
  addons?: AddonEntry[]
}

// ─── extras added after booking (G-22, ADR-034) ─────────────────────────

/** What was asked for: code, how many and the service day(s). */
export interface AddonRequest {
  code: string
  quantity: number
  service_dates?: string[]
}

/** An add-on priced on its own (pricing.addons.AddonQuote.to_dict). Money is a string. */
export interface AddonQuote {
  ok: boolean
  currency: string
  extras: ExtraOutcome[]
  lines: QuoteLine[]
  taxes: TaxLine[]
  /** extras, subtotal, tax, tax_added, total */
  totals: Record<string, string>
  reasons: Reason[]
  /** Only for price.view_cost. */
  explanation?: ExplanationStep[]
}

/** One add-on in the reservation's snapshot (pricing.addons[]). */
export interface AddonEntry {
  id: string
  /** Server wall-clock time it was added. */
  at: string
  quote: AddonQuote
  requests?: AddonRequest[]
  /** Guest, Desk, … */
  source?: string | null
}

/** One extra that can be added now (crs.addon_options). */
export interface AddonOption {
  code: string
  name: string
  category: string | null
  description: string | null
  image: string | null
  pricing_mode: string
  currency: string
  /** List price in the extra's currency (a guide; the proposal prices it). */
  amount: string
  /** null = no maximum per stay. */
  max_quantity: number | null
  /** Already on the reservation (its booking and earlier add-ons). */
  booked: number
  /** Must be ordered at least this many hours before the day it is used. */
  cutoff_hours: number
  limited: boolean
  /** Limited extras: what is left per day of the stay (check-in..check-out inclusive). */
  days: Record<string, { remaining: number; closed: boolean }> | null
}

export interface AddonOptions {
  reservation: string
  check_in: string
  check_out: string
  currency: string
  extras: AddonOption[]
}

export interface AddonProposal {
  reservation: string
  ok: boolean
  reasons: Reason[]
  addon: AddonQuote
  currency: string
  old_total: string
  new_total: string | null
  /** null when the extras cannot be added (reasons say why). */
  proposal_token: string | null
}

export interface AddonApplyResult {
  reservation: string
  addon: string
  total: string
  currency: string
  /** The same proposal was applied before: nothing was added twice. */
  replay: boolean
  booking?: string
  balance?: string
  payment_status?: string | null
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
  /** `addons`: the earlier add-ons carried over (those not dropped). */
  proposed: QuoteDict & { addons?: AddonEntry[] }
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

/** A guest's own change of a reservation and how its money was settled (crs.guest_change_requests; G-45). */
export interface GuestChangeRequest {
  name: string
  property: string
  booking: string
  reservation: string
  status: "Awaiting Payment" | "Applied" | "Requested" | "Approved" | "Rejected" | "Failed" | "Expired" | "Superseded"
  currency: string
  /** booking totals before and after the change */
  old_total: string
  new_total: string
  difference: string
  /** charged online before the change applies */
  collect_amount: string
  payment_transaction: string | null
  attempt: number | null
  settlement: "" | "None" | "Online payment" | "Pay at hotel" | "Balance" | "Refund" | "Credit on booking" | "Staff" | null
  settlement_amount: string
  refunded_amount: string
  settle_pending: boolean
  /** money of this change waits for staff: a refund TEX could not make, or one to verify at the gateway */
  staff_open: boolean
  staff_amount: string
  staff_reason: "" | "Refund by staff" | "Verify refund at gateway" | null
  /** the refund the gateway never confirmed */
  unknown_refund: string | null
  revision: string | null
  error: string | null
  note: string | null
  expires_at: string | null
  resolved_by: string | null
  resolved_at: string | null
  resolution: string | null
  creation: string
  modified: string
  /** a request to decide, or money left for staff to refund */
  needs_staff: boolean
  changes: { check_in?: string; check_out?: string; adults?: number; children?: (number | { age?: number | null })[] }
  /** Requested with a lower price: what approving it would leave paid above the new total */
  overpaid_after?: string
}
