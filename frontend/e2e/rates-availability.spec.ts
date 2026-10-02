// Rates & availability, the daily work view (UX revision 2026-10): select rooms × nights in the
// grid and change their price or their sale without a dialog.
// - a percentage on a selection: the server previews every room's price before and after; one save
//   writes the contract's draft; nothing sells at it until the draft is published;
// - prices typed into cells and a block pasted from a spreadsheet, with Undo; unsaved prices are
//   protected when the user leaves;
// - closing and opening sale for a selection, its scope stated, applied at once, with Undo.
// Each test works on a contract of its own (made through the API, published, archived after), at
// Aurora Beach Resort in May of next year, so it changes nothing the other specs read.
//   TEX_E2E_BASE=http://localhost:5173 TEX_E2E_PASSWORD=… npx playwright test -c e2e rates-availability
import { expect, test, type Page } from "@playwright/test"
import { login, pageApiOk, texPath, trackErrors } from "./helpers"
import { Budget } from "./flows/budget"
import { archiveAll, DLX, HOTEL, N, newDraft, ownerDraft, publish, SUP, STD, Y, type NewContract } from "./flows/workspace"

test.use({ locale: "en-US" })

const made: string[] = []
test.afterAll(async ({ browser }) => archiveAll(browser, made, "E2E rates & availability clean-up"))

async function english(page: Page) {
  await page.addInitScript(() => {
    try {
      localStorage.setItem("tex-lang", "en")
      localStorage.removeItem("tex-inv-grid:Aurora Beach Resort")
    } catch {
      /* storage blocked */
    }
  })
}

/** A published contract with the owner's example terms (May: Standard 80, Family Suite ×1.15 = 92,
 * Garden Villa ×1.35 = 108), shown in the grid from 10 May of next year. */
async function openGrid(page: Page): Promise<NewContract & { code: string }> {
  await english(page)
  await login(page, "revenue@demo.tex")
  await page.goto(texPath("/tex"))
  const d = await newDraft(page, "UXG", ownerDraft())
  made.push(d.contract)
  await publish(page, d.version)
  const code = (await pageApiOk<{ contract: { contract_code: string } }>(page, "kamra.tex.api.contracts.get_contract", { name: d.contract })).contract.contract_code
  await page.goto(texPath(`/tex/inventory?start=${Y}-05-10`))
  const hotel = page.getByRole("banner").getByRole("combobox", { name: "Hotel" })
  if (await hotel.count()) await hotel.selectOption(HOTEL)
  await page.getByLabel("Price source (contract)").selectOption({ label: `${code} · DE` })
  await expect(cell(page, N.STD, "Rate", 1)).toHaveAccessibleName(/: 80\.00 EUR/)
  return { ...d, code }
}

/** A cell by room name, row (Rate, Available, Stop sell…) and the day's index in view. */
function cell(page: Page, room: string, row: string, day: number) {
  return page.getByRole("gridcell", { name: new RegExp(`^${room}, ${row}, `) }).nth(day)
}

const bar = (page: Page) => page.getByRole("region", { name: "Selection and changes" })

async function gridRow(page: Page, contract: string, roomType: string) {
  const g = await pageApiOk<{ rows: { room_type: string | null; cells: { date: string; rate?: string; draft_rate?: string; own: { stop_sell: string | null } | null; stop_sell: boolean }[] }[] }>(
    page,
    "kamra.tex.api.crs.ari_grid",
    { property: HOTEL, start: `${Y}-05-10`, days: 14, contract },
  )
  return g.rows.find((r) => r.room_type === roomType)!.cells
}

test("+10 % for two rooms on five nights: previewed by the server, saved to the draft in one step, not on sale until published", async ({ page }, testInfo) => {
  test.setTimeout(120_000)
  const noErrors = trackErrors(page)
  const budget = await Budget.attach(page)
  const d = await openGrid(page)

  budget.start()
  // drag from Family Suite's price on 11 May to Garden Villa's price on 15 May
  await cell(page, N.SUP, "Rate", 1).hover()
  await page.mouse.down()
  await cell(page, N.DLX, "Rate", 5).hover()
  await page.mouse.up()
  await expect(bar(page)).toContainText("10 cells selected")
  await expect(bar(page)).toContainText(`2 rooms: ${N.SUP}, ${N.DLX}`)
  await budget.fill(bar(page).getByRole("textbox", { name: /New price or change for 10 cells/ }), "+10%")
  await expect(page.locator("#inv-entry-help")).toHaveText("Raise by 10 % · 10 price cells")
  await bar(page).getByRole("button", { name: "Enter for selection" }).click()
  await expect(cell(page, N.SUP, "Rate", 1)).toHaveAccessibleName(/unsaved change \+10%/)
  const answer = page.waitForResponse((r) => r.url().includes("ari_rate_changes"))
  await bar(page).getByRole("button", { name: "Preview new prices" }).click()
  expect((await answer).ok()).toBeTruthy()
  // the server's numbers, room by room: 92.00 → 101.20 and 108.00 → 118.80
  const table = bar(page).getByRole("table", { name: "New prices by room and nights" })
  await expect(table.getByRole("row").filter({ hasText: N.SUP })).toContainText(/92\.00 EUR\s*101\.20 EUR/)
  await expect(table.getByRole("row").filter({ hasText: N.DLX })).toContainText(/108\.00 EUR\s*118\.80 EUR/)
  await expect(bar(page)).toContainText("Guests see the new prices only after the draft is published.")
  await bar(page).getByRole("button", { name: "Save to draft" }).click()
  await expect(page.getByText(/10 prices saved to draft V2/)).toBeVisible()
  await budget.stop()
  // a drag, the entry field, "Enter for selection", Preview, Save; no dialog
  await budget.expectWithin(testInfo, { clicks: 5, sectionSwitches: 0, modals: 0 })

  // the draft holds the new prices; the version on sale still sells the old ones
  const sup = await gridRow(page, d.contract, SUP)
  expect(sup.slice(1, 6).map((c) => [c.rate, c.draft_rate])).toEqual(Array(5).fill(["92.00", "101.20"]))
  expect([sup[0].draft_rate, sup[6].draft_rate]).toEqual(["92.00", "92.00"])
  const dlx = await gridRow(page, d.contract, DLX)
  expect(dlx.slice(1, 6).map((c) => c.draft_rate)).toEqual(Array(5).fill("118.80"))
  expect((await gridRow(page, d.contract, STD)).slice(1, 6).map((c) => c.draft_rate)).toEqual(Array(5).fill("80.00"))
  await expect(page.getByText(/10 prices in view are changed in draft V2 and not on sale yet; guests still book V1\./)).toBeVisible()
  noErrors()
})

