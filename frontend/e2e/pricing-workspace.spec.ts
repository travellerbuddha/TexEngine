// The Pricing Workspace acceptance (PRICING_WORKSPACE_UX.md §5.3): the owner's 13-step ORS-style
// contract entered in the workspace of one draft, with no section switch, no modal dialog and no
// save before the price is checked, within 50 clicks. The contract is made through the API with
// the ROOM basis, so step 1 chooses PERSON in the UI. Family Suite and Garden Villa stand for the
// design's "Superior" and "Deluxe" (the demo hotel's rooms). Every amount on screen comes from the
// server: the spec compares the Explain ladder with the preview_price answer it observed.
//   TEX_E2E_BASE=http://test.localhost:8000 TEX_E2E_PASSWORD=… npx playwright test -c e2e pricing-workspace
import { expect, test, type Locator, type Page, type Response } from "@playwright/test"
import { answerOf, login, pageApiOk, trackErrors } from "./helpers"
import { Budget, choose, pickFrom } from "./flows/budget"
import { addPeriod, addRooms, boardsGrid, ladderCell, occupancyLadder, priceCell, priceMatrix, saveDraft, setBasis } from "./flows/contracts"
import { archiveAll, DLX, N, newContract, newDraft, openVersion, ownerDraft, readVersion, STD, SUP, twoDecimals, versionPath, watchContracts, Y } from "./flows/workspace"

test.use({ locale: "en-US", actionTimeout: 15_000, navigationTimeout: 30_000 })

const made: string[] = []
test.afterAll(async ({ browser }) => archiveAll(browser, made, "pricing workspace e2e clean-up"))

/** A matrix cell by its full accessible name ("{room} · {period}: {state}, {value}"). */
const named = (page: Page, name: string) => priceMatrix(page).getByRole("gridcell", { name, exact: true })
const resolved = (page: Page, room: string, period: string, amount: string) => named(page, `${room} · ${period}: resolved price, EUR ${amount}`)
/** What a ladder cell shows (its content, not its tooltip). */
const shown = (cell: Locator) => cell.locator(":scope > span").first()
/** An Explain ladder row: [row header's first line, before, after]. */
async function stageRow(table: Locator, stage: RegExp): Promise<string[]> {
  const row = table.getByRole("row").filter({ has: table.page().getByRole("rowheader", { name: stage }) }).first()
  await expect(row).toBeVisible()
  const cells = row.getByRole("cell")
  const n = await cells.count()
  const header = (await row.getByRole("rowheader").innerText()).split("\n")[0].trim()
  return [header, ...(await Promise.all(Array.from({ length: n }, (_, i) => cells.nth(i).innerText()))).map((s) => s.trim())]
}

