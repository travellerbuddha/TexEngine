import { expect, type Locator, type Page } from "@playwright/test"
import { esc } from "../helpers"

// Guest booking engine journey steps (R-58), composable into larger specs.
// They drive the public booking UI (/book/<slug>, same path on the bench and on a
// Vite dev server) in English with role and label locators (plus a few structural
// ones where the page has no role: counter values, <dt>/<dd> pairs, the submit button
// whose text a site may override). They assume no demo-data names: hotels, rooms,
// rate plans and extras are whatever the caller passes (the site slug defaults to
// "aurora"). Typical use:
//
//   await guestSearch(page, { checkIn, checkOut, rooms: [{ adults: 2 }], hotel, market })
//   await pickRoom(page, { roomName, ratePlan, board })
//   await addExtra(page, { name, quantity: 1 })        // optional
//   await fillGuest(page, guest)
//   await payWithSandbox(page, "success")
//   const { booking, total, status } = await readConfirmation(page)

export interface GuestParty {
  adults: number
  /** child ages in years, one entry per child */
  children?: number[]
}

export interface GuestSearchOptions {
  slug?: string
  checkIn: string
  checkOut: string
  rooms?: GuestParty[]
  /** group sites: limit the search to this hotel (its display name) */
  hotel?: string
  promo?: string
  /** campaign deep link: price with this market's contracts (?market=) */
  market?: string
  /** campaign deep link: the guest's country, from which the server picks the market (?country=) */
  country?: string
  /** entry page instead of the platform's /book/<slug> (e.g. "/?lang=en" on a site's own host, G-21) */
  path?: string
}

/** Booking engine URL of a site, with optional market / country deep-link parameters. */
export function bookingPath(slug = "aurora", params: { market?: string; country?: string; [k: string]: string | undefined } = {}) {
  const q = new URLSearchParams({ lang: "en" })
  for (const [k, v] of Object.entries(params)) if (v) q.set(k, v)
  return `/book/${encodeURIComponent(slug)}?${q}`
}

export interface HotelPrice {
  hotel: string
  /** "From" price as shown (all requested rooms), null when the hotel cannot take the search */
  price: string | null
  amount: string | null
}

export interface RatePrice {
  room: string
  ratePlan: string
  board: string
  /** stay total as shown, e.g. "€675.00" */
  price: string
  amount: string
}

export interface SearchPrices {
  view: "hotels" | "rooms" | "none"
  hotels: HotelPrice[]
  /** rates on screen for the active room (the meal plan shown on each room card) */
  rates: RatePrice[]
}

export interface PickRoomOptions {
  roomName: string
  /** meal plan label as shown, e.g. "Bed & breakfast" */
  board?: string
  /** rate plan name as shown */
  ratePlan?: string
  /** 0-based requested room (multi-room searches); default: the room currently shown */
  roomIndex?: number
  /** group sites: open this hotel first when the hotel list is shown */
  hotel?: string
}

export interface GuestDetails {
  firstName: string
  lastName: string
  email: string
  phone: string
  /** ISO 3166-1 alpha-2 code ("DE") or the country name as listed */
  country?: string
  requests?: string
  marketingEmail?: boolean
}

export interface Confirmation {
  booking: string
  /** total as shown, e.g. "€675.00" */
  total: string
  amount: string
  /** booking status as shown, e.g. "Confirmed" or "Awaiting payment" */
  status: string
  paymentStatus: string | null
  heading: string
}

/** Plain decimal from an en-GB money text ("€1,234.50" → "1234.50"). */
export function moneyAmount(text: string) {
  const m = text.replace(/\u00a0/g, " ").match(/-?[\d,]+(\.\d+)?/)
  return m ? m[0].replace(/,/g, "") : ""
}

const english = new WeakSet<Page>()
async function forceEnglish(page: Page) {
  if (english.has(page)) return
  english.add(page)
  await page.addInitScript(() => {
    try {
      localStorage.setItem("tex.book.lang", "en")
    } catch {
      /* storage blocked */
    }
  })
}

const visible = (l: Locator) => l.filter({ visible: true }).first()

async function stepHeading(page: Page) {
  return ((await page.getByRole("heading", { level: 1 }).first().textContent()) ?? "").trim()
}

const RESULTS_HEADING = /^(Choose (your hotel|your room|room \d+)|Nothing available for these dates)$/

async function waitForResults(page: Page) {
  await expect(page.getByRole("heading", { level: 2, name: RESULTS_HEADING }).first()).toBeVisible({ timeout: 30_000 })
}

