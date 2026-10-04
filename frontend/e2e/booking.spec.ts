import { expect, test, type Page, type TestInfo } from "@playwright/test"
import { addExtra, completeSandbox, fillGuest, guestSearch, nextStep, payWithSandbox, pickRoom, readConfirmation, visiblePrices } from "./flows/booking"
import { stayDates, trackErrors } from "./helpers"

// Guest booking engine (R-58): search → room → extras → guest details → sandbox card
// payment → confirmation, on the demo booking site. Runs in the desktop project and in
// the mobile project, where the viewport is a 390 px wide phone.
// The public write endpoints (quote, book, pay_booking) allow 20 calls per IP in 10
// minutes; one run of both projects makes 16, so back-to-back runs need that window.
const SLUG = "aurora"
const HOTEL = "Aurora Beach Resort"
const GUEST = {
  firstName: "Elif",
  lastName: "Demir",
  email: "elif.demir@example.com",
  phone: "+49 170 1234567",
  country: "DE",
  requests: "Late arrival around 22:00.",
}

/** Exact comparison of two decimal strings (no floats for money). */
const cents = (amount: string) => {
  const [whole, frac = ""] = amount.split(".")
  return BigInt(whole + frac.padEnd(2, "0").slice(0, 2))
}

/** Stay window per test; the desktop and mobile runs book different nights. */
const stay = (offsetDays: number, nights: number, project: string) => stayDates(offsetDays + (project === "mobile" ? 30 : 0), nights)

test.beforeEach(async ({ page }, testInfo) => {
  if (testInfo.project.name === "mobile") await page.setViewportSize({ width: 390, height: 844 })
})

test("guest books a room with an extra and pays by sandbox card", async ({ page }, testInfo) => {
  const noErrors = trackErrors(page)
  const { checkIn, checkOut } = stay(120, 3, testInfo.project.name)
  const found = await guestSearch(page, { slug: SLUG, checkIn, checkOut, rooms: [{ adults: 2, children: [5] }], hotel: HOTEL })
  expect(found.view).toBe("rooms")
  expect(found.rates.length, "rates on offer").toBeGreaterThan(0)
  for (const r of found.rates) expect(r.amount).toMatch(/^\d+\.\d{2}$/)

  const rate = found.rates[0]
  const chosen = await pickRoom(page, { roomName: rate.room, ratePlan: rate.ratePlan, board: rate.board })
  expect(chosen.price).toBe(rate.price)

  await addExtra(page, { name: "Airport transfer", quantity: 1 })
  await fillGuest(page, GUEST)
  const paid = await payWithSandbox(page, "success")
  expect(paid.transaction).not.toBe("")
  expect(paid.dueNow, "the book button names the amount due now").not.toBeNull()
  expect(paid.amount).toBe(paid.dueNow)

  const done = await readConfirmation(page)
  expect(done.heading).toBe("Your booking is confirmed")
  expect(done.status).toBe("Confirmed")
  expect(done.booking).not.toBe("")
  expect(done.paymentStatus).toMatch(/^(Paid|Partly paid)$/)
  // the stay total includes the room as priced in the results plus the extra
  expect(cents(done.amount) > cents(chosen.amount)).toBeTruthy()
  noErrors()
})

