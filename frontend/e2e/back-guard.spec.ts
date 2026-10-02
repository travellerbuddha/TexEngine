// The browser's Back button with unsaved edits (UX revision 2026-10): the app asks before a history
// step takes the user off a page whose edits are not saved; staying keeps the page, its URL and its
// edits; leaving goes back as usual. Without edits, Back is never asked.
//   TEX_E2E_BASE=http://localhost:5173 TEX_E2E_PASSWORD=… npx playwright test -c e2e back-guard
import { expect, test } from "@playwright/test"
import { login, texPath, trackErrors } from "./helpers"
import { priceMatrix } from "./flows/contracts"
import { archiveAll, N, newDraft, ownerDraft } from "./flows/workspace"

test.use({ locale: "en-US" })

const made: string[] = []
test.afterAll(async ({ browser }) => archiveAll(browser, made, "E2E back guard clean-up"))

test("Back with an unsaved price asks; staying keeps the edit, leaving goes back", async ({ page }) => {
  test.setTimeout(120_000)
  const noErrors = trackErrors(page)
  await login(page, "revenue@demo.tex")
  await page.goto(texPath("/tex"))
  const d = await newDraft(page, "UXB", ownerDraft())
  made.push(d.contract)
  const detail = texPath(`/tex/rates/contracts/${encodeURIComponent(d.contract)}`)
  await page.goto(detail)

  // into the draft through the app (a history entry of its own), Back without edits is not asked
  await page.getByRole("button", { name: /^Open draft V1/ }).click()
  await page.waitForURL(/\/versions\//)
  await expect(priceMatrix(page)).toBeVisible()
  let asked = 0
  page.on("dialog", () => void asked++)
  await page.goBack()
  await expect(page).toHaveURL(new RegExp(`/contracts/${d.contract}$`))
  expect(asked).toBe(0)
  await page.goForward()
  await expect(priceMatrix(page)).toBeVisible()

  // an unsaved price, then Back: asked; the user stays
  const cell = priceMatrix(page).getByRole("gridcell", { name: new RegExp(`^${N.STD} · P2: (?!resolved)`) }).first()
  await cell.click()
  await page.keyboard.type("85")
  await page.keyboard.press("Enter")
  await expect(page.getByText("Unsaved changes", { exact: true })).toBeVisible()
  const editor = page.url()
  page.once("dialog", (dlg) => {
    expect(dlg.message()).toContain("You have changes that are not saved")
    void dlg.dismiss()
  })
  await page.goBack().catch(() => undefined)
  await expect.poll(() => page.url()).toBe(editor)
  await page.waitForTimeout(300) // the step back to the editor is done: still there, still unsaved
  expect(page.url()).toBe(editor)
  await expect(cell).toHaveAccessibleName(/85/)
  await expect(page.getByText("Unsaved changes", { exact: true })).toBeVisible()

  // Back again, and this time leave: the contract page
  page.once("dialog", (dlg) => void dlg.accept())
  await page.goBack().catch(() => undefined)
  await expect(page).toHaveURL(new RegExp(`/contracts/${d.contract}$`))
  await expect(page.getByRole("button", { name: /^Open draft V1/ })).toBeVisible()
  noErrors()
})
