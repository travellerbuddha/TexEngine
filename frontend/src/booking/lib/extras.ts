// Limited extras (G-19): a spa slot or a transfer with a daily capacity. The server
// says per day whether the extra can still be booked online and whether few are left
// (never how many); these helpers work out what that means for one extra of this stay,
// and turn the quote's English refusal reasons into the guest's language.
import type { I18n } from "../i18n"
import { addDays, nightsBetween } from "./dates"

export interface DayAvailability {
  available: boolean
  low: boolean
}

/** public.extras_availability: { "<EXTRA_CODE>": { "yyyy-mm-dd": { available, low } } } */
export type ExtrasAvailability = Record<string, Record<string, DayAvailability>>

/** Every day an extra can be used on: arrival to departure, both included (as the server accepts). */
export function stayDays(checkIn: string | null | undefined, checkOut: string | null | undefined): string[] {
  if (!checkIn || !checkOut) return []
  const n = nightsBetween(checkIn, checkOut)
  return Array.from({ length: Math.max(n, 0) + 1 }, (_, i) => addDays(checkIn, i))
}

const NIGHTLY = new Set(["NIGHT", "PERSON_NIGHT"])
const OPEN: DayAvailability = { available: true, low: false }

export interface ExtraStock {
  /** the hotel limits this extra per day */
  limited: boolean
  /** the day's state (open when the extra is not limited or the day is unknown: the server decides) */
  day: (d: string) => DayAvailability
  /** no day this extra could use is left for this stay */
  soldOut: boolean
  /** few left on the days it would use */
  low: boolean
  /** used on one day the guest may pick (arrival by default) */
  oneDay: boolean
  /** that day when the guest has not picked one: arrival, else the first day still available */
  defaultDay: string | null
}

/**
 * What the per-day availability means for one extra of this stay, by how the server
 * counts its use: chosen dates for SERVICE_DATE, every night for nightly extras,
 * otherwise one day of the stay (the chosen service date, else arrival).
 */
export function extraStock(
  mode: string,
  days: Record<string, DayAvailability> | undefined,
  checkIn: string | null | undefined,
  checkOut: string | null | undefined,
  chosenDay?: string | null,
): ExtraStock {
  const stay = stayDays(checkIn, checkOut)
  const day = (d: string) => days?.[d] ?? OPEN
  if (!days || !stay.length) return { limited: false, day, soldOut: false, low: false, oneDay: false, defaultDay: null }
  if (mode === "SERVICE_DATE") {
    const open = stay.filter((d) => day(d).available)
    return { limited: true, day, soldOut: !open.length, low: false, oneDay: false, defaultDay: null }
  }
  if (NIGHTLY.has(mode)) {
    const nights = stay.length > 1 ? stay.slice(0, -1) : stay
    return {
      limited: true,
      day,
      soldOut: nights.some((d) => !day(d).available),
      low: nights.some((d) => day(d).low),
      oneDay: false,
      defaultDay: null,
    }
  }
  const open = stay.filter((d) => day(d).available)
  const defaultDay = day(stay[0]).available ? stay[0] : open[0] ?? null
  const used = chosenDay && stay.includes(chosenDay) ? chosenDay : defaultDay
  return { limited: true, day, soldOut: !open.length, low: !!used && day(used).low, oneDay: true, defaultDay }
}

type Refusal = { kind: "sold_out" | "few_left" | "closed"; date: string } | { kind: "other" }

// the quote's reasons for a limited extra it could not add (pricing/extras.py capacity_refusal);
// guest endpoints say "not enough left on D" (guest_reason), staff ones "only N left on D"
const SOLD_OUT_ON = /^sold out on (\d{4}-\d{2}-\d{2})$/i
const NOT_ENOUGH_ON = /^(?:not enough|only \d+) left on (\d{4}-\d{2}-\d{2})$/i
const CLOSED_ON = /^closed on (\d{4}-\d{2}-\d{2})$/i

export function parseRefusal(reason: string | null | undefined): Refusal {
  const r = (reason ?? "").trim()
  let m = SOLD_OUT_ON.exec(r)
  if (m) return { kind: "sold_out", date: m[1] }
  m = NOT_ENOUGH_ON.exec(r)
  if (m) return { kind: "few_left", date: m[1] }
  m = CLOSED_ON.exec(r)
  if (m) return { kind: "closed", date: m[1] }
  return { kind: "other" }
}

/** Why the quote did not add an extra, in the guest's words (never the remaining count). */
export function refusalText(i18n: Pick<I18n, "t" | "day">, reason: string | null | undefined): string {
  const r = parseRefusal(reason)
  if (r.kind === "sold_out") return i18n.t("extras.reasonSoldOut", { date: i18n.day(r.date) })
  if (r.kind === "few_left") return i18n.t("extras.reasonFewLeft", { date: i18n.day(r.date) })
  if (r.kind === "closed") return i18n.t("extras.reasonClosed", { date: i18n.day(r.date) })
  return i18n.t("extras.reasonOther")
}

/** Element id of an extra's card on the extras step (the notice scrolls to it). */
export function extraAnchor(room: number, code: string) {
  return `bk-extra-r${room}-${code.replace(/[^A-Za-z0-9_-]/g, "_")}`
}
