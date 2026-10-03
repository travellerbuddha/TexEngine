// 2Z: a payment account's drawer starts from the account it opens in its first frame. It stayed mounted while
// closed and reset its form in a passive effect after opening, so "Add account" showed the last account's label
// for a frame and dropped what was typed at once (the channels.spec race, HANDOFF_RELEASE §5).
//   TEX_E2E_BASE=http://test.localhost:8000 TEX_E2E_PASSWORD=… npx playwright test -c e2e payments-setup
import { expect, test, type Page } from "@playwright/test"
import { login, texPath, trackErrors } from "./helpers"

/** settings.admin at the beach hotel (the demo's General Manager) */
const HOTEL_ADMIN = "beach.gm@demo.tex"

async function english(page: Page) {
  await page.addInitScript(() => {
    try {
      localStorage.setItem("tex-lang", "en")
    } catch {
      /* storage blocked: the default language is English */
    }
  })
}

test("a new payment account starts blank in its first frame, after an account was edited (2Z)", async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== "desktop", "one layout is enough: the drawer is the same")
  const noErrors = trackErrors(page)
  await english(page)
  await login(page, HOTEL_ADMIN)
  await page.goto(texPath("/tex/payments/setup"))
  await expect(page.getByRole("heading", { level: 1, name: "Payment setup" })).toBeVisible()

  // open an existing account and close it again: its label was the drawer's form
  const edit = page.getByRole("button", { name: /^Edit / }).first()
  await edit.click()
  const drawer = page.getByRole("dialog", { name: /^Edit / })
  await expect(drawer.locator("input[data-autofocus]")).not.toHaveValue("")
  await drawer.getByRole("button", { name: "Close" }).click()
  await expect(drawer).toBeHidden()

  await expect(page.getByRole("button", { name: "Add account" })).toBeEnabled()
  const firstFrame = await page.evaluate(async () => {
    const add = [...document.querySelectorAll<HTMLButtonElement>("button")].find((b) => b.textContent?.trim() === "Add account")
    add?.click()
    await Promise.resolve() // React commits the click's update in a microtask
    return document.querySelector<HTMLInputElement>('[role="dialog"] input[data-autofocus]')?.value ?? null
  })
  expect(firstFrame).toBe("")
  const fresh = page.getByRole("dialog", { name: "New payment account" })
  await expect(fresh).toBeVisible()
  await fresh.getByRole("button", { name: "Close" }).click()
  noErrors()
})
