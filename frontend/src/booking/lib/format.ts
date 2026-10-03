// Display formatting for the guest bundle. Amounts are decimal strings from the
// server; they are formatted exactly (BigInt integer part + string fraction) and
// never pass through binary floating point. Same approach as tex/lib/format.ts,
// but with an explicit locale so the guest bundle does not load the admin i18n.

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

// the server's minor units (kamra/tex/money.py MINOR_UNITS; anything missing: 2), in which it keeps and sends
// every amount; tests/unit/minor-units.test.ts keeps them the same
const MINOR: Record<string, number> = { JPY: 0, KRW: 0, VND: 0, KWD: 3, BHD: 3, JOD: 3, OMR: 3, TND: 3 }

export function minorUnits(ccy: string) {
  return MINOR[ccy?.toUpperCase()] ?? 2
}

const DECIMAL = /^[-+]?\d+(\.\d+)?$/

export function isAmount(s: unknown): s is string {
  return typeof s === "string" && DECIMAL.test(s.trim())
}

/** True when a server amount is exactly zero ("0", "0.00", "-0.000000"). */
export function isZero(s: string | null | undefined) {
  return !!s && isAmount(s) && /^[-+]?0+(\.0+)?$/.test(s.trim())
}

/** True when a server amount is negative and non-zero. */
export function isNegative(s: string | null | undefined) {
  return !!s && isAmount(s) && s.trim().startsWith("-") && !isZero(s)
}

/** True when a server amount is positive and non-zero. */
export function isPositive(s: string | null | undefined) {
  return !!s && isAmount(s) && !s.trim().startsWith("-") && !isZero(s)
}

/** Rounds half-up on the string representation (display only, never used in arithmetic). */
function roundedParts(amount: string, digits: number) {
  const neg = amount.trim().startsWith("-")
  const clean = amount.trim().replace(/^[-+]/, "")
  const [ip = "0", fp = ""] = clean.split(".")
  let intPart = BigInt(ip || "0")
  let frac = (fp + "0".repeat(digits + 1)).slice(0, digits + 1)
  const roundUp = Number(frac.slice(digits) || "0") >= 5
  frac = frac.slice(0, digits)
  if (roundUp) {
    if (digits === 0) intPart += 1n
    else {
      const bumped = (BigInt(frac) + 1n).toString().padStart(digits, "0")
      if (bumped.length > digits) {
        intPart += 1n
        frac = "0".repeat(digits)
      } else frac = bumped
    }
  }
  return { neg, intPart, frac }
}

export function formatMoney(amount: string | null | undefined, ccy: string | null | undefined, locale: string) {
  if (!isAmount(amount)) return "—"
  const code = (ccy || "").toUpperCase()
  const digits = code ? minorUnits(code) : 2
  const { neg, intPart, frac } = roundedParts(amount, digits)
  const intFmt = nf(locale, { maximumFractionDigits: 0 }).format(intPart)
  const sep = nf(locale, { minimumFractionDigits: 1 }).formatToParts(1.1).find((p) => p.type === "decimal")?.value ?? "."
  const text = digits ? `${intFmt}${sep}${frac}` : intFmt
  const isNeg = neg && !/^0*$/.test(intPart.toString() + frac)
  if (!code) return (isNeg ? "−" : "") + text
  let parts: Intl.NumberFormatPart[]
  try {
    parts = nf(locale, { style: "currency", currency: code }).formatToParts(0)
  } catch {
    return `${isNeg ? "−" : ""}${text} ${code}`
  }
  const out: string[] = []
  let placed = false
  for (const p of parts) {
    if (p.type === "currency" || p.type === "literal") out.push(p.value)
    else if (!placed && (p.type === "integer" || p.type === "decimal" || p.type === "fraction" || p.type === "group")) {
      out.push(text)
      placed = true
    }
  }
  return (isNeg ? "−" : "") + out.join("")
}

export function toDate(v: string | Date) {
  if (v instanceof Date) return v
  // plain dates are calendar days, not instants: parse as local noon
  if (/^\d{4}-\d{2}-\d{2}$/.test(v)) return new Date(`${v}T12:00:00`)
  return new Date(v.replace(" ", "T"))
}

const dfCache = new Map<string, Intl.DateTimeFormat>()

function df(locale: string, opts: Intl.DateTimeFormatOptions) {
  const key = locale + JSON.stringify(opts)
  let f = dfCache.get(key)
  if (!f) {
    f = new Intl.DateTimeFormat(locale, opts)
    dfCache.set(key, f)
  }
  return f
}

export function formatDate(v: string | Date | null | undefined, locale: string, opts: Intl.DateTimeFormatOptions = { dateStyle: "medium" }) {
  if (!v) return "—"
  const d = toDate(v)
  if (Number.isNaN(d.getTime())) return "—"
  return df(locale, opts).format(d)
}

/** "Wed, 10 Dec" */
export function formatDay(v: string, locale: string) {
  return formatDate(v, locale, { weekday: "short", day: "numeric", month: "short" })
}

export function formatDateTime(v: string | null | undefined, locale: string) {
  return formatDate(v, locale, { dateStyle: "medium", timeStyle: "short" })
}

/** "10 – 13 Dec 2026" style range, locale aware. */
export function formatRange(a: string, b: string, locale: string) {
  const f = df(locale, { day: "numeric", month: "short", year: "numeric" }) as Intl.DateTimeFormat & {
    formatRange?: (x: Date, y: Date) => string
  }
  if (typeof f.formatRange === "function") return f.formatRange(toDate(a), toDate(b))
  return `${f.format(toDate(a))} – ${f.format(toDate(b))}`
}

export function formatTime(v: string | null | undefined, locale: string) {
  if (!v) return ""
  const m = /^(\d{1,2}):(\d{2})/.exec(v)
  if (!m) return v
  const d = new Date(2000, 0, 1, Number(m[1]), Number(m[2]))
  return df(locale, { hour: "numeric", minute: "2-digit" }).format(d)
}
