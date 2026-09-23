// Shapes returned by kamra/tex/api/public.py (guest-safe). Every amount is a
// decimal string computed by the server; the browser only formats it.

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
  default_market?: string | null
  branding: Branding
  contact: { phone?: string | null; email?: string | null; whatsapp?: string | null; address?: string | null }
  /** { "<lang>": { headline, tagline, search_button, confirmation_note, footer_note, … } } */
  texts: Record<string, Record<string, string> | string>
  policies?: string | null
  self_service: boolean
  analytics: { ga4?: string | null; gtm?: string | null; meta_pixel?: string | null; consent_banner: boolean }
  extras: Record<string, SiteExtra[]>
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
  } | null
  payment_policy?: {
    allow_pay_at_hotel?: boolean
    deposit_type?: string | null
    deposit_value?: string | null
    description?: string | null
    name?: string | null
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
   * "only N left on yyyy-mm-dd" or "closed on yyyy-mm-dd" (G-19) */
  reason?: string
  quantity: string
  amount: Money
  currency: string
  pricing_mode: string
  mandatory?: boolean
  service_dates?: string[]
  /** days (and units on each) it takes from a limited extra's daily capacity */
  usage?: { date: string; units: number }[]
}

export interface Promotion {
  promo_id: string
  name: string
  applied: boolean
  discount?: string
  code?: string | null
  value_added?: string | null
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

export interface Reason {
  code: string
  message: string
  /** occupancy limits, on MAX_ADULTS / MAX_CHILDREN / MAX_OCCUPANTS */
  max_adults?: number
  max_children?: number
  max_occupants?: number
}

export interface OfferRoom {
  room_index: number
  offer_key: string
  quote: RoomQuote
}

export interface RoomReason extends Reason {
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
  reasons?: Reason[]
  rooms: OfferRoom[]
  room_indexes: number[]
  /** fits every requested room */
  complete: boolean
  /** why it does not fit the other rooms */
  room_reasons?: RoomReason[]
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
}

export interface SearchResult {
  check_in: string
  check_out: string
  nights: number
  market: string
  rooms: { adults: number; children: { age: number | null }[] }[]
  properties: PropertyResult[]
}

export interface QuoteResponse {
  ok: boolean
  reasons?: Reason[]
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
  child_ages?: { age: number | null }[]
  rate_plan?: string | null
  refundable?: boolean
  lines?: QuoteLine[]
  extras?: ExtraOutcome[]
  cancellation_fee_now?: Money
  pending_change?: boolean
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
}

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
}

export interface Proposal {
  sellable: boolean
  old_total: Money
  new_total: Money | null
  difference: Money | null
  currency: string
  warnings: Reason[]
  lines?: QuoteLine[]
  proposal_token: string
}

export type PaymentMethod = "Card" | "Bank Transfer" | "Pay at Hotel"
