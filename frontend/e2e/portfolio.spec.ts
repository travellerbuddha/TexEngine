// G-25 (ADR-038): the portfolio dashboard. The revenue manager reports on both Aurora
// hotels: Dashboard → Portfolio lists both, the key figures are money strings with their
// currency (exactly the server's decimals, per currency, never added across currencies),
// choosing one hotel as the scope narrows the table to it, and the alerts section renders
// (it may be empty). The Aurora Beach Resort admin reports on one hotel only: the portfolio
// view is not offered, and the server's portfolio of the whole group holds only that hotel.
//   TEX_E2E_BASE=http://test.localhost:8000 TEX_E2E_PASSWORD=… npx playwright test -c e2e portfolio
import { expect, test, type Page, type Response } from "@playwright/test"
import { esc, login, pageApi, texPath, trackErrors } from "./helpers"
import { displayAmount } from "./flows/contracts"

const REVENUE = "revenue@demo.tex"
const HOTEL_ADMIN = "beach.gm@demo.tex"
const BEACH = "Aurora Beach Resort"
const CITY = "Aurora City Hotel"
const GROUP = "Aurora Riviera Collection"

type Amounts = Record<string, string>
interface Portfolio {
  scope: { level: string; name: string | null; hotels: number }
  from: string
  to: string
  today: string
  totals: {
    today_value: Amounts
    booking_value: Amounts
    direct_value: Amounts
    call_centre_value: Amounts
    cancelled_value: Amounts
    pending_payment_value: Amounts
    open_balance_value: Amounts
    abandoned_value: Amounts
  }
  hotels: { hotel: string; hotel_name: string; booking_value: Amounts }[]
  alerts: { hotel: string; hotel_name?: string }[]
  alerts_total: number
}

/** KPI tiles and the totals each shows (label → amounts). */
const TILES: [string, keyof Portfolio["totals"]][] = [
  ["Sales today", "today_value"],
  ["Booking value", "booking_value"],
  ["Direct revenue", "direct_value"],
  ["Call-centre revenue", "call_centre_value"],
  ["Cancellations", "cancelled_value"],
  ["Waiting for payment", "pending_payment_value"],
  ["Open balances", "open_balance_value"],
  ["Abandoned opportunities", "abandoned_value"],
]

/** One money line as the app shows it in English: currency symbol or code, then the amount. */
const MONEY_LINE = /^-?(?:[^\d\s,.-]{1,3}|[A-Z]{3}\s?)\d{1,3}(?:,\d{3})*\.\d{2,3}$/

async function english(page: Page) {
  await page.addInitScript(() => {
    try {
      localStorage.setItem("tex-lang", "en")
    } catch {
      /* storage blocked: the default language is English */
    }
  })
}

/** The portfolio figures the page loads next (the request the UI makes, not a second one). */
function nextPortfolio(page: Page, match: (u: URL) => boolean = () => true) {
  return page
    .waitForResponse((r: Response) => {
      const u = new URL(r.url())
      return u.pathname === "/api/method/kamra.tex.api.reports.portfolio" && r.ok() && match(u)
    })
    .then(async (r) => ((await r.json()) as { message: Portfolio }).message)
}

/** "€1,234.50": the currency's symbol (as Intl gives it in en-GB) before the exact decimal. */
async function moneyText(page: Page, amount: string, currency: string) {
  const symbol = await page.evaluate(
    (c) => new Intl.NumberFormat("en-GB", { style: "currency", currency: c }).formatToParts(0).find((p) => p.type === "currency")?.value ?? c,
    currency,
  )
  return `${amount.startsWith("-") ? "-" : ""}${symbol}${displayAmount(amount.replace(/^-/, ""))}`
}

/** Lines of text of an element (stacked amounts are one line per currency). */
const lines = async (text: Promise<string>) =>
  (await text)
    .split("\n")
    .map((l) => l.trim())
    .filter(Boolean)

