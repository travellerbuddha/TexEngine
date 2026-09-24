// The S7 keyboard check (PRICING_WORKSPACE_UX.md §3.10, §3.19) as browser tests on the harness
// page tests/dom/keyboard.tsx: Popover (Escape, focus in and back, outside pointerdown, flip and
// clamp, phone sheet), Menu (roving focus, typeahead, Enter/Space, Escape, Tab), Tooltip (300 ms on
// hover and keyboard focus, Escape, blur, aria-describedby, never on touch) and the grid hooks.
// Run: `npm run test:dom` (PW_CHROMIUM=/path/to/chrome when Playwright's browsers are elsewhere).
import { expect, test, type Locator, type Page } from "@playwright/test"

// set by the harness page (tests/dom/keyboard.tsx)
declare global {
  interface Window {
    __log: string[]
    __probe: { focus?: number; pointer?: number }
    __tips: Record<string, number>
  }
}

const HARNESS = "/tests/dom/keyboard.html"

test.use({ viewport: { width: 1200, height: 800 } })

test.beforeEach(async ({ page }) => {
  await page.goto(HARNESS)
  await expect(page.getByTestId("grid")).toBeVisible()
})

const ranLog = (page: Page) => page.evaluate(() => window.__log)

async function resetProbe(page: Page) {
  await page.evaluate(() => {
    window.__probe = {}
    window.__tips = {}
  })
}

/** Milliseconds from the probe's focus / pointer entry to the tooltip `text` appearing. */
async function tooltipDelay(page: Page, from: "focus" | "pointer", text: string): Promise<number> {
  return page.evaluate(([f, t]) => (window.__tips[t] ?? NaN) - (window.__probe[f as "focus" | "pointer"] ?? NaN), [from, text])
}

async function box(l: Locator) {
  const b = await l.boundingBox()
  expect(b, "bounding box").not.toBeNull()
  return b!
}

// ------------------------------------------------------------------------------------ Popover

test("Popover: non-modal labelled dialog; focus moves to initialFocusRef and back to the trigger on Escape", async ({ page }) => {
  const trigger = page.getByTestId("pop-trigger")
  await trigger.focus()
  await page.keyboard.press("Enter")
  const dialog = page.getByRole("dialog", { name: "Edit price: Superior · P4" })
  await expect(dialog).toBeVisible()
  expect(await dialog.getAttribute("aria-modal")).toBeNull()
  const labelId = await dialog.getAttribute("aria-labelledby")
  expect(await page.locator(`[id="${labelId}"]`).textContent()).toBe("Edit price: Superior · P4")
  // initialFocusRef wins over the first focusable element
  await expect(page.getByLabel("Value", { exact: true })).toBeFocused()

  // bottom-start: below the trigger, left edges aligned
  const t = await box(trigger)
  const d = await box(dialog)
  expect(await dialog.getAttribute("data-placement")).toBe("bottom-start")
  expect(d.y).toBeGreaterThanOrEqual(t.y + t.height)
  expect(Math.abs(d.x - t.x)).toBeLessThanOrEqual(1)

  await page.keyboard.press("Escape")
  await expect(dialog).toBeHidden()
  await expect(trigger).toBeFocused()
})

test("Popover: the trigger toggles it; an outside pointerdown closes it and leaves focus where the user clicked", async ({ page }) => {
  const trigger = page.getByTestId("pop-trigger")
  const dialog = page.getByRole("dialog", { name: "Edit price: Superior · P4" })
  await trigger.click()
  await expect(dialog).toBeVisible()
  await trigger.click()
  await expect(dialog).toBeHidden()

  await trigger.click()
  await expect(dialog).toBeVisible()
  await page.getByTestId("after").click()
  await expect(dialog).toBeHidden()
  await expect(page.getByTestId("after")).toBeFocused()
})