test("quotes older than 25 minutes are made again before booking, and the new ones are booked (O-30)", async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== "desktop", "the page's clock, not the viewport, is under test")
  const noErrors = trackErrors(page)
  await page.clock.install()
  const quoted: string[][] = []
  page.on("response", async (r) => {
    if (new URL(r.url()).pathname !== "/api/method/kamra.tex.api.public.quote_rooms" || !r.ok()) return
    const b = (await r.json().catch(() => null)) as { message?: { rooms?: { quote_id?: string }[] } } | null
    quoted.push((b?.message?.rooms ?? []).map((q) => q.quote_id ?? ""))
  })
  const { checkIn, checkOut } = stay(190, 2, testInfo.project.name)
  const found = await guestSearch(page, { slug: SLUG, checkIn, checkOut, rooms: [{ adults: 2 }], hotel: HOTEL })
  const rate = found.rates[0]
  await pickRoom(page, { roomName: rate.room, ratePlan: rate.ratePlan, board: rate.board })
  await fillGuest(page, GUEST)
  await expect.poll(() => quoted.length, { message: "the stay was quoted" }).toBeGreaterThan(0)
  const before = quoted.length

  // the guest lingers on the payment step: the quotes are 26 minutes old when they book (the page
  // quotes again after 25; the server keeps a quote for 30)
  await page.clock.fastForward("26:00")
  await page.getByRole("radio", { name: /^Credit or debit card/ }).first().check()
  await page.getByRole("checkbox", { name: /^I have read the cancellation and payment conditions/ }).check()
  const [book] = await Promise.all([
    page.waitForRequest((r) => new URL(r.url()).pathname === "/api/method/kamra.tex.api.public.book"),
    page.getByRole("button", { name: /^Book and pay/ }).filter({ visible: true }).first().click(),
  ])
  await expect.poll(() => quoted.length, { message: "the stay was quoted again" }).toBeGreaterThan(before)
  // what is booked is what the guest was just quoted, not the old quotes
  expect((book.postDataJSON() as { quote_ids: string[] }).quote_ids).toEqual(quoted[quoted.length - 1])
  expect(quoted[quoted.length - 1]).not.toEqual(quoted[before - 1])

  await completeSandbox(page, "success")
  const done = await readConfirmation(page)
  expect(done.status).toBe("Confirmed")
  noErrors()
})

test("a new price found when the quotes are made again stops the booking; the next submit books the new quotes (O-30)", async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== "desktop", "the page's clock, not the viewport, is under test")
  const noErrors = trackErrors(page)
  await page.clock.install()
  const isQuoteRooms = (url: string) => new URL(url).pathname === "/api/method/kamra.tex.api.public.quote_rooms"
  const quoted: string[][] = []
  page.on("response", async (r) => {
    if (!isQuoteRooms(r.url()) || !r.ok()) return
    const b = (await r.json().catch(() => null)) as { message?: { rooms?: { quote_id?: string }[] } } | null
    quoted.push((b?.message?.rooms ?? []).map((q) => q.quote_id ?? ""))
  })
  const booked: string[][] = []
  page.on("request", (r) => {
    if (new URL(r.url()).pathname === "/api/method/kamra.tex.api.public.book") booked.push((r.postDataJSON() as { quote_ids: string[] }).quote_ids)
  })
  const { checkIn, checkOut } = stay(200, 2, testInfo.project.name)
  const found = await guestSearch(page, { slug: SLUG, checkIn, checkOut, rooms: [{ adults: 2 }], hotel: HOTEL })
  const rate = found.rates[0]
  await pickRoom(page, { roomName: rate.room, ratePlan: rate.ratePlan, board: rate.board })
  await fillGuest(page, GUEST)
  await expect.poll(() => quoted.length, { message: "the stay was quoted" }).toBeGreaterThan(0)
  const before = quoted.length

  // the refresh made at submit (the quotes are 26 minutes old) finds another price: the server's quotes,
  // their total raised by 10.00 and marked as changed
  await page.route(
    (url) => isQuoteRooms(url.href),
    async (route) => {
      const response = await route.fetch()
      const body = (await response.json()) as { message: { rooms: { price_changed?: boolean; previous_total?: string; quote?: { totals: { total: string } } }[] } }
      for (const q of body.message.rooms) {
        if (!q.quote) continue
        q.previous_total = q.quote.totals.total
        const c = cents(q.quote.totals.total) + 1000n
        q.quote.totals.total = `${c / 100n}.${String(c % 100n).padStart(2, "0")}`
        q.price_changed = true
      }
      await route.fulfill({ response, json: body })
    },
    { times: 1 },
  )
  await page.clock.fastForward("26:00")
  await page.getByRole("radio", { name: /^Credit or debit card/ }).first().check()
  await page.getByRole("checkbox", { name: /^I have read the cancellation and payment conditions/ }).check()
  const bookButton = page.getByRole("button", { name: /^Book and pay/ }).filter({ visible: true }).first()
  await bookButton.click()
  // the guest sees the new price before anything is booked
  await expect(page.getByText("The price has changed").first()).toBeVisible()
  await expect.poll(() => quoted.length, { message: "the stay was quoted again" }).toBeGreaterThan(before)
  expect(booked, "no booking before the guest has seen the new price").toEqual([])

  // the next submit books the quotes just made (fresh, so not made again)
  const [book] = await Promise.all([page.waitForRequest((r) => new URL(r.url()).pathname === "/api/method/kamra.tex.api.public.book"), bookButton.click()])
  expect((book.postDataJSON() as { quote_ids: string[] }).quote_ids).toEqual(quoted[quoted.length - 1])
  expect(booked).toHaveLength(1)
  await completeSandbox(page, "success")
  expect((await readConfirmation(page)).status).toBe("Confirmed")
  noErrors()
})

