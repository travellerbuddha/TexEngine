// Special combinations in the Pricing Workspace (PRICING_WORKSPACE_UX.md §3.7; slice S12 and its
// review follow-up): the 2A+2C card built in the structured builder with band labels, Edit and
// Remove as one undoable entry, the quick chips a room can or cannot host, rooms × periods cards,
// any children, the twin refusal, All-rooms and one-room cards kept apart, cards the builder cannot
// express, and a read-only published version.
import { expect, test, type Page } from "@playwright/test"
import { api, login, trackErrors } from "./helpers"
import { archiveAll, CAP, DLX, N, newDraft as draftOf, ownerBands, ownerRates, periods, STD, SUP, versionPath, watchContracts, type Data } from "./flows/workspace"

test.use({ locale: "en-US", actionTimeout: 15_000, navigationTimeout: 30_000 })

const made: string[] = []
const bb = [{ board: "BB", is_base: 1, op: "ADD", adult_amount: null, child_percent: "50", infant_free: 1 }]
const BANDS = ownerBands()
const RULES = [
  { target: "ADULT", position: 3, op: "MULTIPLY", value: "0.7" },
  { target: "CHILD", age_band: "INF", op: "MULTIPLY", value: "0" },
  { target: "CHILD", age_band: "CHA", op: "MULTIPLY", value: "0.25" },
  { target: "CHILD", age_band: "CHB", op: "MULTIPLY", value: "0.5" },
]

/** The owner's draft: three rooms (Standard's capacity overridable), P1–P4, the prices, bands and
 * rules, BB, plus `extra`. */
function newDraft(page: Page, opts: { stdCap?: Record<string, number>; extra?: Data } = {}) {
  return draftOf(page, "E2E-PWC", {
    rooms: [
      { room_type: STD, is_base: 1, ...CAP, ...(opts.stdCap ?? {}) },
      { room_type: SUP, is_base: 0, ...CAP },
      { room_type: DLX, is_base: 0, ...CAP },
    ],
    periods: periods(),
    period_rates: ownerRates(),
    boards: bb,
    age_bands: BANDS,
    occupancy_rules: RULES,
    ...(opts.extra ?? {}),
  })
}

async function open(page: Page, opts: Parameters<typeof newDraft>[1] = {}) {
  await login(page, "revenue@demo.tex")
  const d = await newDraft(page, opts)
  made.push(d.contract)
  await page.goto(versionPath(d, "#occupancy"))
  await expect(page.getByRole("grid", { name: "Occupancy and child pricing by period" })).toBeVisible()
  return d
}

/** Two rooms and two periods with the bands and rules, plus `extraRules` (the review's draft). */
async function openReview(page: Page, extraRules: Record<string, unknown>[] = []) {
  await login(page, "revenue@demo.tex")
  const d = await draftOf(page, "E2E-PWC", {
    rooms: [
      { room_type: STD, is_base: 1, ...CAP },
      { room_type: SUP, is_base: 0, ...CAP },
    ],
    periods: periods().slice(0, 2),
    period_rates: ownerRates().filter((r) => r.room_type === SUP || r.period_code === "P1" || r.period_code === "P2"),
    boards: bb,
    age_bands: BANDS,
    occupancy_rules: [...RULES, ...extraRules],
  })
  made.push(d.contract)
  await page.goto(versionPath(d, "#occupancy"))
  await expect(page.getByRole("grid", { name: "Occupancy and child pricing by period" })).toBeVisible()
  return d
}

const combos = (page: Page) => page.getByRole("region", { name: /^Special combinations/ })
const builder = (page: Page) => page.getByRole("group", { name: /special combination/ })
const card = (page: Page, combination: string) => page.locator(`[data-card][data-combination="${combination}"]`)
const cards = card

async function build2A2C(page: Page) {
  await combos(page).getByRole("button", { name: "Add combination" }).click()
  const b = builder(page)
  await expect(b).toBeVisible()
  await expect(page.locator('[aria-modal="true"]')).toHaveCount(0)
  await expect(b.getByRole("spinbutton", { name: "Adults" })).toBeFocused()
  await b.getByRole("button", { name: "2A+2C", exact: true }).click()
  await expect(b.getByRole("button", { name: "2A+2C", exact: true })).toHaveAttribute("aria-pressed", "true")
  await b.getByLabel("Age band: Child 1 (oldest)").selectOption({ label: "Child 7–11.99" })
  await b.getByLabel("Value: Child 1 (oldest)").fill("x0.5")
  await expect(b.getByLabel("Rule: Child 1 (oldest)")).toHaveValue("MULTIPLY")
  await b.getByLabel("Age band: Child 2 (youngest)").selectOption({ label: "Child 3–6.99" })
  await b.getByLabel("Value: Child 2 (youngest)").fill("0.25")
  await expect(b).toContainText("Reads: 2 Adults + 2 Children → Child 1 ×0.50 · Child 2 ×0.25")
  await expect(b).toContainText("Child 1: Child 7–11.99 · Child 2: Child 3–6.99 · All rooms · All periods")
  await b.getByRole("button", { name: "Save combination" }).click()
  await expect(b).toHaveCount(0)
}