test("Popover: a Menu inside it closes first on Escape, and clicking one of its items does not close the Popover", async ({ page }) => {
  const trigger = page.getByTestId("pop-trigger")
  const dialog = page.getByRole("dialog", { name: "Edit price: Superior · P4" })
  await trigger.click()
  const more = dialog.getByRole("button", { name: "More" })
  await more.focus()
  await page.keyboard.press("ArrowDown")
  const inner = page.getByRole("menu", { name: "More" })
  await expect(inner).toBeVisible()
  await expect(page.getByRole("menuitem", { name: "Set as base" })).toBeFocused()

  await page.keyboard.press("Escape")
  await expect(inner).toBeHidden()
  await expect(dialog).toBeVisible()
  await expect(more).toBeFocused()

  await more.click()
  await page.getByRole("menuitem", { name: "Move up" }).click()
  await expect(inner).toBeHidden()
  await expect(dialog).toBeVisible()
  expect(await ranLog(page)).toEqual(["pop:move-up"])

  await page.keyboard.press("Escape")
  await expect(dialog).toBeHidden()
  await expect(trigger).toBeFocused()
})

test("Popover: near the bottom-right corner it flips above its trigger and stays inside the viewport", async ({ page }) => {
  const trigger = page.getByRole("button", { name: "Corner" })
  await trigger.click()
  const dialog = page.getByRole("dialog", { name: "Corner popover" })
  await expect(dialog).toBeVisible()
  await expect(page.getByLabel("Corner value")).toBeFocused()
  expect(await dialog.getAttribute("data-placement")).toBe("top-start")
  const t = await box(trigger)
  const d = await box(dialog)
  const view = page.viewportSize()!
  expect(d.y + d.height).toBeLessThanOrEqual(t.y + 0.5)
  expect(d.x).toBeGreaterThanOrEqual(8 - 0.5)
  expect(d.x + d.width).toBeLessThanOrEqual(view.width - 8 + 0.5)
  await page.keyboard.press("Escape")
  await expect(dialog).toBeHidden()
  await expect(trigger).toBeFocused()
})

// ------------------------------------------------------------------------------------ Menu

test("Menu: menu button semantics; arrows, Home/End and wrap move the roving focus", async ({ page }) => {
  const btn = page.getByRole("button", { name: "Row actions: Superior" })
  expect(await btn.getAttribute("aria-haspopup")).toBe("menu")
  expect(await btn.getAttribute("aria-expanded")).toBe("false")
  expect(await btn.getAttribute("aria-controls")).toBeNull()
  await btn.focus()
  await page.keyboard.press("Enter")
  const menu = page.getByRole("menu", { name: "Row actions: Superior" })
  await expect(menu).toBeVisible()
  expect(await btn.getAttribute("aria-expanded")).toBe("true")
  expect(await btn.getAttribute("aria-controls")).toBe(await menu.getAttribute("id"))
  // every item is out of the Tab order; focus roves between them
  expect(await menu.getByRole("menuitem").evaluateAll((els) => els.map((e) => (e as HTMLElement).tabIndex))).toEqual([-1, -1, -1, -1, -1, -1, -1])

  const item = (name: string) => page.getByRole("menuitem", { name, exact: true })
  await expect(item("Set as base")).toBeFocused()
  const steps: Array<[string, string]> = [
    ["ArrowDown", "Derive from…"],
    ["ArrowDown", "Capacity…"],
    // the separator is skipped
    ["ArrowDown", "Move up"],
    ["End", "Remove room"],
    ["Home", "Set as base"],
    ["ArrowUp", "Remove room"],
    ["ArrowDown", "Set as base"],
  ]
  for (const [key, name] of steps) {
    await page.keyboard.press(key)
    await expect(item(name), `${key} → ${name}`).toBeFocused()
  }
  // the keys stay in the menu: the page does not scroll
  expect(await page.evaluate(() => window.scrollY)).toBe(0)
})

test("Menu: first-letter typeahead cycles through matches, uses textValue, and ignores case", async ({ page }) => {
  const btn = page.getByRole("button", { name: "Row actions: Superior" })
  await btn.focus()
  await page.keyboard.press("Enter")
  const item = (name: string) => page.getByRole("menuitem", { name, exact: true })
  await expect(item("Set as base")).toBeFocused()
  const steps: Array<[string, string]> = [
    ["m", "Move up"],
    ["m", "Move down"],
    ["m", "Move up"],
    ["d", "Derive from…"],
    ["t", "▶ Test this price"],
    ["Shift+R", "Remove room"],
    ["s", "Set as base"],
    // no match: focus stays
    ["q", "Set as base"],
  ]
  for (const [key, name] of steps) {
    await page.keyboard.press(key)
    await expect(item(name), `${key} → ${name}`).toBeFocused()
  }
})

