// The Pricing Workspace for viewers who cannot edit (PRICING_WORKSPACE_UX.md §3.14, §3.17, §3.21,
// §5.3), on the desktop and the Pixel 7 projects:
// - a published version is read-only (no editor, aria-readonly grids, no basis popover, no "Add
//   room"), fits a 375 px phone without sideways page scroll, and never asks validate_version;
// - an agent (price.view without cost access) gets the catalogue: rooms and boards, no amounts, no
//   page error, no call to price_matrix, validate_version or preview_price, and no 403 answer.
import { expect, test, type Page, type Response } from "@playwright/test"
import { login, trackErrors } from "./helpers"
import { expectPublishedReadOnly, occupancyLadder, priceMatrix } from "./flows/contracts"
import { archiveAll, N, newDraft, occ, ownerDraft, publish, versionPath, watchContracts, type NewContract } from "./flows/workspace"

test.use({ locale: "en-US", actionTimeout: 15_000, navigationTimeout: 30_000 })

const made: string[] = []
let published: NewContract
test.beforeAll(async ({ browser }) => {
  const page = await browser.newPage()
  await login(page, "revenue@demo.tex")
  const data = ownerDraft()
  data.occupancy_rules.push(occ({ target: "CHILD", position: 1, age_band: "CHB", combination: "2+2", value: "0.5" }))
  published = await newDraft(page, "E2E-PWM", data)
  made.push(published.contract)
  await publish(page, published.version)
  await page.close()
})
test.afterAll(async ({ browser }) => archiveAll(browser, made, "pricing workspace mobile e2e clean-up"))

const noHorizontalScroll = (page: Page) => page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth)

/** The 403 answers the page gets. */
function forbidden(page: Page) {
  const seen: string[] = []
  page.on("response", (r: Response) => {
    if (r.status() === 403) seen.push(`${r.request().method()} ${new URL(r.url()).pathname}`)
  })
  return seen
}

test("a published version is read-only in the workspace, fits a 375 px phone, and is never sent to validate_version", async ({ page }) => {
  test.setTimeout(120_000)
  const noErrors = trackErrors(page)
  await login(page, "revenue@demo.tex")
  const calls = watchContracts(page)
  const denied = forbidden(page)
  await page.goto(versionPath(published, "#pricing"))
  await expect(priceMatrix(page)).toBeVisible()
  await expectPublishedReadOnly(page)
  // the ladder and the boards grid are read-only too
  await page.goto(versionPath(published, "#occupancy"))
  await expect(occupancyLadder(page)).toHaveAttribute("aria-readonly", "true")
  await expect(occupancyLadder(page).getByRole("textbox")).toHaveCount(0)
  await expect(page.getByRole("region", { name: /^Special combinations/ }).getByRole("button", { name: "Add combination" })).toHaveCount(0)
  // the resolved prices come from the frozen version
  await expect(priceMatrix(page).getByRole("gridcell", { name: `${N.SUP} · P1: resolved price, EUR 80.50`, exact: true })).toBeAttached()
  expect(await noHorizontalScroll(page), "no sideways page scroll").toBe(true)

  await page.setViewportSize({ width: 375, height: 812 })
  await page.goto(versionPath(published, "#pricing"))
  await expect(priceMatrix(page)).toBeVisible()
  await expect(priceMatrix(page)).toHaveAttribute("aria-readonly", "true")
  await page.waitForLoadState("networkidle")
  expect(await noHorizontalScroll(page), "no sideways page scroll at 375 px").toBe(true)
  await expect(page.getByRole("button", { name: /^Pricing basis:/ })).toHaveCount(0)
  await expect(page.getByRole("button", { name: "Add room", exact: true })).toHaveCount(0)
  await expect(priceMatrix(page).getByRole("textbox")).toHaveCount(0)

  expect(calls.count("validate_version"), "a published version is never re-checked").toBe(0)
  expect(calls.count("price_matrix")).toBeGreaterThan(0)
  expect(denied).toEqual([])
  noErrors()
})

test("an agent without cost access sees the catalogue: no amounts, no page error, no cost call, no 403", async ({ page }) => {
  test.setTimeout(120_000)
  const noErrors = trackErrors(page)
  await login(page, "agent@demo.tex")
  const calls = watchContracts(page)
  const denied = forbidden(page)
  await page.goto(versionPath(published))
  await expect(page.getByText("Amounts are not shown to your role.").first()).toBeVisible()
  for (const room of [N.STD, N.SUP, N.DLX]) await expect(page.getByText(room, { exact: true }).first()).toBeVisible()
  await page.waitForLoadState("networkidle")
  // no amount anywhere in the page's main area (prices would read 70.00, 80.50, …)
  const text = await page.getByRole("main").innerText()
  expect(text).not.toMatch(/\b\d+[.,]\d{2}\b/)
  await expect(priceMatrix(page).getByRole("gridcell", { name: /resolved price/ })).toHaveCount(0)
  await expect(page.getByRole("button", { name: "Price test", exact: true })).toHaveCount(0)
  await expect(page.getByRole("button", { name: /^Pricing basis:/ })).toHaveCount(0)
  expect(await noHorizontalScroll(page)).toBe(true)
  for (const m of ["price_matrix", "validate_version", "preview_price"]) expect(calls.count(m), `${m} is not called`).toBe(0)
  expect(denied).toEqual([])
  noErrors()
})
