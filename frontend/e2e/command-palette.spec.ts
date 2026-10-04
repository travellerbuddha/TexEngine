// §6L "Not done" (batch 2O): the command palette (TexShell, not a design-system overlay) stayed mounted while closed and
// reset its query in a passive effect after opening, so its first commit showed the last query (what is typed then
// is lost), as the 2Z payment drawer did (payments-setup.spec). Read the commit the opening key makes, before any
// later pass: the query must be empty.
//   TEX_E2E_BASE=http://test.localhost:8000 TEX_E2E_PASSWORD=… npx playwright test -c e2e command-palette
import { expect, test } from "@playwright/test"
import { login, texPath, trackErrors } from "./helpers"

test.use({ locale: "en-US" })

test("the command palette opens with an empty query in its first frame (2O)", async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== "desktop", "one layout is enough: the palette is the same")
  const noErrors = trackErrors(page)
  await page.addInitScript(() => {
    try {
      localStorage.setItem("tex-lang", "en")
    } catch {
      /* storage blocked: the default language is English */
    }
  })
  await login(page, "revenue@demo.tex")
  await page.goto(texPath("/tex"))
  await expect(page.getByRole("navigation", { name: "Main navigation" })).toBeVisible()      // the shell listens
  const palette = page.getByRole("combobox", { name: "Command palette" })

  // a query typed, the palette closed: the query is the last session's
  await page.keyboard.press("Control+k")
  await palette.fill("zzz-last-query")
  await page.keyboard.press("Escape")
  await expect(palette).toBeHidden()

  const firstFrame = await page.evaluate(async () => {
    window.dispatchEvent(new KeyboardEvent("keydown", { key: "k", ctrlKey: true, bubbles: true }))
    await Promise.resolve() // React commits the key's update in a microtask
    return document.querySelector<HTMLInputElement>('input[role="combobox"][aria-controls="tex-cmd-list"]')?.value ?? null
  })
  expect(firstFrame).toBe("")
  await expect(palette).toHaveValue("")
  await expect(palette).toBeFocused()
  await page.keyboard.press("Escape")
  noErrors()
})
