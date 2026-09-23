// G-22 (ADR-034): extras added to a booked stay. A guest books a far-future stay on the demo
// booking site (public API, pay at the hotel), then adds a late check-out and a massage on
// the second day from the manage page: the add-on is priced on its own, the review shows
// its total and the new total (old + add-on), and the booking's balance grows by exactly
// that. The revenue manager sees the guest's add-on on the reservation, adds an airport
// transfer at the desk (price → add with a note), finds it in the revision history as an
// add-on, and removes it again through Modify; the total goes back. The reservation is
// cancelled at the end (a hotel admin waives the fee) so the massage slot is released.
// Runs in the desktop project and in the mobile one (390 px wide, guest and staff).
//   TEX_E2E_BASE=http://test.localhost:8000 TEX_E2E_PASSWORD=… npx playwright test -c e2e post-booking-extras
import { devices, expect, test, type APIRequestContext, type BrowserContext, type Locator, type Page } from "@playwright/test"
import { api, esc, isoDate, login, pageApi, PASSWORD, trackErrors, uniqueRunId } from "./helpers"
import { moneyAmount } from "./flows/booking"
import { applyChange, openReservation, proposeChange, readLockedPrice, readRevisions } from "./flows/reservations"

const SLUG = "aurora"
const HOTEL = "Aurora Beach Resort"
/** Demo extras sold online and after booking: two per-booking ones and a limited massage. */
const LCO = { code: "LCO", name: "Late check-out" }
const MASSAGE = { code: "MASSAGE", name: "Massage (60 min)" }
const TRF = { code: "TRF", name: "Airport transfer" }
/** Staff who may cancel and waive the fee (the revenue manager may not cancel). */
const HOTEL_ADMIN = "beach.gm@demo.tex"

interface Booked {
  booking: string
  reservation: string
  total: string
  token: string
}
interface AddonProposal {
  ok: boolean
  reasons: { code: string; message: string }[]
  currency: string
  old_total: string
  new_total: string | null
  proposal_token: string | null
  lines: { kind: string; code: string; description: string; amount: string }[]
  extras: { code: string; service_dates: string[] }[]
  totals: { total: string }
}
interface AddonApplied {
  reservation: string
  addon: string
  total: string
  currency: string
  replay: boolean
  booking: string
  balance: string
  payment_status: string
}
interface StaffProposal {
  ok: boolean
  reasons: { code: string; message: string }[]
  old_total: string
  new_total: string
  proposal_token: string
  addon: { totals: { total: string }; explanation?: { code?: string; rule?: string }[] }
}
interface GuestBooking {
  total: string
  balance: string
  payment_status: string
  rooms: { reservation: string; amount: string; extras: { code: string; service_dates?: string[] }[] }[]
}
interface GridCell {
  date: string
  sold: number
}
interface Grid {
  extras: { code: string; cells: GridCell[] }[]
}

/** Exact decimal strings as cents (no floats for money); signed. */
const cents = (amount: string) => {
  const s = amount.trim()
  const [whole, frac = ""] = s.replace(/^[-+]/, "").split(".")
  const v = BigInt(whole + frac.padEnd(2, "0").slice(0, 2))
  return s.startsWith("-") ? -v : v
}

const addDays = (iso: string, n: number) => {
  const d = new Date(`${iso}T12:00:00Z`)
  d.setUTCDate(d.getUTCDate() + n)
  return d.toISOString().slice(0, 10)
}

/** Nothing on screen is wider than the viewport, nor than `scope` (a dialog or drawer). */
async function noSideScroll(page: Page, scope?: Locator) {
  expect(await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth), "page scrolls sideways").toBeLessThanOrEqual(0)
  if (scope) expect(await scope.evaluate((el) => el.scrollWidth - el.clientWidth), "dialog scrolls sideways").toBeLessThanOrEqual(1)
}

/** Value next to a <dt> term in a description list. */
const dd = (scope: Locator, term: string) => scope.locator("dt", { hasText: new RegExp(`^${esc(term)}$`) }).locator("xpath=following-sibling::dd[1]")

