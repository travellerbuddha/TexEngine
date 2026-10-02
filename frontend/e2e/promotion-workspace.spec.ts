// Task 3 of the UX revision (2026-10): a discount for one market and stay dates, made, explained,
// checked with the pricing engine before it is activated, then a similar one for another market.
// - the summary states what the promotion gives, when it is booked and stayed and where it applies
//   (and warns while it would apply to every market, channel and room);
// - "Check the price" prices one stay without and with the draft (policies.promotion_check);
// - "Create similar" starts a new draft from its terms (never a revision that replaces it);
// - the list says what each promotion gives and covers, and where it stands.
// The promotions stay drafts and are deleted after: nothing is sold at them.
//   TEX_E2E_BASE=http://localhost:5173 TEX_E2E_PASSWORD=… npx playwright test -c e2e promotion-workspace
import { expect, test, type Locator, type Page } from "@playwright/test"
import { login, pageApi, pageApiOk, texPath, trackErrors, uniqueRunId } from "./helpers"
import { Budget } from "./flows/budget"
import { archiveAll, HOTEL, newDraft, ownerDraft, publish, Y } from "./flows/workspace"

test.use({ locale: "en-US", actionTimeout: 15_000 })

const made: string[] = []
const promos: string[] = []
test.afterAll(async ({ browser }) => {
  const page = await browser.newPage()
  await login(page, "revenue@demo.tex")
  for (const name of promos) await page.request.post("/api/method/kamra.tex.api.policies.delete_record", { data: { doctype: "TEX Promotion", name } }).catch(() => undefined)
  await page.close()
  await archiveAll(browser, made, "E2E promotion workspace clean-up")
})

/** Choose `options` in a multi-select (a button that opens a list with Apply). */
async function pick(page: Page, field: string, options: RegExp[], clear: RegExp[] = []) {
  await page.getByRole("button", { name: new RegExp(`^${field}: `) }).click()
  const dlg = page.getByRole("dialog", { name: field })
  for (const o of clear) await dlg.getByRole("checkbox", { name: o }).uncheck()
  for (const o of options) await dlg.getByRole("checkbox", { name: o }).check()
  await dlg.getByRole("button", { name: "Apply" }).click()
}

const field = (page: Page, label: string | RegExp): Locator => page.getByLabel(label)

