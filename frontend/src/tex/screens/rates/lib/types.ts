// Shapes returned by kamra/tex/api/contracts.py, policies.py and ui_rates.py.
// Money and rule values stay decimal *strings* in the editor (never floats).

export interface ContractRow {
  name: string
  property: string
  contract_code: string
  contract_name: string
  market: string
  status: string
  pricing_basis: "PERSON" | "ROOM"
  contract_currency: string
  sale_from: string | null
  sale_to: string | null
  stay_from: string | null
  stay_to: string | null
  active_version: string | null
  latest_version_no: number
  priority: number
  modified: string
  has_draft: boolean
}

export interface ContractDoc {
  name: string
  property: string
  contract_code: string
  contract_name: string
  market: string
  status: string
  pricing_basis: "PERSON" | "ROOM"
  contract_currency: string
  sell_currency: string | null
  priority: number
  is_bar: number
  sale_from: string | null
  sale_to: string | null
  stay_from: string | null
  stay_to: string | null
  active_version: string | null
  latest_version_no: number
  notes: string | null
  channels: { sales_channel: string }[]
  modified?: string
}

export interface VersionRow {
  name: string
  version_no: number
  status: "Draft" | "Published" | "Superseded" | "Withdrawn"
  effective_from: string | null
  active_to: string | null
  published_at: string | null
  published_by: string | null
  change_note: string | null
  payload_hash: string | null
  based_on: string | null
}

export interface ContractBundle {
  contract: ContractDoc
  versions: VersionRow[]
  can_edit: boolean
  can_publish: boolean
  /** A version was published once: the commercial header fields are fixed (G-50, ADR-045). */
  published?: boolean
  /** Header fields the server refuses to change (read-only in the header editor). */
  locked_fields?: string[]
  /** Status actions the user may take now (suspend, resume, archive, restore). */
  status_actions?: ContractStatusAction[]
  /** What the live version sells (a version frozen before G-50: narrowed by its header). */
  live_selling?: SellingTerms | null
}

export type ContractStatusAction = "suspend" | "resume" | "archive" | "restore"

/** A version's selling terms (G-50): frozen when published, the draft's own once the contract
 * was published, the contract header's before that. */
export interface SellingTerms {
  sale_from: string | null
  sale_to: string | null
  stay_from: string | null
  stay_to: string | null
  priority: number | null
  sell_currency: string | null
  channels: string[]
  /** Channels of the payload and of the header do not overlap: it sells on no channel. */
  no_channel?: boolean
  /** Frozen before G-50: its header (``header_market`` and the terms above) still narrows it. */
  legacy?: boolean
  header_market?: string | null
}

export interface RoomTypeOpt {
  name: string
  room_type_name: string
  adults_capacity?: number
  children_capacity?: number
  max_total_occupants?: number
  base_occupancy?: number
}

export interface RatePlanOpt {
  name: string
  rate_plan_name: string
  code?: string
  tex_refundable?: number
}

/** One editable child-table row. `_key` is client-only (save_version drops `_*`). */
export type Row = Record<string, string | number | null> & { _key: string }

export const VERSION_TABLES = [
  "rooms",
  "periods",
  "period_rates",
  "age_bands",
  "occupancy_rules",
  "boards",
  "rate_plans",
  "offers",
] as const
export type VersionTable = (typeof VERSION_TABLES)[number]

export const VERSION_SETTINGS = [
  "child_ordering",
  "age_basis",
  "children_over_max_as_adults",
  "infants_count_as_occupants",
  "prices_include_tax",
  "stacking",
  "room_basis_extra_unit",
  "room_basis_children_fill_included",
  "change_note",
] as const
export type VersionSetting = (typeof VERSION_SETTINGS)[number]

export interface VersionDoc {
  name: string
  contract: string
  version_no: number
  status: VersionRow["status"]
  change_note: string | null
  effective_from: string | null
  published_at: string | null
  published_by: string | null
  active_to: string | null
  based_on: string | null
  payload_hash: string | null
  child_ordering: string
  age_basis: string
  children_over_max_as_adults: number
  infants_count_as_occupants: number
  prices_include_tax: number
  stacking: string
  room_basis_extra_unit: string
  room_basis_children_fill_included: number
  validation_report: { ok?: boolean; issues?: Issue[] } | null | number
  editable: boolean
  selling?: SellingTerms
  selling_source?: "frozen" | "version" | "header"
  selling_editable?: boolean
  contract_doc: {
    name: string
    property: string
    contract_code: string
    contract_name: string
    market: string
    pricing_basis: "PERSON" | "ROOM"
    contract_currency: string
    status: string
  }
  room_types: RoomTypeOpt[]
  rate_plan_options: RatePlanOpt[]
  rooms: Record<string, unknown>[]
  periods: Record<string, unknown>[]
  period_rates: Record<string, unknown>[]
  age_bands: Record<string, unknown>[]
  occupancy_rules: Record<string, unknown>[]
  boards: Record<string, unknown>[]
  rate_plans: Record<string, unknown>[]
  offers: Record<string, unknown>[]
  modified?: string
}

export interface Issue {
  level: "ERROR" | "WARNING"
  code: string
  message: string
}

export interface ValidationResult {
  ok: boolean
  issues: Issue[]
}

export interface Lookups {
  room_types: RoomTypeOpt[]
  rate_plans: RatePlanOpt[]
  contracts: {
    name: string
    contract_code: string
    contract_name: string
    market: string
    status: string
    active_version: string | null
    contract_currency: string
    pricing_basis: "PERSON" | "ROOM"
  }[]
  cancellation_policies: { name: string; policy_name: string; refundable: number }[]
  payment_policies: { name: string; policy_name: string; deposit_type: string }[]
}

// ─── preview_price (engine RoomQuote.to_dict(internal=True)) ──────────────

export interface RuleRef {
  kind: string
  rule_id: string
  level: string | null
  source: string | null
  label: string | null
}

export interface ExplainStep {
  stage: string
  text: string
  code: string
  night: string | null
  before: string | null
  after: string | null
  currency: string | null
  rule: RuleRef | null
  overridden: RuleRef[]
}

export interface NightLine {
  date: string
  period: string
  unit: string
  occupancy: string
  board: string
  cost: string
  cost_net: string
  sell_contract: string
  sell: string
  final: string
}

export interface QuoteLine {
  kind: string
  code: string
  description: string
  amount: string
  quantity: string
  category: string
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

export interface PreviewResult {
  sellable: boolean
  reasons: { code: string; message: string }[]
  currency?: string
  contract?: { code: string; name: string; version_no: number; market: string; currency: string; basis: string; payload_hash: string }
  rate_plan?: {
    code: string
    name: string
    refundable: boolean
    cancellation_policy?: { name: string; description?: string } | null
    payment_policy?: { name: string; description?: string; deposit_type?: string } | null
    inclusions?: string[]
  } | null
  lines?: QuoteLine[]
  promotions?: PromoOutcome[]
  taxes?: { code: string; name: string; amount: string; included: boolean }[]
  totals?: Record<string, string>
  fx?: { from: string; to: string; mode: string; sell_rate: string | null; provider: string | null; provider_rate: string | null; rate_date: string | null; adjustment: string | null } | null
  nights?: NightLine[]
  explanation?: ExplainStep[]
}

export interface PriceMatrix {
  periods: { code: string; name: string; start: string; end: string }[]
  rooms: { room_type: string; name: string; cells: Record<string, string | null>; errors?: Record<string, string> }[]
  basis: "PERSON" | "ROOM"
  currency: string
}
