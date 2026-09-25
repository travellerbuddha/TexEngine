// The matrix's bulk tools (PRICING_WORKSPACE_UX.md §3.10; slice S10 and its two review follow-ups):
// Ctrl/Cmd+Enter over a selection with undo, redo and the ten-second toast; Adjust… priced by the
// server; TSV copy and paste (shape, invalid cells, resolved rows); header selection; Fill → / Fill ↓
// and the fixed price override; the Russian-layout shortcuts; Rule table edits in the same undo
// history; the keyboard shortcuts popover, the phone toolbar and Discard clearing the history.
// Every test starts from its own API-made draft of the owner's prices.
import { expect, test, type Locator, type Page } from "@playwright/test"
import { login, trackErrors } from "./helpers"
import { cell as rowCell, openSection, openTab, priceMatrix } from "./flows/contracts"
import { archiveAll, DLX, N, newDraft, openVersion, ownerRates, periods, rooms, watchContracts, type Data } from "./flows/workspace"

test.use({ locale: "en-US", actionTimeout: 15_000, navigationTimeout: 30_000 })

const made: string[] = []
test.afterAll(async ({ browser }) => archiveAll(browser, made, "pricing workspace bulk e2e clean-up"))

const bb = [{ board: "BB", is_base: 1, op: "ADD", adult_amount: null, child_percent: "50", infant_free: 1 }]

/** Standard (base) 70 / 80 / 100 / 130, Family Suite ×1.15 and Garden Villa ×1.35 for all periods. */
async function open(page: Page) {
  return openWith(page, { rooms: rooms({}), periods: periods(), period_rates: ownerRates(), boards: bb })
}

/** Standard (base) 70 / 80 / 100 / 130, Family Suite ×1.15, Garden Villa a manual room 90 / 95 / 100 /
 * 105: with the resolved rows shown the rows are Standard, Family Suite, its resolved row, Garden Villa. */
async function openManual(page: Page) {
  const P = ["P1", "P2", "P3", "P4"]
  return openWith(page, {
    rooms: rooms({}),
    periods: periods(),
    period_rates: [
      ...ownerRates().filter((r) => r.room_type !== DLX),
      ...P.map((p, i) => ({ room_type: DLX, period_code: p, op: "ABSOLUTE", value: ["90", "95", "100", "105"][i] })),
    ],
    boards: bb,
  })
}

async function openWith(page: Page, data: Data) {
  await login(page, "revenue@demo.tex")
  const d = await newDraft(page, "E2E-PWK", data)
  made.push(d.contract)
  await openVersion(page, d)
  await expect(resolved(page, N.SUP, "P1", "80.50")).toBeVisible()
  return d
}

const grid = (page: Page) => priceMatrix(page)
const cellOf = (page: Page, room: string, period: string) =>
  grid(page)
    .getByRole("gridcell", { name: new RegExp(`^${room} · ${period}: (?!resolved)`) })
    .first()
const named = (page: Page, name: string) => grid(page).getByRole("gridcell", { name, exact: true })
const resolved = (page: Page, room: string, period: string, amount: string) => grid(page).getByRole("gridcell", { name: `${room} · ${period}: resolved price, EUR ${amount}` })
/** The matrix's live region (what a screen reader hears after a gesture). */
const live = (page: Page, text: string | RegExp) => page.locator("section[aria-labelledby='pm-title'] [role='status'] .sr-only").filter({ hasText: text })
const toastOf = (page: Page) => page.getByTestId("undo-toast")
const toolbar = (page: Page) => page.getByRole("group", { name: "Bulk tools" })
const read = (page: Page) => page.evaluate(() => navigator.clipboard.readText())
const focusedRole = (page: Page) => page.evaluate(() => `${document.activeElement?.getAttribute("role")}:${document.activeElement?.getAttribute("aria-label") ?? document.activeElement?.tagName}`)

async function selectRange(page: Page, from: Locator, shiftRight: number) {
  await from.click()
  for (let i = 0; i < shiftRight; i++) await page.keyboard.press("Shift+ArrowRight")
}

