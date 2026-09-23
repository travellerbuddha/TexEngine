// Shapes returned by kamra/tex/api/crs.py, ui_crs.py and the quoting / booking /
// modification services. Every amount is a decimal string owned by the server.

export interface ChildSpec {
  age: number | null
  dob?: string | null
  age_months?: number | null
}

export interface StayRequest {
  property: string
  room_type: string
  board: string
  rate_plan: string | null
  check_in: string
  check_out: string
  adults: number
  children: ChildSpec[]
  sale_at: string
  market: string
  channel: string
  sell_currency: string
  promo_codes: string[]
  member: boolean
  extras: { code: string; quantity: number; service_dates?: string[] }[]
}

export interface QuoteLine {
  kind: "ACCOMMODATION" | "DISCOUNT" | "EXTRA" | "COUPON" | "TAX" | string
  code: string
  description: string
  amount: string
  quantity: string
  category: string
  included: boolean
  ref: string | null
}

export interface TaxLine {
  code: string
  name: string
  category: string
  base: string
  rate: string | null
  amount: string
  included: boolean
}

export interface PromoOutcome {
  promo_id: string
  name: string
  kind: string
  applied: boolean
  reason: string
  discount: string
  nights: string[]
  value_added: string
  source: string
  code: string | null
}

export interface ExtraOutcome {
  code: string
  name: string
  ok: boolean
  reason: string
  quantity: string
  amount: string
  currency: string
  mandatory: boolean
  pricing_mode: string
  detail: string
}

export interface CancellationRule {
  days_before_arrival: number
  penalty_type: "PERCENT" | "NIGHTS" | "FIXED" | string
  penalty_value: string
}

export interface RatePlanInfo {
  code: string
  name: string
  refundable: boolean
  cancellation_policy?: {
    id?: string
    name?: string
    description?: string
    refundable?: boolean
    rules?: CancellationRule[]
    no_show?: { type: string; value: string }
  } | null
  payment_policy?: {
    id?: string
    name?: string
    description?: string
    deposit_type?: string
    deposit_value?: string
    allow_pay_at_hotel?: boolean
    balance_due_days?: number
  } | null
  inclusions: string[]
}

export interface ContractRef {
  contract: string
  code: string
  name: string
  version: string
  version_no: number
  payload_hash: string
  market: string
  currency: string
  basis: string
}

export interface ExplanationStep {
  stage: string
  text: string
  code: string
  night: string | null
  rule: { kind: string; rule_id: string; level: string | null; source: string; label: string } | null
  overridden: { kind: string; rule_id: string; level: string | null; source: string; label: string }[]
}

/** Guest-facing night (quote) or internal night (cost viewers). */
export interface NightLine {
  date: string
  amount?: string
  final?: string
}

export interface Reason {
  code: string
  message: string
}

export interface QuoteDict {
  engine_version?: string
  sellable: boolean
  reasons: Reason[]
  currency: string
  request: StayRequest
  contract: ContractRef
  rate_plan: RatePlanInfo | null
  lines: QuoteLine[]
  promotions: PromoOutcome[]
  extras: ExtraOutcome[]
  taxes: TaxLine[]
  totals: Record<string, string>
  nights?: NightLine[]
  explanation?: ExplanationStep[]
  fx?: { from: string; to: string; mode: string; sell_rate: string } | null
}

// ─── search ────────────────────────────────────────────────────────────

export interface OfferRoom {
  room_index: number
  offer_key: string
  quote: QuoteDict
  per_night?: string | null
}

export interface DayAvailability {
  day: string
  capacity: number
  sold: number
  available: number
  allotment_remaining: number | null
  reason: string
}

export interface Offer {
  room_type: string
  board: string
  rate_plan: string | null
  contract: string
  contract_code: string
  market: string
  version: string
  currency: string
  available: number
  availability: DayAvailability[] | null
  restrictions: Reason[]
  /** Only the rooms of the party this room type fits (R-29: each room priced on its own). */
  rooms: OfferRoom[]
  room_indexes: number[]
  /** The room type takes every room of the party. */
  complete: boolean
  /** Why it does not fit the other rooms. */
  room_reasons?: (Reason & { room_index: number })[]
  /** Grand total, only when `complete`. */
  total?: string
  per_night?: string | null
  refundable?: boolean
  rate_plan_info?: RatePlanInfo | null
  /** At least one room fits, no restriction, `available > 0`. */
  bookable: boolean
  reasons?: (Reason & { room_index?: number })[]
}

