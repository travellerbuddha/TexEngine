// The Price test drawer and its Explain ladder (PRICING_WORKSPACE_UX.md §3.13; slice S14): Test
// this price from a cell with unsaved edits and no save, a ladder of served values only in engine
// order, exact child ages in months or by date of birth, Show in grid to the matrix cell, the
// combination card and the ladder cell, Live re-pricing, Preview & audit, German with the decimal
// comma, and a 375 px phone. Every test starts from its own API-made draft of the owner's example.
import { expect, test, type Locator, type Page, type Response } from "@playwright/test"
import { api, login, texPath, trackErrors } from "./helpers"
import { archiveAll, CAP, DLX, HOTEL, newContract, occ, periods, STD, SUP, watchContracts, Y } from "./flows/workspace"

test.use({ locale: "en-US", actionTimeout: 15_000, navigationTimeout: 30_000 })

const made: string[] = []

/** A draft of the owner's example: Standard 70/80/100/130, Superior ×1.15 (P4 ×1.20), Deluxe ×1.30
 * saved (test 1 types ×1.35 unsaved), bands 2.99/6.99/11.99 with labels, 3rd adult ×0.70, the
 * 2A+2C combination (child 1 7–11.99 ×0.50, child 2 3–6.99 ×0.25), BB base. */
async function newDraft(page: Page): Promise<{ contract: string; version: string; names: Record<string, string> }> {
  const { contract, version } = await newContract(page, { prefix: "E2E-PWT" })
  await api(page.request, "kamra.tex.api.contracts.save_version", {
    name: version,
    data: {
      rooms: [
        { room_type: STD, is_base: 1, ...CAP },
        { room_type: SUP, is_base: 0, ...CAP },
        { room_type: DLX, is_base: 0, ...CAP },
      ],
      periods: periods(),
      period_rates: [
        { room_type: STD, period_code: "P1", op: "ABSOLUTE", value: "70" },
        { room_type: STD, period_code: "P2", op: "ABSOLUTE", value: "80" },
        { room_type: STD, period_code: "P3", op: "ABSOLUTE", value: "100" },
        { room_type: STD, period_code: "P4", op: "ABSOLUTE", value: "130" },
        { room_type: SUP, period_code: "", op: "MULTIPLY", value: "1.15", base_room_type: STD },
        { room_type: SUP, period_code: "P4", op: "MULTIPLY", value: "1.2", base_room_type: STD },
        { room_type: DLX, period_code: "", op: "MULTIPLY", value: "1.3", base_room_type: STD },
      ],
      age_bands: [
        { band_code: "INF", label: "Infant 0–2.99", from_age: "0", to_age: "2.99", is_infant: 1 },
        { band_code: "CHA", label: "Child 3–6.99", from_age: "3", to_age: "6.99", is_infant: 0 },
        { band_code: "CHB", label: "Child 7–11.99", from_age: "7", to_age: "11.99", is_infant: 0 },
      ],
      occupancy_rules: [
        occ({ target: "ADULT", position: 3, value: "0.7" }),
        occ({ target: "CHILD", age_band: "INF", value: "0" }),
        occ({ target: "CHILD", age_band: "CHA", value: "0.25" }),
        occ({ target: "CHILD", age_band: "CHB", value: "0.5" }),
        occ({ target: "CHILD", position: 1, age_band: "CHB", combination: "2+2", value: "0.5" }),
        occ({ target: "CHILD", position: 2, age_band: "CHA", combination: "2+2", value: "0.25" }),
      ],
      boards: [{ board: "BB", is_base: 1, op: "ADD", adult_amount: null, child_percent: "50", infant_free: 1, room_type: "", period_code: "" }],
    },
  })
  const v = await api<{ room_types: { name: string; room_type_name: string }[] }>(page.request, "kamra.tex.api.contracts.get_version", { name: version })
  const names = Object.fromEntries(v.room_types.map((r) => [r.name, r.room_type_name || r.name]))
  return { contract, version, names }
}

