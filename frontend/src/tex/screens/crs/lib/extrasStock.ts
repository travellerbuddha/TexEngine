// Limited extras (G-19): what the agent chose per extra (quantity and service days) and
// what is left of a hotel's daily capacity for them. Guidance only — the server checks the
// capacity again on every quote and under a lock when booking. No money here.
import { getTexLang, intlLocale, type Params } from "../../../i18n"
import { addDays, date, nightsBetween } from "../../../lib/format"

type T = (key: string, params?: Params) => string

/** One extra as the agent chose it: how many, and on which day(s) of the stay. */
export interface ExtraChoice {
  quantity: number
  /** SERVICE_DATE: every day it is served (at least one). Other modes: at most one day, the
   * day of the stay it is used on — for a limited extra the day its capacity is taken
   * (empty = the arrival day). Nightly modes use every night and ignore it. */
  service_dates: string[]
}

/** crs.extras_availability: limited extras only, every day check-in..check-out inclusive. */
export type ExtrasAvailability = Record<string, Record<string, { remaining: number; closed: boolean }>>

export interface StayDates {
  check_in: string
  check_out: string
}

/** Guests of one room (per-person modes take one unit per guest). */
export interface Heads {
  adults: number
  children: number
}

const NIGHTLY = new Set(["NIGHT", "PERSON_NIGHT"])

/** The extra is served on dates the agent picks (one or more). */
export function isServiceDateMode(mode: string) {
  return mode === "SERVICE_DATE"
}

/** The extra is used every night of the stay: no day to choose. */
export function isNightlyMode(mode: string) {
  return NIGHTLY.has(mode)
}

/** Every day of the stay, check-in to check-out inclusive (the days a service date may take). */
export function stayDays(stay: StayDates): string[] {
  const n = nightsBetween(stay.check_in, stay.check_out)
  if (!(n >= 0) || n > 400) return []
  return Array.from({ length: n + 1 }, (_, i) => addDays(stay.check_in, i))
}

/** The nights of the stay (at least one), as the server counts them for nightly extras. */
export function stayNights(stay: StayDates): string[] {
  const n = nightsBetween(stay.check_in, stay.check_out)
  if (!(n >= 0) || n > 400) return []
  return Array.from({ length: Math.max(n, 1) }, (_, i) => addDays(stay.check_in, i))
}

/** The days an extra takes capacity on, mirroring the server's usage(): each chosen date,
 * every night, or one day (the chosen one, else arrival). */
export function usageDays(mode: string, choice: Pick<ExtraChoice, "service_dates"> | undefined, stay: StayDates): string[] {
  if (isServiceDateMode(mode)) return [...(choice?.service_dates ?? [])].sort()
  if (isNightlyMode(mode)) return stayNights(stay)
  return [choice?.service_dates?.[0] || stay.check_in]
}

/** Units one quantity takes per day: 1 for per-unit style modes, the guests for per-person
 * ones; null when the room's split is not known here (children vs infants). */
export function unitsPerQuantity(mode: string, heads?: Heads): number | null {
  switch (mode) {
    case "PERSON":
    case "PERSON_NIGHT":
      return heads ? Math.max(heads.adults + heads.children, 1) : null
    case "ADULT":
      return heads ? Math.max(heads.adults, 1) : null
    case "CHILD":
    case "INFANT":
      return null
    default:
      return 1
  }
}

/** Units an extra takes per day (0 when the split is unknown: the server still checks). */
export function usage(mode: string, choice: ExtraChoice, stay: StayDates, heads?: Heads): Record<string, number> {
  const per = unitsPerQuantity(mode, heads) ?? 0
  const out: Record<string, number> = {}
  if (choice.quantity < 1 || per < 1) return out
  for (const d of usageDays(mode, choice, stay)) out[d] = (out[d] ?? 0) + choice.quantity * per
  return out
}

/** What is left of a limited extra on one day, net of what other rooms of the booking take. */
export interface DayStock {
  day: string
  left: number
  closed: boolean
  /** The day is outside the loaded availability (another stay): treat as unknown. */
  unknown: boolean
}

export function dayStock(
  stock: ExtrasAvailability | undefined,
  code: string,
  day: string,
  taken?: Record<string, Record<string, number>>,
): DayStock | null {
  const byDay = stock?.[code]
  if (!byDay) return null
  const a = byDay[day]
  if (!a) return { day, left: 0, closed: false, unknown: true }
  return { day, left: a.remaining - (taken?.[code]?.[day] ?? 0), closed: a.closed, unknown: false }
}

/** The tightest day of `days` (closed first, then fewest left); null when not limited. */
export function tightest(
  stock: ExtrasAvailability | undefined,
  code: string,
  days: string[],
  taken?: Record<string, Record<string, number>>,
): DayStock | null {
  let worst: DayStock | null = null
  for (const d of days) {
    const s = dayStock(stock, code, d, taken)
    if (!s) return null
    if (s.unknown) continue
    if (!worst || (s.closed && !worst.closed) || (s.closed === worst.closed && s.left < worst.left)) worst = s
  }
  return worst
}