/** Search from the site's home page with the search form (dates, rooms and guests,
 * optional hotel and promo code) and return the prices on screen. A market / country
 * opens the page as a campaign deep link (/book/<slug>?market=…), which the search keeps. */
export async function guestSearch(page: Page, opts: GuestSearchOptions): Promise<SearchPrices> {
  const slug = opts.slug ?? "aurora"
  const rooms = opts.rooms?.length ? opts.rooms : [{ adults: 2 }]
  await forceEnglish(page)
  await page.goto(opts.path ?? bookingPath(slug, { market: opts.market, country: opts.country }))
  const form = page.getByRole("search", { name: "Search for a stay" })
  await expect(form).toBeVisible()

  if (opts.hotel) {
    const select = form.getByLabel("Hotel", { exact: true })
    if (await select.count()) {
      const option = select.locator("option").filter({ hasText: new RegExp(`^${esc(opts.hotel)}( — |$)`) })
      await expect(option, `hotel ${opts.hotel} on the search form`).toHaveCount(1)
      await select.selectOption((await option.getAttribute("value")) ?? "")
    }
  }

  // dates: the calendar dialog, days by their accessible name (formatted by the page itself)
  await form.getByRole("button", { name: /^Dates/ }).click()
  const cal = page.getByRole("dialog", { name: "Select dates" })
  await expect(cal).toBeVisible()
  for (const d of [opts.checkIn, opts.checkOut]) {
    const label = await page.evaluate(
      (iso) => new Intl.DateTimeFormat("en-GB", { weekday: "long", day: "numeric", month: "long", year: "numeric" }).format(new Date(`${iso}T12:00:00`)),
      d,
    )
    const day = cal.getByRole("button", { name: new RegExp(`^${esc(label)}(,|$)`) })
    for (let i = 0; i < 24 && !(await day.count()); i++) {
      const next = cal.getByRole("button", { name: "Next month" })
      if (!(await next.isVisible()) || (await next.isDisabled())) break
      await next.click()
    }
    await expect(day, `calendar day ${d}`).toHaveCount(1)
    await day.click()
  }
  await cal.getByRole("button", { name: "Done", exact: true }).click()
  await expect(cal).toBeHidden()

  // rooms and guests
  await form.getByRole("button", { name: /^Guests/ }).click()
  const gd = page.getByRole("dialog", { name: "Rooms and guests" })
  await expect(gd).toBeVisible()
  const roomGroups = gd.getByRole("group", { name: /^Room \d+$/ })
  while ((await roomGroups.count()) > rooms.length) await gd.getByRole("button", { name: `Remove room ${await roomGroups.count()}` }).click()
  while ((await roomGroups.count()) < rooms.length) await gd.getByRole("button", { name: "Add another room" }).click()
  for (let r = 0; r < rooms.length; r++) {
    const n = r + 1
    const fs = gd.getByRole("group", { name: `Room ${n}`, exact: true })
    const kids = rooms[r].children ?? []
    await setCounter(fs.getByRole("group", { name: "Adults" }), rooms[r].adults, `More adults in room ${n}`, `Fewer adults in room ${n}`)
    await setCounter(fs.getByRole("group", { name: "Children" }), kids.length, `More children in room ${n}`, `Fewer children in room ${n}`)
    for (let k = 0; k < kids.length; k++) await fs.getByLabel(`Age of child ${k + 1}`, { exact: true }).selectOption(String(kids[k]))
  }
  await gd.getByRole("button", { name: "Done", exact: true }).click()
  await expect(gd).toBeHidden()

  if (opts.promo) {
    const toggle = form.getByRole("button", { name: "Have a promo code?" })
    if (await toggle.isVisible()) await toggle.click()
    await form.getByLabel(/^Promo code/).fill(opts.promo)
  }
  // the submit button's text can be set per site, so it is found by type
  await form.locator("button[type=submit]").click()
  await waitForResults(page)
  if (opts.market) await expect(page).toHaveURL(new RegExp(`[?&]market=${esc(encodeURIComponent(opts.market))}(&|$)`))
  return visiblePrices(page)
}

async function setCounter(group: Locator, want: number, incName: string, decName: string) {
  const out = group.locator("output")
  for (let i = 0; i < 20; i++) {
    const now = Number((await out.textContent())?.trim() ?? "0")
    if (now === want) return
    await group.getByRole("button", { name: now < want ? incName : decName, exact: true }).click()
  }
  await expect(out).toHaveText(String(want))
}

