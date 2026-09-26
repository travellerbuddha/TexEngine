// Field kinds and new-row defaults of the contract-version child tables
// (TEX Contract Room, TEX Price Period, TEX Period Rate, TEX Child Age Band,
// TEX Occupancy Rule, TEX Board Rule, TEX Contract Rate Plan, TEX Contract Offer).
import { keepKeys, overSaved } from "../../../lib/edits"
import { ROW_DEFAULTS } from "../workspace/rows"
import type { Row, VersionDoc, VersionSetting, VersionTable } from "./types"
import { fromRow, joinCsv, splitCsv, toRow, type FieldKind } from "./util"

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

/** New-row defaults per table (kept in the pure workspace module so its tests can use them). */
export const NEW_ROW: Record<VersionTable, () => Omit<Row, "_key">> = ROW_DEFAULTS

export type Tables = Record<VersionTable, Row[]>
export type Settings = Record<VersionSetting, string | number>

/** A draft's own selling terms as edited (G-50); absent when they are not editable here. */
export interface SellingForm {
  sale_from: string
  sale_to: string
  stay_from: string
  stay_to: string
  priority: number
  sell_currency: string
  channels: string
}

export interface EditorState {
  settings: Settings
  tables: Tables
  selling?: SellingForm
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
    selling:
      doc.selling && doc.selling_editable && doc.editable
        ? {
            sale_from: doc.selling.sale_from ?? "",
            sale_to: doc.selling.sale_to ?? "",
            stay_from: doc.selling.stay_from ?? "",
            stay_to: doc.selling.stay_to ?? "",
            priority: doc.selling.priority ?? 0,
            sell_currency: doc.selling.sell_currency ?? "",
            channels: joinCsv(doc.selling.channels ?? []),
          }
        : undefined,
  }
}

/** Payload for contracts.save_version (settings + every child table). */
export function payloadOf(s: EditorState): Record<string, unknown> {
  const out: Record<string, unknown> = { ...s.settings }
  if (out.change_note === "") out.change_note = null
  if (s.selling) {
    const g = s.selling
    out.selling = {
      sale_from: g.sale_from || null,
      sale_to: g.sale_to || null,
      stay_from: g.stay_from || null,
      stay_to: g.stay_to || null,
      priority: g.priority,
      sell_currency: g.sell_currency || null,
      channels: splitCsv(g.channels),
    }
  }
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

/** The payload for the read-only draft overlay (`price_matrix` / `validate_version` / `preview_price`
 * with `data`, §3.14): payloadOf plus each row's client `_key`, which the server turns into the
 * rule ids it reports ("~" + _key), so results map back to rows. save_version never gets it (it
 * would drop `_*` fields anyway), and the fingerprint stays payloadOf's. */
export function overlayPayloadOf(s: EditorState): Record<string, unknown> {
  const out = payloadOf(s)
  for (const k of Object.keys(KINDS) as VersionTable[]) {
    const rows = out[k] as Record<string, unknown>[]
    out[k] = rows.map((row, i) => ({ ...row, _key: s.tables[k][i]._key }))
  }
  return out
}

/** The editor state once a save has answered (§3.16): the saved copy, with the client row keys of
 * what was `sent` (keepKeys) and, on top, whatever the user changed while the save was in flight
 * (a setting, a table, the selling terms; overSaved). Replacing the editor with the saved copy
 * would drop those edits, and a later save would send them away too. */
export function settleState(saved: EditorState, sent: EditorState, cur: EditorState | undefined): EditorState {
  const keyed: EditorState = { ...saved, tables: keepKeys(saved.tables, sent.tables) }
  if (!cur) return keyed
  return {
    ...keyed,
    settings: overSaved(keyed.settings, sent.settings, cur.settings),
    tables: overSaved(keyed.tables, sent.tables, cur.tables),
    ...(JSON.stringify(cur.selling) !== JSON.stringify(sent.selling) ? { selling: cur.selling } : {}),
  }
}
