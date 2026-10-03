// Display formatting only. Amounts arrive as decimal strings from the server and
// are formatted without passing through binary floating point.
import { intlLocale, getTexLang } from "../i18n"

const nfCache = new Map<string, Intl.NumberFormat>()

function nf(locale: string, opts: Intl.NumberFormatOptions) {
  const key = locale + JSON.stringify(opts)
  let f = nfCache.get(key)
  if (!f) {
    f = new Intl.NumberFormat(locale, opts)
    nfCache.set(key, f)
  }
  return f
}

/** Split "1234.5" into grouped integer + fixed decimals using Intl for the
 * integer part (BigInt keeps it exact) and the string for the fraction. */
function exactParts(amount: string, digits: number, locale: string) {
  const neg = amount.trim().startsWith("-")
  const clean = amount.trim().replace(/^[-+]/, "")
  const [ip = "0", fp = ""] = clean.split(".")
  const frac = (fp + "0".repeat(digits)).slice(0, digits)
  const intFmt = nf(locale, { maximumFractionDigits: 0 }).format(BigInt(ip || "0"))
  const sep = nf(locale, { minimumFractionDigits: 1 }).formatToParts(1.1).find((p) => p.type === "decimal")?.value ?? "."
  return { neg, text: digits ? `${intFmt}${sep}${frac}` : intFmt }
}

// the server's minor units (kamra/tex/money.py MINOR_UNITS; anything missing: 2), in which it keeps and sends
// every amount; tests/unit/minor-units.test.ts keeps them the same
const MINOR: Record<string, number> = { JPY: 0, KRW: 0, VND: 0, HUF: 2, KWD: 3, BHD: 3, JOD: 3, OMR: 3, TND: 3 }

export function minorUnits(ccy: string) {
  return MINOR[ccy?.toUpperCase()] ?? 2
}

/** "842.5", "EUR" → "€842.50" (locale aware). Invalid input → "—". */
export function money(amount: string | number | null | undefined, ccy?: string | null, locale = intlLocale(getTexLang())) {
  if (amount === null || amount === undefined || amount === "") return "—"
  const s = typeof amount === "number" ? String(amount) : amount
  if (!/^[-+]?\d+(\.\d+)?$/.test(s.trim())) return "—"
  const code = (ccy || "").toUpperCase()
  const digits = code ? minorUnits(code) : 2
  const { neg, text } = exactParts(s, digits, locale)
  if (!code) return (neg ? "-" : "") + text
  // take the currency symbol and its position from Intl, value from exactParts
  const parts = nf(locale, { style: "currency", currency: code }).formatToParts(0)
  const out: string[] = []
  let placed = false
  for (const p of parts) {
    if (p.type === "currency" || p.type === "literal") out.push(p.value)
    else if (!placed && (p.type === "integer" || p.type === "decimal" || p.type === "fraction" || p.type === "group")) {
      out.push(text)
      placed = true
    }
  }
  return (neg ? "-" : "") + out.join("")
}

export function num(value: number | string | null | undefined, locale = intlLocale(getTexLang())) {
  if (value === null || value === undefined || value === "") return "—"
  const n = typeof value === "number" ? value : Number(value)
  return Number.isFinite(n) ? nf(locale, { maximumFractionDigits: 2 }).format(n) : "—"
}

export function pct(value: string | number | null | undefined, locale = intlLocale(getTexLang())) {
  if (value === null || value === undefined || value === "") return "—"
  return `${num(value, locale)} %`
}

function toDate(v: string | Date) {
  if (v instanceof Date) return v
  // plain dates are calendar days, not instants: parse as local noon
  if (/^\d{4}-\d{2}-\d{2}$/.test(v)) return new Date(`${v}T12:00:00`)
  return new Date(v.replace(" ", "T"))
}

export function date(v: string | Date | null | undefined, style: "short" | "medium" | "long" = "medium", locale = intlLocale(getTexLang())) {
  if (!v) return "—"
  const d = toDate(v)
  if (Number.isNaN(d.getTime())) return "—"
  return new Intl.DateTimeFormat(locale, { dateStyle: style }).format(d)
}

export function dateTime(v: string | Date | null | undefined, locale = intlLocale(getTexLang())) {
  if (!v) return "—"
  const d = toDate(v)
  if (Number.isNaN(d.getTime())) return "—"
  return new Intl.DateTimeFormat(locale, { dateStyle: "medium", timeStyle: "short" }).format(d)
}

/** Time of day ("14:30" / "2:30 PM", locale aware); accepts "HH:MM[:SS]" or a datetime. */
export function time(v: string | Date | null | undefined, locale = intlLocale(getTexLang())) {
  if (!v) return "—"
  let d: Date
  const m = typeof v === "string" ? /^(\d{1,2}):(\d{2})(?::(\d{2}))?/.exec(v) : null
  if (m && typeof v === "string" && !v.includes("-")) d = new Date(2000, 0, 1, Number(m[1]), Number(m[2]), Number(m[3] ?? 0))
  else d = toDate(v)
  if (Number.isNaN(d.getTime())) return "—"
  return new Intl.DateTimeFormat(locale, { timeStyle: "short" }).format(d)
}

/** "2026-10" or a date → "Oct 2026" (locale aware). */
export function month(v: string | Date | null | undefined, locale = intlLocale(getTexLang())) {
  if (!v) return "—"
  const d = typeof v === "string" && /^\d{4}-\d{2}$/.test(v) ? toDate(`${v}-01`) : toDate(v as string | Date)
  if (Number.isNaN(d.getTime())) return "—"
  return new Intl.DateTimeFormat(locale, { month: "short", year: "numeric" }).format(d)
}

export function weekday(v: string, locale = intlLocale(getTexLang())) {
  return new Intl.DateTimeFormat(locale, { weekday: "short" }).format(toDate(v))
}

/** ISO yyyy-mm-dd for a local calendar day. */
export function isoDay(d: Date) {
  const y = String(d.getFullYear()).padStart(4, "0")
  const m = String(d.getMonth() + 1).padStart(2, "0")
  const day = String(d.getDate()).padStart(2, "0")
  return `${y}-${m}-${day}`
}

export function addDays(iso: string, n: number) {
  const d = toDate(iso)
  d.setDate(d.getDate() + n)
  return isoDay(d)
}

export function nightsBetween(a: string, b: string) {
  return Math.round((toDate(b).getTime() - toDate(a).getTime()) / 86400000)
}

/** Validate a decimal string typed by a user (no float parsing). */
export function isDecimal(s: string, maxDecimals = 6) {
  return new RegExp(`^-?\\d+(\\.\\d{1,${maxDecimals}})?$`).test(s.trim())
}
