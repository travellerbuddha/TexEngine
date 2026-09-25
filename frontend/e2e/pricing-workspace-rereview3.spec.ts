// The Pricing Workspace S16 third re-review (PRICING_WORKSPACE_UX.md §3.6.2, §3.7.4, §3.8, §3.13,
// §3.19): the single-use row leaves a special combination's rules alone (a builder's "1 adult + any
// children" card keeps its Adult 1 through a switch, and a write into its cell is refused), switches
// only the scope's own rules and never carries a relative rule into the other form; a keyboard undo
// that removes the focused row puts the focus back on the grid; a refused new child-age band keeps
// the tab from closing without asking; each grid's header-lane note says its own controls; a new
// period's dates hand the focus to its first cell; the Price test panel's nightly table fits it, and
// the panel lies over the page where the matrix could not keep columns beside it. Every test makes
// its own API draft of the owner's example.
import { expect, test, type Page } from "@playwright/test"
import { login, trackErrors } from "./helpers"
import { priceMatrix } from "./flows/contracts"
import { archiveAll, DLX, esc, N, newDraft, occ, ownerDraft, publish, versionPath, watchContracts, Y, type Data, type NewContract } from "./flows/workspace"

test.use({ locale: "en-US", actionTimeout: 15_000, navigationTimeout: 30_000 })

const made: string[] = []

async function open(page: Page, data: Data, o: { publish?: boolean } = {}): Promise<NewContract> {
  await login(page, "revenue@demo.tex")
  const d = await newDraft(page, "E2E-PWR3", data)
  made.push(d.contract)
  if (o.publish) await publish(page, d.version)
  await page.goto(versionPath(d, "#pricing"))
  await expect(page.getByRole("grid").first()).toBeVisible()
  return d
}

const ladder = (page: Page) => page.getByRole("grid", { name: "Occupancy and child pricing by period" })
const lcell = (page: Page, slot: string, period: string) => ladder(page).getByRole("gridcell", { name: new RegExp(`^${esc(slot)} · ${period}: `) })
const boards = (page: Page) => page.getByRole("grid", { name: "Board supplements by period" })
const cellOf = (page: Page, room: string, period: string) =>
  priceMatrix(page)
    .getByRole("gridcell", { name: new RegExp(`^${esc(room)} · ${period}: (?!resolved)`) })
    .first()

async function expand(page: Page, section: "occupancy" | "boards") {
  const toggle = page.locator(`section#${section} h2 button[aria-expanded]`)
  if ((await toggle.getAttribute("aria-expanded")) === "false") await toggle.click()
  await expect(toggle).toHaveAttribute("aria-expanded", "true")
}

/** The 1+0 / 1+* rules the last price_matrix call priced (target:combination:period:value). */
function singleUse(calls: ReturnType<typeof watchContracts>) {
  const body = calls.bodies("price_matrix").at(-1) as { data?: { occupancy_rules?: Record<string, unknown>[] } } | undefined
  return (body?.data?.occupancy_rules ?? [])
    .filter((r) => r.combination === "1+0" || r.combination === "1+*")
    .map((r) => `${r.target}:${r.combination}:${r.period_code || "ALL"}:${r.value}`)
    .sort()
}

const withRules = (...extra: Record<string, unknown>[]): Data => {
  const d = ownerDraft()
  d.occupancy_rules = [...d.occupancy_rules, ...extra]
  return d
}
/** The builder's "1 adult + any children" card: Adult 1 ×1.20 and Child 1 ×0.30, All rooms, All periods. */
const ANY_CHILDREN_CARD = [
  occ({ target: "ADULT", position: 1, combination: "1+*", value: "1.2" }),
  occ({ target: "CHILD", position: 1, combination: "1+*", value: "0.3" }),
]
const WHOLE = occ({ target: "COMBINATION", combination: "1+0", value: "1.5" })

async function popover(page: Page, slot: string, period: string) {
  await lcell(page, slot, period).click()
  await page.keyboard.press("Alt+Enter")
  const pop = page.getByRole("dialog", { name: `Edit rule: ${slot} · ${period}` })
  await expect(pop).toBeVisible()
  return pop
}

