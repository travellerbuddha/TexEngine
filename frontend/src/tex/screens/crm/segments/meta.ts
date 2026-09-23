// Vocabulary of the segment screens: how facts are grouped and explained, and what the
// shared presets mean (kamra/tex/crm/segments.py FIELDS and SYSTEM_SEGMENTS, ADR-036).
import type { Condition, FieldKind, SegmentRules } from "../types"

type T = (k: string, p?: Record<string, string | number>) => string

/** Facts grouped for the field picker; a fact the server adds later lands in "other". */
export const FIELD_GROUPS: { id: "stays" | "behaviour" | "profile" | "loyalty"; fields: string[] }[] = [
  {
    id: "stays",
    fields: ["stays", "lifetime_value", "lifetime_currency", "last_stay_days_ago", "has_upcoming_stay", "has_children"],
  },
  { id: "behaviour", fields: ["last_lead_days", "cancellations", "last_cancel_days_ago", "abandoned_days_ago"] },
  {
    id: "profile",
    fields: [
      "country",
      "nationality",
      "market",
      "language",
      "days_to_birthday",
      "vip",
      "tags",
      "blacklisted",
      "consent_email",
      "consent_sms",
      "consent_whatsapp",
    ],
  },
  { id: "loyalty", fields: ["loyalty_points"] },
]

/** Facts whose meaning is not obvious from the label get a hint under the condition. */
const HINTED = new Set([
  "stays",
  "lifetime_value",
  "last_stay_days_ago",
  "has_upcoming_stay",
  "has_children",
  "last_lead_days",
  "cancellations",
  "last_cancel_days_ago",
  "abandoned_days_ago",
  "days_to_birthday",
  "loyalty_points",
])

export const fieldKey = (f: string) => `crm.seg.field.${f}`
export const opKey = (o: string) => `crm.seg.op.${o}`

/** Translated label of a fact; an unknown fact shows its code. */
export function fieldLabel(t: T, f: string) {
  const k = fieldKey(f)
  const v = t(k)
  return v === k ? f : v
}

export function fieldHint(t: T, f: string): string | null {
  return HINTED.has(f) ? t(`crm.seg.hint.${f}`) : null
}

/** Field picker groups (translated, sorted by label inside each group). */
export function fieldGroups(t: T, fields: Record<string, FieldKind>) {
  const known = new Set(FIELD_GROUPS.flatMap((g) => g.fields))
  const byLabel = (a: string, b: string) => fieldLabel(t, a).localeCompare(fieldLabel(t, b))
  const groups = FIELD_GROUPS.map((g) => ({
    label: t(`crm.seg.group.${g.id}`),
    options: g.fields.filter((f) => f in fields).map((f) => ({ value: f, label: fieldLabel(t, f) })),
  }))
  const other = Object.keys(fields)
    .filter((f) => !known.has(f))
    .sort(byLabel)
  if (other.length) groups.push({ label: t("crm.seg.group.other"), options: other.map((f) => ({ value: f, label: fieldLabel(t, f) })) })
  return groups
}

/** The presets seeded by the server, by system_key. */
const PRESETS = new Set(["REPEAT", "VIP", "EMAIL_OPT_IN", "LAPSED", "FAMILY", "LAST_MINUTE", "CANCELLED", "ABANDONED", "BIRTHDAY"])

const presetKey = (key: string) => `crm.seg.preset.${key.toLowerCase()}`

/** A segment's display name: presets are translated, own segments keep their name. */
export function segmentLabel(t: T, s: { segment_name: string; system_key?: string | null }) {
  return s.system_key && PRESETS.has(s.system_key) ? t(presetKey(s.system_key)) : s.segment_name
}

/** What a preset means, in words (a custom segment: its own description). */
export function segmentMeaning(t: T, s: { description?: string | null; system_key?: string | null }): string | null {
  if (s.system_key && PRESETS.has(s.system_key)) return t(`${presetKey(s.system_key)}_hint`)
  return s.description || null
}

/** A money condition without a currency never matches (the server compares money only in one currency). */
export function lacksCurrency(c: Condition, kind: FieldKind | undefined) {
  return kind === "money" && !String(c.currency ?? "").trim()
}

export function rulesLackCurrency(rules: SegmentRules | null | undefined, fields: Record<string, FieldKind>) {
  return Boolean(rules?.conditions?.some((c) => lacksCurrency(c, fields[c.field])))
}
