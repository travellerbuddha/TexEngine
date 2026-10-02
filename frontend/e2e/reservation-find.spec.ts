// Success criterion of the UX revision (2026-10): staff find a reservation without help.
// - the list searches the hotel chosen in the header; "All my hotels" is an explicit choice;
// - a search that finds nothing in that hotel offers the other hotels in one click;
// - the command palette ("Search or jump to…", Ctrl+K) finds a reservation by number or e-mail in every hotel;
// - the breadcrumb goes back to the list as it was left (its search and hotel choice).
// The channel's own booking number (an OTA reference) is matched too: covered by
// kamra.tex.tests.integration.test_reservation_search (channel bookings only arrive signed).
//   TEX_E2E_BASE=http://localhost:5173 TEX_E2E_PASSWORD=… npx playwright test -c e2e reservation-find
import { expect, test } from "@playwright/test"
import { login, pageApi, stayDates, texPath, trackErrors, uniqueRunId } from "./helpers"
import { Budget } from "./flows/budget"

test.use({ locale: "en-US" })

test("a reservation of another hotel: found from the list in one click, and from the palette by its e-mail", async ({ page }, testInfo) => {
  const noErrors = trackErrors(page)
  await login(page, "revenue@demo.tex")
  await page.goto(texPath("/tex/reservations"))

  // a confirmed stay at the city hotel (set up through the API)
  const run = uniqueRunId()
  const surname = `Findme ${run}`
  const email = `find.${run.toLowerCase()}@example.com`
  const { checkIn, checkOut } = stayDates(120, 2)
  const s = await pageApi<{ properties: { offers: { refundable?: boolean; rooms: { offer_key: string }[] }[] }[] }>(page, "kamra.tex.api.ui_crs.search", {
    check_in: checkIn,
    check_out: checkOut,
    rooms: [{ adults: 2, children: [] }],
    market: "DE",
    properties: ["Aurora City Hotel"],
  })
  expect(s.ok, JSON.stringify(s.body).slice(0, 300)).toBeTruthy()
  const offers = s.message.properties[0].offers
  const offer = offers.find((o) => o.refundable) ?? offers[0]
  const q = await pageApi<{ quote_id: string }>(page, "kamra.tex.api.crs.quote", { offer_key: offer.rooms[0].offer_key })
  expect(q.ok, JSON.stringify(q.body).slice(0, 300)).toBeTruthy()
  const bk = await pageApi<{ booking: string; status: string }>(page, "kamra.tex.api.ui_crs.book", {
    quote_ids: [q.message.quote_id],
    guest: { first_name: "Mia", last_name: surname, email },
    payment_method: "Pay at Hotel",
    confirm_without_payment: 1,
    idempotency_key: `e2e-find-${run}`,
  })
  expect(bk.ok, JSON.stringify(bk.body).slice(0, 300)).toBeTruthy()

  // the screen works on the beach resort
  const hotel = page.getByRole("banner").getByRole("combobox", { name: "Hotel" })
  await hotel.selectOption("Aurora Beach Resort")
  await expect(page.getByLabel("Hotel", { exact: true }).last()).toHaveValue("Aurora Beach Resort")

  const budget = await Budget.attach(page)
  budget.start()
  await budget.fill(page.getByRole("searchbox"), surname)
  await page.keyboard.press("Enter")
  // nothing there: said, with the way to the other hotels
  await expect(page.getByText(/^Nothing matches at Aurora Beach Resort\./)).toBeVisible()
  await page.getByRole("button", { name: "Search all my hotels" }).last().click()
  await expect(page).toHaveURL(/property=all/)
  const row = page.locator("main table tbody tr").filter({ hasText: surname })
  await expect(row).toHaveCount(1)
  await expect(row).toContainText("Aurora City Hotel")
  await row.click()
  await expect(page.getByRole("heading", { level: 1, name: /RES-/ })).toBeVisible()
  await expect(page.getByText(new RegExp(`${surname} · Aurora City Hotel`))).toBeVisible()
  await budget.stop()
  const c = await budget.counts()
  testInfo.annotations.push({ type: "budget: find in another hotel", description: `${c.clicks} clicks, ${c.modals} dialogs` })
  const name = (await page.getByRole("heading", { level: 1 }).innerText()).match(/RES-[\w-]+/)?.[0]
  expect(name).toBeTruthy()

  // back to the list as it was left
  await page.getByRole("navigation", { name: "Breadcrumb" }).getByRole("link", { name: "Reservations" }).click()
  await expect(page).toHaveURL(/property=all/)
  await expect(page.getByRole("searchbox")).toHaveValue(surname)
  await expect(page.locator("main table tbody tr").filter({ hasText: surname })).toHaveCount(1)

  // a hotel chosen right after Enter stays chosen: the search box's debounce (350 ms) never undoes it
  const search = page.getByRole("searchbox")
  await search.fill(email)
  await search.press("Enter")
  await page.locator("main").getByLabel("Hotel", { exact: true }).selectOption("Aurora City Hotel")
  await page.waitForTimeout(700) // past the debounce: the URL must not fall back
  await expect(page).toHaveURL(/[?&]property=Aurora\+City\+Hotel(&|$)/)
  await expect(page).toHaveURL(new RegExp(`[?&]q=${encodeURIComponent(email).replace(/\./g, "\\.")}(&|$)`))
  await expect(page.locator("main table tbody tr").filter({ hasText: surname })).toHaveCount(1)

  // a row opened just before that debounce fires stays open: the list, left already, never pulls the
  // page back (typed and clicked inside the page, so the click lands 5 ms before the 350 ms are up)
  await page.evaluate(async (who) => {
    const input = document.querySelector<HTMLInputElement>('main input[type="search"]')!
    Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")!.set!.call(input, `${input.value} `)
    input.dispatchEvent(new Event("input", { bubbles: true }))
    await new Promise((r) => setTimeout(r, 345))
    Array.from(document.querySelectorAll<HTMLElement>("main table tbody tr")).find((tr) => tr.textContent?.includes(who))!.click()
  }, surname)
  await expect(page.getByRole("heading", { level: 1, name: new RegExp(name ?? "RES-") })).toBeVisible()
  await page.waitForTimeout(700) // past the debounce: the detail must still be open
  await expect(page).toHaveURL(new RegExp(`/tex/reservations/${name}$`))

  // the palette: an e-mail finds it in every hotel, first in the list
  await page.goto(texPath("/tex"))
  await page.getByRole("button", { name: /^Search or jump to/ }).click()
  const palette = page.getByRole("dialog", { name: "Command palette" })
  await palette.getByRole("combobox").fill(email)
  const option = palette.getByRole("option", { name: new RegExp(`${surname} · ${name}`) })
  await expect(option).toBeVisible()
  await expect(palette.getByRole("option").first()).toHaveText(new RegExp(name ?? "RES-"))
  await page.keyboard.press("Enter")
  await expect(page).toHaveURL(new RegExp(`/tex/reservations/${name}$`))
  noErrors()
})
