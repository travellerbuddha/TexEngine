// G-53: publishing a draft from the contract page runs the Pricing Workspace's publish check
// (`workspace: 1`, ADR-061), as the version editor does: a twin board row (two UAI rows for one
// scope, BOARD_DUPLICATE) is an error and the publish is refused. The server's default for other
// callers is unchanged (test_existing_semantics).
import { expect, test } from "@playwright/test"
import { login, texPath } from "./helpers"
import { archiveAll, newDraft, ownerDraft } from "./flows/workspace"

test.use({ locale: "en-US", actionTimeout: 15_000, navigationTimeout: 30_000 })

const made: string[] = []

test.afterAll(async ({ browser }) => archiveAll(browser, made, "G-53 e2e clean-up"))

test("publishing from the contract page sends workspace: 1 and refuses a twin board row", async ({ page }) => {
  await login(page, "revenue@demo.tex")
  const data = ownerDraft()
  const uai = { board: "UAI", is_base: 0, op: "ADD", adult_amount: "20", child_percent: "50", infant_free: 1, room_type: "", period_code: "" }
  data.boards = [...data.boards, uai, { ...uai, adult_amount: "25" }]
  const d = await newDraft(page, "E2E-G53", data)
  made.push(d.contract)
  const checks: string[] = []
  page.on("request", (r) => {
    if (r.url().includes("kamra.tex.api.contracts.validate_version")) checks.push(r.method() === "POST" ? (r.postData() ?? "") : r.url())
  })

  await page.goto(texPath(`/tex/rates/contracts/${encodeURIComponent(d.contract)}`))
  await page.getByRole("button", { name: "Publish V1", exact: true }).click()
  const dialog = page.getByRole("dialog", { name: /^Publish V1 of / })
  await expect(dialog.getByRole("alert")).toContainText("BOARD_DUPLICATE")
  await expect(dialog.getByText("Fix the errors in the draft before publishing.")).toBeVisible()
  await expect(dialog.getByRole("button", { name: "Publish", exact: true })).toBeDisabled()
  expect(checks.length).toBeGreaterThan(0)
  expect(checks.every((c) => /workspace(=|":)1/.test(c)), checks.join("\n")).toBeTruthy()
})
