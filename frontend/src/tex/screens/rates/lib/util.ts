// Small helpers shared by the Rates & Inventory screens. No money is computed here:
// values are carried as the decimal strings the user typed or the server returned.
import { useEffect, useState } from "react"
import { tex, TexApiError, type TexModule } from "../../../lib/api"
import { intlLocale, getTexLang } from "../../../i18n"
import { editorHash, issueSection, issueTable, parseEditorHash, type SectionId } from "../workspace/sections.ts"
import { newKey } from "./keys"
import type { Issue, IssueRef, Lookups, Row } from "./types"

/** Module name of the workstream-A helper endpoints (kamra/tex/api/ui_rates.py). */
export const UI_RATES = "ui_rates" as TexModule

/** Number/str from the server → decimal string for editing. JSON numbers are
 * already the shortest round-trip representation, so String() is exact enough
 * for display/edit; the server re-parses the string with Decimal. */
export function decStr(v: unknown): string {
  if (v === null || v === undefined || v === "") return ""
  if (typeof v === "number") return Number.isFinite(v) ? String(v) : ""
  return String(v).trim()
}

export function intVal(v: unknown): number {
  const n = typeof v === "number" ? v : parseInt(String(v ?? ""), 10)
  return Number.isFinite(n) ? Math.trunc(n) : 0
}

export function strVal(v: unknown): string {
  return v === null || v === undefined ? "" : String(v)
}

export { newKey }

export type FieldKind = "text" | "int" | "decimal" | "check" | "select" | "date" | "csv" | "weekdays"

/** Normalise a server row for the editor: decimals → strings, ints → numbers,
 * checks → 0/1, everything else → string. Frappe bookkeeping keys are dropped, except the
 * server row name, kept as `_name` (the rule id of a saved row, for issue anchoring); fromRow,
 * payloadOf and the fingerprint ignore it. */
export function toRow(src: Record<string, unknown>, kinds: Record<string, FieldKind>): Row {
  const out: Row = { _key: newKey() }
  if (typeof src.name === "string" && src.name) out._name = src.name
  for (const [k, kind] of Object.entries(kinds)) {
    const v = src[k]
    if (kind === "int") out[k] = intVal(v)
    else if (kind === "check") out[k] = v ? 1 : 0
    else if (kind === "decimal") out[k] = decStr(v)
    else out[k] = strVal(v)
  }
  return out
}

/** Editor row → API row (drops client keys, blank strings become null). */
export function fromRow(row: Row, kinds: Record<string, FieldKind>): Record<string, unknown> {
  const out: Record<string, unknown> = {}
  for (const [k, kind] of Object.entries(kinds)) {
    const v = row[k]
    if (kind === "int") out[k] = intVal(v)
    else if (kind === "check") out[k] = v ? 1 : 0
    else if (kind === "decimal") out[k] = v === "" || v === null || v === undefined ? null : String(v)
    else out[k] = v === "" || v === null || v === undefined ? null : String(v)
  }
  return out
}

export function splitCsv(s: unknown): string[] {
  return strVal(s)
    .replace(/\n/g, ",")
    .split(",")
    .map((x) => x.trim())
    .filter(Boolean)
}

export function joinCsv(items: string[]): string {
  return items.filter(Boolean).join(",")
}

/** Period weekday codes (as parsed by commercial/contracts.parse_weekdays). */
export const WEEKDAY_CODES = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"] as const

/** Localised short weekday name for 0=Mon…6=Sun (2024-01-01 was a Monday). */
export function weekdayName(i: number, style: "short" | "narrow" | "long" = "short"): string {
  const d = new Date(2024, 0, 1 + i, 12)
  return new Intl.DateTimeFormat(intlLocale(getTexLang()), { weekday: style }).format(d)
}

/** ISO date → 0=Mon…6=Sun. */
export function isoWeekday(iso: string): number {
  const d = new Date(`${iso}T12:00:00`)
  return (d.getDay() + 6) % 7
}

/** Age boundary in years (string, e.g. "2.99") → whole months, integer maths only
 * (mirrors pricing/ages.years_to_months: round half up). Display helper. */
export function yearsToMonths(years: string): number | null {
  const s = years.trim()
  if (!/^\d+(\.\d{1,2})?$/.test(s)) return null
  const [ip, fp = ""] = s.split(".")
  const hundredths = parseInt(ip, 10) * 100 + parseInt((fp + "00").slice(0, 2), 10)
  return Math.floor((hundredths * 12 + 50) / 100)
}

