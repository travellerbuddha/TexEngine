// Boards in the Pricing Workspace (PRICING_WORKSPACE_UX.md §3.12; slice S13): the owner's boards
// typed as BASE, -5% and -20 (O1–O3) and priced in the Price test, the reading line with the unit,
// BASE and x2 refused with board words, a period rule and clearing a board with its confirmation and
// undo, the row terms popover and a rule for one room, the matrix's active period, the collapsed
// chips and #boards, a phone, and a read-only published version.
import { expect, test, type Locator, type Page } from "@playwright/test"
import { login, pageApiOk, trackErrors } from "./helpers"
import { pickFrom } from "./flows/budget"
import { archiveAll, DLX, newDraft as draftOf, ownerRates, periods, rooms, SUP, versionPath, watchContracts, Y } from "./flows/workspace"

test.use({ locale: "en-US", actionTimeout: 15_000, navigationTimeout: 30_000 })

const made: string[] = []

type BoardRowIn = { board: string; is_base: number; op: string; adult_amount: string | null; child_percent?: string; infant_free?: number; room_type?: string; period_code?: string }

/** The owner's rooms (with capacity), P1–P4 and prices, and `boards`. */
const newDraft = (page: Page, boards: BoardRowIn[]) =>
  draftOf(page, "E2E-PWD", {
    rooms: rooms(),
    periods: periods(),
    period_rates: ownerRates(),
    boards: boards.map((x) => ({ child_percent: "50", infant_free: 1, room_type: "", period_code: "", ...x })),
  })

async function open(page: Page, boards: BoardRowIn[], hash = "#boards") {
  await login(page, "revenue@demo.tex")
  const d = await newDraft(page, boards)
  made.push(d.contract)
  await page.goto(versionPath(d, hash))
  await expect(page.getByRole("grid", { name: "Room prices by period" })).toBeVisible()
  return d
}

const section = (page: Page) => page.locator("section#boards")
const grid = (page: Page) => page.getByRole("grid", { name: "Board supplements by period" })
const cell = (page: Page, name: string) => grid(page).getByRole("gridcell", { name: new RegExp(`^${name.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}: `) })
const editor = (page: Page) => grid(page).getByRole("textbox")
const reading = (page: Page) => grid(page).getByRole("status")
const addBoard = (page: Page, code: string) => pickFrom(section(page).getByRole("button", { name: "Add board", exact: true }), code)
/** the main line of a stacked cell (the unit is the second line) */
const shown = (l: Locator) => l.locator("span").first().locator("xpath=./span[1]")

const OWNER = [
  { board: "UAI", is_base: 1, op: "ADD", adult_amount: null },
  { board: "AI", is_base: 0, op: "ADJUST_PERCENT", adult_amount: "-5" },
  { board: "HB", is_base: 0, op: "ADD", adult_amount: "-20" },
]

