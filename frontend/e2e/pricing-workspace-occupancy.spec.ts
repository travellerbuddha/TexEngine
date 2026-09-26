// Occupancy & child pricing in the Pricing Workspace (PRICING_WORKSPACE_UX.md §3.6, §3.8, §3.11;
// slice S11): the ladder's OVERRIDE and engine-default cells, the child ages drawer (bands with
// labels, never codes), band rules typed down the rows, the server-resolved line for a sample party,
// the ROOM basis labels, #ages / #occupancy, the rule popover with Always wins, and a read-only
// published version. Every test starts from its own API-made draft of the owner's prices.
import { expect, test, type Page } from "@playwright/test"
import { login, pageApiOk, trackErrors } from "./helpers"
import { archiveAll, newDraft as draftOf, N, ownerRates, periods, rooms, versionPath, watchContracts, type Data } from "./flows/workspace"

test.use({ locale: "en-US", actionTimeout: 15_000, navigationTimeout: 30_000 })

const made: string[] = []
const bb = [{ board: "BB", is_base: 1, op: "ADD", adult_amount: null, child_percent: "50", infant_free: 1 }]

/** Rooms with capacity (4 adults, 2 children), P1–P4, the owner's prices, BB, plus `extra`. */
const newDraft = (page: Page, extra: Data = {}) => draftOf(page, "E2E-PWO", { rooms: rooms(), periods: periods(), period_rates: ownerRates(), boards: bb, ...extra })

async function open(page: Page, hash = "#pricing", extra: Data = {}) {
  await login(page, "revenue@demo.tex")
  const d = await newDraft(page, extra)
  made.push(d.contract)
  await page.goto(versionPath(d, hash))
  await expect(page.getByRole("grid", { name: "Room prices by period" })).toBeVisible()
  return d
}

const ladder = (page: Page) => page.getByRole("grid", { name: "Occupancy and child pricing by period" })
/** A ladder cell by "{slot} · {period}" (its accessible name starts so). */
const lcell = (page: Page, slot: string, period: string) => ladder(page).getByRole("gridcell", { name: new RegExp(`^${slot.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")} · ${period}: `) })
/** What the cell shows (its content, not its tooltip). */
const shown = (page: Page, slot: string, period: string) => lcell(page, slot, period).locator(":scope > span").first()

