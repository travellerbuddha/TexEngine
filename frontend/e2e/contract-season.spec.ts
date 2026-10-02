// Contract work of a busy commercial team (UX revision 2026-10):
// - task 4: a new season contract from the one on sale — duplicate with "a new season", the windows
//   proposed a year on, the new draft opened with every period a year on as an unsaved edit listed
//   for checking, saved in one step; prices and rules copied as they were;
// - task 2: a season's prices copied from any other season (not only the one to its left), then
//   edited, as undoable unsaved edits;
// - task 5: "3rd adult 30 % off" typed the Turkish way (-%30) reads as a sentence; the Price test
//   keeps its party when it is opened again after a rule change.
// Each test makes its own contract through the API (archived after).
//   TEX_E2E_BASE=http://localhost:5173 TEX_E2E_PASSWORD=… npx playwright test -c e2e contract-season
import { expect, test, type Page } from "@playwright/test"
import { login, pageApiOk, texPath, trackErrors } from "./helpers"
import { Budget } from "./flows/budget"
import { priceMatrix } from "./flows/contracts"
import { archiveAll, N, newDraft, ownerDraft, publish, readVersion, versionPath, Y } from "./flows/workspace"

test.use({ locale: "en-US", actionTimeout: 15_000 })

const made: string[] = []
test.afterAll(async ({ browser }) => archiveAll(browser, made, "E2E contract season clean-up"))

const cellOf = (page: Page, room: string, period: string) => priceMatrix(page).getByRole("gridcell", { name: new RegExp(`^${room} · ${period}: (?!resolved)`) }).first()

