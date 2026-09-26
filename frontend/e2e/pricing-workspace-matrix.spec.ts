// The room price matrix of the Pricing Workspace (PRICING_WORKSPACE_UX.md §3.3–§3.5, §3.9; slice
// S9): typed prices and formulas priced by the server before any save, the override glyph, a bulk
// Ctrl+Enter, the parser's refusals and the AMBIGUOUS guard, a relative entry on the base room
// adjusted once by the server, a formula over a fixed price, the rename cascade, the rule popover
// and the cell menu, rooms and periods, Delete, and a read-only published version.
// One draft (API-made, empty prices) is shared by the tests, in order.
import { expect, test, type Locator, type Page } from "@playwright/test"
import { api, login, trackErrors } from "./helpers"
import { priceMatrix } from "./flows/contracts"
import { pickFrom } from "./flows/budget"
import { archiveAll, DLX, N, newContract, newDraft, ownerDraft, periods, publish, readVersion, STD, SUP, versionPath, watchContracts, Y, type NewContract } from "./flows/workspace"

test.use({ locale: "en-US", actionTimeout: 15_000, navigationTimeout: 30_000 })

const made: string[] = []
let draft: NewContract

/** The editable (non-resolved) cell of a room in a period. */
const cellOf = (page: Page, room: string, period: string) =>
  priceMatrix(page)
    .getByRole("gridcell", { name: new RegExp(`^${room} · ${period}: (?!resolved)`) })
    .first()
const named = (page: Page, name: string) => priceMatrix(page).getByRole("gridcell", { name, exact: true })
const resolved = (page: Page, room: string, period: string, amount: string) => named(page, `${room} · ${period}: resolved price, EUR ${amount}`)
const editor = (page: Page, room: string, period: string) => priceMatrix(page).getByRole("textbox", { name: `Price: ${room} · ${period}`, exact: true })

async function typeInto(page: Page, cell: Locator, text: string) {
  await cell.click()
  await expect(cell).toBeFocused()
  await page.keyboard.type(text)
}