async function open(page: Page, lang = "en") {
  await login(page, "revenue@demo.tex")
  const d = await newDraft(page)
  made.push(d.contract)
  await page.addInitScript((l) => window.localStorage.setItem("tex-lang", l), lang)
  await page.goto(texPath(`/tex/rates/contracts/${encodeURIComponent(d.contract)}/versions/${encodeURIComponent(d.version)}`) + "#pricing")
  await expect(page.getByRole("grid", { name: lang === "de" ? /.+/ : "Room prices by period" }).first()).toBeVisible()
  return d
}

const matrix = (page: Page) => page.getByRole("grid", { name: "Room prices by period" })
const cell = (grid: Locator, name: string) => grid.getByRole("gridcell", { name: new RegExp(`^${name.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}: `) })
const drawer = (page: Page, name = "Price test") => page.getByRole("dialog", { name })
const why = (d: Locator) => d.getByRole("list").filter({ hasText: "Rule applied:" })
async function priced(page: Page, run: () => Promise<unknown>): Promise<Record<string, unknown>> {
  const res: Promise<Response> = page.waitForResponse((r) => r.url().includes("contracts.preview_price") && r.request().method() === "POST")
  await run()
  const body = await (await res).json()
  return body.message
}
/** a ladder table's row for a stage: [stage cell text, before, after] */
async function stageRow(table: Locator, stage: string) {
  const row = table.getByRole("row").filter({ has: table.page().getByRole("rowheader", { name: new RegExp(`^${stage}`) }) }).first()
  const cells = row.getByRole("cell")
  const n = await cells.count()
  return [(await row.getByRole("rowheader").innerText()).split("\n")[0], ...(await Promise.all(Array.from({ length: n }, (_, i) => cells.nth(i).innerText())))]
}