async function english(page: Page) {
  await page.addInitScript(() => {
    try {
      localStorage.setItem("tex.book.lang", "en")
      localStorage.setItem("tex-lang", "en")
    } catch {
      /* storage blocked: the default language is English */
    }
  })
}

/** A 2-night stay ~250–280 days ahead whose second day still has massage slots (and not
 * just a few, so the guest's day chip is a plain one). */
async function freeStay(req: APIRequestContext) {
  for (let i = 0; i < 10; i++) {
    const checkIn = isoDate(250 + Math.floor(Math.random() * 30))
    const checkOut = addDays(checkIn, 2)
    const a = await api<Record<string, Record<string, { available: boolean; low: boolean }>>>(req, "kamra.tex.api.public.extras_availability", {
      site: SLUG,
      hotel: HOTEL,
      check_in: checkIn,
      check_out: checkOut,
    })
    const day = a[MASSAGE.code]?.[addDays(checkIn, 1)]
    if (day?.available && !day.low) return { checkIn, checkOut, day2: addDays(checkIn, 1) }
  }
  throw new Error(`no stay with ${MASSAGE.code} slots left ~250–280 days ahead`)
}

/** Book a refundable room without extras through the public booking API, paid at the hotel. */
async function bookStay(req: APIRequestContext, checkIn: string, checkOut: string, run: string): Promise<Booked> {
  const session_id = `e2e-addon-${run.toLowerCase()}`
  const s = await api<{ properties: { offers: { refundable: boolean; rooms: { offer_key: string }[] }[] }[] }>(req, "kamra.tex.api.public.search", {
    site: SLUG,
    hotel: HOTEL,
    check_in: checkIn,
    check_out: checkOut,
    rooms: [{ adults: 2, children: [] }],
    session_id,
  })
  const offers = s.properties[0]?.offers ?? []
  expect(offers.length, `offers at ${HOTEL} ${checkIn}–${checkOut}`).toBeGreaterThan(0)
  const offer = offers.find((o) => o.refundable) ?? offers[0]
  const q = await api<{ ok: boolean; quote_id: string }>(req, "kamra.tex.api.public.quote", { site: SLUG, offer_key: offer.rooms[0].offer_key, session_id })
  expect(q.ok, "quote").toBe(true)
  const b = await api<{ booking: string; status: string; total: string; payment_status: string; manage_token: string; rooms: { reservation: string }[] }>(
    req,
    "kamra.tex.api.public.book",
    {
      site: SLUG,
      quote_ids: [q.quote_id],
      guest: { first_name: "Mara", last_name: `Addon ${run}`, email: `mara.${run.toLowerCase()}@example.com`, phone: "+49 170 7654321", country: "DE" },
      payment_method: "Pay at Hotel",
      idempotency_key: `e2e-addon-${run}`,
      session_id,
    },
  )
  expect(b.status).toBe("Confirmed")
  expect(b.payment_status).toBe("Pay at Hotel")
  expect(b.manage_token, "the guest's manage token").toBeTruthy()
  return { booking: b.booking, reservation: b.rooms[0].reservation, total: b.total, token: b.manage_token }
}

/** Massage slots sold on a day (staff inventory grid). */
async function massageSold(page: Page, day: string): Promise<number> {
  const g = await pageApi<Grid>(page, "kamra.tex.api.crs.extras_grid", { property: HOTEL, start: day, days: 1 })
  expect(g.ok, JSON.stringify(g.body).slice(0, 300)).toBeTruthy()
  const cell = g.message.extras.find((x) => x.code === MASSAGE.code)?.cells.find((c) => c.date === day)
  expect(cell, `${MASSAGE.code} on ${day} in the grid`).toBeTruthy()
  return cell!.sold
}

test.beforeEach(async ({ page }, testInfo) => {
  if (testInfo.project.name === "mobile") await page.setViewportSize({ width: 390, height: 844 })
})

/** Browser contexts a test opened itself (the staff's), closed whatever happened. */
const opened: BrowserContext[] = []
test.afterEach(async () => {
  for (const c of opened.splice(0)) await c.close()
})