test("prices typed into cells and pasted from a spreadsheet, undone with Ctrl+Z; leaving with unsaved prices asks first", async ({ page }) => {
  test.setTimeout(120_000)
  const noErrors = trackErrors(page)
  await openGrid(page)

  // type straight into a price cell: Enter moves to the next night
  await cell(page, N.STD, "Rate", 2).click()
  await page.keyboard.type("85")
  await page.keyboard.press("Enter")
  await page.keyboard.type("+%5")
  await page.keyboard.press("Enter")
  await expect(cell(page, N.STD, "Rate", 2)).toHaveAccessibleName(/unsaved change 85/)
  await expect(cell(page, N.STD, "Rate", 3)).toHaveAccessibleName(/unsaved change \+5%/)
  // a share is never guessed as a raise or a cut
  await page.keyboard.type("10%")
  await page.keyboard.press("Enter")
  await expect(page.getByRole("alert")).toContainText("raise or lower? type +10% or -10%")
  await page.keyboard.press("Escape")

  // a 2 × 2 block from a spreadsheet, pasted on Family Suite's price on 18 May: rooms down, nights across
  await cell(page, N.SUP, "Rate", 8).click()
  await page.evaluate(() => {
    const dt = new DataTransfer()
    dt.setData("text/plain", "100\t101\n110\t111\n")
    document.activeElement?.dispatchEvent(new ClipboardEvent("paste", { clipboardData: dt, bubbles: true }))
  })
  await expect(page.getByText("4 prices pasted — preview, then save")).toBeVisible()
  await expect(cell(page, N.SUP, "Rate", 9)).toHaveAccessibleName(/unsaved change 101/)
  await expect(cell(page, N.DLX, "Rate", 9)).toHaveAccessibleName(/unsaved change 111/)
  await expect(bar(page)).toContainText("6 price changes not saved yet")
  // Ctrl+Z takes the paste back, as one step
  await page.keyboard.press("Control+z")
  await expect(bar(page)).toContainText("2 price changes not saved yet")
  await expect(cell(page, N.DLX, "Rate", 9)).not.toHaveAccessibleName(/unsaved/)

  // leaving the page with unsaved prices asks; staying keeps them
  page.once("dialog", (dlg) => {
    expect(dlg.message()).toContain("You have changes that are not saved")
    void dlg.dismiss()
  })
  await page.getByRole("navigation", { name: "Main navigation" }).getByRole("link", { name: "Reservations", exact: true }).click()
  await expect(page).toHaveURL(/\/tex\/inventory/)
  await expect(bar(page)).toContainText("2 price changes not saved yet")
  await bar(page).getByRole("button", { name: "Discard all" }).click()
  await expect(bar(page)).not.toContainText("not saved yet")
  await expect(cell(page, N.STD, "Rate", 2)).not.toHaveAccessibleName(/unsaved/)
  noErrors()
})

test("close sale for a selection with its scope stated, applied at once, and undone", async ({ page }) => {
  test.setTimeout(120_000)
  const noErrors = trackErrors(page)
  const d = await openGrid(page)

  // Standard on 12–14 May: click, then Shift+click
  await cell(page, N.STD, "Rate", 2).click()
  await cell(page, N.STD, "Rate", 4).click({ modifiers: ["Shift"] })
  await expect(bar(page)).toContainText("3 cells selected")
  await bar(page).getByRole("button", { name: "Close sale" }).click()
  const confirm = bar(page).getByRole("group", { name: "Close sale" })
  await expect(confirm).toContainText("Close sale for 3 cells?")
  // where it applies is a choice, shown with the grid's own scope chosen
  await expect(confirm.getByRole("radio", { name: `Only contract ${d.code}` })).toBeChecked()
  await expect(confirm.getByRole("radio", { name: "Every contract of the hotel" })).not.toBeChecked()
  await expect(confirm).toContainText("Applies at once to new searches and bookings.")
  await confirm.getByRole("button", { name: "Close sale" }).click()
  await expect(bar(page)).toContainText("Sale closed for 3 cells")
  await expect(cell(page, N.STD, "Stop sell", 3)).toHaveAccessibleName(/: Stop sell, Set at this scope$/)
  let std = await gridRow(page, d.contract, STD)
  expect(std.slice(1, 6).map((c) => c.own?.stop_sell ?? null)).toEqual([null, "STOP", "STOP", "STOP", null])

  // Undo puts back what each cell held before (nothing of its own here)
  await bar(page).getByRole("button", { name: "Undo" }).click()
  await expect(page.getByText("Undone: the previous values are back")).toBeVisible()
  std = await gridRow(page, d.contract, STD)
  expect(std.slice(1, 6).every((c) => !c.own && !c.stop_sell)).toBe(true)
  noErrors()
})
