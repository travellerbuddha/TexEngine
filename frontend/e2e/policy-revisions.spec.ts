import { expect, test } from "@playwright/test"
import { login, pageApi, texPath, trackErrors, uniqueRunId } from "./helpers"

// G-20: extras and taxes are effective-dated revisions, edited through the policy
// screens. The extra is unique per run and archived at the end; the tax policy stays a
// draft and is deleted, so no live demo price changes. Taxes are Finance's (tax.edit).

const HOTEL = "Aurora Beach Resort"

test.use({ locale: "en-US" })

test("an extra's new price is a revision; finance drafts a tax policy, then deletes it", async ({ page }) => {
  test.setTimeout(180_000)
  const noErrors = trackErrors(page)
  const run = uniqueRunId()
  const code = `E2E${run}`.slice(0, 20)
  await login(page, "revenue@demo.tex")
  await page.goto(texPath("/tex/rates/policies/extras"))

  // a live extra, created through the API (the editor itself is covered below)
  const created = await pageApi<{ name: string }>(page, "kamra.tex.api.policies.save_record", {
    doctype: "TEX Extra",
    data: { property: HOTEL, extra_code: code, extra_name: `Revision check ${run}`, category: "Service", pricing_mode: "UNIT", currency: "EUR", amount: "10", bookable_online: 0 },
  })
  expect(created.ok, JSON.stringify(created.body).slice(0, 300)).toBeTruthy()
  const first = created.message.name
  expect((await pageApi(page, "kamra.tex.api.policies.activate", { doctype: "TEX Extra", name: first })).ok).toBeTruthy()

  await test.step("a live extra is read-only; Revise opens a draft of the next revision", async () => {
    await page.goto(texPath(`/tex/rates/policies/extras/${encodeURIComponent(first)}`))
    await expect(page.getByText("Live", { exact: true }).first()).toBeVisible()
    await expect(page.getByLabel("Price (adult / unit)")).toBeDisabled()
    await page.getByRole("button", { name: "Revise" }).click()
    await expect(page).not.toHaveURL(new RegExp(`${first}$`))
    await expect(page.getByText("Draft", { exact: true }).first()).toBeVisible()
  })

  await test.step("the draft takes the new price and goes live", async () => {
    const price = page.getByLabel("Price (adult / unit)")
    await price.fill("12.50")
    await page.getByRole("button", { name: "Save", exact: true }).click()
    await expect(page.getByRole("button", { name: "Activate" })).toBeEnabled()
    await page.getByRole("button", { name: "Activate" }).click()
    const dialog = page.getByRole("dialog", { name: "Activate this revision?" })
    await dialog.getByRole("button", { name: "Activate" }).click()
    await expect(dialog).toBeHidden()
    await expect(page.getByText("Live", { exact: true }).first()).toBeVisible()
  })

  await test.step("selling uses the new revision; the first one is superseded", async () => {
    const extras = await pageApi<{ extra_code: string; amount: string }[]>(page, "kamra.tex.api.crs.extras_for", { property: HOTEL })
    const ours = extras.message.filter((e) => e.extra_code === code)
    expect(ours.map((e) => Number(e.amount))).toEqual([12.5])
    const firstNow = await pageApi<{ tex_status: string }>(page, "kamra.tex.api.policies.get_record", { doctype: "TEX Extra", name: first })
    expect(firstNow.message.tex_status).toBe("Superseded")
  })

  // leave nothing on sale
  const live = await pageApi<{ name: string; tex_status: string }[]>(page, "kamra.tex.api.policies.list_records", { doctype: "TEX Extra", property: HOTEL })
  for (const r of live.message.filter((x) => x.tex_status === "Active" && (x as unknown as { extra_code: string }).extra_code === code))
    await pageApi(page, "kamra.tex.api.policies.archive", { doctype: "TEX Extra", name: r.name, reason: "e2e clean-up" })

  await test.step("taxes belong to finance: a revenue manager cannot write a tax policy", async () => {
    const denied = await pageApi(page, "kamra.tex.api.policies.save_record", {
      doctype: "TEX Tax Policy",
      data: { policy_name: `E2E denied ${run}`, property: HOTEL, rules: [{ code: "VAT", kind: "PERCENT", rate: "10" }] },
    })
    expect(denied.status).toBe(403)
  })

  await test.step("finance drafts a tax policy with its rules, then deletes the draft", async () => {
    await login(page, "finance@demo.tex")
    await page.goto(texPath("/tex/rates/policies/taxes"))
    await page.getByRole("button", { name: "New tax policy" }).first().click()
    await page.getByLabel("Policy name").fill(`E2E taxes ${run}`)
    await page.getByRole("main").getByLabel("Hotel").selectOption({ label: HOTEL })
    await page.getByRole("button", { name: "Add row" }).click()
    const row = page.getByRole("row").last()
    await row.getByLabel("Code").fill("VAT")
    await row.getByLabel("Rate %").fill("10")
    await page.getByRole("button", { name: "Create draft" }).click()
    await expect(page.getByText("Draft", { exact: true }).first()).toBeVisible()
    await expect(page.getByLabel("Currency of fixed amounts")).toHaveValue("EUR")   // the hotel's currency
    await page.getByRole("button", { name: "Delete draft" }).click()
    await page.getByRole("dialog").getByRole("button", { name: /Delete/ }).click()
    await expect(page).toHaveURL(/\/tex\/rates\/policies\/taxes$/)
  })

  noErrors()
})
