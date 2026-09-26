// The Pricing Workspace after its final verification (ARCHITECTURE_DECISIONS.md ADR-061 "Final
// follow-up, workspace UX and keyboard"): "+ Period" reached and used by keyboard in a draft with
// rooms and no period; a new period's dates left by a click keep the page where it is; a key typed
// straight after Escape closes an invalid cell editor reaches the cell, in the matrix, the ladder and
// the boards grid, with frames held (deterministic: the focus came back only a frame later before);
// the shell's top bar beside an open side panel at 1280 and 1440 px; the single-use switch refused
// where an Always-wins Adult 1 would decide what one adult pays; the single-use row naming a special
// combination that prices one adult. Every test makes its own API draft.
import { expect, test, type Locator, type Page } from "@playwright/test"
import { login, trackErrors } from "./helpers"
import { priceMatrix } from "./flows/contracts"
import {
  archiveAll,
  baseBoard,
  DLX,
  esc,
  N,
  newDraft,
  occ,
  ownerBands,
  ownerDraft,
  ownerOccupancy,
  rooms,
  versionPath,
  watchContracts,
  Y,
  type Data,
  type NewContract,
} from "./flows/workspace"

test.use({ locale: "en-US", actionTimeout: 15_000, navigationTimeout: 30_000 })

const made: string[] = []

async function open(page: Page, data: Data): Promise<NewContract> {
  await login(page, "revenue@demo.tex")
  const d = await newDraft(page, "E2E-PWFN", data)
  made.push(d.contract)
  await page.goto(versionPath(d, "#pricing"))
  await expect(page.getByRole("grid").first()).toBeVisible()
  return d
}

const cellOf = (page: Page, room: string, period: string) =>
  priceMatrix(page)
    .getByRole("gridcell", { name: new RegExp(`^${esc(room)} · ${period}: (?!resolved)`) })
    .first()
const ladder = (page: Page) => page.getByRole("grid", { name: "Occupancy and child pricing by period" })
const lcell = (page: Page, slot: string, period: string) => ladder(page).getByRole("gridcell", { name: new RegExp(`^${esc(slot)} · ${period}: `) })
const boards = (page: Page) => page.getByRole("grid", { name: "Board supplements by period" })
const bcell = (page: Page, row: string, period: string) => boards(page).getByRole("gridcell", { name: new RegExp(`^${esc(row)} · ${period}: `) })
const focusedName = (page: Page) => page.evaluate(() => document.activeElement?.getAttribute("aria-label") ?? document.activeElement?.tagName ?? null)

async function expand(page: Page, section: "occupancy" | "boards") {
  const toggle = page.locator(`section#${section} h2 button[aria-expanded]`)
  if ((await toggle.getAttribute("aria-expanded")) === "false") await toggle.click()
  await expect(toggle).toHaveAttribute("aria-expanded", "true")
}

/** requestAnimationFrame callbacks wait until releaseFrames: a key pressed now comes before any
 * frame an earlier key asked for (fast typing, a busy page). */
async function holdFrames(page: Page) {
  await page.evaluate(() => {
    const w = window as unknown as { __held: FrameRequestCallback[]; __raf: typeof requestAnimationFrame }
    w.__held = []
    w.__raf = window.requestAnimationFrame
    window.requestAnimationFrame = (cb) => {
      w.__held.push(cb)
      return 0
    }
  })
}

async function releaseFrames(page: Page) {
  await page.evaluate(() => {
    const w = window as unknown as { __held: FrameRequestCallback[]; __raf: typeof requestAnimationFrame }
    window.requestAnimationFrame = w.__raf
    const held = w.__held
    w.__held = []
    for (const cb of held) cb(performance.now())
  })
  await page.evaluate(() => new Promise((r) => requestAnimationFrame(() => requestAnimationFrame(r))))
}

/** Types an invalid entry into a cell, then Escape and `next` straight after it, with frames held:
 * `next` must be in the cell's new editor, whole. */