/** Prices on the results screen: hotel cards (group sites) or the rates of the active room. */
export async function visiblePrices(page: Page): Promise<SearchPrices> {
  const heading = ((await page.getByRole("heading", { level: 2, name: RESULTS_HEADING }).first().textContent()) ?? "").trim()
  if (heading === "Choose your hotel") {
    const hotels: HotelPrice[] = []
    const cards = page.getByRole("region", { name: "Choose your hotel" }).getByRole("listitem")
    for (const card of await cards.all()) {
      const name = ((await card.getByRole("heading", { level: 3 }).textContent()) ?? "").trim()
      const lines = (await card.innerText()).split("\n").map((l) => l.trim()).filter(Boolean)
      const at = lines.findIndex((l) => l.startsWith("From, for"))
      const price = at >= 0 ? lines[at + 1] ?? null : null
      hotels.push({ hotel: name, price, amount: price ? moneyAmount(price) : null })
    }
    return { view: "hotels", hotels, rates: [] }
  }
  if (!heading.startsWith("Choose")) return { view: "none", hotels: [], rates: [] }
  const rates: RatePrice[] = []
  for (const card of await roomCards(page).all()) {
    const room = ((await card.getByRole("heading", { level: 3 }).first().textContent()) ?? "").trim()
    for (const btn of await card.getByRole("button", { name: /^Select(ed)?: / }).all()) {
      const label = (await btn.getAttribute("aria-label")) ?? ""
      const rest = label.replace(/^Select(ed)?: /, "").slice(room.length + 2).split(", ")
      const price = rest.pop() ?? ""
      const board = rest.pop() ?? ""
      rates.push({ room, ratePlan: rest.join(", "), board, price, amount: moneyAmount(price) })
    }
  }
  return { view: "rooms", hotels: [], rates }
}

/** Room cards of the active room (each has a heading and a list of rates). */
function roomCards(page: Page) {
  return page.getByRole("region", { name: /^Choose (your room|room \d+)$/ }).getByRole("listitem").filter({ has: page.getByRole("list", { name: /^Rates for / }) })
}

/** Group sites: open a hotel from the hotel list and return the rates on screen. */
export async function openHotel(page: Page, hotel: string): Promise<SearchPrices> {
  await waitForResults(page)
  await page.getByRole("button", { name: `See rooms at ${hotel}`, exact: true }).click()
  await expect(page.getByRole("heading", { level: 2, name: /^Choose (your room|room \d+)$/ })).toBeVisible({ timeout: 30_000 })
  await expect(roomCards(page).first()).toBeVisible()
  return visiblePrices(page)
}

/** Select a rate on the results screen and return it (price as shown before selecting). */
export async function pickRoom(page: Page, opts: PickRoomOptions): Promise<RatePrice> {
  await waitForResults(page)
  const h2 = page.getByRole("heading", { level: 2, name: RESULTS_HEADING }).first()
  if (((await h2.textContent()) ?? "").trim() === "Choose your hotel") {
    if (!opts.hotel) throw new Error("pickRoom: the hotel list is shown; pass { hotel }")
    await openHotel(page, opts.hotel)
  }
  const tabs = page.getByRole("navigation", { name: "Rooms in your booking" })
  const multi = (await tabs.count()) > 0
  let index = opts.roomIndex
  if (multi && index !== undefined) {
    await tabs.getByRole("button", { name: new RegExp(`^Room ${index + 1}\\s*,`) }).click()
    await expect(page.getByRole("heading", { level: 2, name: `Choose room ${index + 1}` })).toBeVisible()
  }
  if (multi && index === undefined) index = Number(/room (\d+)/.exec((await h2.textContent()) ?? "")?.[1] ?? "1") - 1

  const card = roomCards(page).filter({ has: page.getByRole("heading", { level: 3, name: opts.roomName, exact: true }) })
  await expect(card, `room card ${opts.roomName}`).toHaveCount(1)
  if (opts.board) {
    const radio = card.getByRole("radio", { name: opts.board, exact: true })
    if (await radio.count()) {
      if (!(await radio.isChecked())) await card.locator("label").filter({ has: radio }).click()
      await expect(radio).toBeChecked()
    }
  }
  const name = new RegExp(`^Select: ${esc(opts.roomName)}, ${opts.ratePlan ? esc(opts.ratePlan) : ".+"}, ${opts.board ? esc(opts.board) : "[^,]+"}, `)
  const btn = card.getByRole("button", { name }).first()
  await expect(btn, `rate ${[opts.roomName, opts.ratePlan, opts.board].filter(Boolean).join(" / ")}`).toBeEnabled()
  const label = (await btn.getAttribute("aria-label")) ?? ""
  const rest = label.replace(/^Select: /, "").slice(opts.roomName.length + 2).split(", ")
  const price = rest.pop() ?? ""
  const board = rest.pop() ?? ""
  await btn.click()
  if (multi) await expect(tabs.getByRole("button", { name: new RegExp(`^Room ${(index ?? 0) + 1}\\s*, chosen: ${esc(opts.roomName)}`) })).toBeVisible()
  else await expect(card.getByRole("button", { name: /^Selected: / })).toHaveAttribute("aria-pressed", "true")
  return { room: opts.roomName, ratePlan: rest.join(", "), board, price, amount: moneyAmount(price) }
}

