// A loyalty member's session on this booking site (C-04, ADR-078): opened by a one-time e-mail link. On a hotel's own
// host it is kept on this device for 30 days (the owner's choice) until the guest signs out; on the platform's shared
// host, where other hotels' pages and their tag containers run on the same origin, only in this tab, and a site's page
// removes every other site's member data before anything else runs (owner, 2026-10-03, review round 1). Only the
// session token is kept, never the link's; the server is the source of truth (an ended session is answered as
// signed out).
import type { RoomQuote } from "../types"
import { getJSON, keysWithPrefix, removeItem, setJSON } from "./storage.ts"

export interface StoredMemberSession {
  token: string
  /** when it ends, in epoch milliseconds by this device's clock */
  expires: number
}

const PREFIX = "tex.member."
const key = (slug: string) => `${PREFIX}${slug}`
const backKey = (slug: string) => `${PREFIX}back.${slug}`

let kind: "local" | "session" = "local"

/** Where sessions are kept: on the device (a hotel's own host) or in the tab (the platform's shared host). Set once,
 * before the app starts. */
export function keepSessionsOnDevice(on: boolean) {
  kind = on ? "local" : "session"
}

/** On the platform's shared host, before anything of a site runs: every other site's member data goes (its session
 * and the search a link was asked from), and nothing is kept on the device there. `current`: the site of the page
 * (null: a site-less page keeps none). */
export function isolateMemberData(current: string | null) {
  const siteOf = (k: string) => {
    const rest = k.slice(PREFIX.length)
    return rest.startsWith("back.") ? rest.slice(5) : rest
  }
  const isBack = (k: string) => k.startsWith(`${PREFIX}back.`)
  for (const k of keysWithPrefix(PREFIX, "local")) if (!isBack(k) || siteOf(k) !== current) removeItem(k, "local")
  for (const k of keysWithPrefix(PREFIX, "session")) if (siteOf(k) !== current) removeItem(k, "session")
}

/** The session kept for this site, while it has not ended; an ended or unreadable one is forgotten. */
export function memberSession(slug: string, now = Date.now()): string | null {
  const s = getJSON<StoredMemberSession>(key(slug), kind)
  if (!s) return null
  if (typeof s.token !== "string" || !s.token || typeof s.expires !== "number" || !Number.isFinite(s.expires) || s.expires <= now) {
    removeItem(key(slug), kind)
    return null
  }
  return s.token
}

/** Keep a session the server opened for `expiresIn` seconds (counted here: the server's time zone is not ours). */
export function keepMemberSession(slug: string, token: string, expiresIn: number, now = Date.now()) {
  if (!token || !Number.isFinite(expiresIn) || expiresIn <= 0) return
  setJSON(key(slug), { token, expires: now + expiresIn * 1000 } satisfies StoredMemberSession, kind)
}

/** The storage key of a site's session (a `storage` event names it when another tab signs in or out). */
export function memberSessionKey(slug: string) {
  return key(slug)
}

/** A short tag of a session (FNV-1a), so a price can name the session it is for without keeping its token. */
export function sessionTag(token: string): string {
  let h = 0x811c9dc5
  for (let i = 0; i < token.length; i++) {
    h ^= token.charCodeAt(i)
    h = Math.imul(h, 0x01000193) >>> 0
  }
  return h.toString(36)
}

export function forgetMemberSession(slug: string) {
  removeItem(key(slug), kind)
}

/** how long the search a link was asked from is kept for it (the link works for 30 minutes) */
const BACK_MS = 60 * 60 * 1000

/** The search a guest asks for a link from ("?checkin=…"), kept to return to once the link is opened (the step and
 * the dialog's own parameters are left out: the member chooses their rooms again, at a member's price). It is kept
 * on the device even on the platform's host (the link opens in a new tab): dates and a party, no personal data. */
export function rememberMemberReturn(slug: string, search: string, now = Date.now()) {
  const q = new URLSearchParams(search)
  for (const k of ["step", "join", "sign_in"]) q.delete(k)
  const s = q.toString()
  if (s) setJSON(backKey(slug), { q: `?${s}`, at: now }, "local")
  else removeItem(backKey(slug), "local")
}

/** Take the search to return to after a link is opened, or null (none, or asked for too long ago). */
export function memberReturn(slug: string, now = Date.now()): string | null {
  const b = getJSON<{ q?: unknown; at?: unknown }>(backKey(slug), "local")
  removeItem(backKey(slug), "local")
  if (!b || typeof b.q !== "string" || !b.q.startsWith("?") || typeof b.at !== "number" || now - b.at > BACK_MS || b.at > now) return null
  return b.q
}

/** The token of a member link, from a URL fragment ("#token=…"), or null. */
export function linkToken(hash: string): string | null {
  const m = /(?:^#?|&)token=([^&]+)/.exec(hash)
  if (!m) return null
  try {
    return decodeURIComponent(m[1]) || null
  } catch {
    return null
  }
}

let adopted: string | null = null

/** Take a member link's token from the address bar's fragment (a fragment never reaches a server or its logs) and
 * remove it, so it is not kept in the history, shared by a copied address or seen by a tag container. Call before the
 * app starts, and on a `hashchange` of the member page. */
export function takeMemberLinkToken(): string | null {
  const token = linkToken(window.location.hash)
  if (token) {
    adopted = token
    try {
      window.history.replaceState(window.history.state, "", window.location.pathname + window.location.search)
    } catch {
      /* ignore */
    }
  }
  return token
}

/** The link token taken from the address this page opened at (or its last `hashchange`), or null. */
export function adoptedLinkToken(): string | null {
  return adopted
}

/** The link is settled (used or refused): it is not offered again. */
export function dropLinkToken() {
  adopted = null
}

/** A members-only promotion priced one of these rooms: the booking is the signed-in member's own (the server refuses
 * a member's price booked under another e-mail, MEMBERS_ONLY). */
export function memberPriced(quotes: readonly (Pick<RoomQuote, "promotions"> | null | undefined)[]): boolean {
  return quotes.some((q) => (q?.promotions ?? []).some((p) => p.applied && p.member_only))
}
