// Browser checks of the TEX design-system overlays (Popover, Menu, Tooltip) and grid keys on the
// harness page (tests/dom/overlays.tsx), at a 1000×400 viewport where the tall panels overflow.
// Run: `npm run test:dom` (PW_CHROMIUM=/path/to/chrome when Playwright's browsers are elsewhere).
import { expect, test, type Locator, type Page } from "@playwright/test"

const HARNESS = "/tests/dom/overlays.html"

/** Two frames (scroll events, ResizeObserver) and a little time for anything they schedule. */
async function settle(page: Page, ms = 150) {
  await page.evaluate(
    (wait) => new Promise<void>((done) => requestAnimationFrame(() => requestAnimationFrame(() => setTimeout(done, wait)))),
    ms,
  )
}

const scrollTop = (l: Locator) => l.evaluate((el) => el.scrollTop)

/** `inner` is fully visible inside `outer` and inside the viewport. */
async function expectShownIn(page: Page, inner: Locator, outer: Locator) {
  const a = await inner.boundingBox()
  const b = await outer.boundingBox()
  const view = page.viewportSize()
  expect(a, "inner box").not.toBeNull()
  expect(b, "outer box").not.toBeNull()
  expect(a!.y).toBeGreaterThanOrEqual(b!.y - 1)
  expect(a!.y + a!.height).toBeLessThanOrEqual(b!.y + b!.height + 1)
  expect(a!.y).toBeGreaterThanOrEqual(0)
  expect(a!.y + a!.height).toBeLessThanOrEqual(view!.height)
}

test.beforeEach(async ({ page }) => {
  await page.goto(HARNESS)
  await expect(page.getByRole("button", { name: "Big menu" })).toBeVisible()
})

test("an overflowing Menu keeps its scroll position; End and ArrowUp show the focused item", async ({ page }) => {
  const button = page.getByRole("button", { name: "Big menu" })
  await button.click()
  const menu = page.getByRole("menu", { name: "Big menu" })
  await expect(menu).toBeVisible()
  const { sh, ch } = await menu.evaluate((el) => ({ sh: el.scrollHeight, ch: el.clientHeight }))
  expect(sh).toBeGreaterThan(ch + 300)

  // the wheel
  await menu.hover()
  await page.mouse.wheel(0, 300)
  await expect.poll(() => scrollTop(menu)).toBeGreaterThan(0)
  await settle(page)
  expect(await scrollTop(menu)).toBeGreaterThan(200)
  await page.mouse.move(990, 390)

  // a script (or a scrollbar drag)
  await menu.evaluate((el) => {
    el.scrollTop = 200
  })
  await settle(page)
  expect(await scrollTop(menu)).toBe(200)

  // End focuses the last item and brings it into view
  await page.keyboard.press("End")
  const last = page.getByRole("menuitem", { name: "Item 49" })
  await expect(last).toBeFocused()
  await settle(page)
  await expectShownIn(page, last, menu)

  // opening with ArrowUp focuses the last item, in view
  await page.keyboard.press("Escape")
  await expect(menu).toBeHidden()
  await expect(button).toBeFocused()
  await page.keyboard.press("ArrowUp")
  await expect(last).toBeFocused()
  await settle(page)
  await expectShownIn(page, last, menu)
})

test("an overflowing Popover keeps its scroll position and shows a field reached with Tab", async ({ page }) => {
  await page.getByRole("button", { name: "Open form" }).click()
  const dialog = page.getByRole("dialog", { name: "Tall form" })
  const body = dialog.locator("div.overflow-y-auto")
  await expect(page.getByLabel("f0", { exact: true })).toBeFocused()
  const { sh, ch } = await body.evaluate((el) => ({ sh: el.scrollHeight, ch: el.clientHeight }))
  expect(sh).toBeGreaterThan(ch + 300)

  await body.hover()
  await page.mouse.wheel(0, 300)
  await expect.poll(() => scrollTop(body)).toBeGreaterThan(0)
  await settle(page)
  expect(await scrollTop(body)).toBeGreaterThan(200)
  await page.mouse.move(990, 390)

  await body.evaluate((el) => {
    el.scrollTop = 0
  })
  await settle(page)
  for (let i = 0; i < 25; i++) await page.keyboard.press("Tab")
  const f25 = page.getByLabel("f25", { exact: true })
  await expect(f25).toBeFocused()
  await settle(page)
  await expectShownIn(page, f25, body)
  await expect(dialog).toBeVisible()
})

