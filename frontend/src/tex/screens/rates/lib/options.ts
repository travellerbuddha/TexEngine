// Enumerations of the commercial DocTypes (kamra/tex/devtools/doctype_specs.py) with
// their i18n label keys. Labels explain the business meaning; the server owns the maths.
import type { Option } from "../../../ui"

type T = (key: string, params?: Record<string, string | number>) => string

export const BOARDS = ["RO", "BB", "HB", "FB", "AI", "UAI"] as const
export const OPS_ROOM = ["ABSOLUTE", "MULTIPLY", "ADJUST_PERCENT", "PERCENT_OF", "ADD", "SUBTRACT", "INHERIT"] as const
export const OPS_OCC = ["MULTIPLY", "PERCENT_OF", "FIXED", "ABSOLUTE", "ADJUST_PERCENT", "ADD", "SUBTRACT", "INHERIT"] as const
export const OPS_ADJ = ["ADJUST_PERCENT", "MULTIPLY", "ADD", "SUBTRACT"] as const
export const OPS_MARKUP = ["ADJUST_PERCENT", "MULTIPLY", "ADD"] as const
export const OPS_BOARD = ["ADD", "ADJUST_PERCENT", "ABSOLUTE"] as const
export const OCC_TARGETS = ["ADULT", "CHILD", "COMBINATION"] as const
export const PROMO_KINDS = [
  "EARLY_BOOKING",
  "LAST_MINUTE",
  "LONG_STAY",
  "MEMBER",
  "PROMO_CODE",
  "MARKET",
  "ROOM",
  "PACKAGE",
  "BOOKING_DATE",
  "STAY_DATE",
  "ARRIVAL",
  "DEPARTURE",
  "SPECIAL_OFFER",
] as const
export const PROMO_VALUE = ["PERCENT", "FIXED_STAY", "FIXED_NIGHT", "MULTIPLIER", "FREE_NIGHTS", "VALUE_ADDED"] as const
export const STAY_MATCH = ["ANY_NIGHT", "ALL_NIGHTS", "ARRIVAL", "DEPARTURE"] as const
export const PROMO_STAGE = ["SELL", "COST"] as const
export const APPLIES_TO = ["ACCOMMODATION", "EXTRAS", "TOTAL"] as const
/** What a promotion can apply to (O-1, ADR-068): the whole booking or its extras take a percentage
 *  or a fixed amount for the stay, at the SELL stage; anything else lowers the accommodation only
 *  (TEX Promotion's validate refuses the rest). */
export function promoAppliesTo(d: { stage?: unknown; value_type?: unknown }): readonly string[] {
  const basket = d.stage !== "COST" && (d.value_type === "PERCENT" || d.value_type === "FIXED_STAY")
  return basket ? APPLIES_TO : ["ACCOMMODATION"]
}
export const TRIGGERS = ["Automatic", "Code"] as const
export const COMBINE = ["REPLACE", "STACK"] as const
export const FX_MODES = ["PROVIDER", "PROVIDER_PERCENT", "PROVIDER_FIXED", "MANUAL"] as const
export const FX_PROVIDERS = ["TCMB", "ECB"] as const
export const RATE_TYPES = ["FOREX_SELLING", "FOREX_BUYING", "BANKNOTE_SELLING", "BANKNOTE_BUYING", "REFERENCE"] as const
export const PENALTY = ["PERCENT", "NIGHTS", "FIXED"] as const
export const DEPOSIT = ["NONE", "PERCENT", "NIGHTS", "FULL", "FIXED"] as const
export const EXTRA_MODES = [
  "RESERVATION",
  "ROOM",
  "STAY",
  "PERSON",
  "ADULT",
  "CHILD",
  "INFANT",
  "NIGHT",
  "PERSON_NIGHT",
  "SERVICE_DATE",
  "UNIT",
  "USAGE",
] as const
export const EXTRA_CATEGORIES = ["Transfer", "Dining", "Spa", "Room", "Package", "Celebration", "Excursion", "Service", "Other"] as const
export const CHILD_PRICING = ["SAME_AS_ADULT", "CUSTOM"] as const
export const INFANT_PRICING = ["SAME_AS_CHILD", "FREE", "CUSTOM"] as const
export const TAX_CATEGORIES = ["SERVICE", "FOOD", "TRANSFER", "ACCOMMODATION"] as const
export const TAX_KINDS = ["PERCENT", "PER_PERSON_NIGHT", "PER_ROOM_NIGHT"] as const
export const TAX_APPLIES = ["ACCOMMODATION", "EXTRA:*", "EXTRA:SERVICE", "EXTRA:FOOD", "EXTRA:TRANSFER", "EXTRA:ACCOMMODATION"] as const
export const CHILD_ORDERING = ["OLDEST_FIRST", "YOUNGEST_FIRST", "AS_ENTERED"] as const
export const AGE_BASIS = ["ARRIVAL", "BOOKING_DATE"] as const
export const STACKING = ["SEQUENTIAL", "ADDITIVE"] as const
export const EXTRA_UNIT = ["PER_PERSON_SHARE", "ROOM_PRICE"] as const
export const CONTRACT_STATUS = ["Draft", "Active", "Suspended", "Archived"] as const
export const BASIS = ["PERSON", "ROOM"] as const

/** Options for an enum, labelled with `rates.<group>.<value>`. */
export function enumOptions(t: T, group: string, values: readonly string[]): Option[] {
  return values.map((v) => ({ value: v, label: t(`rates.${group}.${v}`) }))
}

export function enumLabel(t: T, group: string, value: string | null | undefined): string {
  if (!value) return "—"
  const key = `rates.${group}.${value}`
  const s = t(key)
  return s === key ? value : s
}

/** Ops that derive a room price from another room's price (need a base room). */
export const DERIVED_OPS = new Set(["MULTIPLY", "ADJUST_PERCENT", "PERCENT_OF", "ADD", "SUBTRACT"])

/** Ops whose value is a percentage (suffix "%"). */
export const PERCENT_OPS = new Set(["ADJUST_PERCENT", "PERCENT_OF"])

/** Compact display of an op + value, e.g. "× 1.35", "+10 %", "= 95". */
export function opText(op: string | null | undefined, value: string | number | null | undefined): string {
  const v = value === null || value === undefined || value === "" ? "0" : String(value)
  switch (op) {
    case "ABSOLUTE":
    case "FIXED":
      return `= ${v}`
    case "MULTIPLY":
      return `× ${v}`
    case "PERCENT_OF":
      return `${v} %`
    case "ADJUST_PERCENT":
      return `${v.startsWith("-") ? "−" + v.slice(1) : "+" + v} %`
    case "ADD":
      return `+ ${v}`
    case "SUBTRACT":
      return `− ${v}`
    case "INHERIT":
      return "↑"
    default:
      return v
  }
}
