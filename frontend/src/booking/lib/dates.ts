// Calendar-day helpers. Days are ISO "yyyy-mm-dd" strings in the guest's local
// calendar; nights and ages are integers — no fractional date maths.

export const ISO_DAY = /^\d{4}-\d{2}-\d{2}$/

export function isoDay(d: Date) {
  const y = d.getFullYear()
  const m = String(d.getMonth() + 1).padStart(2, "0")
  const day = String(d.getDate()).padStart(2, "0")
  return `${y}-${m}-${day}`
}

export function parseDay(iso: string) {
  const [y, m, d] = iso.split("-").map(Number)
  return new Date(y, m - 1, d, 12)
}

export function today() {
  return isoDay(new Date())
}

export function addDays(iso: string, n: number) {
  const d = parseDay(iso)
  d.setDate(d.getDate() + n)
  return isoDay(d)
}

export function addMonths(iso: string, n: number) {
  const d = parseDay(iso)
  d.setDate(1)
  d.setMonth(d.getMonth() + n)
  return isoDay(d)
}

export function nightsBetween(a: string, b: string) {
  return Math.round((parseDay(b).getTime() - parseDay(a).getTime()) / 86400000)
}

export function isValidDay(s: string | null | undefined): s is string {
  if (!s || !ISO_DAY.test(s)) return false
  return isoDay(parseDay(s)) === s
}

export function monthStart(iso: string) {
  return iso.slice(0, 8) + "01"
}

/** Days of the month grid (Monday-first by default), padded with nulls. */
export function monthGrid(firstOfMonth: string, weekStart = 1): (string | null)[] {
  const d = parseDay(firstOfMonth)
  const lead = (d.getDay() - weekStart + 7) % 7
  const out: (string | null)[] = Array.from({ length: lead }, () => null)
  const month = d.getMonth()
  while (d.getMonth() === month) {
    out.push(isoDay(d))
    d.setDate(d.getDate() + 1)
  }
  while (out.length % 7) out.push(null)
  return out
}

/** First day of week for a locale (1 = Monday, 0 = Sunday). */
export function weekStartFor(locale: string) {
  try {
    const info = (new Intl.Locale(locale) as Intl.Locale & { weekInfo?: { firstDay: number }; getWeekInfo?: () => { firstDay: number } })
    const wi = info.getWeekInfo?.() ?? info.weekInfo
    if (wi) return wi.firstDay % 7
  } catch {
    /* older engines */
  }
  return /^en-(US|CA)|^pt-BR|^ja|^he/.test(locale) ? 0 : 1
}