/** Continue to the next booking step (rooms → extras → details) and return its heading. */
export async function nextStep(page: Page) {
  const before = await stepHeading(page)
  await visible(page.getByRole("button", { name: "Continue", exact: true })).click()
  await expect
    .poll(async () => {
      const alert = page.getByRole("alert").filter({ hasText: /./ })
      if (await alert.count()) {
        const text = ((await alert.first().textContent()) ?? "").trim()
        if (text && !/^Please fix/.test(text)) throw new Error(`booking flow error: ${text}`)
      }
      return stepHeading(page)
    }, { timeout: 30_000 })
    .not.toBe(before)
  return stepHeading(page)
}

async function goToStep(page: Page, heading: string) {
  for (let i = 0; i < 3; i++) {
    if ((await stepHeading(page)) === heading) return
    await nextStep(page)
  }
  await expect(page.getByRole("heading", { level: 1 })).toHaveText(heading)
}

/** Add an extra on the extras step (continuing there from the rooms step if needed).
 * Counted extras are set to `quantity`; per-date extras get the first `quantity` dates. */
export async function addExtra(page: Page, opts: { name: string; quantity?: number; roomIndex?: number }) {
  const quantity = opts.quantity ?? 1
  await goToStep(page, "Make your stay special")
  const section = page.getByRole("region", { name: new RegExp(`^Room ${(opts.roomIndex ?? 0) + 1} · `) })
  const scope = (await section.count()) ? section : page.getByRole("main")
  const item = scope.getByRole("listitem").filter({ has: page.getByRole("heading", { level: 3, name: opts.name, exact: true }) })
  await expect(item, `extra ${opts.name}`).toHaveCount(1)
  const more = item.getByRole("button", { name: `More ${opts.name}`, exact: true })
  const box = item.getByRole("checkbox", { name: new RegExp(`: ${esc(opts.name)}$`) })
  const dates = item.getByRole("group", { name: "Choose the dates" })
  if (await more.count()) {
    await setCounter(item.getByRole("group", { name: "Quantity" }), quantity, `More ${opts.name}`, `Fewer ${opts.name}`)
  } else if (await box.count()) {
    await box.setChecked(quantity > 0)
  } else if (await dates.count()) {
    const days = dates.getByRole("checkbox")
    const n = await days.count()
    for (let i = 0; i < n; i++) await days.nth(i).setChecked(i < quantity)
  } else {
    // mandatory extras are included by the hotel and cannot be changed
    await expect(item.getByText("Included — required by the hotel")).toBeVisible()
  }
  const price = ((await item.getByRole("heading", { level: 3 }).locator("xpath=../following-sibling::p[1]").first().textContent().catch(() => "")) ?? "").trim()
  return { price }
}

/** Fill the guest form (continuing there from rooms / extras if needed) and go on to payment. */
export async function fillGuest(page: Page, guest: GuestDetails) {
  await goToStep(page, "Your details")
  await page.getByLabel("First name", { exact: true }).fill(guest.firstName)
  await page.getByLabel("Last name", { exact: true }).fill(guest.lastName)
  await page.getByLabel("Email", { exact: true }).fill(guest.email)
  await page.getByLabel("Mobile phone", { exact: true }).fill(guest.phone)
  if (guest.country) {
    const country = page.getByLabel(/^Country of residence/)
    await country.selectOption(/^[A-Za-z]{2}$/.test(guest.country) ? guest.country.toUpperCase() : { label: guest.country })
  }
  if (guest.requests !== undefined) await page.getByLabel(/^Anything the hotel should know\?/).fill(guest.requests)
  if (guest.marketingEmail !== undefined) await page.getByRole("checkbox", { name: "Email me offers and news" }).setChecked(guest.marketingEmail)
  await visible(page.getByRole("button", { name: "Continue to payment", exact: true })).click()
  const problems = page.getByRole("alert").filter({ hasText: /^Please fix/ })
  await expect
    .poll(async () => {
      if (await problems.count()) throw new Error(`guest form: ${((await problems.first().innerText()) ?? "").replace(/\s+/g, " ")}`)
      return stepHeading(page)
    }, { timeout: 30_000 })
    .toBe("Payment")
}

