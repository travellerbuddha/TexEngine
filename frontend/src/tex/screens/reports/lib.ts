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

export function presetRange(p: Exclude<RangePreset, "custom">, today = new Date()): [string, string] {
  const y = today.getFullYear()
  const m = today.getMonth()
  const t = isoDay(today)
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
  "month",
  "day",
] as const
export type Dimension = (typeof DIMENSIONS)[number]

export const TIME_DIMENSIONS: Dimension[] = ["month", "day"]

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

/** Human label for a production row key (the key itself is kept in CSV). */
export function groupLabel(dim: Dimension, key: string, boot: Bootstrap, t: T, locale: string): string {
  if (!key || key === "—") return t("reports.not_set")
  switch (dim) {
    case "channel":
      return boot.channels.find((c) => c.name === key)?.channel_name ?? key
    case "market":
      return boot.markets.find((m) => m.name === key)?.market_name ?? key
    case "board": {
      const l = t(`reports.board.${key}`)
      return l === `reports.board.${key}` ? key : l
    }
    case "status": {
      const k = `reports.status.${key.toLowerCase().replace(/\s+/g, "_")}`
      const l = t(k)
      return l === k ? key : l
    }
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
