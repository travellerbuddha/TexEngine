// Shapes returned by kamra.tex.api.crm (see kamra/tex/crm/service.py). Money is a
// decimal string; flags are 0/1 as Frappe stores them.

export type Flag = 0 | 1

export const CONSENT_FIELDS = ["tex_consent_email", "tex_consent_sms", "tex_consent_whatsapp"] as const
export type ConsentField = (typeof CONSENT_FIELDS)[number]

export interface GuestRow {
  name: string
  full_name: string | null
  first_name: string | null
  last_name: string | null
  email: string | null
  phone: string | null
  vip: Flag
  blacklisted: Flag
  nationality: string | null
  tex_country: string | null
  tex_market: string | null
  tex_language: string | null
  tex_tags: string | null
  tex_stays: number | null
  tex_lifetime_value: string
  tex_lifetime_currency?: string | null
  tex_last_stay: string | null
  tex_loyalty_points: number | null
  tex_consent_email: Flag
  tex_consent_sms: Flag
  tex_consent_whatsapp: Flag
  tex_enterprise: string | null
}

export interface GuestPage {
  total: number
  rows: GuestRow[]
}

export interface Guest {
  name: string
  full_name: string | null
  first_name: string | null
  last_name: string | null
  phone: string | null
  email: string | null
  nationality: string | null
  date_of_birth: string | null
  gender: string | null
  vip: Flag
  guest_notes: string | null
  address_line: string | null
  city: string | null
  tex_language: string | null
  tex_country: string | null
  tex_market: string | null
  tex_tags: string | null
  tex_preferences: string | null
  blacklisted: Flag
  blacklist_reason: string | null
  tex_consent_email: Flag
  tex_consent_sms: Flag
  tex_consent_whatsapp: Flag
  tex_consent_updated_at: string | null
  tex_consent_source: string | null
  tex_consent_text_version: string | null
  tex_stays: number | null
  tex_lifetime_value: string
  tex_lifetime_currency?: string | null
  tex_last_stay: string | null
  tex_loyalty_points: number | null
  tex_enterprise: string | null
}

export interface Stay {
  name: string
  property: string
  status: string
  check_in_date: string
  check_out_date: string
  room_type: string | null
  tex_board: string | null
  adults: number | null
  children: number | null
  tex_total_amount: string
  tex_currency: string | null
  tex_booking: string | null
  tex_sales_channel: string | null
  tex_market: string | null
  /** the fee charged for a cancelled stay or a no-show (decimal string); null otherwise */
  cancellation_fee?: string | null
}

/** An extra on one of the guest's stays at the viewer's hotels (from its price-locked snapshot). */
export interface StayExtra {
  reservation: string
  property: string
  check_in: string
  code: string
  name: string
  /** decimal string, e.g. "1" or "2.5" */
  quantity: string
  amount: string
  currency: string
  service_dates: string[]
  /** added after the booking (post-booking extras) */
  added_later: boolean
}

/** Extras bought, per extra and currency (never summed across currencies). */
export interface ExtraSummary {
  code: string
  name: string
  currency: string
  quantity: string
  amount: string
  stays: number
}

/** Cancellations and no-shows at the viewer's hotels; fees per currency. */
export interface CancellationStats {
  count: number
  no_shows: number
  fees: { currency: string; amount: string }[]
  last_cancelled_on: string | null
}

export type CommChannel = "Email" | "SMS" | "WhatsApp" | "Phone" | "Note"
export type CommDirection = "Outbound" | "Inbound" | "Internal"
export type ConsentBasis = "Transactional" | "Marketing" | "Legitimate Interest"

export interface Communication {
  name: string
  channel: CommChannel
  direction: CommDirection
  status: string
  consent_basis: ConsentBasis
  subject: string | null
  body: string | null
  sent_at: string | null
  actor: string | null
  booking: string | null
  reservation: string | null
  creation: string
  /** e-mail: why the mail failed, e.g. "SMTPRecipientsRefused (550)" (ADR-047) */
  delivery_error?: string | null
}

export interface LoyaltyEntry {
  name: string
  entry_type: "Earn" | "Burn" | "Adjust" | "Expire" | "Reverse"
  points: number
  status: "Pending" | "Available" | "Used" | "Expired" | "Reversed"
  available_on: string | null
  expires_on: string | null
  booking: string | null
  reason: string | null
  creation: string | null
  /** earned or spent at another hotel of a shared (group) program: its booking and reason stay
   * with that hotel (ADR-056) */
  other_hotel?: boolean
}

export interface LoyaltyAccount {
  program: string
  program_name: string
  currency: string | null
  available: number
  pending: number
  lifetime_earned: number
  value: string
  tier: string | null
  entries: LoyaltyEntry[]
}

/** kamra.tex.api.ui_backoffice_crm_payments.loyalty_programs */
export interface LoyaltyProgramInfo {
  program: string
  program_name: string
  currency: string | null
  property: string
  min_redeem_points: number
  max_redeem_percent: string
}

export interface ConsentEvent {
  event_time: string
  /** guest.consent: a change; guest.consent_requested: asked for in an online booking on a known
   * profile and NOT applied until the guest confirms on a verified channel (ADR-046) */
  action: "guest.consent" | "guest.consent_requested"
  actor: string | null
  new_value: string | null
  reason: string | null
  source: string | null
  booking?: string | null
}

