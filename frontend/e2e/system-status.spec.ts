// ADR-047: Settings → System status. The platform administrator sees the platform checks
// (scheduler, workers, encryption key, e-mail queue), the operations checks and the
// uptime-monitor address; refresh re-reads the checks. The Aurora Beach admin (system.monitor
// at one hotel) sees only the operations checks of that hotel, and the server refuses the
// other hotel. The reservations agent (no system.monitor) is refused. The guest ping answers
// booleans only.
//   TEX_E2E_BASE=http://test.localhost:8000 TEX_E2E_PASSWORD=… npx playwright test -c e2e system-status
import { expect, request as playwrightRequest, test, type Page, type Response } from "@playwright/test"
import { ADMIN_PASSWORD, login, texPath, trackErrors } from "./helpers"

const HOTEL_ADMIN = "beach.gm@demo.tex"
const AGENT = "agent@demo.tex"
const BEACH = "Aurora Beach Resort"
const CITY = "Aurora City Hotel"
const BASE = process.env.TEX_E2E_BASE || "http://test.localhost:8000"

interface Status {
  overall: "ok" | "warn" | "fail"
  platform: boolean
  hotels: string[] | null
  checks: { key: string; scope: string; status: string; properties?: string[] }[]
}

async function english(page: Page) {
  await page.addInitScript(() => {
    try {
      localStorage.setItem("tex-lang", "en")
    } catch {
      /* storage blocked: the default language is English */
    }
  })
}

/** The status endpoint is a read (GET only), in the page's session. */
async function statusStatus(page: Page, args: Record<string, string> = {}) {
  const r = await page.request.get("/api/method/kamra.tex.api.system.status", { params: args })
  return r.status()
}

function nextStatus(page: Page) {
  return page
    .waitForResponse((r: Response) => new URL(r.url()).pathname === "/api/method/kamra.tex.api.system.status" && r.ok())
    .then(async (r) => ((await r.json()) as { message: Status }).message)
}

test("platform administrator: platform and operations checks, refresh, uptime address", async ({ page }) => {
  const noErrors = trackErrors(page)
  await english(page)
  await login(page, "Administrator", ADMIN_PASSWORD)
  const loaded = nextStatus(page)
  await page.goto(texPath("/tex/settings/status"))
  const status = await loaded
  expect(status.platform).toBe(true)
  await expect(page.getByRole("link", { name: "System status" })).toHaveAttribute("aria-current", "page")
  await expect(page.getByTestId("status-overall")).toBeVisible()
  const platform = page.getByRole("list", { name: "Platform" })
  for (const key of ["scheduler", "scheduler.jobs", "workers", "encryption_key", "mail.queue"]) {
    await expect(platform.getByTestId(`status-check-${key}`)).toHaveCount(1)
  }
  await expect(page.getByRole("list", { name: "Operations" }).getByTestId("status-check-outbox.pms")).toHaveCount(1)
  // every check shows the status the server gave it
  for (const c of status.checks) await expect(page.getByTestId(`status-check-${c.key}`)).toHaveAttribute("data-status", c.status)
  await expect(page.getByText(/\/api\/method\/kamra\.tex\.api\.system\.ping$/)).toBeVisible()

  const again = nextStatus(page)
  await page.getByRole("button", { name: "Refresh" }).click()
  expect((await again).checks.length).toBe(status.checks.length)
  noErrors()
})

test("hotel admin: only their hotel's operations checks; the other hotel is refused", async ({ page }) => {
  const noErrors = trackErrors(page)
  await english(page)
  await login(page, HOTEL_ADMIN)
  const loaded = nextStatus(page)
  await page.goto(texPath("/tex/settings/status"))
  const status = await loaded
  expect(status.platform).toBe(false)
  expect(status.hotels).toEqual([BEACH])
  expect(status.checks.some((c) => c.scope === "platform")).toBe(false)
  for (const c of status.checks) for (const p of c.properties ?? []) expect(p).toBe(BEACH)
  await expect(page.getByRole("list", { name: "Platform" })).toHaveCount(0)
  await expect(page.getByRole("list", { name: "Operations" })).toBeVisible()
  await expect(page.getByText(`Your hotels: ${BEACH}`)).toBeVisible()
  await expect(page.getByText(/kamra\.tex\.api\.system\.ping/)).toHaveCount(0)

  expect(await statusStatus(page, { property: BEACH })).toBe(200)
  expect(await statusStatus(page, { property: CITY })).toBe(403)
  noErrors()
})

test("reservations agent: no system status", async ({ page }) => {
  await english(page)
  await login(page, AGENT)
  expect(await statusStatus(page)).toBe(403)
  await page.goto(texPath("/tex/settings/status"))
  await expect(page.getByTestId("status-overall")).toHaveCount(0)
})

test("guest ping: booleans only", async () => {
  const anon = await playwrightRequest.newContext({ baseURL: BASE })
  const r = await anon.get("/api/method/kamra.tex.api.system.ping")
  expect([200, 503]).toContain(r.status())
  const body = (await r.json()) as { message: Record<string, unknown> }
  expect(Object.keys(body.message).every((k) => ["ok", "db", "cache", "scheduler"].includes(k))).toBe(true)
  expect(Object.values(body.message).every((v) => typeof v === "boolean")).toBe(true)
  expect(body.message.ok).toBe(r.status() === 200)
  await anon.dispose()
})
