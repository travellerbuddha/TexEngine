// Browser checks of the workspace undo history's React binding (PRICING_WORKSPACE_UX.md §3.10;
// slice S10) on the harness page tests/dom/history.tsx, with Playwright's clock: the
// "Applied to N cells · Undo" toast (10 s, held while hovered or focused, gone with any later
// change, its Undo undoing its own entry only) and the Rule tables' keystrokes recorded through
// `record` (one entry per table within 1.5 s; undoing a matrix entry never drops them).
// Run: `npm run test:dom` (PW_CHROMIUM=/path/to/chrome when Playwright's browsers are elsewhere).
import { expect, test, type Page } from "@playwright/test"

// set by the harness page (tests/dom/history.tsx)
declare global {
  interface Window {
    __log: string[]
  }
}

const HARNESS = "/tests/dom/history.html"
const T0 = new Date("2026-09-25T09:00:00Z")

test.beforeEach(async ({ page }) => {
  await page.clock.install({ time: T0 })
  await page.goto(HARNESS)
  await expect(page.getByRole("button", { name: "Fill" })).toBeVisible()
  // time moves only when a test says so
  await page.clock.pauseAt(new Date(T0.getTime() + 60_000))
})

const rates = (page: Page) => page.getByTestId("rates")
const size = (page: Page) => page.getByTestId("size")
const toast = (page: Page) => page.getByTestId("undo-toast")
const ranLog = (page: Page) => page.evaluate(() => window.__log)
/** the harness's toolbar (the toast has an Undo of its own) */
const button = (page: Page, name: string) => page.getByRole("group", { name: "Toolbar" }).getByRole("button", { name, exact: true })

test("the toast of a bulk entry stays 10 s, longer while hovered or focused, and its Undo undoes that entry", async ({ page }) => {
  await button(page, "Fill").click()
  await expect(toast(page)).toContainText("Applied to 1 cell")
  await expect(rates(page)).toHaveText("STD:P1:70")
  await page.clock.runFor(9_900)
  await expect(toast(page)).toBeVisible()
  await page.clock.runFor(200)
  await expect(toast(page)).toHaveCount(0)

  // held while the pointer is on it; 10 s again once it leaves
  await button(page, "Fill").click()
  await toast(page).hover()
  await page.clock.runFor(30_000)
  await expect(toast(page)).toBeVisible()
  await page.mouse.move(5, 5)
  await page.clock.runFor(9_900)
  await expect(toast(page)).toBeVisible()
  await page.clock.runFor(200)
  await expect(toast(page)).toHaveCount(0)

  // held while the focus is in it (keyboard users reach its Undo)
  await button(page, "Fill").click()
  await toast(page).getByRole("button", { name: "Undo" }).focus()
  await page.clock.runFor(30_000)
  await expect(toast(page)).toBeVisible()

  // its Undo undoes the third Fill only, and the toast goes
  await expect(rates(page)).toHaveText("STD:P1:70,STD:P2:70,STD:P3:70")
  await toast(page).getByRole("button", { name: "Undo" }).click()
  await expect(rates(page)).toHaveText("STD:P1:70,STD:P2:70")
  await expect(toast(page)).toHaveCount(0)
  expect(await ranLog(page)).toEqual(["toast:Fill"])
  // and a new toast starts unheld (the one that went while focused never got its blur)
  await button(page, "Fill").click()
  await expect(toast(page)).toBeVisible()
  await page.mouse.move(5, 5)
  await page.clock.runFor(10_100)
  await expect(toast(page)).toHaveCount(0)
})

test("the toast goes with any later change: another entry, a Rule table keystroke, an undo", async ({ page }) => {
  await button(page, "Fill").click()
  await expect(toast(page)).toBeVisible()
  await button(page, "Edit").click()
  await expect(toast(page)).toHaveCount(0)
  // the toolbar's Undo undoes the later entry, not the Fill
  await button(page, "Undo").click()
  await expect(rates(page)).toHaveText("STD:P1:70")
  expect(await ranLog(page)).toEqual(["undo:Edit"])

  await button(page, "Fill").click()
  await expect(toast(page)).toBeVisible()
  await page.getByLabel("Family price").pressSequentially("9")
  await expect(toast(page)).toHaveCount(0)

  await button(page, "Fill").click()
  await expect(toast(page)).toBeVisible()
  await button(page, "Undo").click()
  await expect(toast(page)).toHaveCount(0)
})

test("Rule table keystrokes are one entry per table within 1.5 s, and undoing a matrix entry never drops them", async ({ page }) => {
  await button(page, "Fill").click()
  await expect(size(page)).toHaveText("1")
  const input = page.getByLabel("Family price")
  // 9, 90, 90.5 within 1.5 s of each other: one entry
  await input.press("9")
  await page.clock.runFor(700)
  await input.press("0")
  await page.clock.runFor(700)
  await input.pressSequentially(".5")
  await expect(rates(page)).toHaveText("STD:P1:70,FAM:*:90.5")
  await expect(size(page)).toHaveText("2")
  // a keystroke 2 s later is an entry of its own
  await page.clock.runFor(2_000)
  await input.press("0")
  await expect(rates(page)).toHaveText("STD:P1:70,FAM:*:90.50")
  await expect(size(page)).toHaveText("3")

  // undo walks back through the Rule table's entries first; the Fill's undo keeps nothing of them
  // only because they were undone before it (as built in S9 an undo of the Fill put back the
  // table as it was before the Fill and silently dropped the Family price typed after it)
  await button(page, "Undo").click()
  await expect(rates(page)).toHaveText("STD:P1:70,FAM:*:90.5")
  await button(page, "Undo").click()
  await expect(rates(page)).toHaveText("STD:P1:70")
  await button(page, "Undo").click()
  await expect(rates(page)).toHaveText("")
  expect(await ranLog(page)).toEqual(["undo:Rule table: Room prices", "undo:Rule table: Room prices", "undo:Fill"])
  // redo puts all of it back, in order
  for (let i = 0; i < 3; i++) await button(page, "Redo").click()
  await expect(rates(page)).toHaveText("STD:P1:70,FAM:*:90.50")
  // a keystroke after an undo starts a new entry (it never joins the undone one)
  await button(page, "Undo").click()
  await input.press("End")
  await input.press("5")
  await expect(rates(page)).toHaveText("STD:P1:70,FAM:*:90.55")
  await expect(button(page, "Redo")).toBeDisabled()
  await button(page, "Undo").click()
  await expect(rates(page)).toHaveText("STD:P1:70,FAM:*:90.5")
})