/** LO-32: the stay chosen, quoted on the payment step, then quoted again at submit 10.00 dearer; the guest accepts that
 * price. `dearer()` makes the next quotes the server's with the stay 10.00 dearer than the search said, marked as the
 * server marks them: changed against the search's total (it knows nothing of what the guest accepted), but not when
 * extras were asked for (it does not compare those). */
async function acceptDearerStay(page: Page, testInfo: TestInfo, offsetDays: number) {
  await page.clock.install()
  const isQuoteRooms = (url: string) => new URL(url).pathname === "/api/method/kamra.tex.api.public.quote_rooms"
  let quoted = 0
  page.on("response", (r) => {
    if (isQuoteRooms(r.url()) && r.ok()) quoted += 1
  })
  const booked: string[][] = []
  page.on("request", (r) => {
    if (new URL(r.url()).pathname === "/api/method/kamra.tex.api.public.book") booked.push((r.postDataJSON() as { quote_ids: string[] }).quote_ids)
  })
  const dearer = () =>
    page.route(
      (url) => isQuoteRooms(url.href),
      async (route) => {
        const asked = (route.request().postDataJSON() as { rooms: { extras?: unknown[] }[] }).rooms
        const response = await route.fetch()
        const body = (await response.json()) as { message: { rooms: { price_changed?: boolean; previous_total?: string; quote?: { totals: Record<string, string> } }[] } }
        body.message.rooms.forEach((q, i) => {
          if (!q.quote) return
          q.previous_total = q.quote.totals.total
          q.price_changed = !asked[i]?.extras?.length
          for (const k of ["accommodation", "total"]) {
            const c = cents(q.quote.totals[k]) + 1000n
            q.quote.totals[k] = `${c / 100n}.${String(c % 100n).padStart(2, "0")}`
          }
        })
        await route.fulfill({ response, json: body })
      },
      { times: 1 },
    )
  const { checkIn, checkOut } = stay(offsetDays, 2, testInfo.project.name)
  const found = await guestSearch(page, { slug: SLUG, checkIn, checkOut, rooms: [{ adults: 2 }], hotel: HOTEL })
  const rate = found.rates[0]
  await pickRoom(page, { roomName: rate.room, ratePlan: rate.ratePlan, board: rate.board })
  await fillGuest(page, GUEST)
  await expect.poll(() => quoted, { message: "the stay was quoted" }).toBeGreaterThan(0)
  const bookButton = page.getByRole("button", { name: /^Book and pay/ }).filter({ visible: true }).first()
  const notice = page.getByText("The price has changed")
  await expect(notice).toHaveCount(0)
  const terms = page.getByRole("checkbox", { name: /^I have read the cancellation and payment conditions/ })
  // the guest lingers 26 minutes, then chooses (the page quotes again after 25), as in the O-30 tests
  const linger = async () => {
    await page.clock.fastForward("26:00")
    await page.getByRole("radio", { name: /^Credit or debit card/ }).first().check()
    await terms.uncheck()
    await terms.check()
  }

  // the quotes are made again at submit and the stay costs 10.00 more: the guest sees it and accepts it
  await dearer()
  await linger()
  const before = quoted
  await bookButton.click()
  await expect(notice.first()).toBeVisible()
  expect(quoted).toBeGreaterThan(before)
  expect(booked, "no booking before the guest has seen the new price").toEqual([])
  await page.getByRole("button", { name: "OK, continue" }).first().click()
  await expect(notice).toHaveCount(0)
  return { booked, bookButton, notice, dearer, linger, quoted: () => quoted }
}