/** Units of each limited extra the other rooms of the booking take, by day. */
export function takenByOtherRooms(
  modes: Map<string, string>,
  stock: ExtrasAvailability | undefined,
  byRoom: Record<number, Record<string, ExtraChoice>>,
  index: number,
  stay: StayDates,
  headsOf: (room: number) => Heads | undefined,
): Record<string, Record<string, number>> {
  const out: Record<string, Record<string, number>> = {}
  if (!stock) return out
  for (const [k, choices] of Object.entries(byRoom)) {
    const room = Number(k)
    if (room === index) continue
    for (const [code, c] of Object.entries(choices)) {
      const mode = modes.get(code)
      if (!mode || !stock[code]) continue
      for (const [d, u] of Object.entries(usage(mode, c, stay, headsOf(room)))) {
        out[code] ??= {}
        out[code][d] = (out[code][d] ?? 0) + u
      }
    }
  }
  return out
}

/** Keep service dates inside the stay (a stay that moved), sorted and unique. */
export function fitChoice(c: ExtraChoice, stay: StayDates, shiftDays = 0): ExtraChoice {
  const dates = [...new Set(c.service_dates.map((d) => (shiftDays ? addDays(d, shiftDays) : d)))]
    .filter((d) => d >= stay.check_in && d <= stay.check_out)
    .sort()
  return { quantity: c.quantity, service_dates: dates }
}

/** Same extras, quantities and days (order-insensitive). */
export function sameChoices(
  a: { code: string; quantity: number; service_dates?: string[] }[],
  b: { code: string; quantity: number; service_dates?: string[] }[],
) {
  const sig = (xs: typeof a) =>
    JSON.stringify(
      xs
        .filter((x) => x.quantity > 0)
        .map((x) => [x.code, x.quantity, [...(x.service_dates ?? [])].sort()])
        .sort((p, q) => String(p[0]).localeCompare(String(q[0]))),
    )
  return sig(a) === sig(b)
}

/** The request form of the choices (what crs.quote / propose_modification take). */
export function choicesToRequest(choices: Record<string, ExtraChoice>) {
  return Object.entries(choices)
    .filter(([, c]) => c.quantity > 0)
    .map(([code, c]) => ({ code, quantity: c.quantity, service_dates: [...c.service_dates] }))
}

/** A capacity refusal of the server ("sold out on …", "only N left on …", "closed on …"). */
export type CapacityReason =
  | { kind: "sold_out"; date: string }
  | { kind: "closed"; date: string }
  | { kind: "only_left"; date: string; count: number }

export function parseCapacityReason(reason: string | null | undefined): CapacityReason | null {
  const s = (reason || "").trim()
  let m = /^sold out on (\d{4}-\d{2}-\d{2})$/.exec(s)
  if (m) return { kind: "sold_out", date: m[1] }
  m = /^closed on (\d{4}-\d{2}-\d{2})$/.exec(s)
  if (m) return { kind: "closed", date: m[1] }
  m = /^only (\d+) left on (\d{4}-\d{2}-\d{2})$/.exec(s)
  if (m) return { kind: "only_left", date: m[2], count: Number(m[1]) }
  return null
}

/** A refusal reason in the agent's language (capacity reasons); any other reason as sent. */
export function extraReasonText(t: T, reason: string): string {
  const c = parseCapacityReason(reason)
  if (!c) return reason
  const day = date(c.date)
  if (c.kind === "sold_out") return t("crs.extras.sold_out_on", { date: day })
  if (c.kind === "closed") return t("crs.extras.closed_on", { date: day })
  return t("crs.extras.only_left_on", { count: c.count, date: day })
}

/** A modification warning "Spa: sold out on 2027-06-12" with its reason translated. */
export function extraWarningText(t: T, message: string): string {
  const m = /^(.*): ((?:sold out|closed|only \d+ left) on \d{4}-\d{2}-\d{2})$/.exec(message)
  return m ? `${m[1]}: ${extraReasonText(t, m[2])}` : message
}

/** The extra's name of a modification warning ("Spa: sold out on 2027-06-12" → "Spa"). */
export function extraWarningName(message: string): string {
  const m = /^(.*): (?:sold out|closed|only \d+ left) on \d{4}-\d{2}-\d{2}$/.exec(message)
  return m ? m[1] : message
}

/** "Tue 12 Jun" — a day of the stay in a chip or a menu. */
export function shortDay(iso: string, locale = intlLocale(getTexLang())): string {
  const d = new Date(`${iso}T12:00:00`)
  if (Number.isNaN(d.getTime())) return iso
  return new Intl.DateTimeFormat(locale, { weekday: "short", day: "numeric", month: "short" }).format(d)
}
