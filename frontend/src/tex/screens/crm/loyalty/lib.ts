// Loyalty program editor helpers. Nothing here computes points or money: decimals stay
// strings and are only compared exactly (scaled BigInt) to mirror the server's checks
// (TEXLoyaltyProgram.validate); the server validates again.
import { intlLocale } from "../../../i18n"
import { isInteger } from "../lib"
import type {
  BlackoutPurpose,
  EarnBasis,
  ProgramDetail,
  ProgramLookups,
  ProgramRow,
} from "../types"

type T = (k: string, p?: Record<string, string | number>) => string

const DEC = /^\d+(\.\d+)?$/

/** Non-negative decimal string with at most `max` decimals. */
export function isPlainDecimal(s: string, max = 6) {
  const v = s.trim()
  return DEC.test(v) && (v.split(".")[1]?.length ?? 0) <= max
}

function scaled(s: string, scale: number): bigint {
  const v = s.trim()
  const neg = v.startsWith("-")
  const [i = "0", f = ""] = v.replace(/^[-+]/, "").split(".")
  const n = BigInt((i || "0") + (f + "0".repeat(scale)).slice(0, scale))
  return neg ? -n : n
}

/** Exact comparison of two decimal strings (-1, 0, 1). */
export function cmpDecimal(a: string, b: string): number {
  const scale = Math.max(a.split(".")[1]?.length ?? 0, b.split(".")[1]?.length ?? 0)
  const x = scaled(a, scale)
  const y = scaled(b, scale)
  return x < y ? -1 : x > y ? 1 : 0
}

/** "0.005000" → "0.005" in the user's locale, keeping every significant decimal (display only). */
export function decimalText(s: string | null | undefined, locale = intlLocale()) {
  const v = String(s ?? "").trim()
  if (!/^-?\d+(\.\d+)?$/.test(v)) return "—"
  const neg = v.startsWith("-")
  const [i, f = ""] = v.replace(/^-/, "").split(".")
  const frac = f.replace(/0+$/, "")
  const int = new Intl.NumberFormat(locale, { maximumFractionDigits: 0 }).format(BigInt(i || "0"))
  const sep = new Intl.NumberFormat(locale, { minimumFractionDigits: 1 }).formatToParts(1.1).find((p) => p.type === "decimal")?.value ?? "."
  return `${neg ? "-" : ""}${int}${frac ? sep + frac : ""}`
}

export const basisKey = (b: string) => `crm.program.basis.${b.toLowerCase()}`
export const purposeKey = (p: string) => `crm.program.purpose.${p.toLowerCase()}`

/** A hotel's display name (from the session), else its code. */
export function hotelName(boot: { properties: { name: string; property_name: string }[] }, name: string | null | undefined) {
  if (!name) return ""
  return boot.properties.find((p) => p.name === name)?.property_name || name
}

/** "Hotel Aurora" or "Group: Aurora Hotels". */
export function scopeText(
  t: T,
  boot: { properties: { name: string; property_name: string }[] },
  p: Pick<ProgramRow, "property" | "hotel_group">,
) {
  if (p.property) return hotelName(boot, p.property)
  if (p.hotel_group) return t("crm.programs.group", { group: p.hotel_group })
  return "—"
}

// ─── the editable draft ──────────────────────────────────────────────────

let seq = 0
const key = () => `r${++seq}`

export interface RuleDraft {
  key: string
  basis: EarnBasis
  rate: string
  room_type: string
  extra: string
  date_from: string
  date_to: string
}

export interface TierDraft {
  key: string
  tier_name: string
  min_points: string
  earn_multiplier: string
}

export interface BlackoutDraft {
  key: string
  date_from: string
  date_to: string
  note: string
  applies_to: BlackoutPurpose
}

export interface ProgramDraft {
  program_name: string
  scopeType: "hotel" | "group"
  property: string
  hotel_group: string
  enabled: boolean
  currency: string
  point_value: string
  min_redeem_points: string
  max_redeem_percent: string
  pending_days: string
  expiry_months: string
  earn_rules: RuleDraft[]
  tiers: TierDraft[]
  blackouts: BlackoutDraft[]
}

const intText = (n: number | null | undefined) => (n === null || n === undefined ? "0" : String(n))

export function newRule(basis: EarnBasis = "NIGHTS"): RuleDraft {
  return { key: key(), basis, rate: "", room_type: "", extra: "", date_from: "", date_to: "" }
}