test.describe("bulk tools", () => {
  test("1. Deluxe P3:P4 x1.40 + Ctrl+Enter → overrides, toast; Ctrl+Z restores; Ctrl+Y and Ctrl+Shift+Z redo; the toast's Undo within 10 s", async ({ page }) => {
    const noErrors = trackErrors(page)
    await open(page)
    await selectRange(page, cellOf(page, N.DLX, "P3"), 1)
    await expect(cellOf(page, N.DLX, "P4")).toHaveAttribute("aria-selected", "true")
    await page.keyboard.type("x1.40")
    await page.keyboard.press("Control+Enter")
    for (const p of ["P3", "P4"]) await expect(named(page, `${N.DLX} · ${p}: period override, ${N.STD} ×1.4`)).toBeVisible()
    await expect(toastOf(page)).toContainText("Applied to 2 cells")
    await expect(live(page, "Applied to 2 cells")).toHaveCount(1)
    for (const [p, v] of [["P3", "140.00"], ["P4", "182.00"]]) await expect(resolved(page, N.DLX, p, v)).toBeVisible()

    // Ctrl+Z with the grid focused (the edited cell, P4) restores both cells (one entry)
    await expect(cellOf(page, N.DLX, "P4")).toBeFocused()
    await page.keyboard.press("Control+z")
    for (const p of ["P3", "P4"]) await expect(named(page, `${N.DLX} · ${p}: follows all periods, ${N.STD} ×1.35`)).toBeVisible()
    await expect(live(page, "Undone: Prices of 2 cells")).toHaveCount(1)
    await expect(toastOf(page)).toHaveCount(0)
    for (const [p, v] of [["P3", "135.00"], ["P4", "175.50"]]) await expect(resolved(page, N.DLX, p, v)).toBeVisible()
    // redo: Ctrl+Y, then undo and Ctrl+Shift+Z
    await page.keyboard.press("Control+y")
    await expect(named(page, `${N.DLX} · P3: period override, ${N.STD} ×1.4`)).toBeVisible()
    await expect(live(page, "Redone: Prices of 2 cells")).toHaveCount(1)
    await page.keyboard.press("Control+z")
    await expect(named(page, `${N.DLX} · P3: follows all periods, ${N.STD} ×1.35`)).toBeVisible()
    await page.keyboard.press("Control+Shift+Z")
    await expect(named(page, `${N.DLX} · P3: period override, ${N.STD} ×1.4`)).toBeVisible()

    // the toast's Undo, within 10 s
    await selectRange(page, cellOf(page, N.SUP, "P1"), 2)
    await page.keyboard.type("x1.2")
    await page.keyboard.press("Control+Enter")
    await expect(toastOf(page)).toContainText("Applied to 3 cells")
    const shownAt = Date.now()
    await page.waitForTimeout(5_000)
    await expect(toastOf(page)).toBeVisible()
    await toastOf(page).getByRole("button", { name: "Undo" }).click()
    expect(Date.now() - shownAt).toBeLessThan(10_000)
    for (const p of ["P1", "P2", "P3"]) await expect(named(page, `${N.SUP} · ${p}: follows all periods, ${N.STD} ×1.15`)).toBeVisible()
    await expect(toastOf(page)).toHaveCount(0)
    // the Deluxe overrides (an earlier entry) are still there: the toast undid its own entry only
    await expect(named(page, `${N.DLX} · P3: period override, ${N.STD} ×1.4`)).toBeVisible()

    // the toast goes by itself after 10 s
    await selectRange(page, cellOf(page, N.SUP, "P1"), 1)
    await page.keyboard.type("x1.25")
    await page.keyboard.press("Control+Enter")
    await expect(toastOf(page)).toBeVisible()
    const t0 = Date.now()
    await page.waitForTimeout(8_500)
    await expect(toastOf(page)).toBeVisible()
    await expect(toastOf(page)).toHaveCount(0, { timeout: 4_000 })
    const gone = Date.now() - t0
    expect(gone).toBeGreaterThan(9_000)
    expect(gone).toBeLessThan(12_500)
    // a later edit takes the toast away (its Undo would no longer undo its own entry)
    await selectRange(page, cellOf(page, N.SUP, "P3"), 1)
    await page.keyboard.type("x1.3")
    await page.keyboard.press("Control+Enter")
    await expect(toastOf(page)).toBeVisible()
    await cellOf(page, N.STD, "P1").click()
    await page.keyboard.type("71")
    await page.keyboard.press("Enter")
    await expect(toastOf(page)).toHaveCount(0)
    noErrors()
  })

  test("2. Adjust +10% on Standard P1:P4: the server's preview 70.00 → 77.00 …, Apply, Undo; O5 on amounts; formula cells skipped", async ({ page }) => {
    const noErrors = trackErrors(page)
    const net = watchContracts(page)
    await open(page)
    await cellOf(page, N.STD, "P1").click()
    await page.keyboard.press("Shift+End")
    await expect(cellOf(page, N.STD, "P4")).toHaveAttribute("aria-selected", "true")
    // Family Suite P1 (a formula) is added with Ctrl+Click: skipped and counted
    await cellOf(page, N.SUP, "P1").click({ modifiers: ["Control"] })
    net.reset()
    await toolbar(page).getByRole("button", { name: "Adjust…" }).click()
    const pop = page.getByRole("dialog", { name: "Adjust prices" })
    await expect(pop).toBeVisible()
    await expect(page.locator("[aria-modal='true']")).toHaveCount(0)
    const value = pop.getByLabel(/^Value/)
    await expect(value).toBeFocused()
    await expect(pop).toContainText("4 entered prices selected")
    await expect(pop).toContainText("1 formula cell skipped")
    await page.keyboard.type("10")
    for (const line of ["Standard Sea View · P1: 70.00 → 77.00", "Standard Sea View · P2: 80.00 → 88.00", "Standard Sea View · P3: 100.00 → 110.00", "Standard Sea View · P4: 130.00 → 143.00"])
      await expect(pop.getByText(line, { exact: true })).toBeVisible()
    // one call for the two keystrokes (debounced), with the prices as they are
    expect(net.count("apply_op_values")).toBe(1)
    expect(net.bodies("apply_op_values")[0]).toMatchObject({ values: ["70", "80", "100", "130"], op: "ADJUST_PERCENT", value: "10" })
    const applyBtn = pop.getByRole("button", { name: "Apply" })
    await expect(applyBtn).toBeEnabled()

    // −amount 1.500 in EUR: AMBIGUOUS, Apply disabled; 1.5 is fine
    await pop.getByRole("radio", { name: "− amount" }).click()
    await value.fill("1.500")
    await expect(pop.getByText("Is this 1500 or 1.5?", { exact: false })).toBeVisible()
    await expect(applyBtn).toBeDisabled()
    // × 0: every price would be 0.00: allowed; − amount 200: below zero, listed and Apply disabled
    await value.fill("200")
    await expect(pop.getByText("Standard Sea View · P1: The result would be below zero.")).toBeVisible()
    await expect(applyBtn).toBeDisabled()
    // back to +10 %
    await pop.getByRole("radio", { name: "+ %" }).click()
    await value.fill("10")
    await expect(pop.getByText("Standard Sea View · P1: 70.00 → 77.00", { exact: true })).toBeVisible()
    await expect(applyBtn).toBeEnabled()
    await applyBtn.click()
    await expect(pop).toBeHidden()
    for (const [p, v] of [["P1", "77.00"], ["P2", "88.00"], ["P3", "110.00"], ["P4", "143.00"]]) await expect(named(page, `${N.STD} · ${p}: entered price, ${v}`)).toBeVisible()
    await expect(named(page, `${N.SUP} · P1: follows all periods, ${N.STD} ×1.15`)).toBeVisible()
    await expect(toastOf(page)).toContainText("Applied to 4 cells")
    await expect(resolved(page, N.SUP, "P1", "88.55")).toBeVisible()
    // Undo (toolbar) restores the recorded prices; no server call
    net.reset()
    await toolbar(page).getByRole("button", { name: "Undo" }).click()
    for (const [p, v] of [["P1", "70.00"], ["P2", "80.00"], ["P3", "100.00"], ["P4", "130.00"]]) await expect(named(page, `${N.STD} · ${p}: entered price, ${v}`)).toBeVisible()
    expect(net.count("apply_op_values")).toBe(0)
    await expect(toolbar(page).getByRole("button", { name: "Redo" })).toBeEnabled()
    noErrors()
  })

  test("3. Paste a 1×4 spreadsheet block into Standard; a 2×2 block over a resolved row; invalid and oversize blocks apply nothing; Ctrl+C copies TSV", async ({ page, context }) => {
    const noErrors = trackErrors(page)
    await context.grantPermissions(["clipboard-read", "clipboard-write"])
    await open(page)
    const clip = (text: string) => page.evaluate((t) => navigator.clipboard.writeText(t), text)
    const read = () => page.evaluate(() => navigator.clipboard.readText())

    // Ctrl+C of Standard P1:P4 (canonical edit text) and of Garden Villa's resolved row (exact amounts)
    await selectRange(page, cellOf(page, N.STD, "P1"), 3)
    await page.keyboard.press("Control+c")
    await expect.poll(read).toBe("70\t80\t100\t130\n")
    await expect(live(page, "Copied 4 cells")).toHaveCount(1)
    await resolved(page, N.DLX, "P1", "94.50").click()
    await page.keyboard.press("Shift+ArrowRight")
    await page.keyboard.press("Control+c")
    await expect.poll(read).toBe("94.5\t108\n")

    // a 1×4 block from a spreadsheet (Windows line break at the end) into Standard P1
    await clip("75\t85,5\t105\t135\r\n")
    await cellOf(page, N.STD, "P1").click()
    await page.keyboard.press("Control+v")
    for (const [p, v] of [["P1", "75.00"], ["P2", "85.50"], ["P3", "105.00"], ["P4", "135.00"]]) await expect(named(page, `${N.STD} · ${p}: entered price, ${v}`)).toBeVisible()
    await expect(toastOf(page)).toContainText("Applied to 4 cells")

    // a 2×2 block at Family Suite P1: its rows go to Family Suite and Garden Villa (the resolved row is passed over)
    await clip("x1.1\tx1.2\nx1.3\tx1.4\n")
    await cellOf(page, N.SUP, "P1").click()
    await page.keyboard.press("Control+v")
    await expect(named(page, `${N.SUP} · P1: period override, ${N.STD} ×1.1`)).toBeVisible()
    await expect(named(page, `${N.SUP} · P2: period override, ${N.STD} ×1.2`)).toBeVisible()
    await expect(named(page, `${N.DLX} · P1: period override, ${N.STD} ×1.3`)).toBeVisible()
    await expect(named(page, `${N.DLX} · P2: period override, ${N.STD} ×1.4`)).toBeVisible()
    await expect(resolved(page, N.SUP, "P1", "82.50")).toBeVisible()

    // an invalid cell: nothing is applied, the failures are named
    await clip("90\tabc\t1.500\n")
    await cellOf(page, N.STD, "P1").click()
    await page.keyboard.press("Control+v")
    const alert = page.getByRole("alert").filter({ hasText: "Nothing was pasted." })
    await expect(alert).toContainText("P2 · Standard Sea View: “abc”: Not a price or formula.")
    await expect(alert).toContainText("P3 · Standard Sea View: “1.500”: Is this 1500 or 1.5?")
    await expect(named(page, `${N.STD} · P1: entered price, 75.00`)).toBeVisible()
    // too wide: SHAPE
    await clip("1\t2\t3\n")
    await cellOf(page, N.STD, "P3").click()
    await page.keyboard.press("Control+v")
    await expect(page.getByRole("alert").filter({ hasText: "The pasted block is 1×3 but only 3×2 editable cells are available here." })).toBeVisible()
    // one value fills a selection
    await clip("x1.5")
    await selectRange(page, cellOf(page, N.DLX, "P3"), 1)
    await page.keyboard.press("Control+v")
    for (const p of ["P3", "P4"]) await expect(named(page, `${N.DLX} · ${p}: period override, ${N.STD} ×1.5`)).toBeVisible()
    // on a resolved row: refused
    await resolved(page, N.DLX, "P1", "97.50").click()
    await clip("80\t90")
    await page.keyboard.press("Control+v")
    await expect(page.getByRole("alert").filter({ hasText: "Paste into a price or formula row" })).toBeVisible()
    noErrors()
  })

  test("4. Header clicks select; Fill → copies across; Fill ↓ into formula rows asks for the fixed price override; a formula is never filled into a price row", async ({ page }) => {
    const noErrors = trackErrors(page)
    await open(page)
    // the row header of Standard selects its five editable cells and focuses the first
    await page.getByRole("rowheader").filter({ hasText: N.STD }).first().click({ position: { x: 12, y: 8 } })
    await expect(grid(page).locator("[aria-selected='true']")).toHaveCount(5)
    await expect(cellOf(page, N.STD, "All periods")).toBeFocused()
    // Ctrl+R: All periods (empty) across P1..P4 would clear them; instead select P1:P4 and fill right
    await selectRange(page, cellOf(page, N.STD, "P1"), 3)
    await page.keyboard.press("Control+r")
    for (const p of ["P2", "P3", "P4"]) await expect(named(page, `${N.STD} · ${p}: entered price, 70.00`)).toBeVisible()
    await expect(toastOf(page)).toContainText("Applied to 3 cells")
    await page.keyboard.press("Control+z")
    await expect(named(page, `${N.STD} · P4: entered price, 130.00`)).toBeVisible()

    // the P2 column header selects Standard, Family Suite and Garden Villa P2 (not the resolved rows)
    await page.getByRole("grid", { name: "Room prices by period" }).getByRole("columnheader").filter({ hasText: "P2" }).click({ position: { x: 60, y: 30 } })
    await expect(grid(page).locator("[aria-selected='true']")).toHaveCount(3)
    await expect(cellOf(page, N.STD, "P2")).toBeFocused()
    await page.keyboard.press("Control+d")
    const ask = page.getByRole("group", { name: "Fixed price override" })
    await expect(ask).toContainText("2 cells of formula rows would get a fixed price instead of their formula. Set a fixed price override?")
    await expect(ask.getByRole("button", { name: "Set fixed price" })).toBeFocused()
    // Escape drops it
    await page.keyboard.press("Escape")
    await expect(ask).toHaveCount(0)
    await expect(named(page, `${N.SUP} · P2: follows all periods, ${N.STD} ×1.15`)).toBeVisible()
    // toolbar Fill ↓ and confirm
    await page.getByRole("grid", { name: "Room prices by period" }).getByRole("columnheader").filter({ hasText: "P2" }).click({ position: { x: 60, y: 30 } })
    await toolbar(page).getByRole("button", { name: /Fill ↓/ }).click()
    await ask.getByRole("button", { name: "Set fixed price" }).click()
    for (const r of [N.SUP, N.DLX]) await expect(named(page, `${r} · P2: fixed price overriding the formula, 80.00`)).toBeVisible()
    await expect(toastOf(page)).toContainText("Applied to 2 cells")
    await expect(resolved(page, N.DLX, "P2", "80.00")).toBeVisible()

    // Garden Villa P3 ×1.2 filled down into ... the formula rows only: move Standard below Family Suite
    await page.getByRole("button", { name: `Room actions: ${N.STD}` }).click()
    await page.getByRole("menuitem", { name: "Move down" }).click()
    await cellOf(page, N.SUP, "P3").click()
    await page.keyboard.type("x1.2")
    await page.keyboard.press("Enter")
    await cellOf(page, N.SUP, "P3").click()
    await cellOf(page, N.STD, "P3").click({ modifiers: ["Shift"] })
    await page.keyboard.press("Control+d")
    await expect(page.getByRole("alert").filter({ hasText: `${N.STD} · P3: A formula is copied only into formula rows` })).toBeVisible()
    await expect(named(page, `${N.STD} · P3: entered price, 100.00`)).toBeVisible()
    // the period menu's "Select prices" selects the column from the keyboard
    await page.getByRole("button", { name: "Period actions: P4" }).click()
    await page.getByRole("menuitem", { name: "Select prices" }).click()
    await expect(grid(page).locator("[aria-selected='true']")).toHaveCount(3)
    await expect(cellOf(page, N.SUP, "P4")).toBeFocused()
    noErrors()
  })

  test("5. Russian layout: Ctrl + the keys marked Z and R (я, к) undo and fill; Advanced table edits are undone as their own entry, never lost", async ({ page }) => {
    const noErrors = trackErrors(page)
    await open(page)
    await cellOf(page, N.STD, "P1").click()
    await page.keyboard.type("72")
    await page.keyboard.press("Enter")
    await expect(named(page, `${N.STD} · P1: entered price, 72.00`)).toBeVisible()
    await cellOf(page, N.STD, "P1").click()
    const press = (key: string, code: string, shift = false) =>
      page.evaluate(
        ([k, c, s]) => {
          const el = document.activeElement as HTMLElement
          el.dispatchEvent(new KeyboardEvent("keydown", { key: k as string, code: c as string, ctrlKey: true, shiftKey: Boolean(s), bubbles: true, cancelable: true }))
        },
        [key, code, shift] as const,
      )
    await press("я", "KeyZ")
    await expect(named(page, `${N.STD} · P1: entered price, 70.00`)).toBeVisible()
    await press("Я", "KeyZ", true)
    await expect(named(page, `${N.STD} · P1: entered price, 72.00`)).toBeVisible()
    await selectRange(page, cellOf(page, N.STD, "P1"), 1)
    await press("к", "KeyR")
    await expect(named(page, `${N.STD} · P2: entered price, 72.00`)).toBeVisible()
    await press("я", "KeyZ")
    await expect(named(page, `${N.STD} · P2: entered price, 80.00`)).toBeVisible()

    // an Advanced table edit (Periods › Name, typed) after the matrix entry
    const periods = await openTab(page, "periods")
    const name = rowCell(periods, "Name", 1)
    await name.fill("")
    await name.pressSequentially("Spring", { delay: 30 })
    await openSection(page, "pricing")
    await expect(page.getByRole("grid", { name: "Room prices by period" }).getByRole("columnheader").filter({ hasText: "Spring" })).toBeVisible()
    const undo = toolbar(page).getByRole("button", { name: "Undo" })
    await undo.click()
    // the name typed in one burst is one entry, undone as such; the matrix entry is still there
    await expect(live(page, "Undone: Rule table: Periods")).toHaveCount(1)
    await expect(page.getByRole("grid", { name: "Room prices by period" }).getByRole("columnheader").filter({ hasText: "Apr" })).toBeVisible()
    await expect(named(page, `${N.STD} · P1: entered price, 72.00`)).toBeVisible()
    await undo.click()
    await expect(named(page, `${N.STD} · P1: entered price, 70.00`)).toBeVisible()
    await toolbar(page).getByRole("button", { name: "Redo" }).click()
    await toolbar(page).getByRole("button", { name: "Redo" }).click()
    await expect(page.getByRole("grid", { name: "Room prices by period" }).getByRole("columnheader").filter({ hasText: "Spring" })).toBeVisible()
    await expect(named(page, `${N.STD} · P1: entered price, 72.00`)).toBeVisible()
    noErrors()
  })

  test("6. Keyboard shortcuts popover; phones hide Fill and Adjust but keep Undo / Redo; Discard clears the history", async ({ page }) => {
    const noErrors = trackErrors(page)
    await open(page)
    await toolbar(page).getByRole("button", { name: "Keyboard shortcuts" }).click()
    const pop = page.getByRole("dialog", { name: "Keyboard shortcuts" })
    await expect(pop).toBeVisible()
    for (const [keys, what] of [
      ["Ctrl+R", "Fill right"],
      ["Ctrl+D", "Fill down"],
      ["Ctrl+Z", "Undo"],
      ["Ctrl+Shift+Z, Ctrl+Y", "Redo"],
      ["Ctrl+V", "Paste"],
    ])
      await expect(pop.getByRole("row", { name: new RegExp(`${keys.replace(/[+]/g, "\\+")}.*${what}`) })).toBeVisible()
    await page.keyboard.press("Escape")
    await expect(pop).toBeHidden()
    await expect(toolbar(page).getByRole("button", { name: "Keyboard shortcuts" })).toBeFocused()

    await cellOf(page, N.STD, "P1").click()
    await page.keyboard.type("71")
    await page.keyboard.press("Enter")
    await expect(toolbar(page).getByRole("button", { name: "Undo" })).toBeEnabled()
    await page.getByRole("button", { name: "Discard" }).click()
    const confirm = page.getByRole("dialog").filter({ hasText: /discard/i })
    if (await confirm.count()) await confirm.getByRole("button", { name: /Discard/ }).last().click()
    await expect(named(page, `${N.STD} · P1: entered price, 70.00`)).toBeVisible()
    await expect(toolbar(page).getByRole("button", { name: "Undo" })).toBeDisabled()

    await page.setViewportSize({ width: 375, height: 800 })
    await expect(toolbar(page).getByRole("button", { name: /Fill →/ })).toBeHidden()
    await expect(toolbar(page).getByRole("button", { name: "Adjust…" })).toBeHidden()
    await expect(toolbar(page).getByRole("button", { name: "Undo" })).toBeVisible()
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth)
    expect(overflow).toBeLessThanOrEqual(0)
    noErrors()
  })
})