test("Menu: Enter and Space run an item, close the menu and return focus; a disabled item does not run", async ({ page }) => {
  const btn = page.getByRole("button", { name: "Row actions: Superior" })
  const menu = page.getByRole("menu", { name: "Row actions: Superior" })
  const item = (name: string) => page.getByRole("menuitem", { name, exact: true })
  await btn.focus()
  await page.keyboard.press("Enter")
  await expect(item("Set as base")).toBeFocused()
  await page.keyboard.press("c")
  await expect(item("Capacity…")).toBeFocused()
  expect(await item("Capacity…").getAttribute("aria-disabled")).toBe("true")
  await page.keyboard.press("Enter")
  await expect(menu).toBeVisible()
  expect(await ranLog(page)).toEqual([])

  await page.keyboard.press("d")
  await page.keyboard.press("Enter")
  await expect(menu).toBeHidden()
  await expect(btn).toBeFocused()
  expect(await btn.getAttribute("aria-expanded")).toBe("false")
  expect(await ranLog(page)).toEqual(["derive"])

  // ArrowUp on the button opens the menu on its last item
  await page.keyboard.press("ArrowUp")
  await expect(menu).toBeVisible()
  await expect(item("Remove room")).toBeFocused()
  await page.keyboard.press("m")
  await page.keyboard.press("m")
  await expect(item("Move down")).toBeFocused()
  expect(await item("Move down").getAttribute("aria-keyshortcuts")).toBe("Alt+ArrowDown")
  await page.keyboard.press(" ")
  await expect(menu).toBeHidden()
  await expect(btn).toBeFocused()
  expect(await ranLog(page)).toEqual(["derive", "move-down"])

  // a pointer click runs an item too
  await btn.click()
  await item("Set as base").click()
  await expect(menu).toBeHidden()
  expect(await ranLog(page)).toEqual(["derive", "move-down", "set-base"])
})

test("Menu: Escape closes and returns focus; Tab and Shift+Tab close and move on from the button", async ({ page }) => {
  const btn = page.getByRole("button", { name: "Row actions: Superior" })
  const menu = page.getByRole("menu", { name: "Row actions: Superior" })
  const first = page.getByRole("menuitem", { name: "Set as base", exact: true })
  await btn.focus()
  await page.keyboard.press("Enter")
  await expect(first).toBeFocused()
  await page.keyboard.press("Escape")
  await expect(menu).toBeHidden()
  await expect(btn).toBeFocused()

  await page.keyboard.press("Enter")
  await expect(first).toBeFocused()
  await page.keyboard.press("Tab")
  await expect(menu).toBeHidden()
  await expect(page.getByTestId("tip-btn")).toBeFocused()

  await btn.focus()
  await page.keyboard.press("Enter")
  await expect(first).toBeFocused()
  await page.keyboard.press("Shift+Tab")
  await expect(menu).toBeHidden()
  await expect(page.getByTestId("pop-trigger")).toBeFocused()

  // outside pointerdown and the button itself close it
  await btn.click()
  await expect(menu).toBeVisible()
  await page.getByTestId("after").click()
  await expect(menu).toBeHidden()
  await btn.click()
  await expect(menu).toBeVisible()
  await btn.click()
  await expect(menu).toBeHidden()
  expect(await ranLog(page)).toEqual([])
})

