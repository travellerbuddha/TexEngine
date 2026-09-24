// G-46 (ADR-059): commercial reports. The revenue manager reports on the Aurora group:
// the filters (scope, stay dates, grouping, market) drive the request the page makes; the
// totals it shows are the server's decimals per currency; switching view keeps the filters;
// "Contract vs selling" reconciles to the cent (revenue = accommodation + extras + taxes on top
// + stays without a contract cost; contract cost + margin = accommodation); the cancellation
// view shows its totals; at 375 px the page never scrolls sideways.
//   TEX_E2E_BASE=http://test.localhost:8000 TEX_E2E_PASSWORD=… npx playwright test -c e2e reports
import { expect, test, type Page, type Response } from "@playwright/test"
import { isoDate, login, texPath, trackErrors } from "./helpers"
import { displayAmount } from "./flows/contracts"

const REVENUE = "revenue@demo.tex"
const GROUP = "Aurora Riviera Collection"

type Totals = Record<string, Record<string, string | number | null>>
interface Report {
  view: string
  scope: { level: string; name: string | null; hotels: string[] }
  group_by: string | null
  cost_visible: boolean
  rows: { key: string; currency?: string }[]
  totals: Totals
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

/** The next report the page loads for `view` whose request matches `params`. */
function nextReport(page: Page, view: string, params: Record<string, string> = {}) {
  return page
    .waitForResponse((r: Response) => {
      const u = new URL(r.url())
      if (u.pathname !== "/api/method/kamra.tex.api.reports.report" || !r.ok()) return false
      if (u.searchParams.get("view") !== view) return false
      return Object.entries(params).every(([k, v]) => u.searchParams.get(k) === v)
    })
    .then(async (r) => ((await r.json()) as { message: Report }).message)
}

/** "€1,234.50": the currency's symbol (en-GB) before the exact decimal. */
async function moneyText(page: Page, amount: string, currency: string) {
  const symbol = await page.evaluate(
    (c) => new Intl.NumberFormat("en-GB", { style: "currency", currency: c }).formatToParts(0).find((p) => p.type === "currency")?.value ?? c,
    currency,
  )
  return `${amount.startsWith("-") ? "-" : ""}${symbol}${displayAmount(amount.replace(/^-/, ""))}`
}

/** A 2-decimal money string in cents, exactly (never a float). */
const cents = (s: unknown) => {
  const [i, f = ""] = String(s).replace(/^-/, "").split(".")
  const v = BigInt(i) * 100n + BigInt((f + "00").slice(0, 2))
  return String(s).startsWith("-") ? -v : v
}

/** The page never scrolls sideways (tables scroll inside their own box). */
async function noSidewaysScroll(page: Page) {
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth)
  expect(overflow, "horizontal page scroll").toBeLessThanOrEqual(0)
}

const STAY_FROM = isoDate(-365)
const STAY_TO = isoDate(400)

