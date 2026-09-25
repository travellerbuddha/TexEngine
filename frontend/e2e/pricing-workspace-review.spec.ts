// The Pricing Workspace after its S16 review (ARCHITECTURE_DECISIONS.md ADR-061 "S16 review
// follow-up"): the three grids scroll sideways together with 10 periods, Ctrl+S saves what is typed
// in an open cell, error drafts survive a section switch and the tab asks before closing with one,
// the focus stays in the matrix after Remove room / Delete period, the header's Base room select
// and ROOM-basis stepper, the Price test panel's Tab order and its modal form on a phone, visible
// read-only selections, Duplicate's unnamed copy with Rename…, dark-theme contrast, and settings in
// the undo history. Every test makes its own API draft of the owner's example.
import { expect, test, type Locator, type Page } from "@playwright/test"
import { login, trackErrors } from "./helpers"
import { priceMatrix } from "./flows/contracts"
import { archiveAll, DLX, N, newDraft, ownerDraft, publish, readVersion, STD, SUP, versionPath, watchContracts, Y, type Data, type NewContract } from "./flows/workspace"

test.use({ locale: "en-US", actionTimeout: 15_000, navigationTimeout: 30_000 })

const made: string[] = []

async function open(page: Page, data: Data, o: { hash?: string; basis?: "PERSON" | "ROOM" } = {}): Promise<NewContract> {
  await login(page, "revenue@demo.tex")
  const d = await newDraft(page, "E2E-PWR", data, o.basis ?? "PERSON")
  made.push(d.contract)
  await page.goto(versionPath(d, o.hash ?? "#pricing"))
  await expect(priceMatrix(page)).toBeVisible()
  return d
}

/** The editable (non-resolved) matrix cell of a room in a period. */
const cellOf = (page: Page, room: string, period: string) =>
  priceMatrix(page)
    .getByRole("gridcell", { name: new RegExp(`^${room} · ${period}: (?!resolved)`) })
    .first()
const ladder = (page: Page) => page.getByRole("grid", { name: "Occupancy and child pricing by period" })
const boards = (page: Page) => page.getByRole("grid", { name: "Board supplements by period" })
const context = (page: Page) => page.getByRole("region", { name: "Commercial context" })

async function expand(page: Page, section: "occupancy" | "boards") {
  const toggle = page.locator(`section#${section} h2 button[aria-expanded]`)
  if ((await toggle.getAttribute("aria-expanded")) === "false") await toggle.click()
  await expect(toggle).toHaveAttribute("aria-expanded", "true")
}

/** Ten periods of ten days from 1 April (P1–P10). */
const tenPeriods = () =>
  Array.from({ length: 10 }, (_, i) => {
    const day = (n: number) => new Date(Date.UTC(Y, 3, 1 + n)).toISOString().slice(0, 10)
    return { period_code: `P${i + 1}`, period_name: `D${i + 1}`, start_date: day(i * 10), end_date: day(i * 10 + 9) }
  })

/** WCAG contrast of two computed CSS colours "rgb(r, g, b)" (the dark theme's remapped hex values). */
function contrast(fg: string, bg: string): number {
  const lum = (c: string) => {
    const [r, g, b] = (c.match(/[\d.]+/g) ?? []).slice(0, 3).map((x) => {
      const v = Number(x) / 255
      return v <= 0.04045 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4
    })
    return 0.2126 * r + 0.7152 * g + 0.0722 * b
  }
  const [a, b] = [lum(fg), lum(bg)]
  return (Math.max(a, b) + 0.05) / (Math.min(a, b) + 0.05)
}

/** The x of a grid's column header that starts with `code`. */
async function headerX(grid: Locator, code: string): Promise<{ x: number; right: number }> {
  const h = grid.getByRole("columnheader").filter({ hasText: new RegExp(`^${code}(?!\\d)`) }).first()
  const box = await h.boundingBox()
  expect(box, `${code} header`).not.toBeNull()
  return { x: Math.round(box!.x), right: Math.round(box!.x + box!.width) }
}

