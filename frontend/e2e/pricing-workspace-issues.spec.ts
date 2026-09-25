// Validation issues anchored in the Pricing Workspace (PRICING_WORKSPACE_UX.md §3.15; slice S15):
// the cell, period header, ladder cell (in its rooms scope), combination card or board cell an issue
// is about shows it (aria-invalid for errors, the message in its description); the live check lists
// issues by section and a click shows each one's place; band labels instead of codes in every issue
// list; a published version's stored report anchored by saved row names, with no validate_version.
import { expect, test, type Locator, type Page } from "@playwright/test"
import { api, login, texPath, trackErrors, uniqueRunId } from "./helpers"
import { archiveAll, DLX, HOTEL, STD, SUP, Y } from "./flows/workspace"

test.use({ locale: "en-US", actionTimeout: 15_000, navigationTimeout: 30_000 })

const CAP = { max_adults: 3, max_children: 2, max_occupants: 5, min_adults: 1 }
const occ = (f: Record<string, unknown>) => ({ target: "ADULT", position: 0, age_band: null, combination: null, room_type: null, period_code: null, op: "MULTIPLY", value: null, is_override: 0, note: null, ...f })
const esc = (s: string) => s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")

type Data = Record<string, unknown[]>
function base(): Data {
  return {
    rooms: [
      { room_type: STD, is_base: 1, ...CAP },
      { room_type: SUP, is_base: 0, ...CAP },
      { room_type: DLX, is_base: 0, ...CAP },
    ],
    periods: [
      { period_code: "P1", period_name: "Apr", start_date: `${Y}-04-01`, end_date: `${Y}-04-30` },
      { period_code: "P2", period_name: "May", start_date: `${Y}-05-01`, end_date: `${Y}-05-31` },
      { period_code: "P3", period_name: "Jun", start_date: `${Y}-06-01`, end_date: `${Y}-06-30` },
      { period_code: "P4", period_name: "Jul", start_date: `${Y}-07-01`, end_date: `${Y}-07-31` },
    ],
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
    boards: [
      { board: "BB", is_base: 1, op: "ADD", adult_amount: null, child_percent: "50", infant_free: 1, room_type: "", period_code: "" },
      { board: "HB", is_base: 0, op: "ADD", adult_amount: "20", child_percent: "50", infant_free: 1, room_type: "", period_code: "" },
      { board: "HB", is_base: 0, op: "ADD", adult_amount: "25", child_percent: "50", infant_free: 1, room_type: SUP, period_code: "P2" },
    ],
  }
}

const made: string[] = []
async function open(page: Page, tweak: (d: Data) => void = () => {}, lang = "en") {
  await login(page, "revenue@demo.tex")
  const run = uniqueRunId()
  const c = await api<{ contract: { name: string } }>(page.request, "kamra.tex.api.contracts.save_contract", {
    data: { property: HOTEL, contract_code: `E2E-PWI-${run}`, contract_name: `E2E-PWI ${run}`, market: "DE", pricing_basis: "PERSON", contract_currency: "EUR", stay_from: `${Y}-04-01`, stay_to: `${Y}-07-31` },
  })
  const contract = c.contract.name
  made.push(contract)
  const b = await api<{ versions: { name: string }[] }>(page.request, "kamra.tex.api.contracts.get_contract", { name: contract })
  const version = b.versions[0].name
  const data = base()
  tweak(data)
  await api(page.request, "kamra.tex.api.contracts.save_version", { name: version, data })
  const v = await api<{ room_types: { name: string; room_type_name: string }[] }>(page.request, "kamra.tex.api.contracts.get_version", { name: version })
  const names = Object.fromEntries(v.room_types.map((r) => [r.name, r.room_type_name || r.name]))
  await page.addInitScript((l) => {
    window.localStorage.setItem("tex-lang", l)
    // the regions open (their remembered state is per viewer)
    window.localStorage.setItem("tex.rates.ws.occupancy_open", "1")
    window.localStorage.setItem("tex.rates.ws.boards_open", "1")
  }, lang)
  await page.goto(texPath(`/tex/rates/contracts/${encodeURIComponent(contract)}/versions/${encodeURIComponent(version)}`) + "#pricing")
  await expect(matrix(page)).toBeVisible()
  return { contract, version, names }
}