test("Menu: inside a modal Drawer it is portaled into the Drawer, stays anchored, and Escape closes it before the Drawer", async ({ page }) => {
  await page.getByTestId("drawer-btn").click()
  const drawer = page.getByRole("dialog", { name: "Bands" })
  await expect(drawer).toBeVisible()
  const btn = page.getByRole("button", { name: "Band actions" })
  await btn.focus()
  await page.keyboard.press("Enter")
  const menu = page.getByRole("menu", { name: "Band actions" })
  await expect(menu).toBeVisible()
  await expect(page.getByRole("menuitem", { name: "Rename" })).toBeFocused()
  expect(await menu.evaluate((m) => !!m.closest('[aria-modal="true"]'))).toBe(true)
  const b = await box(btn)
  const m = await box(menu)
  expect(Math.abs(m.y - (b.y + b.height + 4))).toBeLessThanOrEqual(1.5)
  expect(Math.abs(m.x - b.x)).toBeLessThanOrEqual(1.5)
  // on top of the Drawer: a hit test lands in the menu
  expect(
    await menu.evaluate((el) => {
      const r = el.getBoundingClientRect()
      const hit = document.elementFromPoint(r.left + 20, r.top + 12)
      return !!hit && el.contains(hit)
    }),
  ).toBe(true)
  await page.keyboard.press("Escape")
  await expect(menu).toBeHidden()
  await expect(drawer).toBeVisible()
  await expect(btn).toBeFocused()
  await page.keyboard.press("Escape")
  await expect(drawer).toBeHidden()
})

// ------------------------------------------------------------------------------------ Tooltip

const TIP = "Published versions are immutable"

test("Tooltip: the text is the trigger's aria-describedby; keyboard focus shows it after 300 ms; Escape and blur hide it", async ({ page }) => {
  const tipBtn = page.getByTestId("tip-btn")
  const describedBy = await tipBtn.getAttribute("aria-describedby")
  expect(describedBy).toBeTruthy()
  expect(await page.locator(`[id="${describedBy}"]`).textContent()).toBe(TIP)
  expect(await tipBtn.getAttribute("title")).toBeNull()

  const tip = page.getByRole("tooltip", { name: TIP })
  // keyboard focus (focus-visible): Tab from the Row actions button
  await page.getByRole("button", { name: "Row actions: Superior" }).focus()
  await resetProbe(page)
  await page.keyboard.press("Tab")
  await expect(tipBtn).toBeFocused()
  await expect(tip).toBeVisible()
  expect(await tooltipDelay(page, "focus", TIP)).toBeGreaterThanOrEqual(290)
  // placement "top", but the trigger is at the top edge of the page: it flips below it
  const b = await box(tipBtn)
  const tt = await box(tip)
  expect(await tip.getAttribute("data-placement")).toBe("bottom")
  expect(tt.y).toBeGreaterThanOrEqual(b.y + b.height - 0.5)

  await page.keyboard.press("Escape")
  await expect(tip).toBeHidden()
  await expect(tipBtn).toBeFocused()

  await page.keyboard.press("Shift+Tab")
  await page.keyboard.press("Tab")
  await expect(tip).toBeVisible()
  await page.keyboard.press("Tab")
  await expect(tip).toBeHidden()
  await expect(page.getByTestId("after")).toBeFocused()
})

test("Tooltip: hover shows it after 300 ms and leaving hides it; focus from a click does not show it", async ({ page }) => {
  const tipBtn = page.getByTestId("tip-btn")
  const tip = page.getByRole("tooltip", { name: TIP })
  await page.mouse.move(5, 790)
  await resetProbe(page)
  await tipBtn.hover()
  await expect(tip).toBeVisible()
  expect(await tooltipDelay(page, "pointer", TIP)).toBeGreaterThanOrEqual(290)
  await page.mouse.move(5, 790)
  await expect(tip).toBeHidden()

  // a click (press) hides it and the focus it gives is not keyboard focus
  await tipBtn.click()
  await expect(tipBtn).toBeFocused()
  await page.waitForTimeout(600)
  await expect(page.getByRole("tooltip")).toHaveCount(0)

  // an icon-only menu button: the tooltip repeats its label, so it is not a description
  const icon = page.getByRole("button", { name: "Row actions: Superior" })
  expect(await icon.getAttribute("aria-describedby")).toBeNull()
  expect(await icon.getAttribute("title")).toBeNull()
  await page.mouse.move(5, 790)
  await icon.hover()
  await expect(page.getByRole("tooltip", { name: "Row actions: Superior" })).toBeVisible()
})

// ------------------------------------------------------------------------------------ Grid

type GridState = { selected: Array<{ r: number; c: number }>; edit: string; right: number; down: number }
const gridState = async (page: Page): Promise<GridState> => JSON.parse((await page.getByTestId("grid-state").textContent()) ?? "{}")
const activeCell = (page: Page) => page.evaluate(() => document.activeElement?.getAttribute("data-cell") ?? null)
const cell = (page: Page, r: number, c: number) => page.locator(`[data-cell="${r}:${c}"]`)
const at = (...pairs: Array<[number, number]>) => pairs.map(([r, c]) => ({ r, c }))

