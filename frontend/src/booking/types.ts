// Shapes returned by kamra/tex/api/public.py (guest-safe). Every amount is a
// decimal string computed by the server; the browser only formats it.

import type { Residency } from "../lib/residency"

export type Money = string

export interface Branding {
  logo?: string | null
  primary?: string | null
  accent?: string | null
  background?: string | null
  font?: string | null
  radius?: string | null
  card_radius?: string | null
  button_style?: string | null
  header?: string | null
  search_style?: string | null
  hero_image?: string | null
}

export interface HotelPhoto {
  url: string
  caption?: string | null
}

export interface Hotel {
  name: string
  property_name: string
  city?: string | null
  star_category?: string | null
  address_line?: string | null
  phone?: string | null
  email?: string | null
  checkin_time?: string | null
  checkout_time?: string | null
  hero_image?: string | null
  logo_url?: string | null
  showcase_description?: string | null
  currency?: string | null
  gallery: HotelPhoto[]
}

export interface SiteExtra {
  extra_code: string
  extra_name: string
  category?: string | null
  description?: string | null
  image?: string | null
  pricing_mode: string
  currency: string
  amount: Money
  max_quantity?: number | null
  is_mandatory?: number | boolean | null
  service_from?: string | null
  service_to?: string | null
}

export interface Site {
  slug: string
  name: string
  hotels: Hotel[]
  group: boolean
  default_language: string
  languages: string[]
  default_currency?: string | null
  currencies: string[]
  branding: Branding
  contact: { phone?: string | null; email?: string | null; whatsapp?: string | null; address?: string | null }
  /** { "<lang>": { headline, tagline, search_button, confirmation_note, footer_note, … } } */
  texts: Record<string, Record<string, string> | string>
  policies?: string | null
  self_service: boolean
  analytics: { ga4?: string | null; gtm?: string | null; meta_pixel?: string | null; consent_banner: boolean }
  extras: Record<string, SiteExtra[]>
  /** the site's loyalty programs a guest may sign in to or join (C-04, ADR-078); null: none */
  membership?: { programs: string[] } | null
}

/** A guest signed in on the site (public.member_status) */
export interface MemberStatus {
  signed_in: boolean
  first_name?: string | null
  last_name?: string | null
  email?: string | null
  /** a member of the program of at least one of the site's hotels */
  member: boolean
  hotels: string[]
}

export interface CancellationRule {
  days_before_arrival: number
  penalty_type: string
  penalty_value: string
}

export interface RatePlanInfo {
  code: string
  name: string
  refundable: boolean
  cancellation_policy?: {
    description?: string | null
    name?: string | null
    refundable?: boolean
    rules?: CancellationRule[]
    /** of its fixed amounts; frozen only on a policy with one (ADR-067) */
    currency?: string | null
  } | null
  payment_policy?: {
    /** the policy's id: a fixed deposit is taken once per booking and policy (LO-35) */
    id?: string | null
    allow_pay_at_hotel?: boolean
    deposit_type?: string | null
    deposit_value?: string | null
    description?: string | null
    name?: string | null
    /** of its fixed deposit; frozen only on a policy with one (ADR-067) */
    currency?: string | null
  } | null
  inclusions?: string[] | null
}

export interface QuoteLine {
  kind: string
  code: string
  description: string
  amount: Money
  quantity: string
  category: string
  included: boolean
  ref?: string | null
}

export interface ExtraOutcome {
  code: string
  name: string
  ok: boolean
  /** why it was not added (ok=false); a limited extra says "sold out on yyyy-mm-dd",
   * "not enough left on yyyy-mm-dd" or "closed on yyyy-mm-dd" (G-19; guests never see a count) */
  reason?: string
  quantity: string
  amount: Money
  currency: string
  pricing_mode: string
  mandatory?: boolean
  service_dates?: string[]
  /** days (and units on each) it takes from a limited extra's daily capacity */
  usage?: { date: string; units: number }[]
  /** set when the extra was added after booking (the add-on's id, ADR-034) */
  addon?: string
}

export interface Promotion {
  promo_id: string
  name: string
  applied: boolean
  discount?: string
  code?: string | null
  value_added?: string | null
  /** a members-only promotion: the signed-in member's price (C-04) */
  member_only?: boolean
}

