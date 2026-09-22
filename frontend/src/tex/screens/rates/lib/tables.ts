// Field kinds and new-row defaults of the contract-version child tables
// (TEX Contract Room, TEX Price Period, TEX Period Rate, TEX Child Age Band,
// TEX Occupancy Rule, TEX Board Rule, TEX Contract Rate Plan, TEX Contract Offer).
import type { Row, VersionDoc, VersionSetting, VersionTable } from "./types"
import { fromRow, toRow, type FieldKind } from "./util"

export const KINDS: Record<VersionTable, Record<string, FieldKind>> = {
  rooms: {
    room_type: "select",
    is_base: "check",
    max_adults: "int",
    max_children: "int",
    max_occupants: "int",
    min_adults: "int",
    included_adults: "int",
  },
  periods: {
    period_code: "text",
    period_name: "text",
    start_date: "date",
    end_date: "date",
    weekdays: "weekdays",
    adjustment_op: "select",
    adjustment_value: "decimal",
    priority: "int",
  },
  period_rates: { room_type: "select", period_code: "select", op: "select", value: "decimal", base_room_type: "select" },
  age_bands: { band_code: "text", label: "text", from_age: "decimal", to_age: "decimal", is_infant: "check" },
  occupancy_rules: {
    target: "select",
    position: "int",
    age_band: "select",
    combination: "text",
    room_type: "select",
    period_code: "select",
    op: "select",
    value: "decimal",
    is_override: "check",
    note: "text",
  },
  boards: {
    board: "select",
    is_base: "check",
    op: "select",
    adult_amount: "decimal",
    child_percent: "decimal",
    infant_free: "check",
    room_type: "select",
    period_code: "select",
    label: "text",
  },
  rate_plans: {
    rate_plan: "select",
    op: "select",
    value: "decimal",
    refundable: "check",
    boards: "csv",
    cancellation_policy: "select",
    payment_policy: "select",
  },
  offers: {
    offer_code: "text",
    offer_name: "text",
    kind: "select",
    value_type: "select",
    value: "decimal",
    stage: "select",
    sale_from: "date",
    sale_to: "date",
    stay_from: "date",
    stay_to: "date",
    stay_match: "select",
    min_nights: "int",
    max_nights: "int",
    min_lead_days: "int",
    max_lead_days: "int",
    room_types: "csv",
    boards: "csv",
    stackable: "check",
    exclusive: "check",
    priority: "int",
    offer_group: "text",
    free_nights_stay: "int",
    free_nights_pay: "int",
  },
}

export const NEW_ROW: Record<VersionTable, () => Omit<Row, "_key">> = {
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

export type Tables = Record<VersionTable, Row[]>
export type Settings = Record<VersionSetting, string | number>

export interface EditorState {
  settings: Settings
  tables: Tables
}

export function stateFromDoc(doc: VersionDoc): EditorState {
  const tables = {} as Tables
  for (const k of Object.keys(KINDS) as VersionTable[]) {
    tables[k] = ((doc[k] as Record<string, unknown>[]) ?? []).map((r) => toRow(r, KINDS[k]))
  }
  return {
    settings: {
      child_ordering: doc.child_ordering || "OLDEST_FIRST",
      age_basis: doc.age_basis || "ARRIVAL",
      children_over_max_as_adults: doc.children_over_max_as_adults ? 1 : 0,
      infants_count_as_occupants: doc.infants_count_as_occupants ? 1 : 0,
      prices_include_tax: doc.prices_include_tax ? 1 : 0,
      stacking: doc.stacking || "SEQUENTIAL",
      room_basis_extra_unit: doc.room_basis_extra_unit || "PER_PERSON_SHARE",
      room_basis_children_fill_included: doc.room_basis_children_fill_included ? 1 : 0,
      change_note: doc.change_note ?? "",
    },
    tables,
  }
}

/** Payload for contracts.save_version (settings + every child table). */
export function payloadOf(s: EditorState): Record<string, unknown> {
  const out: Record<string, unknown> = { ...s.settings }
  if (out.change_note === "") out.change_note = null
  for (const k of Object.keys(KINDS) as VersionTable[]) {
    out[k] = s.tables[k].map((r) => {
      const row = fromRow(r, KINDS[k])
      // codes are matched case-insensitively by the engine; keep them tidy
      if (k === "age_bands" && typeof row.band_code === "string") row.band_code = row.band_code.trim().toUpperCase()
      if (k === "offers" && typeof row.offer_code === "string") row.offer_code = row.offer_code.trim().toUpperCase()
      if (k === "periods" && typeof row.period_code === "string") row.period_code = row.period_code.trim()
      return row
    })
  }
  return out
}

/** Stable fingerprint for dirty checking (ignores client row keys). */
export function fingerprint(s: EditorState): string {
  return JSON.stringify(payloadOf(s))
}
