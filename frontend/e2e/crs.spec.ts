// CRS journeys (R-19–R-23, R-58): a keyboard-only call-centre booking by an agent, and a
// reservation change where the revenue manager sees OLD vs NEW price before applying.
//   TEX_E2E_BASE=http://test.localhost:8000 TEX_E2E_PASSWORD=… npx playwright test -c e2e crs
import { expect, test, type Page } from "@playwright/test"
import { byLabel, login, pageApi, stayDates, texPath, trackErrors, uniqueRunId } from "./helpers"
import { applyChange, openReservation, proposeChange, readLockedPrice, readRevisions } from "./flows/reservations"

// typed dates follow the browser locale (mm/dd/yyyy); the UI language is pinned per page
test.use({ locale: "en-US" })

async function english(page: Page) {
  await page.addInitScript(() => {
    try {
      localStorage.setItem("tex-lang", "en")
    } catch {
      /* storage blocked: the default language is English */
    }
  })
}

const mdy = (iso: string) => `${iso.slice(5, 7)}${iso.slice(8, 10)}${iso.slice(0, 4)}`
const addDays = (iso: string, n: number) => {
  const d = new Date(`${iso}T12:00:00Z`)
  d.setUTCDate(d.getUTCDate() + n)
  return d.toISOString().slice(0, 10)
}

test("Call Center: keyboard-only booking by an agent", async ({ page }) => {
  const noErrors = trackErrors(page)
  await english(page)
  await login(page, "agent@demo.tex")
  await page.goto(texPath("/tex/crs/call-center"))
  await expect(page.getByRole("heading", { level: 1, name: "Call Center" })).toBeVisible()
  const kb = page.keyboard

  // Alt+C: find the caller; Enter takes the first match
  await kb.press("Alt+KeyC")
  await expect(page.getByRole("combobox", { name: "Find caller" })).toBeFocused()
  await kb.type("Schmidt", { delay: 20 })
  await expect(page.getByRole("option", { name: /Schmidt/ }).first()).toBeVisible()
  await kb.press("Enter")
  await expect(page.getByRole("button", { name: "Clear caller" })).toBeVisible()

  // Alt+S without a market: validation puts the cursor on the market; type to choose it
  await kb.press("Alt+KeyS")
  const market = byLabel(page, "Market")
  await expect(market).toBeFocused()
  await kb.type("Germ")
  await expect(market).toHaveValue("DE")

  // dates typed into check-in; check-out follows with the same stay length
  const { checkIn } = stayDates(75, 2)
  await byLabel(page, "Check-in").focus()
  await kb.type(mdy(checkIn))
  await expect(byLabel(page, "Check-in")).toHaveValue(checkIn)
  await expect(byLabel(page, "Check-out")).toHaveValue(addDays(checkIn, 2))

  // Alt+S searches; focus lands in the offer list
  await Promise.all([page.waitForResponse((r) => r.url().includes("ui_crs.search") && r.ok()), kb.press("Alt+KeyS")])
  const offers = page.getByRole("listbox", { name: "Offers" })
  await expect(offers).toBeFocused()
  await expect(offers.getByRole("option").first()).toBeVisible()

  // ↓ / Enter: quote the highlighted offer; validity is on the server clock, with its zone
  await kb.press("ArrowDown")
  await Promise.all([page.waitForResponse((r) => r.url().includes("ui_crs.quote_summary") && r.ok()), kb.press("Enter")])
  await expect(page.getByText(/Valid until .+\(.+\) · \d+:\d{2} left/).first()).toBeVisible()

  // Alt+G: the caller's details are already in the guest form
  await kb.press("Alt+KeyG")
  await expect(byLabel(page, "First name")).toBeFocused()
  await expect(byLabel(page, "First name")).not.toHaveValue("")

  // Alt+P: payment; ↓ picks the next method (bank transfer)
  await kb.press("Alt+KeyP")
  await expect(page.getByRole("radio", { name: /Card/ })).toBeFocused()
  await Promise.all([page.waitForResponse((r) => r.url().includes("ui_crs.quote_summary") && r.ok()), kb.press("ArrowDown")])
  await expect(page.getByRole("radio", { name: /Bank transfer/ })).toBeChecked()
  // agents may not confirm without payment (reservation.confirm_unpaid): a hint, no tick box
  await expect(page.getByText("Payment is due now.", { exact: false })).toBeVisible()
  await expect(page.getByRole("checkbox", { name: /Confirm without payment/ })).toHaveCount(0)

  // Ctrl+Enter books; the staff answer never carries the guest's manage token
  const [booked] = await Promise.all([page.waitForResponse((r) => r.url().includes("ui_crs.book")), kb.press("Control+Enter")])
  expect(booked.ok(), `book ${booked.status()}`).toBeTruthy()
  const b = (await booked.json()).message as { booking: string; status: string; manage_token?: string }
  expect(b.booking).toMatch(/^TEX-/)
  expect(b.manage_token).toBeUndefined()
  expect(b.status).toBe("Pending Payment")
  await expect(page.getByRole("heading", { name: "Booking held — awaiting payment" })).toBeFocused()
  await expect(page.getByText(b.booking).first()).toBeVisible()
  noErrors()
})