export interface RoomQuote {
  sellable: boolean
  currency: string
  rate_plan?: RatePlanInfo | null
  lines: QuoteLine[]
  promotions: Promotion[]
  extras: ExtraOutcome[]
  taxes: { code?: string; name?: string; amount?: Money; included?: boolean }[]
  totals: Record<string, Money>
  nights: { date: string; amount: Money }[]
}

/** Why a search offer or a quote cannot be sold: a code and the limit it names, never the engine's text
 * (which may name the contract, G-71). */
export interface OfferReason {
  code: string
  /** occupancy limits, on MAX_ADULTS / MAX_CHILDREN / MAX_OCCUPANTS */
  max_adults?: number
  max_children?: number
  max_occupants?: number
}

/** A warning or refusal of the manage page (a change, extras added to a stay), with its text. */
export interface Reason extends OfferReason {
  message: string
}

export interface OfferRoom {
  room_index: number
  offer_key: string
  quote: RoomQuote
  /** what a member pays for this room ("Member price", applied only when signed in) */
  member_total?: Money
}

export interface RoomReason extends OfferReason {
  room_index: number
}

/** One room type × board × rate plan. Every requested room (party) is priced on its
 * own: `rooms` holds only the parties this room type fits — look them up by
 * `room_index`, never by position. */
export interface Offer {
  room_type: string
  board: string
  rate_plan: string | null
  currency: string
  /** rooms of this type still free (the same type cannot take more requested rooms) */
  available: number
  /** server total for all requested rooms — only when `complete` */
  total?: Money
  refundable?: boolean
  rate_plan_info?: RatePlanInfo | null
  bookable: boolean
  reasons?: OfferReason[]
  rooms: OfferRoom[]
  room_indexes: number[]
  /** fits every requested room */
  complete: boolean
  /** why it does not fit the other rooms */
  room_reasons?: RoomReason[]
  /** a members-only promotion priced it: the signed-in member's price */
  member_price?: boolean
  /** what a member pays for every requested room, shown beside anyone's price (only when `complete`) */
  member_total?: Money
}

export interface RoomContent {
  name: string
  description?: string | null
  bed_type?: string | null
  beds?: string | number | null
  size_sqm?: number | null
  view?: string | null
  amenities: string[]
  image?: string | null
  max_adults?: number | null
  max_children?: number | null
}

export interface PropertyResult {
  property: string
  property_name: string
  city?: string | null
  star_category?: string | null
  offers: Offer[]
  unavailable: Offer[]
  rooms: Record<string, RoomContent>
  /** cheapest placement of every requested room (null when a room fits nowhere) */
  from_total?: Money | null
  from_currency?: string | null
  /** requested rooms (0-based) no room type of this hotel fits */
  unplaced_rooms?: number[]
  /** the cheapest placement at a member's price, when lower */
  member_from_total?: Money | null
}

export interface SearchResult {
  check_in: string
  check_out: string
  nights: number
  /** these prices are for residents of these countries (a residents-only market, O-8): checkout asks the guest */
  residency?: Residency | null
  rooms: { adults: number; children: { age: number | null }[] }[]
  properties: PropertyResult[]
  /** the member session sent: signed in, and the hotels it is priced as a member at */
  member?: { signed_in: boolean; hotels: string[] }
}

export interface QuoteResponse {
  ok: boolean
  reasons?: OfferReason[]
  quote_id?: string
  expires_at?: string
  price_changed?: boolean
  previous_total?: Money
  quote?: RoomQuote
  room_index?: number
}

export interface PaymentStart {
  transaction: string
  kind: "redirect" | "form_post" | "instructions" | "none" | string
  url?: string | null
  fields?: Record<string, string> | null
  instructions?: Record<string, string | null> | null
  sandbox?: boolean
}

export interface BookingRoom {
  reservation: string
  room_type: string
  room_type_name?: string
  check_in: string
  check_out: string
  adults: number
  children: number
  amount: Money
  status: string
  board?: string
  /** age on arrival (whole years); dob when the child was given by date of birth (G-52) */
  child_ages?: { age: number | null; dob?: string | null }[]
  rate_plan?: string | null
  refundable?: boolean
  lines?: QuoteLine[]
  extras?: ExtraOutcome[]
  cancellation_fee_now?: Money
  /** in the fee: the discount the other rooms keep once this one is cancelled (G-84 review H1) */
  cancellation_basket?: BasketClawback | null
  /** the guest's change of this room still waiting (for their payment or for the hotel), or
   * { status: "noted" } for a change the hotel has not reviewed yet (G-45) */
  pending_change?: PendingChange | null
  /** the guest may change this room online (confirmed, not arrived yet) */
  can_change?: boolean
  /** the guest may cancel this room online: only before the arrival day (O-16) */
  can_cancel?: boolean
  /** the guest's latest change of this room and what came of it */
  last_change?: ChangeOutcome | null
}