test.describe.serial("price test drawer", () => {
  test.afterAll(async ({ browser }) => archiveAll(browser, made, "pricing workspace price test e2e clean-up"))

  test("1. unsaved Deluxe ×1.35, Test this price on Deluxe · P2: 2A + child 8, no save; the ladder reads only served values", async ({ page }) => {
    const noErrors = trackErrors(page)
    const calls = watchContracts(page)
    const d = await open(page)
    const m = matrix(page)
    const DLXN = d.names[DLX]
    // an unsaved edit: Deluxe ×1.30 → ×1.35
    await cell(m, `${DLXN} · All periods`).first().click()
    await page.keyboard.type("x1.35")
    await page.keyboard.press("Enter")
    await expect(page.getByText("Unsaved changes", { exact: true })).toBeVisible()
    // the cell's context menu on Deluxe's P2 (the resolved row's cell: read-only, the menu has only the test)
    await cell(m, `${DLXN} · P2`).last().click({ button: "right" })
    const menu = page.getByRole("menu", { name: `Cell actions: ${DLXN} · P2` })
    await expect(menu).toBeVisible()
    await page.getByRole("menuitem", { name: "Test this price" }).click()
    const dr = drawer(page)
    await expect(dr).toBeVisible()
    expect(await dr.getAttribute("aria-modal")).toBeNull()
    expect(await page.locator('[aria-modal="true"]').count()).toBe(0)
    // prefill: Deluxe, P2's start for 3 nights, the base board, 2 adults
    await expect(dr.getByLabel(/^Room type/)).toHaveValue(DLX)
    await expect(dr.getByLabel(/^Check-in/)).toHaveValue(`${Y}-05-01`)
    await expect(dr.getByLabel(/^Check-out/)).toHaveValue(`${Y}-05-04`)
    await expect(dr.getByLabel(/^Board/)).toHaveValue("BB")
    await expect(dr.getByLabel(/^Adults/)).toHaveValue("2")
    await expect(dr.getByText("Priced with your unsaved changes.")).toBeVisible()
    await dr.getByRole("button", { name: "Add child", exact: true }).click()
    await dr.getByLabel("Age of child 1", { exact: true }).fill("8")
    const q = await priced(page, () => dr.getByRole("button", { name: /^Calculate/ }).click())
    const n0 = (q.nights as Record<string, string>[])[0]
    const ladder = dr.getByRole("table", { name: /Nights 1–3 · P2/ })
    await expect(ladder).toBeVisible()
    expect(await stageRow(ladder, "Base price")).toEqual(["Base price", "", "80.00"])
    expect((await stageRow(ladder, "Period"))[1]).toBe("no amount (period used to choose rules)")
    expect(await stageRow(ladder, "Room")).toEqual(["Room", "80.00", "108.00"])
    expect(await stageRow(ladder, "Occupancy \\(adults\\)")).toEqual(["Occupancy (adults)", "108.00", "216.00"])
    expect(await stageRow(ladder, "Children")).toEqual(["Children", "216.00", "270.00"])
    expect(await stageRow(ladder, "Board")).toEqual(["Board", "270.00", "270.00"])
    expect(await stageRow(ladder, "Night cost")).toEqual(["Night cost", "", "270.00"])
    // the child line 54.00 (CHILD_SLOT.after)
    await expect(ladder.locator('tr[data-line="CHILD_SLOT"]')).toContainText("54.00")
    await expect(ladder.getByRole("rowheader", { name: /^Board/ })).toContainText("included")
    for (const absent of ["Special combination", "Period .* adjustment", "Rate plan"]) await expect(ladder.getByRole("rowheader", { name: new RegExp(`^${absent}`) })).toHaveCount(0)
    // the stage values are the served nights[0] fields, formatted
    const two = (s: string) => s.replace(/(\.\d\d)0+$/, "$1")
    expect([n0.unit, n0.subtotal_adults, n0.subtotal_children, n0.subtotal_board, n0.cost].map(two)).toEqual(["108.00", "216.00", "270.00", "270.00", "270.00"])
    await expect(dr.getByText("Stages are shown in the order the engine applies them.")).toBeVisible()
    await expect(dr.getByRole("table", { name: "Whole stay" })).toBeVisible()
    // no save was needed, and none was made
    expect(calls.count("save_version")).toBe(0)
    // the night selector defaults to All nights; one night shows that night alone
    await expect(dr.getByLabel("Nights shown")).toHaveValue("")
    await dr.getByLabel("Nights shown").selectOption({ index: 2 })
    await expect(dr.getByRole("table", { name: /^Night 2 · P2/ })).toBeVisible()
    noErrors()
  })

  test("2. exact age: {age_months: 143} is priced in Child 7–11.99, 144 is not; a date of birth is sent as {dob}", async ({ page }) => {
    const noErrors = trackErrors(page)
    await open(page)
    await page.getByRole("button", { name: "Price test", exact: true }).click()
    const dr = drawer(page)
    await dr.getByRole("button", { name: "Add child", exact: true }).click()
    await dr.getByLabel("Child 1: age given in").selectOption("months")
    const months = dr.getByLabel("Age of child 1 in months", { exact: true })
    await months.fill("143")
    let body: Record<string, unknown> = {}
    page.on("request", (r) => {
      if (r.url().includes("contracts.preview_price")) body = r.postDataJSON()
    })
    await priced(page, () => dr.getByRole("button", { name: /^Calculate/ }).click())
    expect(body.children).toEqual([{ age_months: 143 }])
    await expect(why(dr)).toContainText("Child 1 (11y11m, Child 7–11.99)")
    await months.fill("144")
    await priced(page, () => dr.getByRole("button", { name: /^Calculate/ }).click())
    expect(body.children).toEqual([{ age_months: 144 }])
    await expect(why(dr)).toContainText("child 1 is above the oldest child band: priced as adult")
    await expect(why(dr)).not.toContainText("Child 7–11.99)")
    // a date of birth
    await dr.getByLabel("Child 1: age given in").selectOption("dob")
    await dr.getByLabel("Date of birth of child 1").fill(`${Y - 8}-01-15`)
    await priced(page, () => dr.getByRole("button", { name: /^Calculate/ }).click())
    expect(body.children).toEqual([{ dob: `${Y - 8}-01-15` }])
    await expect(why(dr)).toContainText("Child 1 (")
    noErrors()
  })

  test("3. Show in grid: Superior P4 2A+2C focuses the Superior · P4 cell, then the 2A+2C card; the header's Price test starts from the focused cell; band labels, no codes", async ({ page }) => {
    const noErrors = trackErrors(page)
    const d = await open(page)
    const SUPN = d.names[SUP]
    const m = matrix(page)
    await cell(m, `${SUPN} · P4`).first().click()
    await page.getByRole("button", { name: "Price test", exact: true }).click()
    let dr = drawer(page)
    await expect(dr.getByLabel(/^Room type/)).toHaveValue(SUP)
    await expect(dr.getByLabel(/^Check-in/)).toHaveValue(`${Y}-07-01`)
    for (const age of ["8", "4"]) {
      await dr.getByRole("button", { name: "Add child", exact: true }).click()
      await dr.getByLabel(`Age of child ${age === "8" ? 1 : 2}`, { exact: true }).fill(age)
    }
    await priced(page, () => dr.getByRole("button", { name: /^Calculate/ }).click())
    const list = why(dr)
    await expect(list).toContainText("Child 1 [Child 7–11.99] @2A+2C")
    await expect(list).toContainText("Child 2 [Child 3–6.99] @2A+2C")
    const text = await list.innerText()
    expect(text).not.toMatch(/\b(INF|CHA|CHB)\b/)
    // Show in grid on the Superior P4 rule
    await list.getByRole("button", { name: new RegExp(`^Show in grid: ${HOTEL}-FAM @P4`) }).first().click()
    await expect(dr).toBeHidden()
    await expect(cell(m, `${SUPN} · P4`).first()).toBeFocused()
    // and on the 2A+2C child rule: the combination card. Opened again, the test keeps its party
    // (UX revision 2026-10): the two children are still there
    await page.getByRole("button", { name: "Price test", exact: true }).click()
    dr = drawer(page)
    await expect(dr.getByLabel("Age of child 1", { exact: true })).toHaveValue("8")
    await expect(dr.getByLabel("Age of child 2", { exact: true })).toHaveValue("4")
    await priced(page, () => dr.getByRole("button", { name: /^Calculate/ }).click())
    await why(dr).getByRole("button", { name: /^Show in grid: Child 1 \[Child 7–11\.99\] @2A\+2C/ }).first().click()
    await expect(dr).toBeHidden()
    const card = page.locator('[data-combination="2+2"]')
    await expect(card).toBeFocused()
    // a ladder rule: Child [Child 7–11.99] (all positions) from a 2A+1C test: the second child removed
    await page.getByRole("button", { name: "Price test", exact: true }).click()
    dr = drawer(page)
    await dr.getByRole("button", { name: "Remove child 2", exact: true }).click()
    await expect(dr.getByLabel("Age of child 1", { exact: true })).toHaveValue("8")
    await expect(dr.getByLabel("Age of child 2", { exact: true })).toHaveCount(0)
    await priced(page, () => dr.getByRole("button", { name: /^Calculate/ }).click())
    await why(dr).getByRole("button", { name: /^Show in grid: Child \[Child 7–11\.99\]/ }).first().click()
    await expect(page.getByRole("grid", { name: "Occupancy and child pricing by period" }).getByRole("gridcell", { name: /^Child 7–11\.99 · All periods/ })).toBeFocused()
    noErrors()
  })

  test("4. Live re-prices a settled edit of the form and of the draft; Preview & audit keeps the full panel", async ({ page }) => {
    const noErrors = trackErrors(page)
    const d = await open(page)
    const calls = watchContracts(page)
    await page.getByRole("button", { name: "Price test", exact: true }).click()
    const dr = drawer(page)
    await priced(page, () => dr.getByRole("button", { name: /^Calculate/ }).click())
    const total = dr.getByRole("status", { name: "Total" })
    const first = await total.innerText()
    await dr.getByRole("switch", { name: /Live/ }).click()
    // the form: 3 adults
    await priced(page, () => dr.getByLabel(/^Adults/).fill("3"))
    await expect(total).not.toHaveText(first)
    // the draft (the drawer is not modal): Standard P1 70 → 75 re-prices the test
    const before = await total.innerText()
    const m = matrix(page)
    await priced(page, async () => {
      await cell(m, `${d.names[STD]} · P1`).click()
      await page.keyboard.type("75")
      await page.keyboard.press("Enter")
    })
    await expect(total).not.toHaveText(before)
    expect(calls.count("save_version")).toBe(0)
    // Preview & audit has the full panel (and the same ladder)
    await page.getByRole("button", { name: "Close" }).first().click()
    await page.getByRole("tab", { name: /Preview & audit/ }).click()
    const panel = page.getByRole("tabpanel", { name: /Preview & audit/ })
    await priced(page, () => panel.getByRole("button", { name: /^Calculate/ }).click())
    await expect(panel.getByRole("heading", { name: "Price ladder" })).toBeVisible()
    // Show in grid from Preview & audit: Pricing opens on the rule's cell
    await why(panel).getByRole("button", { name: new RegExp(`^Show in grid: ${HOTEL}-STD @P1`) }).first().click()
    await expect(page.getByRole("tab", { name: /^Pricing/ })).toHaveAttribute("aria-selected", "true")
    await expect(cell(matrix(page), `${d.names[STD]} · P1`)).toBeFocused()
    expect(new URL(page.url()).hash).toBe("#pricing")
    // Escape closes the drawer, the focus goes back to the Price test button
    await page.getByRole("button", { name: "Price test", exact: true }).click()
    await expect(drawer(page)).toBeVisible()
    await page.keyboard.press("Escape")
    await expect(drawer(page)).toBeHidden()
    await expect(page.getByRole("button", { name: "Price test", exact: true })).toBeFocused()
    noErrors()
  })

  test("5. German: stage labels and the sentences with a template are localised, room names and band labels, the decimal comma", async ({ page }) => {
    const noErrors = trackErrors(page)
    const d = await open(page, "de")
    await page.getByRole("button", { name: "Preistest", exact: true }).click()
    const dr = drawer(page, "Preistest")
    await dr.getByLabel(/^Zimmertyp/).selectOption(DLX)
    await dr.getByLabel(/^Anreise/).fill(`${Y}-05-10`)
    await dr.getByLabel(/^Abreise/).fill(`${Y}-05-13`)
    await dr.getByRole("button", { name: /Kind hinzufügen/ }).click()
    await dr.getByLabel("Alter von Kind 1", { exact: true }).fill("8")
    await priced(page, () => dr.getByRole("button", { name: /^Berechnen/ }).click())
    const ladder = dr.getByRole("table", { name: /Nächte 1–3 · P2/ })
    for (const s of ["Basispreis", "Zeitraum", "Zimmer", "Belegung (Erwachsene)", "Kinder", "Verpflegung", "Kosten der Nacht", "Aufschlag", "Währungsumrechnung", "Aktion"])
      await expect(ladder.getByRole("rowheader", { name: new RegExp(`^${s.replace(/[()]/g, "\\$&")}`) })).toHaveCount(1)
    await expect(ladder.getByRole("row").filter({ hasText: /^Zimmer/ }).first()).toContainText("104,00")
    await expect(dr.getByText("Die Schritte stehen in der Reihenfolge, in der die Preisberechnung sie anwendet.")).toBeVisible()
    const list = why(dr).or(dr.getByRole("list", { name: "Erklärung" }))
    await expect(list.first()).toContainText(`${d.names[DLX]} = ${d.names[STD]} × 1,30 → 104,00`)
    await expect(list.first()).toContainText("Kind 1 (8 J., Child 7–11.99) × 0,50 104,00 = 52,00")
    await expect(list.first()).toContainText("Zeitraum P2 (May)")
    await expect(list.first()).toContainText("Übernachtung mit Frühstück: im Preis enthalten")
    noErrors()
  })

  test("6. a 375 px phone: the drawer's ladder does not scroll sideways", async ({ page }) => {
    const noErrors = trackErrors(page)
    await page.setViewportSize({ width: 375, height: 800 })
    await open(page)
    await page.getByRole("button", { name: "Price test", exact: true }).click()
    const dr = drawer(page)
    await dr.getByRole("button", { name: "Add child", exact: true }).click()
    await dr.getByLabel("Age of child 1", { exact: true }).fill("8")
    await priced(page, () => dr.getByRole("button", { name: /^Calculate/ }).click())
    await dr.getByRole("heading", { name: "Price ladder" }).scrollIntoViewIfNeeded()
    const overflow = await dr.evaluate((el) => {
      const body = el.querySelector(".overflow-y-auto") as HTMLElement
      return { scroll: body.scrollWidth, client: body.clientWidth }
    })
    expect(overflow.scroll).toBeLessThanOrEqual(overflow.client + 1)
    noErrors()
  })
})
