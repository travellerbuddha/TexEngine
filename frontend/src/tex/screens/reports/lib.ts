// Reports helpers: date presets, group labels and client-side CSV export.
// Amounts stay the server's decimal strings; nothing here recomputes money.
import { addDays, date, isoDay, nightsBetween } from "../../lib/format"
import type { Bootstrap } from "../../lib/session"

export const MAX_RANGE_DAYS = 800

export type RangePreset =
  | "this_month"
  | "last_month"
  | "next_month"
  | "next_30"
  | "next_90"
  | "last_30"
  | "ytd"
  | "this_year"
  | "last_year"
  | "custom"

/** The dates of a preset around `today`, the site's calendar day ("YYYY-MM-DD", lib/siteDay):
 * "this month" is the hotel's month, whatever the browser's clock says (G-91). */
export function presetRange(p: Exclude<RangePreset, "custom">, today: string): [string, string] {
  const y = Number(today.slice(0, 4))
  const m = Number(today.slice(5, 7)) - 1
  const t = today
  switch (p) {
    case "this_month":
      return [isoDay(new Date(y, m, 1)), isoDay(new Date(y, m + 1, 0))]
    case "last_month":
      return [isoDay(new Date(y, m - 1, 1)), isoDay(new Date(y, m, 0))]
    case "next_month":
      return [isoDay(new Date(y, m + 1, 1)), isoDay(new Date(y, m + 2, 0))]
    case "next_30":
      return [t, addDays(t, 29)]
    case "next_90":
      return [t, addDays(t, 89)]
    case "last_30":
      return [addDays(t, -29), t]
    case "ytd":
      return [isoDay(new Date(y, 0, 1)), t]
    case "this_year":
      return [isoDay(new Date(y, 0, 1)), isoDay(new Date(y, 11, 31))]
    case "last_year":
      return [isoDay(new Date(y - 1, 0, 1)), isoDay(new Date(y - 1, 11, 31))]
  }
}

/** i18n key of the validation problem with a range, or null when it is fine. */
export function rangeProblem(from: string, to: string): string | null {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(from) || !/^\d{4}-\d{2}-\d{2}$/.test(to)) return "reports.err.dates"
  if (to < from) return "reports.err.order"
  if (nightsBetween(from, to) > MAX_RANGE_DAYS) return "reports.err.too_long"
  return null
}

/** The report views (kamra/tex/reports/service.py VIEWS). "margin" is contract vs selling. */
export const VIEWS = ["production", "margin", "promotion", "extras", "cancellation", "payment", "conversion"] as const
export type ReportView = (typeof VIEWS)[number]

/** Groupings of stays (production, contract vs selling, cancellations). */
export const DIMENSIONS = [
  "channel",
  "market",
  "room_type",
  "board",
  "rate_plan",
  "contract",
  "agency",
  "country",
  "status",
  "hotel",
  "group",
  "month",
  "day",
] as const
export type Dimension = (typeof DIMENSIONS)[number]
/** Groupings of bookings (payments). */
export const PAYMENT_DIMENSIONS = ["payment_status", "payment_method", "status", "channel", "market", "hotel", "group", "month", "day"] as const
/** Groupings of booking-engine sessions (conversion). */
export const CONVERSION_DIMENSIONS = ["day", "month", "site", "market", "hotel", "group"] as const
export type AnyDimension = Dimension | (typeof PAYMENT_DIMENSIONS)[number] | (typeof CONVERSION_DIMENSIONS)[number]

export const TIME_DIMENSIONS: AnyDimension[] = ["month", "day"]

/** The groupings a view offers (none: its rows are the promotions / extras themselves). */
export function viewDimensions(view: ReportView): readonly AnyDimension[] {
  if (view === "payment") return PAYMENT_DIMENSIONS
  if (view === "conversion") return CONVERSION_DIMENSIONS
  if (view === "promotion" || view === "extras") return []
  return DIMENSIONS
}

export const DEFAULT_GROUP: Record<ReportView, AnyDimension | null> = {
  production: "channel",
  margin: "channel",
  cancellation: "channel",
  payment: "payment_status",
  conversion: "day",
  promotion: null,
  extras: null,
}