/** How the money of a guest's change is settled (server-decided; G-45, ADR-044):
 * pay_now: paid online before the change applies · pay_at_hotel: applies now, the difference
 * is paid at the hotel · balance: applies now, the open balance changes · refund: applies now,
 * the overpayment goes back to the card · credit: applies now, kept as credit on the booking ·
 * staff_approval: a lower price the hotel approves first · staff: due now without online
 * payment, the hotel takes it · none: the price does not change. */
export type SettlementKind = "pay_now" | "pay_at_hotel" | "balance" | "refund" | "credit" | "staff_approval" | "staff" | "none"

export interface Settlement {
  kind: SettlementKind
  /** the one figure the guest is shown for this kind */
  amount: Money
  collect?: Money
  /** of a refund: what goes back to the card automatically */
  refund?: Money
  /** of a refund: what goes back to the guest's loyalty points (the share points paid) */
  points_back?: Money
  /** of a refund: what the hotel refunds (paid in cash, by transfer, …) */
  hotel_refund?: Money
  /** of a refund: what went back to the card so far */
  refunded?: Money
  /** of a refund: the card part is back on the card */
  refund_done?: boolean
  credit?: Money
  balance_after?: Money
  currency: string
}

export interface PendingChange {
  request?: string
  status: "awaiting_payment" | "requested" | "noted"
  kind?: "pay_now" | "staff_approval" | "staff"
  changes?: { check_in?: string; check_out?: string; adults?: number; children?: unknown[] }
  difference?: Money
  /** what to pay online (awaiting_payment) */
  amount?: Money | null
  currency?: string
  expires_at?: string | null
}

export interface ChangeOutcome {
  request: string
  status: "awaiting_payment" | "requested" | "applied" | "approved" | "rejected" | "failed" | "expired" | "superseded"
  settlement: SettlementKind | null
  amount: Money
  /** what the guest paid online for this change */
  paid: Money
  refunded: Money
  /** money of this change the hotel refunds (it could not go back to a card automatically) */
  hotel_refund: Money
  /** a change not made: what became of the guest's payment (null while the change is open or made) */
  money_back: "none" | "refunded" | "refunding" | "hotel" | null
  currency: string
}

/** manage_apply / manage_change_pay */
export interface ChangeResult {
  status: "payment_required" | "applied" | "requested" | "processing"
  request?: string | null
  amount?: Money
  currency?: string
  expires_at?: string
  settlement?: Settlement
  payment?: PaymentStart
  balance?: Money
  paid?: Money
  credit?: Money
  refund_due?: Money
  message?: string
  replay?: boolean
}

export interface BookingSummary {
  booking: string
  status: string
  property: string
  currency: string
  total: Money
  paid: Money
  balance: Money
  due_now: Money
  payment_status: string
  booker_name?: string
  guest_change_pending?: boolean
  rooms: BookingRoom[]
  idempotent_replay?: boolean
  hotel?: string
  self_service?: boolean
  /** money held above the total: a change kept as credit, or a refund still to come */
  credit?: Money
  /** why the guest cannot change the booking yet (its own payment comes first) */
  /** money of this booking being refunded, or that the hotel refunds: not the guest's credit */
  refund_due?: Money
  /** PAYMENT_PENDING: its own payment first · REFUND_PENDING: a refund of an earlier change is being
   * made · CHANGE_APPLYING: a paid change is being applied (G-45) */
  changes_blocked?: "PAYMENT_PENDING" | "REFUND_PENDING" | "CHANGE_APPLYING" | null
  /** the hotel takes card payments online for this booking */
  can_pay_online?: boolean
  /** money that came when the booking could no longer take it: refunded, or the hotel will contact the guest (B5) */
  late_payment?: LatePayment | null
  /** a channel's booking (LO-12): who sold it, by the channel's label; it is changed and cancelled there */
  sold_by?: { label: string } | null
}

export type LatePayment = "refund" | "contact"

export interface BookResponse extends BookingSummary {
  /** manage token; on a retried request (idempotent_replay) a signed 24 h resume token */
  manage_token?: string
  payment: PaymentStart | null
}