const matrix = (page: Page) => page.getByRole("grid", { name: "Room prices by period" })
const ladder = (page: Page) => page.getByRole("grid", { name: "Occupancy and child pricing by period" })
const boardsGrid = (page: Page) => page.getByRole("grid", { name: "Board supplements by period" })
const cell = (grid: Locator, name: string) => grid.getByRole("gridcell", { name: new RegExp(`^${esc(name)}: `) }).first()
const chip = (page: Page) => page.getByRole("button", { name: /^Live check/ })
const checkPopover = (page: Page) => page.getByRole("dialog", { name: "Live check" })
/** the text a screen reader reads as an element's description */
const description = (el: Locator) =>
  el.evaluate((node) =>
    (node.getAttribute("aria-describedby") ?? "")
      .split(/\s+/)
      .filter(Boolean)
      .map((id) => document.getElementById(id)?.textContent ?? "")
      .join(" "),
  )

test.describe.serial("anchored issues", () => {
  test.afterAll(async ({ browser }) => archiveAll(browser, made, "pricing workspace issues e2e clean-up"))

  test("1. a duplicate SUP P4 row marks the SUP · P4 cell and the chip count; a duplicate board row made in the Advanced tables marks its board cell; clicks focus them", async ({ page }) => {
    const noErrors = trackErrors(page)
    const d = await open(page, (data) => {
      data.period_rates.push({ room_type: SUP, period_code: "P4", op: "MULTIPLY", value: "1.25", base_room_type: STD })
    })
    const SUPN = d.names[SUP]
    const m = matrix(page)
    // the chip counts the duplicate
    await expect(chip(page)).toContainText("1 error")
    const sup4 = cell(m, `${SUPN} · P4`)
    await expect(sup4).toHaveAttribute("aria-invalid", "true")
    await expect(sup4).toHaveAttribute("data-issue", "error")
    expect(await description(sup4)).toMatch(new RegExp(`Error: room ${esc(SUP)} has two rules for period P4`))
    // the other cells are not marked
    await expect(cell(m, `${SUPN} · P3`)).not.toHaveAttribute("aria-invalid", "true")
    // the popover lists it under Pricing; a click focuses the cell
    await chip(page).click()
    const pop = checkPopover(page)
    await expect(pop.getByRole("region", { name: /^Pricing: 1 issue/ })).toBeVisible()
    await pop.getByRole("button", { name: /ROOM_RULE_DUPLICATE/ }).click()
    await expect(pop).toBeHidden()
    await expect(sup4).toBeFocused()

    // Advanced tables → Boards: duplicate the HB SUP P2 row
    await page.evaluate(() => (window.location.hash = "#rules/boards"))
    const panel = page.getByRole("tabpanel", { name: "Boards" })
    await expect(panel).toBeVisible()
    await panel.getByRole("button", { name: "Duplicate row 3" }).click()
    await expect(chip(page)).toContainText("2 errors")
    // the Boards table lists its issue (formatted), the chip's list has it under Pricing
    await expect(panel.getByText(/BOARD_DUPLICATE/)).toBeVisible()
    await chip(page).click()
    await expect(checkPopover(page).getByRole("region", { name: /^Pricing: 2 issues/ })).toBeVisible()
    await checkPopover(page).getByRole("button", { name: /BOARD_DUPLICATE/ }).click()
    // Pricing opens and the board cell is focused
    const hb = cell(boardsGrid(page), `Half board · ${SUPN} only · P2`)
    await expect(hb).toBeFocused()
    await expect(hb).toHaveAttribute("aria-invalid", "true")
    expect(await description(hb)).toContain("Error: board HB has 2 rules for the same room and period")
    await expect(page).toHaveURL(/#pricing$/)

    // clearing SUP · P4 removes both rows: the issue goes, the cell is clean
    await sup4.click()
    await page.keyboard.press("Delete")
    await expect(chip(page)).toContainText("1 error")
    await expect(cell(m, `${SUPN} · P4`)).not.toHaveAttribute("aria-invalid", "true")
    noErrors()
  })

  test("2. an overlapping band: labels, not codes, in the chip popover, the Advanced table and Preview & audit; a click opens the child ages drawer", async ({ page }) => {
    const noErrors = trackErrors(page)
    await open(page, (data) => {
      data.age_bands = [
        { band_code: "INF", label: "Baby", from_age: "0", to_age: "2.99", is_infant: 1 },
        { band_code: "CHA", label: "Small kids", from_age: "3", to_age: "6.99", is_infant: 0 },
        { band_code: "CHB", label: "", from_age: "6", to_age: "11.99", is_infant: 0 },
      ]
    })
    await expect(chip(page)).toContainText(/error/)
    await chip(page).click()
    const pop = checkPopover(page)
    const item = pop.getByRole("button", { name: /AGE_BANDS/ })
    await expect(item).toContainText("age bands Small kids and Child 6–11.99 overlap at")
    await expect(pop.getByText(/\b(INF|CHA|CHB)\b/)).toHaveCount(0)
    await item.click()
    await expect(page.getByRole("dialog", { name: "Child age bands" })).toBeVisible()
    // the Advanced Child ages table and Preview & audit read labels too
    await page.keyboard.press("Escape")
    await page.evaluate(() => (window.location.hash = "#rules/ages"))
    const ages = page.getByRole("tabpanel", { name: "Child ages" })
    await expect(ages.getByText(/age bands Small kids and Child 6–11\.99 overlap at/)).toBeVisible()
    await page.evaluate(() => (window.location.hash = "#preview"))
    await expect(page.getByText(/age bands Small kids and Child 6–11\.99 overlap at/)).toBeVisible()
    noErrors()
  })

  test("3. the publish sweep's parties: the 2A+2C card, and a 2A+1C party on its band row in the room's ladder scope", async ({ page }) => {
    const noErrors = trackErrors(page)
    await open(page, (data) => {
      // no rule for infants: every party with an infant is unsellable (sweep warnings)
      data.occupancy_rules = (data.occupancy_rules as Record<string, unknown>[]).filter((r) => r.age_band !== "INF")
    })
    await expect(chip(page)).toContainText(/warnings/)
    // the 2+2 card shows its sweep warning with the band's label
    const card = page.locator('[data-card][data-combination="2+2"]')
    await expect(card).toHaveAttribute("data-issue", "warning")
    await expect(card).toContainText("[Infant 0–2.99]")
    await expect(card).not.toContainText("[INF]")
    // the chip's list: STD 2A+1C [Infant 0–2.99] → the STD scope, the Infant row, P1
    await chip(page).click()
    const pop = checkPopover(page)
    await expect(pop.getByText(/\[INF\]/)).toHaveCount(0)
    await pop.getByRole("button", { name: new RegExp(`${esc(STD)} 2A\\+1C \\[Infant 0–2\\.99\\]`) }).click()
    await expect(page.getByRole("combobox", { name: /^Rooms/ })).toHaveValue(STD)
    const inf = cell(ladder(page), "Infant 0–2.99 · P1")
    await expect(inf).toBeFocused()
    await expect(inf).toHaveAttribute("data-issue", "warning")
    // a warning is described, not invalid
    await expect(inf).not.toHaveAttribute("aria-invalid", "true")
    expect(await description(inf)).toContain(`Warning: ${STD} 2A+1C [Infant 0–2.99]`)
    // the All rooms scope's Infant row is not the STD one
    await page.getByRole("combobox", { name: /^Rooms/ }).selectOption("")
    await expect(cell(ladder(page), "Infant 0–2.99 · P1")).not.toHaveAttribute("data-issue", /.+/)
    // the 2A+2C party's issue focuses its card, from a collapsed section too
    await page.getByRole("button", { name: "Occupancy & child pricing" }).click()
    await expect(card).toBeHidden()
    await chip(page).click()
    await checkPopover(page).getByRole("button", { name: new RegExp(`${esc(STD)} 2A\\+2C \\[Infant 0–2\\.99\\]`) }).click()
    await expect(card).toBeFocused()
    expect(await description(card)).toContain("Warning:")
    noErrors()
  })

  test("4. overlapping periods mark both headers; twin 3rd-adult rules mark the ladder cell; a click focuses the header", async ({ page }) => {
    const noErrors = trackErrors(page)
    await open(page, (data) => {
      const p = data.periods as Record<string, unknown>[]
      p[2] = { ...p[2], start_date: `${Y}-05-20` }
      data.occupancy_rules.push(occ({ target: "ADULT", position: 3, value: "0.75" }))
    })
    const h2 = page.locator('[data-cellid="period:P2"]')
    const h3 = page.locator('[data-cellid="period:P3"]')
    await expect(h2).toHaveAttribute("aria-invalid", "true")
    await expect(h2).toHaveAttribute("data-issue", "error")
    await expect(h3).toHaveAttribute("aria-invalid", "true")
    await expect(page.locator('[data-cellid="period:P1"]')).not.toHaveAttribute("aria-invalid", "true")
    expect(await description(h2)).toContain("Error: periods P2 and P3 overlap with equal priority")
    const a3 = cell(ladder(page), "3rd adult · All periods")
    await expect(a3).toHaveAttribute("aria-invalid", "true")
    expect(await description(a3)).toContain("share the same scope")
    await chip(page).click()
    await checkPopover(page).getByRole("button", { name: /PERIOD_OVERLAP/ }).click()
    await expect(h2).toBeFocused()
    await chip(page).click()
    await checkPopover(page).getByRole("button", { name: /OCC_DUPLICATE/ }).click()
    await expect(a3).toBeFocused()
    noErrors()
  })

  test("5. a published version: the stored report (Checked when published) anchors by saved row names; a click focuses the cell", async ({ page }) => {
    const noErrors = trackErrors(page)
    const d = await open(page, (data) => {
      // infants are priced by a band-less child rule: OCC_INFANT_GENERIC names that rule (a warning)
      data.occupancy_rules = [...(data.occupancy_rules as Record<string, unknown>[]).filter((r) => r.age_band !== "INF"), occ({ target: "CHILD", value: "0.4" })]
    })
    await api(page.request, "kamra.tex.api.contracts.publish_version", { name: d.version })
    const v = await api<{ validation_report?: unknown; occupancy_rules: { name: string; target: string; age_band: string | null }[] }>(page.request, "kamra.tex.api.contracts.get_version", { name: d.version })
    const generic = v.occupancy_rules.find((r) => r.target === "CHILD" && !r.age_band)
    expect(JSON.stringify(v.validation_report)).toContain(generic?.name ?? "missing")
    const calls: string[] = []
    page.on("request", (r) => {
      const m = /kamra\.tex\.api\.contracts\.(\w+)/.exec(r.url())
      if (m) calls.push(m[1])
    })
    await page.reload()
    await expect(matrix(page)).toBeVisible()
    const saved = page.getByRole("button", { name: /^Checked when published/ })
    await expect(saved).toContainText(/warning/)
    const any = cell(ladder(page), "Every child (any age band) · All periods")
    await expect(any).toHaveAttribute("data-issue", "warning")
    expect(await description(any)).toContain("Warning: no rule names infant band Infant 0–2.99")
    await saved.click()
    await page.getByRole("dialog", { name: "Checked when published" }).getByRole("button", { name: /OCC_INFANT_GENERIC/ }).click()
    await expect(any).toBeFocused()
    expect(calls.filter((c) => c === "validate_version")).toHaveLength(0)
    noErrors()
  })
})