test("Grid: one tab stop, roving tabindex, Shift+Arrow skips read-only cells, keys never scroll the page", async ({ page }) => {
  const stops = () => page.locator('[data-testid="grid"] [role="gridcell"][tabindex="0"]').count()
  expect(await stops()).toBe(1)
  expect(await page.locator('[data-testid="grid"] [role="gridcell"][tabindex="-1"]').count()).toBe(19)

  await cell(page, 0, 1).click()
  await page.keyboard.press("ArrowRight")
  await expect.poll(() => activeCell(page)).toBe("0:2")
  expect(await cell(page, 0, 2).getAttribute("tabindex")).toBe("0")
  expect(await stops()).toBe(1)

  const y0 = await page.evaluate(() => window.scrollY)
  await page.keyboard.press("Shift+ArrowDown")
  await page.keyboard.press("Shift+ArrowDown")
  await expect.poll(() => activeCell(page)).toBe("2:2")
  expect((await gridState(page)).selected).toEqual(at([0, 2], [2, 2]))
  expect(await cell(page, 2, 2).getAttribute("aria-selected")).toBe("true")
  expect(await cell(page, 1, 2).getAttribute("aria-selected")).toBe("false")

  await page.keyboard.press("Escape")
  expect((await gridState(page)).selected).toEqual(at([2, 2]))

  const moves: Array<[string, string]> = [
    ["Home", "2:0"],
    ["Control+End", "3:4"],
    ["Control+Home", "0:0"],
    ["PageDown", "3:0"],
    ["End", "3:4"],
    ["PageUp", "0:4"],
  ]
  for (const [key, want] of moves) {
    await page.keyboard.press(key)
    await expect.poll(() => activeCell(page), key).toBe(want)
  }
  expect(await page.evaluate(() => window.scrollY)).toBe(y0)
})

test("Grid: typing, Enter, F2 and double-click ask to edit; onKey runs first", async ({ page }) => {
  await cell(page, 0, 4).click()
  await page.keyboard.press("7")
  expect((await gridState(page)).edit).toBe("0:4:7")
  await page.keyboard.press("Delete")
  expect((await gridState(page)).edit).toBe("delete")
  await page.keyboard.press("Enter")
  expect((await gridState(page)).edit).toBe("0:4:<select-all>")
  await page.keyboard.press("Delete")
  await page.keyboard.press("F2")
  expect((await gridState(page)).edit).toBe("0:4:<select-all>")
  await cell(page, 2, 3).dblclick()
  expect((await gridState(page)).edit).toBe("2:3:<select-all>")
})

test("Grid: Ctrl+A, Ctrl+Click, Shift+Click and header clicks select editable cells; fill plans follow", async ({ page }) => {
  await cell(page, 0, 0).click()
  await page.keyboard.press("Control+a")
  let s = await gridState(page)
  expect(s.selected).toHaveLength(15)
  expect(s.right).toBe(12)
  expect(s.down).toBe(10)
  await page.keyboard.press("Escape")
  expect((await gridState(page)).selected).toHaveLength(1)

  await cell(page, 0, 0).click()
  await cell(page, 3, 4).click({ modifiers: ["Control"] })
  expect((await gridState(page)).selected).toEqual(at([0, 0], [3, 4]))

  await cell(page, 0, 0).click()
  await cell(page, 2, 1).click({ modifiers: ["Shift"] })
  s = await gridState(page)
  expect(s.selected).toEqual(at([0, 0], [0, 1], [2, 0], [2, 1]))
  expect(s.right).toBe(2)
  expect(s.down).toBe(2)
  expect(await activeCell(page)).toBe("2:1")
  expect(await page.evaluate(() => String(window.getSelection()))).toBe("")

  await page.getByTestId("col2").click()
  expect((await gridState(page)).selected).toEqual(at([0, 2], [2, 2], [3, 2]))
  await page.getByTestId("col4").click({ modifiers: ["Control"] })
  expect((await gridState(page)).selected).toEqual(at([0, 2], [0, 4], [2, 2], [2, 4], [3, 2], [3, 4]))
  await page.getByTestId("row3").click()
  expect((await gridState(page)).selected).toEqual(at([3, 0], [3, 1], [3, 2], [3, 3], [3, 4]))
  // a read-only row has nothing to select: the selection stays
  await page.getByTestId("row1").click()
  expect((await gridState(page)).selected).toEqual(at([3, 0], [3, 1], [3, 2], [3, 3], [3, 4]))
})

