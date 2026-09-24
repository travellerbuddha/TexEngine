// G-48: restrictions at hotel level, for the Booking Engine + Call Center, with a booking
// window. The revenue manager chooses the "Booking Engine + Call Center" scope in Inventory,
// sets one hotel-level cell (no room type) for a far-future night that is only sold from a
// sale date still to come, and the grid shows it on the hotel row ("All room types") and,
// inherited, on every room row. A call-centre search for a stay through that night is refused
// with the booking window; a B2B search is not (another channel).
// Re-runnable on a shared site: the night is one no booking window touches yet (read from the
// grid), and the cell is cleared again even when a step fails (a clear of a missing cell writes
// nothing), then checked gone.
//   TEX_E2E_BASE=http://test.localhost:8000 TEX_E2E_PASSWORD=… npx playwright test -c e2e restrictions-grid
import { expect, test, type Page } from "@playwright/test"
import { byLabel, esc, isoDate, login, pageApi, texPath, trackErrors } from "./helpers"

const HOTEL = "Aurora Beach Resort"
const SCOPE = "Booking Engine + Call Center"

test.use({ locale: "en-US" })

interface Entry {
  bookable: boolean
  restrictions: { code: string }[]
}
interface Search {
  properties: { offers: Entry[]; unavailable: Entry[] }[]
}
interface GridCellLite {
  date: string
  own: Record<string, unknown> | null
  book_from: string | null
  book_to: string | null
}
interface GridLite {
  rows: { level: "hotel" | "room"; cells: GridCellLite[] }[]
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

/** How the grid names a day ("Tuesday 20 Jul 2027") and a date ("20 Jul 2027"). */
async function dayNames(page: Page, iso: string) {
  return page.evaluate((d) => {
    const x = new Date(`${d}T12:00:00`)
    return {
      weekday: new Intl.DateTimeFormat("en-GB", { weekday: "long" }).format(x),
      medium: new Intl.DateTimeFormat("en-GB", { dateStyle: "medium" }).format(x),
    }
  }, iso)
}

/** Every offer of a 2-night stay around `night` on `channel`. */
async function entries(page: Page, night: string, channel: string): Promise<Entry[]> {
  const s = await pageApi<Search>(page, "kamra.tex.api.ui_crs.search", {
    check_in: addDays(night, -1),
    check_out: addDays(night, 1),
    rooms: [{ adults: 2, children: [] }],
    market: "DE",
    channel,
    properties: [HOTEL],
  })
  expect(s.ok, JSON.stringify(s.body).slice(0, 300)).toBeTruthy()
  const p = s.message.properties[0]
  return [...(p?.offers ?? []), ...(p?.unavailable ?? [])]
}

async function hotelGrid(page: Page, start: string, days: number) {
  const g = await pageApi<GridLite>(page, "kamra.tex.api.crs.ari_grid", { property: HOTEL, start, days, channel_scope: SCOPE })
  expect(g.ok, JSON.stringify(g.body).slice(0, 300)).toBeTruthy()
  return g.message.rows
}

/** A far-future night (with free neighbours for a 2-night search) that no booking window of
 * this scope touches and that has no hotel-level cell of its own: earlier runs, or other work on
 * the shared site, may have left cells elsewhere. */
async function freeNight(page: Page): Promise<string> {
  for (let attempt = 0; attempt < 6; attempt++) {
    const rows = await hotelGrid(page, isoDate(300 + Math.floor(Math.random() * 60)), 14)
    const clear = (i: number) => rows.every((r) => !r.cells[i].book_from && !r.cells[i].book_to && (r.level !== "hotel" || !r.cells[i].own))
    for (let i = 1; i < rows[0].cells.length - 1; i++) if (clear(i - 1) && clear(i) && clear(i + 1)) return rows[0].cells[i].date
  }
  throw new Error(`no night free of booking windows at ${HOTEL}`)
}

/** Clear the test's hotel-level cell (all fields blank deletes it; nothing set, nothing written). */
async function removeCell(page: Page, night: string) {
  return pageApi(page, "kamra.tex.api.crs.ari_bulk_update", {
    property: HOTEL,
    start: night,
    end: night,
    room_types: [],
    hotel_level: 1,
    channel_scope: SCOPE,
    restrictions: { book_from: "" },
  })
}

test("restrictions: a hotel-level booking window for the Booking Engine + Call Center", async ({ page }) => {
  test.setTimeout(180_000)
  const noErrors = trackErrors(page)
  await english(page)
  await login(page, "revenue@demo.tex")
  await page.goto(texPath("/tex/inventory"))
  const night = await freeNight(page)
  const opens = isoDate(420)
  const names = await dayNames(page, night)
  const opensName = (await dayNames(page, opens)).medium
  const hotelCell = page.getByRole("gridcell", { name: new RegExp(`^All room types, Booking window, ${esc(names.weekday)} ${esc(names.medium)}: `) })

  try {
    await test.step("the grid shows the hotel-level row for the Booking Engine + Call Center scope", async () => {
      await page.getByRole("banner").getByRole("combobox", { name: "Hotel" }).selectOption(HOTEL)
      await byLabel(page, "Start date").fill(night)
      await byLabel(page, "Sales channel").selectOption({ label: SCOPE })
      await expect(page.getByText(`Scope: all contracts · all markets · sold through ${SCOPE} · all rate plans`)).toBeVisible()
      await expect(page.getByRole("rowheader", { name: /^All room types/ }).first()).toContainText("hotel / market level")
      await expect(hotelCell).toHaveAccessibleName(/: No rule$/)
    })

    await test.step("bulk update: one hotel-level cell, bookable from a later sale date", async () => {
      await page.getByRole("button", { name: "Bulk update" }).click()
      const dialog = page.getByRole("dialog", { name: "Bulk update" })
      await expect(dialog).toBeVisible()
      await byLabel(dialog, "From").fill(night)
      await byLabel(dialog, "To (inclusive)").fill(night)
      await dialog.getByRole("checkbox", { name: "One hotel-level cell (every room type)" }).check()
      await expect(dialog.getByRole("checkbox", { name: "All room types" })).toBeDisabled()
      await byLabel(dialog, "Bookable from (sale date)").fill(opens)
      await dialog.getByRole("button", { name: "Review changes" }).click()
      await expect(dialog.getByText("Days: 1 × room types: 1 = cells to update: 1.")).toBeVisible()
      await expect(dialog.getByRole("listitem")).toHaveText([`Bookable from (sale date): ${opensName}`])
      await dialog.getByRole("button", { name: "Apply to 1 cell" }).click()
      await expect(dialog.getByText("Updated 1 day(s) for 1 room type(s).")).toBeVisible()
      await dialog.getByRole("button", { name: "Close" }).last().click()
      await expect(dialog).toBeHidden()
    })

    await test.step("the hotel row holds the window; every room row inherits it", async () => {
      await expect(hotelCell).toHaveAccessibleName(new RegExp(`: sold from ${esc(opensName)}, Set at this scope$`))
      const roomCells = page.getByRole("gridcell", { name: new RegExp(`, Booking window, ${esc(names.weekday)} ${esc(names.medium)}: sold from `) })
      expect(await roomCells.count()).toBeGreaterThan(1)
      // the hotel row has no availability or rate rows (restrictions only)
      await expect(page.getByRole("gridcell", { name: new RegExp(`^All room types, Available, `) })).toHaveCount(0)
    })

    await test.step("the call centre is refused by the booking window; another channel is not", async () => {
      const cc = await entries(page, night, "CALL_CENTER")
      expect(cc.length, "call-centre offers").toBeGreaterThan(0)
      expect(cc.every((e) => !e.bookable)).toBe(true)
      expect(cc.some((e) => e.restrictions.some((r) => r.code === "BOOKING_WINDOW"))).toBe(true)
      const b2b = await entries(page, night, "B2B")
      expect(b2b.some((e) => e.restrictions.some((r) => r.code === "BOOKING_WINDOW"))).toBe(false)
    })
    noErrors()
  } finally {
    const r = await removeCell(page, night)
    expect(r.ok, JSON.stringify(r.body).slice(0, 300)).toBeTruthy()
    // gone: no cell of its own left on the hotel row, and no window left on that night
    const rows = await hotelGrid(page, night, 1)
    expect(rows[0].cells[0].own).toBeNull()
    expect(rows.every((row) => !row.cells[0].book_from)).toBe(true)
  }
})