test("task 4: a new season contract from the one on sale, its dates a year on, checked and saved", async ({ page }, testInfo) => {
  test.setTimeout(120_000)
  const noErrors = trackErrors(page)
  const budget = await Budget.attach(page)
  await login(page, "revenue@demo.tex")
  await page.goto(texPath("/tex"))
  const src = await newDraft(page, `UXS${Y}`, ownerDraft())
  made.push(src.contract)
  await publish(page, src.version)
  const before = await readVersion(page, src.version)
  await page.goto(texPath(`/tex/rates/contracts/${encodeURIComponent(src.contract)}`))
  await expect(page.getByRole("heading", { level: 1 })).toBeVisible()

  budget.start()
  await page.getByRole("button", { name: "Duplicate", exact: true }).click()
  const dlg = page.getByRole("dialog", { name: /^Duplicate / })
  await dlg.getByRole("checkbox", { name: "A new season: move every date a year on" }).check()
  // the windows proposed a year on, and the code and name name the next year
  await expect(dlg.getByLabel("Stay from")).toHaveValue(`${Y + 1}-04-01`)
  await expect(dlg.getByLabel("Stay to")).toHaveValue(`${Y + 1}-07-31`)
  await expect(dlg.getByLabel(/^Contract code/)).toHaveValue(new RegExp(`^UXS${Y + 1}-`))
  await dlg.getByRole("button", { name: "Create the new season" }).click()
  await page.waitForURL(/\/versions\/[^/?#]+/)
  const notice = page.getByRole("status").filter({ hasText: "New season: the dates moved a year on — check them, then save" })
  await expect(notice).toBeVisible()
  await expect(notice).toContainText("4 periods moved 1 year later:")
  await expect(notice).toContainText(`P1 Apr: 01/04/${Y} – 30/04/${Y} → 01/04/${Y + 1} – 30/04/${Y + 1}`)
  await expect(page.getByText("Unsaved changes", { exact: true })).toBeVisible()
  await page.getByRole("button", { name: /^Save/ }).click()
  await expect(page.getByText("Saved to the draft · not on sale until published")).toBeVisible()
  await budget.stop()
  // Duplicate, the season box, Create, Save: four clicks, one dialog (the duplicate's)
  await budget.expectWithin(testInfo, { clicks: 4, sectionSwitches: 0, modals: 1 })

  const contract = new URL(page.url()).pathname.split("/contracts/")[1].split("/")[0]
  made.push(decodeURIComponent(contract))
  const version = decodeURIComponent(new URL(page.url()).pathname.split("/versions/")[1])
  const after = await readVersion(page, version)
  expect(after.periods.map((p) => [p.period_code, p.start_date, p.end_date])).toEqual(
    before.periods.map((p) => [p.period_code, String(p.start_date).replace(String(Y), String(Y + 1)), String(p.end_date).replace(String(Y), String(Y + 1))]),
  )
  // prices and rules copied as they were
  const rules = (rows: Record<string, unknown>[]) => rows.map((r) => `${r.room_type}|${r.period_code || "all"}|${r.op}|${Number(r.value)}`).sort()
  expect(rules(after.period_rates)).toEqual(rules(before.period_rates))
  expect(after.occupancy_rules.length).toBe(before.occupancy_rules.length)
  const header = await pageApiOk<{ contract: { stay_from: string; stay_to: string } }>(page, "kamra.tex.api.contracts.get_contract", { name: decodeURIComponent(contract) })
  expect([header.contract.stay_from, header.contract.stay_to]).toEqual([`${Y + 1}-04-01`, `${Y + 1}-07-31`])
  noErrors()
})

test("task 2: copy a season's prices from any season, then edit them; Ctrl+Z undoes the copy", async ({ page }) => {
  test.setTimeout(120_000)
  const noErrors = trackErrors(page)
  await login(page, "revenue@demo.tex")
  await page.goto(texPath("/tex"))
  const d = await newDraft(page, "UXC", ownerDraft())
  made.push(d.contract)
  await page.goto(versionPath(d, "#pricing"))
  await expect(priceMatrix(page)).toBeVisible()
  await expect(cellOf(page, N.STD, "P4")).toHaveAccessibleName(/130/)

  // P4 (Jul, 130) takes P2's prices (May, 80): not its left neighbour
  await page.getByRole("button", { name: "Period actions: P4" }).click()
  await page.getByRole("menuitem", { name: "Copy prices from another period…" }).click()
  const pop = page.getByRole("dialog", { name: "P4: copy prices from" })
  await pop.getByLabel("Copy from").selectOption("P2")
  await expect(pop).toContainText("are replaced by copies of P2's")
  await pop.getByRole("button", { name: "Copy", exact: true }).click()
  await expect(cellOf(page, N.STD, "P4")).toHaveAccessibleName(/80/)
  // then edited: 85 for Standard in July
  await cellOf(page, N.STD, "P4").click()
  await page.keyboard.type("85")
  await page.keyboard.press("Enter")
  await expect(cellOf(page, N.STD, "P4")).toHaveAccessibleName(/85/)
  // undo twice: the edit, then the copy
  await page.keyboard.press("Control+z")
  await page.keyboard.press("Control+z")
  await expect(cellOf(page, N.STD, "P4")).toHaveAccessibleName(/130/)
  await page.keyboard.press("Control+y")
  await page.keyboard.press("Control+y")
  await expect(cellOf(page, N.STD, "P4")).toHaveAccessibleName(/85/)
  await page.getByRole("button", { name: /^Save/ }).click()
  await expect(page.getByText("Saved to the draft · not on sale until published")).toBeVisible()
  const saved = await readVersion(page, d.version)
  const p4 = saved.period_rates.filter((r) => r.period_code === "P4")
  expect(p4.map((r) => `${r.room_type}|${r.op}|${Number(r.value)}`)).toContain(`Aurora Beach Resort-STD|ABSOLUTE|85`)
  noErrors()
})

test("task 5: '3rd adult 30 % off' typed as -%30 reads as a sentence; the Price test keeps its party", async ({ page }) => {
  test.setTimeout(120_000)
  const noErrors = trackErrors(page)
  await login(page, "revenue@demo.tex")
  await page.goto(texPath("/tex"))
  const d = await newDraft(page, "UXK", ownerDraft())
  made.push(d.contract)
  await page.goto(versionPath(d, "#pricing"))
  const ladder = page.getByRole("grid", { name: "Occupancy and child pricing by period" })
  const section = page.getByRole("button", { name: "Occupancy & child pricing" })
  if ((await section.getAttribute("aria-expanded")) !== "true") await section.click()
  await expect(ladder).toBeVisible()
  const third = ladder.getByRole("gridcell", { name: /^3rd adult · All periods: / })
  await third.click()
  await page.keyboard.type("-%30")
  await expect(page.getByRole("status").filter({ hasText: "3rd adult · All periods pays the base person price less 30 %" })).toBeVisible()
  await page.keyboard.press("Enter")

  // the Price test: 3 adults and a child of 5, calculated, closed, opened again
  await page.getByRole("button", { name: "Price test", exact: true }).click()
  let dr = page.getByRole("dialog", { name: "Price test" })
  await dr.getByLabel(/^Adults/).fill("3")
  await dr.getByRole("button", { name: "Add child", exact: true }).click()
  await dr.getByLabel("Age of child 1", { exact: true }).fill("5")
  await dr.getByRole("button", { name: /^Calculate/ }).click()
  await expect(dr.getByRole("table", { name: "Whole stay" })).toBeVisible()
  await dr.getByRole("button", { name: "Close" }).first().click()
  await expect(dr).toBeHidden()
  await page.getByRole("button", { name: "Price test", exact: true }).click()
  dr = page.getByRole("dialog", { name: "Price test" })
  await expect(dr.getByLabel(/^Adults/)).toHaveValue("3")
  await expect(dr.getByLabel("Age of child 1", { exact: true })).toHaveValue("5")
  noErrors()
})
