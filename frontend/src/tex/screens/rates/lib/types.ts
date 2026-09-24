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
  /** The issues the server stored at publish: the list of issues (an older `{issues}` object is
   * read too; use workspace/draftPreview.storedIssues). */
  validation_report: Issue[] | { ok?: boolean; issues?: Issue[] } | null
  editable: boolean
  /** An agent's catalogue (price.view without cost): rooms, boards and rate plans, no amounts. */
  cost_hidden?: boolean
  // what the Pricing Workspace may offer this viewer (ADR-061); the endpoints check again.
  // An agent's catalogue carries the three can_* flags as false and no basis_locked.
  can_preview: boolean
  can_publish: boolean
  can_edit_contract: boolean
  /** the contract's pricing basis is fixed: one of its versions was published */
  basis_locked?: boolean
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
    /** decimal places of the contract currency (2 EUR, 0 JPY, 3 KWD); not in an agent's catalogue */
    minor_units?: number
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

/**
 * What a validation issue is about (ADR-061 D9, GAP-4): only the parts it has. Rule ids are the
 * saved row names, or `~<_key>` for rows sent unsaved to `validate_version(name, data)`.
 * `rule_ids` lists every rule of an issue about several (twins, ties); `rule_id` is the first.
 * `age_bands` (AGE_BANDS) is every band code of the contract, so the message's codes can be
 * shown as labels. The sweep reports a combination once, with the first period it fails in.
 */
export interface IssueRef {
  rule_id?: string
  rule_ids?: string[]
  room_type?: string
  period?: string
  other_period?: string
  age_band?: string
  age_bands?: string[]
  adults?: number
  children?: number
  board?: string
}

export interface Issue {
  level: "ERROR" | "WARNING"
  code: string
  message: string
  ref?: IssueRef
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
  /**
   * The night's running totals for the Explain ladder (ADR-061 GAP-12), 6-dp strings: after the
   * adults (ROOM basis: room price + extra adults), after the children (before a combination
   * rule; `occupancy` is after it) and occupancy + board (before the period adjustment). Absent
   * from quotes stored before GAP-12: the ladder then leaves those stages blank.
   */
  subtotal_adults?: string
  subtotal_children?: string
  subtotal_board?: string
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

/**
 * A child of a price test (ADR-061 GAP-6): an age in whole years 0–17, or exactly — in months
 * (0–215) or by date of birth (ISO `YYYY-MM-DD`, under 18 on arrival, never in the future).
 */
export type PreviewChild = number | { age_months: number } | { dob: string }

/** What `contracts.preview_price` takes. */
export interface PreviewRequest {
  version: string
  room_type: string
  board: string
  rate_plan?: string | null
  check_in: string
  check_out: string
  adults: number
  /** at most 12 */
  children: PreviewChild[]
  market?: string | null
  channel?: string
  currency?: string | null
  sale_at?: string | null
  promo_codes?: string[]
  /** the editor's unsaved `save_version` payload (ADR-061 GAP-1): price the draft as shown */
  data?: unknown
}

/**
 * One entered price changed once by `contracts.apply_op_values` (ADR-061 GAP-7): the new price as
 * exact decimal text in the contract currency, or null with why — `NO_VALUE` (no price was given)
 * or `NEGATIVE` (the result would be below zero). One per value sent, in order.
 */
export interface ApplyOpResult {
  value: string | null
  error: null | "NO_VALUE" | "NEGATIVE"
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

// ─── price_matrix (ADR-061: GAP-2 sources, GAP-2b sample parties, GAP-3 inherited terms) ───

/** The rule that priced a room's unit in a period (matrix.unit_source). */
export interface CellSource {
  rule_id: string
  /** PERIOD: the period's own rule; ALL: the room's rule for every period */
  scope: "PERIOD" | "ALL"
  op: string
  /** exact decimal text without trailing zeros ("1.15", "245") */
  value: string | null
  base_room_type: string | null
  /** the room, then the rooms it is derived from */
  chain: string[]
  /** rules of the room that did not win (a generic rule, an INHERIT row) */
  overridden: string[]
}

/** Effective capacity: the contract room's values, else the room type's. */
export interface RoomCapacity {
  max_adults: number
  max_children: number
  max_occupants: number
  min_adults: number
  included_adults: number
}

export interface MatrixRoom {
  room_type: string
  name: string
  cells: Record<string, string | null>
  errors?: Record<string, string>
  /** per period code; a cell with an error has none */
  sources: Record<string, CellSource>
  capacity: RoomCapacity
}

export interface MatrixAgeBand {
  code: string
  /** as built: equals the code when the band has no label */
  label: string
  from_months: number
  to_months: number
  is_infant: boolean
  /** "version", or the pricing policy the bands are inherited from ("policy:<id>/r<rev>/<scope>") */
  source: string
}

/** An occupancy rule the version inherits from a pricing policy. */
export interface InheritedOccupancyRule {
  rule_id: string
  target: "ADULT" | "CHILD" | "COMBINATION"
  position: number | null
  age_band: string | null
  adults: number | null
  children: number | null
  room_type: string | null
  period: string | null
  op: string
  value: string | null
  is_override: boolean
  source: string
}

/** The engine's own default for a slot no rule prices (D12). */
export interface OccupancyDefault {
  rule_id: string
  target: "ADULT"
  op: string
  value: string
  source: string
  note: string
}

/** A sample party posted as price_matrix(parties): each child named by its age band code. */
export interface SampleParty {
  adults: number
  children: string[]
}

export interface PartySlot {
  target: "ADULT" | "CHILD"
  position: number
  age_band: string | null
  amount: string
  /** null for a place included in a ROOM-basis price */
  rule_id: string | null
  included: boolean
}

/** One sample party priced per period code (occupancy total of one night in party_room). */
export interface PartyCell {
  cells: Record<string, string | null>
  slots: Record<string, PartySlot[]>
  errors: Record<string, string>
}

export interface PriceMatrix {
  periods: { code: string; name: string; start: string; end: string }[]
  rooms: MatrixRoom[]
  basis: "PERSON" | "ROOM"
  currency: string
  age_bands: MatrixAgeBand[]
  inherited_rules: InheritedOccupancyRule[]
  occupancy_defaults: { adult: OccupancyDefault; child: null }
  /** only when parties were posted, in their order */
  party_cells?: PartyCell[]
  build_error?: undefined
}

/** price_matrix with unsaved data that cannot be built (a room of another hotel, ambiguous policies). */
export interface PriceMatrixBuildError {
  build_error: string
  rooms: []
  periods: []
}

export type PriceMatrixResponse = PriceMatrix | PriceMatrixBuildError
