// The header lane and the grid's focus timing (PRICING_WORKSPACE_UX.md §3.19; Pricing Workspace
// final follow-up) on tests/dom/lanes.tsx, a grid shaped as the room price matrix: "All periods"
// has no header control, "+ Period" follows the last column. Also the Keyboard shortcuts popover's
// width in every language. Run: `npm run test:dom`.
import { expect, test, type Page } from "@playwright/test"

const HARNESS = "/tests/dom/lanes.html"

test.use({ viewport: { width: 1200, height: 800 } })

const focused = (page: Page) => page.evaluate(() => document.activeElement?.getAttribute("aria-label") ?? document.activeElement?.getAttribute("data-cell") ?? null)
const cell = (page: Page, r: number, c: number) => page.getByTestId("lane-grid").locator(`[data-cell="${r}:${c}"]`)

/** Frames are held: requestAnimationFrame callbacks wait until releaseFrames, so a key pressed
 * now comes before the frame the previous key asked for (as with fast typing, or a busy page). */
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
}

test("with rooms and no period, ArrowUp from 'All periods' reaches '+ Period', which adds P1 from the keyboard; ArrowDown goes back", async ({ page }) => {
  await page.goto(HARNESS)
  await cell(page, 1, 0).click()
  await page.keyboard.press("ArrowUp")
  await page.keyboard.press("ArrowUp")
  await expect.poll(() => focused(page)).toBe("Add period")
  await page.keyboard.press("ArrowDown")
  await expect.poll(() => focused(page)).toBe("0:0")
  await page.keyboard.press("ArrowUp")
  await expect.poll(() => focused(page)).toBe("Add period")
  await page.keyboard.press("Enter")
  await expect.poll(() => page.evaluate(() => window.__log)).toEqual(["add-period:P1"])
  await expect(page.getByRole("button", { name: "Period actions: P1" })).toBeVisible()
})

test("with periods, ArrowUp from 'All periods' reaches the first period's menu; from a period, its own", async ({ page }) => {
  await page.goto(`${HARNESS}?periods=2`)
  await cell(page, 0, 0).click()
  await page.keyboard.press("ArrowUp")
  await expect.poll(() => focused(page)).toBe("Period actions: P1")
  await page.keyboard.press("ArrowRight")
  await page.keyboard.press("ArrowRight")
  await expect.poll(() => focused(page)).toBe("Add period")
  await page.keyboard.press("ArrowDown")
  await expect.poll(() => focused(page)).toBe("0:2")
  await page.keyboard.press("ArrowUp")
  await expect.poll(() => focused(page)).toBe("Period actions: P2")
})

test("a key pressed before the frame of the previous move keeps its effect: Home, then ArrowLeft at once, stays on the room's menu", async ({ page }) => {
  await page.goto(`${HARNESS}?periods=2`)
  await cell(page, 0, 2).click()
  await holdFrames(page)
  await page.keyboard.press("Home")
  // the cell Home moved to has the focus at once, before any frame
  expect(await focused(page)).toBe("0:0")
  await page.keyboard.press("ArrowLeft")
  expect(await focused(page)).toBe("Room actions: Standard")
  // the frame Home asked for comes now: it does not take the focus back to the cell
  await releaseFrames(page)
  await page.evaluate(() => new Promise((r) => requestAnimationFrame(() => requestAnimationFrame(r))))
  expect(await focused(page)).toBe("Room actions: Standard")
  await page.keyboard.press("ArrowDown")
  await expect.poll(() => focused(page)).toBe("Room actions: Family Suite")
  await page.keyboard.press("ArrowRight")
  await expect.poll(() => focused(page)).toBe("1:0")
})

test("arrows held down with frames late: every key moves from where the previous one went, the selection stays one cell", async ({ page }) => {
  await page.goto(`${HARNESS}?periods=3`)
  await cell(page, 0, 0).click()
  await holdFrames(page)
  for (const key of ["ArrowRight", "ArrowRight", "ArrowDown", "ArrowRight", "ArrowDown"]) await page.keyboard.press(key)
  expect(await focused(page)).toBe("2:3")
  await releaseFrames(page)
  await page.evaluate(() => new Promise((r) => requestAnimationFrame(() => requestAnimationFrame(r))))
  expect(await focused(page)).toBe("2:3")
  expect(await page.getByTestId("lane-grid").locator('[aria-selected="true"]').count()).toBe(1)
  // Shift+Arrow with frames late extends from the moved cell, the focus follows
  await holdFrames(page)
  await page.keyboard.press("Shift+ArrowLeft")
  await page.keyboard.press("Shift+ArrowUp")
  expect(await focused(page)).toBe("1:2")
  await releaseFrames(page)
  await page.evaluate(() => new Promise((r) => requestAnimationFrame(() => requestAnimationFrame(r))))
  expect(await focused(page)).toBe("1:2")
  expect(await page.getByTestId("lane-grid").locator('[aria-selected="true"]').count()).toBe(4)
})

for (const lang of ["en", "de", "pl", "ru", "tr", "ro"]) {
  test(`the Keyboard shortcuts popover fits its panel: no row runs past it (${lang})`, async ({ page }) => {
    await page.goto(`${HARNESS}?lang=${lang}`)
    await page.locator('button[aria-haspopup="dialog"]').click()
    const dialog = page.getByRole("dialog")
    await expect(dialog).toBeVisible()
    await expect(dialog.locator("tbody tr")).toHaveCount(21)
    const m = await dialog.evaluate((el) => {
      const body = el.lastElementChild as HTMLElement
      const box = body.getBoundingClientRect()
      const right = Math.max(...Array.from(body.querySelectorAll("table, th, td, kbd")).map((x) => x.getBoundingClientRect().right))
      return { scroll: body.scrollWidth - body.clientWidth, past: Math.round(right - box.right), panel: Math.round(el.getBoundingClientRect().width) }
    })
    expect(m.scroll, "the popover body scrolls sideways").toBe(0)
    expect(m.past, "a key or action runs past the popover").toBeLessThanOrEqual(0)
    expect(m.panel).toBe(448)
  })
}
