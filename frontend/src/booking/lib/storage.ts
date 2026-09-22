// Tab-scoped guest state. sessionStorage can be unavailable (private mode, blocked
// storage, sandboxed frames): every access is guarded and the app keeps working
// from memory. Nothing here is a source of truth — the server is.
import type { PaymentStart } from "../types"

const memory = new Map<string, string>()

function store(kind: "session" | "local"): Storage | null {
  try {
    return kind === "session" ? window.sessionStorage : window.localStorage
  } catch {
    return null
  }
}

export function getItem(key: string, kind: "session" | "local" = "session"): string | null {
  try {
    const v = store(kind)?.getItem(key)
    if (v !== null && v !== undefined) return v
  } catch {
    /* blocked */
  }
  return memory.get(`${kind}:${key}`) ?? null
}

export function setItem(key: string, value: string, kind: "session" | "local" = "session") {
  memory.set(`${kind}:${key}`, value)
  try {
    store(kind)?.setItem(key, value)
  } catch {
    /* quota or blocked */
  }
}

export function removeItem(key: string, kind: "session" | "local" = "session") {
  memory.delete(`${kind}:${key}`)
  try {
    store(kind)?.removeItem(key)
  } catch {
    /* blocked */
  }
}

export function getJSON<T>(key: string, kind: "session" | "local" = "session"): T | null {
  const raw = getItem(key, kind)
  if (!raw) return null
  try {
    return JSON.parse(raw) as T
  } catch {
    return null
  }
}

export function setJSON(key: string, value: unknown, kind: "session" | "local" = "session") {
  setItem(key, JSON.stringify(value), kind)
}

function randomId() {
  try {
    return crypto.randomUUID().replace(/-/g, "")
  } catch {
    const a = new Uint8Array(16)
    crypto.getRandomValues(a)
    return Array.from(a, (b) => b.toString(16).padStart(2, "0")).join("")
  }
}

export function newKey(prefix: string) {
  return `${prefix}-${randomId()}`
}

/** Random funnel session id for this tab (no personal data). */
export function sessionId() {
  let sid = getItem("tex.sid")
  if (!sid) {
    sid = randomId()
    setItem("tex.sid", sid)
  }
  return sid
}

// ─── manage tokens (stored at booking time, read by confirmation/manage) ───

export function saveManageToken(booking: string, token: string, site?: string) {
  setItem(`tex.manage.${booking}`, token)
  if (site) setItem(`tex.manage.site.${site}`, token)
}

export function manageToken(booking: string) {
  return getItem(`tex.manage.${booking}`)
}

export function siteManageToken(site: string) {
  return getItem(`tex.manage.site.${site}`)
}

// ─── payments ───

export interface StoredPayment {
  transaction: string
  success_sig?: string
  fail_sig?: string
  amount?: string
  currency?: string
  hotel?: string
  label?: string
}

/** Remember what the next page needs from a payment start (mock signatures,
 * bank instructions). Only the signatures the server handed out are stored. */
export function rememberPayment(p: PaymentStart, extra: Omit<StoredPayment, "transaction"> = {}) {
  if (p.fields && (p.fields.success_sig || p.fields.fail_sig)) {
    setJSON(`tex.pay.${p.transaction}`, {
      transaction: p.transaction,
      success_sig: p.fields.success_sig,
      fail_sig: p.fields.fail_sig,
      ...extra,
    } satisfies StoredPayment)
  }
}

export function storedPayment(txn: string) {
  return getJSON<StoredPayment>(`tex.pay.${txn}`)
}

export function forgetPayment(txn: string) {
  removeItem(`tex.pay.${txn}`)
}

export function saveInstructions(booking: string, instructions: Record<string, string | null>) {
  setJSON(`tex.instructions.${booking}`, instructions)
}

export function instructionsFor(booking: string) {
  return getJSON<Record<string, string | null>>(`tex.instructions.${booking}`)
}

export function isEmbedded() {
  if (getItem("tex.embed") === "1") return true
  try {
    if (new URLSearchParams(window.location.search).get("embed") === "1") {
      setItem("tex.embed", "1")
      return true
    }
  } catch {
    /* ignore */
  }
  return false
}
