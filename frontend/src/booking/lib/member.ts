// A loyalty member's session on this booking site (C-04, ADR-078): opened by a one-time e-mail link, kept on this
// device for 30 days (the owner's choice) until the guest signs out. Only the session token is kept, never the
// link's; the server is the source of truth (an ended session is answered as signed out).
import type { RoomQuote } from "../types"
import { getJSON, removeItem, setJSON } from "./storage.ts"

export interface StoredMemberSession {
  token: string
  /** when it ends, in epoch milliseconds by this device's clock */
  expires: number
}

const key = (slug: string) => `tex.member.${slug}`

/** The session kept for this site, while it has not ended; an ended or unreadable one is forgotten. */
export function memberSession(slug: string, now = Date.now()): string | null {
  const s = getJSON<StoredMemberSession>(key(slug), "local")
  if (!s) return null
  if (typeof s.token !== "string" || !s.token || typeof s.expires !== "number" || !Number.isFinite(s.expires) || s.expires <= now) {
    removeItem(key(slug), "local")
    return null
  }
  return s.token
}

/** Keep a session the server opened for `expiresIn` seconds (counted here: the server's time zone is not ours). */
export function keepMemberSession(slug: string, token: string, expiresIn: number, now = Date.now()) {
  if (!token || !Number.isFinite(expiresIn) || expiresIn <= 0) return
  setJSON(key(slug), { token, expires: now + expiresIn * 1000 } satisfies StoredMemberSession, "local")
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
  removeItem(key(slug), "local")
}

const backKey = (slug: string) => `tex.member.back.${slug}`
/** how long the search a link was asked from is kept for it (the link works for 30 minutes) */
const BACK_MS = 60 * 60 * 1000

/** The search a guest asks for a link from ("?checkin=…"), kept to return to once the link is opened (the step and
 * the dialog's own parameters are left out: the member chooses their rooms again, at a member's price). */
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

/** Take a member link's token from the address bar's fragment (a fragment never reaches a server or its logs) and
 * remove it, so it is not kept in the history or shared by a copied address. */
export function takeMemberLinkToken(): string | null {
  const token = linkToken(window.location.hash)
  if (token) {
    try {
      window.history.replaceState(window.history.state, "", window.location.pathname + window.location.search)
    } catch {
      /* ignore */
    }
  }
  return token
}

/** A members-only promotion priced one of these rooms: the booking is the signed-in member's own (the server refuses
 * a member's price booked under another e-mail, MEMBERS_ONLY). */
export function memberPriced(quotes: readonly (Pick<RoomQuote, "promotions"> | null | undefined)[]): boolean {
  return quotes.some((q) => (q?.promotions ?? []).some((p) => p.applied && p.member_only))
}
