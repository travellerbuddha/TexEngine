import { expect, type APIRequestContext, type Locator, type Page } from "@playwright/test"

export const PASSWORD = process.env.TEX_E2E_PASSWORD || ""
export const ADMIN_PASSWORD = process.env.TEX_E2E_ADMIN_PASSWORD || "admin"

/** Session login through Frappe's API (cookie lands in the page's context). */
export async function login(page: Page, user: string, password = PASSWORD) {
  const r = await page.request.post("/api/method/login", { data: { usr: user, pwd: password } })
  expect(r.ok(), `login ${user}`).toBeTruthy()
}

export async function api<T>(req: APIRequestContext, method: string, args: Record<string, unknown> = {}) {
  const r = await req.post(`/api/method/${method}`, { data: args })
  const body = await r.json().catch(() => ({}))
  expect(r.ok(), `${method}: ${JSON.stringify(body).slice(0, 400)}`).toBeTruthy()
  return (body as { message: T }).message
}

/** A future stay window, spread at random over ~4 months per call so repeated runs on the
 * same bench don't sell the demo hotel out (demo contracts run to the end of next year). */
export function stayDates(offsetDays: number, nights: number) {
  const base = new Date()
  base.setDate(base.getDate() + offsetDays + Math.floor(Math.random() * 120))
  const ci = new Date(base)
  const co = new Date(base)
  co.setDate(co.getDate() + nights)
  const iso = (d: Date) => d.toISOString().slice(0, 10)
  return { checkIn: iso(ci), checkOut: iso(co) }
}

/** No uncaught page errors during a test. */
export function trackErrors(page: Page) {
  const errors: string[] = []
  page.on("pageerror", (e) => errors.push(e.message))
  return () => expect(errors, errors.join("\n")).toEqual([])
}

// ─── shared by the flows (contracts, booking, reservations) ─────────────────

const BASE = process.env.TEX_E2E_BASE || "http://test.localhost:8000"
/** The admin SPA lives under /kamra on the bench and at / on a Vite dev server (51xx). */
export const APP_PREFIX = process.env.TEX_E2E_APP_PREFIX ?? (/:51\d\d(\/|$)/.test(BASE) ? "" : "/kamra")
export const texPath = (path: string) => `${APP_PREFIX}${path}`

/** Upper-case id unique per run (base-36 time + 2 random chars), e.g. "MFX3K2QA7Z". */
export function uniqueRunId(): string {
  const rnd = Math.floor(Math.random() * 1296)
    .toString(36)
    .padStart(2, "0")
  return `${Date.now().toString(36)}${rnd}`.toUpperCase()
}

/** Local calendar date `offsetDays` from today as YYYY-MM-DD (what date inputs take). */
export function isoDate(offsetDays: number, from = new Date()): string {
  const d = new Date(from)
  d.setDate(d.getDate() + offsetDays)
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`
}

export const esc = (s: string) => s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")

/** Control by its label; required fields show "Label*", so an optional marker is accepted. */
export const byLabel = (scope: Page | Locator, label: string) => scope.getByLabel(new RegExp(`^${esc(label)}\\s*\\*?$`))

/** API call in the page's session (assertions and clean-up only). Once the bench has
 * rendered the SPA the session holds a CSRF token, which POSTs must echo. */
export async function pageApi<T = unknown>(page: Page, method: string, args: Record<string, unknown> = {}) {
  const csrf = await page.evaluate(() => (window as unknown as { csrf_token?: string }).csrf_token).catch(() => undefined)
  const r = await page.request.post(`/api/method/${method}`, {
    data: args,
    headers: csrf ? { "X-Frappe-CSRF-Token": csrf } : {},
  })
  const body = (await r.json().catch(() => ({}))) as { message?: T }
  return { ok: r.ok(), status: r.status(), body, message: body.message as T }
}

/** `api` in the page's session: `pageApi` (the CSRF token echoed) that must succeed. For calls
 * made once the page may have rendered the SPA, where a POST without the token is refused. */
export async function pageApiOk<T = unknown>(page: Page, method: string, args: Record<string, unknown> = {}) {
  const r = await pageApi<T>(page, method, args)
  expect(r.ok, `${method}: ${JSON.stringify(r.body).slice(0, 400)}`).toBeTruthy()
  return r.message
}

const isMethod = (url: string, method: string) => new URL(url).pathname.endsWith(`/api/method/${method}`)

/** The page's next call to `method` (a whitelisted path such as "kamra.tex.api.contracts.save_version")
 * answered. Start waiting before the action that sends it. */
export function answerOf(page: Page, method: string) {
  return page.waitForResponse((r) => isMethod(r.url(), method))
}

/** Hold the page's next call to `method` in flight: the server does the work at once, the page
 * hears back only on `release()`. `held` resolves once the server has answered. */
export async function holdNext(page: Page, method: string) {
  let release!: () => void
  const gate = new Promise<void>((r) => (release = r))
  let arrived!: () => void
  const held = new Promise<void>((r) => (arrived = r))
  await page.route(
    (url) => isMethod(url.href, method),
    async (route) => {
      const response = await route.fetch()
      arrived()
      await gate
      await route.fulfill({ response })
    },
    { times: 1 },
  )
  return { held, release }
}