test("a 15 % discount for Germany, July stays booked until 31 May: made, explained, checked by the engine, then copied for the UK", async ({ page }, testInfo) => {
  test.setTimeout(150_000)
  const noErrors = trackErrors(page)
  const budget = await Budget.attach(page)
  await login(page, "revenue@demo.tex")
  await page.goto(texPath("/tex"))
  const d = await newDraft(page, "UXP", ownerDraft())
  made.push(d.contract)
  await publish(page, d.version)
  const code = (await pageApiOk<{ contract: { contract_code: string } }>(page, "kamra.tex.api.contracts.get_contract", { name: d.contract })).contract.contract_code
  const hotel = page.getByRole("banner").getByRole("combobox", { name: "Hotel" })
  await page.goto(texPath("/tex/rates/policies/promotions"))
  if (await hotel.count()) await hotel.selectOption(HOTEL)
  const run = uniqueRunId()

  budget.start()
  await page.getByRole("button", { name: "New promotion" }).click()
  await budget.fill(field(page, /^Promotion\s*\*?$/), `Summer DE ${run}`)
  await budget.fill(field(page, /^Value/), "15")
  await budget.fill(field(page, "Booked until (booking date)"), `${Y}-05-31`)
  await budget.fill(field(page, "Stay from (night)"), `${Y}-07-01`)
  await budget.fill(field(page, "Stay until (night)"), `${Y}-07-31`)
  // while nothing is chosen, it would apply everywhere: said before it is saved
  await expect(page.getByText(/This promotion applies to every market, every channel and every room type/)).toBeVisible()
  await pick(page, "Markets", [/^DE · Germany$/])
  await pick(page, "Sales channels", [/^Direct web \(booking engine\)$/])
  await pick(page, "Room types", [/^Standard Sea View$/, /^Garden Villa$/])
  await expect(page.getByText("15 % off · applied automatically")).toBeVisible()
  await expect(page.getByText(/applies to every market, every channel/)).toHaveCount(0)
  await page.getByRole("button", { name: "Create draft" }).click()
  await page.waitForURL(/\/policies\/promotions\/PRM-/)
  const first = decodeURIComponent(new URL(page.url()).pathname.split("/").pop() ?? "")
  promos.push(first)
  await budget.stop()
  const created = await budget.expectWithin(testInfo, { clicks: 20, sectionSwitches: 0, modals: 3 })

  // the engine's answer for a July stay on the test contract, before activation
  await page.getByLabel("Contract", { exact: true }).selectOption({ label: `${code} · DE` })
  await page.getByLabel("Room type", { exact: true }).selectOption({ label: "Standard Sea View" })
  await page.getByLabel("Arrival", { exact: true }).fill(`${Y}-07-10`)
  const answer = page.waitForResponse((r) => r.url().includes("policies.promotion_check"))
  await page.getByRole("button", { name: "Check the price" }).click()
  const body = (await (await answer).json()) as { message: { outcome: { applied: boolean; discount: string }; with: { total: string }; without: { total: string } } }
  expect(body.message.outcome.applied).toBe(true)
  expect(Number(body.message.with.total)).toBeLessThan(Number(body.message.without.total))
  await expect(page.getByText("Applied by the pricing engine to this stay.")).toBeVisible()
  await expect(page.getByText("Without this promotion")).toBeVisible()
  // it is still a draft: nothing is sold at it
  const rec = await pageApiOk<{ tex_status: string }>(page, "kamra.tex.api.policies.get_record", { doctype: "TEX Promotion", name: first })
  expect(rec.tex_status).toBe("Draft")

  // a similar one for the UK: a new draft from these terms, the market changed
  budget.start()
  await page.getByRole("button", { name: "Create similar" }).click()
  await expect(page.getByText(/^A copy of Summer DE .* — not saved yet$/)).toBeVisible()
  await expect(field(page, /^Promotion\s*\*?$/)).toHaveValue(`Summer DE ${run} (copy)`)
  await budget.fill(field(page, /^Promotion\s*\*?$/), `Summer UK ${run}`)
  await pick(page, "Markets", [/^UK · United Kingdom$/], [/^DE · Germany$/])
  await page.getByRole("button", { name: "Create draft" }).click()
  await page.waitForURL((u) => /\/policies\/promotions\/PRM-/.test(u.pathname) && !u.pathname.endsWith(first))
  const second = decodeURIComponent(new URL(page.url()).pathname.split("/").pop() ?? "")
  promos.push(second)
  await budget.stop()
  const copied = await budget.counts()
  testInfo.annotations.push({ type: "budget: similar promotion", description: `${copied.clicks - created.clicks} clicks, ${copied.modals - created.modals} dialogs` })
  const uk = await pageApiOk<Record<string, unknown>>(page, "kamra.tex.api.policies.get_record", { doctype: "TEX Promotion", name: second })
  expect([uk.markets, uk.channels, uk.room_types, uk.stay_from, uk.stay_to, uk.sale_to, Number(uk.value), uk.tex_status]).toEqual([
    "UK",
    "DIRECT_WEB",
    expect.stringMatching(/STD.*VIL|VIL.*STD/),
    `${Y}-07-01`,
    `${Y}-07-31`,
    `${Y}-05-31`,
    15,
    "Draft",
  ])
  // the first one is untouched (not a revision of it)
  const de = await pageApi<Record<string, unknown>>(page, "kamra.tex.api.policies.get_record", { doctype: "TEX Promotion", name: first })
  expect([de.message.markets, de.message.tex_status]).toEqual(["DE", "Draft"])

  // the list says what each one gives and covers
  await page.goto(texPath("/tex/rates/policies/promotions"))
  const row = page.locator("main table tbody tr").filter({ hasText: `Summer UK ${run}` })
  await expect(row).toContainText("15 % off")
  await expect(row).toContainText("UK")
  await expect(row).toContainText("Draft")
  noErrors()
})
