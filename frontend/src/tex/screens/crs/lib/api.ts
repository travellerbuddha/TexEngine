// CRS / Call Center / Reservations calls. Signatures: kamra/tex/api/crs.py and
// ui_crs.py (this workstream's helper module). The server owns every amount.
import { tex, type TexModule } from "../../../lib/api"
import type { ExtrasAvailability } from "./extrasStock"
import type {
  BookingSummary,
  ExtraDef,
  GuestProfile,
  GuestRow,
  PaymentMethod,
  QuoteResult,
  QuoteSummary,
  SearchResult,
} from "./types"

/** kamra.tex.api.ui_crs — not yet in the shared TexModule union (see report). */
export const UI_CRS = "ui_crs" as TexModule

export interface SearchArgs {
  check_in: string
  check_out: string
  rooms: { adults: number; children: ({ age: number } | { dob: string })[] }[]
  market: string
  channel: string
  currency?: string
  promo_codes?: string[]
  properties?: string[]
}

/** POST: a party may carry a child's date of birth, which never goes into a URL (G-52 review). */
export function searchOffers(args: SearchArgs, signal?: AbortSignal) {
  return tex<SearchResult>(UI_CRS, "search", { ...args }, { signal, post: true })
}

/** An extra of a quote request: SERVICE_DATE extras need at least one date; the others may
 * name the day of the stay they are used on (default: arrival). */
export interface ExtraRequest {
  code: string
  quantity: number
  service_dates?: string[]
}

export function quoteOffer(offer_key: string, extras: ExtraRequest[], promo_codes?: string[]) {
  return tex<QuoteResult>("crs", "quote", { offer_key, extras, promo_codes }, { post: true })
}

/** The rooms of one booking quoted together (G-84): a coupon's minimum basket is the whole
 * booking's. One answer per room, in the order given. */
export async function quoteRooms(rooms: { offer_key: string; extras: ExtraRequest[] }[], promo_codes?: string[]) {
  const out = await tex<{ ok: boolean; rooms: QuoteResult[]; booking_basket: string | null }>("crs", "quote_rooms", { rooms, promo_codes }, { post: true })
  return out.rooms
}

export function quoteSummary(quote_ids: string[], payment_method?: string) {
  return tex<QuoteSummary>(UI_CRS, "quote_summary", { quote_ids, payment_method: payment_method || undefined })
}

export interface BookArgs {
  quote_ids: string[]
  guest: Record<string, unknown>
  booker?: { name?: string; email?: string; phone?: string } | null
  payment_method?: string
  confirm_without_payment?: 0 | 1
  notes?: string
  idempotency_key: string
  language?: string
}

export function bookQuotes(args: BookArgs) {
  return tex<BookingSummary>(UI_CRS, "book", { ...args }, { post: true })
}

export function paymentMethods(property: string, market: string, currency: string, channel: string) {
  return tex<PaymentMethod[]>("crs", "payment_methods", { property, market, currency, channel })
}

export function extrasFor(property: string) {
  return tex<ExtraDef[]>("crs", "extras_for", { property })
}

/** What is left of each limited extra per day of the stay, check-in..check-out inclusive (G-19). */
export function extrasAvailability(property: string, check_in: string, check_out: string, signal?: AbortSignal) {
  return tex<ExtrasAvailability>("crs", "extras_availability", { property, check_in, check_out }, { signal })
}

export function findGuests(q: string, signal?: AbortSignal) {
  return tex<{ total: number; rows: GuestRow[] }>("crm", "guests", { q, limit: 8 }, { signal })
}

export function guestProfile(name: string) {
  return tex<GuestProfile>("crm", "guest", { name })
}

export function logCall(args: { guest: string; subject: string; body: string; booking?: string; property?: string }) {
  return tex<{ name: string }>(
    "crm",
    "log_communication",
    { ...args, channel: "Phone", direction: "Inbound", consent_basis: "Transactional" },
    { post: true },
  )
}

export function fetchBooking(name: string) {
  return tex<BookingSummary>("crs", "booking", { name })
}

export interface PaymentLinkArgs {
  property: string
  amount: string
  currency: string
  description: string
  expires_hours: number
  provider_account?: string
  booking?: string
  reservation?: string
  guest_name?: string
  guest_email?: string
  idempotency_key: string
  /** 1 = the server e-mails the link to guest_email (transactional). */
  send_email?: 0 | 1
  language?: string
}

/** The URL carries a bearer token: the server returns it once and never stores it. */
export interface PaymentLinkResult {
  link: string
  url?: string
  emailed?: boolean
  replay?: boolean
}

export function createPaymentLink(args: PaymentLinkArgs) {
  return tex<PaymentLinkResult>("payments", "create_link", { ...args }, { post: true })
}

/** New token for an open link; the previous URL stops working. */
export function reissuePaymentLink(name: string, send_email: 0 | 1, language?: string) {
  return tex<PaymentLinkResult>("payments", "reissue_link", { name, send_email, language }, { post: true })
}