test("the 13 steps of an ORS-style contract in one workspace: ≤ 50 clicks, no section switch, no modal dialog, no save before the price test", async ({ page }, testInfo) => {
  test.setTimeout(300_000)
  const noErrors = trackErrors(page)
  await login(page, "revenue@demo.tex")
  const d = await newContract(page, { prefix: "E2E-PW", basis: "ROOM" })
  made.push(d.contract)
  const calls = watchContracts(page)
  const budget = await Budget.attach(page)
  await page.goto(versionPath(d))
  const matrix = priceMatrix(page)
  await expect(matrix).toBeVisible()
  const save = page.getByRole("button", { name: /^Save/ })
  await expect(save).toBeDisabled()
  budget.start()

  await test.step("1. PERSON pricing, chosen in the workspace's basis popover", async () => {
    await expect(page.getByRole("button", { name: "Pricing basis: Per room", exact: true })).toBeVisible()
    await setBasis(page, "PERSON", budget)
    await expect(page.getByRole("button", { name: "Pricing basis: Per person", exact: true })).toBeVisible()
    await expect(page.getByText("Base person rate per night · EUR", { exact: true })).toBeVisible()
    const c = await pageApiOk<{ contract: { pricing_basis: string } }>(page, "kamra.tex.api.contracts.get_contract", { name: d.contract })
    expect(c.contract.pricing_basis).toBe("PERSON")
    // the header was saved on its own: the draft is still clean, and nothing modal opened
    await expect(save).toBeDisabled()
    expect((await budget.counts()).modals).toBe(0)
  })

  await test.step("2. Standard (the base room), Superior and Deluxe", async () => {
    await addRooms(page, [{ room: N.STD }, { room: N.SUP }, { room: N.DLX }], { budget, save: false })
    const std = page.getByRole("rowheader").filter({ has: page.getByRole("button", { name: `Room actions: ${N.STD}` }) })
    await expect(std).toContainText("BASE")
    await expect(std).toContainText("Base person price")
  })

  await test.step("3. four stay periods, April to July", async () => {
    const months = [
      ["P1", "04-01", "04-30"],
      ["P2", "05-01", "05-31"],
      ["P3", "06-01", "06-30"],
      ["P4", "07-01", "07-31"],
    ]
    for (const [code, from, to] of months) await addPeriod(page, { code, from: `${Y}-${from}`, to: `${Y}-${to}` }, { budget, save: false })
    for (const [code] of months) await expect(page.getByRole("button", { name: `Period actions: ${code}`, exact: true })).toBeVisible()
  })

  await test.step("4. the base person price for the four periods: 70⇥80⇥100⇥130↵", async () => {
    await priceCell(page, N.STD, "P1").click()
    await page.keyboard.type("70")
    for (const v of ["80", "100", "130"]) {
      await page.keyboard.press("Tab")
      await page.keyboard.type(v)
    }
    await page.keyboard.press("Enter")
    for (const [p, v] of [["P1", "70.00"], ["P2", "80.00"], ["P3", "100.00"], ["P4", "130.00"]])
      await expect(named(page, `${N.STD} · ${p}: entered price, ${v}`)).toBeVisible()
  })

  await test.step("5. Superior = base × 1.15, P4 × 1.20 (an override)", async () => {
    await priceCell(page, N.SUP).click()
    await page.keyboard.type("x1.15")
    await page.keyboard.press("Enter")
    await priceCell(page, N.SUP, "P4").click()
    await page.keyboard.type("x1.20")
    await page.keyboard.press("Enter")
    const p4 = named(page, `${N.SUP} · P4: period override, ${N.STD} ×1.2`)
    await expect(p4).toBeVisible()
    await expect(p4).toContainText("◆ ×1.2")
    await expect(named(page, `${N.SUP} · P2: follows all periods, ${N.STD} ×1.15`)).toBeVisible()
  })

  await test.step("6. Deluxe = base × 1.35, P3–P4 × 1.40 in one bulk entry; the resolved rows", async () => {
    await priceCell(page, N.DLX).click()
    await page.keyboard.type("x1.35")
    await page.keyboard.press("Enter")
    await priceCell(page, N.DLX, "P3").click()
    await priceCell(page, N.DLX, "P4").click({ modifiers: ["Shift"] })
    await expect(priceCell(page, N.DLX, "P4")).toHaveAttribute("aria-selected", "true")
    await page.keyboard.type("x1.40")
    await page.keyboard.press("Control+Enter")
    for (const p of ["P3", "P4"]) await expect(named(page, `${N.DLX} · ${p}: period override, ${N.STD} ×1.4`)).toBeVisible()
    for (const [p, v] of [["P1", "80.50"], ["P2", "92.00"], ["P3", "115.00"], ["P4", "156.00"]]) await expect(resolved(page, N.SUP, p, v)).toBeVisible()
    for (const [p, v] of [["P1", "94.50"], ["P2", "108.00"], ["P3", "140.00"], ["P4", "182.00"]]) await expect(resolved(page, N.DLX, p, v)).toBeVisible()
  })

  await test.step("7. the 3rd adult × 0.70; the 4th adult shows the engine's default ×1.00", async () => {
    await expect(occupancyLadder(page)).toBeVisible()
    await expect(page.getByRole("button", { name: "Occupancy & child pricing", exact: true })).toHaveAttribute("aria-expanded", "true")
    await ladderCell(page, "3rd adult").click()
    await page.keyboard.type("x0.70")
    await expect(page.getByRole("status").filter({ hasText: "3rd adult · All periods pays ×0.70 of the base person price" })).toBeVisible()
    await page.keyboard.press("Enter")
    await expect(shown(ladderCell(page, "3rd adult"))).toHaveText("×0.70")
    await expect(shown(ladderCell(page, "4th adult"))).toHaveText("×1.00 default")
    await expect(shown(ladderCell(page, "4th adult", "P3"))).toHaveText("×1.00 default")
  })

  await test.step("8. child bands 0–2.99 / 3–6.99 / 7–11.99 in the child ages drawer: labels, never codes", async () => {
    await page.getByRole("button", { name: "Child ages…", exact: true }).click()
    const drawer = page.getByRole("dialog", { name: "Child age bands", exact: true })
    await expect(drawer).toBeVisible()
    await drawer.getByRole("button", { name: "Add age band", exact: true }).click()
    for (const to of ["2.99", "6.99", "11.99"]) {
      await expect(drawer.getByLabel("Up to (not incl.) age: new band", { exact: true })).toBeFocused()
      await page.keyboard.type(to)
      await page.keyboard.press("Enter")
    }
    await expect(drawer.getByLabel("Label: Infant 0–2.99", { exact: true })).toHaveValue("Infant 0–2.99")
    await expect(drawer.getByRole("switch", { name: "Infant band: Infant 0–2.99" })).toBeChecked()
    await expect(drawer.getByLabel("Label: Child 3–6.99", { exact: true })).toHaveValue("Child 3–6.99")
    await expect(drawer.getByLabel("Label: Child 7–11.99", { exact: true })).toHaveValue("Child 7–11.99")
    await expect(drawer).toContainText("No gaps or overlaps")
    // Escape closes the drawer (the empty band Enter started is dropped)
    await page.keyboard.press("Escape")
    await expect(drawer).toBeHidden()
    for (const band of ["Infant 0–2.99", "Child 3–6.99", "Child 7–11.99"]) await expect(shown(ladderCell(page, band, "P1"))).toHaveText("No rule · not sellable")
    await expect(page.getByText(/\b(INF|CHA|CHB)\b/)).toHaveCount(0)
  })

  await test.step("9. the bands × 0 / × 0.25 / × 0.50, Enter moving down", async () => {
    await ladderCell(page, "Infant 0–2.99").click()
    await page.keyboard.type("x0")
    await page.keyboard.press("Enter")
    await expect(ladderCell(page, "Child 3–6.99")).toBeFocused()
    await page.keyboard.type("x0.25")
    await page.keyboard.press("Enter")
    await expect(ladderCell(page, "Child 7–11.99")).toBeFocused()
    await page.keyboard.type("x0.5")
    await page.keyboard.press("Enter")
    await expect(shown(ladderCell(page, "Infant 0–2.99"))).toHaveText("×0.00")
    await expect(shown(ladderCell(page, "Child 3–6.99"))).toHaveText("×0.25")
    await expect(shown(ladderCell(page, "Child 7–11.99"))).toHaveText("×0.50")
    await expect(page.getByText(/\b(INF|CHA|CHB)\b/)).toHaveCount(0)
  })

  await test.step("10. 2A+2C in the structured builder: child 1 (7–11.99) × 0.50, child 2 (3–6.99) × 0.25", async () => {
    const combos = page.getByRole("region", { name: /^Special combinations/ })
    await combos.getByRole("button", { name: "Add combination", exact: true }).click()
    const b = page.getByRole("group", { name: "New special combination" })
    await expect(b).toBeVisible()
    await b.getByRole("button", { name: "2A+2C", exact: true }).click()
    await expect(b.getByRole("button", { name: "2A+2C", exact: true })).toHaveAttribute("aria-pressed", "true")
    await choose(budget, b.getByLabel("Age band: Child 1 (oldest)"), { label: "Child 7–11.99" })
    await budget.fill(b.getByLabel("Value: Child 1 (oldest)"), "x0.5")
    await choose(budget, b.getByLabel("Age band: Child 2 (youngest)"), { label: "Child 3–6.99" })
    await budget.fill(b.getByLabel("Value: Child 2 (youngest)"), "x0.25")
    await expect(b).toContainText("Reads: 2 Adults + 2 Children → Child 1 ×0.50 · Child 2 ×0.25")
    await b.getByRole("button", { name: "Save combination", exact: true }).click()
    await expect(b).toHaveCount(0)
    const card = page.locator('[data-card][data-combination="2+2"]')
    await expect(card.locator("p").first()).toHaveText("2 Adults + 2 Children → Child 1 ×0.50 · Child 2 ×0.25")
    await expect(card.locator("p").nth(1)).toHaveText("Child 1: Child 7–11.99 · Child 2: Child 3–6.99 · All rooms · All periods")
    await expect(page.getByText(/\b(INF|CHA|CHB)\b/)).toHaveCount(0)
  })

  await test.step("11. the 3rd adult × 0.80 in P4 (an override)", async () => {
    await ladderCell(page, "3rd adult", "P4").click()
    await page.keyboard.type("x0.80")
    await page.keyboard.press("Enter")
    await expect(shown(ladderCell(page, "3rd adult", "P4"))).toHaveText(/^◆ ×0\.80\s*OVERRIDE$/)
    await expect(ladderCell(page, "3rd adult", "P4")).toHaveAttribute("aria-label", /3rd adult · P4: period override, ×0\.80/)
    await expect(shown(ladderCell(page, "3rd adult", "P2"))).toHaveText("↳ ×0.70")
  })

  await test.step("the base board BB, included", async () => {
    const boards = page.getByRole("region", { name: "Boards", exact: true })
    await expect(boards.getByRole("button", { name: "Boards", exact: true })).toHaveAttribute("aria-expanded", "true")
    await pickFrom(boards.getByRole("button", { name: "Add board", exact: true }), "BB")
    await expect(boardsGrid(page).getByRole("gridcell", { name: /^Bed & breakfast · All periods: base board, included/ })).toBeVisible()
  })

  let quote: { nights: Record<string, string>[] } = { nights: [] }
  const drawer = page.getByRole("dialog", { name: "Price test", exact: true })
  await test.step("12. Price test: Deluxe, 2 adults + a child of 8, 3 nights in P2, with no save; the ladder shows served values only", async () => {
    // "Test this price" on Deluxe's resolved P2 cell: the drawer starts there
    await priceMatrix(page).getByRole("gridcell", { name: `${N.DLX} · P2: resolved price, EUR 108.00`, exact: true }).click({ button: "right" })
    await page.getByRole("menu", { name: `Cell actions: ${N.DLX} · P2` }).getByRole("menuitem", { name: "Test this price" }).click()
    await expect(drawer).toBeVisible()
    expect(await drawer.getAttribute("aria-modal")).toBeNull()
    await expect(drawer.getByLabel(/^Room type/)).toHaveValue(DLX)
    await expect(drawer.getByLabel(/^Check-in/)).toHaveValue(`${Y}-05-01`)
    await expect(drawer.getByLabel(/^Check-out/)).toHaveValue(`${Y}-05-04`)
    await expect(drawer.getByLabel(/^Board/)).toHaveValue("BB")
    await expect(drawer.getByLabel(/^Adults/)).toHaveValue("2")
    await expect(drawer.getByText("Priced with your unsaved changes.")).toBeVisible()
    await drawer.getByRole("button", { name: "Add child", exact: true }).click()
    await budget.fill(drawer.getByLabel("Age of child 1", { exact: true }), "8")
    const answered: Promise<Response> = answerOf(page, "kamra.tex.api.contracts.preview_price")
    await drawer.getByRole("button", { name: /^Calculate/ }).click()
    const res = await answered
    expect(res.ok()).toBeTruthy()
    quote = ((await res.json()) as { message: typeof quote }).message
    // one group for the three identical nights
    const ladderTable = drawer.getByRole("table", { name: /^Nights 1–3 · P2/ })
    await expect(ladderTable).toBeVisible()
    await expect(drawer.getByRole("table", { name: /^Night \d/ })).toHaveCount(0)
    expect(await stageRow(ladderTable, /^Base price/)).toEqual(["Base price", "", "80.00"])
    const period = await stageRow(ladderTable, /^Period/)
    expect(period[1]).toBe("no amount (period used to choose rules)")
    await expect(ladderTable.getByRole("rowheader", { name: /^Period/ }).first()).toContainText("P2")
    expect(await stageRow(ladderTable, /^Room/)).toEqual(["Room", "80.00", "108.00"])
    expect(await stageRow(ladderTable, /^Occupancy \(adults\)/)).toEqual(["Occupancy (adults)", "108.00", "216.00"])
    // the design's stage "Child" is labelled "Children" on screen
    const child = await stageRow(ladderTable, /^Child(ren)?\b/)
    expect(child.slice(1)).toEqual(["216.00", "270.00"])
    await expect(ladderTable.locator('tr[data-line="CHILD_SLOT"]')).toContainText("54.00")
    expect(await stageRow(ladderTable, /^Board/)).toEqual(["Board", "270.00", "270.00"])
    await expect(ladderTable.getByRole("rowheader", { name: /^Board/ })).toContainText("included")
    expect(await stageRow(ladderTable, /^Night cost/)).toEqual(["Night cost", "", "270.00"])
    for (const absent of [/^Special combination/, /^Period .*adjustment/, /^Rate plan/]) await expect(ladderTable.getByRole("rowheader", { name: absent })).toHaveCount(0)
    // the page shows the served nights[0] fields (formatted), it did not compute them
    const n0 = quote.nights[0]
    expect(n0.subtotal_adults, "GAP-12 fields served").toBeDefined()
    expect([
      (await stageRow(ladderTable, /^Room/))[2],
      ...(await stageRow(ladderTable, /^Occupancy \(adults\)/)).slice(1),
      ...child.slice(1),
      ...(await stageRow(ladderTable, /^Board/)).slice(1),
      (await stageRow(ladderTable, /^Night cost/))[2],
    ]).toEqual([n0.unit, n0.unit, n0.subtotal_adults, n0.subtotal_adults, n0.subtotal_children, n0.occupancy, n0.subtotal_board, n0.cost].map(twoDecimals))
    // no save was needed, and none was made
    expect(calls.count("save_version")).toBe(0)
    await expect(save).toBeEnabled()
  })

  await test.step("13. the price and its explanation: the stages in engine order, Rule applied, band labels", async () => {
    await expect(drawer.getByRole("status", { name: "Total" })).toBeVisible()
    await expect(drawer.getByText("Stages are shown in the order the engine applies them.", { exact: true })).toBeVisible()
    await expect(drawer.getByRole("table", { name: "Whole stay", exact: true })).toBeVisible()
    const why = drawer.getByRole("list").filter({ hasText: "Rule applied:" })
    await expect(why).toHaveCount(1)
    await expect(why).toContainText("Child 7–11.99")
    expect(await why.innerText()).not.toMatch(/\b(INF|CHA|CHB)\b/)
  })

  await test.step("the interaction budget: ≤ 50 clicks, 0 section switches, 0 modal dialogs", async () => {
    await budget.stop()
    const c = await budget.expectWithin(testInfo, { clicks: 50, sectionSwitches: 0, modals: 0 })
    console.log(`pricing workspace budget: ${c.clicks} clicks, ${c.sectionSwitches} section switches, ${c.modals} modal dialogs`)
    if (process.env.TEX_E2E_BUDGET_LOG) console.log(budget.log())
  })

  await test.step("Save: the rules are stored as the typed strings, the bands with their labels", async () => {
    await drawer.getByRole("button", { name: "Close", exact: true }).click()
    await saveDraft(page)
    const v = await readVersion(page, d.version)
    const rate = (room: string, period: string) => v.period_rates.filter((r) => r.room_type === room && (r.period_code || "") === period).map((r) => `${r.op} ${r.value} ${r.base_room_type ?? ""}`)
    expect(rate(SUP, "")).toEqual([`MULTIPLY 1.15 ${STD}`])
    expect(rate(SUP, "P4")).toEqual([`MULTIPLY 1.2 ${STD}`])
    expect(rate(DLX, "")).toEqual([`MULTIPLY 1.35 ${STD}`])
    expect(rate(DLX, "P3")).toEqual([`MULTIPLY 1.4 ${STD}`])
    expect(rate(DLX, "P4")).toEqual([`MULTIPLY 1.4 ${STD}`])
    expect(["P1", "P2", "P3", "P4"].map((p) => rate(STD, p)[0])).toEqual(["ABSOLUTE 70 ", "ABSOLUTE 80 ", "ABSOLUTE 100 ", "ABSOLUTE 130 "])
    const rules = v.occupancy_rules.map((r) => `${r.target}:${r.position}:${r.age_band || ""}:${r.combination || ""}:${r.period_code || ""}:${r.op}:${r.value}`).sort()
    expect(rules).toEqual(
      [
        "ADULT:3::::MULTIPLY:0.7",
        "ADULT:3:::P4:MULTIPLY:0.8",
        "CHILD:0:INF:::MULTIPLY:0",
        "CHILD:0:CHA:::MULTIPLY:0.25",
        "CHILD:0:CHB:::MULTIPLY:0.5",
        "CHILD:1:CHB:2+2::MULTIPLY:0.5",
        "CHILD:2:CHA:2+2::MULTIPLY:0.25",
      ].sort(),
    )
    expect(v.age_bands.map((b) => [b.band_code, String(b.from_age), String(b.to_age), b.is_infant])).toEqual([
      ["INF", "0", "2.99", 1],
      ["CHA", "3", "6.99", 0],
      ["CHB", "7", "11.99", 0],
    ])
    for (const b of v.age_bands) expect(String(b.label ?? "").trim(), `label of ${b.band_code}`).not.toBe("")
    expect(v.boards.map((b) => `${b.board}:${b.is_base}`)).toEqual(["BB:1"])
  })

  noErrors()
})