test("Call Center on a Mac: Option types characters in fields; ⌃⌥ runs the shortcut (O-32)", async ({ page }) => {
  const noErrors = trackErrors(page)
  // the page reads the platform once, when its module loads
  await page.addInitScript(() => Object.defineProperty(Navigator.prototype, "platform", { get: () => "MacIntel", configurable: true }))
  await english(page)
  await page.context().grantPermissions(["clipboard-read", "clipboard-write"])
  await login(page, "agent@demo.tex")
  await page.goto(texPath("/tex/crs/call-center"))
  await expect(page.getByRole("heading", { level: 1, name: "Call Center" })).toBeVisible()
  // a Mac shows the shortcuts that work everywhere, fields included
  await expect(page.getByText("⌃⌥S").first()).toBeVisible()
  const kb = page.keyboard

  // a quote to copy: market, dates, search and the first offer, with ⌃⌥ shortcuts
  await kb.press("Control+Alt+KeyS")
  const market = byLabel(page, "Market")
  await expect(market).toBeFocused()
  await kb.type("Germ")
  await expect(market).toHaveValue("DE")
  const { checkIn } = stayDates(80, 2)
  await byLabel(page, "Check-in").focus()
  await kb.type(mdy(checkIn))
  await expect(byLabel(page, "Check-out")).toHaveValue(addDays(checkIn, 2))
  await Promise.all([page.waitForResponse((r) => r.url().includes("ui_crs.search") && r.ok()), kb.press("Control+Alt+KeyS")])
  await expect(page.getByRole("listbox", { name: "Offers" })).toBeFocused()
  await kb.press("ArrowDown")
  await Promise.all([page.waitForResponse((r) => r.url().includes("ui_crs.quote_summary") && r.ok()), kb.press("Enter")])
  await expect(page.getByText(/Valid until /).first()).toBeVisible()

  // Turkish-Q: ⌥Q types "@" in the guest's e-mail; the page leaves it to the field
  const email = byLabel(page, "Email").first()
  await email.focus()
  const typed = await email.evaluate((el) =>
    el.dispatchEvent(new KeyboardEvent("keydown", { key: "@", code: "KeyQ", altKey: true, bubbles: true, cancelable: true })),
  )
  expect(typed, "⌥Q in a field is not taken by the page").toBe(true)
  await expect(page.getByText("Quote text copied")).toHaveCount(0)
  // ⌃⌥Q is the shortcut, in the field too: the page takes it and copies the quote
  const taken = await email.evaluate((el) =>
    el.dispatchEvent(new KeyboardEvent("keydown", { key: "@", code: "KeyQ", altKey: true, ctrlKey: true, bubbles: true, cancelable: true })),
  )
  expect(taken, "⌃⌥Q is taken by the page").toBe(false)
  await expect(page.getByText("Quote text copied").first()).toBeVisible()
  noErrors()
})

