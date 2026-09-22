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

export type LocalText = string | Record<string, string>

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
  texts: Record<string, LocalText>
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
  reason?: string
  quantity: string
  amount: Money
  currency: string
  pricing_mode: string
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
}

export interface OfferRoom {
  room_index: number
  offer_key: string
  quote: RoomQuote
}

export interface Offer {
  room_type: string
  board: string
  rate_plan: string | null
  currency: string
  available: number
  total?: Money
  refundable?: boolean
  rate_plan_info?: RatePlanInfo | null
  bookable: boolean
  reasons?: Reason[]
  rooms: OfferRoom[]
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
  manage_token?: string
  payment: PaymentStart | null
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
