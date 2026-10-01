// O-12 (2D-2, D-4): a Revenue Manager enters a dated manual FX rate for the hotel (it bridges a provider gap such
// as a bank holiday); the FX rates page shows it with the hotel and who entered it, offers no provider fetch and no
// "All hotels" choice. A viewer without the permission is told it is read only.
//   TEX_E2E_BASE=http://test.localhost:8000 TEX_E2E_PASSWORD=… npx playwright test -c e2e fx-manual-rate
import { expect, test, type Page } from "@playwright/test"
import { login, texPath, trackErrors, uniqueRunId } from "./helpers"

const REVENUE = "revenue@demo.tex"
const AGENT = "agent@demo.tex"

async function english(page: Page) {
  await page.addInitScript(() => {
    try {
      localStorage.setItem("tex-lang", "en")
    } catch {
      /* storage blocked: the default language is English */
    }
  })
}

test("a revenue manager enters a manual rate for the hotel and sees who entered it", async ({ page }) => {
  const noErrors = trackErrors(page)
  const reason = `bank holiday ${uniqueRunId()}`
  await english(page)
  await login(page, REVENUE)
  await page.goto(texPath("/tex/rates/fx-rates"))
  await expect(page.getByRole("heading", { level: 1, name: "FX rates" })).toBeVisible()
  // provider rates are fetched by platform administrators only
  await expect(page.getByRole("button", { name: /Fetch TCMB/ })).toHaveCount(0)
  const form = page.locator("form").filter({ hasText: "Rate date" })
  await expect(form).toBeVisible()
  const hotel = form.getByLabel("Hotel")
  await expect(hotel.locator("option", { hasText: "All hotels" })).toHaveCount(0)     // every hotel: platform administrators
  await form.getByLabel("Rate", { exact: false }).first().fill("50.5")
  await form.getByLabel("Reason (optional)").fill(reason)
  await form.getByRole("button", { name: "Add rate" }).click()
  await expect(page.getByRole("status").filter({ hasText: "EUR/TRY rate saved" }).last()).toBeVisible()
  // the page shows the manual rates: this one, with its hotel and who entered it
  const row = page.getByRole("row").filter({ hasText: "EUR/TRY" }).filter({ hasText: "50.5" }).first()
  await expect(row).toBeVisible()
  await expect(row).toContainText(REVENUE)
  noErrors()
})

test("a user without the permission sees the read-only notice and no form", async ({ page }) => {
  await english(page)
  await login(page, AGENT)
  await page.goto(texPath("/tex/rates/fx-rates"))
  await expect(page.getByText(/permission to enter manual FX rates/)).toBeVisible()
  await expect(page.locator("form").filter({ hasText: "Rate date" })).toHaveCount(0)
})