export function newTier(): TierDraft {
  return { key: key(), tier_name: "", min_points: "", earn_multiplier: "1" }
}

export function newBlackout(): BlackoutDraft {
  return { key: key(), date_from: "", date_to: "", note: "", applies_to: "Redemption" }
}

export function draftFromProgram(p: ProgramDetail): ProgramDraft {
  return {
    program_name: p.program_name ?? "",
    scopeType: p.property ? "hotel" : "group",
    property: p.property ?? "",
    hotel_group: p.hotel_group ?? "",
    enabled: Boolean(p.enabled),
    currency: p.currency ?? "",
    point_value: p.point_value ?? "0",
    min_redeem_points: intText(p.min_redeem_points),
    max_redeem_percent: p.max_redeem_percent ?? "0",
    pending_days: intText(p.pending_days),
    expiry_months: intText(p.expiry_months),
    earn_rules: (p.earn_rules ?? []).map((r) => ({
      key: key(),
      basis: r.basis,
      rate: r.rate ?? "",
      room_type: r.room_type ?? "",
      extra: r.extra ?? "",
      date_from: r.date_from ?? "",
      date_to: r.date_to ?? "",
    })),
    tiers: (p.tiers ?? []).map((x) => ({
      key: key(),
      tier_name: x.tier_name ?? "",
      min_points: intText(x.min_points),
      earn_multiplier: x.earn_multiplier ?? "1",
    })),
    blackouts: (p.blackouts ?? []).map((b) => ({
      key: key(),
      date_from: b.date_from ?? "",
      date_to: b.date_to ?? "",
      note: b.note ?? "",
      applies_to: b.applies_to ?? "Both",
    })),
  }
}

/** A new program: the doctype's defaults (pending 1 day, expiry 24 months, 100 % redeemable).
 * `hotel` is the session hotel, preferred when the user may create a program there. The
 * currency is the chosen hotel's (from the session's hotel list), never the session
 * hotel's when another one is chosen; for a group scope, the session hotel's only when it
 * belongs to that group. */
export function blankDraft(
  scopes: { hotels: string[]; groups: string[] },
  hotel: string | undefined,
  properties: { name: string; currency?: string; hotel_group?: string }[],
): ProgramDraft {
  const property = hotel && scopes.hotels.includes(hotel) ? hotel : (scopes.hotels[0] ?? "")
  const scopeType = scopes.hotels.length || !scopes.groups.length ? "hotel" : "group"
  const hotel_group = scopes.groups[0] ?? ""
  const from =
    scopeType === "hotel"
      ? properties.find((x) => x.name === property)
      : properties.find((x) => x.name === hotel && Boolean(hotel_group) && x.hotel_group === hotel_group)
  return {
    program_name: "",
    scopeType,
    property,
    hotel_group,
    enabled: true,
    currency: from?.currency ?? "",
    point_value: "0",
    min_redeem_points: "0",
    max_redeem_percent: "100",
    pending_days: "1",
    expiry_months: "24",
    earn_rules: [newRule("MONEY")],
    tiers: [],
    blackouts: [],
  }
}

/** What save_program receives (the key/React ids stay here). `enabled` only for a new
 * program: an existing one is enabled or disabled with its own audited action. */
export function payloadOf(d: ProgramDraft, isNew: boolean): Record<string, unknown> {
  const int = (s: string) => (isInteger(s) ? Number(s.trim()) : 0)
  return {
    program_name: d.program_name.trim(),
    property: d.scopeType === "hotel" ? d.property || null : null,
    hotel_group: d.scopeType === "group" ? d.hotel_group || null : null,
    ...(isNew ? { enabled: d.enabled ? 1 : 0 } : {}),
    currency: d.currency || null,
    point_value: d.point_value.trim() || "0",
    min_redeem_points: int(d.min_redeem_points),
    max_redeem_percent: d.max_redeem_percent.trim() || "0",
    pending_days: int(d.pending_days),
    expiry_months: int(d.expiry_months),
    earn_rules: d.earn_rules.map((r) => ({
      basis: r.basis,
      rate: r.rate.trim(),
      room_type: r.basis === "ROOM" ? r.room_type || null : null,
      extra: r.basis === "EXTRA" ? r.extra || null : null,
      date_from: r.date_from || null,
      date_to: r.date_to || null,
    })),
    tiers: d.tiers.map((x) => ({ tier_name: x.tier_name.trim(), min_points: int(x.min_points), earn_multiplier: x.earn_multiplier.trim() })),
    blackouts: d.blackouts.map((b) => ({ date_from: b.date_from, date_to: b.date_to, note: b.note.trim() || null, applies_to: b.applies_to })),
  }
}