test.describe.serial("pricing workspace, S16 review", () => {
  test.afterAll(async ({ browser }) => archiveAll(browser, made, "pricing workspace review e2e clean-up"))

  test("10 periods at 1440×900: the matrix, the ladder and the boards grid scroll sideways together, P8 lines up on screen", async ({ page }) => {
    const noErrors = trackErrors(page)
    await page.setViewportSize({ width: 1440, height: 900 })
    await open(page, {
      ...ownerDraft(),
      periods: tenPeriods(),
      period_rates: [
        { room_type: STD, period_code: "", op: "ABSOLUTE", value: "100" },
        { room_type: SUP, period_code: "", op: "MULTIPLY", value: "1.15", base_room_type: STD },
        { room_type: DLX, period_code: "", op: "MULTIPLY", value: "1.35", base_room_type: STD },
      ],
      boards: [
        { board: "BB", is_base: 1, op: "ADD", adult_amount: null, child_percent: "50", infant_free: 1, room_type: "", period_code: "" },
        { board: "HB", is_base: 0, op: "ADD", adult_amount: "20", child_percent: "50", infant_free: 1, room_type: "", period_code: "" },
      ],
    })
    await expand(page, "occupancy")
    await expand(page, "boards")
    await expect(ladder(page)).toBeVisible()
    await expect(boards(page)).toBeVisible()
    // P8 starts off screen in all three
    expect((await headerX(priceMatrix(page), "P8")).right).toBeGreaterThan(1440)
    // the keyboard walks the matrix to P8: the matrix scrolls, and the other two with it
    await cellOf(page, N.STD, "P1").click()
    for (let i = 0; i < 7; i++) await page.keyboard.press("ArrowRight")
    await expect(cellOf(page, N.STD, "P8")).toBeFocused()
    await expect
      .poll(async () => {
        const xs = await Promise.all([priceMatrix(page), ladder(page), boards(page)].map((g) => headerX(g, "P8")))
        return { aligned: Math.max(...xs.map((x) => x.x)) - Math.min(...xs.map((x) => x.x)) <= 1, onScreen: xs.every((x) => x.right <= 1440) }
      })
      .toEqual({ aligned: true, onScreen: true })
    // the boards grid's highlight of the matrix's active period is on screen too
    await expect(boards(page).locator("[data-matrix-period]")).toContainText("P8")
    expect((await boards(page).locator("[data-matrix-period]").boundingBox())!.x).toBeLessThan(1440)
    // scrolling the ladder back scrolls the matrix and the boards back
    await ladder(page).locator("xpath=..").evaluate((el) => (el.scrollLeft = 0))
    await expect.poll(() => priceMatrix(page).locator("xpath=..").evaluate((el) => el.scrollLeft)).toBe(0)
    await expect.poll(() => boards(page).locator("xpath=..").evaluate((el) => el.scrollLeft)).toBe(0)
    noErrors()
  })

  test("Ctrl+S in an open cell editor saves the typed price, and the focus stays on the cell", async ({ page }) => {
    const noErrors = trackErrors(page)
    const calls = watchContracts(page)
    const draft = ownerDraft()
    draft.period_rates = draft.period_rates.filter((r) => !(r.room_type === STD && r.period_code === "P1"))
    const d = await open(page, draft)
    await expect(page.getByText("Unsaved changes", { exact: true })).toHaveCount(0)
    await cellOf(page, N.STD, "P1").click()
    await page.keyboard.type("=120")
    await expect(priceMatrix(page).getByRole("textbox", { name: `Price: ${N.STD} · P1` })).toBeVisible()
    await page.keyboard.press("Control+s")
    await expect(page.getByText("Draft saved")).toBeVisible()
    expect(calls.count("save_version")).toBe(1)
    const body = calls.bodies("save_version")[0] as { data: { period_rates: Record<string, unknown>[] } }
    expect(body.data.period_rates.find((r) => r.room_type === STD && r.period_code === "P1")).toMatchObject({ op: "ABSOLUTE", value: "120" })
    const saved = await readVersion(page, d.version)
    expect(saved.period_rates.find((r) => r.room_type === STD && r.period_code === "P1")?.value).toBe("120")
    await expect(priceMatrix(page).getByRole("gridcell", { name: `${N.STD} · P1: entered price, 120.00`, exact: true })).toBeFocused()
    await expect(page.getByText("Unsaved changes", { exact: true })).toHaveCount(0)
    noErrors()
  })

  test("an error draft survives a section switch, and the tab asks before it closes with one", async ({ page }) => {
    const noErrors = trackErrors(page)
    await open(page, ownerDraft())
    await cellOf(page, N.SUP, "P3").click()
    await page.keyboard.type("abc")
    // leaving the cell keeps a refused entry as an error draft (§3.4.1; Tab would keep the editor open)
    await cellOf(page, N.STD, "P1").click()
    await expect(cellOf(page, N.SUP, "P3")).toContainText("abc")
    await page.getByRole("tab", { name: /^Commercial rules/ }).click()
    await expect(priceMatrix(page)).toHaveCount(0)
    await page.getByRole("tab", { name: /^Pricing/ }).click()
    await expect(cellOf(page, N.SUP, "P3")).toContainText("abc")
    // not in the version (nothing to save), yet the page asks before it goes
    await expect(page.getByText("Unsaved changes", { exact: true })).toHaveCount(0)
    let asked = ""
    page.once("dialog", (dlg) => {
      asked = dlg.type()
      void dlg.dismiss()
    })
    noErrors()
    await page.close({ runBeforeUnload: true })
    await expect.poll(() => asked).toBe("beforeunload")
  })

  test("Remove room and Delete period by keyboard leave the focus on a matrix cell; Ctrl+Z brings them back", async ({ page }) => {
    const noErrors = trackErrors(page)
    await open(page, ownerDraft())
    const focusedCell = () => page.evaluate(() => (document.activeElement?.getAttribute("role") === "gridcell" ? document.activeElement.getAttribute("aria-label") : `not a cell: ${document.activeElement?.tagName}`))
    await cellOf(page, N.DLX, "P2").click()
    await page.getByRole("button", { name: `Room actions: ${N.DLX}` }).focus()
    await page.keyboard.press("Enter")
    await page.getByRole("menuitem", { name: "Remove room" }).press("Enter")
    const rm = page.getByRole("dialog", { name: `Remove ${N.DLX}?` })
    await expect(rm.getByRole("button", { name: "Cancel" })).toBeFocused()
    await page.keyboard.press("Tab")
    await expect(rm.getByRole("button", { name: "Remove room" })).toBeFocused()
    await page.keyboard.press("Enter")
    await expect(page.getByRole("button", { name: `Room actions: ${N.DLX}` })).toHaveCount(0)
    await expect.poll(focusedCell).toMatch(new RegExp(`^${N.SUP} · `))
    await page.keyboard.press("Control+z")
    await expect(page.getByRole("button", { name: `Room actions: ${N.DLX}` })).toBeVisible()
    // Delete period P3: the focus goes to the same row's next period, P4
    await cellOf(page, N.STD, "P3").click()
    await page.getByRole("button", { name: "Period actions: P3" }).focus()
    await page.keyboard.press("Enter")
    await page.getByRole("menuitem", { name: "Delete period" }).press("Enter")
    const del = page.getByRole("dialog", { name: "Delete P3?" })
    await expect(del.getByRole("button", { name: "Cancel" })).toBeFocused()
    await page.keyboard.press("Tab")
    await page.keyboard.press("Enter")
    await expect(page.getByRole("button", { name: "Period actions: P3" })).toHaveCount(0)
    await expect.poll(focusedCell).toMatch(new RegExp(`^${N.STD} · P4`))
    await page.keyboard.press("Control+z")
    await expect(page.getByRole("button", { name: "Period actions: P3" })).toBeVisible()
    noErrors()
  })

  test("the header's Base room select sets the base room; the ROOM basis stepper writes the base room's included adults", async ({ page }) => {
    const noErrors = trackErrors(page)
    await open(page, ownerDraft())
    await context(page).getByRole("button", { name: N.STD }).click()
    const pop = page.getByRole("dialog", { name: "Base room" })
    await expect(pop.getByRole("combobox", { name: "Base room" })).toBeFocused()
    await pop.getByRole("combobox", { name: "Base room" }).selectOption({ label: N.SUP })
    await expect(pop.getByRole("checkbox", { name: `Re-point formulas that use ${N.STD} to ${N.SUP}` })).toBeChecked()
    await pop.getByRole("button", { name: "Set as base" }).click()
    await expect(context(page).getByRole("button", { name: N.SUP })).toBeVisible()
    await expect(page.getByText("Unsaved changes", { exact: true })).toBeVisible()
    await expect(priceMatrix(page).getByRole("rowheader").filter({ hasText: N.SUP }).first()).toContainText("BASE")

    // ROOM basis: 2 adults included (the room type's) → 3
    const room = await newDraft(page, "E2E-PWR", ownerDraft(), "ROOM")
    made.push(room.contract)
    const calls = watchContracts(page)
    await page.goto(versionPath(room, "#pricing"))
    await expect(priceMatrix(page)).toBeVisible()
    const chip = context(page).getByRole("button", { name: /adults? included/ })
    await expect(chip).toHaveText(/2 adults included/)
    await chip.click()
    const step = page.getByRole("dialog", { name: `Adults included in the price of ${N.STD}` })
    await step.getByRole("button", { name: "One adult more" }).click()
    await expect(step.getByRole("textbox", { name: "Adults included in room price" })).toHaveValue("3")
    await step.getByRole("button", { name: "Apply" }).click()
    await expect(chip).toHaveText(/3 adults included/)
    const sent = calls.bodies("price_matrix").at(-1) as { data?: { rooms?: Record<string, unknown>[] } }
    expect(sent.data?.rooms?.find((r) => r.room_type === STD)?.included_adults).toBe(3)
    noErrors()
  })

  test("the Price test panel sits after its opener in the Tab order; on a phone it is a modal drawer", async ({ page }) => {
    const noErrors = trackErrors(page)
    await open(page, ownerDraft())
    const opener = context(page).getByRole("button", { name: "Price test", exact: true })
    await opener.click()
    const dr = page.getByRole("dialog", { name: "Price test" })
    await expect(dr).toBeVisible()
    expect(await dr.getAttribute("aria-modal")).toBeNull()
    await dr.getByRole("button", { name: "Close" }).focus()
    await page.keyboard.press("Shift+Tab")
    await expect(opener).toBeFocused()
    await expect(dr).toBeVisible()
    // Tab from the panel's last control goes on after the opener, not to the page's start or end
    await dr.evaluate((el) => {
      const items = Array.from(el.querySelectorAll<HTMLElement>('a[href],button:not([disabled]),input:not([disabled]),select:not([disabled]),textarea:not([disabled]),[tabindex]:not([tabindex="-1"])')).filter((x) => x.tabIndex >= 0 && x.getClientRects().length > 0)
      items[items.length - 1].focus()
    })
    await page.keyboard.press("Tab")
    const where = await page.evaluate(() => {
      const a = document.activeElement as HTMLElement
      const panel = document.querySelector("[data-side-panel]")
      const price = Array.from(document.querySelectorAll("button")).find((b) => b.textContent?.trim() === "Price test")
      return { inPanel: Boolean(panel?.contains(a)), body: a === document.body, after: Boolean(price && price.compareDocumentPosition(a) & Node.DOCUMENT_POSITION_FOLLOWING) }
    })
    expect(where).toEqual({ inPanel: false, body: false, after: true })
    noErrors()
    // a phone: the panel covers the page, so it is modal there
    await page.setViewportSize({ width: 375, height: 800 })
    await expect(dr).toHaveAttribute("aria-modal", "true")
  })

  test("a range over read-only cells is selected and shown (outline, aria-selected); the grids say they are multiselectable", async ({ page }) => {
    const noErrors = trackErrors(page)
    await login(page, "revenue@demo.tex")
    const pub = await newDraft(page, "E2E-PWR", ownerDraft())
    made.push(pub.contract)
    await publish(page, pub.version)
    await page.goto(versionPath(pub, "#pricing"))
    await expect(priceMatrix(page)).toHaveAttribute("aria-readonly", "true")
    await expect(priceMatrix(page)).toHaveAttribute("aria-multiselectable", "true")
    const first = priceMatrix(page).getByRole("gridcell", { name: new RegExp(`^${N.STD} · P1: `) }).first()
    await first.click()
    await page.keyboard.press("Shift+ArrowRight")
    await page.keyboard.press("Shift+ArrowRight")
    const p3 = priceMatrix(page).getByRole("gridcell", { name: new RegExp(`^${N.STD} · P3: `) }).first()
    await expect(p3).toHaveAttribute("aria-selected", "true")
    await expect(first).toHaveAttribute("aria-selected", "true")
    const style = await first.evaluate((el) => {
      const s = getComputedStyle(el)
      return { style: s.outlineStyle, width: s.outlineWidth }
    })
    expect(style).toEqual({ style: "solid", width: "2px" })
    noErrors()
  })

  test("Duplicate makes an unnamed copy and opens Rename… on it; a weekday-limited period has a dotted top border", async ({ page }) => {
    const noErrors = trackErrors(page)
    const draft = ownerDraft()
    draft.periods = draft.periods.map((p) => (p.period_code === "P2" ? { ...p, weekdays: "Fri,Sat" } : p))
    await open(page, draft)
    await page.getByRole("button", { name: "Period actions: P4" }).click()
    await page.getByRole("menuitem", { name: "Duplicate" }).click()
    const rename = page.getByRole("dialog", { name: "Rename P5" })
    await expect(rename).toBeVisible()
    // the copy has no name: the focus is in its name
    await expect(rename.getByRole("textbox", { name: "Name", exact: true })).toBeFocused()
    await expect(rename.getByRole("textbox", { name: "Name", exact: true })).toHaveValue("")
    const p5 = priceMatrix(page).getByRole("columnheader").filter({ hasText: /^P5/ }).first()
    await expect(p5).not.toContainText("Jul")
    const p2 = priceMatrix(page).getByRole("columnheader").filter({ hasText: /^P2/ }).first()
    expect(await p2.evaluate((el) => getComputedStyle(el).borderTopStyle)).toBe("dotted")
    expect(await p2.evaluate((el) => getComputedStyle(el).borderRightStyle)).toBe("solid")
    noErrors()
  })

  test("dark theme: override, fixed and formula cells stay readable", async ({ page }) => {
    const noErrors = trackErrors(page)
    const draft = ownerDraft()
    draft.period_rates = [
      ...draft.period_rates,
      { room_type: SUP, period_code: "P4", op: "MULTIPLY", value: "1.2", base_room_type: STD },
      { room_type: DLX, period_code: "P3", op: "ABSOLUTE", value: "245" },
    ]
    await open(page, draft)
    await page.evaluate(() => document.documentElement.classList.add("dark"))
    const pair = (l: Locator, inner?: string) =>
      l.evaluate((el, sel) => {
        const text = sel ? (el.querySelector(sel) as HTMLElement) : el
        return { fg: getComputedStyle(text).color, bg: getComputedStyle(el).backgroundColor }
      }, inner)
    const override = await pair(cellOf(page, N.SUP, "P4"))
    const fixed = await pair(cellOf(page, N.DLX, "P3"))
    const formula = await pair(cellOf(page, N.SUP, "All periods"), "span > span")
    for (const [what, c] of Object.entries({ override, fixed })) expect(contrast(c.fg, c.bg), `${what} ${JSON.stringify(c)}`).toBeGreaterThanOrEqual(4.5)
    // the formula cell has no background of its own: the grid's box (white, remapped)
    const box = await priceMatrix(page).locator("xpath=..").evaluate((el) => getComputedStyle(el).backgroundColor)
    expect(contrast(formula.fg, box), JSON.stringify({ formula, box })).toBeGreaterThanOrEqual(4.5)
    noErrors()
  })

  test("settings are in the undo history: child ordering then Ctrl+Z in the ladder puts it back first", async ({ page }) => {
    const noErrors = trackErrors(page)
    await open(page, ownerDraft())
    await expand(page, "occupancy")
    const order = page.locator("section#occupancy").getByRole("combobox", { name: "Child 1:" })
    const before = await order.inputValue()
    const other = before === "YOUNGEST_FIRST" ? "OLDEST_FIRST" : "YOUNGEST_FIRST"
    await order.selectOption(other)
    await expect(page.getByText("Unsaved changes", { exact: true })).toBeVisible()
    await ladder(page).getByRole("gridcell").first().click()
    await page.keyboard.press("Control+z")
    await expect(order).toHaveValue(before)
    await expect(page.getByText("Undone: Which child counts as child 1").first()).toBeAttached()
    await expect(page.getByText("Unsaved changes", { exact: true })).toHaveCount(0)
    noErrors()
  })
})