test("page scroll and a resize move the panel with its trigger and keep its own scroll", async ({ page }) => {
  const button = page.getByRole("button", { name: "Big menu" })
  await button.click()
  const menu = page.getByRole("menu", { name: "Big menu" })
  await expect(menu).toBeVisible()
  await menu.evaluate((el) => {
    el.scrollTop = 200
  })
  await settle(page)

  await page.evaluate(() => window.scrollBy(0, 20))
  await settle(page)
  expect(await page.evaluate(() => window.scrollY)).toBe(20)
  expect(await scrollTop(menu)).toBe(200)
  const a = (await button.boundingBox())!
  const m = (await menu.boundingBox())!
  expect(Math.abs(m.y - (a.y + a.height + 4))).toBeLessThanOrEqual(2)

  await page.setViewportSize({ width: 1000, height: 380 })
  await settle(page)
  expect(await scrollTop(menu)).toBe(200)
  await expect(menu).toBeVisible()
})

test("Tab past a Popover's last field closes it and moves on from its trigger; Shift+Tab from the first returns to the trigger", async ({
  page,
}) => {
  const trigger = page.getByRole("button", { name: "Open small" })
  const dialog = page.getByRole("dialog", { name: "Popover small" })
  await trigger.click()
  await expect(page.getByLabel("s1", { exact: true })).toBeFocused()
  await page.keyboard.press("Tab")
  await expect(page.getByLabel("s2", { exact: true })).toBeFocused()
  await page.keyboard.press("Tab")
  await expect(dialog).toBeHidden()
  await expect(page.getByRole("button", { name: "After small" })).toBeFocused()

  await trigger.click()
  await expect(page.getByLabel("s1", { exact: true })).toBeFocused()
  await page.keyboard.press("Shift+Tab")
  await expect(dialog).toBeHidden()
  await expect(trigger).toBeFocused()
})

test("in a Drawer, Tab past a Popover's last field closes the Popover and stays in the Drawer", async ({ page }) => {
  await page.getByRole("button", { name: "Open drawer" }).click()
  const drawer = page.getByRole("dialog", { name: "Drawer title" })
  await expect(drawer).toBeVisible()
  await page.getByRole("button", { name: "Open drawer popover" }).click()
  const popover = page.getByRole("dialog", { name: "Popover drawer popover" })
  await expect(page.getByLabel("d1", { exact: true })).toBeFocused()
  await page.keyboard.press("Tab")
  await expect(page.getByLabel("d2", { exact: true })).toBeFocused()
  await page.keyboard.press("Tab")
  await expect(popover).toBeHidden()
  await expect(page.getByRole("button", { name: "Drawer after" })).toBeFocused()
  await expect(drawer).toBeVisible()

  // a trigger that is the Drawer's last Tab stop: Tab goes round to the Drawer's first
  await page.getByRole("button", { name: "Open drawer last" }).click()
  await expect(page.getByLabel("e1", { exact: true })).toBeFocused()
  await page.keyboard.press("Tab")
  await page.keyboard.press("Tab")
  await expect(page.getByRole("dialog", { name: "Popover drawer last" })).toBeHidden()
  await expect(drawer.getByRole("button", { name: "Close" })).toBeFocused()
  await expect(drawer).toBeVisible()
})

test("in a Drawer, the first Escape hides a tooltip and the second closes the Drawer", async ({ page }) => {
  await page.getByRole("button", { name: "Open drawer" }).click()
  const drawer = page.getByRole("dialog", { name: "Drawer title" })
  await expect(drawer).toBeVisible()
  await page.keyboard.press("Tab")
  await expect(page.getByRole("button", { name: "Tip target" })).toBeFocused()
  const tip = page.getByRole("tooltip")
  await expect(tip).toHaveText("Tip text")
  await page.keyboard.press("Escape")
  await expect(tip).toBeHidden()
  await expect(drawer).toBeVisible()
  await page.keyboard.press("Escape")
  await expect(drawer).toBeHidden()
})