export interface GuestProfile {
  guest: Guest
  stays: Stay[]
  communications: Communication[]
  /** segments this guest is in, among the viewer's (presets and their enterprise's) */
  segments: { name: string; segment_name: string; system_key?: string | null }[]
  /** the viewer's programs only (their hotels' own, or their group's) */
  loyalty: LoyaltyAccount[]
  extras: StayExtra[]
  extras_summary: ExtraSummary[]
  cancellations: CancellationStats
  consent_history: ConsentEvent[]
  hotels: string[]
}

export type FieldKind = "int" | "money" | "str" | "bool" | "list"

export interface Condition {
  field: string
  op: string
  value?: unknown
  /** money conditions only: the 3-letter currency the value is compared in (ADR-036) */
  currency?: string | null
}

export interface SegmentRules {
  match: "all" | "any"
  conditions: Condition[]
}

export interface Segment {
  name: string
  segment_name: string
  /** set on the shared, read-only presets */
  system_key: string | null
  description: string | null
  /** owner of a custom segment (null: a preset or a platform-level segment) */
  enterprise?: string | null
  /** stored count of a custom segment (all the counting user's hotels); always null for presets */
  member_count: number | null
  last_evaluated: string | null
  rules_json: string | null
}

export interface SegmentsResponse {
  segments: Segment[]
  fields: Record<string, FieldKind>
  ops: Record<FieldKind, string[]>
  /** currencies a money condition may use */
  currencies: string[]
  /** enterprises a new segment may belong to (where the user holds crm.edit) */
  enterprises: { name: string; label: string }[]
}

export interface ExportRow {
  guest: string
  first_name: string | null
  last_name: string | null
  email: string | null
  phone: string | null
  language: string | null
  country: string | null
}

export type AbandonedStatus = "Open" | "Contacted" | "Recovered" | "Dismissed"
export const FUNNEL_STAGES = ["search", "room_view", "quote", "guest_details", "payment_started"] as const
export type FunnelStage = (typeof FUNNEL_STAGES)[number]

export interface AbandonedRow {
  name: string
  site: string | null
  stage_reached: FunnelStage
  status: AbandonedStatus
  guest: string | null
  email: string | null
  phone: string | null
  consent_marketing: Flag
  value: string
  currency: string | null
  check_in: string | null
  check_out: string | null
  last_event_at: string | null
  recovered_booking: string | null
}

// ─── loyalty administration (kamra.tex.api.loyalty, ADR-037) ───────────────

export type EarnBasis = "MONEY" | "NIGHTS" | "STAY" | "ROOM" | "EXTRA"
export const EARN_BASES: EarnBasis[] = ["MONEY", "NIGHTS", "STAY", "ROOM", "EXTRA"]
export type BlackoutPurpose = "Redemption" | "Earning" | "Both"
export const BLACKOUT_PURPOSES: BlackoutPurpose[] = ["Redemption", "Earning", "Both"]
export const LEDGER_TYPES = ["Earn", "Burn", "Adjust", "Expire", "Reverse"] as const
export type LedgerType = (typeof LEDGER_TYPES)[number]

export interface ProgramStats {
  members: number
  available_points: number
  pending_points: number
  /** available points × point value, a decimal string in the program currency */
  liability: string
}

interface ProgramFields {
  name: string
  program_name: string
  property: string | null
  hotel_group: string | null
  enabled: Flag
  currency: string | null
  /** decimal string (up to 6 decimals) */
  point_value: string
  min_redeem_points: number | null
  /** decimal string, 0–100; 0 = points cannot be redeemed */
  max_redeem_percent: string
  pending_days: number | null
  expiry_months: number | null
  /** the enabled hotels the program reaches */
  hotels: string[]
  can_edit: boolean
}

export interface ProgramRow extends ProgramFields, ProgramStats {
  modified: string
}

export interface ProgramsResponse {
  programs: ProgramRow[]
  /** where the user may create a program */
  scopes: { hotels: string[]; groups: string[] }
}

export interface EarnRule {
  basis: EarnBasis
  rate: string
  room_type: string | null
  extra: string | null
  date_from: string | null
  date_to: string | null
}

export interface ProgramTier {
  tier_name: string
  min_points: number | null
  earn_multiplier: string
}

export interface ProgramBlackout {
  date_from: string
  date_to: string
  note: string | null
  applies_to: BlackoutPurpose | null
}

export interface ProgramLookups {
  room_types: { name: string; room_type_name: string | null; property: string }[]
  extras: { name: string; extra_name: string | null; extra_code: string | null; property: string }[]
  currencies: string[]
}

export interface ProgramDetail extends ProgramFields, ProgramStats {
  earn_rules: EarnRule[]
  tiers: ProgramTier[]
  blackouts: ProgramBlackout[]
  lookups: ProgramLookups
}

export interface LedgerRow {
  name: string
  guest: string
  guest_name: string | null
  entry_type: LedgerType
  points: number
  status: LoyaltyEntry["status"]
  available_on: string | null
  expires_on: string | null
  booking: string | null
  reservation: string | null
  reason: string | null
  actor: string | null
  creation: string | null
  /** JSON of an earning: {lines: [{rule, rate?, points, note?}], tier, multiplier} */
  explanation: string | null
}

export interface LedgerPage {
  rows: LedgerRow[]
  total: number
}