test("edge checks: 'abc' and '1.500' refused, Escape reverts, Ctrl+Z undoes the bulk entry, a TSV block pastes, +10% on the base adjusts once on the server, x1.20 over a fixed price restores a formula", async ({ page, context }) => {
  test.setTimeout(180_000)
  const noErrors = trackErrors(page)
  await context.grantPermissions(["clipboard-read", "clipboard-write"])
  await login(page, "revenue@demo.tex")
  const d = await newDraft(page, "E2E-PWE", ownerDraft())
  made.push(d.contract)
  await openVersion(page, d)
  const editor = (room: string, period: string) => priceMatrix(page).getByRole("textbox", { name: `Price: ${room} · ${period}`, exact: true })
  await expect(resolved(page, N.SUP, "P1", "80.50")).toBeVisible()

  await test.step("'abc' shows the parser's error and stays an error draft; Escape reverts", async () => {
    await priceCell(page, N.SUP, "P2").click()
    await page.keyboard.type("abc")
    await page.keyboard.press("Enter")
    await expect(editor(N.SUP, "P2")).toHaveAttribute("aria-invalid", "true")
    await expect(page.getByRole("status").filter({ hasText: "Not a price or formula" })).toBeVisible()
    await page.keyboard.press("Escape")
    await expect(editor(N.SUP, "P2")).toHaveCount(0)
    await expect(named(page, `${N.SUP} · P2: follows all periods, ${N.STD} ×1.15`)).toBeFocused()
    // a typed price, then Escape: the cell keeps its price
    await priceCell(page, N.STD, "P1").click()
    await page.keyboard.type("999")
    await page.keyboard.press("Escape")
    await expect(editor(N.STD, "P1")).toHaveCount(0)
    await expect(named(page, `${N.STD} · P1: entered price, 70.00`)).toBeFocused()
  })

  await test.step("'1.500' in a price cell: the AMBIGUOUS message (O5), nothing stored", async () => {
    await priceCell(page, N.DLX, "P2").click()
    await page.keyboard.type("1.500")
    await expect(page.getByRole("status").filter({ hasText: "Is this 1500 or 1.5? Type 1500 for one thousand five hundred, or 1.5 for one and a half." })).toBeVisible()
    await page.keyboard.press("Enter")
    await expect(editor(N.DLX, "P2")).toHaveAttribute("aria-invalid", "true")
    await page.keyboard.press("Escape")
    await expect(named(page, `${N.DLX} · P2: follows all periods, ${N.STD} ×1.35`)).toBeVisible()
  })

  await test.step("Ctrl+Z after the bulk entry restores ×1.35 on both cells", async () => {
    await priceCell(page, N.DLX, "P3").click()
    await page.keyboard.press("Shift+ArrowRight")
    await page.keyboard.type("x1.40")
    await page.keyboard.press("Control+Enter")
    for (const p of ["P3", "P4"]) await expect(named(page, `${N.DLX} · ${p}: period override, ${N.STD} ×1.4`)).toBeVisible()
    await expect(resolved(page, N.DLX, "P4", "182.00")).toBeVisible()
    await page.keyboard.press("Control+z")
    for (const p of ["P3", "P4"]) await expect(named(page, `${N.DLX} · ${p}: follows all periods, ${N.STD} ×1.35`)).toBeVisible()
    await expect(resolved(page, N.DLX, "P4", "175.50")).toBeVisible()
  })

  await test.step("a 2×2 block pasted from a spreadsheet at Superior P1 fills Superior and Deluxe P1:P2", async () => {
    await page.evaluate((t) => navigator.clipboard.writeText(t), "x1.1\tx1.2\r\nx1.3\tx1.4\r\n")
    await priceCell(page, N.SUP, "P1").click()
    await page.keyboard.press("Control+v")
    await expect(named(page, `${N.SUP} · P1: period override, ${N.STD} ×1.1`)).toBeVisible()
    await expect(named(page, `${N.SUP} · P2: period override, ${N.STD} ×1.2`)).toBeVisible()
    await expect(named(page, `${N.DLX} · P1: period override, ${N.STD} ×1.3`)).toBeVisible()
    await expect(named(page, `${N.DLX} · P2: period override, ${N.STD} ×1.4`)).toBeVisible()
    await expect(resolved(page, N.SUP, "P1", "77.00")).toBeVisible()
    await expect(page.getByTestId("undo-toast")).toContainText("Applied to 4 cells")
  })

  await test.step("+10% on the base room's P1 is applied once by the server: 77.00, stored as a price", async () => {
    await priceCell(page, N.STD, "P1").click()
    await page.keyboard.type("+10%")
    await expect(page.getByRole("status").filter({ hasText: `${N.STD} · P1: adjust 70.00 by +10% (calculated on commit)` })).toBeVisible()
    const answered = page.waitForResponse((r) => r.url().includes("contracts.apply_op_values"))
    await page.keyboard.press("Enter")
    const res = await answered
    expect(res.ok()).toBeTruthy()
    expect(res.request().postDataJSON()).toMatchObject({ values: ["70"], op: "ADJUST_PERCENT", value: "10" })
    await expect(named(page, `${N.STD} · P1: entered price, 77.00`)).toBeVisible()
  })

  await test.step("=245 fixes Superior P3; x1.20 over it restores a formula", async () => {
    await priceCell(page, N.SUP, "P3").click()
    await page.keyboard.type("=245")
    await page.keyboard.press("Enter")
    await expect(named(page, `${N.SUP} · P3: fixed price overriding the formula, 245.00`)).toBeVisible()
    await expect(resolved(page, N.SUP, "P3", "245.00")).toBeVisible()
    await priceCell(page, N.SUP, "P3").click()
    await page.keyboard.type("x1.20")
    await expect(page.getByRole("status").filter({ hasText: `${N.SUP} · P3 = ${N.STD} ×1.2 (replaces the fixed price 245.00)` })).toBeVisible()
    await page.keyboard.press("Enter")
    await expect(named(page, `${N.SUP} · P3: period override, ${N.STD} ×1.2`)).toBeVisible()
    await expect(resolved(page, N.SUP, "P3", "120.00")).toBeVisible()
  })

  // the edits were never saved
  const v = await readVersion(page, d.version)
  expect(v.period_rates.filter((r) => r.period_code === "P3" && r.room_type === SUP)).toEqual([])
  noErrors()
})