test.describe.serial("boards", () => {
  test.afterAll(async ({ browser }) => archiveAll(browser, made, "pricing workspace boards e2e clean-up"))

  test("1. the owner example typed as BASE, -5%, -20: saved as UAI base, AI ADJUST_PERCENT -5, HB ADD -20; priced in the Price test with board HB", async ({ page }) => {
    const noErrors = trackErrors(page)
    const calls = watchContracts(page)
    const d = await open(page, [])
    // #boards on a draft without boards: the section is open, with the empty notice
    await expect(section(page).getByRole("button", { name: "Boards" })).toHaveAttribute("aria-expanded", "true")
    await expect(section(page)).toContainText("No boards yet. Add the board the room price includes first")
    // the first board is the base board
    await addBoard(page, "UAI")
    await expect(grid(page)).toBeVisible()
    await expect(cell(page, "Ultra all inclusive · All periods")).toBeFocused()
    await expect(cell(page, "Ultra all inclusive · All periods")).toHaveAttribute("aria-label", /base board, included/)
    await expect(shown(cell(page, "Ultra all inclusive · All periods"))).toHaveText("BASE")
    // BASE typed again: no change
    await page.keyboard.type("BASE")
    await expect(reading(page)).toHaveText("No change.")
    await page.keyboard.press("Enter")
    // AI: a row waiting for its value, edited at once
    await addBoard(page, "AI")
    await expect(editor(page)).toBeFocused()
    await expect(editor(page)).toHaveAccessibleName("Supplement: All inclusive · All periods")
    await expect(reading(page)).toContainText("Type the supplement: 20 = per room per night")
    await page.keyboard.type("-5%")
    await expect(reading(page)).toHaveText("All inclusive · All periods: −5% of the night's occupancy price")
    await page.keyboard.press("Enter")
    await expect(shown(cell(page, "All inclusive · All periods"))).toHaveText("−5%")
    // HB
    await addBoard(page, "HB")
    await expect(editor(page)).toBeFocused()
    await page.keyboard.type("-20")
    await expect(reading(page)).toHaveText("Half board · All periods: −20.00 per adult per night; children 50 %, infants free")
    await page.keyboard.press("Enter")
    await expect(shown(cell(page, "Half board · All periods"))).toHaveText("−20.00")
    await expect(cell(page, "Half board · P3")).toHaveAttribute("aria-label", /follows another rule/)
    await expect(page.locator('[aria-modal="true"]')).toHaveCount(0)
    // BASE moved to AI before any save: UAI's row has no value (the server would refuse it)
    await cell(page, "All inclusive · All periods").click()
    await page.keyboard.type("base")
    await page.keyboard.press("Enter")
    await expect(cell(page, "Ultra all inclusive · All periods")).toHaveAttribute("aria-label", /no supplement yet/)
    await expect(shown(cell(page, "All inclusive · All periods"))).toHaveText("BASE")
    await page.keyboard.press("Control+z")
    await expect(shown(cell(page, "Ultra all inclusive · All periods"))).toHaveText("BASE")
    await expect(shown(cell(page, "All inclusive · All periods"))).toHaveText("−5%")
    // collapsed: the chips
    await section(page).getByRole("button", { name: "Boards" }).click()
    const chips = section(page).getByRole("list", { name: "Boards summary" })
    await expect(chips.getByRole("listitem")).toHaveText(["UAI BASE", "AI −5 %", "HB −20.00 per adult"])
    expect(calls.count("save_version")).toBe(0)
    // Save: ordinary board rows
    await page.getByRole("button", { name: /^Save/ }).first().click()
    await expect(page.getByText("Draft saved")).toBeVisible()
    const v = await pageApiOk<{ boards: Record<string, unknown>[] }>(page, "kamra.tex.api.contracts.get_version", { name: d.version })
    expect(v.boards.map((b) => `${b.board}:${b.is_base}:${b.is_base ? "" : `${b.op}:${Number(b.adult_amount)}:${Number(b.child_percent)}:${b.infant_free}`}:${b.room_type || ""}:${b.period_code || ""}`)).toEqual([
      "UAI:1:::",
      "AI:0:ADJUST_PERCENT:-5:50:1::",
      "HB:0:ADD:-20:50:1::",
    ])
    // the Price test with board HB: 2 adults in Standard, 3 nights in P1 (70 per person)
    const priceTest = async (board: string) => {
      await page.getByRole("button", { name: "Price test" }).click()
      const drawer = page.getByRole("dialog", { name: "Price test" })
      await expect(drawer).toBeVisible()
      await drawer.getByLabel(/^Room type/).selectOption({ label: "Standard Sea View" })
      await drawer.getByLabel(/^Board/).selectOption(board)
      await drawer.getByLabel(/^Adults/).fill("2")
      await drawer.getByLabel(/^Check-in/).fill(`${Y}-04-10`)
      await drawer.getByLabel(/^Check-out/).fill(`${Y}-04-13`)
      await drawer.getByRole("button", { name: /^Calculate/ }).click()
      const total = drawer.getByRole("status", { name: "Total" })
      await expect(total).toBeVisible()
      const text = (await total.innerText()).trim()
      const steps = (await drawer.getByRole("list").filter({ hasText: "Rule applied:" }).getByRole("listitem").allInnerTexts()).map((s) => s.replace(/\s+/g, " ").trim())
      await drawer.getByRole("button", { name: /close/i }).first().click()
      return { text, steps }
    }
    const hb = await priceTest("HB")
    const uai = await priceTest("UAI")
    expect(hb.steps.some((s) => /board HB supplement/i.test(s) && /-40|−40/.test(s))).toBe(true)
    expect(uai.steps.some((s) => /board UAI included/i.test(s))).toBe(true)
    expect(hb.text).not.toEqual(uai.text)
    noErrors()
  })

  test("2. typing 100 in HB shows the per-room reading; BASE outside All periods and x2 are refused with board words", async ({ page }) => {
    const noErrors = trackErrors(page)
    await open(page, OWNER)
    const hb = cell(page, "Half board · All periods")
    await hb.click()
    await page.keyboard.type("100")
    await expect(reading(page)).toHaveText("Half board · All periods: 100.00 per room per night (fixed)")
    await page.keyboard.press("Escape")
    await expect(shown(hb)).toHaveText("−20.00")
    await cell(page, "Half board · P2").click()
    await page.keyboard.type("base")
    await expect(reading(page)).toHaveText("Type BASE in one board's All periods cell: the base board is included in every room and period.")
    await expect(editor(page)).toHaveAttribute("aria-invalid", "true")
    await page.keyboard.press("Escape")
    await page.keyboard.type("x2")
    await expect(reading(page)).toContainText("Boards take no multiplier.")
    // Enter keeps the entry as an error draft in the cell
    await page.keyboard.press("Enter")
    await expect(editor(page)).toBeFocused()
    await page.keyboard.press("Escape")
    // AI BASE: UAI loses its base and needs a value
    await cell(page, "All inclusive · All periods").click()
    await page.keyboard.type("BASE")
    // boards by name, as the row headers and cells name them (S16 re-review)
    await expect(reading(page)).toHaveText("All inclusive · All periods: All inclusive becomes the base board, included in the room price; Ultra all inclusive is no longer included and needs a supplement")
    await page.keyboard.press("Enter")
    // a saved base row loads with the amount 0 (GAP-8): UAI now reads as a +0.00 supplement
    await expect(cell(page, "Ultra all inclusive · All periods")).toHaveAttribute("aria-label", /\+0\.00 per adult per night/)
    await expect(section(page).getByText("No board is marked as included")).toHaveCount(0)
    await page.keyboard.press("Control+z")
    await expect(shown(cell(page, "Ultra all inclusive · All periods"))).toHaveText("BASE")
    noErrors()
  })

  test("3. period rule ◆, clear a period cell, clear the board's own cell asks first; Undo brings the board back; data-cellid", async ({ page }) => {
    const noErrors = trackErrors(page)
    await open(page, OWNER)
    await cell(page, "Half board · P2").click()
    await page.keyboard.type("-25")
    await expect(reading(page)).toHaveText("Half board · P2: −25.00 per adult per night; children 50 %, infants free")
    await page.keyboard.press("Enter")
    const p2 = cell(page, "Half board · P2")
    await expect(shown(p2)).toHaveText("◆ −25.00")
    await expect(p2).toHaveAttribute("data-cellid", "board:HB||P2")
    await expect(p2).toHaveAttribute("aria-label", /period rule/)
    // Delete on the period cell: that row only
    await p2.click()
    await page.keyboard.press("Delete")
    await expect(p2).toHaveAttribute("aria-label", /follows another rule/)
    // Delete on the board's own All periods cell: the inline confirmation
    await cell(page, "Half board · All periods").click()
    await page.keyboard.press("Delete")
    const confirm = section(page).getByRole("group", { name: "Remove board" })
    await expect(confirm).toContainText("Remove Half board from this version? 1 rule is removed.")
    await expect(confirm.getByRole("button", { name: "Remove" })).toBeFocused()
    await page.keyboard.press("Escape")
    await expect(confirm).toHaveCount(0)
    await expect(cell(page, "Half board · All periods")).toBeFocused()
    await page.keyboard.press("Delete")
    await confirm.getByRole("button", { name: "Remove" }).click()
    await expect(cell(page, "Half board · All periods")).toHaveCount(0)
    await expect(page.getByTestId("undo-toast")).toContainText("Removed: Half board")
    await page.getByTestId("undo-toast").getByRole("button", { name: "Undo" }).click()
    await expect(shown(cell(page, "Half board · All periods"))).toHaveText("−20.00")
    noErrors()
  })

  test("4. the row popover: children %, a rule for one room (indented row), room scope; the matrix's active period is highlighted", async ({ page }) => {
    const noErrors = trackErrors(page)
    await open(page, OWNER)
    await section(page).getByRole("button", { name: "Board terms: Half board" }).click()
    const pop = page.getByRole("dialog", { name: "Board terms: Half board" })
    await expect(pop).toBeVisible()
    await expect(page.locator('[aria-modal="true"]')).toHaveCount(0)
    await pop.getByLabel(/^Children pay/).fill("30")
    await pop.getByRole("button", { name: "Apply" }).click()
    await expect(pop).toHaveCount(0)
    await expect(section(page).getByRole("button", { name: "Board terms: Half board" })).toBeFocused()
    await expect(section(page).locator('[data-board-row="HB|"]')).toContainText("per adult per night; children 30 %, infants free")
    // Add a rule for one room: an indented row edited at once
    await section(page).getByRole("button", { name: "Board terms: Half board" }).click()
    await pickFrom(page.getByRole("dialog", { name: "Board terms: Half board" }).getByRole("button", { name: "Add a rule for one room", exact: true }), "Garden Villa")
    await expect(editor(page)).toBeFocused()
    await expect(editor(page)).toHaveAccessibleName("Supplement: Half board · Garden Villa only · All periods")
    await page.keyboard.type("-10")
    await expect(reading(page)).toHaveText("Half board · Garden Villa only · All periods: −10.00 per adult per night; children 30 %, infants free")
    await page.keyboard.press("Enter")
    const row = section(page).locator('[data-board-row="HB|' + DLX + '"]')
    await expect(row.getByRole("rowheader")).toContainText("Half board · Garden Villa only")
    // the matrix's active period (P3) is highlighted in the boards grid
    const matrix = page.getByRole("grid", { name: "Room prices by period" })
    await matrix.getByRole("gridcell", { name: /^Standard Sea View · P3: / }).click()
    await expect(grid(page).locator("[data-matrix-period]")).toContainText("P3")
    await matrix.getByRole("gridcell", { name: /^Standard Sea View · P3: / }).press("ArrowRight")
    await expect(grid(page).locator("[data-matrix-period]")).toContainText("P4")
    // Rooms: the Garden Villa rule moves to Family Suite
    await section(page).getByRole("button", { name: "Board terms: Half board · Garden Villa only" }).click()
    const pop2 = page.getByRole("dialog", { name: "Board terms: Half board · Garden Villa only" })
    await pop2.getByLabel(/^Rooms/).selectOption({ label: "Family Suite" })
    await pop2.getByRole("button", { name: "Apply" }).click()
    await expect(section(page).locator('[data-board-row="HB|' + SUP + '"]')).toBeVisible()
    await expect(cell(page, "Half board · Family Suite only · All periods")).toBeFocused()
    // moving the board's own rows onto a scope it has: refused in the popover
    await section(page).getByRole("button", { name: "Board terms: Half board", exact: true }).click()
    const pop3 = page.getByRole("dialog", { name: "Board terms: Half board" })
    await pop3.getByLabel(/^Rooms/).selectOption({ label: "Family Suite" })
    await pop3.getByRole("button", { name: "Apply" }).click()
    await expect(pop3).toContainText("Half board already has rules for Family Suite: edit that row instead.")
    await page.keyboard.press("Escape")
    // a cell's context menu (and Alt+Enter) opens its row's terms; Escape gives the focus back
    await cell(page, "All inclusive · P2").click({ button: "right" })
    await expect(page.getByRole("dialog", { name: "Board terms: All inclusive" })).toBeVisible()
    await page.keyboard.press("Escape")
    await expect(cell(page, "All inclusive · P2")).toBeFocused()
    await page.keyboard.press("Alt+Enter")
    await expect(page.getByRole("dialog", { name: "Board terms: All inclusive" })).toBeVisible()
    await page.keyboard.press("Escape")
    noErrors()
  })

  test("5. a version with boards opens collapsed with chips; #boards opens it; phones: no sideways page scroll", async ({ page }) => {
    const noErrors = trackErrors(page)
    await page.addInitScript(() => window.localStorage.removeItem("tex.rates.ws.boards_open"))
    const d = await open(page, OWNER, "")
    await expect(section(page).getByRole("button", { name: "Boards" })).toHaveAttribute("aria-expanded", "false")
    await expect(section(page).getByRole("list", { name: "Boards summary" })).toBeVisible()
    await page.goto(versionPath(d, "#boards"))
    await expect(section(page).getByRole("button", { name: "Boards" })).toHaveAttribute("aria-expanded", "true")
    await expect(grid(page)).toBeVisible()
    // scrolled to (the section is the last on the page, so it is brought into view as far as the page goes)
    await expect(section(page).getByRole("heading", { name: "Boards" })).toBeInViewport()
    await page.setViewportSize({ width: 375, height: 800 })
    await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth)).toBeLessThanOrEqual(0)
    await section(page).scrollIntoViewIfNeeded()
    noErrors()
  })

  test("6. a published version: the grid is read-only, no Add board, no terms, no editor", async ({ page }) => {
    const noErrors = trackErrors(page)
    await login(page, "revenue@demo.tex")
    const d = await newDraft(page, OWNER)
    made.push(d.contract)
    await pageApiOk(page, "kamra.tex.api.contracts.publish_version", { name: d.version })
    await page.goto(versionPath(d, "#boards"))
    await expect(grid(page)).toHaveAttribute("aria-readonly", "true")
    await expect(shown(cell(page, "Half board · All periods"))).toHaveText("−20.00")
    await expect(section(page).getByRole("button", { name: "Add board", exact: true })).toHaveCount(0)
    await expect(section(page).getByRole("button", { name: /^Board terms/ })).toHaveCount(0)
    await cell(page, "Half board · All periods").click()
    await page.keyboard.type("100")
    await page.keyboard.press("Delete")
    await expect(grid(page).getByRole("textbox")).toHaveCount(0)
    await expect(shown(cell(page, "Half board · All periods"))).toHaveText("−20.00")
    await expect(cell(page, "Half board · All periods")).toHaveAttribute("aria-readonly", "true")
    noErrors()
  })
})