/** Room types and extras the saved program's earn rules already reference. */
export interface SavedRefs {
  room_types: ReadonlySet<string>
  extras: ReadonlySet<string>
}

export function savedRefs(rules: { room_type: string | null; extra: string | null }[]): SavedRefs {
  return {
    room_types: new Set(rules.map((r) => r.room_type).filter((v): v is string => Boolean(v))),
    extras: new Set(rules.map((r) => r.extra).filter((v): v is string => Boolean(v))),
  }
}

/** Field errors keyed like "point_value", "rule.<key>.rate", "tier.<key>.name". Mirrors
 * the program controller; the server stays the authority. `saved` (only while the scope is
 * unchanged): what the saved program already references stays valid even when the lookups
 * omit it (a superseded extra revision, a room of a now-disabled group hotel). */
export function validateDraft(t: T, d: ProgramDraft, lookups: ProgramLookups | undefined, saved?: SavedRefs): Record<string, string> {
  const e: Record<string, string> = {}
  const nonNegInt = (k: keyof ProgramDraft) => {
    const v = String(d[k] ?? "").trim()
    if (!isInteger(v)) e[k] = t("crm.program.err.int")
  }
  if (!d.program_name.trim()) e.program_name = t("crm.edit.required")
  if (d.scopeType === "hotel" && !d.property) e.scope = t("crm.program.pick_hotel")
  if (d.scopeType === "group" && !d.hotel_group) e.scope = t("crm.program.pick_group")
  if (!isPlainDecimal(d.point_value)) e.point_value = t("crm.program.err.decimal")
  nonNegInt("min_redeem_points")
  nonNegInt("pending_days")
  nonNegInt("expiry_months")
  if (!isPlainDecimal(d.max_redeem_percent, 2) || cmpDecimal(d.max_redeem_percent, "100") > 0)
    e.max_redeem_percent = t("crm.program.err.percent")
  const worthMoney = isPlainDecimal(d.point_value) && cmpDecimal(d.point_value, "0") > 0
  if ((worthMoney || d.earn_rules.some((r) => r.basis === "MONEY")) && !d.currency) e.currency = t("crm.program.err.currency")
  const rooms = new Set((lookups?.room_types ?? []).map((r) => r.name))
  const extras = new Set((lookups?.extras ?? []).map((x) => x.name))
  for (const r of d.earn_rules) {
    if (!isPlainDecimal(r.rate) || cmpDecimal(r.rate, "0") <= 0) e[`rule.${r.key}.rate`] = t("crm.program.err.rate")
    if (r.date_from && r.date_to && r.date_from > r.date_to) e[`rule.${r.key}.window`] = t("crm.program.err.window")
    if (r.basis === "ROOM" && (!r.room_type || (lookups && !rooms.has(r.room_type) && !saved?.room_types.has(r.room_type))))
      e[`rule.${r.key}.room_type`] = t("crm.program.err.room_type")
    if (r.basis === "EXTRA" && (!r.extra || (lookups && !extras.has(r.extra) && !saved?.extras.has(r.extra))))
      e[`rule.${r.key}.extra`] = t("crm.program.err.extra")
  }
  const names = new Set<string>()
  const floors = new Set<string>()
  for (const x of d.tiers) {
    const n = x.tier_name.trim().toLowerCase()
    if (!n) e[`tier.${x.key}.name`] = t("crm.edit.required")
    else if (names.has(n)) e[`tier.${x.key}.name`] = t("crm.program.err.tier_dup")
    names.add(n)
    const f = x.min_points.trim()
    if (!isInteger(f)) e[`tier.${x.key}.min_points`] = t("crm.program.err.int")
    else if (floors.has(String(Number(f)))) e[`tier.${x.key}.min_points`] = t("crm.program.err.tier_floor")
    if (isInteger(f)) floors.add(String(Number(f)))
    if (!isPlainDecimal(x.earn_multiplier) || cmpDecimal(x.earn_multiplier, "0") <= 0) e[`tier.${x.key}.multiplier`] = t("crm.program.err.multiplier")
  }
  for (const b of d.blackouts) {
    if (!b.date_from || !b.date_to) e[`blackout.${b.key}.dates`] = t("crm.program.err.dates")
    else if (b.date_from > b.date_to) e[`blackout.${b.key}.dates`] = t("crm.program.err.window")
  }
  return e
}
