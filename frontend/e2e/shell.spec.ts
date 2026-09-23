import { expect, test } from "@playwright/test"
import { login, trackErrors } from "./helpers"

test("TEX shell: spec navigation, PMS hidden, hotel scope, language switch", async ({ page }) => {
  const noErrors = trackErrors(page)
  await login(page, "revenue@demo.tex")
  await page.goto("/kamra/")
  await expect(page).toHaveURL(/\/kamra\/tex$/)
  const nav = page.getByRole("navigation", { name: "Main navigation" })
  for (const item of ["Dashboard", "CRS", "Reservations", "Rates & Contracts", "Inventory", "Booking Engine", "CRM", "Reports"])
    await expect(nav.getByRole("link", { name: item, exact: true })).toBeVisible()
  // PMS-only modules never appear in TEX navigation
  for (const pms of ["Housekeeping", "Laundry", "POS", "Night audit", "Maintenance"])
    await expect(nav.getByText(pms, { exact: false })).toHaveCount(0)
  // only the group's hotels are selectable
  const hotels = await page.getByLabel("Hotel").locator("option").allTextContents()
  expect(hotels.join("|")).toContain("Aurora Beach Resort")
  expect(hotels.every((h) => h.startsWith("Aurora"))).toBeTruthy()
  // language switch re-renders the shell
  await page.locator("#tex-lang-header").selectOption("tr")
  const navTr = page.getByRole("navigation", { name: "Ana menü" })
  await expect(navTr.getByRole("link", { name: "Rezervasyonlar" })).toBeVisible()
  await page.locator("#tex-lang-header").selectOption("en")
  // command palette
  await page.keyboard.press("Control+k")
  await page.getByRole("combobox", { name: "Command palette" }).fill("reserv")
  await page.keyboard.press("Enter")
  await expect(page).toHaveURL(/\/tex\/reservations/)
  // PMS screens are not reachable by URL either while the PMS is switched off (G-16)
  for (const legacy of ["/kamra/today", "/kamra/pos", "/kamra/housekeeping", "/kamra/cashier"]) {
    await page.goto(legacy)
    await expect(page).toHaveURL(/\/kamra\/tex/)
  }
  noErrors()
})