async function escapeThenType(page: Page, cell: Locator, grid: Locator, next: string) {
  await cell.click()
  await expect(cell).toBeFocused()
  await page.keyboard.type("abc")
  await page.keyboard.press("Enter")
  const editor = grid.getByRole("textbox")
  await expect(editor).toHaveAttribute("aria-invalid", "true")
  await holdFrames(page)
  await page.keyboard.press("Escape")
  await page.keyboard.type(next)
  await expect(editor).toHaveValue(next)
  await releaseFrames(page)
  await expect(editor).toHaveValue(next)
  await expect(editor).toBeFocused()
  await page.keyboard.press("Escape")
  await expect(editor).toHaveCount(0)
}

const withBoards = (): Data => ({
  ...ownerDraft(),
  boards: [...baseBoard(), { board: "HB", is_base: 0, op: "ADD", adult_amount: "20", child_percent: "50", infant_free: 1, room_type: "", period_code: "" }],
})

test.describe("pricing workspace, final follow-up", () => {
  test.afterAll(async ({ browser }) => archiveAll(browser, made, "pricing workspace final follow-up e2e clean-up"))

  test("keyboard only: a draft with rooms and no period reaches '+ Period' (Shift+Tab, or ArrowUp from All periods), adds P1 with its dates and takes a price in its first cell", async ({ page }) => {
    const noErrors = trackErrors(page)
    await open(page, { rooms: rooms(), periods: [], period_rates: [], age_bands: ownerBands(), occupancy_rules: ownerOccupancy(), boards: baseBoard() })
    const add = page.getByRole("button", { name: "Add period" })
    // the next step of the design's order, a Tab stop while the matrix has no period column
    await expect(add).toHaveAttribute("tabindex", "0")
    const first = cellOf(page, N.STD, "All periods")
    await first.focus()
    await page.keyboard.press("ArrowUp")
    await expect(add).toBeFocused()
    await page.keyboard.press("ArrowDown")
    await expect(first).toBeFocused()
    await page.keyboard.press("Shift+Tab")
    await expect(add).toBeFocused()
    await page.keyboard.press("Enter")
    // no dated period before it: both dates are asked, the start first
    const start = page.getByLabel("Start date: P1")
    await expect(start).toBeFocused()
    await start.fill(`${Y}-04-01`)
    // Tab moves through the date field's own parts first (month, day, year), then to the end date
    const end = page.getByLabel("End date: P1")
    for (let i = 0; i < 4 && !(await end.evaluate((el) => el === document.activeElement)); i++) await page.keyboard.press("Tab")
    await expect(end).toBeFocused()
    await end.fill(`${Y}-04-30`)
    await page.keyboard.press("Enter")
    await expect(page.getByRole("button", { name: "Period actions: P1" })).toBeVisible()
    await expect(cellOf(page, N.STD, "P1")).toBeFocused()
    await page.keyboard.type("70")
    await page.keyboard.press("Enter")
    await expect(cellOf(page, N.STD, "P1")).toHaveAttribute("aria-label", /entered price, 70\.00/)
    // with a period column, "+ Period" is on the header lane again (one tab stop per grid)
    await expect(add).toHaveAttribute("tabindex", "-1")
    noErrors()
  })

  test("a new period's dates left by a click on the page keep the focus there, and the page does not jump back to the matrix", async ({ page }) => {
    const noErrors = trackErrors(page)
    await page.setViewportSize({ width: 1280, height: 600 })
    await open(page, withBoards())
    await expand(page, "occupancy")
    await expand(page, "boards")
    await page.getByRole("button", { name: "Add period" }).click()
    const end = page.getByLabel("End date: P5")
    await expect(end).toBeFocused()
    await end.fill(`${Y}-08-15`)
    // down the page, where the matrix is out of view, and a click on a text that takes no focus
    // and has no focusable container (the side navigation's group label; a click inside the main
    // region focuses the region itself): the focus goes to the page's body
    await page.getByText("ArrowLeft on the first column reaches the row's board terms (Enter opens them).").scrollIntoViewIfNeeded()
    const before = await page.evaluate(() => window.scrollY)
    expect(before).toBeGreaterThan(300)
    expect(await cellOf(page, N.STD, "P5").evaluate((el) => el.getBoundingClientRect().bottom)).toBeLessThan(0)
    await page.getByRole("navigation", { name: "Main navigation" }).getByText("Commercial", { exact: true }).click()
    await expect(page.getByRole("button", { name: "Period actions: P5" })).toBeVisible()
    await page.evaluate(() => new Promise((r) => requestAnimationFrame(() => requestAnimationFrame(r))))
    expect(await priceMatrix(page).evaluate((g) => g.contains(document.activeElement))).toBe(false)
    expect(await page.evaluate(() => document.activeElement === document.body)).toBe(true)
    expect(Math.abs((await page.evaluate(() => window.scrollY)) - before)).toBeLessThanOrEqual(2)
    // the dates were kept (leaving the field commits them)
    await expect(priceMatrix(page).getByRole("columnheader").filter({ hasText: /^P5/ })).toContainText(/15 Aug/)
    noErrors()
  })

  test("a key typed straight after Escape closes an invalid editor reaches the cell (frames held): the matrix", async ({ page }) => {
    const noErrors = trackErrors(page)
    await open(page, ownerDraft())
    await escapeThenType(page, cellOf(page, N.SUP, "P2"), priceMatrix(page), "1.500")
    noErrors()
  })

  test("a key typed straight after Escape closes an invalid editor reaches the cell (frames held): the ladder and the boards grid", async ({ page }) => {
    const noErrors = trackErrors(page)
    await open(page, withBoards())
    await expand(page, "occupancy")
    await escapeThenType(page, lcell(page, "3rd adult", "P2"), ladder(page), "x0.8")
    await expand(page, "boards")
    await escapeThenType(page, bcell(page, "Half board", "P2"), boards(page), "+25")
    noErrors()
  })

  for (const width of [1280, 1440]) {
    test(`at ${width} px the shell's top bar keeps its width beside the Price test, and none of its controls overlaps another`, async ({ page }) => {
      const noErrors = trackErrors(page)
      await page.setViewportSize({ width, height: 900 })
      await open(page, ownerDraft())
      const bar = page.locator(".tex-page > header").first()
      const layout = () =>
        bar.evaluate((h) => {
          const boxes = Array.from(h.querySelectorAll<HTMLElement>("button, select, input, a, [role='status'], .rounded-full"))
            .filter((e) => e.offsetParent !== null && e.getBoundingClientRect().width > 0)
            .map((e) => {
              const r = e.getBoundingClientRect()
              return { name: e.getAttribute("aria-label") ?? e.textContent?.trim().slice(0, 30) ?? e.tagName, x0: r.left, x1: r.right, y0: r.top, y1: r.bottom, inner: e }
            })
          const overlaps: string[] = []
          for (let i = 0; i < boxes.length; i++)
            for (let j = i + 1; j < boxes.length; j++) {
              const a = boxes[i]
              const b = boxes[j]
              if (a.inner.contains(b.inner) || b.inner.contains(a.inner)) continue
              const w = Math.min(a.x1, b.x1) - Math.max(a.x0, b.x0)
              const hgt = Math.min(a.y1, b.y1) - Math.max(a.y0, b.y0)
              if (w > 1 && hgt > 1) overlaps.push(`${a.name} × ${b.name}`)
            }
          const select = h.querySelector("select")
          return { width: Math.round(h.getBoundingClientRect().width), right: Math.round(h.getBoundingClientRect().right), bottom: h.getBoundingClientRect().bottom, select: Math.round(select?.getBoundingClientRect().width ?? 0), overlaps }
        })
      const closed = await layout()
      expect(closed.overlaps).toEqual([])
      await page.getByRole("region", { name: "Commercial context" }).getByRole("button", { name: "Price test", exact: true }).click()
      const panel = page.getByRole("dialog", { name: "Price test" })
      await expect(panel).toBeVisible()
      expect(await page.locator(".tex-page").evaluate((el) => getComputedStyle(el).paddingRight)).toBe("448px")
      const open_ = await layout()
      expect(open_.overlaps).toEqual([])
      expect(open_.width).toBe(closed.width)
      expect(open_.right).toBe(closed.right)
      expect(open_.select).toBe(closed.select)
      // the panel starts under the bar: nothing of the bar is covered
      const box = (await panel.boundingBox())!
      expect(box.y).toBeGreaterThanOrEqual(open_.bottom - 1)
      // the page content still gives up the panel's width: Publish stays uncovered
      const publish = (await page.getByRole("button", { name: "Publish", exact: true }).boundingBox())!
      expect(publish.x + publish.width).toBeLessThanOrEqual(box.x + 1)
      noErrors()
    })
  }

  test("the single-use switch is refused where an Always-wins Adult 1 would decide what one adult pays; without the switch the rule is written", async ({ page }) => {
    const noErrors = trackErrors(page)
    const calls = watchContracts(page)
    const draft = ownerDraft()
    draft.occupancy_rules = [...draft.occupancy_rules, occ({ target: "ADULT", position: 1, value: "1", is_override: 1 }), occ({ target: "COMBINATION", combination: "1+0", value: "0.8" })]
    await open(page, draft)
    await expand(page, "occupancy")
    await lcell(page, "1 Adult (single use)", "All periods").click()
    await page.keyboard.press("Alt+Enter")
    const pop = page.getByRole("dialog", { name: "Edit rule: 1 Adult (single use) · All periods" })
    await expect(pop).toBeVisible()
    const apply = pop.getByRole("button", { name: "Apply" })
    await pop.getByRole("checkbox", { name: "Also when children travel" }).check()
    await expect(apply).toBeDisabled()
    await expect(pop).toContainText("Not switched: in the other form another rule would decide what one adult pays")
    await expect(apply).toHaveAccessibleDescription(/an Always wins rule for Adult 1/)
    await pop.getByRole("checkbox", { name: "Also when children travel" }).uncheck()
    await expect(apply).toBeEnabled()
    await pop.getByRole("textbox").first().fill("0.85")
    await apply.click()
    await expect(pop).toBeHidden()
    await expect
      .poll(() => {
        const body = calls.bodies("price_matrix").at(-1) as { data?: { occupancy_rules?: Record<string, unknown>[] } } | undefined
        return (body?.data?.occupancy_rules ?? []).filter((r) => r.combination === "1+0" || r.combination === "1+*").map((r) => `${r.target}:${r.combination}:${r.value}`)
      })
      .toEqual(["COMBINATION:1+0:0.85"])
    noErrors()
  })

  test("a special combination that prices one adult: the single-use row names it instead of the engine default", async ({ page }) => {
    const noErrors = trackErrors(page)
    const draft = ownerDraft()
    // the builder's "1 adult + any children" card: children = any includes none, so it prices 1A+0C
    draft.occupancy_rules = [...draft.occupancy_rules, occ({ target: "ADULT", position: 1, combination: "1+*", value: "1.2" }), occ({ target: "CHILD", position: 1, combination: "1+*", value: "0.3" })]
    await open(page, draft)
    await expand(page, "occupancy")
    for (const period of ["All periods", "P2"]) {
      const cell = lcell(page, "1 Adult (single use)", period)
      await expect(cell).toHaveAttribute("aria-label", /special combination/)
      await expect(cell).toHaveAttribute("aria-label", /Special combinations win over period rules unless the rule is marked Always wins: /)
      await expect(cell).not.toHaveAttribute("aria-label", /×1\.00 default/)
    }
    // in a room's scope the All-rooms card holds the column too
    await page.getByRole("combobox", { name: /^Rooms/ }).selectOption({ label: N.DLX })
    await expect(lcell(page, "1 Adult (single use)", "P2")).toHaveAttribute("aria-label", /special combination/)
    noErrors()
  })

  test("a card for one room prices one adult in that room only: All rooms keeps the default, says the exception and carries the note", async ({ page }) => {
    const noErrors = trackErrors(page)
    const draft = ownerDraft()
    draft.occupancy_rules = [
      ...draft.occupancy_rules,
      occ({ target: "ADULT", position: 1, combination: "1+*", room_type: DLX, value: "1.2" }),
      occ({ target: "CHILD", position: 1, combination: "1+*", room_type: DLX, value: "0.3" }),
    ]
    await open(page, draft)
    await expand(page, "occupancy")
    const cell = lcell(page, "1 Adult (single use)", "P2")
    await expect(cell).toHaveAttribute("aria-label", /×1\.00 default/)
    await expect(cell).toHaveAttribute("aria-label", /Special combinations win over period rules/)
    await expect(cell).toHaveAccessibleDescription(/except where a special combination prices one adult/)
    // (the room's option carries the dot of a scope with rules of its own)
    await page.getByRole("combobox", { name: /^Rooms/ }).selectOption({ value: DLX })
    await expect(lcell(page, "1 Adult (single use)", "P2")).toHaveAttribute("aria-label", /special combination/)
    noErrors()
  })
})