test.describe("fill and copy take the rule a cell shows (review follow-up)", () => {
  test("R1. Family Suite P1 (follows ×1.15) filled down onto Garden Villa P1 (override ×1.5) gives ×1.15, not Garden Villa's ×1.35", async ({ page }) => {
    const noErrors = trackErrors(page)
    await open(page)
    await cellOf(page, N.DLX, "P1").click()
    await page.keyboard.type("x1.5")
    await page.keyboard.press("Enter")
    await expect(named(page, `${N.DLX} · P1: period override, ${N.STD} ×1.5`)).toBeVisible()
    await expect(resolved(page, N.DLX, "P1", "105.00")).toBeVisible()
    await expect(named(page, `${N.SUP} · P1: follows all periods, ${N.STD} ×1.15`)).toBeVisible()
    await cellOf(page, N.SUP, "P1").click()
    await cellOf(page, N.DLX, "P1").click({ modifiers: ["Shift"] })
    await page.keyboard.press("Control+d")
    await expect(named(page, `${N.DLX} · P1: period override, ${N.STD} ×1.15`)).toBeVisible()
    await expect(resolved(page, N.DLX, "P1", "80.50")).toBeVisible()
    await expect(toastOf(page)).toHaveText(/Applied to 1 cell/)
    await expect(toastOf(page)).not.toContainText("cleared")
    await page.keyboard.press("Control+z")
    await expect(named(page, `${N.DLX} · P1: period override, ${N.STD} ×1.5`)).toBeVisible()
    noErrors()
  })

  test("R2. The row header of Standard + Ctrl+R: the empty All periods clears P1–P4 and the toast says so; Ctrl+Z restores", async ({ page }) => {
    const noErrors = trackErrors(page)
    await open(page)
    await page.getByRole("rowheader").filter({ hasText: N.STD }).first().click({ position: { x: 12, y: 8 } })
    await expect(grid(page).locator("[aria-selected='true']")).toHaveCount(5)
    await page.keyboard.press("Control+r")
    await expect(toastOf(page)).toContainText("Applied to 4 cells · 4 cells cleared (copied from empty cells)")
    await expect(live(page, "Applied to 4 cells · 4 cells cleared (copied from empty cells)")).toHaveCount(1)
    await page.keyboard.press("Control+z")
    for (const [p, v] of [["P1", "70.00"], ["P4", "130.00"]]) await expect(named(page, `${N.STD} · ${p}: entered price, ${v}`)).toBeVisible()
    noErrors()
  })

  test("R3. Ctrl+C of following cells copies the rule they show; pasted onto Garden Villa it gives ×1.15", async ({ page, context }) => {
    const noErrors = trackErrors(page)
    await context.grantPermissions(["clipboard-read", "clipboard-write"])
    await open(page)
    const read = () => page.evaluate(() => navigator.clipboard.readText())
    await selectRange(page, cellOf(page, N.SUP, "P1"), 1)
    await page.keyboard.press("Control+c")
    await expect.poll(read).toBe("x1.15\tx1.15\n")
    await cellOf(page, N.DLX, "P1").click()
    await page.keyboard.press("Control+v")
    for (const p of ["P1", "P2"]) await expect(named(page, `${N.DLX} · ${p}: period override, ${N.STD} ×1.15`)).toBeVisible()
    await expect(resolved(page, N.DLX, "P1", "80.50")).toBeVisible()
    // pasted back onto Family Suite: nothing changes (they follow all periods as before)
    await cellOf(page, N.SUP, "P1").click()
    await page.keyboard.press("Control+v")
    for (const p of ["P1", "P2"]) await expect(named(page, `${N.SUP} · ${p}: follows all periods, ${N.STD} ×1.15`)).toBeVisible()
    noErrors()
  })
})