test("Grid: a burst of Shift+Arrow keys before a frame keeps the whole range", async ({ page }) => {
  await cell(page, 2, 0).click()
  await page.evaluate(() => {
    const el = document.querySelector('[data-cell="2:0"]')!
    for (let i = 0; i < 3; i++) el.dispatchEvent(new KeyboardEvent("keydown", { key: "ArrowRight", shiftKey: true, bubbles: true, cancelable: true }))
  })
  await expect.poll(() => activeCell(page)).toBe("2:3")
  expect((await gridState(page)).selected).toEqual(at([2, 0], [2, 1], [2, 2], [2, 3]))
})

test("Grid: a cell tooltip shows on keyboard focus, hides on Escape and when the active cell moves", async ({ page }) => {
  const tip = page.getByRole("tooltip", { name: "Cell 0:0 tooltip" })
  await cell(page, 0, 1).click()
  await page.keyboard.press("ArrowLeft")
  await expect.poll(() => activeCell(page)).toBe("0:0")
  await expect(tip).toBeVisible()
  // with room above the cell it keeps the default placement "top"
  expect(await tip.getAttribute("data-placement")).toBe("top")
  const c = await box(cell(page, 0, 0))
  const tt = await box(tip)
  expect(tt.y + tt.height).toBeLessThanOrEqual(c.y + 0.5)
  await page.keyboard.press("Escape")
  await expect(tip).toBeHidden()
  await expect.poll(() => activeCell(page)).toBe("0:0")
  // wait for each move to land: a key pressed before the frame that moves focus goes to the
  // cell that still has it, so focus would never leave 0:0 and the tooltip would stay dismissed
  await page.keyboard.press("ArrowRight")
  await expect.poll(() => activeCell(page)).toBe("0:1")
  await page.keyboard.press("ArrowLeft")
  await expect.poll(() => activeCell(page)).toBe("0:0")
  await expect(tip).toBeVisible()
  await page.keyboard.press("ArrowDown")
  await expect.poll(() => activeCell(page)).toBe("1:0")
  await expect(tip).toBeHidden()
})

// ------------------------------------------------------------------------------------ Phone

test.describe("phone (< 640 px, touch)", () => {
  test.use({ viewport: { width: 375, height: 700 }, hasTouch: true, isMobile: true })

  test("Popover is a non-modal bottom sheet with a close button; a tap never shows a tooltip", async ({ page }) => {
    // the harness fits the phone: the sheet spans the viewport, not a wider page
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(375)
    const trigger = page.getByTestId("pop-trigger")
    await trigger.tap()
    const dialog = page.getByRole("dialog", { name: "Edit price: Superior · P4" })
    await expect(dialog).toBeVisible()
    expect(await dialog.getAttribute("data-sheet")).toBe("true")
    expect(await dialog.getAttribute("aria-modal")).toBeNull()
    const d = await box(dialog)
    expect(Math.abs(d.x)).toBeLessThanOrEqual(0.5)
    expect(Math.abs(d.width - 375)).toBeLessThanOrEqual(0.5)
    expect(Math.abs(d.y + d.height - 700)).toBeLessThanOrEqual(0.5)
    await expect(page.getByLabel("Value", { exact: true })).toBeFocused()
    await dialog.getByRole("button", { name: "Close" }).tap()
    await expect(dialog).toBeHidden()
    await expect(trigger).toBeFocused()

    await trigger.tap()
    await expect(dialog).toBeVisible()
    await page.keyboard.press("Escape")
    await expect(dialog).toBeHidden()

    await page.getByTestId("tip-btn").tap()
    await page.waitForTimeout(600)
    await expect(page.getByRole("tooltip")).toHaveCount(0)
  })
})