test("the budget counts what it must: clicks, a native select as two, a section switch, a modal dialog", async ({ page }) => {
  // a check of the counter itself, so that the acceptance's zero counts cannot pass by not counting
  test.setTimeout(120_000)
  await login(page, "revenue@demo.tex")
  const d = await newDraft(page, "E2E-PWB", ownerDraft())
  made.push(d.contract)
  const budget = await Budget.attach(page)
  await openVersion(page, d)
  budget.start()
  // the Publish dialog is modal (Publish needs a clean draft, so it comes first)
  await page.getByRole("button", { name: "Publish", exact: true }).click()
  await expect(page.getByRole("dialog", { name: /^Publish V\d+ of / })).toBeVisible()
  await page.keyboard.press("Escape")
  await expect(page.getByRole("dialog", { name: /^Publish V\d+ of / })).toBeHidden()
  await priceCell(page, N.STD, "P1").click()
  await page.keyboard.type("71")
  await page.keyboard.press("Enter")
  await pickFrom(page.getByRole("region", { name: "Boards", exact: true }).getByRole("button", { name: "Add board", exact: true }), "HB")
  await page.keyboard.press("Escape")
  const sections = page.getByRole("tablist", { name: "Version sections", exact: true })
  await sections.getByRole("tab", { name: /^Commercial rules/ }).click()
  await sections.getByRole("tab", { name: /^Pricing/ }).click()
  await budget.stop()
  expect(await budget.counts(), budget.log()).toEqual({ clicks: 6, sectionSwitches: 2, modals: 1 })
})
