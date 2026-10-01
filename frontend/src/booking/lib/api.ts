// Guest API client for kamra.tex.api.public. Every call is a POST with a JSON body
// so tokens never travel in query strings (and never reach access logs). Money is
// returned as decimal strings and is never recomputed here.

export type ErrorKind =
  | "sold_out"
  /** a limited extra (spa slot, transfer…) ran out while booking — the room is not affected */
  | "extra_sold_out"
  | "expired"
  | "rate_limit"
  | "not_found"
  | "permission"
  | "network"
  | "invalid"
  | "server"

export class ApiError extends Error {
  status: number
  type: string
  kind: ErrorKind
  /** the refusal's stable code (`tex_code`, G-70a), e.g. "SOLD_OUT" or "MARKET_RESIDENCY"; null when the server sent none */
  code: string | null
  /** the refusal's guest-safe params (`tex_params`): ISO dates, decimal strings, ISO codes, hotel names */
  params: Record<string, unknown>
  constructor(message: string, status: number, type: string, kind: ErrorKind, code: string | null = null,
              params: Record<string, unknown> = {}) {
    super(message)
    this.status = status
    this.type = type
    this.kind = kind
    this.code = code
    this.params = params
  }
}

const ENTITIES: Record<string, string> = { "&amp;": "&", "&lt;": "<", "&gt;": ">", "&quot;": '"', "&#39;": "'" }

function clean(s: string) {
  return s
    .replace(/<[^>]+>/g, "")
    .replace(/&(amp|lt|gt|quot|#39);/g, (m) => ENTITIES[m] ?? m)
    .trim()
}

// The server's wording for the states the guest must recover from by searching again: only for a refusal
// that carries no code yet (G-70b codes them all and drops the wording).
const SOLD_OUT = /sold out|no longer available|not enough rooms/i
const EXPIRED = /expired|search again|no longer on sale|already used|invalid offer|invalid quote/i

/** A refusal code as the server sends it (kamra/tex/refusal_codes.py): UPPER_SNAKE. */
const CODE = /^[A-Z][A-Z0-9_]{1,63}$/

/** The kind a code means, whatever the language of its message (G-70a). A code missing here (the server's
 * fallback codes NOT_FOUND / NOT_PERMITTED / RATE_LIMITED included) is classified as before, by its wording and
 * status; a market code is a refusal the search or checkout recovers from (G-55b, O-8), never sold out: a quote of a
 * market the site no longer sells is searched again (expired), a residents-only market's goes back to the guest's
 * country of residence. */
const KIND_BY_CODE: Record<string, ErrorKind> = {
  SOLD_OUT: "sold_out",
  EXTRA_SOLD_OUT: "extra_sold_out",
  CONTRACT_NOT_ON_SALE: "expired",
  CONTRACT_SUSPENDED: "expired",
  MARKET_UNKNOWN: "invalid",
  MARKET_AMBIGUOUS: "invalid",
  MARKET_REQUIRED: "invalid",
  MARKET_NOT_ALLOWED: "expired",
  MARKET_RESIDENCY: "invalid",
}

function classify(message: string, status: number, type: string, code: string | null): ErrorKind {
  if (status === 429 || type === "RateLimitExceededError") return "rate_limit"
  const byCode = code ? KIND_BY_CODE[code] : undefined
  if (byCode) return byCode
  // before the wording test: "Spa has just sold out…" is an extra, not the room (G-19)
  if (type === "ExtraSoldOut" || type.endsWith(".ExtraSoldOut")) return "extra_sold_out"
  if (SOLD_OUT.test(message)) return "sold_out"
  if (EXPIRED.test(message)) return "expired"
  if (status === 404 || type === "DoesNotExistError") return "not_found"
  if (status === 403 || type === "PermissionError") return "permission"
  if (status === 417 || type === "ValidationError") return "invalid"
  return "server"
}

export function parseError(body: string, status: number): ApiError {
  let message = ""
  let type = ""
  let code: string | null = null
  let params: Record<string, unknown> = {}
  try {
    const j = JSON.parse(body) as {
      _server_messages?: string
      exception?: string
      exc_type?: string
      message?: unknown
      tex_code?: unknown
      tex_params?: unknown
    }
    type = j.exc_type ?? ""
    if (typeof j.tex_code === "string" && CODE.test(j.tex_code)) {
      code = j.tex_code
      if (j.tex_params && typeof j.tex_params === "object" && !Array.isArray(j.tex_params))
        params = j.tex_params as Record<string, unknown>
    }
    if (j._server_messages) {
      const msgs = JSON.parse(j._server_messages) as string[]
      message = msgs
        .map((m) => {
          try {
            return clean(String((JSON.parse(m) as { message?: string }).message ?? m))
          } catch {
            return clean(m)
          }
        })
        .filter(Boolean)
        .join("\n")
    }
    if (!message && j.exception) message = clean(j.exception.split(":").slice(1).join(":") || j.exception)
    if (!message && typeof j.message === "string") message = clean(j.message)
  } catch {
    /* not JSON */
  }
  return new ApiError(message, status, type, classify(message, status, type, code), code, params)
}

let acceptLanguage = "en"

/** Server messages follow the guest's chosen language where the server has a translation. */
export function setApiLanguage(lang: string) {
  acceptLanguage = lang
}

export function endpoint(fn: string) {
  return `/api/method/kamra.tex.api.public.${fn}`
}

/** The session's CSRF token, when the page was served to a signed-in user (O-28): Frappe refuses
 * a POST of such a session without it, `allow_guest` or not. A guest's page has none. */
export function sessionToken(): string | null {
  const t = (window as Window & { csrf_token?: unknown }).csrf_token
  return typeof t === "string" && t ? t : null
}

export async function pub<T>(fn: string, args: Record<string, unknown> = {}, signal?: AbortSignal): Promise<T> {
  let res: Response
  const csrf = sessionToken()
  try {
    res = await fetch(endpoint(fn), {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Accept: "application/json",
        "Accept-Language": acceptLanguage,
        ...(csrf ? { "X-Frappe-CSRF-Token": csrf } : {}),
      },
      body: JSON.stringify(args),
      credentials: "same-origin",
      signal,
    })
  } catch (e) {
    if ((e as Error).name === "AbortError") throw e
    throw new ApiError("", 0, "NetworkError", "network")
  }
  const text = await res.text()
  if (!res.ok) throw parseError(text, res.status)
  try {
    // successful responses may still carry unrelated _server_messages (e.g. mail setup) — ignore them
    return (JSON.parse(text) as { message: T }).message
  } catch {
    throw new ApiError("", res.status, "ParseError", "server")
  }
}

/** Fire-and-forget POST that survives page unload (funnel events). */
export function beacon(fn: string, args: Record<string, string>) {
  const body = new URLSearchParams(args)
  // sendBeacon cannot send headers: Frappe also takes the token as a form field
  const csrf = sessionToken()
  if (csrf) body.set("csrf_token", csrf)
  try {
    if (navigator.sendBeacon && navigator.sendBeacon(endpoint(fn), body)) return
  } catch {
    /* fall through */
  }
  try {
    void fetch(endpoint(fn), { method: "POST", body, keepalive: true, credentials: "same-origin" }).catch(() => undefined)
  } catch {
    /* ignore */
  }
}