test("a price the guest accepted is not announced again when the quotes are made again at that price (LO-32)", async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== "desktop", "the page's clock, not the viewport, is under test")
  const noErrors = trackErrors(page)
  const { booked, bookButton, notice, dearer, linger } = await acceptDearerStay(page, testInfo, 210)

  // they linger again: the quotes made at the next submit cost what they accepted, so nothing is announced
  await dearer()
  await linger()
  await bookButton.click()
  await expect.poll(() => booked.length, { message: "booked at the price the guest accepted" }).toBe(1)
  await expect(notice).toHaveCount(0)
  await completeSandbox(page, "success")
  expect((await readConfirmation(page)).status).toBe("Confirmed")
  noErrors()
})

test("a price the guest accepted is not announced again when they add an extra afterwards (LO-32)", async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== "desktop", "the page's clock, not the viewport, is under test")
  const noErrors = trackErrors(page)
  const { booked, notice, dearer, quoted } = await acceptDearerStay(page, testInfo, 220)

  // back to the extras: one more makes the page quote again (the room still at the price they accepted); the extra
  // is the guest's own choice, the room's price is what they accepted, so nothing is announced
  await page.getByRole("navigation", { name: "Booking steps" }).getByRole("button", { name: /^Extras/ }).click()
  await expect(page.getByRole("heading", { level: 1 })).toHaveText("Make your stay special")
  await addExtra(page, { name: "Airport transfer", quantity: 1 })
  await dearer()
  const before = quoted()
  await nextStep(page)
  await expect.poll(quoted, { message: "the stay was quoted again with the extra" }).toBeGreaterThan(before)
  await expect(page.getByRole("heading", { level: 1 })).toHaveText("Your details")
  await expect(notice).toHaveCount(0)
  await fillGuest(page, GUEST)
  await page.getByRole("radio", { name: /^Credit or debit card/ }).first().check()
  await page.getByRole("checkbox", { name: /^I have read the cancellation and payment conditions/ }).check()
  await page.getByRole("button", { name: /^Book and pay/ }).filter({ visible: true }).first().click()
  await expect.poll(() => booked.length, { message: "booked with the extra" }).toBe(1)
  await completeSandbox(page, "success")
  expect((await readConfirmation(page)).status).toBe("Confirmed")
  noErrors()
})

