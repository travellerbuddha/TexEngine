// The dashboard's "Today" figures open the reservations behind them (UX revision 2026-10): today's
// arrivals and departures are links to the reservation list for that day, which holds exactly as many
// reservations as the figure says (crs.reservations(arriving=…, departing=…), the dashboard's statuses).
//   TEX_E2E_BASE=http://localhost:5173 TEX_E2E_PASSWORD=… npx playwright test -c e2e dashboard-links
import { expect, test } from "@playwright/test"
import { login, pageApi, pageApiOk, texPath, trackErrors, uniqueRunId } from "./helpers"
import { Budget } from "./flows/budget"

test.use({ locale: "en-US" })

const HOTEL = "Aurora Beach Resort"

test("today's arrivals and departures open the list of exactly those reservations", async ({ page }, testInfo) => {
  test.setTimeout(120_000)
  const noErrors = trackErrors(page)
  await login(page, "revenue@demo.tex")
  await page.goto(texPath("/tex"))
  const hotel = page.getByRole("banner").getByRole("combobox", { name: "Hotel" })
  if (await hotel.count()) await hotel.selectOption(HOTEL)

  // someone arriving today (booked through the API as the revenue manager)
  const day = (await pageApiOk<{ today: { date: string } }>(page, "kamra.tex.api.reports.dashboard", { property: HOTEL })).today.date
  const tomorrow = new Date(`${day}T12:00:00Z`)
  tomorrow.setUTCDate(tomorrow.getUTCDate() + 1)
  const s = await pageApi<{ properties: { offers: { refundable?: boolean; rooms: { offer_key: string }[] }[] }[] }>(page, "kamra.tex.api.ui_crs.search", {
    check_in: day,
    check_out: tomorrow.toISOString().slice(0, 10),
    rooms: [{ adults: 2, children: [] }],
    market: "DE",
    properties: [HOTEL],
  })
  const offer = s.ok ? (s.message.properties[0]?.offers.find((o) => o.refundable) ?? s.message.properties[0]?.offers[0]) : undefined
  if (offer) {
    const q = await pageApi<{ quote_id: string }>(page, "kamra.tex.api.crs.quote", { offer_key: offer.rooms[0].offer_key })
    if (q.ok) {
      const run = uniqueRunId()
      await pageApi(page, "kamra.tex.api.ui_crs.book", {
        quote_ids: [q.message.quote_id],
        guest: { first_name: "Ada", last_name: `Today ${run}`, email: `today.${run.toLowerCase()}@example.com` },
        payment_method: "Pay at Hotel",
        confirm_without_payment: 1,
        idempotency_key: `e2e-today-${run}`,
      })
    }
  }

  const budget = await Budget.attach(page)
  for (const [kind, param, chip] of [
    ["arrivals", "arriving", "Arrivals on"],
    ["departures", "departing", "Departures on"],
  ] as const) {
    await page.goto(texPath("/tex"))
    const link = page.getByRole("link", { name: new RegExp(`^Today's ${kind}: \\d+ — open the list$`) })
    await expect(link).toBeVisible()
    const n = Number((await link.getAttribute("aria-label"))!.match(/: (\d+)/)![1])
    budget.start()
    await link.click()
    await expect(page).toHaveURL(new RegExp(`[?&]${param}=${day}(&|$)`))
    await budget.stop()
    await expect(page.getByText(new RegExp(`^${chip} `))).toBeVisible()
    const rows = page.locator("main table tbody tr")
    testInfo.annotations.push({ type: `today's ${kind}`, description: String(n) })
    if (n === 0) await expect(page.getByText("No reservation matches").filter({ visible: true })).toHaveCount(1)
    else await expect(rows).toHaveCount(Math.min(n, 25))
    // the chip's × shows every date again
    await page.getByRole("button", { name: "Show every date" }).click()
    await expect(page).not.toHaveURL(new RegExp(`${param}=`))
  }
  const c = await budget.counts()
  testInfo.annotations.push({ type: "budget: dashboard figure → its list", description: `${c.clicks / 2} click each` })
  noErrors()
})