test("a non-modal Drawer: no aria-modal, the page stays usable, Escape inside closes it (a Popover in it first)", async ({ page }) => {
  const opener = page.getByRole("button", { name: "Open side panel" })
  await opener.click()
  const panel = page.getByRole("dialog", { name: "Side panel title" })
  await expect(panel).toBeVisible()
  await expect(panel).not.toHaveAttribute("aria-modal", /.*/)
  await expect(page.locator('[aria-modal="true"]')).toHaveCount(0)
  // the focus moves in (its first control: Close, as in the modal Drawer)
  await expect(panel.getByRole("button", { name: "Close" })).toBeFocused()
  // the page beside it takes clicks and keys; Escape there leaves the panel open
  await page.getByRole("button", { name: "Page button" }).click()
  await expect(page.getByTestId("page-clicks")).toHaveText("1")
  await page.keyboard.press("Escape")
  await expect(panel).toBeVisible()
  // a Popover opened in the panel closes on the first Escape, the panel on the second
  await page.getByRole("button", { name: "Open panel popover" }).click()
  const popover = page.getByRole("dialog", { name: "Popover panel popover" })
  await expect(page.getByLabel("q1", { exact: true })).toBeFocused()
  await page.keyboard.press("Escape")
  await expect(popover).toBeHidden()
  await expect(panel).toBeVisible()
  await expect(page.getByRole("button", { name: "Open panel popover" })).toBeFocused()
  await page.keyboard.press("Escape")
  await expect(panel).toBeHidden()
  await expect(opener).toBeFocused()
})

test("Ctrl+A selects the whole grid on a Cyrillic layout too (key ф, code KeyA), but not AZERTY's Ctrl+Q", async ({ page }) => {
  const count = page.getByTestId("grid-selected")
  const cell = page.getByRole("gridcell", { name: "0:0" })
  await cell.click()
  await expect(count).toHaveText("1")
  await page.keyboard.press("Control+a")
  await expect(count).toHaveText("9")
  await page.keyboard.press("Escape")
  await expect(count).toHaveText("1")

  const press = (key: string, code: string) =>
    cell.evaluate(
      (el, k) => {
        const e = new KeyboardEvent("keydown", { key: k.key, code: k.code, ctrlKey: true, bubbles: true, cancelable: true })
        el.dispatchEvent(e)
        return e.defaultPrevented
      },
      { key, code },
    )
  // AZERTY: the key at KeyA types "q"; Ctrl+Q is not select-all
  expect(await press("q", "KeyA")).toBe(false)
  await expect(count).toHaveText("1")
  // Russian ЙЦУКЕН: the key at KeyA types "ф"; Ctrl+ф is select-all
  expect(await press("ф", "KeyA")).toBe(true)
  await expect(count).toHaveText("9")
})

// 2L (ADR-073's proposal): a Dialog or Drawer keeps its content hidden until one effect pass after it opens,
// so a form its parent resets in a passive effect on opening is never seen, or typed into, with the last
// session's values. Each overlay is opened twice: the second time after a close that left "last session" in
// the parent's state.
for (const kind of ["dialog", "drawer", "panel"] as const) {
  test(`a ${kind} never shows the last session's form values in its first frame`, async ({ page }) => {
    const commits = () => page.evaluate((k) => (window as unknown as { __commits: Record<string, string[]> }).__commits[k] ?? [], kind)
    for (const round of [1, 2]) {
      await page.evaluate((k) => {
        ;(window as unknown as { __commits: Record<string, string[]> }).__commits[k] = []
      }, kind)
      await page.getByRole("button", { name: `Open reset ${kind}` }).click()
      await expect(page.getByLabel(`${kind} amount`)).toHaveValue(`fresh ${round}`)
      const seen = (await commits()).filter((v) => v !== "(hidden)")
      expect(seen, `opening ${round}`).not.toContain("last session")
      expect(seen[0]).toBe(`fresh ${round}`)
      await page.getByRole("button", { name: `Done ${kind}` }).click()
      await expect(page.getByLabel(`${kind} amount`)).toHaveCount(0)
    }
  })
}
