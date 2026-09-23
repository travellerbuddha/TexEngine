// G-91: staff date pickers start on the site's day, not the browser's. The browser sits in
// Honolulu (UTC−10) while the demo site runs on Europe/Istanbul (UTC+3), and its clock is pinned
// to a few minutes after the site's last midnight: in Honolulu that is still the day before.
// The CRS arrival default and the inventory grids must start on the site's day all the same —
// the expected day comes from the API (session.bootstrap), never from the browser's clock.
//   TEX_E2E_BASE=http://test.localhost:8000 TEX_E2E_PASSWORD=… npx playwright test -c e2e site-day
import { expect, test, type Page } from "@playwright/test"
import { byLabel, login, texPath, trackErrors } from "./helpers"

test.use({ locale: "en-US", timezoneId: "Pacific/Honolulu" })

interface ServerClock {
  time_zone: string
  /** naive wall-clock time in `time_zone` */
  now: string
  /** the site's calendar day */
  today: string
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

const addDays = (iso: string, n: number) => {
  const d = new Date(`${iso}T12:00:00Z`)
  d.setUTCDate(d.getUTCDate() + n)
  return d.toISOString().slice(0, 10)
}

/** The site's clock as the session bootstrap reports it (a GET: no CSRF token needed yet). */
async function siteClock(page: Page): Promise<ServerClock> {
  const r = await page.request.get("/api/method/kamra.tex.api.session.bootstrap")
  const body = (await r.json().catch(() => ({}))) as { message?: { server?: ServerClock } }
  expect(r.ok(), JSON.stringify(body).slice(0, 300)).toBeTruthy()
  const server = body.message?.server
  expect(server?.today, "session.bootstrap carries server.today").toMatch(/^\d{4}-\d{2}-\d{2}$/)
  return server as ServerClock
}

/** Pin the browser clock (Date only, timers keep running) to five minutes after the site's last
 * midnight: the real instant, read off the server's wall clock. */
async function pinJustAfterSiteMidnight(page: Page, server: ServerClock) {
  const wall = Date.parse(`${server.now.slice(0, 19)}Z`) // the site's wall-clock digits
  const sinceMidnight = wall - Date.parse(`${server.today}T00:00:00Z`)
  await page.clock.setFixedTime(Date.now() - sinceMidnight + 5 * 60_000)
}

/** The browser's own calendar day, which must still be before the site's (else nothing is tested). */
async function browserDayBefore(page: Page, server: ServerClock): Promise<string> {
  const day = await page.evaluate(() => {
    const d = new Date()
    return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`
  })
  expect(day < server.today, `the browser (${day}) is still before the site's day (${server.today})`).toBeTruthy()
  return day
}

test("CRS: the arrival defaults and limits follow the site's day, not the browser's", async ({ page }) => {
  const noErrors = trackErrors(page)
  await english(page)
  await login(page, "agent@demo.tex")
  const server = await siteClock(page)
  await pinJustAfterSiteMidnight(page, server)

  await page.goto(texPath("/tex/crs/call-center"))
  await expect(page.getByRole("heading", { level: 1, name: "Call Center" })).toBeVisible()
  const browserDay = await browserDayBefore(page, server)
  const checkIn = byLabel(page, "Check-in")
  // a new search: tomorrow on the site's calendar, two nights; nothing before the site's today
  await expect(checkIn).toHaveValue(addDays(server.today, 1))
  await expect(byLabel(page, "Check-out")).toHaveValue(addDays(server.today, 3))
  await expect(checkIn).toHaveAttribute("min", server.today)

  // the browser's "today" is already the past for the hotel: refused here, before any search
  let searched = 0
  page.on("request", (r) => {
    if (r.url().includes("ui_crs.search")) searched++
  })
  await checkIn.fill(browserDay)
  await page.getByRole("form", { name: "Search" }).getByRole("button", { name: /^Search/ }).click()
  await expect(page.getByText("Check-in cannot be in the past.").first()).toBeVisible()
  expect(searched, "no search is sent for a past arrival").toBe(0)
  noErrors()
})

test("Inventory: the rooms and extras grids start on the site's day", async ({ page }) => {
  const noErrors = trackErrors(page)
  await english(page)
  await login(page, "revenue@demo.tex")
  const server = await siteClock(page)
  await pinJustAfterSiteMidnight(page, server)

  // the rooms grid asks the server for the site's day and shows it as its start
  const ari = page.waitForRequest((r) => r.url().includes("kamra.tex.api.crs.ari_grid"))
  await page.goto(texPath("/tex/inventory"))
  await browserDayBefore(page, server)
  expect(new URL((await ari).url()).searchParams.get("start")).toBe(server.today)
  await expect(byLabel(page, "Start date")).toHaveValue(server.today)
  await expect(page.getByRole("button", { name: "Today", exact: true })).toBeDisabled()

  // moved away and back: "Today" returns to the site's day
  await byLabel(page, "Start date").fill(addDays(server.today, 21))
  await expect(page.getByRole("button", { name: "Today", exact: true })).toBeEnabled()
  await page.getByRole("button", { name: "Today", exact: true }).click()
  await expect(byLabel(page, "Start date")).toHaveValue(server.today)

  // the limited-extras grid too
  const extras = page.waitForRequest((r) => r.url().includes("kamra.tex.api.crs.extras_grid"))
  await page.goto(texPath("/tex/inventory/extras"))
  expect(new URL((await extras).url()).searchParams.get("start")).toBe(server.today)
  await expect(byLabel(page, "Start date")).toHaveValue(server.today)
  noErrors()
})
