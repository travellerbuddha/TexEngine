// TEX API client: thin wrapper over Frappe's /api/method for the whitelisted
// modules in kamra/tex/api. Money travels as strings and is never recomputed
// here — the server owns every price (ADR-003).
import { useCallback, useEffect, useRef, useState } from "react"

export type TexModule =
  | "session"
  | "contracts"
  | "policies"
  | "crs"
  | "public"
  | "payments"
  | "crm"
  | "loyalty"
  | "reports"
  | "admin"
  | "content"
  | "distribution"
  // area helper modules (kamra/tex/api/ui_<area>.py)
  | `ui_${string}`

export class TexApiError extends Error {
  status: number
  type: string
  constructor(message: string, status: number, type: string) {
    super(message)
    this.status = status
    this.type = type
  }
  get isPermission() {
    return this.status === 403 || this.type === "PermissionError"
  }
  get isNotFound() {
    return this.status === 404 || this.type === "DoesNotExistError"
  }
}

function csrfToken(): string | undefined {
  const t = (window as unknown as { csrf_token?: string }).csrf_token
  return t && t !== "None" ? t : undefined
}

function stripHtml(s: string) {
  return s.replace(/<[^>]+>/g, "").trim()
}

/** Extract the human message Frappe put in an error response. */
export function parseFrappeError(body: string, status: number): TexApiError {
  let message = ""
  let type = ""
  try {
    const j = JSON.parse(body) as { _server_messages?: string; exception?: string; exc_type?: string; message?: string }
    type = j.exc_type ?? ""
    if (j._server_messages) {
      const msgs = JSON.parse(j._server_messages) as string[]
      message = msgs
        .map((m) => {
          try {
            return stripHtml(String((JSON.parse(m) as { message?: string }).message ?? m))
          } catch {
            return stripHtml(m)
          }
        })
        .filter(Boolean)
        .join("\n")
    }
    if (!message && j.exception) message = stripHtml(j.exception.split(":").slice(1).join(":") || j.exception)
    if (!message && typeof j.message === "string") message = stripHtml(j.message)
  } catch {
    /* non-JSON body */
  }
  if (!message) {
    message =
      status === 403
        ? "You don't have permission for this."
        : status === 404
          ? "Not found."
          : status === 429
            ? "Too many requests — please wait a moment."
            : `Request failed (${status}).`
  }
  return new TexApiError(message, status, type)
}

function encodeArgs(args: Record<string, unknown>): URLSearchParams {
  const q = new URLSearchParams()
  for (const [k, v] of Object.entries(args)) {
    if (v === undefined || v === null) continue
    q.set(k, typeof v === "object" ? JSON.stringify(v) : String(v))
  }
  return q
}

export interface CallOptions {
  post?: boolean
  signal?: AbortSignal
}

/** Call kamra.tex.api.<module>.<method>. Reads use GET, writes POST. */
export async function tex<T = unknown>(
  module: TexModule,
  method: string,
  args: Record<string, unknown> = {},
  opts: CallOptions = {},
): Promise<T> {
  const path = `/api/method/kamra.tex.api.${module}.${method}`
  const token = csrfToken()
  const headers: Record<string, string> = { Accept: "application/json" }
  if (token) headers["X-Frappe-CSRF-Token"] = token
  let res: Response
  try {
    if (opts.post) {
      headers["Content-Type"] = "application/json"
      res = await fetch(path, {
        method: "POST",
        headers,
        body: JSON.stringify(args),
        credentials: "include",
        signal: opts.signal,
      })
    } else {
      const q = encodeArgs(args).toString()
      res = await fetch(q ? `${path}?${q}` : path, { headers, credentials: "include", signal: opts.signal })
    }
  } catch (e) {
    if ((e as Error).name === "AbortError") throw e
    throw new TexApiError("Can't reach the server. Check your connection and try again.", 0, "NetworkError")
  }
  if (!res.ok) {
    const err = parseFrappeError(await res.text(), res.status)
    if (res.status === 401 || (res.status === 403 && err.type === "AuthenticationError"))
      window.dispatchEvent(new Event("kamra:auth-error"))
    throw err
  }
  const json = (await res.json()) as { message: T }
  return json.message
}

export interface QueryState<T> {
  data: T | undefined
  error: TexApiError | undefined
  loading: boolean
  reload: () => void
}

/** Fetch on mount and whenever `deps` change; aborts stale requests. Pass
 * `enabled=false` to wait (e.g. until a hotel is selected). */
export function useTexQuery<T>(
  module: TexModule,
  method: string,
  args: Record<string, unknown>,
  deps: unknown[],
  enabled = true,
): QueryState<T> {
  const [data, setData] = useState<T>()
  const [error, setError] = useState<TexApiError>()
  const [loading, setLoading] = useState(enabled)
  const [tick, setTick] = useState(0)
  const argsRef = useRef(args)
  argsRef.current = args

  useEffect(() => {
    if (!enabled) {
      setLoading(false)
      return
    }
    const ctl = new AbortController()
    setLoading(true)
    setError(undefined)
    tex<T>(module, method, argsRef.current, { signal: ctl.signal })
      .then((d) => {
        setData(d)
        setLoading(false)
      })
      .catch((e: unknown) => {
        if ((e as Error).name === "AbortError") return
        setError(e instanceof TexApiError ? e : new TexApiError(String(e), 0, "Error"))
        setLoading(false)
      })
    return () => ctl.abort()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [module, method, enabled, tick, ...deps])

  const reload = useCallback(() => setTick((n) => n + 1), [])
  return { data, error, loading, reload }
}

/** Imperative write with pending/error state. */
export function useTexMutation<A extends Record<string, unknown>, T = unknown>(module: TexModule, method: string) {
  const [pending, setPending] = useState(false)
  const [error, setError] = useState<TexApiError>()
  const run = useCallback(
    async (args: A): Promise<T> => {
      setPending(true)
      setError(undefined)
      try {
        return await tex<T>(module, method, args, { post: true })
      } catch (e) {
        const err = e instanceof TexApiError ? e : new TexApiError(String(e), 0, "Error")
        setError(err)
        throw err
      } finally {
        setPending(false)
      }
    },
    [module, method],
  )
  return { run, pending, error, clearError: () => setError(undefined) }
}

/** A client-side idempotency key for one user intent (e.g. one "Book" click). */
export function idempotencyKey(prefix: string): string {
  const rnd = crypto.getRandomValues(new Uint8Array(12))
  return `${prefix}-${Array.from(rnd, (b) => b.toString(16).padStart(2, "0")).join("")}`
}