async function add2A2C(page: Page, room: string | null) {
  await combos(page).getByRole("button", { name: "Add combination" }).click()
  const b = builder(page)
  await b.getByRole("button", { name: "2A+2C", exact: true }).click()
  if (room) {
    await b.getByRole("group", { name: "Rooms" }).getByRole("radio", { name: "Chosen rooms" }).click()
    await b.getByRole("group", { name: "Chosen rooms" }).getByLabel(room).check()
  }
  await b.getByLabel("Age band: Child 1 (oldest)").selectOption({ label: "Child 7–11.99" })
  await b.getByLabel("Value: Child 1 (oldest)").fill("x0.5")
  await expect(b.getByRole("button", { name: "Save combination" })).toBeEnabled()
  await b.getByRole("button", { name: "Save combination" }).click()
  await expect(b).toHaveCount(0)
}

test.afterAll(async ({ browser }) => archiveAll(browser, made, "pricing workspace combinations e2e clean-up"))

test.describe("special combinations", () => {
  test("1. build 2A+2C (C1 7–11.99 ×0.50, C2 3–6.99 ×0.25): the card text with labels, no codes; get_version after Save", async ({ page }) => {
    const noErrors = trackErrors(page)
    const calls = watchContracts(page)
    const d = await open(page)
    await expect(combos(page)).toContainText("No special combinations")
    await build2A2C(page)
    const c = card(page, "2+2")
    await expect(c).toBeFocused()
    await expect(c.locator("p").first()).toHaveText("2 Adults + 2 Children → Child 1 ×0.50 · Child 2 ×0.25")
    await expect(c.locator("p").nth(1)).toHaveText("Child 1: Child 7–11.99 · Child 2: Child 3–6.99 · All rooms · All periods")
    await expect(c).not.toContainText("◆")
    await expect(page.getByTestId("undo-toast")).toContainText("Combination applied: 2 Adults + 2 Children")
    await expect(page.getByText(/\b(INF|CHA|CHB)\b/)).toHaveCount(0)
    expect(calls.count("save_version")).toBe(0)
    // Save: ordinary occupancy rules
    await page.getByRole("button", { name: /^Save/ }).first().click()
    await expect(page.getByText("Draft saved")).toBeVisible()
    const v = await api<{ occupancy_rules: Record<string, unknown>[] }>(page.request, "kamra.tex.api.contracts.get_version", { name: d.version })
    const combo = v.occupancy_rules.filter((r) => r.combination).map((r) => `${r.target}:${r.position}:${r.age_band}:${r.combination}:${r.room_type || ""}:${r.period_code || ""}:${r.op}:${Number(r.value)}:${r.is_override}`)
    expect(combo.sort()).toEqual(["CHILD:1:CHB:2+2:::MULTIPLY:0.5:0", "CHILD:2:CHA:2+2:::MULTIPLY:0.25:0"])
    // the ⓘ note on the CHB row links to the card
    const ladder = page.getByRole("grid", { name: "Occupancy and child pricing by period" })
    await ladder.getByRole("gridcell", { name: /^Child 7–11\.99 · P2: / }).click()
    await expect(ladder.getByRole("gridcell", { name: /^Child 7–11\.99 · P2: / })).toHaveAttribute("aria-label", /2 Adults \+ 2 Children/)
    const show = page.getByRole("button", { name: "Show combination 2 Adults + 2 Children" })
    await expect(show).toBeVisible()
    await show.click()
    await expect(card(page, "2+2")).toBeFocused()
    noErrors()
  })

  test("2. Edit replaces exactly the card's rows (one entry, Undo); Remove and its Undo", async ({ page }) => {
    const noErrors = trackErrors(page)
    await open(page, {
      extra: {
        occupancy_rules: [
          ...RULES,
          { target: "CHILD", position: 1, age_band: "CHB", combination: "2+2", op: "MULTIPLY", value: "0.5" },
          { target: "CHILD", position: 2, age_band: "CHA", combination: "2+2", op: "MULTIPLY", value: "0.25" },
          { target: "COMBINATION", combination: "3+0", op: "MULTIPLY", value: "2.5", note: "promo" },
        ],
      },
    })
    const c = card(page, "2+2")
    await expect(c.locator("p").first()).toHaveText("2 Adults + 2 Children → Child 1 ×0.50 · Child 2 ×0.25")
    // the 3+0 card has a note: edited in the rule tables
    await expect(card(page, "3+0")).toContainText("3 Adults → Whole party ×2.50")
    await expect(card(page, "3+0").getByRole("link", { name: "Edit in rule tables" })).toHaveAttribute("href", "#rules/occupancy")
    // saved as it was: no history entry, no toast; the focus goes back to Edit
    await c.getByRole("button", { name: "Edit combination: 2 Adults + 2 Children" }).click()
    const b = builder(page)
    await b.getByRole("button", { name: "Save combination" }).click()
    await expect(b).toHaveCount(0)
    await expect(page.getByTestId("undo-toast")).toHaveCount(0)
    await expect(c.getByRole("button", { name: "Edit combination: 2 Adults + 2 Children" })).toBeFocused()
    await c.getByRole("button", { name: "Edit combination: 2 Adults + 2 Children" }).click()
    await expect(b.getByLabel("Value: Child 2 (youngest)")).toHaveValue("0.25")
    await expect(b.getByLabel("Age band: Child 1 (oldest)")).toHaveValue("CHB")
    await b.getByLabel("Value: Child 2 (youngest)").fill("x0.3")
    await b.getByRole("button", { name: "Save combination" }).click()
    await expect(card(page, "2+2").locator("p").first()).toHaveText("2 Adults + 2 Children → Child 1 ×0.50 · Child 2 ×0.30")
    await expect(page.locator("[data-card]")).toHaveCount(2)
    // the toast's Undo puts the card back
    await page.getByTestId("undo-toast").getByRole("button", { name: "Undo" }).click()
    await expect(card(page, "2+2").locator("p").first()).toHaveText("2 Adults + 2 Children → Child 1 ×0.50 · Child 2 ×0.25")
    // Remove, then Undo
    await card(page, "2+2").getByRole("button", { name: "Remove combination: 2 Adults + 2 Children" }).click()
    await expect(card(page, "2+2")).toHaveCount(0)
    await expect(card(page, "3+0").getByRole("link", { name: "Edit in rule tables" })).toBeFocused()
    await page.getByTestId("undo-toast").getByRole("button", { name: "Undo" }).click()
    await expect(card(page, "2+2")).toHaveCount(1)
    noErrors()
  })

  test("3. a room with max_children 1 greys out 2A+2C (tooltip names the rooms that can); rooms × periods give one ◆ card", async ({ page }) => {
    const noErrors = trackErrors(page)
    await open(page, { stdCap: { max_children: 1, max_occupants: 4 } })
    await combos(page).getByRole("button", { name: "Add combination" }).click()
    const b = builder(page)
    // all rooms: some room hosts 2A+2C
    await expect(b.getByRole("button", { name: "2A+2C", exact: true })).not.toHaveAttribute("aria-disabled", "true")
    await b.getByRole("group", { name: "Rooms" }).getByRole("radio", { name: "Chosen rooms" }).click()
    await b.getByRole("group", { name: "Chosen rooms" }).getByLabel(N.STD).check()
    const chip = b.getByRole("button", { name: "2A+2C", exact: true })
    await expect(chip).toHaveAttribute("aria-disabled", "true")
    await chip.hover()
    await expect(page.getByRole("tooltip")).toHaveText(`2 Adults + 2 Children: no room in scope can host it. Rooms that can: ${N.SUP}, ${N.DLX}.`)
    await chip.click({ force: true })
    await expect(chip).toHaveAttribute("aria-pressed", "false")
    // Standard and Garden Villa × P1, P2, with an adult and a whole-party rule
    await b.getByRole("group", { name: "Chosen rooms" }).getByLabel(N.DLX).check()
    await expect(chip).not.toHaveAttribute("aria-disabled", "true")
    await b.getByRole("button", { name: "3A+1C", exact: true }).click()
    await b.getByRole("group", { name: "Periods" }).getByRole("radio", { name: "Chosen periods" }).click()
    await b.getByRole("group", { name: "Chosen periods" }).getByLabel("P1 · Apr").check()
    await b.getByRole("group", { name: "Chosen periods" }).getByLabel("P2 · May").check()
    await b.getByLabel("Value: Child 1 (oldest)").fill("50%")
    await expect(b.getByLabel("Rule: Child 1 (oldest)")).toHaveValue("PERCENT_OF")
    await b.getByRole("button", { name: "Adult rule" }).click()
    await b.getByLabel("Value: Adult 3").fill("0.6")
    await b.getByRole("button", { name: "Price for the whole party" }).click()
    await b.getByLabel("Rule: Whole party").selectOption("ADJUST_PERCENT")
    await b.getByLabel("Value: Whole party").fill("-5")
    await expect(b).toContainText("Per night, what its guests pay together changes by −5%.")
    await expect(b).toContainText("Reads: 3 Adults + 1 Child → Adult 3 ×0.60 · Child 1 50% · Whole party −5%")
    await expect(b.getByRole("combobox", { name: "Which adult" })).toHaveValue("3")
    await b.getByRole("button", { name: "Save combination" }).click()
    const c = card(page, "3+1")
    await expect(c).toHaveCount(1)
    await expect(c).toContainText("◆ by period")
    await expect(c.locator("p").nth(1)).toHaveText(`Child 1: Any age · ${N.STD}, ${N.DLX} · P1, P2`)
    // phones: the open builder does not make the page scroll sideways; Enter in a value saves
    await c.getByRole("button", { name: "Edit combination: 3 Adults + 1 Child" }).click()
    await page.setViewportSize({ width: 375, height: 800 })
    await expect(b.getByLabel("Value: Child 1 (oldest)")).toHaveValue("50")
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1)).toBe(true)
    await b.getByLabel("Value: Child 1 (oldest)").fill("40")
    await b.getByLabel("Value: Child 1 (oldest)").press("Enter")
    await expect(card(page, "3+1").locator("p").first()).toHaveText("3 Adults + 1 Child → Adult 3 ×0.60 · Child 1 40% · Whole party −5%")
    noErrors()
  })

  test("4. any children (2+*) under More; the builder refuses a twin of another card", async ({ page }) => {
    const noErrors = trackErrors(page)
    await open(page, { extra: { occupancy_rules: [...RULES, { target: "CHILD", position: 1, age_band: "CHB", combination: "2+2", op: "MULTIPLY", value: "0.5" }] } })
    await combos(page).getByRole("button", { name: "Add combination" }).click()
    const b = builder(page)
    await b.getByText("More").click()
    await b.getByLabel(/^Any number of children/).check()
    await expect(b.getByRole("spinbutton", { name: "Children" })).toBeDisabled()
    // any children: another child position, and taking it away again
    await b.getByRole("button", { name: "Rule for another child" }).click()
    await expect(b.getByLabel("Value: Child 2")).toBeVisible()
    await b.getByRole("button", { name: "Remove: Child 2" }).click()
    await expect(b.getByLabel("Value: Child 2")).toHaveCount(0)
    await b.getByLabel("Value: Child 1 (oldest)").fill("x0.4")
    await expect(b).toContainText("Reads: 2 Adults + any children → Child 1 ×0.40")
    await b.getByRole("button", { name: "Save combination" }).click()
    await expect(card(page, "2+*").locator("p").first()).toHaveText("2 Adults + any children → Child 1 ×0.40")
    // a twin of the 2+2 card's CHB rule is refused, naming that card
    await combos(page).getByRole("button", { name: "Add combination" }).click()
    await b.getByRole("button", { name: "2A+2C", exact: true }).click()
    await b.getByLabel("Age band: Child 1 (oldest)").selectOption({ label: "Child 7–11.99" })
    await b.getByLabel("Value: Child 1 (oldest)").fill("x0.45")
    await expect(b).toContainText("2 Adults + 2 Children already has a rule for Child 1 (oldest) in these rooms and periods.")
    await expect(b.getByRole("button", { name: "Save combination" })).toBeDisabled()
    await b.getByRole("button", { name: "Cancel" }).click()
    await expect(combos(page).getByRole("button", { name: "Add combination" })).toBeFocused()
    noErrors()
  })

  test("5. a published version: cards without Add, Edit or Remove", async ({ page }) => {
    const noErrors = trackErrors(page)
    await login(page, "revenue@demo.tex")
    const d = await newDraft(page, { extra: { occupancy_rules: [...RULES, { target: "CHILD", position: 1, age_band: "CHB", combination: "2+2", op: "MULTIPLY", value: "0.5" }] } })
    made.push(d.contract)
    await api(page.request, "kamra.tex.api.contracts.publish_version", { name: d.version })
    await page.goto(versionPath(d, "#occupancy"))
    await expect(card(page, "2+2").locator("p").first()).toHaveText("2 Adults + 2 Children → Child 1 ×0.50")
    await expect(combos(page).getByRole("button", { name: "Add combination" })).toHaveCount(0)
    await expect(card(page, "2+2").getByRole("button")).toHaveCount(0)
    await page.setViewportSize({ width: 375, height: 800 })
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1)).toBe(true)
    noErrors()
  })
})