export interface RoomContent {
  name: string
  description: string | null
  bed_type: string | null
  beds: string | null
  size_sqm: number | null
  view: string | null
  amenities: string[]
  image: string | null
  max_adults: number | null
  max_children: number | null
}

export interface PropertyResult {
  property: string
  property_name: string
  city: string | null
  star_category: string | number | null
  offers: Offer[]
  unavailable: Offer[]
  messages: string[]
  rooms: Record<string, RoomContent>
  /** Cheapest placement of every room (room types may differ). */
  from_total?: string | null
  from_currency?: string | null
  /** Rooms of the party no available room type fits. */
  unplaced_rooms?: number[]
}

export interface SearchResult {
  check_in: string
  check_out: string
  nights: number
  market: string
  channel: string
  rooms: { adults: number; children: ChildSpec[] }[]
  properties: PropertyResult[]
}

// ─── quote / book ──────────────────────────────────────────────────────

export interface QuoteResult {
  ok: boolean
  reasons?: Reason[]
  quote_id?: string
  expires_at?: string
  price_changed?: boolean
  previous_total?: string
  quote?: QuoteDict
  room_index?: number
}

export interface QuoteSummaryRoom {
  quote_id: string
  room_type: string
  total: string
  due_now: string | null
  deposit_type: string
  payment_policy: string | null
  pay_at_hotel_allowed: boolean
  expires_at: string
  problem: string | null
}

export interface QuoteSummary {
  property: string
  currency: string
  market?: string
  channel?: string
  payment_method: string | null
  total: string
  due_now: string | null
  balance_after: string | null
  payment_required: boolean
  pay_at_hotel_allowed: boolean
  usable: boolean
  expires_at: string
  rooms: QuoteSummaryRoom[]
}

export interface PaymentMethod {
  method: string
  provider_account: string | null
  provider: string | null
  label: string
  sandbox: boolean
}

export interface ExtraDef {
  extra_code: string
  extra_name: string
  category: string
  pricing_mode: string
  currency: string
  amount: number | string
  is_mandatory: number
  description: string | null
  max_quantity: number
}

export interface BookingRoom {
  reservation: string
  room_type: string
  check_in: string
  check_out: string
  adults: number
  children: number
  amount: string
  status: string
}

export interface PaymentTxn {
  name: string
  txn_type: string
  status: string
  method: string
  amount: string
  currency: string
  provider: string | null
  card_brand: string | null
  card_last4: string | null
  completed_at: string | null
  creation: string
}

export interface PaymentLinkRow {
  name: string
  status: string
  amount: string
  paid_amount: string
  currency: string
  expires_at: string | null
  creation?: string
}

export interface BookingSummary {
  booking: string
  status: string
  property: string
  currency: string
  total: string
  paid: string
  balance: string
  due_now: string
  payment_status: string
  market: string
  channel: string
  booker_name: string
  guest_change_pending: boolean
  rooms: BookingRoom[]
  idempotent_replay: boolean
  transactions?: PaymentTxn[]
  payment_links?: PaymentLinkRow[]
}

// ─── CRM ───────────────────────────────────────────────────────────────

export interface GuestRow {
  name: string
  full_name: string
  first_name: string | null
  last_name: string | null
  email: string | null
  phone: string | null
  vip: number
  blacklisted: number
  nationality: string | null
  tex_country: string | null
  tex_market: string | null
  tex_language: string | null
  tex_tags: string | null
  tex_stays: number | null
  tex_lifetime_value: string
  tex_last_stay: string | null
  tex_loyalty_points: number | null
  tex_consent_email: number
  tex_consent_sms: number
  tex_consent_whatsapp: number
}

export interface GuestStay {
  name: string
  property: string
  status: string
  check_in_date: string
  check_out_date: string
  room_type: string
  tex_board: string | null
  adults: number
  children: number
  tex_total_amount: string
  tex_currency: string | null
  tex_booking: string | null
  tex_sales_channel: string | null
  tex_market: string | null
}

export interface GuestProfile {
  guest: GuestRow & { guest_notes?: string | null; blacklist_reason?: string | null }
  stays: GuestStay[]
  communications: { name: string; channel: string; direction: string; subject: string | null; creation: string }[]
  segments: string[]
  hotels: string[]
}