test.describe("copy and paste over resolved rows, editor keys, the toast's focus (second review follow-up)", () => {
  test("V1. Shift+ArrowDown from Standard P1 over Family Suite's resolved row to Garden Villa, Ctrl+C, Ctrl+V at Standard P2: each room gets its own row's text", async ({ page, context }) => {
    const noErrors = trackErrors(page)
    await context.grantPermissions(["clipboard-read", "clipboard-write"])
    await openManual(page)
    for (const [p, v] of [["P1", "90.00"], ["P2", "95.00"]]) await expect(named(page, `${N.DLX} · ${p}: entered price, ${v}`)).toBeVisible()
    await cellOf(page, N.STD, "P1").click()
    for (let i = 0; i < 3; i++) await page.keyboard.press("Shift+ArrowDown")
    // the range holds Standard, Family Suite, Family Suite's resolved row, Garden Villa: all four are
    // selected and shown (S16 review); the copy and the paste take the entry rows only
    await expect(grid(page).locator("[aria-selected='true']")).toHaveCount(4)
    await expect(resolved(page, N.SUP, "P1", "80.50")).toHaveAttribute("aria-selected", "true")
    await expect(focusedRole(page)).resolves.toMatch(/^gridcell:Garden Villa · P1: /)
    await page.keyboard.press("Control+c")
    await expect.poll(() => read(page)).toBe("70\nx1.15\n90\n")
    await cellOf(page, N.STD, "P2").click()
    await page.keyboard.press("Control+v")
    await expect(named(page, `${N.STD} · P2: entered price, 70.00`)).toBeVisible()
    await expect(named(page, `${N.SUP} · P2: follows all periods, ${N.STD} ×1.15`)).toBeVisible()
    await expect(named(page, `${N.DLX} · P2: entered price, 90.00`)).toBeVisible()
    await expect(resolved(page, N.SUP, "P2", "80.50")).toBeVisible()
    await expect(toastOf(page)).toContainText("Applied to 3 cells")
    // Garden Villa's other periods and Standard P3 are untouched
    await expect(named(page, `${N.DLX} · P3: entered price, 100.00`)).toBeVisible()
    await expect(named(page, `${N.STD} · P3: entered price, 100.00`)).toBeVisible()
    // Ctrl+Z puts P2 back
    await page.keyboard.press("Control+z")
    await expect(named(page, `${N.STD} · P2: entered price, 80.00`)).toBeVisible()
    await expect(named(page, `${N.DLX} · P2: entered price, 95.00`)).toBeVisible()
    noErrors()
  })

  test("V2. Shift+ArrowDown ×2 from Standard P1 (Standard, Family Suite, its resolved row) pasted at P3 never writes Garden Villa; resolved cells alone copy the server amounts", async ({ page, context }) => {
    const noErrors = trackErrors(page)
    await context.grantPermissions(["clipboard-read", "clipboard-write"])
    await openManual(page)
    await cellOf(page, N.STD, "P1").click()
    for (let i = 0; i < 2; i++) await page.keyboard.press("Shift+ArrowDown")
    await page.keyboard.press("Control+c")
    await expect.poll(() => read(page)).toBe("70\nx1.15\n")
    await cellOf(page, N.STD, "P3").click()
    await page.keyboard.press("Control+v")
    await expect(named(page, `${N.STD} · P3: entered price, 70.00`)).toBeVisible()
    await expect(named(page, `${N.DLX} · P3: entered price, 100.00`)).toBeVisible()
    await expect(toastOf(page)).toContainText("Applied to 2 cells")
    // Family Suite's resolved P1:P2 alone: the server's amounts; pasted onto Garden Villa P1 they are its prices
    await resolved(page, N.SUP, "P1", "80.50").click()
    await page.keyboard.press("Shift+ArrowRight")
    await page.keyboard.press("Control+c")
    await expect.poll(() => read(page)).toBe("80.5\t92\n")
    await cellOf(page, N.DLX, "P1").click()
    await page.keyboard.press("Control+v")
    await expect(named(page, `${N.DLX} · P1: entered price, 80.50`)).toBeVisible()
    await expect(named(page, `${N.DLX} · P2: entered price, 92.00`)).toBeVisible()
    noErrors()
  })

  test("V3. A copied empty cell pastes as a clear, not 'nothing to paste'", async ({ page, context }) => {
    const noErrors = trackErrors(page)
    await context.grantPermissions(["clipboard-read", "clipboard-write"])
    await openManual(page)
    // Family Suite's All periods holds ×1.15; Standard's All periods holds nothing
    await cellOf(page, N.STD, "All periods").click()
    await page.keyboard.press("Control+c")
    await expect.poll(() => read(page)).toBe("\n")
    await cellOf(page, N.DLX, "P4").click()
    await page.keyboard.press("Control+v")
    // a manual room's period without a rule has no price (the cell shows "—")
    await expect(grid(page).getByRole("gridcell", { name: /^Garden Villa · P4: no (rule|price)$/ })).toBeVisible()
    await expect(toastOf(page)).toHaveCount(0)
    noErrors()
  })

  test("V4. Ctrl+R and Ctrl+D in a cell editor are kept from the browser; Ctrl+Z is left to the field", async ({ page }) => {
    const noErrors = trackErrors(page)
    await openManual(page)
    await page.evaluate(() => {
      ;(window as unknown as { __dp: string[] }).__dp = []
      document.addEventListener("keydown", (e) => (window as unknown as { __dp: string[] }).__dp.push(`${e.ctrlKey ? "C+" : ""}${e.key}:${e.defaultPrevented}`))
    })
    await cellOf(page, N.STD, "P3").click()
    await page.keyboard.press("F2")
    const editor = grid(page).getByRole("textbox")
    await expect(editor).toBeFocused()
    await page.keyboard.press("Control+r")
    await page.keyboard.press("Control+d")
    await page.keyboard.press("Control+z")
    await expect(editor).toBeFocused()
    expect((await page.evaluate(() => (window as unknown as { __dp: string[] }).__dp)).filter((x) => x.startsWith("C+") && !x.startsWith("C+Control"))).toEqual(["C+r:true", "C+d:true", "C+z:false"])
    // no fill ran: Standard P4 is as it was
    await page.keyboard.press("Escape")
    await expect(named(page, `${N.STD} · P4: entered price, 130.00`)).toBeVisible()
    noErrors()
  })

  test("V5. The toast's Undo (keyboard and click) and close button give the focus back to the grid's active cell", async ({ page }) => {
    const noErrors = trackErrors(page)
    await openManual(page)
    const bulkClear = async () => {
      await cellOf(page, N.STD, "P1").click()
      await page.keyboard.press("Shift+ArrowRight")
      await page.keyboard.press("Delete")
      await expect(toastOf(page)).toContainText("Applied to 2 cells")
    }
    await bulkClear()
    await toastOf(page).getByRole("button", { name: "Undo" }).focus()
    await page.keyboard.press("Enter")
    await expect(toastOf(page)).toHaveCount(0)
    await expect(named(page, `${N.STD} · P1: entered price, 70.00`)).toBeVisible()
    await expect.poll(() => focusedRole(page)).toMatch(/^gridcell:Standard Sea View · P2: /)
    await bulkClear()
    await toastOf(page).getByRole("button", { name: "Undo" }).click()
    await expect(toastOf(page)).toHaveCount(0)
    await expect.poll(() => focusedRole(page)).toMatch(/^gridcell:Standard Sea View · P2: /)
    await page.keyboard.press("Control+z")
    await page.keyboard.press("Control+z")
    await expect(named(page, `${N.STD} · P1: entered price, 70.00`)).toBeVisible()
    await bulkClear()
    await toastOf(page).getByRole("button", { name: "Close" }).focus()
    await page.keyboard.press("Enter")
    await expect(toastOf(page)).toHaveCount(0)
    await expect.poll(() => focusedRole(page)).toMatch(/^gridcell:Standard Sea View · P2: /)
    noErrors()
  })
})