test("an extra the quotes made again cannot add is told as such, not as a price change (LO-32)", async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== "desktop", "the page's clock, not the viewport, is under test")
  const noErrors = trackErrors(page)
  await page.clock.install()
  const isQuoteRooms = (url: string) => new URL(url).pathname === "/api/method/kamra.tex.api.public.quote_rooms"
  let quoted = 0
  page.on("response", (r) => {
    if (isQuoteRooms(r.url()) && r.ok()) quoted += 1
  })
  const booked: string[][] = []
  page.on("request", (r) => {
    if (new URL(r.url()).pathname === "/api/method/kamra.tex.api.public.book") booked.push((r.postDataJSON() as { quote_ids: string[] }).quote_ids)
  })
  const { checkIn, checkOut } = stay(230, 2, testInfo.project.name)
  const found = await guestSearch(page, { slug: SLUG, checkIn, checkOut, rooms: [{ adults: 2 }], hotel: HOTEL })
  const rate = found.rates[0]
  await pickRoom(page, { roomName: rate.room, ratePlan: rate.ratePlan, board: rate.board })
  await addExtra(page, { name: "Airport transfer", quantity: 1 })
  await fillGuest(page, GUEST)
  await expect.poll(() => quoted, { message: "the stay was quoted" }).toBeGreaterThan(0)

  // the transfer sells out while the guest lingers: the quotes made at submit cannot add it, and leave it (and its
  // price) out of the total, as the server does; the room costs what it did
  await page.route(
    (url) => isQuoteRooms(url.href),
    async (route) => {
      const response = await route.fetch()
      const body = (await response.json()) as { message: { rooms: { quote?: { totals: Record<string, string>; extras: { name: string; ok: boolean; amount: string; reason?: string }[] } }[] } }
      for (const q of body.message.rooms) {
        for (const e of q.quote?.extras ?? []) {
          if (!e.ok || e.name !== "Airport transfer") continue
          const c = cents(q.quote!.totals.total) - cents(e.amount)
          q.quote!.totals.total = `${c / 100n}.${String(c % 100n).padStart(2, "0")}`
          Object.assign(e, { ok: false, amount: "0.00", reason: `sold out on ${checkIn}` })
        }
      }
      await route.fulfill({ response, json: body })
    },
    { times: 1 },
  )
  await page.clock.fastForward("26:00")
  await page.getByRole("radio", { name: /^Credit or debit card/ }).first().check()
  await page.getByRole("checkbox", { name: /^I have read the cancellation and payment conditions/ }).check()
  const before = quoted
  await page.getByRole("button", { name: /^Book and pay/ }).filter({ visible: true }).first().click()
  const rejected = page.getByRole("status").filter({ hasText: "Could not be added to your stay" })
  await expect(rejected).toBeVisible()
  await expect(rejected).toContainText("Airport transfer")
  expect(quoted).toBeGreaterThan(before)
  expect(booked, "no booking before the guest has seen what could not be added").toEqual([])
  const notice = page.getByText("The price has changed")
  await expect(notice).toHaveCount(0)
  // they go on without it: still no price change, for the room's price did not change
  await rejected.getByRole("button", { name: "Continue anyway" }).click()
  await expect(rejected).toHaveCount(0)
  await expect(notice).toHaveCount(0)
  noErrors()
})

test("a new price found on the extras step is announced on the next step, though the guest changed the extras (LO-32)", async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== "desktop", "the flow's steps, not the viewport, are under test")
  const noErrors = trackErrors(page)
  const isQuoteRooms = (url: string) => new URL(url).pathname === "/api/method/kamra.tex.api.public.quote_rooms"
  let quoted = 0
  page.on("response", (r) => {
    if (isQuoteRooms(r.url()) && r.ok()) quoted += 1
  })
  const money = (c: bigint) => `${c / 100n}.${String(c % 100n).padStart(2, "0")}`
  // the next quotes: the server's, the room 10.00 dearer than the search said; the transfer sold out (left out of the
  // total), and marked as the server marks them (changed against the search's total only when no extras were asked)
  const dearer = () =>
    page.route(
      (url) => isQuoteRooms(url.href),
      async (route) => {
        const asked = (route.request().postDataJSON() as { rooms: { extras?: unknown[] }[] }).rooms
        const response = await route.fetch()
        const body = (await response.json()) as {
          message: { rooms: { price_changed?: boolean; previous_total?: string; quote?: { totals: Record<string, string>; extras: { name: string; ok: boolean; amount: string; reason?: string }[] } }[] }
        }
        body.message.rooms.forEach((q, i) => {
          if (!q.quote) return
          q.previous_total = q.quote.totals.total
          q.price_changed = !asked[i]?.extras?.length
          let total = cents(q.quote.totals.total) + 1000n
          for (const e of q.quote.extras) {
            if (!e.ok || e.name !== "Airport transfer") continue
            total -= cents(e.amount)
            Object.assign(e, { ok: false, amount: "0.00", reason: `sold out on ${checkIn}` })
          }
          q.quote.totals.accommodation = money(cents(q.quote.totals.accommodation) + 1000n)
          q.quote.totals.total = money(total)
        })
        await route.fulfill({ response, json: body })
      },
      { times: 1 },
    )
  const { checkIn, checkOut } = stay(250, 2, testInfo.project.name)
  const found = await guestSearch(page, { slug: SLUG, checkIn, checkOut, rooms: [{ adults: 2 }], hotel: HOTEL })
  const rate = found.rates[0]
  await pickRoom(page, { roomName: rate.room, ratePlan: rate.ratePlan, board: rate.board })
  await addExtra(page, { name: "Airport transfer", quantity: 1 })

  // Continue: the transfer cannot be added and the room costs 10.00 more; the guest stays on the extras step, which
  // tells only what could not be added
  await dearer()
  await page.getByRole("button", { name: "Continue", exact: true }).filter({ visible: true }).first().click()
  const rejected = page.getByRole("status").filter({ hasText: "Could not be added to your stay" })
  await expect(rejected).toBeVisible()
  await expect(page.getByRole("heading", { level: 1 })).toHaveText("Make your stay special")
  // they take the transfer out and go on: the room still costs 10.00 more than they were shown, so the next step says so
  await addExtra(page, { name: "Airport transfer", quantity: 0 })
  await dearer()
  const before = quoted
  await page.getByRole("button", { name: "Continue", exact: true }).filter({ visible: true }).first().click()
  await expect(page.getByRole("heading", { level: 1 })).toHaveText("Your details")
  expect(quoted).toBeGreaterThan(before)
  await expect(page.getByRole("status").filter({ hasText: "The price has changed" })).toBeVisible()
  noErrors()
})

