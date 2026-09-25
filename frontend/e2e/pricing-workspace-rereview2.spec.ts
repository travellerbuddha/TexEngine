// The Pricing Workspace S16 second re-review (PRICING_WORKSPACE_UX.md §3.6.2, §3.8, §3.12, §3.19):
// the single-use row switches form as a whole (one period switched, All periods switched with a
// period override) and both forms of a saved draft are a row each; a cleared child-age name leaves
// nothing unsaved behind; the header lane is in the Keyboard shortcuts and on each grid; Add room
// focuses the room it added; the Price test's status region is there before the first result; the
// terms popover's Add a rule for one room carries its help; a read-only viewer's Ctrl+C notice; Add
// board names the board in the history. Every test makes its own API draft of the owner's example.
import { expect, test, type Page } from "@playwright/test"
import { login, trackErrors } from "./helpers"
import { priceMatrix } from "./flows/contracts"
import { archiveAll, DLX, esc, N, newDraft, occ, ownerDraft, publish, versionPath, watchContracts, Y, type Data, type NewContract } from "./flows/workspace"

test.use({ locale: "en-US", actionTimeout: 15_000, navigationTimeout: 30_000 })

const made: string[] = []

async function open(page: Page, data: Data, o: { publish?: boolean } = {}): Promise<NewContract> {
  await login(page, "revenue@demo.tex")
  const d = await newDraft(page, "E2E-PWR2", data)
  made.push(d.contract)
  if (o.publish) await publish(page, d.version)
  await page.goto(versionPath(d, "#pricing"))
  await expect(page.getByRole("grid").first()).toBeVisible()
  return d
}

const ladder = (page: Page) => page.getByRole("grid", { name: "Occupancy and child pricing by period" })
const lcell = (page: Page, slot: string, period: string) => ladder(page).getByRole("gridcell", { name: new RegExp(`^${esc(slot)} · ${period}: `) })
const boards = (page: Page) => page.getByRole("grid", { name: "Board supplements by period" })
const bcell = (page: Page, row: string, period: string) => boards(page).getByRole("gridcell", { name: new RegExp(`^${esc(row)} · ${period}: `) })
const cellOf = (page: Page, room: string, period: string) =>
  priceMatrix(page)
    .getByRole("gridcell", { name: new RegExp(`^${esc(room)} · ${period}: (?!resolved)`) })
    .first()

async function expand(page: Page, section: "occupancy" | "boards") {
  const toggle = page.locator(`section#${section} h2 button[aria-expanded]`)
  if ((await toggle.getAttribute("aria-expanded")) === "false") await toggle.click()
  await expect(toggle).toHaveAttribute("aria-expanded", "true")
}

/** The single-use rules the last price_matrix call priced (target:combination:period:value). */
function singleUse(calls: ReturnType<typeof watchContracts>) {
  const body = calls.bodies("price_matrix").at(-1) as { data?: { occupancy_rules?: Record<string, unknown>[] } } | undefined
  return (body?.data?.occupancy_rules ?? [])
    .filter((r) => r.combination === "1+0" || r.combination === "1+*")
    .map((r) => `${r.target}:${r.combination}:${r.period_code || "ALL"}:${r.value}`)
    .sort()
}

const withSingle = (...extra: Record<string, unknown>[]): Data => {
  const d = ownerDraft()
  d.occupancy_rules = [...d.occupancy_rules, occ({ target: "COMBINATION", combination: "1+0", value: "1.5" }), ...extra]
  return d
}

async function switchSingle(page: Page, period: string, value: string) {
  await lcell(page, "1 Adult (single use)", period).click()
  await page.keyboard.press("Alt+Enter")
  const pop = page.getByRole("dialog", { name: `Edit rule: 1 Adult (single use) · ${period}` })
  await pop.getByRole("checkbox", { name: "Also when children travel" }).check()
  await expect.soft(pop).toContainText("The whole row switches")
  await pop.getByRole("textbox").first().fill(value)
  await pop.getByRole("button", { name: "Apply" }).click()
  await expect(pop).toBeHidden()
}