test("revenue manager: filters, view switch, reconciled totals, cancellations, 375 px", async ({ page }) => {
  const noErrors = trackErrors(page)
  await english(page)
  await login(page, REVENUE)
  await page.goto(texPath("/tex/reports"))
  await expect(page.getByRole("heading", { level: 1, name: "Reports" })).toBeVisible()

  // filters: the whole group, stays over ~2 years, grouped by hotel
  await page.getByLabel("Report on", { exact: true }).selectOption({ label: GROUP })
  await expect(page).toHaveURL(/[?&]scope=Group(%3A|:)Aurora/)
  await page.getByLabel("From", { exact: true }).fill(STAY_FROM)
  await expect(page).toHaveURL(new RegExp(`[?&]from=${STAY_FROM}`))
  await page.getByLabel("To", { exact: true }).fill(STAY_TO)
  await expect(page).toHaveURL(new RegExp(`[?&]to=${STAY_TO}`))
  const byHotel = nextReport(page, "production", { level: "Group", name: GROUP, group_by: "hotel", stay_from: STAY_FROM, stay_to: STAY_TO })
  await page.getByLabel("Group by", { exact: true }).selectOption("hotel")
  const prod = await byHotel
  expect(prod.scope.hotels.sort()).toEqual(["Aurora Beach Resort", "Aurora City Hotel"])
  expect(prod.cost_visible).toBe(true)
  for (const r of prod.rows) expect(prod.scope.hotels).toContain(r.key)
  await expect(page).toHaveURL(/[?&]group=hotel/)

  // totals: per currency, exactly the server's decimals, in the tiles and the table footer
  const totals = page.getByRole("region", { name: "Totals" })
  const ccys = Object.keys(prod.totals).sort()
  expect(ccys.length, "the demo group has sales in the window").toBeGreaterThan(0)
  for (const c of ccys) {
    const revenue = String(prod.totals[c].revenue)
    await expect(totals).toContainText(await moneyText(page, revenue, c))
    // the table's total row (footer) shows the same figure
    const totalRow = page.getByRole("table").getByRole("row").filter({ has: page.getByRole("rowheader", { name: /^Total/ }) })
    await expect(totalRow.first()).toContainText(await moneyText(page, revenue, c))
  }

  // the market filter narrows the same request
  const de = nextReport(page, "production", { level: "Group", market: "DE", group_by: "hotel" })
  await page.getByLabel("Market", { exact: true }).selectOption("DE")
  const inDe = await de
  for (const c of Object.keys(inDe.totals)) expect(Number(inDe.totals[c].bookings)).toBeLessThanOrEqual(Number(prod.totals[c]?.bookings ?? 0))
  const all = nextReport(page, "production", { level: "Group", group_by: "hotel" })
  await page.getByLabel("Market", { exact: true }).selectOption("")
  await all

  // view switch: contract vs selling keeps the scope, dates and grouping, and reconciles
  const margin = nextReport(page, "margin", { level: "Group", name: GROUP, stay_from: STAY_FROM, stay_to: STAY_TO })
  await page.getByRole("navigation", { name: "Reports" }).getByRole("link", { name: "Contract vs selling" }).click()
  const m = await margin
  await expect(page).toHaveURL(/\/tex\/reports\/margin\?/)
  for (const [c, t] of Object.entries(m.totals)) {
    expect(cents(t.accommodation) + cents(t.extras) + cents(t.taxes) + cents(t.not_from_contract), `revenue ${c}`).toBe(cents(t.revenue))
    expect(cents(t.cost) + cents(t.margin), `accommodation ${c}`).toBe(cents(t.accommodation))
    for (const k of ["revenue", "accommodation", "cost", "margin"]) await expect(totals).toContainText(await moneyText(page, String(t[k]), c))
  }
  for (const r of m.rows as unknown as Record<string, string>[]) {
    expect(cents(r.cost) + cents(r.margin)).toBe(cents(r.accommodation))
    expect(cents(r.accommodation) + cents(r.extras) + cents(r.taxes) + cents(r.not_from_contract)).toBe(cents(r.revenue))
  }
  await expect(page.getByLabel("Report on", { exact: true })).toHaveValue(`Group:${GROUP}`)

  // cancellations: the same selection, whole stays; the totals the page shows
  const cxl = nextReport(page, "cancellation", { level: "Group", name: GROUP })
  await page.getByRole("navigation", { name: "Reports" }).getByRole("link", { name: "Cancellations" }).click()
  const x = await cxl
  for (const [c, t] of Object.entries(x.totals)) {
    await expect(totals).toContainText(await moneyText(page, String(t.cancelled_value), c))
    await expect(totals).toContainText(await moneyText(page, String(t.fees), c))
  }

  // a room type belongs to a hotel: choosing another scope clears it (a hidden filter would empty the report)
  const room = page.getByLabel("Room type", { exact: true })
  const firstRoom = await room.locator("option").nth(1).getAttribute("value")
  expect(firstRoom, "the group has room types").toBeTruthy()
  await room.selectOption(firstRoom!)
  await expect(page).toHaveURL(/[?&]room=/)
  await page.getByLabel("Report on", { exact: true }).selectOption({ label: "Aurora City Hotel" })
  await expect(page).not.toHaveURL(/[?&]room=/)
  await expect(page.getByLabel("Room type", { exact: true })).toHaveValue("")

  // a phone: filters and tables fit, nothing scrolls sideways
  await page.setViewportSize({ width: 375, height: 812 })
  for (const path of ["/tex/reports/margin", "/tex/reports"]) {
    const loaded = nextReport(page, path.endsWith("margin") ? "margin" : "production", { level: "Group" })
    await page.goto(texPath(`${path}?scope=Group:${encodeURIComponent(GROUP)}&period=custom&from=${STAY_FROM}&to=${STAY_TO}&group=hotel`))
    await loaded
    await expect(page.getByRole("region", { name: "Totals" })).toBeVisible()
    await noSidewaysScroll(page)
  }
  noErrors()
})
