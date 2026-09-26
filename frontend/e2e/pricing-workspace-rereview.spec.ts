// The Pricing Workspace after its S16 re-review (ARCHITECTURE_DECISIONS.md ADR-061 "S16 re-review
// follow-up"): the Price test's explanation after a second result, a child position rule and the
// "also when children travel" single use from the ladder popover, Add room / Add board menus that
// arrows do not trigger, the matrix after a failed price_matrix call, Ctrl+S and beforeunload for
// the child-age fields, Alt+Enter in the boards grid keeping what was typed, one tab stop per grid
// with the headers on the arrow keys, Shift+click on a column header, the Price test beside the
// matrix at 1440×900, a word on Ctrl+V in the ladder, board names in row headers, and German weekday
// names and "+ Periode". Every test makes its own API draft of the owner's example.
import { expect, test, type Locator, type Page } from "@playwright/test"
import { login, trackErrors } from "./helpers"
import { priceMatrix } from "./flows/contracts"
import { archiveAll, DLX, N, newDraft, ownerDraft, periods, SUP, versionPath, watchContracts, Y, type Data, type NewContract } from "./flows/workspace"

test.use({ locale: "en-US", actionTimeout: 15_000, navigationTimeout: 30_000 })

const made: string[] = []

async function open(page: Page, data: Data, o: { hash?: string; lang?: string } = {}): Promise<NewContract> {
  await login(page, "revenue@demo.tex")
  const d = await newDraft(page, "E2E-PWRR", data)
  made.push(d.contract)
  if (o.lang) await page.addInitScript((l) => window.localStorage.setItem("tex-lang", l), o.lang)
  await page.goto(versionPath(d, o.hash ?? "#pricing"))
  await expect(page.getByRole("grid").first()).toBeVisible()
  return d
}

const esc = (s: string) => s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")
/** The editable (non-resolved) matrix cell of a room in a period. */
const cellOf = (page: Page, room: string, period: string) =>
  priceMatrix(page)
    .getByRole("gridcell", { name: new RegExp(`^${esc(room)} · ${period}: (?!resolved)`) })
    .first()
const ladder = (page: Page) => page.getByRole("grid", { name: "Occupancy and child pricing by period" })
const lcell = (page: Page, slot: string, period: string) => ladder(page).getByRole("gridcell", { name: new RegExp(`^${esc(slot)} · ${period}: `) })
const boards = (page: Page) => page.getByRole("grid", { name: "Board supplements by period" })
const bcell = (page: Page, row: string, period: string) => boards(page).getByRole("gridcell", { name: new RegExp(`^${esc(row)} · ${period}: `) })
const context = (page: Page) => page.getByRole("region", { name: "Commercial context" })
const inGrid = (grid: Locator) => grid.evaluate((g) => g.contains(document.activeElement))

async function expand(page: Page, section: "occupancy" | "boards") {
  const toggle = page.locator(`section#${section} h2 button[aria-expanded]`)
  if ((await toggle.getAttribute("aria-expanded")) === "false") await toggle.click()
  await expect(toggle).toHaveAttribute("aria-expanded", "true")
}

const withBoards = (): Data => ({
  ...ownerDraft(),
  boards: [
    { board: "BB", is_base: 1, op: "ADD", adult_amount: null, child_percent: "50", infant_free: 1, room_type: "", period_code: "" },
    { board: "HB", is_base: 0, op: "ADD", adult_amount: "20", child_percent: "50", infant_free: 1, room_type: "", period_code: "" },
    { board: "HB", is_base: 0, op: "ADD", adult_amount: "30", child_percent: "50", infant_free: 1, room_type: DLX, period_code: "" },
  ],
})