test("extras added after booking: the guest adds them online, staff add and remove one; the stay stays price-locked", async ({ page, browser, request }, testInfo) => {
  test.setTimeout(240_000)
  const mobile = testInfo.project.name === "mobile"
  const baseURL = testInfo.project.use.baseURL
  const run = uniqueRunId()
  const noGuestErrors = trackErrors(page)
  await english(page)

  // staff browser (same viewport as the guest's)
  const staffCtx = await browser.newContext(
    mobile ? { ...devices["Pixel 7"], viewport: { width: 390, height: 844 }, baseURL, locale: "en-US" } : { viewport: { width: 1440, height: 900 }, baseURL, locale: "en-US" },
  )
  opened.push(staffCtx)
  const sp = await staffCtx.newPage()
  const noStaffErrors = trackErrors(sp)
  await english(sp)
  await login(sp, "revenue@demo.tex")

  const { checkIn, checkOut, day2 } = await freeStay(page.request)
  const soldBefore = await massageSold(sp, day2)
  const booked = await bookStay(page.request, checkIn, checkOut, run)
  const res = booked.reservation

  let guestAddon = ""
  let guestTotal = ""
  let cancelled: { ok: boolean; body: unknown } | undefined
  try {
    await test.step("the guest adds a late check-out and a massage on the second day from the manage page", async () => {
      await page.goto(`/book/${SLUG}/manage?lang=en#token=${encodeURIComponent(booked.token)}`)
      await expect(page.getByRole("heading", { level: 1, name: "Manage your booking" })).toBeVisible()
      await expect(page.getByText(booked.booking, { exact: true }).first()).toBeVisible()
      const room = page.getByRole("listitem").filter({ has: page.getByRole("button", { name: "Add extras", exact: true }) })
      await expect(room).toHaveCount(1)
      await room.getByRole("button", { name: "Add extras", exact: true }).click()

      const dlg = page.getByRole("dialog", { name: /^Add extras to / })
      await expect(dlg).toBeVisible()
      const card = (name: string) => dlg.getByRole("listitem").filter({ has: page.getByRole("heading", { level: 3, name, exact: true }) })
      for (const x of [LCO, MASSAGE, TRF]) await expect(card(x.name), `${x.name} is offered`).toHaveCount(1)
      // the transfer needs a day's notice; guests never see how many massages are left
      await expect(card(TRF.name)).toContainText("Order at least 24 hours in advance.")
      await expect(dlg).not.toContainText(/\d+ left/)

      await card(LCO.name).getByRole("checkbox", { name: new RegExp(`: ${esc(LCO.name)}$`) }).check()
      const chips = card(MASSAGE.name).getByRole("group", { name: /^Choose the dates/ }).getByRole("checkbox")
      await expect(chips).toHaveCount(3) // arrival, the second day, departure
      await expect(chips.nth(1)).toBeEnabled()
      const day2Label = ((await chips.nth(1).locator("xpath=..").innerText()) ?? "").replace(/\s+/g, " ").trim()
      await chips.nth(1).check()

      await noSideScroll(page, dlg)
      const [pr] = await Promise.all([
        page.waitForResponse((r) => r.url().includes("kamra.tex.api.public.manage_extras_propose")),
        dlg.getByRole("button", { name: "Check price", exact: true }).click(),
      ])
      const pBody = (await pr.json().catch(() => ({}))) as { message?: AddonProposal }
      expect(pr.ok(), `manage_extras_propose ${pr.status()}: ${JSON.stringify(pBody).slice(0, 300)}`).toBeTruthy()
      const p = pBody.message!
      expect(p.ok, JSON.stringify(p.reasons)).toBe(true)
      expect(p.old_total).toBe(booked.total)
      expect(cents(p.new_total!)).toBe(cents(p.old_total) + cents(p.totals.total))
      expect(p.extras.find((e) => e.code === MASSAGE.code)?.service_dates).toEqual([day2])
      expect(JSON.stringify(p)).not.toMatch(/remaining|capacity|explanation/)

      // the review: each extra, the add-on total, the room total now and with the extras
      const yours = dlg.getByRole("region", { name: "Your extras" })
      await expect(yours).toBeVisible()
      const lco = p.lines.find((l) => l.code === LCO.code)!
      const massage = p.lines.find((l) => l.code === MASSAGE.code)!
      expect(moneyAmount((await dd(yours, LCO.name).innerText()) ?? "")).toBe(lco.amount)
      await expect(yours.locator("dt").filter({ hasText: MASSAGE.name })).toContainText(day2Label)
      expect(moneyAmount(await yours.locator("dt").filter({ hasText: MASSAGE.name }).locator("xpath=following-sibling::dd[1]").innerText())).toBe(massage.amount)
      expect(moneyAmount(await dd(yours, "Extras total").innerText())).toBe(p.totals.total)
      expect(moneyAmount(await dd(dlg, "Room total now").innerText())).toBe(p.old_total)
      const newTotalText = (await dd(dlg, "Room total with extras").innerText()).trim()
      expect(moneyAmount(newTotalText)).toBe(p.new_total)

      await noSideScroll(page, dlg)
      const [ar] = await Promise.all([
        page.waitForResponse((r) => r.url().includes("kamra.tex.api.public.manage_extras_apply")),
        dlg.getByRole("button", { name: "Add to my booking", exact: true }).click(),
      ])
      const aBody = (await ar.json().catch(() => ({}))) as { message?: AddonApplied }
      expect(ar.ok(), `manage_extras_apply ${ar.status()}: ${JSON.stringify(aBody).slice(0, 300)}`).toBeTruthy()
      const a = aBody.message!
      expect(a).toMatchObject({ reservation: res, booking: booked.booking, total: p.new_total, replay: false, payment_status: "Pay at Hotel" })
      expect(a.balance).toBe(p.new_total) // nothing paid yet: the balance is the new total
      guestAddon = p.totals.total
      guestTotal = p.new_total!

      await expect(dlg).toBeHidden()
      const notice = page.getByRole("status").filter({ hasText: "Extras added" })
      await expect(notice).toBeVisible()
      const shown = /Amount to pay at the hotel: (.+)\.$/.exec(((await notice.innerText()) ?? "").replace(/\s+/g, " ").trim())?.[1] ?? ""
      expect(moneyAmount(shown), `notice: ${await notice.innerText()}`).toBe(a.balance)

      // the room lists its extras; its price details show them as added after booking
      await expect(room).toContainText(LCO.name)
      await expect(room).toContainText(`${MASSAGE.name} (${day2Label})`)
      await expect(room).toContainText(newTotalText) // the room's price now includes them
      await room.getByRole("button", { name: "Price details" }).click()
      await expect(room.getByText("Added after booking", { exact: true })).toBeVisible()
      expect(moneyAmount(await dd(room, LCO.name).innerText())).toBe(lco.amount)
      expect(moneyAmount(await dd(room, MASSAGE.name).innerText())).toBe(massage.amount)
      const hotel = page.getByRole("region", { name: HOTEL })
      expect(moneyAmount(await dd(hotel, "Total").innerText())).toBe(p.new_total)
      expect(moneyAmount(await dd(hotel, "To pay at the hotel").innerText())).toBe(p.new_total)
      await noSideScroll(page)

      // the booking's total grew by exactly the add-on
      const st = await api<GuestBooking>(page.request, "kamra.tex.api.public.booking_status", { token: booked.token })
      expect(st.total).toBe(p.new_total)
      expect(cents(st.total) - cents(booked.total)).toBe(cents(p.totals.total))
      expect(st.balance).toBe(p.new_total)
      const ex = st.rooms[0].extras
      expect(ex.map((e) => e.code).sort()).toEqual([LCO.code, MASSAGE.code])
      expect(ex.find((e) => e.code === MASSAGE.code)?.service_dates).toEqual([day2])
      expect(await massageSold(sp, day2)).toBe(soldBefore + 1)
      noGuestErrors()
    })

    let locked = ""
    let staffAddon = ""
    await test.step("staff see the guest's add-on and add an airport transfer at the desk", async () => {
      await openReservation(sp, { reservation: res })
      locked = (await readLockedPrice(sp)).amount ?? ""
      expect(locked).toBe(guestTotal)
      const card = sp.getByRole("region", { name: "Added after booking" })
      await expect(card.locator("li[data-addon]")).toHaveCount(1)
      const guestItem = card.locator("li[data-addon]").first()
      await expect(guestItem).toHaveAttribute("data-total", guestAddon)
      await expect(guestItem).toContainText("Guest (self-service)")
      await expect(guestItem).toContainText(LCO.name)
      await expect(guestItem).toContainText(MASSAGE.name)
      await noSideScroll(sp)

      await sp.getByRole("button", { name: "Add extras", exact: true }).click()
      const drawer = sp.getByRole("dialog", { name: `Add extras to ${res}` })
      await expect(drawer).toBeVisible()
      const row = (code: string) => drawer.locator(`li[data-extra="${code}"]`)
      await expect(row(LCO.code)).toContainText("1 already booked")
      // staff may see how many are left of a limited extra
      await expect(row(MASSAGE.code)).toContainText(/\d+ left/)
      await row(TRF.code).getByRole("button", { name: `More: ${TRF.name}`, exact: true }).click()
      await expect(drawer.getByLabel(TRF.name, { exact: true })).toHaveValue("1")

      const [pr] = await Promise.all([
        sp.waitForResponse((r) => r.url().includes("kamra.tex.api.crs.addon_propose")),
        drawer.getByRole("button", { name: /^Price extras/ }).click(),
      ])
      const pBody = (await pr.json().catch(() => ({}))) as { message?: StaffProposal }
      expect(pr.ok(), `addon_propose ${pr.status()}: ${JSON.stringify(pBody).slice(0, 300)}`).toBeTruthy()
      const p = pBody.message!
      expect(p.ok, JSON.stringify(p.reasons)).toBe(true)
      expect(p.old_total).toBe(locked)
      expect(cents(p.new_total)).toBe(cents(locked) + cents(p.addon.totals.total))
      // the revenue manager may see the explanation (price.view_cost): no promotion on add-ons
      expect(JSON.stringify(p.addon.explanation ?? [])).toContain("ADDON_NO_PROMOTIONS")
      const figure = (name: string) => drawer.getByRole("group", { name, exact: true }).locator("data[value]")
      await expect(figure("Reservation total now")).toHaveAttribute("value", p.old_total)
      await expect(figure("With the extras")).toHaveAttribute("value", p.new_total)
      await expect(figure("Added")).toHaveAttribute("value", p.addon.totals.total)

      await noSideScroll(sp, drawer)
      const note = `Guest asked for a pick-up at the airport (${run})`
      await drawer.getByLabel("Note (optional)", { exact: true }).fill(note)
      const [ar] = await Promise.all([
        sp.waitForResponse((r) => r.url().includes("kamra.tex.api.crs.addon_apply")),
        drawer.getByRole("button", { name: /^Add to reservation/ }).click(),
      ])
      const aBody = (await ar.json().catch(() => ({}))) as { message?: AddonApplied }
      expect(ar.ok(), `addon_apply ${ar.status()}: ${JSON.stringify(aBody).slice(0, 300)}`).toBeTruthy()
      expect(aBody.message).toMatchObject({ reservation: res, total: p.new_total, replay: false, balance: p.new_total })
      staffAddon = aBody.message!.addon
      await expect(drawer).toBeHidden()
      await expect.poll(async () => (await readLockedPrice(sp)).amount).toBe(p.new_total)

      await expect(card.locator("li[data-addon]")).toHaveCount(2)
      const deskItem = card.locator(`li[data-addon="${staffAddon}"]`)
      await expect(deskItem).toHaveAttribute("data-total", p.addon.totals.total)
      await expect(deskItem).toContainText(TRF.name)
      await expect(deskItem).toContainText("Desk")

      // the revision history: two add-ons, neither re-priced the stay
      const revs = await readRevisions(sp)
      expect(revs[0]).toMatchObject({ changeType: "Extras", oldAmount: locked, newAmount: p.new_total })
      expect(revs[0].text).toContain("Add-on (stay not repriced)")
      expect(revs[0].text).toContain(`Added: ${TRF.name} × 1`)
      expect(revs[0].text).toContain(note)
      expect(revs[1]).toMatchObject({ changeType: "Extras", oldAmount: booked.total, newAmount: guestTotal })
      expect(revs[1].text).toContain("Add-on (stay not repriced)")
      expect(revs[1].text).toContain("Guest (self-service)")
      expect(revs[1].text).toContain(`${LCO.name} × 1`)
      expect(revs.at(-1)?.changeType).toBe("Original")
      noStaffErrors()
    })

    await test.step("staff remove the transfer through Modify; the total goes back", async () => {
      await sp.getByRole("button", { name: "Modify", exact: true }).click()
      const md = sp.getByRole("dialog", { name: /^Modify / })
      await expect(md).toBeVisible()
      const drop = md.getByRole("group", { name: "Remove extras added after booking" })
      await expect(drop.getByRole("checkbox")).toHaveCount(2)
      await drop.getByRole("checkbox", { name: new RegExp(`^${esc(TRF.name)} × 1`) }).check()

      const pc = await proposeChange(sp, { basis: "ORIGINAL_VERSION" })
      await noSideScroll(sp, md)
      const before = (await readLockedPrice(sp)).amount ?? ""
      expect(pc.old.amount).toBe(before)
      expect(pc.proposed.amount).toBe(locked)
      expect(cents(pc.difference.amount ?? "")).toBe(cents(locked) - cents(before))
      const removed = md.locator("li[data-addon]")
      await expect(removed).toHaveCount(1)
      await expect(removed).toHaveAttribute("data-addon", staffAddon)
      await expect(md.getByText("1 add-on removed", { exact: true })).toBeVisible()
      await expect(md).toContainText(/Applying this change removes the add-on: Airport transfer × 1/)

      const reason = `Transfer no longer needed (${run})`
      const applied = await applyChange(sp, reason)
      expect(applied).toMatchObject({ reservation: res, old_total: before, new_total: locked })
      expect((await readLockedPrice(sp)).amount).toBe(locked)
      const card = sp.getByRole("region", { name: "Added after booking" })
      await expect(card.locator("li[data-addon]")).toHaveCount(1)
      await expect(card.locator(`li[data-addon="${staffAddon}"]`)).toHaveCount(0)
      const revs = await readRevisions(sp)
      expect(revs[0]).toMatchObject({ changeType: "Extras", oldAmount: before, newAmount: locked })
      expect(revs[0].text).toContain("1 add-on removed")
      expect(revs[0].text).toContain(reason)

      const st = await api<GuestBooking>(page.request, "kamra.tex.api.public.booking_status", { token: booked.token })
      expect(st.total).toBe(guestTotal)
      noStaffErrors()
    })
  } finally {
    // whatever happened above: cancel the stay (fee waived) so its massage slot is released
    cancelled = await (async () => {
      const ok = await request.post("/api/method/login", { data: { usr: HOTEL_ADMIN, pwd: PASSWORD } })
      if (!ok.ok()) return { ok: false, body: `login ${HOTEL_ADMIN}: ${ok.status()}` }
      const r = await request.post("/api/method/kamra.tex.api.crs.cancel", { data: { reservation: res, reason: `E2E clean-up (${run})`, waive_penalty: 1 } })
      return { ok: r.ok(), body: await r.json().catch(() => ({})) }
    })().catch((e: unknown) => ({ ok: false, body: String(e) }))
  }
  expect(cancelled?.ok, `cancel ${res}: ${JSON.stringify(cancelled?.body).slice(0, 300)}`).toBeTruthy()
  expect(await massageSold(sp, day2), `${MASSAGE.code} on ${day2} released`).toBe(soldBefore)
  const st = await api<{ status: string }>(page.request, "kamra.tex.api.public.booking_status", { token: booked.token })
  expect(st.status).toBe("Cancelled")
})
