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
  constructor(message: string, status: number, type: string, kind: ErrorKind) {
    super(message)
    this.status = status
    this.type = type
    this.kind = kind
  }
}

const ENTITIES: Record<string, string> = { "&amp;": "&", "&lt;": "<", "&gt;": ">", "&quot;": '"', "&#39;": "'" }

function clean(s: string) {
  return s
    .replace(/<[^>]+>/g, "")
    .replace(/&(amp|lt|gt|quot|#39);/g, (m) => ENTITIES[m] ?? m)
    .trim()
}

// The server's wording for the states the guest must recover from by searching again.
const SOLD_OUT = /sold out|no longer available|not enough rooms/i
const EXPIRED = /expired|search again|no longer on sale|already used|invalid offer|invalid quote/i

function classify(message: string, status: number, type: string): ErrorKind {
  if (status === 429 || type === "RateLimitExceededError") return "rate_limit"
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
  try {
    const j = JSON.parse(body) as { _server_messages?: string; exception?: string; exc_type?: string; message?: unknown }
    type = j.exc_type ?? ""
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
  return new ApiError(message, status, type, classify(message, status, type))
}

let acceptLanguage = "en"

/** Server messages follow the guest's chosen language where the server has a translation. */
export function setApiLanguage(lang: string) {
  acceptLanguage = lang
}

export function endpoint(fn: string) {
  return `/api/method/kamra.tex.api.public.${fn}`
}

export async function pub<T>(fn: string, args: Record<string, unknown> = {}, signal?: AbortSignal): Promise<T> {
  let res: Response
  try {
    res = await fetch(endpoint(fn), {
      method: "POST",
      headers: { "Content-Type": "application/json", Accept: "application/json", "Accept-Language": acceptLanguage },
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