test.describe("All-rooms and one-room cards, cards for the rule tables (review follow-up)", () => {
  test("R1. the same 2+2 rule for All rooms and for Standard: two cards, each saved unchanged keeps both rows", async ({ page }) => {
    const noErrors = trackErrors(page)
    const d = await openReview(page)
    await add2A2C(page, null)
    await add2A2C(page, N.STD)
    const both = cards(page, "2+2")
    await expect(both).toHaveCount(2)
    const all = both.filter({ hasText: "All rooms · All periods" })
    const std = both.filter({ hasText: `${N.STD} · All periods` })
    await expect(all.locator("p").nth(1)).toHaveText("Child 1: Child 7–11.99 · All rooms · All periods")
    await expect(std.locator("p").nth(1)).toHaveText(`Child 1: Child 7–11.99 · ${N.STD} · All periods`)
    await page.getByTestId("undo-toast").getByRole("button", { name: "Close" }).click()
    await expect(page.getByTestId("undo-toast")).toHaveCount(0)
    for (const c of [std, all]) {
      await c.getByRole("button", { name: "Edit combination: 2 Adults + 2 Children" }).click()
      const b = builder(page)
      await expect(b.getByLabel("Value: Child 1 (oldest)")).toHaveValue("0.5")
      await b.getByRole("button", { name: "Save combination" }).click()
      await expect(b).toHaveCount(0)
      await expect(cards(page, "2+2")).toHaveCount(2)
      // saved unchanged: nothing recorded, no toast
      await expect(page.getByTestId("undo-toast")).toHaveCount(0)
    }
    await expect(std).toHaveCount(1)
    await expect(all).toHaveCount(1)
    await page.getByRole("button", { name: /^Save/ }).first().click()
    await expect(page.getByText("Draft saved")).toBeVisible()
    const v = await api<{ occupancy_rules: Record<string, unknown>[] }>(page.request, "kamra.tex.api.contracts.get_version", { name: d.version })
    const combo = v.occupancy_rules.filter((r) => r.combination).map((r) => `${r.target}:${r.position}:${r.age_band}:${r.combination}:${r.room_type || ""}:${r.period_code || ""}:${r.op}:${Number(r.value)}`)
    expect(combo.sort()).toEqual(["CHILD:1:CHB:2+2:::MULTIPLY:0.5", `CHILD:1:CHB:2+2:${STD}::MULTIPLY:0.5`])
    noErrors()
  })

  test("R2. ADD -5 is edited in the rule tables; the twin message and the value hint", async ({ page }) => {
    const noErrors = trackErrors(page)
    await openReview(page, [
      { target: "CHILD", position: 1, combination: "2+1", op: "ADD", value: "-5" },
      { target: "CHILD", position: 1, combination: "2+2", op: "ADJUST_PERCENT", value: "-5" },
    ])
    await expect(cards(page, "2+1").getByRole("link", { name: "Edit in rule tables" })).toHaveAttribute("href", "#rules/occupancy")
    await expect(cards(page, "2+1").getByRole("button", { name: /^Edit combination/ })).toHaveCount(0)
    await expect(cards(page, "2+2").getByRole("button", { name: "Edit combination: 2 Adults + 2 Children" })).toBeVisible()
    await combos(page).getByRole("button", { name: "Add combination" }).click()
    const b = builder(page)
    await expect(b).toContainText("In Value, a number alone takes the rule chosen, and so does a signed number under Plus/minus %.")
    await b.getByRole("button", { name: "2A+1C", exact: true }).click()
    await b.getByLabel("Value: Child 1 (oldest)").fill("x0.4")
    await expect(b).toContainText("2 Adults + 1 Child already has a rule for Child 1 (oldest) in these rooms and periods.")
    await expect(b.getByRole("button", { name: "Save combination" })).toBeDisabled()
    noErrors()
  })
})