/** Decimal string → locale text keeping every significant decimal (min `minDec`),
 * without binary float: "356.994000" → "356,994" (tr), "128.250000" → "128.25".
 * Used for intermediate engine values and FX rates, which must not look rounded. */
export function decText(s: string | number | null | undefined, minDec = 2): string {
  if (s === null || s === undefined || s === "") return "—"
  const str = typeof s === "number" ? String(s) : s.trim()
  if (!/^[-+]?\d+(\.\d+)?$/.test(str)) return "—"
  const neg = str.startsWith("-")
  const [ip, fp = ""] = str.replace(/^[-+]/, "").split(".")
  let frac = fp.replace(/0+$/, "")
  if (frac.length < minDec) frac = (frac + "0".repeat(minDec)).slice(0, minDec)
  const locale = intlLocale(getTexLang())
  const intTxt = new Intl.NumberFormat(locale, { maximumFractionDigits: 0 }).format(BigInt(ip || "0"))
  const sep = new Intl.NumberFormat(locale, { minimumFractionDigits: 1 }).formatToParts(1.1).find((p) => p.type === "decimal")?.value ?? "."
  return `${neg ? "−" : ""}${intTxt}${frac ? sep + frac : ""}`
}

/** Datetime-local input value → "YYYY-MM-DD HH:MM:SS" for Frappe. */
export function toFrappeDatetime(v: string): string | null {
  if (!v) return null
  return v.replace("T", " ") + (v.length === 16 ? ":00" : "")
}

/** Which version-editor section (Pricing, Commercial rules, Offers, Preview & audit) a validation
 * issue belongs to (PRICING_WORKSPACE_UX.md §2): BOARD_* and the child ages are Pricing, the
 * selling windows and the currency Commercial rules. The Advanced rule tables list their own
 * issues by `issueTable`. */
export function issueTab(code: string, ref?: IssueRef): SectionId {
  return issueSection(code, ref)
}

/** Errors and warnings of one section (the section badges). */
export function countIssues(issues: Issue[] | undefined, section: string) {
  let errors = 0
  let warnings = 0
  for (const i of issues ?? []) {
    if (issueSection(i.code, i.ref) !== section) continue
    if (i.level === "ERROR") errors += 1
    else warnings += 1
  }
  return { errors, warnings }
}

/** Errors and warnings listed by one Advanced rule table (the inner tab badges). */
export function countTableIssues(issues: Issue[] | undefined, table: string) {
  let errors = 0
  let warnings = 0
  for (const i of issues ?? []) {
    if (issueTable(i.code, i.ref) !== table) continue
    if (i.level === "ERROR") errors += 1
    else warnings += 1
  }
  return { errors, warnings }
}

// the section hashes and their aliases (#rates, #occupancy, #plans …)
export { editorHash, issueTable, parseEditorHash }

/** Version number from a name like "CTR-00019-V2"; falls back to the name. */
export function versionLabel(name: string | null | undefined, versionNo?: number): string {
  if (versionNo) return `V${versionNo}`
  if (!name) return "—"
  const m = /-V(\d+)$/.exec(name)
  return m ? `V${m[1]}` : name
}

// ─── hotel lookups (room types, rate plans, contracts, policies) ─────────

const lookupCache = new Map<string, Promise<Lookups>>()

export function invalidateLookups(property?: string) {
  if (property) lookupCache.delete(property)
  else lookupCache.clear()
}

export function loadLookups(property: string): Promise<Lookups> {
  let p = lookupCache.get(property)
  if (!p) {
    p = tex<Lookups>(UI_RATES, "lookups", { property })
    p.catch(() => lookupCache.delete(property))
    lookupCache.set(property, p)
  }
  return p
}

export function useLookups(property: string | undefined) {
  const [data, setData] = useState<Lookups>()
  const [error, setError] = useState<TexApiError>()
  useEffect(() => {
    if (!property) return
    let live = true
    setError(undefined)
    loadLookups(property)
      .then((d) => live && setData(d))
      .catch((e: unknown) => live && setError(e instanceof TexApiError ? e : new TexApiError(String(e), 0, "Error")))
    return () => {
      live = false
    }
  }, [property])
  return { data, error }
}

/** Human label for a room type name ("Aurora Beach Resort-STD" → "Standard Sea View"). */
export function roomLabel(lookups: { name: string; room_type_name: string }[] | undefined, name: string | null | undefined) {
  if (!name) return "—"
  return lookups?.find((r) => r.name === name)?.room_type_name ?? name
}