test.describe("pricing workspace, S16 re-review 2", () => {
  test.afterAll(async ({ browser }) => archiveAll(browser, made, "pricing workspace re-review 2 e2e clean-up"))

  test("single use switched in one period: the whole row takes the new form, P4 its own value, every other period the old one", async ({ page }) => {
    const noErrors = trackErrors(page)
    const calls = watchContracts(page)
    await open(page, withSingle())
    await expand(page, "occupancy")
    await switchSingle(page, "P4", "1.6")
    await expect.poll(() => singleUse(calls)).toEqual(["ADULT:1+*:ALL:1.5", "ADULT:1+*:P4:1.6"])
    await expect(lcell(page, "1 Adult (also with children)", "P4")).toHaveAttribute("aria-label", /×1\.60/)
    await expect(lcell(page, "1 Adult (also with children)", "All periods")).toHaveAttribute("aria-label", /×1\.50/)
    await expect(lcell(page, "1 Adult (also with children)", "P1")).toHaveAttribute("aria-label", /×1\.50/)
    await expect(ladder(page).getByRole("rowheader").filter({ hasText: /^1 Adult \(single use\)/ })).toHaveCount(0)
    // the row that now holds the rule has the focus
    await expect(lcell(page, "1 Adult (also with children)", "P4")).toBeFocused()
    noErrors()
  })

  test("single use switched in All periods takes a period override along", async ({ page }) => {
    const noErrors = trackErrors(page)
    const calls = watchContracts(page)
    await open(page, withSingle(occ({ target: "COMBINATION", combination: "1+0", period_code: "P4", value: "1.6" })))
    await expand(page, "occupancy")
    await switchSingle(page, "All periods", "1.5")
    await expect.poll(() => singleUse(calls)).toEqual(["ADULT:1+*:ALL:1.5", "ADULT:1+*:P4:1.6"])
    await expect(lcell(page, "1 Adult (also with children)", "P4")).toHaveAttribute("aria-label", /×1\.60/)
    await expect(lcell(page, "1 Adult (also with children)", "P1")).toHaveAttribute("aria-label", /×1\.50/)
    noErrors()
  })

  test("a draft with both single-use forms shows a row for each; neither offers the switch", async ({ page }) => {
    const noErrors = trackErrors(page)
    await open(page, withSingle(occ({ target: "ADULT", position: 1, combination: "1+*", period_code: "P2", value: "1.2" })))
    await expand(page, "occupancy")
    await expect(lcell(page, "1 Adult (single use)", "P2")).toHaveAttribute("aria-label", /×1\.50/)
    await expect(lcell(page, "1 Adult (also with children)", "P2")).toHaveAttribute("aria-label", /×1\.20/)
    await lcell(page, "1 Adult (also with children)", "P2").click()
    await page.keyboard.press("Alt+Enter")
    const pop = page.getByRole("dialog", { name: "Edit rule: 1 Adult (also with children) · P2" })
    await expect(pop).toBeVisible()
    await expect(pop.getByRole("checkbox", { name: "Also when children travel" })).toHaveCount(0)
    await page.keyboard.press("Escape")
    noErrors()
  })

  test("a child-age name cleared and left: the field shows the generated name and the tab closes without asking", async ({ page }) => {
    const noErrors = trackErrors(page)
    await open(page, ownerDraft())
    await expand(page, "occupancy")
    await page.getByRole("button", { name: "Child ages…" }).click()
    const drawer = page.getByRole("dialog", { name: "Child age bands" })
    const label = drawer.getByLabel("Label: Infant 0–2.99", { exact: true })
    await label.fill("")
    await page.keyboard.press("Tab")
    await expect(label).toHaveValue("Infant 0–2.99")
    await expect(drawer.locator("[data-uncommitted][data-changed]")).toHaveCount(0)
    await expect(page.getByText("Unsaved changes", { exact: true })).toHaveCount(0)
    let asked = ""
    page.once("dialog", (dlg) => {
      asked = dlg.type()
      void dlg.dismiss()
    })
    noErrors()
    await page.close({ runBeforeUnload: true })
    await expect.poll(() => page.isClosed()).toBe(true)
    expect(asked).toBe("")
  })

  test("the header lane is in the Keyboard shortcuts and described on each grid", async ({ page }) => {
    const noErrors = trackErrors(page)
    await open(page, ownerDraft())
    await page.getByRole("group", { name: "Bulk tools" }).getByRole("button", { name: "Keyboard shortcuts" }).click()
    const pop = page.getByRole("dialog", { name: "Keyboard shortcuts" })
    await expect(pop.getByRole("row", { name: /ArrowUp on the first row, ArrowLeft on the first column.*actions/ })).toBeVisible()
    await page.keyboard.press("Escape")
    const lane = /ArrowUp on the first row or ArrowLeft on the first column reaches the headers' actions/
    await expect(priceMatrix(page)).toHaveAccessibleDescription(lane)
    await expand(page, "occupancy")
    await expect(ladder(page)).toHaveAccessibleDescription(lane)
    await expand(page, "boards")
    await expect(boards(page)).toHaveAccessibleDescription(lane)
    await expect(page.locator("section#occupancy")).toContainText("reaches the headers' actions")
    noErrors()
  })

  test("Add room: the room added takes the focus, not the body, when nothing is left to add", async ({ page }) => {
    const noErrors = trackErrors(page)
    const draft = ownerDraft()
    draft.rooms = draft.rooms.filter((r) => r.room_type !== DLX)
    draft.period_rates = draft.period_rates.filter((r) => r.room_type !== DLX)
    await open(page, draft)
    await page.getByRole("button", { name: "Add room", exact: true }).focus()
    await page.keyboard.press("Enter")
    await expect(page.getByRole("menuitem", { name: N.DLX })).toBeFocused()
    await page.keyboard.press("Enter")
    await expect(page.getByRole("button", { name: "Add room", exact: true })).toBeDisabled()
    await expect(cellOf(page, N.DLX, "All periods")).toBeFocused()
    noErrors()
  })

  test("the Price test's status region is there before the first result, and says the total", async ({ page }) => {
    const noErrors = trackErrors(page)
    await open(page, ownerDraft())
    await page.getByRole("region", { name: "Commercial context" }).getByRole("button", { name: "Price test", exact: true }).click()
    const dr = page.getByRole("dialog", { name: "Price test" })
    const status = dr.locator("p[role=status].sr-only")
    await expect(status).toHaveCount(1)
    await expect(status).toHaveText("")
    const before = await status.elementHandle()
    await dr.getByLabel(/^Check-in/).fill(`${Y}-04-01`)
    await dr.getByLabel(/^Check-out/).fill(`${Y}-04-04`)
    await dr.getByRole("button", { name: /^Calculate/ }).click()
    await expect(status).toHaveText(/^Price test total: /)
    // the same element: its text changed, it was not inserted with it
    expect(await before?.evaluate((el) => el.isConnected && /^Price test total: /.test(el.textContent ?? ""))).toBe(true)
    noErrors()
  })

  test("the terms popover's Add a rule for one room is described by its help", async ({ page }) => {
    const noErrors = trackErrors(page)
    const draft = ownerDraft()
    draft.boards = [
      ...(draft.boards ?? []),
      { board: "HB", is_base: 0, op: "ADD", adult_amount: "20", child_percent: "50", infant_free: 1, room_type: "", period_code: "" },
    ]
    await open(page, draft)
    await expand(page, "boards")
    await bcell(page, "Half board", "All periods").click()
    await page.keyboard.press("Alt+Enter")
    const pop = page.getByRole("dialog", { name: "Board terms: Half board" })
    await expect(pop.getByRole("button", { name: "Add a rule for one room" })).toHaveAccessibleDescription(/A row for that room under Half board/)
    await page.keyboard.press("Escape")
    noErrors()
  })

  test("Add board names the board in the history: undoing it says 'Add board: Bed & breakfast'", async ({ page }) => {
    const noErrors = trackErrors(page)
    const draft = ownerDraft()
    draft.boards = []
    await open(page, draft)
    await expand(page, "boards")
    await page.getByRole("button", { name: "Add board", exact: true }).click()
    await page.getByRole("menuitem", { name: /\(BB\)$/ }).click()
    await expect(bcell(page, "Bed & breakfast", "All periods")).toBeFocused()
    await page.keyboard.press("Control+z")
    await expect(page.locator("section#boards [role=status]").filter({ hasText: /^Undone: / })).toHaveText("Undone: Add board: Bed & breakfast")
    noErrors()
  })

  test("a read-only ladder: Ctrl+C says only where copy works", async ({ page }) => {
    const noErrors = trackErrors(page)
    await open(page, ownerDraft(), { publish: true })
    await expand(page, "occupancy")
    await expect(ladder(page)).toHaveAttribute("aria-readonly", "true")
    await lcell(page, "3rd adult", "All periods").click()
    await page.keyboard.press("Control+c")
    await expect(page.getByText("Copy works in the room price matrix.").first()).toBeVisible()
    await expect(page.getByText("type one entry for all of them")).toHaveCount(0)
    noErrors()
  })
})