test("on a phone the price-change notice is focused and scrolled into view (LO-33)", async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== "mobile", "the phone's viewport is under test")
  const noErrors = trackErrors(page)
  await page.clock.install()
  const isQuoteRooms = (url: string) => new URL(url).pathname === "/api/method/kamra.tex.api.public.quote_rooms"
  let quoted = 0
  page.on("response", (r) => {
    if (isQuoteRooms(r.url()) && r.ok()) quoted += 1
  })
  const { checkIn, checkOut } = stay(215, 2, testInfo.project.name)
  const found = await guestSearch(page, { slug: SLUG, checkIn, checkOut, rooms: [{ adults: 2 }], hotel: HOTEL })
  const rate = found.rates[0]
  await pickRoom(page, { roomName: rate.room, ratePlan: rate.ratePlan, board: rate.board })
  await fillGuest(page, GUEST)
  await expect.poll(() => quoted, { message: "the stay was quoted" }).toBeGreaterThan(0)
  // the refresh made at submit (the quotes are 26 minutes old) finds the stay 10.00 dearer
  await page.route(
    (url) => isQuoteRooms(url.href),
    async (route) => {
      const response = await route.fetch()
      const body = (await response.json()) as { message: { rooms: { quote?: { totals: Record<string, string> } }[] } }
      for (const q of body.message.rooms) {
        if (!q.quote) continue
        for (const k of ["accommodation", "total"]) {
          const c = cents(q.quote.totals[k]) + 1000n
          q.quote.totals[k] = `${c / 100n}.${String(c % 100n).padStart(2, "0")}`
        }
      }
      await route.fulfill({ response, json: body })
    },
    { times: 1 },
  )
  await page.clock.fastForward("26:00")
  await page.getByRole("radio", { name: /^Credit or debit card/ }).first().check()
  await page.getByRole("checkbox", { name: /^I have read the cancellation and payment conditions/ }).check()
  // the guest books from the bottom of the page: the notice sits above, out of a phone's view
  const bookButton = page.getByRole("button", { name: /^Book and pay/ }).filter({ visible: true }).last()
  await bookButton.scrollIntoViewIfNeeded()
  await bookButton.click()
  const notice = page.getByRole("status").filter({ hasText: "The price has changed" })
  await expect(notice).toBeVisible()
  await expect(notice).toBeInViewport()
  await expect(notice).toBeFocused()
  noErrors()
})

