// Search criteria <-> URL. The URL is the source of truth for a search so that
// links from the widget, back/forward and reloads all land on the same results.
//
//   ?checkin=2026-12-10&checkout=2026-12-13&rooms=2-5.8,1&promo=EARLY10&currency=EUR&hotel=…
//
// `rooms` lists each room as "<adults>" or "<adults>-<age>.<age>…" (child ages in
// whole years). `adults` + `children` (comma-separated ages) are accepted as a
// single-room shorthand.
import { isValidDay } from "./dates"

export interface Party {
  adults: number
  /** whole years 0–17; null = not chosen yet */
  ages: (number | null)[]
}

export interface Criteria {
  checkIn: string | null
  checkOut: string | null
  rooms: Party[]
  promo: string
  currency: string | null
  hotel: string | null
}

export const MAX_ROOMS = 8
export const MAX_ADULTS = 8
export const MAX_CHILDREN = 6
export const MAX_NIGHTS = 90

function clampInt(v: string | undefined, lo: number, hi: number, dflt: number) {
  const n = Number.parseInt(v ?? "", 10)
  return Number.isFinite(n) ? Math.min(hi, Math.max(lo, n)) : dflt
}

function parseAges(s: string, sep: string) {
  return s
    .split(sep)
    .filter((x) => x !== "")
    .slice(0, MAX_CHILDREN)
    .map((x) => (/^\d{1,2}$/.test(x) && Number(x) <= 17 ? Number(x) : null))
}

export function parseRooms(raw: string | null): Party[] | null {
  if (!raw) return null
  const rooms = raw
    .split(",")
    .slice(0, MAX_ROOMS)
    .map((r) => {
      const [a, kids = ""] = r.split("-")
      return { adults: clampInt(a, 1, MAX_ADULTS, 2), ages: parseAges(kids, ".") }
    })
  return rooms.length ? rooms : null
}

export function roomsParam(rooms: Party[]) {
  return rooms.map((r) => (r.ages.length ? `${r.adults}-${r.ages.map((a) => (a === null ? "x" : a)).join(".")}` : `${r.adults}`)).join(",")
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
  }
}

export function applyCriteria(sp: URLSearchParams, c: Criteria) {
  const out = new URLSearchParams(sp)
  for (const k of ["checkin", "checkout", "check_in", "check_out", "rooms", "adults", "children", "ages", "promo", "currency", "hotel", "step"]) out.delete(k)
  if (c.checkIn) out.set("checkin", c.checkIn)
  if (c.checkOut) out.set("checkout", c.checkOut)
  out.set("rooms", roomsParam(c.rooms))
  if (c.promo) out.set("promo", c.promo)
  if (c.currency) out.set("currency", c.currency)
  if (c.hotel) out.set("hotel", c.hotel)
  return out
}

export function isComplete(c: Criteria) {
  return !!(c.checkIn && c.checkOut && c.checkOut > c.checkIn && c.rooms.every((r) => r.ages.every((a) => a !== null)))
}

/** Identity of a search (everything that changes prices), without the hotel filter. */
export function searchKey(c: Criteria) {
  return JSON.stringify([c.checkIn, c.checkOut, roomsParam(c.rooms), c.promo.toUpperCase(), c.currency])
}

export function apiRooms(c: Criteria) {
  return c.rooms.map((r) => ({ adults: r.adults, children: r.ages.map((a) => a ?? 0) }))
}

export function totalGuests(c: Criteria) {
  return {
    adults: c.rooms.reduce((n, r) => n + r.adults, 0),
    children: c.rooms.reduce((n, r) => n + r.ages.length, 0),
  }
}