export interface BasketMethod {
  method: PaymentMethod | string
  provider_account: string | null
  label: string
  provider: string | null
  sandbox: boolean
  available: boolean
  due_now: Money | null
  balance_after: Money | null
}

/** Server totals of the quoted rooms before booking (public.basket). */
export interface Basket {
  currency: string
  total: Money
  usable: boolean
  expires_at: string
  pay_at_hotel_allowed: boolean
  rooms: {
    quote_id: string
    room_type: string
    total: Money
    due_now: Money | null
    deposit_type: string
    pay_at_hotel_allowed: boolean
    expires_at: string
    problem: string | null
  }[]
  methods: BasketMethod[]
  /** the booked quotes' market is for residents of these countries (O-8) */
  residency?: Residency | null
}

export interface PaymentLinkInfo {
  description?: string | null
  amount: Money
  paid: Money
  currency: string
  status: string
  expires_at?: string | null
  guest_name?: string | null
  hotel?: string | null
  methods: { method: string; provider_account: string; label: string; sandbox: boolean }[]
  /** its booking could not take the money: refunded, or the hotel will contact the guest (B5) */
  late_payment?: LatePayment | null
}

/** What a room carries for the other rooms of its booking once a change or a cancellation takes
 * the booking below a promotion's minimum basket: the discount they keep (a credit when negative;
 * G-84 review H1). Server figures only. */
export interface BasketClawback {
  amount: Money
  currency: string
  promotions: { name: string; minimum: Money | null; basket_after: Money; amount: Money }[]
}

export interface Proposal {
  sellable: boolean
  old_total: Money
  new_total: Money | null
  difference: Money | null
  currency: string
  warnings: Reason[]
  lines?: QuoteLine[]
  /** in the new price: the discount the other rooms keep (G-84 review H1) */
  basket_clawback?: BasketClawback | null
  /** how the change would be settled; null when it cannot be made */
  settlement?: Settlement | null
  proposal_token: string | null
}

// ─── extras added to a booked stay (G-22, ADR-034) ───────────────────────

/** public.manage_extras: an extra the guest can still add to a booked room. Only what
 * the hotel sells online after booking; never a remaining count (available / few left). */
export interface AddonOption {
  code: string
  /** in the guest's language */
  name: string
  category?: string | null
  description?: string | null
  image?: string | null
  pricing_mode: string
  currency: string
  /** the catalogue price (the exact price comes from manage_extras_propose) */
  amount: Money
  max_quantity?: number | null
  /** how many this room already has (its booking and earlier add-ons) */
  booked: number
  /** hours of notice the hotel needs before the day it is used */
  cutoff_hours?: number | null
  /** the hotel limits it per day (spa slots, transfers…, G-19) */
  limited: boolean
  /** per day of the stay (arrival to departure) for a limited extra, else null */
  days: Record<string, { available: boolean; low: boolean }> | null
}

export interface AddonOptions {
  reservation: string
  check_in: string
  check_out: string
  currency: string
  extras: AddonOption[]
}

/** One extra asked for in manage_extras_propose. */
export interface AddonRequest {
  code: string
  quantity: number
  service_dates?: string[]
}

/** public.manage_extras_propose: the extras priced on their own (the stay stays price-locked).
 * Refusal codes: ADDON_EMPTY, ADDON_PARTY, ADDON_NOT_AVAILABLE, ADDON_QUANTITY,
 * ADDON_TOO_LATE, ADDON_SOLD_OUT ("Spa: sold out on yyyy-mm-dd", never a count). */
export interface AddonProposal {
  ok: boolean
  reasons: Reason[]
  currency: string
  /** the room's total now, and with the extras (null when refused) */
  old_total: Money
  new_total: Money | null
  /** signed, valid 30 minutes; null when refused */
  proposal_token: string | null
  /** EXTRA lines, then the extras' own TAX lines */
  lines: QuoteLine[]
  extras: ExtraOutcome[]
  totals: Record<string, Money>
}

/** public.manage_extras_apply: the booking's balance grows by the add-on (paid online or at the hotel). */
export interface AddonApplied {
  reservation: string
  addon: string
  /** the room's new total */
  total: Money
  currency: string
  /** the same proposal was applied before (a retried request) */
  replay: boolean
  booking?: string
  balance?: Money
  payment_status?: string
}

export type PaymentMethod = "Card" | "Bank Transfer" | "Pay at Hotel"