test("payment options that could not be loaded say why, and load on Try again (LO-14)", async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== "desktop", "the checkout's wording, not the viewport, is under test")
  const noErrors = trackErrors(page)
  const isBasket = (url: URL) => url.pathname === "/api/method/kamra.tex.api.public.basket"
  // the server's refusals as Frappe sends them: a rate limit (429), then a coded refusal (G-70b)
  const refuse = (status: number, body: Record<string, unknown>) =>
    page.route(isBasket, (route) => route.fulfill({ status, contentType: "application/json", json: { ...body, _server_messages: JSON.stringify([JSON.stringify({ message: "Refused" })]) } }), { times: 1 })
  await refuse(429, { exc_type: "RateLimitExceededError" })
  const { checkIn, checkOut } = stay(240, 2, testInfo.project.name)
  const found = await guestSearch(page, { slug: SLUG, checkIn, checkOut, rooms: [{ adults: 2 }], hotel: HOTEL })
  const rate = found.rates[0]
  await pickRoom(page, { roomName: rate.room, ratePlan: rate.ratePlan, board: rate.board })
  await fillGuest(page, GUEST)

  const failed = page.getByRole("status").filter({ has: page.getByRole("button", { name: "Try again" }) })
  await expect(failed).toContainText("Too many attempts")
  await expect(failed).toContainText("Please wait a minute and try again.")
  await expect(failed).not.toContainText("Check your connection")
  // a coded refusal is told in its own words
  await refuse(417, { exc_type: "ValidationError", tex_code: "QUOTE_INVALID" })
  await failed.getByRole("button", { name: "Try again" }).click()
  await expect(failed).toContainText("The payment options could not be loaded")
  await expect(failed).toContainText("Your selection is no longer valid. Please search again.")
  await expect(failed).not.toContainText("Check your connection")
  // and the options load when the server answers
  await failed.getByRole("button", { name: "Try again" }).click()
  await expect(page.getByRole("radio", { name: /^Credit or debit card/ }).first()).toBeVisible()
  await expect(failed).toHaveCount(0)
  noErrors()
})

test("a declined card keeps the booking awaiting payment until the retry succeeds", async ({ page }, testInfo) => {
  const noErrors = trackErrors(page)
  const { checkIn, checkOut } = stay(160, 2, testInfo.project.name)
  const found = await guestSearch(page, { slug: SLUG, checkIn, checkOut, rooms: [{ adults: 2 }], hotel: HOTEL })
  expect(found.rates.length, "rates on offer").toBeGreaterThan(0)
  const rate = found.rates[found.rates.length - 1]
  await pickRoom(page, { roomName: rate.room, ratePlan: rate.ratePlan, board: rate.board })
  await fillGuest(page, GUEST)

  await payWithSandbox(page, "fail")
  const failed = await readConfirmation(page)
  expect(failed.heading).toBe("The payment didn't go through")
  expect(failed.status).toBe("Awaiting payment")

  await page.getByRole("button", { name: "Try the payment again" }).click()
  await completeSandbox(page, "success")
  const done = await readConfirmation(page)
  expect(done.booking).toBe(failed.booking)
  expect(done.heading).toBe("Your booking is confirmed")
  expect(done.status).toBe("Confirmed")
  noErrors()
})

// The demo's DE and GLOBAL contracts give the same bed-and-breakfast price in their high season, July and August:
// (70 + 55) × 1.08 = 80 + 55 at the beach resort (demo_seed). A stay with a night then is moved two months back, so the
// campaign link's prices are compared where they differ (batch 2P: the random window reached July 2027 and CI failed
// "DE prices differ"). Setup only: the assertions are unchanged.
function outsideHighSeason(d: { checkIn: string; checkOut: string }) {
  const nights = (iso: string, n: number) => {
    const t = new Date(`${iso}T12:00:00Z`)
    t.setUTCDate(t.getUTCDate() + n)
    return t.toISOString().slice(0, 10)
  }
  const high = (iso: string) => ["07", "08"].includes(iso.slice(5, 7))
  return high(d.checkIn) || high(nights(d.checkOut, -1)) ? { checkIn: nights(d.checkIn, -62), checkOut: nights(d.checkOut, -62) } : d
}