export interface SandboxPayment {
  /** amount charged on the sandbox page as shown */
  amount: string
  transaction: string
  /** amount the book button announced ("Book and pay €…"), when it did */
  dueNow: string | null
}

/** On the payment step: choose card, accept the conditions, book and finish on the
 * sandbox provider page with the given outcome (lands on the confirmation page). */
export async function payWithSandbox(page: Page, outcome: "success" | "fail"): Promise<SandboxPayment> {
  await expect(page.getByRole("heading", { level: 1 })).toHaveText("Payment")
  const card = page.getByRole("radio", { name: /^Credit or debit card/ }).first()
  await expect(card, "card payment offered").toBeVisible()
  await card.check()
  await page.getByRole("checkbox", { name: /^I have read the cancellation and payment conditions/ }).check()
  const book = visible(page.getByRole("button", { name: /^Book and pay/ }))
  await expect(book).toBeEnabled()
  const dueNow = /^Book and pay (.+)$/.exec(((await book.textContent()) ?? "").trim())?.[1] ?? null
  await book.click()
  return { ...(await completeSandbox(page, outcome)), dueNow }
}

/** On the payment step: pay at the hotel, accept the conditions and book (nothing is
 * charged now, so the engine goes straight to the confirmation page). */
export async function bookPayAtHotel(page: Page) {
  await expect(page.getByRole("heading", { level: 1 })).toHaveText("Payment")
  const atHotel = page.getByRole("radio", { name: /^Pay at the hotel/ }).first()
  await expect(atHotel, "pay at the hotel offered").toBeVisible()
  await atHotel.check()
  await page.getByRole("checkbox", { name: /^I have read the cancellation and payment conditions/ }).check()
  const book = visible(page.getByRole("button", { name: "Book now", exact: true }))
  await expect(book).toBeEnabled()
  await book.click()
}

/** The sandbox provider page: simulate the outcome and return to the booking engine. */
export async function completeSandbox(page: Page, outcome: "success" | "fail"): Promise<Omit<SandboxPayment, "dueNow">> {
  await page.waitForURL(/\/book\/pay\/mock\//, { timeout: 30_000 })
  await expect(page.getByRole("heading", { name: "Sandbox payment page" })).toBeVisible()
  const dd = (term: string) => page.locator("dt", { hasText: new RegExp(`^${esc(term)}$`) }).locator("xpath=following-sibling::dd[1]")
  const amount = ((await dd("Test amount").textContent()) ?? "").trim()
  const transaction = ((await dd("Transaction").textContent()) ?? "").trim()
  await page.getByRole("button", { name: outcome === "success" ? "Simulate successful payment" : "Simulate declined payment" }).click()
  await page.waitForURL(/\/book\/[^/]+\/confirmation\//, { timeout: 30_000 })
  return { amount, transaction }
}

/** Read the confirmation page once the payment outcome is known. `url` is where the page
 * is expected (default: the platform's /book/<slug>/confirmation/<booking>). */
export async function readConfirmation(page: Page, opts: { url?: RegExp } = {}): Promise<Confirmation> {
  await page.waitForURL(opts.url ?? /\/book\/[^/]+\/confirmation\/[^/?#]+/, { timeout: 30_000 })
  const h1 = page.getByRole("heading", { level: 1 })
  await expect(h1).toBeVisible({ timeout: 30_000 })
  // the page re-checks a payment the provider has not reported yet
  await expect(h1).not.toHaveText(/^(We're confirming your payment|Loading)/, { timeout: 45_000 })
  const booking = decodeURIComponent(/\/confirmation\/([^/?#]+)/.exec(page.url())?.[1] ?? "")
  await expect(page.getByText(booking, { exact: true }).first()).toBeVisible()
  const dd = (term: string) => page.locator("dt", { hasText: new RegExp(`^${esc(term)}$`) }).locator("xpath=following-sibling::dd[1]")
  const total = ((await dd("Total").first().textContent()) ?? "").trim()
  const status = ((await page.getByRole("status", { name: "Booking status" }).textContent()) ?? "").trim()
  const pay = dd("Payment status")
  const paymentStatus = (await pay.count()) ? ((await pay.first().textContent()) ?? "").trim() : null
  return { booking, total, amount: moneyAmount(total), status, paymentStatus, heading: ((await h1.textContent()) ?? "").trim() }
}