test("revenue manager: portfolio of both hotels, money per currency, one-hotel scope, alerts", async ({ page }) => {
  const noErrors = trackErrors(page)
  await english(page)
  await login(page, REVENUE)
  await page.goto(texPath("/tex"))
  await expect(page.getByRole("heading", { level: 1, name: "Dashboard" })).toBeVisible()

  // Dashboard → Portfolio (offered: the user reports on two hotels)
  const view = page.getByRole("radiogroup", { name: "Dashboard view" })
  await expect(view.getByRole("radio", { name: "This hotel" })).toHaveAttribute("aria-checked", "true")
  const loaded = nextPortfolio(page, (u) => u.searchParams.get("level") === "All")
  await view.getByRole("radio", { name: "Portfolio" }).click()
  const all = await loaded
  await expect(page).toHaveURL(/[?&]view=portfolio(&|$)/)
  await expect(view.getByRole("radio", { name: "Portfolio" })).toHaveAttribute("aria-checked", "true")
  expect(all.scope).toMatchObject({ level: "All", hotels: 2 })
  expect(all.hotels.map((h) => h.hotel).sort()).toEqual([BEACH, CITY])
  await expect(byLabelExact(page, "Report on")).toHaveValue("All")
  await expect(page.getByText(/^2 hotels · sold /)).toBeVisible()

  // both hotels, each linking to its own dashboard
  const table = page.getByRole("table", { name: "Hotels" })
  await expect(table.locator("tbody tr")).toHaveCount(2)
  for (const h of all.hotels) {
    const tr = table.locator("tbody tr").filter({ has: page.getByRole("link", { name: new RegExp(`^${esc(h.hotel_name)}`) }) })
    await expect(tr).toHaveCount(1)
    // the hotel's booking value, per currency, exactly as the server summed it
    for (const [ccy, amount] of Object.entries(h.booking_value)) await expect(tr).toContainText(await moneyText(page, amount, ccy))
  }

  // key figures: money strings with a currency, the server's decimals exactly
  const kpis = page.getByRole("region", { name: "Key figures" })
  const todayInWindow = all.from <= all.today && all.today <= all.to
  for (const [label, key] of TILES) {
    const tile = kpis.locator("div").filter({ has: page.locator("dt", { hasText: new RegExp(`^${esc(label)}$`) }) }).last()
    const value = tile.locator("dd").first()
    await expect(value, label).toBeVisible()
    const shown = await lines(value.innerText())
    const amounts = key === "today_value" && !todayInWindow ? {} : all.totals[key]
    if (key === "today_value" && !todayInWindow) {
      expect(shown, label).toEqual(["—"])
      continue
    }
    expect(shown.length, `${label}: an amount`).toBeGreaterThan(0)
    for (const l of shown) expect(l, `${label}: a money string with its currency`).toMatch(MONEY_LINE)
    const expected = await Promise.all(Object.entries(amounts).map(([c, a]) => moneyText(page, a, c)))
    if (expected.length) expect(shown.sort(), label).toEqual(expected.sort())
  }

  // alerts of the next two weeks: the section renders, empty or grouped by hotel
  await expect(page.getByRole("heading", { level: 2, name: "Inventory and restriction alerts" })).toBeVisible()
  if (all.alerts.length === 0) await expect(page.getByText("No alerts", { exact: true })).toBeVisible()
  else
    for (const name of new Set(all.alerts.map((a) => a.hotel_name ?? a.hotel)))
      await expect(page.getByRole("heading", { level: 3, name, exact: true })).toBeVisible()

  // one hotel as the scope narrows everything to it
  const narrowed = nextPortfolio(page, (u) => u.searchParams.get("level") === "Hotel" && u.searchParams.get("name") === CITY)
  await byLabelExact(page, "Report on").selectOption({ label: CITY })
  const one = await narrowed
  expect(one.scope).toMatchObject({ level: "Hotel", name: CITY, hotels: 1 })
  expect(one.hotels.map((h) => h.hotel)).toEqual([CITY])
  await expect(page).toHaveURL(/[?&]scope=/)
  await expect(page.getByText(/^1 hotel · sold /)).toBeVisible()
  await expect(table.locator("tbody tr")).toHaveCount(1)
  await expect(table.getByRole("link", { name: new RegExp(`^${esc(CITY)}`) })).toBeVisible()
  await expect(table.getByRole("link", { name: new RegExp(`^${esc(BEACH)}`) })).toHaveCount(0)
  const booked = await lines(kpis.locator("div").filter({ has: page.locator("dt", { hasText: /^Booking value$/ }) }).last().locator("dd").first().innerText())
  const cityValue = await Promise.all(Object.entries(one.totals.booking_value).map(([c, a]) => moneyText(page, a, c)))
  if (cityValue.length) expect(booked.sort()).toEqual(cityValue.sort())
  await expect(page.getByRole("heading", { level: 2, name: "Inventory and restriction alerts" })).toBeVisible()
  noErrors()
})

test("hotel admin of one hotel: the portfolio view is not offered and covers only that hotel", async ({ page }) => {
  const noErrors = trackErrors(page)
  await english(page)
  await login(page, HOTEL_ADMIN)
  await page.goto(texPath("/tex?view=portfolio"))
  await expect(page.getByRole("heading", { level: 1, name: "Dashboard" })).toBeVisible()
  // one hotel: its own dashboard, no view switch, no portfolio table
  await expect(page.getByRole("banner")).toContainText(BEACH)
  await expect(page.getByRole("radiogroup", { name: "Dashboard view" })).toHaveCount(0)
  await expect(page.getByRole("table", { name: "Hotels" })).toHaveCount(0)
  await expect(page.getByRole("region", { name: "Key figures" }).getByText("Sales today", { exact: true })).toHaveCount(0)

  // the server agrees: whatever scope is asked, only the hotel the user reports on
  const scopes = await pageApi<{ hotels: { name: string }[] }>(page, "kamra.tex.api.reports.portfolio_scopes")
  expect(scopes.ok).toBeTruthy()
  expect(scopes.message.hotels.map((h) => h.name)).toEqual([BEACH])
  const group = await pageApi<Portfolio>(page, "kamra.tex.api.reports.portfolio", { level: "Group", name: GROUP })
  expect(group.ok, JSON.stringify(group.body).slice(0, 300)).toBeTruthy()
  expect(group.message.scope.hotels).toBe(1)
  expect(group.message.hotels.map((h) => h.hotel)).toEqual([BEACH])
  const other = await pageApi(page, "kamra.tex.api.reports.portfolio", { level: "Hotel", name: CITY })
  expect(other.ok, "another hotel of the group is refused").toBe(false)
  noErrors()
})

/** A form control by its exact label. */
const byLabelExact = (page: Page, label: string) => page.getByLabel(label, { exact: true })
