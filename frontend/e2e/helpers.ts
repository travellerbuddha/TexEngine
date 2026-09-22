import { expect, type APIRequestContext, type Page } from "@playwright/test"

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

/** A future stay window that never collides between runs. */
export function stayDates(offsetDays: number, nights: number) {
  const base = new Date()
  base.setDate(base.getDate() + offsetDays + (Math.floor(Date.now() / 86400000) % 20))
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