/** The row the server folds the tail of a very long result into. */
export const OTHER_KEY = "__other__"

type T = (key: string, params?: Record<string, string | number>) => string

function monthLabel(key: string, locale: string) {
  const m = /^(\d{4})-(\d{2})$/.exec(key)
  if (!m) return key
  return new Intl.DateTimeFormat(locale, { month: "short", year: "numeric" }).format(new Date(Number(m[1]), Number(m[2]) - 1, 1))
}

function countryLabel(code: string, locale: string) {
  if (!/^[A-Za-z]{2}$/.test(code)) return code
  try {
    return new Intl.DisplayNames([locale], { type: "region" }).of(code.toUpperCase()) ?? code
  } catch {
    return code
  }
}

const slug = (s: string) => s.toLowerCase().replace(/\s+/g, "_")

/** A translation, or `fallback` when the catalog has none. */
function tOr(t: T, key: string, fallback: string) {
  const l = t(key)
  return l === key ? fallback : l
}

/** Human label for a report row key (the key itself is kept in CSV). `labels`: the names the
 * server sent for hotels, groups, room types, rate plans, contracts, agencies and sites. */
export function groupLabel(
  dim: AnyDimension,
  key: string,
  boot: Bootstrap,
  t: T,
  locale: string,
  labels?: Record<string, string>,
  view?: ReportView,
): string {
  if (key === OTHER_KEY) return t("reports.other")
  if (!key || key === "—") return t("reports.not_set")
  if (labels?.[key]) return labels[key]
  switch (dim) {
    case "channel":
      return boot.channels.find((c) => c.name === key)?.channel_name ?? key
    case "market":
      return boot.markets.find((m) => m.name === key)?.market_name ?? key
    case "board":
      return tOr(t, `reports.board.${key}`, key)
    case "status":
      return view === "payment" ? tOr(t, `payments.booking_status.${slug(key)}`, key) : tOr(t, `reports.status.${slug(key)}`, key)
    case "payment_status":
      return tOr(t, `payments.payment_status.${slug(key)}`, key)
    case "payment_method":
      return tOr(t, `payments.method.${slug(key)}`, key)
    case "month":
      return monthLabel(key, locale)
    case "day":
      return date(key)
    case "country":
      return countryLabel(key, locale)
    default:
      return key
  }
}

// ─── CSV ───────────────────────────────────────────────────────────────

function csvCell(v: unknown, text: boolean): string {
  let s = v === null || v === undefined ? "" : String(v)
  // spreadsheet formula injection: neutralise text cells that start like a formula
  if (text && /^[=+\-@\t\r]/.test(s)) s = `'${s}`
  return /[",\n\r;]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s
}

export interface CsvColumn<R> {
  header: string
  value: (row: R) => unknown
  /** Free-text column (formula-injection guard applies). */
  text?: boolean
}

export function toCsv<R>(columns: CsvColumn<R>[], rows: R[]): string {
  const lines = [columns.map((c) => csvCell(c.header, true)).join(",")]
  for (const r of rows) lines.push(columns.map((c) => csvCell(c.value(r), Boolean(c.text))).join(","))
  return lines.join("\r\n")
}

export function downloadCsv(filename: string, csv: string) {
  // BOM so spreadsheet apps read UTF-8 (Turkish, Cyrillic) correctly
  const blob = new Blob(["﻿", csv], { type: "text/csv;charset=utf-8" })
  const url = URL.createObjectURL(blob)
  const a = document.createElement("a")
  a.href = url
  a.download = filename
  document.body.appendChild(a)
  a.click()
  a.remove()
  window.setTimeout(() => URL.revokeObjectURL(url), 1000)
}

export function slugify(s: string) {
  return s
    .normalize("NFKD")
    .replace(/[̀-ͯ]/g, "")
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-|-$/g, "")
}

/** Sort key for a server decimal string (display ordering only). */
export function decimalSort(s: string | null | undefined): number | null {
  if (s === null || s === undefined || s === "") return null
  const n = Number(s)
  return Number.isFinite(n) ? n : null
}
