// New-row defaults of the contract-version child tables and the row helpers the pure Pricing
// Workspace modules share (PRICING_WORKSPACE_UX.md D1). No runtime imports except lib/keys.ts, so
// everything here runs under `node --test`. lib/tables.ts re-exports ROW_DEFAULTS as NEW_ROW.
import { newKey } from "../lib/keys.ts"
import type { Issue, Row, VersionTable } from "../lib/types.ts"

/** New-row defaults (TEX Contract Room, TEX Price Period, TEX Period Rate, TEX Child Age Band,
 * TEX Occupancy Rule, TEX Board Rule, TEX Contract Rate Plan, TEX Contract Offer). */
export const ROW_DEFAULTS: Record<VersionTable, () => Omit<Row, "_key">> = {
  rooms: () => ({ room_type: "", is_base: 0, max_adults: 0, max_children: 0, max_occupants: 0, min_adults: 0, included_adults: 0 }),
  periods: () => ({ period_code: "", period_name: "", start_date: "", end_date: "", weekdays: "", adjustment_op: "", adjustment_value: "", priority: 0 }),
  period_rates: () => ({ room_type: "", period_code: "", op: "ABSOLUTE", value: "", base_room_type: "" }),
  age_bands: () => ({ band_code: "", label: "", from_age: "", to_age: "", is_infant: 0 }),
  occupancy_rules: () => ({
    target: "CHILD",
    position: 0,
    age_band: "",
    combination: "",
    room_type: "",
    period_code: "",
    op: "PERCENT_OF",
    value: "",
    is_override: 0,
    note: "",
  }),
  boards: () => ({ board: "HB", is_base: 0, op: "ADD", adult_amount: "", child_percent: "50", infant_free: 1, room_type: "", period_code: "", label: "" }),
  rate_plans: () => ({ rate_plan: "", op: "", value: "", refundable: 1, boards: "", cancellation_policy: "", payment_policy: "" }),
  offers: () => ({
    offer_code: "",
    offer_name: "",
    kind: "EARLY_BOOKING",
    value_type: "PERCENT",
    value: "",
    stage: "SELL",
    sale_from: "",
    sale_to: "",
    stay_from: "",
    stay_to: "",
    stay_match: "ANY_NIGHT",
    min_nights: 0,
    max_nights: 0,
    min_lead_days: 0,
    max_lead_days: 0,
    room_types: "",
    boards: "",
    stackable: 1,
    exclusive: 0,
    priority: 0,
    offer_group: "",
    free_nights_stay: 0,
    free_nights_pay: 0,
  }),
}

/** A new row of `table` with its defaults, `patch` on top and a fresh key. */
export function newRow(table: VersionTable, patch: Record<string, string | number | null> = {}): Row {
  return { ...ROW_DEFAULTS[table](), ...patch, _key: newKey() }
}

/** A copy of `row` as a new row: a fresh key and no server name (it is not that saved row). */
export function copyRow(row: Row, patch: Record<string, string | number | null> = {}): Row {
  const out: Row = { ...row, ...patch, _key: newKey() }
  delete out._name
  return out
}

/** A row field as a trimmed string ("" for null/undefined). */
export function str(v: unknown): string {
  return v === null || v === undefined ? "" : String(v).trim()
}

/** A row field as a whole number (ints only; 0 for blank or unreadable). Integers such as a
 * position are the only numbers these modules handle (§3.14 (f)). */
export function int(v: unknown): number {
  if (typeof v === "number") return Number.isInteger(v) ? v : 0
  const s = str(v)
  return /^-?[0-9]+$/.test(s) ? parseInt(s, 10) : 0
}

/** A 0/1 check field as a boolean. */
export function isSet(v: unknown): boolean {
  return v === 1 || v === true || v === "1"
}

/** The refundable flag of a rate-plan row whose rate plan or cancellation policy was just chosen
 * (Y-4, ADR-067): refundable only when the rate plan (`tex_refundable`, blank = refundable) and the
 * row's own cancellation policy, when it names one, both are. The server sells the row so and
 * refuses to publish a refundable row on a non-refundable policy (RATE_PLAN_REFUNDABLE). */
export function planRowRefundable(
  plan: { tex_refundable?: number | null } | undefined,
  policy: { refundable?: number | null } | undefined,
): 0 | 1 {
  const planSays = plan?.tex_refundable === undefined || plan.tex_refundable === null || isSet(plan.tex_refundable)
  const policySays = !policy || policy.refundable === undefined || policy.refundable === null || isSet(policy.refundable)
  return planSays && policySays ? 1 : 0
}

/** The rate-plan table after an edit (`next`), each row whose rate plan or cancellation policy
 * changed (or that is new with a rate plan) taking its refundable flag from them
 * (`planRowRefundable`): the row's own policy, else the rate plan's default policy, as the server
 * freezes it (O-2b). The other rows, and a flag the user set by hand, are kept. */
export function withPlanRefundable(
  prev: Row[],
  next: Row[],
  plans: readonly { name: string; tex_refundable?: number | null; tex_cancellation_policy?: string | null }[],
  policies: readonly { name: string; refundable?: number | null }[],
): Row[] {
  const before = new Map(prev.map((r) => [r._key, r]))
  return next.map((r) => {
    const old = before.get(r._key)
    const chosen = old ? str(old.rate_plan) !== str(r.rate_plan) || str(old.cancellation_policy) !== str(r.cancellation_policy) : !!str(r.rate_plan)
    if (!chosen || !str(r.rate_plan)) return r
    const plan = plans.find((p) => p.name === str(r.rate_plan))
    const policyName = str(r.cancellation_policy) || str(plan?.tex_cancellation_policy)
    const policy = policyName ? policies.find((p) => p.name === policyName) : undefined
    return { ...r, refundable: planRowRefundable(plan, policy) }
  })
}

/** The issues about one rate plan row (their `ref.rate_plan`, O-2b): listed under that row, the
 * row marked by the worst of them. */
export function planRowIssues(issues: readonly Issue[] | undefined, ratePlan: unknown): { issues: Issue[]; tone: "danger" | "warning" | undefined } {
  const code = str(ratePlan)
  const mine = code ? (issues ?? []).filter((i) => i.ref?.rate_plan === code) : []
  return { issues: mine, tone: mine.some((i) => i.level === "ERROR") ? "danger" : mine.length ? "warning" : undefined }
}