test.describe.serial("occupancy & child pricing", () => {
  test.afterAll(async ({ browser }) => archiveAll(browser, made, "pricing workspace occupancy e2e clean-up"))

  test("1-7. OVERRIDE, ×1.00 default, No rule · not sellable, bands with saved labels, band rules down with Enter, the resolved line, ROOM labels", async ({ page }) => {
    const noErrors = trackErrors(page)
    const calls = watchContracts(page)
    const d = await open(page)
    // a draft without occupancy rules opens the section
    await expect(ladder(page)).toBeVisible()
    await expect(page.getByRole("button", { name: "Occupancy & child pricing" })).toHaveAttribute("aria-expanded", "true")
    // PERSON: the BASE pair reads "×1.00 each (default) = 2 × base person price"
    await expect(ladder(page).getByRole("rowheader").filter({ hasText: /^2 Adults/ })).toContainText("×1.00 each (default) = 2 × base person price")
    // 2. the 4th adult row shows ×1.00 default (the server's value)
    await expect(shown(page, "4th adult", "All periods")).toHaveText("×1.00 default")
    await expect(shown(page, "4th adult", "P3")).toHaveText("×1.00 default")

    // 1. 3rd adult ×0.70 for all periods, ×0.80 in P4 → ◆ OVERRIDE
    await lcell(page, "3rd adult", "All periods").click()
    await page.keyboard.type("x0.70")
    await expect(page.getByRole("status").filter({ hasText: "3rd adult · All periods pays ×0.70 of the base person price" })).toBeVisible()
    await page.keyboard.press("Enter")
    await lcell(page, "3rd adult", "P4").click()
    await page.keyboard.type("x0.80")
    await page.keyboard.press("Enter")
    await expect(shown(page, "3rd adult", "All periods")).toHaveText("×0.70")
    await expect(shown(page, "3rd adult", "P2")).toHaveText("↳ ×0.70")
    await expect(shown(page, "3rd adult", "P4")).toHaveText(/^◆ ×0\.80\s*OVERRIDE$/)
    await expect(lcell(page, "3rd adult", "P4")).toHaveAttribute("aria-label", /3rd adult · P4: period override, ×0\.80/)

    // 4. the child ages drawer: 2.99 / 6.99 / 11.99, not modal
    await page.getByRole("button", { name: "Child ages…" }).click()
    const drawer = page.getByRole("dialog", { name: "Child age bands" })
    await expect(drawer).toBeVisible()
    await expect(page.locator('[aria-modal="true"]')).toHaveCount(0)
    await drawer.getByRole("button", { name: "Add age band" }).click()
    await expect(drawer.getByLabel("Up to (not incl.) age: new band")).toBeFocused()
    await expect(drawer.getByLabel("From age: new band")).toHaveValue("0")
    await page.keyboard.type("2.99")
    await page.keyboard.press("Enter")
    await expect(drawer.getByLabel("From age: new band")).toHaveValue("3")
    await expect(drawer.getByLabel("Up to (not incl.) age: new band")).toBeFocused()
    await page.keyboard.type("6.99")
    await page.keyboard.press("Enter")
    await expect(drawer.getByLabel("From age: new band")).toHaveValue("7")
    await page.keyboard.type("11.99")
    await page.keyboard.press("Enter")
    await expect(drawer.getByLabel("Label: Infant 0–2.99")).toHaveValue("Infant 0–2.99")
    await expect(drawer.getByLabel("Infant band: Infant 0–2.99")).toBeChecked()
    await expect(drawer.getByLabel("Label: Child 3–6.99")).toHaveValue("Child 3–6.99")
    await expect(drawer.getByLabel("Infant band: Child 3–6.99")).not.toBeChecked()
    await expect(drawer.getByLabel("Label: Child 7–11.99")).toHaveValue("Child 7–11.99")
    await expect(drawer).toContainText("No gaps or overlaps")
    // the page stays usable beside the drawer; Escape inside closes it (the empty new band goes)
    await page.keyboard.press("Escape")
    await expect(drawer).toBeHidden()
    // reopened: the three bands, the uncommitted fourth is gone
    await page.getByRole("button", { name: "Child ages…" }).click()
    await expect(drawer.getByLabel(/^Up to \(not incl\.\) age:/)).toHaveCount(3)
    await drawer.getByRole("button", { name: "Close" }).click()
    await expect(drawer).toBeHidden()
    await expect(page.getByRole("button", { name: "Child ages…" })).toBeFocused()
    // 3. band rows without a rule: No rule · not sellable
    for (const band of ["Infant 0–2.99", "Child 3–6.99", "Child 7–11.99"]) await expect(shown(page, band, "P1")).toHaveText("No rule · not sellable")
    // no band code is visible anywhere
    await expect(page.getByText(/\b(INF|CHA|CHB)\b/)).toHaveCount(0)

    // 5. band rules x0 / x0.25 / x0.5 down the rows with Enter
    await lcell(page, "Infant 0–2.99", "All periods").click()
    await page.keyboard.type("x0")
    await page.keyboard.press("Enter")
    await expect(lcell(page, "Child 3–6.99", "All periods")).toBeFocused()
    await page.keyboard.type("x0.25")
    await page.keyboard.press("Enter")
    await expect(lcell(page, "Child 7–11.99", "All periods")).toBeFocused()
    await page.keyboard.type("x0.5")
    await page.keyboard.press("Enter")
    await expect(shown(page, "Infant 0–2.99", "All periods")).toHaveText("×0.00")
    await expect(shown(page, "Child 3–6.99", "All periods")).toHaveText("×0.25")
    await expect(shown(page, "Child 7–11.99", "All periods")).toHaveText("×0.50")
    await expect(shown(page, "Child 7–11.99", "P3")).toHaveText("↳ ×0.50")
    await expect(page.getByText(/\b(INF|CHA|CHB)\b/)).toHaveCount(0)

    // 6. the resolved line for Standard, 2 adults + 1 child 7–11.99
    const party = ladder(page).getByRole("combobox", { name: "Sample party" })
    await expect(ladder(page).getByRole("rowheader").filter({ hasText: `Resolved · ${N.STD}` })).toBeVisible()
    await party.selectOption({ label: "2 adults + 1 child (Child 7–11.99)" })
    for (const [p, v] of [["P1", "175.00"], ["P2", "200.00"], ["P3", "250.00"], ["P4", "325.00"]])
      await expect(lcell(page, `Resolved · ${N.STD}`, p)).toHaveAttribute("aria-label", `Resolved · ${N.STD} · ${p}: resolved occupancy total, EUR ${v}`)
    // the server priced it: price_matrix got the party; no save was made
    const withParty = calls.bodies("price_matrix").filter((b) => JSON.stringify(b).includes('"party_room"'))
    expect(withParty.length).toBeGreaterThan(0)
    expect(JSON.stringify(withParty.at(-1))).toContain('"children":["CHB"]')
    expect(calls.count("save_version")).toBe(0)

    // save: the bands carry their labels
    await page.getByRole("button", { name: /^Save/ }).click()
    await expect(page.getByText("Draft saved")).toBeVisible()
    const v = await pageApiOk<{ age_bands: { band_code: string; label: string; from_age: number; to_age: number; is_infant: number }[]; occupancy_rules: Record<string, unknown>[] }>(page, "kamra.tex.api.contracts.get_version", { name: d.version })
    expect(v.age_bands.map((b) => [b.band_code, b.label, String(b.from_age), String(b.to_age), b.is_infant])).toEqual([
      ["INF", "Infant 0–2.99", "0", "2.99", 1],
      ["CHA", "Child 3–6.99", "3", "6.99", 0],
      ["CHB", "Child 7–11.99", "7", "11.99", 0],
    ])
    const rules = v.occupancy_rules.map((r) => `${r.target}:${r.position}:${r.age_band || ""}:${r.period_code || ""}:${r.op}:${Number(r.value)}`).sort()
    expect(rules).toEqual(["ADULT:3:::MULTIPLY:0.7", "ADULT:3::P4:MULTIPLY:0.8", "CHILD:0:CHA::MULTIPLY:0.25", "CHILD:0:CHB::MULTIPLY:0.5", "CHILD:0:INF::MULTIPLY:0"])

    // 7. switch the (unpublished) contract to ROOM basis in the header popover: the labels change
    await page.getByRole("button", { name: "Pricing basis: Per person" }).click()
    await page.getByRole("dialog", { name: "Pricing basis" }).getByRole("radio", { name: "Per room" }).click()
    await page.getByRole("dialog", { name: "Pricing basis" }).getByRole("button", { name: "Apply" }).click()
    await expect(page.getByRole("button", { name: "Pricing basis: Per room" })).toBeVisible()
    await expect(ladder(page).getByRole("rowheader").filter({ hasText: "Single use (1 adult)" })).toBeVisible()
    await expect(ladder(page).getByRole("rowheader").filter({ hasText: "Extra adult (3rd)" })).toContainText("from the per-person share (room ÷ 2)")
    await expect(shown(page, "1st adult", "P1")).toHaveText("included in the room price")
    await expect(shown(page, "Extra adult (4th)", "P1")).toHaveText("×1.00 default")
    await expect(ladder(page).getByRole("rowheader").filter({ hasText: /^2 Adults/ })).toHaveCount(0)
    // extra adults priced from the room price: the unit words follow
    await page.getByRole("combobox", { name: "Extra adults priced from" }).selectOption("ROOM_PRICE")
    await expect(ladder(page).getByRole("rowheader").filter({ hasText: "Extra adult (3rd)" })).toContainText("from the room price")
    noErrors()
  })

  test("8. #ages opens the drawer, #occupancy opens a closed section; the collapsed summary; Name them", async ({ page }) => {
    const noErrors = trackErrors(page)
    const d = await open(page, "#ages", {
      age_bands: [
        { band_code: "INF", label: "", from_age: 0, to_age: 2.99, is_infant: 1 },
        { band_code: "CHD", label: "CHD", from_age: 3, to_age: 11.99, is_infant: 0 },
      ],
      occupancy_rules: [
        { target: "ADULT", position: 3, op: "MULTIPLY", value: "0.7" },
        { target: "CHILD", age_band: "CHD", op: "PERCENT_OF", value: "50" },
        { target: "CHILD", position: 1, age_band: "CHD", combination: "2+2", op: "MULTIPLY", value: "0.4" },
      ],
    })
    const drawer = page.getByRole("dialog", { name: "Child age bands" })
    await expect(drawer).toBeVisible()
    // bands saved without a name are not renamed silently: a notice offers it
    await expect(drawer).toContainText("2 bands have no name.")
    await expect(drawer.getByLabel("Label: Infant 0–2.99")).toHaveValue("")
    await drawer.getByRole("button", { name: "Name them" }).click()
    await expect(drawer.getByLabel("Label: Infant 0–2.99")).toHaveValue("Infant 0–2.99")
    await expect(drawer.getByLabel("Label: Child 3–11.99")).toHaveValue("Child 3–11.99")
    await expect(drawer).not.toContainText("have no name")
    // codes only behind Advanced; a rename cascades to the rules
    await expect(drawer.getByLabel("Code: Child 3–11.99")).toHaveCount(0)
    await drawer.getByLabel("Advanced: show band codes").check()
    const code = drawer.getByLabel("Code: Child 3–11.99")
    await code.fill("KID")
    await code.press("Enter")
    await drawer.getByLabel("Advanced: show band codes").uncheck()
    await drawer.getByRole("button", { name: "Close" }).click()
    await expect(drawer).toBeHidden()
    // the section is open (a draft with rules opens closed unless remembered; #ages did not open it)
    const toggle = page.getByRole("button", { name: "Occupancy & child pricing" })
    if ((await toggle.getAttribute("aria-expanded")) === "true") await toggle.click()
    await expect(toggle).toHaveAttribute("aria-expanded", "false")
    await expect(page.locator("section#occupancy")).toContainText("Adults: 3rd ×0.70 | Children: Child 3–11.99 50% | 1 special combination")
    // the precedence note (the 2+2 card prices child 1 of 3–11.99), then #occupancy opens it again
    await page.evaluate(() => (window.location.hash = "#occupancy"))
    await expect(toggle).toHaveAttribute("aria-expanded", "true")
    await expect(lcell(page, "Child 3–11.99", "P2")).toHaveAttribute("aria-label", /Special combinations win over period rules unless the rule is marked Always wins: 2 Adults \+ 2 Children/)
    const v = await pageApiOk<{ occupancy_rules: Record<string, unknown>[] }>(page, "kamra.tex.api.contracts.get_version", { name: d.version })
    expect(v.occupancy_rules.some((r) => r.age_band === "CHD")).toBe(true) // not saved yet
    noErrors()
  })

  test("9. the rule popover (Alt+Enter): Always wins and a note, one row per room; Undo restores the default", async ({ page }) => {
    const noErrors = trackErrors(page)
    await open(page)
    await lcell(page, "4th adult", "P2").click()
    await page.keyboard.press("Alt+Enter")
    const pop = page.getByRole("dialog", { name: "Edit rule: 4th adult · P2" })
    await expect(pop).toBeVisible()
    await pop.getByRole("textbox").first().fill("0.9")
    await pop.getByRole("radio", { name: "Chosen rooms" }).click()
    await pop.getByRole("checkbox", { name: N.SUP }).check()
    await pop.getByRole("checkbox", { name: "Always wins (override)" }).check()
    await expect(pop).toContainText("4th adult · P2 pays ×0.90 of the base person price")
    await pop.getByRole("button", { name: "Apply" }).click()
    await expect(pop).toBeHidden()
    // the All rooms scope still shows the default; the Family Suite scope shows the rule
    await expect(shown(page, "4th adult", "P2")).toHaveText("×1.00 default")
    await page.getByRole("combobox", { name: /^Rooms/ }).selectOption({ label: `${N.SUP} •` })
    await expect(shown(page, "4th adult", "P2")).toHaveText(/◆ ×0\.90\s*wins\s*OVERRIDE/)
    await lcell(page, "4th adult", "P2").click()
    await page.keyboard.press("Control+z")
    await expect(shown(page, "4th adult", "P2")).toHaveText("×1.00 default")
    // an invalid entry stays as an error draft; Escape drops it
    await page.keyboard.type("abc")
    await page.keyboard.press("Enter")
    await expect(page.getByRole("status").filter({ hasText: "Not a price or formula" })).toBeVisible()
    await page.keyboard.press("Escape")
    await expect(shown(page, "4th adult", "P2")).toHaveText("×1.00 default")
    noErrors()
  })

  test("10. a published version: the ladder and the drawer are read-only; the resolved line is priced from the frozen version", async ({ page }) => {
    const noErrors = trackErrors(page)
    const calls = watchContracts(page)
    await login(page, "revenue@demo.tex")
    const d = await newDraft(page, {
      age_bands: [
        { band_code: "INF", label: "Infant 0–2.99", from_age: 0, to_age: 2.99, is_infant: 1 },
        { band_code: "CHA", label: "Child 3–6.99", from_age: 3, to_age: 6.99, is_infant: 0 },
        { band_code: "CHB", label: "Child 7–11.99", from_age: 7, to_age: 11.99, is_infant: 0 },
      ],
      occupancy_rules: [
        { target: "ADULT", position: 3, op: "MULTIPLY", value: "0.7" },
        { target: "CHILD", age_band: "INF", op: "MULTIPLY", value: "0" },
        { target: "CHILD", age_band: "CHA", op: "MULTIPLY", value: "0.25" },
        { target: "CHILD", age_band: "CHB", op: "MULTIPLY", value: "0.5" },
      ],
    })
    made.push(d.contract)
    await pageApiOk(page, "kamra.tex.api.contracts.publish_version", { name: d.version })
    await page.goto(versionPath(d, "#occupancy"))
    await expect(ladder(page)).toBeVisible()
    await expect(ladder(page)).toHaveAttribute("aria-readonly", "true")
    await expect(ladder(page).getByRole("textbox")).toHaveCount(0)
    await expect(ladder(page).getByRole("button", { name: /^Edit rule:/ })).toHaveCount(0)
    await expect(shown(page, "3rd adult", "P2")).toHaveText("↳ ×0.70")
    await page.getByRole("combobox", { name: "Sample party" }).selectOption({ label: "2 adults + 1 child (Child 7–11.99)" })
    await expect(lcell(page, `Resolved · ${N.STD}`, "P4")).toHaveAttribute("aria-label", `Resolved · ${N.STD} · P4: resolved occupancy total, EUR 325.00`)
    expect(calls.count("validate_version")).toBe(0)
    await page.getByRole("button", { name: "Child ages…" }).click()
    const drawer = page.getByRole("dialog", { name: "Child age bands" })
    await expect(drawer.getByLabel("Label: Child 3–6.99")).toBeDisabled()
    await expect(drawer.getByRole("button", { name: "Add age band" })).toHaveCount(0)
    await expect(drawer.getByRole("switch", { name: /Children above/ })).toBeDisabled()
    // phones: the page does not scroll sideways
    await drawer.getByRole("button", { name: "Close" }).click()
    await page.setViewportSize({ width: 375, height: 800 })
    await expect(ladder(page)).toBeVisible()
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1)).toBe(true)
    noErrors()
  })
})