test.describe("pricing workspace, S16 re-review", () => {
  test.afterAll(async ({ browser }) => archiveAll(browser, made, "pricing workspace re-review e2e clean-up"))

  test("the Price test keeps its full explanation after a second result with other dates; the result is not one live region", async ({ page }) => {
    const noErrors = trackErrors(page)
    await open(page, ownerDraft())
    await context(page).getByRole("button", { name: "Price test", exact: true }).click()
    const dr = page.getByRole("dialog", { name: "Price test" })
    await dr.getByLabel(/^Check-in/).fill(`${Y}-04-01`)
    await dr.getByLabel(/^Check-out/).fill(`${Y}-04-04`)
    await dr.getByRole("button", { name: /^Calculate/ }).click()
    const why = dr.getByRole("list", { name: "Explanation" })
    await expect(why.getByText("Rule applied:").first()).toBeVisible()
    // one night picked in both views
    await dr.getByLabel("Nights shown").selectOption({ index: 2 })
    await dr.getByLabel("Night", { exact: true }).selectOption({ index: 2 })
    await expect(dr.getByRole("table", { name: /^Night 2 · P1/ })).toBeVisible()
    // other dates: the picked night is not among the new result's nights
    await dr.getByLabel(/^Check-in/).fill(`${Y}-05-10`)
    await dr.getByLabel(/^Check-out/).fill(`${Y}-05-13`)
    await dr.getByRole("button", { name: /^Calculate/ }).click()
    await expect(dr.getByRole("table", { name: /Nights 1–3 · P2/ })).toBeVisible()
    await expect(dr.getByLabel("Nights shown")).toHaveValue("")
    await expect(dr.getByLabel("Night", { exact: true })).toHaveValue("")
    // Room and Occupancy steps with the rule that won are there again
    for (const stage of ["Room", "Occupancy"]) await expect(why.getByRole("listitem").filter({ hasText: new RegExp(`^${stage}`) }).first()).toBeVisible()
    expect(await why.getByText("Rule applied:").count()).toBeGreaterThan(3)
    // the result is not a live region; a short summary is
    expect(await dr.locator("[aria-live]").filter({ has: dr.getByRole("list", { name: "Explanation" }) }).count()).toBe(0)
    await expect(dr.getByRole("status").filter({ hasText: /^Price test total: / })).toHaveCount(1)
    noErrors()
  })

  test("the ladder popover adds a Child 2 position row and switches single use to 'also when children travel'", async ({ page }) => {
    const noErrors = trackErrors(page)
    const calls = watchContracts(page)
    await open(page, ownerDraft())
    await expand(page, "occupancy")
    await lcell(page, "Child 3–6.99", "All periods").click()
    await page.keyboard.press("Alt+Enter")
    const pop = page.getByRole("dialog", { name: "Edit rule: Child 3–6.99 · All periods" })
    await pop.getByLabel("Child position").selectOption({ label: "Child 2 only" })
    await pop.getByRole("textbox").first().fill("0.5")
    await expect(pop).toContainText("Child 2 · Child 3–6.99 · All periods")
    await pop.getByRole("button", { name: "Apply" }).click()
    await expect(pop).toBeHidden()
    await expect(lcell(page, "Child 2 · Child 3–6.99", "All periods")).toHaveAttribute("aria-label", /×0\.50/)
    await expect(lcell(page, "Child 3–6.99", "All periods")).toHaveAttribute("aria-label", /×0\.25/)
    // single use: the whole 1+0 room switched to Adult 1 in 1 adult + any children
    await lcell(page, "1 Adult (single use)", "All periods").click()
    await page.keyboard.press("Alt+Enter")
    const single = page.getByRole("dialog", { name: "Edit rule: 1 Adult (single use) · All periods" })
    await single.getByRole("checkbox", { name: "Also when children travel" }).check()
    await single.getByRole("textbox").first().fill("1.5")
    await single.getByRole("button", { name: "Apply" }).click()
    await expect(lcell(page, "1 Adult (also with children)", "All periods")).toHaveAttribute("aria-label", /×1\.50/)
    await expect.poll(() => {
      const body = calls.bodies("price_matrix").at(-1) as { data?: { occupancy_rules?: Record<string, unknown>[] } } | undefined
      return (body?.data?.occupancy_rules ?? []).filter((r) => r.position === 2 || r.combination === "1+*").map((r) => `${r.target}:${r.position}:${r.age_band ?? ""}:${r.combination ?? ""}:${r.value}`)
    }).toEqual(["CHILD:2:CHA::0.5", "ADULT:1::1+*:1.5"])
    noErrors()
  })

  test("Add room and Add board are menus: arrow keys only move between rooms, Enter adds one", async ({ page }) => {
    const noErrors = trackErrors(page)
    const draft = ownerDraft()
    draft.rooms = draft.rooms.filter((r) => r.room_type !== DLX)
    draft.period_rates = draft.period_rates.filter((r) => r.room_type !== DLX)
    await open(page, draft)
    const add = page.getByRole("button", { name: "Add room", exact: true })
    await add.focus()
    await page.keyboard.press("ArrowDown")
    const menu = page.getByRole("menu", { name: "Add room" })
    await expect(menu).toBeVisible()
    for (let i = 0; i < 3; i++) await page.keyboard.press("ArrowDown")
    await page.keyboard.press("Escape")
    await expect(add).toBeFocused()
    await expect(page.getByRole("button", { name: `Room actions: ${N.DLX}` })).toHaveCount(0)
    await expect(page.getByText("Unsaved changes", { exact: true })).toHaveCount(0)
    await page.keyboard.press("Enter")
    await expect(page.getByRole("menuitem", { name: N.DLX })).toBeFocused()
    await page.keyboard.press("Enter")
    await expect(page.getByRole("button", { name: `Room actions: ${N.DLX}` })).toHaveCount(1)
    await expect(page.getByRole("button", { name: "Add room", exact: true })).toBeDisabled()
    noErrors()
  })

  test("after a failed price_matrix call the matrix says the prices were not updated, not 'Updating…' for ever; stale values are not dimmed", async ({ page }) => {
    await open(page, ownerDraft())
    await expect(cellOf(page, N.STD, "P1")).toHaveAttribute("aria-label", /entered price, 70\.00/)
    // the saved draft's prices are there first (Family Suite P1: 70 × 1.15)
    await expect(priceMatrix(page)).toContainText("80.50")
    await expect(page.locator("[data-resolved-status]")).toHaveAttribute("data-resolved-status", "current")
    await page.route(/contracts\.price_matrix/, (route) => route.fulfill({ status: 500, contentType: "application/json", body: JSON.stringify({ exc_type: "Exception", _server_messages: "[]" }) }))
    const failed = page.waitForResponse((r) => r.url().includes("contracts.price_matrix") && r.status() === 500)
    await cellOf(page, N.STD, "P1").click()
    await page.keyboard.type("75")
    await page.keyboard.press("Enter")
    await failed
    const status = page.locator("[data-resolved-status]")
    await expect(status).toHaveAttribute("data-resolved-status", "failed")
    await expect(status).toHaveText("Prices not updated")
    await page.waitForTimeout(1000)
    await expect(priceMatrix(page).locator("xpath=ancestor::section[1]").getByText("Updating…")).toHaveCount(0)
    const resolved = priceMatrix(page).getByRole("gridcell", { name: new RegExp(`^${esc(N.SUP)} · P1: .*not updated: the last calculation failed`) }).first()
    await expect(resolved).toBeVisible()
    expect(await resolved.evaluate((el) => ({ opacity: getComputedStyle(el).opacity, style: getComputedStyle(el).fontStyle }))).toEqual({ opacity: "1", style: "italic" })
  })

  test("Ctrl+S in a child-age field saves what is typed; a typed field keeps the tab from closing silently", async ({ page }) => {
    const noErrors = trackErrors(page)
    const calls = watchContracts(page)
    await open(page, ownerDraft())
    await expand(page, "occupancy")
    await page.getByRole("button", { name: "Child ages…" }).click()
    const drawer = page.getByRole("dialog", { name: "Child age bands" })
    const label = drawer.getByLabel("Label: Child 3–6.99", { exact: true })
    await label.fill("Small child")
    await page.keyboard.press("Control+s")
    await expect(page.getByText("Draft saved")).toBeVisible()
    const body = calls.bodies("save_version").at(-1) as { data: { age_bands: Record<string, unknown>[] } }
    expect(body.data.age_bands.find((b) => b.band_code === "CHA")?.label).toBe("Small child")
    await expect(page.getByText("Unsaved changes", { exact: true })).toHaveCount(0)
    // typed, not committed: the tab asks before it closes
    await drawer.getByLabel("Label: Small child", { exact: true }).fill("Kid")
    let asked = ""
    page.once("dialog", (dlg) => {
      asked = dlg.type()
      void dlg.dismiss()
    })
    noErrors()
    await page.close({ runBeforeUnload: true })
    await expect.poll(() => asked).toBe("beforeunload")
  })

  test("Alt+Enter in a boards cell keeps what was typed and opens the row's terms; the row headers name the board", async ({ page }) => {
    const noErrors = trackErrors(page)
    await open(page, withBoards())
    await expand(page, "boards")
    await expect(boards(page).getByRole("rowheader").filter({ hasText: `Half board · ${N.DLX} only` })).toHaveCount(1)
    await bcell(page, "Half board", "All periods").click()
    await page.keyboard.type("+25")
    await page.keyboard.press("Alt+Enter")
    const pop = page.getByRole("dialog", { name: "Board terms: Half board" })
    await expect(pop).toBeVisible()
    await page.keyboard.press("Escape")
    await expect(pop).toBeHidden()
    await expect(bcell(page, "Half board", "All periods")).toHaveAttribute("aria-label", /\+25\.00/)
    await expect(page.getByText("Unsaved changes", { exact: true })).toBeVisible()
    noErrors()
  })

  test("one tab stop per grid: Tab leaves the matrix from a cell; the headers' menus are on the arrow keys", async ({ page }) => {
    const noErrors = trackErrors(page)
    await open(page, ownerDraft())
    const m = priceMatrix(page)
    await cellOf(page, N.STD, "P1").click()
    await page.keyboard.press("Tab")
    expect(await inGrid(m)).toBe(false)
    await cellOf(page, N.STD, "P1").click()
    await page.keyboard.press("Shift+Tab")
    expect(await inGrid(m)).toBe(false)
    // no header control is a Tab stop while the grid has a cell
    expect(await m.evaluate((g) => Array.from(g.querySelectorAll<HTMLElement>("button, select")).filter((b) => b.tabIndex >= 0).map((b) => b.getAttribute("aria-label") ?? b.textContent))).toEqual([])
    // ArrowUp from the first row: the period's menu button; ArrowRight along the header; ArrowDown back
    await cellOf(page, N.STD, "P1").click()
    await page.keyboard.press("ArrowUp")
    await expect(page.getByRole("button", { name: "Period actions: P1" })).toBeFocused()
    await page.keyboard.press("ArrowRight")
    await expect(page.getByRole("button", { name: "Period actions: P2" })).toBeFocused()
    await page.keyboard.press("ArrowDown")
    await expect(cellOf(page, N.STD, "P2")).toBeFocused()
    // ArrowLeft from the first column: the room's menu, opened with Enter
    await page.keyboard.press("Home")
    await page.keyboard.press("ArrowLeft")
    const roomMenu = page.getByRole("button", { name: `Room actions: ${N.STD}` })
    await expect(roomMenu).toBeFocused()
    await page.keyboard.press("ArrowDown")
    await expect(page.getByRole("button", { name: `Room actions: ${N.SUP}` })).toBeFocused()
    await page.keyboard.press("Enter")
    await expect(page.getByRole("menu", { name: `Room actions: ${N.SUP}` })).toBeVisible()
    await page.keyboard.press("Escape")
    await page.keyboard.press("ArrowRight")
    await expect(cellOf(page, N.SUP, "All periods")).toBeFocused()
    noErrors()
  })

  test("Shift+click on a column header selects every column from the last one picked", async ({ page }) => {
    const noErrors = trackErrors(page)
    await open(page, ownerDraft())
    const header = (code: string) => priceMatrix(page).getByRole("columnheader").filter({ hasText: new RegExp(`^${code}(?!\\d)`) }).first()
    await header("P3").click({ position: { x: 8, y: 8 } })
    await header("P4").click({ position: { x: 8, y: 8 }, modifiers: ["Shift"] })
    const selected = await priceMatrix(page).locator('[role="gridcell"][aria-selected="true"]').evaluateAll((els) => els.map((e) => (e.getAttribute("aria-label") ?? "").split(":")[0]))
    expect(selected.some((n) => n.endsWith("· P3"))).toBe(true)
    expect(selected.some((n) => n.endsWith("· P4"))).toBe(true)
    expect(selected.every((n) => /· P[34]$/.test(n))).toBe(true)
    noErrors()
  })

  test("at 1440×900 the Price test sits beside the matrix: the matrix, Save and Publish stay uncovered", async ({ page }) => {
    const noErrors = trackErrors(page)
    await page.setViewportSize({ width: 1440, height: 900 })
    await open(page, ownerDraft())
    await context(page).getByRole("button", { name: "Price test", exact: true }).click()
    const dr = page.getByRole("dialog", { name: "Price test" })
    await expect(dr).toBeVisible()
    const panel = (await dr.boundingBox())!
    expect(panel.width).toBeLessThanOrEqual(450)
    for (const el of [priceMatrix(page).locator("xpath=.."), page.getByRole("button", { name: "Publish", exact: true })]) {
      const box = (await el.boundingBox())!
      expect(box.x + box.width).toBeLessThanOrEqual(panel.x + 1)
    }
    // a right-click on a matrix cell beside it still reaches the cell
    await cellOf(page, N.SUP, "P3").click({ button: "right" })
    await page.getByRole("menuitem", { name: "Test this price" }).click()
    await expect(dr.getByLabel(/^Room type/)).toHaveValue(SUP)
    noErrors()
  })

  test("Ctrl+V and Ctrl+R on a ladder cell say where copy, paste and fill work", async ({ page }) => {
    const noErrors = trackErrors(page)
    await open(page, ownerDraft())
    await expand(page, "occupancy")
    await lcell(page, "3rd adult", "P2").click()
    const notice = page.getByText("Copy, paste and fill work in the room price matrix.", { exact: false })
    await page.keyboard.press("Control+v")
    await expect(notice.first()).toBeVisible()
    await expect(lcell(page, "3rd adult", "P2")).toBeFocused()
    // Ctrl+R neither reloads the page nor does nothing without a word
    const shown = await notice.count()
    await page.keyboard.press("Control+r")
    await expect.poll(() => notice.count()).toBeGreaterThan(shown)
    await expect(lcell(page, "3rd adult", "P2")).toBeFocused()
    noErrors()
  })

  test("German: a weekday-limited period names its days in German; + Periode is named by what it shows (the workspace says Periode throughout, final follow-up)", async ({ page }) => {
    const noErrors = trackErrors(page)
    const draft = ownerDraft()
    draft.periods = [...periods(), { period_code: "P5", period_name: "WE", start_date: `${Y}-04-01`, end_date: `${Y}-07-31`, weekdays: "Fri,Sat", priority: 1 }]
    await open(page, draft, { lang: "de" })
    const m = page.getByRole("grid").first()
    const p5 = m.getByRole("columnheader").filter({ hasText: /^P5/ }).first()
    await expect(p5).toContainText("nur ")
    await expect(p5).not.toContainText("Fri")
    await expect(p5).toContainText(new Intl.DateTimeFormat("de", { weekday: "short" }).format(new Date(2024, 0, 5, 12)))
    const add = page.getByRole("button", { name: "Periode hinzufügen" })
    await expect(add).toHaveText("Periode")
    // one word for a period in the matrix: its menus say Periodenaktionen, its first column Alle Perioden
    await expect(m.getByRole("columnheader").filter({ hasText: "Alle Perioden" })).toHaveCount(1)
    await expect(m.getByRole("button", { name: "Periodenaktionen: P1" })).toHaveCount(1)
    expect(await m.textContent()).not.toMatch(/Zeitr/)
    noErrors()
  })
})