test.describe.serial("room price matrix", () => {
  test.beforeAll(async ({ browser }) => {
    const page = await browser.newPage()
    await login(page, "revenue@demo.tex")
    draft = await newContract(page, { prefix: "E2E-PWX" })
    made.push(draft.contract)
    await api(page.request, "kamra.tex.api.contracts.save_version", {
      name: draft.version,
      data: {
        rooms: [
          { room_type: STD, is_base: 1 },
          { room_type: SUP, is_base: 0 },
          { room_type: DLX, is_base: 0 },
        ],
        periods: periods(),
        boards: [{ board: "BB", is_base: 1, op: "ADD", adult_amount: null, child_percent: "50", infant_free: 1 }],
      },
    })
    await page.close()
  })
  test.afterAll(async ({ browser }) => archiveAll(browser, made, "pricing workspace matrix e2e clean-up"))

  test("typed prices and formulas give the server's resolved rows before any save; P4 override; Ctrl+Enter over a selection", async ({ page }) => {
    const noErrors = trackErrors(page)
    await login(page, "revenue@demo.tex")
    const net = watchContracts(page)
    await page.goto(versionPath(draft, "#pricing"))
    await expect(priceMatrix(page)).toBeVisible()
    await expect(priceMatrix(page)).toHaveAttribute("aria-multiselectable", "true")

    // 70⇥80⇥100⇥130↵ on the base row
    await typeInto(page, cellOf(page, N.STD, "P1"), "70")
    await expect(editor(page, N.STD, "P1")).toBeVisible()
    await expect(page.getByRole("status").filter({ hasText: `${N.STD} · P1 = 70.00` })).toBeVisible()
    await page.keyboard.press("Tab")
    await expect(cellOf(page, N.STD, "P2")).toBeFocused()
    await page.keyboard.type("80")
    await page.keyboard.press("Tab")
    await page.keyboard.type("100")
    await page.keyboard.press("Tab")
    await page.keyboard.type("130")
    await page.keyboard.press("Enter")
    for (const [p, v] of [["P1", "70.00"], ["P2", "80.00"], ["P3", "100.00"], ["P4", "130.00"]]) await expect(named(page, `${N.STD} · ${p}: entered price, ${v}`)).toBeVisible()

    // Superior All periods x1.15, Deluxe x1.35
    await typeInto(page, cellOf(page, N.SUP, "All periods"), "x1.15")
    await expect(page.getByRole("status").filter({ hasText: `${N.SUP} · All periods = ${N.STD} ×1.15` })).toBeVisible()
    await page.keyboard.press("Enter")
    await typeInto(page, cellOf(page, N.DLX, "All periods"), "x1.35")
    await page.keyboard.press("Enter")
    for (const [p, v] of [["P1", "80.50"], ["P2", "92.00"], ["P3", "115.00"], ["P4", "149.50"]]) await expect(resolved(page, N.SUP, p, v)).toBeVisible()
    for (const [p, v] of [["P1", "94.50"], ["P2", "108.00"], ["P3", "135.00"], ["P4", "175.50"]]) await expect(resolved(page, N.DLX, p, v)).toBeVisible()
    expect(net.count("save_version"), "nothing is saved").toBe(0)
    await expect(page.getByRole("button", { name: /^Save/ })).toBeEnabled()

    // P4 x1.20: the override glyph
    await typeInto(page, cellOf(page, N.SUP, "P4"), "x1.20")
    await page.keyboard.press("Enter")
    const p4 = named(page, `${N.SUP} · P4: period override, ${N.STD} ×1.2`)
    await expect(p4).toContainText("◆ ×1.2")
    await expect(resolved(page, N.SUP, "P4", "156.00")).toBeVisible()

    // select Deluxe P3:P4, x1.40 + Ctrl+Enter: one gesture
    await cellOf(page, N.DLX, "P3").click()
    await page.keyboard.press("Shift+ArrowRight")
    await expect(cellOf(page, N.DLX, "P4")).toHaveAttribute("aria-selected", "true")
    await page.keyboard.type("x1.40")
    await page.keyboard.press("Control+Enter")
    for (const p of ["P3", "P4"]) await expect(named(page, `${N.DLX} · ${p}: period override, ${N.STD} ×1.4`)).toBeVisible()
    for (const [p, v] of [["P1", "94.50"], ["P2", "108.00"], ["P3", "140.00"], ["P4", "182.00"]]) await expect(resolved(page, N.DLX, p, v)).toBeVisible()
    expect(net.count("save_version")).toBe(0)
    noErrors()
  })

  test("Escape reverts; 'abc' and '1.500' are refused with their messages; an invalid entry stays as an error draft", async ({ page }) => {
    const noErrors = trackErrors(page)
    await login(page, "revenue@demo.tex")
    await page.goto(versionPath(draft, "#pricing"))
    await typeInto(page, cellOf(page, N.STD, "P1"), "70")
    await page.keyboard.press("Enter")
    await typeInto(page, cellOf(page, N.STD, "P1"), "999")
    await page.keyboard.press("Escape")
    await expect(editor(page, N.STD, "P1")).toHaveCount(0)
    await expect(named(page, `${N.STD} · P1: entered price, 70.00`)).toBeFocused()

    await typeInto(page, cellOf(page, N.SUP, "P2"), "abc")
    await page.keyboard.press("Enter")
    await expect(editor(page, N.SUP, "P2")).toHaveAttribute("aria-invalid", "true")
    await expect(page.getByRole("status").filter({ hasText: "Not a price or formula" })).toBeVisible()
    await page.keyboard.press("Escape")

    await page.keyboard.type("1.500")
    await expect(page.getByRole("status").filter({ hasText: "Is this 1500 or 1.5? Type 1500 for one thousand five hundred, or 1.5 for one and a half." })).toBeVisible()
    await page.keyboard.press("Enter")
    await expect(editor(page, N.SUP, "P2")).toHaveAttribute("aria-invalid", "true")
    // leaving the cell keeps the entry as an error draft, never lost
    await cellOf(page, N.DLX, "P1").click()
    const errorDraft = named(page, `${N.SUP} · P2: entry not kept, with an error, 1.500`)
    await expect(errorDraft).toHaveAttribute("aria-invalid", "true")
    await errorDraft.click()
    await page.keyboard.press("Escape")
    await expect(priceMatrix(page).getByRole("gridcell", { name: /^Family Suite · P2: no price$/ })).toBeVisible()
    noErrors()
  })

  test("+10% on the base P1 becomes 77.00 through apply_op_values; a base and a formula cell in one Ctrl+Enter make one call", async ({ page }) => {
    const noErrors = trackErrors(page)
    await login(page, "revenue@demo.tex")
    const net = watchContracts(page)
    await page.goto(versionPath(draft, "#pricing"))
    await typeInto(page, cellOf(page, N.STD, "P1"), "70")
    await page.keyboard.press("Enter")
    await typeInto(page, cellOf(page, N.STD, "P1"), "+10%")
    await expect(page.getByRole("status").filter({ hasText: `${N.STD} · P1: adjust 70.00 by +10% (calculated on commit)` })).toBeVisible()
    const answered = page.waitForResponse((r) => r.url().includes("contracts.apply_op_values"))
    await page.keyboard.press("Enter")
    const res = await answered
    expect(res.ok()).toBeTruthy()
    expect(res.request().postDataJSON()).toMatchObject({ values: ["70"], op: "ADJUST_PERCENT", value: "10" })
    await expect(named(page, `${N.STD} · P1: entered price, 77.00`)).toBeVisible()

    // Ctrl+Click adds Garden Villa P1 to Standard P1; +5 on both: one apply_op_values call
    await typeInto(page, cellOf(page, N.DLX, "All periods"), "x1.35")
    await page.keyboard.press("Enter")
    net.reset()
    await cellOf(page, N.STD, "P1").click()
    await cellOf(page, N.DLX, "P1").click({ modifiers: ["Control"] })
    const second = page.waitForResponse((r) => r.url().includes("contracts.apply_op_values"))
    await page.keyboard.type("+5")
    await page.keyboard.press("Control+Enter")
    expect((await second).request().postDataJSON()).toMatchObject({ values: ["77.00"], op: "ADD", value: "5" })
    await expect(named(page, `${N.STD} · P1: entered price, 82.00`)).toBeVisible()
    await expect(named(page, `${N.DLX} · P1: period override, ${N.STD} +5`)).toBeVisible()
    expect(net.count("apply_op_values")).toBe(1)
    noErrors()
  })

  test("SUP P2 =245 then x1.20 restores a formula; renaming P2 → MAY rewrites its rules (get_version after save)", async ({ page }) => {
    const noErrors = trackErrors(page)
    await login(page, "revenue@demo.tex")
    await page.goto(versionPath(draft, "#pricing"))
    await typeInto(page, cellOf(page, N.STD, "P2"), "80")
    await page.keyboard.press("Enter")
    await typeInto(page, cellOf(page, N.SUP, "All periods"), "x1.15")
    await page.keyboard.press("Enter")
    await typeInto(page, cellOf(page, N.SUP, "P2"), "=245")
    await page.keyboard.press("Enter")
    await expect(named(page, `${N.SUP} · P2: fixed price overriding the formula, 245.00`)).toBeVisible()
    await expect(resolved(page, N.SUP, "P2", "245.00")).toBeVisible()
    await typeInto(page, cellOf(page, N.SUP, "P2"), "x1.20")
    await expect(page.getByRole("status").filter({ hasText: `${N.SUP} · P2 = ${N.STD} ×1.2 (replaces the fixed price 245.00)` })).toBeVisible()
    await page.keyboard.press("Enter")
    await expect(resolved(page, N.SUP, "P2", "96.00")).toBeVisible()

    // rename P2 → MAY through the period menu
    await page.getByRole("button", { name: "Period actions: P2" }).click()
    await page.getByRole("menuitem", { name: "Rename…" }).click()
    const dlg = page.getByRole("dialog", { name: "Rename P2" })
    await expect(dlg).toBeVisible()
    await expect(page.locator("[aria-modal='true']")).toHaveCount(0)
    await dlg.getByLabel(/^Code/).fill("MAY")
    await dlg.getByRole("button", { name: "Apply" }).click()
    await expect(page.getByRole("button", { name: "Period actions: MAY" })).toBeVisible()
    await expect(resolved(page, N.SUP, "MAY", "96.00")).toBeVisible()

    const saved = page.waitForResponse((r) => r.url().includes("contracts.save_version"))
    await page.getByRole("button", { name: /^Save/ }).click()
    expect((await saved).ok()).toBeTruthy()
    const v = await readVersion(page, draft.version)
    expect(v.periods.map((p) => p.period_code)).toEqual(["P1", "MAY", "P3", "P4"])
    const supMay = v.period_rates.filter((r) => r.room_type === SUP && r.period_code === "MAY")
    expect(supMay.map((r) => [r.op, r.value, r.base_room_type])).toEqual([["MULTIPLY", "1.2", STD]])
    expect(v.period_rates.some((r) => r.period_code === "P2")).toBeFalsy()
    noErrors()
  })

  test("the rule popover: Alt+Enter opens 'Edit price: …', the op chosen is stored; Shift+F10 opens the cell menu, whose Edit rule… opens it too", async ({ page }) => {
    const noErrors = trackErrors(page)
    await login(page, "revenue@demo.tex")
    await page.goto(versionPath(draft, "#pricing"))
    const cell = cellOf(page, N.DLX, "P3")
    await cell.click()
    await page.keyboard.press("Alt+Enter")
    const pop = page.getByRole("dialog", { name: `Edit price: ${N.DLX} · P3` })
    await expect(pop).toBeVisible()
    await expect(page.locator("[aria-modal='true']")).toHaveCount(0)
    await pop.getByLabel(/^Rule/).selectOption("PERCENT_OF")
    await pop.getByLabel(/^Value/).fill("120")
    await pop.getByRole("button", { name: "Apply" }).click()
    await expect(pop).toBeHidden()
    await expect(named(page, `${N.DLX} · P3: period override, 120% of ${N.STD}`)).toBeFocused()
    // Shift+F10 opens the cell's menu (S14): "Edit rule…" first, then "Test this price"; Enter opens
    // the popover; Escape closes it and focus returns
    await page.keyboard.press("Shift+F10")
    const menu = page.getByRole("menu", { name: `Cell actions: ${N.DLX} · P3` })
    await expect(menu).toBeVisible()
    await expect(menu.getByRole("menuitem")).toHaveText(["Edit rule…Alt+↵", "Test this price"])
    await expect(page.getByRole("menuitem", { name: "Edit rule…" })).toBeFocused()
    await page.keyboard.press("Enter")
    await expect(menu).toBeHidden()
    await expect(pop).toBeVisible()
    await page.keyboard.press("Escape")
    await expect(pop).toBeHidden()
    await expect(named(page, `${N.DLX} · P3: period override, 120% of ${N.STD}`)).toBeFocused()
    noErrors()
  })

  test("rooms and periods: + Period with the end date, Add room, Remove with counts", async ({ page }) => {
    const noErrors = trackErrors(page)
    await login(page, "revenue@demo.tex")
    await page.goto(versionPath(draft, "#pricing"))
    await page.getByRole("button", { name: "Add period" }).click()
    const end = page.getByLabel("End date: P5")
    await expect(end).toBeFocused()
    await expect(end).toHaveValue(`${Y}-08-31`)
    await end.fill(`${Y}-08-15`)
    await end.press("Enter")
    await expect(page.getByRole("button", { name: "Period actions: P5" })).toBeVisible()
    await page.getByRole("button", { name: `Room actions: ${N.DLX}` }).click()
    await page.getByRole("menuitem", { name: "Remove room" }).click()
    const rm = page.getByRole("dialog", { name: `Remove ${N.DLX}?` })
    await expect(rm).toBeVisible()
    await rm.getByRole("button", { name: "Remove room" }).click()
    await expect(page.getByRole("button", { name: `Room actions: ${N.DLX}` })).toHaveCount(0)
    await pickFrom(page.getByRole("button", { name: "Add room", exact: true }), N.DLX)
    await expect(page.getByRole("button", { name: `Room actions: ${N.DLX}` })).toBeVisible()
    noErrors()
  })

  test("Delete clears the selected cells in one gesture, also after Ctrl+A kept the active cell", async ({ page }) => {
    const noErrors = trackErrors(page)
    await login(page, "revenue@demo.tex")
    await page.goto(versionPath(draft, "#pricing"))
    await typeInto(page, cellOf(page, N.STD, "P1"), "70")
    for (const v of ["80", "100", "130"]) {
      await page.keyboard.press("Tab")
      await page.keyboard.type(v)
    }
    await page.keyboard.press("Enter")
    // P2 was renamed MAY and saved by an earlier test
    await cellOf(page, N.STD, "MAY").click()
    await page.keyboard.press("Shift+ArrowRight")
    await page.keyboard.press("Delete")
    await expect(named(page, `${N.STD} · MAY: no price`)).toBeVisible()
    await expect(named(page, `${N.STD} · P3: no price`)).toBeVisible()
    await expect(named(page, `${N.STD} · P4: entered price, 130.00`)).toBeVisible()
    // Ctrl+A keeps the active cell (P3, selected) and selects every editable cell: Delete clears them all
    await page.keyboard.press("Control+a")
    await expect(cellOf(page, N.STD, "P4")).toHaveAttribute("aria-selected", "true")
    await page.keyboard.press("Delete")
    await expect(named(page, `${N.STD} · P4: no price`)).toBeVisible()
    await expect(named(page, `${N.STD} · P1: no price`)).toBeVisible()
    noErrors()
  })

  test("a published version is read-only: aria-readonly, no textbox, no Edit price: triggers, no mutating menus", async ({ page }) => {
    const noErrors = trackErrors(page)
    await login(page, "revenue@demo.tex")
    const pub = await newDraft(page, "E2E-PWXP", ownerDraft())
    made.push(pub.contract)
    await publish(page, pub.version)
    await page.goto(versionPath(pub, "#pricing"))
    await expect(priceMatrix(page)).toHaveAttribute("aria-readonly", "true")
    await expect(priceMatrix(page).getByRole("gridcell").first()).toBeVisible()
    await priceMatrix(page).getByRole("gridcell").first().click()
    await page.keyboard.type("5")
    await page.keyboard.press("Enter")
    await expect(priceMatrix(page).getByRole("textbox")).toHaveCount(0)
    await expect(page.getByRole("button", { name: /^Edit price:/ })).toHaveCount(0)
    await expect(page.getByRole("button", { name: /^Room actions:|^Period actions:|^Add period$/ })).toHaveCount(0)
    await expect(page.getByRole("button", { name: "Add room", exact: true })).toHaveCount(0)
    await expect(resolved(page, N.SUP, "P1", "80.50")).toBeVisible()
    noErrors()
  })
})
