import { expect, test } from "@playwright/test"
import { addExtra, completeSandbox, fillGuest, guestSearch, payWithSandbox, pickRoom, readConfirmation, visiblePrices } from "./flows/booking"
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

test("a campaign link's market prices the stay; an unknown market falls back quietly", async ({ page }, testInfo) => {
  const noErrors = trackErrors(page)
  const warnings: string[] = []
  page.on("console", (m) => {
    if (m.type() === "warning") warnings.push(m.text())
  })
  const { checkIn, checkOut } = stay(130, 2, testInfo.project.name)
  const search = { slug: SLUG, checkIn, checkOut, rooms: [{ adults: 2 }], hotel: HOTEL }
  const same = (a: { room: string; ratePlan: string; board: string }, b: typeof a) => a.room === b.room && a.ratePlan === b.ratePlan && a.board === b.board

  const standard = await guestSearch(page, search)
  expect(standard.rates.length).toBeGreaterThan(0)
  // the demo hotel sells a separate DE market contract
  const de = await guestSearch(page, { ...search, market: "DE" })
  expect(de.rates.some((r) => standard.rates.some((s) => same(s, r) && s.amount !== r.amount)), "DE prices differ").toBeTruthy()
  const byCountry = await guestSearch(page, { ...search, country: "DE" })
  expect(byCountry.rates).toEqual(de.rates)

  const unknown = await guestSearch(page, { ...search, market: "E2E_NO_SUCH_MARKET" })
  expect(unknown.view).toBe("rooms")
  expect(unknown.rates).toEqual(standard.rates)
  expect(warnings.join("\n")).toContain("market link ignored")
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
