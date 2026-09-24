// Search criteria <-> URL. The URL is the source of truth for a search so that
// links from the widget, back/forward and reloads all land on the same results.
//
//   ?checkin=2026-12-10&checkout=2026-12-13&rooms=2-5_8,1&promo=EARLY10&currency=EUR&hotel=…
//   &market=DE&country=DE   (campaign deep links: which market's contracts price the stay)
//
// `rooms` lists each room as "<adults>" or "<adults>-<age>_<age>…" (child ages in
// whole years). `adults` + `children` (comma-separated ages) are accepted as a
// single-room shorthand.
//
// A child may be given by date of birth instead (G-52). The date never goes into the URL
// (links are shared and reach analytics): the URL says "b" for that child and the date
// stays in this tab (sessionStorage); elsewhere the child's age must be chosen again.
import { isValidDay } from "./dates"
import { getJSON, setJSON } from "./storage"

export interface Party {
  adults: number
  /** per child: whole years 0–17; a date of birth "yyyy-mm-dd" ("" while being typed) that the
   * server prices in completed months on arrival; null = not chosen yet */
  ages: (number | string | null)[]
}

const DOBS_KEY = "tex.dobs"

/** A child whose age (or date of birth) is given. */
export function childSet(a: number | string | null): boolean {
  return typeof a === "number" || isValidDay(a)
}

/** Why a child's date of birth cannot be used ("" when it can). The server checks it again;
 * at 18 on arrival a guest is an adult. Plain calendar-day string comparisons. */
export function dobProblem(dob: string, today: string, checkIn?: string | null): "" | "missing" | "future" | "adult" {
  if (!isValidDay(dob)) return "missing"
  if (dob > today) return "future"
  if (checkIn && isValidDay(checkIn) && `${String(Number(dob.slice(0, 4)) + 18).padStart(4, "0")}${dob.slice(4)}` <= checkIn)
    return "adult"
  return ""
}

function dobsOf(rooms: Party[]): (string | null)[][] {
  return rooms.map((r) => r.ages.map((a) => (typeof a === "string" && isValidDay(a) ? a : null)))
}

function storedDobs(): (string | null)[][] {
  const v = getJSON<unknown>(DOBS_KEY)
  return Array.isArray(v) ? (v as (string | null)[][]) : []
}

export interface Criteria {
  checkIn: string | null
  checkOut: string | null
  rooms: Party[]
  promo: string
  currency: string | null
  hotel: string | null
  /** market code from a campaign link (never shown to the guest) */
  market: string | null
  /** guest country (ISO 3166-1 alpha-2) from a link; the server picks the market from it */
  country: string | null
}

export const MAX_ROOMS = 8
export const MAX_ADULTS = 8
export const MAX_CHILDREN = 6
export const MAX_NIGHTS = 90

function clampInt(v: string | undefined, lo: number, hi: number, dflt: number) {
  const n = Number.parseInt(v ?? "", 10)
  return Number.isFinite(n) ? Math.min(hi, Math.max(lo, n)) : dflt
}

function parseAges(s: string, sep: string | RegExp, dobs: (string | null)[] = []): (number | string | null)[] {
  return s
    .split(sep)
    .filter((x) => x !== "")
    .slice(0, MAX_CHILDREN)
    .map((x, k) => {
      if (x === "b") return isValidDay(dobs[k]) ? dobs[k] : null
      return /^\d{1,2}$/.test(x) && Number(x) <= 17 ? Number(x) : null
    })
}

export function parseRooms(raw: string | null): Party[] | null {
  if (!raw) return null
  const dobs = storedDobs()
  const rooms = raw
    .split(",")
    .slice(0, MAX_ROOMS)
    .map((r, i) => {
      const [a, kids = ""] = r.split("-")
      return { adults: clampInt(a, 1, MAX_ADULTS, 2), ages: parseAges(kids, /[._]/, Array.isArray(dobs[i]) ? dobs[i] : []) }
    })
  return rooms.length ? rooms : null
}

export function roomsParam(rooms: Party[]) {
  const token = (a: number | string | null) => (a === null ? "x" : typeof a === "string" ? "b" : a)
  return rooms.map((r) => (r.ages.length ? `${r.adults}-${r.ages.map(token).join("_")}` : `${r.adults}`)).join(",")
}

export function parseCriteria(sp: URLSearchParams): Criteria {
  let rooms = parseRooms(sp.get("rooms"))
  if (!rooms) {
    const adults = clampInt(sp.get("adults") ?? undefined, 1, MAX_ADULTS, 2)
    // shorthand: children / ages = comma-separated ages in years
    rooms = [{ adults, ages: parseAges(sp.get("children") ?? sp.get("ages") ?? "", ",") }]
  }
  const ci = sp.get("checkin") ?? sp.get("check_in")
  const co = sp.get("checkout") ?? sp.get("check_out")
  return {
    checkIn: isValidDay(ci) ? ci : null,
    checkOut: isValidDay(co) ? co : null,
    rooms,
    promo: (sp.get("promo") ?? "").trim().slice(0, 40),
    currency: /^[A-Z]{3}$/.test(sp.get("currency") ?? "") ? sp.get("currency") : null,
    hotel: sp.get("hotel") || null,
    market: /^[A-Za-z0-9_-]{1,40}$/.test(sp.get("market") ?? "") ? sp.get("market") : null,
    country: /^[A-Za-z]{2}$/.test(sp.get("country") ?? "") ? sp.get("country")!.toUpperCase() : null,
  }
}

export function applyCriteria(sp: URLSearchParams, c: Criteria) {
  const out = new URLSearchParams(sp)
  for (const k of ["checkin", "checkout", "check_in", "check_out", "rooms", "adults", "children", "ages", "promo", "currency", "hotel", "market", "country", "step"])
    out.delete(k)
  setJSON(DOBS_KEY, dobsOf(c.rooms))       // dates of birth stay in this tab, never in the URL
  if (c.checkIn) out.set("checkin", c.checkIn)
  if (c.checkOut) out.set("checkout", c.checkOut)
  out.set("rooms", roomsParam(c.rooms))
  if (c.promo) out.set("promo", c.promo)
  if (c.currency) out.set("currency", c.currency)
  if (c.hotel) out.set("hotel", c.hotel)
  if (c.market) out.set("market", c.market)
  if (c.country) out.set("country", c.country)
  return out
}

export function isComplete(c: Criteria) {
  return !!(c.checkIn && c.checkOut && c.checkOut > c.checkIn && c.rooms.every((r) => r.ages.every(childSet)))
}

/** Identity of a search (everything that changes prices), without the hotel filter. */
export function searchKey(c: Criteria) {
  return JSON.stringify([c.checkIn, c.checkOut, roomsParam(c.rooms), dobsOf(c.rooms), c.promo.toUpperCase(), c.currency, c.market, c.country])
}

export function apiRooms(c: Criteria) {
  return c.rooms.map((r) => ({ adults: r.adults, children: r.ages.map(apiChild) }))
}

/** A child as the API takes it: an age in whole years, or ``{ dob }`` (checked and priced by the server). */
export function apiChild(a: number | string | null): number | { dob: string } {
  return typeof a === "string" ? { dob: a } : (a ?? 0)
}

export function totalGuests(c: Criteria) {
  return {
    adults: c.rooms.reduce((n, r) => n + r.adults, 0),
    children: c.rooms.reduce((n, r) => n + r.ages.length, 0),
  }
}