test("a campaign link's market prices the stay; an unknown market falls back with a notice", async ({ page }, testInfo) => {
  const noErrors = trackErrors(page)
  const warnings: string[] = []
  page.on("console", (m) => {
    if (m.type() === "warning") warnings.push(m.text())
  })
  const { checkIn, checkOut } = outsideHighSeason(stay(130, 2, testInfo.project.name))
  const search = { slug: SLUG, checkIn, checkOut, rooms: [{ adults: 2 }], hotel: HOTEL }
  const same = (a: { room: string; ratePlan: string; board: string }, b: typeof a) => a.room === b.room && a.ratePlan === b.ratePlan && a.board === b.board

  const standard = await guestSearch(page, search)
  expect(standard.rates.length).toBeGreaterThan(0)
  // the demo hotel sells a separate DE market contract
  const de = await guestSearch(page, { ...search, market: "DE" })
  expect(de.rates.some((r) => standard.rates.some((s) => same(s, r) && s.amount !== r.amount)), "DE prices differ").toBeTruthy()
  const byCountry = await guestSearch(page, { ...search, country: "DE" })
  expect(byCountry.rates).toEqual(de.rates)

  // the link's market is not sold: the standard prices, a notice saying so, and a funnel event (G-55b)
  const notice = page.getByRole("status").filter({ hasText: "The offer in your link is not available here" })
  await expect(notice).toHaveCount(0)
  const counted = page.waitForRequest((r) => r.url().includes("kamra.tex.api.public.track") && (r.postData() ?? "").includes("market_refused"))
  const unknown = await guestSearch(page, { ...search, market: "E2E_NO_SUCH_MARKET" })
  expect(unknown.view).toBe("rooms")
  expect(unknown.rates).toEqual(standard.rates)
  expect(warnings.join("\n")).toContain("market link ignored")
  await expect(notice).toBeVisible()
  const body = new URLSearchParams((await counted).postData() ?? "")
  // the server keeps the refusal and an existing market only (ADR-056): this one it drops
  expect(JSON.parse(body.get("payload") ?? "{}")).toEqual({ reason: "MARKET_UNKNOWN", market: "E2E_NO_SUCH_MARKET" })
  noErrors()
})

test("two rooms with different parties are priced and booked together", async ({ page }, testInfo) => {
  const noErrors = trackErrors(page)
  const { checkIn, checkOut } = stay(200, 3, testInfo.project.name)
  const found = await guestSearch(page, {
    slug: SLUG,
    checkIn,
    checkOut,
    rooms: [{ adults: 2 }, { adults: 1, children: [4, 9] }],
    hotel: HOTEL,
  })
  expect(found.rates.length, "rates for room 1").toBeGreaterThan(0)
  const first = found.rates[0]
  await pickRoom(page, { roomName: first.room, ratePlan: first.ratePlan, board: first.board, roomIndex: 0 })

  // room 2 lists only the room types its party fits; take another type when there is one
  await expect(page.getByRole("heading", { level: 2, name: "Choose room 2" })).toBeVisible()
  const second = await visiblePrices(page)
  expect(second.rates.length, "rates for room 2").toBeGreaterThan(0)
  const fit = second.rates.find((r) => r.room !== first.room) ?? second.rates[0]
  await pickRoom(page, { roomName: fit.room, ratePlan: fit.ratePlan, board: fit.board, roomIndex: 1 })

  await fillGuest(page, GUEST)
  const paid = await payWithSandbox(page, "success")
  expect(paid.amount).toBe(paid.dueNow)
  const done = await readConfirmation(page)
  expect(done.status).toBe("Confirmed")
  await expect(page.getByText("Room 2", { exact: true })).toBeVisible()
  // the server total covers both rooms
  expect(cents(done.amount) >= cents(first.amount) + cents(fit.amount)).toBeTruthy()
  noErrors()
})