test("Reservation change: OLD vs NEW price before applying, then a new revision", async ({ page }) => {
  const noErrors = trackErrors(page)
  await english(page)
  await login(page, "revenue@demo.tex")
  await page.goto(texPath("/tex/reservations"))

  // a confirmed, price-locked stay to change (set up through the API as the revenue manager)
  const run = uniqueRunId()
  const { checkIn, checkOut } = stayDates(95, 2)
  const s = await pageApi<{ properties: { offers: { refundable?: boolean; rooms: { offer_key: string }[] }[] }[] }>(
    page,
    "kamra.tex.api.ui_crs.search",
    { check_in: checkIn, check_out: checkOut, rooms: [{ adults: 2, children: [] }], market: "DE", properties: ["Aurora Beach Resort"] },
  )
  expect(s.ok, JSON.stringify(s.body).slice(0, 300)).toBeTruthy()
  const offers = s.message.properties[0].offers
  const offer = offers.find((o) => o.refundable) ?? offers[0]
  const q = await pageApi<{ quote_id: string }>(page, "kamra.tex.api.crs.quote", { offer_key: offer.rooms[0].offer_key })
  expect(q.ok, JSON.stringify(q.body).slice(0, 300)).toBeTruthy()
  const bk = await pageApi<{ booking: string; status: string }>(page, "kamra.tex.api.ui_crs.book", {
    quote_ids: [q.message.quote_id],
    guest: { first_name: "Ella", last_name: `Journey ${run}`, email: `ella.${run.toLowerCase()}@example.com` },
    payment_method: "Pay at Hotel",
    confirm_without_payment: 1,
    idempotency_key: `e2e-crs-${run}`,
  })
  expect(bk.ok, JSON.stringify(bk.body).slice(0, 300)).toBeTruthy()
  expect(bk.message.status).toBe("Confirmed")

  await openReservation(page, { booking: bk.message.booking })
  const locked = await readLockedPrice(page)
  expect(locked.amount).toMatch(/^\d+\.\d{2}$/)

  // one more night on current prices: both figures are on screen before anything changes
  const p = await proposeChange(page, { checkOut: addDays(checkOut, 1), basis: "CURRENT" })
  expect(p.old).toEqual(locked)
  expect(p.proposed.amount).toMatch(/^\d+\.\d{2}$/)
  expect(p.proposed.amount).not.toBe(p.old.amount)
  expect(p.difference.amount).not.toBeNull()
  expect((await readLockedPrice(page)).amount).toBe(locked.amount) // still locked until applied

  const applied = await applyChange(page, `Guest extends by one night (${run})`)
  expect(applied.old_total).toBe(p.old.amount)
  expect(applied.new_total).toBe(p.proposed.amount)
  expect(applied.difference).toBe(p.difference.amount)
  expect((await readLockedPrice(page)).amount).toBe(p.proposed.amount)

  const revisions = await readRevisions(page)
  expect(revisions.length).toBeGreaterThanOrEqual(2)
  expect(revisions[0]).toMatchObject({ oldAmount: p.old.amount, newAmount: p.proposed.amount })
  expect(revisions[0].text).toContain(`Guest extends by one night (${run})`)
  expect(revisions.at(-1)?.changeType).toBe("Original")
  noErrors()
})

test("Call Center on a Mac: the shortcuts help says what VoiceOver's ⌃⌥ means for them (LO-49)", async ({ page }) => {
  const noErrors = trackErrors(page)
  await page.addInitScript(() => Object.defineProperty(Navigator.prototype, "platform", { get: () => "MacIntel", configurable: true }))
  await english(page)
  await login(page, "agent@demo.tex")
  await page.goto(texPath("/tex/crs/call-center"))
  await expect(page.getByRole("heading", { level: 1, name: "Call Center" })).toBeVisible()
  await page.locator("body").press("?")
  const help = page.getByRole("dialog", { name: "Shortcuts" })
  await expect(help).toBeVisible()
  await expect(help.getByText(/VoiceOver/)).toBeVisible()
  noErrors()
})

test("Call Center elsewhere: the shortcuts help says nothing of VoiceOver (LO-49)", async ({ page }) => {
  const noErrors = trackErrors(page)
  await page.addInitScript(() => Object.defineProperty(Navigator.prototype, "platform", { get: () => "Win32", configurable: true }))
  await english(page)
  await login(page, "agent@demo.tex")
  await page.goto(texPath("/tex/crs/call-center"))
  await expect(page.getByRole("heading", { level: 1, name: "Call Center" })).toBeVisible()
  await page.locator("body").press("?")
  const help = page.getByRole("dialog", { name: "Shortcuts" })
  await expect(help).toBeVisible()
  await expect(help.getByText(/VoiceOver/)).toHaveCount(0)
  noErrors()
})
