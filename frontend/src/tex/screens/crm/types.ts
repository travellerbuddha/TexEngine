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
  actor: string | null
  new_value: string | null
  reason: string | null
  source: string | null
}

export interface GuestProfile {
  guest: Guest
  stays: Stay[]
  communications: Communication[]
  segments: string[]
  loyalty: LoyaltyAccount[]
  consent_history: ConsentEvent[]
  hotels: string[]
}

export type FieldKind = "int" | "money" | "str" | "bool" | "list"

export interface Condition {
  field: string
  op: string
  value?: unknown
}

export interface SegmentRules {
  match: "all" | "any"
  conditions: Condition[]
}

export interface Segment {
  name: string
  segment_name: string
  system_key: string | null
  description: string | null
  member_count: number | null
  last_evaluated: string | null
  rules_json: string | null
}

export interface SegmentsResponse {
  segments: Segment[]
  fields: Record<string, FieldKind>
  ops: Record<FieldKind, string[]>
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
