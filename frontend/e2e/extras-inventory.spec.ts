// G-19: limited daily inventory of extras (spa slots…). The revenue manager closes one day
// of the demo hotel's massage in Inventory → Extras; the guest's booking engine then offers
// that day as sold out (never with counts) and a staff quote refuses it; re-opened with a
// capacity of one, the grid shows 0/1. The day is far in the future, chosen free of any
// sale, and put back as it was (open, default capacity, no note) even when a step fails.
//   TEX_E2E_BASE=http://test.localhost:8000 TEX_E2E_PASSWORD=… npx playwright test -c e2e extras-inventory
import { expect, test, type Locator, type Page } from "@playwright/test"
import { byLabel, esc, isoDate, login, pageApi, texPath, trackErrors, uniqueRunId } from "./helpers"
import { guestSearch, nextStep, pickRoom } from "./flows/booking"

const HOTEL = "Aurora Beach Resort"
const SLUG = "aurora"
/** Demo data: a service-date extra with four slots a day. */
const EXTRA = { code: "MASSAGE", name: "Massage (60 min)", capacity: 4 }

test.use({ locale: "en-US" })

interface GridCell {
  date: string
  capacity: number
  override: number | null
  closed: boolean
  sold: number
  remaining: number
  note: string | null
}
interface Grid {
  dates: string[]
  extras: { code: string; name: string; daily_capacity: number; cells: GridCell[] }[]
}
interface QuoteExtra {
  code: string
  ok: boolean
  reason: string
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

/** A day ~300 days ahead that nothing has touched (no sale, override, closure or note),
 * with open neighbours so the guest can still pick another day of a 2-night stay. */
async function freeDay(page: Page): Promise<string> {
  const start = isoDate(290 + Math.floor(Math.random() * 30))
  const g = await pageApi<Grid>(page, "kamra.tex.api.crs.extras_grid", { property: HOTEL, start, days: 14 })
  expect(g.ok, JSON.stringify(g.body).slice(0, 300)).toBeTruthy()
  const row = g.message.extras.find((x) => x.code === EXTRA.code)
  expect(row, `${EXTRA.code} is a limited extra at ${HOTEL}`).toBeTruthy()
  expect(row!.daily_capacity).toBe(EXTRA.capacity)
  const c = row!.cells
  const untouched = (x: GridCell) => x.sold === 0 && !x.closed && x.override === null && !x.note
  const open = (x: GridCell) => !x.closed && x.remaining > 0
  for (let i = 1; i < c.length - 1; i++) if (untouched(c[i]) && open(c[i - 1]) && open(c[i + 1])) return c[i].date
  throw new Error(`no untouched ${EXTRA.code} day from ${start}`)
}

/** How the grid names a day ("Tuesday 20 Jul 2027") and the caption date ("20 Jul 2027"). */
async function dayNames(page: Page, iso: string) {
  return page.evaluate((d) => {
    const x = new Date(`${d}T12:00:00`)
    return {
      weekday: new Intl.DateTimeFormat("en-GB", { weekday: "long" }).format(x),
      medium: new Intl.DateTimeFormat("en-GB", { dateStyle: "medium" }).format(x),
    }
  }, iso)
}

/** Value next to a <dt> term in a description list. */
const dd = (scope: Locator, term: string) => scope.locator("dt", { hasText: new RegExp(`^${esc(term)}$`) }).locator("xpath=following-sibling::dd[1]")

/** Staff quote of a 2-night stay around `day` with the extra on that service date. */
async function staffQuote(page: Page, day: string, quantity: number): Promise<{ ok: boolean; extra: QuoteExtra | undefined }> {
  const s = await pageApi<{ properties: { offers: { rooms: { offer_key: string }[] }[] }[] }>(page, "kamra.tex.api.ui_crs.search", {
    check_in: addDays(day, -1),
    check_out: addDays(day, 1),
    rooms: [{ adults: 2, children: [] }],
    market: "DE",
    properties: [HOTEL],
  })
  expect(s.ok, JSON.stringify(s.body).slice(0, 300)).toBeTruthy()
  const offer = s.message.properties[0]?.offers[0]
  expect(offer, `an offer at ${HOTEL} around ${day}`).toBeTruthy()
  const q = await pageApi<{ ok: boolean; reasons?: unknown; quote: { extras: QuoteExtra[] } }>(page, "kamra.tex.api.crs.quote", {
    offer_key: offer!.rooms[0].offer_key,
    extras: [{ code: EXTRA.code, quantity, service_dates: [day] }],
  })
  expect(q.ok, JSON.stringify(q.body).slice(0, 300)).toBeTruthy()
  expect(q.message.ok, `room quote: ${JSON.stringify(q.message.reasons ?? "")}`).toBe(true)
  return { ok: q.message.ok, extra: q.message.quote.extras.find((e) => e.code === EXTRA.code) }
}

/** Open the change dialog of one day from its cell (cell → day dialog → Change this day). */
async function changeThisDay(page: Page, cell: Locator) {
  await cell.click()
  const day = page.getByRole("dialog", { name: new RegExp(`^${esc(EXTRA.name)} · `) })
  await expect(day).toBeVisible()
  await day.getByRole("button", { name: "Change this day" }).click()
  const dialog = page.getByRole("dialog", { name: "Change limited extras" })
  await expect(dialog).toBeVisible()
  await expect(dialog.getByText("1 day selected")).toBeVisible()
  return dialog
}

/** Review, check the listed changes, apply to one cell and wait for the toast. */
async function reviewAndApply(page: Page, dialog: Locator, lines: string[]) {
  await dialog.getByRole("button", { name: "Review changes" }).click()
  await expect(dialog.getByText("Days: 1 × extras: 1 = cells to update: 1.")).toBeVisible()
  await expect(dd(dialog, "Extras")).toHaveText(EXTRA.name)
  await expect(dialog.getByRole("listitem")).toHaveText(lines)
  await dialog.getByRole("button", { name: "Apply to 1 cell" }).click()
  await expect(dialog).toBeHidden()
  await expect(page.getByRole("status").filter({ hasText: "1 cell updated" }).last()).toBeVisible()
}

test("limited extra: close a day in Inventory → Extras, guests and quotes see it, re-open with capacity 1", async ({ page, browser }) => {
  test.setTimeout(240_000)
  const noErrors = trackErrors(page)
  const note = `E2E spa closed ${uniqueRunId()}`
  await english(page)
  await login(page, "revenue@demo.tex")
  await page.goto(texPath("/tex/inventory"))
  const day = await freeDay(page)
  const names = await dayNames(page, day)
  // a cell's accessible name: "<extra>, <weekday> <date>: " + `rest` (a regex source)
  const cellName = (rest: string) => new RegExp(`^${esc(`${EXTRA.name}, ${names.weekday} ${names.medium}: `)}${rest}`)

  let restored: { ok: boolean; body: unknown } | undefined
  try {
    const cell = page.getByRole("gridcell", { name: cellName("") })

    await test.step("Inventory → Extras shows the massage for the hotel; the grid moves to the chosen day", async () => {
      await page.getByRole("banner").getByRole("combobox", { name: "Hotel" }).selectOption(HOTEL)
      await page.getByRole("navigation", { name: "Rates & availability views" }).getByRole("link", { name: "Extras" }).click()
      await expect(page).toHaveURL(/\/tex\/inventory\/extras$/)
      const row = page.getByRole("row").filter({ has: page.getByRole("rowheader", { name: new RegExp(`^${esc(EXTRA.name)}`) }) })
      await expect(row).toBeVisible()
      await expect(row.getByRole("rowheader")).toContainText(`${EXTRA.code} · ${EXTRA.capacity}/day`)

      await byLabel(page, "Start date").fill(day)
      await expect(page.getByRole("grid", { name: new RegExp(`^Limited extras from ${esc(names.medium)} to `) })).toBeVisible()
      await expect(row.getByRole("gridcell").first()).toHaveAccessibleName(cellName(""))
      // sold / capacity and what is left, also in the cell's accessible name
      await expect(cell).toHaveText(new RegExp(`^0/${EXTRA.capacity}\\s*${EXTRA.capacity} left$`))
      await expect(cell).toHaveAccessibleName(cellName(`0 of ${EXTRA.capacity} sold, ${EXTRA.capacity} left$`))
    })

    await test.step("the change dialog closes the day with a note; the day dialog shows it", async () => {
      const dialog = await changeThisDay(page, cell)
      await byLabel(dialog, "Sale").selectOption({ label: "Close for sale" })
      await dialog.getByRole("checkbox", { name: "Change the note" }).check()
      await byLabel(dialog, "Note").fill(note)
      await reviewAndApply(page, dialog, ["Sale: Closed for sale", `Note: “${note}”`])

      await expect(cell).toHaveText(new RegExp(`^0/${EXTRA.capacity}\\s*Closed$`))
      await expect(cell).toHaveAccessibleName(cellName(`0 of ${EXTRA.capacity} sold, ${EXTRA.capacity} left, Closed for sale, note: ${esc(note)}$`))
      await cell.click()
      const detail = page.getByRole("dialog", { name: new RegExp(`^${esc(EXTRA.name)} · `) })
      await expect(dd(detail, "Sale")).toHaveText("Closed for sale")
      await expect(dd(detail, "Note")).toHaveText(note)
      await expect(dd(detail, "Capacity")).toHaveText(`${EXTRA.capacity} (default)`)
      await detail.getByRole("button", { name: "Close" }).last().click()
      await expect(detail).toBeHidden()
    })

    await test.step("guests see the day as not available, without counts; a staff quote refuses it", async () => {
      const guest = await browser.newContext({ baseURL: test.info().project.use.baseURL, locale: "en-US" })
      try {
        const gp = await guest.newPage()
        const guestErrors = trackErrors(gp)
        // the public endpoint, as an anonymous guest
        const r = await gp.request.post("/api/method/kamra.tex.api.public.extras_availability", {
          data: { site: SLUG, hotel: HOTEL, check_in: addDays(day, -1), check_out: addDays(day, 1) },
        })
        const body = (await r.json().catch(() => ({}))) as { message?: Record<string, Record<string, Record<string, boolean>>> }
        expect(r.ok(), JSON.stringify(body).slice(0, 300)).toBeTruthy()
        const days = body.message?.[EXTRA.code] ?? {}
        expect(days[day]).toEqual({ available: false, low: false })
        expect(days[addDays(day, -1)]?.available).toBe(true)
        for (const d of Object.values(body.message ?? {}).flatMap((x) => Object.values(x))) expect(Object.keys(d).sort()).toEqual(["available", "low"])
        expect(JSON.stringify(body)).not.toMatch(/remaining|capacity|sold|held|\bleft\b/)

        // the booking engine's extras step: that day cannot be chosen, the others can
        const found = await guestSearch(gp, { slug: SLUG, checkIn: addDays(day, -1), checkOut: addDays(day, 1), rooms: [{ adults: 2 }], hotel: HOTEL })
        expect(found.view).toBe("rooms")
        expect(found.rates.length, "rates on offer").toBeGreaterThan(0)
        await pickRoom(gp, { roomName: found.rates[0].room, ratePlan: found.rates[0].ratePlan, board: found.rates[0].board })
        expect(await nextStep(gp)).toBe("Make your stay special")
        const item = gp
          .getByRole("main")
          .getByRole("listitem")
          .filter({ has: gp.getByRole("heading", { level: 3, name: EXTRA.name, exact: true }) })
        await expect(item).toHaveCount(1)
        const chips = item.getByRole("group", { name: "Choose the dates" }).getByRole("checkbox")
        await expect(chips).toHaveCount(3) // arrival, the closed day, departure
        await expect(chips.nth(1)).toBeDisabled()
        await expect(chips.nth(1)).toHaveAccessibleName(/· Sold out$/)
        await expect(chips.nth(0)).toBeEnabled()
        await expect(chips.nth(0)).not.toHaveAccessibleName(/Sold out/)
        await expect(item).not.toContainText(/\d+ left/)
        guestErrors()
      } finally {
        await guest.close()
      }

      const q = await staffQuote(page, day, 1)
      expect(q.extra).toMatchObject({ ok: false, reason: `closed on ${day}` })
    })

    await test.step("re-opened with a capacity of 1, the cell shows 0/1; then the day is put back", async () => {
      await page.getByRole("button", { name: "Change", exact: true }).click()
      const dialog = page.getByRole("dialog", { name: "Change limited extras" })
      await expect(dialog).toBeVisible()
      await dialog.getByRole("checkbox", { name: "All limited extras" }).uncheck()
      await dialog.getByRole("checkbox", { name: new RegExp(`^${esc(EXTRA.name)} ${EXTRA.code}$`) }).check()
      await byLabel(dialog, "From").fill(day)
      await byLabel(dialog, "To (inclusive)").fill(day)
      await expect(dialog.getByText("1 day selected")).toBeVisible()
      await byLabel(dialog, "Capacity per day").fill("1")
      await byLabel(dialog, "Sale").selectOption({ label: "Open for sale" })
      await reviewAndApply(page, dialog, ["Capacity: 1 per day", "Sale: Open for sale"])

      await expect(cell).toHaveText(/^0\/1\s*1 left$/)
      await expect(cell).toHaveAccessibleName(
        cellName(`0 of 1 sold, 1 left, capacity changed for this day \\(default ${EXTRA.capacity}\\), note: ${esc(note)}$`),
      )
      // one left: guests are told "few left" (still no count); two are refused, one is quoted
      const pub = await pageApi<Record<string, Record<string, { available: boolean; low: boolean }>>>(page, "kamra.tex.api.public.extras_availability", {
        site: SLUG,
        hotel: HOTEL,
        check_in: addDays(day, -1),
        check_out: addDays(day, 1),
      })
      expect(pub.ok, JSON.stringify(pub.body).slice(0, 300)).toBeTruthy()
      expect(pub.message[EXTRA.code][day]).toEqual({ available: true, low: true })
      expect((await staffQuote(page, day, 2)).extra).toMatchObject({ ok: false, reason: `only 1 left on ${day}` })
      expect((await staffQuote(page, day, 1)).extra).toMatchObject({ ok: true })

      // put back: default capacity, no note (the day is already open)
      const back = await changeThisDay(page, cell)
      await byLabel(back, "Capacity per day").fill("0")
      await back.getByRole("checkbox", { name: "Change the note" }).check()
      await expect(byLabel(back, "Note")).toHaveValue("") // an empty note removes it
      await reviewAndApply(page, back, ["Capacity: back to the default", "Note: removed"])
      await expect(cell).toHaveText(new RegExp(`^0/${EXTRA.capacity}\\s*${EXTRA.capacity} left$`))
      await expect(cell).toHaveAccessibleName(cellName(`0 of ${EXTRA.capacity} sold, ${EXTRA.capacity} left$`))
    })
  } finally {
    // whatever happened above: open, default capacity, no note
    restored = await pageApi(page, "kamra.tex.api.crs.extras_bulk_update", {
      property: HOTEL,
      extra_codes: [EXTRA.code],
      start: day,
      end: day,
      capacity: 0,
      closed: 0,
      note: "",
    }).catch((e: unknown) => ({ ok: false, body: String(e) }))
  }
  expect(restored?.ok, `restore ${day}: ${JSON.stringify(restored?.body).slice(0, 300)}`).toBeTruthy()
  const after = await pageApi<Grid>(page, "kamra.tex.api.crs.extras_grid", { property: HOTEL, start: day, days: 1 })
  const back = after.message.extras.find((x) => x.code === EXTRA.code)?.cells[0]
  expect(back).toMatchObject({ closed: false, override: null, capacity: EXTRA.capacity })
  expect(back?.note ?? "", "the note is removed").toBe("")
  noErrors()
})