const focusedRole = (page: Page) => page.evaluate(() => (document.activeElement && document.activeElement !== document.body ? document.activeElement.getAttribute("role") : "body"))

test.describe("pricing workspace, S16 re-review 3", () => {
  test.afterAll(async ({ browser }) => archiveAll(browser, made, "pricing workspace re-review 3 e2e clean-up"))

  test("a '1 adult + any children' card keeps its rules when the single-use row switches form, both ways; a write into its cell is refused", async ({ page }) => {
    const noErrors = trackErrors(page)
    const calls = watchContracts(page)
    await open(page, withRules(...ANY_CHILDREN_CARD))
    await expand(page, "occupancy")
    // the card's Adult 1 is the card's: the row is the whole 1+0 combination, at its default
    await expect(ladder(page).getByRole("rowheader").filter({ hasText: /^1 Adult \(also with children\)/ })).toHaveCount(0)
    await expect(lcell(page, "1 Adult (single use)", "All periods")).toHaveAttribute("aria-label", /×1\.00/)
    let pop = await popover(page, "1 Adult (single use)", "P2")
    const box = pop.getByRole("checkbox", { name: "Also when children travel" })
    await expect(box).toHaveAccessibleDescription(/^Prices the adult of a room with one adult/)
    await box.check()
    await expect(box).toHaveAccessibleDescription(/The whole row switches/)
    await pop.getByRole("textbox").first().fill("1.5")
    await pop.getByRole("button", { name: "Apply" }).click()
    await expect(pop).toBeHidden()
    await expect.poll(() => singleUse(calls)).toEqual(["ADULT:1+*:ALL:1.2", "ADULT:1+*:P2:1.5", "CHILD:1+*:ALL:0.3"])
    await expect(lcell(page, "1 Adult (also with children)", "P2")).toHaveAttribute("aria-label", /×1\.50/)
    // and back from P2 (the review's case): the card still has its Adult 1 ×1.20
    pop = await popover(page, "1 Adult (also with children)", "P2")
    await pop.getByRole("checkbox", { name: "Also when children travel" }).uncheck()
    await pop.getByRole("textbox").first().fill("1.5")
    await pop.getByRole("button", { name: "Apply" }).click()
    await expect(pop).toBeHidden()
    await expect.poll(() => singleUse(calls)).toEqual(["ADULT:1+*:ALL:1.2", "CHILD:1+*:ALL:0.3", "COMBINATION:1+0:P2:1.5"])
    // switching All periods would write into the card's cell: said, and Apply waits
    pop = await popover(page, "1 Adult (single use)", "All periods")
    await pop.getByRole("checkbox", { name: "Also when children travel" }).check()
    await pop.getByRole("textbox").first().fill("1.4")
    const apply = pop.getByRole("button", { name: "Apply" })
    await expect(apply).toBeDisabled()
    await expect(pop).toContainText("A special combination has a rule for 1 adult")
    await expect(apply).toHaveAccessibleDescription(/A special combination has a rule for 1 adult/)
    await page.keyboard.press("Escape")
    await expect(pop).toBeHidden()
    await expect.poll(() => singleUse(calls)).toEqual(["ADULT:1+*:ALL:1.2", "CHILD:1+*:ALL:0.3", "COMBINATION:1+0:P2:1.5"])
    noErrors()
  })

  test("a room scope whose single-use rule is All rooms': the popover says that rule still applies and offers no switch", async ({ page }) => {
    const noErrors = trackErrors(page)
    await open(page, withRules(WHOLE))
    await expand(page, "occupancy")
    // All rooms: its own rule, the switch is offered
    let pop = await popover(page, "1 Adult (single use)", "P2")
    await expect(pop.getByRole("checkbox", { name: "Also when children travel" })).toHaveCount(1)
    await page.keyboard.press("Escape")
    await page.getByRole("combobox", { name: /^Rooms/ }).selectOption({ label: N.SUP })
    pop = await popover(page, "1 Adult (single use)", "P2")
    await expect(pop.getByRole("checkbox", { name: "Also when children travel" })).toHaveCount(0)
    await expect(pop).toContainText("This row's rule comes from All rooms or a pricing policy and would still apply")
    await page.keyboard.press("Escape")
    noErrors()
  })

  test("the switch refuses to carry a relative rule of another period into the other form", async ({ page }) => {
    const noErrors = trackErrors(page)
    const calls = watchContracts(page)
    await open(page, withRules(WHOLE, occ({ target: "COMBINATION", combination: "1+0", period_code: "P4", op: "ADD", value: "30" })))
    await expand(page, "occupancy")
    const pop = await popover(page, "1 Adult (single use)", "P2")
    await pop.getByRole("checkbox", { name: "Also when children travel" }).check()
    await pop.getByRole("textbox").first().fill("1.6")
    await expect(pop.getByRole("button", { name: "Apply" })).toBeDisabled()
    await expect(pop).toContainText("Not switched: another period or room of this row has a rule that adds, subtracts or changes by a percentage")
    // without the switch the rule is written as usual
    await pop.getByRole("checkbox", { name: "Also when children travel" }).uncheck()
    await pop.getByRole("button", { name: "Apply" }).click()
    await expect(pop).toBeHidden()
    await expect.poll(() => singleUse(calls)).toEqual(["COMBINATION:1+0:ALL:1.5", "COMBINATION:1+0:P2:1.6", "COMBINATION:1+0:P4:30"])
    noErrors()
  })

  test("a keyboard undo that removes the focused row puts the focus back on the grid: Add room, the single-use switch", async ({ page }) => {
    const noErrors = trackErrors(page)
    const draft = withRules(WHOLE)
    draft.rooms = draft.rooms.filter((r) => r.room_type !== DLX)
    draft.period_rates = draft.period_rates.filter((r) => r.room_type !== DLX)
    await open(page, draft)
    await page.getByRole("button", { name: "Add room", exact: true }).click()
    await page.getByRole("menuitem", { name: N.DLX }).click()
    await expect(cellOf(page, N.DLX, "All periods")).toBeFocused()
    await page.keyboard.press("Control+z")
    await expect(cellOf(page, N.DLX, "All periods")).toHaveCount(0)
    await expect.poll(() => focusedRole(page)).toBe("gridcell")
    await expect(priceMatrix(page).locator(":focus")).toHaveCount(1)
    // the grid's keys still work: redo, then undo again from the keyboard
    await page.keyboard.press("Control+y")
    await expect(cellOf(page, N.DLX, "All periods")).toBeVisible()
    await page.keyboard.press("Control+z")
    await expect(cellOf(page, N.DLX, "All periods")).toHaveCount(0)
    await expect.poll(() => focusedRole(page)).toBe("gridcell")
    // the single-use row in its other form is a row of another id: Ctrl+Z brings the focus to the old form's cell
    await expand(page, "occupancy")
    const pop = await popover(page, "1 Adult (single use)", "P4")
    await pop.getByRole("checkbox", { name: "Also when children travel" }).check()
    await pop.getByRole("textbox").first().fill("1.6")
    await pop.getByRole("button", { name: "Apply" }).click()
    await expect(lcell(page, "1 Adult (also with children)", "P4")).toBeFocused()
    await page.keyboard.press("Control+z")
    await expect(lcell(page, "1 Adult (single use)", "P4")).toBeFocused()
    await page.keyboard.press("ArrowDown")
    await expect(ladder(page).locator(":focus")).toHaveCount(1)
    await expect(lcell(page, "1 Adult (single use)", "P4")).not.toBeFocused()
    noErrors()
  })

  test("a new child-age band with a refused range is kept as unsaved input: the tab asks before it closes", async ({ page }) => {
    const noErrors = trackErrors(page)
    await open(page, ownerDraft())
    await expand(page, "occupancy")
    await page.getByRole("button", { name: "Child ages…" }).click()
    const drawer = page.getByRole("dialog", { name: "Child age bands" })
    await drawer.getByRole("button", { name: "Add age band" }).click()
    const upTo = drawer.getByLabel("Up to (not incl.) age: new band", { exact: true })
    await expect(upTo).toBeFocused()
    await upTo.fill("5")
    await page.keyboard.press("Enter")
    await expect(drawer).toContainText("The band must end after it starts.")
    await expect(drawer.locator("[data-uncommitted][data-changed]")).not.toHaveCount(0)
    let asked = ""
    page.once("dialog", (dlg) => {
      asked = dlg.type()
      void dlg.dismiss()
    })
    noErrors()
    await page.close({ runBeforeUnload: true })
    await expect.poll(() => asked).toBe("beforeunload")
  })

  test("each grid's header-lane note says its own controls; a read-only matrix has none", async ({ page }) => {
    const noErrors = trackErrors(page)
    await open(page, ownerDraft())
    await expect(priceMatrix(page)).toHaveAccessibleDescription(/^ArrowUp on the first row or ArrowLeft on the first column reaches the headers' actions/)
    await expand(page, "occupancy")
    await expect(ladder(page)).toHaveAccessibleDescription("ArrowLeft on the first column of the resolved line reaches its sample party.")
    await expand(page, "boards")
    await expect(boards(page)).toHaveAccessibleDescription("ArrowLeft on the first column reaches the row's board terms (Enter opens them).")
    // shown once: the note is the visible hint's own text, not a second copy for screen readers
    await expect(page.getByText("ArrowLeft on the first column of the resolved line reaches its sample party.")).toHaveCount(1)
    noErrors()
  })

  test("a read-only matrix and boards grid are not described by a header lane they do not have", async ({ page }) => {
    const noErrors = trackErrors(page)
    await open(page, ownerDraft(), { publish: true })
    await expect(priceMatrix(page)).toHaveAttribute("aria-readonly", "true")
    await expect(priceMatrix(page)).toHaveAccessibleDescription("")
    await expand(page, "boards")
    await expect(boards(page)).toHaveAccessibleDescription("")
    noErrors()
  })

  test("a new period's dates committed with Enter hand the focus to the period's first cell", async ({ page }) => {
    const noErrors = trackErrors(page)
    await open(page, ownerDraft())
    await page.getByRole("button", { name: "Add period" }).click()
    const end = page.getByLabel("End date: P5")
    await expect(end).toBeFocused()
    await end.fill(`${Y}-08-15`)
    await end.press("Enter")
    await expect(page.getByRole("button", { name: "Period actions: P5" })).toBeVisible()
    await expect(cellOf(page, N.STD, "P5")).toBeFocused()
    noErrors()
  })

  test("the Price test panel's nightly table fits it at 1440×900; at 1100 px the panel lies over the page", async ({ page }) => {
    const noErrors = trackErrors(page)
    await page.setViewportSize({ width: 1440, height: 900 })
    await open(page, ownerDraft())
    const ctx = page.getByRole("region", { name: "Commercial context" })
    await ctx.getByRole("button", { name: "Price test", exact: true }).click()
    const dr = page.getByRole("dialog", { name: "Price test" })
    await dr.getByLabel(/^Check-in/).fill(`${Y}-05-01`)
    await dr.getByLabel(/^Check-out/).fill(`${Y}-05-03`)
    await dr.getByRole("button", { name: /^Calculate/ }).click()
    const nightly = dr.getByRole("table", { name: "Night by night" })
    await expect(nightly).toBeVisible()
    await expect(nightly.getByRole("columnheader", { name: "Final" })).toBeVisible()
    const fits = await nightly.evaluate((el) => {
      const box = el.parentElement as HTMLElement
      return box.scrollWidth <= box.clientWidth + 1
    })
    expect(fits).toBe(true)
    expect(await page.locator(".tex-page").evaluate((el) => getComputedStyle(el).paddingRight)).toBe("448px")
    await page.setViewportSize({ width: 1100, height: 800 })
    await expect.poll(() => page.locator(".tex-page").evaluate((el) => getComputedStyle(el).paddingRight)).toBe("0px")
    noErrors()
  })
})
